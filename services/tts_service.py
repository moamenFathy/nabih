"""
Text-to-Speech (TTS) Service for Project Nabih.
Synthesizes Egyptian Arabic speech via Microsoft Edge-TTS (ar-EG-SalmaNeural).
Plays audio in real-time from RAM using pygame.mixer with zero disk I/O.
"""

import sys
import io
import time
import asyncio
from pathlib import Path
from typing import Optional, Callable, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Suppress pygame startup message
import os
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame
import edge_tts
from loguru import logger
from rich.panel import Panel

from config import settings
from core.diagnostics import PipelineTelemetry, console


class TTSService:
    """High-quality Egyptian Arabic Speech synthesis and playback service."""

    def __init__(
        self,
        voice: str = settings.TTS_VOICE,
        rate: str = settings.TTS_RATE,
        pitch: str = settings.TTS_PITCH,
    ):
        self.voice = voice
        self.rate = rate
        self.pitch = pitch
        self._is_initialized = False
        self._ensure_mixer()

    def _ensure_mixer(self):
        """Initializes pygame mixer for in-memory audio playback."""
        if not pygame.mixer.get_init():
            try:
                # 24000 Hz is the native sample rate for Edge-TTS neural models
                pygame.mixer.init(frequency=24000, size=-16, channels=2, buffer=1024)
                self._is_initialized = True
                logger.debug("[TTS SERVICE] Pygame audio mixer initialized.")
            except Exception as ex:
                logger.error(f"[TTS SERVICE] Failed to initialize pygame mixer: {ex}")
                self._is_initialized = False

    async def synthesize(self, text: str) -> Tuple[bytes, float]:
        """
        Synthesizes text to in-memory MP3 audio bytes.
        Returns: (audio_bytes, latency_ms)
        """
        if not text.strip():
            return b"", 0.0

        start_time = time.perf_counter()
        audio_buffer = bytearray()

        try:
            communicate = edge_tts.Communicate(
                text=text,
                voice=self.voice,
                rate=self.rate,
                pitch=self.pitch,
            )

            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_buffer.extend(chunk["data"])

            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            audio_bytes = bytes(audio_buffer)
            logger.debug(
                f"[TTS SERVICE] Synthesized {len(audio_bytes) / 1024:.1f} KB in {latency_ms}ms "
                f"({self.voice})"
            )
            return audio_bytes, latency_ms

        except Exception as ex:
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.error(f"[TTS SERVICE] Synthesis failed: {ex}")
            raise ex

    async def speak(
        self,
        text: str,
        on_start: Optional[Callable[[], None]] = None,
    ) -> float:
        """
        Synthesizes text and plays it through the speakers from RAM.
        Triggers on_start callback immediately as the first sound is played.
        Returns total execution time in milliseconds.
        """
        audio_bytes, synth_latency = await self.synthesize(text)
        if not audio_bytes:
            return 0.0

        self._ensure_mixer()

        # Stop any currently playing audio
        self.stop()

        try:
            # Load MP3 bytes directly from in-memory stream
            bio = io.BytesIO(audio_bytes)
            pygame.mixer.music.load(bio)
            pygame.mixer.music.play()

            # Trigger start callback (e.g., to begin live text animation)
            if on_start:
                on_start()

            # Wait asynchronously until playback finishes
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.04)

            return synth_latency

        except Exception as ex:
            logger.error(f"[TTS SERVICE] Playback error: {ex}")
            return synth_latency

    def stop(self):
        """Immediately interrupts and halts audio playback."""
        if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
            logger.debug("[TTS SERVICE] Audio playback halted.")


# -----------------------------------------------------------------------------
# Standalone Live Speech Synthesis Test
# -----------------------------------------------------------------------------
async def run_tts_test():
    console.print(Panel(
        f"[bold cyan]Testing Edge-TTS Playback Engine[/bold cyan]\n"
        f"Voice: {settings.TTS_VOICE} (Egyptian Arabic)\n"
        "Synthesizing and playing speech directly through your headphones...",
        title="🔊 [bold blue]EDGE-TTS PLAYBACK TEST[/bold blue]",
        border_style="blue",
    ))

    tts = TTSService()
    test_phrase = "أهلاً يا برنس، أنا شوري ومبسوطة إني شغالة معاك على جهازك، صوتي واصلك تمام؟"

    session = PipelineTelemetry("tts_playback_test")

    with session.profile_step("Edge-TTS Voice", "🔊") as step:
        start = time.perf_counter()
        
        console.print(f"🤖 [bold green]Speaking:[/bold green] [bold white]{test_phrase}[/bold white]")
        await tts.speak(test_phrase)
        
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        step.notes = f"Voice: {settings.TTS_VOICE} | Played in {elapsed_ms}ms"

    session.print_telemetry_table(
        user_text="Test TTS Phrase Request",
        shuri_reply=test_phrase
    )


if __name__ == "__main__":
    asyncio.run(run_tts_test())
