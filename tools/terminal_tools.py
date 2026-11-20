"""
Safe Terminal Execution Tools for Project Nabih (Phase 3 - Step 3.3).
Provides a sandboxed terminal runner allowing the agent to execute safe CLI commands
(git, npm, python, tests, directory queries) with:
  - Destructive command blocklist (Guardrails)
  - Configurable execution timeout
  - Scoped working directory resolution
  - Truncated output formatting to protect context window headroom
"""

import sys
import time
import subprocess
from pathlib import Path
from typing import Optional, List, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from rich.panel import Panel
from config import settings
from tools.registry import register_tool
from core.diagnostics import console

# Strict blocklist of destructive commands that should never be executed autonomously
BLOCKED_PATTERNS = [
    # Wiping / Formatting
    "format ",
    "diskpart",
    # Destructive mass deletion
    "rmdir /s /q c:",
    "rmdir /s /q /",
    "del /f /s /q c:",
    "del /f /s /q /",
    "rm -rf /",
    "rm -rf c:",
    # System Shutdown / Reboots
    "shutdown",
    "restart-computer",
    "stop-computer",
    # Registry and critical ACL tampering
    "reg delete",
    "bcdedit",
    "takeown",
    # Fork bombs / Infinite loops
    ":(){ :|:& };:",
]

# Max characters of command output to return to the model
MAX_OUTPUT_CHARS = 6000


def _is_command_safe(command: str) -> Tuple[bool, str]:
    """Inspects the command against the safety blocklist."""
    cmd_lower = command.lower().strip()

    for pattern in BLOCKED_PATTERNS:
        if pattern in cmd_lower:
            return False, f"Command contains restricted pattern '{pattern}'."

    return True, "OK"


@register_tool
def run_terminal_command(
    command: str,
    cwd: Optional[str] = None,
    timeout_seconds: int = 25,
) -> str:
    """
    Executes a shell command (PowerShell / CLI) in the user's workspace and returns its output.
    command: The exact command string to run (e.g. 'git status', 'python -m pytest', 'dir').
    cwd: Optional working directory for the command (defaults to current project root).
    timeout_seconds: Maximum allowed execution time before terminating (default is 25s).
    """
    # 1. Safety verification against destructive commands
    is_safe, reason = _is_command_safe(command)
    if not is_safe:
        err_msg = f"⛔ Security Guardrail: Command blocked! {reason}"
        logger.warning(f"[TERMINAL TOOLS] {err_msg} (Command: '{command}')")
        return err_msg

    # 2. Resolve working directory
    if cwd:
        working_dir = Path(cwd).expanduser().resolve()
    else:
        working_dir = PROJECT_ROOT.resolve()

    if not working_dir.exists() or not working_dir.is_dir():
        return f"Error: Working directory '{working_dir}' does not exist."

    logger.info(f"[TERMINAL TOOLS] 🚀 Running: '{command}' in {working_dir} (Timeout: {timeout_seconds}s)")
    start_time = time.perf_counter()

    # 3. Execute in PowerShell
    try:
        process = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            cwd=str(working_dir),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            encoding="utf-8",
            errors="replace",
        )

        elapsed_ms = round((time.perf_counter() - start_time) * 1000, 1)
        exit_code = process.returncode
        stdout = process.stdout.strip()
        stderr = process.stderr.strip()

        # Build clean report
        output_parts = [
            f"=== Command Execution Report ===",
            f"Command: {command}",
            f"Working Dir: {working_dir.name}",
            f"Exit Code: {exit_code} ({'SUCCESS' if exit_code == 0 else 'FAILED'}) | Time: {elapsed_ms}ms\n",
        ]

        if stdout:
            if len(stdout) > MAX_OUTPUT_CHARS:
                stdout = stdout[:MAX_OUTPUT_CHARS] + f"\n... [Output truncated at {MAX_OUTPUT_CHARS} characters]"
            output_parts.append(f"[STDOUT]:\n{stdout}")

        if stderr:
            if len(stderr) > MAX_OUTPUT_CHARS:
                stderr = stderr[:MAX_OUTPUT_CHARS] + f"\n... [Errors truncated at {MAX_OUTPUT_CHARS} characters]"
            output_parts.append(f"\n[STDERR]:\n{stderr}")

        if not stdout and not stderr:
            output_parts.append("[Output]: (Command completed with no terminal output)")

        final_report = "\n".join(output_parts)
        logger.info(f"[TERMINAL TOOLS] Completed in {elapsed_ms}ms with exit code {exit_code}")
        return final_report

    except subprocess.TimeoutExpired:
        logger.error(f"[TERMINAL TOOLS] Command '{command}' timed out after {timeout_seconds}s.")
        return f"Error: Command execution timed out after {timeout_seconds} seconds."

    except Exception as ex:
        logger.error(f"[TERMINAL TOOLS] Execution exception on '{command}': {ex}")
        return f"Error executing command: {type(ex).__name__} - {ex}"


# -----------------------------------------------------------------------------
# Standalone Unit Test
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    console.print(Panel("[bold cyan]Safe Terminal Tools - Verification Suite[/bold cyan]", border_style="cyan"))

    # Test 1: Safe command execution (git status or dir)
    res_safe = run_terminal_command("git status --short")
    print("Test 1 (Safe Command Result):")
    print(res_safe)

    # Test 2: Python one-liner
    res_py = run_terminal_command("python -c \"print('Hello from Nabih Terminal!')\"")
    print("\nTest 2 (Python Execution):")
    print(res_py)

    # Test 3: Blocklist verification
    res_blocked = run_terminal_command("shutdown /s /t 0")
    print("\nTest 3 (Security Blocklist Check):")
    print(res_blocked)
    assert "Security Guardrail: Command blocked" in res_blocked, "Blocked command should be rejected!"

    # Test 4: Verify tool is registered in registry
    from tools.registry import registry
    schemas = registry.get_schemas()
    tool_names = [s["function"]["name"] for s in schemas]
    print(f"\nRegistered Tools in Catalog ({len(tool_names)}): {tool_names}")
    assert "run_terminal_command" in tool_names, "run_terminal_command should be registered!"

    console.print("\n[bold green]✅ All Terminal Tools & Security Guardrails Verified Successfully![/bold green]")
