"""
PyWebView Window Manager & Bridge Layer for Project Nabih (Phase 4 - Step 4.3).
Provides a lightweight, frameless, transparent floating desktop widget.
Bridges State Machine transitions and live subtitles into the Glowing Orb UI.
"""

import sys
import json
import asyncio
from pathlib import Path
from typing import Optional, Callable

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import webview
from loguru import logger
from config import settings
from core.state_machine import AgentState, StateMachine


class AssistantBridgeApi:
    """Exposes Python methods to JavaScript running inside the PyWebView webview."""

    def __init__(
        self,
        on_close: Optional[Callable[[], None]] = None,
        on_orb_click: Optional[Callable[[], None]] = None,
        on_interrupt: Optional[Callable[[], None]] = None,
    ):
        self.on_close = on_close
        self.on_orb_click = on_orb_click
        self.on_interrupt = on_interrupt

    def get_initial_config(self):
        """Returns startup configuration to JavaScript."""
        return {
            "hotkey": settings.HOTKEY,
            "version": "1.0.0",
        }

    def close_app(self):
        """Called by UI close button."""
        logger.info("[UI BRIDGE] Close application requested from UI.")
        if self.on_close:
            self.on_close()

    def interrupt(self):
        """Called when user requests an immediate interruption/cancellation from UI."""
        logger.info("[UI BRIDGE] 🛑 Instant interrupt requested from UI.")
        if self.on_interrupt:
            self.on_interrupt()

    def on_orb_clicked(self):
        """Called when user clicks the Glowing Orb."""
        logger.debug("[UI BRIDGE] Orb clicked in UI.")
        if self.on_orb_click:
            self.on_orb_click()


class AssistantUI:
    """Manages the lifecycle of the floating Glowing Orb desktop widget."""

    def __init__(
        self,
        state_machine: Optional[StateMachine] = None,
        on_close: Optional[Callable[[], None]] = None,
        on_orb_click: Optional[Callable[[], None]] = None,
        on_interrupt: Optional[Callable[[], None]] = None,
    ):
        self.state_machine = state_machine
        self.bridge_api = AssistantBridgeApi(
            on_close=on_close,
            on_orb_click=on_orb_click,
            on_interrupt=on_interrupt,
        )
        self.window: Optional[webview.Window] = None
        self._html_path = (Path(__file__).parent / "index.html").resolve()

        # Connect state machine listener if provided
        if self.state_machine:
            self.state_machine.add_listener(self._on_state_change)

    def create_window(self) -> webview.Window:
        """Constructs the frameless transparent floating window."""
        self.window = webview.create_window(
            title="Nabih AI Assistant",
            url=str(self._html_path),
            width=430,
            height=520,
            resizable=False,
            frameless=True,
            on_top=True,
            transparent=True,
            background_color="#000000",
            js_api=self.bridge_api,
        )
        logger.info("[UI WINDOW] Floating widget window initialized.")
        return self.window

    def _on_state_change(self, old_state: AgentState, new_state: AgentState):
        """Sync listener triggered on any State Machine transition."""
        self.set_state(new_state)

    def set_state(self, state: AgentState, label: Optional[str] = None):
        """Updates the Glowing Orb state and animation in the UI."""
        if not self.window:
            return

        try:
            js_code = f"window.setAssistantState('{state.value}', {json.dumps(label)});"
            self.window.evaluate_js(js_code)
            logger.debug(f"[UI WINDOW] Pushed state '{state.value}' to UI.")
        except Exception as ex:
            logger.debug(f"[UI WINDOW] Could not evaluate JS state (window closing?): {ex}")

    def update_subtitles(self, text: str, is_user: bool = False):
        """Updates synchronized live subtitles in the UI."""
        if not self.window or not text:
            return

        try:
            js_code = f"window.updateSubtitles({json.dumps(text)}, {json.dumps(is_user)});"
            self.window.evaluate_js(js_code)
        except Exception as ex:
            logger.debug(f"[UI WINDOW] Subtitle update error: {ex}")

    def close(self):
        """Destroys the desktop window."""
        if self.window:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None
