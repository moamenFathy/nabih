"""
In-Memory Audio Recorder for Project Nabih.
Captures microphone audio directly into RAM (BytesIO) using sounddevice.
No temporary files are created on disk.
"""

import sys
import io
import wave
import time
import queue
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import sounddevice as sd
from loguru import logger
from rich.panel import Panel

from config import settings
from core.diagnostics import AudioProfiler, console


class AudioRecorder:
    """High-performance in-memory audio recorder for Push-to-Talk interactions."""

    def __init__(
        self,
        sample_rate: int = settings.AUDIO_SAMPLE_RATE,
        channels: int = settings.AUDIO_CHANNELS,
        dtype: str = "int16",
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.dtype = dtype

        self._audio_queue: queue.Queue = queue.Queue()
        self._stream: Optional[sd.InputStream] = None
        self._is_recording: bool = False
        self._start_time: float = 0.0

    @property
    def is_recording(self) -> bool:
        """Returns True if the recorder is actively capturing mic input."""
        return self._is_recording

    def _audio_callback(self, indata, frames, time_info, status):
        """Callback executed by sounddevice for every incoming audio buffer."""
        if status:
            logger.warning(f"[AUDIO STREAM] Status: {status}")
        if self._is_recording:
            self._audio_queue.put(indata.copy())

    def start(self):
        """Starts capturing microphone audio into RAM buffer."""
        if self._is_recording:
            logger.warning("[AUDIO RECORDER] Already recording. Ignoring start call.")
            return

        # Clear existing queue
        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

        self._is_recording = True
        self._start_time = time.perf_counter()

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=self.channels,
            dtype=self.dtype,
            callback=self._audio_callback,
        )
        self._stream.start()
        logger.debug("[AUDIO RECORDER] Microphone stream started in RAM.")

    def cancel(self):
        """Immediately halts active recording and discards all buffered audio without processing."""
        if not self._is_recording and self._stream is None:
            return

        self._is_recording = False
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as ex:
                logger.error(f"[AUDIO RECORDER] Error cancelling stream: {ex}")
            finally:
                self._stream = None

        while not self._audio_queue.empty():
            try:
                self._audio_queue.get_nowait()
            except queue.Empty:
                break

        logger.debug("[AUDIO RECORDER] 🛑 Active recording cancelled and RAM buffer purged.")

    def stop(self) -> Tuple[bytes, Dict[str, Any]]:
        """
        Stops capturing audio and returns:
        1. raw_pcm_bytes: Raw 16-bit PCM bytes.
        2. analysis: Dictionary with duration, RMS, dBFS, and quality diagnosis.
        """
        if not self._is_recording:
            logger.warning("[AUDIO RECORDER] Recorder was not active.")
            return b"", AudioProfiler.analyze_pcm16(b"")

        self._is_recording = False
        duration_elapsed = time.perf_counter() - self._start_time

        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as ex:
                logger.error(f"[AUDIO RECORDER] Error closing stream: {ex}")
            finally:
                self._stream = None

        # Collect all chunks from the queue
        chunks = []
        while not self._audio_queue.empty():
            try:
                chunks.append(self._audio_queue.get_nowait())
            except queue.Empty:
                break

        if not chunks:
            logger.warning("[AUDIO RECORDER] No audio chunks captured in buffer.")
            return b"", AudioProfiler.analyze_pcm16(b"")

        # Concatenate numpy arrays and convert to raw PCM bytes
        full_audio_array = np.concatenate(chunks, axis=0)
        pcm_bytes = full_audio_array.tobytes()

        # Run diagnostic analysis
        analysis = AudioProfiler.analyze_pcm16(pcm_bytes, sample_rate=self.sample_rate)
        logger.debug(
            f"[AUDIO RECORDER] Captured {analysis['duration_s']}s ({analysis['size_kb']} KB) | "
            f"RMS: {analysis['rms']} | {analysis['status']}"
        )

        return pcm_bytes, analysis

    @staticmethod
    def pcm_to_wav_bytes(
        pcm_bytes: bytes,
        sample_rate: int = settings.AUDIO_SAMPLE_RATE,
        channels: int = settings.AUDIO_CHANNELS,
        sample_width: int = 2,  # 2 bytes for int16
    ) -> bytes:
        """
        Wraps raw PCM bytes in a standard WAV container entirely in RAM.
        Returns a valid WAV file as bytes without writing anything to disk.
        """
        if not pcm_bytes:
            return b""

        wav_io = io.BytesIO()
        with wave.open(wav_io, "wb") as wav_file:
            wav_file.setnchannels(channels)
            wav_file.setsampwidth(sample_width)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(pcm_bytes)

        wav_io.seek(0)
        return wav_io.read()


# -----------------------------------------------------------------------------
# Standalone Audio Hardware & Recording Test
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    console.print(Panel(
        "[bold cyan]Testing Audio Recorder Hardware & Memory Buffer[/bold cyan]\n"
        "Verifying default input/output audio devices...",
        title="🎙️ [bold blue]AUDIO HARDWARE TEST[/bold blue]",
        border_style="blue",
    ))

    # 1. Query Default Audio Devices
    try:
        default_in = sd.query_devices(kind="input")
        default_out = sd.query_devices(kind="output")
        console.print(f"🎤 [bold green]Default Mic:[/bold green] {default_in['name']}")
        console.print(f"🔊 [bold green]Default Speaker:[/bold green] {default_out['name']}\n")
    except Exception as ex:
        console.print(f"⚠️ [bold red]Audio Device Query Warning:[/bold red] {ex}\n")

    # 2. Automated 2-Second Recording Test
    recorder = AudioRecorder()
    console.print("[yellow]Recording 2 seconds of audio into RAM buffer for testing... Speak now![/yellow]")
    
    recorder.start()
    time.sleep(2.0)
    pcm_data, report = recorder.stop()

    wav_data = AudioRecorder.pcm_to_wav_bytes(pcm_data)

    console.print(f"✅ [bold green]Recording Complete![/bold green]")
    console.print(f"📊 [white]PCM Size:[/white] {report['size_kb']} KB")
    console.print(f"📦 [white]In-Memory WAV Size:[/white] {round(len(wav_data) / 1024.0, 1)} KB")
    console.print(f"⏱️ [white]Duration:[/white] {report['duration_s']} seconds")
    console.print(f"🔊 [white]RMS Volume:[/white] {report['rms']} ({report['dbfs']} dBFS)")
    console.print(f"🩺 [bold cyan]Diagnosis:[/bold cyan] {report['diagnosis']}\n")
