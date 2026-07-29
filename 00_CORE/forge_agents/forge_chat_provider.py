"""
forge_chat_provider.py — Dashboard Chat Provider Configuration
===============================================================
Manages API keys for the dashboard chat feature.
Supports: Claude Code, Google AI Pro, Hermes (MiMo).

Usage:
    POST /api/chat/config — set API keys
    GET /api/chat/config — get current config (masked)
    POST /api/chat/send — send message with selected provider
"""

from __future__ import annotations
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("ChatProvider")

FORGE_ROOT = Path(__file__).parent.parent.parent
CONFIG_PATH = FORGE_ROOT / "05_STATE" / "chat_providers.json"

# Provider configs
PROVIDERS = {
    "hermes": {
        "name": "Hermes (MiMo)",
        "base_url": "https://api.nousresearch.com/v1",
        "model": "hermes-3-llama-3.1-405b",
        "env_key": "HERMES_API_KEY",
    },
    "claude": {
        "name": "Claude Code (Anthropic)",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-sonnet-4-20250514",
        "env_key": "ANTHROPIC_API_KEY",
    },
    "google": {
        "name": "Google AI Pro (Antigravity)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "model": "gemini-2.5-pro",
        "env_key": "GOOGLE_API_KEY",
    },
}


class ChatProviderConfig:
    """Manages API keys for dashboard chat."""

    def __init__(self):
        self._config = self._load()

    def _load(self) -> dict:
        """Load config from file or create default."""
        if CONFIG_PATH.exists():
            try:
                return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.debug("exception ignorée (%s): %s", type(exc).__name__, exc)
        return {
            "active_provider": "hermes",
            "keys": {},
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def _save(self):
        """Persist config."""
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps(self._config, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Failed to save chat config: {e}")

    def set_key(self, provider: str, api_key: str):
        """Set API key for a provider."""
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")
        self._config.setdefault("keys", {})[provider] = api_key
        # Also set env var for forge_llm
        os.environ[PROVIDERS[provider]["env_key"]] = api_key
        self._save()
        logger.info(f"[ChatProvider] Key set for {provider}")

    def set_active(self, provider: str):
        """Set the active provider."""
        if provider not in PROVIDERS:
            raise ValueError(f"Unknown provider: {provider}")
        self._config["active_provider"] = provider
        self._save()

    def get_config(self) -> dict:
        """Get current config (keys masked)."""
        keys = self._config.get("keys", {})
        masked = {}
        for p, key in keys.items():
            if key:
                masked[p] = key[:8] + "..." + key[-4:] if len(key) > 12 else "***"
            else:
                masked[p] = None

        return {
            "active_provider": self._config.get("active_provider", "hermes"),
            "providers": {
                p: {
                    "name": info["name"],
                    "model": info["model"],
                    "has_key": p in keys and bool(keys[p]),
                }
                for p, info in PROVIDERS.items()
            },
            "keys_masked": masked,
        }

    def get_active_key(self) -> Optional[str]:
        """Get the active provider's API key."""
        provider = self._config.get("active_provider", "hermes")
        keys = self._config.get("keys", {})
        key = keys.get(provider)

        # Fallback to env var
        if not key:
            key = os.environ.get(PROVIDERS.get(provider, {}).get("env_key", ""), "")

        return key

    def get_active_provider(self) -> dict:
        """Get active provider info."""
        provider = self._config.get("active_provider", "hermes")
        info = PROVIDERS.get(provider, PROVIDERS["hermes"])
        return {
            "provider": provider,
            "name": info["name"],
            "base_url": info["base_url"],
            "model": info["model"],
            "has_key": bool(self.get_active_key()),
        }


# Singleton
_instance: ChatProviderConfig | None = None


def get_chat_config() -> ChatProviderConfig:
    global _instance
    if _instance is None:
        _instance = ChatProviderConfig()
    return _instance
