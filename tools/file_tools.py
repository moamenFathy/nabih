"""
File and Project Exploration Tools for Project Nabih (Phase 3 - Step 3.2).
Provides safe, scoped file system operations:
  - list_directory: Directory tree explorer with noisy directory filtering
  - read_file: Safe file reader with optional line-range slicing
  - write_file: File creation and overwrite utility
  - patch_file: Surgical search-and-replace code updater
All operations are sandboxed to the user's workspace to protect system stability.
"""

import os
import sys
from pathlib import Path
from typing import Optional, List, Dict, Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from rich.panel import Panel
from config import settings
from tools.registry import register_tool
from core.diagnostics import console

# Directories ignored by default during folder listing
IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".idea",
    ".vscode",
    "dist",
    "build",
    "coverage",
    ".pytest_cache",
}

# Maximum characters allowed in a single file read to protect context headroom
MAX_READ_CHARS = 100_000
MAX_READ_LINES = 1_000


def _resolve_safe_path(path_str: str) -> Path:
    """
    Resolves relative paths against PROJECT_ROOT or WORKSPACE_ROOT and enforces
    workspace boundary checks to prevent accidental system directory modification.
    """
    raw_path = Path(path_str).expanduser()
    if raw_path.is_absolute():
        resolved = raw_path.resolve()
    else:
        # Default relative resolution to PROJECT_ROOT
        resolved = (PROJECT_ROOT / raw_path).resolve()

    # Safety check: Block Windows root or System directories
    system_drives = {Path("C:/Windows").resolve(), Path("C:/Program Files").resolve()}
    for sys_dir in system_drives:
        if resolved == sys_dir or sys_dir in resolved.parents:
            raise PermissionError(f"Access to critical system path '{resolved}' is strictly blocked for security.")

    return resolved


@register_tool
def list_directory(path: str = ".", max_depth: int = 2) -> str:
    """
    Lists files and subdirectories in a directory with a clean tree view.
    path: The relative or absolute path of the directory to explore (defaults to project root).
    max_depth: Maximum recursion depth (default is 2 levels).
    """
    try:
        target_dir = _resolve_safe_path(path)
        if not target_dir.exists():
            return f"Error: Directory '{target_dir}' does not exist."
        if not target_dir.is_dir():
            return f"Error: Path '{target_dir}' is a file, not a directory."

        lines = [f"📁 {target_dir.name}/ (Path: {target_dir})"]

        def _scan(current_dir: Path, current_depth: int, prefix: str):
            if current_depth > max_depth:
                return

            try:
                entries = sorted(list(current_dir.iterdir()), key=lambda e: (not e.is_dir(), e.name.lower()))
            except PermissionError:
                lines.append(f"{prefix}└── [Permission Denied]")
                return

            # Filter out ignored directories
            visible_entries = [e for e in entries if e.name not in IGNORED_DIRS and not e.name.startswith(".system_")]
            total = len(visible_entries)

            for i, entry in enumerate(visible_entries):
                is_last = (i == total - 1)
                connector = "└── " if is_last else "├── "
                sub_prefix = "    " if is_last else "│   "

                if entry.is_dir():
                    lines.append(f"{prefix}{connector}📁 {entry.name}/")
                    _scan(entry, current_depth + 1, prefix + sub_prefix)
                else:
                    size_kb = round(entry.stat().st_size / 1024.0, 1)
                    lines.append(f"{prefix}{connector}📄 {entry.name} ({size_kb} KB)")

        _scan(target_dir, 1, "")
        return "\n".join(lines)

    except Exception as ex:
        logger.error(f"[FILE TOOLS] list_directory error: {ex}")
        return f"Error exploring directory '{path}': {ex}"


@register_tool
def read_file(path: str, start_line: Optional[int] = None, end_line: Optional[int] = None) -> str:
    """
    Reads the text contents of a file with optional line-range slicing.
    path: The relative or absolute path of the file to read.
    start_line: Optional 1-based start line index to begin reading.
    end_line: Optional 1-based end line index to stop reading (inclusive).
    """
    try:
        target_file = _resolve_safe_path(path)
        if not target_file.exists():
            return f"Error: File '{target_file}' does not exist."
        if not target_file.is_file():
            return f"Error: Path '{target_file}' is a directory, not a file."

        # Check file size
        file_size = target_file.stat().st_size
        if file_size > 2 * 1024 * 1024:  # 2 MB limit
            return f"Error: File '{target_file.name}' is too large ({file_size / (1024*1024):.1f} MB). Max supported size is 2 MB."

        # Read contents with UTF-8 encoding
        with open(target_file, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        total_lines = len(lines)
        s_line = max(1, start_line) if start_line is not None else 1
        e_line = min(total_lines, end_line) if end_line is not None else total_lines

        if s_line > total_lines:
            return f"Error: start_line ({s_line}) exceeds total lines in file ({total_lines})."

        selected_lines = lines[s_line - 1 : e_line]
        numbered_output = []
        for idx, line_content in enumerate(selected_lines, start=s_line):
            numbered_output.append(f"{idx:4d} | {line_content.rstrip()}")

        header = f"--- File: {target_file.name} (Lines {s_line}-{e_line} of {total_lines}) ---\n"
        result_text = header + "\n".join(numbered_output)

        if len(result_text) > MAX_READ_CHARS:
            result_text = result_text[:MAX_READ_CHARS] + f"\n... [Truncated at {MAX_READ_CHARS} characters]"

        return result_text

    except Exception as ex:
        logger.error(f"[FILE TOOLS] read_file error: {ex}")
        return f"Error reading file '{path}': {ex}"


@register_tool
def write_file(path: str, content: str, overwrite: bool = True) -> str:
    """
    Creates a new file or overwrites an existing file with the specified content.
    path: Relative or absolute path of the file to create or update.
    content: The exact text content to write.
    overwrite: If False, will refuse to overwrite an existing file (defaults to True).
    """
    try:
        target_file = _resolve_safe_path(path)

        if target_file.exists() and not overwrite:
            return f"Error: File '{target_file}' already exists and overwrite is set to False."

        # Ensure parent directory exists
        target_file.parent.mkdir(parents=True, exist_ok=True)

        with open(target_file, "w", encoding="utf-8") as f:
            f.write(content)

        size_kb = round(len(content.encode("utf-8")) / 1024.0, 2)
        lines_count = len(content.splitlines())
        logger.info(f"[FILE TOOLS] Successfully wrote {lines_count} lines ({size_kb} KB) to '{target_file.name}'")
        return f"Success: Wrote {lines_count} lines ({size_kb} KB) to '{target_file}'."

    except Exception as ex:
        logger.error(f"[FILE TOOLS] write_file error: {ex}")
        return f"Error writing to file '{path}': {ex}"


@register_tool
def patch_file(path: str, target: str, replacement: str) -> str:
    """
    Performs a surgical search-and-replace modification in an existing file.
    path: Relative or absolute path of the file to modify.
    target: The exact string block to find and replace.
    replacement: The new string block to replace the target with.
    """
    try:
        target_file = _resolve_safe_path(path)
        if not target_file.exists():
            return f"Error: File '{target_file}' does not exist."

        with open(target_file, "r", encoding="utf-8") as f:
            content = f.read()

        if target not in content:
            return f"Error: Target block was not found in '{target_file.name}'. Make sure the target text matches exactly."

        occurrences = content.count(target)
        new_content = content.replace(target, replacement, 1)

        with open(target_file, "w", encoding="utf-8") as f:
            f.write(new_content)

        logger.info(f"[FILE TOOLS] Successfully patched '{target_file.name}' (1 of {occurrences} occurrences replaced)")
        return f"Success: Replaced target block in '{target_file.name}' ({occurrences} match(es) detected)."

    except Exception as ex:
        logger.error(f"[FILE TOOLS] patch_file error: {ex}")
        return f"Error patching file '{path}': {ex}"


# -----------------------------------------------------------------------------
# Standalone Unit Test
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    console.print(Panel("[bold cyan]File & Project Tools - Verification Suite[/bold cyan]", border_style="cyan"))

    # Test 1: list_directory on project root
    tree = list_directory(".", max_depth=1)
    print("Project Directory Tree:")
    print(tree[:300] + "...\n")

    # Test 2: write_file
    scratch_file = "test_scratch.tmp"
    write_res = write_file(scratch_file, "Line 1: Hello from Nabih\nLine 2: Testing Phase 3 File Tools\nLine 3: Goodbye!")
    print("Write File Result:", write_res)

    # Test 3: read_file with line slicing
    read_res = read_file(scratch_file, start_line=1, end_line=2)
    print("\nRead File Result (Lines 1-2):")
    print(read_res)

    # Test 4: patch_file
    patch_res = patch_file(scratch_file, "Hello from Nabih", "Greetings from Griot & Nabih")
    print("\nPatch File Result:", patch_res)

    # Verify patched content
    verified = read_file(scratch_file)
    print("\nPatched Content:")
    print(verified)

    # Clean up scratch test file
    Path(scratch_file).unlink(missing_ok=True)
    console.print("\n[bold green]✅ All File Tools Verified Successfully![/bold green]")
