# ⚡ Antigravity Auto-Clicker

**One program. One GUI. Clicks Run, Accept All, and Confirm buttons automatically in your AI coding IDE.**

## Quick Start

```bash
pip install -r requirements.txt
python core/antigravity_clicker.py
```

Or use the desktop app:

```bash
npm install
npm run tauri dev
```

## How It Works

1. **Select your profile** — Antigravity (Gemini), VS Code, GitHub Copilot, Claude Code, Kimi Code, Cursor, or Windsurf
2. **Click START** — the scanner finds your IDE window automatically
3. **Buttons are detected** via HSV color matching + optional OCR text recognition
4. **Clicks execute** using Windows SendInput API (works with Electron apps like VS Code)
5. **Mouse restores** to its original position after each click

## Features

### 🖱️ Auto-Clicker
- 🎯 **Accurate detection** — HSV color profiles calibrated per IDE, strict geometry filters, morphological noise reduction
- 🖱️ **Reliable clicking** — Windows SendInput API (not PostMessage, which fails on Electron)
- 🔍 **OCR fallback** — Tesseract text detection when color matching alone isn't enough
- 🛡️ **Safe** — Failsafe enabled (move mouse to corner to abort), cooldown between clicks, DPI-aware
- 📜 **Smart scrolling** — Smooth multi-step SendInput scrolling with direction alternation to find off-screen buttons
- ⌨️ **Typing guard** — Pauses auto-clicking when you're actively typing
- ⏸️ **Focus cooldown** — 5-second click pause when you focus the autoclicker window, so it doesn't immediately click away
- 🖥️ **Multi-monitor** — Correct coordinate mapping on multi-monitor setups (virtual screen aware)

### 🤖 AI Agent (Autonomous Coder)
- 🧠 **Local LLM supervisor** — Uses Ollama to run a local AI that supervises your coding AI
- 💬 **Multi-turn memory** — Uses `/api/chat` endpoint for proper conversation history
- 🔄 **Auto-pilot modes** — Design, Build, Test, Review, Refactor, or Full Auto
- 🔧 **Self-healing** — Stall detection (5min timeout), loop detection, exponential backoff
- 📥 **Auto-setup** — Auto-starts Ollama server, auto-pulls models if needed
- 🛑 **Safety limits** — Max 50 steps per session, max retries on loops

### 🎨 GUI
- 🎨 **Dark theme** — Single Tkinter window, tabbed interface
- 📊 **Debug overlay** — Real-time scan visualization with bounding boxes
- ⌨️ **Hotkey** — Ctrl+Shift+P to pause/resume
- 🔔 **Notifications** — Optional Windows toast notifications
- 📦 **System tray** — Minimize to tray support

## Configuration

All settings are saved to `config.json` and editable from the GUI:

| Setting | Default | Description |
|---------|---------|-------------|
| Profile | antigravity | Which IDE/AI assistant to detect |
| Interval | 0.5s | How often to scan |
| Confidence | 55% | Minimum detection confidence |
| Detect Run | ✓ | Click Run/Continue buttons |
| Detect Accept | ✓ | Click Accept All buttons |
| Detect Confirm | ✓ | Click Confirm/Session buttons |
| OCR Assist | ✓ | Use Tesseract for text detection |
| Auto-Detect IDE | ✓ | Auto-switch profile based on window title |

## Supported IDEs

| Profile | IDE | Button Colors |
|---------|-----|---------------|
| Antigravity (Gemini) | VS Code + Gemini Extension | Blue (#0078D4) |
| GitHub Copilot | VS Code + Copilot Extension | Blue + Teal/Green |
| Claude Code | VS Code + Claude Extension | Orange + Purple-Blue |
| Kimi Code | VS Code + Kimi Extension | Purple + Teal |
| Cursor | Cursor IDE | Blue + Teal |
| Windsurf | Windsurf (Codeium) | Cyan + Purple |

> **Works with any VS Code-based editor** — All profiles that target VS Code extensions will match windows
> titled "Visual Studio Code" or "VS Code". The auto-detect feature switches profiles automatically
> based on which extension/tool is active.

## AI Agent Modes

| Mode | Description |
|------|-------------|
| 🏗️ Design & Plan | Architecture, specs, file structure. No implementation. |
| 🔨 Build & Implement | Write code, create files, implement features step by step. |
| 🧪 Test & Debug | Run tests, find bugs, fix errors. Focus on quality. |
| 🔍 Review & Audit | Review code for bugs, security issues, and improvements. |
| 🧹 Refactor & Polish | Clean up code, optimize, improve naming, add docs. |
| 🚀 Full Auto | Plan → Build → Test → Fix → Polish. Complete development cycle. |

## File Structure

```
core/
  antigravity_clicker.py  ← Main Python autoclicker + AI agent
  config.json             ← Settings (auto-generated, gitignored)
backend/
  autoclicker_service.py  ← FastAPI backend for desktop app
  agent_brain.py          ← AI agent logic
  llm_client.py           ← LLM API client
  chat_reader.py          ← Chat window reader
  workspace_scanner.py    ← Workspace file scanner
src/
  App.tsx                 ← React (Tauri) desktop frontend
  index.css               ← Styles
src-tauri/                ← Tauri (Rust) desktop shell
requirements.txt          ← Python dependencies
package.json              ← Node dependencies
launch.bat                ← Quick launcher
```

## Requirements

- **Python 3.8+** with tkinter
- **Windows 10/11** (uses Win32 API for mouse control and window detection)
- **Optional**: [Tesseract OCR](https://github.com/tesseract-ocr/tesseract) for text-based button detection
- **Optional**: [Ollama](https://ollama.com) for the AI Agent autonomous coder feature

## License

MIT — see [LICENSE](LICENSE) for details.
