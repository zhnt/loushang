from __future__ import annotations

import secrets
import threading
import weakref
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from time import monotonic
from typing import Literal, Protocol, cast

from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.declarations import (
    PLUGIN_DECLARATION_DOCUMENT_VERSION,
    PluginContributionReservation,
    PluginDeclaration,
    PluginDeclarationCodecError,
    PluginDeclarationDocument,
    PluginDeclarationSource,
    _freeze_json_mapping,
    _thaw_json,
)
from loushang.harness.resources.plugins.locators import parse_plugin_entrypoint
from loushang.harness.resources.plugins.types import (
    PluginSource,
    PluginSourceBinding,
    PublishedPluginPackage,
)

PLUGIN_EFFECTIVE_CONFIGURATION_SET_VERSION = 1
PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION = 2
PLUGIN_EXECUTION_DECISION_RECORD_VERSION = 2
PLUGIN_DECLARATION_EVIDENCE_VERSION = 1
PLUGIN_PREFLIGHT_CONTEXT_VERSION = 1
PLUGIN_SELECTION_PLAN_VERSION = 2
PLUGIN_SOURCE_TRUST_SNAPSHOT_VERSION = 1
_PLUGIN_HOST_BOOT_ID = secrets.token_hex(16)
_PLUGIN_PREFLIGHT_TTL_SECONDS = 300.0
_PLUGIN_MAX_ACTIVE_ATTEMPTS = 1024
_PLUGIN_MAX_TERMINAL_TOMBSTONES = 8192
_PLUGIN_MAX_ATTEMPT_LIFETIME_SECONDS = 300.0


class PluginSelectionError(RuntimeError):
    """Structured fail-closed error from inert Plugin selection."""

    def __init__(self, message: str, *, code: str, path: Path = Path()) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True, order=True, slots=True)
class PluginContributionRef:
    plugin_id: str
    contribution_id: str

    def __post_init__(self) -> None:
        _require_nonempty(self.plugin_id, name="Plugin id")
        _require_nonempty(self.contribution_id, name="contribution id")


@dataclass(frozen=True, slots=True)
class PluginInstanceRevisionRef:
    instance_id: str
    plugin_id: str
    revision: int

    def __post_init__(self) -> None:
        _require_nonempty(self.instance_id, name="Plugin instance id")
        _require_nonempty(self.plugin_id, name="Plugin id")
        if (
            not isinstance(self.revision, int)
            or isinstance(self.revision, bool)
            or self.revision < 1
        ):
            raise ValueError("Plugin instance revision must be a positive integer")

    def to_dict(self) -> dict[str, object]:
        return {
            "instanceId": self.instance_id,
            "pluginId": self.plugin_id,
            "revision": self.revision,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginInstanceRevisionRef:
        document = _selection_wire_object(value, name="Plugin instance revision ref")
        _selection_wire_exact_fields(
            document,
            keys={"instanceId", "pluginId", "revision"},
            name="Plugin instance revision ref",
        )
        try:
            return cls(
                instance_id=_selection_wire_string(
                    document["instanceId"], name="Plugin instance id"
                ),
                plugin_id=_selection_wire_string(
                    document["pluginId"], name="Plugin id"
                ),
                revision=_selection_wire_integer(
                    document["revision"], name="Plugin instance revision"
                ),
            )
        except PluginDeclarationCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise PluginDeclarationCodecError(
                f"Invalid Plugin instance revision ref: {exc}",
                code="plugin_declaration_field_value_mismatch",
            ) from exc


@dataclass(frozen=True, slots=True)
class PluginPreflightContextV1:
    product_id: str
    scope_id: str
    policy_revision: str
    instance_revision_refs: tuple[PluginInstanceRevisionRef, ...]
    context_version: int = PLUGIN_PREFLIGHT_CONTEXT_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.product_id, name="Product id")
        _require_nonempty(self.scope_id, name="scope id")
        _require_nonempty(self.policy_revision, name="policy revision")
        _require_exact_version(
            self.context_version,
            supported=PLUGIN_PREFLIGHT_CONTEXT_VERSION,
            name="Plugin preflight context",
        )
        refs = self.instance_revision_refs
        if not refs or any(
            not isinstance(item, PluginInstanceRevisionRef) for item in refs
        ):
            raise TypeError("Plugin preflight context requires instance revision refs")
        expected = tuple(
            sorted(
                refs,
                key=lambda item: (item.plugin_id, item.instance_id, item.revision),
            )
        )
        if refs != expected:
            raise ValueError("Plugin instance revision refs must be strictly sorted")
        plugin_ids = tuple(item.plugin_id for item in refs)
        instance_ids = tuple(item.instance_id for item in refs)
        if (
            len(plugin_ids) != len(set(plugin_ids))
            or len(instance_ids) != len(set(instance_ids))
            or len(refs) != len(set(refs))
        ):
            raise ValueError("Plugin instance revision refs must be unique")


@dataclass(frozen=True, order=True, slots=True)
class PluginSourceTrustSnapshotV1:
    plugin_id: str
    package_source_identity: str
    source_trust_class: str
    source_trust_policy_revision: str
    trusted: bool
    trust_snapshot_version: int = PLUGIN_SOURCE_TRUST_SNAPSHOT_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.plugin_id, name="Plugin id")
        _require_nonempty(self.package_source_identity, name="package source identity")
        _require_nonempty(self.source_trust_class, name="source trust class")
        _require_nonempty(
            self.source_trust_policy_revision,
            name="source trust policy revision",
        )
        if not isinstance(self.trusted, bool):
            raise TypeError("Plugin source trust decision must be a boolean")
        _require_exact_version(
            self.trust_snapshot_version,
            supported=PLUGIN_SOURCE_TRUST_SNAPSHOT_VERSION,
            name="Plugin source trust snapshot",
        )


@dataclass(frozen=True, slots=True)
class PluginEffectiveConfigurationEntry:
    plugin_id: str
    contribution_id: str
    configuration: Mapping[str, object]

    def __post_init__(self) -> None:
        _require_nonempty(self.plugin_id, name="Plugin id")
        _require_nonempty(self.contribution_id, name="contribution id")
        try:
            _validate_effective_configuration_value(self.configuration)
            configuration = _freeze_json_mapping(self.configuration)
        except PluginSelectionError:
            raise
        except (TypeError, ValueError) as exc:
            raise PluginSelectionError(
                "Plugin effective configuration is invalid.",
                code="invalid_plugin_effective_configuration",
            ) from exc
        object.__setattr__(self, "configuration", configuration)

    @property
    def ref(self) -> PluginContributionRef:
        return PluginContributionRef(self.plugin_id, self.contribution_id)

    def to_dict(self) -> dict[str, object]:
        return {
            "configuration": _thaw_json(self.configuration),
            "contributionId": self.contribution_id,
            "pluginId": self.plugin_id,
        }


@dataclass(frozen=True, slots=True)
class PluginEffectiveConfigurationSetV1:
    entries: tuple[PluginEffectiveConfigurationEntry, ...]
    configuration_set_version: int = PLUGIN_EFFECTIVE_CONFIGURATION_SET_VERSION

    def __post_init__(self) -> None:
        _require_exact_version(
            self.configuration_set_version,
            supported=PLUGIN_EFFECTIVE_CONFIGURATION_SET_VERSION,
            name="Plugin effective configuration set",
        )
        if any(
            not isinstance(item, PluginEffectiveConfigurationEntry)
            for item in self.entries
        ):
            raise TypeError("Plugin effective configuration entries have invalid type")
        expected = tuple(
            sorted(
                self.entries,
                key=lambda item: (item.plugin_id, item.contribution_id),
            )
        )
        refs = tuple(item.ref for item in self.entries)
        if self.entries != expected or len(refs) != len(set(refs)):
            raise PluginSelectionError(
                "Plugin effective configuration entries must be sorted and unique.",
                code="invalid_plugin_effective_configuration",
            )


@dataclass(frozen=True, slots=True)
class PluginSelectionPlanV2:
    """The sole Product-owned input to Plugin declaration preflight."""

    context: PluginPreflightContextV1
    selected_plugin_ids: tuple[str, ...]
    selected_contributions: tuple[PluginContributionRef, ...]
    source_trust_snapshots: tuple[PluginSourceTrustSnapshotV1, ...]
    effective_configuration_set: PluginEffectiveConfigurationSetV1
    allowed_authority_ceiling: tuple[str, ...]
    plan_version: int = PLUGIN_SELECTION_PLAN_VERSION

    def __post_init__(self) -> None:
        _require_exact_version(
            self.plan_version,
            supported=PLUGIN_SELECTION_PLAN_VERSION,
            name="Plugin selection plan",
        )
        if not isinstance(self.context, PluginPreflightContextV1):
            raise TypeError("Plugin selection plan requires an exact context")
        plugin_ids = _strict_sorted_unique_strings(
            self.selected_plugin_ids,
            name="selected Plugin ids",
        )
        if not plugin_ids:
            raise ValueError("Selected Plugin ids must not be empty")
        contributions = self.selected_contributions
        if not contributions or any(
            not isinstance(item, PluginContributionRef) for item in contributions
        ):
            raise TypeError("Selected Plugin contributions have invalid type")
        expected_contributions = tuple(sorted(contributions))
        if contributions != expected_contributions or len(contributions) != len(
            set(contributions)
        ):
            raise ValueError(
                "Selected Plugin contributions must be strictly sorted and unique"
            )
        if any(item.plugin_id not in plugin_ids for item in contributions):
            raise ValueError("Selected contributions must belong to selected Plugins")
        trust = self.source_trust_snapshots
        if any(not isinstance(item, PluginSourceTrustSnapshotV1) for item in trust):
            raise TypeError("Plugin source trust snapshots have invalid type")
        if trust != tuple(sorted(trust, key=lambda item: item.plugin_id)):
            raise ValueError("Plugin source trust snapshots must be strictly sorted")
        trust_ids = tuple(item.plugin_id for item in trust)
        if len(trust_ids) != len(set(trust_ids)) or set(trust_ids) != set(plugin_ids):
            raise ValueError(
                "Plugin source trust snapshots must cover selected Plugins"
            )
        instance_plugin_ids = tuple(
            item.plugin_id for item in self.context.instance_revision_refs
        )
        if set(instance_plugin_ids) != set(plugin_ids):
            raise ValueError(
                "Plugin instance revision refs must cover selected Plugins"
            )
        if not isinstance(
            self.effective_configuration_set,
            PluginEffectiveConfigurationSetV1,
        ):
            raise TypeError(
                "Plugin selection plan requires an effective configuration set"
            )
        configuration_refs = {
            item.ref for item in self.effective_configuration_set.entries
        }
        if not set(contributions).issubset(configuration_refs) or any(
            item.plugin_id not in plugin_ids for item in configuration_refs
        ):
            raise PluginSelectionError(
                "Plugin effective configuration does not cover Product selection.",
                code="invalid_plugin_effective_configuration",
            )
        _strict_sorted_unique_strings(
            self.allowed_authority_ceiling,
            name="allowed authority ceiling",
        )


@dataclass(frozen=True, slots=True)
class PluginExecutionApprovalSubject:
    plugin_id: str
    package_content_digest: str
    dependency_lock_digest: str
    entrypoint: str
    package_source_identity: str
    source_trust_class: str
    source_trust_policy_revision: str
    product_id: str
    scope_id: str
    policy_revision: str
    ambient_host_authority: bool
    configuration_map_fingerprint: str
    requested_authorities: tuple[str, ...]
    allowed_authority_ceiling: tuple[str, ...]
    reservation_closure_fingerprint: str
    source_descriptor_fingerprint: str
    instance_revision_ref: PluginInstanceRevisionRef
    schema_version: int = PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("Plugin id", self.plugin_id),
            ("entrypoint", self.entrypoint),
            ("package source identity", self.package_source_identity),
            ("source trust class", self.source_trust_class),
            ("source trust policy revision", self.source_trust_policy_revision),
            ("Product id", self.product_id),
            ("scope id", self.scope_id),
            ("policy revision", self.policy_revision),
        ):
            _require_nonempty(value, name=name)
        for name, value in (
            ("package content digest", self.package_content_digest),
            ("dependency lock digest", self.dependency_lock_digest),
            ("configuration map fingerprint", self.configuration_map_fingerprint),
            (
                "reservation closure fingerprint",
                self.reservation_closure_fingerprint,
            ),
            ("source descriptor fingerprint", self.source_descriptor_fingerprint),
        ):
            _require_sha256(value, name=name)
        if not isinstance(self.ambient_host_authority, bool):
            raise TypeError("ambient host authority must be a boolean")
        if not self.ambient_host_authority:
            raise ValueError("PLC1B in-process Subject requires ambient host authority")
        _require_exact_version(
            self.schema_version,
            supported=PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION,
            name="Plugin execution approval subject",
        )
        parse_plugin_entrypoint(self.entrypoint)
        if (
            PluginDeclarationSource.in_process(self.entrypoint).fingerprint
            != self.source_descriptor_fingerprint
        ):
            raise ValueError(
                "Subject source descriptor fingerprint must match its entrypoint"
            )
        requested = _strict_sorted_unique_strings(
            self.requested_authorities, name="requested authorities"
        )
        ceiling = _strict_sorted_unique_strings(
            self.allowed_authority_ceiling, name="allowed authority ceiling"
        )
        if not set(requested).issubset(ceiling):
            raise ValueError("Requested authorities must be a subset of the ceiling")
        if not isinstance(self.instance_revision_ref, PluginInstanceRevisionRef):
            raise TypeError("Subject requires a Plugin instance revision ref")
        if self.instance_revision_ref.plugin_id != self.plugin_id:
            raise ValueError("Subject instance Plugin id must match Subject Plugin id")

    @property
    def digest(self) -> str:
        return _digest_document(
            {
                "domain": "loushang.plugin-execution-approval-subject/v2",
                "subject": self.to_dict(),
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "allowedAuthorityCeiling": list(self.allowed_authority_ceiling),
            "ambientHostAuthority": self.ambient_host_authority,
            "configurationMapFingerprint": self.configuration_map_fingerprint,
            "dependencyLockDigest": self.dependency_lock_digest,
            "entrypoint": self.entrypoint,
            "instanceRevisionRef": self.instance_revision_ref.to_dict(),
            "packageContentDigest": self.package_content_digest,
            "packageSourceIdentity": self.package_source_identity,
            "pluginId": self.plugin_id,
            "policyRevision": self.policy_revision,
            "productId": self.product_id,
            "requestedAuthorities": list(self.requested_authorities),
            "reservationClosureFingerprint": self.reservation_closure_fingerprint,
            "scopeId": self.scope_id,
            "schemaVersion": self.schema_version,
            "sourceDescriptorFingerprint": self.source_descriptor_fingerprint,
            "sourceTrustClass": self.source_trust_class,
            "sourceTrustPolicyRevision": self.source_trust_policy_revision,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginExecutionApprovalSubject:
        document = _selection_wire_object(value, name="Plugin execution subject")
        _selection_wire_version(
            document,
            key="schemaVersion",
            supported=PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION,
            code="unsupported_plugin_execution_approval_subject_version",
        )
        _selection_wire_exact_fields(
            document,
            keys={
                "allowedAuthorityCeiling",
                "ambientHostAuthority",
                "configurationMapFingerprint",
                "dependencyLockDigest",
                "entrypoint",
                "instanceRevisionRef",
                "packageContentDigest",
                "packageSourceIdentity",
                "pluginId",
                "policyRevision",
                "productId",
                "requestedAuthorities",
                "reservationClosureFingerprint",
                "schemaVersion",
                "scopeId",
                "sourceDescriptorFingerprint",
                "sourceTrustClass",
                "sourceTrustPolicyRevision",
            },
            name="Plugin execution subject",
        )
        ambient = document["ambientHostAuthority"]
        if not isinstance(ambient, bool):
            raise PluginDeclarationCodecError(
                "ambientHostAuthority must be a boolean",
                code="plugin_declaration_field_type_mismatch",
            )
        try:
            return cls(
                plugin_id=_selection_wire_string(
                    document["pluginId"], name="Plugin id"
                ),
                package_content_digest=_selection_wire_string(
                    document["packageContentDigest"], name="package content digest"
                ),
                dependency_lock_digest=_selection_wire_string(
                    document["dependencyLockDigest"], name="dependency lock digest"
                ),
                entrypoint=_selection_wire_string(
                    document["entrypoint"], name="entrypoint"
                ),
                package_source_identity=_selection_wire_string(
                    document["packageSourceIdentity"], name="package source identity"
                ),
                source_trust_class=_selection_wire_string(
                    document["sourceTrustClass"], name="source trust class"
                ),
                source_trust_policy_revision=_selection_wire_string(
                    document["sourceTrustPolicyRevision"],
                    name="source trust policy revision",
                ),
                product_id=_selection_wire_string(
                    document["productId"], name="Product id"
                ),
                scope_id=_selection_wire_string(document["scopeId"], name="scope id"),
                policy_revision=_selection_wire_string(
                    document["policyRevision"], name="policy revision"
                ),
                ambient_host_authority=ambient,
                configuration_map_fingerprint=_selection_wire_string(
                    document["configurationMapFingerprint"],
                    name="configuration map fingerprint",
                ),
                requested_authorities=_selection_wire_string_list(
                    document["requestedAuthorities"], name="requested authorities"
                ),
                allowed_authority_ceiling=_selection_wire_string_list(
                    document["allowedAuthorityCeiling"],
                    name="allowed authority ceiling",
                ),
                reservation_closure_fingerprint=_selection_wire_string(
                    document["reservationClosureFingerprint"],
                    name="reservation closure fingerprint",
                ),
                source_descriptor_fingerprint=_selection_wire_string(
                    document["sourceDescriptorFingerprint"],
                    name="source descriptor fingerprint",
                ),
                instance_revision_ref=PluginInstanceRevisionRef.from_dict(
                    document["instanceRevisionRef"]
                ),
            )
        except PluginDeclarationCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise PluginDeclarationCodecError(
                f"Invalid Plugin execution subject: {exc}",
                code="plugin_declaration_field_value_mismatch",
            ) from exc


@dataclass(frozen=True, slots=True)
class PluginExecutionDecisionRecord:
    decision_id: str
    subject_digest: str
    policy_revision: str
    disposition: Literal["approved", "denied"]
    decision_record_version: int = PLUGIN_EXECUTION_DECISION_RECORD_VERSION
    subject_schema_version: int = PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION

    def __post_init__(self) -> None:
        _require_nonempty(self.decision_id, name="decision id")
        _require_sha256(self.subject_digest, name="decision subject digest")
        _require_nonempty(self.policy_revision, name="decision policy revision")
        if self.disposition not in {"approved", "denied"}:
            raise ValueError("Unsupported Plugin execution decision disposition")
        _require_exact_version(
            self.decision_record_version,
            supported=PLUGIN_EXECUTION_DECISION_RECORD_VERSION,
            name="Plugin execution decision record",
        )
        _require_exact_version(
            self.subject_schema_version,
            supported=PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION,
            name="Plugin execution approval subject",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "decisionId": self.decision_id,
            "decisionRecordVersion": self.decision_record_version,
            "disposition": self.disposition,
            "policyRevision": self.policy_revision,
            "subjectDigest": self.subject_digest,
            "subjectSchemaVersion": self.subject_schema_version,
        }

    @classmethod
    def from_dict(cls, value: object) -> PluginExecutionDecisionRecord:
        document = _selection_wire_object(value, name="Plugin execution decision")
        _selection_wire_version(
            document,
            key="decisionRecordVersion",
            supported=PLUGIN_EXECUTION_DECISION_RECORD_VERSION,
            code="unsupported_plugin_execution_decision_record_version",
        )
        if "subjectSchemaVersion" not in document:
            raise PluginDeclarationCodecError(
                "subjectSchemaVersion is missing",
                code="unsupported_plugin_execution_approval_subject_version",
            )
        subject_version = document["subjectSchemaVersion"]
        if not isinstance(subject_version, int) or isinstance(subject_version, bool):
            raise PluginDeclarationCodecError(
                "subjectSchemaVersion must be an integer",
                code="plugin_declaration_field_type_mismatch",
            )
        if subject_version != PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION:
            raise PluginDeclarationCodecError(
                "Unsupported Plugin execution approval subject version",
                code="unsupported_plugin_execution_approval_subject_version",
            )
        _selection_wire_exact_fields(
            document,
            keys={
                "decisionId",
                "decisionRecordVersion",
                "disposition",
                "policyRevision",
                "subjectDigest",
                "subjectSchemaVersion",
            },
            name="Plugin execution decision",
        )
        disposition = _selection_wire_string(
            document["disposition"], name="decision disposition"
        )
        try:
            return cls(
                decision_id=_selection_wire_string(
                    document["decisionId"], name="decision id"
                ),
                subject_digest=_selection_wire_string(
                    document["subjectDigest"], name="decision subject digest"
                ),
                policy_revision=_selection_wire_string(
                    document["policyRevision"], name="decision policy revision"
                ),
                disposition=cast(Literal["approved", "denied"], disposition),
                decision_record_version=PLUGIN_EXECUTION_DECISION_RECORD_VERSION,
                subject_schema_version=subject_version,
            )
        except PluginDeclarationCodecError:
            raise
        except (TypeError, ValueError) as exc:
            raise PluginDeclarationCodecError(
                f"Invalid Plugin execution decision: {exc}",
                code="plugin_declaration_field_value_mismatch",
            ) from exc


@dataclass(frozen=True, slots=True)
class PluginExecutionDecisionMissing:
    disposition: Literal["missing"] = "missing"

    def __post_init__(self) -> None:
        if self.disposition != "missing":
            raise ValueError("Unsupported missing execution decision disposition")


@dataclass(frozen=True, slots=True)
class PluginExecutionDecisionCurrent:
    decision: PluginExecutionDecisionRecord
    disposition: Literal["current"] = "current"

    def __post_init__(self) -> None:
        if not isinstance(self.decision, PluginExecutionDecisionRecord):
            raise TypeError("Current lookup result requires a DecisionRecord v2")
        if self.disposition != "current":
            raise ValueError("Unsupported current execution decision disposition")


PluginExecutionDecisionLookupResult = (
    PluginExecutionDecisionMissing | PluginExecutionDecisionCurrent
)


class PluginExecutionDecisionLookupPort(Protocol):
    """Read-only Approval-owner lookup by one exact execution Subject."""

    def lookup_execution_decision(
        self,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginExecutionDecisionLookupResult: ...


class PendingOnlyPluginExecutionDecisionLookup:
    """Pre-PAP2 production adapter that can never return a positive decision."""

    def lookup_execution_decision(
        self,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginExecutionDecisionLookupResult:
        if not isinstance(subject, PluginExecutionApprovalSubject):
            raise TypeError("Plugin execution lookup requires a Subject v2")
        return PluginExecutionDecisionMissing()


@dataclass(frozen=True, slots=True)
class PluginDeclarationDataOnlyDisposition:
    kind: Literal["data_only"] = "data_only"

    def __post_init__(self) -> None:
        if self.kind != "data_only":
            raise ValueError("Unsupported data-only source disposition")


@dataclass(frozen=True, slots=True)
class PluginDeclarationExecutionSubjectDisposition:
    subject: PluginExecutionApprovalSubject
    kind: Literal["execution_subject"] = "execution_subject"

    def __post_init__(self) -> None:
        if not isinstance(self.subject, PluginExecutionApprovalSubject):
            raise TypeError("Executable source disposition requires a Subject v2")
        if self.kind != "execution_subject":
            raise ValueError("Unsupported executable source disposition")


PluginDeclarationSourceDisposition = (
    PluginDeclarationDataOnlyDisposition | PluginDeclarationExecutionSubjectDisposition
)


@dataclass(frozen=True, slots=True)
class PluginDeclarationSourceProposal:
    """Pure proposed facts for one complete package/source closure."""

    package: PublishedPluginPackage = field(repr=False)
    declaration_source: PluginDeclarationSource
    source_descriptor_fingerprint: str
    reservation_closure: tuple[PluginContributionReservation, ...]
    effective_configuration_entries: tuple[PluginEffectiveConfigurationEntry, ...]
    configuration_map_fingerprint: str
    trust_snapshot: PluginSourceTrustSnapshotV1
    requested_authorities: tuple[str, ...]
    allowed_authority_ceiling: tuple[str, ...]
    source_disposition: PluginDeclarationSourceDisposition

    def __post_init__(self) -> None:
        if not isinstance(self.package, PublishedPluginPackage):
            raise TypeError("Source proposal requires a published package")
        if not isinstance(self.declaration_source, PluginDeclarationSource):
            raise TypeError("Source proposal requires a declaration source")
        _require_sha256(
            self.source_descriptor_fingerprint,
            name="source descriptor fingerprint",
        )
        if self.declaration_source.fingerprint != self.source_descriptor_fingerprint:
            raise ValueError("Source proposal descriptor fingerprint does not match")
        closure = self.reservation_closure
        if not closure or any(
            not isinstance(item, PluginContributionReservation) for item in closure
        ):
            raise TypeError("Source proposal requires a reservation closure")
        if closure != tuple(sorted(closure, key=lambda item: item.contribution_id)):
            raise ValueError("Source proposal closure must be strictly sorted")
        contribution_ids = tuple(item.contribution_id for item in closure)
        if len(contribution_ids) != len(set(contribution_ids)):
            raise ValueError("Source proposal closure must be unique")
        if any(
            item.declaration_source != self.declaration_source
            or item.source_descriptor_fingerprint != self.source_descriptor_fingerprint
            for item in closure
        ):
            raise ValueError("Source proposal closure crosses declaration sources")
        if any(item not in self.package.contribution_index.items for item in closure):
            raise ValueError("Source proposal closure is not owned by its package")

        plugin_id = self.package.manifest.name
        entries = self.effective_configuration_entries
        if any(
            not isinstance(item, PluginEffectiveConfigurationEntry) for item in entries
        ):
            raise TypeError("Source proposal configuration entries have invalid type")
        expected_refs = tuple(
            PluginContributionRef(plugin_id, item.contribution_id) for item in closure
        )
        if tuple(item.ref for item in entries) != expected_refs:
            raise ValueError("Source proposal configuration does not match its closure")
        _require_sha256(
            self.configuration_map_fingerprint,
            name="configuration map fingerprint",
        )
        if (
            _configuration_map_fingerprint(entries)
            != self.configuration_map_fingerprint
        ):
            raise ValueError("Source proposal configuration fingerprint does not match")
        if not isinstance(self.trust_snapshot, PluginSourceTrustSnapshotV1):
            raise TypeError("Source proposal requires a trust snapshot")
        if self.trust_snapshot.plugin_id != plugin_id:
            raise ValueError(
                "Source proposal trust snapshot does not match its package"
            )

        requested = _strict_sorted_unique_strings(
            self.requested_authorities,
            name="requested authorities",
        )
        expected_requested = tuple(
            sorted(
                {
                    authority
                    for item in closure
                    for authority in item.requested_authorities
                }
            )
        )
        if requested != expected_requested:
            raise ValueError("Source proposal authorities do not match its closure")
        ceiling = _strict_sorted_unique_strings(
            self.allowed_authority_ceiling,
            name="allowed authority ceiling",
        )
        if not set(requested).issubset(ceiling):
            raise ValueError("Source proposal exceeds its authority ceiling")

        disposition = self.source_disposition
        if self.declaration_source.kind == "document":
            if not isinstance(disposition, PluginDeclarationDataOnlyDisposition):
                raise ValueError("Document source proposal must be data-only")
            return
        if not isinstance(disposition, PluginDeclarationExecutionSubjectDisposition):
            raise ValueError("In-process source proposal requires an execution Subject")
        subject = disposition.subject
        if (
            subject.plugin_id != plugin_id
            or subject.package_content_digest != self.package.content_digest
            or subject.dependency_lock_digest != self.package.dependency_lock.digest
            or subject.entrypoint != self.declaration_source.entrypoint
            or subject.package_source_identity
            != self.trust_snapshot.package_source_identity
            or subject.source_trust_class != self.trust_snapshot.source_trust_class
            or subject.source_trust_policy_revision
            != self.trust_snapshot.source_trust_policy_revision
            or subject.configuration_map_fingerprint
            != self.configuration_map_fingerprint
            or subject.requested_authorities != requested
            or subject.allowed_authority_ceiling != ceiling
            or subject.reservation_closure_fingerprint
            != _reservation_closure_fingerprint(closure)
            or subject.source_descriptor_fingerprint
            != self.source_descriptor_fingerprint
        ):
            raise ValueError("Source proposal Subject does not match proposed facts")

    @property
    def key(self) -> tuple[str, str]:
        return (self.package.manifest.name, self.source_descriptor_fingerprint)


@dataclass(frozen=True, slots=True)
class PluginPreflightProposal:
    """Non-authoritative, resumeless result of one complete validation pass."""

    plan: PluginSelectionPlanV2
    source_proposals: tuple[PluginDeclarationSourceProposal, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.plan, PluginSelectionPlanV2):
            raise TypeError("Plugin preflight proposal requires a Plan v2")
        sources = self.source_proposals
        if not sources or any(
            not isinstance(item, PluginDeclarationSourceProposal) for item in sources
        ):
            raise TypeError("Plugin preflight proposal requires source proposals")
        keys = tuple(item.key for item in sources)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError(
                "Plugin source proposals must be strictly sorted and unique"
            )
        if any(item.key[0] not in self.plan.selected_plugin_ids for item in sources):
            raise ValueError("Plugin source proposal is outside the Product selection")
        selected_refs = set(self.plan.selected_contributions)
        proposed_refs = {
            PluginContributionRef(
                item.package.manifest.name, contribution.contribution_id
            )
            for item in sources
            for contribution in item.reservation_closure
        }
        if not selected_refs.issubset(proposed_refs):
            raise ValueError("Plugin source proposals do not cover Product selection")
        if any(
            not selected_refs.intersection(
                PluginContributionRef(
                    source.package.manifest.name,
                    contribution.contribution_id,
                )
                for contribution in source.reservation_closure
            )
            for source in sources
        ):
            raise ValueError("Plugin source proposal is not selected by the Product")
        if {
            entry.ref for entry in self.plan.effective_configuration_set.entries
        } != proposed_refs:
            raise ValueError(
                "Plugin proposal configuration does not cover source closures"
            )
        instance_refs = {
            item.plugin_id: item for item in self.plan.context.instance_revision_refs
        }
        for source in sources:
            disposition = source.source_disposition
            if isinstance(disposition, PluginDeclarationExecutionSubjectDisposition):
                subject = disposition.subject
                if (
                    subject.product_id != self.plan.context.product_id
                    or subject.scope_id != self.plan.context.scope_id
                    or subject.policy_revision != self.plan.context.policy_revision
                    or subject.instance_revision_ref
                    != instance_refs[source.package.manifest.name]
                ):
                    raise ValueError("Source proposal Subject does not match its Plan")


@dataclass(frozen=True, slots=True)
class PluginDeclarationDataOnlyGate:
    kind: Literal["data_only"] = "data_only"

    def __post_init__(self) -> None:
        if self.kind != "data_only":
            raise ValueError("Unsupported data-only declaration gate")


@dataclass(frozen=True, slots=True)
class PluginDeclarationExecutionPreflightGate:
    subject: PluginExecutionApprovalSubject
    decision: PluginExecutionDecisionRecord
    kind: Literal["execution_preflight"] = "execution_preflight"

    def __post_init__(self) -> None:
        if not isinstance(self.subject, PluginExecutionApprovalSubject):
            raise TypeError("Execution-preflight gate requires a Subject v2")
        if not isinstance(self.decision, PluginExecutionDecisionRecord):
            raise TypeError("Execution-preflight gate requires a DecisionRecord v2")
        if self.kind != "execution_preflight":
            raise ValueError("Unsupported execution-preflight declaration gate")
        if (
            self.decision.disposition != "approved"
            or self.decision.subject_digest != self.subject.digest
            or self.decision.policy_revision != self.subject.policy_revision
            or self.decision.subject_schema_version != self.subject.schema_version
        ):
            raise ValueError("Execution-preflight gate decision does not match Subject")


PluginDeclarationGate = (
    PluginDeclarationDataOnlyGate | PluginDeclarationExecutionPreflightGate
)


@dataclass(frozen=True, slots=True)
class PluginDeclarationReservation:
    package: PublishedPluginPackage = field(repr=False)
    contribution: PluginContributionReservation
    source_group_id: str
    source_group_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.package, PublishedPluginPackage):
            raise TypeError("Declaration reservation requires a published package")
        if not isinstance(self.contribution, PluginContributionReservation):
            raise TypeError("Declaration reservation requires an indexed contribution")
        if self.contribution not in self.package.contribution_index.items:
            raise ValueError("Declaration reservation is not owned by its package")
        _require_sha256(self.source_group_id, name="source group id")
        _require_sha256(
            self.source_group_fingerprint,
            name="source group fingerprint",
        )

    @property
    def ref(self) -> PluginContributionRef:
        return PluginContributionRef(
            plugin_id=self.package.manifest.name,
            contribution_id=self.contribution.contribution_id,
        )


@dataclass(frozen=True, slots=True)
class PluginDeclarationSourceGroup:
    preflight_use_id: str
    source_group_id: str
    source_group_fingerprint: str
    package: PublishedPluginPackage = field(repr=False)
    declaration_source: PluginDeclarationSource
    source_descriptor_fingerprint: str
    context: PluginPreflightContextV1
    instance_revision_ref: PluginInstanceRevisionRef
    reservation_closure: tuple[PluginContributionReservation, ...]
    reservation_closure_fingerprint: str
    effective_configuration_entries: tuple[PluginEffectiveConfigurationEntry, ...]
    configuration_map_fingerprint: str
    trust_snapshot: PluginSourceTrustSnapshotV1
    requested_authorities: tuple[str, ...]
    allowed_authority_ceiling: tuple[str, ...]
    gate: PluginDeclarationGate

    def __post_init__(self) -> None:
        _require_hex(self.preflight_use_id, length=48, name="preflight use id")
        _require_sha256(self.source_group_id, name="source group id")
        _require_sha256(
            self.source_group_fingerprint,
            name="source group fingerprint",
        )
        if not isinstance(self.package, PublishedPluginPackage):
            raise TypeError("Source group requires a published package")
        if not isinstance(self.context, PluginPreflightContextV1):
            raise TypeError("Source group requires a preflight Context v1")
        if not isinstance(self.instance_revision_ref, PluginInstanceRevisionRef):
            raise TypeError("Source group requires an instance revision ref")
        plugin_id = self.package.manifest.name
        if self.instance_revision_ref.plugin_id != plugin_id:
            raise ValueError("Source group instance revision does not match package")
        proposal_disposition: PluginDeclarationSourceDisposition
        if isinstance(self.gate, PluginDeclarationDataOnlyGate):
            proposal_disposition = PluginDeclarationDataOnlyDisposition()
        elif isinstance(self.gate, PluginDeclarationExecutionPreflightGate):
            proposal_disposition = PluginDeclarationExecutionSubjectDisposition(
                subject=self.gate.subject
            )
        else:
            raise TypeError("Source group requires an exact declaration gate")
        proposal = PluginDeclarationSourceProposal(
            package=self.package,
            declaration_source=self.declaration_source,
            source_descriptor_fingerprint=self.source_descriptor_fingerprint,
            reservation_closure=self.reservation_closure,
            effective_configuration_entries=self.effective_configuration_entries,
            configuration_map_fingerprint=self.configuration_map_fingerprint,
            trust_snapshot=self.trust_snapshot,
            requested_authorities=self.requested_authorities,
            allowed_authority_ceiling=self.allowed_authority_ceiling,
            source_disposition=proposal_disposition,
        )
        expected_closure_fingerprint = _reservation_closure_fingerprint(
            self.reservation_closure
        )
        if self.reservation_closure_fingerprint != expected_closure_fingerprint:
            raise ValueError("Source group closure fingerprint does not match")
        expected_group_fingerprint = _source_group_fingerprint(
            proposal,
            context=self.context,
            instance_revision_ref=self.instance_revision_ref,
        )
        if self.source_group_fingerprint != expected_group_fingerprint:
            raise ValueError("Source group fingerprint does not match")
        if self.source_group_id != _source_group_id(
            self.preflight_use_id,
            self.source_group_fingerprint,
        ):
            raise ValueError("Source group id does not match its accepted attempt")
        if isinstance(self.gate, PluginDeclarationExecutionPreflightGate):
            subject = self.gate.subject
            if (
                subject.product_id != self.context.product_id
                or subject.scope_id != self.context.scope_id
                or subject.policy_revision != self.context.policy_revision
                or subject.instance_revision_ref != self.instance_revision_ref
            ):
                raise ValueError("Source group gate does not match its Context")

    @property
    def key(self) -> tuple[str, str]:
        return (self.package.manifest.name, self.source_descriptor_fingerprint)

    @property
    def reservations(self) -> tuple[PluginDeclarationReservation, ...]:
        return tuple(
            PluginDeclarationReservation(
                package=self.package,
                contribution=contribution,
                source_group_id=self.source_group_id,
                source_group_fingerprint=self.source_group_fingerprint,
            )
            for contribution in self.reservation_closure
        )


@dataclass(frozen=True, slots=True)
class _PluginPreflightTerminalHandle:
    token: str

    def __post_init__(self) -> None:
        _require_hex(self.token, length=48, name="preflight terminal handle")


@dataclass(frozen=True, slots=True, weakref_slot=True)
class AcceptedPluginPreflight:
    preflight_use_id: str
    host_boot_id: str
    expires_at: float
    context: PluginPreflightContextV1
    source_groups: tuple[PluginDeclarationSourceGroup, ...]
    _terminal_handle: _PluginPreflightTerminalHandle = field(
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        _require_hex(self.preflight_use_id, length=48, name="preflight use id")
        _require_hex(self.host_boot_id, length=32, name="host boot id")
        if (
            not isinstance(self.expires_at, int | float)
            or isinstance(self.expires_at, bool)
            or self.expires_at <= 0
        ):
            raise ValueError("Accepted preflight requires a monotonic deadline")
        if not isinstance(self.context, PluginPreflightContextV1):
            raise TypeError("Accepted preflight requires a Context v1")
        groups = self.source_groups
        if not groups or any(
            not isinstance(item, PluginDeclarationSourceGroup) for item in groups
        ):
            raise TypeError("Accepted preflight requires source groups")
        keys = tuple(item.key for item in groups)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise ValueError("Accepted source groups must be sorted and unique")
        if any(
            item.preflight_use_id != self.preflight_use_id
            or item.context != self.context
            for item in groups
        ):
            raise ValueError("Accepted source group does not match its attempt")
        group_ids = tuple(item.source_group_id for item in groups)
        if len(group_ids) != len(set(group_ids)):
            raise ValueError("Accepted source group ids must be unique")
        if not isinstance(self._terminal_handle, _PluginPreflightTerminalHandle):
            raise TypeError("Accepted preflight requires an internal terminal handle")
        if self._terminal_handle.token != self.preflight_use_id:
            raise ValueError("Accepted preflight terminal handle does not match use id")

    @property
    def host_epoch(self) -> str:
        return self.host_boot_id

    @property
    def reservations(self) -> tuple[PluginDeclarationReservation, ...]:
        return tuple(
            reservation
            for group in self.source_groups
            for reservation in group.reservations
        )


@dataclass(slots=True)
class _PluginGroupRuntime:
    group: PluginDeclarationSourceGroup
    state: Literal["pending", "claimed", "completed", "failed"] = "pending"
    claim_token: str = ""
    start_permit_token: str = ""
    cancel_requested: bool = False


@dataclass(slots=True)
class _ActivePluginPreflight:
    accepted: AcceptedPluginPreflight
    proposal: PluginPreflightProposal
    groups: dict[str, _PluginGroupRuntime]
    state: Literal[
        "active_open",
        "closing_abort",
        "closing_expire",
    ] = "active_open"
    in_flight: int = 0


@dataclass(frozen=True, slots=True)
class _TerminalPluginPreflight:
    accepted_ref: weakref.ReferenceType[AcceptedPluginPreflight]
    state: Literal["finalized", "aborted", "expired"]
    late_group_results: tuple[
        tuple[str, Literal["completed", "failed"]],
        ...,
    ]


@dataclass(frozen=True, slots=True)
class _PluginGroupClaimLease:
    preflight_use_id: str
    source_group_id: str
    claim_token: str


@dataclass(frozen=True, slots=True)
class PluginExecutionStartPermit:
    """Opaque aggregate proof that one claimed executable group won start."""

    preflight_use_id: str
    source_group_id: str
    host_boot_id: str
    _claim_token: str = field(repr=False, compare=False)
    _permit_token: str = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _require_hex(self.preflight_use_id, length=48, name="preflight use id")
        _require_sha256(self.source_group_id, name="source group id")
        _require_hex(self.host_boot_id, length=32, name="host boot id")
        _require_hex(self._claim_token, length=48, name="group claim token")
        _require_hex(self._permit_token, length=48, name="execution start permit")


@dataclass(frozen=True, order=True, slots=True)
class PluginPreflightDiagnostic:
    code: str
    message: str
    plugin_id: str = ""
    source_descriptor_fingerprint: str = ""

    def __post_init__(self) -> None:
        _require_nonempty(self.code, name="Plugin preflight diagnostic code")
        _require_nonempty(self.message, name="Plugin preflight diagnostic message")
        if self.plugin_id:
            _require_nonempty(self.plugin_id, name="Plugin id")
        if self.source_descriptor_fingerprint:
            _require_sha256(
                self.source_descriptor_fingerprint,
                name="source descriptor fingerprint",
            )


@dataclass(frozen=True, slots=True)
class PluginPreflightAcceptedOutcome:
    accepted: AcceptedPluginPreflight
    disposition: Literal["accepted"] = "accepted"

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, AcceptedPluginPreflight):
            raise TypeError("Outcome requires an accepted preflight")
        if self.disposition != "accepted":
            raise ValueError("Unsupported accepted preflight disposition")


@dataclass(frozen=True, slots=True)
class PluginPreflightPendingApprovalOutcome:
    subjects: tuple[PluginExecutionApprovalSubject, ...]
    diagnostics: tuple[PluginPreflightDiagnostic, ...]
    disposition: Literal["pending_approval"] = "pending_approval"

    def __post_init__(self) -> None:
        if not self.subjects or any(
            not isinstance(item, PluginExecutionApprovalSubject)
            for item in self.subjects
        ):
            raise ValueError("Pending approval requires proposed subjects")
        if self.subjects != tuple(sorted(self.subjects, key=lambda item: item.digest)):
            raise ValueError("Pending approval subjects must be strictly sorted")
        if len(self.subjects) != len({item.digest for item in self.subjects}):
            raise ValueError("Pending approval subjects must be unique")
        _validate_preflight_diagnostics(self.diagnostics, required=False)
        if self.disposition != "pending_approval":
            raise ValueError("Unsupported pending approval disposition")


@dataclass(frozen=True, slots=True)
class PluginPreflightDeniedOutcome:
    diagnostics: tuple[PluginPreflightDiagnostic, ...]
    disposition: Literal["denied"] = "denied"

    def __post_init__(self) -> None:
        _validate_preflight_diagnostics(self.diagnostics, required=True)
        if self.disposition != "denied":
            raise ValueError("Unsupported denied preflight disposition")


@dataclass(frozen=True, slots=True)
class PluginPreflightRejectedOutcome:
    diagnostics: tuple[PluginPreflightDiagnostic, ...]
    disposition: Literal["rejected"] = "rejected"

    def __post_init__(self) -> None:
        _validate_preflight_diagnostics(self.diagnostics, required=True)
        if self.disposition != "rejected":
            raise ValueError("Unsupported rejected preflight disposition")


PluginPreflightOutcome = (
    PluginPreflightAcceptedOutcome
    | PluginPreflightPendingApprovalOutcome
    | PluginPreflightDeniedOutcome
    | PluginPreflightRejectedOutcome
)


@dataclass(frozen=True, slots=True, init=False)
class PluginDocumentDecodedEvidence:
    declaration_set_fingerprint: str
    document_bytes_digest: str
    document_schema_version: int
    evidence_version: int
    kind: Literal["document_decoded"]
    package_content_digest: str
    preflight_use_id: str
    reservation_closure_fingerprint: str
    source_descriptor_fingerprint: str
    source_group_fingerprint: str
    source_group_id: str

    def __init__(self) -> None:
        raise TypeError("Plugin declaration Evidence is Host-constructed")

    def __post_init__(self) -> None:
        for name, value in (
            ("declaration set fingerprint", self.declaration_set_fingerprint),
            ("document bytes digest", self.document_bytes_digest),
            ("package content digest", self.package_content_digest),
            (
                "reservation closure fingerprint",
                self.reservation_closure_fingerprint,
            ),
            ("source descriptor fingerprint", self.source_descriptor_fingerprint),
            ("source group fingerprint", self.source_group_fingerprint),
            ("source group id", self.source_group_id),
        ):
            _require_sha256(value, name=name)
        _require_hex(self.preflight_use_id, length=48, name="preflight use id")
        _require_exact_version(
            self.document_schema_version,
            supported=PLUGIN_DECLARATION_DOCUMENT_VERSION,
            name="Plugin declaration document",
        )
        _require_exact_version(
            self.evidence_version,
            supported=PLUGIN_DECLARATION_EVIDENCE_VERSION,
            name="Plugin declaration evidence",
        )
        if self.kind != "document_decoded":
            raise ValueError("Unsupported document declaration evidence kind")

    @property
    def fingerprint(self) -> str:
        return _digest_document(
            {
                "domain": "loushang.plugin-declaration-evidence/v1",
                "evidence": self.to_dict(),
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "declarationSetFingerprint": self.declaration_set_fingerprint,
            "documentBytesDigest": self.document_bytes_digest,
            "documentSchemaVersion": self.document_schema_version,
            "evidenceVersion": self.evidence_version,
            "kind": self.kind,
            "packageContentDigest": self.package_content_digest,
            "preflightUseId": self.preflight_use_id,
            "reservationClosureFingerprint": (
                self.reservation_closure_fingerprint
            ),
            "sourceDescriptorFingerprint": self.source_descriptor_fingerprint,
            "sourceGroupFingerprint": self.source_group_fingerprint,
            "sourceGroupId": self.source_group_id,
        }


@dataclass(frozen=True, slots=True, init=False)
class PluginDeclarationBatch:
    preflight_use_id: str
    source_group_id: str
    source_group_fingerprint: str
    declarations: tuple[PluginDeclaration, ...]
    evidence: PluginDocumentDecodedEvidence

    def __init__(self) -> None:
        raise TypeError("Plugin declaration Batch is Host-constructed")

    def __post_init__(self) -> None:
        _require_hex(self.preflight_use_id, length=48, name="preflight use id")
        _require_sha256(self.source_group_id, name="source group id")
        _require_sha256(
            self.source_group_fingerprint,
            name="source group fingerprint",
        )
        declarations = self.declarations
        if not declarations or any(
            not isinstance(item, PluginDeclaration) for item in declarations
        ):
            raise TypeError("Plugin declaration Batch requires declarations")
        identities = tuple(
            (item.plugin_id, item.contribution_id) for item in declarations
        )
        if identities != tuple(sorted(identities)):
            raise ValueError("Plugin declaration Batch must be strictly sorted")
        if len(identities) != len(set(identities)):
            raise ValueError("Plugin declaration Batch identities must be unique")
        if not isinstance(self.evidence, PluginDocumentDecodedEvidence):
            raise TypeError("Plugin declaration Batch requires document evidence")
        if (
            self.evidence.preflight_use_id != self.preflight_use_id
            or self.evidence.source_group_id != self.source_group_id
            or self.evidence.source_group_fingerprint
            != self.source_group_fingerprint
        ):
            raise ValueError("Plugin declaration Batch evidence does not match its group")

    @classmethod
    def _from_document_decoded(
        cls,
        group: PluginDeclarationSourceGroup,
        document: PluginDeclarationDocument,
        encoded: bytes,
    ) -> PluginDeclarationBatch:
        if not isinstance(group, PluginDeclarationSourceGroup):
            raise TypeError("Document Batch requires a SourceGroup")
        if not isinstance(group.gate, PluginDeclarationDataOnlyGate):
            raise ValueError("Executable SourceGroup cannot form document evidence")
        if group.declaration_source.kind != "document":
            raise ValueError("Document Batch requires a document source")
        if not isinstance(document, PluginDeclarationDocument):
            raise TypeError("Document Batch requires a decoded declaration document")
        if not isinstance(encoded, bytes):
            raise TypeError("Document Batch requires exact source bytes")
        declarations = document.declarations
        evidence = object.__new__(PluginDocumentDecodedEvidence)
        evidence_values = {
            "declaration_set_fingerprint": _declaration_set_fingerprint(
                declarations
            ),
            "document_bytes_digest": sha256(encoded).hexdigest(),
            "document_schema_version": document.document_version,
            "evidence_version": PLUGIN_DECLARATION_EVIDENCE_VERSION,
            "kind": "document_decoded",
            "package_content_digest": group.package.content_digest,
            "preflight_use_id": group.preflight_use_id,
            "reservation_closure_fingerprint": (
                group.reservation_closure_fingerprint
            ),
            "source_descriptor_fingerprint": (
                group.source_descriptor_fingerprint
            ),
            "source_group_fingerprint": group.source_group_fingerprint,
            "source_group_id": group.source_group_id,
        }
        for name, value in evidence_values.items():
            object.__setattr__(evidence, name, value)
        evidence.__post_init__()
        batch = object.__new__(cls)
        batch_values = {
            "preflight_use_id": group.preflight_use_id,
            "source_group_id": group.source_group_id,
            "source_group_fingerprint": group.source_group_fingerprint,
            "declarations": declarations,
            "evidence": evidence,
        }
        for name, value in batch_values.items():
            object.__setattr__(batch, name, value)
        batch.__post_init__()
        return batch


@dataclass(frozen=True, slots=True, init=False)
class PluginContributionCandidate:
    package: PublishedPluginPackage = field(repr=False)
    declaration: PluginDeclaration
    evidence: PluginDocumentDecodedEvidence
    fingerprint: str

    def __init__(self) -> None:
        raise TypeError("Plugin contribution Candidate is Host-constructed")

    def __post_init__(self) -> None:
        if not isinstance(self.package, PublishedPluginPackage):
            raise TypeError("Plugin candidate requires a published package")
        if not isinstance(self.declaration, PluginDeclaration):
            raise TypeError("Plugin candidate requires a declaration")
        if not isinstance(self.evidence, PluginDocumentDecodedEvidence):
            raise TypeError("Plugin candidate requires exact declaration evidence")
        if self.evidence.package_content_digest != self.package.content_digest:
            raise ValueError("Plugin candidate evidence does not match its package")
        _require_sha256(self.fingerprint, name="candidate fingerprint")
        if self.fingerprint != _candidate_fingerprint(
            self.package,
            self.declaration,
            self.evidence,
        ):
            raise ValueError("Plugin candidate fingerprint does not match")

    @classmethod
    def _from_validated_batch(
        cls,
        package: PublishedPluginPackage,
        declaration: PluginDeclaration,
        batch: PluginDeclarationBatch,
    ) -> PluginContributionCandidate:
        if not isinstance(batch, PluginDeclarationBatch):
            raise TypeError("Plugin candidate requires a declaration Batch")
        if declaration not in batch.declarations:
            raise ValueError("Plugin candidate declaration is not in its Batch")
        if batch.evidence.declaration_set_fingerprint != (
            _declaration_set_fingerprint(batch.declarations)
        ):
            raise ValueError("Plugin candidate Batch evidence does not match")
        candidate = object.__new__(cls)
        candidate_values = {
            "package": package,
            "declaration": declaration,
            "evidence": batch.evidence,
            "fingerprint": _candidate_fingerprint(
                package,
                declaration,
                batch.evidence,
            ),
        }
        for name, value in candidate_values.items():
            object.__setattr__(candidate, name, value)
        candidate.__post_init__()
        return candidate


@dataclass(frozen=True, slots=True)
class PluginSelection:
    plan: PluginSelectionPlanV2
    candidates: tuple[PluginContributionCandidate, ...]


class PluginSelectionResolver:
    """Two-phase inert selector with one-use declaration reservations."""

    def __init__(self) -> None:
        self._gate = threading.Condition()
        self._active: dict[str, _ActivePluginPreflight] = {}
        self._terminal: dict[str, _TerminalPluginPreflight] = {}
        self._reaper: threading.Thread | None = None

    def preflight(
        self,
        packages: tuple[PublishedPluginPackage, ...],
        *,
        bindings: tuple[PluginSourceBinding, ...],
        plan: PluginSelectionPlanV2,
        decision_lookup: PluginExecutionDecisionLookupPort,
    ) -> PluginPreflightOutcome:
        try:
            result = self._resolve_preflight(
                packages,
                bindings=bindings,
                plan=plan,
                decision_lookup=decision_lookup,
            )
        except PluginSelectionError as exc:
            return PluginPreflightRejectedOutcome(
                diagnostics=(_preflight_diagnostic(exc),)
            )
        if not isinstance(result, AcceptedPluginPreflight):
            return result
        return PluginPreflightAcceptedOutcome(accepted=result)

    def _resolve_preflight(
        self,
        packages: tuple[PublishedPluginPackage, ...],
        *,
        bindings: tuple[PluginSourceBinding, ...],
        plan: PluginSelectionPlanV2,
        decision_lookup: PluginExecutionDecisionLookupPort,
    ) -> (
        AcceptedPluginPreflight
        | PluginPreflightPendingApprovalOutcome
        | PluginPreflightDeniedOutcome
        | PluginPreflightRejectedOutcome
    ):
        packages_by_id = _packages_by_id(packages)
        bindings_by_id = _bindings_by_id(bindings)
        selected_ids = set(plan.selected_plugin_ids)
        if set(packages_by_id) != selected_ids or set(bindings_by_id) != selected_ids:
            raise PluginSelectionError(
                "Published Plugin/binding set does not exactly match Product selection.",
                code="plugin_selection_package_mismatch",
            )
        trust_by_id = {item.plugin_id: item for item in plan.source_trust_snapshots}
        if set(trust_by_id) != selected_ids:
            raise PluginSelectionError(
                "Plugin source trust facts do not exactly match Product selection.",
                code="plugin_selection_trust_mismatch",
            )
        lookup_method = getattr(
            decision_lookup,
            "lookup_execution_decision",
            None,
        )
        if not callable(lookup_method):
            raise PluginSelectionError(
                "Plugin preflight requires an Approval-owned decision lookup port.",
                code="invalid_plugin_execution_decision_lookup",
            )

        indexed: dict[PluginContributionRef, PluginContributionReservation] = {}
        for plugin_id, package in packages_by_id.items():
            _verify_package(package)
            binding = bindings_by_id[plugin_id]
            _verify_binding(package, binding)
            if not package.source.enabled or not package.manifest.enabled:
                raise PluginSelectionError(
                    f"Selected Plugin is disabled: {plugin_id}",
                    code="selected_plugin_disabled",
                    path=package.root,
                )
            trust = trust_by_id[plugin_id]
            if (
                trust.package_source_identity != binding.source_identity
                or not trust.trusted
            ):
                raise PluginSelectionError(
                    f"Selected Plugin source is not trusted: {plugin_id}",
                    code="selected_plugin_untrusted",
                    path=package.root,
                )
            for contribution in package.contribution_index.items:
                indexed[
                    PluginContributionRef(plugin_id, contribution.contribution_id)
                ] = contribution

        requested_refs = set(plan.selected_contributions)
        required_refs = {
            ref for ref, contribution in indexed.items() if contribution.required
        }
        if not required_refs.issubset(requested_refs):
            raise PluginSelectionError(
                "Product selection omitted a required Plugin contribution.",
                code="required_plugin_contribution_unselected",
            )
        if not requested_refs.issubset(indexed):
            raise PluginSelectionError(
                "Product selection references an unknown Plugin contribution.",
                code="unknown_plugin_contribution",
            )

        proposed_refs: set[PluginContributionRef] = set()
        for ref in plan.selected_contributions:
            package = packages_by_id[ref.plugin_id]
            contribution = indexed[ref]
            proposed_refs.update(
                PluginContributionRef(ref.plugin_id, item.contribution_id)
                for item in _source_reservation_closure(package, contribution)
            )
        configuration_refs = {
            item.ref for item in plan.effective_configuration_set.entries
        }
        if configuration_refs != proposed_refs:
            raise PluginSelectionError(
                "Plugin effective configuration does not exactly cover source closures.",
                code="invalid_plugin_effective_configuration",
            )
        proposal = PluginPreflightProposal(
            plan=plan,
            source_proposals=_build_source_proposals(
                packages_by_id,
                bindings_by_id,
                indexed,
                plan=plan,
            ),
        )
        resolved_gates: list[PluginDeclarationGate] = []
        lookup_results: dict[
            str,
            PluginExecutionDecisionLookupResult | PluginSelectionError,
        ] = {}
        pending_subjects: list[PluginExecutionApprovalSubject] = []
        pending_diagnostics: list[PluginPreflightDiagnostic] = []
        denied_diagnostics: list[PluginPreflightDiagnostic] = []
        rejected_diagnostics: list[PluginPreflightDiagnostic] = []
        for source_proposal in proposal.source_proposals:
            package = source_proposal.package
            disposition = source_proposal.source_disposition
            if isinstance(disposition, PluginDeclarationDataOnlyDisposition):
                resolved_gates.append(PluginDeclarationDataOnlyGate())
                continue
            subject = disposition.subject
            lookup_result = lookup_results.get(subject.digest)
            if lookup_result is None:
                try:
                    candidate_result = lookup_method(subject)
                except Exception:
                    lookup_result = PluginSelectionError(
                        "Plugin execution decision lookup failed closed: "
                        f"{source_proposal.key}",
                        code="invalid_plugin_execution_decision_lookup",
                        path=package.root,
                    )
                else:
                    lookup_result = candidate_result
                if not isinstance(
                    lookup_result,
                    PluginSelectionError
                    | PluginExecutionDecisionMissing
                    | PluginExecutionDecisionCurrent,
                ):
                    lookup_result = PluginSelectionError(
                        "Plugin execution decision lookup returned an invalid "
                        f"result: {source_proposal.key}",
                        code="invalid_plugin_execution_decision_lookup",
                        path=package.root,
                    )
                lookup_results[subject.digest] = lookup_result
            if isinstance(lookup_result, PluginSelectionError):
                rejected_diagnostics.append(
                    _source_preflight_diagnostic(lookup_result, source_proposal)
                )
                continue
            if isinstance(lookup_result, PluginExecutionDecisionMissing):
                pending_subjects.append(subject)
                pending_diagnostics.append(
                    _source_preflight_diagnostic(
                        PluginSelectionError(
                            "Plugin execution approval is pending: "
                            f"{source_proposal.key}",
                            code="plugin_execution_approval_required",
                            path=package.root,
                        ),
                        source_proposal,
                    )
                )
                continue
            matched_decision = lookup_result.decision
            if (
                matched_decision.subject_digest != subject.digest
                or matched_decision.policy_revision != plan.context.policy_revision
                or matched_decision.subject_schema_version != subject.schema_version
            ):
                rejected_diagnostics.append(
                    _source_preflight_diagnostic(
                        PluginSelectionError(
                            "Approval owner returned a decision for a different "
                            f"Subject: {source_proposal.key}",
                            code="invalid_plugin_execution_decision_lookup",
                            path=package.root,
                        ),
                        source_proposal,
                    )
                )
                continue
            if matched_decision.disposition != "approved":
                denied_diagnostics.append(
                    _source_preflight_diagnostic(
                        PluginSelectionError(
                            f"Plugin execution was denied: {source_proposal.key}",
                            code="plugin_execution_denied",
                            path=package.root,
                        ),
                        source_proposal,
                    )
                )
                continue
            resolved_gates.append(
                PluginDeclarationExecutionPreflightGate(
                    subject=subject,
                    decision=matched_decision,
                )
            )

        if rejected_diagnostics:
            return PluginPreflightRejectedOutcome(
                diagnostics=_sorted_unique_diagnostics(rejected_diagnostics)
            )
        if denied_diagnostics:
            return PluginPreflightDeniedOutcome(
                diagnostics=_sorted_unique_diagnostics(denied_diagnostics)
            )
        if pending_subjects:
            return PluginPreflightPendingApprovalOutcome(
                subjects=tuple(
                    sorted(
                        {item.digest: item for item in pending_subjects}.values(),
                        key=lambda item: item.digest,
                    )
                ),
                diagnostics=_sorted_unique_diagnostics(pending_diagnostics),
            )

        with self._gate:
            self._compact_tombstones_locked()
            if (
                len(self._active) >= _PLUGIN_MAX_ACTIVE_ATTEMPTS
                or len(self._active) + len(self._terminal)
                >= _PLUGIN_MAX_TERMINAL_TOMBSTONES
            ):
                raise PluginSelectionError(
                    "Plugin preflight process capacity is exhausted.",
                    code="plugin_preflight_capacity_exhausted",
                )
            preflight_use_id = secrets.token_hex(24)
            while (
                preflight_use_id in self._active
                or preflight_use_id in self._terminal
            ):
                preflight_use_id = secrets.token_hex(24)
            instance_refs = {
                item.plugin_id: item for item in plan.context.instance_revision_refs
            }
            source_groups = tuple(
                _accepted_source_group(
                    source_proposal,
                    gate=gate,
                    preflight_use_id=preflight_use_id,
                    context=plan.context,
                    instance_revision_ref=instance_refs[
                        source_proposal.package.manifest.name
                    ],
                )
                for source_proposal, gate in zip(
                    proposal.source_proposals,
                    resolved_gates,
                    strict=True,
                )
            )
            terminal_handle = _PluginPreflightTerminalHandle(
                token=preflight_use_id
            )
            accepted = AcceptedPluginPreflight(
                preflight_use_id=preflight_use_id,
                host_boot_id=_PLUGIN_HOST_BOOT_ID,
                expires_at=monotonic()
                + min(
                    max(_PLUGIN_PREFLIGHT_TTL_SECONDS, 0.0),
                    _PLUGIN_MAX_ATTEMPT_LIFETIME_SECONDS,
                ),
                context=plan.context,
                source_groups=source_groups,
                _terminal_handle=terminal_handle,
            )
            self._active[terminal_handle.token] = _ActivePluginPreflight(
                accepted=accepted,
                proposal=proposal,
                groups={
                    group.source_group_id: _PluginGroupRuntime(group=group)
                    for group in source_groups
                },
            )
            self._ensure_reaper_locked()
            self._gate.notify_all()
        return accepted

    def _claim_group(
        self,
        preflight: AcceptedPluginPreflight,
        group: PluginDeclarationSourceGroup,
    ) -> _PluginGroupClaimLease:
        with self._gate:
            active = self._active_record_locked(preflight)
            if active.state != "active_open":
                raise PluginSelectionError(
                    "Plugin preflight is closing and accepts no new group claim.",
                    code="preflight_closing",
                )
            now = monotonic()
            if now >= preflight.expires_at:
                self._begin_close_locked(active, state="closing_expire")
                self._finish_close_if_quiescent_locked(active)
                self._wait_for_terminal_locked(preflight)
            runtime = active.groups.get(group.source_group_id)
            if runtime is None or runtime.group is not group:
                raise PluginSelectionError(
                    "Plugin declaration group does not belong to this preflight.",
                    code="plugin_declaration_group_mismatch",
                    path=group.package.root,
                )
            if runtime.state != "pending":
                while preflight.preflight_use_id in self._active:
                    self._gate.wait()
                self._raise_terminal_locked(preflight)
            claim_token = secrets.token_hex(24)
            runtime.state = "claimed"
            runtime.claim_token = claim_token
            active.in_flight += 1
            return _PluginGroupClaimLease(
                preflight_use_id=preflight.preflight_use_id,
                source_group_id=group.source_group_id,
                claim_token=claim_token,
            )

    def _settle_group(
        self,
        lease: _PluginGroupClaimLease,
        *,
        succeeded: bool,
    ) -> None:
        if not isinstance(lease, _PluginGroupClaimLease):
            raise PluginSelectionError(
                "Plugin group claim lease is foreign or already consumed.",
                code="plugin_group_claim_consumed",
            )
        if not isinstance(succeeded, bool):
            raise TypeError("Plugin group settlement requires a boolean outcome")
        with self._gate:
            active = self._active.get(lease.preflight_use_id)
            if active is None:
                raise PluginSelectionError(
                    "Plugin group claim lease is foreign or already consumed.",
                    code="plugin_group_claim_consumed",
                )
            runtime = active.groups.get(lease.source_group_id)
            if (
                runtime is None
                or runtime.state != "claimed"
                or runtime.claim_token != lease.claim_token
            ):
                raise PluginSelectionError(
                    "Plugin group claim lease is foreign or already consumed.",
                    code="plugin_group_claim_consumed",
                )
            runtime.state = "completed" if succeeded else "failed"
            runtime.claim_token = ""
            active.in_flight -= 1
            self._finish_close_if_quiescent_locked(active)
            self._gate.notify_all()
            if lease.preflight_use_id not in self._active:
                self._raise_terminal_for_token_locked(lease.preflight_use_id)
            if active.state != "active_open":
                raise PluginSelectionError(
                    "Plugin preflight is closing; the late group result was discarded.",
                    code="preflight_closing",
                    path=runtime.group.package.root,
                )

    def _issue_execution_start_permit(
        self,
        lease: _PluginGroupClaimLease,
    ) -> PluginExecutionStartPermit:
        """Linearize executable start after claim and before Approval access."""

        if not isinstance(lease, _PluginGroupClaimLease):
            raise PluginSelectionError(
                "Plugin group claim lease is foreign or already consumed.",
                code="plugin_group_claim_consumed",
            )
        with self._gate:
            active = self._active.get(lease.preflight_use_id)
            if active is None:
                raise PluginSelectionError(
                    "Plugin group claim lease is foreign or already consumed.",
                    code="plugin_group_claim_consumed",
                )
            runtime = active.groups.get(lease.source_group_id)
            if (
                runtime is None
                or runtime.state != "claimed"
                or runtime.claim_token != lease.claim_token
            ):
                raise PluginSelectionError(
                    "Plugin group claim lease is foreign or already consumed.",
                    code="plugin_group_claim_consumed",
                )
            if not isinstance(
                runtime.group.gate,
                PluginDeclarationExecutionPreflightGate,
            ):
                raise PluginSelectionError(
                    "Document declaration groups do not require an execution start.",
                    code="plugin_execution_start_not_applicable",
                    path=runtime.group.package.root,
                )
            if runtime.start_permit_token:
                raise PluginSelectionError(
                    "Plugin execution start permit was already issued.",
                    code="plugin_execution_start_permit_consumed",
                    path=runtime.group.package.root,
                )
            if active.state != "active_open":
                raise PluginSelectionError(
                    "Plugin preflight is closing and forbids execution start.",
                    code="preflight_closing",
                    path=runtime.group.package.root,
                )
            if monotonic() >= active.accepted.expires_at:
                self._begin_close_locked(active, state="closing_expire")
                self._finish_close_if_quiescent_locked(active)
                raise PluginSelectionError(
                    "Plugin preflight expired before execution start.",
                    code="preflight_closing",
                    path=runtime.group.package.root,
                )
            permit_token = secrets.token_hex(24)
            runtime.start_permit_token = permit_token
            return PluginExecutionStartPermit(
                preflight_use_id=lease.preflight_use_id,
                source_group_id=lease.source_group_id,
                host_boot_id=active.accepted.host_boot_id,
                _claim_token=lease.claim_token,
                _permit_token=permit_token,
            )

    def _abort(self, preflight: AcceptedPluginPreflight) -> None:
        with self._gate:
            active = self._active_record_locked(preflight)
            initiated_abort = False
            if active.state == "active_open":
                if monotonic() >= preflight.expires_at:
                    self._begin_close_locked(active, state="closing_expire")
                else:
                    self._begin_close_locked(active, state="closing_abort")
                    initiated_abort = True
                self._finish_close_if_quiescent_locked(active)
            while preflight.preflight_use_id in self._active:
                self._gate.wait()
            terminal = self._terminal_record_locked(preflight)
            if initiated_abort and terminal.state == "aborted":
                return
            raise self._terminal_error(terminal.state)

    def _finalize(
        self,
        preflight: AcceptedPluginPreflight,
        batches: tuple[PluginDeclarationBatch, ...],
    ) -> PluginSelection:
        active = self._peek_active(preflight)
        plan = active.proposal.plan
        batches_by_group_id: dict[str, PluginDeclarationBatch] = {}
        for batch in batches:
            if not isinstance(batch, PluginDeclarationBatch):
                raise PluginSelectionError(
                    "Plugin finalization accepts only declaration Batches.",
                    code="plugin_declaration_batch_mismatch",
                )
            if batch.source_group_id in batches_by_group_id:
                raise PluginSelectionError(
                    "Plugin declaration SourceGroup was emitted twice.",
                    code="duplicate_plugin_declaration_batch",
                )
            batches_by_group_id[batch.source_group_id] = batch
        expected_group_ids = {
            group.source_group_id for group in preflight.source_groups
        }
        if set(batches_by_group_id) != expected_group_ids:
            raise PluginSelectionError(
                "Plugin declaration Batches do not exactly fulfill SourceGroups.",
                code="plugin_declaration_batch_mismatch",
            )

        selected_refs = set(plan.selected_contributions)
        candidates: list[PluginContributionCandidate] = []
        for group in preflight.source_groups:
            if not isinstance(group.gate, PluginDeclarationDataOnlyGate):
                raise PluginSelectionError(
                    "Executable declaration SourceGroup was not consumed.",
                    code="execution_not_consumed",
                    path=group.package.root,
                )
            batch = batches_by_group_id[group.source_group_id]
            evidence = batch.evidence
            if (
                batch.preflight_use_id != preflight.preflight_use_id
                or batch.source_group_fingerprint
                != group.source_group_fingerprint
                or evidence.package_content_digest != group.package.content_digest
                or evidence.preflight_use_id != preflight.preflight_use_id
                or evidence.source_group_id != group.source_group_id
                or evidence.source_group_fingerprint
                != group.source_group_fingerprint
                or evidence.reservation_closure_fingerprint
                != group.reservation_closure_fingerprint
                or evidence.source_descriptor_fingerprint
                != group.source_descriptor_fingerprint
            ):
                raise PluginSelectionError(
                    "Plugin declaration evidence belongs to a different attempt.",
                    code="plugin_declaration_evidence_attempt_mismatch",
                    path=group.package.root,
                )
            if evidence.declaration_set_fingerprint != _declaration_set_fingerprint(
                batch.declarations
            ):
                raise PluginSelectionError(
                    "Plugin declaration evidence set fingerprint does not match.",
                    code="plugin_declaration_evidence_mismatch",
                    path=group.package.root,
                )
            declarations_by_ref = {
                PluginContributionRef(
                    declaration.plugin_id,
                    declaration.contribution_id,
                ): declaration
                for declaration in batch.declarations
            }
            expected_reservations = {item.ref: item for item in group.reservations}
            if (
                len(declarations_by_ref) != len(batch.declarations)
                or set(declarations_by_ref) != set(expected_reservations)
            ):
                raise PluginSelectionError(
                    "Plugin declarations do not exactly fulfill their SourceGroup.",
                    code="plugin_declaration_reservation_mismatch",
                    path=group.package.root,
                )
            for ref, reservation in expected_reservations.items():
                declaration = declarations_by_ref[ref]
                contribution = reservation.contribution
                if (
                    declaration.kind != contribution.kind
                    or declaration.owner != contribution.owner
                    or declaration.reservation_fingerprint
                    != contribution.fingerprint
                    or declaration.source_descriptor_fingerprint
                    != contribution.source_descriptor_fingerprint
                    or declaration.source_kind
                    != contribution.declaration_source.kind
                ):
                    raise PluginSelectionError(
                        "Plugin declaration changed its inert reservation: "
                        f"{reservation.ref}",
                        code="plugin_declaration_envelope_mismatch",
                        path=reservation.package.root,
                    )
                if ref not in selected_refs:
                    continue
                candidates.append(
                    PluginContributionCandidate._from_validated_batch(
                        reservation.package,
                        declaration,
                        batch,
                    )
                )
        self._commit_finalized(preflight, active)
        return PluginSelection(plan=plan, candidates=tuple(candidates))

    def _peek_active(
        self,
        preflight: AcceptedPluginPreflight,
    ) -> _ActivePluginPreflight:
        with self._gate:
            active = self._active_record_locked(preflight)
            if active.state != "active_open":
                raise PluginSelectionError(
                    "Plugin preflight is closing.",
                    code="preflight_closing",
                )
            if monotonic() >= preflight.expires_at:
                self._begin_close_locked(active, state="closing_expire")
                self._finish_close_if_quiescent_locked(active)
                self._wait_for_terminal_locked(preflight)
            return active

    def _commit_finalized(
        self,
        preflight: AcceptedPluginPreflight,
        expected: _ActivePluginPreflight,
    ) -> None:
        with self._gate:
            active = self._active_record_locked(preflight)
            if active is not expected:
                raise PluginSelectionError(
                    "Plugin preflight aggregate identity changed.",
                    code="plugin_preflight_consumed",
                )
            if active.state != "active_open":
                while preflight.preflight_use_id in self._active:
                    self._gate.wait()
                self._raise_terminal_locked(preflight)
            if monotonic() >= preflight.expires_at:
                self._begin_close_locked(active, state="closing_expire")
                self._finish_close_if_quiescent_locked(active)
                self._wait_for_terminal_locked(preflight)
            if active.in_flight != 0 or any(
                runtime.state != "completed"
                for runtime in active.groups.values()
            ):
                raise PluginSelectionError(
                    "Plugin preflight groups are not completely settled.",
                    code="plugin_preflight_incomplete",
                )
            self._terminalize_locked(active, state="finalized")

    def _active_record_locked(
        self,
        preflight: AcceptedPluginPreflight,
    ) -> _ActivePluginPreflight:
        if not isinstance(preflight, AcceptedPluginPreflight):
            raise PluginSelectionError(
                "Plugin preflight reservation is foreign.",
                code="plugin_preflight_consumed",
            )
        if preflight.host_boot_id != _PLUGIN_HOST_BOOT_ID:
            raise PluginSelectionError(
                "Plugin preflight belongs to a prior Host boot.",
                code="preflight_expired",
            )
        active = self._active.get(preflight.preflight_use_id)
        if active is not None and active.accepted is preflight:
            return active
        terminal = self._terminal.get(preflight.preflight_use_id)
        if terminal is not None and terminal.accepted_ref() is preflight:
            raise self._terminal_error(terminal.state)
        raise PluginSelectionError(
            "Plugin preflight reservation is foreign or unknown.",
            code="plugin_preflight_consumed",
        )

    def _terminal_record_locked(
        self,
        preflight: AcceptedPluginPreflight,
    ) -> _TerminalPluginPreflight:
        if preflight.host_boot_id != _PLUGIN_HOST_BOOT_ID:
            raise PluginSelectionError(
                "Plugin preflight belongs to a prior Host boot.",
                code="preflight_expired",
            )
        terminal = self._terminal.get(preflight.preflight_use_id)
        if terminal is None or terminal.accepted_ref() is not preflight:
            raise PluginSelectionError(
                "Plugin preflight reservation is foreign or unknown.",
                code="plugin_preflight_consumed",
            )
        return terminal

    def _wait_for_terminal_locked(
        self,
        preflight: AcceptedPluginPreflight,
    ) -> None:
        while preflight.preflight_use_id in self._active:
            self._gate.wait()
        self._raise_terminal_locked(preflight)

    def _raise_terminal_locked(
        self,
        preflight: AcceptedPluginPreflight,
    ) -> None:
        terminal = self._terminal_record_locked(preflight)
        raise self._terminal_error(terminal.state)

    def _raise_terminal_for_token_locked(self, preflight_use_id: str) -> None:
        terminal = self._terminal.get(preflight_use_id)
        if terminal is None:
            raise PluginSelectionError(
                "Plugin preflight reservation is foreign or unknown.",
                code="plugin_preflight_consumed",
            )
        raise self._terminal_error(terminal.state)

    @staticmethod
    def _terminal_error(
        state: Literal["finalized", "aborted", "expired"],
    ) -> PluginSelectionError:
        if state == "finalized":
            return PluginSelectionError(
                "Plugin preflight was already finalized.",
                code="preflight_already_finalized",
            )
        if state == "aborted":
            return PluginSelectionError(
                "Plugin preflight was already aborted.",
                code="preflight_already_aborted",
            )
        return PluginSelectionError(
            "Plugin preflight expired before terminal use.",
            code="preflight_expired",
        )

    def _begin_close_locked(
        self,
        active: _ActivePluginPreflight,
        *,
        state: Literal["closing_abort", "closing_expire"],
    ) -> None:
        if active.state != "active_open":
            return
        active.state = state
        for runtime in active.groups.values():
            if runtime.state == "claimed":
                runtime.cancel_requested = True
        self._gate.notify_all()

    def _finish_close_if_quiescent_locked(
        self,
        active: _ActivePluginPreflight,
    ) -> None:
        if active.in_flight != 0:
            return
        if active.state == "closing_abort":
            self._terminalize_locked(active, state="aborted")
        elif active.state == "closing_expire":
            self._terminalize_locked(active, state="expired")

    def _terminalize_locked(
        self,
        active: _ActivePluginPreflight,
        *,
        state: Literal["finalized", "aborted", "expired"],
    ) -> None:
        token = active.accepted.preflight_use_id
        if self._active.get(token) is not active:
            raise PluginSelectionError(
                "Plugin preflight terminal state changed concurrently.",
                code="plugin_preflight_consumed",
            )
        self._active.pop(token)
        self._terminal[token] = _TerminalPluginPreflight(
            accepted_ref=weakref.ref(active.accepted),
            state=state,
            late_group_results=tuple(
                (
                    group_id,
                    cast(
                        Literal["completed", "failed"],
                        runtime.state,
                    ),
                )
                for group_id, runtime in sorted(active.groups.items())
                if runtime.cancel_requested
                and runtime.state in {"completed", "failed"}
            ),
        )
        self._gate.notify_all()

    def _compact_tombstones_locked(self) -> None:
        for token, terminal in tuple(self._terminal.items()):
            if terminal.accepted_ref() is None:
                self._terminal.pop(token, None)

    def _ensure_reaper_locked(self) -> None:
        if self._reaper is not None and self._reaper.is_alive():
            return
        reaper = threading.Thread(
            target=self._run_reaper,
            name="loushang-plugin-preflight-reaper",
            daemon=True,
        )
        self._reaper = reaper
        reaper.start()

    def _run_reaper(self) -> None:
        while True:
            with self._gate:
                open_attempts = tuple(
                    active
                    for active in self._active.values()
                    if active.state == "active_open"
                )
                if not open_attempts:
                    if self._active:
                        self._gate.wait()
                        continue
                    self._reaper = None
                    return
                now = monotonic()
                deadline = min(
                    active.accepted.expires_at for active in open_attempts
                )
                if now < deadline:
                    self._gate.wait(timeout=deadline - now)
                    continue
                due = tuple(
                    active.accepted.preflight_use_id
                    for active in open_attempts
                    if now >= active.accepted.expires_at
                )
            for preflight_use_id in due:
                self._expire_from_reaper(preflight_use_id, monotonic())

    def _expire_from_reaper(self, preflight_use_id: str, now: float) -> None:
        with self._gate:
            active = self._active.get(preflight_use_id)
            if (
                active is None
                or active.state != "active_open"
                or now < active.accepted.expires_at
            ):
                return
            self._begin_close_locked(active, state="closing_expire")
            self._finish_close_if_quiescent_locked(active)


def _build_execution_approval_subject(
    package: PublishedPluginPackage,
    contribution: PluginContributionReservation,
    *,
    plan: PluginSelectionPlanV2,
    binding: PluginSourceBinding,
) -> PluginExecutionApprovalSubject:
    _verify_package(package)
    _verify_binding(package, binding)
    if contribution not in package.contribution_index.items:
        raise PluginSelectionError(
            "Plugin contribution is not reserved by the published package.",
            code="unknown_plugin_contribution",
            path=package.root,
        )
    source_trust_by_id = {item.plugin_id: item for item in plan.source_trust_snapshots}
    source_trust = source_trust_by_id.get(package.manifest.name)
    if (
        source_trust is None
        or source_trust.package_source_identity != binding.source_identity
    ):
        raise PluginSelectionError(
            "Plugin source trust fact does not match the package identity.",
            code="plugin_selection_trust_mismatch",
            path=package.root,
        )
    source = contribution.declaration_source
    if source.kind != "in_process" or source.entrypoint is None:
        raise PluginSelectionError(
            "Document declaration sources do not require execution approval.",
            code="plugin_execution_subject_not_applicable",
            path=package.root,
        )
    closure = _source_reservation_closure(package, contribution)
    requested_authorities = tuple(
        sorted(
            {authority for item in closure for authority in item.requested_authorities}
        )
    )
    if not set(requested_authorities).issubset(plan.allowed_authority_ceiling):
        raise PluginSelectionError(
            "Plugin declaration source exceeds its authority ceiling.",
            code="plugin_authority_ceiling_exceeded",
            path=package.root,
        )
    return PluginExecutionApprovalSubject(
        plugin_id=package.manifest.name,
        package_content_digest=package.content_digest,
        dependency_lock_digest=package.dependency_lock.digest,
        entrypoint=source.entrypoint,
        package_source_identity=binding.source_identity,
        source_trust_class=source_trust.source_trust_class,
        source_trust_policy_revision=(source_trust.source_trust_policy_revision),
        product_id=plan.context.product_id,
        scope_id=plan.context.scope_id,
        policy_revision=plan.context.policy_revision,
        ambient_host_authority=True,
        configuration_map_fingerprint=_configuration_map_fingerprint(
            _effective_configuration_projection(
                plan,
                package.manifest.name,
                closure,
            ),
        ),
        requested_authorities=requested_authorities,
        allowed_authority_ceiling=plan.allowed_authority_ceiling,
        reservation_closure_fingerprint=_reservation_closure_fingerprint(closure),
        source_descriptor_fingerprint=contribution.source_descriptor_fingerprint,
        instance_revision_ref={
            item.plugin_id: item for item in plan.context.instance_revision_refs
        }[package.manifest.name],
    )


def _build_source_proposals(
    packages_by_id: Mapping[str, PublishedPluginPackage],
    bindings_by_id: Mapping[str, PluginSourceBinding],
    indexed: Mapping[PluginContributionRef, PluginContributionReservation],
    *,
    plan: PluginSelectionPlanV2,
) -> tuple[PluginDeclarationSourceProposal, ...]:
    trust_by_id = {item.plugin_id: item for item in plan.source_trust_snapshots}
    source_keys = sorted(
        {
            (
                ref.plugin_id,
                indexed[ref].source_descriptor_fingerprint,
            )
            for ref in plan.selected_contributions
        }
    )
    proposals: list[PluginDeclarationSourceProposal] = []
    for plugin_id, source_fingerprint in source_keys:
        package = packages_by_id[plugin_id]
        contribution = next(
            item
            for item in package.contribution_index.items
            if item.source_descriptor_fingerprint == source_fingerprint
        )
        closure = _source_reservation_closure(package, contribution)
        entries = _effective_configuration_projection(plan, plugin_id, closure)
        requested_authorities = tuple(
            sorted(
                {
                    authority
                    for item in closure
                    for authority in item.requested_authorities
                }
            )
        )
        if contribution.declaration_source.kind == "document":
            source_disposition: PluginDeclarationSourceDisposition = (
                PluginDeclarationDataOnlyDisposition()
            )
        else:
            source_disposition = PluginDeclarationExecutionSubjectDisposition(
                subject=_build_execution_approval_subject(
                    package,
                    contribution,
                    plan=plan,
                    binding=bindings_by_id[plugin_id],
                )
            )
        proposals.append(
            PluginDeclarationSourceProposal(
                package=package,
                declaration_source=contribution.declaration_source,
                source_descriptor_fingerprint=source_fingerprint,
                reservation_closure=closure,
                effective_configuration_entries=entries,
                configuration_map_fingerprint=_configuration_map_fingerprint(entries),
                trust_snapshot=trust_by_id[plugin_id],
                requested_authorities=requested_authorities,
                allowed_authority_ceiling=plan.allowed_authority_ceiling,
                source_disposition=source_disposition,
            )
        )
    return tuple(proposals)


def _accepted_source_group(
    proposal: PluginDeclarationSourceProposal,
    *,
    gate: PluginDeclarationGate,
    preflight_use_id: str,
    context: PluginPreflightContextV1,
    instance_revision_ref: PluginInstanceRevisionRef,
) -> PluginDeclarationSourceGroup:
    source_group_fingerprint = _source_group_fingerprint(
        proposal,
        context=context,
        instance_revision_ref=instance_revision_ref,
    )
    return PluginDeclarationSourceGroup(
        preflight_use_id=preflight_use_id,
        source_group_id=_source_group_id(
            preflight_use_id,
            source_group_fingerprint,
        ),
        source_group_fingerprint=source_group_fingerprint,
        package=proposal.package,
        declaration_source=proposal.declaration_source,
        source_descriptor_fingerprint=proposal.source_descriptor_fingerprint,
        context=context,
        instance_revision_ref=instance_revision_ref,
        reservation_closure=proposal.reservation_closure,
        reservation_closure_fingerprint=_reservation_closure_fingerprint(
            proposal.reservation_closure
        ),
        effective_configuration_entries=proposal.effective_configuration_entries,
        configuration_map_fingerprint=proposal.configuration_map_fingerprint,
        trust_snapshot=proposal.trust_snapshot,
        requested_authorities=proposal.requested_authorities,
        allowed_authority_ceiling=proposal.allowed_authority_ceiling,
        gate=gate,
    )


def _packages_by_id(
    packages: tuple[PublishedPluginPackage, ...],
) -> dict[str, PublishedPluginPackage]:
    result: dict[str, PublishedPluginPackage] = {}
    for package in packages:
        if not isinstance(package, PublishedPluginPackage):
            raise PluginSelectionError(
                "Plugin preflight accepts only published packages.",
                code="unpublished_plugin_package",
                path=package.root,
            )
        plugin_id = package.manifest.name
        if plugin_id in result:
            raise PluginSelectionError(
                f"Plugin preflight received duplicate Plugin id: {plugin_id}",
                code="duplicate_selected_plugin",
                path=package.root,
            )
        result[plugin_id] = package
    return result


def _verify_package(package: PublishedPluginPackage) -> None:
    if package.dependency_lock.package_content_digest != package.content_digest:
        raise PluginSelectionError(
            "Plugin dependency closure does not match the published revision.",
            code="invalid_plugin_revision_publication",
            path=package.root,
        )
    package.revision_handle.verify()


def _bindings_by_id(
    bindings: tuple[PluginSourceBinding, ...],
) -> dict[str, PluginSourceBinding]:
    result: dict[str, PluginSourceBinding] = {}
    for binding in bindings:
        if binding.plugin_id in result:
            raise PluginSelectionError(
                f"Plugin preflight received duplicate binding: {binding.plugin_id}",
                code="duplicate_plugin_binding",
            )
        result[binding.plugin_id] = binding
    return result


def _verify_binding(
    package: PublishedPluginPackage,
    binding: PluginSourceBinding,
) -> None:
    if (
        binding.plugin_id != package.manifest.name
        or binding.source_kind != package.source.kind
        or binding.source != _source_value(package.source)
        or binding.content_digest != package.content_digest
        or binding.dependency_lock != package.dependency_lock
    ):
        raise PluginSelectionError(
            "Plugin source binding does not match the published package.",
            code="invalid_plugin_source_binding",
            path=package.root,
        )


def _candidate_fingerprint(
    package: PublishedPluginPackage,
    declaration: PluginDeclaration,
    evidence: PluginDocumentDecodedEvidence,
) -> str:
    return _digest_document(
        {
            "domain": "loushang.plugin-contribution-candidate/v2",
            "declarationFingerprint": declaration.fingerprint,
            "evidenceFingerprint": evidence.fingerprint,
            "packageContentDigest": package.content_digest,
            "sourceGroupFingerprint": evidence.source_group_fingerprint,
        }
    )


def _declaration_set_fingerprint(
    declarations: tuple[PluginDeclaration, ...],
) -> str:
    return _digest_document(
        {
            "declarations": [
                {
                    "contributionId": item.contribution_id,
                    "declarationFingerprint": item.fingerprint,
                    "pluginId": item.plugin_id,
                }
                for item in declarations
            ],
            "domain": "loushang.plugin-declaration-set/v2",
        }
    )


def _source_value(source: PluginSource) -> str:
    if source.kind == "remote":
        if source.url is None:
            raise PluginSelectionError(
                "Remote Plugin source has no URL identity.",
                code="invalid_plugin_source_identity",
            )
        return source.url
    if source.path is None:
        raise PluginSelectionError(
            "Local Plugin source has no path identity.",
            code="invalid_plugin_source_identity",
        )
    return str(source.path.expanduser().resolve())


def _source_reservation_closure(
    package: PublishedPluginPackage,
    contribution: PluginContributionReservation,
) -> tuple[PluginContributionReservation, ...]:
    source_fingerprint = contribution.source_descriptor_fingerprint
    return tuple(
        sorted(
            (
                item
                for item in package.contribution_index.items
                if item.source_descriptor_fingerprint == source_fingerprint
            ),
            key=lambda item: item.contribution_id,
        )
    )


def _reservation_closure_fingerprint(
    closure: tuple[PluginContributionReservation, ...],
) -> str:
    return _digest_document(
        {
            "domain": "loushang.plugin-reservation-closure/v1",
            "reservations": [
                {
                    "contributionId": item.contribution_id,
                    "reservationFingerprint": item.fingerprint,
                }
                for item in closure
            ],
        }
    )


def _effective_configuration_projection(
    plan: PluginSelectionPlanV2,
    plugin_id: str,
    closure: tuple[PluginContributionReservation, ...],
) -> tuple[PluginEffectiveConfigurationEntry, ...]:
    entries_by_ref = {
        item.ref: item for item in plan.effective_configuration_set.entries
    }
    refs = tuple(
        PluginContributionRef(plugin_id, item.contribution_id) for item in closure
    )
    try:
        return tuple(entries_by_ref[ref] for ref in refs)
    except KeyError as exc:
        raise PluginSelectionError(
            "Plugin effective configuration does not cover a source closure.",
            code="invalid_plugin_effective_configuration",
        ) from exc


def _package_default_configuration_projection(
    plugin_id: str,
    closure: tuple[PluginContributionReservation, ...],
) -> tuple[PluginEffectiveConfigurationEntry, ...]:
    """Temporary Builder guard until accepted SourceGroups own effective entries."""

    return tuple(
        PluginEffectiveConfigurationEntry(
            plugin_id=plugin_id,
            contribution_id=item.contribution_id,
            configuration=item.configuration,
        )
        for item in closure
    )


def _configuration_map_fingerprint(
    entries: tuple[PluginEffectiveConfigurationEntry, ...],
) -> str:
    return _digest_document(
        {
            "configurations": [item.to_dict() for item in entries],
            "domain": "loushang.plugin-group-configuration/v1",
        }
    )


def _source_group_fingerprint(
    proposal: PluginDeclarationSourceProposal,
    *,
    context: PluginPreflightContextV1,
    instance_revision_ref: PluginInstanceRevisionRef,
) -> str:
    return _digest_document(
        {
            "allowedAuthorityCeiling": list(proposal.allowed_authority_ceiling),
            "ambientHostAuthority": (
                proposal.declaration_source.kind == "in_process"
            ),
            "configurationMapFingerprint": (
                proposal.configuration_map_fingerprint
            ),
            "dependencyLockDigest": proposal.package.dependency_lock.digest,
            "domain": "loushang.plugin-declaration-source-group/v1",
            "instanceRevisionRef": instance_revision_ref.to_dict(),
            "packageContentDigest": proposal.package.content_digest,
            "packageSourceIdentity": (
                proposal.trust_snapshot.package_source_identity
            ),
            "pluginId": proposal.package.manifest.name,
            "policyRevision": context.policy_revision,
            "productId": context.product_id,
            "requestedAuthorities": list(proposal.requested_authorities),
            "reservationClosureFingerprint": _reservation_closure_fingerprint(
                proposal.reservation_closure
            ),
            "scopeId": context.scope_id,
            "sourceDescriptorFingerprint": (
                proposal.source_descriptor_fingerprint
            ),
            "sourceTrustClass": proposal.trust_snapshot.source_trust_class,
            "sourceTrustPolicyRevision": (
                proposal.trust_snapshot.source_trust_policy_revision
            ),
        }
    )


def _source_group_id(
    preflight_use_id: str,
    source_group_fingerprint: str,
) -> str:
    return _digest_document(
        {
            "domain": "loushang.plugin-declaration-source-group-use/v1",
            "preflightUseId": preflight_use_id,
            "sourceGroupFingerprint": source_group_fingerprint,
        }
    )


def _strict_sorted_unique_strings(
    values: tuple[str, ...], *, name: str
) -> tuple[str, ...]:
    if any(
        not isinstance(value, str) or not value or value != value.strip()
        for value in values
    ):
        raise ValueError(f"{name} must contain non-empty strings")
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError(f"{name} must use canonical sorted order without duplicates")
    return values


def _validate_effective_configuration_value(value: object) -> None:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise PluginSelectionError(
                "Plugin effective configuration keys must be strings.",
                code="invalid_plugin_effective_configuration",
            )
        if "$secretRef" in value:
            if set(value) != {"$secretRef"}:
                raise PluginSelectionError(
                    "A Plugin secret reference object cannot contain peer fields.",
                    code="invalid_plugin_effective_configuration",
                )
            reference = value["$secretRef"]
            if not isinstance(reference, Mapping) or set(reference) != {
                "authorityClass",
                "providerId",
                "referenceId",
                "rotationEpoch",
                "secretReferenceVersion",
            }:
                raise PluginSelectionError(
                    "Plugin secret reference fields are invalid.",
                    code="invalid_plugin_effective_configuration",
                )
            for key in ("authorityClass", "providerId", "referenceId"):
                item = reference[key]
                if not isinstance(item, str) or not item or item != item.strip():
                    raise PluginSelectionError(
                        "Plugin secret reference identity is invalid.",
                        code="invalid_plugin_effective_configuration",
                    )
            rotation_epoch = reference["rotationEpoch"]
            if (
                not isinstance(rotation_epoch, int)
                or isinstance(rotation_epoch, bool)
                or rotation_epoch < 0
            ):
                raise PluginSelectionError(
                    "Plugin secret reference rotation epoch is invalid.",
                    code="invalid_plugin_effective_configuration",
                )
            secret_reference_version = reference["secretReferenceVersion"]
            if (
                not isinstance(secret_reference_version, int)
                or isinstance(secret_reference_version, bool)
                or secret_reference_version != 1
            ):
                raise PluginSelectionError(
                    "Plugin secret reference version is invalid.",
                    code="invalid_plugin_effective_configuration",
                )
            return
        for item in value.values():
            _validate_effective_configuration_value(item)
        return
    if isinstance(value, list | tuple):
        for item in value:
            _validate_effective_configuration_value(item)
        return
    try:
        StrictPluginJsonCodec.encode(value)
    except (TypeError, ValueError) as exc:
        raise PluginSelectionError(
            "Plugin effective configuration contains a non-JSON value.",
            code="invalid_plugin_effective_configuration",
        ) from exc


def _validate_preflight_diagnostics(
    diagnostics: tuple[PluginPreflightDiagnostic, ...],
    *,
    required: bool,
) -> None:
    if required and not diagnostics:
        raise ValueError("Preflight outcome requires diagnostics")
    if any(not isinstance(item, PluginPreflightDiagnostic) for item in diagnostics):
        raise TypeError("Preflight diagnostics have invalid type")
    if diagnostics != tuple(sorted(diagnostics)):
        raise ValueError("Preflight diagnostics must be strictly sorted")
    if len(diagnostics) != len(set(diagnostics)):
        raise ValueError("Preflight diagnostics must be unique")


def _preflight_diagnostic(error: PluginSelectionError) -> PluginPreflightDiagnostic:
    return PluginPreflightDiagnostic(
        code=error.code,
        message=str(error),
    )


def _source_preflight_diagnostic(
    error: PluginSelectionError,
    proposal: PluginDeclarationSourceProposal,
) -> PluginPreflightDiagnostic:
    return PluginPreflightDiagnostic(
        code=error.code,
        message=str(error),
        plugin_id=proposal.package.manifest.name,
        source_descriptor_fingerprint=proposal.source_descriptor_fingerprint,
    )


def _sorted_unique_diagnostics(
    diagnostics: list[PluginPreflightDiagnostic],
) -> tuple[PluginPreflightDiagnostic, ...]:
    return tuple(sorted(set(diagnostics)))


def _selection_wire_object(value: object, *, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise PluginDeclarationCodecError(
            f"{name} must be an object",
            code="plugin_declaration_field_type_mismatch",
        )
    return value


def _selection_wire_exact_fields(
    document: Mapping[str, object], *, keys: set[str], name: str
) -> None:
    if set(document) != keys:
        raise PluginDeclarationCodecError(
            f"{name} fields do not match the supported format",
            code="plugin_declaration_exact_field_mismatch",
        )


def _selection_wire_version(
    document: Mapping[str, object], *, key: str, supported: int, code: str
) -> None:
    if key not in document:
        raise PluginDeclarationCodecError(f"{key} is missing", code=code)
    value = document[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise PluginDeclarationCodecError(
            f"{key} must be an integer",
            code="plugin_declaration_field_type_mismatch",
        )
    if value != supported:
        raise PluginDeclarationCodecError(f"Unsupported {key}", code=code)


def _selection_wire_string(value: object, *, name: str) -> str:
    if not isinstance(value, str):
        raise PluginDeclarationCodecError(
            f"{name} must be a string",
            code="plugin_declaration_field_type_mismatch",
        )
    return value


def _selection_wire_integer(value: object, *, name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise PluginDeclarationCodecError(
            f"{name} must be an integer",
            code="plugin_declaration_field_type_mismatch",
        )
    return value


def _selection_wire_string_list(value: object, *, name: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise PluginDeclarationCodecError(
            f"{name} must be a string list",
            code="plugin_declaration_field_type_mismatch",
        )
    return tuple(value)


def _require_nonempty(value: object, *, name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty string")


def _require_exact_version(value: object, *, supported: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value != supported:
        raise ValueError(f"Unsupported {name} version")


def _require_sha256(value: object, *, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be a lowercase SHA-256 digest")


def _require_hex(value: object, *, length: int, name: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{name} must be {length} lowercase hexadecimal characters")


def _digest_document(value: object) -> str:
    encoded = StrictPluginJsonCodec.encode(value)
    return sha256(encoded).hexdigest()


__all__ = [
    "AcceptedPluginPreflight",
    "PLUGIN_DECLARATION_EVIDENCE_VERSION",
    "PLUGIN_EFFECTIVE_CONFIGURATION_SET_VERSION",
    "PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION",
    "PLUGIN_EXECUTION_DECISION_RECORD_VERSION",
    "PLUGIN_PREFLIGHT_CONTEXT_VERSION",
    "PLUGIN_SELECTION_PLAN_VERSION",
    "PLUGIN_SOURCE_TRUST_SNAPSHOT_VERSION",
    "PendingOnlyPluginExecutionDecisionLookup",
    "PluginContributionCandidate",
    "PluginContributionRef",
    "PluginDeclarationBatch",
    "PluginDeclarationDataOnlyGate",
    "PluginDeclarationDataOnlyDisposition",
    "PluginDeclarationExecutionPreflightGate",
    "PluginDeclarationExecutionSubjectDisposition",
    "PluginDeclarationGate",
    "PluginDeclarationReservation",
    "PluginDeclarationSourceGroup",
    "PluginDeclarationSourceDisposition",
    "PluginDeclarationSourceProposal",
    "PluginDocumentDecodedEvidence",
    "PluginEffectiveConfigurationEntry",
    "PluginEffectiveConfigurationSetV1",
    "PluginExecutionApprovalSubject",
    "PluginExecutionDecisionCurrent",
    "PluginExecutionDecisionLookupPort",
    "PluginExecutionDecisionLookupResult",
    "PluginExecutionDecisionMissing",
    "PluginExecutionDecisionRecord",
    "PluginInstanceRevisionRef",
    "PluginPreflightAcceptedOutcome",
    "PluginPreflightContextV1",
    "PluginPreflightDeniedOutcome",
    "PluginPreflightDiagnostic",
    "PluginPreflightOutcome",
    "PluginPreflightPendingApprovalOutcome",
    "PluginPreflightProposal",
    "PluginPreflightRejectedOutcome",
    "PluginSelection",
    "PluginSelectionError",
    "PluginSelectionPlanV2",
    "PluginSelectionResolver",
    "PluginSourceTrustSnapshotV1",
]
