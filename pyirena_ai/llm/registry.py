"""Factory mapping a provider name to a constructed `LLMProvider`.

Defaults for `base_url` per provider are read from
`pyirena_ai.config.settings`; CLI flags override per invocation.
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
