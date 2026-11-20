"""
Tool Registry and Automatic Schema Generator for Project Nabih (Phase 3 - Step 3.1).
Provides the `@register_tool` decorator which inspects Python functions, type annotations,
and docstrings to automatically generate OpenAI-compatible function calling schemas.
Dispatches synchronous and asynchronous tool invocations with robust error handling.
"""

import sys
import json
import inspect
import asyncio
from pathlib import Path
from typing import (
    Dict,
    Any,
    Callable,
    List,
    Optional,
    Union,
    get_type_hints,
    get_origin,
    get_args,
)

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from rich.panel import Panel
from core.diagnostics import console


# Mapping standard Python types to JSON Schema types
TYPE_MAPPING = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _python_type_to_json_schema(py_type: Any) -> Dict[str, Any]:
    """Converts a Python type annotation to an OpenAI-compatible JSON Schema definition."""
    origin = get_origin(py_type)

    # Handle Optional[T] / Union[T, None]
    if origin is Union:
        args = [arg for arg in get_args(py_type) if arg is not type(None)]
        if len(args) == 1:
            return _python_type_to_json_schema(args[0])

    # Handle List[T]
    if origin in (list, List):
        args = get_args(py_type)
        item_schema = _python_type_to_json_schema(args[0]) if args else {"type": "string"}
        return {"type": "array", "items": item_schema}

    # Handle Dict[K, V]
    if origin in (dict, Dict):
        return {"type": "object"}

    # Base types
    schema_type = TYPE_MAPPING.get(py_type, "string")
    return {"type": schema_type}


def _parse_param_docs(docstring: Optional[str]) -> Dict[str, str]:
    """Extracts parameter descriptions from Google or Sphinx style docstrings."""
    if not docstring:
        return {}

    param_docs = {}
    lines = docstring.split("\n")
    for line in lines:
        line = line.strip()
        # Google style: "param_name: description" or "param_name (type): description"
        if ":" in line:
            parts = line.split(":", 1)
            raw_param = parts[0].strip()
            # Strip leading words like "param", "arg", "* "
            param_clean = raw_param.replace("param", "").replace("arg", "").replace("*", "").strip()
            param_name = param_clean.split()[0] if param_clean else ""
            if param_name and param_name.isidentifier():
                param_docs[param_name] = parts[1].strip()

    return param_docs


class ToolRegistry:
    """Central catalog of callable system tools for Claude and local execution."""

    def __init__(self):
        self._tools: Dict[str, Callable] = {}
        self._schemas: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        func: Optional[Callable] = None,
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ):
        """Decorator to register a Python function as a model-callable tool."""

        def decorator(fn: Callable) -> Callable:
            tool_name = name or fn.__name__
            tool_doc = description or inspect.getdoc(fn) or f"Executes {tool_name}"

            # 1. Inspect parameters and types
            sig = inspect.signature(fn)
            type_hints = {}
            try:
                type_hints = get_type_hints(fn)
            except Exception as ex:
                logger.debug(f"[TOOL REGISTRY] Could not resolve all type hints for {tool_name}: {ex}")

            param_docs = _parse_param_docs(inspect.getdoc(fn))
            properties: Dict[str, Any] = {}
            required: List[str] = []

            for param_name, param in sig.parameters.items():
                # Skip *args and **kwargs
                if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                    continue

                py_type = type_hints.get(param_name, str)
                param_schema = _python_type_to_json_schema(py_type)

                # Add description if available
                if param_name in param_docs:
                    param_schema["description"] = param_docs[param_name]

                properties[param_name] = param_schema

                # If no default value, it is required
                if param.default is inspect.Parameter.empty:
                    required.append(param_name)

            # 2. Build OpenAI-compatible tool definition
            schema = {
                "type": "function",
                "function": {
                    "name": tool_name,
                    "description": tool_doc.split("\n\n")[0].strip(),
                    "parameters": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                },
            }

            self._tools[tool_name] = fn
            self._schemas[tool_name] = schema

            logger.debug(f"[TOOL REGISTRY] Registered tool: '{tool_name}' ({len(properties)} parameters)")
            return fn

        if func is None:
            return decorator
        return decorator(func)

    def get_schemas(self) -> List[Dict[str, Any]]:
        """Returns list of all registered tool schemas formatted for Claude/OpenAI."""
        return list(self._schemas.values())

    def get_tool(self, name: str) -> Optional[Callable]:
        """Retrieves a registered tool callable by name."""
        return self._tools.get(name)

    async def execute(self, tool_name: str, arguments: Union[Dict[str, Any], str]) -> str:
        """
        Executes a registered tool by name with arguments.
        Returns serialized string result for feeding back into LLM conversation history.
        """
        if tool_name not in self._tools:
            error_msg = f"Error: Tool '{tool_name}' is not registered. Available tools: {list(self._tools.keys())}"
            logger.error(f"[TOOL REGISTRY] {error_msg}")
            return error_msg

        # Parse string arguments if received as JSON string
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments) if arguments.strip() else {}
            except Exception as ex:
                return f"Error: Failed to parse tool arguments as JSON: {ex}"

        fn = self._tools[tool_name]
        logger.info(f"[TOOL REGISTRY] 🛠️ Executing tool: '{tool_name}' with args: {arguments}")

        try:
            # Handle async and sync callables cleanly
            if inspect.iscoroutinefunction(fn):
                result = await fn(**arguments)
            else:
                result = await asyncio.to_thread(fn, **arguments)

            if isinstance(result, (dict, list)):
                return json.dumps(result, ensure_ascii=False, indent=2)
            return str(result)

        except Exception as ex:
            error_msg = f"Error executing tool '{tool_name}': {type(ex).__name__} - {ex}"
            logger.error(f"[TOOL REGISTRY] {error_msg}")
            return error_msg


# Global singleton registry instance
registry = ToolRegistry()
register_tool = registry.register


# -----------------------------------------------------------------------------
# Standalone Unit Verification
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    console.print(Panel("[bold cyan]Tool Registry & Schema Generator - Unit Test[/bold cyan]", border_style="cyan"))

    @register_tool
    def sample_calculator(a: int, b: int, operation: str = "add") -> int:
        """
        Performs a basic math operation on two integers.
        a: First integer operand
        b: Second integer operand
        operation: The operation name (add, multiply)
        """
        if operation == "multiply":
            return a * b
        return a + b

    schemas = registry.get_schemas()
    print("Generated Schema for Claude/OpenAI:")
    print(json.dumps(schemas, indent=2, ensure_ascii=False))

    async def test_exec():
        res1 = await registry.execute("sample_calculator", {"a": 7, "b": 6, "operation": "multiply"})
        print(f"\nExecution Result (7 * 6): {res1}")
        assert res1 == "42", f"Expected 42, got {res1}"

        res_err = await registry.execute("unknown_tool", {})
        print(f"Unknown Tool Handling: {res_err}")

    asyncio.run(test_exec())
    console.print("[bold green]✅ Tool Registry Unit Test Passed Successfully![/bold green]")
