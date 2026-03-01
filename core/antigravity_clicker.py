#!/usr/bin/env python3
"""
Antigravity Autoclicker v2.0
=======================
Autonomous coding assistant with auto-click engine + AI agent brain.
Detects IDE windows running Antigravity / Gemini (or other AI coding
assistants), finds Run/Accept/Confirm buttons via color + OCR, and clicks them
automatically. Includes Ollama-powered AI supervisor for fully autonomous coding.

Key design decisions:
  • DPI-awareness set FIRST, before any GUI or screenshot code runs.
  • SendInput API for reliable clicking (Electron requires it).
  • Thread-safe logging to Tkinter ScrolledText via queue.
  • Single config.json, single entry point, single file.
"""

import ctypes
import ctypes.wintypes as wintypes
import os
import sys
import json
import time
import threading
import logging
import queue
import hashlib
import webbrowser
import subprocess
import urllib.request
import urllib.error
import shutil
from datetime import datetime
from logging.handlers import RotatingFileHandler
from typing import Optional, Tuple, List, Dict, Any

# —— DPI Awareness — MUST be first, before any GUI/screenshot ——————————
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-monitor DPI aware
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ── Hide console window — only show the Tkinter GUI ──────────────────────
try:
    _console_hwnd = ctypes.windll.kernel32.GetConsoleWindow()
    if _console_hwnd:
        ctypes.windll.user32.ShowWindow(_console_hwnd, 0)  # SW_HIDE = 0
except Exception:
    pass

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, scrolledtext, messagebox
import pyautogui
import numpy as np
import cv2
from PIL import ImageGrab, Image, ImageTk
import win32gui
import win32con
import win32api
import win32process

# Optional: clipboard for reliable text paste
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

# Optional: toast notifications
try:
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        from win10toast import ToastNotifier
    _toaster = ToastNotifier()
    TOAST_AVAILABLE = True
except Exception:
    TOAST_AVAILABLE = False

# Optional: system tray
try:
    import pystray
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False

# —— PyAutoGUI config ———————————————————————————————————————————————————
pyautogui.FAILSAFE = True  # Safety: move mouse to corner to abort
pyautogui.PAUSE = 0.02     # Tiny pause between pyautogui calls
pyautogui.MINIMUM_DURATION = 0
pyautogui.MINIMUM_SLEEP = 0

# ——————————————————————————————————————————————————————————————————————
# CONFIGURATION
# ——————————————————————————————————————————————————————————————————————
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# IDE / AI assistant profiles — HSV ranges calibrated to actual button colors
PROFILES: Dict[str, dict] = {
    "antigravity": {
        "name": "Antigravity (Google Gemini)",
        "window_hints": ["antigravity", "gemini", "agent manager"],
        "buttons": {
            "run": {
                "hsv_min": [90, 60, 60],  "hsv_max": [135, 255, 255],
                "desc": "Blue (#0078D4-style)",
                "min_w": 35, "max_w": 200, "min_h": 15, "max_h": 70,
                "min_ratio": 1.2, "max_ratio": 6.0
            },
            "accept": {
                "hsv_min": [90, 60, 60],  "hsv_max": [135, 255, 255],
                "desc": "Blue (#0078D4-style)",
                "min_w": 60, "max_w": 800, "min_h": 15, "max_h": 90,
                "min_ratio": 1.5, "max_ratio": 35.0
            },
            "confirm": {
                "hsv_min": [90, 60, 60],  "hsv_max": [135, 255, 255],
                "desc": "Blue",
                "min_w": 35, "max_w": 800, "min_h": 15, "max_h": 90,
                "min_ratio": 1.2, "max_ratio": 35.0
            },
        },
        "ocr_keywords": {
            "run": ["run", "continue", "accept", "execute", "send"],
            "accept": ["accept all", "accept", "apply", "apply all", "yes", "confirm"],
            "confirm": ["yes", "confirm", "ok", "proceed", "allow", "allow this conversation"],
            "busy": ["thinking", "typing", "...", "analyzing", "generating"],
        },
    },
    "github_copilot": {
        "name": "GitHub Copilot",
        "window_hints": ["visual studio code", "vs code", "copilot"],
        "buttons": {
            "run": {
                "hsv_min": [100, 120, 100], "hsv_max": [125, 255, 255],
                "desc": "Copilot Blue"
            },
            "accept": {
                "hsv_min": [75, 80, 100],   "hsv_max": [105, 255, 230],
                "desc": "Copilot Teal/Green"
            },
        },
        "ocr_keywords": {
            "run": ["run", "continue", "generate", "send", "ask"],
            "accept": ["accept", "accept all", "apply", "tab", "commit", "yes"],
            "busy": ["copilot is", "generating", "thinking", "processing", "..."],
        },
    },
    "claude_code": {
        "name": "Claude Code",
        "window_hints": ["visual studio code", "vs code", "claude"],
        "buttons": {
            "run": {
                "hsv_min": [10, 100, 140],  "hsv_max": [30, 255, 255],
                "desc": "Claude Orange"
            },
            "accept": {
                "hsv_min": [130, 80, 100],  "hsv_max": [165, 255, 220],
                "desc": "Claude Purple-Blue"
            },
        },
        "ocr_keywords": {
            "run": ["run", "execute", "continue", "go", "send", "proceed"],
            "accept": ["accept", "accept all", "apply", "save", "yes", "confirm"],
            "busy": ["claude is", "thinking", "working", "processing", "...", "analyzing"],
        },
    },
    "kimi_code": {
        "name": "Kimi Code",
        "window_hints": ["visual studio code", "vs code", "kimi"],
        "buttons": {
            "run": {
                "hsv_min": [130, 100, 80],  "hsv_max": [170, 255, 255],
                "desc": "Kimi Purple"
            },
            "accept": {
                "hsv_min": [80, 80, 80],    "hsv_max": [110, 255, 220],
                "desc": "Kimi Teal"
            },
        },
        "ocr_keywords": {
            "run": ["run", "execute", "continue", "generate", "send", "go"],
            "accept": ["accept", "accept all", "apply changes", "apply", "commit", "apply all"],
            "busy": ["kimi is", "generating", "thinking", "processing", "...", "working"],
        },
    },
    "cursor": {
        "name": "Cursor IDE",
        "window_hints": ["cursor"],
        "buttons": {
            "run": {
                "hsv_min": [100, 80, 100],  "hsv_max": [125, 255, 255],
                "desc": "Cursor Blue"
            },
            "accept": {
                "hsv_min": [75, 80, 100],   "hsv_max": [105, 255, 220],
                "desc": "Cursor Teal"
            },
        },
        "ocr_keywords": {
            "run": ["run", "execute", "continue", "generate", "send"],
            "accept": ["accept", "accept all", "apply", "yes", "confirm", "apply diff"],
            "busy": ["cursor is", "generating", "thinking", "processing", "..."],
        },
    },
    "windsurf": {
        "name": "Windsurf (Codeium)",
        "window_hints": ["windsurf", "codeium"],
        "buttons": {
            "run": {
                "hsv_min": [85, 100, 100],  "hsv_max": [100, 255, 255],
                "desc": "Windsurf Cyan"
            },
            "accept": {
                "hsv_min": [125, 80, 100],  "hsv_max": [155, 255, 220],
                "desc": "Windsurf Purple",
                "max_w": 800,
                "max_ratio": 35.0
            },
        },
        "ocr_keywords": {
            "run": ["run", "execute", "continue", "generate", "send", "go"],
            "accept": ["accept", "accept all", "apply", "yes", "confirm", "apply changes", "allow", "allow this conversation"],
            "busy": ["windsurf is", "generating", "thinking", "processing", "...", "working"],
        },
    },
}

DEFAULT_SETTINGS = {
    "profile": "antigravity",
    "check_interval": 0.5,
    "confidence": 0.55,
    "pause_hotkey": "ctrl+shift+p",
    "detect_run": True,
    "detect_accept": True,
    "detect_confirm": True,
    "use_ocr": True,
    "cooldown_seconds": 2.0,
    "min_button_area": 600,
    "max_button_area": 120000,
    "min_aspect_ratio": 1.2,
    "max_aspect_ratio": 35.0,
    "min_button_width": 35,
    "min_button_height": 15,
    "scan_bottom_portion": 0.75,
    "input_box_clip_px": 100,
    "typing_cooldown_seconds": 5.0,
    "auto_detect_window": True,
    # v2.0 — Agent & UI settings
    "agent_mode": "build",
    "agent_model": "phi3:mini",
    "ollama_host": "localhost",
    "ollama_port": 11434,
    "max_retries": 3,
    "debug_overlay": False,
    "minimize_to_tray": False,
    "loop_detect_enabled": True,
    "retry_message": "retry",
}

AGENT_MODES: Dict[str, dict] = {
    "design": {
        "name": "\U0001f3d7\ufe0f Design & Plan",
        "description": "Architecture, specs, file structure. No implementation.",
        "auto_click": ["accept"],
        "system_prompt": (
            "You are an AI project supervisor in DESIGN mode. Your job is to ask the coding AI "
            "to plan, architect, and outline the project. Ask it to create specs, define the file "
            "structure, and plan the approach. Do NOT ask it to write implementation code yet. "
            "Give one clear instruction at a time. When the design is complete, say TASK_COMPLETE."
        ),
    },
    "build": {
        "name": "\U0001f528 Build & Implement",
        "description": "Write code, create files, implement features step by step.",
        "auto_click": ["run", "accept"],
        "system_prompt": (
            "You are an AI project supervisor in BUILD mode. Your job is to give the coding AI "
            "clear, specific implementation instructions one step at a time. Read its response. "
            "If it completed the task, move to the next logical step. If it errored, ask it to fix. "
            "Keep going until the feature is fully implemented. Say TASK_COMPLETE when done."
        ),
    },
    "test": {
        "name": "\U0001f9ea Test & Debug",
        "description": "Run tests, find bugs, fix errors. Focus on quality.",
        "auto_click": ["run", "accept", "confirm"],
        "system_prompt": (
            "You are an AI project supervisor in TEST mode. Your job is to ask the coding AI to "
            "write tests, run them, analyze failures, and fix bugs. Focus on code quality, edge "
            "cases, and robustness. When all tests pass and code is solid, say TASK_COMPLETE."
        ),
    },
    "review": {
        "name": "\U0001f50d Review & Audit",
        "description": "Review code for bugs, security issues, and improvements.",
        "auto_click": ["accept"],
        "system_prompt": (
            "You are an AI project supervisor in REVIEW mode. Ask the coding AI to review its "
            "own code for bugs, security vulnerabilities, performance issues, and code quality. "
            "Document findings and ask it to fix critical issues. Say TASK_COMPLETE when audit is done."
        ),
    },
    "refactor": {
        "name": "\U0001f9f9 Refactor & Polish",
        "description": "Clean up code, optimize, improve naming, add docs.",
        "auto_click": ["run", "accept"],
        "system_prompt": (
            "You are an AI project supervisor in REFACTOR mode. Ask the coding AI to clean up "
            "the codebase: improve naming, add docstrings, optimize performance, remove dead code, "
            "and ensure consistency. Do not change behavior. Say TASK_COMPLETE when polishing is done."
        ),
    },
    "full_auto": {
        "name": "\U0001f680 Full Auto",
        "description": "Plan \u2192 Build \u2192 Test \u2192 Fix \u2192 Polish. Complete the entire task.",
        "auto_click": ["run", "accept", "confirm"],
        "system_prompt": (
            "You are an AI project supervisor in FULL AUTO mode. You will guide the coding AI "
            "through the complete development cycle: 1) Plan the approach, 2) Implement step by step, "
            "3) Write and run tests, 4) Fix any issues, 5) Refactor and polish. Give one instruction "
            "at a time. Track which phase you're in. Say TASK_COMPLETE only when everything is done."
        ),
    },
}


def load_settings() -> dict:
    """Load settings from config file, merging with defaults."""
    settings = DEFAULT_SETTINGS.copy()
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
            # Only pull the keys we care about
            for key in DEFAULT_SETTINGS:
                if key in saved:
                    settings[key] = saved[key]
        except Exception:
            pass
    return settings


def save_settings(settings: dict):
    """Save current settings to config file."""
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        logging.error(f"Failed to save settings: {e}")


# ——————————————————————————————————————————————————————————————————————
# MOUSE CONTROL — SendInput for reliable clicking
# ——————————————————————————————————————————————————————————————————————

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
INPUT_MOUSE = 0


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("iu", _INPUT_UNION),
    ]


def _screen_to_absolute(x: int, y: int) -> Tuple[int, int]:
    """Convert screen pixels to 0-65535 absolute coordinates.
    
    Uses virtual screen dimensions (SM_CXVIRTUALSCREEN / SM_CYVIRTUALSCREEN)
    and virtual screen origin (SM_XVIRTUALSCREEN / SM_YVIRTUALSCREEN) so that
    coordinates are correct on multi-monitor setups where secondary monitors
    may have negative or offset positions.
    """
    # Virtual screen = bounding rectangle of ALL monitors
    virt_left = ctypes.windll.user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
    virt_top  = ctypes.windll.user32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
    virt_w    = ctypes.windll.user32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
    virt_h    = ctypes.windll.user32.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN
    # Map pixel position into the 0-65535 absolute range relative to virtual screen
    abs_x = int((x - virt_left) * 65535 / virt_w)
    abs_y = int((y - virt_top)  * 65535 / virt_h)
    return abs_x, abs_y


def sendinput_click(x: int, y: int, hold_ms: int = 50):
    """Click at (x, y) screen coordinates using Windows SendInput API.
    
    This is more reliable than pyautogui for Electron apps and
    doesn't get blocked like PostMessage WM_LBUTTON.
    """
    abs_x, abs_y = _screen_to_absolute(x, y)
    extra = ctypes.pointer(wintypes.ULONG(0))

    # Move
    inp_move = INPUT()
    inp_move.type = INPUT_MOUSE
    inp_move.iu.mi.dx = abs_x
    inp_move.iu.mi.dy = abs_y
    inp_move.iu.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
    inp_move.iu.mi.dwExtraInfo = extra

    # Down
    inp_down = INPUT()
    inp_down.type = INPUT_MOUSE
    inp_down.iu.mi.dx = abs_x
    inp_down.iu.mi.dy = abs_y
    inp_down.iu.mi.dwFlags = MOUSEEVENTF_LEFTDOWN | MOUSEEVENTF_ABSOLUTE
    inp_down.iu.mi.dwExtraInfo = extra

    # Up
    inp_up = INPUT()
    inp_up.type = INPUT_MOUSE
    inp_up.iu.mi.dx = abs_x
    inp_up.iu.mi.dy = abs_y
    inp_up.iu.mi.dwFlags = MOUSEEVENTF_LEFTUP | MOUSEEVENTF_ABSOLUTE
    inp_up.iu.mi.dwExtraInfo = extra

    # Execute
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp_move), ctypes.sizeof(INPUT))
    time.sleep(0.02)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp_down), ctypes.sizeof(INPUT))
    time.sleep(hold_ms / 1000.0)
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp_up), ctypes.sizeof(INPUT))


def restore_mouse(orig_x: int, orig_y: int):
    """Move mouse back to original position using SendInput."""
    abs_x, abs_y = _screen_to_absolute(orig_x, orig_y)
    extra = ctypes.pointer(wintypes.ULONG(0))
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.iu.mi.dx = abs_x
    inp.iu.mi.dy = abs_y
    inp.iu.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
    inp.iu.mi.dwExtraInfo = extra
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def sendinput_scroll(x: int, y: int, clicks: int = -5, smooth: bool = True):
    """Scroll at (x, y) using SendInput.
    
    Args:
        x, y: Screen coordinates to scroll at.
        clicks: Number of wheel notches. Negative = scroll down, positive = scroll up.
        smooth: If True, send one notch at a time with small delays for smoother scrolling.
    """
    MOUSEEVENTF_WHEEL = 0x0800
    abs_x, abs_y = _screen_to_absolute(x, y)
    extra = ctypes.pointer(wintypes.ULONG(0))

    # Move mouse to the target position first
    inp_move = INPUT()
    inp_move.type = INPUT_MOUSE
    inp_move.iu.mi.dx = abs_x
    inp_move.iu.mi.dy = abs_y
    inp_move.iu.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
    inp_move.iu.mi.dwExtraInfo = extra
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp_move), ctypes.sizeof(INPUT))
    time.sleep(0.03)

    if smooth and abs(clicks) > 1:
        # Smooth scrolling: send one notch at a time with delay
        direction = -1 if clicks < 0 else 1
        notch_delta = direction * 120  # 120 = one wheel notch
        for _ in range(abs(clicks)):
            inp_wheel = INPUT()
            inp_wheel.type = INPUT_MOUSE
            inp_wheel.iu.mi.dx = 0
            inp_wheel.iu.mi.dy = 0
            # Use ctypes.c_int32 to correctly handle negative values,
            # then cast to unsigned for the DWORD field
            inp_wheel.iu.mi.mouseData = ctypes.c_uint32(ctypes.c_int32(notch_delta).value).value
            inp_wheel.iu.mi.dwFlags = MOUSEEVENTF_WHEEL
            inp_wheel.iu.mi.dwExtraInfo = extra
            ctypes.windll.user32.SendInput(1, ctypes.byref(inp_wheel), ctypes.sizeof(INPUT))
            time.sleep(0.04)  # Small delay between notches for smooth feel
    else:
        # Single burst scroll
        total_delta = clicks * 120
        inp_wheel = INPUT()
        inp_wheel.type = INPUT_MOUSE
        inp_wheel.iu.mi.dx = 0
        inp_wheel.iu.mi.dy = 0
        inp_wheel.iu.mi.mouseData = ctypes.c_uint32(ctypes.c_int32(total_delta).value).value
        inp_wheel.iu.mi.dwFlags = MOUSEEVENTF_WHEEL
        inp_wheel.iu.mi.dwExtraInfo = extra
        ctypes.windll.user32.SendInput(1, ctypes.byref(inp_wheel), ctypes.sizeof(INPUT))


# ——————————————————————————————————————————————————————————————————————
# IDE WINDOW SAFETY — HARD WHITELIST
# The autoclicker can ONLY interact with windows from these executables.
# ——————————————————————————————————————————————————————————————————————

IDE_EXES = {
    "code.exe", "code - insiders.exe",       # VS Code
    "antigravity.exe",                         # Antigravity IDE
    "cursor.exe",                              # Cursor
    "windsurf.exe",                            # Windsurf / Codeium
    "kimi.exe",                                # Kimi Code
}


def _get_exe_for_hwnd(hwnd) -> str:
    """Get the executable name (lowercase) for a window handle."""
    try:
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = win32api.OpenProcess(0x0400 | 0x0010, False, pid)
        try:
            exe_path = win32process.GetModuleFileNameEx(handle, 0)
            return os.path.basename(exe_path).lower()
        finally:
            win32api.CloseHandle(handle)
    except Exception:
        return ""


def _is_ide_hwnd(hwnd) -> bool:
    """Check if a window handle belongs to a whitelisted IDE executable."""
    if not hwnd:
        return False
    return _get_exe_for_hwnd(hwnd) in IDE_EXES


def is_point_on_ide_window(x: int, y: int) -> bool:
    """Check if screen coordinates (x, y) are on top of a whitelisted IDE window.

    Uses WindowFromPoint to find which window is at that pixel, then walks
    the parent chain to find the top-level owner and checks if its process
    is a whitelisted IDE. Returns False for ANY non-IDE window.
    """
    try:
        point_hwnd = ctypes.windll.user32.WindowFromPoint(
            ctypes.wintypes.POINT(x, y)
        )
        if not point_hwnd:
            return False
        # Walk up the parent chain to find the top-level window
        check_hwnd = point_hwnd
        for _ in range(20):  # Max depth guard
            parent = win32gui.GetParent(check_hwnd)
            if parent == 0 or parent == check_hwnd:
                break
            check_hwnd = parent
        # check_hwnd is now the top-level window — verify it's an IDE
        return _is_ide_hwnd(check_hwnd)
    except Exception:
        return False


def is_rect_inside_ide_window(bbox: Tuple[int, int, int, int], ide_rect: Tuple[int, int, int, int]) -> bool:
    """Check that a bounding box is fully contained within the IDE window rect.
    
    This prevents capturing screenshots of areas outside the IDE window,
    even if the scan region math is slightly off.
    """
    bl, bt, br, bb = bbox
    wl, wt, wr, wb = ide_rect
    return bl >= wl and bt >= wt and br <= wr and bb <= wb


# ——————————————————————————————————————————————————————————————————————
# WINDOW FINDER — Reliable via EnumWindows
# ——————————————————————————————————————————————————————————————————————

def find_target_windows(hints: List[str]) -> list:
    """Find visible windows whose titles contain any of the hint strings
    AND belong to a whitelisted IDE executable.
    
    Returns list of (hwnd, title, rect) tuples, sorted by relevance.
    """
    # Use the global IDE_EXES whitelist
    results = []

    def _get_exe_name(hwnd):
        """Get the executable name for a window's process (uses global helper)."""
        return _get_exe_for_hwnd(hwnd)

    def callback(hwnd, _):
        try:
            if not win32gui.IsWindowVisible(hwnd):
                return 1
            title = win32gui.GetWindowText(hwnd)
            if not title:
                return 1
            title_lower = title.lower()

            # Skip our own GUI / app windows
            if title_lower.startswith("\u26a1 antigravity autoclicker"):
                return 1

            # WHITELIST: Only match windows from known IDE executables
            exe_name = _get_exe_name(hwnd)
            if exe_name not in IDE_EXES:
                return 1

            # Check if any hint matches the title
            for hint in hints:
                hint_lower = hint.lower()
                if hint_lower in title_lower:
                    try:
                        rect = win32gui.GetWindowRect(hwnd)
                        w = rect[2] - rect[0]
                        h = rect[3] - rect[1]
                        if w > 200 and h > 200:
                            # Score: hint at end = main window, area as tiebreaker
                            score = 0
                            if title_lower.rstrip().endswith(hint_lower):
                                score += 1000
                            score += (w * h) // 10000
                            results.append((hwnd, title, rect, score))
                    except Exception:
                        pass
                    break
        except Exception:
            pass
        return 1

    try:
        win32gui.EnumWindows(callback, 0)
    except Exception:
        pass
    # Sort by score descending — main IDE window first
    results.sort(key=lambda r: r[3], reverse=True)
    return [(hwnd, title, rect) for hwnd, title, rect, _score in results]


def auto_detect_profile(window_title: str) -> Optional[str]:
    """Try to determine which profile matches a window title."""
    title_lower = window_title.lower()
    # Check specific hints first
    for key, profile in PROFILES.items():
        for hint in profile.get("window_hints", []):
            if hint in title_lower:
                return key
    # Fallback: if it looks like VS Code, default to antigravity
    if "visual studio code" in title_lower or "vs code" in title_lower:
        return "antigravity"
    return None


# ——————————————————————————————————————————————————————————————————————
# BUTTON DETECTOR — Color + shape + optional OCR
# ——————————————————————————————————————————————————————————————————————

class ButtonDetection:
    """Represents a detected button candidate."""
    __slots__ = ("x", "y", "w", "h", "cx", "cy", "btn_type", "confidence", "method")

    def __init__(self, x, y, w, h, btn_type, confidence, method="color"):
        self.x = x
        self.y = y
        self.w = w
        self.h = h
        self.cx = x + w // 2
        self.cy = y + h // 2
        self.btn_type = btn_type
        self.confidence = confidence
        self.method = method

    def __repr__(self):
        return f"Button({self.btn_type}, {self.cx},{self.cy}, {self.w}x{self.h}, {self.confidence:.2f}, {self.method})"


def detect_buttons_color(frame: np.ndarray, profile: dict, settings: dict) -> List[ButtonDetection]:
    """Detect buttons using HSV color filtering + contour analysis.
    
    Strict filtering prevents false positives on:
      - Dropdown menu items (too small, wrong aspect ratio)
      - Send/submit buttons (excluded by scan region clipping)
      - Scrollbar thumbs (too narrow)
      - Status bar icons (too small)
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    detections = []

    min_area = settings.get("min_button_area", 1500)
    max_area = settings.get("max_button_area", 60000)
    min_ratio = settings.get("min_aspect_ratio", 1.5)
    max_ratio = settings.get("max_aspect_ratio", 10.0)
    min_w = settings.get("min_button_width", 60)
    min_h = settings.get("min_button_height", 20)
    frame_h = frame.shape[0]

    buttons_config = profile.get("buttons", {})

    for btn_type, color_cfg in buttons_config.items():
        # Check if this button type is enabled
        if btn_type == "run" and not settings.get("detect_run", True):
            continue
        if btn_type == "accept" and not settings.get("detect_accept", True):
            continue
        if btn_type == "confirm" and not settings.get("detect_confirm", True):
            continue

        hsv_min = np.array(color_cfg["hsv_min"], dtype=np.uint8)
        hsv_max = np.array(color_cfg["hsv_max"], dtype=np.uint8)

        mask = cv2.inRange(hsv, hsv_min, hsv_max)

        # Morphological cleaning to reduce noise
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        b_min_w = color_cfg.get("min_w", min_w)
        b_max_w = color_cfg.get("max_w", 9999)
        b_min_h = color_cfg.get("min_h", min_h)
        b_max_h = color_cfg.get("max_h", 9999)
        b_min_ratio = color_cfg.get("min_ratio", min_ratio)
        b_max_ratio = color_cfg.get("max_ratio", max_ratio)

        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            
            # SIZE GUARDS: strict constraints based on profile
            if w < b_min_w or w > b_max_w or h < b_min_h or h > b_max_h:
                continue
            
            area = w * h
            if area < min_area or area > max_area:
                continue

            ratio = w / h if h > 0 else 0
            if ratio < b_min_ratio or ratio > b_max_ratio:
                continue

            # Confidence based on how much of the bounding rect is filled
            fill_ratio = cv2.contourArea(cnt) / area if area > 0 else 0
            confidence = min(1.0, fill_ratio * 1.2)

            if confidence >= settings.get("confidence", 0.55):
                detections.append(ButtonDetection(x, y, w, h, btn_type, confidence, "color"))

    return detections


def _render_text_template(text: str, font_size: int = 14) -> np.ndarray:
    """Render text as a small white-on-black image for template matching."""
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = font_size / 30.0  # approximate scale
    thickness = 1 if font_size < 16 else 2
    (tw, th), _ = cv2.getTextSize(text, font, scale, thickness)
    # Pad to give some margin
    img = np.zeros((th + 10, tw + 10), dtype=np.uint8)
    cv2.putText(img, text, (5, th + 5), font, scale, 255, thickness)
    return img

# Template cache: built lazily on first call
_template_cache: Dict[str, List[Tuple[str, str, np.ndarray]]] = {}

def _build_template_cache(profile: dict) -> Dict[str, List[Tuple[str, str, np.ndarray]]]:
    """Pre-render keyword templates for a profile. Returns {btn_type: [(keyword, size_label, template_img), ...]}"""
    cache: Dict[str, List[Tuple[str, str, np.ndarray]]] = {}
    keywords = profile.get("ocr_keywords", {})
    for btn_type, kw_list in keywords.items():
        templates = []
        for kw in kw_list:
            if " " in kw:
                # Multi-word: render as single string
                for sz, label in [(12, "s"), (14, "m"), (16, "l")]:
                    tmpl = _render_text_template(kw, sz)
                    templates.append((kw, label, tmpl))
            else:
                for sz, label in [(12, "s"), (14, "m"), (16, "l")]:
                    tmpl = _render_text_template(kw, sz)
                    templates.append((kw, label, tmpl))
        cache[btn_type] = templates
    return cache


def detect_buttons_template(frame: np.ndarray, profile: dict, settings: dict) -> List[ButtonDetection]:
    """Detect buttons using fast OpenCV template matching (~2ms vs 100-200ms for OCR).
    
    Pre-renders expected button text as templates and uses cv2.matchTemplate
    to find them. Much faster than Tesseract while being accurate for known text.
    """
    global _template_cache
    if not settings.get("use_ocr", True):
        return []

    profile_name = profile.get("name", "default")
    if profile_name not in _template_cache:
        _template_cache[profile_name] = _build_template_cache(profile)
    
    cache = _template_cache[profile_name]
    detections = []
    
    try:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        # Enhance text visibility
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        keywords = profile.get("ocr_keywords", {})
        
        for btn_type, templates in cache.items():
            if btn_type == "busy":
                # For busy detection, just check if any busy keyword template matches
                for kw, _label, tmpl in templates:
                    if tmpl.shape[0] >= thresh.shape[0] or tmpl.shape[1] >= thresh.shape[1]:
                        continue
                    result = cv2.matchTemplate(thresh, tmpl, cv2.TM_CCOEFF_NORMED)
                    _, max_val, _, max_loc = cv2.minMaxLoc(result)
                    if max_val >= 0.6:  # Good match
                        mx, my = max_loc
                        detections.append(ButtonDetection(
                            mx, my, tmpl.shape[1], tmpl.shape[0], "busy", max_val, "template"
                        ))
                        break  # One busy indicator is enough
                continue
            
            # Template matching is ONLY used for "busy" indicators.
            # Clickable buttons (run, accept, confirm) MUST come from color detection
            # to avoid false positives (e.g., matching "run" in "Always run" text).
            continue
                    
    except Exception as e:
        logging.debug(f"Template detection error: {e}")
    
    return detections


def merge_detections(detections: List[ButtonDetection], distance_threshold: int = 40) -> List[ButtonDetection]:
    """Remove duplicate detections that overlap, keeping highest confidence."""
    if not detections:
        return []

    # Sort by confidence descending
    detections.sort(key=lambda d: d.confidence, reverse=True)
    merged = []

    for det in detections:
        is_dup = False
        for existing in merged:
            dx = abs(det.cx - existing.cx)
            dy = abs(det.cy - existing.cy)
            if dx < distance_threshold and dy < distance_threshold:
                is_dup = True
                break
        if not is_dup:
            merged.append(det)

    return merged


# ——————————————————————————————————————————————————————————————————————
# LOOP DETECTOR — Detects when the AI gets stuck in a spam loop
# ——————————————————————————————————————————————————————————————————————

class LoopDetector:
    """Detects AI spam loops by comparing recent OCR text snapshots."""

    def __init__(self, max_retries: int = 3):
        self.text_hashes: List[str] = []
        self.click_timestamps: Dict[str, List[float]] = {}
        self.retry_count = 0
        self.max_retries = max_retries

    def record_text(self, text: str) -> bool:
        """Record OCR'd text. Returns True if loop detected (3+ identical snapshots)."""
        normalized = ''.join(text[-500:].split()).lower()
        h = hashlib.md5(normalized.encode()).hexdigest()
        self.text_hashes.append(h)
        if len(self.text_hashes) > 10:
            self.text_hashes = self.text_hashes[-10:]
        if len(self.text_hashes) >= 3:
            return self.text_hashes[-1] == self.text_hashes[-2] == self.text_hashes[-3]
        return False

    def record_click(self, btn_type: str) -> bool:
        """Record a click. Returns True if rapid-fire (4+ in 60s)."""
        now = time.time()
        if btn_type not in self.click_timestamps:
            self.click_timestamps[btn_type] = []
        self.click_timestamps[btn_type].append(now)
        self.click_timestamps[btn_type] = [t for t in self.click_timestamps[btn_type] if t > now - 60]
        return len(self.click_timestamps[btn_type]) >= 10

    def reset(self):
        self.text_hashes.clear()
        self.click_timestamps.clear()
        self.retry_count = 0


# ——————————————————————————————————————————————————————————————————————
# SCREEN READER — OCR the IDE chat panel to extract text
# ——————————————————————————————————————————————————————————————————————

class ScreenReader:
    """Reads text from the IDE chat panel via OCR."""

    def read_chat_panel(self, window_rect: Tuple[int, int, int, int],
                        settings: Optional[dict] = None) -> str:
        """OCR the chat panel area of the IDE window. Returns extracted text."""
        if not OCR_AVAILABLE:
            return ""
        try:
            left, top, right, bottom = window_rect
            win_w = right - left
            chat_left = left + int(win_w * 0.55) if win_w > 800 else left
            chat_top = top + 30
            input_clip = (settings or {}).get("input_box_clip_px", 100)
            chat_bottom = bottom - input_clip
            if chat_bottom <= chat_top or right <= chat_left:
                return ""
            screenshot = ImageGrab.grab(bbox=(chat_left, chat_top, right - 5, chat_bottom))
            gray = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2GRAY)
            return pytesseract.image_to_string(gray).strip()
        except Exception as e:
            logging.debug(f"ScreenReader error: {e}")
            return ""


# ——————————————————————————————————————————————————————————————————————
# OLLAMA CLIENT — Interface to the Ollama REST API
# ——————————————————————————————————————————————————————————————————————

class OllamaClient:
    """Communicates with the Ollama API for local LLM inference."""

    # Common Windows install locations for Ollama
    _OLLAMA_PATHS = [
        os.path.expanduser(r"~\AppData\Local\Programs\Ollama\ollama.exe"),
        os.path.expanduser(r"~\AppData\Local\Ollama\ollama.exe"),
        r"C:\Program Files\Ollama\ollama.exe",
        r"C:\Program Files (x86)\Ollama\ollama.exe",
    ]

    def __init__(self, host: str = "localhost", port: int = 11434):
        self.base_url = f"http://{host}:{port}"
        self._ollama_bin: Optional[str] = None  # Cached path to ollama binary

    @staticmethod
    def find_ollama_binary() -> Optional[str]:
        """Find the ollama binary on PATH or common install locations."""
        # Check PATH first
        on_path = shutil.which("ollama")
        if on_path:
            return on_path
        # Check common Windows install locations
        for p in OllamaClient._OLLAMA_PATHS:
            if os.path.isfile(p):
                return p
        return None

    @staticmethod
    def is_installed() -> bool:
        """Check if the ollama binary exists on PATH or common install locations."""
        return OllamaClient.find_ollama_binary() is not None

    def is_running(self) -> bool:
        """Check if the Ollama server is responding."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            urllib.request.urlopen(req, timeout=3)
            return True
        except Exception:
            return False

    def start_server(self, max_wait: int = 15) -> Optional[subprocess.Popen]:
        """Start the Ollama server in the background.
        
        Polls for readiness up to max_wait seconds.
        Returns the Popen object or None on failure.
        """
        ollama_bin = self.find_ollama_binary()
        if not ollama_bin:
            return None
        try:
            # CREATE_NO_WINDOW = 0x08000000
            proc = subprocess.Popen(
                [ollama_bin, "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=0x08000000,
            )
            # Poll for readiness instead of blind sleep
            for _ in range(max_wait * 2):
                time.sleep(0.5)
                if self.is_running():
                    return proc
            if proc.poll() is None:
                return proc
            return None
        except Exception as e:
            logging.error(f"Failed to start Ollama: {e}")
            return None

    @staticmethod
    def stop_server():
        """Stop Ollama server processes (graceful then forceful)."""
        try:
            subprocess.run(["taskkill", "/im", "ollama.exe"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            time.sleep(1)
        except Exception:
            pass
        try:
            subprocess.run(["taskkill", "/f", "/im", "ollama.exe"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            subprocess.run(["taskkill", "/f", "/im", "ollama_llama_server.exe"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except Exception:
            pass

    def list_models(self) -> List[str]:
        """Return list of locally available model names."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    def check_model_available(self, model: str) -> bool:
        """Check if a specific model is downloaded."""
        return model in self.list_models()

    def pull_model(self, name: str, progress_callback=None):
        """Download a model. Calls progress_callback(status_text) periodically."""
        try:
            payload = json.dumps({"name": name, "stream": True}).encode()
            req = urllib.request.Request(
                f"{self.base_url}/api/pull", data=payload,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=600) as resp:
                for line in resp:
                    if line.strip():
                        chunk = json.loads(line)
                        status = chunk.get("status", "")
                        if progress_callback:
                            progress_callback(status)
                        if chunk.get("error"):
                            raise RuntimeError(chunk["error"])
        except urllib.error.URLError as e:
            raise RuntimeError(f"Cannot reach Ollama server: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to pull model '{name}': {e}")

    def _http_request(self, endpoint: str, payload: dict, timeout: int = 120) -> dict:
        """Make an HTTP POST to the Ollama API with proper error handling."""
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.base_url}{endpoint}", data=data,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            try:
                err_msg = json.loads(body).get("error", body[:200])
            except Exception:
                err_msg = body[:200]
            raise RuntimeError(f"Ollama API error ({e.code}): {err_msg}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Cannot reach Ollama at {self.base_url}: {e.reason}")
        except TimeoutError:
            raise RuntimeError(f"Ollama request timed out after {timeout}s")

    def generate(self, prompt: str, model: str = "phi3:mini",
                 system: str = "", context=None) -> Tuple[str, Any]:
        """Generate a response (non-streaming). Returns (response_text, context)."""
        payload: dict = {"model": model, "prompt": prompt, "system": system, "stream": False}
        if context:
            payload["context"] = context
        result = self._http_request("/api/generate", payload)
        return result.get("response", ""), result.get("context")

    def chat(self, messages: List[dict], model: str = "llama3.2:latest",
             stream: bool = False) -> Tuple[str, List[dict]]:
        """Chat with a model using message history.

        Uses /api/chat which properly supports multi-turn conversation.
        Returns (response_text, updated_messages).
        """
        payload: dict = {"model": model, "messages": messages, "stream": stream}
        result = self._http_request("/api/chat", payload, timeout=180)
        assistant_msg = result.get("message", {})
        response_text = assistant_msg.get("content", "")
        # Append assistant response to history
        updated = messages + [{"role": "assistant", "content": response_text}]
        return response_text, updated

    def generate_stream(self, prompt: str, model: str, system: str,
                        callback, context=None) -> Tuple[str, Any]:
        """Streaming generation. Calls callback(token) for each token."""
        payload: dict = {"model": model, "prompt": prompt, "system": system, "stream": True}
        if context:
            payload["context"] = context
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            f"{self.base_url}/api/generate", data=data,
            headers={"Content-Type": "application/json"})
        full_response = ""
        out_context = None
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                for line in resp:
                    if line.strip():
                        chunk = json.loads(line)
                        token = chunk.get("response", "")
                        full_response += token
                        callback(token)
                        if chunk.get("done"):
                            out_context = chunk.get("context")
        except Exception as e:
            if full_response:
                callback(f"\n[Stream interrupted: {e}]")
            else:
                raise
        return full_response, out_context


# ——————————————————————————————————————————————————————————————————————
# CHAT CONTROLLER — Types prompts into the IDE and handles cancel
# ——————————————————————————————————————————————————————————————————————

class ChatController:
    """Interacts with the IDE chat input: types text, submits, finds cancel buttons."""

    def click_input_area(self, window_rect: Tuple[int, int, int, int], settings: dict = None):
        """Click into the chat input box at the bottom of the IDE.
        SAFETY: Only clicks if the target point is on a whitelisted IDE window.
        """
        settings = settings or {}
        left, top, right, bottom = window_rect
        win_w = right - left
        input_clip = settings.get("input_box_clip_px", 100)
        # Input box center
        if win_w > 800:
            ix = left + int(win_w * 0.55) + (right - left - int(win_w * 0.55)) // 2
        else:
            ix = left + win_w // 2
        iy = bottom - input_clip // 2
        # IDE SAFETY GATE
        if not is_point_on_ide_window(ix, iy):
            logging.warning(f"ChatController: BLOCKED click at ({ix},{iy}) — not on IDE window")
            return
        sendinput_click(ix, iy, hold_ms=30)
        time.sleep(0.15)

    def type_text(self, text: str):
        """Type text into the focused input using clipboard paste (fast & reliable)."""
        if CLIPBOARD_AVAILABLE:
            try:
                win32clipboard.OpenClipboard()
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
                win32clipboard.CloseClipboard()
                pyautogui.hotkey('ctrl', 'v')
                time.sleep(0.1)
                return
            except Exception:
                pass
        # Fallback: character-by-character (slower)
        pyautogui.typewrite(text, interval=0.02)

    def submit(self):
        """Press Enter to submit the prompt."""
        pyautogui.press('enter')
        time.sleep(0.2)

    def find_cancel_button(self, window_rect: Tuple[int, int, int, int],
                           settings: dict = None) -> Optional[Tuple[int, int]]:
        """Find the red cancel/stop button in the input area. Returns (x,y) or None."""
        settings = settings or {}
        try:
            left, top, right, bottom = window_rect
            win_w = right - left
            input_clip = settings.get("input_box_clip_px", 100)
            input_top = bottom - input_clip
            input_left = left + int(win_w * 0.55) if win_w > 800 else left
            bbox = (input_left, input_top, right - 5, bottom - 5)
            screenshot = ImageGrab.grab(bbox=bbox)
            frame = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            # Red wraps in HSV: 0-10 and 170-180
            mask1 = cv2.inRange(hsv, np.array([0, 100, 100]), np.array([10, 255, 255]))
            mask2 = cv2.inRange(hsv, np.array([170, 100, 100]), np.array([180, 255, 255]))
            mask = mask1 | mask2
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                x, y, w, h = cv2.boundingRect(cnt)
                area = w * h
                if 100 < area < 5000 and 0.3 < (w / h if h > 0 else 0) < 3.0:
                    return (input_left + x + w // 2, input_top + y + h // 2)
        except Exception as e:
            logging.debug(f"Cancel button search error: {e}")
        return None


# ——————————————————————————————————————————————————————————————————————
# AGENT BRAIN — Autonomous coding agent powered by Ollama
# ——————————————————————————————————————————————————————————————————————

# Maximum steps per agent session to prevent runaway
AGENT_MAX_STEPS = 50

# Maximum seconds to wait for coding AI to stabilize before timing out
AGENT_STALL_TIMEOUT = 300  # 5 minutes


class AgentBrain:
    """The autonomous coding supervisor that drives another AI via Ollama.
    
    Uses the /api/chat endpoint for proper multi-turn conversation memory,
    so the agent remembers what it has already asked the coding AI to do.
    """

    def __init__(self, ollama: OllamaClient, scan_engine, log_callback=None,
                 status_callback=None, chat_callback=None):
        self.ollama = ollama
        self.scan_engine = scan_engine
        self.log = log_callback or (lambda msg, tag="info": None)
        self.set_status = status_callback or (lambda s: None)
        self.chat_display = chat_callback or (lambda role, msg: None)
        self.running = False
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.mode = "build"
        self.model = "llama3.2:latest"
        self.task = ""
        self.conversation: List[dict] = []  # Full chat history for /api/chat
        self.steps_completed = 0
        self.screen_reader = ScreenReader()
        self.chat_controller = ChatController()
        self.loop_detector = LoopDetector()
        self.settings: dict = {}
        self.user_msg_queue: queue.Queue = queue.Queue()
        # Separate context for direct chat (so it doesn't corrupt agent loop)
        self._direct_chat_history: List[dict] = []
        self._consecutive_errors = 0

    def set_task(self, task: str):
        self.task = task
        self.conversation = []
        self._direct_chat_history = []
        self.steps_completed = 0
        self.loop_detector.reset()
        self._consecutive_errors = 0

    def send_user_message(self, msg: str):
        """Send a message from the user to the agent (thread-safe)."""
        self.user_msg_queue.put(msg)

    def chat_with_ollama(self, user_msg: str) -> str:
        """Direct chat with the local model (for planning/discussion, not agent loop).
        
        Uses a SEPARATE conversation history so it doesn't corrupt
        the autonomous agent loop's context.
        """
        try:
            self._direct_chat_history.append({"role": "user", "content": user_msg})
            # Keep direct chat history manageable
            if len(self._direct_chat_history) > 20:
                self._direct_chat_history = self._direct_chat_history[-20:]
            
            messages = [
                {"role": "system", "content": (
                    "You are a helpful AI coding supervisor. Help the user plan "
                    "and discuss their project. Be concise and practical."
                )}
            ] + self._direct_chat_history
            
            response, self._direct_chat_history = self.ollama.chat(
                messages, self.model)
            return response
        except Exception as e:
            return f"❌ Ollama error: {e}"

    def _ensure_model_ready(self) -> bool:
        """Ensure the selected model is available, auto-pulling if needed."""
        if self.ollama.check_model_available(self.model):
            return True
        
        self.log(f"Model '{self.model}' not found locally. Pulling...", "warning")
        self.set_status(f"Downloading {self.model}...")
        try:
            self.ollama.pull_model(
                self.model,
                progress_callback=lambda s: self.log(f"  Pull: {s}", "info")
            )
            self.log(f"✅ Model '{self.model}' downloaded!", "success")
            return True
        except Exception as e:
            self.log(f"❌ Failed to pull model: {e}", "error")
            return False

    def _ensure_ollama_running(self) -> bool:
        """Ensure Ollama server is running, starting it if needed."""
        if self.ollama.is_running():
            return True
        
        if not OllamaClient.is_installed():
            self.log("❌ Ollama is not installed. Visit https://ollama.com to install.", "error")
            return False
        
        self.log("Starting Ollama server...", "info")
        self.set_status("Starting Ollama...")
        self._ollama_proc = self.ollama.start_server(max_wait=15)
        
        if self.ollama.is_running():
            self._we_started_ollama = True
            self.log("✅ Ollama server started", "success")
            return True
        else:
            self.log("❌ Failed to start Ollama server. Try starting it manually.", "error")
            return False

    def start(self):
        if self.running:
            return
        self._we_started_ollama = False
        
        # 1. Ensure Ollama server is running
        if not self._ensure_ollama_running():
            return
        
        # 2. Ensure the selected model is available
        if not self._ensure_model_ready():
            return
        
        self.running = True
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._agent_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        self.stop_event.set()
        self.set_status("Idle")
        # Auto-stop Ollama if we started it
        if getattr(self, '_we_started_ollama', False):
            self.log("Stopping Ollama server...", "info")
            OllamaClient.stop_server()
            self._we_started_ollama = False
            self.log("Ollama server stopped", "info")

    def _build_system_message(self) -> dict:
        """Build the system message for the agent conversation."""
        mode_cfg = AGENT_MODES.get(self.mode, AGENT_MODES["build"])
        base_prompt = mode_cfg["system_prompt"]
        
        # Enhance with guard rails for autonomous operation
        enhanced = (
            f"{base_prompt}\n\n"
            "IMPORTANT RULES:\n"
            "1. Give ONE clear, specific instruction at a time. Do not give multiple tasks.\n"
            "2. Keep your instructions under 200 words.\n"
            "3. After reading the AI's response, decide: was the step successful or does it need a fix?\n"
            "4. Track your progress. Do not repeat instructions that were already completed.\n"
            "5. If the AI reports an error, analyze it and give a specific fix instruction.\n"
            "6. When the task is truly complete and working, respond with exactly: TASK_COMPLETE\n"
            "7. Do NOT include any pleasantries, explanations to the user, or meta-commentary. "
            "Only output the exact instruction to send to the coding AI.\n"
            f"\nORIGINAL TASK: {self.task}\n"
        )
        return {"role": "system", "content": enhanced}

    def _agent_loop(self):
        """Main autonomous loop: read screen → think → type → wait → repeat.
        
        Uses /api/chat for proper multi-turn conversation memory.
        """
        mode_cfg = AGENT_MODES.get(self.mode, AGENT_MODES["build"])
        self.set_status("Planning...")
        self.log(f"🤖 Agent started in mode: {mode_cfg['name']}", "success")
        self.log(f"🤖 Task: {self.task[:100]}{'...' if len(self.task) > 100 else ''}", "info")
        self.log(f"🤖 Model: {self.model}", "info")

        # Initialize conversation with system message
        self.conversation = [self._build_system_message()]

        # Step 1: Generate initial plan
        try:
            self.conversation.append({
                "role": "user",
                "content": (
                    f"Task: {self.task}\n\n"
                    "Create a concise step-by-step plan (max 8 steps). "
                    "Then give me the FIRST instruction to send to the coding AI."
                )
            })
            response, self.conversation = self.ollama.chat(
                self.conversation, self.model)
            self.chat_display("agent", f"📝 Plan:\n{response}")
            self.log("📝 Plan generated", "info")
        except Exception as e:
            self.log(f"❌ Ollama error during planning: {e}", "error")
            self.running = False
            self.set_status("Error")
            return

        # Step 2: Main agent loop
        last_click_count = self.scan_engine.clicks_total
        while not self.stop_event.is_set():
            try:
                # Safety: step limit
                if self.steps_completed >= AGENT_MAX_STEPS:
                    self.log(f"⚠️ Reached max steps ({AGENT_MAX_STEPS}). Stopping.", "warning")
                    self.chat_display("agent", f"⚠️ Reached maximum {AGENT_MAX_STEPS} steps. Stopping.")
                    break

                # Check for user messages
                try:
                    user_msg = self.user_msg_queue.get_nowait()
                    if user_msg.lower() in ["stop", "quit", "exit"]:
                        self.stop()
                        break
                    # User override: inject into the agent's conversation
                    self.conversation.append({"role": "user", "content": f"[USER OVERRIDE]: {user_msg}"})
                    response, self.conversation = self.ollama.chat(
                        self.conversation, self.model)
                    self.chat_display("agent", response)
                    continue
                except queue.Empty:
                    pass

                # Find IDE window
                self.set_status("Finding window...")
                profile_key = self.settings.get("profile", "antigravity")
                profile = PROFILES.get(profile_key, PROFILES["antigravity"])
                hints = profile.get("window_hints", ["antigravity"])
                windows = find_target_windows(hints)
                if not windows:
                    # Also try auto-detect
                    if self.settings.get("auto_detect_window", True):
                        windows = find_target_windows([
                            "visual studio code", "vs code", "cursor",
                            "windsurf", "antigravity"
                        ])
                if not windows:
                    self.set_status("Waiting for IDE window...")
                    time.sleep(3)
                    continue
                hwnd, title, rect = windows[0]

                # Wait for coding AI to finish with stall detection
                self.set_status("Waiting for AI to finish...")
                stable_ticks = 0
                stall_start = time.time()
                while not self.stop_event.is_set() and stable_ticks < 6:
                    # Stall detection: if we've been waiting too long, something is stuck
                    if (time.time() - stall_start) > AGENT_STALL_TIMEOUT:
                        self.log("⚠️ AI appears stalled (5min timeout). Attempting recovery...", "warning")
                        # Try clicking cancel and retrying
                        self._handle_loop(hwnd, rect)
                        stall_start = time.time()  # Reset timer
                        break
                    
                    if self.scan_engine.clicks_total > last_click_count:
                        last_click_count = self.scan_engine.clicks_total
                        stable_ticks = 0
                        stall_start = time.time()  # Reset stall timer on activity
                    else:
                        stable_ticks += 1
                    time.sleep(2)

                if self.stop_event.is_set():
                    break

                # Read the screen
                self.set_status("Reading screen...")
                screen_text = self.screen_reader.read_chat_panel(rect, self.settings)

                # Check for loops
                if self.settings.get("loop_detect_enabled", True) and self.loop_detector.record_text(screen_text):
                    self.log("⚠️ Spam loop detected! Cancelling and retrying...", "warning")
                    self._handle_loop(hwnd, rect)
                    if self.loop_detector.retry_count >= self.loop_detector.max_retries:
                        self.log("❌ Max retries reached. Stopping.", "error")
                        break
                    continue

                # Ask local model what to do next (with conversation memory)
                self.set_status("Thinking...")
                screen_summary = screen_text[-2000:] if screen_text else "[Could not read screen - OCR unavailable or failed]"
                self.conversation.append({
                    "role": "user",
                    "content": (
                        f"[SCREEN CAPTURE - Step {self.steps_completed + 1}]\n"
                        f"The coding AI's latest response:\n---\n{screen_summary}\n---\n\n"
                        "Based on this response, what is the NEXT instruction to send? "
                        "If the original task is complete, say TASK_COMPLETE."
                    )
                })
                
                # Trim conversation history to prevent context overflow
                # Keep system message + last 20 exchanges
                if len(self.conversation) > 42:  # 1 system + 20 pairs + 1 new
                    self.conversation = [self.conversation[0]] + self.conversation[-40:]
                
                response, self.conversation = self.ollama.chat(
                    self.conversation, self.model)
                
                self._consecutive_errors = 0  # Reset on success

                if "TASK_COMPLETE" in response:
                    self.chat_display("agent", "✅ Task complete!")
                    self.log("✅ Agent: Task complete!", "success")
                    break

                # Clean the response — extract just the instruction
                instruction = response.strip()
                # Remove common LLM wrapper artifacts
                for prefix in ["Instruction:", "Next step:", "Tell the AI:", "Send:"]:
                    if instruction.lower().startswith(prefix.lower()):
                        instruction = instruction[len(prefix):].strip()

                if not instruction or len(instruction) < 5:
                    self.log("⚠️ Agent returned empty instruction, skipping", "warning")
                    time.sleep(2)
                    continue

                # Type the instruction into the IDE
                self.set_status("Typing prompt...")
                display_text = instruction[:300] + ("..." if len(instruction) > 300 else "")
                self.chat_display("agent", f"💬 Step {self.steps_completed + 1}: {display_text}")
                self.log(f"🤖 Instruction: {instruction[:150]}...", "info")
                
                try:
                    win32gui.SetForegroundWindow(hwnd)
                    time.sleep(0.3)
                except Exception:
                    pass
                self.chat_controller.click_input_area(rect, self.settings)
                time.sleep(0.2)
                self.chat_controller.type_text(instruction)
                time.sleep(0.15)
                self.chat_controller.submit()

                self.steps_completed += 1
                last_click_count = self.scan_engine.clicks_total
                self.log(f"🤖 Step {self.steps_completed} sent", "info")
                self.set_status(f"Waiting for AI response (step {self.steps_completed})...")
                time.sleep(5)  # Initial settle time

            except Exception as e:
                self._consecutive_errors += 1
                self.log(f"Agent error ({self._consecutive_errors}): {e}", "error")
                logging.error(f"Agent loop error: {e}", exc_info=True)
                if self._consecutive_errors >= 5:
                    self.log("❌ Too many consecutive errors. Stopping agent.", "error")
                    break
                # Exponential backoff: 3s, 6s, 12s, 24s, 48s
                backoff = min(3 * (2 ** (self._consecutive_errors - 1)), 60)
                time.sleep(backoff)

        self.running = False
        self.set_status("Idle")
        self.log(f"🤖 Agent stopped after {self.steps_completed} steps", "warning")

    def _handle_loop(self, hwnd, rect):
        """Handle a spam loop: cancel the current generation, type retry, submit.
        SAFETY: Only clicks if the target is a whitelisted IDE window.
        """
        # IDE SAFETY GATE: verify hwnd is an IDE before interacting
        if not _is_ide_hwnd(hwnd):
            self.log(f"_handle_loop: BLOCKED — hwnd={hwnd} is not a whitelisted IDE", "error")
            return
        try:
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.3)
        except Exception:
            pass
        # Try to click the red cancel button
        cancel_pos = self.chat_controller.find_cancel_button(rect, self.settings)
        if cancel_pos:
            # Verify cancel button position is on an IDE window
            if is_point_on_ide_window(cancel_pos[0], cancel_pos[1]):
                sendinput_click(cancel_pos[0], cancel_pos[1], hold_ms=60)
                self.log("Clicked cancel button", "info")
            else:
                self.log(f"BLOCKED cancel click at ({cancel_pos[0]},{cancel_pos[1]}): not on IDE", "error")
            time.sleep(2.0)
        else:
            self.log("No cancel button found, pressing Escape", "info")
            pyautogui.press('escape')
            time.sleep(1.0)
        # Type "retry" and submit
        self.chat_controller.click_input_area(rect, self.settings)
        time.sleep(0.3)
        retry_msg = self.settings.get("retry_message", "retry")
        self.chat_controller.type_text(retry_msg)
        time.sleep(0.15)
        self.chat_controller.submit()
        self.loop_detector.retry_count += 1
        self.log(f"Retried ({self.loop_detector.retry_count}/{self.loop_detector.max_retries})", "warning")


# ——————————————————————————————————————————————————————————————————————
# DEBUG OVERLAY — Real-time scan visualization
# ——————————————————————————————————————————————————————————————————————

class DebugOverlay:
    """Shows what the scanner sees with colored bounding boxes."""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.window: Optional[tk.Toplevel] = None
        self.enabled = False
        self.canvas: Optional[tk.Canvas] = None
        self._photo = None

    def toggle(self, force: Optional[bool] = None):
        self.enabled = force if force is not None else not self.enabled
        if self.enabled:
            self._create()
        else:
            self._close()

    def _create(self):
        if self.window:
            return
        self.window = tk.Toplevel(self.root)
        self.window.title("🔎 Debug Overlay")
        self.window.geometry("520x360")
        self.window.attributes("-topmost", True)
        self.window.configure(bg="#0a0e17")
        self.canvas = tk.Canvas(self.window, bg="#0a0e17", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.window.protocol("WM_DELETE_WINDOW", lambda: self.toggle(False))

    def update(self, frame: np.ndarray, detections: List[ButtonDetection]):
        """Update the overlay with current scan frame and detections."""
        if not self.enabled or not self.window or not self.canvas:
            return
        try:
            display = frame.copy()
            for det in detections:
                if det.btn_type == "busy":
                    color = (0, 165, 255)
                elif det.confidence >= 0.70:
                    color = (0, 255, 0)
                else:
                    color = (0, 0, 255)
                cv2.rectangle(display, (det.x, det.y), (det.x + det.w, det.y + det.h), color, 2)
                label = f"{det.btn_type} {det.confidence:.0%}"
                cv2.putText(display, label, (det.x, det.y - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
            img = Image.fromarray(cv2.cvtColor(display, cv2.COLOR_BGR2RGB))
            cw = self.canvas.winfo_width() or 520
            ch = self.canvas.winfo_height() or 360
            img = img.resize((cw, ch), Image.LANCZOS)
            self._photo = ImageTk.PhotoImage(img)
            self.canvas.delete("all")
            self.canvas.create_image(0, 0, anchor=tk.NW, image=self._photo)
        except Exception:
            pass

    def _close(self):
        if self.window:
            self.window.destroy()
            self.window = None
            self.canvas = None


# ——————————————————————————————————————————————————————————————————————
# SCAN ENGINE — The core detection + click loop
# ——————————————————————————————————————————————————————————————————————

class ScanEngine:
    """Background scanning engine that finds and clicks buttons."""

    def __init__(self, log_callback=None):
        self.running = False
        self.paused = False
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self.log_callback = log_callback or (lambda msg, tag="info": None)
        self.settings = load_settings()
        self.last_click_times: Dict[str, float] = {}
        self.clicks_total = 0
        self.last_scan_region = None
        self.detected_profile = None
        self.detected_window_title = None
        self._last_key_time = 0.0  # Track when user last typed
        self._focus_cooldown_until = 0.0  # Timestamp until which clicks are suppressed
        self.loop_detector = LoopDetector()  # Click-rate loop detection
        self._last_toast_time = 0.0  # Rate-limit toast notifications
        self._last_bottom_hash = None  # For scroll-change detection
        self._last_scroll_time = 0.0  # Rate-limit scroll operations
        self._last_focused_hwnd = None  # Track which IDE window we auto-focused

    def start(self):
        if self.running:
            return
        self.settings = load_settings()
        self.running = True
        self.paused = False
        self._last_focused_hwnd = None  # Reset so IDE gets auto-focused on start
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._scan_loop, daemon=True)
        self.thread.start()
        self.log("Scanner STARTED", "success")

    def stop(self):
        self.running = False
        self.stop_event.set()
        self.log("Scanner STOPPED", "warning")

    def toggle_pause(self):
        self.paused = not self.paused
        state = "PAUSED" if self.paused else "RESUMED"
        self.log(f"Scanner {state}", "warning")

    def trigger_focus_cooldown(self, seconds: float = 5.0):
        """Suppress all clicks for `seconds` after the autoclicker window gains focus.
        
        This prevents the autoclicker from immediately clicking the IDE window
        and stealing focus back before the user can interact with settings.
        """
        self._focus_cooldown_until = time.time() + seconds
        self.log(f"⏸️ Focus cooldown: clicks paused for {seconds:.0f}s", "warning")

    def _is_focus_cooldown_active(self) -> bool:
        """Check if the focus cooldown is still active."""
        return time.time() < self._focus_cooldown_until

    def log(self, msg: str, tag: str = "info"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_callback(f"[{timestamp}] {msg}", tag)

    def _check_cooldown(self, btn_type: str, hwnd: int = 0) -> bool:
        """Return True if enough time has passed since last click of this type."""
        cooldown = self.settings.get("cooldown_seconds", 1.5)
        key = f"{hwnd}_{btn_type}" if hwnd else btn_type
        last = self.last_click_times.get(key, 0)
        return (time.time() - last) >= cooldown

    def _record_click(self, btn_type: str, hwnd: int = 0):
        key = f"{hwnd}_{btn_type}" if hwnd else btn_type
        self.last_click_times[key] = time.time()
        # Also update global for the status API
        self.last_click_times[btn_type] = time.time()
        self.clicks_total += 1

    def _get_profile(self) -> dict:
        """Get the active detection profile."""
        key = self.settings.get("profile", "antigravity")
        return PROFILES.get(key, PROFILES["antigravity"])

    def _find_windows(self) -> list:
        """Find target windows based on current profile."""
        profile = self._get_profile()
        hints = profile.get("window_hints", ["antigravity"])
        return find_target_windows(hints)

    def _is_user_typing(self) -> bool:
        """Check if the user is CURRENTLY holding a typing key down.
        
        Only returns True if a key is literally pressed RIGHT NOW.
        Uses a very short cooldown (0.5s) to avoid interrupting rapid
        typing but not causing long pauses that make the scanner
        appear to 'stop randomly'.
        """
        try:
            typing_keys = (
                list(range(0x41, 0x5B)) +    # A-Z
                list(range(0x30, 0x3A)) +    # 0-9
                list(range(0x21, 0x29)) +    # PG_UP, PG_DN, END, HOME, ARROWS
                [0x20, 0x08, 0x0D, 0x09]     # Space, Backspace, Enter, Tab
            )
            for vk in typing_keys:
                state = ctypes.windll.user32.GetAsyncKeyState(vk)
                if state & 0x8000:  # Key is CURRENTLY held down
                    self._last_key_time = time.time()
                    return True
            
            # Cooldown — avoid stealing focus while typing or shortly after
            cooldown = self.settings.get("typing_cooldown_seconds", 5.0)
            if (time.time() - self._last_key_time) < cooldown:
                return True
                
        except Exception:
            pass
        return False

    def _force_foreground(self, hwnd):
        """Reliably bring a window to the foreground using AttachThreadInput trick.
        
        Windows restricts SetForegroundWindow — only the foreground process can call it.
        The workaround is to temporarily attach our thread to the foreground thread,
        call SetForegroundWindow, then detach.
        """
        try:
            # Get our thread and the foreground window's thread
            our_thread = ctypes.windll.kernel32.GetCurrentThreadId()
            fg_hwnd = win32gui.GetForegroundWindow()
            fg_thread = ctypes.windll.user32.GetWindowThreadProcessId(fg_hwnd, None)
            
            if our_thread != fg_thread:
                # Attach our thread to the foreground thread
                ctypes.windll.user32.AttachThreadInput(our_thread, fg_thread, True)
                try:
                    # Restore if minimized
                    if win32gui.IsIconic(hwnd):
                        win32gui.ShowWindow(hwnd, 9)  # SW_RESTORE
                    win32gui.BringWindowToTop(hwnd)
                    win32gui.SetForegroundWindow(hwnd)
                finally:
                    # Always detach
                    ctypes.windll.user32.AttachThreadInput(our_thread, fg_thread, False)
            else:
                # We're already the foreground thread, just set it
                if win32gui.IsIconic(hwnd):
                    win32gui.ShowWindow(hwnd, 9)
                win32gui.SetForegroundWindow(hwnd)
        except Exception:
            # Last resort fallback
            try:
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass

    def _get_scan_region(self, rect: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
        """Calculate the scan region — focus on the right panel (AI chat area)
        and the bottom portion where buttons typically appear.
        
        CRITICAL: Clips the bottom ~100px to exclude the chat input box
        and send/submit button, preventing false positive clicks on
        the send button while the user is typing.
        
        Returns (left, top, right, bottom) for ImageGrab.
        """
        left, top, right, bottom = rect
        win_w = right - left
        win_h = bottom - top

        # For wide windows (main IDE), focus on the right ~45% (AI chat panel)
        # For narrow/popup windows (agent manager), scan more width
        if win_w > 800:
            scan_left = left + int(win_w * 0.55)
        elif win_w > 400:
            scan_left = left + int(win_w * 0.15)  # Narrow popup: slight left margin
        else:
            scan_left = left  # Very small window: scan everything

        # Scan most of the window height to catch buttons anywhere in the chat
        bottom_pct = self.settings.get("scan_bottom_portion", 0.75)
        # For popup/agent windows (< 800px wide), scan even more
        if win_w <= 800:
            bottom_pct = max(bottom_pct, 0.85)
        scan_top = top + int(win_h * (1.0 - bottom_pct))

        # CRITICAL: Clip the bottom to exclude the chat input box + send button
        input_clip = self.settings.get("input_box_clip_px", 100)
        # Popup windows may have a smaller input area
        if win_w <= 800:
            input_clip = min(input_clip, 80)
        scan_bottom = bottom - input_clip

        # Add small margins to avoid window borders
        scan_left = max(scan_left, left + 5)
        scan_top = max(scan_top, top + 30)  # Below title bar
        scan_right = right - 5

        return (scan_left, scan_top, scan_right, scan_bottom)

    def _has_content_changed(self, frame, scan_bbox) -> bool:
        """Check if the bottom portion of the chat has new content.
        
        Compares a hash of the bottom ~60px of the scan region to detect
        whether new messages have appeared (meaning we should scroll down).
        Returns True only if content has genuinely changed.
        """
        try:
            h = frame.shape[0]
            bottom_strip = frame[max(0, h - 60):h, :]
            if bottom_strip.size == 0:
                return False
            # Downscale to tiny thumbnail for fast comparison
            small = cv2.resize(bottom_strip, (32, 8))
            current_hash = hash(small.tobytes())
            if self._last_bottom_hash is None:
                self._last_bottom_hash = current_hash
                return False
            changed = current_hash != self._last_bottom_hash
            self._last_bottom_hash = current_hash
            return changed
        except Exception:
            return False
    def _is_mouse_in_region(self, region: Tuple[int, int, int, int]) -> bool:
        """Check if the mouse cursor is hovering over the scan region."""
        try:
            x, y = win32api.GetCursorPos()
            left, top, right, bottom = region
            return left <= x <= right and top <= y <= bottom
        except Exception:
            return False

    def _smart_scroll_down(self, frame, scan_bbox, hwnd=None, force=False):
        """Scroll the chat down periodically to keep it at the bottom.
        
        Scrolls every 2 seconds with 5 notches to keep up with streaming output.
        HARD SAFETY: Only scrolls if the target point is on an IDE window.
        """
        now = time.time()
        
        # ACTIVE WINDOW GUARD: Only scroll if the window is actually currently active/foreground.
        # This prevents the mouse from teleporting around to scroll background IDEs.
        if hwnd and hwnd != win32gui.GetForegroundWindow() and not force:
            return

        if now - self._last_scroll_time < 2.0 and not force:
            return
            
        # HOVER GUARD: Pause scrolling if user's mouse is actively over the chat area
        if not force and self._is_mouse_in_region(scan_bbox):
            return
            
        # CONTENT GUARD: Only scroll down if the text actually changed (streaming output)
        if not force and not self._has_content_changed(frame, scan_bbox):
            return

        
        try:
            scan_left, scan_top, scan_right, scan_bottom = scan_bbox
            sx = (scan_left + scan_right) // 2
            sy = scan_top + int((scan_bottom - scan_top) * 0.75)  # Lower 75% of scan area
            
            # === IDE SAFETY GATE: Only scroll if the target point is on an IDE window ===
            if not is_point_on_ide_window(sx, sy):
                logging.debug(f"Scroll blocked: ({sx},{sy}) is not on an IDE window")
                return

            # Save → scroll → restore in one tight block
            orig_x, orig_y = win32api.GetCursorPos()
            sendinput_scroll(sx, sy, clicks=-5, smooth=False)
            restore_mouse(orig_x, orig_y)
            
            self._last_scroll_time = now
        except Exception as e:
            logging.debug(f"Scroll error: {e}")

    def _perform_click(self, screen_x: int, screen_y: int, detection: ButtonDetection, hwnd=None):
        """Click the detected button natively.
        
        HARD SAFETY: Will ONLY click if the screen coordinates physically map
        to a whitelisted IDE window on your desktop.
        """
        if not self._check_cooldown(detection.btn_type, hwnd):
            return False

        # === IDE SAFETY GATE 1: Verify the target hwnd is an IDE ===
        if hwnd and not _is_ide_hwnd(hwnd):
            self.log(f"BLOCKED click: hwnd={hwnd} is NOT a whitelisted IDE", "error")
            return False

        # === IDE SAFETY GATE 2: Verify the click point is on an IDE window ===
        if not is_point_on_ide_window(screen_x, screen_y):
            self.log(f"BLOCKED click at ({screen_x},{screen_y}): not on an IDE window", "error")
            return False

        try:
            # === SAVE STATE ===
            orig_x, orig_y = win32api.GetCursorPos()
            orig_fg_hwnd = win32gui.GetForegroundWindow()

            # Pre-activate the target window if it isn't the foreground window.
            # Electron/Chromium apps often swallow the first physical click if the window is inactive.
            if hwnd and hwnd != orig_fg_hwnd:
                self._activate_window(hwnd)
                time.sleep(0.05)

            # === CLICK (atomic: move → down → up) ===
            sendinput_click(screen_x, screen_y, hold_ms=15)

            # === RESTORE STATE ===
            # Electron apps need a tiny moment to process the mousedown/up events through their JS event loop
            time.sleep(0.05)
            restore_mouse(orig_x, orig_y)
            
            # Restore keyboard focus to whatever the user was looking at
            if orig_fg_hwnd:
                self._activate_window(orig_fg_hwnd)
                
            # As requested, physically click where the mouse was resting to refocus the text input
            # Safety: ONLY do this if the mouse is over an IDE window to avoid misclicking other apps
            if is_point_on_ide_window(orig_x, orig_y):
                # Ensure the OS registered the mouse jump back before firing the click
                time.sleep(0.04)
                sendinput_click(orig_x, orig_y, hold_ms=25)

            self._record_click(detection.btn_type, hwnd)
            self.log(
                f"✓ CLICKED {detection.btn_type.upper()} at ({screen_x},{screen_y}) "
                f"[{detection.method}, {detection.confidence:.0%}]",
                "success"
            )

            # Rate-limited toast: max 1 per 30s
            if TOAST_AVAILABLE and (time.time() - self._last_toast_time) >= 30.0:
                try:
                    _toaster.show_toast(
                        "Antigravity Autoclicker",
                        f"Clicked: {detection.btn_type}",
                        duration=2,
                        threaded=True
                    )
                    self._last_toast_time = time.time()
                except Exception:
                    pass

            return True

        except Exception as e:
            self.log(f"Click error: {e}", "error")
            return False

    @staticmethod
    def _activate_window(hwnd):
        """Bring a window to the foreground using the AttachThreadInput trick."""
        try:
            if not win32gui.IsWindow(hwnd):
                return False

            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, 9)

            target_thread, _ = win32process.GetWindowThreadProcessId(hwnd)
            curr_thread = win32api.GetCurrentThreadId()

            attached = False
            if target_thread != curr_thread:
                if ctypes.windll.user32.AttachThreadInput(curr_thread, target_thread, True):
                    attached = True
                try:
                    win32gui.SetForegroundWindow(hwnd)
                finally:
                    if attached:
                        ctypes.windll.user32.AttachThreadInput(curr_thread, target_thread, False)
            else:
                win32gui.SetForegroundWindow(hwnd)

            time.sleep(0.01)
            actual_fg = win32gui.GetForegroundWindow()
            return actual_fg == hwnd
        except Exception:
            try:
                win32gui.ShowWindow(hwnd, 9)
                win32gui.BringWindowToTop(hwnd)
                win32gui.SetForegroundWindow(hwnd)
            except Exception:
                pass
            return False

    def _scan_loop(self):
        """Main scanning loop — runs in background thread."""
        self.log("Scanning for target windows...", "info")
        scan_count = 0

        while not self.stop_event.is_set():
            try:
                if self.paused:
                    time.sleep(0.5)
                    continue

                # FOCUS COOLDOWN: Skip clicking when user just focused our window
                if self._is_focus_cooldown_active():
                    remaining = self._focus_cooldown_until - time.time()
                    if remaining > 0 and int(remaining * 2) % 2 == 0:  # Log every ~1s
                        self.log(f"⏸️ Focus cooldown: {remaining:.0f}s remaining...", "info")
                    time.sleep(0.5)
                    continue

                # TYPING GUARD: Only pause if the IDE window is foreground AND user is typing
                # (GetAsyncKeyState is system-wide, so we must scope it to the IDE window)
                # This check is deferred until after we find the target window below

                interval = self.settings.get("check_interval", 0.5)
                profile = self._get_profile()

                # Find target windows
                windows = self._find_windows()
                if not windows:
                    # If auto-detect enabled, try finding VS Code / any IDE
                    if self.settings.get("auto_detect_window", True):
                        windows = find_target_windows([
                            "visual studio code", "vs code", "cursor",
                            "windsurf", "antigravity"
                        ])
                
                if not windows:
                    scan_count += 1
                    if scan_count % 20 == 1:
                        self.log("No target windows found. Is the IDE open?", "warning")
                    time.sleep(interval * 2)
                    continue

                scan_count += 1

                clicked_anything = False
                
                # Iterate through ALL matching windows
                for hwnd, title, rect in windows:
                        self.detected_window_title = title

                        # (No auto-focus: if windows are side-by-side, they will just be scanned where they are)

                        if scan_count % 30 == 1:
                            w = rect[2] - rect[0]
                            h = rect[3] - rect[1]
                            self.log(f"Scanning: {title[:50]}... ({w}x{h}, {len(windows)} match{'es' if len(windows) > 1 else ''})", "info")

                        # Auto-detect profile from window title
                        if self.settings.get("auto_detect_window", True):
                            detected_key = auto_detect_profile(title)
                            if detected_key and detected_key != self.settings.get("profile"):
                                self.detected_profile = detected_key
                                profile = PROFILES.get(detected_key, profile)

                        # Calculate scan region
                        scan_bbox = self._get_scan_region(rect)
                        self.last_scan_region = scan_bbox
                        scan_left, scan_top, scan_right, scan_bottom = scan_bbox

                        # TYPING GUARD: Pause scanning if the user is typing ANYWHERE.
                        # This prevents the autoclicker from stealing focus mid-sentence.
                        try:
                            if self._is_user_typing():
                                time.sleep(0.3)
                                continue
                        except Exception:
                            pass

                        if scan_right <= scan_left or scan_bottom <= scan_top:
                            time.sleep(interval)
                            continue

                        # Capture screenshot of the scan region
                        # SAFETY: Clamp scan_bbox to the IDE window rect to prevent
                        # capturing anything outside the IDE window
                        try:
                            clamped_bbox = (
                                max(scan_left, rect[0]),
                                max(scan_top, rect[1]),
                                min(scan_right, rect[2]),
                                min(scan_bottom, rect[3]),
                            )
                            if not is_rect_inside_ide_window(clamped_bbox, rect):
                                logging.debug(f"Scan region outside IDE window, skipping")
                                time.sleep(interval)
                                continue
                            screenshot = ImageGrab.grab(bbox=clamped_bbox)
                            # Update scan offsets to match clamped box
                            scan_left, scan_top, scan_right, scan_bottom = clamped_bbox
                            frame = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
                        except Exception as e:
                            logging.debug(f"Screenshot error: {e}")
                            time.sleep(interval)
                            continue

                        if frame is None or frame.size == 0:
                            time.sleep(interval)
                            continue

                        # Detect buttons via color
                        detections = detect_buttons_color(frame, profile, self.settings)

                        # If color detection found nothing, try template matching (fast, ~2ms)
                        if not detections and self.settings.get("use_ocr", True):
                            detections = detect_buttons_template(
                                frame, profile, self.settings
                            )

                        # Merge overlapping detections
                        detections = merge_detections(detections)

                        if scan_count % 30 == 1 and not detections:
                            self.log(f"Scan #{scan_count}: No buttons in region ({scan_left},{scan_top})-({scan_right},{scan_bottom})", "info")

                        # Click the best detection
                        if detections:
                            # For "run" buttons: pick the NARROWEST one.
                            # "Run" is always shorter than "Always run" or "Ask every time".
                            # This handles any DPI scaling since we compare relative widths.
                            run_detections = [d for d in detections if d.btn_type == "run"]
                            other_detections = [d for d in detections if d.btn_type != "run"]

                            if len(run_detections) > 1:
                                # Multiple run buttons — pick narrowest (that's the real "Run")
                                run_detections.sort(key=lambda d: d.w)
                                best_run = run_detections[0]
                                self.log(f"Multiple run buttons: picked narrowest ({best_run.w}px) over wider ({run_detections[-1].w}px)", "info")
                            elif len(run_detections) == 1:
                                best_run = run_detections[0]
                            else:
                                best_run = None

                            # Pick the best overall detection
                            if other_detections:
                                # For allow/confirm buttons, the larger one is usually "allow for this conversation"
                                # We sort by area descending to ensure we click the biggest one.
                                other_detections.sort(key=lambda d: d.w * d.h, reverse=True)
                                best = other_detections[0]  # Non-run buttons get priority (busy, accept, etc.)
                            elif best_run:
                                best = best_run
                            else:
                                best = detections[0]

                            # FINAL: "Always run" guard — if this is the ONLY run button and
                            # it's suspiciously wide, skip it. Normal "Run" ≈ 50-90px.
                            should_click = True
                            if best.btn_type == "run" and len(run_detections) == 1:
                                if best.w > 100:
                                    self.log(f"Skipping wide Run button ({best.w}px) — likely 'Always run'", "warning")
                                    should_click = False

                            if should_click:
                                # Convert frame-relative coords to screen coords
                                screen_x = scan_left + best.cx
                                screen_y = scan_top + best.cy

                                if best.btn_type == "busy":
                                    # AI is generating — scroll down only if new content appeared
                                    self._smart_scroll_down(frame, scan_bbox, hwnd)
                                    time.sleep(1.0)
                                else:
                                    # === ONLY move mouse here — confirmed button to click ===
                                    self._perform_click(screen_x, screen_y, best, hwnd)
                                    # Track click rate for loop detection
                                    if self.loop_detector.record_click(best.btn_type):
                                        self.log("⚠️ Rapid clicking detected (4+ in 60s)!", "warning")
                                    # Short pause after click to let UI update
                                    time.sleep(0.5)
                                    clicked_anything = True
                                    break  # Break out of window loop if we clicked something
                            else:
                                # Rejected detection, sleep and try again
                                pass
                        else:
                            # No buttons detected — DO NOT move the mouse or scroll randomly.
                            # Only scroll down if we detect new content at the bottom of the chat
                            # (i.e., the AI is still generating and chat needs to follow along).
                            self._smart_scroll_down(frame, scan_bbox, hwnd)
                
                if not clicked_anything:
                    time.sleep(interval)
                else:
                    time.sleep(0.5)

            except Exception as e:
                logging.error(f"Scan loop error: {e}", exc_info=True)
                self.log(f"Scan error: {e}", "error")
                time.sleep(1.0)
                
        self.running = False


# ——————————————————————————————————————————————————————————————————————
# GUI — Tabbed interface v2.0
# ——————————————————————————————————————————————————————————————————————

COLORS = {
    "bg_dark":      "#0a0e17",
    "bg_secondary": "#0f1420",
    "bg_panel":     "#111827",
    "bg_card":      "#141e30",
    "bg_card_hover":"#1a2236",
    "bg_sidebar":   "#0c1019",
    "bg_input":     "#0d1117",
    "border":       "#1e293b",
    "border_active":"#00d4ff40",
    "text":         "#e2e8f0",
    "text_dim":     "#94a3b8",
    "text_muted":   "#64748b",
    "accent":       "#00D4FF",
    "accent_dim":   "#0a2a3a",
    "green":        "#10b981",
    "green_dim":    "#0a2a1f",
    "red":          "#ef4444",
    "red_dim":      "#2a0a0a",
    "yellow":       "#f59e0b",
    "yellow_dim":   "#2a1f0a",
    "orange":       "#f97316",
    "purple":       "#8B5CF6",
    "purple_dim":   "#1a0a3a",
    "pink":         "#ec4899",
}

# Font families
FONT_MAIN = "Segoe UI"
FONT_MONO = "Cascadia Code"
FONT_HEADING = "Segoe UI Semibold"

# Sidebar width  
SIDEBAR_WIDTH = 200


class AntigravityAutoclickerApp:
    """Main GUI application v2.0 — tabbed interface with AI Agent."""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("⚡ Antigravity Autoclicker v2.0")
        self.root.geometry("960x750")
        self.root.minsize(800, 600)
        self.root.configure(bg=COLORS["bg_dark"])
        try:
            self.root.iconbitmap(default="")
        except Exception:
            pass

        self.settings = load_settings()
        self.log_queue = queue.Queue()
        self.agent_chat_queue = queue.Queue()

        # Core engines
        self.engine = ScanEngine(log_callback=self._enqueue_log)
        self.overlay = DebugOverlay(self.root)
        self.ollama = OllamaClient(
            self.settings.get("ollama_host", "localhost"),
            self.settings.get("ollama_port", 11434))
        self.agent = AgentBrain(
            self.ollama, self.engine,
            log_callback=self._enqueue_log,
            status_callback=self._set_agent_status,
            chat_callback=self._enqueue_agent_chat)
        self.agent.settings = self.settings
        self._tray_icon = None

        # Tkinter variables
        self.var_profile = tk.StringVar(value=self.settings.get("profile", "antigravity"))
        self.var_running = tk.BooleanVar(value=False)
        self.var_run = tk.BooleanVar(value=self.settings.get("detect_run", True))
        self.var_accept = tk.BooleanVar(value=self.settings.get("detect_accept", True))
        self.var_confirm = tk.BooleanVar(value=self.settings.get("detect_confirm", True))
        self.var_ocr = tk.BooleanVar(value=self.settings.get("use_ocr", True))
        self.var_auto_detect = tk.BooleanVar(value=self.settings.get("auto_detect_window", True))
        self.var_interval = tk.StringVar(value=str(self.settings.get("check_interval", 0.5)))
        self.var_confidence = tk.StringVar(value=str(self.settings.get("confidence", 0.70)))
        self.var_agent_mode = tk.StringVar(value=self.settings.get("agent_mode", "build"))
        self.var_agent_model = tk.StringVar(value=self.settings.get("agent_model", "phi3:mini"))
        self.var_debug_overlay = tk.BooleanVar(value=self.settings.get("debug_overlay", False))
        self.var_loop_detect = tk.BooleanVar(value=self.settings.get("loop_detect_enabled", True))
        self._agent_status = "Idle"

        self._setup_styles()
        self._build_ui()
        self._poll_log_queue()
        self._poll_agent_chat()
        self._update_status()

        self._hotkey_id = 1
        self._hotkey_registered = False
        self._bind_hotkey()
        self._poll_hotkey()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.bind("<FocusIn>", self._on_window_focus)
        self._log_info("\u26a1 Antigravity Autoclicker v2.0 ready.", "info")
        threading.Thread(target=self._check_ollama, daemon=True).start()

        # File watcher for auto-restart on updates
        self._script_path = os.path.abspath(__file__)
        self._script_mtime = os.path.getmtime(self._script_path)
        self._poll_file_changes()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Dark.TFrame", background=COLORS["bg_dark"])
        style.configure("Panel.TFrame", background=COLORS["bg_panel"])
        style.configure("Card.TFrame", background=COLORS["bg_card"])
        style.configure("Sidebar.TFrame", background=COLORS["bg_sidebar"])
        style.configure("Dark.TLabel", background=COLORS["bg_dark"],
                        foreground=COLORS["text"], font=(FONT_MAIN, 10))
        style.configure("Title.TLabel", background=COLORS["bg_dark"],
                        foreground=COLORS["accent"], font=(FONT_HEADING, 18, "bold"))
        style.configure("Subtitle.TLabel", background=COLORS["bg_dark"],
                        foreground=COLORS["text_dim"], font=(FONT_MAIN, 10))
        style.configure("Status.TLabel", background=COLORS["bg_dark"],
                        foreground=COLORS["green"], font=(FONT_MAIN, 10, "bold"))
        style.configure("StatusOff.TLabel", background=COLORS["bg_dark"],
                        foreground=COLORS["red"], font=(FONT_MAIN, 10, "bold"))
        style.configure("Dim.TLabel", background=COLORS["bg_dark"],
                        foreground=COLORS["text_dim"], font=(FONT_MAIN, 9))
        style.configure("CardLabel.TLabel", background=COLORS["bg_card"],
                        foreground=COLORS["text"], font=(FONT_MAIN, 10))
        style.configure("CardDim.TLabel", background=COLORS["bg_card"],
                        foreground=COLORS["text_dim"], font=(FONT_MAIN, 9))
        style.configure("CardTitle.TLabel", background=COLORS["bg_card"],
                        foreground=COLORS["text_dim"], font=(FONT_MAIN, 10, "bold"))
        style.configure("SidebarLabel.TLabel", background=COLORS["bg_sidebar"],
                        foreground=COLORS["text_dim"], font=(FONT_MAIN, 9))
        style.configure("SidebarBrand.TLabel", background=COLORS["bg_sidebar"],
                        foreground=COLORS["accent"], font=(FONT_HEADING, 13, "bold"))
        style.configure("SidebarVersion.TLabel", background=COLORS["bg_sidebar"],
                        foreground=COLORS["text_muted"], font=(FONT_MONO, 8))
        style.configure("Mono.TLabel", background=COLORS["bg_dark"],
                        foreground=COLORS["text"], font=(FONT_MONO, 10))
        style.configure("MonoAccent.TLabel", background=COLORS["bg_dark"],
                        foreground=COLORS["accent"], font=(FONT_MONO, 12, "bold"))
        # Combobox
        style.configure("Dark.TCombobox", fieldbackground=COLORS["bg_input"],
                        background=COLORS["bg_card"], foreground=COLORS["text"],
                        font=(FONT_MAIN, 10))
        style.map("Dark.TCombobox",
                  fieldbackground=[("readonly", COLORS["bg_input"])],
                  foreground=[("readonly", COLORS["text"])])

    # ── Helper: create a styled card frame ──
    def _make_card(self, parent, **kwargs):
        """Create a card-style frame with border and rounded appearance."""
        card = tk.Frame(parent, bg=COLORS["bg_card"], highlightbackground=COLORS["border"],
                        highlightthickness=1, padx=16, pady=12, **kwargs)
        def _on_enter(e):
            card.configure(highlightbackground=COLORS["accent"])
        def _on_leave(e):
            card.configure(highlightbackground=COLORS["border"])
        card.bind("<Enter>", _on_enter)
        card.bind("<Leave>", _on_leave)
        return card

    # ── Helper: create a stat mini card ──
    def _make_stat_card(self, parent, icon, label, value_var, color):
        """Create a stat mini card with icon, value, and label."""
        card = self._make_card(parent)
        icon_frame = tk.Frame(card, bg=color, width=36, height=36)
        icon_frame.pack(side=tk.LEFT, padx=(0, 12))
        icon_frame.pack_propagate(False)
        tk.Label(icon_frame, text=icon, font=(FONT_MAIN, 14), bg=color, fg="#FFFFFF").place(relx=0.5, rely=0.5, anchor="center")
        info = tk.Frame(card, bg=COLORS["bg_card"])
        info.pack(side=tk.LEFT, fill=tk.X)
        val_lbl = tk.Label(info, textvariable=value_var, font=(FONT_MONO, 16, "bold"),
                           bg=COLORS["bg_card"], fg=COLORS["text"], anchor="w")
        val_lbl.pack(anchor="w")
        tk.Label(info, text=label, font=(FONT_MAIN, 9), bg=COLORS["bg_card"],
                 fg=COLORS["text_muted"], anchor="w").pack(anchor="w")
        return card, val_lbl

    # ── Helper: nav button for sidebar ──
    def _make_nav_btn(self, parent, icon, label, page_name):
        """Create a sidebar navigation button."""
        btn = tk.Frame(parent, bg=COLORS["bg_sidebar"], cursor="hand2", padx=12, pady=7)
        btn.pack(fill=tk.X)
        tk.Label(btn, text=icon, font=(FONT_MAIN, 13), bg=COLORS["bg_sidebar"],
                 fg=COLORS["text_dim"], width=2).pack(side=tk.LEFT, padx=(0, 8))
        lbl = tk.Label(btn, text=label, font=(FONT_MAIN, 11), bg=COLORS["bg_sidebar"],
                       fg=COLORS["text_dim"], anchor="w")
        lbl.pack(side=tk.LEFT, fill=tk.X)
        indicator = tk.Frame(btn, bg=COLORS["bg_sidebar"], width=3, height=24)
        indicator.pack(side=tk.RIGHT)
        def _select(e=None):
            self._select_page(page_name)
        for w in [btn, lbl]:
            w.bind("<Button-1>", _select)
        self._nav_buttons[page_name] = (btn, lbl, indicator)
        return btn

    def _select_page(self, page_name):
        """Switch to a different page and update sidebar highlighting."""
        self._current_page = page_name
        # Update sidebar highlights
        for name, (btn, lbl, indicator) in self._nav_buttons.items():
            if name == page_name:
                btn.configure(bg=COLORS["accent_dim"])
                lbl.configure(bg=COLORS["accent_dim"], fg=COLORS["accent"])
                indicator.configure(bg=COLORS["accent"])
                for child in btn.winfo_children():
                    if isinstance(child, tk.Label):
                        child.configure(bg=COLORS["accent_dim"])
            else:
                btn.configure(bg=COLORS["bg_sidebar"])
                lbl.configure(bg=COLORS["bg_sidebar"], fg=COLORS["text_dim"])
                indicator.configure(bg=COLORS["bg_sidebar"])
                for child in btn.winfo_children():
                    if isinstance(child, tk.Label):
                        child.configure(bg=COLORS["bg_sidebar"])
        # Show/hide page frames
        for name, frame in self._page_frames.items():
            if name == page_name:
                frame.pack(fill=tk.BOTH, expand=True)
            else:
                frame.pack_forget()

    def _build_ui(self):
        self._nav_buttons = {}
        self._page_frames = {}
        self._current_page = "clicker"

        # Main horizontal layout
        main_layout = tk.Frame(self.root, bg=COLORS["bg_dark"])
        main_layout.pack(fill=tk.BOTH, expand=True)

        # ═══════════ SIDEBAR ═══════════
        sidebar = tk.Frame(main_layout, bg=COLORS["bg_sidebar"], width=SIDEBAR_WIDTH)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        # Brand
        brand = tk.Frame(sidebar, bg=COLORS["bg_sidebar"], padx=16, pady=14)
        brand.pack(fill=tk.X)
        tk.Label(brand, text="⚡ Antigravity", font=(FONT_HEADING, 14, "bold"),
                 bg=COLORS["bg_sidebar"], fg=COLORS["accent"]).pack(anchor="w")
        tk.Label(brand, text="v2.0 — Autoclicker", font=(FONT_MONO, 8),
                 bg=COLORS["bg_sidebar"], fg=COLORS["text_muted"]).pack(anchor="w")
        # Separator
        tk.Frame(sidebar, bg=COLORS["border"], height=1).pack(fill=tk.X, padx=12)

        # Nav sections
        tk.Label(sidebar, text="CONTROLS", font=(FONT_MAIN, 8, "bold"),
                 bg=COLORS["bg_sidebar"], fg=COLORS["text_muted"], anchor="w",
                 padx=16, pady=(10, 2)).pack(fill=tk.X)
        self._make_nav_btn(sidebar, "🖱️", "Auto-Clicker", "clicker")
        self._make_nav_btn(sidebar, "🤖", "AI Agent", "agent")

        tk.Label(sidebar, text="CONFIGURE", font=(FONT_MAIN, 8, "bold"),
                 bg=COLORS["bg_sidebar"], fg=COLORS["text_muted"], anchor="w",
                 padx=16, pady=(10, 2)).pack(fill=tk.X)
        self._make_nav_btn(sidebar, "⚙️", "Settings", "settings")
        self._make_nav_btn(sidebar, "🔎", "Debug", "debug")

        # Spacer
        tk.Frame(sidebar, bg=COLORS["bg_sidebar"]).pack(fill=tk.BOTH, expand=True)

        # Sidebar footer — status
        tk.Frame(sidebar, bg=COLORS["border"], height=1).pack(fill=tk.X, padx=12)
        self._sidebar_footer = tk.Frame(sidebar, bg=COLORS["bg_sidebar"], padx=12, pady=8)
        self._sidebar_footer.pack(fill=tk.X)
        self._sidebar_status_dot = tk.Label(self._sidebar_footer, text="●", font=(FONT_MAIN, 14),
                                             bg=COLORS["bg_sidebar"], fg=COLORS["red"])
        self._sidebar_status_dot.pack(side=tk.LEFT, padx=(0, 6))
        self._sidebar_status_text = tk.Label(self._sidebar_footer, text="Standby",
                                              font=(FONT_MAIN, 10), bg=COLORS["bg_sidebar"],
                                              fg=COLORS["text_dim"])
        self._sidebar_status_text.pack(side=tk.LEFT)

        # ═══════════ MAIN CONTENT ═══════════
        content_area = tk.Frame(main_layout, bg=COLORS["bg_dark"])
        content_area.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Top header bar
        header = tk.Frame(content_area, bg=COLORS["bg_dark"], padx=20, pady=12)
        header.pack(fill=tk.X)
        self._page_title = tk.Label(header, text="Auto-Clicker", font=(FONT_HEADING, 20, "bold"),
                                    bg=COLORS["bg_dark"], fg=COLORS["text"])
        self._page_title.pack(side=tk.LEFT)
        self._page_subtitle = tk.Label(header, text="Detect and click IDE buttons automatically",
                                       font=(FONT_MAIN, 10), bg=COLORS["bg_dark"],
                                       fg=COLORS["text_dim"])
        self._page_subtitle.pack(side=tk.LEFT, padx=(12, 0), pady=(4, 0))

        # Status badges in header
        hdr_right = tk.Frame(header, bg=COLORS["bg_dark"])
        hdr_right.pack(side=tk.RIGHT)
        self.lbl_clicks = tk.Label(hdr_right, text="0", font=(FONT_MONO, 14, "bold"),
                                   bg=COLORS["bg_dark"], fg=COLORS["accent"])
        self.lbl_clicks.pack(side=tk.RIGHT, padx=(8, 0))
        tk.Label(hdr_right, text="Clicks", font=(FONT_MAIN, 9),
                 bg=COLORS["bg_dark"], fg=COLORS["text_muted"]).pack(side=tk.RIGHT, padx=(0, 4))
        self.lbl_status = tk.Label(hdr_right, text="● STANDBY", font=(FONT_MAIN, 10, "bold"),
                                   bg=COLORS["bg_dark"], fg=COLORS["red"])
        self.lbl_status.pack(side=tk.RIGHT, padx=(0, 20))

        # Page container
        page_container = tk.Frame(content_area, bg=COLORS["bg_dark"])
        page_container.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 5))

        # Build pages
        for page_name, builder in [("clicker", self._build_clicker_page),
                                    ("agent", self._build_agent_page),
                                    ("settings", self._build_settings_page),
                                    ("debug", self._build_debug_page)]:
            frame = tk.Frame(page_container, bg=COLORS["bg_dark"])
            self._page_frames[page_name] = frame
            builder(frame)

        # Activity log at bottom
        log_frame = tk.Frame(content_area, bg=COLORS["bg_dark"], padx=20)
        log_frame.pack(fill=tk.X, pady=(5, 8))
        log_header = tk.Frame(log_frame, bg=COLORS["bg_dark"])
        log_header.pack(fill=tk.X, pady=(0, 4))
        tk.Label(log_header, text="Activity Log", font=(FONT_MAIN, 10, "bold"),
                 bg=COLORS["bg_dark"], fg=COLORS["text_dim"]).pack(side=tk.LEFT)
        tk.Button(log_header, text="Clear", font=(FONT_MAIN, 8), bg=COLORS["bg_card"],
                  fg=COLORS["text_dim"], relief=tk.FLAT, padx=8, pady=1, bd=0,
                  command=self._clear_log, cursor="hand2").pack(side=tk.RIGHT)
        tk.Label(log_header, text="Ctrl+Shift+P to pause", font=(FONT_MAIN, 8),
                 bg=COLORS["bg_dark"], fg=COLORS["text_muted"]).pack(side=tk.RIGHT, padx=10)

        self.log_text = scrolledtext.ScrolledText(
            log_frame, wrap=tk.WORD, bg=COLORS["bg_panel"], fg=COLORS["text_dim"],
            insertbackground=COLORS["text"], font=(FONT_MONO, 9),
            relief=tk.FLAT, state=tk.DISABLED, height=6,
            highlightbackground=COLORS["border"], highlightthickness=1)
        self.log_text.pack(fill=tk.X)
        for tag, clr in [("info", COLORS["text_dim"]), ("success", COLORS["green"]),
                         ("warning", COLORS["yellow"]), ("error", COLORS["red"]),
                         ("detect", COLORS["accent"])]:
            self.log_text.tag_configure(tag, foreground=clr)

        # Select initial page
        self._select_page("clicker")

    # ═══════════ CLICKER PAGE ═══════════
    def _build_clicker_page(self, parent):
        # Top row: Start/Stop + Pause
        ctrl = tk.Frame(parent, bg=COLORS["bg_dark"])
        ctrl.pack(fill=tk.X, pady=(0, 12))

        self.btn_start = tk.Button(ctrl, text="▶ START", font=(FONT_MAIN, 11, "bold"),
            bg=COLORS["green"], fg="#000000", activebackground="#0a8c5f",
            relief=tk.FLAT, padx=22, pady=10, command=self._start_scanner, cursor="hand2")
        self.btn_start.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_stop = tk.Button(ctrl, text="■ STOP", font=(FONT_MAIN, 11, "bold"),
            bg=COLORS["bg_card"], fg=COLORS["red"], activebackground=COLORS["bg_card_hover"],
            relief=tk.FLAT, padx=14, pady=10, command=self._stop_scanner,
            state=tk.DISABLED, cursor="hand2", highlightbackground=COLORS["border"], highlightthickness=1)
        self.btn_stop.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_pause = tk.Button(ctrl, text="⏸ Pause", font=(FONT_MAIN, 11),
            bg=COLORS["bg_card"], fg=COLORS["yellow"], activebackground=COLORS["bg_card_hover"],
            relief=tk.FLAT, padx=14, pady=10, command=self._toggle_pause,
            state=tk.DISABLED, cursor="hand2", highlightbackground=COLORS["border"], highlightthickness=1)
        self.btn_pause.pack(side=tk.LEFT, padx=(0, 8))

        # Restart
        tk.Button(ctrl, text="🔄", font=(FONT_MAIN, 12), bg=COLORS["bg_card"],
                  fg=COLORS["text_dim"], relief=tk.FLAT, padx=10, pady=8,
                  command=self._restart, cursor="hand2",
                  highlightbackground=COLORS["border"], highlightthickness=1).pack(side=tk.RIGHT)

        # Stats row
        stats_frame = tk.Frame(parent, bg=COLORS["bg_dark"])
        stats_frame.pack(fill=tk.X, pady=(0, 12))

        self._var_stat_profile = tk.StringVar(value="antigravity")
        self._var_stat_clicks = tk.StringVar(value="0")
        self._var_stat_window = tk.StringVar(value="—")
        self._var_stat_ocr = tk.StringVar(value="Yes" if OCR_AVAILABLE else "No")

        for i, (icon, lbl, var, clr) in enumerate([
            ("🎯", "Profile", self._var_stat_profile, COLORS["accent"]),
            ("🖱️", "Total Clicks", self._var_stat_clicks, COLORS["green"]),
            ("🪟", "Target Window", self._var_stat_window, COLORS["purple"]),
            ("👁️", "OCR Ready", self._var_stat_ocr, COLORS["yellow"]),
        ]):
            card, _ = self._make_stat_card(stats_frame, icon, lbl, var, clr)
            card.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0 if i == 0 else 6, 0))

        # Profile selector
        profile_card = self._make_card(parent)
        profile_card.pack(fill=tk.X, pady=(0, 12))
        tk.Label(profile_card, text="TARGET PROFILE", font=(FONT_MAIN, 9, "bold"),
                 bg=COLORS["bg_card"], fg=COLORS["text_muted"]).pack(anchor="w", pady=(0, 8))
        profile_grid = tk.Frame(profile_card, bg=COLORS["bg_card"])
        profile_grid.pack(fill=tk.X)
        for key, profile in PROFILES.items():
            name = profile.get("name", key)
            pf = tk.Frame(profile_grid, bg=COLORS["bg_panel"], padx=12, pady=8,
                          cursor="hand2", highlightbackground=COLORS["border"], highlightthickness=1)
            pf.pack(side=tk.LEFT, padx=(0, 6), fill=tk.X, expand=True)
            tk.Label(pf, text=name[:20], font=(FONT_MAIN, 9, "bold"),
                     bg=COLORS["bg_panel"], fg=COLORS["text"]).pack(anchor="w")
            tk.Label(pf, text=key, font=(FONT_MONO, 8),
                     bg=COLORS["bg_panel"], fg=COLORS["text_muted"]).pack(anchor="w")
            pf.bind("<Button-1>", lambda e, k=key: self._set_profile(k))
            for child in pf.winfo_children():
                child.bind("<Button-1>", lambda e, k=key: self._set_profile(k))
        # Hidden combobox for compatibility
        self.combo_profile = ttk.Combobox(profile_card, textvariable=self.var_profile,
            values=list(PROFILES.keys()), state="readonly", width=18, font=(FONT_MAIN, 10))
        self.combo_profile.bind("<<ComboboxSelected>>", self._on_profile_change)
        self.lbl_profile_desc = tk.Label(profile_card, text="", bg=COLORS["bg_card"],
                                         fg=COLORS["text_dim"], font=(FONT_MAIN, 9))
        # These are hidden — profiles are selected via the grid above

        # Detection settings card
        detect_card = self._make_card(parent)
        detect_card.pack(fill=tk.X, pady=(0, 12))
        tk.Label(detect_card, text="DETECTION SETTINGS", font=(FONT_MAIN, 9, "bold"),
                 bg=COLORS["bg_card"], fg=COLORS["text_muted"]).pack(anchor="w", pady=(0, 8))
        toggles = tk.Frame(detect_card, bg=COLORS["bg_card"])
        toggles.pack(fill=tk.X)
        for txt, var in [("🟢 Run/Continue", self.var_run), ("✅ Accept All", self.var_accept),
                         ("☑️ Confirm", self.var_confirm), ("👁️ OCR Assist", self.var_ocr),
                         ("🔍 Auto-Detect IDE", self.var_auto_detect)]:
            tk.Checkbutton(toggles, text=txt, variable=var, bg=COLORS["bg_card"],
                fg=COLORS["text"], selectcolor=COLORS["bg_panel"],
                activebackground=COLORS["bg_card"], activeforeground=COLORS["text"],
                font=(FONT_MAIN, 10), command=self._save_settings).pack(side=tk.LEFT, padx=(0, 12))

        # Interval / confidence
        params = tk.Frame(detect_card, bg=COLORS["bg_card"], pady=6)
        params.pack(fill=tk.X)
        tk.Label(params, text="Interval:", font=(FONT_MAIN, 10), bg=COLORS["bg_card"],
                 fg=COLORS["text_dim"]).pack(side=tk.LEFT, padx=(0, 4))
        e1 = tk.Entry(params, textvariable=self.var_interval, width=5, bg=COLORS["bg_input"],
            fg=COLORS["text"], insertbackground=COLORS["text"], font=(FONT_MONO, 10),
            relief=tk.FLAT, highlightbackground=COLORS["border"], highlightthickness=1)
        e1.pack(side=tk.LEFT, padx=(0, 4), ipady=3)
        e1.bind("<FocusOut>", lambda e: self._save_settings())
        tk.Label(params, text="sec", font=(FONT_MAIN, 9), bg=COLORS["bg_card"],
                 fg=COLORS["text_muted"]).pack(side=tk.LEFT, padx=(0, 16))
        tk.Label(params, text="Confidence:", font=(FONT_MAIN, 10), bg=COLORS["bg_card"],
                 fg=COLORS["text_dim"]).pack(side=tk.LEFT, padx=(0, 4))
        e2 = tk.Entry(params, textvariable=self.var_confidence, width=5, bg=COLORS["bg_input"],
            fg=COLORS["text"], insertbackground=COLORS["text"], font=(FONT_MONO, 10),
            relief=tk.FLAT, highlightbackground=COLORS["border"], highlightthickness=1)
        e2.pack(side=tk.LEFT, padx=(0, 4), ipady=3)
        e2.bind("<FocusOut>", lambda e: self._save_settings())

        self.lbl_window = tk.Label(params, text="Window: —", font=(FONT_MAIN, 9),
                                   bg=COLORS["bg_card"], fg=COLORS["text_muted"])
        self.lbl_window.pack(side=tk.RIGHT)
        self._update_profile_desc()

    def _set_profile(self, key):
        """Set profile via the profile card grid."""
        self.var_profile.set(key)
        self._on_profile_change()
        self._var_stat_profile.set(key)

    # ═══════════ AGENT PAGE ═══════════
    def _build_agent_page(self, parent):
        # Top control bar
        ctrl = tk.Frame(parent, bg=COLORS["bg_dark"])
        ctrl.pack(fill=tk.X, pady=(0, 10))

        # Mode selector
        mode_card = self._make_card(ctrl)
        mode_card.pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(mode_card, text="Mode", font=(FONT_MAIN, 9, "bold"),
                 bg=COLORS["bg_card"], fg=COLORS["text_muted"]).pack(anchor="w")
        mode_combo = ttk.Combobox(mode_card, textvariable=self.var_agent_mode,
            values=list(AGENT_MODES.keys()), state="readonly", width=12, font=(FONT_MAIN, 10))
        mode_combo.pack(anchor="w", pady=(2, 0))

        # Model selector
        model_card = self._make_card(ctrl)
        model_card.pack(side=tk.LEFT, padx=(0, 8))
        tk.Label(model_card, text="Model", font=(FONT_MAIN, 9, "bold"),
                 bg=COLORS["bg_card"], fg=COLORS["text_muted"]).pack(anchor="w")
        self.combo_model = ttk.Combobox(model_card, textvariable=self.var_agent_model,
            values=["phi3:mini"], state="readonly", width=18, font=(FONT_MAIN, 10))
        self.combo_model.pack(anchor="w", pady=(2, 0))

        # Agent buttons
        btn_frame = tk.Frame(ctrl, bg=COLORS["bg_dark"])
        btn_frame.pack(side=tk.RIGHT)
        self.btn_agent_start = tk.Button(btn_frame, text="▶ Start Agent",
            font=(FONT_MAIN, 11, "bold"), bg=COLORS["purple"], fg="#FFFFFF",
            activebackground="#7C4DDB", relief=tk.FLAT, padx=18, pady=8,
            command=self._start_agent, cursor="hand2")
        self.btn_agent_start.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_agent_stop = tk.Button(btn_frame, text="■ Stop",
            font=(FONT_MAIN, 11), bg=COLORS["bg_card"], fg=COLORS["red"],
            activebackground=COLORS["bg_card_hover"], relief=tk.FLAT, padx=14, pady=8,
            command=self._stop_agent, state=tk.DISABLED, cursor="hand2",
            highlightbackground=COLORS["border"], highlightthickness=1)
        self.btn_agent_stop.pack(side=tk.LEFT)

        # Status bar
        status_bar = tk.Frame(parent, bg=COLORS["bg_dark"])
        status_bar.pack(fill=tk.X, pady=(0, 8))
        self.lbl_agent_status = tk.Label(status_bar, text="Status: Idle",
            font=(FONT_MAIN, 10), bg=COLORS["bg_dark"], fg=COLORS["text_dim"])
        self.lbl_agent_status.pack(side=tk.LEFT)
        self.lbl_ollama_status = tk.Label(status_bar, text="Ollama: checking...",
            font=(FONT_MAIN, 10), bg=COLORS["bg_dark"], fg=COLORS["text_dim"])
        self.lbl_ollama_status.pack(side=tk.RIGHT)
        self.lbl_agent_steps = tk.Label(status_bar, text="Steps: 0",
            font=(FONT_MONO, 10, "bold"), bg=COLORS["bg_dark"], fg=COLORS["accent"])
        self.lbl_agent_steps.pack(side=tk.RIGHT, padx=15)

        # Chat display
        chat_frame = tk.Frame(parent, bg=COLORS["bg_dark"])
        chat_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self.agent_chat = scrolledtext.ScrolledText(chat_frame, wrap=tk.WORD,
            bg=COLORS["bg_panel"], fg=COLORS["text"], insertbackground=COLORS["text"],
            font=(FONT_MONO, 10), relief=tk.FLAT, state=tk.DISABLED,
            highlightbackground=COLORS["border"], highlightthickness=1)
        self.agent_chat.pack(fill=tk.BOTH, expand=True)
        self.agent_chat.tag_configure("user", foreground=COLORS["accent"])
        self.agent_chat.tag_configure("agent", foreground=COLORS["green"])
        self.agent_chat.tag_configure("system", foreground=COLORS["yellow"])

        # Input box
        inp_frame = tk.Frame(parent, bg=COLORS["bg_dark"])
        inp_frame.pack(fill=tk.X)
        self.agent_input = tk.Entry(inp_frame, bg=COLORS["bg_input"], fg=COLORS["text"],
            insertbackground=COLORS["text"], font=(FONT_MAIN, 11), relief=tk.FLAT,
            highlightbackground=COLORS["border"], highlightthickness=1)
        self.agent_input.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8, padx=(0, 6))
        self.agent_input.bind("<Return>", lambda e: self._send_agent_msg())
        self.agent_input.insert(0, "Type a task description and click Start Agent...")
        self.agent_input.bind("<FocusIn>", lambda e: self.agent_input.delete(0, tk.END) if self.agent_input.get().startswith("Type") else None)
        tk.Button(inp_frame, text="Send", font=(FONT_MAIN, 10, "bold"), bg=COLORS["accent"],
            fg="#000000", activebackground="#00B8D9", relief=tk.FLAT, padx=18, pady=8,
            command=self._send_agent_msg, cursor="hand2").pack(side=tk.RIGHT)

    # ═══════════ SETTINGS PAGE ═══════════
    def _build_settings_page(self, parent):
        # Display settings card
        disp_card = self._make_card(parent)
        disp_card.pack(fill=tk.X, pady=(0, 12))
        tk.Label(disp_card, text="DISPLAY", font=(FONT_MAIN, 9, "bold"),
                 bg=COLORS["bg_card"], fg=COLORS["text_muted"]).pack(anchor="w", pady=(0, 6))
        for txt, var in [("🔬 Debug Overlay (scan visualization)", self.var_debug_overlay),
                         ("🔄 Loop Detection (detect AI spam)", self.var_loop_detect)]:
            tk.Checkbutton(disp_card, text=txt, variable=var, bg=COLORS["bg_card"],
                fg=COLORS["text"], selectcolor=COLORS["bg_panel"],
                activebackground=COLORS["bg_card"], activeforeground=COLORS["text"],
                font=(FONT_MAIN, 10), command=self._save_settings, anchor="w").pack(anchor="w", pady=2)

        # Ollama settings card
        ollama_card = self._make_card(parent)
        ollama_card.pack(fill=tk.X, pady=(0, 12))
        tk.Label(ollama_card, text="OLLAMA AI ENGINE", font=(FONT_MAIN, 9, "bold"),
                 bg=COLORS["bg_card"], fg=COLORS["text_muted"]).pack(anchor="w", pady=(0, 6))
        btn_row = tk.Frame(ollama_card, bg=COLORS["bg_card"])
        btn_row.pack(fill=tk.X, pady=4)
        tk.Button(btn_row, text="🌐 Install Ollama", font=(FONT_MAIN, 10),
            bg=COLORS["bg_panel"], fg=COLORS["accent"], relief=tk.FLAT, padx=14, pady=6,
            cursor="hand2", highlightbackground=COLORS["border"], highlightthickness=1,
            command=lambda: webbrowser.open("https://ollama.com")).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn_row, text="⬇️ Pull Selected Model", font=(FONT_MAIN, 10),
            bg=COLORS["bg_panel"], fg=COLORS["green"], relief=tk.FLAT, padx=14, pady=6,
            cursor="hand2", highlightbackground=COLORS["border"], highlightthickness=1,
            command=self._pull_model).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(btn_row, text="🔄 Refresh Models", font=(FONT_MAIN, 10),
            bg=COLORS["bg_panel"], fg=COLORS["accent"], relief=tk.FLAT, padx=14, pady=6,
            cursor="hand2", highlightbackground=COLORS["border"], highlightthickness=1,
            command=lambda: threading.Thread(target=self._check_ollama, daemon=True).start()
            ).pack(side=tk.LEFT)

        # System settings card
        sys_card = self._make_card(parent)
        sys_card.pack(fill=tk.X, pady=(0, 12))
        tk.Label(sys_card, text="SYSTEM", font=(FONT_MAIN, 9, "bold"),
                 bg=COLORS["bg_card"], fg=COLORS["text_muted"]).pack(anchor="w", pady=(0, 6))
        sys_btns = tk.Frame(sys_card, bg=COLORS["bg_card"])
        sys_btns.pack(fill=tk.X, pady=4)
        tk.Button(sys_btns, text="📥 Minimize to Tray", font=(FONT_MAIN, 10),
            bg=COLORS["bg_panel"], fg=COLORS["text"], relief=tk.FLAT, padx=14, pady=6,
            cursor="hand2", highlightbackground=COLORS["border"], highlightthickness=1,
            command=self._minimize_to_tray).pack(side=tk.LEFT, padx=(0, 6))
        tk.Button(sys_btns, text="🔄 Restart App", font=(FONT_MAIN, 10),
            bg=COLORS["bg_panel"], fg=COLORS["yellow"], relief=tk.FLAT, padx=14, pady=6,
            cursor="hand2", highlightbackground=COLORS["border"], highlightthickness=1,
            command=self._restart).pack(side=tk.LEFT)

    # ═══════════ DEBUG PAGE ═══════════
    def _build_debug_page(self, parent):
        debug_card = self._make_card(parent)
        debug_card.pack(fill=tk.X, pady=(0, 12))
        tk.Label(debug_card, text="SCAN VISUALIZATION", font=(FONT_MAIN, 9, "bold"),
                 bg=COLORS["bg_card"], fg=COLORS["text_muted"]).pack(anchor="w", pady=(0, 6))
        tk.Label(debug_card, text="Enable 'Debug Overlay' in Settings to see what the scanner detects in real-time.",
                 font=(FONT_MAIN, 10), bg=COLORS["bg_card"], fg=COLORS["text_dim"],
                 wraplength=600).pack(anchor="w", pady=4)
        tk.Button(debug_card, text="Toggle Debug Overlay", font=(FONT_MAIN, 10, "bold"),
            bg=COLORS["accent"], fg="#000000", relief=tk.FLAT, padx=18, pady=8,
            cursor="hand2", command=lambda: (self.var_debug_overlay.set(not self.var_debug_overlay.get()), self._save_settings())
            ).pack(anchor="w", pady=6)

        info_card = self._make_card(parent)
        info_card.pack(fill=tk.X, pady=(0, 12))
        tk.Label(info_card, text="SYSTEM INFO", font=(FONT_MAIN, 9, "bold"),
                 bg=COLORS["bg_card"], fg=COLORS["text_muted"]).pack(anchor="w", pady=(0, 6))
        for label, value in [
            ("OCR Engine", "Tesseract (available)" if OCR_AVAILABLE else "Not installed"),
            ("Clipboard", "win32clipboard" if CLIPBOARD_AVAILABLE else "Fallback mode"),
            ("Toast Notifications", "Available" if TOAST_AVAILABLE else "Not available"),
            ("System Tray", "Available" if TRAY_AVAILABLE else "Not available"),
        ]:
            row = tk.Frame(info_card, bg=COLORS["bg_card"])
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=label, font=(FONT_MAIN, 10), bg=COLORS["bg_card"],
                     fg=COLORS["text_dim"]).pack(side=tk.LEFT)
            color = COLORS["green"] if "available" in value.lower() or "Available" in value else COLORS["yellow"]
            tk.Label(row, text=value, font=(FONT_MONO, 10), bg=COLORS["bg_card"],
                     fg=color).pack(side=tk.RIGHT)

    # ── Agent ───────────────────────────────────────────────────
    _ollama_check_lock = threading.Lock()

    def _check_ollama(self):
        """Check Ollama status and auto-start if installed but not running.
        
        Uses a lock to prevent concurrent auto-start attempts when multiple
        background threads call this (e.g. startup + Refresh Models button).
        """
        if not self._ollama_check_lock.acquire(blocking=False):
            return  # Another check is already in progress
        try:
            installed = OllamaClient.is_installed()
            running = False
            models = []

            if installed:
                running = self.ollama.is_running()
                if not running:
                    # Auto-start Ollama if installed but not running
                    self._enqueue_log("Ollama installed but not running. Starting...", "info")
                    self.ollama.start_server(max_wait=10)
                    running = self.ollama.is_running()
                    if running:
                        self._enqueue_log("\u2705 Ollama server auto-started", "success")
                    else:
                        self._enqueue_log("\u26a0\ufe0f Could not auto-start Ollama", "warning")
                if running:
                    models = self.ollama.list_models()

            def _u():
                if not installed:
                    self.lbl_ollama_status.configure(text="Ollama: \u274c Not installed")
                elif not running:
                    self.lbl_ollama_status.configure(text="Ollama: \u26a0\ufe0f Not running")
                else:
                    self.lbl_ollama_status.configure(text=f"Ollama: \u2705 ({len(models)} models)")
                    if models:
                        self.combo_model.configure(values=models)
                        current = self.var_agent_model.get()
                        if current not in models:
                            # Prefer coding-oriented models
                            preferred = ["codellama:latest", "llama3.2:latest", "llama3.1:8b"]
                            chosen = None
                            for p in preferred:
                                if p in models:
                                    chosen = p
                                    break
                            self.var_agent_model.set(chosen or models[0])
            self.root.after(0, _u)
        finally:
            self._ollama_check_lock.release()

    def _set_agent_status(self, status):
        self._agent_status = status
        self.root.after(0, lambda: self.lbl_agent_status.configure(text=f"Status: {status}"))
        self.root.after(0, lambda: self.lbl_agent_steps.configure(text=f"Steps: {self.agent.steps_completed}"))

    def _enqueue_agent_chat(self, role, msg):
        self.agent_chat_queue.put((role, msg))

    def _poll_agent_chat(self):
        while True:
            try:
                role, msg = self.agent_chat_queue.get_nowait()
                pfx = "\U0001f916 Agent" if role == "agent" else "\U0001f464 You" if role == "user" else "\u2699\ufe0f"
                tg = role if role in ("user", "agent") else "system"
                self.agent_chat.configure(state=tk.NORMAL)
                self.agent_chat.insert(tk.END, f"\n{pfx}: {msg}\n", tg)
                self.agent_chat.see(tk.END)
                self.agent_chat.configure(state=tk.DISABLED)
            except queue.Empty:
                break
        self.root.after(150, self._poll_agent_chat)

    def _send_agent_msg(self):
        msg = self.agent_input.get().strip()
        if not msg:
            return
        self.agent_input.delete(0, tk.END)
        self._enqueue_agent_chat("user", msg)
        if self.agent.running:
            self.agent.send_user_message(msg)
        else:
            def _bg():
                resp = self.agent.chat_with_ollama(msg)
                self._enqueue_agent_chat("agent", resp)
            threading.Thread(target=_bg, daemon=True).start()

    def _start_agent(self):
        if self.agent.running:
            return
        self.agent.mode = self.var_agent_mode.get()
        self.agent.model = self.var_agent_model.get()
        self.agent.settings = self.settings.copy()
        task = self.agent_input.get().strip()
        if not task:
            self._enqueue_agent_chat("system", "\u26a0\ufe0f Type a task description in the input box, then click Start Agent.")
            return

        # Validate model selection
        selected_model = self.var_agent_model.get()
        models = self.ollama.list_models()
        if selected_model not in models:
            if models:
                self.var_agent_model.set(models[0])
                self.agent.model = models[0]
                self._enqueue_agent_chat("system", f"Model '{selected_model}' not found, using '{models[0]}' instead.")
            else:
                self._enqueue_agent_chat("system", "\u274c No models available. Pull a model first in Settings.")
                return

        self.agent_input.delete(0, tk.END)
        self._enqueue_agent_chat("user", task)
        self.agent.set_task(task)

        # Auto-start scanner if not running
        if not self.engine.running:
            self._save_settings()
            self.engine.settings = self.settings
            self.engine.start()
            self.var_running.set(True)

        self.btn_agent_start.configure(state=tk.DISABLED)
        self.btn_agent_stop.configure(state=tk.NORMAL)

        # Start agent in background so UI doesn't freeze during model auto-pull
        def _start_bg():
            self.agent.start()
            # Update buttons when agent finishes
            self.root.after(0, lambda: self.btn_agent_start.configure(state=tk.NORMAL))
            self.root.after(0, lambda: self.btn_agent_stop.configure(state=tk.DISABLED))
        threading.Thread(target=_start_bg, daemon=True).start()

    def _stop_agent(self):
        self.agent.stop()
        self.btn_agent_start.configure(state=tk.NORMAL)
        self.btn_agent_stop.configure(state=tk.DISABLED)

    def _pull_model(self):
        model = self.var_agent_model.get() or "phi3:mini"
        self._log_info(f"Pulling '{model}'... This may take a few minutes.", "info")
        def _bg():
            try:
                self.ollama.pull_model(model, lambda s: self._enqueue_log(f"Pull: {s}", "info"))
                self._enqueue_log(f"\u2705 Model '{model}' ready!", "success")
                self._check_ollama()
            except Exception as e:
                self._enqueue_log(f"\u274c Pull failed: {e}", "error")
        threading.Thread(target=_bg, daemon=True).start()

    # â”€â”€ Tray â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _minimize_to_tray(self):
        if TRAY_AVAILABLE:
            self.root.withdraw()
            def _mk():
                ic = Image.new("RGB", (64, 64), COLORS["green"])
                mn = pystray.Menu(
                    pystray.MenuItem("Show", lambda: self.root.after(0, self._restore_from_tray)),
                    pystray.MenuItem("Quit", lambda: self.root.after(0, self._on_close)))
                self._tray_icon = pystray.Icon("antigravity", ic, "Antigravity Autoclicker", mn)
                self._tray_icon.run()
            threading.Thread(target=_mk, daemon=True).start()
        else:
            self.root.iconify()

    def _restore_from_tray(self):
        if self._tray_icon:
            self._tray_icon.stop()
            self._tray_icon = None
        self.root.deiconify()
        self.root.lift()

    # â”€â”€ Core methods â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _enqueue_log(self, msg, tag="info"):
        self.log_queue.put((msg, tag))

    def _log_info(self, msg, tag="info"):
        self._enqueue_log(msg, tag)

    def _poll_log_queue(self):
        while True:
            try:
                msg, tag = self.log_queue.get_nowait()
                self.log_text.configure(state=tk.NORMAL)
                self.log_text.insert(tk.END, msg + "\n", tag)
                self.log_text.see(tk.END)
                self.log_text.configure(state=tk.DISABLED)
            except queue.Empty:
                break
        self.root.after(100, self._poll_log_queue)

    def _update_status(self):
        if self.engine.running:
            if self.engine._is_focus_cooldown_active():
                remaining = self.engine._focus_cooldown_until - time.time()
                self.lbl_status.configure(text=f"● COOLDOWN ({remaining:.0f}s)", fg=COLORS["yellow"])
                self._sidebar_status_dot.configure(fg=COLORS["yellow"])
                self._sidebar_status_text.configure(text="Cooldown")
            elif self.engine.paused:
                self.lbl_status.configure(text="● PAUSED", fg=COLORS["yellow"])
                self._sidebar_status_dot.configure(fg=COLORS["yellow"])
                self._sidebar_status_text.configure(text="Paused")
            else:
                self.lbl_status.configure(text="● SCANNING", fg=COLORS["green"])
                self._sidebar_status_dot.configure(fg=COLORS["green"])
                self._sidebar_status_text.configure(text="Scanning")
            
            self.btn_start.configure(state=tk.DISABLED, bg=COLORS["bg_card"], fg=COLORS["text_dim"])
            self.btn_stop.configure(state=tk.NORMAL)
            self.btn_pause.configure(state=tk.NORMAL)
            if self.engine.paused:
                self.btn_pause.configure(text="▶ Resume", fg=COLORS["green"])
            else:
                self.btn_pause.configure(text="⏸ Pause", fg=COLORS["yellow"])
        else:
            self.lbl_status.configure(text="● STANDBY", fg=COLORS["red"])
            self._sidebar_status_dot.configure(fg=COLORS["red"])
            self._sidebar_status_text.configure(text="Standby")
            
            self.btn_start.configure(state=tk.NORMAL, bg=COLORS["green"], fg="#000000")
            self.btn_stop.configure(state=tk.DISABLED)
            self.btn_pause.configure(state=tk.DISABLED, text="⏸ Pause")
        
        # Update stat cards
        self.lbl_clicks.configure(text=str(self.engine.clicks_total))
        self._var_stat_clicks.set(str(self.engine.clicks_total))
        self._var_stat_profile.set(self.settings.get("profile", "antigravity"))
        if self.engine.detected_window_title:
            t = self.engine.detected_window_title
            short = t[:25] + "..." if len(t) > 28 else t
            self.lbl_window.configure(text=f"Window: {short}")
            self._var_stat_window.set(short)
        else:
            self.lbl_window.configure(text="Window: —")
            self._var_stat_window.set("—")
        if self.var_debug_overlay.get() != self.overlay.enabled:
            self.overlay.toggle(self.var_debug_overlay.get())
        if not self.agent.running:
            self.btn_agent_start.configure(state=tk.NORMAL)
            self.btn_agent_stop.configure(state=tk.DISABLED)
        # Update page title based on current page
        page_titles = {
            "clicker": ("Auto-Clicker", "Detect and click IDE buttons automatically"),
            "agent": ("AI Agent", "Autonomous coding supervisor powered by Ollama"),
            "settings": ("Settings", "Configure detection, AI engine, and system options"),
            "debug": ("Debug", "Scan visualization and system diagnostics"),
        }
        title, subtitle = page_titles.get(self._current_page, ("", ""))
        self._page_title.configure(text=title)
        self._page_subtitle.configure(text=subtitle)
        self.root.after(500, self._update_status)

    def _start_scanner(self):
        if not self.engine.running:
            self._save_settings()
            self.engine.settings = self.settings
            self.engine.start()
            self.var_running.set(True)

    def _stop_scanner(self):
        if self.engine.running:
            self.engine.stop()
            self.var_running.set(False)

    def _toggle_pause(self):
        self.engine.toggle_pause()

    def _on_window_focus(self, event):
        """Triggered when the autoclicker window gains focus.
        
        Activates a 5-second click cooldown so the scanner doesn't
        immediately click the IDE window and steal focus back before
        the user can interact with autoclicker settings.
        
        Only triggers on top-level window focus (not individual widget
        focus changes within the app), and only when scanner is running.
        """
        # Only trigger on the root window, not child widget focus events
        if event.widget != self.root:
            return
        # Only trigger cooldown when scanner is actively running
        if self.engine.running and not self.engine.paused:
            # Debounce: don't re-trigger if already in cooldown
            if not self.engine._is_focus_cooldown_active():
                self.engine.trigger_focus_cooldown(5.0)

    def _on_profile_change(self, event=None):
        self.settings["profile"] = self.var_profile.get()
        self._save_settings()
        self._update_profile_desc()
        n = PROFILES.get(self.settings["profile"], {}).get("name", "Unknown")
        self._log_info(f"Profile: {n}", "detect")

    def _update_profile_desc(self):
        p = PROFILES.get(self.var_profile.get(), {})
        self.lbl_profile_desc.configure(text=f"({p.get('name', '')})")

    def _save_settings(self):
        try:
            self.settings["profile"] = self.var_profile.get()
            self.settings["detect_run"] = self.var_run.get()
            self.settings["detect_accept"] = self.var_accept.get()
            self.settings["detect_confirm"] = self.var_confirm.get()
            self.settings["use_ocr"] = self.var_ocr.get()
            self.settings["auto_detect_window"] = self.var_auto_detect.get()
            self.settings["debug_overlay"] = self.var_debug_overlay.get()
            self.settings["loop_detect_enabled"] = self.var_loop_detect.get()
            self.settings["agent_mode"] = self.var_agent_mode.get()
            self.settings["agent_model"] = self.var_agent_model.get()
            try:
                self.settings["check_interval"] = max(0.1, float(self.var_interval.get()))
            except ValueError:
                pass
            try:
                self.settings["confidence"] = max(0.1, min(1.0, float(self.var_confidence.get())))
            except ValueError:
                pass
            save_settings(self.settings)
            self.engine.settings = self.settings.copy()
        except Exception as e:
            logging.error(f"Save settings error: {e}")

    def _clear_log(self):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state=tk.DISABLED)

    def _bind_hotkey(self):
        try:
            hwnd = int(self.root.wm_frame(), 16)
            result = ctypes.windll.user32.RegisterHotKey(hwnd, self._hotkey_id, 0x0002 | 0x0004, 0x50)
            if result:
                self._hotkey_registered = True
                self._log_info("Hotkey Ctrl+Shift+P registered.", "info")
            else:
                self._log_info("Could not register hotkey.", "warning")
        except Exception as e:
            self._log_info(f"Hotkey error: {e}", "warning")

    def _poll_hotkey(self):
        try:
            msg = wintypes.MSG()
            while ctypes.windll.user32.PeekMessageW(ctypes.byref(msg), 0, 0x0312, 0x0312, 0x0001):
                if msg.message == 0x0312 and msg.wParam == self._hotkey_id:
                    self._toggle_pause()
        except Exception:
            pass
        self.root.after(200, self._poll_hotkey)

    def _on_close(self):
        self.engine.stop()
        self.agent.stop()
        if self._tray_icon:
            self._tray_icon.stop()
        if self._hotkey_registered:
            try:
                hwnd = int(self.root.wm_frame(), 16)
                ctypes.windll.user32.UnregisterHotKey(hwnd, self._hotkey_id)
            except Exception:
                pass
        self.root.destroy()

    def _restart(self):
        """Restart the application by launching a new instance and exiting."""
        self._log_info("Restarting...", "warning")
        self.engine.stop()
        self.agent.stop()
        # Prefer pythonw.exe (no console window) over python.exe
        exe = sys.executable
        pythonw = exe.replace("python.exe", "pythonw.exe")
        if os.path.exists(pythonw):
            exe = pythonw
        # CREATE_NO_WINDOW = 0x08000000
        subprocess.Popen([exe] + sys.argv,
                         cwd=os.path.dirname(os.path.abspath(__file__)),
                         creationflags=0x08000000)
        self.root.destroy()
        sys.exit(0)

    def _poll_file_changes(self):
        """Check for local file changes AND remote git updates.
        
        - Every 5s: check if the script file mtime changed (local edits)
        - Every 60s: run 'git fetch' in background and check if branch is behind
        Shows a popup dialog when updates are detected.
        """
        try:
            # 1) Local file mtime check
            current_mtime = os.path.getmtime(self._script_path)
            if current_mtime != self._script_mtime:
                self._script_mtime = current_mtime
                self._show_update_popup("local")
                return  # Stop polling — popup handles restart or dismissal
        except Exception:
            pass

        # 2) Periodic git remote check (every 60s)
        now = time.time()
        last_git_check = getattr(self, '_last_git_check', 0)
        if now - last_git_check >= 60:
            self._last_git_check = now
            threading.Thread(target=self._check_git_updates, daemon=True).start()
        
        self.root.after(5000, self._poll_file_changes)

    def _check_git_updates(self):
        """Background thread: git fetch + check if behind remote."""
        try:
            repo_dir = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(repo_dir)
            # Try repo root (parent of core/)
            git_dir = parent_dir if os.path.isdir(os.path.join(parent_dir, ".git")) else repo_dir
            
            subprocess.run(
                ["git", "fetch"],
                cwd=git_dir,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15
            )
            result = subprocess.run(
                ["git", "status", "-uno"],
                cwd=git_dir,
                capture_output=True,
                text=True,
                timeout=10
            )
            if "Your branch is behind" in result.stdout:
                # Schedule popup on main thread
                self.root.after(0, lambda: self._show_update_popup("git"))
        except Exception as e:
            logging.debug(f"Git update check failed: {e}")

    def _do_git_pull_and_restart(self):
        """Pull latest from git and restart the app."""
        try:
            repo_dir = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(repo_dir)
            git_dir = parent_dir if os.path.isdir(os.path.join(parent_dir, ".git")) else repo_dir
            
            result = subprocess.run(
                ["git", "pull"],
                cwd=git_dir,
                capture_output=True,
                text=True,
                timeout=30
            )
            self._log_info(f"Git pull: {result.stdout.strip()}", "success")
        except Exception as e:
            self._log_info(f"Git pull failed: {e}", "error")
        self._restart()

    def _show_update_popup(self, source="local"):
        """Show a centered popup window with Update & Restart / Stay Open options."""
        # Prevent duplicate popups
        if getattr(self, '_update_popup_open', False):
            return
        self._update_popup_open = True

        popup = tk.Toplevel(self.root)
        popup.title("Update Available")
        popup.configure(bg=COLORS["bg_panel"])
        popup.resizable(False, False)
        popup.attributes("-topmost", True)
        popup.grab_set()

        # Size and center
        pw, ph = 420, 220
        rx = self.root.winfo_x() + (self.root.winfo_width() - pw) // 2
        ry = self.root.winfo_y() + (self.root.winfo_height() - ph) // 2
        popup.geometry(f"{pw}x{ph}+{rx}+{ry}")

        # Icon
        tk.Label(popup, text="⚡", font=("Segoe UI Emoji", 36),
                 bg=COLORS["bg_panel"], fg=COLORS["accent"]).pack(pady=(18, 5))

        # Message
        if source == "git":
            msg = "A newer version is available from the repository."
        else:
            msg = "The script files have been updated on disk."
        tk.Label(popup, text=msg, font=("Segoe UI", 11),
                 bg=COLORS["bg_panel"], fg=COLORS["text"], wraplength=360).pack(pady=(0, 5))
        tk.Label(popup, text="Would you like to update and restart?",
                 font=("Segoe UI", 10), bg=COLORS["bg_panel"],
                 fg=COLORS["text_dim"]).pack(pady=(0, 12))

        btn_frame = tk.Frame(popup, bg=COLORS["bg_panel"])
        btn_frame.pack(pady=(0, 15))

        def _on_update():
            popup.destroy()
            self._update_popup_open = False
            if source == "git":
                threading.Thread(target=self._do_git_pull_and_restart, daemon=True).start()
            else:
                self._restart()

        def _on_stay():
            popup.destroy()
            self._update_popup_open = False
            # Resume file polling
            self.root.after(5000, self._poll_file_changes)

        tk.Button(btn_frame, text="🔄  Update && Restart", font=("Segoe UI", 10, "bold"),
                  bg=COLORS["accent"], fg="#ffffff", relief=tk.FLAT,
                  padx=16, pady=6, cursor="hand2",
                  command=_on_update).pack(side=tk.LEFT, padx=8)

        tk.Button(btn_frame, text="Stay Open", font=("Segoe UI", 10),
                  bg=COLORS["bg_card"], fg=COLORS["text_dim"], relief=tk.FLAT,
                  padx=16, pady=6, cursor="hand2",
                  command=_on_stay).pack(side=tk.LEFT, padx=8)

        def _on_close_popup():
            _on_stay()
        popup.protocol("WM_DELETE_WINDOW", _on_close_popup)

    def run(self):
        self.root.mainloop()


# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# ENTRY POINT
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

def main():
    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "autoclicker.log")
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S",
        handlers=[RotatingFileHandler(log_file, maxBytes=500*1024, backupCount=2, encoding="utf-8")])
    logging.info("=" * 60)
    logging.info("Antigravity Autoclicker v2.0 starting...")
    app = AntigravityAutoclickerApp()
    app.run()


if __name__ == "__main__":
    main()
