"""
Interactive Real-Time Voice & Live Text Loop for Project Nabih (Phase 1).
Synchronized audio playback and real-time live subtitles with zero disk I/O.
"""

import sys
import time
import asyncio
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from rich.panel import Panel
from rich.text import Text
from rich.live import Live

from config import settings
from core.audio_recorder import AudioRecorder
from services.stt_service import STTService
from services.tts_service import TTSService
from core.diagnostics import PipelineTelemetry, console


async def stream_synchronized_text(prefix: str, full_text: str, playback_event: asyncio.Event, delay_per_word: float = 0.22):
    """Waits for playback to actually begin, then animates text in sync with speech."""
    # Wait until audio is actively emitting sound from the speakers!
    await playback_event.wait()
    
    words = full_text.split()
    accumulated = ""
    
    with Live(console=console, refresh_per_second=20) as live:
        for word in words:
            accumulated += word + " "
            display_text = Text()
            display_text.append(prefix, style="bold magenta")
            display_text.append(accumulated, style="bold white")
            live.update(Panel(display_text, border_style="magenta", expand=False))
            await asyncio.sleep(delay_per_word)


async def run_voice_turn(recorder: AudioRecorder, stt: STTService, tts: TTSService, turn_index: int):
    """Executes a single interactive voice-to-voice turn."""
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

    # 5. Snappy, Natural Confirmation Phrase (optimized for ultra-low latency)
    shuri_reply = f"سامعاك يا برنس! قولت: {user_transcript}."

    # 6. Synchronized Audio Playback + Live Subtitle Streaming
    with session.profile_step("Edge-TTS Voice", "🔊") as step:
        playback_started_event = asyncio.Event()

        # Run speech playback and synchronized typewriter subtitles concurrently!
        await asyncio.gather(
            tts.speak(shuri_reply, on_start=playback_started_event.set),
            stream_synchronized_text("شوري: ", shuri_reply, playback_started_event, delay_per_word=0.22)
        )
        step.notes = f"Voice: {settings.TTS_VOICE} | Perfectly synchronized audio & text"

    # 7. Print the Telemetry Breakdown Table
    session.print_telemetry_table(
        user_text=user_transcript,
        shuri_reply=shuri_reply
    )


async def main():
    console.print(Panel(
        f"[bold cyan]Project Nabih - Interactive Voice Loop (Phase 1 Optimized)[/bold cyan]\n"
        f"Microphone: In-Memory 16kHz PCM (RAM Buffer)\n"
        f"STT: Groq Whisper API ({settings.GROQ_MODEL})\n"
        f"TTS: Microsoft Edge Neural Voice ({settings.TTS_VOICE}) [Synchronized]\n"
        "Press [Ctrl + C] anytime to exit.",
        title="🌟 [bold blue]INTERACTIVE VOICE ENGINE[/bold blue]",
        border_style="blue"
    ))

    # Initialize services
    tts = TTSService()
    recorder = AudioRecorder()
    stt = STTService()

    turn_count = 1
    try:
        while True:
            await run_voice_turn(recorder, stt, tts, turn_count)
            turn_count += 1
    except KeyboardInterrupt:
        console.print("\n[bold yellow]👋 Exiting Voice Loop. Great session, Prince![/bold yellow]\n")


if __name__ == "__main__":
    asyncio.run(main())
