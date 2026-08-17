from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.diagnostics.types import DiagnosticLevel, DiagnosticPhase
from loushang.harness.resources.packages.materializer import (
    PackageMaterializationRecord,
    PackageMaterializer,
    package_offline_enabled,
)
from loushang.harness.resources.packages.source import (
    PackageSourceConfig,
    PackageSourceIdentity,
    is_remote_package_source,
    package_source_from_raw,
    package_source_match_key,
)

MissingSourceAction = Literal["install", "skip", "error"]
MissingSourceResolver = Callable[[str], MissingSourceAction]
PackageSourceScope = Literal["user", "project", "session", "merged"]


@dataclass(frozen=True)
class PackageResolveResult:
    """Result of resolving configured remote package sources."""

    records: tuple[PackageMaterializationRecord, ...] = ()
    skipped_sources: tuple[str, ...] = ()
    failed_sources: tuple[str, ...] = ()


@dataclass
class PackageSourceResolver:
    """Materialize configured package sources through product-supplied settings.

    The settings object is intentionally a structural port. Products choose how
    settings are persisted; the resolver only reads source declarations and
    coordinates their existing materializer and diagnostics services.
    """

    settings_manager: object
    materializer: PackageMaterializer
    diagnostics_service: DiagnosticsService | None = None
    session_id: str | None = None

    def resolve_configured_sources_sync(
        self,
        *,
        missing_source_action: MissingSourceAction | MissingSourceResolver = "install",
        phase: DiagnosticPhase = "runtime",
    ) -> PackageResolveResult:
        records: list[PackageMaterializationRecord] = []
        skipped: list[str] = []
        failed: list[str] = []
        for package_source in configured_package_sources(self.settings_manager):
            source = package_source.source
            if not is_remote_package_source(source):
                continue
            record = self.materializer.get_record(source)
            if record is not None and record.lifecycle == "installed":
                records.append(record)
                continue
            action = (
                missing_source_action(source)
                if callable(missing_source_action)
                else missing_source_action
            )
            if package_offline_enabled() and action == "install":
                action = "skip"
            if action == "skip":
                skipped.append(source)
                self._record_missing_source_skip(source, phase=phase)
                continue
            if action == "error":
                failed.append(source)
                self._record_missing_source_error(source, phase=phase)
                continue
            record = self.materializer.materialize_remote_source_sync(source)
            if record.lifecycle == "failed":
                failed.append(source)
                self._record_materialization_failure(record, phase=phase)
            else:
                records.append(record)
        return PackageResolveResult(
            records=tuple(records),
            skipped_sources=tuple(skipped),
            failed_sources=tuple(failed),
        )

    def prepare_configured_remote_records(
        self,
    ) -> tuple[PackageMaterializationRecord, ...]:
        records: list[PackageMaterializationRecord] = []
        for package_source in configured_package_sources(self.settings_manager):
            source = package_source.source
            if not is_remote_package_source(source):
                continue
            record = self.materializer.get_record(source)
            if record is None:
                record = self.materializer.prepare_remote_source(source)
            records.append(record)
        return tuple(records)

    def _record_missing_source_skip(
        self, source: str, *, phase: DiagnosticPhase
    ) -> None:
        self._record_missing_source(
            "package_source_missing_skipped",
            f"Package source was not installed: {source}",
            source,
            phase=phase,
            level="warning",
        )

    def _record_missing_source_error(
        self, source: str, *, phase: DiagnosticPhase
    ) -> None:
        self._record_missing_source(
            "package_source_missing",
            f"Missing package source: {source}",
            source,
            phase=phase,
            level="error",
        )

    def _record_materialization_failure(
        self, record: PackageMaterializationRecord, *, phase: DiagnosticPhase
    ) -> None:
        if self.diagnostics_service is None:
            return
        self.diagnostics_service.capture_failure(
            code="package_materialization_failed",
            error=record.error_message
            or f"Package materialization failed: {record.source}",
            phase=phase,
            source="package",
            level="warning",
            session_id=self.session_id,
            details={
                "package_source": record.source,
                "package_name": record.name,
                "security": record.security,
                "source_type": record.source_type,
            },
        )

    def _record_missing_source(
        self,
        code: str,
        message: str,
        source: str,
        *,
        phase: DiagnosticPhase,
        level: DiagnosticLevel,
    ) -> None:
        if self.diagnostics_service is None:
            return
        identity = PackageSourceIdentity.parse(source)
        self.diagnostics_service.capture_failure(
            code=code,
            error=message,
            phase=phase,
            source="package",
            level=level,
            session_id=self.session_id,
            details={
                "package_source": source,
                "package_name": identity.path or "",
                "source_type": identity.source_type,
            },
        )


def configured_package_sources(
    settings_manager: object,
) -> tuple[PackageSourceConfig, ...]:
    """Return deduplicated sources with relative paths resolved by scope."""

    seen: set[str] = set()
    values: list[PackageSourceConfig] = []
    for getter_name, scope in _SETTINGS_SCOPES:
        getter = getattr(settings_manager, getter_name, None)
        if not callable(getter):
            continue
        patch = getter()
        if not isinstance(patch, Mapping):
            continue
        raw_sources = patch.get("packages", patch.get("package_sources"))
        if not isinstance(raw_sources, list | tuple):
            continue
        for raw_source in raw_sources:
            package_source = package_source_from_raw(raw_source)
            if package_source is None:
                continue
            package_source = _normalize_package_source_for_scope(
                package_source, scope, settings_manager
            )
            source_key = package_source_match_key(package_source.source)
            if source_key in seen:
                continue
            seen.add(source_key)
            values.append(package_source)
    if values:
        return tuple(values)
    getter = getattr(settings_manager, "get_package_sources", None)
    return tuple(getter()) if callable(getter) else ()


def package_source_scopes(settings_manager: object) -> dict[str, str]:
    """Return the source scope for configured package declarations."""

    scopes: dict[str, str] = {}
    for getter_name, scope in _SETTINGS_SCOPES:
        getter = getattr(settings_manager, getter_name, None)
        if not callable(getter):
            continue
        patch = getter()
        if not isinstance(patch, Mapping):
            continue
        raw_sources = patch.get("packages", patch.get("package_sources"))
        if not isinstance(raw_sources, list | tuple):
            continue
        for raw_source in raw_sources:
            package_source = package_source_from_raw(raw_source)
            if package_source is not None:
                package_source = _normalize_package_source_for_scope(
                    package_source, scope, settings_manager
                )
                scopes.setdefault(package_source.source, scope)
    return scopes


_SETTINGS_SCOPES: tuple[tuple[str, PackageSourceScope], ...] = (
    ("get_project_settings", "project"),
    ("get_global_settings", "user"),
    ("get_session_settings", "session"),
)


def _normalize_package_source_for_scope(
    package_source: PackageSourceConfig,
    scope: PackageSourceScope,
    settings_manager: object,
) -> PackageSourceConfig:
    source = package_source.source
    if is_remote_package_source(source):
        return package_source
    path = Path(source).expanduser()
    if path.is_absolute():
        return replace(package_source, source=str(path.resolve()))
    base_dir = _scope_base_dir(settings_manager, scope)
    if base_dir is None:
        return package_source
    return replace(package_source, source=str((base_dir / path).resolve()))


def _scope_base_dir(settings_manager: object, scope: PackageSourceScope) -> Path | None:
    attr = (
        "global_base_dir"
        if scope == "user"
        else "project_base_dir"
        if scope == "project"
        else ""
    )
    value = getattr(settings_manager, attr, None) if attr else None
    return Path(value).expanduser().resolve() if value is not None else None
