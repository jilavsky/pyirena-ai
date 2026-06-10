"""User configuration: read/write `~/.pyirena-ai/config.toml`.

The config file is auto-created with sensible defaults the first time
something reads it. Per-provider sections carry `model` and `base_url`;
API keys are NEVER written here — they go through `keyring_io.py`.

CLI flags override the config file for a single invocation; `update_provider`
persists a change back to disk.
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore[no-redef]


CONFIG_DIR = Path(os.environ.get("PYIRENA_AI_HOME", str(Path.home() / ".pyirena-ai")))
CONFIG_FILE = CONFIG_DIR / "config.toml"


# Built-in defaults shipped with the package. Used to initialise a fresh
# config file and to fill any missing sections in an older one.
DEFAULT_PROVIDERS: dict[str, dict[str, str]] = {
    "anthropic": {"model": "claude-opus-4-7",       "base_url": ""},
    "openai":    {"model": "gpt-4o",                "base_url": "https://api.openai.com/v1"},
    "lmstudio":  {"model": "local-model",           "base_url": "http://localhost:1234/v1"},
    "ollama":    {"model": "llama3.1",              "base_url": "http://localhost:11434/v1"},
}


@dataclass
class ProviderSettings:
    name:     str
    model:    str = ""
    base_url: str = ""


@dataclass
class Settings:
    providers: dict[str, ProviderSettings] = field(default_factory=dict)

    def get(self, name: str) -> ProviderSettings:
        if name not in self.providers:
            raise KeyError(
                f"No settings for provider {name!r}. "
                f"Known: {', '.join(sorted(self.providers))}"
            )
        return self.providers[name]


def load_settings() -> Settings:
    """Load `~/.pyirena-ai/config.toml`, creating it with defaults if missing."""
    if not CONFIG_FILE.exists():
        _write_default_config()

    with CONFIG_FILE.open("rb") as f:
        data = tomllib.load(f)

    providers: dict[str, ProviderSettings] = {}
    raw = data.get("provider", {}) or {}
    for name, defaults in DEFAULT_PROVIDERS.items():
        section = raw.get(name, {}) or {}
        providers[name] = ProviderSettings(
            name=name,
            model=section.get("model", defaults["model"]),
            base_url=section.get("base_url", defaults["base_url"]),
        )
    return Settings(providers=providers)


def update_provider(
    name: str,
    *,
    model: str | None = None,
    base_url: str | None = None,
) -> None:
    """Persist a model/base_url change for one provider."""
    settings = load_settings()
    if name not in settings.providers:
        settings.providers[name] = ProviderSettings(name=name)
    if model is not None:
        settings.providers[name].model = model
    if base_url is not None:
        settings.providers[name].base_url = base_url
    _write_settings(settings)


# ---------------------------------------------------------------------------
# Disk I/O
# ---------------------------------------------------------------------------

def _write_default_config() -> None:
    """Create CONFIG_FILE on disk with DEFAULT_PROVIDERS."""
    settings = Settings(providers={
        name: ProviderSettings(name=name, model=d["model"], base_url=d["base_url"])
        for name, d in DEFAULT_PROVIDERS.items()
    })
    _write_settings(settings)


def _write_settings(settings: Settings) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "# pyirena-ai config — managed via `pyirena-ai` CLI.",
        "# API keys are NEVER stored here; they live in the OS keyring",
        "# under service name 'pyirena-ai'.",
        "",
    ]
    for name in sorted(settings.providers):
        p = settings.providers[name]
        lines.append(f"[provider.{name}]")
        lines.append(f'model    = "{_toml_escape(p.model)}"')
        lines.append(f'base_url = "{_toml_escape(p.base_url)}"')
        lines.append("")
    CONFIG_FILE.write_text("\n".join(lines), encoding="utf-8")


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# CLI helpers
# ---------------------------------------------------------------------------

def summarise_for_cli(settings: Settings, key_status: dict[str, bool]) -> str:
    """Pretty-print provider list for `pyirena-ai providers`."""
    rows: list[str] = ["Provider     Model                          Base URL                           Key"]
    rows.append("-" * 110)
    for name in sorted(settings.providers):
        p = settings.providers[name]
        url = p.base_url or "(default)"
        key = "set" if key_status.get(name) else "not set"
        rows.append(f"{name:<12} {p.model:<30} {url:<35} {key}")
    return "\n".join(rows)
