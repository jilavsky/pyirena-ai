"""Audit-trail format tests: round-trip, schema version, image redaction."""

from __future__ import annotations

import json

from pyirena_ai.core.audit import AUDIT_SCHEMA, default_audit_path, write_audit_json
from pyirena_ai.core.session import RunSession


def test_default_audit_path_uses_subfolder(tmp_path):
    p = tmp_path / "scan_007.h5"
    out = default_audit_path(p)
    # Audit goes into <data_dir>/pyirena-ai/<filename>.audit.json
    assert out.parent.name == "pyirena-ai"
    assert out.parent.parent == tmp_path
    assert out.name == "scan_007.h5.audit.json"


def test_round_trip_minimal(tmp_path):
    s = RunSession(
        input_file=str(tmp_path / "data.h5"),
        provider="anthropic",
        model="claude-opus-4-7",
        strategy="unified_fit_default",
        system_prompt="(test)",
    )
    s.add_assistant_text("Hi.")
    s.add_tool_use(
        tool="open_dataset",
        args={"file_path": str(tmp_path / "data.h5")},
        result={"session_id": "abc123", "n_points": 200},
        elapsed_s=0.01,
    )
    s.add_tool_use(
        tool="run_fit",
        args={"session_id": "abc123"},
        result={"success": True, "chi_squared": 1.83, "reduced_chi_squared": 1.21},
        elapsed_s=0.05,
    )
    s.final_chi_squared = 1.21

    out_path = write_audit_json(s, tmp_path / "data.h5.audit.json")
    assert out_path.exists()

    loaded = json.loads(out_path.read_text())

    assert loaded["schema"] == AUDIT_SCHEMA
    assert loaded["provider"] == "anthropic"
    assert loaded["model"] == "claude-opus-4-7"
    assert loaded["final_chi_squared"] == 1.21
    assert len(loaded["turns"]) == 3
    assert loaded["turns"][1]["tool"] == "open_dataset"
    assert loaded["turns"][2]["result"]["reduced_chi_squared"] == 1.21
    assert "tokens" in loaded


def test_image_result_redacted(tmp_path):
    """Base64 PNG payloads are replaced by a placeholder in the audit file."""
    s = RunSession(input_file=str(tmp_path / "x.h5"))
    fake_png = "A" * 12345
    s.add_tool_use(
        tool="get_fit_image",
        args={"session_id": "sid"},
        result={"image_base64": fake_png, "format": "png", "width": 1024, "height": 768},
        elapsed_s=0.02,
    )

    out = write_audit_json(s, tmp_path / "x.h5.audit.json")
    loaded = json.loads(out.read_text())

    redacted = loaded["turns"][0]["result"]["image_base64"]
    assert "<redacted" in redacted
    # The actual base64 string is not present anywhere in the file.
    assert fake_png not in out.read_text()
