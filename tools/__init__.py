"""
Tools package for Nabih AI Assistant.
Exports the tool registry and automatically loads all file and terminal tools.
"""

from tools.registry import registry, register_tool
import tools.file_tools
import tools.terminal_tools

__all__ = ["registry", "register_tool"]
