"""
Text-to-Speech (TTS) Service for Project Nabih.
Supports Google Gemini TTS (gemini-3.8-flash-tts) as primary and Microsoft Edge-TTS as automatic fallback.
Plays audio in real-time from RAM using pygame.mixer with zero disk I/O.
"""

import sys
import io
import os
import re
import time
import json
import base64
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
os.environ["PYGAME_HIDE_SUPPORT_PROMPT"] = "1"
import pygame
import edge_tts
from loguru import logger
from rich.panel import Panel

from config import settings
from core.diagnostics import PipelineTelemetry, console
from core.circuit_breaker import ServiceCircuitBreaker

# Regex to strip emojis and symbols from text before sending to speech engines
EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # emoticons
    "\U0001F300-\U0001F5FF"  # symbols & pictographs
    "\U0001F680-\U0001F6FF"  # transport & map symbols
    "\U0001F1E0-\U0001F1FF"  # flags
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001F900-\U0001F9FF"  # supplemental symbols
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"  # misc symbols (like 🖤)
    "]+",
    flags=re.UNICODE,
)


def clean_text_for_speech(text: str) -> str:
    """Removes emojis and special symbol characters so TTS never pronounces them aloud."""
    cleaned = EMOJI_PATTERN.sub("", text)
    return re.sub(r"\s+", " ", cleaned).strip()


class TTSService:
    """High-quality Speech synthesis and playback service (Google Gemini TTS + Edge-TTS fallback)."""

    def __init__(
        self,
        provider: str = settings.TTS_PROVIDER,
        gemini_api_key: str = settings.GEMINI_API_KEY,
        gemini_model: str = settings.GEMINI_TTS_MODEL,
        gemini_voice: str = settings.GEMINI_TTS_VOICE,
        edge_voice: str = settings.TTS_VOICE,
        edge_rate: str = settings.TTS_RATE,
        edge_pitch: str = settings.TTS_PITCH,
        rate: Optional[str] = None,
        pitch: Optional[str] = None,
        voice: Optional[str] = None,
        **kwargs,
    ):
        self.provider = provider.lower()
        self.gemini_api_key = gemini_api_key
        self.gemini_model = gemini_model
        self.gemini_voice = gemini_voice
        self.edge_voice = voice or edge_voice
        self.edge_rate = rate or edge_rate
        self.edge_pitch = pitch or edge_pitch
        self.circuit_breaker = ServiceCircuitBreaker(
            service_name="Gemini-TTS",
            failure_threshold=3,
            recovery_timeout_s=120.0
        )
        self._ensure_mixer()

    @property
    def fallback_stats(self) -> dict:
        """Returns the health and fallback statistics of the primary TTS service."""
        return self.circuit_breaker.get_status_summary()

    def _ensure_mixer(self):
        """Initializes pygame mixer for in-memory audio playback."""
        if not pygame.mixer.get_init():
            try:
                # 24000 Hz handles Gemini WAV and Edge-TTS audio smoothly
                pygame.mixer.init(frequency=24000, size=-16, channels=2, buffer=1024)
                logger.debug("[TTS SERVICE] Pygame audio mixer initialized.")
            except Exception as ex:
                logger.error(f"[TTS SERVICE] Failed to initialize pygame mixer: {ex}")

    async def _synthesize_gemini_raw(self, text: str) -> Tuple[bytes, float]:
        """Synthesizes text using Google Gemini TTS in RAM. Raises exception on failure."""
        start_time = time.perf_counter()
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.gemini_model}:generateContent?key={self.gemini_api_key}"

        payload = {
            "contents": [{
                "parts": [{"text": text}]
            }],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "voiceConfig": {
                        "prebuiltVoiceConfig": {
                            "voiceName": self.gemini_voice
                        }
                    }
                }
            }
        }

        def _request():
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=8.0) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                candidates = res_data.get("candidates", [])
                if not candidates:
                    raise ValueError("No candidates returned from Gemini TTS")
                parts = candidates[0].get("content", {}).get("parts", [])
                for part in parts:
                    if "inlineData" in part:
                        b64_audio = part["inlineData"].get("data", "")
                        return base64.b64decode(b64_audio)
                raise ValueError("No audio inlineData found in Gemini response")

        audio_bytes = await asyncio.to_thread(_request)
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.info(f"[TTS SERVICE] Gemini TTS synthesized {len(audio_bytes) / 1024:.1f} KB in {latency_ms}ms ({self.gemini_model} - {self.gemini_voice})")
        return audio_bytes, latency_ms

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
        """
        Synthesizes text according to configured provider.
        Governed by Circuit Breaker: if primary fails repeatedly, it bypasses
        directly to Edge-TTS with 0s latency overhead.
        """
        clean_text = clean_text_for_speech(text)
        if not clean_text:
            return b"", 0.0

        if self.provider == "gemini" and self.gemini_api_key:
            # 1. Check Circuit Breaker: Is primary currently marked as DOWN?
            if not self.circuit_breaker.should_attempt_primary():
                logger.debug(
                    f"[TTS SERVICE] Circuit Breaker is OPEN ({self.circuit_breaker.consecutive_failures} failures). "
                    f"Skipping Gemini to avoid latency. Synthesizing directly via Edge-TTS."
                )
                return await self._synthesize_edge(clean_text)

            # 2. Attempt Primary (Gemini TTS)
            try:
                audio_bytes, latency_ms = await self._synthesize_gemini_raw(clean_text)
                self.circuit_breaker.record_success()
                return audio_bytes, latency_ms
            except Exception as ex:
                self.circuit_breaker.record_fallback(str(ex))
                # Fallback to Edge-TTS
                return await self._synthesize_edge(clean_text)

        return await self._synthesize_edge(clean_text)

    async def speak(
        self,
        text: str,
        on_start: Optional[Callable[[], None]] = None,
    ) -> float:
        """
        Synthesizes text and plays audio through speakers directly from RAM.
        Triggers on_start callback as soon as playback begins.
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
        """Immediately halts audio playback."""
        if pygame.mixer.get_init() and pygame.mixer.music.get_busy():
            pygame.mixer.music.stop()
            logger.debug("[TTS SERVICE] Audio playback halted.")


# -----------------------------------------------------------------------------
# Standalone Live Speech Synthesis Test
# -----------------------------------------------------------------------------
async def run_tts_test():
    console.print(Panel(
        f"[bold cyan]Testing Google Gemini Speech Synthesis Engine[/bold cyan]\n"
        f"Provider: {settings.TTS_PROVIDER.upper()} | Model: {settings.GEMINI_TTS_MODEL} | Voice: {settings.GEMINI_TTS_VOICE}\n"
        "Synthesizing and playing speech through your headphones...",
        title="🔊 [bold blue]GEMINI TTS TEST[/bold blue]",
        border_style="blue",
    ))

    tts = TTSService()
    test_phrase = "يا مساء الفل يا برنس! أنا نبيه، وصوتي طالع لايف من جوجل جيميني فلاش تي تي اس!"

    session = PipelineTelemetry("gemini_tts_playback_test")

    with session.profile_step("Gemini TTS", "🔊") as step:
        start = time.perf_counter()
        console.print(f"🤖 [bold green]Speaking (Gemini {settings.GEMINI_TTS_VOICE}):[/bold green] [bold white]{test_phrase}[/bold white]")
        await tts.speak(test_phrase)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        step.notes = f"Model: {settings.GEMINI_TTS_MODEL} | Synthesized & played in {elapsed_ms}ms"

    session.print_telemetry_table(
        user_text="Test Gemini TTS Request",
        shuri_reply=test_phrase
    )


if __name__ == "__main__":
    asyncio.run(run_tts_test())
