"""Read-only A2 Package and A1 Management operation correlation.

Matching operation and Installation identities do not prove Product handoff,
selection, or Session consumption. Those owners need their own evidence.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol

from loushang.harness.plugin_management.application import (
    PluginManagementApplicationResultV1,
)
from loushang.harness.plugin_management.operations import PluginManagementCommandV1
from loushang.harness.plugin_management.package_operation_explanation import (
    PackageOperationExplanationProjector,
    PackageOperationExplanationV1,
    PackageOperationReadPort,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.plugin_management.updates import PluginManagementUpdateCommandV2
from loushang.harness.resources.packages.plugin_lifecycle.retention_handoff import (
    PackageDesiredStateCommitRequestV1,
    PackageRetentionHandoffReceiptV1,
)
from loushang.harness.resources.packages.product_handoff import (
    package_product_command_identity,
)

PLUGIN_OPERATION_EXPLANATION_VERSION = 1


@dataclass(frozen=True, slots=True)
class PluginOperationExplanationRequestV1:
    correlation_id: str
    product_id: str
    scope_id: str
    operation_id: str

    def __post_init__(self) -> None:
        for name in ("correlation_id", "product_id", "scope_id", "operation_id"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"Plugin operation explanation {name} is invalid")


class PluginManagementOperationReadPort(Protocol):
    def operation(
        self, operation_id: str, *, correlation_id: str
    ) -> PluginManagementApplicationResultV1 | None: ...


class PackageProductHandoffReadPort(Protocol):
    def read_operation(
        self, operation_id: str
    ) -> PackageRetentionHandoffReceiptV1 | None: ...


class PluginOperationExplanationQueryPort(Protocol):
    def explain_plugin_operation(
        self, request: PluginOperationExplanationRequestV1
    ) -> PluginOperationExplanationV1: ...


@dataclass(frozen=True, slots=True)
class PluginOperationExplanationV1:
    correlation_id: str
    operation_id: str
    management_operation_id: str
    observed_at_unix_ns: int
    package: PackageOperationExplanationV1
    management_status: Literal["observed", "unknown"]
    management_installation_key: PluginInstallationKeyV1 | None
    management_action: str | None
    management_actor_id: str | None
    management_progress_code: str | None
    management_disposition: str | None
    management_journal_revision: int | None
    handoff_evidence: Literal[
        "not_queried", "absent", "incomplete", "settled", "identity_conflict"
    ]
    handoff_receipt_id: str | None
    handoff_revision: int | None
    join_status: Literal[
        "same_identity",
        "package_only",
        "management_only",
        "unknown",
        "identity_conflict",
    ]
    evidence_gaps: tuple[str, ...]
    desired_commit_evidence: Literal[
        "not_checked", "owner_receipt", "verified_transition"
    ] = "not_checked"
    repair_command: str | None = None
    snapshot_status: Literal["partial_evidence"] = "partial_evidence"
    explanation_version: int = PLUGIN_OPERATION_EXPLANATION_VERSION

    def __post_init__(self) -> None:
        if (
            not self.correlation_id
            or not self.operation_id
            or not self.management_operation_id
        ):
            raise ValueError("Plugin operation explanation identity is required")
        if self.package.operation_id != self.operation_id:
            raise ValueError("Package explanation changed operation identity")
        expected_management_id = (
            package_product_command_identity(
                self.operation_id, self.package.request_fingerprint
            )[0]
            if self.package.request_fingerprint is not None
            else self.operation_id
        )
        if self.management_operation_id != expected_management_id:
            raise ValueError("Management lookup changed Package command identity")
        if type(self.observed_at_unix_ns) is not int or self.observed_at_unix_ns < 0:
            raise ValueError("Plugin operation observation time is invalid")
        if self.evidence_gaps != tuple(sorted(set(self.evidence_gaps))):
            raise ValueError("Plugin operation evidence gaps must be canonical")
        management_facts = (
            self.management_installation_key,
            self.management_action,
            self.management_actor_id,
            self.management_progress_code,
            self.management_disposition,
            self.management_journal_revision,
        )
        if self.management_status == "unknown" and any(
            fact is not None for fact in management_facts
        ):
            raise ValueError("Unknown Management operation cannot assert owner facts")
        observed_management = self.management_status == "observed"
        observed_package = self.package.status == "observed"
        expected_join = (
            "unknown"
            if not observed_management and not observed_package
            else "package_only"
            if not observed_management
            else "management_only"
            if not observed_package
            else "same_identity"
            if self.management_installation_key is not None
            and (
                self.package.product_id,
                self.package.scope_id,
                self.package.requested_plugin_id,
            )
            == (
                self.management_installation_key.product_id,
                self.management_installation_key.scope_id,
                self.management_installation_key.plugin_id,
            )
            else "identity_conflict"
        )
        if self.join_status != expected_join:
            raise ValueError("Cross-owner operation join status is inconsistent")
        if self.package.status == "unknown":
            if (
                self.handoff_evidence != "not_queried"
                or self.handoff_receipt_id is not None
                or self.handoff_revision is not None
                or "package_product_handoff" in self.evidence_gaps
            ):
                raise ValueError("A1-only explanation cannot assert Package handoff")
        elif self.handoff_evidence == "settled":
            if (
                self.join_status != "same_identity"
                or self.package.disposition != "committed"
                or self.management_disposition not in {"succeeded", "restart_required"}
                or self.handoff_receipt_id is None
                or self.handoff_revision is None
                or "package_product_handoff" in self.evidence_gaps
            ):
                raise ValueError("Settled handoff requires exact cross-owner evidence")
        elif "package_product_handoff" not in self.evidence_gaps:
            raise ValueError("Unproven Package Product handoff must remain a gap")
        if self.handoff_evidence in {"not_queried", "absent"} and (
            self.handoff_receipt_id is not None or self.handoff_revision is not None
        ):
            raise ValueError("Absent handoff cannot assert a receipt")
        if self.snapshot_status != "partial_evidence":
            raise ValueError("Cross-owner operation explanation remains partial")
        if self.desired_commit_evidence not in {
            "not_checked", "owner_receipt", "verified_transition"
        }:
            raise ValueError("Plugin desired commit evidence is invalid")
        if self.desired_commit_evidence != "not_checked" and (
            self.package.status != "observed"
            or self.package.disposition != "committed"
            or self.handoff_evidence not in {"incomplete", "settled"}
        ):
            raise ValueError("Plugin desired commit evidence changed Package stage")
        if self.repair_command is not None and (
            not self.repair_command
            or not self.repair_command.isprintable()
            or "\n" in self.repair_command
        ):
            raise ValueError("Plugin operation repair command is invalid")
        if self.explanation_version != PLUGIN_OPERATION_EXPLANATION_VERSION:
            raise ValueError("Unsupported Plugin operation explanation")

    def to_dict(self) -> dict[str, object]:
        return {
            "correlationId": self.correlation_id,
            "operationId": self.operation_id,
            "managementOperationId": self.management_operation_id,
            "observedAtUnixNs": self.observed_at_unix_ns,
            "package": self.package.to_dict(),
            "managementStatus": self.management_status,
            "managementInstallationKey": (
                None
                if self.management_installation_key is None
                else self.management_installation_key.to_dict()
            ),
            "managementAction": self.management_action,
            "managementActorId": self.management_actor_id,
            "operationKind": (
                "a2_package"
                if self.package.status == "observed"
                else "a1_desired"
                if self.management_status == "observed"
                else "unknown"
            ),
            "managementProgressCode": self.management_progress_code,
            "managementDisposition": self.management_disposition,
            "managementJournalRevision": self.management_journal_revision,
            "handoffEvidence": self.handoff_evidence,
            "handoffReceiptId": self.handoff_receipt_id,
            "handoffRevision": self.handoff_revision,
            "joinStatus": self.join_status,
            "evidenceGaps": list(self.evidence_gaps),
            "desiredCommitEvidence": self.desired_commit_evidence,
            "repairCommand": self.repair_command,
            "snapshotStatus": self.snapshot_status,
            "explanationVersion": self.explanation_version,
        }


class PluginOperationExplanationProjector:
    """Observe independent owners once; never synthesize a handoff receipt."""

    def __init__(
        self,
        *,
        package_operations: PackageOperationReadPort,
        management_commands: PluginManagementOperationReadPort,
        handoffs: PackageProductHandoffReadPort | None = None,
        clock_ns: Callable[[], int] = time.time_ns,
    ) -> None:
        if not callable(getattr(management_commands, "operation", None)):
            raise TypeError("Plugin management operation read port is required")
        self._package = PackageOperationExplanationProjector(
            package_operations, clock_ns=clock_ns
        )
        self._management = management_commands
        if handoffs is not None and not callable(getattr(handoffs, "read_operation", None)):
            raise TypeError("Package Product handoff read port is required")
        self._handoffs = handoffs
        self._clock_ns = clock_ns

    def explain_operation(
        self, operation_id: str, *, correlation_id: str
    ) -> PluginOperationExplanationV1:
        if not isinstance(operation_id, str) or not operation_id:
            raise ValueError("Plugin operation id is required")
        if not isinstance(correlation_id, str) or not correlation_id:
            raise ValueError("Plugin operation correlation id is required")
        package = self._package.explain_operation(operation_id)
        management_operation_id = (
            package_product_command_identity(operation_id, package.request_fingerprint)[
                0
            ]
            if package.request_fingerprint is not None
            else operation_id
        )
        result = self._management.operation(
            management_operation_id, correlation_id=correlation_id
        )
        if result is not None and (
            result.correlation_id != correlation_id
            or result.operation.command.operation_id != management_operation_id
        ):
            raise ValueError("Management operation changed exact request identity")
        event = None if result is None else result.operation
        key = None
        if event is not None:
            command = event.command
            key = (
                command.mutation.installation_key
                if isinstance(command, PluginManagementCommandV1)
                else command.installation_key
            )
        join_status: Literal[
            "same_identity",
            "package_only",
            "management_only",
            "unknown",
            "identity_conflict",
        ]
        if event is None:
            join_status = "package_only" if package.status == "observed" else "unknown"
        elif package.status == "unknown":
            join_status = "management_only"
        elif key is not None and (
            package.product_id,
            package.scope_id,
            package.requested_plugin_id,
        ) == (key.product_id, key.scope_id, key.plugin_id):
            join_status = "same_identity"
        else:
            join_status = "identity_conflict"
        gaps = {"product_selection", "session_capture", "owner_atomic_snapshot"}
        if package.status == "observed":
            gaps.add("package_product_handoff")
        if event is None:
            gaps.add("management_operation")
        if package.status == "unknown" and event is None:
            gaps.add("package_operation")
        if join_status == "identity_conflict":
            gaps.add("owner_identity_conflict")
        receipt = (
            None
            if self._handoffs is None or package.status == "unknown"
            else self._handoffs.read_operation(operation_id)
        )
        handoff_evidence: Literal[
            "not_queried", "absent", "incomplete", "settled", "identity_conflict"
        ]
        if package.status == "unknown" or self._handoffs is None:
            handoff_evidence = "not_queried"
        elif receipt is None:
            handoff_evidence = "absent"
        else:
            desired = receipt.request.desired_request
            expected_command = (
                package_product_command_identity(
                    operation_id, package.request_fingerprint
                )
                if package.request_fingerprint is not None
                else None
            )
            if (
                desired.operation_id != operation_id
                or desired.request_fingerprint != package.request_fingerprint
                or expected_command is None
                or (desired.command_id, desired.command_fingerprint)
                != expected_command
                or (desired.product_id, desired.scope_id, desired.plugin_id)
                != (package.product_id, package.scope_id, package.requested_plugin_id)
                or (
                    event is not None
                    and not _management_command_matches_handoff(
                        event.command,
                        package_action=package.action,
                        desired=desired,
                    )
                )
            ):
                handoff_evidence = "identity_conflict"
                gaps.add("owner_identity_conflict")
            elif (
                receipt.state == "settled"
                and receipt.desired_receipt is not None
                and event is not None
                and join_status == "same_identity"
                and package.disposition == "committed"
                and event.result is not None
                and event.result.disposition in {"succeeded", "restart_required"}
                and event.result.transition is not None
                and receipt.desired_receipt.inventory_revision
                == event.result.transition.inventory_revision
                and receipt.desired_receipt.owner_revision == event.journal_revision
            ):
                handoff_evidence = "settled"
                gaps.discard("package_product_handoff")
            else:
                handoff_evidence = "incomplete"
        return PluginOperationExplanationV1(
            correlation_id=correlation_id,
            operation_id=operation_id,
            management_operation_id=management_operation_id,
            observed_at_unix_ns=self._clock_ns(),
            package=package,
            management_status="unknown" if event is None else "observed",
            management_installation_key=key,
            management_action=None if event is None else event.command.action,
            management_actor_id=(
                None
                if event is None
                else event.command.mutation.actor_id
                if isinstance(event.command, PluginManagementCommandV1)
                else event.command.actor_id
            ),
            management_progress_code=None if event is None else event.progress_code,
            management_disposition=(
                None
                if event is None or event.result is None
                else event.result.disposition
            ),
            management_journal_revision=(
                None if event is None else event.journal_revision
            ),
            handoff_evidence=handoff_evidence,
            handoff_receipt_id=None if receipt is None else receipt.receipt_id,
            handoff_revision=None if receipt is None else receipt.handoff_revision,
            join_status=join_status,
            evidence_gaps=tuple(sorted(gaps)),
        )


def _management_command_matches_handoff(
    command: PluginManagementCommandV1 | PluginManagementUpdateCommandV2,
    *,
    package_action: str | None,
    desired: PackageDesiredStateCommitRequestV1,
) -> bool:
    if package_action == "install" and isinstance(
        command, PluginManagementCommandV1
    ):
        revision = command.mutation.package_revision
        return (
            command.action == "install"
            and command.idempotency_key == desired.desired_request_id
            and command.mutation.expected_inventory_revision
            == desired.expected_inventory_revision
            and revision is not None
            and revision.plugin_id == desired.plugin_id
            and revision.plugin_version == desired.root_ref.version
            and revision.package_content_digest == desired.root_ref.artifact_digest
        )
    if package_action == "update" and isinstance(
        command, PluginManagementUpdateCommandV2
    ):
        revision = command.staged_package_revision
        return (
            command.idempotency_key == desired.desired_request_id
            and command.expected_inventory_revision
            == desired.expected_inventory_revision
            and revision.plugin_id == desired.plugin_id
            and revision.plugin_version == desired.root_ref.version
            and revision.package_content_digest == desired.root_ref.artifact_digest
        )
    return False


def project_plugin_operation_explanation(
    query: PluginOperationExplanationQueryPort,
    request: PluginOperationExplanationRequestV1,
) -> dict[str, object]:
    """Keep every transport on the same typed, scope-bound read contract."""

    if not isinstance(request, PluginOperationExplanationRequestV1):
        raise TypeError("Plugin operation explanation requires a typed request")
    result = query.explain_plugin_operation(request)
    if type(result) is not PluginOperationExplanationV1:
        raise TypeError("Plugin operation explanation requires a typed Product result")
    if (
        result.correlation_id != request.correlation_id
        or result.operation_id != request.operation_id
        or (
            result.package.status == "observed"
            and (
                result.package.product_id != request.product_id
                or result.package.scope_id != request.scope_id
            )
        )
        or (
            result.management_installation_key is not None
            and (
                result.management_installation_key.product_id != request.product_id
                or result.management_installation_key.scope_id != request.scope_id
            )
        )
    ):
        raise ValueError("Plugin operation explanation changed Product request")
    return result.to_dict()


__all__ = [
    "PLUGIN_OPERATION_EXPLANATION_VERSION",
    "PluginOperationExplanationProjector",
    "PluginOperationExplanationQueryPort",
    "PluginOperationExplanationRequestV1",
    "PluginOperationExplanationV1",
    "PluginManagementOperationReadPort",
    "PackageProductHandoffReadPort",
    "project_plugin_operation_explanation",
]
