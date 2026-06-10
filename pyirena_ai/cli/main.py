"""`pyirena-ai` command-line entry point.

Subcommands:

  fit FILE         run the agent on one NXcanSAS file
  gui              launch the Gradio fitting GUI
  providers        show configured providers and their endpoints
  set-key NAME     prompt for an API key and store it in the OS keyring
  strategies       list available fitting strategies
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from pyirena_ai import __version__
from pyirena_ai.config.keyring_io import (
    KEY_NAMES,
    get_api_key,
    have_api_key,
    set_api_key,
)
from pyirena_ai.config.settings import (
    DEFAULT_PROVIDERS,
    load_settings,
    summarise_for_cli,
)
from pyirena_ai.core.agent import Agent
from pyirena_ai.core.audit import default_audit_path, write_audit_json
from pyirena_ai.core.session import RunSession
from pyirena_ai.core.skills import build_system_prompt
from pyirena_ai.core.strategy import list_strategies, load_strategy
from pyirena_ai.core.tools import dispatch
from pyirena_ai.llm.pricing import estimate_cost_usd
from pyirena_ai.llm.registry import build_provider, known_providers


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pyirena-ai",
        description="AI-driven SAXS/USAXS fitting on top of pyirena.",
    )
    p.add_argument("--version", action="version", version=f"pyirena-ai {__version__}")

    sub = p.add_subparsers(dest="command", required=True)

    # ---- fit ---------------------------------------------------------
    p_fit = sub.add_parser("fit", help="Run the agent on one NXcanSAS file.")
    p_fit.add_argument("input", help="Path to a NXcanSAS HDF5 file.")
    p_fit.add_argument("--model", default="unified",
                       choices=["unified"],
                       help="pyirena model to fit (Phase 1: unified only).")
    p_fit.add_argument("--strategy", default="unified_fit_default",
                       help="Name of a bundled or user strategy (or .md path).")
    p_fit.add_argument("--provider", default="anthropic",
                       choices=known_providers(),
                       help="LLM provider.")
    p_fit.add_argument("--model-id", default="",
                       help="LLM model identifier (e.g. claude-opus-4-7). "
                            "Defaults to the per-provider setting.")
    p_fit.add_argument("--base-url", default="",
                       help="Override provider base URL (institutional proxy, "
                            "local server, etc.).")
    p_fit.add_argument("--audit-out", default="",
                       help="Path for the JSON audit trail. "
                            "Default: <input>.audit.json")
    p_fit.add_argument("--save-out", default="",
                       help="HDF5 output path. Default: overwrite input.")
    p_fit.add_argument("--max-tokens", type=int, default=4096,
                       help="Max tokens per LLM turn.")
    p_fit.add_argument("--max-iterations", type=int, default=50,
                       help="Hard cap on tool-use round-trips.")
    p_fit.add_argument("--context", default="",
                       help="One-shot context for this fit (sample description, "
                            "expected structure, etc.). Appended to the system prompt.")
    p_fit.add_argument("--verbose", "-v", action="store_true",
                       help="Stream agent progress to stderr.")
    p_fit.set_defaults(func=cmd_fit)

    # ---- providers ---------------------------------------------------
    p_prov = sub.add_parser("providers", help="Show configured providers.")
    p_prov.set_defaults(func=cmd_providers)

    # ---- set-key -----------------------------------------------------
    p_key = sub.add_parser("set-key", help="Store an API key in the OS keyring.")
    p_key.add_argument("provider", choices=known_providers())
    p_key.set_defaults(func=cmd_set_key)

    # ---- strategies --------------------------------------------------
    p_strat = sub.add_parser("strategies", help="List available fitting strategies.")
    p_strat.set_defaults(func=cmd_strategies)

    # ---- gui ---------------------------------------------------------
    p_gui = sub.add_parser("gui", help="Launch the Gradio fitting GUI.")
    p_gui.add_argument("--host", default="127.0.0.1",
                       help="Interface to bind (default: 127.0.0.1).")
    p_gui.add_argument("--port", type=int, default=7860,
                       help="Port to listen on (default: 7860).")
    p_gui.add_argument("--share", action="store_true",
                       help="Create a public Gradio share link (requires internet).")
    p_gui.set_defaults(func=cmd_gui)

    return p


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------

def cmd_providers(args: argparse.Namespace) -> int:
    settings = load_settings()
    key_status = {name: have_api_key(name) for name in known_providers()}
    print(summarise_for_cli(settings, key_status))
    print(
        "\nKeys are stored in the OS keyring under service name 'pyirena-ai' "
        "(shared with pyirena's in-GUI AI advisor)."
    )
    return 0


def cmd_set_key(args: argparse.Namespace) -> int:
    provider = args.provider
    prompt = f"Enter API key for {provider!r} (input hidden): "
    try:
        key = getpass.getpass(prompt)
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.", file=sys.stderr)
        return 1
    if not key.strip():
        print("Empty key — not stored.", file=sys.stderr)
        return 1
    ok = set_api_key(provider, key.strip())
    if ok:
        print(f"OK — key for {provider!r} stored in keyring "
              f"(entry name '{KEY_NAMES.get(provider, provider)}').")
        return 0
    return 1


def cmd_strategies(args: argparse.Namespace) -> int:
    names = list_strategies()
    if not names:
        print("No strategies found.")
        return 0
    print("Available strategies:")
    for n in names:
        print(f"  - {n}")
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    try:
        from pyirena_ai.gui.app import launch  # noqa: PLC0415
    except ImportError as e:
        print(
            f"error: {e}\n"
            "Install the GUI extra: pip install \"pyirena-ai[gui]\"",
            file=sys.stderr,
        )
        return 2
    print(f"Starting Gradio GUI at http://{args.host}:{args.port} …")
    launch(host=args.host, port=args.port, share=args.share)
    return 0


def cmd_fit(args: argparse.Namespace) -> int:
    input_path = Path(args.input).resolve()
    if not input_path.is_file():
        print(f"error: input file not found: {input_path}", file=sys.stderr)
        return 2

    settings = load_settings()

    try:
        provider_settings = settings.get(args.provider)
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    model_id = args.model_id or provider_settings.model
    base_url = args.base_url or provider_settings.base_url
    api_key  = get_api_key(args.provider)

    if not api_key and args.provider in ("anthropic", "openai"):
        print(
            f"error: no API key found for {args.provider!r}. "
            f"Run: pyirena-ai set-key {args.provider}",
            file=sys.stderr,
        )
        return 2

    try:
        strategy_text = load_strategy(args.strategy)
    except KeyError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    system_prompt = build_system_prompt(
        strategy_text,
        tool_name="unified_fit",
        extra_context=args.context,
    )

    progress = (lambda msg: print(msg, file=sys.stderr)) if args.verbose else None

    provider = build_provider(
        args.provider,
        api_key=api_key,
        model=model_id,
        base_url=base_url,
    )

    save_out = args.save_out or str(input_path)
    user_prompt = _build_user_prompt(input_path, save_out)

    session = RunSession(
        input_file=str(input_path),
        provider=args.provider,
        model=model_id,
        base_url=base_url,
        strategy=args.strategy,
        system_prompt=system_prompt,
    )

    agent = Agent(
        provider,
        system_prompt=system_prompt,
        session=session,
        max_iterations=args.max_iterations,
        max_tokens_per_turn=args.max_tokens,
        on_progress=progress,
    )

    try:
        final = agent.run(user_prompt)
    except Exception as e:  # provider / network / SDK errors
        session.add_error(f"{type(e).__name__}: {e}")
        audit_path = Path(args.audit_out) if args.audit_out else default_audit_path(input_path)
        write_audit_json(session, audit_path)
        print(f"error: {type(e).__name__}: {e}", file=sys.stderr)
        print(f"(partial audit written to {audit_path})", file=sys.stderr)
        return 3

    session.cost_usd_estimate = estimate_cost_usd(
        model_id, session.input_tokens, session.output_tokens
    )

    # Make sure pyirena's in-memory session, if still open, is released.
    if session.pyirena_session_id:
        dispatch("close_session", {"session_id": session.pyirena_session_id})

    audit_path = Path(args.audit_out) if args.audit_out else default_audit_path(input_path)
    write_audit_json(session, audit_path)

    print()
    print(final.text or "(no final assistant text)")
    print()
    print(f"input file:        {input_path}")
    print(f"saved fit to:      {session.saved_to or '(not saved by agent)'}")
    print(f"tools invoked:     {session.tool_use_count()}")
    print(f"tokens (in/out):   {session.input_tokens} / {session.output_tokens}")
    if session.cost_usd_estimate is not None:
        print(f"estimated cost:    ${session.cost_usd_estimate:.4f} USD")
    print(f"audit trail:       {audit_path}")
    if session.final_chi_squared is not None:
        print(f"final χ²ᵣ:         {session.final_chi_squared:.4f}")

    return 0


def _build_user_prompt(input_path: Path, save_out: str) -> str:
    return (
        f"Fit the dataset at:\n  {input_path}\n\n"
        f"When done, save the result with:\n"
        f"  save_fit(session_id, output_path={save_out!r})\n\n"
        "Follow the staged fitting workflow from your system prompt. "
        "When you finish, return a short plain-English summary as your "
        "final message — do not call any more tools after that."
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
