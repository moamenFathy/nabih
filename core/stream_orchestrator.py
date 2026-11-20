"""
Prefetched Pipelined Voice Orchestrator for Project Nabih (Step 2.3 & 2.4).
Features a 3-Stage Concurrent Pipeline:
  1. Token Producer -> Chunks into complete semantic sentences (No comma chopping).
  2. Audio Synthesizer (Prefetcher) -> Synthesizes sentence N+1 in background while N is playing.
  3. Audio Player & Subtitle Synchronizer -> Plays audio with 0ms seam gaps and reveals text in exact sync with speech!
"""

import sys
import io
import time
import asyncio
from pathlib import Path
from typing import AsyncGenerator, List, Tuple, Optional, Callable

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pygame
from loguru import logger
from rich.panel import Panel
from rich.live import Live
from rich.text import Text

from config import settings
from services.tts_service import TTSService
from core.diagnostics import PipelineTelemetry, console


class NaturalSentenceChunker:
    """
    Buffers streaming LLM tokens and yields complete sentences on natural terminal boundaries.
    Never splits on commas (،) to preserve vocal flow, prosody, and emotional continuity.
    """

    TERMINAL_DELIMITERS = {'.', '!', '؟', '?', '\n', '؛'}
    MIN_WORDS_THRESHOLD = 6  # Minimum words required before allowing a split

    def __init__(self):
        self.buffer = ""

    def add_token(self, token: str) -> List[str]:
        """Adds a token and returns any completed sentences."""
        self.buffer += token
        sentences = []

        while True:
            split_idx = -1
            for idx, char in enumerate(self.buffer):
                if char in self.TERMINAL_DELIMITERS:
                    words_so_far = len(self.buffer[:idx].split())
                    if words_so_far >= self.MIN_WORDS_THRESHOLD:
                        split_idx = idx
                        break

            if split_idx != -1:
                sentence = self.buffer[:split_idx + 1].strip()
                self.buffer = self.buffer[split_idx + 1:].lstrip()
                if sentence:
                    sentences.append(sentence)
            else:
                break

        return sentences

    def flush(self) -> Optional[str]:
        """Flushes any remaining text in the buffer as the final sentence."""
        remaining = self.buffer.strip()
        self.buffer = ""
        return remaining if remaining else None


class StreamOrchestrator:
    """
    Coordinates concurrent token streaming, background audio prefetching,
    and zero-gap synchronized speech playback.
    """

    def __init__(self, tts_service: TTSService):
        self.tts = tts_service

    async def execute_stream(
        self,
        token_stream: AsyncGenerator[Tuple[str, Optional[float]], None],
        session: PipelineTelemetry,
        on_sentence_display: Optional[Callable[[str], None]] = None,
    ) -> Tuple[str, float]:
        """
        Executes 3 concurrent stages:
          - Stage 1: LLM tokens -> Natural Sentences
          - Stage 2: Background Synthesis Prefetching -> Audio queue in RAM
          - Stage 3: Zero-gap Playback & Synchronized Subtitles
        Returns: (full_text_response, time_to_first_speech_ms)
        """
        sentence_queue: asyncio.Queue = asyncio.Queue()
        audio_queue: asyncio.Queue = asyncio.Queue(maxsize=3)

        full_tokens: List[str] = []
        first_token_ttft = 0.0
        ttfa_ms = 0.0
        pipeline_start = time.perf_counter()
        chunker = NaturalSentenceChunker()

        # ---------------------------------------------------------------------
        # Stage 1: Producer - Streams LLM tokens into complete sentences
        # ---------------------------------------------------------------------
        async def producer():
            nonlocal first_token_ttft
            try:
                async for token, ttft in token_stream:
                    if ttft is not None and first_token_ttft == 0.0:
                        first_token_ttft = ttft
                    full_tokens.append(token)

                    for sentence in chunker.add_token(token):
                        await sentence_queue.put(sentence)

                # Flush final trailing sentence if any
                trailing = chunker.flush()
                if trailing:
                    await sentence_queue.put(trailing)

            except Exception as ex:
                logger.error(f"[STREAM ORCHESTRATOR] Producer error: {ex}")
            finally:
                # Sentinel to signal end of sentences
                await sentence_queue.put(None)

        # ---------------------------------------------------------------------
        # Stage 2: Synthesizer (Prefetcher) - Prepares audio in RAM ahead of time
        # ---------------------------------------------------------------------
        async def synthesizer():
            while True:
                sentence = await sentence_queue.get()
                if sentence is None:
                    # Signal player that all audio has been queued
                    await audio_queue.put((None, None))
                    break

                try:
                    audio_bytes, latency_ms = await self.tts.synthesize(sentence)
                    if audio_bytes:
                        await audio_queue.put((sentence, audio_bytes))
                except Exception as ex:
                    logger.error(f"[STREAM ORCHESTRATOR] Synthesis prefetch error on '{sentence[:20]}...': {ex}")

        # ---------------------------------------------------------------------
        # Stage 3: Player - Plays audio with 0ms gap & reveals synced subtitles
        # ---------------------------------------------------------------------
        async def player():
            nonlocal ttfa_ms
            is_first_sentence = True

            while True:
                sentence, audio_bytes = await audio_queue.get()
                if sentence is None or audio_bytes is None:
                    break

                # Record Time-To-First-Audio (TTFA)
                if is_first_sentence:
                    ttfa_ms = round((time.perf_counter() - pipeline_start) * 1000, 2)
                    is_first_sentence = False

                # Reveal subtitle precisely as audio begins playing!
                if on_sentence_display:
                    try:
                        on_sentence_display(sentence)
                    except Exception as disp_err:
                        logger.error(f"[STREAM ORCHESTRATOR] Display callback error: {disp_err}")

                # Play audio directly from RAM
                try:
                    self.tts._ensure_mixer()
                    bio = io.BytesIO(audio_bytes)
                    pygame.mixer.music.load(bio)
                    pygame.mixer.music.play()

                    while pygame.mixer.music.get_busy():
                        await asyncio.sleep(0.02)

                except Exception as play_err:
                    logger.error(f"[STREAM ORCHESTRATOR] Playback error: {play_err}")

        # Run all 3 stages concurrently!
        await asyncio.gather(producer(), synthesizer(), player())

        full_reply = "".join(full_tokens).strip()
        return full_reply, ttfa_ms
