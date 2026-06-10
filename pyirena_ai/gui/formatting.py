"""Format pyirena control-surface dicts into human-readable Markdown strings
for the Gradio parameter table, agent log, and token counter panels.
"""

from __future__ import annotations

from typing import Any


def params_to_markdown(result: dict[str, Any]) -> str:
    """Render a `get_model_parameters` result dict as a Markdown table.

    Returns a placeholder string if the result contains an error or is empty.
    """
    if "error" in result:
        return f"**Error reading parameters:** {result['error']}"
    params = result.get("parameters") or []
    if not params:
        return "_No parameters (model not yet selected)_"

    lines = [
        "| Parameter | Value | Fixed | Lo | Hi |",
        "|-----------|------:|:-----:|---:|---:|",
    ]
    for p in params:
        name  = p.get("name", "?")
        val   = _fmt(p.get("value"))
        fixed = "✓" if p.get("fixed") else ""
        lo    = _fmt(p.get("lo"))
        hi    = _fmt(p.get("hi"))
        lines.append(f"| `{name}` | {val} | {fixed} | {lo} | {hi} |")

    chi = result.get("chi_squared")
    rchi = result.get("reduced_chi_squared")
    if chi is not None or rchi is not None:
        parts = []
        if chi is not None:
            parts.append(f"χ²={_fmt(chi)}")
        if rchi is not None:
            parts.append(f"χ²ᵣ={_fmt(rchi)}")
        lines.append("")
        lines.append("_" + "  ·  ".join(parts) + "_")

    return "\n".join(lines)


def tool_event_line(name: str, args: dict, result: dict, elapsed_s: float) -> str:
    """One-line summary of a tool dispatch for the agent log chatbot."""
    if "error" in result:
        return f"⚠ **{name}** → `{result['error']}`  ({elapsed_s:.2f}s)"

    if name == "run_fit":
        rchi = result.get("reduced_chi_squared")
        ok   = "✓" if result.get("success") else "✗"
        seed = result.get("random_seed")
        seed_str = f"  seed={seed}" if seed is not None else ""
        chi_str = f"χ²ᵣ={_fmt(rchi)}" if rchi is not None else ""
        return f"🔧 **run_fit** → {ok} {chi_str}{seed_str}  ({elapsed_s:.1f}s)"

    if name in ("get_fit_image", "get_residuals_image"):
        return f"🖼 **{name}**  ({elapsed_s:.1f}s)"

    if name == "open_dataset":
        sid = result.get("session_id", "?")[:8]
        npts = result.get("n_points", "?")
        return f"📂 **open_dataset** → session `{sid}…`  {npts} pts  ({elapsed_s:.2f}s)"

    if name == "save_fit":
        saved = result.get("saved_to", "?")
        return f"💾 **save_fit** → `{saved}`  ({elapsed_s:.2f}s)"

    short = _short_args(args, max_chars=60)
    return f"🔧 **{name}**({short})  ({elapsed_s:.2f}s)"


def token_line(in_tok: int, out_tok: int, cost: float | None) -> str:
    cost_str = f"  ≈ **${cost:.4f}**" if cost is not None else ""
    return f"Tokens: in={in_tok:,}  out={out_tok:,}{cost_str}"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if abs(v) >= 1e4 or (abs(v) < 1e-3 and v != 0):
            return f"{v:.3e}"
        return f"{v:.4g}"
    return str(v)


def _short_args(args: dict, max_chars: int = 60) -> str:
    parts = []
    for k, v in (args or {}).items():
        s = f"{k}={v!r}"
        if len(s) > 30:
            s = s[:27] + "…"
        parts.append(s)
    joined = ", ".join(parts)
    if len(joined) > max_chars:
        joined = joined[:max_chars - 1] + "…"
    return joined
