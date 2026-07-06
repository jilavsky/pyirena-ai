"""Fit-model registry.

pyirena-ai drives more than one pyirena fitting model. Each model differs in a
handful of presentation/wiring details — which expert-skill file to load, which
strategy to default to, which control-surface tool saves the result, and which
tool reports the live parameter state for the GUI panel. This registry is the
single place those differences live, so the runners, the CLI, and the GUI never
hardcode ``"unified_fit"`` again.

The agent itself sees *all* control tools regardless of the selected model
(``core/tools.py`` auto-exposes every ``pyirena.api.control.__all__`` function).
The model selection only steers the *system prompt* (strategy + skill) and a few
UI niceties — it never restricts the tool set.

Adding a new model (e.g. Modeling, Simple Fits) is a single ``FIT_MODELS`` entry
plus a strategy/skill markdown pair.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FitModel:
    key: str               # stable identifier, e.g. "unified_fit"
    label: str             # human label for the GUI dropdown
    skill: str             # tool_name passed to build_system_prompt / load_skills
    default_strategy: str  # strategy file stem to default to
    save_tool: str         # control tool that persists the fit (one-shot prompt text)
    state_tool: str        # control tool that returns live model state (GUI panel)


FIT_MODELS: dict[str, FitModel] = {
    "unified_fit": FitModel(
        key="unified_fit",
        label="Unified Fit",
        skill="unified_fit",
        default_strategy="unified_fit_default",
        save_tool="save_fit",
        state_tool="get_model_parameters",
    ),
    "size_distribution": FitModel(
        key="size_distribution",
        label="Size Distribution",
        skill="size_distribution",
        default_strategy="size_distribution_default",
        save_tool="save_sizes_fit",
        state_tool="get_sizes_config",
    ),
}

DEFAULT_MODEL = "unified_fit"

# CLI ``--model`` aliases → registry key (keeps the short CLI words stable).
CLI_MODEL_ALIASES: dict[str, str] = {
    "unified": "unified_fit",
    "sizes": "size_distribution",
}


def get_model(key: str | None) -> FitModel:
    """Return the FitModel for *key*, falling back to the default model.

    Accepts both registry keys and CLI aliases (``"unified"``, ``"sizes"``).
    """
    if key:
        if key in FIT_MODELS:
            return FIT_MODELS[key]
        if key in CLI_MODEL_ALIASES:
            return FIT_MODELS[CLI_MODEL_ALIASES[key]]
    return FIT_MODELS[DEFAULT_MODEL]


def model_choices() -> list[tuple[str, str]]:
    """``[(label, key), …]`` for a Gradio Dropdown (value is the registry key)."""
    return [(m.label, m.key) for m in FIT_MODELS.values()]
