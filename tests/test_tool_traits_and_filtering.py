"""Tests for tool traits: grouping/filtering, dispatch hardening, harvest rules.

All offline — no LLM, no data file needed (pyirena must be importable).
"""

from __future__ import annotations

from pyirena_ai.core.tools import (
    HARVEST_RULES,
    MUTATING_TOOLS,
    TOOL_FUNCS,
    TOOL_GROUPS,
    TOOL_SCHEMAS,
    dispatch,
    schemas_for_groups,
)

# ---------------------------------------------------------------------------
# Grouping / filtering
# ---------------------------------------------------------------------------

def test_every_control_tool_is_classified():
    """New pyirena control functions should get a TOOL_GROUPS entry.

    (Unclassified tools still work — they are exposed to every fit model —
    but classifying keeps the per-model tool count low for local LLMs.)
    """
    unclassified = set(TOOL_FUNCS) - set(TOOL_GROUPS)
    assert not unclassified, (
        f"Tools missing from TOOL_GROUPS (add them so per-model filtering "
        f"stays effective): {sorted(unclassified)}"
    )


def test_groups_reference_real_tools():
    stale = set(TOOL_GROUPS) - set(TOOL_FUNCS)
    assert not stale, f"TOOL_GROUPS entries with no dispatch function: {sorted(stale)}"


def test_filtering_reduces_tool_count():
    all_schemas = schemas_for_groups(None)
    unified = schemas_for_groups(("shared", "unified"))
    sizes = schemas_for_groups(("shared", "sizes"))
    assert len(unified) < len(all_schemas)
    assert len(sizes) < len(all_schemas)
    # Union of the two models must cover the full classified surface.
    assert {t["name"] for t in unified} | {t["name"] for t in sizes} == {
        t["name"] for t in all_schemas
    }


def test_unified_run_never_sees_sizes_tools_and_vice_versa():
    unified_names = {t["name"] for t in schemas_for_groups(("shared", "unified"))}
    sizes_names = {t["name"] for t in schemas_for_groups(("shared", "sizes"))}
    assert "run_sizes_fit" not in unified_names
    assert "select_sizes_model" not in unified_names
    assert "run_fit" not in sizes_names
    assert "add_unified_level" not in sizes_names
    # Shared tools appear in both.
    for name in ("open_dataset", "set_fit_q_range", "close_session"):
        assert name in unified_names and name in sizes_names


def test_unknown_tools_are_always_included():
    """A schema whose name is not in TOOL_GROUPS must never be filtered out."""
    fake = {"name": "brand_new_tool", "description": "", "input_schema": {}}
    try:
        TOOL_SCHEMAS.append(fake)
        names = {t["name"] for t in schemas_for_groups(("shared", "unified"))}
        assert "brand_new_tool" in names
    finally:
        TOOL_SCHEMAS.remove(fake)


def test_mutating_tools_are_real():
    stale = MUTATING_TOOLS - set(TOOL_FUNCS)
    assert not stale, f"MUTATING_TOOLS entries with no dispatch function: {sorted(stale)}"


def test_harvest_rules_reference_real_tools():
    stale = set(HARVEST_RULES) - set(TOOL_FUNCS)
    assert not stale, f"HARVEST_RULES entries with no dispatch function: {sorted(stale)}"


# ---------------------------------------------------------------------------
# Dispatch hardening
# ---------------------------------------------------------------------------

def test_dispatch_never_raises_on_internal_error(monkeypatch):
    """Unexpected exceptions inside a control function become error dicts."""
    from pyirena_ai.core import tools as tools_mod

    def boom(**kwargs):
        raise RuntimeError("simulated internal failure")

    monkeypatch.setitem(tools_mod.TOOL_FUNCS, "open_dataset", boom)

    r = dispatch("open_dataset", {"file_path": "/x.h5"})
    assert isinstance(r, dict)
    assert r.get("code") == "TOOL_EXCEPTION"
    assert "simulated internal failure" in r.get("error", "")
    assert "traceback_tail" in r
