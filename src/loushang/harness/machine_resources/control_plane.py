"""Unified machine-resource inventory, maintenance, and migration control plane.

Path resolution is pure. Inspection is bounded and read-only. Cleanup is
restricted to authorities whose inactivity or orphan status can be proven, and
migration is copy-first: canonical publication commits before a compatibility
source is ever considered redundant, and this module never deletes the source.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import stat
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from uuid import uuid4

from loushang.foundation.platform_paths import PlatformPaths, resolve_platform_paths
from loushang.foundation.runtime_scope import (
    RuntimeScope,
    RuntimeSweepPolicy,
    sweep_runtime_runs,
)
from loushang.harness.artifacts import (
    ArtifactRetentionPolicy,
    SessionBlobStore,
    require_portable_artifact_id,
    resolve_session_blob_data_root,
    session_blob_authority_id,
    sweep_managed_artifacts,
)
from loushang.harness.conversation import (
    ConversationKey,
    StoreCommitOutcomeUnknown,
    StoreDataError,
    load_conversation_deletion_receipt,
)
from loushang.harness.transcript.jsonl_file import (
    AgentTranscriptFileLayout,
    create_agent_transcript_file_store,
    decode_agent_transcript_bytes,
    load_agent_transcript_header,
)
from loushang.harness.transcript.session_artifacts import (
    clone_agent_transcript_session_blobs,
    collect_agent_transcript_session_blobs,
)

MachineResourceLifetime = Literal[
    "durable_user_data",
    "durable_machine_state",
    "reproducible_cache",
    "live_process",
    "disposable_scratch",
]
MachineResourceMode = Literal["canonical", "compatibility"]
MachineResourceCleanTarget = Literal[
    "runtime",
    "diagnostics",
    "orphan_session_assets",
]
MachineResourceState = Literal["missing", "available", "partial", "unsafe"]
MachineResourceMigrationDisposition = Literal[
    "migrated",
    "already_present",
    "failed",
]
MachineResourceMigrationDiagnosticCode = Literal[
    "already_present",
    "destination_conflict",
    "duplicate_identity",
    "scan_truncated",
    "source_rejected",
]

MACHINE_RESOURCE_SCHEMA_VERSION = 1
DEFAULT_MACHINE_RESOURCE_SCAN_ENTRIES = 10_000
DEFAULT_MACHINE_RESOURCE_SCAN_DEPTH = 16
DEFAULT_MACHINE_RESOURCE_MIGRATION_TRANSCRIPT_BYTES = 64 * 1024 * 1024
DEFAULT_MACHINE_RESOURCE_MIGRATION_BLOB_BYTES = 64 * 1024 * 1024
_SESSION_SUFFIX = ".jsonl"
_DIAGNOSTIC_PREFIX = "loushang-diag"
_DIAGNOSTIC_SUFFIX = ".zip"
_SHA256 = re.compile(r"[0-9a-f]{64}")


@dataclass(frozen=True, slots=True)
class MachineResourcePath:
    resource_id: str
    path: Path
    lifetime: MachineResourceLifetime
    mode: MachineResourceMode
    cleanup: str

    def to_dict(self) -> dict[str, object]:
        return {
            "resourceId": self.resource_id,
            "path": str(self.path),
            "lifetime": self.lifetime,
            "mode": self.mode,
            "cleanup": self.cleanup,
        }


@dataclass(frozen=True, slots=True)
class MachineResourceLayout:
    platform_paths: PlatformPaths
    cwd: Path
    resources: tuple[MachineResourcePath, ...]

    @property
    def sessions(self) -> Path:
        return self.platform_paths.data / "sessions"

    @property
    def session_assets(self) -> Path:
        return self.platform_paths.data / "session-assets"

    @property
    def compatibility_session_dirs(self) -> tuple[Path, ...]:
        return tuple(
            resource.path
            for resource in self.resources
            if resource.resource_id.startswith("sessions.")
            and resource.mode == "compatibility"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": MACHINE_RESOURCE_SCHEMA_VERSION,
            "home": str(self.platform_paths.home),
            "cwd": str(self.cwd),
            "resources": [resource.to_dict() for resource in self.resources],
        }


@dataclass(frozen=True, slots=True)
class MachineResourceStatus:
    resource: MachineResourcePath
    state: MachineResourceState
    files: int = 0
    directories: int = 0
    bytes: int = 0
    truncated: bool = False
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            **self.resource.to_dict(),
            "state": self.state,
            "files": self.files,
            "directories": self.directories,
            "bytes": self.bytes,
            "truncated": self.truncated,
            "errors": list(self.errors),
        }


@dataclass(frozen=True, slots=True)
class MachineResourceStatusSnapshot:
    resources: tuple[MachineResourceStatus, ...]

    @property
    def total_bytes(self) -> int:
        return sum(resource.bytes for resource in self.resources)

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": MACHINE_RESOURCE_SCHEMA_VERSION,
            "totalBytes": self.total_bytes,
            "resources": [resource.to_dict() for resource in self.resources],
        }


@dataclass(frozen=True, slots=True)
class MachineResourceCleanRequest:
    targets: tuple[MachineResourceCleanTarget, ...] = (
        "runtime",
        "diagnostics",
        "orphan_session_assets",
    )
    apply: bool = False

    def __post_init__(self) -> None:
        targets = tuple(self.targets)
        supported = {"runtime", "diagnostics", "orphan_session_assets"}
        if not targets or any(target not in supported for target in targets):
            raise ValueError("machine resource cleanup target is invalid")
        if len(set(targets)) != len(targets):
            raise ValueError("machine resource cleanup targets must be unique")
        if type(self.apply) is not bool:
            raise TypeError("machine resource cleanup apply must be a boolean")
        object.__setattr__(self, "targets", targets)


@dataclass(frozen=True, slots=True)
class MachineResourceCleanReport:
    target: MachineResourceCleanTarget
    candidates: int = 0
    removed: int = 0
    removed_bytes: int = 0
    active: int = 0
    skipped: int = 0
    failed: int = 0
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "candidates": self.candidates,
            "removed": self.removed,
            "removedBytes": self.removed_bytes,
            "active": self.active,
            "skipped": self.skipped,
            "failed": self.failed,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class MachineResourceCleanResult:
    applied: bool
    reports: tuple[MachineResourceCleanReport, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": MACHINE_RESOURCE_SCHEMA_VERSION,
            "applied": self.applied,
            "reports": [report.to_dict() for report in self.reports],
        }


@dataclass(frozen=True, slots=True)
class MachineResourceMigrationDiagnostic:
    source: Path
    code: MachineResourceMigrationDiagnosticCode
    detail: str

    def to_dict(self) -> dict[str, object]:
        return {
            "source": str(self.source),
            "code": self.code,
            "detail": self.detail,
        }


@dataclass(frozen=True, slots=True)
class MachineResourceMigrationCandidate:
    source: Path
    destination: Path
    conversation_id: str
    source_sha256: str
    source_size: int
    blob_count: int

    def to_dict(self) -> dict[str, object]:
        return {
            "source": str(self.source),
            "destination": str(self.destination),
            "conversationId": self.conversation_id,
            "sourceSha256": self.source_sha256,
            "sourceSize": self.source_size,
            "blobCount": self.blob_count,
        }


@dataclass(frozen=True, slots=True)
class MachineResourceMigrationPlan:
    candidates: tuple[MachineResourceMigrationCandidate, ...]
    diagnostics: tuple[MachineResourceMigrationDiagnostic, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": MACHINE_RESOURCE_SCHEMA_VERSION,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "diagnostics": [diagnostic.to_dict() for diagnostic in self.diagnostics],
        }


@dataclass(frozen=True, slots=True)
class MachineResourceMigrationResult:
    candidate: MachineResourceMigrationCandidate
    disposition: MachineResourceMigrationDisposition
    detail: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            **self.candidate.to_dict(),
            "disposition": self.disposition,
            "detail": self.detail,
        }


def resolve_machine_resource_layout(
    *,
    platform_paths: PlatformPaths | None = None,
    cwd: str | Path | None = None,
    additional_session_dirs: Sequence[str | Path] = (),
) -> MachineResourceLayout:
    """Resolve canonical and compatibility resources without filesystem I/O."""

    paths = platform_paths or resolve_platform_paths()
    resolved_cwd = (Path.cwd() if cwd is None else Path(cwd).expanduser()).resolve(
        strict=False
    )
    resources = [
        MachineResourcePath(
            "sessions.global",
            paths.data / "sessions",
            "durable_user_data",
            "canonical",
            "never; delete through the Session authority",
        ),
        MachineResourcePath(
            "session_assets.global",
            paths.data / "session-assets",
            "durable_user_data",
            "canonical",
            "orphan-only after transcript authority scan",
        ),
        MachineResourcePath(
            "logs.debug",
            paths.state / "debug",
            "durable_machine_state",
            "canonical",
            "producer retention",
        ),
        MachineResourcePath(
            "logs.traces",
            paths.state / "traces",
            "durable_machine_state",
            "canonical",
            "producer retention",
        ),
        MachineResourcePath(
            "diagnostics.archives",
            paths.state / "diagnostics",
            "durable_machine_state",
            "canonical",
            "managed archive retention",
        ),
        MachineResourcePath(
            "plugins.state",
            paths.state / "plugins",
            "durable_machine_state",
            "canonical",
            "Plugin lifecycle authority only; never generic cleanup",
        ),
        MachineResourcePath(
            "coding.apphost_canary.control",
            paths.state
            / "products"
            / "coding"
            / "apphost-explicit-canary-control.jsonl",
            "durable_machine_state",
            "canonical",
            "Coding Product canary control only; never generic cleanup",
        ),
        MachineResourcePath(
            "cache.global",
            paths.cache,
            "reproducible_cache",
            "canonical",
            "evictable by an owning cache implementation",
        ),
        MachineResourcePath(
            "runtime.runs",
            paths.runtime / "runs",
            "live_process",
            "canonical",
            "lease-proven inactive runs only",
        ),
        MachineResourcePath(
            "temporary.global",
            paths.temporary,
            "disposable_scratch",
            "canonical",
            "creating owner only; no blind recursive cleanup",
        ),
        MachineResourcePath(
            "sessions.cwd_compatibility",
            resolved_cwd / ".loushang" / "sessions",
            "durable_user_data",
            "compatibility",
            "read-only discovery; copy-first migration",
        ),
        MachineResourcePath(
            "sessions.home_compatibility",
            paths.home / "sessions",
            "durable_user_data",
            "compatibility",
            "read-only discovery; copy-first migration",
        ),
        MachineResourcePath(
            "logs.debug_home_compatibility",
            paths.home / "debug",
            "durable_machine_state",
            "compatibility",
            "read-only status",
        ),
        MachineResourcePath(
            "logs.traces_home_compatibility",
            paths.home / "traces",
            "durable_machine_state",
            "compatibility",
            "read-only status",
        ),
    ]
    resources.extend(
        MachineResourcePath(
            f"sessions.configured_compatibility.{index}",
            _authority_path(Path(directory)),
            "durable_user_data",
            "compatibility",
            "read-only discovery; copy-first migration",
        )
        for index, directory in enumerate(additional_session_dirs, start=1)
    )
    deduplicated: list[MachineResourcePath] = []
    seen: set[tuple[str, Path]] = set()
    for resource in resources:
        normalized = _authority_path(resource.path)
        key = (resource.resource_id.split(".", 1)[0], normalized)
        if key in seen:
            continue
        seen.add(key)
        deduplicated.append(
            MachineResourcePath(
                resource.resource_id,
                normalized,
                resource.lifetime,
                resource.mode,
                resource.cleanup,
            )
        )
    return MachineResourceLayout(paths, resolved_cwd, tuple(deduplicated))


def inspect_machine_resources(
    layout: MachineResourceLayout,
    *,
    max_entries: int = DEFAULT_MACHINE_RESOURCE_SCAN_ENTRIES,
    max_depth: int = DEFAULT_MACHINE_RESOURCE_SCAN_DEPTH,
) -> MachineResourceStatusSnapshot:
    """Return a bounded read-only inventory without following links."""

    if max_entries < 1 or max_depth < 0:
        raise ValueError("machine resource scan bounds are invalid")
    return MachineResourceStatusSnapshot(
        tuple(
            _inspect_resource_path(
                resource,
                max_entries=max_entries,
                max_depth=max_depth,
            )
            for resource in layout.resources
        )
    )


def clean_machine_resources(
    layout: MachineResourceLayout,
    request: MachineResourceCleanRequest,
    *,
    now: Callable[[], float] = time.time,
) -> MachineResourceCleanResult:
    """Preview or apply only cleanup operations with explicit ownership proofs."""

    reports: list[MachineResourceCleanReport] = []
    for target in request.targets:
        if target == "runtime":
            reports.append(_clean_runtime(layout, apply=request.apply, now=now))
        elif target == "diagnostics":
            reports.append(_clean_diagnostics(layout, apply=request.apply, now=now))
        else:
            reports.append(_clean_orphan_session_assets(layout, apply=request.apply))
    return MachineResourceCleanResult(request.apply, tuple(reports))


def plan_machine_resource_migration(
    layout: MachineResourceLayout,
) -> MachineResourceMigrationPlan:
    """Plan safe compatibility-session copies into the canonical global root."""

    candidates: list[MachineResourceMigrationCandidate] = []
    diagnostics: list[MachineResourceMigrationDiagnostic] = []
    claimed_destinations: dict[Path, Path] = {}
    for source_root in layout.compatibility_session_dirs:
        try:
            sources, truncated = _compatibility_session_sources(source_root)
        except (OSError, ValueError) as error:
            diagnostics.append(
                MachineResourceMigrationDiagnostic(
                    source_root,
                    "source_rejected",
                    str(error) or error.__class__.__name__,
                )
            )
            continue
        if truncated:
            diagnostics.append(
                MachineResourceMigrationDiagnostic(
                    source_root,
                    "scan_truncated",
                    "compatibility directory exceeds the bounded scan limit",
                )
            )
            continue
        for source in sources:
            try:
                metadata = source.lstat()
                if not stat.S_ISREG(metadata.st_mode) or _is_reparse_point(metadata):
                    raise ValueError("source is not a safe regular file")
                if not _owned_by_current_user(metadata):
                    raise PermissionError("migration source is not owned by this user")
                if (
                    metadata.st_size
                    > DEFAULT_MACHINE_RESOURCE_MIGRATION_TRANSCRIPT_BYTES
                ):
                    raise ValueError("migration transcript exceeds its size limit")
                content = _read_stable_regular_file(source, metadata)
                header, records = decode_agent_transcript_bytes(
                    content,
                    source_path=source,
                )
                references = collect_agent_transcript_session_blobs(
                    records,
                    expected_session_id=header.conversation_id,
                )
                _require_migration_blob_budget(references)
                destination = layout.sessions / _migration_filename(
                    header.created_at,
                    header.conversation_id,
                )
                if destination.exists():
                    if _same_file_content(destination, content):
                        diagnostics.append(
                            MachineResourceMigrationDiagnostic(
                                source,
                                "already_present",
                                "canonical transcript already has identical bytes",
                            )
                        )
                    else:
                        diagnostics.append(
                            MachineResourceMigrationDiagnostic(
                                source,
                                "destination_conflict",
                                f"canonical destination already exists: {destination}",
                            )
                        )
                    continue
                prior = claimed_destinations.setdefault(destination, source)
                if prior != source:
                    diagnostics.append(
                        MachineResourceMigrationDiagnostic(
                            source,
                            "duplicate_identity",
                            f"another source already claims this conversation: {prior}",
                        )
                    )
                    continue
                candidates.append(
                    MachineResourceMigrationCandidate(
                        source=source.resolve(strict=False),
                        destination=destination.resolve(strict=False),
                        conversation_id=header.conversation_id,
                        source_sha256=hashlib.sha256(content).hexdigest(),
                        source_size=len(content),
                        blob_count=len(references),
                    )
                )
            except Exception as error:
                diagnostics.append(
                    MachineResourceMigrationDiagnostic(
                        source,
                        "source_rejected",
                        str(error) or error.__class__.__name__,
                    )
                )
    return MachineResourceMigrationPlan(tuple(candidates), tuple(diagnostics))


async def migrate_machine_resources(
    layout: MachineResourceLayout,
    plan: MachineResourceMigrationPlan,
) -> tuple[MachineResourceMigrationResult, ...]:
    """Apply a migration plan transactionally while retaining every source."""

    results: list[MachineResourceMigrationResult] = []
    for candidate in plan.candidates:
        publication = None
        committed = False
        try:
            _require_migration_candidate_scope(layout, candidate)
            source_metadata = candidate.source.lstat()
            source_content = _read_stable_regular_file(
                candidate.source,
                source_metadata,
            )
            if (
                len(source_content) != candidate.source_size
                or hashlib.sha256(source_content).hexdigest() != candidate.source_sha256
            ):
                raise ValueError("migration source changed after planning")
            header, records = decode_agent_transcript_bytes(
                source_content,
                source_path=candidate.source,
            )
            if header.conversation_id != candidate.conversation_id:
                raise ValueError("migration source identity changed after planning")
            expected_destination = (
                layout.sessions
                / _migration_filename(header.created_at, header.conversation_id)
            ).resolve(strict=False)
            if candidate.destination != expected_destination:
                raise ValueError(
                    "migration destination is outside its canonical authority"
                )
            references = collect_agent_transcript_session_blobs(
                records,
                expected_session_id=header.conversation_id,
            )
            if len(references) != candidate.blob_count:
                raise ValueError("migration blob inventory changed after planning")
            _require_migration_blob_budget(references)
            if candidate.destination.exists():
                disposition: MachineResourceMigrationDisposition = (
                    "already_present"
                    if _same_file_content(candidate.destination, source_content)
                    else "failed"
                )
                results.append(
                    MachineResourceMigrationResult(
                        candidate,
                        disposition,
                        None
                        if disposition == "already_present"
                        else "canonical destination appeared with different content",
                    )
                )
                continue
            prepared_records, publication = (
                clone_agent_transcript_session_blobs(
                    records,
                    source_session_dir=candidate.source.parent,
                    source_session_id=header.conversation_id,
                    target_session_dir=layout.sessions,
                    target_session_id=header.conversation_id,
                )
                if candidate.blob_count
                else (tuple(records), None)
            )
            file_layout = AgentTranscriptFileLayout(layout.sessions)
            key = ConversationKey(
                namespace=file_layout.namespace,
                conversation_id=header.conversation_id,
            )
            file_layout.bind_create_path(key, candidate.destination)
            store = create_agent_transcript_file_store(file_layout)
            create_task = asyncio.create_task(
                store.create(
                    key,
                    header,
                    prepared_records,
                    operation_id=(
                        "machine-resource-migrate:"
                        + hashlib.sha256(
                            f"{candidate.source}\0{candidate.source_sha256}".encode()
                        ).hexdigest()
                    ),
                )
            )
            try:
                await asyncio.shield(create_task)
                committed = True
            except asyncio.CancelledError as cancellation:
                try:
                    await create_task
                except StoreCommitOutcomeUnknown:
                    committed = _migration_target_matches(
                        candidate.destination,
                        header,
                        prepared_records,
                    )
                except BaseException as create_error:
                    cancellation.add_note(
                        "migration create failed while cancellation was coordinated: "
                        f"{create_error.__class__.__name__}: {create_error}"
                    )
                else:
                    committed = True
                raise
            except StoreCommitOutcomeUnknown:
                committed = _migration_target_matches(
                    candidate.destination,
                    header,
                    prepared_records,
                )
                if not committed:
                    raise
            if committed:
                publication = None
        except BaseException as error:
            if publication is not None and not committed:
                try:
                    publication.rollback()
                except BaseException as cleanup_error:
                    error.add_note(
                        "Session blob rollback also failed: "
                        f"{cleanup_error.__class__.__name__}: {cleanup_error}"
                    )
            if not isinstance(error, Exception):
                raise
            results.append(
                MachineResourceMigrationResult(
                    candidate,
                    "failed",
                    str(error) or error.__class__.__name__,
                )
            )
        else:
            results.append(MachineResourceMigrationResult(candidate, "migrated"))
    return tuple(results)


def _inspect_resource_path(
    resource: MachineResourcePath,
    *,
    max_entries: int,
    max_depth: int,
) -> MachineResourceStatus:
    try:
        root_metadata = resource.path.lstat()
    except FileNotFoundError:
        return MachineResourceStatus(resource, "missing")
    except OSError as error:
        return MachineResourceStatus(resource, "partial", errors=(str(error),))
    if _is_reparse_point(root_metadata):
        return MachineResourceStatus(
            resource,
            "unsafe",
            errors=("resource root is a symbolic link or reparse point",),
        )
    if stat.S_ISREG(root_metadata.st_mode):
        return MachineResourceStatus(
            resource, "available", files=1, bytes=root_metadata.st_size
        )
    if not stat.S_ISDIR(root_metadata.st_mode):
        return MachineResourceStatus(
            resource,
            "unsafe",
            errors=("resource root is not a regular file or directory",),
        )
    files = 0
    directories = 1
    total_bytes = 0
    inspected = 0
    errors: list[str] = []
    truncated = False
    pending: list[tuple[Path, int]] = [(resource.path, 0)]
    while pending:
        directory, depth = pending.pop()
        if depth >= max_depth:
            truncated = True
            continue
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if inspected >= max_entries:
                        truncated = True
                        pending.clear()
                        break
                    inspected += 1
                    try:
                        metadata = entry.stat(follow_symlinks=False)
                    except OSError as error:
                        errors.append(f"{entry.path}: {error}")
                        continue
                    if _is_reparse_point(metadata):
                        continue
                    if stat.S_ISDIR(metadata.st_mode):
                        directories += 1
                        pending.append((Path(entry.path), depth + 1))
                    elif stat.S_ISREG(metadata.st_mode):
                        files += 1
                        total_bytes += metadata.st_size
        except OSError as error:
            errors.append(f"{directory}: {error}")
            continue
    return MachineResourceStatus(
        resource,
        "partial" if errors or truncated else "available",
        files=files,
        directories=directories,
        bytes=total_bytes,
        truncated=truncated,
        errors=tuple(errors[:20]),
    )


def _authority_path(path: Path) -> Path:
    """Resolve an authority's parent without hiding a link at the authority."""

    expanded = path.expanduser()
    return expanded.parent.resolve(strict=False) / expanded.name


def _clean_runtime(
    layout: MachineResourceLayout,
    *,
    apply: bool,
    now: Callable[[], float],
) -> MachineResourceCleanReport:
    if not apply:
        status = _status_for(layout, "runtime.runs")
        return MachineResourceCleanReport(
            "runtime",
            candidates=max(0, status.directories - 1),
            detail="preview is conservative; apply rechecks every RunLease and preserves active runs",
        )
    report = sweep_runtime_runs(
        RuntimeScope(layout.platform_paths, uuid4().hex),
        policy=RuntimeSweepPolicy(
            stale_after_seconds=0,
            max_inactive_runs=0,
            max_inactive_bytes=0,
            max_scan_entries=DEFAULT_MACHINE_RESOURCE_SCAN_ENTRIES,
        ),
        now=now,
    )
    return MachineResourceCleanReport(
        "runtime",
        candidates=max(
            0, report.inspected - report.active - report.skipped - report.failed
        ),
        removed=report.removed,
        removed_bytes=report.removed_bytes,
        active=report.active,
        skipped=report.skipped,
        failed=report.failed,
    )


def _clean_diagnostics(
    layout: MachineResourceLayout,
    *,
    apply: bool,
    now: Callable[[], float],
) -> MachineResourceCleanReport:
    directory = layout.platform_paths.state / "diagnostics"
    candidates, candidate_bytes, skipped, complete = _managed_file_candidates(
        directory,
        prefix=_DIAGNOSTIC_PREFIX,
        suffix=_DIAGNOSTIC_SUFFIX,
    )
    if not apply:
        return MachineResourceCleanReport(
            "diagnostics",
            candidates=candidates,
            removed_bytes=0,
            skipped=skipped,
            failed=0 if complete else 1,
            detail=(
                f"preview would remove {candidate_bytes} bytes"
                if complete
                else "diagnostic scan exceeded its bound; cleanup would be refused"
            ),
        )
    report = sweep_managed_artifacts(
        directory,
        name_prefix=_DIAGNOSTIC_PREFIX,
        suffix=_DIAGNOSTIC_SUFFIX,
        policy=ArtifactRetentionPolicy(
            max_files=0,
            max_total_bytes=0,
            max_age_seconds=0,
            max_scan_entries=DEFAULT_MACHINE_RESOURCE_SCAN_ENTRIES,
        ),
        now=now,
    )
    return MachineResourceCleanReport(
        "diagnostics",
        candidates=candidates,
        removed=report.removed,
        removed_bytes=report.removed_bytes,
        skipped=report.skipped,
        failed=report.failed,
    )


def _clean_orphan_session_assets(
    layout: MachineResourceLayout,
    *,
    apply: bool,
) -> MachineResourceCleanReport:
    owners, authority_scan_complete = _known_session_authorities(layout)
    if not authority_scan_complete:
        return MachineResourceCleanReport(
            "orphan_session_assets",
            failed=1,
            detail="transcript authority scan was incomplete; cleanup refused",
        )
    candidates: list[tuple[SessionBlobStore, tuple[int, int]]] = []
    skipped = failed = 0
    root = layout.session_assets
    try:
        root_metadata = root.lstat()
    except FileNotFoundError:
        return MachineResourceCleanReport("orphan_session_assets")
    except OSError:
        return MachineResourceCleanReport("orphan_session_assets", failed=1)
    if (
        not stat.S_ISDIR(root_metadata.st_mode)
        or _is_reparse_point(root_metadata)
        or not _owned_by_current_user(root_metadata)
    ):
        return MachineResourceCleanReport(
            "orphan_session_assets",
            failed=1,
            detail="session asset root is not a safe owned directory",
        )
    truncated = False
    try:
        with os.scandir(root) as entries:
            for index, entry in enumerate(entries):
                if index >= DEFAULT_MACHINE_RESOURCE_SCAN_ENTRIES:
                    truncated = True
                    break
                if entry.name.startswith("."):
                    skipped += 1
                    continue
                try:
                    metadata = Path(entry.path).lstat()
                    require_portable_artifact_id(
                        entry.name,
                        name="session asset authority",
                    )
                    if (
                        entry.name in owners
                        or not _has_canonical_deletion_tombstone(layout, entry.name)
                        or not stat.S_ISDIR(metadata.st_mode)
                        or _is_reparse_point(metadata)
                        or not _owned_by_current_user(metadata)
                    ):
                        skipped += 1
                        continue
                    candidates.append(
                        (
                            SessionBlobStore(
                                resolve_session_blob_data_root(layout.sessions),
                                entry.name,
                            ),
                            (metadata.st_dev, metadata.st_ino),
                        )
                    )
                except (OSError, ValueError):
                    failed += 1
    except OSError:
        failed += 1
    if truncated:
        return MachineResourceCleanReport(
            "orphan_session_assets",
            skipped=skipped,
            failed=failed + 1,
            detail="session asset scan exceeded its bound; cleanup refused",
        )
    candidate_bytes = sum(store.total_bytes for store, _identity in candidates)
    if not apply:
        return MachineResourceCleanReport(
            "orphan_session_assets",
            candidates=len(candidates),
            skipped=skipped,
            failed=failed,
            detail=f"preview would remove {candidate_bytes} bytes",
        )
    removed = removed_bytes = 0
    for store, expected_identity in candidates:
        size = store.total_bytes
        try:
            current_owners, complete = _known_session_authorities(layout)
            if (
                not complete
                or store.session_id in current_owners
                or not _has_canonical_deletion_tombstone(layout, store.session_id)
            ):
                skipped += 1
                continue
            if store.delete(expected_root_identity=expected_identity):
                removed += 1
                removed_bytes += size
        except (OSError, ValueError):
            failed += 1
    return MachineResourceCleanReport(
        "orphan_session_assets",
        candidates=len(candidates),
        removed=removed,
        removed_bytes=removed_bytes,
        skipped=skipped,
        failed=failed,
    )


def _known_session_authorities(
    layout: MachineResourceLayout,
) -> tuple[set[str], bool]:
    result: set[str] = set()
    roots = (layout.sessions, *layout.compatibility_session_dirs)
    for root in roots:
        try:
            root_metadata = root.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            return result, False
        if (
            not stat.S_ISDIR(root_metadata.st_mode)
            or _is_reparse_point(root_metadata)
            or not _owned_by_current_user(root_metadata)
        ):
            return result, False
        try:
            with os.scandir(root) as entries:
                for index, entry in enumerate(entries):
                    if index >= DEFAULT_MACHINE_RESOURCE_SCAN_ENTRIES:
                        return result, False
                    if not entry.name.endswith(_SESSION_SUFFIX):
                        continue
                    metadata = entry.stat(follow_symlinks=False)
                    if (
                        not stat.S_ISREG(metadata.st_mode)
                        or _is_reparse_point(metadata)
                        or not _owned_by_current_user(metadata)
                    ):
                        return result, False
                    header = load_agent_transcript_header(Path(entry.path))
                    result.add(session_blob_authority_id(header.conversation_id))
        except Exception:
            return result, False
    return result, True


def _has_canonical_deletion_tombstone(
    layout: MachineResourceLayout,
    authority_id: str,
) -> bool:
    """Require a valid positive deletion receipt before reclaiming assets."""

    try:
        require_portable_artifact_id(authority_id, name="session asset authority")
        file_layout = AgentTranscriptFileLayout(layout.sessions)
        tombstone = file_layout.tombstone_path(file_layout.key(authority_id))
        parent_metadata = tombstone.parent.lstat()
        metadata = tombstone.lstat()
        if (
            not stat.S_ISDIR(parent_metadata.st_mode)
            or _is_reparse_point(parent_metadata)
            or not _owned_by_current_user(parent_metadata)
            or not stat.S_ISREG(metadata.st_mode)
            or _is_reparse_point(metadata)
            or not _owned_by_current_user(metadata)
            or metadata.st_size > 16 * 1024
        ):
            return False
        receipt = load_conversation_deletion_receipt(tombstone)
    except (OSError, StoreDataError, UnicodeError, ValueError):
        return False
    return receipt is not None


def _status_for(
    layout: MachineResourceLayout, resource_id: str
) -> MachineResourceStatus:
    resource = next(
        resource for resource in layout.resources if resource.resource_id == resource_id
    )
    return _inspect_resource_path(
        resource,
        max_entries=DEFAULT_MACHINE_RESOURCE_SCAN_ENTRIES,
        max_depth=2,
    )


def _managed_file_candidates(
    directory: Path,
    *,
    prefix: str,
    suffix: str,
) -> tuple[int, int, int, bool]:
    count = total = skipped = 0
    try:
        metadata = directory.lstat()
    except FileNotFoundError:
        return 0, 0, 0, True
    except OSError:
        return 0, 0, 1, False
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or _is_reparse_point(metadata)
        or not _owned_by_current_user(metadata)
    ):
        return 0, 0, 1, False
    try:
        with os.scandir(directory) as entries:
            for index, entry in enumerate(entries):
                if index >= DEFAULT_MACHINE_RESOURCE_SCAN_ENTRIES:
                    return count, total, skipped, False
                try:
                    metadata = entry.stat(follow_symlinks=False)
                except OSError:
                    skipped += 1
                    continue
                if (
                    entry.name.startswith(prefix)
                    and entry.name.endswith(suffix)
                    and stat.S_ISREG(metadata.st_mode)
                    and not _is_reparse_point(metadata)
                    and _owned_by_current_user(metadata)
                ):
                    count += 1
                    total += metadata.st_size
                else:
                    skipped += 1
    except OSError:
        return count, total, skipped + 1, False
    return count, total, skipped, True


def _migration_filename(created_at: str, conversation_id: str) -> str:
    timestamp = re.sub(r"[^A-Za-z0-9._-]", "-", created_at)[:64].strip(".-")
    if not timestamp:
        timestamp = "imported"
    return f"{timestamp}_{session_blob_authority_id(conversation_id)}.jsonl"


def _compatibility_session_sources(root: Path) -> tuple[tuple[Path, ...], bool]:
    try:
        metadata = root.lstat()
    except FileNotFoundError:
        return (), False
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or _is_reparse_point(metadata)
        or not _owned_by_current_user(metadata)
    ):
        raise ValueError("compatibility session root is not a safe owned directory")
    selected: list[Path] = []
    truncated = False
    with os.scandir(root) as entries:
        for index, entry in enumerate(entries):
            if index >= DEFAULT_MACHINE_RESOURCE_SCAN_ENTRIES:
                truncated = True
                break
            if entry.name.endswith(_SESSION_SUFFIX):
                selected.append(Path(entry.path))
    return tuple(sorted(selected)), truncated


def _require_migration_candidate_scope(
    layout: MachineResourceLayout,
    candidate: MachineResourceMigrationCandidate,
) -> None:
    if not isinstance(candidate.source, Path) or not isinstance(
        candidate.destination,
        Path,
    ):
        raise TypeError("migration candidate paths must be Path values")
    source = candidate.source.resolve(strict=False)
    destination = candidate.destination.resolve(strict=False)
    if (
        source != candidate.source
        or source.suffix != _SESSION_SUFFIX
        or source.parent not in layout.compatibility_session_dirs
    ):
        raise ValueError("migration source is outside compatibility authority")
    if destination != candidate.destination or destination.parent != layout.sessions:
        raise ValueError("migration destination is outside canonical authority")
    if (
        not isinstance(candidate.source_sha256, str)
        or _SHA256.fullmatch(candidate.source_sha256) is None
    ):
        raise ValueError("migration source digest is invalid")
    if (
        isinstance(candidate.source_size, bool)
        or not isinstance(candidate.source_size, int)
        or candidate.source_size < 0
        or candidate.source_size > DEFAULT_MACHINE_RESOURCE_MIGRATION_TRANSCRIPT_BYTES
    ):
        raise ValueError("migration source size is invalid")
    if (
        isinstance(candidate.blob_count, bool)
        or not isinstance(candidate.blob_count, int)
        or candidate.blob_count < 0
    ):
        raise ValueError("migration blob count is invalid")


def _require_migration_blob_budget(references: Sequence[object]) -> None:
    total = 0
    for reference in references:
        size = getattr(reference, "size_bytes", None)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise ValueError("migration blob size is invalid")
        if size > DEFAULT_MACHINE_RESOURCE_MIGRATION_BLOB_BYTES:
            raise ValueError("migration blob exceeds its per-blob size limit")
        total += size
        if total > DEFAULT_MACHINE_RESOURCE_MIGRATION_BLOB_BYTES:
            raise ValueError("migration blobs exceed their aggregate size limit")


def _migration_target_matches(
    path: Path,
    expected_header: object,
    expected_records: Sequence[object],
) -> bool:
    try:
        metadata = path.lstat()
        content = _read_stable_regular_file(path, metadata)
        header, records = decode_agent_transcript_bytes(content, source_path=path)
    except (OSError, ValueError):
        return False
    return header == expected_header and tuple(records) == tuple(expected_records)


def _read_stable_regular_file(path: Path, metadata: os.stat_result) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or _is_reparse_point(metadata)
            or not _owned_by_current_user(before)
            or not os.path.samestat(metadata, before)
        ):
            raise ValueError("migration source identity changed")
        if before.st_size > DEFAULT_MACHINE_RESOURCE_MIGRATION_TRANSCRIPT_BYTES:
            raise ValueError("migration transcript exceeds its size limit")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            if (
                sum(len(item) for item in chunks)
                > DEFAULT_MACHINE_RESOURCE_MIGRATION_TRANSCRIPT_BYTES
            ):
                raise ValueError("migration transcript exceeds its size limit")
        after = os.fstat(descriptor)
        if (
            (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
        ):
            raise ValueError("migration source changed while being read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _same_file_content(path: Path, expected: bytes) -> bool:
    try:
        metadata = path.lstat()
        return _read_stable_regular_file(path, metadata) == expected
    except (OSError, ValueError):
        return False


def _is_reparse_point(metadata: os.stat_result) -> bool:
    return stat.S_ISLNK(metadata.st_mode) or bool(
        getattr(metadata, "st_file_attributes", 0)
        & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _owned_by_current_user(metadata: os.stat_result) -> bool:
    getuid = getattr(os, "getuid", None)
    return not callable(getuid) or metadata.st_uid == getuid()


__all__ = [
    "DEFAULT_MACHINE_RESOURCE_SCAN_DEPTH",
    "DEFAULT_MACHINE_RESOURCE_SCAN_ENTRIES",
    "DEFAULT_MACHINE_RESOURCE_MIGRATION_BLOB_BYTES",
    "DEFAULT_MACHINE_RESOURCE_MIGRATION_TRANSCRIPT_BYTES",
    "MACHINE_RESOURCE_SCHEMA_VERSION",
    "MachineResourceCleanReport",
    "MachineResourceCleanRequest",
    "MachineResourceCleanResult",
    "MachineResourceCleanTarget",
    "MachineResourceLayout",
    "MachineResourceLifetime",
    "MachineResourceMigrationCandidate",
    "MachineResourceMigrationDiagnostic",
    "MachineResourceMigrationDiagnosticCode",
    "MachineResourceMigrationDisposition",
    "MachineResourceMigrationPlan",
    "MachineResourceMigrationResult",
    "MachineResourceMode",
    "MachineResourcePath",
    "MachineResourceState",
    "MachineResourceStatus",
    "MachineResourceStatusSnapshot",
    "clean_machine_resources",
    "inspect_machine_resources",
    "migrate_machine_resources",
    "plan_machine_resource_migration",
    "resolve_machine_resource_layout",
]
