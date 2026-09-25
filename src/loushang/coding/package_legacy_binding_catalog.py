"""Dark, durable Product policy bindings for reacquired local legacy Sources."""

from __future__ import annotations

import json
import os
import re
import stat
from contextlib import suppress
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

from loushang.harness.journal import (
    DURABLE_LOCKED_JOURNAL,
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFileError,
    JournalLoadPolicy,
    JsonlSnapshot,
    append_jsonl_record,
    journal_file_lock,
    load_jsonl,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelBindingV1,
    PackageProductLocalWheelPolicy,
)

from .package_legacy_local_wheel import CodingLegacyLocalWheelCandidateV1

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_WHEEL_FILENAME = re.compile(r"loushang_legacy_[0-9a-f]{24}-1-py3-none-any\.whl\Z")
_MAX_WHEEL_BYTES = 2 * 1024 * 1024
_BUILTIN_PLUGIN_IDS = frozenset(
    {"coding.base", "coding.lsp.default", "coding.arch.default"}
)


class CodingLegacyBindingError(RuntimeError):
    """A durable migrated Source binding cannot be trusted or replayed."""


@dataclass(frozen=True, slots=True)
class CodingLegacyLocalBindingV1:
    record_revision: int
    store_id: str
    namespace_id: str
    scope_id: str
    plugin_id: str
    legacy_source_identity: str
    legacy_binding_digest: str
    source_content_digest: str
    manifest_digest: str
    dependency_lock_digest: str
    wheel_filename: str
    artifact_digest: str
    requested_package: str
    plugin_manifest_path: str
    policy_revision: str
    approval_id: str
    record_id: str
    record_version: int = 1

    def __post_init__(self) -> None:
        if type(self.record_revision) is not int or self.record_revision < 1:
            raise ValueError("Legacy Product binding revision is invalid")
        for value, name in (
            (self.store_id, "Store"),
            (self.scope_id, "scope"),
            (self.plugin_id, "Plugin"),
            (self.policy_revision, "policy"),
            (self.approval_id, "approval"),
        ):
            if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
                raise ValueError(f"Legacy Product {name} identity is invalid")
        if self.plugin_id in _BUILTIN_PLUGIN_IDS:
            raise ValueError("Legacy Product binding cannot replace a builtin Plugin")
        for value, name in (
            (self.namespace_id, "namespace"),
            (self.legacy_binding_digest, "old binding"),
            (self.source_content_digest, "Source content"),
            (self.manifest_digest, "manifest"),
            (self.dependency_lock_digest, "dependency lock"),
            (self.artifact_digest, "Wheel artifact"),
            (self.record_id, "record"),
        ):
            if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
                raise ValueError(f"Legacy Product {name} digest is invalid")
        if (
            not isinstance(self.legacy_source_identity, str)
            or not self.legacy_source_identity.startswith("local:")
            or len(self.legacy_source_identity) > 4096
            or _WHEEL_FILENAME.fullmatch(self.wheel_filename) is None
            or type(self.record_version) is not int
            or self.record_version != 1
        ):
            raise ValueError("Legacy Product binding Source shape is invalid")
        prefix = self.wheel_filename.removesuffix("-1-py3-none-any.whl")
        if (
            self.requested_package != f"{prefix.replace('_', '-')}==1"
            or self.plugin_manifest_path != f"{prefix}/plugin.json"
        ):
            raise ValueError("Legacy Product binding Wheel identity is inconsistent")
        binding = self.to_policy_binding(Path("/"))
        if binding.requested_package != self.requested_package:
            raise ValueError("Legacy Product binding package is invalid")
        if self.record_id != sha256(canonical_json_bytes(self._identity())).hexdigest():
            raise ValueError("Legacy Product binding record identity is invalid")

    @classmethod
    def create(
        cls,
        *,
        record_revision: int,
        store_id: str,
        namespace_id: str,
        scope_id: str,
        legacy_source_identity: str,
        legacy_binding_digest: str,
        dependency_lock_digest: str,
        policy_revision: str,
        approval_id: str,
        candidate: CodingLegacyLocalWheelCandidateV1,
    ) -> CodingLegacyLocalBindingV1:
        if not isinstance(candidate, CodingLegacyLocalWheelCandidateV1):
            raise TypeError("Reacquired legacy Wheel candidate is required")
        if legacy_source_identity != candidate.original_source_identity:
            raise ValueError("Legacy Product original Source identity changed")
        values = {
            "recordRevision": record_revision,
            "storeId": store_id,
            "namespaceId": namespace_id,
            "scopeId": scope_id,
            "pluginId": candidate.plugin_id,
            "legacySourceIdentity": legacy_source_identity,
            "legacyBindingDigest": legacy_binding_digest,
            "sourceContentDigest": candidate.source_content_digest,
            "manifestDigest": candidate.manifest_digest,
            "dependencyLockDigest": dependency_lock_digest,
            "wheelFilename": candidate.filename,
            "artifactDigest": candidate.artifact_digest,
            "requestedPackage": candidate.requested_package,
            "pluginManifestPath": candidate.plugin_manifest_path,
            "policyRevision": policy_revision,
            "approvalId": approval_id,
            "recordVersion": 1,
        }
        return cls(
            record_revision=record_revision,
            store_id=store_id,
            namespace_id=namespace_id,
            scope_id=scope_id,
            plugin_id=candidate.plugin_id,
            legacy_source_identity=legacy_source_identity,
            legacy_binding_digest=legacy_binding_digest,
            source_content_digest=candidate.source_content_digest,
            manifest_digest=candidate.manifest_digest,
            dependency_lock_digest=dependency_lock_digest,
            wheel_filename=candidate.filename,
            artifact_digest=candidate.artifact_digest,
            requested_package=candidate.requested_package,
            plugin_manifest_path=candidate.plugin_manifest_path,
            policy_revision=policy_revision,
            approval_id=approval_id,
            record_id=sha256(canonical_json_bytes(values)).hexdigest(),
        )

    def _identity(self) -> dict[str, object]:
        return {
            key: value for key, value in self.to_dict().items() if key != "recordId"
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "recordRevision": self.record_revision,
            "storeId": self.store_id,
            "namespaceId": self.namespace_id,
            "scopeId": self.scope_id,
            "pluginId": self.plugin_id,
            "legacySourceIdentity": self.legacy_source_identity,
            "legacyBindingDigest": self.legacy_binding_digest,
            "sourceContentDigest": self.source_content_digest,
            "manifestDigest": self.manifest_digest,
            "dependencyLockDigest": self.dependency_lock_digest,
            "wheelFilename": self.wheel_filename,
            "artifactDigest": self.artifact_digest,
            "requestedPackage": self.requested_package,
            "pluginManifestPath": self.plugin_manifest_path,
            "policyRevision": self.policy_revision,
            "approvalId": self.approval_id,
            "recordId": self.record_id,
            "recordVersion": self.record_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingLegacyLocalBindingV1:
        expected = {
            "recordRevision",
            "storeId",
            "namespaceId",
            "scopeId",
            "pluginId",
            "legacySourceIdentity",
            "legacyBindingDigest",
            "sourceContentDigest",
            "manifestDigest",
            "dependencyLockDigest",
            "wheelFilename",
            "artifactDigest",
            "requestedPackage",
            "pluginManifestPath",
            "policyRevision",
            "approvalId",
            "recordId",
            "recordVersion",
        }
        if type(value) is not dict or set(value) != expected:
            raise JournalCodecError(
                "Invalid Coding legacy binding record",
                code="coding_legacy_binding_invalid",
            )
        try:
            return cls(
                record_revision=value["recordRevision"],
                store_id=value["storeId"],
                namespace_id=value["namespaceId"],
                scope_id=value["scopeId"],
                plugin_id=value["pluginId"],
                legacy_source_identity=value["legacySourceIdentity"],
                legacy_binding_digest=value["legacyBindingDigest"],
                source_content_digest=value["sourceContentDigest"],
                manifest_digest=value["manifestDigest"],
                dependency_lock_digest=value["dependencyLockDigest"],
                wheel_filename=value["wheelFilename"],
                artifact_digest=value["artifactDigest"],
                requested_package=value["requestedPackage"],
                plugin_manifest_path=value["pluginManifestPath"],
                policy_revision=value["policyRevision"],
                approval_id=value["approvalId"],
                record_id=value["recordId"],
                record_version=value["recordVersion"],
            )
        except (TypeError, ValueError) as exc:
            raise JournalCodecError(
                "Invalid Coding legacy binding record",
                code="coding_legacy_binding_invalid",
            ) from exc

    def to_policy_binding(self, source_root: Path) -> PackageProductLocalWheelBindingV1:
        return PackageProductLocalWheelBindingV1(
            source_identity=str(source_root / self.wheel_filename),
            requested_package=self.requested_package,
            plugin_id=self.plugin_id,
            artifact_digest=self.artifact_digest,
            plugin_manifest_path=self.plugin_manifest_path,
            source_trust_class="legacy-local-reacquired",
        )


_CODEC = FunctionalJournalRecordCodec(
    encoder=CodingLegacyLocalBindingV1.to_dict,
    decoder=CodingLegacyLocalBindingV1.from_dict,
)


class CodingLegacyLocalBindingCatalog:
    """Append-only pre-transaction Source authorization for one B namespace."""

    def __init__(
        self,
        path: Path,
        *,
        source_root: Path,
        store_id: str,
        namespace_id: str,
        scope_id: str,
        policy_revision: str,
    ) -> None:
        if not isinstance(path, Path) or not path.is_absolute():
            raise ValueError("Legacy binding catalog path is invalid")
        self.path = path
        self.source_root = source_root
        self.store_id = store_id
        self.namespace_id = namespace_id
        self.scope_id = scope_id
        self.policy_revision = policy_revision
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    def publish_candidate(
        self,
        candidate: CodingLegacyLocalWheelCandidateV1,
        *,
        epoch_runtime: PackageProductPosixFencedRuntimeOwner,
    ) -> Path:
        """Stage verified inert bytes atomically under the exact B Source root."""

        if not isinstance(candidate, CodingLegacyLocalWheelCandidateV1):
            raise TypeError("Reacquired legacy Wheel candidate is required")
        if not isinstance(epoch_runtime, PackageProductPosixFencedRuntimeOwner):
            raise TypeError("Fenced Product epoch owner is required")
        switch = epoch_runtime.cutover_result.switch_receipt
        if (
            epoch_runtime.registry.store_id != self.store_id
            or switch is None
            or switch.namespace_id != self.namespace_id
            or epoch_runtime.prepare_product_source_root() != self.source_root
        ):
            raise CodingLegacyBindingError("Legacy Product Source epoch changed")
        body = candidate.wheel_bytes
        if (
            _WHEEL_FILENAME.fullmatch(candidate.filename) is None
            or not isinstance(body, bytes)
            or not body
            or len(body) > _MAX_WHEEL_BYTES
            or sha256(body).hexdigest() != candidate.artifact_digest
        ):
            raise CodingLegacyBindingError("Legacy Wheel candidate is invalid")
        with journal_file_lock(self.path, "exclusive"):
            epoch_runtime.assert_current()
            descriptor = os.open(
                self.source_root,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            try:
                root_before = os.fstat(descriptor)
                if (
                    not stat.S_ISDIR(root_before.st_mode)
                    or stat.S_IMODE(root_before.st_mode) & 0o077
                    or root_before.st_uid != os.geteuid()
                ):
                    raise CodingLegacyBindingError(
                        "Legacy Product Source root is not private"
                    )
                try:
                    os.stat(
                        candidate.filename, dir_fd=descriptor, follow_symlinks=False
                    )
                except FileNotFoundError:
                    self._publish_missing_candidate(descriptor, candidate, body)
                _verify_artifact(
                    self.source_root, candidate.filename, candidate.artifact_digest
                )
                with suppress(FileNotFoundError):
                    os.unlink(f".{candidate.filename}.staging", dir_fd=descriptor)
                    os.fsync(descriptor)
                root_after = self.source_root.lstat()
                if (
                    root_before.st_dev,
                    root_before.st_ino,
                    root_before.st_mode,
                    root_before.st_uid,
                ) != (
                    root_after.st_dev,
                    root_after.st_ino,
                    root_after.st_mode,
                    root_after.st_uid,
                ):
                    raise CodingLegacyBindingError(
                        "Legacy Product Source root changed on disk"
                    )
                epoch_runtime.assert_current()
                return self.source_root / candidate.filename
            finally:
                os.close(descriptor)

    @staticmethod
    def _publish_missing_candidate(
        directory: int, candidate: CodingLegacyLocalWheelCandidateV1, body: bytes
    ) -> None:
        staging_name = f".{candidate.filename}.staging"
        with suppress(FileNotFoundError):
            os.unlink(staging_name, dir_fd=directory)
        member = os.open(
            staging_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=directory,
        )
        try:
            os.fchmod(member, 0o600)
            remaining = memoryview(body)
            while remaining:
                written = os.write(member, remaining)
                if written <= 0:
                    raise OSError("Legacy Product Wheel write made no progress")
                remaining = remaining[written:]
            os.fsync(member)
        finally:
            os.close(member)
        try:
            with suppress(FileExistsError):
                os.link(
                    staging_name,
                    candidate.filename,
                    src_dir_fd=directory,
                    dst_dir_fd=directory,
                    follow_symlinks=False,
                )
            os.fsync(directory)
        finally:
            os.unlink(staging_name, dir_fd=directory)
            os.fsync(directory)

    def append(
        self,
        candidate: CodingLegacyLocalWheelCandidateV1,
        *,
        legacy_source_identity: str,
        legacy_binding_digest: str,
        dependency_lock_digest: str,
        approval_id: str,
    ) -> CodingLegacyLocalBindingV1:
        if not isinstance(candidate, CodingLegacyLocalWheelCandidateV1):
            raise TypeError("Reacquired legacy Wheel candidate is required")
        if sha256(candidate.wheel_bytes).hexdigest() != candidate.artifact_digest:
            raise CodingLegacyBindingError("Legacy Wheel candidate digest changed")
        _verify_artifact(
            self.source_root, candidate.filename, candidate.artifact_digest
        )
        with journal_file_lock(self.path, "exclusive"):
            records = self._load_unlocked()
            proposed = CodingLegacyLocalBindingV1.create(
                record_revision=len(records) + 1,
                store_id=self.store_id,
                namespace_id=self.namespace_id,
                scope_id=self.scope_id,
                legacy_source_identity=legacy_source_identity,
                legacy_binding_digest=legacy_binding_digest,
                dependency_lock_digest=dependency_lock_digest,
                policy_revision=self.policy_revision,
                approval_id=approval_id,
                candidate=candidate,
            )
            previous = next(
                (item for item in records if item.plugin_id == proposed.plugin_id), None
            )
            if previous is not None:
                ignored = {"recordRevision", "recordId"}
                proposed_payload = {
                    key: value
                    for key, value in proposed.to_dict().items()
                    if key not in ignored
                }
                previous_payload = {
                    key: value
                    for key, value in previous.to_dict().items()
                    if key not in ignored
                }
                if proposed_payload != previous_payload:
                    raise CodingLegacyBindingError(
                        "Legacy Product binding conflicts with prior approval"
                    )
                return previous
            append_jsonl_record(
                self.path,
                proposed,
                record_codec=_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return proposed

    def records(self) -> tuple[CodingLegacyLocalBindingV1, ...]:
        with journal_file_lock(self.path, "exclusive"):
            return self._load_unlocked()

    def extend_policy(
        self, base: PackageProductLocalWheelPolicy
    ) -> PackageProductLocalWheelPolicy:
        if (
            base.product_id != "coding"
            or base.source_root != self.source_root
            or base.project_scope_id != self.scope_id
            or base.policy_revision != self.policy_revision
        ):
            raise CodingLegacyBindingError("Legacy Product policy authority changed")
        records = self.records()
        used_ids = {item.plugin_id for item in base.bindings}
        for record in records:
            if record.plugin_id in used_ids:
                raise CodingLegacyBindingError(
                    "Legacy Product Plugin identity collides"
                )
            used_ids.add(record.plugin_id)
            _verify_artifact(
                self.source_root, record.wheel_filename, record.artifact_digest
            )
        return replace(
            base,
            bindings=tuple(
                sorted(
                    (
                        *base.bindings,
                        *(item.to_policy_binding(self.source_root) for item in records),
                    ),
                    key=lambda item: item.source_identity,
                )
            ),
        )

    def _load_unlocked(self) -> tuple[CodingLegacyLocalBindingV1, ...]:
        if not self.path.exists():
            return ()
        try:
            loaded: JsonlSnapshot[None, CodingLegacyLocalBindingV1] = load_jsonl(
                self.path,
                record_codec=_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
            records = loaded.records
            _require_unique_json_keys(self.path)
            identities: set[str] = set()
            for revision, record in enumerate(records, start=1):
                if (
                    record.record_revision != revision
                    or record.plugin_id in identities
                    or record.store_id != self.store_id
                    or record.namespace_id != self.namespace_id
                    or record.scope_id != self.scope_id
                    or record.policy_revision != self.policy_revision
                ):
                    raise ValueError("Legacy Product binding chain changed")
                identities.add(record.plugin_id)
            return records
        except (
            JournalFileError,
            JournalCodecError,
            OSError,
            UnicodeError,
            ValueError,
        ) as exc:
            raise CodingLegacyBindingError(
                "Legacy Product binding catalog is corrupt"
            ) from exc


def _verify_artifact(root: Path, filename: str, expected_digest: str) -> None:
    if os.name != "posix" or _WHEEL_FILENAME.fullmatch(filename) is None:
        raise CodingLegacyBindingError("Legacy Product Wheel identity is invalid")
    try:
        directory = os.open(
            root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
    except OSError as exc:
        raise CodingLegacyBindingError(
            "Legacy Product Source root is unavailable"
        ) from exc
    try:
        metadata = os.fstat(directory)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or metadata.st_uid != os.geteuid()
        ):
            raise CodingLegacyBindingError("Legacy Product Source root is not private")
        try:
            member = os.open(
                filename,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=directory,
            )
        except OSError as exc:
            raise CodingLegacyBindingError(
                "Legacy Product Wheel is unavailable"
            ) from exc
        try:
            before = os.fstat(member)
            if (
                not stat.S_ISREG(before.st_mode)
                or before.st_nlink != 1
                or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) & 0o077
                or before.st_size > _MAX_WHEEL_BYTES
            ):
                raise CodingLegacyBindingError("Legacy Product Wheel is unsafe")
            body = bytearray()
            while chunk := os.read(member, 64 * 1024):
                body.extend(chunk)
                if len(body) > _MAX_WHEEL_BYTES:
                    raise CodingLegacyBindingError(
                        "Legacy Product Wheel exceeds budget"
                    )
            after = os.fstat(member)
            try:
                visible = os.stat(filename, dir_fd=directory, follow_symlinks=False)
            except OSError as exc:
                raise CodingLegacyBindingError(
                    "Legacy Product Wheel changed on disk"
                ) from exc
            if (
                _file_identity(before) != _file_identity(after)
                or _file_identity(before) != _file_identity(visible)
                or sha256(body).hexdigest() != expected_digest
            ):
                raise CodingLegacyBindingError("Legacy Product Wheel changed on disk")
        finally:
            os.close(member)
    finally:
        os.close(directory)


def _file_identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_nlink,
        value.st_uid,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _require_unique_json_keys(path: Path) -> None:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                json.loads(line, object_pairs_hook=_unique_object)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Legacy Product binding has duplicate JSON keys")
        result[key] = value
    return result


__all__ = [
    "CodingLegacyBindingError",
    "CodingLegacyLocalBindingCatalog",
    "CodingLegacyLocalBindingV1",
]
