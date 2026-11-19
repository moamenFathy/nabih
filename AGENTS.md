# 🤖 Project Nabih - Ultra-Fast AI Desktop Voice Assistant

> **Nabih (نبيه):** An ultra-fast, zero-cost, voice-first desktop AI assistant inspired by **JARVIS** and **Shuri (Wakanda)**. Nabih natively understands and speaks Egyptian Arabic with a witty, sharp, genius persona, operating via Push-to-Talk to inspect, debug, and execute code across your local projects with zero operational cost ($0.00).

---

## 🧭 AI Agent Onboarding Guide
> **CRITICAL FOR ALL NEW SESSIONS / AGENTS:**
> Always read this file first upon starting a conversation. This document serves as the Single Source of Truth (SSOT). It tracks the real-time project state, approved architecture decisions, completed milestones, and immediate next steps. Update the checkboxes and state section whenever a milestone is completed.

---

## 🔬 Deep Observability & Pipeline Telemetry Engine
Nabih features a dedicated **distributed tracing, latency profiling, and root-cause diagnostic engine** (`core/diagnostics.py`). 

Instead of guessing why an audio snippet was misunderstood or why a call lagged, every single interaction generates a comprehensive breakdown:
1. **Audio Stage Profiling:** Mic recording duration (ms), In-memory buffer size (KB), and RMS volume level (alerts if mic is too quiet or muted).
2. **STT Stage Profiling (Groq Whisper):** Exact HTTP response code, network round-trip time (RTT in ms), and raw extracted Egyptian Arabic text.
3. **LLM Brain Stage Profiling (Hosted Qwen 27B):** Time To First Token (TTFT in ms), total generation time, tokens per second, and complete tool-calling schema inspection.
4. **Tool Execution Profiler:** Exact tool invoked, incoming arguments, execution duration, and full formatted traceback if an error occurs.
5. **TTS Streaming Profiling (Edge-TTS):** Time to first audio chunk (ms) and playback status.
6. **End-to-End Latency Table:** Formatted visual table rendered in the terminal via `rich` after every turn:
   ```text
   ┌───────────────────────┬────────────┬──────────┐
   │ Pipeline Stage        │ Latency    │ Status   │
   ├───────────────────────┼────────────┼──────────┤
   │ 🎙️ Audio Capture      │ 2.10s      │ SUCCESS  │
   │ ⚡ Groq Whisper STT   │ 184ms      │ 200 OK   │
   │ 🧠 Qwen 27B Brain     │ 320ms      │ STREAMING│
   │ 🔧 Tool: read_file    │ 14ms       │ SUCCESS  │
   │ 🔊 Edge-TTS Streaming │ 110ms      │ PLAYING  │
   ├───────────────────────┼────────────┼──────────┤
   │ 🚀 Total Latency      │ 0.62s      │ DONE     │
   └───────────────────────┴────────────┴──────────┘
   ```
All logs are dual-outputted: formatted colorfully to the terminal with `rich` and written as structured JSON lines to rotating files in `logs/shuri_diagnostics.log`.

---

## 📐 Architecture & Technology Stack

| Layer / Component | Technology | Architectural Rationale |
| :--- | :--- | :--- |
| **Core Runtime** | Python 3.10+ | Dominant AI/ML ecosystem, native audio streaming, AST code manipulation, future RAG support |
| **LLM Brain** | `Qwen 27B-FP8` (User Hosted) | State-of-the-art coding and Arabic comprehension, zero token cost ($0) |
| **Speech-to-Text (STT)**| Groq Whisper API (`whisper-large-v3`) | Fastest cloud transcription (~200ms latency), exceptional Egyptian Arabic parsing, free tier |
| **Text-to-Speech (TTS)**| Microsoft Edge-TTS (`ar-EG-SalmaNeural`) | 100% free, natural Egyptian Arabic voice, low-latency audio chunk streaming |
| **Desktop UI** | Modern HTML/CSS/Tailwind via `pywebview` | Sleek glowing orb interface using native Edge WebView2 (lightweight, ~30MB RAM vs 250MB Electron) |
| **Trigger Mechanism** | Push-to-Talk (`pynput` Global Hotkey) | Zero idle CPU/GPU consumption, prevents ambient noise false-triggers |
| **Audio Pipeline** | In-Memory Audio (`io.BytesIO`) | Zero disk I/O latency; audio buffers live and die directly in RAM |
| **Observability** | Pipeline Telemetry (`rich` + `loguru`) | Real-time millisecond profiling and deterministic root cause error analysis |

---

## 📊 Current Project State

* **Active Phase:** `Phase 1: In-Memory Voice Loop (STT & TTS)`
* **Codebase Status:** Phase 0 (Environment, Config, Telemetry, and Sanity Checks) **100% COMPLETE & VERIFIED**.
* **Connectivity Verified:**
  - Groq Whisper API: Connected (HTTP 200 OK - 11 models available)
  - Hosted Qwen 27B: Connected (HTTP 200 OK - Qwen3.8-27B-FP8)
  - Edge-TTS: Verified (ar-EG-SalmaNeural generated audio in memory)
* **Immediate Next Action:**
  - Build `core/audio_recorder.py` for RAM-based microphone capture.
  - Build `services/stt_service.py` to stream audio buffers to Groq Whisper.
  - Build `services/tts_service.py` to stream Edge-TTS audio to speakers.
  - Test end-to-end voice loop in terminal (<1.0s latency).

---

## 🗺️ Implementation Roadmap

### [x] Phase 0: Environment Setup, Configuration & Diagnostics (COMPLETED)
- [x] Create standardized project directory skeleton (`core/`, `services/`, `tools/`, `ui/`, `logs/`).
- [x] Define dependencies in `requirements.txt` (`rich`, `loguru`, `openai`, `edge-tts`, `sounddevice`, `numpy`, `pywebview`, `pynput`).
- [x] Implement central configuration reader in `config.py` with `.env` validation.
- [x] **Build Pipeline Telemetry & Diagnostics Engine (`core/diagnostics.py`):**
  - [x] Implement `Timer` context managers for millisecond-level step profiling.
  - [x] Implement RMS audio volume level analyzer to detect microphone clipping or silence.
  - [x] Implement `rich` terminal summary tables for end-to-end latency breakdowns.
  - [x] Configure `loguru` file logger with automatic daily rotation in `logs/`.
- [x] **Build Sanity Verification Suite (`sanity_check.py`):**
  - [x] Ping Groq Whisper API endpoint (Verified: HTTP 200 OK).
  - [x] Ping Hosted Qwen 27B LLM endpoint (Verified: HTTP 200 OK).
  - [x] Synthesize test audio chunk with Edge-TTS (`ar-EG-SalmaNeural` verified).
  - [x] Print complete diagnostic verification table to terminal.

### [ ] Phase 1: In-Memory Voice Loop (STT & TTS)
- [ ] Build `core/audio_recorder.py`: In-memory recording (`io.BytesIO`), buffer management, and volume calculation.
- [ ] Build `services/stt_service.py`: Forward in-memory audio bytes to Groq Whisper and extract Egyptian Arabic text.
- [ ] Build `services/tts_service.py`: Edge-TTS audio stream consumer with playback queue.
- [ ] Integrate Phase 1 CLI test: Press key -> record voice -> transcribe -> repeat back in Egyptian voice (<1.0s response).

### [ ] Phase 2: The Brain & Shuri Persona (Qwen 27B Streaming)
- [ ] Build `services/llm_service.py`: OpenAI-compatible client connecting to user's hosted `Qwen 27B-FP8`.
- [ ] Engineer the **Shuri Persona System Prompt**: Egyptian Arabic dialect, witty, sharp, direct, technical mastery.
- [ ] Implement Producer-Consumer token chunker: Forward first generated sentence directly to TTS while LLM continues streaming.
- [ ] Run full conversational test in CLI with Shuri's real-time voice under 1.5 seconds.

### [ ] Phase 3: The Hands - Tool Registry & Project Access
- [ ] Build `tools/registry.py`: `@register_tool` decorator with automated JSON schema extraction for function calling.
- [ ] Build `tools/file_tools.py`: Local directory tree explorer, file reader, and code writer.
- [ ] Build `tools/terminal_tools.py`: Safe CLI command runner (`git status`, `npm run`, etc.) with security sandboxing.
- [ ] Hook tool-calling loop into the LLM orchestrator with diagnostic profiling for tool execution time and I/O.
- [ ] Test voice-guided bug fixing on a local project file.

### [ ] Phase 4: Desktop UI & Global Hotkey (The Full Experience)
- [ ] Build `core/state_machine.py`: Deterministic state transitions (`IDLE`, `LISTENING`, `THINKING`, `SPEAKING`).
- [ ] Build `core/hotkey_listener.py`: Global Push-to-Talk hotkey daemon (e.g. `Caps Lock`).
- [ ] Design `ui/`: Modern, glowing orb widget in HTML/CSS/Tailwind rendered via `pywebview`.
- [ ] Establish two-way Python-to-JS bridge to update orb state (glow, pulse, rotate, speak).
- [ ] Deliver complete standalone desktop application.

### [ ] Phase 5: Hardening, Safety & Latency Tuning
- [ ] Add explicit safety confirmation before executing destructive terminal commands (`rm`, `git reset --hard`).
- [ ] Implement auto-reconnection and fallback handling for transient network dropouts.
- [ ] Fine-tune audio chunk thresholds for minimum latency.

---

## 📂 Project Directory Structure

```text
C:/Users/moame/nabih/
│
├── core/
│   ├── __init__.py
│   ├── orchestrator.py      # Main pipeline coordinator
│   ├── state_machine.py     # State management (Idle, Listening, Thinking, Speaking)
│   ├── audio_recorder.py    # In-memory RAM audio capture
│   ├── hotkey_listener.py   # Global Push-to-Talk daemon
│   └── diagnostics.py       # Pipeline Telemetry & Root Cause Diagnostics
│
├── services/
│   ├── __init__.py
│   ├── stt_service.py       # Groq Whisper API adapter
│   ├── llm_service.py       # Hosted Qwen 27B adapter
│   └── tts_service.py       # Edge-TTS streaming playback adapter
│
├── tools/
│   ├── __init__.py
│   ├── registry.py          # Automatic tool registration & schema generation
│   ├── file_tools.py        # Local project file inspection & editing
│   └── terminal_tools.py    # Safe CLI / Terminal execution
│
├── ui/
│   ├── index.html           # Glowing Orb presentation
│   ├── styles.css           # Pulse & glow animations
│   └── app.js               # Bi-directional Python/UI bridge
│
├── logs/                    # Rotating structured diagnostic logs
├── .env.example             # Template for API credentials & endpoints
├── .env                     # Local secrets
├── config.py                # Centralized environment loader
├── requirements.txt         # Pinned project dependencies
├── sanity_check.py          # End-to-end diagnostic verification script
├── AGENTS.md                # AI Agent Single Source of Truth (this file)
└── main.py                  # Desktop application entry point
```
