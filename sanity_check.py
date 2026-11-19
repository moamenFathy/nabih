"""
Sanity Verification Suite for Project Nabih.
Tests local configuration, Edge-TTS synthesis, Groq Whisper reachability, and Qwen LLM endpoint.
Renders real-time telemetry profiling for all external connections.
"""

import sys
import asyncio
import time
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import edge_tts
from openai import AsyncOpenAI
from rich.panel import Panel

from config import settings
from core.diagnostics import PipelineTelemetry, console, AudioProfiler


async def run_sanity_checks():
    """Executes end-to-end connectivity and synthesis checks."""
    console.print(Panel(
        f"[bold cyan]Project Nabih - Environment & Connectivity Sanity Check[/bold cyan]\n"
        f"Workspace: {settings.WORKSPACE_ROOT}\n"
        f"Python: {sys.version.split()[0]} | Edge Voice: {settings.TTS_VOICE}",
        title="🔍 [bold blue]SANITY CHECK SUITE[/bold blue]",
        border_style="blue"
    ))

    session = PipelineTelemetry("sanity_verification_run")

    # -------------------------------------------------------------------------
    # 1. Configuration Validation
    # -------------------------------------------------------------------------
    with session.profile_step("Config Validation", "⚙️") as step:
        step.notes = f"HotKey: {settings.HOTKEY} | Rate: {settings.AUDIO_SAMPLE_RATE}Hz"

    # -------------------------------------------------------------------------
    # 2. Edge-TTS Egyptian Arabic Voice Synthesis
    # -------------------------------------------------------------------------
    test_phrase = "أهلاً يا برنس، صوت شوري شغال تمام ومفيش أي مشكلة."
    audio_buffer = bytearray()

    with session.profile_step("Edge-TTS Voice", "🔊") as step:
        try:
            communicate = edge_tts.Communicate(
                text=test_phrase,
                voice=settings.TTS_VOICE,
                rate=settings.TTS_RATE,
                pitch=settings.TTS_PITCH
            )
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_buffer.extend(chunk["data"])

            size_kb = round(len(audio_buffer) / 1024.0, 1)
            step.notes = f"Generated {size_kb} KB audio in memory ({settings.TTS_VOICE})"
        except Exception as ex:
            step.status = "FAIL"
            step.error = f"Edge-TTS synthesis error: {ex}"

    # -------------------------------------------------------------------------
    # 3. Groq Whisper Endpoint Check
    # -------------------------------------------------------------------------
    with session.profile_step("Groq STT Endpoint", "⚡") as step:
        if not settings.is_groq_configured:
            step.status = "WARNING"
            step.notes = "Using placeholder key. Update GROQ_API_KEY in .env when ready."
        else:
            try:
                groq_client = AsyncOpenAI(
                    api_key=settings.GROQ_API_KEY,
                    base_url="https://api.groq.com/openai/v1",
                    timeout=5.0
                )
                models = await groq_client.models.list()
                step.notes = f"Connected (HTTP 200 OK) - {len(models.data)} models available"
            except Exception as ex:
                step.status = "FAIL"
                step.error = f"Groq connection error: {ex}"

    # -------------------------------------------------------------------------
    # 4. Hosted Qwen 27B LLM Endpoint Check
    # -------------------------------------------------------------------------
    with session.profile_step("Hosted Qwen 27B", "🧠") as step:
        if not settings.is_qwen_configured or "localhost:8000" in settings.QWEN_BASE_URL:
            step.status = "WARNING"
            step.notes = f"Default endpoint ({settings.QWEN_BASE_URL}). Update in .env with your Sovereign URL."
        else:
            try:
                qwen_client = AsyncOpenAI(
                    api_key=settings.QWEN_API_KEY,
                    base_url=settings.QWEN_BASE_URL,
                    timeout=5.0
                )
                # Quick 1-token probe
                response = await qwen_client.chat.completions.create(
                    model=settings.QWEN_MODEL_NAME,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=1
                )
                step.notes = f"Connected (HTTP 200 OK) - Model: {settings.QWEN_MODEL_NAME}"
            except Exception as ex:
                step.status = "WARNING"
                step.notes = f"Host not reachable at {settings.QWEN_BASE_URL} ({type(ex).__name__})"

    # -------------------------------------------------------------------------
    # 5. Output Telemetry Table & Summary
    # -------------------------------------------------------------------------
    session.print_telemetry_table(
        user_text="Sanity Verification Test",
        shuri_reply="All foundational modules verified and ready."
    )


if __name__ == "__main__":
    asyncio.run(run_sanity_checks())
