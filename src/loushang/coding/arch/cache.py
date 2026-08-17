"""Versioned, rebuildable cache for normalized per-file import facts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from loushang.coding.arch.model import (
    ArchitectureDiagnostic,
    DiagnosticSeverity,
    ImportCategory,
    ImportDependencyFact,
    ImportKind,
    ImportModuleFact,
    SourceEvidence,
)
from loushang.harness.resources.layout import resolve_platform_home

IMPORT_FACT_CACHE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ImportFactCacheNamespace:
    root_id: str
    language: str
    provider_version: int
    package_prefix: str | None
    configuration_key: str = ""


@dataclass(frozen=True)
class ImportFileFingerprint:
    sha256: str
    size: int


@dataclass(frozen=True)
class CachedImportFile:
    fingerprint: ImportFileFingerprint
    module: ImportModuleFact | None
    dependencies: tuple[ImportDependencyFact, ...] = ()
    diagnostics: tuple[ArchitectureDiagnostic, ...] = ()


@dataclass(frozen=True)
class ImportFactCacheSnapshot:
    namespace: ImportFactCacheNamespace
    module_index: tuple[tuple[str, str | None], ...]
    entries: tuple[tuple[str, CachedImportFile], ...]

    def entry_map(self) -> dict[str, CachedImportFile]:
        return dict(self.entries)


class ImportFactCache:
    """In-memory fact cache with optional atomic JSON persistence."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path).expanduser() if path is not None else None
        self._snapshots: dict[ImportFactCacheNamespace, ImportFactCacheSnapshot] = {}
        self._disk_loaded = False
        self._persisted_snapshot: ImportFactCacheSnapshot | None = None
        self.last_error: str | None = None

    def load(
        self, namespace: ImportFactCacheNamespace
    ) -> ImportFactCacheSnapshot | None:
        self._load_disk_once()
        return self._snapshots.get(namespace)

    def replace(self, snapshot: ImportFactCacheSnapshot) -> None:
        if (
            self._snapshots.get(snapshot.namespace) == snapshot
            and self.last_error is None
        ):
            return
        self._snapshots[snapshot.namespace] = snapshot
        if self.path is None:
            return
        if self._persisted_snapshot == snapshot:
            self.last_error = None
            return
        try:
            _write_snapshot(self.path, snapshot)
        except OSError as exc:
            self.last_error = str(exc)
        else:
            self._persisted_snapshot = snapshot
            self.last_error = None

    def _load_disk_once(self) -> None:
        if self._disk_loaded:
            return
        self._disk_loaded = True
        if self.path is None or not self.path.is_file():
            return
        try:
            snapshot = _read_snapshot(self.path)
        except (OSError, TypeError, ValueError) as exc:
            self.last_error = str(exc)
            return
        self._snapshots[snapshot.namespace] = snapshot
        self._persisted_snapshot = snapshot


def import_cache_root_id(root: str | Path) -> str:
    canonical = os.path.normcase(str(Path(root).expanduser().resolve()))
    return hashlib.sha256(os.fsencode(canonical)).hexdigest()[:24]


def default_import_fact_cache_path(
    root: str | Path,
    *,
    language: str,
    provider_version: int,
    cache_root: str | Path | None = None,
) -> Path:
    normalized_language = _cache_path_segment(language, "language")
    if provider_version < 1:
        raise ValueError("provider_version must be at least 1")
    base = (
        resolve_platform_home() / "cache" / "coding" / "arch"
        if cache_root is None
        else Path(cache_root).expanduser()
    )
    root_id = import_cache_root_id(root)
    filename = f"{normalized_language}-facts-v{provider_version}.json"
    return base.resolve(strict=False) / root_id / filename


def fingerprint_source(content: bytes) -> ImportFileFingerprint:
    return ImportFileFingerprint(
        sha256=hashlib.sha256(content).hexdigest(),
        size=len(content),
    )


def _write_snapshot(path: Path, snapshot: ImportFactCacheSnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _snapshot_payload(snapshot)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            with suppress(FileNotFoundError):
                temporary_path.unlink()


def _read_snapshot(path: Path) -> ImportFactCacheSnapshot:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("import fact cache must contain a JSON object")
    if payload.get("schema_version") != IMPORT_FACT_CACHE_SCHEMA_VERSION:
        raise ValueError("unsupported import fact cache schema version")
    namespace = _decode_namespace(payload.get("namespace"))
    raw_module_index = _require_mapping(payload.get("module_index"), "module_index")
    module_index = tuple(
        sorted(
            (
                _require_string(path, "module_index path"),
                _optional_string(module, "module_index module"),
            )
            for path, module in raw_module_index.items()
        )
    )
    raw_entries = _require_mapping(payload.get("entries"), "entries")
    entries = tuple(
        sorted(
            (
                _require_string(relative_path, "entry path"),
                _decode_cached_file(value),
            )
            for relative_path, value in raw_entries.items()
        )
    )
    return ImportFactCacheSnapshot(
        namespace=namespace,
        module_index=module_index,
        entries=entries,
    )


def _snapshot_payload(snapshot: ImportFactCacheSnapshot) -> dict[str, object]:
    return {
        "schema_version": IMPORT_FACT_CACHE_SCHEMA_VERSION,
        "namespace": asdict(snapshot.namespace),
        "module_index": dict(snapshot.module_index),
        "entries": {
            path: _cached_file_payload(entry) for path, entry in snapshot.entries
        },
    }


def _cached_file_payload(entry: CachedImportFile) -> dict[str, object]:
    return {
        "fingerprint": asdict(entry.fingerprint),
        "module": asdict(entry.module) if entry.module is not None else None,
        "dependencies": [
            {
                **asdict(dependency),
                "evidence": asdict(dependency.evidence),
            }
            for dependency in entry.dependencies
        ],
        "diagnostics": [asdict(diagnostic) for diagnostic in entry.diagnostics],
    }


def _decode_namespace(value: object) -> ImportFactCacheNamespace:
    raw = _require_mapping(value, "namespace")
    return ImportFactCacheNamespace(
        root_id=_require_string(raw.get("root_id"), "namespace.root_id"),
        language=_require_string(raw.get("language"), "namespace.language"),
        provider_version=_require_integer(
            raw.get("provider_version"), "namespace.provider_version"
        ),
        package_prefix=_optional_string(
            raw.get("package_prefix"), "namespace.package_prefix"
        ),
        configuration_key=_require_string(
            raw.get("configuration_key"),
            "namespace.configuration_key",
            allow_empty=True,
        ),
    )


def _decode_cached_file(value: object) -> CachedImportFile:
    raw = _require_mapping(value, "cache entry")
    fingerprint_raw = _require_mapping(raw.get("fingerprint"), "fingerprint")
    fingerprint = ImportFileFingerprint(
        sha256=_require_string(fingerprint_raw.get("sha256"), "fingerprint.sha256"),
        size=_require_integer(fingerprint_raw.get("size"), "fingerprint.size"),
    )
    module_raw = raw.get("module")
    module = None if module_raw is None else _decode_module(module_raw)
    dependencies_raw = _require_list(raw.get("dependencies"), "dependencies")
    diagnostics_raw = _require_list(raw.get("diagnostics"), "diagnostics")
    return CachedImportFile(
        fingerprint=fingerprint,
        module=module,
        dependencies=tuple(_decode_dependency(item) for item in dependencies_raw),
        diagnostics=tuple(_decode_diagnostic(item) for item in diagnostics_raw),
    )


def _decode_module(value: object) -> ImportModuleFact:
    raw = _require_mapping(value, "module")
    return ImportModuleFact(
        module=_require_string(raw.get("module"), "module.module"),
        path=_require_string(raw.get("path"), "module.path"),
        language=_require_string(raw.get("language"), "module.language"),
        is_package=_require_boolean(raw.get("is_package"), "module.is_package"),
    )


def _decode_dependency(value: object) -> ImportDependencyFact:
    raw = _require_mapping(value, "dependency")
    evidence_raw = _require_mapping(raw.get("evidence"), "dependency.evidence")
    category = _require_string(raw.get("category"), "dependency.category")
    if category not in {"eager", "typing", "deferred", "lazy_export"}:
        raise ValueError(f"unsupported cached import category: {category!r}")
    kind = _require_string(raw.get("kind"), "dependency.kind")
    if kind not in {"import", "from_import", "dynamic_import"}:
        raise ValueError(f"unsupported cached import kind: {kind!r}")
    return ImportDependencyFact(
        source=_require_string(raw.get("source"), "dependency.source"),
        target=_require_string(raw.get("target"), "dependency.target"),
        category=cast(ImportCategory, category),
        kind=cast(ImportKind, kind),
        evidence=SourceEvidence(
            path=_require_string(evidence_raw.get("path"), "evidence.path"),
            line=_require_integer(evidence_raw.get("line"), "evidence.line"),
            column=_require_integer(evidence_raw.get("column"), "evidence.column"),
            statement=_require_string(
                evidence_raw.get("statement"), "evidence.statement", allow_empty=True
            ),
        ),
        is_reexport=_require_boolean(raw.get("is_reexport"), "dependency.is_reexport"),
    )


def _decode_diagnostic(value: object) -> ArchitectureDiagnostic:
    raw = _require_mapping(value, "diagnostic")
    severity = _require_string(raw.get("severity"), "diagnostic.severity")
    if severity not in {"error", "warning"}:
        raise ValueError(f"unsupported cached diagnostic severity: {severity!r}")
    line = raw.get("line")
    return ArchitectureDiagnostic(
        code=_require_string(raw.get("code"), "diagnostic.code"),
        message=_require_string(raw.get("message"), "diagnostic.message"),
        severity=cast(DiagnosticSeverity, severity),
        path=_optional_string(raw.get("path"), "diagnostic.path"),
        line=None if line is None else _require_integer(line, "diagnostic.line"),
    )


def _require_mapping(value: object, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} keys must be strings")
    return value


def _require_list(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise TypeError(f"{field_name} must be an array")
    return value


def _require_string(
    value: object, field_name: str, *, allow_empty: bool = False
) -> str:
    if not isinstance(value, str) or (not allow_empty and not value):
        raise TypeError(f"{field_name} must be a string")
    return value


def _optional_string(value: object, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, field_name)


def _require_integer(value: object, field_name: str) -> int:
    if type(value) is not int:
        raise TypeError(f"{field_name} must be an integer")
    return value


def _require_boolean(value: object, field_name: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{field_name} must be a boolean")
    return value


def _cache_path_segment(value: str, field_name: str) -> str:
    normalized = value.strip()
    if (
        not normalized
        or normalized in {".", ".."}
        or "/" in normalized
        or "\\" in normalized
    ):
        raise ValueError(f"{field_name} must be a non-empty path segment")
    return normalized


__all__ = [
    "IMPORT_FACT_CACHE_SCHEMA_VERSION",
    "CachedImportFile",
    "ImportFactCache",
    "ImportFactCacheNamespace",
    "ImportFactCacheSnapshot",
    "ImportFileFingerprint",
    "default_import_fact_cache_path",
    "fingerprint_source",
    "import_cache_root_id",
]
