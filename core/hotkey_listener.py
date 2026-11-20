"""
Global Push-to-Talk Hotkey Listener for Project Nabih (Phase 4 - Step 4.2).
Monitors system-wide keyboard events across Windows using `pynput`.
Features:
  - Windows keyboard auto-repeat suppression (debouncing)
  - Configurable hotkey (Caps Lock, F8, etc.) from `config.py`
  - Push-to-Talk triggers: Press -> Start Recording, Release -> Stop & Process
  - Full StateMachine integration and background thread daemon lifecycle
"""

import sys
import time
import threading
from pathlib import Path
from typing import Callable, Optional, Union

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from rich.panel import Panel
from pynput import keyboard

from config import settings
from core.state_machine import StateMachine, AgentState
from core.diagnostics import console


class HotkeyListener:
    """
    Global low-level keyboard hook monitoring Push-to-Talk activations
    independently of whichever window is active on Windows.
    """

    def __init__(
        self,
        hotkey_name: str = settings.HOTKEY,
        state_machine: Optional[StateMachine] = None,
        on_press_callback: Optional[Callable[[], None]] = None,
        on_release_callback: Optional[Callable[[], None]] = None,
        on_interrupt_callback: Optional[Callable[[], None]] = None,
    ):
        self.hotkey_name = hotkey_name.lower().strip()
        self.state_machine = state_machine
        self.on_press_callback = on_press_callback
        self.on_release_callback = on_release_callback
        self.on_interrupt_callback = on_interrupt_callback

        self._target_key = self._resolve_key(self.hotkey_name)
        self._is_pressed = False
        self._listener: Optional[keyboard.Listener] = None
        self._lock = threading.Lock()

    def _resolve_key(self, key_str: str) -> Union[keyboard.Key, keyboard.KeyCode]:
        """Maps configuration string to a pynput Key or KeyCode object."""
        key_mapping = {
            "caps_lock": keyboard.Key.caps_lock,
            "capslock": keyboard.Key.caps_lock,
            "f8": keyboard.Key.f8,
            "f9": keyboard.Key.f9,
            "f10": keyboard.Key.f10,
            "f12": keyboard.Key.f12,
            "ctrl_l": keyboard.Key.ctrl_l,
            "ctrl_r": keyboard.Key.ctrl_r,
            "alt_l": keyboard.Key.alt_l,
            "alt_r": keyboard.Key.alt_r,
            "space": keyboard.Key.space,
            "scroll_lock": keyboard.Key.scroll_lock,
        }

        if key_str in key_mapping:
            return key_mapping[key_str]

        # Single alphanumeric character
        if len(key_str) == 1:
            return keyboard.KeyCode.from_char(key_str)

        logger.warning(f"[HOTKEY LISTENER] Unknown key '{key_str}', defaulting to Caps Lock.")
        return keyboard.Key.caps_lock

    def _matches_target(self, key) -> bool:
        """Determines if the intercepted key matches the configured target hotkey."""
        if self._target_key == key:
            return True

        # Check char match if applicable
        if isinstance(self._target_key, keyboard.KeyCode) and hasattr(key, "char") and key.char:
            return key.char.lower() == self._target_key.char.lower()

        return False

    def _on_key_press(self, key):
        """Low-level keyboard hook callback on key down."""
        # Check for global Escape key (Instant Interrupt / Cancel)
        if key == keyboard.Key.esc:
            with self._lock:
                was_holding = self._is_pressed
                self._is_pressed = False

            logger.info("[HOTKEY LISTENER] 🛑 Global ESC intercepted -> Triggering instant cancellation.")
            if self.on_interrupt_callback:
                try:
                    self.on_interrupt_callback()
                except Exception as ex:
                    logger.error(f"[HOTKEY LISTENER] on_interrupt_callback error: {ex}")
            return

        if not self._matches_target(key):
            return

        with self._lock:
            # Suppress Windows OS auto-repeat events when a key is continuously held down!
            if self._is_pressed:
                return

            self._is_pressed = True
            logger.debug(f"[HOTKEY LISTENER] 🔴 Push-to-Talk key PRESSED ({self.hotkey_name})")

            # Update State Machine
            if self.state_machine:
                # If assistant was speaking, barge-in is triggered cleanly
                self.state_machine.transition_to_sync(
                    AgentState.LISTENING,
                    reason="Push-to-Talk key pressed"
                )

            # Trigger custom callback (e.g. start in-memory audio recording)
            if self.on_press_callback:
                try:
                    self.on_press_callback()
                except Exception as ex:
                    logger.error(f"[HOTKEY LISTENER] on_press_callback error: {ex}")

    def _on_key_release(self, key):
        """Low-level keyboard hook callback on key up."""
        if not self._matches_target(key):
            return

        with self._lock:
            if not self._is_pressed:
                return

            self._is_pressed = False
            logger.debug(f"[HOTKEY LISTENER] ⚪ Push-to-Talk key RELEASED ({self.hotkey_name})")

            # Update State Machine to THINKING
            if self.state_machine:
                self.state_machine.transition_to_sync(
                    AgentState.THINKING,
                    reason="Push-to-Talk key released"
                )

            # Trigger custom callback (e.g. stop audio recording & process turn)
            if self.on_release_callback:
                try:
                    self.on_release_callback()
                except Exception as ex:
                    logger.error(f"[HOTKEY LISTENER] on_release_callback error: {ex}")

    def start(self):
        """Starts the global keyboard listener in a dedicated background daemon thread."""
        if self._listener is not None and self._listener.is_alive():
            logger.debug("[HOTKEY LISTENER] Listener is already running.")
            return

        self._listener = keyboard.Listener(
            on_press=self._on_key_press,
            on_release=self._on_key_release,
        )
        self._listener.daemon = True
        self._listener.start()
        logger.info(f"[HOTKEY LISTENER] ⌨️ Global listener active (Monitoring hotkey: '{self.hotkey_name}')")

    def stop(self):
        """Halts the global keyboard listener."""
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
            logger.debug("[HOTKEY LISTENER] Global listener stopped.")


# -----------------------------------------------------------------------------
# Standalone Unit Test
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    console.print(Panel("[bold cyan]Global Hotkey Listener - Unit Verification[/bold cyan]", border_style="cyan"))

    sm = StateMachine()
    press_count = 0
    release_count = 0

    def on_press():
        global press_count
        press_count += 1
        print("  [HOTKEY EVENT] 🔴 on_press callback executed!")

    def on_release():
        global release_count
        release_count += 1
        print("  [HOTKEY EVENT] ⚪ on_release callback executed!")

    test_key = "caps_lock"
    listener = HotkeyListener(
        hotkey_name=test_key,
        state_machine=sm,
        on_press_callback=on_press,
        on_release_callback=on_release
    )

    print(f"Testing Hotkey Listener logic (Target: {test_key})...")
    assert sm.is_idle(), "Initial state must be IDLE"

    # 1. Test Press & Debounce
    print("Testing key press and Windows auto-repeat suppression...")
    listener._on_key_press(listener._target_key)
    # Simulate Windows holding-key auto-repeat events
    listener._on_key_press(listener._target_key)
    listener._on_key_press(listener._target_key)

    assert sm.is_listening(), f"State should be LISTENING, got {sm.state_name}"
    assert press_count == 1, f"Debounce failed! Expected 1 press event, got {press_count}"
    print("  ✅ Auto-repeat suppressed successfully! (Single press confirmed)")

    # 2. Test Release
    print("Testing key release...")
    listener._on_key_release(listener._target_key)
    assert sm.is_thinking(), f"State should be THINKING, got {sm.state_name}"
    assert release_count == 1, f"Expected 1 release event, got {release_count}"
    print("  ✅ Key release handled cleanly! (State transitioned to THINKING)")

    # 3. Test background thread startup and shutdown
    listener.start()
    assert listener._listener is not None and listener._listener.is_alive()
    print("  ✅ Background listener thread started successfully!")
    listener.stop()
    assert listener._listener is None
    print("  ✅ Background listener thread stopped cleanly!")

    console.print("[bold green]✅ Global Hotkey Listener Verified Successfully![/bold green]")
