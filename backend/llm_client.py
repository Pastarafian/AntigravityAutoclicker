"""
Unified LLM Client — DeepSeek, Kimi (Moonshot), and Ollama
===========================================================
All three providers use OpenAI-compatible chat completions API.
"""

import json
import os
import time
import logging
import urllib.request
import urllib.error
from typing import List, Dict, Optional, Callable, Any

logger = logging.getLogger(__name__)


def _load_env(env_path: str = None) -> dict:
    """Load .env file into a dict (no external dependency)."""
    if env_path is None:
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    env = {}
    if os.path.exists(env_path):
        with open(env_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                env[key.strip()] = val.strip()
    return env


# ═══════════════════════════════════════════════════════════════════
# Provider Configurations
# ═══════════════════════════════════════════════════════════════════

PROVIDERS = {
    "ollama": {
        "name": "Ollama (Local)",
        "base_url": "http://{host}:{port}/v1/chat/completions",
        "models_url": "http://{host}:{port}/api/tags",
        "default_model": "llama3.2:latest",
        "needs_key": False,
        "env_key": None,
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/chat/completions",
        "models_url": "https://api.deepseek.com/models",
        "default_model": "deepseek-chat",
        "needs_key": True,
        "env_key": "DEEPSEEK_API_KEY",
        "available_models": [
            "deepseek-chat",
            "deepseek-reasoner",
        ],
    },
    "kimi": {
        "name": "Kimi (Moonshot)",
        "base_url": "https://api.moonshot.cn/v1/chat/completions",
        "models_url": "https://api.moonshot.cn/v1/models",
        "default_model": "moonshot-v1-128k",
        "needs_key": True,
        "env_key": "KIMI_API_KEY",
        "available_models": [
            "moonshot-v1-8k",
            "moonshot-v1-32k",
            "moonshot-v1-128k",
        ],
    },
}


class LLMClient:
    """Unified LLM client supporting Ollama, DeepSeek, and Kimi."""

    def __init__(self, provider: str = "ollama", model: str = None):
        env = _load_env()

        self.provider = provider
        self.config = PROVIDERS.get(provider, PROVIDERS["ollama"])
        self.model = model or self.config["default_model"]
        self.api_key = None

        # Load API key from .env
        if self.config["needs_key"] and self.config["env_key"]:
            self.api_key = env.get(self.config["env_key"], "")
            if not self.api_key:
                self.api_key = os.environ.get(self.config["env_key"], "")

        # Ollama host/port from env
        self.ollama_host = env.get("OLLAMA_HOST", os.environ.get("OLLAMA_HOST", "localhost"))
        self.ollama_port = env.get("OLLAMA_PORT", os.environ.get("OLLAMA_PORT", "11434"))

        # Token tracking
        self.total_tokens_used = 0
        self.session_cost = 0.0

        logger.info(f"LLMClient initialized: provider={provider}, model={self.model}")

    @property
    def base_url(self) -> str:
        url = self.config["base_url"]
        if self.provider == "ollama":
            url = url.format(host=self.ollama_host, port=self.ollama_port)
        return url

    def is_available(self) -> bool:
        """Check if the selected provider is reachable."""
        try:
            if self.provider == "ollama":
                url = f"http://{self.ollama_host}:{self.ollama_port}/api/tags"
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=3) as resp:
                    return resp.status == 200
            elif self.config["needs_key"]:
                return bool(self.api_key)
            return False
        except Exception:
            return False

    def list_models(self) -> List[str]:
        """List available models for the current provider."""
        try:
            if self.provider == "ollama":
                url = f"http://{self.ollama_host}:{self.ollama_port}/api/tags"
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read().decode())
                    return [m["name"] for m in data.get("models", [])]
            elif "available_models" in self.config:
                return self.config["available_models"]
        except Exception as e:
            logger.warning(f"Failed to list models: {e}")
        return []

    def chat(self, messages: List[Dict], system: str = "",
             temperature: float = 0.7, max_tokens: int = 2048) -> str:
        """Send a chat completion request and return the assistant's response text."""
        # Prepend system message if provided
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        payload = {
            "model": self.model,
            "messages": full_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base_url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode())

                # Track tokens
                usage = result.get("usage", {})
                tokens = usage.get("total_tokens", 0)
                self.total_tokens_used += tokens
                self._track_cost(tokens)

                # Extract response
                choices = result.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
                return ""
        except urllib.error.HTTPError as e:
            body = e.read().decode() if e.fp else ""
            logger.error(f"LLM API error ({e.code}): {body[:200]}")
            raise RuntimeError(f"LLM API error {e.code}: {body[:200]}")
        except urllib.error.URLError as e:
            logger.error(f"LLM connection error: {e}")
            raise RuntimeError(f"LLM connection error: {e}")

    def chat_stream(self, messages: List[Dict], system: str = "",
                    callback: Callable[[str], None] = None,
                    temperature: float = 0.7, max_tokens: int = 2048) -> str:
        """Streaming chat — calls callback(token) for each token. Returns full response."""
        full_messages = []
        if system:
            full_messages.append({"role": "system", "content": system})
        full_messages.extend(messages)

        payload = {
            "model": self.model,
            "messages": full_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.base_url, data=data, headers=headers, method="POST")

        full_response = []
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                for line in resp:
                    line = line.decode("utf-8").strip()
                    if not line or line == "data: [DONE]":
                        continue
                    if line.startswith("data: "):
                        line = line[6:]
                    try:
                        chunk = json.loads(line)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        token = delta.get("content", "")
                        if token:
                            full_response.append(token)
                            if callback:
                                callback(token)
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.error(f"Streaming error: {e}")

        return "".join(full_response)

    def _track_cost(self, tokens: int):
        """Estimate cost based on provider pricing."""
        if self.provider == "deepseek":
            # DeepSeek-chat: ~$0.14/M input, $0.28/M output (blended ~$0.20/M)
            self.session_cost += tokens * 0.0000002
        elif self.provider == "kimi":
            # Moonshot: ~$1.00/M tokens (blended)
            self.session_cost += tokens * 0.000001

    def get_status(self) -> dict:
        """Return current LLM client status."""
        return {
            "provider": self.provider,
            "provider_name": self.config["name"],
            "model": self.model,
            "available": self.is_available(),
            "has_key": bool(self.api_key) if self.config["needs_key"] else True,
            "total_tokens": self.total_tokens_used,
            "session_cost_usd": round(self.session_cost, 6),
        }

    def switch_provider(self, provider: str, model: str = None):
        """Switch to a different provider/model at runtime."""
        if provider in PROVIDERS:
            env = _load_env()
            self.provider = provider
            self.config = PROVIDERS[provider]
            self.model = model or self.config["default_model"]
            if self.config["needs_key"] and self.config["env_key"]:
                self.api_key = env.get(self.config["env_key"], "")
                if not self.api_key:
                    self.api_key = os.environ.get(self.config["env_key"], "")
            else:
                self.api_key = None
            logger.info(f"Switched to {provider}/{self.model}")
