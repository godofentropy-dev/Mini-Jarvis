# Mini-Jarvis 🦾

> A local-first, voice-controlled AI assistant for Windows, powered by Ollama. No subscriptions.

[![Python](https://img.shields.io/badge/Python-3.10-blue?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%2F11-lightgrey?logo=windows&logoColor=white)](https://www.microsoft.com/windows)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)
[![Local-first](https://img.shields.io/badge/AI-Local--first-brightgreen)](#-privacy-first)

---

## 📸 Screenshots

![Mini-Jarvis UI](screenshots/ui.png)
*The arc reactor interface with N.O.V.A. active — system stats, transcript, and voice controls.*

---

## ✨ Features

| Category | Details |
| --- | --- |
| **🧠 AI Brain** | Local inference through **Ollama** (llama3.2:3b); optional web-connected features use the internet |
| **🔐 Voice Lock** | Optional speaker verification for spoken commands; typed commands remain available |
| **👥 6 AI Personas** | Each with unique voice, color, personality, and specialty |
| **👁️ Vision** | Screen reading + camera input + drag-and-drop image analysis |
| **💬 Messaging** | Reads/sends WhatsApp & Instagram via browser automation |
| **📅 Calendar** | Google Calendar integration (read-only iCal, offline cache) |
| **🎮 System Control** | Open/close apps, web search, volume control — all by voice |
| **⚡ Smart Power** | Sleep mode cuts CPU/RAM, interruptible with "stop" |
| **🧠 Memory** | Asks permission before saving — *"Should I remember that?"* |
| **🎨 UI** | Animated arc reactor, floating orb mode, real-time system monitor |

---

## 🎭 The Assistants

| Name | Color | Role |
| --- | --- | --- |
| **Echo** | 🔵 Blue | Daily driver — general tasks, conversation |
| **Nova** | 🟢 Green | Code help — programming, debugging, tech questions |
| **Aegis** | ⚪ Silver | System monitor & security — alerts, battery, performance |
| **Atlas** | 🟡 Gold | Heavy data & storage — file management, backups |
| **Vortex** | 🟣 Purple | Web gathering — research, news, information retrieval |
| **Silo** | 🔴 Red | *Kept in containment. Do not call him.* |

---

## 🚀 Quick Start

### Prerequisites

- Windows 10/11
- Python 3.10, 64-bit (the pinned Windows dlib wheel currently targets CPython 3.10)
- [Ollama](https://ollama.com/) installed
- Microphone

### Installation

```bash
# 1. Pull the AI model
ollama pull llama3.2:3b

# 2. Clone the repo
git clone https://github.com/godofentropy-dev/Mini-Jarvis.git
cd Mini-Jarvis

# 3. Set up virtual environment
python -m venv venv
venv\Scripts\activate

# 4. Install dependencies
pip install -r requirements.txt
playwright install

# 5. Download models (not included in repo)
# - Vosk speech model: https://alphacephei.com/vosk/models
#   → vosk-model-small-en-us-0.15 (unzip to project folder)
# - Piper voices: place in `voices/` folder

# 6. Add your Google Calendar iCal link
#    (create a text file — see calendar_agent.py for filename)

# 7. Run!
python voice.py
```

**First launch:** Say *"register my voice"* to set up voice lock.

### Optional feature dependencies

Install only the extras for the features you plan to use:

- Screen automation: `pyautogui`, `pywinauto`, `pynput`, `pyperclip`
- Voice lock: `resemblyzer` and a compatible `torch` build
- Silero voice activity detection: `silero-vad` and `torch`
- System telemetry: `psutil`
- Windows notifications: `winotify`
- PDF search and song downloads: `ddgs`, `yt-dlp`, and FFmpeg
- Android integration: Android Platform Tools (ADB) and USB debugging

These are optional; the core app can start without many of them, but related features will be unavailable.

---

## 🗂️ Project Structure

The current repository is intentionally flat rather than split into packages:

```text
Mini-Jarvis/
├── voice.py                 # Main entry point and orchestration
├── jarvis_ui.py             # Tkinter interface
├── reactors.py, ui_effects.py
├── llm_utils.py, jobs.py    # Local model helpers and job logic
├── *_agent.py               # Feature agents (calendar, files, phone, vision, etc.)
├── plugins/                 # Optional extensions
├── tests/                   # Regression tests
├── screenshots/             # Project screenshots
├── requirements.txt
└── .github/workflows/       # CI checks
```

---

## 🔒 Privacy-First Design

| What | How |
| --- | --- |
| **Voice processing** | Vosk and Piper run locally after their models are installed |
| **AI inference** | Ollama inference runs locally; no hosted LLM API is required |
| **Voice prints** | Stored locally on the device |
| **Memories** | Stored locally, with a consent prompt before saving personal facts |
| **Browser sessions** | Playwright profile stays on the device |
| **Internet use** | Web search, news, downloads, calendar feed refreshes, and messaging require network access |

---

## 🎮 Voice Commands

| Say... | Action |
| --- | --- |
| *"Open Chrome"* | Launch applications |
| *"Search for [query]"* | Web search |
| *"Volume up / down / mute"* | Audio control |
| *"What's on my screen?"* | Vision analysis |
| *"Read my messages"* | Check WhatsApp/Instagram |
| *"Stop"* | Interrupt current task |
| *"Go to sleep"* | Low-power mode |
| *"Register my voice"* | Set up voice lock |

---

## 🛠️ Tech Stack

| Component | Technology |
| --- | --- |
| **LLM** | Ollama (llama3.2:3b) |
| **Speech-to-Text** | Vosk (offline) |
| **Text-to-Speech** | Piper (offline) |
| **Speaker Verification** | Resemblyzer |
| **Vision** | Local vision models |
| **Memory** | ChromaDB (vector store) |
| **Browser Automation** | Playwright |
| **UI** | Python (arc reactor animation) |
| **Calendar** | iCal parsing (read-only) |

---

## 🔐 Execution boundaries

- Generated Python scripts require explicit approval, but they still run with the current Windows account's permissions. The scratch folder and timeout are guardrails, **not** an operating-system sandbox.
- Plugins are checked for import-time executable statements before loading, but plugin functions still run inside Jarvis. Only use plugin code you have reviewed.
- Screen and phone automation ask for confirmation before detected risky actions and before continuing after text entry. Review each action before approving it.

## ⚠️ Disclaimer

> This is a **personal project**. WhatsApp/Instagram features use browser automation on your own accounts. Platforms may restrict automated access. Your voice profile, memories, and login sessions stay on your machine and are **not** part of this repo.

---

## 🗺️ Roadmap

- [ ] Raspberry Pi port (home server mode)
- [ ] Advanced screen reading (OCR + context)
- [ ] Home Assistant integration
- [ ] Multi-language support
- [ ] Mobile companion app

---

## 🤝 Contributing

This is a personal learning project, but suggestions are welcome! Feel free to:

- Open an issue for bugs or ideas
- Fork and experiment
- Share your own Jarvis builds

---

## 📜 License

MIT License — see [LICENSE](LICENSE)

---

## 👤 Author

**Shreyas**

- GitHub: [@godofentropy-dev](https://github.com/godofentropy-dev)

---

> *"Sometimes you gotta run before you can walk."* — Tony Stark
