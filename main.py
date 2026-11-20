"""
Main Desktop Application Entry Point for Project Nabih (Phase 4 - Step 4.4).
Orchestrates the complete JARVIS-like experience:
  - Floating 3D Glowing Orb UI (HTML/CSS/Tailwind via pywebview)
  - Global Push-to-Talk Hotkey Daemon (Caps Lock via pynput)
  - Sub-second Whisper STT (Groq) & Sovereign Reasoning (Claude Haiku 5.5)
  - Autonomous Agent Tools (File & Terminal operations)
  - Prefetched Speech Synthesis (Google Gemini TTS + Edge-TTS fallback + Circuit Breaker)
"""

import sys
import time
import asyncio
import threading
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Activate resilient DNS fallback against ISP dropouts
import core.network_resilience
import tools  # Automatically registers all project and terminal tools

import webview
from loguru import logger
from rich.panel import Panel

from config import settings
from core.diagnostics import PipelineTelemetry, console
from core.state_machine import StateMachine, AgentState
from core.audio_recorder import AudioRecorder
from core.hotkey_listener import HotkeyListener
from core.stream_orchestrator import StreamOrchestrator
from services.stt_service import STTService
from services.llm_service import LLMService
from services.tts_service import TTSService
from ui.window import AssistantUI


class NabihDesktopApp:
    """Central orchestrator managing the desktop assistant lifecycle."""

    def __init__(self):
        provider_display = (
            f"Colab XTTS-v2 ({settings.XTTS_API_URL})"
            if settings.TTS_PROVIDER == "xtts"
            else f"{settings.TTS_PROVIDER} ({settings.TTS_VOICE})"
        )
        console.print(Panel(
            "[bold cyan]NABIH AI ASSISTANT - STARTING SYSTEM[/bold cyan]\n"
            f"[dim]Model: {settings.QWEN_MODEL_NAME} | TTS: {provider_display} | Hotkey: {settings.HOTKEY.upper()}[/dim]",
            border_style="cyan"
        ))

        # 1. Initialize Core State Machine
        self.state_machine = StateMachine(initial_state=AgentState.IDLE)

        # 2. Initialize Hardware & AI Adapters
        self.recorder = AudioRecorder(
            sample_rate=settings.AUDIO_SAMPLE_RATE,
            channels=settings.AUDIO_CHANNELS
        )
        self.stt = STTService()
        self.llm = LLMService()
        self.tts = TTSService()
        self.orchestrator = StreamOrchestrator(self.tts)

        # 3. Dedicated Background Asyncio Loop for AI Operations
        self.loop = asyncio.new_event_loop()
        self.loop_thread = threading.Thread(target=self._run_async_loop, daemon=True)
        self.loop_thread.start()
        self._active_asyncio_task: Optional[asyncio.Task] = None

        # 4. Initialize UI & Windows
        self.ui = AssistantUI(
            state_machine=self.state_machine,
            on_close=self.shutdown,
            on_orb_click=self._on_orb_click,
            on_interrupt=self.interrupt,
        )

        # 5. Initialize Global Push-to-Talk Hotkey (with ESC global interrupt)
        self.hotkey_listener = HotkeyListener(
            hotkey_name=settings.HOTKEY,
            state_machine=self.state_machine,
            on_press_callback=self._on_hotkey_press,
            on_release_callback=self._on_hotkey_release,
            on_interrupt_callback=self.interrupt,
        )

        self.turn_counter = 0
        self._is_processing = False

    def _run_async_loop(self):
        """Runs background asyncio event loop dedicated to non-blocking AI tasks."""
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def interrupt(self, reason: str = "User interrupt"):
        """
        Instantly halts any active recording, AI reasoning, tool execution, or speech:
          - Discards audio capture buffer immediately
          - Cancels active asyncio pipeline turn task
          - Stops background speech synthesis and pygame audio output
          - Resets state machine to IDLE with visual confirmation
        """
        logger.info(f"[DESKTOP APP] 🛑 Interrupt triggered: {reason}")

        # 1. Discard recorder if actively capturing
        if self.recorder.is_recording:
            self.recorder.cancel()

        # 2. Stop TTS and stream orchestrator immediately
        self.orchestrator.interrupt()
        self.tts.stop()

        # 3. Cancel active asyncio pipeline task
        def _cancel():
            if self._active_asyncio_task and not self._active_asyncio_task.done():
                self._active_asyncio_task.cancel()

        self.loop.call_soon_threadsafe(_cancel)

        # 4. Transition state machine back to IDLE
        self.state_machine.transition_to_sync(AgentState.IDLE, reason=reason)

        # 5. Show clean cancellation feedback in subtitles
        self.ui.update_subtitles("تم إلغاء الطلب فوراً يا هندسة ✋", is_user=False)
        console.print("\n[bold yellow]🛑 تم إلغاء الطلب فوراً (Interrupt) بنجاح.[/bold yellow]\n")

    def _on_orb_click(self):
        """Fallback for mouse click on the Glowing Orb to trigger interaction or interrupt."""
        if self.state_machine.is_idle():
            self._on_hotkey_press()
        else:
            # If listening, thinking, or speaking: clicking the Orb cancels immediately!
            self.interrupt(reason="User clicked Orb to interrupt")

    def _on_hotkey_press(self):
        """Triggered immediately when Push-to-Talk key is pressed down."""
        # Barge-in / Retake: If assistant is active (Thinking or Speaking), cancel previous turn!
        if not self.state_machine.is_idle():
            logger.info("[DESKTOP APP] ⚡ Barge-in: Halting active turn to record new speech.")
            self.orchestrator.interrupt()
            self.tts.stop()

            def _cancel():
                if self._active_asyncio_task and not self._active_asyncio_task.done():
                    self._active_asyncio_task.cancel()

            self.loop.call_soon_threadsafe(_cancel)

        # Start recording in RAM
        self.recorder.start()
        logger.info("[DESKTOP APP] 🎙️ Audio recording started in RAM.")

    def _on_hotkey_release(self):
        """Triggered immediately when Push-to-Talk key is released."""
        # Stop recording
        pcm_bytes, analysis = self.recorder.stop()

        if analysis["status"] == "EMPTY" or analysis["duration_s"] < 0.3:
            logger.debug("[DESKTOP APP] Audio capture too brief or empty. Returning to IDLE.")
            self.state_machine.transition_to_sync(AgentState.IDLE, reason="Brief or empty capture")
            return

        wav_bytes = AudioRecorder.pcm_to_wav_bytes(pcm_bytes)
        self.turn_counter += 1

        # Dispatch turn processing to async loop as a tracked task
        def _schedule():
            if self._active_asyncio_task and not self._active_asyncio_task.done():
                self._active_asyncio_task.cancel()
            self._active_asyncio_task = asyncio.create_task(
                self._process_turn_pipeline(wav_bytes, analysis, self.turn_counter)
            )

        self.loop.call_soon_threadsafe(_schedule)

    async def _process_turn_pipeline(self, wav_bytes: bytes, audio_analysis: dict, turn_num: int):
        """Executes full pipeline: STT -> Agent Tool Loop -> Prefetched Speech -> Synced UI."""
        session = PipelineTelemetry(f"desktop_turn_{turn_num:03d}")
        session.profile_step("Audio Capture", "🎙️").notes = (
            f"Duration: {audio_analysis['duration_s']}s | RMS: {audio_analysis['rms']}"
        )

        try:
            # Step 1: Speech-to-Text via Groq Whisper
            with session.profile_step("Groq Whisper STT", "⚡") as stt_step:
                user_transcript, stt_latency = await self.stt.transcribe_audio(wav_bytes, is_wav=True)
                stt_step.notes = f"Transcribed in {stt_latency}ms: '{user_transcript}'"

            if not user_transcript:
                logger.warning("[DESKTOP APP] No words recognized from audio.")
                await self.state_machine.transition_to(AgentState.IDLE, reason="No transcription recognized")
                return

            # Display user speech in UI subtitles
            self.ui.update_subtitles(user_transcript, is_user=True)
            console.print(f"\n[bold cyan]👤 أنت:[/bold cyan] [bold white]{user_transcript}[/bold white]")

            # Step 2: Stream reasoning, agent tools, and prefetched speech
            with session.profile_step("Brain & Voice Stream", "⚡") as brain_step:
                accumulated_sentence = ""

                def on_sentence_playback_starts(sentence: str):
                    nonlocal accumulated_sentence
                    # Transition state machine to SPEAKING precisely as audio begins!
                    self.state_machine.transition_to_sync(AgentState.SPEAKING, reason="Playback started")
                    accumulated_sentence += sentence + " "
                    self.ui.update_subtitles(accumulated_sentence.strip(), is_user=False)
                    console.print(f"🤖 [bold magenta]نبيه:[/bold magenta] [bold white]{sentence}[/bold white]")

                # Execute autonomous agent reasoning and prefetch audio
                token_stream = self.llm.chat_stream(user_transcript, enable_tools=True)
                full_reply, ttfa = await self.orchestrator.execute_stream(
                    token_stream=token_stream,
                    session=session,
                    on_sentence_display=on_sentence_playback_starts
                )
                brain_step.notes = f"TTFA: {ttfa:.1f}ms | Reply length: {len(full_reply)} chars"

                # Safety guarantee: If audio synthesis was skipped or silent, ensure text is visible on screen!
                if not accumulated_sentence.strip() and full_reply.strip():
                    logger.warning("[DESKTOP APP] Fallback: Displaying full reply directly in UI subtitles.")
                    self.ui.update_subtitles(full_reply.strip(), is_user=False)
                    console.print(f"🤖 [bold magenta]نبيه:[/bold magenta] [bold white]{full_reply.strip()}[/bold white]")

            # Print telemetry summary table
            session.print_telemetry_table(user_text=user_transcript, shuri_reply=full_reply)

        except asyncio.CancelledError:
            logger.info("[DESKTOP APP] 🛑 Turn pipeline cancelled/interrupted.")
            self.tts.stop()
            raise

        except Exception as ex:
            logger.error(f"[DESKTOP APP] Error during voice turn execution: {ex}")
            self.ui.update_subtitles("حصل خطأ بسيط في معالجة طلبك يا هندسة.", is_user=False)

        finally:
            # Return to IDLE state unless user already pressed Caps Lock to record next turn
            if not self.state_machine.is_listening():
                await self.state_machine.transition_to(AgentState.IDLE, reason="Turn completed or interrupted")

    def run(self):
        """Starts the desktop application window on main thread and activates global hotkey."""
        # Start global keyboard hook
        self.hotkey_listener.start()

        # Build PyWebView Window
        window = self.ui.create_window()

        # pywebview.start blocks the main thread with native Windows message loop
        webview.start(debug=False)

        # Cleanup on window close
        self.shutdown()

    def shutdown(self):
        """Cleanly tears down all background daemons and stops audio playback."""
        logger.info("[DESKTOP APP] Shutting down Nabih Assistant...")
        self.hotkey_listener.stop()
        self.tts.stop()
        self.ui.close()

        # Stop async loop
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)


# -----------------------------------------------------------------------------
# Application Main Execution
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    try:
        app = NabihDesktopApp()
        app.run()
    except (KeyboardInterrupt, SystemExit):
        console.print("\n[bold yellow]👋 تم إغلاق نبيه بنجاح. مع السلامة يا برنس![/bold yellow]\n")
        try:
            sys.exit(0)
        except SystemExit:
            pass
