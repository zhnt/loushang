from __future__ import annotations

from loushang.coding.control import ControlConfig, SettingsManager
from loushang.coding.resource_runtime import (
    CodingPackageMaterializer as PackageMaterializer,
)
from loushang.harness.diagnostics import DiagnosticsService
from loushang.harness.resources.packages.materializer import (
    PackageMaterializationRecord,
    PackageProgressEvent,
)
from loushang.harness.resources.packages.source import PackageSourceConfig
from loushang.harness.resources.packages.source_resolver import PackageSourceResolver


def test_package_source_resolver_installs_missing_configured_sources_and_emits_progress(tmp_path) -> None:
    source = "https://packages.example.invalid/review-pack.git"
    events: list[PackageProgressEvent] = []

    def backend(record: PackageMaterializationRecord) -> PackageMaterializationRecord:
        record.target_path.mkdir(parents=True)
        return record.with_lifecycle("installed")

    settings = SettingsManager(ControlConfig(package_sources=(PackageSourceConfig(source=source),)))
    materializer = PackageMaterializer(
        install_root=tmp_path / "packages",
        backend=backend,
        progress_callback=events.append,
    )
    resolver = PackageSourceResolver(settings_manager=settings, materializer=materializer)

    result = resolver.resolve_configured_sources_sync(missing_source_action="install")

    assert [record.lifecycle for record in result.records] == ["installed"]
    assert materializer.get_record(source).lifecycle == "installed"  # type: ignore[union-attr]
    assert [(event.type, event.action, event.source) for event in events] == [
        ("start", "install", source),
        ("complete", "install", source),
    ]


def test_package_source_resolver_skips_missing_sources_and_records_diagnostics(tmp_path) -> None:
    source = "pypi:acme-review-pack==1.2.3"
    settings = SettingsManager(ControlConfig(package_sources=(PackageSourceConfig(source=source),)))
    materializer = PackageMaterializer(install_root=tmp_path / "packages")
    diagnostics = DiagnosticsService()
    resolver = PackageSourceResolver(
        settings_manager=settings,
        materializer=materializer,
        diagnostics_service=diagnostics,
        session_id="session-1",
    )

    result = resolver.resolve_configured_sources_sync(missing_source_action="skip", phase="startup")

    assert result.records == ()
    assert result.skipped_sources == (source,)
    assert materializer.get_record(source) is None
    records = diagnostics.get_diagnostics(phase="startup", source="package")
    assert [record.code for record in records] == ["package_source_missing_skipped"]
    assert records[0].details["package_source"] == source


def test_package_source_resolver_errors_missing_sources_and_records_diagnostics(tmp_path) -> None:
    source = "https://packages.example.invalid/review-pack.git"
    settings = SettingsManager(ControlConfig(package_sources=(PackageSourceConfig(source=source),)))
    materializer = PackageMaterializer(install_root=tmp_path / "packages")
    diagnostics = DiagnosticsService()
    resolver = PackageSourceResolver(
        settings_manager=settings,
        materializer=materializer,
        diagnostics_service=diagnostics,
        session_id="session-1",
    )

    result = resolver.resolve_configured_sources_sync(missing_source_action="error", phase="startup")

    assert result.records == ()
    assert result.failed_sources == (source,)
    records = diagnostics.get_diagnostics(phase="startup", source="package")
    assert [record.code for record in records] == ["package_source_missing"]
    assert records[0].details["package_source"] == source
