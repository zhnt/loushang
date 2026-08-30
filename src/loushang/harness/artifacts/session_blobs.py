"""Durable, session-owned immutable blob storage."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import time
from collections.abc import Callable, Iterable, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass, replace
from pathlib import Path
from threading import RLock
from typing import Literal, Protocol
from uuid import uuid4

from loushang.harness.journal import journal_file_lock

from .references import SessionBlobRef, session_blob_authority_id
from .store import (
    ArtifactDisclosure,
    ArtifactSourceRejected,
    ArtifactStoreError,
    ArtifactStoreQuotaExceeded,
    _is_reparse_point,
    _owned_by_current_user,
    _prepare_private_directory,
    _publish_file_exclusive,
    _sync_directory,
    _unlink_owned_file,
    _validate_private_directory,
    _write_new_private_file,
)


class SessionBlobError(ArtifactStoreError):
    """Base class for durable session-blob failures."""


class SessionBlobManifestError(SessionBlobError, ValueError):
    """Raised when a durable manifest is malformed or inconsistent."""


@dataclass(frozen=True, slots=True)
class SessionBlobPolicy:
    """Hard bounds applied independently to each durable session."""

    max_blobs: int = 256
    max_blob_bytes: int = 128 * 1024 * 1024
    max_total_bytes: int = 1024 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.max_blobs < 1:
            raise ValueError("max_blobs must be positive")
        if self.max_blob_bytes < 1:
            raise ValueError("max_blob_bytes must be positive")
        if self.max_total_bytes < self.max_blob_bytes:
            raise ValueError("max_total_bytes must be at least max_blob_bytes")


DEFAULT_SESSION_BLOB_POLICY = SessionBlobPolicy()

SessionBlobHealthState = Literal["available", "missing", "corrupt"]


@dataclass(frozen=True, slots=True)
class SessionBlobHealth:
    reference: SessionBlobRef
    state: SessionBlobHealthState
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class SessionBlobPublication:
    """Rollback authority for exactly one unchanged publication."""

    _store: SessionBlobStore
    references: tuple[SessionBlobRef, ...]
    _previous_records: tuple[SessionBlobRef, ...]
    _expected_records: tuple[SessionBlobRef, ...]
    _root_identity: tuple[int, int]
    _root_preexisting: bool

    def rollback(self) -> bool:
        return self._store._rollback_publication(
            self._previous_records,
            self._expected_records,
            self._root_identity,
            self._root_preexisting,
        )


class SessionBlobReader(Protocol):
    def read_bytes(self, blob: SessionBlobRef) -> bytes: ...


class SessionBlobWriter(Protocol):
    def put_bytes(
        self,
        content: bytes,
        *,
        logical_name: str,
        kind: str,
        media_type: str,
        disclosure: ArtifactDisclosure = "private",
        source: str | None = None,
    ) -> SessionBlobRef: ...


class SessionBlobStore(SessionBlobReader, SessionBlobWriter):
    """Own immutable blobs under ``data/session-assets/<session-id>``.

    Public references contain logical identity and integrity metadata only.
    This store is the sole authority that maps them to physical object paths.
    """

    def __init__(
        self,
        data_root: str | Path,
        session_id: str,
        *,
        policy: SessionBlobPolicy = DEFAULT_SESSION_BLOB_POLICY,
        now: Callable[[], float] = time.time,
    ) -> None:
        # Logical conversation ids historically allowed non-portable text.  The
        # store exposes and persists only their safe physical authority key.
        session_id = session_blob_authority_id(session_id)
        self.data_root = Path(data_root).expanduser().resolve(strict=False)
        self.session_id = session_id
        self.policy = policy
        self._now = now
        self._lock = RLock()
        self._records: list[SessionBlobRef] = []
        self._initialized = False
        with self._authority_lock("shared"):
            self._load_manifest_if_present()

    @property
    def assets_root(self) -> Path:
        return self.data_root / "session-assets"

    @property
    def root(self) -> Path:
        return self.assets_root / self.session_id

    @property
    def objects_root(self) -> Path:
        return self.root / "objects"

    @property
    def manifest_path(self) -> Path:
        return self.root / "manifest.json"

    @property
    def records(self) -> tuple[SessionBlobRef, ...]:
        with self._lock:
            return tuple(self._records)

    @property
    def total_bytes(self) -> int:
        with self._lock:
            return sum(
                record.size_bytes for record in _unique_objects(self._records).values()
            )

    def put_bytes(
        self,
        content: bytes,
        *,
        logical_name: str,
        kind: str,
        media_type: str,
        disclosure: ArtifactDisclosure = "private",
        source: str | None = None,
    ) -> SessionBlobRef:
        payload = bytes(content)
        digest = hashlib.sha256(payload).hexdigest()
        reference = SessionBlobRef(
            session_id=self.session_id,
            blob_id=digest,
            logical_name=logical_name,
            kind=kind,
            media_type=media_type,
            disclosure=disclosure,
            size_bytes=len(payload),
            sha256=digest,
            created_at=float(self._now()),
            source=source,
        )
        return self.import_blob(reference, payload)

    def import_blob(
        self,
        reference: SessionBlobRef,
        content: bytes,
        *,
        preserve_created_at: bool = True,
    ) -> SessionBlobRef:
        """Publish verified bytes using portable metadata from another authority."""

        return self.import_blobs(
            ((reference, bytes(content)),),
            preserve_created_at=preserve_created_at,
        ).references[0]

    def import_blobs(
        self,
        items: Sequence[tuple[SessionBlobRef, bytes]],
        *,
        preserve_created_at: bool = True,
        require_new_authority: bool = False,
    ) -> SessionBlobPublication:
        """Publish a bounded group under one cross-process authority lock."""

        prepared = tuple((reference, bytes(content)) for reference, content in items)
        if not prepared:
            raise ValueError("session blob import requires at least one item")
        with self._lock, self._authority_lock("exclusive"):
            root_preexisting = self.root.exists()
            self._load_manifest_if_present()
            if require_new_authority and self.root.exists():
                raise SessionBlobError("target session blob authority already exists")
            previous_records = tuple(self._records)
            try:
                references = tuple(
                    self._import_blob_locked(
                        reference,
                        payload,
                        preserve_created_at=preserve_created_at,
                    )
                    for reference, payload in prepared
                )
            except BaseException as error:
                try:
                    self._restore_records_locked(
                        previous_records,
                        root_preexisting=root_preexisting,
                    )
                except BaseException as cleanup_error:
                    error.add_note(
                        "session blob rollback also failed: "
                        f"{cleanup_error.__class__.__name__}: {cleanup_error}"
                    )
                raise
            root_metadata = self.root.lstat()
            return SessionBlobPublication(
                _store=self,
                references=references,
                _previous_records=previous_records,
                _expected_records=tuple(self._records),
                _root_identity=(root_metadata.st_dev, root_metadata.st_ino),
                _root_preexisting=root_preexisting,
            )

    def _import_blob_locked(
        self,
        reference: SessionBlobRef,
        payload: bytes,
        *,
        preserve_created_at: bool,
    ) -> SessionBlobRef:
        payload = bytes(payload)
        digest = hashlib.sha256(payload).hexdigest()
        if digest != reference.sha256 or len(payload) != reference.size_bytes:
            raise ArtifactSourceRejected(
                "session blob payload does not match reference"
            )
        if reference.blob_id != digest:
            raise ArtifactSourceRejected("session blob id does not match its digest")
        target = replace(
            reference,
            session_id=self.session_id,
            created_at=(
                reference.created_at if preserve_created_at else float(self._now())
            ),
        )

        existing = next((item for item in self._records if item == target), None)
        if existing is not None:
            _read_blob_object(self.objects_root / existing.blob_id, existing)
            return existing
        self._check_capacity(target)
        self._prepare_tree()
        object_path = self.objects_root / target.blob_id
        object_identity: tuple[int, int] | None = None
        object_created = False
        if object_path.exists():
            _read_blob_object(object_path, target)
        else:
            try:
                object_identity = _write_new_private_file(object_path, payload)
                object_created = True
                _sync_directory(self.objects_root)
            except FileExistsError:
                _read_blob_object(object_path, target)
        try:
            self._write_manifest((*self._records, target))
        except BaseException:
            if object_created and object_identity is not None:
                with suppress(OSError):
                    _unlink_owned_file(object_path, object_identity)
                    _sync_directory(self.objects_root)
            raise
        self._records.append(target)
        self._initialized = True
        return target

    def read_bytes(self, blob: SessionBlobRef) -> bytes:
        with self._lock, self._authority_lock("shared"):
            self._load_manifest_if_present()
            if blob.session_id != self.session_id or blob not in self._records:
                raise ArtifactSourceRejected("blob is not owned by this session")
            return _read_blob_object(self.objects_root / blob.blob_id, blob)

    def inspect(
        self, blobs: Iterable[SessionBlobRef] | None = None
    ) -> tuple[SessionBlobHealth, ...]:
        """Report missing/corrupt blobs without making resume fail closed."""

        selected = tuple(self.records if blobs is None else blobs)
        health: list[SessionBlobHealth] = []
        for blob in selected:
            try:
                self.read_bytes(blob)
            except FileNotFoundError:
                health.append(SessionBlobHealth(blob, "missing", "object is missing"))
            except ArtifactSourceRejected as error:
                state: SessionBlobHealthState = (
                    "missing"
                    if blob not in self.records
                    and not (self.objects_root / blob.blob_id).exists()
                    else "corrupt"
                )
                health.append(SessionBlobHealth(blob, state, str(error)))
            except OSError as error:
                health.append(SessionBlobHealth(blob, "corrupt", str(error)))
            else:
                health.append(SessionBlobHealth(blob, "available"))
        return tuple(health)

    def inspect_metadata(
        self,
        blobs: Iterable[SessionBlobRef] | None = None,
    ) -> tuple[SessionBlobHealth, ...]:
        """Inspect bounded ownership and object metadata without reading bytes.

        This is an advisory preview operation. Model-input hydration continues
        to use ``read_bytes`` and therefore performs full digest validation.
        """

        with self._lock, self._authority_lock("shared"):
            self._load_manifest_if_present()
            records = tuple(self._records)
            selected = records if blobs is None else tuple(blobs)
            owned = set(records)
            health: list[SessionBlobHealth] = []
            for blob in selected:
                object_path = self.objects_root / blob.blob_id
                if blob.session_id != self.session_id or blob not in owned:
                    try:
                        object_path.lstat()
                    except FileNotFoundError:
                        object_exists = False
                    except OSError:
                        object_exists = True
                    else:
                        object_exists = True
                    health.append(
                        SessionBlobHealth(
                            blob,
                            "corrupt" if object_exists else "missing",
                            "blob is not owned by this session",
                        )
                    )
                    continue
                try:
                    metadata = object_path.lstat()
                except FileNotFoundError:
                    health.append(
                        SessionBlobHealth(blob, "missing", "object is missing")
                    )
                    continue
                except OSError as error:
                    health.append(SessionBlobHealth(blob, "corrupt", str(error)))
                    continue
                if (
                    not stat.S_ISREG(metadata.st_mode)
                    or _is_reparse_point(metadata)
                    or not _owned_by_current_user(metadata)
                    or metadata.st_size != blob.size_bytes
                ):
                    health.append(
                        SessionBlobHealth(
                            blob,
                            "corrupt",
                            "object metadata does not match its manifest",
                        )
                    )
                    continue
                health.append(SessionBlobHealth(blob, "available"))
            return tuple(health)

    def clone_into(
        self,
        target: SessionBlobStore,
        blobs: Sequence[SessionBlobRef],
    ) -> tuple[SessionBlobRef, ...]:
        """Copy only selected references into a target session authority."""

        publication = target.import_blobs(
            tuple((blob, self.read_bytes(blob)) for blob in blobs),
            require_new_authority=True,
        )
        return publication.references

    def delete(
        self,
        *,
        expected_root_identity: tuple[int, int] | None = None,
    ) -> bool:
        """Delete this session's complete blob authority without following links."""

        with self._lock, self._authority_lock("exclusive"):
            self._load_manifest_if_present()
            return self._delete_locked(expected_root_identity=expected_root_identity)

    def _rollback_publication(
        self,
        previous_records: tuple[SessionBlobRef, ...],
        expected_records: tuple[SessionBlobRef, ...],
        root_identity: tuple[int, int],
        root_preexisting: bool,
    ) -> bool:
        with self._lock, self._authority_lock("exclusive"):
            self._load_manifest_if_present()
            if not self.root.exists() or tuple(self._records) != expected_records:
                return False
            metadata = self.root.lstat()
            if (metadata.st_dev, metadata.st_ino) != root_identity:
                return False
            self._restore_records_locked(
                previous_records,
                root_preexisting=root_preexisting,
            )
            return True

    def _restore_records_locked(
        self,
        previous_records: tuple[SessionBlobRef, ...],
        *,
        root_preexisting: bool,
    ) -> None:
        """Restore one interrupted publication without deleting older records."""

        if not self.root.exists():
            self._records = list(previous_records)
            self._initialized = bool(previous_records) or root_preexisting
            return
        if not previous_records and not root_preexisting:
            self._delete_locked()
            return

        current_records = tuple(self._records)
        self._write_manifest(previous_records)
        retained_ids = set(_unique_objects(previous_records))
        removed_object = False
        for blob_id in set(_unique_objects(current_records)) - retained_ids:
            object_path = self.objects_root / blob_id
            try:
                metadata = object_path.lstat()
            except FileNotFoundError:
                continue
            _unlink_owned_file(
                object_path,
                (metadata.st_dev, metadata.st_ino),
            )
            removed_object = True
        if removed_object:
            _sync_directory(self.objects_root)
        self._records = list(previous_records)
        self._initialized = True

    def _delete_locked(
        self,
        *,
        expected_root_identity: tuple[int, int] | None = None,
    ) -> bool:
        if not self.root.exists():
            self._records.clear()
            self._initialized = False
            return False
        _validate_private_directory(self.root)
        metadata = self.root.lstat()
        identity = metadata.st_dev, metadata.st_ino
        if (
            _is_reparse_point(metadata)
            or not _owned_by_current_user(metadata)
            or (
                expected_root_identity is not None
                and identity != expected_root_identity
            )
        ):
            raise PermissionError("session blob root is not safe to delete")
        shutil.rmtree(self.root)
        self._records.clear()
        self._initialized = False
        _sync_directory(self.assets_root)
        return True

    def _check_capacity(self, reference: SessionBlobRef) -> None:
        if reference.size_bytes > self.policy.max_blob_bytes:
            raise ArtifactStoreQuotaExceeded(
                f"blob is {reference.size_bytes} bytes; per-blob limit is "
                f"{self.policy.max_blob_bytes} bytes"
            )
        if len(self._records) >= self.policy.max_blobs:
            raise ArtifactStoreQuotaExceeded(
                f"session blob count limit is {self.policy.max_blobs}"
            )
        objects = _unique_objects(self._records)
        added = 0 if reference.blob_id in objects else reference.size_bytes
        retained = sum(item.size_bytes for item in objects.values())
        if retained + added > self.policy.max_total_bytes:
            raise ArtifactStoreQuotaExceeded(
                f"session blob byte limit is {self.policy.max_total_bytes} bytes"
            )

    def _prepare_tree(self) -> None:
        _prepare_private_directory(self.data_root)
        _prepare_private_directory(self.assets_root)
        _prepare_private_directory(self.root)
        _prepare_private_directory(self.objects_root)

    @contextmanager
    def _authority_lock(
        self,
        mode: Literal["shared", "exclusive"],
    ):
        lock_target = self.assets_root / ".locks" / self.session_id
        with journal_file_lock(lock_target, mode):
            yield

    def _load_manifest_if_present(self) -> None:
        self._records = []
        self._initialized = False
        if not self.root.exists():
            return
        _validate_private_directory(self.root)
        if not self.manifest_path.exists():
            raise SessionBlobManifestError("session blob root has no manifest")
        try:
            metadata = self.manifest_path.lstat()
            if (
                not stat.S_ISREG(metadata.st_mode)
                or _is_reparse_point(metadata)
                or not _owned_by_current_user(metadata)
            ):
                raise SessionBlobManifestError(
                    "session blob manifest is not a safe file"
                )
            if metadata.st_size > 8 * 1024 * 1024:
                raise SessionBlobManifestError("session blob manifest is too large")
            value = json.loads(
                _read_stable_private_file(
                    self.manifest_path,
                    metadata,
                    max_bytes=8 * 1024 * 1024,
                ).decode("utf-8")
            )
        except SessionBlobManifestError:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise SessionBlobManifestError(
                "session blob manifest is unreadable"
            ) from error
        if not isinstance(value, dict) or set(value) != {
            "schemaVersion",
            "sessionId",
            "blobs",
        }:
            raise SessionBlobManifestError("session blob manifest shape is invalid")
        if value["schemaVersion"] != 1 or value["sessionId"] != self.session_id:
            raise SessionBlobManifestError("session blob manifest identity is invalid")
        raw_blobs = value["blobs"]
        if not isinstance(raw_blobs, list):
            raise SessionBlobManifestError("session blob manifest blobs must be a list")
        try:
            records = [SessionBlobRef.from_manifest_entry(item) for item in raw_blobs]
        except (TypeError, ValueError) as error:
            raise SessionBlobManifestError(
                "session blob manifest entry is invalid"
            ) from error
        if any(record.session_id != self.session_id for record in records):
            raise SessionBlobManifestError(
                "session blob manifest mixes session identities"
            )
        if len(records) > self.policy.max_blobs:
            raise ArtifactStoreQuotaExceeded(
                f"session blob count limit is {self.policy.max_blobs}"
            )
        objects = _unique_objects(records)
        if any(
            item.size_bytes > self.policy.max_blob_bytes for item in objects.values()
        ):
            raise ArtifactStoreQuotaExceeded(
                f"session blob exceeds per-blob limit of {self.policy.max_blob_bytes} bytes"
            )
        if (
            sum(item.size_bytes for item in objects.values())
            > self.policy.max_total_bytes
        ):
            raise ArtifactStoreQuotaExceeded(
                f"session blob byte limit is {self.policy.max_total_bytes} bytes"
            )
        self._records = records
        self._initialized = True

    def _write_manifest(self, records: Sequence[SessionBlobRef]) -> None:
        manifest = {
            "schemaVersion": 1,
            "sessionId": self.session_id,
            "blobs": [record.manifest_entry() for record in records],
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
                    raise SessionBlobError(
                        "session blob store is already initialized"
                    ) from error
            _sync_directory(self.root)
        finally:
            if identity is not None:
                with suppress(FileNotFoundError):
                    _unlink_owned_file(temporary, identity)


def resolve_session_blob_data_root(session_dir: str | Path) -> Path:
    """Resolve the data authority adjacent to a standard ``data/sessions`` root."""

    return Path(session_dir).expanduser().resolve(strict=False).parent


def _unique_objects(
    records: Iterable[SessionBlobRef],
) -> dict[str, SessionBlobRef]:
    result: dict[str, SessionBlobRef] = {}
    for record in records:
        previous = result.setdefault(record.blob_id, record)
        if previous.sha256 != record.sha256 or previous.size_bytes != record.size_bytes:
            raise SessionBlobManifestError(
                "blob id maps to conflicting content metadata"
            )
    return result


def _read_blob_object(path: Path, reference: SessionBlobRef) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or _is_reparse_point(metadata)
            or not _owned_by_current_user(metadata)
            or metadata.st_size != reference.size_bytes
        ):
            raise ArtifactSourceRejected("session blob object identity is invalid")
        payload = bytearray()
        while len(payload) <= reference.size_bytes:
            chunk = os.read(
                descriptor,
                min(1024 * 1024, reference.size_bytes + 1 - len(payload)),
            )
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) != reference.size_bytes:
            raise ArtifactSourceRejected("session blob object size changed")
        content = bytes(payload)
        if hashlib.sha256(content).hexdigest() != reference.sha256:
            raise ArtifactSourceRejected("session blob object digest changed")
        return content
    finally:
        os.close(descriptor)


def _read_stable_private_file(
    path: Path,
    expected: os.stat_result,
    *,
    max_bytes: int,
) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    parent_descriptor = -1
    directory_flag = getattr(os, "O_DIRECTORY", 0)
    try:
        if os.name != "nt" and directory_flag:
            parent_flags = os.O_RDONLY | directory_flag
            parent_flags |= getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
            parent_descriptor = os.open(path.parent, parent_flags)
            descriptor = os.open(path.name, flags, dir_fd=parent_descriptor)
        else:
            descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                not os.path.samestat(expected, opened)
                or not stat.S_ISREG(opened.st_mode)
                or _is_reparse_point(opened)
                or not _owned_by_current_user(opened)
                or opened.st_size > max_bytes
            ):
                raise SessionBlobManifestError(
                    "session blob manifest identity changed"
                )
            remaining = opened.st_size
            chunks: list[bytes] = []
            while remaining:
                chunk = os.read(descriptor, min(remaining, 1024 * 1024))
                if not chunk:
                    raise SessionBlobManifestError(
                        "session blob manifest changed while reading"
                    )
                chunks.append(chunk)
                remaining -= len(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if parent_descriptor >= 0:
            os.close(parent_descriptor)
    current = path.lstat()
    if not _same_file_status(opened, after) or not _same_file_status(expected, current):
        raise SessionBlobManifestError("session blob manifest changed while reading")
    return b"".join(chunks)


def _same_file_status(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        left.st_dev,
        left.st_ino,
        left.st_size,
        left.st_mtime_ns,
        left.st_ctime_ns,
    ) == (
        right.st_dev,
        right.st_ino,
        right.st_size,
        right.st_mtime_ns,
        right.st_ctime_ns,
    )


__all__ = [
    "DEFAULT_SESSION_BLOB_POLICY",
    "SessionBlobError",
    "SessionBlobHealth",
    "SessionBlobHealthState",
    "SessionBlobManifestError",
    "SessionBlobPolicy",
    "SessionBlobPublication",
    "SessionBlobReader",
    "SessionBlobStore",
    "SessionBlobWriter",
    "resolve_session_blob_data_root",
]
