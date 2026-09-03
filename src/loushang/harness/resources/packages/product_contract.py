"""Transport-neutral PLC9A2 Product package lifecycle contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, TypeAlias

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleAction,
    PackageLifecycleDisposition,
    PackageLifecyclePhase,
    PackageLifecycleStatusV1,
)

PACKAGE_PRODUCT_INTENT_VERSION = 1
PACKAGE_PRODUCT_OUTCOME_VERSION = 1
PACKAGE_PRODUCT_RECORD_VERSION = 1

PackageProductLifecycleAction: TypeAlias = PackageLifecycleAction
PackageProductEntrypoint = Literal[
    "cli",
    "rpc",
    "session",
    "startup",
    "operations",
    "direct_materializer",
]
PackageProductRoutingDisposition = Literal["plugin_handled", "non_plugin"]


@dataclass(frozen=True, slots=True)
class PackageProductLifecycleIntentV1:
    """One transport-neutral package intent; provenance is carried separately."""

    operation_id: str
    action: PackageProductLifecycleAction
    source: str
    scope: str
    intent_version: int = PACKAGE_PRODUCT_INTENT_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.operation_id, "Package Product operation id"),
            (self.source, "Package Product source"),
            (self.scope, "Package Product scope"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty")
        if self.action not in {
            "materialize",
            "install",
            "update",
            "remove",
            "uninstall",
        }:
            raise ValueError("Unsupported Package Product action")
        if self.intent_version != PACKAGE_PRODUCT_INTENT_VERSION:
            raise ValueError("Unsupported Package Product intent")


@dataclass(frozen=True, slots=True)
class PackageProductLifecycleRecordV1:
    """Pathless compatibility projection of one PLC9B terminal status."""

    operation_id: str
    action: PackageProductLifecycleAction
    source_identity: str
    name: str
    lifecycle: Literal["installed", "remote_registered", "failed"]
    phase: PackageLifecyclePhase
    disposition: PackageLifecycleDisposition
    failure_code: str | None
    record_version: int = PACKAGE_PRODUCT_RECORD_VERSION

    def __post_init__(self) -> None:
        for value, name in (
            (self.operation_id, "Package Product operation id"),
            (self.source_identity, "Package Product source identity"),
            (self.name, "Package Product name"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty")
        if self.lifecycle == "failed":
            if self.failure_code is None:
                raise ValueError("Failed Package Product record requires a code")
        elif self.failure_code is not None:
            raise ValueError("Successful Package Product record cannot carry a code")
        if self.record_version != PACKAGE_PRODUCT_RECORD_VERSION:
            raise ValueError("Unsupported Package Product record")

    @property
    def source(self) -> str:
        return self.source_identity

    @property
    def error_message(self) -> str | None:
        return self.failure_code

    @property
    def security(self) -> Literal["allowed", "denied"]:
        return "denied" if self.lifecycle == "failed" else "allowed"

    @property
    def source_type(self) -> Literal["plugin"]:
        return "plugin"

    @classmethod
    def from_status(
        cls,
        intent: PackageProductLifecycleIntentV1,
        status: PackageLifecycleStatusV1,
    ) -> PackageProductLifecycleRecordV1:
        classification = status.classification
        if classification is None or classification.decision == "non_plugin":
            raise ValueError("Plugin Product record requires Plugin classification")
        failure = status.failure
        succeeded = status.disposition == "committed"
        lifecycle: Literal["installed", "remote_registered", "failed"]
        if not succeeded:
            lifecycle = "failed"
        elif intent.action in {"remove", "uninstall"}:
            lifecycle = "remote_registered"
        else:
            lifecycle = "installed"
        return cls(
            operation_id=status.operation_id,
            action=intent.action,
            source_identity=classification.canonical_source_identity,
            name=classification.canonical_source_identity,
            lifecycle=lifecycle,
            phase=status.phase,
            disposition=status.disposition,
            failure_code=(
                None
                if succeeded
                else (failure.code if failure else "package_lifecycle_incomplete")
            ),
        )

    def to_dict(self) -> dict[str, object]:
        """Project without a filesystem path, live handle, or raw source locator."""

        return {
            "action": self.action,
            "errorCode": self.failure_code or "",
            "errorMessage": self.failure_code or "",
            "kind": "plugin_package",
            "lifecycle": self.lifecycle,
            "name": self.name,
            "operationId": self.operation_id,
            "packageLifecycleDisposition": self.disposition,
            "packageLifecyclePhase": self.phase,
            "path": "",
            "recordVersion": self.record_version,
            "source": self.source_identity,
        }


@dataclass(frozen=True, slots=True)
class PackageProductLifecycleOutcomeV1:
    """Exact split between handled Plugin work and explicit non-Plugin work."""

    routing_disposition: PackageProductRoutingDisposition
    status: PackageLifecycleStatusV1
    record: PackageProductLifecycleRecordV1 | None
    outcome_version: int = PACKAGE_PRODUCT_OUTCOME_VERSION

    def __post_init__(self) -> None:
        classification = self.status.classification
        if classification is None:
            raise ValueError("Package Product outcome requires classification")
        if self.routing_disposition == "non_plugin":
            if classification.decision != "non_plugin" or self.record is not None:
                raise ValueError("Non-Plugin outcome is inconsistent")
            if self.status.phase != "classified" or self.status.disposition != "active":
                raise ValueError("Non-Plugin outcome must retain classified evidence")
        elif self.routing_disposition == "plugin_handled":
            if classification.decision == "non_plugin" or self.record is None:
                raise ValueError("Plugin outcome is inconsistent")
            if (
                self.record.operation_id != self.status.operation_id
                or self.record.source_identity
                != classification.canonical_source_identity
                or self.record.phase != self.status.phase
                or self.record.disposition != self.status.disposition
            ):
                raise ValueError("Plugin Product record changed lifecycle evidence")
        else:
            raise ValueError("Unsupported Package Product routing disposition")
        if self.outcome_version != PACKAGE_PRODUCT_OUTCOME_VERSION:
            raise ValueError("Unsupported Package Product outcome")

    @property
    def handled(self) -> bool:
        return self.routing_disposition == "plugin_handled"


class PackageProductLifecycleOperationPort(Protocol):
    """The sole Product-facing operation port used by every transport."""

    def route(
        self,
        intent: PackageProductLifecycleIntentV1,
        *,
        entrypoint: PackageProductEntrypoint,
    ) -> PackageProductLifecycleOutcomeV1: ...


__all__ = [
    "PACKAGE_PRODUCT_INTENT_VERSION",
    "PACKAGE_PRODUCT_OUTCOME_VERSION",
    "PACKAGE_PRODUCT_RECORD_VERSION",
    "PackageProductEntrypoint",
    "PackageProductLifecycleAction",
    "PackageProductLifecycleIntentV1",
    "PackageProductLifecycleOperationPort",
    "PackageProductLifecycleOutcomeV1",
    "PackageProductLifecycleRecordV1",
    "PackageProductRoutingDisposition",
]
