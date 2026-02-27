"""
Upgraded Agent Brain v2 — Autonomous AI Coding Supervisor
==========================================================
State machine-based agent that drives IDE AI assistants.
Uses multi-provider LLM (DeepSeek, Kimi, Ollama) for reasoning,
workspace scanning for project context, and enhanced chat reading
for deep understanding of what the IDE is doing.

States:
  IDLE → STARTING → READING → THINKING → TYPING → WAITING → READING → ...
                                                      ↓
                                              COMPLETION_DETECTED → DONE
                                              STUCK_DETECTED → RECOVERY
                                              ERROR_DETECTED → RETRY
"""

import os
import time
import json
import threading
import logging
from datetime import datetime
from typing import Optional, List, Dict, Callable, Any

from backend.llm_client import LLMClient
from backend.workspace_scanner import WorkspaceScanner
from backend.chat_reader import ChatReader

logger = logging.getLogger(__name__)

# Agent modes with detailed system prompts
AGENT_MODES = {
    "build": {
        "name": "🏗️ Build & Implement",
        "description": "Implement features step by step. Focus on working code.",
        "auto_click": ["run", "accept", "confirm"],
        "system_prompt": (
            "You are an autonomous coding supervisor. You are watching an AI coding assistant "
            "work inside an IDE. Your job is to give it ONE clear instruction at a time and "
            "monitor its progress.\n\n"
            "RULES:\n"
            "1. Give ONE specific, actionable instruction per message\n"
            "2. If the AI completed the task, give the NEXT logical step\n"
            "3. If it errored, analyze the error and give a targeted fix instruction\n"
            "4. If it's stuck in a loop, try a completely different approach\n"
            "5. Keep instructions concise (1-3 sentences max)\n"
            "6. Track what has been done to avoid repeating work\n"
            "7. Say TASK_COMPLETE when the entire task is finished\n\n"
            "RESPONSE FORMAT (always use this):\n"
            "ACTION: type | wait | complete\n"
            "INSTRUCTION: [your instruction to the IDE AI]\n"
            "REASON: [brief explanation of why]"
        ),
    },
    "design": {
        "name": "🏛️ Design & Plan",
        "description": "Architecture, specs, file structure. No implementation.",
        "auto_click": ["accept"],
        "system_prompt": (
            "You are a software architect supervising an AI coding assistant. "
            "Focus on design: architecture, file structure, interfaces, data models. "
            "Do NOT ask for implementation code yet — only design documents and plans.\n\n"
            "RESPONSE FORMAT:\n"
            "ACTION: type | wait | complete\n"
            "INSTRUCTION: [your design instruction]\n"
            "REASON: [explanation]"
        ),
    },
    "test": {
        "name": "🧪 Test & Debug",
        "description": "Run tests, find bugs, fix errors. Focus on quality.",
        "auto_click": ["run", "accept", "confirm"],
        "system_prompt": (
            "You are a QA engineer supervising an AI coding assistant. "
            "Focus on: writing tests, running tests, fixing bugs, code review. "
            "When you see errors, give precise fix instructions.\n\n"
            "RESPONSE FORMAT:\n"
            "ACTION: type | wait | complete\n"
            "INSTRUCTION: [your testing instruction]\n"
            "REASON: [explanation]"
        ),
    },
    "refactor": {
        "name": "🧹 Refactor & Polish",
        "description": "Clean up code, optimize, improve naming, add docs.",
        "auto_click": ["run", "accept"],
        "system_prompt": (
            "You are a senior developer reviewing and refactoring code. "
            "Focus on: code quality, naming, documentation, performance, DRY principle. "
            "Give one small, focused refactoring instruction at a time.\n\n"
            "RESPONSE FORMAT:\n"
            "ACTION: type | wait | complete\n"
            "INSTRUCTION: [your refactoring instruction]\n"
            "REASON: [explanation]"
        ),
    },
}

# State constants
STATE_IDLE = "idle"
STATE_STARTING = "starting"
STATE_READING = "reading"
STATE_THINKING = "thinking"
STATE_TYPING = "typing"
STATE_WAITING = "waiting"
STATE_RECOVERY = "recovery"
STATE_SMART_PAUSED = "smart_paused"
STATE_DONE = "done"

AGENT_MAX_STEPS = 50
AGENT_STALL_TIMEOUT = 300  # 5 minutes


class UpgradedAgentBrain:
    """
    Autonomous coding supervisor v2.
    
    Uses multi-provider LLM, workspace context, and deep chat understanding
    to drive IDE AI assistants through complex coding tasks.
    """

    def __init__(self, llm_client: LLMClient, scan_engine,
                 log_callback=None, status_callback=None, chat_callback=None):
        # Core components
        self.llm = llm_client
        self.scan_engine = scan_engine
        self.workspace_scanner = WorkspaceScanner()
        self.chat_reader = ChatReader()

        # Callbacks
        self.log_callback = log_callback or (lambda msg, tag="info": None)
        self.status_callback = status_callback or (lambda status: None)
        self.chat_callback = chat_callback or (lambda role, msg: None)

        # State machine
        self.state = STATE_IDLE
        self.running = False
        self.stop_event = threading.Event()
        self.thread: Optional[threading.Thread] = None

        # Task config
        self.task: str = ""
        self.mode: str = "build"
        self.settings: dict = {}

        # Statistics
        self.step_count = 0
        self.start_time: Optional[float] = None
        self.errors_encountered = 0
        self.recovery_count = 0

        # Conversation history (for the agent's LLM)
        self.conversation_history: List[Dict] = []
        self.max_history = 20  # Keep last N exchanges

        # Chat conversation (separate from agent loop)
        self.chat_history: List[Dict] = []

        # Smart pause
        self.smart_pause_enabled = True
        self._last_activity_time = 0.0
        self._consecutive_idle_reads = 0

        # Workspace context
        self.workspace_root: Optional[str] = None
        self.workspace_context: Optional[str] = None

        # Session logging
        self._session_log: List[str] = []
        self._session_id = ""

        # User message queue
        self._user_messages: List[str] = []
        self._user_msg_lock = threading.Lock()

    # ── Public API ────────────────────────────────────────────────────

    def set_task(self, task: str):
        """Set the task for the agent to work on."""
        self.task = task
        self.conversation_history = []
        self.step_count = 0
        self.errors_encountered = 0
        self.recovery_count = 0

    def start(self):
        """Start the autonomous agent loop."""
        if self.running:
            return

        self.running = True
        self.stop_event.clear()
        self.start_time = time.time()
        self._session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
        self._session_log = []
        self.state = STATE_STARTING

        self.thread = threading.Thread(target=self._agent_loop, daemon=True, name="AgentBrain")
        self.thread.start()
        self.log("Agent started", "agent")

    def stop(self):
        """Stop the agent gracefully."""
        if not self.running:
            return
        self.running = False
        self.stop_event.set()
        self.state = STATE_IDLE
        self.log("Agent stopping...", "agent")
        self._save_session_log()
        if self.thread:
            self.thread.join(timeout=5)
            self.thread = None

    def send_user_message(self, msg: str):
        """Send a message from the user to the agent (thread-safe)."""
        with self._user_msg_lock:
            self._user_messages.append(msg)

    def chat_with_llm(self, user_msg: str) -> str:
        """
        Direct chat with the LLM (for planning/discussion, not agent loop).
        Uses a SEPARATE conversation history.
        """
        self.chat_history.append({"role": "user", "content": user_msg})

        # Build context-aware system prompt
        system = (
            "You are an AI coding assistant integrated into the VegaAutoclicker. "
            "You help the user plan tasks, discuss strategies, and answer questions. "
            "Be concise and practical."
        )

        if self.workspace_context:
            system += f"\n\nPROJECT CONTEXT:\n{self.workspace_context}"

        try:
            response = self.llm.chat(self.chat_history[-10:], system=system)
            self.chat_history.append({"role": "assistant", "content": response})
            return response
        except Exception as e:
            error_msg = f"LLM error: {e}"
            logger.error(error_msg)
            return error_msg

    def get_status(self) -> dict:
        """Return current agent status."""
        elapsed = 0
        if self.start_time:
            elapsed = int(time.time() - self.start_time)

        return {
            "running": self.running,
            "state": self.state,
            "mode": self.mode,
            "task": self.task,
            "step_count": self.step_count,
            "errors": self.errors_encountered,
            "recoveries": self.recovery_count,
            "elapsed_seconds": elapsed,
            "smart_pause_enabled": self.smart_pause_enabled,
            "workspace_root": self.workspace_root,
            "llm": self.llm.get_status(),
        }

    # ── Main Agent Loop ───────────────────────────────────────────────

    def _agent_loop(self):
        """Main autonomous loop with state machine."""
        self.log(f"Agent task: {self.task}", "agent")
        self.log(f"Mode: {self.mode}, LLM: {self.llm.provider}/{self.llm.model}", "agent")

        # Phase 1: Initialize
        self.state = STATE_STARTING
        self._initialize()

        if not self.running:
            return

        # Phase 2: Main loop
        while self.running and not self.stop_event.is_set():
            try:
                if self.step_count >= AGENT_MAX_STEPS:
                    self.log(f"Max steps ({AGENT_MAX_STEPS}) reached", "agent")
                    self.state = STATE_DONE
                    break

                # Check for user messages
                self._process_user_messages()

                # STATE: Reading screen
                self.state = STATE_READING
                situation = self._read_situation()

                if not self.running:
                    break

                # Detect if we should smart-pause
                if self.smart_pause_enabled:
                    indicators = self.chat_reader.detect_completion_indicators(situation)
                    if not indicators["is_busy"] and not indicators["has_error"] \
                       and not indicators["has_buttons"]:
                        self._consecutive_idle_reads += 1
                        if self._consecutive_idle_reads >= 5:
                            self.state = STATE_SMART_PAUSED
                            self.log("Smart pause: waiting for activity...", "agent")
                            # Wait until screen changes
                            while self.running and not self.stop_event.wait(2.0):
                                windows = self.scan_engine._find_windows()
                                if windows:
                                    _, _, rect = windows[0]
                                    if self.chat_reader.has_screen_changed(rect, self.settings):
                                        self.log("Activity detected, resuming", "agent")
                                        self._consecutive_idle_reads = 0
                                        break
                            continue
                    else:
                        self._consecutive_idle_reads = 0

                # STATE: Thinking
                self.state = STATE_THINKING
                action, instruction, reason = self._think(situation)

                if not self.running:
                    break

                # Handle action
                if action == "complete":
                    self.log(f"Task complete! Reason: {reason}", "agent")
                    self.chat_callback("agent", f"✅ TASK COMPLETE: {reason}")
                    self.state = STATE_DONE
                    break

                elif action == "wait":
                    self.log(f"Waiting: {reason}", "agent")
                    self.stop_event.wait(3.0)
                    continue

                elif action == "type":
                    # STATE: Typing
                    self.state = STATE_TYPING
                    self._type_instruction(instruction)
                    self.step_count += 1
                    self._session_log.append(
                        f"[Step {self.step_count}] {instruction[:100]}"
                    )

                    # STATE: Waiting for IDE AI to process
                    self.state = STATE_WAITING
                    self._wait_for_ide(timeout=AGENT_STALL_TIMEOUT)

                else:
                    self.log(f"Unknown action: {action}", "warning")
                    self.stop_event.wait(2.0)

            except Exception as e:
                self.errors_encountered += 1
                self.log(f"Agent error: {e}", "error")
                logger.exception("Agent loop error")

                if self.errors_encountered >= 5:
                    self.log("Too many errors, stopping agent", "error")
                    break

                self.stop_event.wait(3.0)

        # Cleanup
        self.running = False
        self.state = STATE_IDLE
        self._save_session_log()
        self.log("Agent loop ended", "agent")
        self.chat_callback("system", "Agent session ended")

    # ── State Handlers ────────────────────────────────────────────────

    def _initialize(self):
        """Initialize agent: scan workspace, check LLM, build context."""
        # Detect workspace from IDE window
        windows = self.scan_engine._find_windows()
        if windows:
            _, title, _ = windows[0]
            detected = self.workspace_scanner.detect_workspace_from_title(title)
            if detected:
                self.workspace_root = detected
                self.log(f"Detected workspace: {detected}", "agent")

        # Scan workspace
        if self.workspace_root:
            ctx = self.workspace_scanner.scan(self.workspace_root)
            self.workspace_context = ctx.to_prompt()
            self.log(f"Workspace: {ctx.file_count} files, {ctx.framework}", "agent")

            # Create backup
            backup = self.workspace_scanner.create_backup(self.workspace_root)
            if backup:
                self.log(f"Backup created: {backup}", "agent")

        # Check LLM
        if not self.llm.is_available():
            self.log(f"LLM provider {self.llm.provider} not available!", "error")
            # Try fallback
            if self.llm.provider != "ollama":
                self.log("Falling back to Ollama...", "agent")
                self.llm.switch_provider("ollama")
                if not self.llm.is_available():
                    self.log("No LLM available. Cannot start agent.", "error")
                    self.running = False
                    return

        self.chat_callback("system", f"Agent initialized. LLM: {self.llm.provider}/{self.llm.model}")

    def _read_situation(self) -> str:
        """Read the current state of the IDE using all available methods."""
        windows = self.scan_engine._find_windows()
        if not windows:
            return "[No IDE window found]"

        _, title, rect = windows[0]

        # Build situation report (OCR + git diff + indicators)
        report = self.chat_reader.build_situation_report(
            rect, self.workspace_root, self.settings
        )

        return report

    def _think(self, situation: str) -> tuple:
        """
        Ask the LLM what to do based on the current situation.
        Returns (action, instruction, reason).
        """
        # Build the current message
        user_content = f"CURRENT SITUATION:\n{situation}\n\nWhat should I tell the IDE AI to do next?"

        # Add to conversation history
        self.conversation_history.append({"role": "user", "content": user_content})

        # Trim history to last N, always keeping the system context
        trimmed = self.conversation_history[-self.max_history:]

        # Build system prompt
        mode_config = AGENT_MODES.get(self.mode, AGENT_MODES["build"])
        system = mode_config["system_prompt"]

        # Inject workspace context
        if self.workspace_context:
            system += f"\n\nPROJECT CONTEXT:\n{self.workspace_context[:2000]}"

        # Inject task
        system += f"\n\nTASK: {self.task}"
        system += f"\n\nSTEPS COMPLETED: {self.step_count}/{AGENT_MAX_STEPS}"
        system += f"\nERRORS ENCOUNTERED: {self.errors_encountered}"

        try:
            response = self.llm.chat(trimmed, system=system, temperature=0.3)

            # Add to history
            self.conversation_history.append({"role": "assistant", "content": response})

            # Log
            self.chat_callback("agent", response)
            self.log(f"Agent thinking: {response[:80]}...", "agent")

            # Parse structured response
            action, instruction, reason = self._parse_response(response)
            return action, instruction, reason

        except Exception as e:
            self.errors_encountered += 1
            self.log(f"LLM error: {e}", "error")

            # Fallback: try different provider
            if self.llm.provider != "ollama" and self.recovery_count < 3:
                self.recovery_count += 1
                self.log("Attempting fallback to Ollama...", "agent")
                self.llm.switch_provider("ollama")
                return "wait", "", "Switching LLM provider"

            return "wait", "", f"LLM error: {e}"

    def _parse_response(self, response: str) -> tuple:
        """Parse the structured agent response into (action, instruction, reason)."""
        action = "type"
        instruction = response
        reason = ""

        lines = response.strip().split("\n")
        for line in lines:
            line_stripped = line.strip()
            lower = line_stripped.lower()

            if lower.startswith("action:"):
                val = line_stripped.split(":", 1)[1].strip().lower()
                if val in ("type", "wait", "complete"):
                    action = val

            elif lower.startswith("instruction:"):
                instruction = line_stripped.split(":", 1)[1].strip()

            elif lower.startswith("reason:"):
                reason = line_stripped.split(":", 1)[1].strip()

        # Detect TASK_COMPLETE in response
        if "task_complete" in response.lower():
            action = "complete"
            if not reason:
                reason = "Agent signaled TASK_COMPLETE"

        # If no structured format found, use the whole response as instruction
        if instruction == response and action == "type":
            # Clean up: remove any "ACTION:" prefix if agent included it inline
            instruction = instruction.strip()

        return action, instruction, reason

    def _type_instruction(self, instruction: str):
        """Type the instruction into the IDE chat, then restore previous focus."""
        import win32gui

        windows = self.scan_engine._find_windows()
        if not windows:
            self.log("No IDE window found for typing", "warning")
            return

        hwnd, title, rect = windows[0]

        # Save the currently focused window so we can restore it after
        prev_hwnd = win32gui.GetForegroundWindow()

        # Focus the IDE window
        try:
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.3)
        except Exception:
            pass

        # Use ChatController from the loaded core
        try:
            from backend.autoclicker_service import _chat_controller
            _chat_controller.click_input_area(rect, self.settings)
            _chat_controller.type_text(instruction)
            _chat_controller.submit()
            self.log(f"Typed: {instruction[:60]}...", "agent")
            self.chat_callback("agent", f"→ {instruction}")
        except Exception as e:
            self.log(f"Typing error: {e}", "error")

        # Restore focus to the previously active window
        time.sleep(0.5)
        if prev_hwnd and prev_hwnd != hwnd:
            try:
                win32gui.SetForegroundWindow(prev_hwnd)
            except Exception:
                pass  # Window may have closed

    def _wait_for_ide(self, timeout: float = 300):
        """Wait for the IDE AI to finish processing."""
        start = time.time()
        stable_count = 0
        last_text = ""

        while self.running and not self.stop_event.is_set():
            elapsed = time.time() - start
            if elapsed > timeout:
                self.log("IDE stall timeout", "warning")
                self.state = STATE_RECOVERY
                self.recovery_count += 1
                break

            # Read screen
            windows = self.scan_engine._find_windows()
            if not windows:
                self.stop_event.wait(2.0)
                continue

            _, _, rect = windows[0]
            text = self.chat_reader.read_chat_panel(rect, self.settings)
            indicators = self.chat_reader.detect_completion_indicators(text)

            # If busy, keep waiting
            if indicators["is_busy"]:
                stable_count = 0
                self.stop_event.wait(2.0)
                continue

            # If screen text stabilized (same 3 times in a row)
            if text == last_text:
                stable_count += 1
            else:
                stable_count = 0
                last_text = text

            if stable_count >= 3:
                # Screen has stabilized — IDE AI is done
                self.log("IDE response stabilized", "agent")
                break

            self.stop_event.wait(2.0)

    def _process_user_messages(self):
        """Process any messages from the user."""
        with self._user_msg_lock:
            messages = self._user_messages[:]
            self._user_messages.clear()

        for msg in messages:
            self.log(f"User message: {msg}", "agent")
            self.chat_callback("user", msg)
            # Add to conversation history so the LLM sees it
            self.conversation_history.append({
                "role": "user",
                "content": f"[USER OVERRIDE] {msg}"
            })

    # ── Helpers ────────────────────────────────────────────────────────

    def log(self, msg: str, tag: str = "info"):
        logger.info(msg)
        if self.log_callback:
            self.log_callback(msg, tag)

    def _save_session_log(self):
        """Save the session log to a markdown file."""
        if not self._session_log:
            return

        try:
            log_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                "core", "agent_sessions"
            )
            os.makedirs(log_dir, exist_ok=True)

            filename = f"session_{self._session_id}.md"
            filepath = os.path.join(log_dir, filename)

            with open(filepath, "w", encoding="utf-8") as f:
                f.write(f"# Agent Session {self._session_id}\n\n")
                f.write(f"**Task:** {self.task}\n")
                f.write(f"**Mode:** {self.mode}\n")
                f.write(f"**LLM:** {self.llm.provider}/{self.llm.model}\n")
                f.write(f"**Steps:** {self.step_count}\n")
                f.write(f"**Errors:** {self.errors_encountered}\n\n")
                f.write("## Steps\n\n")
                for entry in self._session_log:
                    f.write(f"- {entry}\n")

            self.log(f"Session log saved: {filename}", "agent")
        except Exception as e:
            logger.error(f"Failed to save session log: {e}")
