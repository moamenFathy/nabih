"""
Text-to-Speech (TTS) Service for Project Nabih.
Supports Munsit AI (Hala Voice) and Microsoft Edge-TTS as a fallback.
Plays audio in real-time from RAM using pygame.mixer with zero disk I/O.
"""

import sys
import io
import time
import json
import asyncio
import urllib.request
import urllib.error
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
    """High-quality Arabic Speech synthesis and playback service (Munsit + Edge-TTS fallback)."""

    def __init__(
        self,
        provider: str = settings.TTS_PROVIDER,
        munsit_api_key: str = settings.MUNSIT_API_KEY,
        munsit_voice_id: str = settings.MUNSIT_VOICE_ID,
        munsit_model_id: str = settings.MUNSIT_MODEL_ID,
        edge_voice: str = settings.TTS_VOICE,
        edge_rate: str = settings.TTS_RATE,
        edge_pitch: str = settings.TTS_PITCH,
        rate: Optional[str] = None,
        pitch: Optional[str] = None,
        voice: Optional[str] = None,
        **kwargs,
    ):
        self.provider = provider.lower()
        self.munsit_api_key = munsit_api_key
        self.munsit_voice_id = munsit_voice_id
        self.munsit_model_id = munsit_model_id
        self.edge_voice = voice or edge_voice
        self.edge_rate = rate or edge_rate
        self.edge_pitch = pitch or edge_pitch
        self._ensure_mixer()

    def _ensure_mixer(self):
        """Initializes pygame mixer for in-memory audio playback."""
        if not pygame.mixer.get_init():
            try:
                # 24000 Hz handles both Munsit WAV and Edge-TTS audio smoothly
                pygame.mixer.init(frequency=24000, size=-16, channels=2, buffer=1024)
                logger.debug("[TTS SERVICE] Pygame audio mixer initialized.")
            except Exception as ex:
                logger.error(f"[TTS SERVICE] Failed to initialize pygame mixer: {ex}")

    async def _synthesize_munsit(self, text: str) -> Tuple[bytes, float]:
        """Synthesizes text using Munsit AI (Hala voice) in RAM."""
        start_time = time.perf_counter()
        url = f"https://api.munsit.com/api/v1/text-to-speech/{self.munsit_model_id}"
        payload = {
            "text": text,
            "voice_id": self.munsit_voice_id,
        }
        headers = {
            "x-api-key": self.munsit_api_key,
            "Content-Type": "application/json",
        }

        # Run blocking network call in background thread pool
        def _request():
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers=headers
            )
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                return resp.read()

        try:
            audio_bytes = await asyncio.to_thread(_request)
            latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
            logger.info(f"[TTS SERVICE] Munsit synthesized {len(audio_bytes) / 1024:.1f} KB in {latency_ms}ms (Voice: Hala)")
            return audio_bytes, latency_ms
        except Exception as ex:
            logger.warning(f"[TTS SERVICE] Munsit synthesis failed ({ex}). Falling back to Edge-TTS...")
            return await self._synthesize_edge(text)

    async def _synthesize_edge(self, text: str) -> Tuple[bytes, float]:
        """Synthesizes text using Microsoft Edge-TTS as fallback."""
        start_time = time.perf_counter()
        audio_buffer = bytearray()

        communicate = edge_tts.Communicate(
            text=text,
            voice=self.edge_voice,
            rate=self.edge_rate,
            pitch=self.edge_pitch,
        )

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.extend(chunk["data"])

        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        audio_bytes = bytes(audio_buffer)
        logger.debug(f"[TTS SERVICE] Edge-TTS synthesized {len(audio_bytes) / 1024:.1f} KB in {latency_ms}ms ({self.edge_voice})")
        return audio_bytes, latency_ms

    async def synthesize(self, text: str) -> Tuple[bytes, float]:
        """Synthesizes text according to configured provider."""
        if not text.strip():
            return b"", 0.0

        if self.provider == "munsit" and self.munsit_api_key:
            return await self._synthesize_munsit(text)
        return await self._synthesize_edge(text)

    async def speak(
        self,
        text: str,
        on_start: Optional[Callable[[], None]] = None,
    ) -> float:
        """
        Synthesizes text and plays audio through the speakers from RAM.
        Triggers on_start callback immediately as playback begins.
        """
        audio_bytes, synth_latency = await self.synthesize(text)
        if not audio_bytes:
            return 0.0

        self._ensure_mixer()
        self.stop()

        try:
            bio = io.BytesIO(audio_bytes)
            pygame.mixer.music.load(bio)
            pygame.mixer.music.play()

            # Trigger start callback (synchronized live subtitles)
            if on_start:
                try:
                    on_start()
                except Exception as cb_err:
                    logger.error(f"[TTS SERVICE] on_start callback error: {cb_err}")

            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.03)

            return synth_latency

        except Exception as ex:
            logger.error(f"[TTS SERVICE] Audio playback error: {ex}")
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
        f"[bold cyan]Testing Munsit AI Speech Synthesis Engine[/bold cyan]\n"
        f"Provider: {settings.TTS_PROVIDER.upper()} | Voice: Hala ({settings.MUNSIT_VOICE_ID})\n"
        "Synthesizing and playing speech through your headphones...",
        title="🔊 [bold blue]MUNSIT VOICE TEST[/bold blue]",
        border_style="blue",
    ))

    tts = TTSService()
    test_phrase = "يا مساء الفل يا برنس! أنا هالة، سامعة صوتك وجاهزة أساعدك في أي كود!"

    session = PipelineTelemetry("munsit_playback_test")

    with session.profile_step("Munsit AI (Hala)", "🔊") as step:
        start = time.perf_counter()
        console.print(f"🤖 [bold green]Speaking (Hala):[/bold green] [bold white]{test_phrase}[/bold white]")
        await tts.speak(test_phrase)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        step.notes = f"Voice: Hala | Synthesized & played in {elapsed_ms}ms"

    session.print_telemetry_table(
        user_text="Test Munsit Voice Request",
        shuri_reply=test_phrase
    )


if __name__ == "__main__":
    asyncio.run(run_tts_test())
