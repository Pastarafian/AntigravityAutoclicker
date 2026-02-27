"""
Workspace Scanner — Project awareness for the AI Agent
========================================================
Scans the workspace directory to build a context summary:
file tree, languages, frameworks, key config files, and git status.
"""

import os
import subprocess
import logging
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Files to always read for context (first 100 lines each)
KEY_FILES = [
    "package.json", "Cargo.toml", "pyproject.toml", "requirements.txt",
    "setup.py", "go.mod", "CMakeLists.txt", "Makefile",
    "README.md", "README.rst", "README.txt",
    ".env.example", "docker-compose.yml", "Dockerfile",
    "tsconfig.json", "vite.config.ts", "webpack.config.js",
    "tauri.conf.json",
]

# Directories to skip
SKIP_DIRS = {
    "node_modules", ".git", "target", "dist", "build", "__pycache__",
    ".vscode", ".idea", ".next", "venv", ".venv", "env", ".env",
    "vendor", "bower_components", ".cache", ".gradle", "bin", "obj",
    "coverage", ".pytest_cache", ".mypy_cache", "src-tauri/target",
}

# Extension → language mapping
LANG_MAP = {
    ".py": "Python", ".rs": "Rust", ".ts": "TypeScript", ".tsx": "TypeScript/React",
    ".js": "JavaScript", ".jsx": "JavaScript/React", ".go": "Go",
    ".java": "Java", ".c": "C", ".cpp": "C++", ".h": "C/C++ Header",
    ".cs": "C#", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift",
    ".kt": "Kotlin", ".lua": "Lua", ".html": "HTML", ".css": "CSS",
    ".sql": "SQL", ".sh": "Shell", ".bat": "Batch", ".ps1": "PowerShell",
    ".mq5": "MQL5", ".mq4": "MQL4", ".mqh": "MQL Header",
    ".toml": "TOML", ".yaml": "YAML", ".yml": "YAML", ".json": "JSON",
    ".md": "Markdown", ".xml": "XML",
}


class WorkspaceContext:
    """Structured workspace information."""

    def __init__(self):
        self.root: str = ""
        self.file_tree: str = ""
        self.file_count: int = 0
        self.languages: Dict[str, int] = {}  # language → file count
        self.framework: str = "Unknown"
        self.key_files: Dict[str, str] = {}  # filename → content preview
        self.git_status: str = ""
        self.git_branch: str = ""
        self.recent_changes: str = ""

    def to_prompt(self) -> str:
        """Convert to a text summary suitable for LLM system prompt injection."""
        parts = [
            f"PROJECT ROOT: {self.root}",
            f"FRAMEWORK: {self.framework}",
            f"FILES: {self.file_count} total",
            f"GIT BRANCH: {self.git_branch}" if self.git_branch else "",
        ]

        if self.languages:
            top_langs = sorted(self.languages.items(), key=lambda x: -x[1])[:5]
            lang_str = ", ".join(f"{l}({c})" for l, c in top_langs)
            parts.append(f"LANGUAGES: {lang_str}")

        if self.file_tree:
            parts.append(f"\nFILE STRUCTURE:\n{self.file_tree}")

        if self.key_files:
            parts.append("\nKEY FILES:")
            for name, content in self.key_files.items():
                preview = content[:500] if len(content) > 500 else content
                parts.append(f"\n--- {name} ---\n{preview}")

        if self.git_status:
            parts.append(f"\nGIT STATUS:\n{self.git_status}")

        if self.recent_changes:
            parts.append(f"\nRECENT CHANGES:\n{self.recent_changes}")

        return "\n".join(p for p in parts if p)

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "file_count": self.file_count,
            "languages": self.languages,
            "framework": self.framework,
            "git_branch": self.git_branch,
            "key_files": list(self.key_files.keys()),
            "has_git": bool(self.git_branch),
        }


class WorkspaceScanner:
    """Scans a workspace directory and builds a context summary."""

    def __init__(self):
        self._last_scan: Optional[WorkspaceContext] = None
        self._last_root: str = ""

    def scan(self, root_dir: str, max_files: int = 300) -> WorkspaceContext:
        """Full workspace scan. Returns WorkspaceContext."""
        ctx = WorkspaceContext()
        ctx.root = os.path.abspath(root_dir)

        if not os.path.isdir(ctx.root):
            logger.warning(f"Workspace root not found: {ctx.root}")
            return ctx

        # 1. Build file tree and count languages
        tree_lines = []
        file_count = 0
        lang_counts: Dict[str, int] = {}

        for dirpath, dirnames, filenames in os.walk(ctx.root):
            # Skip ignored directories
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]

            rel_dir = os.path.relpath(dirpath, ctx.root)
            depth = 0 if rel_dir == "." else rel_dir.count(os.sep) + 1

            if depth <= 3 and file_count < max_files:
                if rel_dir != ".":
                    indent = "  " * (depth - 1)
                    tree_lines.append(f"{indent}📁 {os.path.basename(dirpath)}/")

                for fname in sorted(filenames):
                    file_count += 1
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in LANG_MAP:
                        lang = LANG_MAP[ext]
                        lang_counts[lang] = lang_counts.get(lang, 0) + 1

                    if depth <= 2 and file_count < max_files:
                        indent = "  " * depth
                        tree_lines.append(f"{indent}📄 {fname}")

        ctx.file_tree = "\n".join(tree_lines[:200])  # Cap at 200 lines
        ctx.file_count = file_count
        ctx.languages = lang_counts

        # 2. Detect framework
        ctx.framework = self._detect_framework(ctx.root)

        # 3. Read key config files
        for fname in KEY_FILES:
            fpath = os.path.join(ctx.root, fname)
            if os.path.isfile(fpath):
                try:
                    with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                        lines = f.readlines()[:100]
                        ctx.key_files[fname] = "".join(lines)
                except Exception:
                    pass

        # 4. Git info
        ctx.git_branch = self._git_branch(ctx.root)
        ctx.git_status = self._git_status(ctx.root)
        ctx.recent_changes = self._git_diff_stat(ctx.root)

        self._last_scan = ctx
        self._last_root = ctx.root
        logger.info(f"Workspace scan: {file_count} files, framework={ctx.framework}")
        return ctx

    def get_recent_changes(self, root_dir: str = None) -> str:
        """Get recent file changes via git diff (uncommitted + staged)."""
        root = root_dir or self._last_root
        if not root:
            return ""
        return self._git_diff(root)

    def get_file_content(self, root_dir: str, rel_path: str, max_lines: int = 200) -> str:
        """Read a specific file from the workspace."""
        fpath = os.path.join(root_dir, rel_path)
        if not os.path.isfile(fpath):
            return f"[File not found: {rel_path}]"
        try:
            with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()[:max_lines]
                return "".join(lines)
        except Exception as e:
            return f"[Error reading {rel_path}: {e}]"

    def detect_workspace_from_title(self, window_title: str) -> Optional[str]:
        """Extract workspace root from an IDE window title."""
        # VS Code titles often look like: "filename.py — ProjectName — Visual Studio Code"
        # or "filename.py - ProjectName - Visual Studio Code"
        parts = window_title.replace("—", "-").split(" - ")
        for part in reversed(parts):
            part = part.strip()
            # Check common locations
            for base in [
                os.path.expanduser("~/Documents"),
                os.path.expanduser("~/Desktop"),
                os.path.expanduser("~/Projects"),
                os.path.expanduser("~"),
                "C:\\Users",
            ]:
                candidate = os.path.join(base, part)
                if os.path.isdir(candidate):
                    return candidate
        return None

    # ── Private helpers ───────────────────────────────────────────────

    def _detect_framework(self, root: str) -> str:
        """Detect the project framework from config files."""
        checks = [
            ("package.json", lambda d: self._detect_js_framework(d)),
            ("Cargo.toml", lambda _: "Rust"),
            ("pyproject.toml", lambda _: "Python"),
            ("requirements.txt", lambda _: "Python"),
            ("go.mod", lambda _: "Go"),
            ("CMakeLists.txt", lambda _: "C/C++"),
        ]
        for fname, detector in checks:
            fpath = os.path.join(root, fname)
            if os.path.isfile(fpath):
                try:
                    with open(fpath, "r") as f:
                        return detector(f.read())
                except Exception:
                    pass
        return "Unknown"

    def _detect_js_framework(self, package_json_content: str) -> str:
        """Detect JS/TS framework from package.json content."""
        import json as _json
        try:
            data = _json.loads(package_json_content)
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            if "@tauri-apps/api" in deps:
                return "Tauri + React" if "react" in deps else "Tauri"
            if "next" in deps:
                return "Next.js"
            if "react" in deps:
                return "React"
            if "vue" in deps:
                return "Vue"
            if "svelte" in deps:
                return "Svelte"
            if "express" in deps:
                return "Express.js"
            return "Node.js"
        except Exception:
            return "JavaScript"

    def _run_git(self, root: str, args: List[str], max_output: int = 5000) -> str:
        """Run a git command and return stdout."""
        try:
            result = subprocess.run(
                ["git"] + args,
                cwd=root, capture_output=True, text=True, timeout=10,
                encoding="utf-8", errors="replace",
            )
            output = result.stdout.strip()
            return output[:max_output] if len(output) > max_output else output
        except Exception:
            return ""

    def _git_branch(self, root: str) -> str:
        return self._run_git(root, ["branch", "--show-current"])

    def _git_status(self, root: str) -> str:
        return self._run_git(root, ["status", "--short"])

    def _git_diff_stat(self, root: str) -> str:
        return self._run_git(root, ["diff", "--stat", "HEAD"])

    def _git_diff(self, root: str) -> str:
        """Full git diff (uncommitted changes)."""
        return self._run_git(root, ["diff", "HEAD"], max_output=10000)

    def create_backup(self, root: str) -> Optional[str]:
        """Create a compressed backup of the workspace via git stash."""
        try:
            # Try git stash first (cleanest)
            status = self._git_status(root)
            if not status:
                logger.info("No changes to backup")
                return None

            # Create a named stash
            from datetime import datetime
            name = f"antigravity-backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
            result = subprocess.run(
                ["git", "stash", "push", "-m", name],
                cwd=root, capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0:
                logger.info(f"Backup created: {name}")
                # Immediately pop the stash to restore working state
                subprocess.run(
                    ["git", "stash", "pop"],
                    cwd=root, capture_output=True, text=True, timeout=30,
                )
                return name
        except Exception as e:
            logger.error(f"Backup failed: {e}")
        return None
