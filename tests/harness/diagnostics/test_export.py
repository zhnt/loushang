from __future__ import annotations

import json
import os
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

import loushang.harness.diagnostics.export as export_module
from loushang.foundation.artifact_store import (
    ArtifactRetentionPolicy,
    ArtifactSourceRejected,
    ArtifactStore,
)
from loushang.foundation.platform_paths import resolve_platform_paths
from loushang.foundation.runtime_scope import RunLease, resolve_runtime_scope
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


@pytest.mark.parametrize(
    "kwargs",
    (
        {"archive_directory": "../outside"},
        {"archive_directory": "C:/outside"},
        {"debug_directory": "/absolute"},
        {"trace_directory": "state\\traces"},
        {"archive_prefix": "nested/name"},
        {"archive_prefix": "windows:stream"},
        {"archive_root": "unknown"},
    ),
)
def test_diagnostic_bundle_profile_rejects_unsafe_storage_policy(kwargs) -> None:
    with pytest.raises(ValueError):
        DiagnosticBundleProfile(**kwargs)


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


@pytest.mark.parametrize(
    "archive_name",
    (
        "../escape.log",
        "..\\escape.log",
        "C:/escape.log",
        "logs//debug.log",
        "logs/debug\n.log",
    ),
)
def test_export_diagnostics_archive_rejects_unsafe_member_name(
    tmp_path,
    archive_name: str,
) -> None:
    source = tmp_path / "source.log"
    source.write_text("content", encoding="utf-8")

    with pytest.raises(ValueError, match="safe relative path"):
        export_diagnostics_archive(
            output_path=tmp_path / "diagnostics.zip",
            readme="diagnostics",
            manifest={},
            diagnostics=(),
            artifacts=(DiagnosticExportArtifact(archive_name, source),),
        )

    assert not (tmp_path / "diagnostics.zip").exists()
    assert tuple(tmp_path.glob(".*.tmp")) == ()


@pytest.mark.parametrize(
    "artifact",
    (
        DiagnosticExportArtifact("logs/debug.log", content=b"debug"),
        DiagnosticExportArtifact("logs/debug.log", source_path=Path("debug.log")),
    ),
)
def test_diagnostics_artifact_accepts_exactly_one_content_authority(artifact) -> None:
    assert artifact.archive_name == "logs/debug.log"


def test_diagnostics_artifact_rejects_ambiguous_content_authority() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        DiagnosticExportArtifact("logs/debug.log")
    with pytest.raises(ValueError, match="exactly one"):
        DiagnosticExportArtifact(
            "logs/debug.log",
            source_path=Path("debug.log"),
            content=b"debug",
        )


def test_standard_bundle_snapshots_observability_through_artifact_store(
    tmp_path,
) -> None:
    paths = resolve_platform_paths(
        environ={"LOUSHANG_RUNTIME_DIR": str(tmp_path / "runtime")},
        home=tmp_path / "home",
    )
    scope = resolve_runtime_scope(paths=paths, run_id="a" * 32)
    lease = RunLease.acquire(scope)
    store = ArtifactStore(scope, now=lambda: 123.0)
    debug = tmp_path / "state" / "debug" / "latest"
    trace = tmp_path / "state" / "traces" / "latest"
    debug.parent.mkdir(parents=True)
    trace.parent.mkdir(parents=True)
    debug.write_text("Authorization: Bearer private-debug\n", encoding="utf-8")
    trace.write_text('{"token":"private-trace"}\n', encoding="utf-8")

    bundle = export_diagnostics_bundle(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        output=tmp_path / "bundle.zip",
        debug_latest_path=debug,
        trace_latest_path=trace,
        artifact_store=store,
    )

    assert [record.kind for record in store.records] == [
        "debug-log",
        "trace-jsonl",
    ]
    assert all(record.disclosure == "redact" for record in store.records)
    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert [item["kind"] for item in manifest["artifacts"]] == [
            "debug-log",
            "trace-jsonl",
        ]
        assert "private-debug" not in archive.read("debug/latest.log").decode()
        assert "private-trace" not in archive.read("traces/latest.jsonl").decode()

    lease.close()
    assert not scope.run_dir.exists()
    assert bundle.exists()


@pytest.mark.skipif(os.name != "posix", reason="symlink semantics are POSIX-specific")
def test_standard_bundle_verifies_snapshot_identity_before_archive_read(
    tmp_path,
    monkeypatch,
) -> None:
    paths = resolve_platform_paths(
        environ={"LOUSHANG_RUNTIME_DIR": str(tmp_path / "runtime")},
        home=tmp_path / "home",
    )
    scope = resolve_runtime_scope(paths=paths, run_id="e" * 32)
    lease = RunLease.acquire(scope)
    store = ArtifactStore(scope)
    debug = tmp_path / "debug" / "latest"
    debug.parent.mkdir()
    debug.write_text("safe", encoding="utf-8")
    outside = tmp_path / "outside.log"
    outside.write_text("must not export", encoding="utf-8")
    snapshot_file = store.snapshot_file

    def replace_snapshot(*args, **kwargs):
        artifact = snapshot_file(*args, **kwargs)
        artifact.path.unlink()
        artifact.path.symlink_to(outside)
        return artifact

    monkeypatch.setattr(store, "snapshot_file", replace_snapshot)

    with pytest.raises(ArtifactSourceRejected, match="identity changed"):
        export_diagnostics_bundle(
            project_root=tmp_path,
            session_dir=tmp_path / "sessions",
            output=tmp_path / "bundle.zip",
            debug_latest_path=debug,
            trace_latest_path=tmp_path / "missing-trace",
            artifact_store=store,
            platform_paths=paths,
        )

    assert not (tmp_path / "bundle.zip").exists()
    lease.close()


def test_standard_bundle_resolves_windows_style_latest_pointer_through_store(
    tmp_path,
) -> None:
    paths = resolve_platform_paths(
        environ={"LOUSHANG_RUNTIME_DIR": str(tmp_path / "runtime")},
        home=tmp_path / "home",
    )
    scope = resolve_runtime_scope(paths=paths, run_id="b" * 32)
    lease = RunLease.acquire(scope)
    store = ArtifactStore(scope)
    debug_dir = tmp_path / "debug"
    debug_dir.mkdir()
    source = debug_dir / "session.log"
    source.write_text("actual log content\n", encoding="utf-8")
    latest = debug_dir / "latest"
    latest.write_text(str(source.resolve()), encoding="utf-8")

    bundle = export_diagnostics_bundle(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        output=tmp_path / "bundle.zip",
        debug_latest_path=latest,
        trace_latest_path=tmp_path / "missing-trace",
        artifact_store=store,
    )

    with zipfile.ZipFile(bundle) as archive:
        assert archive.read("debug/latest.log") == b"actual log content\n"
        assert "traces/latest.jsonl" not in archive.namelist()
    lease.close()


def test_standard_bundle_omits_windows_style_pointer_outside_state_root(
    tmp_path,
) -> None:
    paths = resolve_platform_paths(
        environ={"LOUSHANG_RUNTIME_DIR": str(tmp_path / "runtime")},
        home=tmp_path / "home",
    )
    scope = resolve_runtime_scope(paths=paths, run_id="d" * 32)
    lease = RunLease.acquire(scope)
    store = ArtifactStore(scope)
    debug_dir = tmp_path / "debug"
    debug_dir.mkdir()
    outside = tmp_path / "outside.log"
    outside.write_text("must not export", encoding="utf-8")
    latest = debug_dir / "latest"
    latest.write_text(str(outside.resolve()), encoding="utf-8")

    bundle = export_diagnostics_bundle(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        output=tmp_path / "bundle.zip",
        debug_latest_path=latest,
        trace_latest_path=tmp_path / "missing-trace",
        artifact_store=store,
    )

    with zipfile.ZipFile(bundle) as archive:
        assert "debug/latest.log" not in archive.namelist()
    assert store.records == ()
    lease.close()


@pytest.mark.skipif(os.name != "posix", reason="symlink semantics are POSIX-specific")
def test_standard_bundle_omits_latest_symlink_outside_authorized_state_root(
    tmp_path,
) -> None:
    paths = resolve_platform_paths(
        environ={"LOUSHANG_RUNTIME_DIR": str(tmp_path / "runtime")},
        home=tmp_path / "home",
    )
    scope = resolve_runtime_scope(paths=paths, run_id="c" * 32)
    lease = RunLease.acquire(scope)
    store = ArtifactStore(scope)
    debug_dir = tmp_path / "debug"
    debug_dir.mkdir()
    outside = tmp_path / "outside.log"
    outside.write_text("must not export", encoding="utf-8")
    latest = debug_dir / "latest"
    latest.symlink_to(outside)

    bundle = export_diagnostics_bundle(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        output=tmp_path / "bundle.zip",
        debug_latest_path=latest,
        trace_latest_path=tmp_path / "missing-trace",
        artifact_store=store,
    )

    with zipfile.ZipFile(bundle) as archive:
        assert "debug/latest.log" not in archive.namelist()
        assert json.loads(archive.read("manifest.json"))["included"][
            "debugLatest"
        ] is False
    assert store.records == ()
    lease.close()


def test_diagnostics_archive_publication_never_replaces_existing_output(
    tmp_path,
) -> None:
    output = tmp_path / "diagnostics.zip"
    output.write_bytes(b"existing")

    with pytest.raises(FileExistsError):
        export_diagnostics_archive(
            output_path=output,
            readme="diagnostics",
            manifest={},
            diagnostics=(),
        )

    assert output.read_bytes() == b"existing"
    assert tuple(tmp_path.glob(".*.tmp")) == ()


def test_diagnostics_archive_rejects_replaced_publication_temporary(
    tmp_path,
    monkeypatch,
) -> None:
    publish = export_module._publish_file_exclusive

    def replace_before_publish(temporary, destination, *, identity):
        temporary.unlink()
        temporary.write_bytes(b"untrusted replacement")
        publish(temporary, destination, identity=identity)

    monkeypatch.setattr(
        export_module,
        "_publish_file_exclusive",
        replace_before_publish,
    )

    with pytest.raises(PermissionError, match="identity changed"):
        export_diagnostics_archive(
            output_path=tmp_path / "diagnostics.zip",
            readme="diagnostics",
            manifest={},
            diagnostics=(),
        )

    assert not (tmp_path / "diagnostics.zip").exists()
    assert [path.read_bytes() for path in tmp_path.glob(".*.tmp")] == [
        b"untrusted replacement"
    ]


@pytest.mark.skipif(os.name != "posix", reason="symlink semantics are POSIX-specific")
def test_diagnostics_archive_publication_does_not_follow_output_symlink(
    tmp_path,
) -> None:
    outside = tmp_path / "outside.zip"
    output = tmp_path / "diagnostics.zip"
    output.symlink_to(outside)

    with pytest.raises(FileExistsError):
        export_diagnostics_archive(
            output_path=output,
            readme="diagnostics",
            manifest={},
            diagnostics=(),
        )

    assert output.is_symlink()
    assert not outside.exists()


def test_default_diagnostics_exports_apply_managed_retention(
    tmp_path,
    monkeypatch,
) -> None:
    platform_home = tmp_path / "home"
    monkeypatch.setenv("LOUSHANG_HOME", str(platform_home))
    directory = platform_home / "state" / "diagnostics"
    directory.mkdir(parents=True)
    for index in range(2):
        path = directory / f"diag-old-{index}.zip"
        path.write_bytes(b"old")
        os.utime(path, (index + 1, index + 1))
    profile = DiagnosticBundleProfile(
        archive_root="platform",
        archive_prefix="diag",
        retention=ArtifactRetentionPolicy(
            max_files=1,
            max_total_bytes=1024 * 1024,
            max_age_seconds=None,
        ),
    )

    exported = export_diagnostics_bundle(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        profile=profile,
        now=lambda: datetime(2026, 8, 27, tzinfo=UTC),
    )

    assert tuple(directory.glob("diag-*.zip")) == (exported,)


def test_standard_bundle_uses_injected_platform_paths(tmp_path, monkeypatch) -> None:
    ambient_home = tmp_path / "ambient-home"
    injected_home = tmp_path / "injected-home"
    monkeypatch.setenv("LOUSHANG_HOME", str(ambient_home))
    paths = resolve_platform_paths(
        environ={"LOUSHANG_HOME": str(injected_home)},
        home=tmp_path / "ignored-user-home",
    )

    exported = export_diagnostics_bundle(
        project_root=tmp_path,
        session_dir=tmp_path / "sessions",
        platform_paths=paths,
        now=lambda: datetime(2026, 8, 27, tzinfo=UTC),
    )

    assert exported.parent == injected_home / "state" / "diagnostics"
    assert not ambient_home.exists()
