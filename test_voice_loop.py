"""
Interactive Real-Time Voice & Live Text Loop for Project Nabih (Phase 2 - Step 2.3 & 2.4).
Features Producer-Consumer Sentence Chunking:
Tokens from Qwen 27B stream into sentences and play through speakers concurrently for sub-second latency!
"""

import sys
import time
import asyncio
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Activate resilient DNS fallback against local ISP dropouts
import core.network_resilience

from rich.panel import Panel
from rich.text import Text
from rich.live import Live

from config import settings
from core.audio_recorder import AudioRecorder
from services.stt_service import STTService
from services.tts_service import TTSService
from services.llm_service import LLMService
from core.stream_orchestrator import StreamOrchestrator
from core.diagnostics import PipelineTelemetry, console


async def run_voice_turn(
    recorder: AudioRecorder,
    stt: STTService,
    tts: TTSService,
    llm: LLMService,
    orchestrator: StreamOrchestrator,
    turn_index: int
):
    """Executes a single interactive voice turn with sentence-chunked streaming."""
    console.print(f"\n[bold cyan]━━━ 🎙️ Turn #{turn_index} ━━━[/bold cyan]")
    console.print("[bold yellow]Press [ENTER] to START recording and speak...[/bold yellow]")
    await asyncio.to_thread(input)

    session = PipelineTelemetry(f"voice_loop_turn_{turn_index:03d}")

    # 1. Start Recording in RAM
    recorder.start()
    console.print("[bold green]🔴 Recording in progress... Press [ENTER] to STOP![/bold green]")
    await asyncio.to_thread(input)

    # 2. Stop Recording
    pcm_bytes, analysis = recorder.stop()
    wav_bytes = AudioRecorder.pcm_to_wav_bytes(pcm_bytes)

    with session.profile_step("Audio Capture", "🎙️") as step:
        step.notes = f"Duration: {analysis['duration_s']}s | RMS: {analysis['rms']} | {analysis['status']}"

    if analysis["status"] == "EMPTY" or analysis["duration_s"] < 0.3:
        console.print("[yellow]⚠️ Recording was too brief or empty. Speak a clear sentence.[/yellow]")
        return

    # 3. Speech-to-Text Transcription via Groq Whisper
    user_transcript = ""
    with session.profile_step("Groq Whisper STT", "⚡") as step:
        try:
            user_transcript, stt_latency = await stt.transcribe_audio(wav_bytes, is_wav=True)
            step.notes = f"Transcribed in {stt_latency}ms: '{user_transcript}'"
        except Exception as ex:
            step.status = "FAIL"
            step.error = f"STT failed: {ex}"
            return

    if not user_transcript:
        console.print("[yellow]⚠️ No words recognized. Check your microphone and speak clearly.[/yellow]")
        return

    # 4. Display User's Transcribed Text in Chat Panel
    user_panel = Panel(
        Text.from_markup(f"[bold cyan]أنت:[/bold cyan] [bold white]{user_transcript}[/bold white]"),
        border_style="cyan",
        expand=False
    )
    console.print(user_panel)

    # 5. Concurrent Producer-Consumer Streaming (Qwen Tokens -> Sentence Chunks -> Voice Playback)
    full_reply = ""
    ttfa_recorded = 0.0

    with session.profile_step("Brain & Voice Stream", "⚡") as step:
        console.print("[dim cyan]🧠 التفكير جاري وبث الصوت فورياً (Sub-second streaming)...[/dim cyan]")
        
        accumulated_text = ""
        live_display = Live(console=console, refresh_per_second=20)
        live_display.start()

        def display_sentence(sentence: str):
            nonlocal accumulated_text
            accumulated_text += sentence + " "
            display = Text()
            display.append("🤖 نبيه: ", style="bold magenta")
            display.append(accumulated_text.strip(), style="bold white")
            live_display.update(Panel(display, border_style="magenta", expand=False))

        try:
            token_stream = llm.chat_stream(user_transcript)
            full_reply, ttfa_recorded = await orchestrator.execute_stream(
                token_stream=token_stream,
                session=session,
                on_sentence_display=display_sentence
            )
            step.notes = f"TTFA (Time-To-First-Audio): {ttfa_recorded:.1f}ms | Streaming Completed"
        except Exception as ex:
            step.status = "FAIL"
            step.error = f"Streaming error: {ex}"
            full_reply = "حصل خطأ بسيط أثناء معالجة الصوت يا هندسة."
        finally:
            live_display.stop()

    # 6. Print the Telemetry Breakdown Table
    session.print_telemetry_table(
        user_text=user_transcript,
        shuri_reply=full_reply
    )


async def main():
    console.print(Panel(
        f"[bold cyan]Project Nabih - Sub-Second Streaming Voice Assistant (Phase 2)[/bold cyan]\n"
        f"Microphone: In-Memory 16kHz PCM (RAM Buffer)\n"
        f"STT: Groq Whisper API ({settings.GROQ_MODEL})\n"
        f"LLM Brain: Sovereign Qwen 27B ({settings.QWEN_MODEL_NAME})\n"
        f"TTS Voice: Munsit AI (Hala) with Edge-TTS Fallback\n"
        f"Optimization: [bold green]Sentence Chunking Producer-Consumer Stream Enabled![/bold green]\n"
        "Press [Ctrl + C] anytime to exit.",
        title="⚡ [bold blue]NABIH ULTRA-FAST VOICE ENGINE[/bold blue]",
        border_style="blue"
    ))

    # Initialize all operational services
    tts = TTSService()
    recorder = AudioRecorder()
    stt = STTService()
    llm = LLMService()
    orchestrator = StreamOrchestrator(tts_service=tts)

    turn_count = 1
    try:
        while True:
            await run_voice_turn(recorder, stt, tts, llm, orchestrator, turn_count)
            turn_count += 1
    except KeyboardInterrupt:
        console.print("\n[bold yellow]👋 Exiting Nabih Assistant. See you later, Prince![/bold yellow]\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit, asyncio.CancelledError):
        console.print("\n[bold yellow]👋 تم إغلاق البرنامج بنجاح. مع السلامة يا برنس![/bold yellow]\n")
        try:
            sys.exit(0)
        except SystemExit:
            pass
