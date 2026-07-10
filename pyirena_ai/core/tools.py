"""Bridge between the LLM agent and pyirena's control surface.

This module is the single integration point with pyirena. The agent loop
never imports `pyirena` directly — it only sees the tool names + schemas
exposed here.

The strategy is to lift `pyirena.api.control` unchanged: every function in
that module becomes an LLM-callable tool, and `TOOL_SCHEMAS` (already shaped
for Anthropic's tool-use protocol) is re-exported as-is.

`dispatch` never raises: bad arguments from the LLM (`TypeError`) and any
unexpected exception inside a control function are both converted into the
contract-shaped error dict `{"error": ..., "code": ..., "suggestion": ...}`
so the agent can see the failure and recover instead of aborting the run.
The control functions themselves also do not raise by contract.

## Tool traits

`TOOL_GROUPS` classifies every known control tool as "shared", "unified",
or "sizes" so a run can send the model only the tools relevant to the
selected fit model (`schemas_for_groups`). Smaller local LLMs degrade
noticeably when offered too many tools, so trimming the tool list per fit
model matters at the beamline. Tools pyirena adds in the future that are
not yet classified here are treated as shared (always included) — new
functionality never silently disappears.

`MUTATING_TOOLS` lists tools that change model/fit state (the GUI refreshes
its parameter panel after these). `HARVEST_RULES` declares which result
fields the agent should copy onto the `RunSession` after a given tool runs,
replacing hardcoded per-tool logic in the agent loop.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable, Iterable
from typing import Any

import pyirena
from pyirena.api import control as _ctrl
from pyirena.api.control.schemas import TOOL_SCHEMA_BY_NAME, TOOL_SCHEMAS

PYIRENA_VERSION: str = pyirena.__version__
CONTROL_API_VERSION: str = _ctrl.__version__

TOOL_FUNCS: dict[str, Callable[..., dict]] = {
    name: getattr(_ctrl, name) for name in _ctrl.__all__
    if callable(getattr(_ctrl, name, None))
}

__all__ = [
    "TOOL_SCHEMAS",
    "TOOL_SCHEMA_BY_NAME",
    "TOOL_FUNCS",
    "TOOL_GROUPS",
    "MUTATING_TOOLS",
    "HARVEST_RULES",
    "PYIRENA_VERSION",
    "CONTROL_API_VERSION",
    "dispatch",
    "schemas_for_groups",
    "is_image_result",
    "extract_image_base64",
]


# ---------------------------------------------------------------------------
# Tool traits
# ---------------------------------------------------------------------------

# Group per tool. "shared" tools apply to every fit model; "unified" /
# "sizes" tools only make sense for that model. Unclassified tools
# (added by future pyirena versions) are included in every run.
TOOL_GROUPS: dict[str, str] = {
    # ---- shared: session, Q-range, generic data analysis -----------------
    "open_dataset":                 "shared",
    "list_open_sessions":           "shared",
    "close_session":                "shared",
    "get_session_summary":          "shared",
    "get_data_q_range":             "shared",
    "get_fit_q_range":              "shared",
    "set_fit_q_range":              "shared",
    "reset_fit_q_range":            "shared",
    "fit_local_guinier":            "shared",
    "fit_local_power_law":          "shared",
    "detect_features":              "shared",
    # ---- Unified Fit ------------------------------------------------------
    "list_available_models":        "unified",
    "select_model":                 "unified",
    "get_model_parameters":         "unified",
    "get_model_description":        "unified",
    "set_parameter_value":          "unified",
    "set_parameter_bounds":         "unified",
    "fix_parameter":                "unified",
    "free_parameter":               "unified",
    "fix_all_except":               "unified",
    "reset_parameters_to_defaults": "unified",
    "add_unified_level":            "unified",
    "remove_unified_level":         "unified",
    "get_level_options":            "unified",
    "set_level_option":             "unified",
    "check_level_feasibility":      "unified",
    "run_fit":                      "unified",
    "get_chi_squared":              "unified",
    "get_residuals":                "unified",
    "get_fit_quality":              "unified",
    "get_fit_image":                "unified",
    "get_residuals_image":          "unified",
    "get_parameter_uncertainties":  "unified",
    "save_fit":                     "unified",
    "export_fit_report":            "unified",
    # ---- Size Distribution -------------------------------------------------
    "select_sizes_model":           "sizes",
    "get_sizes_config":             "sizes",
    "suggest_sizes_setup":          "sizes",
    "set_size_grid":                "sizes",
    "set_shape":                    "sizes",
    "set_method":                   "sizes",
    "set_error_handling":           "sizes",
    "set_background":               "sizes",
    "fit_power_law_background":     "sizes",
    "fit_flat_background":          "sizes",
    "get_background_preview_image": "sizes",
    "run_sizes_fit":                "sizes",
    "get_sizes_distribution":       "sizes",
    "get_sizes_results":            "sizes",
    "get_sizes_fit_image":          "sizes",
    "save_sizes_fit":               "sizes",
}

# Tools that mutate model/fit state — the GUI re-reads and re-renders the
# parameter panel after these.
MUTATING_TOOLS: frozenset[str] = frozenset({
    # Unified Fit
    "select_model", "set_parameter_value", "set_parameter_bounds",
    "fix_parameter", "free_parameter", "fix_all_except",
    "reset_parameters_to_defaults", "add_unified_level", "remove_unified_level",
    "set_level_option", "run_fit",
    # Size Distribution
    "select_sizes_model", "set_size_grid", "set_shape", "set_method",
    "set_error_handling", "set_background", "fit_power_law_background",
    "fit_flat_background", "run_sizes_fit",
})

# After a successful tool call, copy selected result fields onto the
# RunSession:  tool name → [(result_key, session_attribute, cast), ...]
HARVEST_RULES: dict[str, list[tuple[str, str, Callable[[Any], Any]]]] = {
    "open_dataset":    [("session_id",          "pyirena_session_id", str)],
    "save_fit":        [("saved_to",            "saved_to",           str)],
    "save_sizes_fit":  [("file_path",           "saved_to",           str)],
    "run_fit":         [("reduced_chi_squared", "final_chi_squared",  float),
                        ("random_seed",         "last_random_seed",   int)],
    "get_chi_squared": [("reduced_chi_squared", "final_chi_squared",  float)],
    "run_sizes_fit":   [("chi_squared",         "final_chi_squared",  float),
                        ("random_seed",         "last_random_seed",   int)],
}


def schemas_for_groups(groups: Iterable[str] | None) -> list[dict]:
    """Return the tool schemas whose group is in `groups`.

    Unclassified tools (not in `TOOL_GROUPS`) are always included so that
    new pyirena control functions remain reachable even before this table
    is updated. Pass None to get the full, unfiltered schema list.
    """
    if groups is None:
        return list(TOOL_SCHEMAS)
    wanted = set(groups)
    return [
        t for t in TOOL_SCHEMAS
        if TOOL_GROUPS.get(t["name"], "shared") in wanted or t["name"] not in TOOL_GROUPS
    ]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch(name: str, args: dict[str, Any] | None) -> dict:
    """Invoke a control-surface function by name. Never raises.

    Returns the function's dict result on success, or a contract-shaped
    error dict when the name is unknown, arguments fail to bind, or the
    function raises unexpectedly. Returning (rather than raising) lets the
    LLM see the failure and recover — retry, adjust arguments, or choose a
    different tool — instead of aborting a long run.
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
    except Exception as e:  # noqa: BLE001 — deliberate catch-all, see docstring
        return {
            "error": f"{type(e).__name__} inside '{name}': {e}",
            "code": "TOOL_EXCEPTION",
            "suggestion": (
                "The tool failed unexpectedly. Check that the session is "
                "still open and the arguments are physically sensible; "
                "you may retry or try a different approach."
            ),
            "traceback_tail": traceback.format_exc(limit=5),
        }


def is_image_result(result: dict) -> bool:
    """True when the tool returned a base64 PNG (get_fit_image / get_residuals_image)."""
    return isinstance(result, dict) and isinstance(result.get("image_base64"), str)


def extract_image_base64(result: dict) -> str:
    """Pull the base64 PNG string out of a tool result, or "" if absent."""
    if not is_image_result(result):
        return ""
    return result["image_base64"]
