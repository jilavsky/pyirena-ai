"""Shared run assembly — one way to build (and finish) an agent run.

The CLI ``fit`` command, the Gradio one-shot Fit tab, and the Gradio Chat
tab all need the same wiring: resolve provider settings → build the
provider → load the strategy → assemble the system prompt → create the
`RunSession` → construct the `Agent` with the right caps and tool subset.
And at the end: estimate cost, close the pyirena session, write the audit.

This module is that single implementation. Frontends supply a `RunConfig`
plus their own `AgentHooks` / progress callback and get back a ready
`RunBundle`. A future batch/folder runner or an embedded advisor should
need nothing beyond this module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from pyirena_ai.config.keyring_io import get_api_key
from pyirena_ai.config.settings import load_settings
from pyirena_ai.core.agent import Agent, AgentHooks, ProgressFn
from pyirena_ai.core.audit import default_audit_path, write_audit_json
from pyirena_ai.core.models import FitModel, get_model
from pyirena_ai.core.session import RunSession
from pyirena_ai.core.skills import build_system_prompt
from pyirena_ai.core.strategy import load_strategy
from pyirena_ai.core.tools import dispatch, schemas_for_groups
from pyirena_ai.llm.pricing import estimate_cost_usd
from pyirena_ai.llm.registry import LOCAL_PROVIDERS, agent_defaults, build_provider

# Local servers may take minutes per turn on big prompts; commercial APIs
# should respond well within two.
TIMEOUT_LOCAL_S = 600.0
TIMEOUT_COMMERCIAL_S = 120.0


@dataclass
class RunConfig:
    """Everything needed to assemble one agent run."""

    file_path: str
    provider_name: str
    model_id: str = ""              # "" → per-provider configured default
    base_url: str = ""              # "" → per-provider configured default
    strategy: str = ""              # "" → fit model's default strategy
    model_key: str = "unified_fit"  # FIT_MODELS key or CLI alias
    user_context: str = ""
    include_strategy: bool = True
    include_skills: bool = True
    show_thinking: bool = False
    all_tools: bool = False         # True → expose the full control surface
    max_tokens_per_turn: int = 4096
    max_iterations: int = 0         # 0 → provider-tier default
    keep_images: int = 2            # newest N images kept in conversation


@dataclass
class RunBundle:
    """The assembled pieces of a run, ready to execute."""

    agent: Agent
    session: RunSession
    fit_model: FitModel
    provider_name: str = ""
    model_id: str = ""
    max_iterations: int = 0
    max_input_tokens: int = 0
    tool_schemas: list = field(default_factory=list)


def build_run(
    config: RunConfig,
    *,
    hooks: AgentHooks | None = None,
    on_progress: ProgressFn | None = None,
) -> RunBundle:
    """Assemble provider + system prompt + session + agent for one run.

    Raises `KeyError` for an unknown provider or strategy — callers surface
    that to the user however fits their UI.
    """
    file_path = _normalize_path(config.file_path)

    settings = load_settings()
    prov_cfg = settings.get(config.provider_name)      # KeyError if unknown
    model_id = config.model_id or prov_cfg.model
    base_url = config.base_url or prov_cfg.base_url
    api_key = get_api_key(config.provider_name)

    fit_model = get_model(config.model_key)
    strategy_name = config.strategy or fit_model.default_strategy
    strategy_text = (
        load_strategy(strategy_name) if config.include_strategy else ""
    )  # KeyError if not found

    system_prompt = build_system_prompt(
        strategy_text,
        tool_name=fit_model.skill,
        extra_context=config.user_context,
        include_strategy=config.include_strategy,
        include_skills=config.include_skills,
    )

    timeout = (
        TIMEOUT_LOCAL_S if config.provider_name in LOCAL_PROVIDERS
        else TIMEOUT_COMMERCIAL_S
    )
    provider = build_provider(
        config.provider_name,
        api_key=api_key,
        model=model_id,
        base_url=base_url,
        timeout=timeout,
        enable_thinking=config.show_thinking,
        supports_vision=prov_cfg.vision,
    )

    session = RunSession(
        input_file=file_path,
        provider=config.provider_name,
        model=model_id,
        base_url=base_url,
        strategy=strategy_name,
        system_prompt=system_prompt,
    )

    defaults = agent_defaults(config.provider_name)
    max_iterations = config.max_iterations or defaults["max_iterations"]
    max_input_tokens = defaults["max_input_tokens"]

    tool_schemas = schemas_for_groups(None if config.all_tools else fit_model.tool_groups)

    agent = Agent(
        provider,
        system_prompt=system_prompt,
        session=session,
        tools=tool_schemas,
        max_iterations=max_iterations,
        max_input_tokens=max_input_tokens,
        max_tokens_per_turn=config.max_tokens_per_turn,
        keep_images=config.keep_images,
        on_progress=on_progress,
        hooks=hooks,
    )

    return RunBundle(
        agent=agent,
        session=session,
        fit_model=fit_model,
        provider_name=config.provider_name,
        model_id=model_id,
        max_iterations=max_iterations,
        max_input_tokens=max_input_tokens,
        tool_schemas=tool_schemas,
    )


def finish_run(
    session: RunSession,
    *,
    audit_path: str | Path | None = None,
) -> Path:
    """Run epilogue: cost estimate, close pyirena session, write audit.

    Safe to call after both successful and failed runs. Returns the audit
    path written.
    """
    session.finished_at = (
        datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    )
    session.cost_usd_estimate = estimate_cost_usd(
        session.model, session.input_tokens, session.output_tokens
    )

    if session.pyirena_session_id:
        try:
            dispatch("close_session", {"session_id": session.pyirena_session_id})
        except Exception:  # noqa: BLE001 — dispatch shouldn't raise, belt & braces
            pass

    path = Path(audit_path) if audit_path else default_audit_path(session.input_file)
    return write_audit_json(session, path)


def _normalize_path(p: str) -> str:
    """Strip whitespace and surrounding quotes users paste from the shell."""
    return (p or "").strip().strip("'\"")
