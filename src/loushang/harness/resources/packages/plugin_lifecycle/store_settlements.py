"""Durable Store-private settlement authority for PLC9B3e-3c3."""

from __future__ import annotations

import json
import re
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Literal

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
from loushang.harness.resources.packages.plugin_lifecycle.commit_records import (
    PluginRevisionRefV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.plugin_lifecycle.staging import (
    PackageArtifactStagingReceiptV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.tree_transfer import (
    PackageVerifiedTreeManifestV1,
)

PACKAGE_STORE_NATIVE_IDENTITY_VERSION = 1
PACKAGE_STORE_ENTRY_IDENTITY_VERSION = 1
PACKAGE_STORE_SETTLEMENT_RECORD_VERSION = 1

PackageStoreRole = Literal["dependency", "root"]
NativeIdentity = tuple[int, int]

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,255}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class PackageStoreSettlementJournalError(RuntimeError):
    """Fail-closed refusal of Store-private settlement evidence."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PackageStoreNativeIdentityV1:
    """One platform-native device/file identity without a pathname."""

    device_id: int
    file_id: int
    identity_version: int = PACKAGE_STORE_NATIVE_IDENTITY_VERSION

    def __post_init__(self) -> None:
        _require_nonnegative(self.device_id, name="native device identity")
        _require_nonnegative(self.file_id, name="native file identity")
        if self.identity_version != PACKAGE_STORE_NATIVE_IDENTITY_VERSION:
            raise ValueError("Unsupported Package Store native identity")

    @classmethod
    def from_native(cls, value: NativeIdentity) -> PackageStoreNativeIdentityV1:
        if (
            not isinstance(value, tuple)
            or len(value) != 2
            or isinstance(value[0], bool)
            or not isinstance(value[0], int)
            or isinstance(value[1], bool)
            or not isinstance(value[1], int)
        ):
            raise TypeError("Package Store native identity is invalid")
        return cls(device_id=value[0], file_id=value[1])

    def to_native(self) -> NativeIdentity:
        return (self.device_id, self.file_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "deviceId": self.device_id,
            "fileId": self.file_id,
            "identityVersion": self.identity_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageStoreNativeIdentityV1:
        document = _exact_dict(
            value,
            fields={"deviceId", "fileId", "identityVersion"},
            name="Package Store native identity",
        )
        return cls(
            device_id=_wire_int(document["deviceId"], name="native device identity"),
            file_id=_wire_int(document["fileId"], name="native file identity"),
            identity_version=_wire_int(
                document["identityVersion"], name="native identity version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageStoreEntryIdentityV1:
    """One manifest-relative member bound to its native identity."""

    logical_path: str
    native_identity: PackageStoreNativeIdentityV1
    entry_version: int = PACKAGE_STORE_ENTRY_IDENTITY_VERSION

    def __post_init__(self) -> None:
        _require_logical_path(self.logical_path)
        if not isinstance(self.native_identity, PackageStoreNativeIdentityV1):
            raise TypeError("Package Store entry native identity is required")
        if self.entry_version != PACKAGE_STORE_ENTRY_IDENTITY_VERSION:
            raise ValueError("Unsupported Package Store entry identity")

    def to_dict(self) -> dict[str, object]:
        return {
            "entryVersion": self.entry_version,
            "logicalPath": self.logical_path,
            "nativeIdentity": self.native_identity.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageStoreEntryIdentityV1:
        document = _exact_dict(
            value,
            fields={"entryVersion", "logicalPath", "nativeIdentity"},
            name="Package Store entry identity",
        )
        return cls(
            logical_path=_wire_string(
                document["logicalPath"], name="entry logical path"
            ),
            native_identity=PackageStoreNativeIdentityV1.from_dict(
                document["nativeIdentity"]
            ),
            entry_version=_wire_int(
                document["entryVersion"], name="entry identity version"
            ),
        )


@dataclass(frozen=True, slots=True)
class PackageStoreSettlementRecordV1:
    """Pre-rename authority for exactly one fully verified physical tree."""

    record_revision: int
    settlement_id: str
    store_role: PackageStoreRole
    store_identity: str
    root_identities: tuple[PackageStoreNativeIdentityV1, ...]
    tree_identity: PackageStoreNativeIdentityV1
    directory_identities: tuple[PackageStoreEntryIdentityV1, ...]
    file_identities: tuple[PackageStoreEntryIdentityV1, ...]
    final_name: str
    staging_name: str
    manifest: PackageVerifiedTreeManifestV1
    receipt: PackageArtifactStagingReceiptV1
    record_version: int = PACKAGE_STORE_SETTLEMENT_RECORD_VERSION

    def __post_init__(self) -> None:
        _require_positive(self.record_revision, name="settlement record revision")
        _require_sha256(self.settlement_id, name="Store settlement identity")
        if self.store_role not in {"dependency", "root"}:
            raise ValueError("Unsupported Package Store role")
        _require_safe_id(self.store_identity, name="Package Store identity")
        if not self.root_identities or not all(
            isinstance(identity, PackageStoreNativeIdentityV1)
            for identity in self.root_identities
        ):
            raise TypeError("Complete Package Store root identities are required")
        if not isinstance(self.tree_identity, PackageStoreNativeIdentityV1):
            raise TypeError("Package Store tree identity is required")
        _require_entry_identities(
            self.directory_identities,
            name="Package Store directory identities",
        )
        _require_entry_identities(
            self.file_identities,
            name="Package Store file identities",
        )
        _require_component(self.final_name, name="Package Store final name")
        _require_component(self.staging_name, name="Package Store staging name")
        if not isinstance(self.manifest, PackageVerifiedTreeManifestV1):
            raise TypeError("Package verified-tree manifest is required")
        if not isinstance(self.receipt, PackageArtifactStagingReceiptV1):
            raise TypeError("Package artifact staging receipt is required")
        _validate_settlement_binding(self)
        if self.record_version != PACKAGE_STORE_SETTLEMENT_RECORD_VERSION:
            raise ValueError("Unsupported Package Store settlement record")
        if self.settlement_id != _fingerprint(self._identity_dict()):
            raise ValueError("Package Store settlement identity does not match")

    @classmethod
    def create(
        cls,
        *,
        record_revision: int,
        store_role: PackageStoreRole,
        store_identity: str,
        root_identities: tuple[NativeIdentity, ...],
        tree_identity: NativeIdentity,
        directory_identities: dict[tuple[str, ...], NativeIdentity],
        file_identities: dict[tuple[str, ...], NativeIdentity],
        final_name: str,
        staging_name: str,
        manifest: PackageVerifiedTreeManifestV1,
        receipt: PackageArtifactStagingReceiptV1,
    ) -> PackageStoreSettlementRecordV1:
        values = _settlement_identity_dict(
            store_role=store_role,
            store_identity=store_identity,
            root_identities=tuple(
                PackageStoreNativeIdentityV1.from_native(value)
                for value in root_identities
            ),
            tree_identity=PackageStoreNativeIdentityV1.from_native(tree_identity),
            directory_identities=_entry_identities(directory_identities),
            file_identities=_entry_identities(file_identities),
            final_name=final_name,
            staging_name=staging_name,
            manifest=manifest,
            receipt=receipt,
            record_version=PACKAGE_STORE_SETTLEMENT_RECORD_VERSION,
        )
        return cls(
            record_revision=record_revision,
            settlement_id=_fingerprint(values),
            store_role=store_role,
            store_identity=store_identity,
            root_identities=tuple(
                PackageStoreNativeIdentityV1.from_native(value)
                for value in root_identities
            ),
            tree_identity=PackageStoreNativeIdentityV1.from_native(tree_identity),
            directory_identities=_entry_identities(directory_identities),
            file_identities=_entry_identities(file_identities),
            final_name=final_name,
            staging_name=staging_name,
            manifest=manifest,
            receipt=receipt,
        )

    def _identity_dict(self) -> dict[str, object]:
        return _settlement_identity_dict(
            store_role=self.store_role,
            store_identity=self.store_identity,
            root_identities=self.root_identities,
            tree_identity=self.tree_identity,
            directory_identities=self.directory_identities,
            file_identities=self.file_identities,
            final_name=self.final_name,
            staging_name=self.staging_name,
            manifest=self.manifest,
            receipt=self.receipt,
            record_version=self.record_version,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            **self._identity_dict(),
            "recordRevision": self.record_revision,
            "settlementId": self.settlement_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> PackageStoreSettlementRecordV1:
        document = _exact_dict(
            value,
            fields={
                "directoryIdentities",
                "fileIdentities",
                "finalName",
                "manifest",
                "receipt",
                "recordRevision",
                "recordVersion",
                "rootIdentities",
                "settlementId",
                "stagingName",
                "storeIdentity",
                "storeRole",
                "treeIdentity",
            },
            name="Package Store settlement record",
        )
        return cls(
            record_revision=_wire_int(
                document["recordRevision"], name="settlement record revision"
            ),
            settlement_id=_wire_string(
                document["settlementId"], name="Store settlement identity"
            ),
            store_role=_wire_role(document["storeRole"]),
            store_identity=_wire_string(
                document["storeIdentity"], name="Package Store identity"
            ),
            root_identities=_wire_native_identities(document["rootIdentities"]),
            tree_identity=PackageStoreNativeIdentityV1.from_dict(
                document["treeIdentity"]
            ),
            directory_identities=_wire_entry_identities(
                document["directoryIdentities"]
            ),
            file_identities=_wire_entry_identities(document["fileIdentities"]),
            final_name=_wire_string(
                document["finalName"], name="Package Store final name"
            ),
            staging_name=_wire_string(
                document["stagingName"], name="Package Store staging name"
            ),
            manifest=PackageVerifiedTreeManifestV1.from_dict(document["manifest"]),
            receipt=PackageArtifactStagingReceiptV1.from_dict(document["receipt"]),
            record_version=_wire_int(
                document["recordVersion"], name="settlement record version"
            ),
        )


def _encode_record(record: PackageStoreSettlementRecordV1) -> dict[str, object]:
    if not isinstance(record, PackageStoreSettlementRecordV1):
        raise TypeError("Package Store settlement record is required")
    return record.to_dict()


def _decode_record(value: object) -> PackageStoreSettlementRecordV1:
    try:
        return PackageStoreSettlementRecordV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Package Store settlement record is invalid",
            code="invalid_package_store_settlement_record",
        ) from exc


PACKAGE_STORE_SETTLEMENT_JOURNAL_CODEC = FunctionalJournalRecordCodec(
    encoder=_encode_record,
    decoder=_decode_record,
)


class PackageStoreSettlementJournal:
    """Append pre-rename authority and verify exact durable reuse."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path).resolve()
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def owner_lock(self) -> AbstractContextManager[None]:
        """Serialize physical namespace ownership across Store instances."""

        return journal_file_lock(self._path, "exclusive", lock_suffix=".owner.lock")

    def validate_store_root(
        self,
        *,
        store_role: PackageStoreRole,
        store_identity: str,
        root_identities: tuple[NativeIdentity, ...],
    ) -> None:
        expected = tuple(
            PackageStoreNativeIdentityV1.from_native(value)
            for value in root_identities
        )
        with self._exclusive():
            self._require_store_binding(
                self._load_unlocked(),
                store_role=store_role,
                store_identity=store_identity,
                root_identities=expected,
            )

    def authorize(
        self,
        *,
        store_role: PackageStoreRole,
        store_identity: str,
        root_identities: tuple[NativeIdentity, ...],
        tree_identity: NativeIdentity,
        directory_identities: dict[tuple[str, ...], NativeIdentity],
        file_identities: dict[tuple[str, ...], NativeIdentity],
        final_name: str,
        staging_name: str,
        manifest: PackageVerifiedTreeManifestV1,
        receipt: PackageArtifactStagingReceiptV1,
    ) -> PackageStoreSettlementRecordV1:
        with self._exclusive():
            records = self._load_unlocked()
            expected_root = tuple(
                PackageStoreNativeIdentityV1.from_native(value)
                for value in root_identities
            )
            self._require_store_binding(
                records,
                store_role=store_role,
                store_identity=store_identity,
                root_identities=expected_root,
            )
            candidate = PackageStoreSettlementRecordV1.create(
                record_revision=len(records) + 1,
                store_role=store_role,
                store_identity=store_identity,
                root_identities=root_identities,
                tree_identity=tree_identity,
                directory_identities=directory_identities,
                file_identities=file_identities,
                final_name=final_name,
                staging_name=staging_name,
                manifest=manifest,
                receipt=receipt,
            )
            existing = next(
                (
                    record
                    for record in records
                    if record.settlement_id == candidate.settlement_id
                ),
                None,
            )
            if existing is not None:
                return existing
            for record in records:
                if (
                    record.store_role == store_role
                    and record.store_identity == store_identity
                    and record.final_name == final_name
                    and (
                        record.manifest != manifest
                        or record.receipt != receipt
                        or record.staging_name != staging_name
                    )
                ):
                    raise self._error(
                        "Package Store final identity changed",
                        code="package_store_settlement_identity_conflict",
                    )
            append_jsonl_record(
                self._path,
                candidate,
                record_codec=PACKAGE_STORE_SETTLEMENT_JOURNAL_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
            )
            return candidate

    def authorizes(
        self,
        *,
        store_role: PackageStoreRole,
        store_identity: str,
        root_identities: tuple[NativeIdentity, ...],
        tree_identity: NativeIdentity,
        directory_identities: dict[tuple[str, ...], NativeIdentity],
        file_identities: dict[tuple[str, ...], NativeIdentity],
        final_name: str,
        staging_name: str,
        manifest: PackageVerifiedTreeManifestV1,
        receipt: PackageArtifactStagingReceiptV1,
    ) -> bool:
        probe = PackageStoreSettlementRecordV1.create(
            record_revision=1,
            store_role=store_role,
            store_identity=store_identity,
            root_identities=root_identities,
            tree_identity=tree_identity,
            directory_identities=directory_identities,
            file_identities=file_identities,
            final_name=final_name,
            staging_name=staging_name,
            manifest=manifest,
            receipt=receipt,
        )
        with self._exclusive():
            records = self._load_unlocked()
            self._require_store_binding(
                records,
                store_role=store_role,
                store_identity=store_identity,
                root_identities=probe.root_identities,
            )
            return any(record.settlement_id == probe.settlement_id for record in records)

    def records(self) -> tuple[PackageStoreSettlementRecordV1, ...]:
        with self._exclusive():
            return self._load_unlocked()

    def settlements_for_receipt(
        self,
        *,
        store_role: PackageStoreRole,
        store_identity: str,
        root_identities: tuple[NativeIdentity, ...],
        receipt: PackageArtifactStagingReceiptV1,
    ) -> tuple[PackageStoreSettlementRecordV1, ...]:
        if not isinstance(receipt, PackageArtifactStagingReceiptV1):
            raise TypeError("Package artifact staging receipt is required")
        expected_root = tuple(
            PackageStoreNativeIdentityV1.from_native(value)
            for value in root_identities
        )
        with self._exclusive():
            records = self._load_unlocked()
            self._require_store_binding(
                records,
                store_role=store_role,
                store_identity=store_identity,
                root_identities=expected_root,
            )
            return tuple(
                record
                for record in records
                if record.store_role == store_role
                and record.store_identity == store_identity
                and record.root_identities == expected_root
                and record.receipt == receipt
            )

    def _load_unlocked(self) -> tuple[PackageStoreSettlementRecordV1, ...]:
        if not self._path.exists():
            return ()
        try:
            snapshot: JsonlSnapshot[None, PackageStoreSettlementRecordV1] = load_jsonl(
                self._path,
                record_codec=PACKAGE_STORE_SETTLEMENT_JOURNAL_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
            records = snapshot.records
            _assert_no_duplicate_json_keys(self._path)
            _validate_records(records)
            return records
        except (JournalCodecError, JournalFileError, TypeError, ValueError) as exc:
            raise self._error(
                "Package Store settlement journal is corrupt",
                code="package_store_settlement_journal_corrupt",
            ) from exc

    def _exclusive(self) -> AbstractContextManager[None]:
        return journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        )

    def _require_store_binding(
        self,
        records: tuple[PackageStoreSettlementRecordV1, ...],
        *,
        store_role: PackageStoreRole,
        store_identity: str,
        root_identities: tuple[PackageStoreNativeIdentityV1, ...],
    ) -> None:
        try:
            _validate_store_binding(
                records,
                store_role=store_role,
                store_identity=store_identity,
                root_identities=root_identities,
            )
        except ValueError as exc:
            raise self._error(
                "Package Store root identity changed",
                code="package_store_root_identity_conflict",
            ) from exc

    def _error(
        self,
        message: str,
        *,
        code: str,
    ) -> PackageStoreSettlementJournalError:
        return PackageStoreSettlementJournalError(
            message,
            code=code,
            path=self._path,
        )


def _validate_settlement_binding(record: PackageStoreSettlementRecordV1) -> None:
    request = record.receipt.staging_request
    stable_ref = record.receipt.stable_ref
    manifest = record.manifest
    expected_role = "root" if isinstance(stable_ref, PluginRevisionRefV1) else "dependency"
    if (
        record.store_role != expected_role
        or stable_ref.store_identity != record.store_identity
        or stable_ref.store_revision != f"tree:{manifest.manifest_id}"
        or request.operation_id != manifest.operation_id
        or request.attempt_epoch != manifest.attempt_epoch
        or request.node_id != manifest.node_id
        or request.plan_node.distribution != manifest.distribution
        or request.plan_node.version != manifest.version
        or request.plan_node.wheel_evidence_fingerprint
        != manifest.wheel_evidence_fingerprint
        or request.plan_node.artifact_digest != manifest.artifact_digest
        or request.plan_node.extraction_tree_digest != manifest.extraction_tree_digest
    ):
        raise ValueError("Package Store settlement changed verified identity")
    prefix = "revision" if record.store_role == "root" else "artifact"
    if (
        record.final_name != f"{prefix}-{stable_ref.ref_id}"
        or record.staging_name != f"staging-{request.staging_request_id}"
    ):
        raise ValueError("Package Store settlement namespace changed")
    expected_files = tuple(entry.logical_path for entry in manifest.entries)
    expected_directories = tuple(
        sorted(
            {
                "/".join(parts[:depth])
                for logical_path in expected_files
                for parts in (tuple(logical_path.split("/")),)
                for depth in range(1, len(parts))
            },
            key=lambda value: tuple(value.split("/")),
        )
    )
    if (
        tuple(item.logical_path for item in record.file_identities) != expected_files
        or tuple(item.logical_path for item in record.directory_identities)
        != expected_directories
    ):
        raise ValueError("Package Store settlement member identities changed")


def _validate_records(records: tuple[PackageStoreSettlementRecordV1, ...]) -> None:
    settlements: set[str] = set()
    roots: dict[
        tuple[PackageStoreRole, str], tuple[PackageStoreNativeIdentityV1, ...]
    ] = {}
    final_bindings: dict[
        tuple[PackageStoreRole, str, str],
        tuple[PackageVerifiedTreeManifestV1, PackageArtifactStagingReceiptV1, str],
    ] = {}
    for revision, record in enumerate(records, start=1):
        if record.record_revision != revision:
            raise ValueError("Package Store settlement revisions are not contiguous")
        if record.settlement_id in settlements:
            raise ValueError("Package Store settlement was recorded twice")
        settlements.add(record.settlement_id)
        root_key = (record.store_role, record.store_identity)
        previous_root = roots.setdefault(root_key, record.root_identities)
        if previous_root != record.root_identities:
            raise ValueError("Package Store identity moved to another root")
        final_key = (record.store_role, record.store_identity, record.final_name)
        binding = (record.manifest, record.receipt, record.staging_name)
        previous_binding = final_bindings.setdefault(final_key, binding)
        if previous_binding != binding:
            raise ValueError("Package Store final name changed identity")


def _validate_store_binding(
    records: tuple[PackageStoreSettlementRecordV1, ...],
    *,
    store_role: PackageStoreRole,
    store_identity: str,
    root_identities: tuple[PackageStoreNativeIdentityV1, ...],
) -> None:
    if store_role not in {"dependency", "root"}:
        raise ValueError("Unsupported Package Store role")
    _require_safe_id(store_identity, name="Package Store identity")
    if not root_identities:
        raise ValueError("Complete Package Store root identities are required")
    for record in records:
        if (
            record.store_role == store_role
            and record.store_identity == store_identity
            and record.root_identities != root_identities
        ):
            raise ValueError("Package Store root identity changed")


def _settlement_identity_dict(
    *,
    store_role: PackageStoreRole,
    store_identity: str,
    root_identities: tuple[PackageStoreNativeIdentityV1, ...],
    tree_identity: PackageStoreNativeIdentityV1,
    directory_identities: tuple[PackageStoreEntryIdentityV1, ...],
    file_identities: tuple[PackageStoreEntryIdentityV1, ...],
    final_name: str,
    staging_name: str,
    manifest: PackageVerifiedTreeManifestV1,
    receipt: PackageArtifactStagingReceiptV1,
    record_version: int,
) -> dict[str, object]:
    return {
        "directoryIdentities": [value.to_dict() for value in directory_identities],
        "fileIdentities": [value.to_dict() for value in file_identities],
        "finalName": final_name,
        "manifest": manifest.to_dict(),
        "receipt": receipt.to_dict(),
        "recordVersion": record_version,
        "rootIdentities": [value.to_dict() for value in root_identities],
        "stagingName": staging_name,
        "storeIdentity": store_identity,
        "storeRole": store_role,
        "treeIdentity": tree_identity.to_dict(),
    }


def _entry_identities(
    values: dict[tuple[str, ...], NativeIdentity],
) -> tuple[PackageStoreEntryIdentityV1, ...]:
    if not isinstance(values, dict):
        raise TypeError("Package Store entry identities must be a mapping")
    return tuple(
        PackageStoreEntryIdentityV1(
            logical_path="/".join(parts),
            native_identity=PackageStoreNativeIdentityV1.from_native(identity),
        )
        for parts, identity in sorted(values.items(), key=lambda item: item[0])
    )


def _require_entry_identities(
    values: tuple[PackageStoreEntryIdentityV1, ...],
    *,
    name: str,
) -> None:
    if not isinstance(values, tuple) or not all(
        isinstance(value, PackageStoreEntryIdentityV1) for value in values
    ):
        raise TypeError(f"{name} are invalid")
    paths = tuple(value.logical_path for value in values)
    if paths != tuple(sorted(paths, key=lambda value: tuple(value.split("/")))):
        raise ValueError(f"{name} are not canonical")
    if len(set(paths)) != len(paths):
        raise ValueError(f"{name} contain duplicate paths")


def _wire_native_identities(
    value: object,
) -> tuple[PackageStoreNativeIdentityV1, ...]:
    if not isinstance(value, list):
        raise TypeError("Package Store root identities must be an array")
    return tuple(PackageStoreNativeIdentityV1.from_dict(item) for item in value)


def _wire_entry_identities(
    value: object,
) -> tuple[PackageStoreEntryIdentityV1, ...]:
    if not isinstance(value, list):
        raise TypeError("Package Store entry identities must be an array")
    return tuple(PackageStoreEntryIdentityV1.from_dict(item) for item in value)


def _fingerprint(value: dict[str, object]) -> str:
    return sha256(canonical_json_bytes(value)).hexdigest()


def _exact_dict(
    value: object,
    *,
    fields: set[str],
    name: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields or not all(
        isinstance(key, str) for key in value
    ):
        raise TypeError(f"{name} is invalid")
    return value


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{name} must be text")
    return value


def _wire_int(value: object, *, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an integer")
    return value


def _wire_role(value: object) -> PackageStoreRole:
    if value == "dependency":
        return "dependency"
    if value == "root":
        return "root"
    raise ValueError("Unsupported Package Store role")


def _require_positive(value: int, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{name} must be positive")


def _require_nonnegative(value: int, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be non-negative")


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ValueError(f"{name} must be lowercase SHA-256")


def _require_safe_id(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")


def _require_component(value: str, *, name: str) -> None:
    if not isinstance(value, str) or _SAFE_COMPONENT.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")


def _require_logical_path(value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value.startswith("/")
        or value.endswith("/")
        or "//" in value
        or "\\" in value
        or "\x00" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
    ):
        raise ValueError("Package Store entry logical path is invalid")


def _assert_no_duplicate_json_keys(path: Path) -> None:
    def reject(pairs: list[tuple[str, object]]) -> dict[str, object]:
        document: dict[str, object] = {}
        for key, value in pairs:
            if key in document:
                raise ValueError("Package Store settlement record repeats a key")
            document[key] = value
        return document

    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                json.loads(line, object_pairs_hook=reject)


__all__ = [
    "PACKAGE_STORE_ENTRY_IDENTITY_VERSION",
    "PACKAGE_STORE_NATIVE_IDENTITY_VERSION",
    "PACKAGE_STORE_SETTLEMENT_JOURNAL_CODEC",
    "PACKAGE_STORE_SETTLEMENT_RECORD_VERSION",
    "PackageStoreEntryIdentityV1",
    "PackageStoreNativeIdentityV1",
    "PackageStoreSettlementJournal",
    "PackageStoreSettlementJournalError",
    "PackageStoreSettlementRecordV1",
]
