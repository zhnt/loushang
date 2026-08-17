from __future__ import annotations

import json
import zipfile

import pytest

from loushang.harness.diagnostics.export import (
    DiagnosticBundleProfile,
    DiagnosticExportArtifact,
    export_diagnostics_archive,
    export_diagnostics_bundle,
)


def test_standard_bundle_accepts_product_archive_profile(tmp_path) -> None:
    project_root = tmp_path / "design"
    project_root.mkdir()
    profile = DiagnosticBundleProfile(
        archive_directory=".product/diagnostics",
        archive_prefix="design-diag",
        readme="Design diagnostics\n",
    )

    output = export_diagnostics_bundle(
        project_root=project_root,
        session_dir=project_root / ".product" / "sessions",
        profile=profile,
    )

    assert output.parent == project_root / ".product" / "diagnostics"
    assert output.name.startswith("design-diag-")


def test_export_diagnostics_archive_redacts_text_and_structured_values(
    tmp_path,
) -> None:
    artifact = tmp_path / "debug.log"
    artifact.write_text("Authorization: Bearer private-token\n", encoding="utf-8")

    archive_path = export_diagnostics_archive(
        output_path=tmp_path / "diagnostics.zip",
        readme="diagnostics",
        manifest={"authorization": "Bearer private-manifest", "nested": {"ok": True}},
        diagnostics=[
            {"token": "private-diagnostic", "message": "Bearer private-message"}
        ],
        artifacts=(DiagnosticExportArtifact("logs/debug.log", artifact),),
    )

    with zipfile.ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        diagnostics = json.loads(archive.read("diagnostics.json"))
        text = archive.read("logs/debug.log").decode("utf-8")

    assert manifest["authorization"] == "[REDACTED]"
    assert diagnostics[0]["token"] == "[REDACTED]"
    assert "private-message" not in diagnostics[0]["message"]
    assert "private-token" not in text


def test_export_diagnostics_archive_rejects_unsafe_member_name(tmp_path) -> None:
    source = tmp_path / "source.log"
    source.write_text("content", encoding="utf-8")

    with pytest.raises(ValueError, match="safe relative path"):
        export_diagnostics_archive(
            output_path=tmp_path / "diagnostics.zip",
            readme="diagnostics",
            manifest={},
            diagnostics=(),
            artifacts=(DiagnosticExportArtifact("../escape.log", source),),
        )
