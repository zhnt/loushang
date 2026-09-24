"""Confirmed delegation to an exact Plugin-private-data domain owner.

The coordinator has no filesystem or GC authority. The injected domain owner
must revalidate the plan at mutation time and durably record its own receipt.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Protocol

from loushang.harness.plugin_management.records import PluginInstallationKeyV1

PRIVATE_DATA_DELETION_VERSION = 1
PrivateDataDeletionDisposition = Literal["deleted", "already_absent"]


def _require_text(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty")


def _require_sha256(value: str, *, name: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


@dataclass(frozen=True, slots=True)
class PluginPrivateDataDeletionPlanV1:
    installation_key: PluginInstallationKeyV1
    owner_id: str
    target_id: str
    plan_version: int = PRIVATE_DATA_DELETION_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.installation_key, PluginInstallationKeyV1):
            raise TypeError("Private-data deletion requires an Installation key")
        _require_text(self.owner_id, name="private-data owner id")
        _require_text(self.target_id, name="private-data target id")
        if self.plan_version != PRIVATE_DATA_DELETION_VERSION:
            raise ValueError("Unsupported private-data deletion plan")

    @property
    def fingerprint(self) -> str:
        document = json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        return hashlib.sha256(
            b"loushang.plugin-private-data-deletion-plan/v1\0" + document
        ).hexdigest()

    def to_dict(self) -> dict[str, object]:
        return {
            "installationKey": self.installation_key.to_dict(),
            "ownerId": self.owner_id,
            "planVersion": self.plan_version,
            "targetId": self.target_id,
        }


@dataclass(frozen=True, slots=True)
class PluginPrivateDataDeletionConfirmationV1:
    """Separate operator confirmation bound to one exact previewed plan."""

    plan_fingerprint: str
    confirmation_id: str
    confirmation_version: int = PRIVATE_DATA_DELETION_VERSION

    def __post_init__(self) -> None:
        _require_sha256(self.plan_fingerprint, name="confirmed plan fingerprint")
        _require_text(self.confirmation_id, name="private-data confirmation id")
        if self.confirmation_version != PRIVATE_DATA_DELETION_VERSION:
            raise ValueError("Unsupported private-data deletion confirmation")


@dataclass(frozen=True, slots=True)
class PluginPrivateDataDeletionReceiptV1:
    """Domain-owned durable result; Package GC cannot issue this receipt."""

    installation_key: PluginInstallationKeyV1
    owner_id: str
    target_id: str
    plan_fingerprint: str
    confirmation_id: str
    receipt_id: str
    disposition: PrivateDataDeletionDisposition
    receipt_version: int = PRIVATE_DATA_DELETION_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.installation_key, PluginInstallationKeyV1):
            raise TypeError("Private-data receipt requires an Installation key")
        for value, name in (
            (self.owner_id, "private-data owner id"),
            (self.target_id, "private-data target id"),
            (self.confirmation_id, "private-data confirmation id"),
            (self.receipt_id, "private-data receipt id"),
        ):
            _require_text(value, name=name)
        _require_sha256(self.plan_fingerprint, name="private-data plan fingerprint")
        if self.disposition not in {"deleted", "already_absent"}:
            raise ValueError("Unsupported private-data deletion disposition")
        if self.receipt_version != PRIVATE_DATA_DELETION_VERSION:
            raise ValueError("Unsupported private-data deletion receipt")

    def to_dict(self) -> dict[str, object]:
        return {
            "confirmationId": self.confirmation_id,
            "disposition": self.disposition,
            "installationKey": self.installation_key.to_dict(),
            "ownerId": self.owner_id,
            "planFingerprint": self.plan_fingerprint,
            "receiptId": self.receipt_id,
            "receiptVersion": self.receipt_version,
            "targetId": self.target_id,
        }


class PluginPrivateDataDeletionOwnerPort(Protocol):
    """Exact data-domain owner, responsible for mutation and durable replay."""

    def plan_for(
        self, key: PluginInstallationKeyV1
    ) -> PluginPrivateDataDeletionPlanV1: ...

    def delete_confirmed(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> PluginPrivateDataDeletionReceiptV1: ...


class PluginPrivateDataConfirmationAuthorityPort(Protocol):
    """Product/operator authority that verifies an independently issued confirmation."""

    def is_confirmed(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> bool: ...


class PluginPrivateDataDeletionCoordinator:
    """Validates a separate confirmation and delegates; never deletes itself."""

    def __init__(
        self,
        owner: PluginPrivateDataDeletionOwnerPort,
        *,
        confirmation_authority: PluginPrivateDataConfirmationAuthorityPort,
    ) -> None:
        if not all(
            callable(getattr(owner, name, None))
            for name in ("plan_for", "delete_confirmed")
        ):
            raise TypeError("Private-data deletion domain owner is required")
        if not callable(getattr(confirmation_authority, "is_confirmed", None)):
            raise TypeError("Private-data confirmation authority is required")
        self._owner = owner
        self._confirmation_authority = confirmation_authority

    def preview(self, key: PluginInstallationKeyV1) -> PluginPrivateDataDeletionPlanV1:
        if not isinstance(key, PluginInstallationKeyV1):
            raise TypeError("Private-data deletion requires an Installation key")
        plan = self._owner.plan_for(key)
        if not isinstance(plan, PluginPrivateDataDeletionPlanV1):
            raise TypeError("Private-data owner must return a deletion plan")
        if plan.installation_key != key:
            raise ValueError("Private-data owner returned a foreign plan")
        return plan

    def delete(
        self,
        plan: PluginPrivateDataDeletionPlanV1,
        confirmation: PluginPrivateDataDeletionConfirmationV1,
    ) -> PluginPrivateDataDeletionReceiptV1:
        if not isinstance(plan, PluginPrivateDataDeletionPlanV1):
            raise TypeError("Private-data deletion plan is required")
        if not isinstance(confirmation, PluginPrivateDataDeletionConfirmationV1):
            raise TypeError("Separate private-data deletion confirmation is required")
        if confirmation.plan_fingerprint != plan.fingerprint:
            raise ValueError("Private-data confirmation does not match the plan")
        if self.preview(plan.installation_key) != plan:
            raise ValueError("Private-data deletion plan is stale")
        if self._confirmation_authority.is_confirmed(plan, confirmation) is not True:
            raise ValueError("Private-data confirmation is not authorized")
        receipt = self._owner.delete_confirmed(plan, confirmation)
        if not isinstance(receipt, PluginPrivateDataDeletionReceiptV1) or (
            receipt.installation_key != plan.installation_key
            or receipt.owner_id != plan.owner_id
            or receipt.target_id != plan.target_id
            or receipt.plan_fingerprint != plan.fingerprint
            or receipt.confirmation_id != confirmation.confirmation_id
        ):
            raise ValueError("Private-data owner returned a mismatched receipt")
        return receipt


__all__ = [
    "PRIVATE_DATA_DELETION_VERSION",
    "PluginPrivateDataDeletionConfirmationV1",
    "PluginPrivateDataConfirmationAuthorityPort",
    "PluginPrivateDataDeletionCoordinator",
    "PluginPrivateDataDeletionOwnerPort",
    "PluginPrivateDataDeletionPlanV1",
    "PluginPrivateDataDeletionReceiptV1",
]
