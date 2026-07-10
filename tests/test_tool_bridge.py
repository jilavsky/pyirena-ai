"""Smoke tests for the pyirena.api.control tool bridge.

These exercise the dispatch table and a couple of representative tools.
They require pyirena to be importable; the `test_h5_path` fixture skips
if no NXcanSAS file is reachable.
"""

from __future__ import annotations

from pyirena_ai.core.tools import (
    PYIRENA_VERSION,
    TOOL_FUNCS,
    TOOL_SCHEMA_BY_NAME,
    TOOL_SCHEMAS,
    dispatch,
)


def test_pyirena_version_is_string():
    assert isinstance(PYIRENA_VERSION, str) and PYIRENA_VERSION


def test_schemas_and_funcs_align():
    """Every schema should have a matching dispatch function and vice versa."""
    schema_names = {t["name"] for t in TOOL_SCHEMAS}
    func_names = set(TOOL_FUNCS)
    # Schemas should be a subset of dispatch functions (control surface).
    # If pyirena adds a new function without a schema we want a test to
    # nudge us to add the schema.
    missing_schema = func_names - schema_names
    missing_func = schema_names - func_names
    assert not missing_func, f"Schemas without dispatch: {missing_func}"
    assert not missing_schema, f"Functions without schema: {missing_schema}"


def test_schema_index_consistent():
    assert set(TOOL_SCHEMA_BY_NAME) == {t["name"] for t in TOOL_SCHEMAS}


def test_dispatch_unknown_tool_returns_error():
    r = dispatch("definitely_not_a_tool", {})
    assert isinstance(r, dict)
    assert r.get("code") == "UNKNOWN_TOOL"


def test_dispatch_list_available_models():
    r = dispatch("list_available_models", {})
    assert isinstance(r, dict)
    # Real call: should not error.
    assert "error" not in r
    assert "models" in r
    assert "unified_fit" in r["models"]


def test_dispatch_bad_arguments_returns_error():
    r = dispatch("open_dataset", {"not_a_real_arg": 1})
    assert isinstance(r, dict)
    assert r.get("code") == "BAD_ARGUMENTS"


def test_open_dataset_round_trip(test_h5_path):
    """End-to-end: open, list parameters, close. No fit run (keeps test fast)."""
    r_open = dispatch("open_dataset", {"file_path": str(test_h5_path)})
    assert "error" not in r_open, r_open
    session_id = r_open["session_id"]
    assert session_id

    r_sel = dispatch("select_model", {
        "session_id": session_id,
        "model_name": "unified_fit",
        "nlevels": 1,
    })
    assert "error" not in r_sel, r_sel

    r_params = dispatch("get_model_parameters", {"session_id": session_id})
    assert "error" not in r_params, r_params
    assert "parameters" in r_params

    r_close = dispatch("close_session", {"session_id": session_id})
    assert "error" not in r_close, r_close
