"""Platform-neutral exact plan for Coding Arch backup expiry."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.plugin_management.records import PluginInstallationKeyV1
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
        return {
            "archiveRootIdentity": list(self.archive_root_identity),
            "archiveTargetId": self.archive_target_id,
            "backupId": self.backup_id,
            "backupReceiptId": self.backup_receipt_id,
            "confirmationId": self.confirmation_id,
            "desiredInventoryRevision": self.desired_inventory_revision,
            "installationKey": self.installation_key.to_dict(),
            "planVersion": self.plan_version,
            "restoreCompletionDigest": self.restore_completion_digest,
            "restoredTargetId": self.restored_target_id,
            "sourceTargetId": self.source_target_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingArchPrivateDataBackupExpiryPlanV1:
        if type(value) is not dict or set(value) != {
            "archiveRootIdentity",
            "archiveTargetId",
            "backupId",
            "backupReceiptId",
            "confirmationId",
            "desiredInventoryRevision",
            "installationKey",
            "planVersion",
            "restoreCompletionDigest",
            "restoredTargetId",
            "sourceTargetId",
        }:
            raise ValueError("Coding Arch backup expiry plan fields are invalid")
        identity = value["archiveRootIdentity"]
        if type(identity) is not list:
            raise ValueError("Coding Arch backup expiry identity is invalid")
        return cls(
            installation_key=PluginInstallationKeyV1.from_dict(
                value["installationKey"]
            ),
            backup_id=value["backupId"],
            backup_receipt_id=value["backupReceiptId"],
            source_target_id=value["sourceTargetId"],
            confirmation_id=value["confirmationId"],
            restore_completion_digest=value["restoreCompletionDigest"],
            restored_target_id=value["restoredTargetId"],
            desired_inventory_revision=value["desiredInventoryRevision"],
            archive_root_identity=tuple(identity),
            archive_target_id=value["archiveTargetId"],
            plan_version=value["planVersion"],
        )


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
        return {
            "actorId": self.actor_id,
            "confirmationId": self.confirmation_id,
            "confirmationVersion": self.confirmation_version,
            "planFingerprint": self.plan_fingerprint,
            "policyRevision": self.policy_revision,
        }

    @classmethod
    def from_dict(
        cls, value: object
    ) -> CodingArchPrivateDataBackupExpiryConfirmationV1:
        if type(value) is not dict or set(value) != {
            "actorId",
            "confirmationId",
            "confirmationVersion",
            "planFingerprint",
            "policyRevision",
        }:
            raise ValueError(
                "Coding Arch backup expiry confirmation fields are invalid"
            )
        return cls(
            plan_fingerprint=value["planFingerprint"],
            actor_id=value["actorId"],
            policy_revision=value["policyRevision"],
            confirmation_id=value["confirmationId"],
            confirmation_version=value["confirmationVersion"],
        )


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
        return {
            "backupId": self.backup_id,
            "confirmationId": self.confirmation_id,
            "installationKey": self.installation_key.to_dict(),
            "planFingerprint": self.plan_fingerprint,
            "receiptId": self.receipt_id,
            "receiptVersion": self.receipt_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingArchPrivateDataBackupExpiryReceiptV1:
        if type(value) is not dict or set(value) != {
            "backupId",
            "confirmationId",
            "installationKey",
            "planFingerprint",
            "receiptId",
            "receiptVersion",
        }:
            raise ValueError("Coding Arch backup expiry receipt fields are invalid")
        return cls(
            installation_key=PluginInstallationKeyV1.from_dict(
                value["installationKey"]
            ),
            backup_id=value["backupId"],
            plan_fingerprint=value["planFingerprint"],
            confirmation_id=value["confirmationId"],
            receipt_id=value["receiptId"],
            receipt_version=value["receiptVersion"],
        )


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


__all__ = [
    "CodingArchPrivateDataBackupExpiryPlanV1",
    "CodingArchPrivateDataBackupExpiryConfirmationV1",
    "CodingArchPrivateDataBackupExpiryReceiptV1",
]
