"""Platform-neutral exact plan for Coding Arch backup expiry."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)

from .package_private_data_backup_records import _digest


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataBackupExpiryPlanV1:
    installation_key: PluginInstallationKeyV1
    backup_id: str
    backup_receipt_id: str
    source_target_id: str
    confirmation_id: str
    restore_completion_digest: str
    restored_target_id: str
    desired_inventory_revision: int
    archive_root_identity: tuple[int, int, int, int, int]
    archive_target_id: str
    plan_version: int = 1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.installation_key, PluginInstallationKeyV1)
            or self.installation_key.plugin_id != "coding.arch.default"
            or not _digest(self.backup_id)
            or self.backup_receipt_id != "arch-backup:" + self.backup_id
            or not isinstance(self.source_target_id, str)
            or not self.source_target_id.startswith("present:")
            or not isinstance(self.confirmation_id, str)
            or not self.confirmation_id.startswith("arch-restore-confirm:")
            or not _digest(self.restore_completion_digest)
            or not isinstance(self.restored_target_id, str)
            or not self.restored_target_id.startswith("present:")
            or type(self.desired_inventory_revision) is not int
            or self.desired_inventory_revision < 0
            or type(self.archive_root_identity) is not tuple
            or len(self.archive_root_identity) != 5
            or any(
                type(item) is not int or item < 0 for item in self.archive_root_identity
            )
            or not isinstance(self.archive_target_id, str)
            or not self.archive_target_id.startswith("present:")
            or self.plan_version != 1
        ):
            raise ValueError("Coding Arch backup expiry plan is invalid")

    @property
    def fingerprint(self) -> str:
        return sha256(
            b"loushang.coding-arch-backup-expiry-plan/v1\0"
            + canonical_json_bytes(self.to_dict())
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return _SCHEMA_BACKUP_EXPIRY_PLAN_V1.encode(self, sort_keys=True)

    @classmethod
    def from_dict(cls, value: object) -> CodingArchPrivateDataBackupExpiryPlanV1:
        if type(value) is not dict or set(value) != _SCHEMA_BACKUP_EXPIRY_PLAN_V1.keys:
            raise ValueError("Coding Arch backup expiry plan fields are invalid")
        identity = value["archiveRootIdentity"]
        if type(identity) is not list:
            raise ValueError("Coding Arch backup expiry identity is invalid")
        return _SCHEMA_BACKUP_EXPIRY_PLAN_V1.decode(cls, value)


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataBackupExpiryConfirmationV1:
    plan_fingerprint: str
    actor_id: str
    policy_revision: str
    confirmation_id: str
    confirmation_version: int = 1

    def __post_init__(self) -> None:
        if (
            not _digest(self.plan_fingerprint)
            or not _label(self.actor_id)
            or not _label(self.policy_revision)
            or self.confirmation_id
            != _confirmation_id(
                self.plan_fingerprint, self.actor_id, self.policy_revision
            )
            or self.confirmation_version != 1
        ):
            raise ValueError("Coding Arch backup expiry confirmation is invalid")

    @classmethod
    def create(
        cls,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        *,
        actor_id: str,
        policy_revision: str,
    ) -> CodingArchPrivateDataBackupExpiryConfirmationV1:
        return cls(
            plan_fingerprint=plan.fingerprint,
            actor_id=actor_id,
            policy_revision=policy_revision,
            confirmation_id=_confirmation_id(
                plan.fingerprint, actor_id, policy_revision
            ),
        )

    def to_dict(self) -> dict[str, object]:
        return _SCHEMA_BACKUP_EXPIRY_CONFIRMATION_V1.encode(self, sort_keys=True)

    @classmethod
    def from_dict(
        cls, value: object
    ) -> CodingArchPrivateDataBackupExpiryConfirmationV1:
        if (
            type(value) is not dict
            or set(value) != _SCHEMA_BACKUP_EXPIRY_CONFIRMATION_V1.keys
        ):
            raise ValueError(
                "Coding Arch backup expiry confirmation fields are invalid"
            )
        return _SCHEMA_BACKUP_EXPIRY_CONFIRMATION_V1.decode(cls, value)


@dataclass(frozen=True, slots=True)
class CodingArchPrivateDataBackupExpiryReceiptV1:
    installation_key: PluginInstallationKeyV1
    backup_id: str
    plan_fingerprint: str
    confirmation_id: str
    receipt_id: str
    receipt_version: int = 1

    def __post_init__(self) -> None:
        if (
            not isinstance(self.installation_key, PluginInstallationKeyV1)
            or self.installation_key.plugin_id != "coding.arch.default"
            or not _digest(self.backup_id)
            or not _digest(self.plan_fingerprint)
            or not isinstance(self.confirmation_id, str)
            or not self.confirmation_id.startswith("arch-backup-expiry-confirm:")
            or self.receipt_id
            != _receipt_id(self.plan_fingerprint, self.confirmation_id)
            or self.receipt_version != 1
        ):
            raise ValueError("Coding Arch backup expiry receipt is invalid")

    @classmethod
    def create(
        cls,
        plan: CodingArchPrivateDataBackupExpiryPlanV1,
        confirmation: CodingArchPrivateDataBackupExpiryConfirmationV1,
    ) -> CodingArchPrivateDataBackupExpiryReceiptV1:
        return cls(
            installation_key=plan.installation_key,
            backup_id=plan.backup_id,
            plan_fingerprint=plan.fingerprint,
            confirmation_id=confirmation.confirmation_id,
            receipt_id=_receipt_id(plan.fingerprint, confirmation.confirmation_id),
        )

    def to_dict(self) -> dict[str, object]:
        return _SCHEMA_BACKUP_EXPIRY_RECEIPT_V1.encode(self, sort_keys=True)

    @classmethod
    def from_dict(cls, value: object) -> CodingArchPrivateDataBackupExpiryReceiptV1:
        if (
            type(value) is not dict
            or set(value) != _SCHEMA_BACKUP_EXPIRY_RECEIPT_V1.keys
        ):
            raise ValueError("Coding Arch backup expiry receipt fields are invalid")
        return _SCHEMA_BACKUP_EXPIRY_RECEIPT_V1.decode(cls, value)


def _confirmation_id(plan_fingerprint: str, actor_id: str, policy: str) -> str:
    return (
        "arch-backup-expiry-confirm:"
        + sha256(
            b"loushang.coding-arch-backup-expiry-confirmation/v1\0"
            + canonical_json_bytes(
                {
                    "actorId": actor_id,
                    "planFingerprint": plan_fingerprint,
                    "policyRevision": policy,
                }
            )
        ).hexdigest()
    )


def _receipt_id(plan_fingerprint: str, confirmation_id: str) -> str:
    return (
        "arch-backup-expiry:"
        + sha256(
            b"loushang.coding-arch-backup-expiry-receipt/v1\0"
            + canonical_json_bytes(
                {
                    "confirmationId": confirmation_id,
                    "planFingerprint": plan_fingerprint,
                }
            )
        ).hexdigest()
    )


def _label(value: object) -> bool:
    return (
        isinstance(value, str)
        and 0 < len(value) <= 128
        and value.strip() == value
        and all(character.isprintable() for character in value)
    )


_SCHEMA_BACKUP_EXPIRY_PLAN_V1 = RecordSchema.for_dataclass(
    CodingArchPrivateDataBackupExpiryPlanV1,
    lambda value: value,
    RecordField(
        "installation_key",
        decoder=PluginInstallationKeyV1.from_dict,
        encoder=PluginInstallationKeyV1.to_dict,
    ),
    RecordField("archive_root_identity", decoder=tuple, encoder=list),
)

_SCHEMA_BACKUP_EXPIRY_CONFIRMATION_V1 = RecordSchema.for_dataclass(
    CodingArchPrivateDataBackupExpiryConfirmationV1,
    lambda value: value,
)

_SCHEMA_BACKUP_EXPIRY_RECEIPT_V1 = RecordSchema.for_dataclass(
    CodingArchPrivateDataBackupExpiryReceiptV1,
    lambda value: value,
    RecordField(
        "installation_key",
        decoder=PluginInstallationKeyV1.from_dict,
        encoder=PluginInstallationKeyV1.to_dict,
    ),
)

__all__ = [
    "CodingArchPrivateDataBackupExpiryPlanV1",
    "CodingArchPrivateDataBackupExpiryConfirmationV1",
    "CodingArchPrivateDataBackupExpiryReceiptV1",
]
