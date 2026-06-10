"""OS-keyring read/write for LLM API keys, with env-var fallback for reads.

Service name `pyirena-ai` is shared with pyirena's in-GUI AI advisor
(`pyirena/gui/ai_advisor.py:174`) so a user who has already configured a
key there gets it for free here.

`keyring` is an optional dependency: if it isn't installed, reads fall back
to the matching environment variable, and writes are a no-op with a
warning. Provider names map to keyring entries:

    anthropic  → ANTHROPIC_API_KEY     (env fallback)
    openai     → OPENAI_API_KEY        (env fallback)
    lmstudio   → LMSTUDIO_API_KEY      (most local servers ignore this)
    ollama     → OLLAMA_API_KEY        (most local servers ignore this)
"""

from __future__ import annotations

import os
import sys

KEYRING_SERVICE = "pyirena-ai"

KEY_NAMES: dict[str, str] = {
    "anthropic": "anthropic_api_key",
    "openai":    "openai_api_key",
    "lmstudio":  "lmstudio_api_key",
    "ollama":    "ollama_api_key",
}

ENV_VARS: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai":    "OPENAI_API_KEY",
    "lmstudio":  "LMSTUDIO_API_KEY",
    "ollama":    "OLLAMA_API_KEY",
}


def get_api_key(provider: str) -> str:
    """Return API key for `provider`, preferring keyring over env var."""
    keyring_name = KEY_NAMES.get(provider, provider)
    try:
        import keyring  # noqa: PLC0415
        val = keyring.get_password(KEYRING_SERVICE, keyring_name)
        if val:
            return val
    except ImportError:
        pass
    except Exception as e:
        print(f"warning: keyring read failed for {provider!r}: {e}", file=sys.stderr)
    return os.environ.get(ENV_VARS.get(provider, ""), "")


def set_api_key(provider: str, key: str) -> bool:
    """Store API key for `provider` in the OS keyring. Returns True on success."""
    keyring_name = KEY_NAMES.get(provider, provider)
    try:
        import keyring  # noqa: PLC0415
    except ImportError:
        print(
            "warning: the `keyring` package is not installed. "
            "Install with: pip install \"pyirena-ai[keyring]\"\n"
            f"For now, set the {ENV_VARS.get(provider, provider.upper() + '_API_KEY')} "
            "environment variable instead.",
            file=sys.stderr,
        )
        return False
    try:
        keyring.set_password(KEYRING_SERVICE, keyring_name, key)
        return True
    except Exception as e:
        print(f"warning: keyring write failed for {provider!r}: {e}", file=sys.stderr)
        return False


def have_api_key(provider: str) -> bool:
    return bool(get_api_key(provider))
