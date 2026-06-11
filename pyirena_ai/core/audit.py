"""Write the run audit trail into a per-folder subfolder.

Schema: ``pyirena-ai/audit/v1``. The format is stamped from day 1 so we
can evolve it without guesswork later.

Audit files go to ``<data_dir>/pyirena-ai/<filename>.audit.json`` so the
data folder stays clean while audits remain easy to find alongside the
fitted HDF5.

The result dict for an image-returning tool (`get_fit_image`,
`get_residuals_image`) embeds a ~50–100 KB base64 PNG, which would bloat
the audit JSON unnecessarily. We replace it with a small placeholder dict
that records the dimensions only.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pyirena_ai import __version__ as PYIRENA_AI_VERSION
from pyirena_ai.core.session import RunSession
from pyirena_ai.core.tools import CONTROL_API_VERSION, PYIRENA_VERSION, is_image_result

AUDIT_SCHEMA = "pyirena-ai/audit/v1"


AUDIT_SUBDIR = "pyirena-ai"


def default_audit_path(input_file: str | Path) -> Path:
    """Return `<data_dir>/pyirena-ai/<filename>.audit.json`.

    Using a subfolder keeps the data directory clean while keeping
    audit files findable right next to the fitted HDF5.
    """
    p = Path(input_file).resolve()
    audit_name = p.name + ".audit.json"
    return p.parent / AUDIT_SUBDIR / audit_name


def write_audit_json(session: RunSession, out_path: str | Path) -> Path:
    """Serialize `session` to a JSON file. Returns the path written."""
    if not session.finished_at:
        session.finished_at = (
            datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        )

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(_to_dict(session), indent=2), encoding="utf-8")
    return out


def _to_dict(session: RunSession) -> dict[str, Any]:
    turns: list[dict[str, Any]] = []
    for t in session.turns:
        d = asdict(t)
        if t.type == "tool_use" and is_image_result(t.result):
            d["result"] = _redact_image_result(t.result)
        if t.type == "tool_use" and t.tool == "run_fit":
            d["random_seed"] = t.result.get("random_seed")
        turns.append(d)

    return {
        "schema":               AUDIT_SCHEMA,
        "pyirena_ai":           PYIRENA_AI_VERSION,
        "pyirena":              PYIRENA_VERSION,
        "control_api_version":  CONTROL_API_VERSION,
        "started_at":           session.started_at,
        "finished_at":      session.finished_at,
        "input_file":       session.input_file,
        "provider":         session.provider,
        "model":            session.model,
        "base_url":         session.base_url,
        "strategy":         session.strategy,
        "system_prompt":    session.system_prompt,
        "turns":            turns,
        "final_chi_squared": session.final_chi_squared,
        "saved_to":         session.saved_to,
        "tokens": {
            "input":             session.input_tokens,
            "output":            session.output_tokens,
            "cost_usd_estimate": session.cost_usd_estimate,
        },
    }


def _redact_image_result(result: dict) -> dict:
    """Drop the base64 PNG payload but keep its metadata."""
    redacted = {k: v for k, v in result.items() if k != "image_base64"}
    redacted["image_base64"] = f"<redacted: {len(result.get('image_base64', ''))} chars>"
    return redacted
