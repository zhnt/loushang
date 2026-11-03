"""Explicit, default-dark Coding Source custody for local Worker Wheels.

Capturing a Wheel only pins its bytes and Product admission inputs. Package
transaction, Desired State selection, native preparation, and activation are
separate owners and decisions.
"""

from __future__ import annotations

import json
import os
import re
import stat
from contextlib import suppress
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    append_jsonl_record,
    journal_file_lock,
    journal_file_read_lock,
    load_jsonl,
)
from loushang.harness.resources.packages.plugin_lifecycle.local_source import (
    open_regular_no_follow,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_epoch_cutover import (
    _PinnedWindowsAuthority,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_regular_file_at,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWheelPolicy,
    PackageProductLocalWorkerAdmissionV1,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)

from .package_builtin_wheel import _publish_windows_product_wheel
from .package_legacy_windows_receipt import (
    CodingWindowsPrivateReceiptError,
    read_windows_private_receipt,
    write_windows_private_receipt,
)

_WHEEL_NAME = re.compile(
    r"(?P<plugin>[a-z][a-z0-9]*)-(?P<version>[0-9]+(?:\.[0-9]+){0,2})-"
    r"py3-none-(?P<tag>(?:(?:linux|manylinux_[0-9]+_[0-9]+)_x86_64|win_amd64))\.whl\Z"
)
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_WHEEL_BYTES = 2 * 1024 * 1024
_MAX_WHEEL_FILENAME = 180
_MAX_WINDOWS_RECORD_BYTES = 16 * 1024


class CodingExternalWorkerWheelError(RuntimeError):
    """Worker Wheel Source custody or binding could not be proved."""


@dataclass(frozen=True, slots=True)
class CodingExternalWorkerWheelBindingV1:
    record_revision: int
    store_id: str
    namespace_id: str
    scope_id: str
    original_source: str
    wheel_filename: str
    plugin_id: str
    version: str
    artifact_digest: str
    admission: PackageProductLocalWorkerAdmissionV1
    record_id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.store_id, str)
            or not isinstance(self.namespace_id, str)
            or not isinstance(self.scope_id, str)
            or not isinstance(self.original_source, str)
            or not isinstance(self.wheel_filename, str)
            or not isinstance(self.plugin_id, str)
            or not isinstance(self.version, str)
            or not isinstance(self.artifact_digest, str)
            or not isinstance(self.record_id, str)
        ):
            raise ValueError("External Worker Wheel binding fields are invalid")
        match = _WHEEL_NAME.fullmatch(self.wheel_filename)
        if (
            type(self.record_revision) is not int
            or self.record_revision < 1
            or not self.store_id
            or _DIGEST.fullmatch(self.namespace_id) is None
            or not self.scope_id
            or not Path(self.original_source).is_absolute()
            or os.path.normpath(self.original_source) != self.original_source
            or match is None
            or len(self.wheel_filename) > _MAX_WHEEL_FILENAME
            or self.plugin_id != match["plugin"]
            or self.version != match["version"]
            or _DIGEST.fullmatch(self.artifact_digest) is None
            or not isinstance(self.admission, PackageProductLocalWorkerAdmissionV1)
            or self.admission.native_platform
            != (
                "windows-amd64"
                if match is not None and match["tag"] == "win_amd64"
                else "linux-x86_64"
            )
            or _DIGEST.fullmatch(self.record_id) is None
        ):
            raise ValueError("External Worker Wheel binding is invalid")
        if self.record_id != sha256(canonical_json_bytes(self._identity())).hexdigest():
            raise ValueError("External Worker Wheel binding identity changed")

    @classmethod
    def create(
        cls,
        *,
        record_revision: int,
        store_id: str,
        namespace_id: str,
        scope_id: str,
        original_source: str,
        wheel_filename: str,
        artifact_digest: str,
        admission: PackageProductLocalWorkerAdmissionV1,
    ) -> CodingExternalWorkerWheelBindingV1:
        match = _WHEEL_NAME.fullmatch(wheel_filename)
        if match is None:
            raise ValueError("External Worker Wheel filename is unsupported")
        fields = {
            "admission": {
                "contributionId": admission.contribution_id,
                "nativePlatform": admission.native_platform,
                "ownerId": admission.owner_id,
            },
            "artifactDigest": artifact_digest,
            "namespaceId": namespace_id,
            "originalSource": original_source,
            "pluginId": match["plugin"],
            "recordRevision": record_revision,
            "scopeId": scope_id,
            "storeId": store_id,
            "version": match["version"],
            "wheelFilename": wheel_filename,
        }
        return cls(
            record_revision=record_revision,
            store_id=store_id,
            namespace_id=namespace_id,
            scope_id=scope_id,
            original_source=original_source,
            wheel_filename=wheel_filename,
            plugin_id=match["plugin"],
            version=match["version"],
            artifact_digest=artifact_digest,
            admission=admission,
            record_id=sha256(canonical_json_bytes(fields)).hexdigest(),
        )

    def _identity(self) -> dict[str, object]:
        return {
            key: value for key, value in self.to_dict().items() if key != "recordId"
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "admission": {
                "contributionId": self.admission.contribution_id,
                "nativePlatform": self.admission.native_platform,
                "ownerId": self.admission.owner_id,
            },
            "artifactDigest": self.artifact_digest,
            "namespaceId": self.namespace_id,
            "originalSource": self.original_source,
            "pluginId": self.plugin_id,
            "recordId": self.record_id,
            "recordRevision": self.record_revision,
            "scopeId": self.scope_id,
            "storeId": self.store_id,
            "version": self.version,
            "wheelFilename": self.wheel_filename,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingExternalWorkerWheelBindingV1:
        keys = {
            "admission",
            "artifactDigest",
            "namespaceId",
            "originalSource",
            "pluginId",
            "recordId",
            "recordRevision",
            "scopeId",
            "storeId",
            "version",
            "wheelFilename",
        }
        if type(value) is not dict or set(value) != keys:
            raise ValueError("External Worker Wheel binding record is invalid")
        admission = value["admission"]
        if type(admission) is not dict or set(admission) != {
            "contributionId",
            "nativePlatform",
            "ownerId",
        }:
            raise ValueError("External Worker Wheel admission record is invalid")
        return cls(
            record_revision=value["recordRevision"],
            store_id=value["storeId"],
            namespace_id=value["namespaceId"],
            scope_id=value["scopeId"],
            original_source=value["originalSource"],
            wheel_filename=value["wheelFilename"],
            plugin_id=value["pluginId"],
            version=value["version"],
            artifact_digest=value["artifactDigest"],
            admission=PackageProductLocalWorkerAdmissionV1(
                contribution_id=admission["contributionId"],
                owner_id=admission["ownerId"],
                native_platform=admission["nativePlatform"],
            ),
            record_id=value["recordId"],
        )

    def policy_binding(self, source_root: Path) -> PackageProductLocalWheelBindingV1:
        return PackageProductLocalWheelBindingV1(
            source_identity=str(source_root / self.wheel_filename),
            requested_package=f"{self.plugin_id}=={self.version}",
            plugin_id=self.plugin_id,
            artifact_digest=self.artifact_digest,
            plugin_manifest_path=f"{self.plugin_id}/plugin.json",
            source_trust_class="local-worker-candidate",
            worker_admission=self.admission,
        )


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingExternalWorkerWheelBindingV1.to_dict,
    decoder=CodingExternalWorkerWheelBindingV1.from_dict,
)


class CodingExternalWorkerWheelCatalog:
    """Pin explicit Linux Worker candidates under a fenced Product Source."""

    def __init__(
        self,
        path: Path,
        *,
        source_root: Path,
        store_id: str,
        namespace_id: str,
        scope_id: str,
        read_only: bool = False,
    ) -> None:
        if not path.is_absolute() or not source_root.is_absolute():
            raise ValueError("External Worker Wheel catalog paths must be absolute")
        self.path = path
        self.source_root = source_root
        self.store_id = store_id
        self.namespace_id = namespace_id
        self.scope_id = scope_id
        self._read_only = read_only
        self._durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)

    def capture(
        self,
        source: Path,
        *,
        admission: PackageProductLocalWorkerAdmissionV1,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    ) -> CodingExternalWorkerWheelBindingV1:
        if self._read_only:
            raise CodingExternalWorkerWheelError(
                "Read-only Worker Source cannot capture"
            )
        self._assert_epoch(epoch_runtime)
        if (
            not isinstance(admission, PackageProductLocalWorkerAdmissionV1)
            or admission.native_platform != "linux-x86_64"
            or not isinstance(source, Path)
            or not source.is_absolute()
            or os.path.normpath(str(source)) != str(source)
            or source.is_relative_to(self.source_root)
            or _WHEEL_NAME.fullmatch(source.name) is None
            or len(source.name) > _MAX_WHEEL_FILENAME
        ):
            raise CodingExternalWorkerWheelError(
                "External Worker Wheel Source is invalid"
            )
        try:
            descriptor = open_regular_no_follow(source)
            with os.fdopen(descriptor, "rb") as handle:
                before = os.fstat(handle.fileno())
                if before.st_size <= 0 or before.st_size > _MAX_WHEEL_BYTES:
                    raise CodingExternalWorkerWheelError(
                        "External Worker Wheel exceeds budget"
                    )
                body = handle.read(_MAX_WHEEL_BYTES + 1)
                after = os.fstat(handle.fileno())
            visible = source.lstat()
        except OSError as exc:
            raise CodingExternalWorkerWheelError(
                "External Worker Wheel Source changed"
            ) from exc
        if (
            not body
            or len(body) > _MAX_WHEEL_BYTES
            or _file_identity(before) != _file_identity(after)
            or _file_identity(before) != _file_identity(visible)
        ):
            raise CodingExternalWorkerWheelError("External Worker Wheel Source changed")
        digest = sha256(body).hexdigest()
        with journal_file_lock(self.path, "exclusive"):
            self._assert_epoch(epoch_runtime)
            records = self._load_unlocked()
            existing = next(
                (item for item in records if item.wheel_filename == source.name), None
            )
            if existing is not None:
                if (
                    existing.artifact_digest != digest
                    or existing.original_source != str(source)
                    or existing.admission != admission
                ):
                    raise CodingExternalWorkerWheelError(
                        "External Worker binding conflicts"
                    )
                self._verify_controlled(existing)
                return existing
            if len(records) >= 125:
                raise CodingExternalWorkerWheelError(
                    "External Worker binding limit reached"
                )
            record = CodingExternalWorkerWheelBindingV1.create(
                record_revision=len(records) + 1,
                store_id=self.store_id,
                namespace_id=self.namespace_id,
                scope_id=self.scope_id,
                original_source=str(source),
                wheel_filename=source.name,
                artifact_digest=digest,
                admission=admission,
            )
            self._publish_controlled(record, body)
            append_jsonl_record(
                self.path,
                record,
                record_codec=_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._durability,
            )
            epoch_runtime.assert_current()
            return record

    def records(self) -> tuple[CodingExternalWorkerWheelBindingV1, ...]:
        if self._read_only:
            return self.read_records()
        with journal_file_lock(self.path, "exclusive"):
            return self._load_unlocked()

    def read_records(self) -> tuple[CodingExternalWorkerWheelBindingV1, ...]:
        try:
            with journal_file_read_lock(self.path, "shared", create_lock=False):
                return self._load_unlocked(
                    load_policy=JournalLoadPolicy(
                        partial_tail="raise", create_lock=False
                    )
                )
        except (
            JournalFileError,
            JournalCodecError,
            OSError,
            TypeError,
            UnicodeError,
            ValueError,
        ) as exc:
            raise CodingExternalWorkerWheelError(
                "External Worker binding catalog is corrupt"
            ) from exc

    def extend_policy(
        self, base: PackageProductLocalWheelPolicy
    ) -> PackageProductLocalWheelPolicy:
        if (
            base.product_id != "coding"
            or base.source_root != self.source_root
            or base.project_scope_id != self.scope_id
        ):
            raise CodingExternalWorkerWheelError("External Worker Product changed")
        records = self.records()
        existing_ids = {item.plugin_id for item in base.bindings}
        for record in records:
            if record.plugin_id in existing_ids:
                raise CodingExternalWorkerWheelError(
                    "External Worker Plugin id collides"
                )
            self._verify_controlled(record)
        return replace(
            base,
            bindings=tuple(
                sorted(
                    (
                        *base.bindings,
                        *(item.policy_binding(self.source_root) for item in records),
                    ),
                    key=lambda item: item.source_identity,
                )
            ),
        )

    def _assert_epoch(
        self, epoch_runtime: PackageProductPosixFencedRuntimeOwner
    ) -> None:
        switch = epoch_runtime.cutover_result.switch_receipt
        if (
            epoch_runtime.registry.store_id != self.store_id
            or switch is None
            or switch.namespace_id != self.namespace_id
            or epoch_runtime.prepare_product_source_root() != self.source_root
        ):
            raise CodingExternalWorkerWheelError("External Worker epoch changed")
        epoch_runtime.assert_current()

    def _load_unlocked(
        self, *, load_policy: JournalLoadPolicy | None = None
    ) -> tuple[CodingExternalWorkerWheelBindingV1, ...]:
        try:
            present = self.path.lstat()
        except FileNotFoundError:
            return ()
        if not stat.S_ISREG(present.st_mode) or present.st_nlink != 1:
            raise CodingExternalWorkerWheelError(
                "External Worker binding file is unsafe"
            )
        records = load_jsonl(
            self.path,
            record_codec=_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._durability,
            load_policy=load_policy or JournalLoadPolicy(partial_tail="raise"),
        ).records
        if any(
            record.record_revision != index
            or record.store_id != self.store_id
            or record.namespace_id != self.namespace_id
            or record.scope_id != self.scope_id
            for index, record in enumerate(records, start=1)
        ):
            raise CodingExternalWorkerWheelError(
                "External Worker binding chain changed"
            )
        names = tuple(item.wheel_filename for item in records)
        identities = tuple((item.plugin_id, item.version) for item in records)
        if len(set(names)) != len(records) or len(set(identities)) != len(records):
            raise CodingExternalWorkerWheelError(
                "External Worker binding is duplicated"
            )
        return records

    def _publish_controlled(
        self, record: CodingExternalWorkerWheelBindingV1, body: bytes
    ) -> None:
        directory = os.open(
            self.source_root,
            os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
        )
        try:
            root = os.fstat(directory)
            if (
                not stat.S_ISDIR(root.st_mode)
                or stat.S_IMODE(root.st_mode) & 0o077
                or root.st_uid != os.geteuid()
            ):
                raise CodingExternalWorkerWheelError("External Worker root is unsafe")
            staging = f".{record.wheel_filename}.staging"
            with suppress(FileNotFoundError):
                os.unlink(staging, dir_fd=directory)
            descriptor = os.open(
                staging,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=directory,
            )
            try:
                os.fchmod(descriptor, 0o600)
                pending = memoryview(body)
                while pending:
                    written = os.write(descriptor, pending)
                    if written <= 0:
                        raise OSError("External Worker write made no progress")
                    pending = pending[written:]
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            try:
                with suppress(FileExistsError):
                    os.link(
                        staging,
                        record.wheel_filename,
                        src_dir_fd=directory,
                        dst_dir_fd=directory,
                        follow_symlinks=False,
                    )
                os.fsync(directory)
            finally:
                os.unlink(staging, dir_fd=directory)
                os.fsync(directory)
        finally:
            os.close(directory)
        self._verify_controlled(record)

    def _verify_controlled(self, record: CodingExternalWorkerWheelBindingV1) -> None:
        descriptor = open_regular_no_follow(self.source_root / record.wheel_filename)
        with os.fdopen(descriptor, "rb") as handle:
            before = os.fstat(handle.fileno())
            if (
                before.st_nlink != 1
                or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) & 0o077
                or before.st_size > _MAX_WHEEL_BYTES
            ):
                raise CodingExternalWorkerWheelError("External Worker bytes are unsafe")
            body = handle.read(_MAX_WHEEL_BYTES + 1)
            after = os.fstat(handle.fileno())
        if (
            _file_identity(before) != _file_identity(after)
            or sha256(body).hexdigest() != record.artifact_digest
        ):
            raise CodingExternalWorkerWheelError("External Worker bytes changed")


class CodingWindowsExternalWorkerWheelCatalog:
    """Pin inert Worker candidates in immutable Windows Product receipts.

    Every revision has one native, ACL-verified receipt. Bounded sequential
    reads refuse gaps and partial stages; no path-based append is trusted as a
    Windows catalog authority.
    """

    def __init__(
        self,
        *,
        epoch_runtime: PackageProductWindowsFencedRuntimeOwner,
        state_root: Path,
        source_root: Path,
        store_id: str,
        namespace_id: str,
        scope_id: str,
    ) -> None:
        if (
            not isinstance(epoch_runtime, PackageProductWindowsFencedRuntimeOwner)
            or os.name != "nt"
            or not state_root.is_absolute()
            or not source_root.is_absolute()
            or epoch_runtime.registry.store_id != store_id
            or epoch_runtime.prepare_product_state_root() != state_root
            or epoch_runtime.prepare_product_source_root() != source_root
        ):
            raise CodingExternalWorkerWheelError("Windows Worker Product roots changed")
        switch = epoch_runtime.cutover_result.switch_receipt
        if switch is None or switch.namespace_id != namespace_id:
            raise CodingExternalWorkerWheelError("Windows Worker Product epoch changed")
        self.epoch_runtime = epoch_runtime
        self.state_root = state_root
        self.source_root = source_root
        self.store_id = store_id
        self.namespace_id = namespace_id
        self.scope_id = scope_id
        epoch_runtime.assert_current()

    def capture(
        self,
        source: Path,
        *,
        admission: PackageProductLocalWorkerAdmissionV1,
    ) -> CodingExternalWorkerWheelBindingV1:
        self._assert_epoch()
        if (
            not isinstance(admission, PackageProductLocalWorkerAdmissionV1)
            or admission.native_platform != "windows-amd64"
            or not isinstance(source, Path)
            or not source.is_absolute()
            or os.path.normpath(str(source)) != str(source)
            or source.is_relative_to(self.source_root)
            or _WHEEL_NAME.fullmatch(source.name) is None
            or not source.name.endswith("-win_amd64.whl")
            or len(source.name) > _MAX_WHEEL_FILENAME
        ):
            raise CodingExternalWorkerWheelError(
                "Windows Worker Wheel Source is invalid"
            )
        try:
            descriptor = open_regular_no_follow(source)
            with os.fdopen(descriptor, "rb") as handle:
                before = os.fstat(handle.fileno())
                if before.st_size <= 0 or before.st_size > _MAX_WHEEL_BYTES:
                    raise CodingExternalWorkerWheelError(
                        "Windows Worker Wheel exceeds budget"
                    )
                body = handle.read(_MAX_WHEEL_BYTES + 1)
                after = os.fstat(handle.fileno())
            visible = source.lstat()
        except OSError as exc:
            raise CodingExternalWorkerWheelError(
                "Windows Worker Wheel Source changed"
            ) from exc
        if (
            not body
            or len(body) > _MAX_WHEEL_BYTES
            or _file_identity(before) != _file_identity(after)
            or _file_identity(before) != _file_identity(visible)
        ):
            raise CodingExternalWorkerWheelError("Windows Worker Wheel Source changed")
        digest = sha256(body).hexdigest()
        records = self._records(allow_pending_stage=True)
        existing = next(
            (item for item in records if item.wheel_filename == source.name), None
        )
        if existing is not None:
            if (
                existing.artifact_digest != digest
                or existing.original_source != str(source)
                or existing.admission != admission
            ):
                raise CodingExternalWorkerWheelError("Windows Worker binding conflicts")
            self.verify_record(existing)
            return existing
        if len(records) >= 125:
            raise CodingExternalWorkerWheelError("Windows Worker binding limit reached")
        record = CodingExternalWorkerWheelBindingV1.create(
            record_revision=len(records) + 1,
            store_id=self.store_id,
            namespace_id=self.namespace_id,
            scope_id=self.scope_id,
            original_source=str(source),
            wheel_filename=source.name,
            artifact_digest=digest,
            admission=admission,
        )
        receipt_bytes = canonical_json_bytes(record.to_dict())
        if len(receipt_bytes) > _MAX_WINDOWS_RECORD_BYTES:
            raise CodingExternalWorkerWheelError(
                "Windows Worker binding exceeds budget"
            )
        try:
            _publish_windows_product_wheel(
                self.source_root,
                filename=record.wheel_filename,
                body=body,
                label="external Worker",
            )
            self._assert_epoch()
            write_windows_private_receipt(
                self._record_path(record.record_revision),
                receipt_bytes,
            )
        except CodingWindowsPrivateReceiptError as exc:
            # A competing writer may have won this revision. Exact replay is
            # admitted after a fresh native read; a distinct winner conflicts.
            current = self.records()
            winner = next(
                (item for item in current if item.wheel_filename == source.name), None
            )
            if winner is not None and winner == record:
                self.verify_record(winner)
                return winner
            raise CodingExternalWorkerWheelError(
                "Windows Worker binding revision conflicts"
            ) from exc
        self._assert_epoch()
        self.verify_record(record)
        return record

    def records(self) -> tuple[CodingExternalWorkerWheelBindingV1, ...]:
        return self._records(allow_pending_stage=False)

    def verify_record(self, record: CodingExternalWorkerWheelBindingV1) -> None:
        """Reopen one exact receipt and its Product-controlled Wheel bytes."""

        if (
            not isinstance(record, CodingExternalWorkerWheelBindingV1)
            or record not in self.records()
        ):
            raise CodingExternalWorkerWheelError("Windows Worker binding changed")
        self._verify_controlled(record)
        self._assert_epoch()

    def _records(
        self, *, allow_pending_stage: bool
    ) -> tuple[CodingExternalWorkerWheelBindingV1, ...]:
        self._assert_epoch()
        records: list[CodingExternalWorkerWheelBindingV1] = []
        missing = False
        try:
            for revision in range(1, 127):
                raw = read_windows_private_receipt(
                    self._record_path(revision),
                    maximum_bytes=_MAX_WINDOWS_RECORD_BYTES,
                    allow_unpublished_stage=allow_pending_stage,
                )
                if revision == 126:
                    if raw is not None:
                        raise CodingExternalWorkerWheelError(
                            "Windows Worker binding limit was exceeded"
                        )
                    break
                if raw is None:
                    missing = True
                    continue
                if missing:
                    raise CodingExternalWorkerWheelError(
                        "Windows Worker binding revisions have a gap"
                    )
                record = CodingExternalWorkerWheelBindingV1.from_dict(
                    json.loads(raw.decode("utf-8"))
                )
                if (
                    raw != canonical_json_bytes(record.to_dict())
                    or record.record_revision != revision
                    or record.store_id != self.store_id
                    or record.namespace_id != self.namespace_id
                    or record.scope_id != self.scope_id
                ):
                    raise CodingExternalWorkerWheelError(
                        "Windows Worker binding chain changed"
                    )
                records.append(record)
        except (
            OSError,
            TypeError,
            UnicodeError,
            ValueError,
            CodingWindowsPrivateReceiptError,
        ) as exc:
            raise CodingExternalWorkerWheelError(
                "Windows Worker binding catalog is corrupt"
            ) from exc
        names = tuple(item.wheel_filename for item in records)
        identities = tuple((item.plugin_id, item.version) for item in records)
        if len(set(names)) != len(records) or len(set(identities)) != len(records):
            raise CodingExternalWorkerWheelError("Windows Worker binding is duplicated")
        self._assert_epoch()
        return tuple(records)

    def extend_policy(
        self, base: PackageProductLocalWheelPolicy
    ) -> PackageProductLocalWheelPolicy:
        if (
            base.product_id != "coding"
            or base.source_root != self.source_root
            or base.project_scope_id != self.scope_id
        ):
            raise CodingExternalWorkerWheelError("Windows Worker Product changed")
        records = self.records()
        existing_ids = {item.plugin_id for item in base.bindings}
        for record in records:
            if record.plugin_id in existing_ids:
                raise CodingExternalWorkerWheelError(
                    "Windows Worker Plugin id collides"
                )
            self._verify_controlled(record)
        self._assert_epoch()
        return replace(
            base,
            bindings=tuple(
                sorted(
                    (
                        *base.bindings,
                        *(item.policy_binding(self.source_root) for item in records),
                    ),
                    key=lambda item: item.source_identity,
                )
            ),
        )

    def _record_path(self, revision: int) -> Path:
        return self.state_root / f"external-worker-binding-{revision:03d}.json"

    def _assert_epoch(self) -> None:
        if (
            self.epoch_runtime.registry.store_id != self.store_id
            or self.epoch_runtime.prepare_product_state_root() != self.state_root
            or self.epoch_runtime.prepare_product_source_root() != self.source_root
            or self.epoch_runtime.cutover_result.switch_receipt is None
            or self.epoch_runtime.cutover_result.switch_receipt.namespace_id
            != self.namespace_id
        ):
            raise CodingExternalWorkerWheelError("Windows Worker Product epoch changed")
        self.epoch_runtime.assert_current()

    def _verify_controlled(self, record: CodingExternalWorkerWheelBindingV1) -> None:
        pinned = _PinnedWindowsAuthority.open(self.source_root, read_control=True)
        try:
            with WindowsPrivateDirectoryAcl() as acl:
                acl.validate(pinned.descriptor)
                descriptor = open_windows_regular_file_at(
                    pinned.descriptor,
                    record.wheel_filename,
                    create_new=False,
                    write=False,
                    read_control=True,
                )
                try:
                    acl.validate(descriptor)
                    before = os.fstat(descriptor)
                    if (
                        not stat.S_ISREG(before.st_mode)
                        or before.st_nlink != 1
                        or before.st_size > _MAX_WHEEL_BYTES
                    ):
                        raise CodingExternalWorkerWheelError(
                            "Windows Worker controlled bytes are unsafe"
                        )
                    body = os.read(descriptor, _MAX_WHEEL_BYTES + 1)
                    after = os.fstat(descriptor)
                    acl.validate(descriptor)
                finally:
                    os.close(descriptor)
            pinned.assert_visible()
        finally:
            pinned.close()
        if (
            _file_identity(before) != _file_identity(after)
            or len(body) != before.st_size
            or sha256(body).hexdigest() != record.artifact_digest
        ):
            raise CodingExternalWorkerWheelError(
                "Windows Worker controlled bytes changed"
            )


def _file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_uid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


__all__ = [
    "CodingExternalWorkerWheelBindingV1",
    "CodingExternalWorkerWheelCatalog",
    "CodingWindowsExternalWorkerWheelCatalog",
    "CodingExternalWorkerWheelError",
]
