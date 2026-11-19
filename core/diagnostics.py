"""
Deep Observability & Pipeline Telemetry Engine for Project Nabih.
Provides millisecond-level step profiling, audio quality analysis, and root-cause error diagnostics.
"""

import sys
import time
import math
from pathlib import Path
from typing import Optional, Dict, Any, List
from contextlib import contextmanager

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
from loguru import logger
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

from config import settings

# Initialize Rich Console
console = Console()

# -----------------------------------------------------------------------------
# 1. Dual Logging Setup (Console + Rotating File in logs/)
# -----------------------------------------------------------------------------
log_path = Path(settings.LOG_FILE_PATH)
if not log_path.is_absolute():
    log_path = PROJECT_ROOT / log_path

log_path.parent.mkdir(parents=True, exist_ok=True)

logger.remove()  # Remove default handler
logger.add(
    sys.stderr,
    level=settings.LOG_LEVEL,
    format="<green>{time:HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
)

if settings.LOG_TO_FILE:
    logger.add(
        str(log_path),
        rotation="10 MB",
        retention="7 days",
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{line} - {message}",
        encoding="utf-8",
    )


# -----------------------------------------------------------------------------
# 2. Audio Quality Profiler (RMS Volume & Silence Detection)
# -----------------------------------------------------------------------------
class AudioProfiler:
    """Analyzes raw audio buffers in RAM to detect mic volume, clipping, or silence."""

    @staticmethod
    def analyze_pcm16(audio_bytes: bytes, sample_rate: int = 16000) -> Dict[str, Any]:
        """Inspects raw PCM 16-bit audio bytes directly in RAM."""
        if not audio_bytes:
            return {
                "duration_s": 0.0,
                "size_kb": 0.0,
                "rms": 0.0,
                "dbfs": -100.0,
                "status": "EMPTY",
                "diagnosis": "❌ No audio captured (0 bytes in buffer)",
            }

        size_kb = len(audio_bytes) / 1024.0
        audio_data = np.frombuffer(audio_bytes, dtype=np.int16)
        num_samples = len(audio_data)
        duration_s = num_samples / float(sample_rate)

        # Calculate Root Mean Square (RMS) volume
        if num_samples == 0:
            rms = 0.0
        else:
            rms = float(np.sqrt(np.mean(audio_data.astype(np.float64) ** 2)))

        # Convert to dBFS (Full Scale)
        if rms > 0:
            dbfs = 20.0 * math.log10(rms / 32768.0)
        else:
            dbfs = -100.0

        # Diagnosis logic
        if duration_s < 0.3:
            status = "TOO_SHORT"
            diagnosis = f"⚠️ Audio too short ({duration_s:.2f}s) - Released hotkey too fast?"
        elif rms < 150:  # Very low amplitude
            status = "SILENT"
            diagnosis = f"🔇 Microphone silent/muted (RMS: {rms:.0f}, {dbfs:.1f} dBFS)"
        elif rms > 30000:
            status = "CLIPPING"
            diagnosis = f"📢 Audio clipping - Microphone gain too high! (RMS: {rms:.0f})"
        else:
            status = "OPTIMAL"
            diagnosis = f"✅ Clear audio ({duration_s:.2f}s, RMS: {rms:.0f}, {dbfs:.1f} dBFS)"

        return {
            "duration_s": round(duration_s, 2),
            "size_kb": round(size_kb, 1),
            "rms": round(rms, 1),
            "dbfs": round(dbfs, 1),
            "status": status,
            "diagnosis": diagnosis,
        }


# -----------------------------------------------------------------------------
# 3. Pipeline Telemetry & Step Profiler
# -----------------------------------------------------------------------------
class StepRecord:
    def __init__(self, name: str, icon: str = "⚡"):
        self.name = name
        self.icon = icon
        self.duration_ms: float = 0.0
        self.status: str = "PENDING"
        self.notes: str = ""
        self.error: Optional[str] = None


class PipelineTelemetry:
    """Tracks a single turn interaction across the entire pipeline."""

    def __init__(self, session_id: Optional[str] = None):
        self.session_id = session_id or f"turn_{int(time.time() * 1000)}"
        self.start_time = time.perf_counter()
        self.steps: List[StepRecord] = []

    @contextmanager
    def profile_step(self, name: str, icon: str = "⚡"):
        """Context manager to measure millisecond execution of a single pipeline stage."""
        record = StepRecord(name, icon)
        start = time.perf_counter()
        try:
            yield record
            record.status = "SUCCESS" if not record.error else "FAIL"
        except Exception as ex:
            record.status = "FAIL"
            record.error = str(ex)
            logger.error(f"[TELEMETRY ERROR] Stage '{name}' failed: {ex}")
            raise ex
        finally:
            record.duration_ms = round((time.perf_counter() - start) * 1000, 2)
            self.steps.append(record)

    def print_telemetry_table(self, user_text: str = "", shuri_reply: str = ""):
        """Renders the step-by-step latency profiling table to the console."""
        total_time_ms = round((time.perf_counter() - self.start_time) * 1000, 2)

        table = Table(
            title=f"⚡ [bold cyan]Pipeline Execution Telemetry[/bold cyan] (Session: {self.session_id})",
            title_style="bold cyan",
            border_style="cyan",
            header_style="bold bright_white on blue",
            show_lines=True,
        )

        table.add_column("Stage", style="bold yellow", width=22)
        table.add_column("Duration", justify="right", width=12)
        table.add_column("Status", justify="center", width=12)
        table.add_column("Details / Diagnosis", style="white")

        for step in self.steps:
            if step.status == "SUCCESS":
                status_badge = "[bold green]DONE[/bold green]"
            elif step.status == "FAIL":
                status_badge = "[bold red]FAILED[/bold red]"
            elif step.status == "WARNING":
                status_badge = "[bold yellow]WARN[/bold yellow]"
            else:
                status_badge = f"[cyan]{step.status}[/cyan]"

            dur_str = f"{step.duration_ms:.1f} ms"
            if step.duration_ms > 1500:
                dur_str = f"[bold red]{dur_str}[/bold red]"
            elif step.duration_ms > 700:
                dur_str = f"[yellow]{dur_str}[/yellow]"
            else:
                dur_str = f"[green]{dur_str}[/green]"

            table.add_row(
                f"{step.icon} {step.name}",
                dur_str,
                status_badge,
                step.error if step.error else step.notes,
            )

        # Total Summary Row
        table.add_row(
            "[bold white]🚀 Total Turn Latency[/bold white]",
            f"[bold cyan]{total_time_ms:.1f} ms[/bold cyan]",
            "[bold green]COMPLETE[/bold green]",
            f"User: '{user_text[:40]}...' | Shuri: '{shuri_reply[:40]}...'" if user_text else "End-to-End Execution Complete",
            style="bold on black",
        )

        console.print()
        console.print(table)
        console.print()

    def print_error_diagnostics(self, step_name: str, error_message: str, suggestion: str = ""):
        """Renders root-cause analysis (RCA) when a stage fails."""
        content = Text()
        content.append(f"❌ PIPELINE STAGE FAILURE: ", style="bold red")
        content.append(f"{step_name}\n\n", style="bold yellow")
        content.append(f"Root Cause Analysis:\n", style="bold underline white")
        content.append(f"{error_message}\n\n", style="red")

        if suggestion:
            content.append(f"💡 Recommended Resolution:\n", style="bold underline green")
            content.append(f"{suggestion}\n", style="green")

        panel = Panel(
            content,
            title="🚨 [bold red]ROOT CAUSE ERROR DIAGNOSTICS[/bold red] 🚨",
            border_style="bright_red",
            expand=False,
        )
        console.print(panel)


# -----------------------------------------------------------------------------
# 4. Standalone Demonstration Test
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    console.print(Panel("[bold green]Testing Telemetry & Diagnostics Engine...[/bold green]", border_style="green"))

    session = PipelineTelemetry("demo_turn_001")

    # Audio stage simulation
    with session.profile_step("Audio Capture", "🎙️") as step:
        time.sleep(0.08)
        dummy_audio = np.random.randint(-1000, 1000, size=16000 * 2, dtype=np.int16).tobytes()
        analysis = AudioProfiler.analyze_pcm16(dummy_audio)
        step.notes = f"Size: {analysis['size_kb']} KB | RMS: {analysis['rms']} | {analysis['status']}"

    # STT stage simulation
    with session.profile_step("Groq Whisper STT", "⚡") as step:
        time.sleep(0.19)
        step.notes = "HTTP 200 OK | Transcribed: 'ازيك يا شوري'"

    # LLM stage simulation
    with session.profile_step("Qwen 27B Brain", "🧠") as step:
        time.sleep(0.31)
        step.notes = "TTFT: 310ms | Tokens: 42 | Speed: 48 tok/s"

    # Tool stage simulation
    with session.profile_step("Tool: read_file", "🔧") as step:
        time.sleep(0.015)
        step.notes = "Read 'config.py' (65 lines, 2.1 KB)"

    # TTS stage simulation
    with session.profile_step("Edge-TTS Streaming", "🔊") as step:
        time.sleep(0.12)
        step.notes = "Voice: ar-EG-SalmaNeural | Chunks: 3 | Status: Playing"

    # Print clean telemetry table
    session.print_telemetry_table(
        user_text="ازيك يا شوري",
        shuri_reply="أهلاً يا برنس! كودك زي الفل وملف config مقروء وجاهز."
    )
