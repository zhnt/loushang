"""Durable Approval-owner authority for in-process Plugin declaration execution.

This module is intentionally internal.  It records inert authority and one-shot
use reservations; it does not issue aggregate start permits, import a Plugin
Definition, or publish a live contribution.
"""

from __future__ import annotations

import secrets
import string
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from time import time_ns
from typing import Literal, Protocol, cast

from loushang.foundation.json import JsonValueError, require_json_mapping
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
from loushang.harness.resources.plugins.declarations import (
    PluginDeclarationCodecError,
)
from loushang.harness.resources.plugins.selection import (
    PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION,
    PluginExecutionApprovalSubject,
    PluginExecutionDecisionCurrent,
    PluginExecutionDecisionLookupResult,
    PluginExecutionDecisionMissing,
    PluginExecutionDecisionRecord,
    PluginInstanceRevisionRef,
)

PLUGIN_APPROVAL_AUTHORIZATION_VERSION = 1
PLUGIN_APPROVAL_DECISION_RECORD_VERSION = 1
PLUGIN_EXECUTION_USE_VERSION = 1
PLUGIN_EXECUTION_RECEIPT_VERSION = 1
PLUGIN_EXECUTION_JOURNAL_EVENT_VERSION = 1

PluginExecutionJournalScopeKind = Literal["installation", "workspace"]
PluginApprovalDisposition = Literal["approved", "denied"]
PluginApprovalAuthorizationKind = Literal[
    "direct",
    "retained_grant",
    "policy_rule",
]
PluginApprovalConsumptionState = Literal[
    "AVAILABLE",
    "DENIED",
    "CONSUMED",
    "REVOKED",
]
PluginExecutionUseState = Literal[
    "CONSUMED_NOT_STARTED",
    "CANCELLED_BEFORE_START",
    "STARTING",
    "EVALUATED",
    "FAILED_AFTER_START",
]
PluginExecutionJournalEventKind = Literal[
    "decision_issued",
    "decision_revoked",
    "execution_consumed",
    "execution_use_transitioned",
    "execution_uses_recovered",
]

_ALLOWED_EXECUTION_USE_TRANSITIONS = frozenset(
    {
        ("CONSUMED_NOT_STARTED", "CANCELLED_BEFORE_START"),
        ("CONSUMED_NOT_STARTED", "STARTING"),
        ("STARTING", "EVALUATED"),
        ("STARTING", "FAILED_AFTER_START"),
    }
)

_HEX = frozenset(string.hexdigits.lower())


class PluginExecutionJournalRecordCodecError(JournalCodecError):
    """Strict durable Plugin execution journal record failure."""


class PluginExecutionJournalError(RuntimeError):
    """Fail-closed Plugin execution authority failure with a stable code."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, slots=True)
class PluginApprovalAuthorizationV1:
    actor_id: str
    source: str
    authorization_kind: PluginApprovalAuthorizationKind
    authority_id: str | None = None
    authorization_version: int = PLUGIN_APPROVAL_AUTHORIZATION_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.actor_id, name="authorization actor id")
        _require_nonempty(self.source, name="authorization source")
        _require_version(
            self.authorization_version,
            expected=PLUGIN_APPROVAL_AUTHORIZATION_VERSION,
        )
        if self.authorization_kind not in {
            "direct",
            "retained_grant",
            "policy_rule",
        }:
            raise ValueError("Unsupported Plugin approval authorization kind")
        if self.authorization_kind == "direct":
            if self.authority_id is not None:
                raise ValueError("Direct Plugin authorization has no authority id")
        else:
            _require_nonempty(self.authority_id, name="retained authority id")

    @classmethod
    def direct(
        cls,
        *,
        actor_id: str,
        source: str,
    ) -> PluginApprovalAuthorizationV1:
        return cls(
            actor_id=actor_id,
            source=source,
            authorization_kind="direct",
        )

    @classmethod
    def retained_grant(
        cls,
        *,
        actor_id: str,
        source: str,
        authority_id: str,
    ) -> PluginApprovalAuthorizationV1:
        return cls(
            actor_id=actor_id,
            source=source,
            authorization_kind="retained_grant",
            authority_id=authority_id,
        )

    @classmethod
    def policy_rule(
        cls,
        *,
        actor_id: str,
        source: str,
        authority_id: str,
    ) -> PluginApprovalAuthorizationV1:
        return cls(
            actor_id=actor_id,
            source=source,
            authorization_kind="policy_rule",
            authority_id=authority_id,
        )

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "actorId": self.actor_id,
            "authorizationKind": self.authorization_kind,
            "authorizationVersion": self.authorization_version,
            "source": self.source,
        }
        if self.authority_id is not None:
            payload["authorityId"] = self.authority_id
        return payload

    @classmethod
    def from_dict(cls, value: object) -> PluginApprovalAuthorizationV1:
        document = _wire_object(value, name="Plugin approval authorization")
        kind = _wire_string(
            document.get("authorizationKind"),
            name="authorization kind",
        )
        keys = {
            "actorId",
            "authorizationKind",
            "authorizationVersion",
            "source",
        }
        if kind != "direct":
            keys.add("authorityId")
        _wire_exact_fields(
            document,
            keys=keys,
            name="Plugin approval authorization",
        )
        _wire_version(
            document.get("authorizationVersion"),
            expected=PLUGIN_APPROVAL_AUTHORIZATION_VERSION,
        )
        try:
            return cls(
                actor_id=_wire_string(document["actorId"], name="actor id"),
                source=_wire_string(document["source"], name="authorization source"),
                authorization_kind=cast(PluginApprovalAuthorizationKind, kind),
                authority_id=(
                    _wire_string(document["authorityId"], name="authority id")
                    if "authorityId" in document
                    else None
                ),
            )
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginApprovalDecisionRecordV1:
    decision_id: str
    subject_kind: Literal["plugin_declaration_execution"]
    subject_digest: str
    subject_schema_version: int
    plugin_id: str
    instance_revision_ref: PluginInstanceRevisionRef
    scope_kind: PluginExecutionJournalScopeKind
    scope_id: str
    disposition: PluginApprovalDisposition
    authorization: PluginApprovalAuthorizationV1
    policy_revision: str
    source_trust_policy_revision: str
    revocation_epoch: int
    issued_at_unix_ms: int
    expires_at_unix_ms: int
    consumption_state: PluginApprovalConsumptionState
    decision_revision: int
    consumed_execution_use_id: str | None = None
    record_version: int = PLUGIN_APPROVAL_DECISION_RECORD_VERSION

    def __post_init__(self) -> None:
        _require_hex(self.decision_id, length=48, name="decision id")
        if self.subject_kind != "plugin_declaration_execution":
            raise ValueError("Unsupported Plugin approval Subject kind")
        _require_sha256(self.subject_digest, name="subject digest")
        _require_version(
            self.subject_schema_version,
            expected=PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION,
        )
        _require_nonempty(self.plugin_id, name="Plugin id")
        if not isinstance(self.instance_revision_ref, PluginInstanceRevisionRef):
            raise TypeError("Decision requires a Plugin instance revision ref")
        if self.instance_revision_ref.plugin_id != self.plugin_id:
            raise ValueError("Decision Plugin identity does not match instance ref")
        if self.scope_kind not in {"installation", "workspace"}:
            raise ValueError("Unsupported Plugin execution journal scope")
        _require_nonempty(self.scope_id, name="Plugin execution scope id")
        if self.disposition not in {"approved", "denied"}:
            raise ValueError("Unsupported Plugin approval disposition")
        if not isinstance(self.authorization, PluginApprovalAuthorizationV1):
            raise TypeError("Decision requires Plugin approval authorization")
        _require_nonempty(self.policy_revision, name="policy revision")
        _require_nonempty(
            self.source_trust_policy_revision,
            name="source trust policy revision",
        )
        _require_non_negative_integer(
            self.revocation_epoch,
            name="revocation epoch",
        )
        _require_non_negative_integer(
            self.issued_at_unix_ms,
            name="issued-at Unix milliseconds",
        )
        _require_non_negative_integer(
            self.expires_at_unix_ms,
            name="expiry Unix milliseconds",
        )
        if self.expires_at_unix_ms <= self.issued_at_unix_ms:
            raise ValueError("Plugin execution decision expiry must follow issue time")
        if self.consumption_state not in {
            "AVAILABLE",
            "DENIED",
            "CONSUMED",
            "REVOKED",
        }:
            raise ValueError("Unsupported Plugin approval consumption state")
        _require_positive_integer(self.decision_revision, name="decision revision")
        _require_version(
            self.record_version,
            expected=PLUGIN_APPROVAL_DECISION_RECORD_VERSION,
        )
        if self.disposition == "denied" and self.consumption_state != "DENIED":
            raise ValueError("Denied Plugin decision must remain DENIED")
        if self.disposition == "approved" and self.consumption_state == "DENIED":
            raise ValueError("Approved Plugin decision cannot become DENIED")
        if self.consumption_state == "CONSUMED":
            _require_hex(
                self.consumed_execution_use_id,
                length=48,
                name="consumed execution use id",
            )
        elif self.consumed_execution_use_id is not None:
            raise ValueError("Only a consumed decision carries an execution use id")

    def to_selection_view(self) -> PluginExecutionDecisionRecord:
        if self.consumption_state not in {"AVAILABLE", "DENIED"}:
            raise ValueError("Terminal decision has no current selection view")
        return PluginExecutionDecisionRecord(
            decision_id=self.decision_id,
            subject_digest=self.subject_digest,
            policy_revision=self.policy_revision,
            disposition=self.disposition,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "authorization": self.authorization.to_dict(),
            "consumedExecutionUseId": self.consumed_execution_use_id,
            "consumptionState": self.consumption_state,
            "decisionId": self.decision_id,
            "decisionRevision": self.decision_revision,
            "disposition": self.disposition,
            "expiresAtUnixMs": self.expires_at_unix_ms,
            "instanceRevisionRef": self.instance_revision_ref.to_dict(),
            "issuedAtUnixMs": self.issued_at_unix_ms,
            "pluginId": self.plugin_id,
            "policyRevision": self.policy_revision,
            "recordVersion": self.record_version,
            "revocationEpoch": self.revocation_epoch,
            "scopeId": self.scope_id,
            "scopeKind": self.scope_kind,
            "sourceTrustPolicyRevision": self.source_trust_policy_revision,
            "subjectDigest": self.subject_digest,
            "subjectKind": self.subject_kind,
            "subjectSchemaVersion": self.subject_schema_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginApprovalDecisionRecordV1:
        document = _wire_object(value, name="Plugin approval decision")
        _wire_exact_fields(
            document,
            keys={
                "authorization",
                "consumedExecutionUseId",
                "consumptionState",
                "decisionId",
                "decisionRevision",
                "disposition",
                "expiresAtUnixMs",
                "instanceRevisionRef",
                "issuedAtUnixMs",
                "pluginId",
                "policyRevision",
                "recordVersion",
                "revocationEpoch",
                "scopeId",
                "scopeKind",
                "sourceTrustPolicyRevision",
                "subjectDigest",
                "subjectKind",
                "subjectSchemaVersion",
            },
            name="Plugin approval decision",
        )
        _wire_version(
            document.get("recordVersion"),
            expected=PLUGIN_APPROVAL_DECISION_RECORD_VERSION,
        )
        try:
            return cls(
                decision_id=_wire_string(document["decisionId"], name="decision id"),
                subject_kind=cast(
                    Literal["plugin_declaration_execution"],
                    _wire_string(document["subjectKind"], name="Subject kind"),
                ),
                subject_digest=_wire_string(
                    document["subjectDigest"], name="subject digest"
                ),
                subject_schema_version=_wire_integer(
                    document["subjectSchemaVersion"],
                    name="subject schema version",
                ),
                plugin_id=_wire_string(document["pluginId"], name="Plugin id"),
                instance_revision_ref=PluginInstanceRevisionRef.from_dict(
                    document["instanceRevisionRef"]
                ),
                scope_kind=cast(
                    PluginExecutionJournalScopeKind,
                    _wire_string(document["scopeKind"], name="scope kind"),
                ),
                scope_id=_wire_string(document["scopeId"], name="scope id"),
                disposition=cast(
                    PluginApprovalDisposition,
                    _wire_string(document["disposition"], name="disposition"),
                ),
                authorization=PluginApprovalAuthorizationV1.from_dict(
                    document["authorization"]
                ),
                policy_revision=_wire_string(
                    document["policyRevision"], name="policy revision"
                ),
                source_trust_policy_revision=_wire_string(
                    document["sourceTrustPolicyRevision"],
                    name="source trust policy revision",
                ),
                revocation_epoch=_wire_integer(
                    document["revocationEpoch"], name="revocation epoch"
                ),
                issued_at_unix_ms=_wire_integer(
                    document["issuedAtUnixMs"], name="issued-at Unix milliseconds"
                ),
                expires_at_unix_ms=_wire_integer(
                    document["expiresAtUnixMs"], name="expiry Unix milliseconds"
                ),
                consumption_state=cast(
                    PluginApprovalConsumptionState,
                    _wire_string(
                        document["consumptionState"], name="consumption state"
                    ),
                ),
                decision_revision=_wire_integer(
                    document["decisionRevision"], name="decision revision"
                ),
                consumed_execution_use_id=_wire_optional_string(
                    document["consumedExecutionUseId"],
                    name="consumed execution use id",
                ),
            )
        except PluginExecutionJournalRecordCodecError:
            raise
        except (PluginDeclarationCodecError, TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginExecutionUseReservationV1:
    decision_id: str
    execution_use_id: str
    host_boot_id: str
    import_realm_id: str
    instance_revision_ref: PluginInstanceRevisionRef
    policy_revision: str
    preflight_use_id: str
    revocation_epoch: int
    source_group_id: str
    source_trust_policy_revision: str
    state: PluginExecutionUseState
    subject_digest: str
    execution_use_version: int = PLUGIN_EXECUTION_USE_VERSION

    def __post_init__(self) -> None:
        _require_hex(self.decision_id, length=48, name="decision id")
        _require_hex(self.execution_use_id, length=48, name="execution use id")
        _require_hex(self.host_boot_id, length=32, name="host boot id")
        _require_hex(self.import_realm_id, length=32, name="import realm id")
        if not isinstance(self.instance_revision_ref, PluginInstanceRevisionRef):
            raise TypeError("Execution use requires a Plugin instance revision ref")
        _require_nonempty(self.policy_revision, name="policy revision")
        _require_hex(self.preflight_use_id, length=48, name="preflight use id")
        _require_non_negative_integer(
            self.revocation_epoch,
            name="revocation epoch",
        )
        _require_sha256(self.source_group_id, name="source group id")
        _require_nonempty(
            self.source_trust_policy_revision,
            name="source trust policy revision",
        )
        if self.state not in {
            "CONSUMED_NOT_STARTED",
            "CANCELLED_BEFORE_START",
            "STARTING",
            "EVALUATED",
            "FAILED_AFTER_START",
        }:
            raise ValueError("Unsupported Plugin execution use state")
        _require_sha256(self.subject_digest, name="subject digest")
        _require_version(
            self.execution_use_version,
            expected=PLUGIN_EXECUTION_USE_VERSION,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "decisionId": self.decision_id,
            "executionUseId": self.execution_use_id,
            "executionUseVersion": self.execution_use_version,
            "hostBootId": self.host_boot_id,
            "importRealmId": self.import_realm_id,
            "instanceRevisionRef": self.instance_revision_ref.to_dict(),
            "policyRevision": self.policy_revision,
            "preflightUseId": self.preflight_use_id,
            "revocationEpoch": self.revocation_epoch,
            "sourceGroupId": self.source_group_id,
            "sourceTrustPolicyRevision": self.source_trust_policy_revision,
            "state": self.state,
            "subjectDigest": self.subject_digest,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginExecutionUseReservationV1:
        document = _wire_object(value, name="Plugin execution use reservation")
        _wire_exact_fields(
            document,
            keys={
                "decisionId",
                "executionUseId",
                "executionUseVersion",
                "hostBootId",
                "importRealmId",
                "instanceRevisionRef",
                "policyRevision",
                "preflightUseId",
                "revocationEpoch",
                "sourceGroupId",
                "sourceTrustPolicyRevision",
                "state",
                "subjectDigest",
            },
            name="Plugin execution use reservation",
        )
        _wire_version(
            document.get("executionUseVersion"),
            expected=PLUGIN_EXECUTION_USE_VERSION,
        )
        try:
            return cls(
                decision_id=_wire_string(document["decisionId"], name="decision id"),
                execution_use_id=_wire_string(
                    document["executionUseId"], name="execution use id"
                ),
                host_boot_id=_wire_string(document["hostBootId"], name="host boot id"),
                import_realm_id=_wire_string(
                    document["importRealmId"], name="import realm id"
                ),
                instance_revision_ref=PluginInstanceRevisionRef.from_dict(
                    document["instanceRevisionRef"]
                ),
                policy_revision=_wire_string(
                    document["policyRevision"], name="policy revision"
                ),
                preflight_use_id=_wire_string(
                    document["preflightUseId"], name="preflight use id"
                ),
                revocation_epoch=_wire_integer(
                    document["revocationEpoch"], name="revocation epoch"
                ),
                source_group_id=_wire_string(
                    document["sourceGroupId"], name="source group id"
                ),
                source_trust_policy_revision=_wire_string(
                    document["sourceTrustPolicyRevision"],
                    name="source trust policy revision",
                ),
                state=cast(
                    PluginExecutionUseState,
                    _wire_string(document["state"], name="execution use state"),
                ),
                subject_digest=_wire_string(
                    document["subjectDigest"], name="subject digest"
                ),
            )
        except (PluginDeclarationCodecError, TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, order=True, slots=True)
class PluginImportRealmRefV1:
    host_boot_id: str
    import_realm_id: str

    def __post_init__(self) -> None:
        _require_hex(self.host_boot_id, length=32, name="host boot id")
        _require_hex(self.import_realm_id, length=32, name="import realm id")

    def to_dict(self) -> dict[str, object]:
        return {
            "hostBootId": self.host_boot_id,
            "importRealmId": self.import_realm_id,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginImportRealmRefV1:
        document = _wire_object(value, name="Plugin import realm ref")
        _wire_exact_fields(
            document,
            keys={"hostBootId", "importRealmId"},
            name="Plugin import realm ref",
        )
        try:
            return cls(
                host_boot_id=_wire_string(document["hostBootId"], name="host boot id"),
                import_realm_id=_wire_string(
                    document["importRealmId"], name="import realm id"
                ),
            )
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


@dataclass(frozen=True, slots=True)
class PluginExecutionConsumptionReceiptV1:
    decision_id: str
    execution_use_id: str
    host_boot_id: str
    import_realm_id: str
    instance_revision_ref: PluginInstanceRevisionRef
    policy_revision: str
    preflight_use_id: str
    revocation_epoch: int
    source_group_id: str
    source_trust_policy_revision: str
    subject_digest: str
    state: Literal["EVALUATED"] = "EVALUATED"
    receipt_version: int = PLUGIN_EXECUTION_RECEIPT_VERSION

    def __post_init__(self) -> None:
        _require_hex(self.decision_id, length=48, name="decision id")
        _require_hex(self.execution_use_id, length=48, name="execution use id")
        _require_hex(self.host_boot_id, length=32, name="host boot id")
        _require_hex(self.import_realm_id, length=32, name="import realm id")
        if not isinstance(self.instance_revision_ref, PluginInstanceRevisionRef):
            raise TypeError("Execution receipt requires an instance revision ref")
        _require_nonempty(self.policy_revision, name="policy revision")
        _require_hex(self.preflight_use_id, length=48, name="preflight use id")
        _require_non_negative_integer(
            self.revocation_epoch,
            name="revocation epoch",
        )
        _require_sha256(self.source_group_id, name="source group id")
        _require_nonempty(
            self.source_trust_policy_revision,
            name="source trust policy revision",
        )
        _require_sha256(self.subject_digest, name="subject digest")
        if self.state != "EVALUATED":
            raise ValueError("Plugin execution receipt requires EVALUATED state")
        _require_version(
            self.receipt_version,
            expected=PLUGIN_EXECUTION_RECEIPT_VERSION,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "decisionId": self.decision_id,
            "executionUseId": self.execution_use_id,
            "hostBootId": self.host_boot_id,
            "importRealmId": self.import_realm_id,
            "instanceRevisionRef": self.instance_revision_ref.to_dict(),
            "policyRevision": self.policy_revision,
            "preflightUseId": self.preflight_use_id,
            "receiptVersion": self.receipt_version,
            "revocationEpoch": self.revocation_epoch,
            "sourceGroupId": self.source_group_id,
            "sourceTrustPolicyRevision": self.source_trust_policy_revision,
            "state": self.state,
            "subjectDigest": self.subject_digest,
        }


@dataclass(frozen=True, slots=True)
class PluginExecutionRecoveryResultV1:
    journal_revision: int
    cancelled_before_start: tuple[PluginExecutionUseReservationV1, ...]
    polluted_import_realms: tuple[PluginImportRealmRefV1, ...]

    def __post_init__(self) -> None:
        _require_non_negative_integer(
            self.journal_revision,
            name="journal revision",
        )
        if self.cancelled_before_start != tuple(
            sorted(
                self.cancelled_before_start,
                key=lambda item: item.execution_use_id,
            )
        ):
            raise ValueError("Cancelled Plugin execution uses must be sorted")
        if any(
            item.state != "CANCELLED_BEFORE_START"
            for item in self.cancelled_before_start
        ):
            raise ValueError("Recovered Plugin execution uses must be cancelled")
        if self.polluted_import_realms != tuple(
            sorted(set(self.polluted_import_realms))
        ):
            raise ValueError("Polluted Plugin import realms must be sorted and unique")


@dataclass(frozen=True, slots=True)
class _DecisionIssuedV1:
    decision: PluginApprovalDecisionRecordV1

    def to_dict(self) -> dict[str, object]:
        return {"decision": self.decision.to_dict()}


@dataclass(frozen=True, slots=True)
class _DecisionRevokedV1:
    decision: PluginApprovalDecisionRecordV1
    expected_decision_revision: int
    actor_id: str
    source: str
    revoked_at_unix_ms: int

    def __post_init__(self) -> None:
        _require_positive_integer(
            self.expected_decision_revision,
            name="expected decision revision",
        )
        _require_nonempty(self.actor_id, name="revocation actor id")
        _require_nonempty(self.source, name="revocation source")
        _require_non_negative_integer(
            self.revoked_at_unix_ms,
            name="revoked-at Unix milliseconds",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "actorId": self.actor_id,
            "decision": self.decision.to_dict(),
            "expectedDecisionRevision": self.expected_decision_revision,
            "revokedAtUnixMs": self.revoked_at_unix_ms,
            "source": self.source,
        }


@dataclass(frozen=True, slots=True)
class _ExecutionConsumedV1:
    decision: PluginApprovalDecisionRecordV1
    expected_decision_revision: int
    reservation: PluginExecutionUseReservationV1
    consumed_at_unix_ms: int

    def __post_init__(self) -> None:
        _require_positive_integer(
            self.expected_decision_revision,
            name="expected decision revision",
        )
        _require_non_negative_integer(
            self.consumed_at_unix_ms,
            name="consumed-at Unix milliseconds",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "consumedAtUnixMs": self.consumed_at_unix_ms,
            "decision": self.decision.to_dict(),
            "expectedDecisionRevision": self.expected_decision_revision,
            "reservation": self.reservation.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class _ExecutionUseTransitionedV1:
    expected_state: PluginExecutionUseState
    reservation: PluginExecutionUseReservationV1
    transitioned_at_unix_ms: int

    def __post_init__(self) -> None:
        if (
            self.expected_state,
            self.reservation.state,
        ) not in _ALLOWED_EXECUTION_USE_TRANSITIONS:
            raise ValueError("Unsupported Plugin execution use transition")
        _require_non_negative_integer(
            self.transitioned_at_unix_ms,
            name="transitioned-at Unix milliseconds",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "expectedState": self.expected_state,
            "reservation": self.reservation.to_dict(),
            "transitionedAtUnixMs": self.transitioned_at_unix_ms,
        }


@dataclass(frozen=True, slots=True)
class _ExecutionUsesRecoveredV1:
    current_host_boot_id: str
    reservations: tuple[PluginExecutionUseReservationV1, ...]
    recovered_at_unix_ms: int

    def __post_init__(self) -> None:
        _require_hex(
            self.current_host_boot_id,
            length=32,
            name="current host boot id",
        )
        if not self.reservations:
            raise ValueError("Plugin execution recovery event cannot be empty")
        if self.reservations != tuple(
            sorted(self.reservations, key=lambda item: item.execution_use_id)
        ):
            raise ValueError("Recovered Plugin execution uses must be sorted")
        if any(
            item.state != "CANCELLED_BEFORE_START"
            or item.host_boot_id == self.current_host_boot_id
            for item in self.reservations
        ):
            raise ValueError("Plugin execution recovery payload is invalid")
        _require_non_negative_integer(
            self.recovered_at_unix_ms,
            name="recovered-at Unix milliseconds",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "currentHostBootId": self.current_host_boot_id,
            "recoveredAtUnixMs": self.recovered_at_unix_ms,
            "reservations": [item.to_dict() for item in self.reservations],
        }


_PluginExecutionEventPayload = (
    _DecisionIssuedV1
    | _DecisionRevokedV1
    | _ExecutionConsumedV1
    | _ExecutionUseTransitionedV1
    | _ExecutionUsesRecoveredV1
)


@dataclass(frozen=True, slots=True)
class _PluginExecutionJournalEventV1:
    journal_revision: int
    expected_journal_revision: int
    event_kind: PluginExecutionJournalEventKind
    payload: _PluginExecutionEventPayload
    event_version: int = PLUGIN_EXECUTION_JOURNAL_EVENT_VERSION

    def __post_init__(self) -> None:
        _require_positive_integer(self.journal_revision, name="journal revision")
        _require_non_negative_integer(
            self.expected_journal_revision,
            name="expected journal revision",
        )
        if self.journal_revision != self.expected_journal_revision + 1:
            raise ValueError("Plugin execution journal CAS revision is invalid")
        _require_version(
            self.event_version,
            expected=PLUGIN_EXECUTION_JOURNAL_EVENT_VERSION,
        )
        expected_type: type[object]
        if self.event_kind == "decision_issued":
            expected_type = _DecisionIssuedV1
        elif self.event_kind == "decision_revoked":
            expected_type = _DecisionRevokedV1
        elif self.event_kind == "execution_consumed":
            expected_type = _ExecutionConsumedV1
        elif self.event_kind == "execution_use_transitioned":
            expected_type = _ExecutionUseTransitionedV1
        elif self.event_kind == "execution_uses_recovered":
            expected_type = _ExecutionUsesRecoveredV1
        else:
            raise ValueError("Unsupported Plugin execution journal event kind")
        if not isinstance(self.payload, expected_type):
            raise TypeError("Plugin execution journal payload does not match kind")

    def to_dict(self) -> dict[str, object]:
        return {
            "eventKind": self.event_kind,
            "eventVersion": self.event_version,
            "expectedJournalRevision": self.expected_journal_revision,
            "journalRevision": self.journal_revision,
            "payload": self.payload.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: object) -> _PluginExecutionJournalEventV1:
        document = _wire_object(value, name="Plugin execution journal event")
        _wire_exact_fields(
            document,
            keys={
                "eventKind",
                "eventVersion",
                "expectedJournalRevision",
                "journalRevision",
                "payload",
            },
            name="Plugin execution journal event",
        )
        _wire_version(
            document.get("eventVersion"),
            expected=PLUGIN_EXECUTION_JOURNAL_EVENT_VERSION,
        )
        kind = _wire_string(document["eventKind"], name="event kind")
        payload = _wire_object(document["payload"], name="event payload")
        try:
            decoded: _PluginExecutionEventPayload
            if kind == "decision_issued":
                _wire_exact_fields(payload, keys={"decision"}, name="issue payload")
                decoded = _DecisionIssuedV1(
                    decision=PluginApprovalDecisionRecordV1.from_dict(
                        payload["decision"]
                    )
                )
            elif kind == "decision_revoked":
                _wire_exact_fields(
                    payload,
                    keys={
                        "actorId",
                        "decision",
                        "expectedDecisionRevision",
                        "revokedAtUnixMs",
                        "source",
                    },
                    name="revocation payload",
                )
                decoded = _DecisionRevokedV1(
                    decision=PluginApprovalDecisionRecordV1.from_dict(
                        payload["decision"]
                    ),
                    expected_decision_revision=_wire_integer(
                        payload["expectedDecisionRevision"],
                        name="expected decision revision",
                    ),
                    actor_id=_wire_string(payload["actorId"], name="actor id"),
                    source=_wire_string(payload["source"], name="source"),
                    revoked_at_unix_ms=_wire_integer(
                        payload["revokedAtUnixMs"],
                        name="revoked-at Unix milliseconds",
                    ),
                )
            elif kind == "execution_consumed":
                _wire_exact_fields(
                    payload,
                    keys={
                        "consumedAtUnixMs",
                        "decision",
                        "expectedDecisionRevision",
                        "reservation",
                    },
                    name="consumption payload",
                )
                decoded = _ExecutionConsumedV1(
                    decision=PluginApprovalDecisionRecordV1.from_dict(
                        payload["decision"]
                    ),
                    expected_decision_revision=_wire_integer(
                        payload["expectedDecisionRevision"],
                        name="expected decision revision",
                    ),
                    reservation=PluginExecutionUseReservationV1.from_dict(
                        payload["reservation"]
                    ),
                    consumed_at_unix_ms=_wire_integer(
                        payload["consumedAtUnixMs"],
                        name="consumed-at Unix milliseconds",
                    ),
                )
            elif kind == "execution_use_transitioned":
                _wire_exact_fields(
                    payload,
                    keys={
                        "expectedState",
                        "reservation",
                        "transitionedAtUnixMs",
                    },
                    name="execution use transition payload",
                )
                decoded = _ExecutionUseTransitionedV1(
                    expected_state=cast(
                        PluginExecutionUseState,
                        _wire_string(
                            payload["expectedState"],
                            name="expected execution use state",
                        ),
                    ),
                    reservation=PluginExecutionUseReservationV1.from_dict(
                        payload["reservation"]
                    ),
                    transitioned_at_unix_ms=_wire_integer(
                        payload["transitionedAtUnixMs"],
                        name="transitioned-at Unix milliseconds",
                    ),
                )
            elif kind == "execution_uses_recovered":
                _wire_exact_fields(
                    payload,
                    keys={
                        "currentHostBootId",
                        "recoveredAtUnixMs",
                        "reservations",
                    },
                    name="execution use recovery payload",
                )
                reservations = payload["reservations"]
                if not isinstance(reservations, list):
                    raise _invalid_record(
                        "Recovered Plugin execution uses must be an array"
                    )
                decoded = _ExecutionUsesRecoveredV1(
                    current_host_boot_id=_wire_string(
                        payload["currentHostBootId"],
                        name="current host boot id",
                    ),
                    reservations=tuple(
                        PluginExecutionUseReservationV1.from_dict(item)
                        for item in reservations
                    ),
                    recovered_at_unix_ms=_wire_integer(
                        payload["recoveredAtUnixMs"],
                        name="recovered-at Unix milliseconds",
                    ),
                )
            else:
                raise ValueError("Unsupported Plugin execution journal event kind")
            return cls(
                journal_revision=_wire_integer(
                    document["journalRevision"], name="journal revision"
                ),
                expected_journal_revision=_wire_integer(
                    document["expectedJournalRevision"],
                    name="expected journal revision",
                ),
                event_kind=cast(PluginExecutionJournalEventKind, kind),
                payload=decoded,
            )
        except PluginExecutionJournalRecordCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise _invalid_record(str(exc)) from exc


_PLUGIN_EXECUTION_EVENT_CODEC = FunctionalJournalRecordCodec(
    encoder=_PluginExecutionJournalEventV1.to_dict,
    decoder=_PluginExecutionJournalEventV1.from_dict,
)


@dataclass(frozen=True, slots=True)
class PluginExecutionDecisionSnapshotV1:
    journal_revision: int
    decisions: tuple[PluginApprovalDecisionRecordV1, ...]
    execution_uses: tuple[PluginExecutionUseReservationV1, ...]

    def __post_init__(self) -> None:
        _require_non_negative_integer(
            self.journal_revision,
            name="journal revision",
        )
        if self.decisions != tuple(
            sorted(self.decisions, key=lambda item: item.decision_id)
        ):
            raise ValueError("Plugin execution decisions must be sorted")
        if self.execution_uses != tuple(
            sorted(self.execution_uses, key=lambda item: item.execution_use_id)
        ):
            raise ValueError("Plugin execution uses must be sorted")


class PluginRetainedAuthorityValidator(Protocol):
    def __call__(self, authorization: PluginApprovalAuthorizationV1) -> bool: ...


@dataclass(slots=True)
class _ReplayedExecutionJournal:
    events: tuple[_PluginExecutionJournalEventV1, ...]
    decisions: dict[str, PluginApprovalDecisionRecordV1]
    subject_decisions: dict[str, list[str]]
    execution_uses: dict[str, PluginExecutionUseReservationV1]


class PluginExecutionDecisionJournal:
    """Installation/workspace-scoped durable Plugin execution authority."""

    def __init__(
        self,
        path: str | Path,
        *,
        scope_kind: PluginExecutionJournalScopeKind,
        scope_id: str,
        decision_id_factory: Callable[[], str] = lambda: secrets.token_hex(24),
        execution_use_id_factory: Callable[[], str] = lambda: secrets.token_hex(24),
        clock: Callable[[], int] = lambda: time_ns() // 1_000_000,
        retained_authority_validator: PluginRetainedAuthorityValidator = (
            lambda _authorization: False
        ),
    ) -> None:
        if scope_kind not in {"installation", "workspace"}:
            raise ValueError("Unsupported Plugin execution journal scope")
        _require_nonempty(scope_id, name="Plugin execution journal scope id")
        self._path = Path(path)
        self._scope_kind = scope_kind
        self._scope_id = scope_id
        self._decision_id_factory = decision_id_factory
        self._execution_use_id_factory = execution_use_id_factory
        self._clock = clock
        self._retained_authority_validator = retained_authority_validator
        self._unlocked_durability = replace(DURABLE_LOCKED_JOURNAL, locking=False)
        self._load_policy = JournalLoadPolicy(partial_tail="repair")

    @property
    def path(self) -> Path:
        return self._path

    def issue_execution_decision(
        self,
        subject: PluginExecutionApprovalSubject,
        *,
        disposition: PluginApprovalDisposition,
        authorization: PluginApprovalAuthorizationV1,
        revocation_epoch: int,
        issued_at_unix_ms: int,
        expires_at_unix_ms: int,
        expected_journal_revision: int,
    ) -> PluginApprovalDecisionRecordV1:
        self._require_subject_scope(subject)
        if disposition not in {"approved", "denied"}:
            raise ValueError("Unsupported Plugin approval disposition")
        if not isinstance(authorization, PluginApprovalAuthorizationV1):
            raise TypeError("Plugin approval authorization is required")
        _require_expected_revision(expected_journal_revision)
        with self._lock():
            replayed = self._load_and_replay_unlocked()
            self._require_journal_revision(replayed, expected_journal_revision)
            now = self._now()
            if issued_at_unix_ms > now:
                raise self._error(
                    "Plugin execution decision issue time is in the future",
                    code="invalid_plugin_execution_decision",
                )
            latest = _latest_subject_decision(replayed, subject.digest)
            if (
                latest is not None
                and latest.consumption_state == "AVAILABLE"
                and issued_at_unix_ms < latest.expires_at_unix_ms
            ):
                raise self._error(
                    "Plugin execution Subject already has an active decision",
                    code="plugin_execution_subject_decision_active",
                )
            decision_id = self._decision_id_factory()
            _require_hex(decision_id, length=48, name="decision id")
            if decision_id in replayed.decisions:
                raise self._error(
                    "Plugin execution decision id was already issued",
                    code="plugin_execution_decision_identity_conflict",
                )
            try:
                decision = PluginApprovalDecisionRecordV1(
                    decision_id=decision_id,
                    subject_kind="plugin_declaration_execution",
                    subject_digest=subject.digest,
                    subject_schema_version=subject.schema_version,
                    plugin_id=subject.plugin_id,
                    instance_revision_ref=subject.instance_revision_ref,
                    scope_kind=self._scope_kind,
                    scope_id=self._scope_id,
                    disposition=disposition,
                    authorization=authorization,
                    policy_revision=subject.policy_revision,
                    source_trust_policy_revision=(subject.source_trust_policy_revision),
                    revocation_epoch=revocation_epoch,
                    issued_at_unix_ms=issued_at_unix_ms,
                    expires_at_unix_ms=expires_at_unix_ms,
                    consumption_state=(
                        "AVAILABLE" if disposition == "approved" else "DENIED"
                    ),
                    decision_revision=1,
                )
            except (TypeError, ValueError) as exc:
                raise self._error(
                    f"Invalid Plugin execution decision: {exc}",
                    code="invalid_plugin_execution_decision",
                ) from exc
            self._append_unlocked(
                replayed,
                event_kind="decision_issued",
                payload=_DecisionIssuedV1(decision=decision),
            )
            return decision

    def lookup_execution_decision(
        self,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginExecutionDecisionLookupResult:
        if not isinstance(subject, PluginExecutionApprovalSubject):
            raise TypeError("Plugin execution lookup requires a Subject v2")
        if subject.scope_id != self._scope_id:
            return PluginExecutionDecisionMissing()
        with self._lock():
            replayed = self._load_and_replay_unlocked()
        decision = _latest_subject_decision(replayed, subject.digest)
        if (
            decision is None
            or decision.consumption_state not in {"AVAILABLE", "DENIED"}
            or self._now() >= decision.expires_at_unix_ms
        ):
            return PluginExecutionDecisionMissing()
        return PluginExecutionDecisionCurrent(decision=decision.to_selection_view())

    def consume_execution_decision(
        self,
        subject: PluginExecutionApprovalSubject,
        *,
        decision_id: str,
        preflight_use_id: str,
        source_group_id: str,
        host_boot_id: str,
        import_realm_id: str,
        expected_revocation_epoch: int,
        current_policy_revision: str,
        current_source_trust_policy_revision: str,
        expected_journal_revision: int,
    ) -> PluginExecutionUseReservationV1:
        self._require_subject_scope(subject)
        _require_expected_revision(expected_journal_revision)
        _require_hex(decision_id, length=48, name="decision id")
        _require_nonempty(current_policy_revision, name="current policy revision")
        _require_nonempty(
            current_source_trust_policy_revision,
            name="current source trust policy revision",
        )
        _require_non_negative_integer(
            expected_revocation_epoch,
            name="expected revocation epoch",
        )
        with self._lock():
            replayed = self._load_and_replay_unlocked()
            self._require_journal_revision(replayed, expected_journal_revision)
            decision = replayed.decisions.get(decision_id)
            if decision is None:
                raise self._error(
                    "Plugin execution decision does not exist",
                    code="plugin_execution_decision_missing",
                )
            if decision.subject_digest != subject.digest:
                raise self._error(
                    "Plugin execution decision belongs to another Subject",
                    code="plugin_execution_decision_subject_mismatch",
                )
            self._require_decision_available(decision)
            if (
                decision.policy_revision != current_policy_revision
                or subject.policy_revision != current_policy_revision
            ):
                raise self._error(
                    "Plugin execution policy revision is stale",
                    code="plugin_execution_decision_policy_stale",
                )
            if (
                decision.source_trust_policy_revision
                != current_source_trust_policy_revision
                or subject.source_trust_policy_revision
                != current_source_trust_policy_revision
            ):
                raise self._error(
                    "Plugin execution source-trust revision is stale",
                    code="plugin_execution_decision_trust_stale",
                )
            if decision.revocation_epoch != expected_revocation_epoch:
                raise self._error(
                    "Plugin execution revocation epoch is stale",
                    code="plugin_execution_decision_revocation_stale",
                )
            now = self._now()
            if now < decision.issued_at_unix_ms:
                raise self._error(
                    "Plugin execution decision issue time is not current",
                    code="invalid_plugin_execution_decision",
                )
            if now >= decision.expires_at_unix_ms:
                raise self._error(
                    "Plugin execution decision has expired",
                    code="plugin_execution_decision_expired",
                )
            if (
                decision.authorization.authorization_kind != "direct"
                and not self._retained_authority_is_live(decision.authorization)
            ):
                raise self._error(
                    "Retained Plugin execution authorization is no longer live",
                    code="plugin_execution_authorization_stale",
                )
            execution_use_id = self._execution_use_id_factory()
            _require_hex(
                execution_use_id,
                length=48,
                name="execution use id",
            )
            if execution_use_id in replayed.execution_uses:
                raise self._error(
                    "Plugin execution use id was already issued",
                    code="plugin_execution_use_identity_conflict",
                )
            try:
                reservation = PluginExecutionUseReservationV1(
                    decision_id=decision.decision_id,
                    execution_use_id=execution_use_id,
                    host_boot_id=host_boot_id,
                    import_realm_id=import_realm_id,
                    instance_revision_ref=subject.instance_revision_ref,
                    policy_revision=decision.policy_revision,
                    preflight_use_id=preflight_use_id,
                    revocation_epoch=decision.revocation_epoch,
                    source_group_id=source_group_id,
                    source_trust_policy_revision=(
                        decision.source_trust_policy_revision
                    ),
                    state="CONSUMED_NOT_STARTED",
                    subject_digest=decision.subject_digest,
                )
                consumed = replace(
                    decision,
                    consumption_state="CONSUMED",
                    consumed_execution_use_id=execution_use_id,
                    decision_revision=decision.decision_revision + 1,
                )
            except (TypeError, ValueError) as exc:
                raise self._error(
                    f"Invalid Plugin execution consumption: {exc}",
                    code="invalid_plugin_execution_consumption",
                ) from exc
            self._append_unlocked(
                replayed,
                event_kind="execution_consumed",
                payload=_ExecutionConsumedV1(
                    decision=consumed,
                    expected_decision_revision=decision.decision_revision,
                    reservation=reservation,
                    consumed_at_unix_ms=now,
                ),
            )
            return reservation

    def transition_execution_use(
        self,
        execution_use_id: str,
        *,
        expected_state: PluginExecutionUseState,
        target_state: PluginExecutionUseState,
        host_boot_id: str,
        import_realm_id: str,
        transitioned_at_unix_ms: int,
        expected_journal_revision: int,
    ) -> PluginExecutionUseReservationV1:
        _require_expected_revision(expected_journal_revision)
        _require_hex(execution_use_id, length=48, name="execution use id")
        _require_hex(host_boot_id, length=32, name="host boot id")
        _require_hex(import_realm_id, length=32, name="import realm id")
        with self._lock():
            replayed = self._load_and_replay_unlocked()
            self._require_journal_revision(replayed, expected_journal_revision)
            current = replayed.execution_uses.get(execution_use_id)
            if current is None:
                raise self._error(
                    "Plugin execution use does not exist",
                    code="plugin_execution_use_missing",
                )
            if current.state != expected_state:
                raise self._error(
                    "Plugin execution use state does not match",
                    code="plugin_execution_use_state_conflict",
                )
            if (
                current.host_boot_id != host_boot_id
                or current.import_realm_id != import_realm_id
            ):
                raise self._error(
                    "Plugin execution use belongs to another import realm",
                    code="plugin_execution_import_realm_mismatch",
                )
            if (expected_state, target_state) not in (
                _ALLOWED_EXECUTION_USE_TRANSITIONS
            ):
                raise self._error(
                    "Plugin execution use transition is not allowed",
                    code="plugin_execution_use_transition_invalid",
                )
            now = self._now()
            if (
                not isinstance(transitioned_at_unix_ms, int)
                or isinstance(transitioned_at_unix_ms, bool)
                or transitioned_at_unix_ms < 0
                or transitioned_at_unix_ms > now
            ):
                raise self._error(
                    "Plugin execution transition time is outside the durable clock",
                    code="invalid_plugin_execution_use_transition",
                )
            transitioned = replace(current, state=target_state)
            self._append_unlocked(
                replayed,
                event_kind="execution_use_transitioned",
                payload=_ExecutionUseTransitionedV1(
                    expected_state=expected_state,
                    reservation=transitioned,
                    transitioned_at_unix_ms=transitioned_at_unix_ms,
                ),
            )
            return transitioned

    def recover_execution_uses(
        self,
        *,
        current_host_boot_id: str,
        recovered_at_unix_ms: int,
        expected_journal_revision: int,
    ) -> PluginExecutionRecoveryResultV1:
        _require_expected_revision(expected_journal_revision)
        _require_hex(
            current_host_boot_id,
            length=32,
            name="current host boot id",
        )
        with self._lock():
            replayed = self._load_and_replay_unlocked()
            self._require_journal_revision(replayed, expected_journal_revision)
            now = self._now()
            if (
                not isinstance(recovered_at_unix_ms, int)
                or isinstance(recovered_at_unix_ms, bool)
                or recovered_at_unix_ms < 0
                or recovered_at_unix_ms > now
            ):
                raise self._error(
                    "Plugin execution recovery time is outside the durable clock",
                    code="invalid_plugin_execution_recovery",
                )
            cancelled = tuple(
                replace(item, state="CANCELLED_BEFORE_START")
                for item in sorted(
                    replayed.execution_uses.values(),
                    key=lambda candidate: candidate.execution_use_id,
                )
                if item.state == "CONSUMED_NOT_STARTED"
                and item.host_boot_id != current_host_boot_id
            )
            if cancelled:
                self._append_unlocked(
                    replayed,
                    event_kind="execution_uses_recovered",
                    payload=_ExecutionUsesRecoveredV1(
                        current_host_boot_id=current_host_boot_id,
                        reservations=cancelled,
                        recovered_at_unix_ms=recovered_at_unix_ms,
                    ),
                )
            final_uses = dict(replayed.execution_uses)
            final_uses.update((item.execution_use_id, item) for item in cancelled)
            return PluginExecutionRecoveryResultV1(
                journal_revision=len(replayed.events) + (1 if cancelled else 0),
                cancelled_before_start=cancelled,
                polluted_import_realms=_polluted_import_realms(final_uses.values()),
            )

    def execution_consumption_receipt(
        self,
        execution_use_id: str,
        *,
        current_host_boot_id: str,
        current_import_realm_id: str,
    ) -> PluginExecutionConsumptionReceiptV1:
        _require_hex(execution_use_id, length=48, name="execution use id")
        _require_hex(
            current_host_boot_id,
            length=32,
            name="current host boot id",
        )
        _require_hex(
            current_import_realm_id,
            length=32,
            name="current import realm id",
        )
        with self._lock():
            replayed = self._load_and_replay_unlocked()
        execution_use = replayed.execution_uses.get(execution_use_id)
        if execution_use is None:
            raise self._error(
                "Plugin execution use does not exist",
                code="plugin_execution_use_missing",
            )
        if execution_use.state != "EVALUATED":
            raise self._error(
                "Plugin execution use cannot produce a receipt",
                code="plugin_execution_receipt_unavailable",
            )
        if (
            execution_use.host_boot_id != current_host_boot_id
            or execution_use.import_realm_id != current_import_realm_id
        ):
            raise self._error(
                "Plugin execution use belongs to another import realm",
                code="plugin_execution_import_realm_mismatch",
            )
        return PluginExecutionConsumptionReceiptV1(
            decision_id=execution_use.decision_id,
            execution_use_id=execution_use.execution_use_id,
            host_boot_id=execution_use.host_boot_id,
            import_realm_id=execution_use.import_realm_id,
            instance_revision_ref=execution_use.instance_revision_ref,
            policy_revision=execution_use.policy_revision,
            preflight_use_id=execution_use.preflight_use_id,
            revocation_epoch=execution_use.revocation_epoch,
            source_group_id=execution_use.source_group_id,
            source_trust_policy_revision=(execution_use.source_trust_policy_revision),
            subject_digest=execution_use.subject_digest,
        )

    def revoke_execution_decision(
        self,
        decision_id: str,
        *,
        revocation_epoch: int,
        actor_id: str,
        source: str,
        revoked_at_unix_ms: int,
        expected_journal_revision: int,
    ) -> PluginApprovalDecisionRecordV1:
        _require_expected_revision(expected_journal_revision)
        _require_hex(decision_id, length=48, name="decision id")
        with self._lock():
            replayed = self._load_and_replay_unlocked()
            self._require_journal_revision(replayed, expected_journal_revision)
            decision = replayed.decisions.get(decision_id)
            if decision is None:
                raise self._error(
                    "Plugin execution decision does not exist",
                    code="plugin_execution_decision_missing",
                )
            self._require_decision_available(decision)
            now = self._now()
            if (
                revoked_at_unix_ms < decision.issued_at_unix_ms
                or revoked_at_unix_ms > now
            ):
                raise self._error(
                    "Plugin execution revocation time is outside the durable clock",
                    code="invalid_plugin_execution_revocation",
                )
            if revocation_epoch <= decision.revocation_epoch:
                raise self._error(
                    "Plugin execution revocation epoch did not advance",
                    code="plugin_execution_decision_revocation_stale",
                )
            try:
                revoked = replace(
                    decision,
                    revocation_epoch=revocation_epoch,
                    consumption_state="REVOKED",
                    decision_revision=decision.decision_revision + 1,
                )
                payload = _DecisionRevokedV1(
                    decision=revoked,
                    expected_decision_revision=decision.decision_revision,
                    actor_id=actor_id,
                    source=source,
                    revoked_at_unix_ms=revoked_at_unix_ms,
                )
            except (TypeError, ValueError) as exc:
                raise self._error(
                    f"Invalid Plugin execution revocation: {exc}",
                    code="invalid_plugin_execution_revocation",
                ) from exc
            self._append_unlocked(
                replayed,
                event_kind="decision_revoked",
                payload=payload,
            )
            return revoked

    def snapshot(self) -> PluginExecutionDecisionSnapshotV1:
        with self._lock():
            replayed = self._load_and_replay_unlocked()
        return PluginExecutionDecisionSnapshotV1(
            journal_revision=len(replayed.events),
            decisions=tuple(
                sorted(replayed.decisions.values(), key=lambda x: x.decision_id)
            ),
            execution_uses=tuple(
                sorted(
                    replayed.execution_uses.values(), key=lambda x: x.execution_use_id
                )
            ),
        )

    def _require_subject_scope(
        self,
        subject: PluginExecutionApprovalSubject,
    ) -> None:
        if not isinstance(subject, PluginExecutionApprovalSubject):
            raise TypeError("Plugin execution operation requires a Subject v2")
        if subject.scope_id != self._scope_id:
            raise self._error(
                "Plugin execution Subject belongs to another durable scope",
                code="plugin_execution_decision_scope_mismatch",
            )

    def _require_decision_available(
        self,
        decision: PluginApprovalDecisionRecordV1,
    ) -> None:
        if decision.consumption_state == "DENIED":
            code = "plugin_execution_decision_denied"
        elif decision.consumption_state == "CONSUMED":
            code = "plugin_execution_decision_consumed"
        elif decision.consumption_state == "REVOKED":
            code = "plugin_execution_decision_revoked"
        else:
            return
        raise self._error(
            "Plugin execution decision is not available",
            code=code,
        )

    def _retained_authority_is_live(
        self,
        authorization: PluginApprovalAuthorizationV1,
    ) -> bool:
        try:
            result = self._retained_authority_validator(authorization)
        except Exception:
            return False
        return result is True

    def _now(self) -> int:
        value = self._clock()
        _require_non_negative_integer(value, name="current Unix milliseconds")
        return value

    def _lock(self):
        return journal_file_lock(
            self._path,
            "exclusive",
            lock_suffix=DURABLE_LOCKED_JOURNAL.lock_suffix,
        )

    def _require_journal_revision(
        self,
        replayed: _ReplayedExecutionJournal,
        expected: int,
    ) -> None:
        if len(replayed.events) != expected:
            raise self._error(
                "Expected Plugin execution journal revision does not match",
                code="plugin_execution_journal_revision_conflict",
            )

    def _append_unlocked(
        self,
        replayed: _ReplayedExecutionJournal,
        *,
        event_kind: PluginExecutionJournalEventKind,
        payload: _PluginExecutionEventPayload,
    ) -> None:
        event = _PluginExecutionJournalEventV1(
            journal_revision=len(replayed.events) + 1,
            expected_journal_revision=len(replayed.events),
            event_kind=event_kind,
            payload=payload,
        )
        append_jsonl_record(
            self._path,
            event,
            record_codec=_PLUGIN_EXECUTION_EVENT_CODEC,
            format_profile=SORTED_UNICODE_JSONL_FORMAT,
            durability=self._unlocked_durability,
        )

    def _load_and_replay_unlocked(self) -> _ReplayedExecutionJournal:
        if not self._path.exists():
            return _empty_replay()
        try:
            snapshot: JsonlSnapshot[None, _PluginExecutionJournalEventV1] = load_jsonl(
                self._path,
                record_codec=_PLUGIN_EXECUTION_EVENT_CODEC,
                format_profile=SORTED_UNICODE_JSONL_FORMAT,
                durability=self._unlocked_durability,
                load_policy=self._load_policy,
            )
        except JournalFileError as exc:
            code = (
                exc.code
                if exc.code
                in {
                    "invalid_plugin_execution_journal_record",
                    "unsupported_plugin_execution_journal_record_version",
                }
                else "plugin_execution_journal_corrupt"
            )
            raise self._error(
                "Plugin execution journal cannot be decoded",
                code=code,
            ) from exc
        replayed = _replay(snapshot.records, path=self._path)
        if any(
            decision.scope_kind != self._scope_kind
            or decision.scope_id != self._scope_id
            for decision in replayed.decisions.values()
        ):
            raise self._error(
                "Plugin execution journal contains another durable scope",
                code="plugin_execution_journal_corrupt",
            )
        return replayed

    def _error(self, message: str, *, code: str) -> PluginExecutionJournalError:
        return PluginExecutionJournalError(message, code=code, path=self._path)


def _empty_replay() -> _ReplayedExecutionJournal:
    return _ReplayedExecutionJournal(
        events=(),
        decisions={},
        subject_decisions={},
        execution_uses={},
    )


def _replay(
    events: tuple[_PluginExecutionJournalEventV1, ...],
    *,
    path: Path,
) -> _ReplayedExecutionJournal:
    replayed = _empty_replay()
    replayed.events = events
    for expected_revision, event in enumerate(events, start=1):
        if event.journal_revision != expected_revision:
            raise _corrupt(path, "Plugin execution journal revision is not contiguous")
        if event.expected_journal_revision != expected_revision - 1:
            raise _corrupt(path, "Plugin execution journal CAS chain is not contiguous")
        payload = event.payload
        if isinstance(payload, _DecisionIssuedV1):
            decision = payload.decision
            latest = _latest_subject_decision(replayed, decision.subject_digest)
            if (
                decision.decision_id in replayed.decisions
                or decision.decision_revision != 1
                or decision.consumed_execution_use_id is not None
                or decision.consumption_state
                != ("AVAILABLE" if decision.disposition == "approved" else "DENIED")
                or (
                    latest is not None
                    and latest.consumption_state == "AVAILABLE"
                    and decision.issued_at_unix_ms < latest.expires_at_unix_ms
                )
            ):
                raise _corrupt(path, "Plugin execution decision issue is invalid")
            replayed.decisions[decision.decision_id] = decision
            replayed.subject_decisions.setdefault(decision.subject_digest, []).append(
                decision.decision_id
            )
            continue
        if isinstance(payload, (_DecisionRevokedV1, _ExecutionConsumedV1)):
            current = replayed.decisions.get(payload.decision.decision_id)
            if current is None:
                raise _corrupt(path, "Plugin execution transition has no decision")
            if payload.expected_decision_revision != current.decision_revision:
                raise _corrupt(
                    path,
                    "Plugin execution decision revision is not contiguous",
                )
            if current.consumption_state != "AVAILABLE":
                raise _corrupt(
                    path,
                    "Plugin execution decision was used more than once",
                )
            if isinstance(payload, _DecisionRevokedV1):
                expected = replace(
                    current,
                    revocation_epoch=payload.decision.revocation_epoch,
                    consumption_state="REVOKED",
                    decision_revision=current.decision_revision + 1,
                )
                if (
                    payload.decision.revocation_epoch <= current.revocation_epoch
                    or payload.decision != expected
                ):
                    raise _corrupt(
                        path,
                        "Plugin execution revocation cannot be replayed",
                    )
                replayed.decisions[current.decision_id] = payload.decision
                continue
            reservation = payload.reservation
            expected_decision = replace(
                current,
                consumption_state="CONSUMED",
                consumed_execution_use_id=reservation.execution_use_id,
                decision_revision=current.decision_revision + 1,
            )
            if (
                payload.decision != expected_decision
                or reservation.execution_use_id in replayed.execution_uses
                or reservation.decision_id != current.decision_id
                or reservation.subject_digest != current.subject_digest
                or reservation.instance_revision_ref != current.instance_revision_ref
                or reservation.policy_revision != current.policy_revision
                or reservation.source_trust_policy_revision
                != current.source_trust_policy_revision
                or reservation.revocation_epoch != current.revocation_epoch
                or reservation.state != "CONSUMED_NOT_STARTED"
            ):
                raise _corrupt(
                    path,
                    "Plugin execution consumption cannot be replayed",
                )
            replayed.decisions[current.decision_id] = payload.decision
            replayed.execution_uses[reservation.execution_use_id] = reservation
            continue
        if isinstance(payload, _ExecutionUseTransitionedV1):
            reservation = payload.reservation
            current_use = replayed.execution_uses.get(reservation.execution_use_id)
            if current_use is None:
                raise _corrupt(
                    path,
                    "Plugin execution use transition has no reservation",
                )
            expected_use = replace(current_use, state=reservation.state)
            if (
                current_use.state != payload.expected_state
                or (payload.expected_state, reservation.state)
                not in _ALLOWED_EXECUTION_USE_TRANSITIONS
                or reservation != expected_use
            ):
                raise _corrupt(
                    path,
                    "Plugin execution use transition cannot be replayed",
                )
            replayed.execution_uses[reservation.execution_use_id] = reservation
            continue
        assert isinstance(payload, _ExecutionUsesRecoveredV1)
        for reservation in payload.reservations:
            current_use = replayed.execution_uses.get(reservation.execution_use_id)
            if current_use is None:
                raise _corrupt(
                    path,
                    "Plugin execution recovery has no reservation",
                )
            expected_use = replace(current_use, state="CANCELLED_BEFORE_START")
            if (
                current_use.state != "CONSUMED_NOT_STARTED"
                or current_use.host_boot_id == payload.current_host_boot_id
                or reservation != expected_use
            ):
                raise _corrupt(
                    path,
                    "Plugin execution recovery cannot be replayed",
                )
            replayed.execution_uses[reservation.execution_use_id] = reservation
    return replayed


def _polluted_import_realms(
    execution_uses: Iterable[PluginExecutionUseReservationV1],
) -> tuple[PluginImportRealmRefV1, ...]:
    return tuple(
        sorted(
            {
                PluginImportRealmRefV1(
                    host_boot_id=item.host_boot_id,
                    import_realm_id=item.import_realm_id,
                )
                for item in execution_uses
                if item.state in {"STARTING", "FAILED_AFTER_START"}
            }
        )
    )


def _latest_subject_decision(
    replayed: _ReplayedExecutionJournal,
    subject_digest: str,
) -> PluginApprovalDecisionRecordV1 | None:
    decision_ids = replayed.subject_decisions.get(subject_digest)
    if not decision_ids:
        return None
    return replayed.decisions[decision_ids[-1]]


def _corrupt(path: Path, message: str) -> PluginExecutionJournalError:
    return PluginExecutionJournalError(
        message,
        code="plugin_execution_journal_corrupt",
        path=path,
    )


def _invalid_record(message: str) -> PluginExecutionJournalRecordCodecError:
    return PluginExecutionJournalRecordCodecError(
        message,
        code="invalid_plugin_execution_journal_record",
    )


def _wire_object(value: object, *, name: str) -> Mapping[str, object]:
    try:
        return require_json_mapping(value, name=name)
    except JsonValueError as exc:
        raise _invalid_record(str(exc)) from exc


def _wire_exact_fields(
    value: Mapping[str, object],
    *,
    keys: set[str],
    name: str,
) -> None:
    if set(value) != keys:
        raise _invalid_record(f"{name} fields do not match the exact schema")


def _wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise _invalid_record(f"{name} must be a non-empty string")
    return value


def _wire_optional_string(value: object, *, name: str) -> str | None:
    if value is None:
        return None
    return _wire_string(value, name=name)


def _wire_integer(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise _invalid_record(f"{name} must be an integer")
    return value


def _wire_version(value: object, *, expected: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value != expected:
        raise PluginExecutionJournalRecordCodecError(
            "Unsupported Plugin execution journal record version",
            code="unsupported_plugin_execution_journal_record_version",
        )


def _require_nonempty(value: object, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")


def _require_hex(value: object, *, length: int, name: str) -> None:
    _require_nonempty(value, name=name)
    assert isinstance(value, str)
    if len(value) != length or any(character not in _HEX for character in value):
        raise ValueError(f"{name} must be {length} lowercase hexadecimal characters")
    if value != value.lower():
        raise ValueError(f"{name} must be lowercase hexadecimal")


def _require_sha256(value: object, *, name: str) -> None:
    _require_hex(value, length=64, name=name)


def _require_non_negative_integer(value: object, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_positive_integer(value: object, *, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_expected_revision(value: object) -> None:
    _require_non_negative_integer(value, name="expected journal revision")


def _require_version(value: object, *, expected: int) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value != expected:
        raise ValueError(f"Unsupported Plugin execution record version: {value!r}")


__all__ = [
    "PLUGIN_APPROVAL_AUTHORIZATION_VERSION",
    "PLUGIN_APPROVAL_DECISION_RECORD_VERSION",
    "PLUGIN_EXECUTION_JOURNAL_EVENT_VERSION",
    "PLUGIN_EXECUTION_RECEIPT_VERSION",
    "PLUGIN_EXECUTION_USE_VERSION",
    "PluginApprovalAuthorizationV1",
    "PluginApprovalDecisionRecordV1",
    "PluginExecutionConsumptionReceiptV1",
    "PluginExecutionDecisionJournal",
    "PluginExecutionDecisionSnapshotV1",
    "PluginExecutionJournalError",
    "PluginExecutionJournalRecordCodecError",
    "PluginExecutionRecoveryResultV1",
    "PluginExecutionUseReservationV1",
    "PluginImportRealmRefV1",
]
