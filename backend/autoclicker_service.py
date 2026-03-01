#!/usr/bin/env python3
"""
Antigravity Autoclicker — Headless Backend Service v2
======================================================
- Multi-provider LLM (DeepSeek, Kimi, Ollama)
- Upgraded Agent Brain with state machine
- Workspace scanning + deep chat understanding
- WebSocket for real-time updates
- Live scan preview streaming
- Backup management
- .env for API keys

HTTP API on port 9876, WebSocket on port 9877.
"""

import ctypes
import ctypes.wintypes as wintypes
import os
import sys

# Force UTF-8 output encoding
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import json
import time
import io
import threading
import logging
import queue
import hashlib
import subprocess
import urllib.request
import urllib.error
import shutil
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional, Tuple, List, Dict, Any
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import glob

# ── File Change Watcher ───────────────────────────────────────────────
class FileWatcher:
    """Track modification times of source files to detect changes since startup."""
    def __init__(self, project_dir: str):
        self.project_dir = project_dir
        self.watched_patterns = [
            os.path.join(project_dir, 'core', '*.py'),
            os.path.join(project_dir, 'backend', '*.py'),
            os.path.join(project_dir, 'src', '*.tsx'),
            os.path.join(project_dir, 'src', '*.css'),
        ]
        self.startup_mtimes: Dict[str, float] = {}
        self._snapshot()
    
    def _snapshot(self):
        """Record current mtimes as the baseline."""
        for pattern in self.watched_patterns:
            for path in glob.glob(pattern):
                try:
                    self.startup_mtimes[path] = os.path.getmtime(path)
                except OSError:
                    pass
    
    def get_changed_files(self) -> list:
        """Return list of files that changed since startup, plus GitHub updates."""
        changed = []
        for path, old_mtime in self.startup_mtimes.items():
            try:
                current_mtime = os.path.getmtime(path)
                if current_mtime > old_mtime:
                    changed.append(os.path.basename(path))
            except OSError:
                pass
        # Also check for new files
        for pattern in self.watched_patterns:
            for path in glob.glob(pattern):
                if path not in self.startup_mtimes:
                    changed.append(os.path.basename(path) + ' (new)')
                    
        # Check GitHub for updates
        try:
            subprocess.run(["git", "fetch", "origin", "main"], cwd=self.project_dir, capture_output=True, timeout=3)
            res = subprocess.run(["git", "rev-list", "HEAD...origin/main", "--count"], cwd=self.project_dir, capture_output=True, text=True, timeout=2)
            if res.stdout and int(res.stdout.strip() or "0") > 0:
                if "GitHub Update Available" not in changed:
                    changed.insert(0, "GitHub Update Available")
        except Exception as e:
            pass
            
        return changed

# ── DPI Awareness ─────────────────────────────────────────────────────
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ── Core dependencies (no Tkinter) ────────────────────────────────────
import pyautogui
import numpy as np
import cv2
from PIL import ImageGrab, Image
import win32gui
import win32con
import win32api
import win32process

# Optional: clipboard
try:
    import win32clipboard
    CLIPBOARD_AVAILABLE = True
except ImportError:
    CLIPBOARD_AVAILABLE = False

# Optional: OCR
try:
    import pytesseract
    _tesseract_bin = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
    if not os.path.exists(_tesseract_bin):
        _tesseract_bin = os.path.expanduser(r'~\AppData\Local\Tesseract-OCR\tesseract.exe')
    if not os.path.exists(_tesseract_bin):
        _fallback = shutil.which("tesseract")
        if _fallback:
            _tesseract_bin = _fallback
    if os.path.exists(_tesseract_bin):
        pytesseract.pytesseract.tesseract_cmd = _tesseract_bin
        OCR_AVAILABLE = True
    else:
        OCR_AVAILABLE = False
except ImportError:
    OCR_AVAILABLE = False

# ══════════════════════════════════════════════════════════════════════
# Import core logic from antigravity_clicker.py — WITHOUT Tkinter
# ══════════════════════════════════════════════════════════════════════

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)

# Add project root to sys.path for backend module imports
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

_MAIN_SCRIPT = os.path.join(_PROJECT_DIR, "core", "antigravity_clicker.py")

with open(_MAIN_SCRIPT, "r", encoding="utf-8") as f:
    _source_lines = f.readlines()

# Dynamic extraction — find markers instead of hardcoding line numbers
# This is robust to future edits that shift line numbers
_debug_overlay_start = None
_scan_engine_start = None
_gui_start = None

for _i, _line in enumerate(_source_lines):
    _stripped = _line.strip()
    if _stripped == 'class DebugOverlay:':
        _debug_overlay_start = _i
    elif _stripped == 'class ScanEngine:':
        _scan_engine_start = _i
    elif _stripped == 'class AntigravityAutoclickerApp:':
        _gui_start = _i

# Segment 1: everything from first IDE profile up to DebugOverlay
# Segment 2: ScanEngine class up to GUI class
_seg1_start = 118  # After imports/globals, starts at IDE profile definitions
_seg1_end = (_debug_overlay_start - 2) if _debug_overlay_start else 1548
_seg2_start = (_scan_engine_start - 4) if _scan_engine_start else 1617  # Include comment header
_seg2_end = (_gui_start - 1) if _gui_start else len(_source_lines)

_core_source = "".join(_source_lines[_seg1_start:_seg1_end]) + "\n" + "".join(_source_lines[_seg2_start:_seg2_end])

# Stub out GUI-only globals
TOAST_AVAILABLE = False
_toaster = None
TRAY_AVAILABLE = False

CONFIG_FILE = os.path.join(_PROJECT_DIR, "core", "config.json")

exec(compile(_core_source, _MAIN_SCRIPT, "exec"), globals())

# ══════════════════════════════════════════════════════════════════════
# Import upgraded modules
# ══════════════════════════════════════════════════════════════════════

from backend.llm_client import LLMClient, PROVIDERS
from backend.workspace_scanner import WorkspaceScanner
from backend.chat_reader import ChatReader
from backend.agent_brain import UpgradedAgentBrain, AGENT_MODES

# ══════════════════════════════════════════════════════════════════════
# LOGGING & STATE
# ══════════════════════════════════════════════════════════════════════

log_file = os.path.join(_PROJECT_DIR, "core", "autoclicker.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        RotatingFileHandler(log_file, maxBytes=500 * 1024, backupCount=2, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

# Thread-safe buffers
_log_buffer: List[Dict[str, str]] = []
_log_lock = threading.Lock()
MAX_LOG_ENTRIES = 500

_chat_buffer: List[Dict[str, str]] = []
_chat_lock = threading.Lock()

# WebSocket message queue
_ws_queue: queue.Queue = queue.Queue(maxsize=1000)

# Event tracking for notifications
_events: List[Dict] = []
_events_lock = threading.Lock()


def _log(msg: str, tag: str = "info"):
    logging.info(msg)
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "msg": msg,
        "tag": tag,
    }
    with _log_lock:
        _log_buffer.append(entry)
        if len(_log_buffer) > MAX_LOG_ENTRIES:
            _log_buffer.pop(0)
    # Push to WebSocket
    _ws_push("log", entry)


def _chat(role: str, msg: str):
    entry = {
        "role": role,
        "msg": msg,
        "time": datetime.now().strftime("%H:%M:%S"),
    }
    with _chat_lock:
        _chat_buffer.append(entry)
    _ws_push("chat", entry)


def _event(event_type: str, data: dict = None):
    """Record an event for notification system."""
    entry = {
        "type": event_type,
        "data": data or {},
        "time": datetime.now().strftime("%H:%M:%S"),
        "timestamp": time.time(),
    }
    with _events_lock:
        _events.append(entry)
        if len(_events) > 100:
            _events.pop(0)
    _ws_push("event", entry)


def _ws_push(msg_type: str, data: dict):
    """Push a message to the WebSocket queue."""
    try:
        _ws_queue.put_nowait({"type": msg_type, **data})
    except queue.Full:
        pass


# ══════════════════════════════════════════════════════════════════════
# INITIALIZE CORE COMPONENTS
# ══════════════════════════════════════════════════════════════════════

_settings = load_settings()

_scan_engine = ScanEngine(log_callback=_log)
_scan_engine.settings = _settings

# ChatController for agent typing
_chat_controller = ChatController()

# Unified LLM Client
_llm_client = LLMClient(
    provider=_settings.get("llm_provider", "ollama"),
    model=_settings.get("agent_model", "llama3.2:latest"),
)

# Upgraded Agent Brain
_agent = UpgradedAgentBrain(
    llm_client=_llm_client,
    scan_engine=_scan_engine,
    log_callback=_log,
    chat_callback=_chat,
)

# Workspace Scanner
_workspace_scanner = WorkspaceScanner()

# Chat Reader (for live preview)
_chat_reader = ChatReader()

# Smart pause state
_smart_pause_enabled = _settings.get("smart_pause_enabled", True)

# Kill switch state
_kill_switch_active = False

# Focus-pause: auto-pause scanner when Antigravity window is focused
_focus_paused = False
_was_running_before_focus = False
_manual_pause_timestamp = 0.0  # Track when user manually pauses/resumes
_PAUSE_STATE_CHANGE_DELAY = 1.0  # Seconds to ignore focus events after manual pause

_log("Backend service v2 initialized", "system")
_log(f"OCR available: {OCR_AVAILABLE}", "system")
_log(f"Clipboard available: {CLIPBOARD_AVAILABLE}", "system")
_log(f"LLM provider: {_llm_client.provider}/{_llm_client.model}", "system")

# Check LLM availability
try:
    if _llm_client.is_available():
        models = _llm_client.list_models()
        _log(f"LLM connected — {len(models)} models available", "system")
    else:
        _log(f"LLM provider '{_llm_client.provider}' not available", "warn")
except Exception:
    _log("Could not check LLM status", "warn")


# ══════════════════════════════════════════════════════════════════════
# LIVE SCAN PREVIEW
# ══════════════════════════════════════════════════════════════════════

_preview_frame: Optional[bytes] = None
_preview_lock = threading.Lock()


def _update_preview():
    """Background thread to capture scan preview frames."""
    global _preview_frame
    while True:
        try:
            if _scan_engine.running and not _kill_switch_active:
                windows = _scan_engine._find_windows()
                if windows:
                    _, _, rect = windows[0]
                    scan_region = _scan_engine._get_scan_region(rect)
                    screenshot = ImageGrab.grab(bbox=scan_region)
                    frame = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

                    # Draw detection bounding boxes
                    profile = _scan_engine._get_profile()
                    detections = detect_buttons_color(frame, profile, _settings)
                    for det in detections:
                        color = (0, 255, 0) if det.btn_type == "run" else (255, 165, 0)
                        cv2.rectangle(frame, (det.x, det.y),
                                      (det.x + det.w, det.y + det.h), color, 2)
                        cv2.putText(frame, f"{det.btn_type} {det.confidence:.0%}",
                                    (det.x, det.y - 5), cv2.FONT_HERSHEY_SIMPLEX,
                                    0.4, color, 1)

                    # Encode as JPEG
                    _, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 60])
                    with _preview_lock:
                        _preview_frame = buf.tobytes()
        except Exception:
            pass
        time.sleep(0.5)  # ~2 FPS


# Start preview thread
_preview_thread = threading.Thread(target=_update_preview, daemon=True, name="PreviewThread")
_preview_thread.start()


# ══════════════════════════════════════════════════════════════════════
# KILL SWITCH
# ══════════════════════════════════════════════════════════════════════

def activate_kill_switch():
    """Stop ALL operations immediately."""
    global _kill_switch_active
    _kill_switch_active = True
    _log("🛑 KILL SWITCH ACTIVATED — all operations stopped", "system")
    _event("kill_switch", {"active": True})

    if _scan_engine.running:
        _scan_engine.stop()
    if _agent.running:
        _agent.stop()


def deactivate_kill_switch():
    """Re-enable operations after kill switch."""
    global _kill_switch_active
    _kill_switch_active = False
    _log("Kill switch deactivated", "system")
    _event("kill_switch", {"active": False})


# ══════════════════════════════════════════════════════════════════════
# WebSocket Server (port 9877)
# ══════════════════════════════════════════════════════════════════════

_ws_clients: List = []
_ws_clients_lock = threading.Lock()


def _start_websocket_server():
    """Run a simple WebSocket server for real-time updates."""
    try:
        import websockets
        import websockets.sync.server

        def ws_handler(websocket):
            with _ws_clients_lock:
                _ws_clients.append(websocket)
            _log("WebSocket client connected", "system")
            try:
                for message in websocket:
                    # Handle incoming messages from frontend
                    try:
                        data = json.loads(message)
                        if data.get("type") == "ping":
                            websocket.send(json.dumps({"type": "pong"}))
                    except Exception:
                        pass
            except Exception:
                pass
            finally:
                with _ws_clients_lock:
                    if websocket in _ws_clients:
                        _ws_clients.remove(websocket)

        server = websockets.sync.server.serve(ws_handler, "127.0.0.1", 9877)
        _log("WebSocket server listening on ws://127.0.0.1:9877", "system")
        server.serve_forever()
    except ImportError:
        _log("websockets package not installed — using HTTP polling fallback", "warn")
    except Exception as e:
        _log(f"WebSocket server error: {e}", "warn")


def _ws_broadcaster():
    """Background thread that broadcasts queued messages to all WS clients."""
    while True:
        try:
            msg = _ws_queue.get(timeout=1.0)
            payload = json.dumps(msg)
            with _ws_clients_lock:
                dead = []
                for ws in _ws_clients:
                    try:
                        ws.send(payload)
                    except Exception:
                        dead.append(ws)
                for ws in dead:
                    _ws_clients.remove(ws)
        except queue.Empty:
            pass
        except Exception:
            pass


# Start WebSocket server and broadcaster in background
threading.Thread(target=_start_websocket_server, daemon=True, name="WSServer").start()
threading.Thread(target=_ws_broadcaster, daemon=True, name="WSBroadcaster").start()


# ══════════════════════════════════════════════════════════════════════
# HTTP API SERVER
# ══════════════════════════════════════════════════════════════════════

class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class APIHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data: bytes, content_type: str, status: int = 200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length))
        except Exception:
            return {}

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = self.path.split("?")[0]

        # ── Health ─────────────────────────────────────────────────
        if path == "/api/health":
            self._send_json({"status": "ok", "version": "2.0"})

        # ── Scanner ────────────────────────────────────────────────
        elif path == "/api/scanner/status":
            last_clicks = getattr(_scan_engine, "last_click_times", {})
            last_click_ago = None
            if last_clicks:
                most_recent = max(last_clicks.values())
                last_click_ago = round(time.time() - most_recent, 1)
            self._send_json({
                "running": _scan_engine.running,
                "paused": _scan_engine.paused,
                "clicks_total": getattr(_scan_engine, "clicks_total", 0),
                "detected_profile": _settings.get("profile", "antigravity"),
                "detected_window": getattr(_scan_engine, "detected_window_title", None),
                "scan_region": getattr(_scan_engine, "last_scan_region", None),
                "last_click_types": {k: round(time.time() - v, 1) for k, v in last_clicks.items()},
                "last_click_ago": last_click_ago,
                "kill_switch": _kill_switch_active,
                "smart_pause": _smart_pause_enabled,
                "focus_paused": _focus_paused,
            })

        elif path == "/api/scanner/preview":
            with _preview_lock:
                if _preview_frame:
                    self._send_bytes(_preview_frame, "image/jpeg")
                else:
                    # Send 1x1 transparent pixel
                    self._send_bytes(b'\xff\xd8\xff\xe0\x00\x10JFIF', "image/jpeg", 204)

        # ── Agent ──────────────────────────────────────────────────
        elif path == "/api/agent/status":
            self._send_json(_agent.get_status())

        elif path == "/api/agent/messages":
            with _chat_lock:
                self._send_json({"messages": list(_chat_buffer)})

        elif path == "/api/agent/modes":
            modes = {}
            for key, mode in AGENT_MODES.items():
                modes[key] = {
                    "name": mode["name"],
                    "description": mode["description"],
                }
            self._send_json(modes)

        # ── LLM ────────────────────────────────────────────────────
        elif path == "/api/llm/status":
            self._send_json(_llm_client.get_status())

        elif path == "/api/llm/providers":
            providers = {}
            for key, prov in PROVIDERS.items():
                providers[key] = {
                    "name": prov["name"],
                    "needs_key": prov["needs_key"],
                    "default_model": prov["default_model"],
                    "models": prov.get("available_models", []),
                }
            self._send_json(providers)

        elif path == "/api/llm/models":
            self._send_json({"models": _llm_client.list_models()})

        # ── Workspace ──────────────────────────────────────────────
        elif path == "/api/workspace/status":
            self._send_json({
                "root": _agent.workspace_root,
                "scanned": _agent.workspace_context is not None,
            })

        # ── Settings ───────────────────────────────────────────────
        elif path == "/api/settings":
            # Include LLM settings
            settings_out = dict(_settings)
            settings_out["llm_provider"] = _llm_client.provider
            settings_out["llm_model"] = _llm_client.model
            settings_out["smart_pause_enabled"] = _smart_pause_enabled
            self._send_json(settings_out)

        elif path == "/api/profiles":
            profiles = {}
            for key, prof in PROFILES.items():
                profiles[key] = {
                    "name": prof["name"],
                    "window_hints": prof.get("window_hints", []),
                }
            self._send_json(profiles)

        # ── Logs & Events ──────────────────────────────────────────
        elif path == "/api/logs":
            with _log_lock:
                self._send_json({"logs": list(_log_buffer)})

        elif path == "/api/events":
            with _events_lock:
                self._send_json({"events": list(_events)})

        # ── System ─────────────────────────────────────────────────
        elif path == "/api/system/info":
            self._send_json({
                "ocr_available": OCR_AVAILABLE,
                "clipboard_available": CLIPBOARD_AVAILABLE,
                "python_version": sys.version,
                "pid": os.getpid(),
                "kill_switch": _kill_switch_active,
                "websocket_port": 9877,
            })

        elif path == "/api/system/file-changes":
            changed = _file_watcher.get_changed_files()
            self._send_json({"changed": changed, "needs_restart": len(changed) > 0})

        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        global _smart_pause_enabled, _focus_paused, _was_running_before_focus, _manual_pause_timestamp
        path = self.path.split("?")[0]
        body = self._read_body()

        # ── Scanner ────────────────────────────────────────────────
        if path == "/api/scanner/start":
            if _kill_switch_active:
                self._send_json({"ok": False, "error": "Kill switch active"})
                return
            if not _scan_engine.running:
                _scan_engine.settings = _settings
                _scan_engine.start()
                _log("Scanner started", "action")
                _event("scanner_start", {})
                # Clear focus-pause state when starting fresh
                _focus_paused = False
                _was_running_before_focus = False
                _manual_pause_timestamp = time.time()
            self._send_json({"ok": True})

        elif path == "/api/scanner/stop":
            if _scan_engine.running:
                _scan_engine.stop()
                _log("Scanner stopped", "action")
                _event("scanner_stop", {})
            # Clear focus-pause state when stopped
            _focus_paused = False
            _was_running_before_focus = False
            self._send_json({"ok": True})

        elif path == "/api/scanner/pause":
            _scan_engine.toggle_pause()
            _manual_pause_timestamp = time.time()
            state = "paused" if _scan_engine.paused else "resumed"
            _log(f"Scanner {state}", "action")
            
            # If user manually resumes while focus-paused, clear the focus-pause state
            # to prevent it from immediately re-pausing or incorrectly resuming later
            if not _scan_engine.paused:
                if _focus_paused:
                    _log("Manual resume cleared focus-pause state", "info")
                _focus_paused = False
                _was_running_before_focus = False
            
            self._send_json({"ok": True, "paused": _scan_engine.paused})

        elif path == "/api/scanner/focuspause":
            # Auto-pause when Antigravity window is focused
            focused = body.get("focused", False)
            now = time.time()
            
            # Skip if user just manually paused/resumed (avoid state fighting)
            if now - _manual_pause_timestamp < _PAUSE_STATE_CHANGE_DELAY:
                self._send_json({"ok": True, "focus_paused": _focus_paused, "skipped": True})
                return
            
            if focused:
                # Window gained focus — pause scanner temporarily
                if _scan_engine.running and not _scan_engine.paused:
                    _was_running_before_focus = True
                    _scan_engine.paused = True
                    _focus_paused = True
                    _log("Scanner paused (window focused)", "action")
                else:
                    _was_running_before_focus = False
                    _focus_paused = False
            else:
                # Window lost focus — resume if we auto-paused
                if _focus_paused and _was_running_before_focus:
                    if _scan_engine.running:
                        _scan_engine.paused = False
                        _log("Scanner resumed (window unfocused)", "action")
                    _focus_paused = False
                    _was_running_before_focus = False
            self._send_json({"ok": True, "focus_paused": _focus_paused})

        # ── Kill Switch ────────────────────────────────────────────
        elif path == "/api/killswitch/activate":
            activate_kill_switch()
            self._send_json({"ok": True, "active": True})

        elif path == "/api/killswitch/deactivate":
            deactivate_kill_switch()
            self._send_json({"ok": True, "active": False})

        # ── Agent ──────────────────────────────────────────────────
        elif path == "/api/agent/start":
            if _kill_switch_active:
                self._send_json({"ok": False, "error": "Kill switch active"})
                return

            task = body.get("task", "")
            mode = body.get("mode", "build")
            provider = body.get("provider", _llm_client.provider)
            model = body.get("model", _llm_client.model)

            if task:
                # Switch LLM if needed
                if provider != _llm_client.provider or model != _llm_client.model:
                    _llm_client.switch_provider(provider, model)

                _agent.mode = mode
                _agent.settings = _settings
                _agent.smart_pause_enabled = _smart_pause_enabled
                _agent.set_task(task)
                _agent.start()
                _log(f"Agent started: {task[:60]}", "action")
                _chat("system", f"Agent started in {mode} mode with {provider}/{model}")
                _event("agent_start", {"task": task, "mode": mode})
            self._send_json({"ok": True})

        elif path == "/api/agent/stop":
            _agent.stop()
            _log("Agent stopped", "action")
            _chat("system", "Agent stopped by user")
            _event("agent_stop", {})
            self._send_json({"ok": True})

        elif path == "/api/agent/chat":
            msg = body.get("message", "")
            if msg:
                _chat("user", msg)
                if _agent.running:
                    _agent.send_user_message(msg)
                else:
                    def _reply():
                        try:
                            reply = _agent.chat_with_llm(msg)
                            if reply:
                                _chat("agent", reply)
                        except Exception as e:
                            _chat("system", f"Error: {e}")
                    threading.Thread(target=_reply, daemon=True).start()
            self._send_json({"ok": True})

        # ── LLM ────────────────────────────────────────────────────
        elif path == "/api/llm/switch":
            provider = body.get("provider", "ollama")
            model = body.get("model")
            _llm_client.switch_provider(provider, model)
            _settings["llm_provider"] = provider
            _settings["agent_model"] = _llm_client.model
            save_settings(_settings)
            _log(f"Switched LLM to {provider}/{_llm_client.model}", "action")
            self._send_json({"ok": True, "status": _llm_client.get_status()})

        # ── Workspace ──────────────────────────────────────────────
        elif path == "/api/workspace/scan":
            workspace_path = body.get("path", "")
            if not workspace_path:
                # Try to detect from IDE window
                windows = _scan_engine._find_windows()
                if windows:
                    _, title, _ = windows[0]
                    detected = _workspace_scanner.detect_workspace_from_title(title)
                    workspace_path = detected or ""

            if workspace_path and os.path.isdir(workspace_path):
                ctx = _workspace_scanner.scan(workspace_path)
                _agent.workspace_root = workspace_path
                _agent.workspace_context = ctx.to_prompt()
                _log(f"Workspace scanned: {workspace_path}", "action")
                self._send_json({"ok": True, **ctx.to_dict()})
            else:
                self._send_json({"ok": False, "error": "Invalid workspace path"})

        elif path == "/api/workspace/changes":
            root = body.get("path", _agent.workspace_root or "")
            if root:
                changes = _workspace_scanner.get_recent_changes(root)
                self._send_json({"ok": True, "changes": changes})
            else:
                self._send_json({"ok": False, "error": "No workspace set"})

        elif path == "/api/workspace/backup":
            root = body.get("path", _agent.workspace_root or "")
            if root:
                backup_name = _workspace_scanner.create_backup(root)
                self._send_json({"ok": True, "backup": backup_name})
            else:
                self._send_json({"ok": False, "error": "No workspace set"})

        # ── Settings ───────────────────────────────────────────────
        elif path == "/api/settings":
            for key, val in body.items():
                _settings[key] = val
            _smart_pause_enabled = _settings.get("smart_pause_enabled", True)
            save_settings(_settings)
            _scan_engine.settings = _settings
            _log("Settings updated", "action")
            self._send_json({"ok": True})

        elif path == "/api/logs/clear":
            with _log_lock:
                _log_buffer.clear()
            self._send_json({"ok": True})

        # ── Smart Pause ────────────────────────────────────────────
        elif path == "/api/smartpause/toggle":
            _smart_pause_enabled = not _smart_pause_enabled
            _settings["smart_pause_enabled"] = _smart_pause_enabled
            save_settings(_settings)
            _log(f"Smart pause {'enabled' if _smart_pause_enabled else 'disabled'}", "action")
            self._send_json({"ok": True, "enabled": _smart_pause_enabled})

        elif path == "/api/system/restart":
            _log("Restarting backend...", "system")
            do_update = body.get("update", False)
            self._send_json({"ok": True, "message": "Updating and restarting..." if do_update else "Restarting..."})
            # Stop everything cleanly
            if _scan_engine.running:
                _scan_engine.stop()
            if _agent.running:
                _agent.stop()
            # Restart the process
            def _do_restart():
                time.sleep(0.5)  # Let response send
                if do_update:
                    try:
                        subprocess.run(["git", "pull", "origin", "main"], cwd=_PROJECT_DIR, check=True)
                        _log("Git pull successful", "system")
                    except Exception as e:
                        _log(f"Git pull failed: {e}", "error")
                os.execv(sys.executable, [sys.executable] + sys.argv)
            threading.Thread(target=_do_restart, daemon=True).start()

        else:
            self._send_json({"error": "Not found"}, 404)


# ══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════

def main():
    port = 9876
    server = ThreadingHTTPServer(("127.0.0.1", port), APIHandler)
    _log(f"Backend API v2 listening on http://127.0.0.1:{port}", "system")
    _log(f"WebSocket server on ws://127.0.0.1:9877", "system")
    print(f"\n  ⚡ Antigravity Backend v2 running on port {port}\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _log("Server shutting down", "system")
        if _scan_engine.running:
            _scan_engine.stop()
        if _agent.running:
            _agent.stop()
        server.server_close()


# Initialize file watcher
_file_watcher = FileWatcher(_PROJECT_DIR)

if __name__ == "__main__":
    main()
