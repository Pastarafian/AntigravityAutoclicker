"""
Chat Reader — Deep understanding of IDE chat windows
=====================================================
Three layers of chat understanding:
1. Enhanced OCR with preprocessing and structured extraction
2. Git diff analysis to see what the IDE AI actually changed
3. Change detection to avoid redundant OCR reads
"""

import os
import time
import hashlib
import logging
import subprocess
import numpy as np
import cv2
from PIL import ImageGrab
from typing import Optional, Tuple, List, Dict

logger = logging.getLogger(__name__)

# Try OCR
try:
    import pytesseract
    import shutil
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


class ChatMessage:
    """A parsed chat message from the IDE."""
    def __init__(self, role: str, content: str, timestamp: float = None):
        self.role = role  # "assistant", "user", "system"
        self.content = content
        self.timestamp = timestamp or time.time()

    def to_dict(self) -> dict:
        return {"role": self.role, "content": self.content}


class ChatReader:
    """Reads and understands IDE chat windows using multiple methods."""

    def __init__(self):
        self._last_frame_hash: str = ""
        self._last_ocr_text: str = ""
        self._last_read_time: float = 0
        self._frame_cache: Optional[np.ndarray] = None
        self._min_read_interval: float = 1.0  # Min seconds between OCR reads

    def read_chat_panel(self, window_rect: Tuple[int, int, int, int],
                        settings: dict = None) -> str:
        """
        Read the IDE chat panel text using enhanced OCR.
        
        Uses change detection to avoid redundant OCR calls.
        Returns the extracted text, or cached text if screen hasn't changed.
        """
        settings = settings or {}
        if not OCR_AVAILABLE:
            return "[OCR not available — install Tesseract]"

        # Rate limit reads
        now = time.time()
        if now - self._last_read_time < self._min_read_interval:
            return self._last_ocr_text

        try:
            left, top, right, bottom = window_rect
            win_w = right - left
            win_h = bottom - top

            # Capture the chat panel region (right 45% of window, excluding bottom input)
            input_clip = settings.get("input_box_clip_px", 100)
            if win_w > 800:
                chat_left = left + int(win_w * 0.55)
            else:
                chat_left = left + int(win_w * 0.3)

            chat_top = top + 80  # Skip title bar
            chat_right = right - 10
            chat_bottom = bottom - input_clip  # Exclude input box

            bbox = (chat_left, chat_top, chat_right, chat_bottom)
            screenshot = ImageGrab.grab(bbox=bbox)
            frame = np.array(screenshot)

            # Change detection — hash the frame
            small = cv2.resize(frame, (64, 64))
            frame_hash = hashlib.md5(small.tobytes()).hexdigest()
            if frame_hash == self._last_frame_hash:
                return self._last_ocr_text  # Screen hasn't changed

            # Enhanced preprocessing for better OCR
            processed = self._preprocess_for_ocr(frame)

            # Run OCR
            text = pytesseract.image_to_string(
                processed,
                config="--oem 3 --psm 6 -l eng",
            )

            # Clean up
            text = self._clean_ocr_text(text)

            self._last_frame_hash = frame_hash
            self._last_ocr_text = text
            self._last_read_time = now
            self._frame_cache = frame

            return text

        except Exception as e:
            logger.debug(f"Chat read error: {e}")
            return self._last_ocr_text

    def has_screen_changed(self, window_rect: Tuple[int, int, int, int],
                            settings: dict = None) -> bool:
        """Quick check if the screen has changed since last read (no OCR)."""
        settings = settings or {}
        try:
            left, top, right, bottom = window_rect
            win_w = right - left
            input_clip = settings.get("input_box_clip_px", 100)
            if win_w > 800:
                chat_left = left + int(win_w * 0.55)
            else:
                chat_left = left + int(win_w * 0.3)

            bbox = (chat_left, top + 80, right - 10, bottom - input_clip)
            screenshot = ImageGrab.grab(bbox=bbox)
            frame = np.array(screenshot)
            small = cv2.resize(frame, (64, 64))
            frame_hash = hashlib.md5(small.tobytes()).hexdigest()
            return frame_hash != self._last_frame_hash
        except Exception:
            return True  # Assume changed on error

    def detect_completion_indicators(self, text: str) -> dict:
        """Analyze OCR text for completion/error/busy signals."""
        text_lower = text.lower()

        indicators = {
            "is_busy": False,
            "is_complete": False,
            "has_error": False,
            "has_buttons": False,
            "completion_signal": "",
        }

        # Busy indicators
        busy_words = ["thinking", "generating", "analyzing", "processing", "typing", "..."]
        if any(w in text_lower for w in busy_words):
            indicators["is_busy"] = True

        # Error indicators
        error_words = ["error", "failed", "traceback", "exception", "panic", "fatal",
                       "cannot find", "not found", "permission denied", "syntax error"]
        if any(w in text_lower for w in error_words):
            indicators["has_error"] = True

        # Completion indicators
        complete_words = ["task_complete", "done", "finished", "completed", "success",
                          "all changes applied", "ready for review"]
        for w in complete_words:
            if w in text_lower:
                indicators["is_complete"] = True
                indicators["completion_signal"] = w
                break

        # Button-like text
        button_words = ["run", "accept", "apply", "confirm", "yes", "continue"]
        if any(w in text_lower for w in button_words):
            indicators["has_buttons"] = True

        return indicators

    def get_git_changes(self, workspace_root: str) -> dict:
        """Get detailed git changes to understand what the IDE AI modified."""
        result = {
            "files_changed": [],
            "diff_summary": "",
            "diff_full": "",
            "has_changes": False,
        }

        try:
            # Get list of changed files
            stat = subprocess.run(
                ["git", "diff", "--stat", "HEAD"],
                cwd=workspace_root, capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            result["diff_summary"] = stat.stdout.strip()

            # Get file names
            names = subprocess.run(
                ["git", "diff", "--name-only", "HEAD"],
                cwd=workspace_root, capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            result["files_changed"] = [f.strip() for f in names.stdout.strip().split("\n") if f.strip()]

            # Get full diff (capped)
            diff = subprocess.run(
                ["git", "diff", "HEAD"],
                cwd=workspace_root, capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            full_diff = diff.stdout.strip()
            result["diff_full"] = full_diff[:8000]  # Cap at 8KB

            result["has_changes"] = bool(result["files_changed"])

        except Exception as e:
            logger.debug(f"Git diff error: {e}")

        return result

    def build_situation_report(self, window_rect: Tuple[int, int, int, int],
                                workspace_root: str,
                                settings: dict = None) -> str:
        """
        Build a comprehensive situation report combining:
        1. Chat panel text (OCR)
        2. Git diff analysis
        3. Status indicators
        
        This is what gets fed to the agent's LLM for decision-making.
        """
        parts = []

        # 1. Read chat panel
        chat_text = self.read_chat_panel(window_rect, settings)
        if chat_text:
            # Trim to last ~2000 chars (most recent messages)
            if len(chat_text) > 2000:
                chat_text = "...\n" + chat_text[-2000:]
            parts.append(f"CHAT PANEL CONTENT:\n{chat_text}")

        # 2. Analyze chat for signals
        indicators = self.detect_completion_indicators(chat_text)
        signals = []
        if indicators["is_busy"]:
            signals.append("IDE AI is currently BUSY/GENERATING")
        if indicators["has_error"]:
            signals.append("ERRORS detected in output")
        if indicators["is_complete"]:
            signals.append(f"COMPLETION signal: {indicators['completion_signal']}")
        if indicators["has_buttons"]:
            signals.append("Action buttons visible")
        if signals:
            parts.append(f"STATUS SIGNALS: {'; '.join(signals)}")

        # 3. Git changes
        if workspace_root:
            changes = self.get_git_changes(workspace_root)
            if changes["has_changes"]:
                parts.append(f"FILES MODIFIED BY IDE AI:\n{changes['diff_summary']}")
                if changes["diff_full"]:
                    # Include abbreviated diff
                    diff_preview = changes["diff_full"][:3000]
                    parts.append(f"CODE CHANGES:\n{diff_preview}")

        return "\n\n".join(parts) if parts else "[No information available]"

    # ── Private helpers ───────────────────────────────────────────────

    def _preprocess_for_ocr(self, frame: np.ndarray) -> np.ndarray:
        """Enhanced image preprocessing for better OCR accuracy."""
        # Convert to grayscale
        gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

        # Scale up 2x for better character recognition
        h, w = gray.shape
        scaled = cv2.resize(gray, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)

        # Adaptive threshold for dark themes
        # Detect if dark theme (mean brightness < 128)
        mean_brightness = np.mean(scaled)
        if mean_brightness < 128:
            # Dark theme: invert first so text becomes dark on light
            scaled = cv2.bitwise_not(scaled)

        # Apply adaptive threshold
        binary = cv2.adaptiveThreshold(
            scaled, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 21, 10,
        )

        # Denoise
        denoised = cv2.medianBlur(binary, 3)

        return denoised

    def _clean_ocr_text(self, text: str) -> str:
        """Clean up raw OCR output."""
        lines = text.split("\n")
        cleaned = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            # Skip lines that are just noise (mostly special chars)
            alpha_ratio = sum(1 for c in line if c.isalnum()) / max(len(line), 1)
            if alpha_ratio < 0.2 and len(line) < 10:
                continue
            cleaned.append(line)
        return "\n".join(cleaned)

    def get_last_frame(self) -> Optional[np.ndarray]:
        """Get the last captured frame (for live preview)."""
        return self._frame_cache
