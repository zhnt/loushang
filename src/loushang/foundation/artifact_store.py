"""Bounded immutable artifacts owned by one machine-local runtime scope."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import time
from collections.abc import Callable, Iterable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from threading import RLock
from typing import Literal, TypeAlias
from uuid import uuid4

from .runtime_scope import RuntimeScope

ArtifactDisclosure: TypeAlias = Literal["private", "redact", "shareable"]


class ArtifactStoreError(Exception):
    """Base class for typed artifact storage failures."""


class ArtifactStoreQuotaExceeded(ArtifactStoreError, ValueError):
    """Raised before a write would exceed a configured store bound."""


class ArtifactSourceRejected(ArtifactStoreError, ValueError):
    """Raised when a snapshot source cannot be proven safe and stable."""


@dataclass(frozen=True, slots=True)
class ArtifactStorePolicy:
    """Hard bounds for artifacts retained by one live run."""

    max_artifacts: int = 64
    max_artifact_bytes: int = 64 * 1024 * 1024
    max_total_bytes: int = 256 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.max_artifacts < 1:
            raise ValueError("max_artifacts must be positive")
        if self.max_artifact_bytes < 1:
            raise ValueError("max_artifact_bytes must be positive")
        if self.max_total_bytes < self.max_artifact_bytes:
            raise ValueError(
                "max_total_bytes must be at least max_artifact_bytes"
            )


DEFAULT_ARTIFACT_STORE_POLICY = ArtifactStorePolicy()


@dataclass(frozen=True, slots=True)
class StoredArtifact:
    """Immutable artifact metadata plus its run-private physical location."""

    artifact_id: str
    logical_name: str
    kind: str
    media_type: str
    disclosure: ArtifactDisclosure
    size_bytes: int
    sha256: str
    created_at: float
    path: Path = field(compare=False, repr=False)
    source: str | None = None
    _identity: tuple[int, int] = field(compare=False, repr=False, default=(0, 0))

    def manifest_entry(self) -> dict[str, object]:
        """Return portable provenance without leaking a machine-local path."""

        return {
            "artifactId": self.artifact_id,
            "logicalName": self.logical_name,
            "kind": self.kind,
            "mediaType": self.media_type,
            "disclosure": self.disclosure,
            "sizeBytes": self.size_bytes,
            "sha256": self.sha256,
            "createdAt": self.created_at,
            "source": self.source,
        }


class ArtifactStore:
    """Write immutable, quota-bounded artifacts below one ``RuntimeScope``.

    The store owns only files it creates. The surrounding ``RunLease`` owns
    the shared run tree and its final cleanup.
    """

    def __init__(
        self,
        scope: RuntimeScope,
        *,
        policy: ArtifactStorePolicy = DEFAULT_ARTIFACT_STORE_POLICY,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.scope = scope
        self.policy = policy
        self._now = now
        self._records: list[StoredArtifact] = []
        self._lock = RLock()
        self._initialized = False

    @property
    def root(self) -> Path:
        return self.scope.artifacts

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @property
    def records(self) -> tuple[StoredArtifact, ...]:
        with self._lock:
            return tuple(self._records)

    @property
    def total_bytes(self) -> int:
        with self._lock:
            return sum(record.size_bytes for record in self._records)

    def put_bytes(
        self,
        content: bytes,
        *,
        logical_name: str,
        kind: str,
        media_type: str,
        disclosure: ArtifactDisclosure = "private",
        source: str | None = None,
    ) -> StoredArtifact:
        """Persist one immutable artifact and atomically refresh its manifest."""

        payload = bytes(content)
        normalized_name = _safe_logical_name(logical_name)
        normalized_kind = _safe_token(kind, name="artifact kind")
        normalized_media_type = _safe_media_type(media_type)
        normalized_source = _safe_optional_label(source, name="artifact source")
        created_at = _finite_timestamp(self._now())
        if disclosure not in {"private", "redact", "shareable"}:
            raise ValueError(f"unsupported artifact disclosure: {disclosure!r}")

        with self._lock:
            self._check_capacity(len(payload))
            _validate_private_directory(self.scope.run_dir)
            _prepare_private_directory(self.root)
            objects = self.root / "objects"
            _prepare_private_directory(objects)
            artifact_id = uuid4().hex
            object_path = objects / artifact_id
            identity = _write_new_private_file(object_path, payload)
            record = StoredArtifact(
                artifact_id=artifact_id,
                logical_name=normalized_name,
                kind=normalized_kind,
                media_type=normalized_media_type,
                disclosure=disclosure,
                size_bytes=len(payload),
                sha256=hashlib.sha256(payload).hexdigest(),
                created_at=created_at,
                path=object_path,
                source=normalized_source,
                _identity=identity,
            )
            try:
                self._write_manifest((*self._records, record))
            except BaseException:
                _unlink_owned_file(object_path, identity)
                raise
            self._initialized = True
            self._records.append(record)
            return record

    def snapshot_file(
        self,
        source_path: str | Path,
        *,
        logical_name: str,
        kind: str,
        media_type: str,
        disclosure: ArtifactDisclosure = "private",
        source: str | None = None,
        allowed_roots: Sequence[str | Path],
    ) -> StoredArtifact:
        """Capture one stable regular file after explicit root authorization."""

        source_file = Path(source_path).expanduser()
        roots = tuple(allowed_roots)
        if not roots:
            raise ArtifactSourceRejected(
                "artifact snapshot requires at least one explicit allowed root"
            )
        with self._lock:
            if len(self._records) >= self.policy.max_artifacts:
                raise ArtifactStoreQuotaExceeded(
                    f"artifact count limit is {self.policy.max_artifacts}"
                )
            available = self.policy.max_total_bytes - sum(
                record.size_bytes for record in self._records
            )
            if available <= 0:
                raise ArtifactStoreQuotaExceeded(
                    f"artifact byte limit is {self.policy.max_total_bytes} bytes"
                )
            payload = _read_stable_source(
                source_file,
                allowed_roots=roots,
                max_bytes=min(self.policy.max_artifact_bytes, available),
            )
            return self.put_bytes(
                payload,
                logical_name=logical_name,
                kind=kind,
                media_type=media_type,
                disclosure=disclosure,
                source=source,
            )

    def read_bytes(self, artifact: StoredArtifact) -> bytes:
        """Read back a record owned by this store and verify its digest."""

        with self._lock:
            if not any(record is artifact for record in self._records):
                raise ArtifactSourceRejected("artifact is not owned by this store")
            payload = _read_owned_artifact(artifact)
            if hashlib.sha256(payload).hexdigest() != artifact.sha256:
                raise ArtifactSourceRejected("artifact digest no longer matches")
            return payload

    def _check_capacity(self, next_bytes: int) -> None:
        if next_bytes > self.policy.max_artifact_bytes:
            raise ArtifactStoreQuotaExceeded(
                f"artifact is {next_bytes} bytes; per-artifact limit is "
                f"{self.policy.max_artifact_bytes} bytes"
            )
        if len(self._records) >= self.policy.max_artifacts:
            raise ArtifactStoreQuotaExceeded(
                f"artifact count limit is {self.policy.max_artifacts}"
            )
        retained_bytes = sum(record.size_bytes for record in self._records)
        if retained_bytes + next_bytes > self.policy.max_total_bytes:
            raise ArtifactStoreQuotaExceeded(
                f"artifact byte limit is {self.policy.max_total_bytes} bytes"
            )

    def _write_manifest(self, records: Iterable[StoredArtifact]) -> None:
        manifest = {
            "schemaVersion": 1,
            "runId": self.scope.run_id,
            "artifacts": [record.manifest_entry() for record in records],
        }
        payload = (
            json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        temporary = self.root / f".manifest-{uuid4().hex}.tmp"
        identity: tuple[int, int] | None = None
        try:
            identity = _write_new_private_file(temporary, payload)
            if self._initialized:
                os.replace(temporary, self.manifest_path)
            else:
                try:
                    _publish_file_exclusive(temporary, self.manifest_path)
                except FileExistsError as error:
                    raise ArtifactStoreError(
                        "artifact store is already initialized for this run"
                    ) from error
            _sync_directory(self.root)
        finally:
            if identity is not None:
                with suppress(FileNotFoundError):
                    _unlink_owned_file(temporary, identity)


@dataclass(frozen=True, slots=True)
class ArtifactRetentionPolicy:
    """Bounds for product-managed durable artifact exports."""

    max_files: int = 20
    max_total_bytes: int = 512 * 1024 * 1024
    max_age_seconds: float | None = 30 * 24 * 60 * 60

    def __post_init__(self) -> None:
        if self.max_files < 0:
            raise ValueError("max_files must not be negative")
        if self.max_total_bytes < 0:
            raise ValueError("max_total_bytes must not be negative")
        if self.max_age_seconds is not None and self.max_age_seconds < 0:
            raise ValueError("max_age_seconds must not be negative")


DEFAULT_ARTIFACT_RETENTION_POLICY = ArtifactRetentionPolicy()


@dataclass(frozen=True, slots=True)
class ArtifactRetentionReport:
    inspected: int = 0
    removed: int = 0
    removed_bytes: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass(frozen=True, slots=True)
class _RetentionCandidate:
    path: Path
    size: int
    modified_at: float
    identity: tuple[int, int]


def sweep_managed_artifacts(
    directory: str | Path,
    *,
    name_prefix: str,
    suffix: str,
    policy: ArtifactRetentionPolicy = DEFAULT_ARTIFACT_RETENTION_POLICY,
    preserve: Iterable[str | Path] = (),
    now: Callable[[], float] = time.time,
) -> ArtifactRetentionReport:
    """Best-effort retention for a private, explicitly managed export family."""

    if not _safe_name_fragment(name_prefix) or not _safe_name_fragment(suffix):
        raise ValueError("managed artifact prefix and suffix must be non-empty names")
    root = Path(directory)
    try:
        _validate_private_directory(root)
    except FileNotFoundError:
        return ArtifactRetentionReport()
    except OSError:
        return ArtifactRetentionReport(failed=1)
    preserved = {Path(path).resolve(strict=False) for path in preserve}
    candidates: list[_RetentionCandidate] = []
    skipped = failed = 0
    try:
        with os.scandir(root) as entries:
            snapshots = tuple(entries)
    except OSError:
        return ArtifactRetentionReport(failed=1)
    for entry in snapshots:
        if not entry.name.startswith(name_prefix) or not entry.name.endswith(suffix):
            skipped += 1
            continue
        try:
            metadata = entry.stat(follow_symlinks=False)
        except OSError:
            failed += 1
            continue
        if (
            not stat.S_ISREG(metadata.st_mode)
            or _is_reparse_point(metadata)
            or not _owned_by_current_user(metadata)
        ):
            skipped += 1
            continue
        candidates.append(
            _RetentionCandidate(
                path=Path(entry.path),
                size=metadata.st_size,
                modified_at=metadata.st_mtime,
                identity=(metadata.st_dev, metadata.st_ino),
            )
        )

    current_time = now()
    selected: set[Path] = {
        candidate.path
        for candidate in candidates
        if candidate.path.resolve(strict=False) not in preserved
        and policy.max_age_seconds is not None
        and current_time - candidate.modified_at >= policy.max_age_seconds
    }
    retained = [candidate for candidate in candidates if candidate.path not in selected]
    retained_count = len(retained)
    retained_bytes = sum(candidate.size for candidate in retained)
    for candidate in sorted(
        retained,
        key=lambda item: (item.modified_at, item.path.name),
    ):
        if (
            retained_count <= policy.max_files
            and retained_bytes <= policy.max_total_bytes
        ):
            break
        if candidate.path.resolve(strict=False) in preserved:
            continue
        selected.add(candidate.path)
        retained_count -= 1
        retained_bytes -= candidate.size

    removed = removed_bytes = 0
    for candidate in candidates:
        if candidate.path not in selected:
            continue
        try:
            _unlink_owned_file(candidate.path, candidate.identity)
        except OSError:
            failed += 1
        else:
            removed += 1
            removed_bytes += candidate.size
    return ArtifactRetentionReport(
        inspected=len(candidates),
        removed=removed,
        removed_bytes=removed_bytes,
        skipped=skipped,
        failed=failed,
    )


def _read_stable_source(
    source: Path,
    *,
    allowed_roots: Sequence[str | Path],
    max_bytes: int,
) -> bytes:
    try:
        resolved = source.resolve(strict=True)
        roots = tuple(Path(root).expanduser().resolve(strict=True) for root in allowed_roots)
    except OSError as error:
        raise ArtifactSourceRejected(str(error) or error.__class__.__name__) from error
    if not any(resolved == root or resolved.is_relative_to(root) for root in roots):
        raise ArtifactSourceRejected(f"artifact source is outside allowed roots: {source}")
    flags = os.O_RDONLY
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(resolved, flags)
    except OSError as error:
        raise ArtifactSourceRejected(str(error) or error.__class__.__name__) from error
    try:
        path_metadata = resolved.lstat()
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or _is_reparse_point(path_metadata)
            or not _owned_by_current_user(before)
            or not os.path.samestat(path_metadata, before)
        ):
            raise ArtifactSourceRejected(f"artifact source is not a safe file: {source}")
        if before.st_size > max_bytes:
            raise ArtifactStoreQuotaExceeded(
                f"artifact is {before.st_size} bytes; per-artifact limit is "
                f"{max_bytes} bytes"
            )
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, max_bytes + 1 - total))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise ArtifactStoreQuotaExceeded(
                    f"artifact exceeds per-artifact limit of {max_bytes} bytes"
                )
        after = os.fstat(descriptor)
        if (
            (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            or before.st_size != after.st_size
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
        ):
            raise ArtifactSourceRejected("artifact source changed during snapshot")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_owned_artifact(artifact: StoredArtifact) -> bytes:
    flags = os.O_RDONLY
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(artifact.path, flags)
    except OSError as error:
        raise ArtifactSourceRejected("artifact file identity changed") from error
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or (metadata.st_dev, metadata.st_ino) != artifact._identity
            or metadata.st_size != artifact.size_bytes
        ):
            raise ArtifactSourceRejected("artifact file identity changed")
        payload = bytearray()
        while len(payload) <= artifact.size_bytes:
            chunk = os.read(
                descriptor,
                min(1024 * 1024, artifact.size_bytes + 1 - len(payload)),
            )
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) != artifact.size_bytes:
            raise ArtifactSourceRejected("artifact file size changed")
        return bytes(payload)
    finally:
        os.close(descriptor)


def _prepare_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    _validate_private_directory(path)
    if os.name == "posix":
        path.chmod(0o700)


def _validate_private_directory(path: Path) -> None:
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or _is_reparse_point(metadata):
        raise NotADirectoryError(str(path))
    if not _owned_by_current_user(metadata):
        raise PermissionError(f"artifact directory is not owned by this user: {path}")


def _write_new_private_file(path: Path, content: bytes) -> tuple[int, int]:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags, 0o600)
    metadata = os.fstat(descriptor)
    identity = metadata.st_dev, metadata.st_ino
    try:
        offset = 0
        while offset < len(content):
            written = os.write(descriptor, content[offset:])
            if written <= 0:
                raise OSError("artifact write made no progress")
            offset += written
        os.fsync(descriptor)
        return identity
    except BaseException:
        os.close(descriptor)
        descriptor = -1
        with suppress(OSError):
            _unlink_owned_file(path, identity)
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _unlink_owned_file(path: Path, identity: tuple[int, int]) -> None:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or (
        metadata.st_dev,
        metadata.st_ino,
    ) != identity:
        raise PermissionError(f"artifact file identity changed: {path}")
    path.unlink()


def _publish_file_exclusive(temporary: Path, destination: Path) -> None:
    if os.name == "nt":
        temporary.rename(destination)
        return
    os.link(temporary, destination)


def _sync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return
    try:
        with suppress(OSError):
            os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _safe_logical_name(value: str) -> str:
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
        or len(value) > 240
    ):
        raise ValueError(f"artifact logical name must be a safe relative path: {value!r}")
    return value


_TOKEN = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}")


def _safe_token(value: str, *, name: str) -> str:
    if _TOKEN.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase portable token")
    return value


def _safe_media_type(value: str) -> str:
    if (
        not value
        or len(value) > 128
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("artifact media type must be a non-empty portable value")
    return value


def _safe_optional_label(value: str | None, *, name: str) -> str | None:
    if value is None:
        return None
    if not value or len(value) > 128 or any(ord(character) < 32 for character in value):
        raise ValueError(f"{name} must be a non-empty portable value")
    return value


def _safe_name_fragment(value: str) -> bool:
    return bool(value) and "/" not in value and "\\" not in value and not any(
        ord(character) < 32 for character in value
    )


def _finite_timestamp(value: float) -> float:
    if not math.isfinite(value):
        raise ValueError("artifact timestamp must be finite")
    return value


def _owned_by_current_user(metadata: os.stat_result) -> bool:
    getuid = getattr(os, "getuid", None)
    return os.name != "posix" or not callable(getuid) or metadata.st_uid == getuid()


def _is_reparse_point(metadata: os.stat_result) -> bool:
    return bool(getattr(metadata, "st_reparse_tag", 0))


__all__ = [
    "ArtifactDisclosure",
    "ArtifactRetentionPolicy",
    "ArtifactRetentionReport",
    "ArtifactSourceRejected",
    "ArtifactStore",
    "ArtifactStoreError",
    "ArtifactStorePolicy",
    "ArtifactStoreQuotaExceeded",
    "DEFAULT_ARTIFACT_RETENTION_POLICY",
    "DEFAULT_ARTIFACT_STORE_POLICY",
    "StoredArtifact",
    "sweep_managed_artifacts",
]
