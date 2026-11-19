"""
Speech-to-Text (STT) Service for Project Nabih.
Streams in-memory WAV audio bytes to Groq Whisper API (whisper-large-v3).
Zero disk writes; audio is uploaded directly from RAM.
"""

import sys
import io
import time
import asyncio
from pathlib import Path
from typing import Tuple, Optional

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from openai import AsyncOpenAI
from loguru import logger
from rich.panel import Panel

from config import settings
from core.audio_recorder import AudioRecorder
from core.diagnostics import PipelineTelemetry, console


# Context prompt to guide Whisper towards natural Egyptian Arabic and tech terminology
EGYPTIAN_ARABIC_PROMPT = (
    "محادثة بالعامية المصرية مع المساعد الذكي شوري وجارفيس. "
    "مصطلحات برمجية وتقنية مثل: بايثون، كود، إيرور، باج، دالة، ملف، جيت، تيرمينال."
)


class STTService:
    """High-speed Speech-to-Text service utilizing Groq Whisper API."""

    def __init__(
        self,
        api_key: str = settings.GROQ_API_KEY,
        model: str = settings.GROQ_MODEL,
        base_url: str = "https://api.groq.com/openai/v1",
    ):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url, timeout=10.0)

    async def transcribe_audio(
        self,
        audio_bytes: bytes,
        is_wav: bool = True,
        sample_rate: int = settings.AUDIO_SAMPLE_RATE,
    ) -> Tuple[str, float]:
        """
        Transcribes in-memory audio bytes to Arabic text.
        
        Args:
            audio_bytes: In-memory raw PCM or WAV bytes.
            is_wav: If False, automatically wraps PCM in WAV container in RAM.
            sample_rate: Sample rate in Hz.

        Returns:
            Tuple[transcript_text, latency_ms]
        """
        if not audio_bytes:
            logger.warning("[STT SERVICE] Received empty audio bytes.")
            return "", 0.0

        # Ensure audio has standard WAV headers in RAM
        if not is_wav:
            wav_bytes = AudioRecorder.pcm_to_wav_bytes(audio_bytes, sample_rate=sample_rate)
        else:
            wav_bytes = audio_bytes

        start_time = time.perf_counter()

        try:
            # Virtual in-memory file tuple: (filename, bytes_data, content_type)
            virtual_file = ("audio.wav", wav_bytes, "audio/wav")

            response = await self._client.audio.transcriptions.create(
                model=self.model,
                file=virtual_file,
                language="ar",  # Arabic transcription
                prompt=EGYPTIAN_ARABIC_PROMPT,
                response_format="text",
                temperature=0.0,  # Strict, accurate transcription
            )

            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            transcript = response.strip() if isinstance(response, str) else response.text.strip()

            logger.info(f"[STT SERVICE] Transcribed in {latency_ms}ms: '{transcript}'")
            return transcript, latency_ms

        except Exception as ex:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(f"[STT SERVICE] Groq Whisper transcription failed after {latency_ms}ms: {ex}")
            raise ex


# -----------------------------------------------------------------------------
# Standalone Live Speech-to-Text Test
# -----------------------------------------------------------------------------
async def run_stt_test():
    console.print(Panel(
        f"[bold cyan]Testing Groq Whisper Speech-to-Text[/bold cyan]\n"
        f"Model: {settings.GROQ_MODEL} | Language: Egyptian Arabic (ar)\n"
        "We will record 3 seconds from your mic and send it directly to Groq...",
        title="⚡ [bold blue]GROQ STT LIVE TEST[/bold blue]",
        border_style="blue",
    ))

    recorder = AudioRecorder()
    stt = STTService()

    console.print("[yellow]🎙️ Speak now! Say something in Egyptian Arabic (e.g. 'ازيك يا شوري يا عبقرية')...[/yellow]")
    
    recorder.start()
    await asyncio.sleep(3.0)
    pcm_bytes, analysis = recorder.stop()

    wav_bytes = AudioRecorder.pcm_to_wav_bytes(pcm_bytes)

    session = PipelineTelemetry("stt_test_run")

    with session.profile_step("Audio Capture", "🎙️") as step:
        step.notes = f"Size: {analysis['size_kb']} KB | RMS: {analysis['rms']} | {analysis['status']}"

    transcript = ""
    with session.profile_step("Groq Whisper STT", "⚡") as step:
        try:
            transcript, stt_latency = await stt.transcribe_audio(wav_bytes, is_wav=True)
            step.notes = f"Transcribed in {stt_latency}ms: '{transcript}'"
        except Exception as ex:
            step.status = "FAIL"
            step.error = f"Transcription error: {ex}"

    session.print_telemetry_table(
        user_text=transcript if transcript else "(No speech detected)",
        shuri_reply="STT Pipeline Test Completed"
    )

    if transcript:
        console.print(f"✨ [bold green]Recognized Text:[/bold green] [bold white]{transcript}[/bold white]\n")
    else:
        console.print("⚠️ [bold yellow]No text transcribed (Mic might have been silent).[/bold yellow]\n")


if __name__ == "__main__":
    asyncio.run(run_stt_test())
