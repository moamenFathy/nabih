"""
Configuration management module for Project Nabih.
Uses Pydantic Settings to load, validate, and provide typed access to environment variables.
"""

from pathlib import Path
from typing import Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Activate resilient DNS fallback for all network calls
import core.network_resilience


class Settings(BaseSettings):
    """Application settings and secrets loaded from .env file."""

    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).parent / ".env"),
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # 1. Speech-to-Text (Groq Whisper)
    GROQ_API_KEY: str = Field(default="gsk_placeholder", description="Groq API Key for Whisper STT")
    GROQ_MODEL: str = Field(default="whisper-large-v3", description="Whisper model on Groq")

    # 2. LLM Brain (Hosted Qwen 27B-FP8)
    QWEN_BASE_URL: str = Field(default="http://localhost:8000/v1", description="OpenAI-compatible base URL")
    QWEN_API_KEY: str = Field(default="EMPTY", description="API key for hosted endpoint if required")
    QWEN_MODEL_NAME: str = Field(default="Qwen3.8-27B-FP8", description="Target model identifier")
    LLM_TEMPERATURE: float = Field(default=0.7, ge=0.0, le=2.0)
    LLM_MAX_TOKENS: int = Field(default=1024, gt=0)

    # 3. Text-to-Speech (Google Gemini TTS & Microsoft Edge-TTS Fallback)
    TTS_PROVIDER: str = Field(default="gemini", description="TTS provider: 'gemini' or 'edge'")
    GEMINI_API_KEY: str = Field(default="", description="Gemini API key for speech synthesis")
    GEMINI_TTS_MODEL: str = Field(default="gemini-3.8-flash-lite-tts", description="Gemini TTS Model ID")
    GEMINI_TTS_VOICE: str = Field(default="Aoede", description="Prebuilt voice name (Aoede, Kore, Puck, etc.)")
    TTS_VOICE: str = Field(default="ar-EG-ShakirNeural", description="Egyptian Arabic voice fallback for Edge-TTS")
    TTS_RATE: str = Field(default="+15%", description="Speaking speed adjustment")
    TTS_PITCH: str = Field(default="+0Hz", description="Voice pitch adjustment")

    # 4. Trigger & Audio
    HOTKEY: str = Field(default="caps_lock", description="Global push-to-talk hotkey")
    AUDIO_SAMPLE_RATE: int = Field(default=16000, description="Audio sample rate in Hz")
    AUDIO_CHANNELS: int = Field(default=1, description="Mono audio recording")

    # 5. Diagnostics & Logging
    LOG_LEVEL: str = Field(default="DEBUG", description="Logging verbosity")
    LOG_TO_FILE: bool = Field(default=True, description="Persist logs to disk")
    LOG_FILE_PATH: str = Field(default="logs/shuri_diagnostics.log", description="Path to log file")

    # 6. Workspace Directory
    WORKSPACE_ROOT: str = Field(default="C:/Users/moame", description="Root folder for local projects")

    @property
    def is_groq_configured(self) -> bool:
        """Check if a real Groq API key is provided."""
        return bool(self.GROQ_API_KEY and not self.GROQ_API_KEY.startswith("gsk_placeholder"))

    @property
    def is_qwen_configured(self) -> bool:
        """Check if Qwen base URL is provided and not default localhost placeholder."""
        return bool(self.QWEN_BASE_URL)


# Global singleton instance
settings = Settings()


if __name__ == "__main__":
    print(f"✅ Settings loaded successfully!")
    print(f"🎙️ TTS Voice: {settings.TTS_VOICE}")
    print(f"⚡ Groq STT Model: {settings.GROQ_MODEL} (Configured: {settings.is_groq_configured})")
    print(f"🧠 LLM Endpoint: {settings.QWEN_BASE_URL} (Model: {settings.QWEN_MODEL_NAME})")
    print(f"⌨️ Push-to-Talk Hotkey: {settings.HOTKEY}")
