"""Product-neutral diagnostics archive creation.

Products project their own diagnostic records and manifest shape before calling
this module. The writer owns only archive safety and mandatory redaction.
"""

from __future__ import annotations

import json
import platform
import re
import sys
import zipfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from pathlib import Path, PurePosixPath
from typing import cast

from loushang.harness.diagnostics.types import DiagnosticRecord


@dataclass(frozen=True)
class DiagnosticExportArtifact:
    """A text artifact to include under a safe relative archive name."""

    archive_name: str
    source_path: Path


@dataclass(frozen=True, slots=True)
class DiagnosticBundleProfile:
    """Stable archive identity shared by Loushang Product hosts."""

    package_name: str = "loushang"
    archive_directory: str = ".loushang/diagnostics"
    archive_prefix: str = "loushang-diag"
    debug_directory: str = ".loushang/debug"
    trace_directory: str = ".loushang/traces"
    readme: str = (
        "Loushang diagnostics bundle\n"
        "\n"
        "This archive contains recent local debugging artifacts for troubleshooting.\n"
        "It may include debug logs, structured trace events, the latest session JSONL,\n"
        "and a diagnostics summary. Common bearer tokens and API key fields are redacted\n"
        "on export, but review the archive before sharing it outside your machine.\n"
    )


DEFAULT_DIAGNOSTIC_BUNDLE_PROFILE = DiagnosticBundleProfile()
DEFAULT_DIAGNOSTICS_LIMIT = 50


def export_diagnostics_bundle(
    *,
    project_root: str | Path,
    session_dir: str | Path,
    output: str | Path | None = None,
    diagnostics_service: object | None = None,
    debug_latest_path: str | Path | None = None,
    trace_latest_path: str | Path | None = None,
    now: Callable[[], datetime] | None = None,
    profile: DiagnosticBundleProfile = DEFAULT_DIAGNOSTIC_BUNDLE_PROFILE,
) -> Path:
    """Collect and export the standard Product diagnostics bundle."""

    from loushang.harness.diagnostics.serialization import serialize_diagnostic

    root = Path(project_root).expanduser().resolve()
    sessions = Path(session_dir).expanduser().resolve()
    generated_at = (now or utc_now)()
    bundle_path = resolve_export_output_path(
        root,
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
        Path.home() / profile.debug_directory / "latest"
        if debug_latest_path is None
        else Path(debug_latest_path).expanduser()
    )
    trace_latest = (
        Path.home() / profile.trace_directory / "latest"
        if trace_latest_path is None
        else Path(trace_latest_path).expanduser()
    )
    session_latest = sessions / "latest.jsonl"
    return export_diagnostics_archive(
        output_path=bundle_path,
        readme=profile.readme,
        manifest=_standard_manifest(
            profile=profile,
            project_root=root,
            session_dir=sessions,
            generated_at=generated_at,
            debug_latest=debug_latest,
            trace_latest=trace_latest,
            session_latest=session_latest,
            diagnostics=diagnostics,
        ),
        diagnostics=diagnostics,
        artifacts=(
            DiagnosticExportArtifact("debug/latest.log", debug_latest),
            DiagnosticExportArtifact("traces/latest.jsonl", trace_latest),
            DiagnosticExportArtifact("sessions/latest.jsonl", session_latest),
        ),
    )


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

    resolved_output = Path(output_path).expanduser().resolve()
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    redacted_manifest = redact_json_value(dict(manifest))
    redacted_diagnostics = [redact_json_value(dict(item)) for item in diagnostics]

    with zipfile.ZipFile(
        resolved_output, "w", compression=zipfile.ZIP_DEFLATED
    ) as archive:
        archive.writestr("README.txt", redact_text(readme))
        archive.writestr("manifest.json", _json_text(redacted_manifest))
        archive.writestr("diagnostics.json", _json_text(redacted_diagnostics))
        for artifact in artifacts:
            _write_text_artifact(archive, artifact)
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

    if output is not None:
        return Path(output).expanduser().resolve()
    timestamp = generated_at.strftime("%Y%m%dT%H%M%SZ")
    return Path(project_root).expanduser().resolve() / directory / f"{prefix}-{timestamp}.zip"


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
    debug_latest: Path,
    trace_latest: Path,
    session_latest: Path,
    diagnostics: list[dict[str, object]],
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
            "debugLatest": path_exists(debug_latest),
            "traceLatest": path_exists(trace_latest),
            "sessionLatest": path_exists(session_latest),
            "diagnostics": bool(diagnostics),
        },
    }


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
    try:
        content = artifact.source_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return
    archive.writestr(archive_name, redact_text(content))


def _safe_archive_name(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
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
