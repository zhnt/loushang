from __future__ import annotations

import json
import zipfile
from types import SimpleNamespace

from loushang.harness.diagnostics import DiagnosticRecord
from loushang.harness.diagnostics.export import export_diagnostics_bundle


def test_export_diagnostics_bundle_collects_latest_artifacts(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    session_dir = project_root / ".loushang" / "sessions"
    session_dir.mkdir(parents=True)
    (session_dir / "latest.jsonl").write_text(
        '{"type":"user","text":"hello"}\n', encoding="utf-8"
    )

    debug_latest = tmp_path / "debug" / "latest"
    debug_latest.parent.mkdir()
    debug_latest.write_text("Authorization: Bearer secret-token\n", encoding="utf-8")
    trace_latest = tmp_path / "traces" / "latest"
    trace_latest.parent.mkdir()
    trace_latest.write_text('{"api_key":"secret-key","event":"x"}\n', encoding="utf-8")

    diagnostics_service = SimpleNamespace(
        get_last_diagnostics=lambda limit=50: [
            DiagnosticRecord(
                type="error",
                code="tool_failed",
                message="tool failed",
                phase="runtime",
                source="tool",
                timestamp="2026-05-14T00:00:00Z",
                details={"path": "tmp/bmi.html"},
            )
        ]
    )

    bundle = export_diagnostics_bundle(
        project_root=project_root,
        session_dir=session_dir,
        output=tmp_path / "bundle.zip",
        diagnostics_service=diagnostics_service,
        debug_latest_path=debug_latest,
        trace_latest_path=trace_latest,
    )

    with zipfile.ZipFile(bundle) as archive:
        names = set(archive.namelist())
        assert {
            "README.txt",
            "manifest.json",
            "debug/latest.log",
            "traces/latest.jsonl",
            "sessions/latest.jsonl",
            "diagnostics.json",
        } <= names
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schemaVersion"] == 1
        assert manifest["cwd"] == str(project_root)
        assert manifest["included"]["debugLatest"] is True
        assert manifest["included"]["traceLatest"] is True
        assert manifest["included"]["sessionLatest"] is True
        assert json.loads(archive.read("diagnostics.json"))[0]["code"] == "tool_failed"
        assert "secret-token" not in archive.read("debug/latest.log").decode("utf-8")
        assert "secret-key" not in archive.read("traces/latest.jsonl").decode("utf-8")


def test_export_diagnostics_bundle_uses_default_project_output(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    bundle = export_diagnostics_bundle(
        project_root=project_root,
        session_dir=project_root / ".loushang" / "sessions",
    )

    assert bundle.parent == project_root / ".loushang" / "diagnostics"
    assert bundle.name.startswith("loushang-diag-")
    assert bundle.suffix == ".zip"


def test_export_diagnostics_bundle_does_not_fall_back_to_record_repr(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    class UnserializableDiagnostic:
        def __repr__(self) -> str:
            return "credential=private-value"

    diagnostics_service = SimpleNamespace(
        get_last_diagnostics=lambda limit=50: [UnserializableDiagnostic()]
    )
    bundle = export_diagnostics_bundle(
        project_root=project_root,
        session_dir=project_root / ".loushang" / "sessions",
        output=tmp_path / "bundle.zip",
        diagnostics_service=diagnostics_service,
    )

    with zipfile.ZipFile(bundle) as archive:
        assert json.loads(archive.read("diagnostics.json")) == []
        assert "private-value" not in archive.read("diagnostics.json").decode("utf-8")
