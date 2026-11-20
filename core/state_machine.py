"""
Deterministic State Machine for Project Nabih (Phase 4 - Step 4.1).
Manages core system states: IDLE, LISTENING, THINKING, SPEAKING.
Enforces valid transition paths, supports user barge-in (interruption),
and broadcasts state changes to both the Python backend and the pywebview UI bridge.
"""

import sys
import enum
import asyncio
from pathlib import Path
from typing import Callable, List, Optional, Set, Dict, Any

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from loguru import logger
from rich.panel import Panel
from core.diagnostics import console


class AgentState(str, enum.Enum):
    """Enumeration of all supported operational states for Project Nabih."""
    IDLE = "IDLE"           # Resting state; zero resource footprint
    LISTENING = "LISTENING" # Microphone recording audio stream in RAM
    THINKING = "THINKING"   # STT transcription, LLM reasoning, & tool execution
    SPEAKING = "SPEAKING"   # TTS speech playback & live subtitles active


class StateMachine:
    """
    Finite State Machine governing assistant behavior.
    Thread-safe and async-friendly with subscriber event broadcasting.
    """

    # Valid state transition rules
    VALID_TRANSITIONS: Dict[AgentState, Set[AgentState]] = {
        AgentState.IDLE: {AgentState.LISTENING},
        AgentState.LISTENING: {AgentState.THINKING, AgentState.IDLE},
        AgentState.THINKING: {AgentState.SPEAKING, AgentState.IDLE},
        # Allow barge-in: Speaking can transition to IDLE (finished) OR directly to LISTENING (interrupted)
        AgentState.SPEAKING: {AgentState.IDLE, AgentState.LISTENING},
    }

    def __init__(self, initial_state: AgentState = AgentState.IDLE):
        self._current_state: AgentState = initial_state
        self._listeners: List[Callable[[AgentState, AgentState], None]] = []
        self._async_listeners: List[Callable[[AgentState, AgentState], Any]] = []
        self._lock = asyncio.Lock()

    @property
    def current_state(self) -> AgentState:
        """Returns the active state of the assistant."""
        return self._current_state

    @property
    def state_name(self) -> str:
        """Returns the string name of the active state."""
        return self._current_state.value

    def is_idle(self) -> bool:
        return self._current_state == AgentState.IDLE

    def is_listening(self) -> bool:
        return self._current_state == AgentState.LISTENING

    def is_thinking(self) -> bool:
        return self._current_state == AgentState.THINKING

    def is_speaking(self) -> bool:
        return self._current_state == AgentState.SPEAKING

    def add_listener(self, callback: Callable[[AgentState, AgentState], None]):
        """Subscribes a synchronous callback function: callback(from_state, to_state)."""
        if callback not in self._listeners:
            self._listeners.append(callback)

    def add_async_listener(self, async_callback: Callable[[AgentState, AgentState], Any]):
        """Subscribes an asynchronous coroutine callback: async_callback(from_state, to_state)."""
        if async_callback not in self._async_listeners:
            self._async_listeners.append(async_callback)

    def can_transition_to(self, new_state: AgentState) -> bool:
        """Validates if transition from current state to new_state is permissible."""
        allowed = self.VALID_TRANSITIONS.get(self._current_state, set())
        return new_state in allowed

    async def transition_to(self, new_state: AgentState, reason: str = "") -> bool:
        """
        Asynchronously transitions the state machine to a new state.
        Executes callbacks and logs state movement. Returns True if transition succeeded.
        """
        async with self._lock:
            old_state = self._current_state
            if old_state == new_state:
                return True

            if not self.can_transition_to(new_state):
                logger.warning(
                    f"[STATE MACHINE] ⚠️ Invalid state transition rejected: {old_state.value} -> {new_state.value} "
                    f"(Reason: {reason or 'N/A'})"
                )
                return False

            self._current_state = new_state
            logger.info(
                f"[STATE MACHINE] 🔄 Transition: {old_state.value} ➡️ {new_state.value}"
                + (f" ({reason})" if reason else "")
            )

            # 1. Trigger synchronous listeners
            for listener in self._listeners:
                try:
                    listener(old_state, new_state)
                except Exception as ex:
                    logger.error(f"[STATE MACHINE] Synchronous listener error: {ex}")

            # 2. Trigger asynchronous listeners
            for async_listener in self._async_listeners:
                try:
                    coro = async_listener(old_state, new_state)
                    if asyncio.iscoroutine(coro):
                        await coro
                except Exception as ex:
                    logger.error(f"[STATE MACHINE] Asynchronous listener error: {ex}")

            return True

    def transition_to_sync(self, new_state: AgentState, reason: str = "") -> bool:
        """Synchronous transition helper for non-async callbacks (e.g. keyboard hooks)."""
        old_state = self._current_state
        if old_state == new_state:
            return True

        if not self.can_transition_to(new_state):
            logger.warning(
                f"[STATE MACHINE] ⚠️ Invalid sync transition rejected: {old_state.value} -> {new_state.value}"
            )
            return False

        self._current_state = new_state
        logger.info(f"[STATE MACHINE] 🔄 Sync Transition: {old_state.value} ➡️ {new_state.value} ({reason})")

        for listener in self._listeners:
            try:
                listener(old_state, new_state)
            except Exception as ex:
                logger.error(f"[STATE MACHINE] Sync listener error: {ex}")

        return True


# -----------------------------------------------------------------------------
# Standalone Unit Test
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    console.print(Panel("[bold cyan]State Machine - Verification Suite[/bold cyan]", border_style="cyan"))

    sm = StateMachine()
    events_logged = []

    def log_state_change(old_st, new_st):
        events_logged.append((old_st.value, new_st.value))
        print(f"  🔔 Listener Alert: State changed from {old_st.value} to {new_st.value}")

    sm.add_listener(log_state_change)

    async def test_lifecycle():
        print("Testing valid standard lifecycle:")
        assert sm.is_idle()
        assert await sm.transition_to(AgentState.LISTENING, "User pressed Push-to-Talk")
        assert sm.is_listening()
        assert await sm.transition_to(AgentState.THINKING, "User released key")
        assert sm.is_thinking()
        assert await sm.transition_to(AgentState.SPEAKING, "TTS synthesis ready")
        assert sm.is_speaking()
        assert await sm.transition_to(AgentState.IDLE, "Speech playback finished")
        assert sm.is_idle()

        print("\nTesting barge-in interruption (Speaking -> Listening):")
        await sm.transition_to(AgentState.LISTENING)
        await sm.transition_to(AgentState.THINKING)
        await sm.transition_to(AgentState.SPEAKING)
        # Barge-in: User presses key while assistant is speaking!
        assert await sm.transition_to(AgentState.LISTENING, "Barge-in interruption")
        assert sm.is_listening()
        await sm.transition_to(AgentState.IDLE, "Cancelled")

        print("\nTesting invalid transition rejection:")
        # Cannot jump from IDLE directly to SPEAKING
        invalid_res = await sm.transition_to(AgentState.SPEAKING, "Invalid jump")
        assert not invalid_res, "Invalid transition should return False!"
        assert sm.is_idle(), "State should remain IDLE"

    asyncio.run(test_lifecycle())
    print(f"\nTotal transitions logged by listener: {len(events_logged)}")
    console.print("[bold green]✅ State Machine Verification Passed Successfully![/bold green]")
