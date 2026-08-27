"""Product-neutral diagnostics archive creation.

Products project their own diagnostic records and manifest shape before calling
this module. The writer owns only archive safety and mandatory redaction.
"""

from __future__ import annotations

import json
import os
import platform
import re
import stat
import sys
import zipfile
from collections.abc import Callable, Iterable, Mapping
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Literal, cast
from uuid import uuid4

from loushang.foundation.artifact_store import (
    DEFAULT_ARTIFACT_RETENTION_POLICY,
    ArtifactRef,
    ArtifactRetentionPolicy,
    ArtifactSnapshotStore,
    ArtifactSourceRejected,
    ArtifactStoreError,
    sweep_managed_artifacts,
)
from loushang.harness.diagnostics.types import DiagnosticRecord
from loushang.harness.environment import PlatformPaths, resolve_platform_paths


def _safe_relative_directory(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(
        value
        and "\\" not in value
        and not any(ord(character) < 32 for character in value)
        and not path.is_absolute()
        and not PureWindowsPath(value).drive
        and ".." not in path.parts
        and path.as_posix() == value
        and str(path) not in {"", "."}
    )


def _safe_filename_fragment(value: str) -> bool:
    return bool(
        value
        and len(value) <= 128
        and "/" not in value
        and "\\" not in value
        and value not in {".", ".."}
        and not any(ord(character) < 32 for character in value)
        and not any(character in '<>:"|?*' for character in value)
        and value[-1] not in {".", " "}
    )


@dataclass(frozen=True)
class DiagnosticExportArtifact:
    """A text artifact to include under a safe relative archive name."""

    archive_name: str
    source_path: Path | None = None
    content: bytes | None = None

    def __post_init__(self) -> None:
        if (self.source_path is None) == (self.content is None):
            raise ValueError(
                "diagnostics artifact requires exactly one source_path or content"
            )


@dataclass(frozen=True, slots=True)
class DiagnosticBundleProfile:
    """Stable archive identity shared by Loushang Product hosts."""

    package_name: str = "loushang"
    archive_root: Literal["project", "platform"] = "project"
    archive_directory: str = "state/diagnostics"
    archive_prefix: str = "loushang-diag"
    debug_directory: str = "state/debug"
    trace_directory: str = "state/traces"
    retention: ArtifactRetentionPolicy = DEFAULT_ARTIFACT_RETENTION_POLICY
    readme: str = (
        "Loushang diagnostics bundle\n"
        "\n"
        "This archive contains recent local debugging artifacts for troubleshooting.\n"
        "It may include debug logs, structured trace events, and a diagnostics summary.\n"
        "Conversation transcripts and prompt attachments are not included. Common bearer\n"
        "tokens and API key fields are redacted on export, but review the archive before\n"
        "sharing it outside your machine.\n"
    )

    def __post_init__(self) -> None:
        if self.archive_root not in {"project", "platform"}:
            raise ValueError(f"unsupported diagnostics archive root: {self.archive_root!r}")
        for name, value in (
            ("archive_directory", self.archive_directory),
            ("debug_directory", self.debug_directory),
            ("trace_directory", self.trace_directory),
        ):
            if not _safe_relative_directory(value):
                raise ValueError(
                    f"diagnostics {name} must be a safe relative directory"
                )
        if not _safe_filename_fragment(self.archive_prefix):
            raise ValueError("diagnostics archive_prefix must be a portable name")


DEFAULT_DIAGNOSTIC_BUNDLE_PROFILE = DiagnosticBundleProfile(
    archive_root="platform"
)
DEFAULT_DIAGNOSTICS_LIMIT = 50


def export_diagnostics_bundle(
    *,
    project_root: str | Path,
    session_dir: str | Path,
    output: str | Path | None = None,
    diagnostics_service: object | None = None,
    debug_latest_path: str | Path | None = None,
    trace_latest_path: str | Path | None = None,
    artifact_store: ArtifactSnapshotStore | None = None,
    platform_paths: PlatformPaths | None = None,
    now: Callable[[], datetime] | None = None,
    profile: DiagnosticBundleProfile = DEFAULT_DIAGNOSTIC_BUNDLE_PROFILE,
) -> Path:
    """Collect and export the standard Product diagnostics bundle."""

    from loushang.harness.diagnostics.serialization import serialize_diagnostic

    root = Path(project_root).expanduser().resolve()
    sessions = Path(session_dir).expanduser().resolve()
    generated_at = (now or utc_now)()
    platform_home = (platform_paths or resolve_platform_paths()).home
    bundle_path = resolve_export_output_path(
        platform_home if profile.archive_root == "platform" else root,
        output,
        generated_at,
        directory=profile.archive_directory,
        prefix=profile.archive_prefix,
    )

    def serialize_record(record: object) -> Mapping[str, object]:
        return serialize_diagnostic(cast(DiagnosticRecord, record))

    diagnostics = collect_diagnostics(
        diagnostics_service,
        serializer=serialize_record,
        limit=DEFAULT_DIAGNOSTICS_LIMIT,
    )
    debug_latest = (
        platform_home / profile.debug_directory / "latest"
        if debug_latest_path is None
        else Path(debug_latest_path).expanduser()
    )
    trace_latest = (
        platform_home / profile.trace_directory / "latest"
        if trace_latest_path is None
        else Path(trace_latest_path).expanduser()
    )
    snapshots = _snapshot_observability_artifacts(
        artifact_store,
        debug_latest=debug_latest,
        trace_latest=trace_latest,
    )
    debug_snapshot = next(
        (item for item in snapshots if item.kind == "debug-log"),
        None,
    )
    trace_snapshot = next(
        (item for item in snapshots if item.kind == "trace-jsonl"),
        None,
    )
    exported = export_diagnostics_archive(
        output_path=bundle_path,
        readme=profile.readme,
        manifest=_standard_manifest(
            profile=profile,
            project_root=root,
            session_dir=sessions,
            generated_at=generated_at,
            debug_included=(
                debug_snapshot is not None
                if artifact_store is not None
                else path_exists(debug_latest)
            ),
            trace_included=(
                trace_snapshot is not None
                if artifact_store is not None
                else path_exists(trace_latest)
            ),
            diagnostics=diagnostics,
            artifacts=snapshots,
        ),
        diagnostics=diagnostics,
        artifacts=_bundle_export_artifacts(
            artifact_store,
            debug_latest=debug_latest,
            trace_latest=trace_latest,
            debug_snapshot=debug_snapshot,
            trace_snapshot=trace_snapshot,
        ),
    )
    if output is None:
        sweep_managed_artifacts(
            exported.parent,
            name_prefix=f"{profile.archive_prefix}-",
            suffix=".zip",
            policy=profile.retention,
            preserve=(exported,),
        )
    return exported


def export_diagnostics_archive(
    *,
    output_path: str | Path,
    readme: str,
    manifest: Mapping[str, object],
    diagnostics: Iterable[Mapping[str, object]],
    artifacts: Iterable[DiagnosticExportArtifact] = (),
) -> Path:
    """Write a redacted diagnostics archive and return its output path.

    ``manifest`` and ``diagnostics`` are product projections. They are copied
    through the default structured redactor before JSON encoding, so a product
    cannot accidentally export a credential embedded in an otherwise valid
    diagnostic payload.
    """

    resolved_output = Path(output_path).expanduser().absolute()
    resolved_output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    redacted_manifest = redact_json_value(dict(manifest))
    redacted_diagnostics = [redact_json_value(dict(item)) for item in diagnostics]

    temporary = resolved_output.with_name(
        f".{resolved_output.name}.{uuid4().hex}.tmp"
    )
    descriptor = _open_new_private_file(temporary)
    metadata = os.fstat(descriptor)
    temporary_identity = (metadata.st_dev, metadata.st_ino)
    try:
        with os.fdopen(descriptor, "w+b") as handle:
            descriptor = -1
            with zipfile.ZipFile(
                handle,
                "w",
                compression=zipfile.ZIP_DEFLATED,
            ) as archive:
                archive.writestr("README.txt", redact_text(readme))
                archive.writestr("manifest.json", _json_text(redacted_manifest))
                archive.writestr("diagnostics.json", _json_text(redacted_diagnostics))
                for artifact in artifacts:
                    _write_text_artifact(archive, artifact)
            handle.flush()
            os.fsync(handle.fileno())
        _publish_file_exclusive(
            temporary,
            resolved_output,
            identity=temporary_identity,
        )
        _sync_directory(resolved_output.parent)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        with suppress(OSError):
            _unlink_owned_file(temporary, temporary_identity)
    return resolved_output


def collect_diagnostics(
    diagnostics_service: object | None,
    *,
    serializer: Callable[[object], Mapping[str, object]],
    limit: int = 50,
) -> list[dict[str, object]]:
    """Collect safe diagnostic mappings from an injected service.

    Services in older Products accepted either ``limit=`` or one positional
    argument.  The compatibility probe belongs here, while the serializer is
    injected so Products retain their external diagnostic schema.
    """

    getter = getattr(diagnostics_service, "get_last_diagnostics", None)
    if not callable(getter):
        return []
    try:
        records = getter(limit=limit)
    except TypeError:
        records = getter(limit)
    except Exception:
        return []
    if not isinstance(records, list | tuple):
        return []
    normalized: list[dict[str, object]] = []
    for record in records:
        try:
            normalized.append(dict(serializer(record)))
        except Exception:
            continue
    return normalized


def resolve_export_output_path(
    project_root: str | Path,
    output: str | Path | None,
    generated_at: datetime,
    *,
    directory: str = ".loushang/diagnostics",
    prefix: str = "loushang-diag",
) -> Path:
    """Resolve an explicit or timestamped archive path without Product IO."""

    if not _safe_relative_directory(directory):
        raise ValueError("diagnostics directory must be a safe relative path")
    if not _safe_filename_fragment(prefix):
        raise ValueError("diagnostics prefix must be a portable name")
    if output is not None:
        return Path(output).expanduser().absolute()
    timestamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    return (
        Path(project_root).expanduser().resolve()
        / directory
        / f"{prefix}-{timestamp}.zip"
    )


def path_exists(path: str | Path) -> bool:
    """Return false instead of leaking an inaccessible artifact path."""

    try:
        return Path(path).exists()
    except OSError:
        return False


def utc_now() -> datetime:
    """Return the shared UTC clock used by diagnostic archive adapters."""

    return datetime.now(UTC)


def _standard_manifest(
    *,
    profile: DiagnosticBundleProfile,
    project_root: Path,
    session_dir: Path,
    generated_at: datetime,
    debug_included: bool,
    trace_included: bool,
    diagnostics: list[dict[str, object]],
    artifacts: tuple[ArtifactRef, ...],
) -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "generatedAt": generated_at.isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        "cwd": str(project_root),
        "sessionDir": str(session_dir),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "loushangVersion": _package_version(profile.package_name),
        "included": {
            "debugLatest": debug_included,
            "traceLatest": trace_included,
            "sessionTranscript": False,
            "diagnostics": bool(diagnostics),
        },
        "artifacts": [artifact.manifest_entry() for artifact in artifacts],
    }


def _snapshot_observability_artifacts(
    store: ArtifactSnapshotStore | None,
    *,
    debug_latest: Path,
    trace_latest: Path,
) -> tuple[ArtifactRef, ...]:
    if store is None:
        return ()
    snapshots: list[ArtifactRef] = []
    for path, logical_name, kind, media_type, source in (
        (
            debug_latest,
            "debug/latest.log",
            "debug-log",
            "text/plain",
            "observability.debug.latest",
        ),
        (
            trace_latest,
            "traces/latest.jsonl",
            "trace-jsonl",
            "application/x-ndjson",
            "observability.trace.latest",
        ),
    ):
        snapshot = _snapshot_latest(
            store,
            path,
            logical_name=logical_name,
            kind=kind,
            media_type=media_type,
            source=source,
        )
        if snapshot is not None:
            snapshots.append(snapshot)
    return tuple(snapshots)


def _bundle_export_artifacts(
    store: ArtifactSnapshotStore | None,
    *,
    debug_latest: Path,
    trace_latest: Path,
    debug_snapshot: ArtifactRef | None,
    trace_snapshot: ArtifactRef | None,
) -> tuple[DiagnosticExportArtifact, ...]:
    artifacts: list[DiagnosticExportArtifact] = []
    for archive_name, latest, snapshot in (
        ("debug/latest.log", debug_latest, debug_snapshot),
        ("traces/latest.jsonl", trace_latest, trace_snapshot),
    ):
        if store is None:
            if path_exists(latest):
                artifacts.append(
                    DiagnosticExportArtifact(
                        archive_name=archive_name,
                        source_path=latest,
                    )
                )
        elif snapshot is not None:
            artifacts.append(
                DiagnosticExportArtifact(
                    archive_name=archive_name,
                    content=store.read_bytes(snapshot),
                )
            )
    return tuple(artifacts)


def _snapshot_latest(
    store: ArtifactSnapshotStore,
    path: Path,
    *,
    logical_name: str,
    kind: str,
    media_type: str,
    source: str,
) -> ArtifactRef | None:
    try:
        source_path = _resolve_latest_source(path)
    except (ArtifactSourceRejected, OSError):
        return None
    for _attempt in range(2):
        try:
            return store.snapshot_file(
                source_path,
                logical_name=logical_name,
                kind=kind,
                media_type=media_type,
                disclosure="redact",
                source=source,
            )
        except ArtifactSourceRejected:
            continue
        except (ArtifactStoreError, OSError):
            return None
    return None


def _resolve_latest_source(path: Path) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        return expanded.resolve(strict=True)
    if expanded.name != "latest" or not expanded.is_file():
        return expanded
    try:
        with expanded.open("rb") as handle:
            raw_pointer = handle.read(4097)
    except (OSError, UnicodeError):
        return expanded
    if len(raw_pointer) > 4096:
        return expanded
    try:
        pointer = raw_pointer.decode("utf-8").strip()
    except UnicodeError:
        return expanded
    if not pointer or "\n" in pointer:
        return expanded
    target = Path(pointer)
    if not target.is_absolute():
        return expanded
    root = expanded.parent.resolve(strict=True)
    resolved_target = target.resolve(strict=True)
    if resolved_target == root or resolved_target.is_relative_to(root):
        return resolved_target
    raise ArtifactSourceRejected("latest pointer is outside its state directory")


def _package_version(package_name: str) -> str | None:
    try:
        return package_version(package_name)
    except PackageNotFoundError:
        return None


def redact_json_value(value: object) -> object:
    """Recursively redact known credential fields while preserving JSON shape."""

    if isinstance(value, Mapping):
        redacted: dict[str, object] = {}
        for key, item in value.items():
            key_text = str(key)
            if _SENSITIVE_KEY.search(key_text):
                redacted[key_text] = "[REDACTED]"
            else:
                redacted[key_text] = redact_json_value(item)
        return redacted
    if isinstance(value, list | tuple):
        return [redact_json_value(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(content: str) -> str:
    """Redact common bearer-token and credential assignment forms."""

    redacted = content
    for pattern, replacement in _REDACTION_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _write_text_artifact(
    archive: zipfile.ZipFile,
    artifact: DiagnosticExportArtifact,
) -> None:
    archive_name = _safe_archive_name(artifact.archive_name)
    if artifact.content is not None:
        content = artifact.content.decode("utf-8", errors="replace")
    else:
        assert artifact.source_path is not None
        try:
            content = artifact.source_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            return
    archive.writestr(archive_name, redact_text(content))


def _safe_archive_name(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or any(ord(character) < 32 for character in value)
        or path.is_absolute()
        or PureWindowsPath(value).drive
        or ".." in path.parts
        or path.as_posix() != value
        or str(path) in {"", "."}
    ):
        raise ValueError(
            f"diagnostics archive member must be a safe relative path: {value!r}"
        )
    return path.as_posix()


def _json_text(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    except (TypeError, ValueError) as error:
        raise TypeError(
            "diagnostics export values must be JSON serializable"
        ) from error


def _open_new_private_file(path: Path) -> int:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    return os.open(path, flags, 0o600)


def _publish_file_exclusive(
    temporary: Path,
    destination: Path,
    *,
    identity: tuple[int, int],
) -> None:
    _validate_owned_file(temporary, identity)
    if os.name == "nt":
        temporary.rename(destination)
    else:
        os.link(temporary, destination, follow_symlinks=False)
    try:
        _validate_owned_file(destination, identity)
    except OSError:
        with suppress(OSError):
            published = destination.lstat()
            _unlink_owned_file(
                destination,
                (published.st_dev, published.st_ino),
            )
        raise


def _validate_owned_file(path: Path, identity: tuple[int, int]) -> None:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or (
        metadata.st_dev,
        metadata.st_ino,
    ) != identity:
        raise PermissionError(f"diagnostics artifact identity changed: {path}")


def _unlink_owned_file(path: Path, identity: tuple[int, int]) -> None:
    _validate_owned_file(path, identity)
    path.unlink()


def _sync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        with suppress(OSError):
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


_SENSITIVE_KEY = re.compile(
    r"(?i)(?:api[_-]?key|authorization|credential|password|secret|token)"
)
_REDACTION_PATTERNS = (
    (
        re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;}\"']+"),
        r"\1[REDACTED]",
    ),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1[REDACTED]"),
    (
        re.compile(
            r"(?i)(\"?(?:api[_-]?key|token|secret|password)\"?\s*[:=]\s*\"?)[^\",\s}]+(\"?)"
        ),
        r"\1[REDACTED]\2",
    ),
)


__all__ = [
    "DEFAULT_DIAGNOSTIC_BUNDLE_PROFILE",
    "DEFAULT_DIAGNOSTICS_LIMIT",
    "DiagnosticBundleProfile",
    "DiagnosticExportArtifact",
    "collect_diagnostics",
    "export_diagnostics_bundle",
    "export_diagnostics_archive",
    "path_exists",
    "redact_json_value",
    "redact_text",
    "resolve_export_output_path",
    "utc_now",
]
