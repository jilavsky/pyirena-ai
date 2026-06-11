"""Factory mapping a provider name to a constructed `LLMProvider`.

Defaults for `base_url` per provider are read from
`pyirena_ai.config.settings`; CLI flags override per invocation.

Agent caps by provider type
---------------------------
Commercial providers (anthropic, openai) are metered per token, so we
keep a firm cap on both iterations and cumulative input tokens to bound
cost. Local providers (lmstudio, ollama) are free to run, so we allow
more iterations and a very high token ceiling — the caps serve only as
protection against infinite loops or catastrophic failures.
"""

from __future__ import annotations

from pyirena_ai.llm.anthropic import AnthropicProvider
from pyirena_ai.llm.base import LLMProvider
from pyirena_ai.llm.openai_compat import OpenAICompatProvider

PROVIDER_CLASSES: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "openai":    OpenAICompatProvider,
    "lmstudio":  OpenAICompatProvider,
    "ollama":    OpenAICompatProvider,
}

LOCAL_PROVIDERS = {"lmstudio", "ollama"}
COMMERCIAL_PROVIDERS = {"anthropic", "openai"}

# max_iterations: hard cap on LLM ↔ tool round-trips
# max_input_tokens: cumulative input-token budget across the whole run
_AGENT_DEFAULTS = {
    "commercial": {"max_iterations": 30,  "max_input_tokens": 500_000},
    "local":      {"max_iterations": 150, "max_input_tokens": 10_000_000},
}


def agent_defaults(provider_name: str) -> dict:
    """Return {'max_iterations': int, 'max_input_tokens': int} for the provider."""
    tier = "local" if provider_name in LOCAL_PROVIDERS else "commercial"
    return dict(_AGENT_DEFAULTS[tier])


def known_providers() -> list[str]:
    return list(PROVIDER_CLASSES)


def build_provider(
    name: str,
    *,
    api_key: str,
    model: str,
    base_url: str = "",
    timeout: float = 120.0,
) -> LLMProvider:
    """Instantiate the provider class registered under `name`."""
    try:
        cls = PROVIDER_CLASSES[name]
    except KeyError as e:
        raise ValueError(
            f"Unknown provider {name!r}. Known: {', '.join(known_providers())}"
        ) from e
    return cls(api_key=api_key, model=model, base_url=base_url, timeout=timeout)
