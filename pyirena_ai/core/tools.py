"""Bridge between the LLM agent and pyirena's control surface.

This module is the single integration point with pyirena. The agent loop
never imports `pyirena` directly — it only sees the tool names + schemas
exposed here.

The strategy is to lift `pyirena.api.control` unchanged: every function in
that module becomes an LLM-callable tool, and `TOOL_SCHEMAS` (already shaped
for Anthropic's tool-use protocol) is re-exported as-is.

If a function call raises `TypeError` (bad arguments from the LLM) we
catch it and return the contract error dict; every other exception is
allowed to propagate so the agent loop can record it in the audit trail.
The control functions themselves do not raise — they return `{"error":
..., "code": ..., "suggestion": ...}` dicts.
"""

from __future__ import annotations

from typing import Any, Callable

import pyirena
from pyirena.api import control as _ctrl
from pyirena.api.control.schemas import TOOL_SCHEMAS, TOOL_SCHEMA_BY_NAME

PYIRENA_VERSION: str = pyirena.__version__

TOOL_FUNCS: dict[str, Callable[..., dict]] = {
    name: getattr(_ctrl, name) for name in _ctrl.__all__
}

__all__ = [
    "TOOL_SCHEMAS",
    "TOOL_SCHEMA_BY_NAME",
    "TOOL_FUNCS",
    "PYIRENA_VERSION",
    "dispatch",
    "is_image_result",
    "extract_image_base64",
]


def dispatch(name: str, args: dict[str, Any] | None) -> dict:
    """Invoke a control-surface function by name.

    Returns the function's dict result on success. Returns a contract-shaped
    error dict if the name is unknown or arguments fail to bind.
    """
    fn = TOOL_FUNCS.get(name)
    if fn is None:
        return {
            "error": f"Unknown tool '{name}'",
            "code": "UNKNOWN_TOOL",
            "suggestion": (
                "Available tools: " + ", ".join(sorted(TOOL_FUNCS))
            ),
        }
    try:
        return fn(**(args or {}))
    except TypeError as e:
        return {
            "error": f"Bad arguments for '{name}': {e}",
            "code": "BAD_ARGUMENTS",
            "suggestion": "Check the tool's input_schema for required fields and types.",
        }


def is_image_result(result: dict) -> bool:
    """True when the tool returned a base64 PNG (get_fit_image / get_residuals_image)."""
    return isinstance(result, dict) and isinstance(result.get("image_base64"), str)


def extract_image_base64(result: dict) -> str:
    """Pull the base64 PNG string out of a tool result, or "" if absent."""
    if not is_image_result(result):
        return ""
    return result["image_base64"]
