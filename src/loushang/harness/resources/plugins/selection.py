from __future__ import annotations

import secrets
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Literal, Protocol, cast

from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclaration,
    PluginDeclarationCodecError,
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
PLUGIN_PREFLIGHT_CONTEXT_VERSION = 1
PLUGIN_SELECTION_PLAN_VERSION = 2
PLUGIN_SOURCE_TRUST_SNAPSHOT_VERSION = 1


class PluginSelectionError(RuntimeError):
    """Structured fail-closed error from inert Plugin selection."""

    def __init__(self, message: str, *, code: str, path: Path = Path()) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


class _PluginExecutionApprovalPending(PluginSelectionError):
    def __init__(
        self,
        message: str,
        *,
        subject: PluginExecutionApprovalSubject,
        path: Path,
    ) -> None:
        super().__init__(
            message,
            code="plugin_execution_approval_required",
            path=path,
        )
        self.subject = subject


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
class PluginDeclarationReservation:
    package: PublishedPluginPackage = field(repr=False)
    contribution: PluginContributionReservation
    approval_subject: PluginExecutionApprovalSubject
    decision_id: str

    @property
    def ref(self) -> PluginContributionRef:
        return PluginContributionRef(
            plugin_id=self.package.manifest.name,
            contribution_id=self.contribution.contribution_id,
        )


@dataclass(frozen=True, slots=True)
class PluginPreflight:
    plan: PluginSelectionPlanV2
    reservations: tuple[PluginDeclarationReservation, ...]
    _token: str = field(repr=False, compare=False)


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
    accepted: PluginPreflight
    disposition: Literal["accepted"] = "accepted"

    def __post_init__(self) -> None:
        if not isinstance(self.accepted, PluginPreflight):
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


@dataclass(frozen=True, slots=True)
class PluginContributionCandidate:
    package: PublishedPluginPackage = field(repr=False)
    declaration: PluginDeclaration
    decision_id: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class PluginSelection:
    plan: PluginSelectionPlanV2
    candidates: tuple[PluginContributionCandidate, ...]


class PluginSelectionResolver:
    """Two-phase inert selector with one-use declaration reservations."""

    def __init__(self) -> None:
        self._gate = threading.Lock()
        self._active: dict[str, PluginPreflight] = {}

    def preflight(
        self,
        packages: tuple[PublishedPluginPackage, ...],
        *,
        bindings: tuple[PluginSourceBinding, ...],
        plan: PluginSelectionPlanV2,
        decision_lookup: PluginExecutionDecisionLookupPort,
    ) -> PluginPreflightOutcome:
        try:
            accepted = self._preflight_accepted(
                packages,
                bindings=bindings,
                plan=plan,
                decision_lookup=decision_lookup,
            )
        except _PluginExecutionApprovalPending as exc:
            return PluginPreflightPendingApprovalOutcome(
                subjects=(exc.subject,),
                diagnostics=(_preflight_diagnostic(exc),),
            )
        except PluginSelectionError as exc:
            diagnostic = _preflight_diagnostic(exc)
            if exc.code == "plugin_execution_denied":
                return PluginPreflightDeniedOutcome(diagnostics=(diagnostic,))
            return PluginPreflightRejectedOutcome(diagnostics=(diagnostic,))
        return PluginPreflightAcceptedOutcome(accepted=accepted)

    def _preflight_accepted(
        self,
        packages: tuple[PublishedPluginPackage, ...],
        *,
        bindings: tuple[PluginSourceBinding, ...],
        plan: PluginSelectionPlanV2,
        decision_lookup: PluginExecutionDecisionLookupPort,
    ) -> PluginPreflight:
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
        source_proposals_by_key = {item.key: item for item in proposal.source_proposals}

        reservations: list[PluginDeclarationReservation] = []
        lookup_results: dict[str, PluginExecutionDecisionLookupResult] = {}
        allowed_authorities = set(plan.allowed_authority_ceiling)
        for ref in plan.selected_contributions:
            package = packages_by_id[ref.plugin_id]
            contribution = indexed[ref]
            if not set(contribution.requested_authorities).issubset(
                allowed_authorities
            ):
                raise PluginSelectionError(
                    f"Plugin contribution exceeds its authority ceiling: {ref}",
                    code="plugin_authority_ceiling_exceeded",
                    path=package.root,
                )
            source_proposal = source_proposals_by_key[
                (ref.plugin_id, contribution.source_descriptor_fingerprint)
            ]
            disposition = source_proposal.source_disposition
            if not isinstance(
                disposition,
                PluginDeclarationExecutionSubjectDisposition,
            ):
                raise PluginSelectionError(
                    "Document declaration sources do not require execution approval.",
                    code="plugin_execution_subject_not_applicable",
                    path=package.root,
                )
            subject = disposition.subject
            lookup_result = lookup_results.get(subject.digest)
            if lookup_result is None:
                try:
                    lookup_result = lookup_method(subject)
                except Exception as exc:
                    raise PluginSelectionError(
                        "Plugin execution decision lookup failed closed.",
                        code="invalid_plugin_execution_decision_lookup",
                        path=package.root,
                    ) from exc
                if not isinstance(
                    lookup_result,
                    PluginExecutionDecisionMissing | PluginExecutionDecisionCurrent,
                ):
                    raise PluginSelectionError(
                        "Plugin execution decision lookup returned an invalid result.",
                        code="invalid_plugin_execution_decision_lookup",
                        path=package.root,
                    )
                lookup_results[subject.digest] = lookup_result
            if isinstance(lookup_result, PluginExecutionDecisionMissing):
                raise _PluginExecutionApprovalPending(
                    f"Plugin execution approval is pending: {ref}",
                    subject=subject,
                    path=package.root,
                )
            matched_decision = lookup_result.decision
            if (
                matched_decision.subject_digest != subject.digest
                or matched_decision.policy_revision != plan.context.policy_revision
                or matched_decision.subject_schema_version != subject.schema_version
            ):
                raise PluginSelectionError(
                    "Approval owner returned a decision for a different Subject.",
                    code="invalid_plugin_execution_decision_lookup",
                    path=package.root,
                )
            if matched_decision.disposition != "approved":
                raise PluginSelectionError(
                    f"Plugin execution was denied: {ref}",
                    code="plugin_execution_denied",
                    path=package.root,
                )
            reservations.append(
                PluginDeclarationReservation(
                    package=package,
                    contribution=contribution,
                    approval_subject=subject,
                    decision_id=matched_decision.decision_id,
                )
            )

        with self._gate:
            token = secrets.token_hex(24)
            while token in self._active:
                token = secrets.token_hex(24)
            preflight = PluginPreflight(
                plan=plan,
                reservations=tuple(reservations),
                _token=token,
            )
            self._active[token] = preflight
        return preflight

    def rollback(self, preflight: PluginPreflight) -> None:
        """Release one unconsumed preflight reservation without finalizing it."""

        with self._gate:
            active = self._active.pop(preflight._token, None)
        if active is not preflight:
            raise PluginSelectionError(
                "Plugin preflight reservation was already consumed or is foreign.",
                code="plugin_preflight_consumed",
            )

    def finalize(
        self,
        preflight: PluginPreflight,
        declarations: tuple[PluginDeclaration, ...],
    ) -> PluginSelection:
        with self._gate:
            active = self._active.pop(preflight._token, None)
        if active is not preflight:
            raise PluginSelectionError(
                "Plugin preflight reservation was already consumed or is foreign.",
                code="plugin_preflight_consumed",
            )

        declarations_by_ref: dict[PluginContributionRef, PluginDeclaration] = {}
        for declaration in declarations:
            ref = PluginContributionRef(
                declaration.plugin_id,
                declaration.contribution_id,
            )
            if ref in declarations_by_ref:
                raise PluginSelectionError(
                    f"Plugin declaration identity was emitted twice: {ref}",
                    code="duplicate_plugin_declaration",
                )
            declarations_by_ref[ref] = declaration
        expected_refs = {reservation.ref for reservation in preflight.reservations}
        if set(declarations_by_ref) != expected_refs:
            raise PluginSelectionError(
                "Plugin declarations do not exactly fulfill preflight reservations.",
                code="plugin_declaration_reservation_mismatch",
            )

        candidates: list[PluginContributionCandidate] = []
        for reservation in preflight.reservations:
            declaration = declarations_by_ref[reservation.ref]
            contribution = reservation.contribution
            if (
                declaration.kind != contribution.kind
                or declaration.owner != contribution.owner
                or declaration.reservation_fingerprint != contribution.fingerprint
                or declaration.source_descriptor_fingerprint
                != contribution.source_descriptor_fingerprint
                or declaration.source_kind != contribution.declaration_source.kind
            ):
                raise PluginSelectionError(
                    f"Plugin declaration changed its inert reservation: "
                    f"{reservation.ref}",
                    code="plugin_declaration_envelope_mismatch",
                    path=reservation.package.root,
                )
            fingerprint = _candidate_fingerprint(
                reservation,
                declaration,
                plan=preflight.plan,
            )
            candidates.append(
                PluginContributionCandidate(
                    package=reservation.package,
                    declaration=declaration,
                    decision_id=reservation.decision_id,
                    fingerprint=fingerprint,
                )
            )
        return PluginSelection(plan=preflight.plan, candidates=tuple(candidates))


def build_execution_approval_subject(
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
        ambient_host_authority=(
            contribution.contribution_execution_model == "in_process"
        ),
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
                subject=build_execution_approval_subject(
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
    reservation: PluginDeclarationReservation,
    declaration: PluginDeclaration,
    *,
    plan: PluginSelectionPlanV2,
) -> str:
    package = reservation.package
    return _digest_document(
        {
            "approvalSubjectDigest": reservation.approval_subject.digest,
            "declaration": declaration.to_dict(),
            "declarationFingerprint": declaration.fingerprint,
            "decisionId": reservation.decision_id,
            "dependencyLockDigest": package.dependency_lock.digest,
            "packageContentDigest": package.content_digest,
            "pluginId": package.manifest.name,
            "policyRevision": plan.context.policy_revision,
            "productId": plan.context.product_id,
            "reservationFingerprint": reservation.contribution.fingerprint,
            "scopeId": plan.context.scope_id,
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


def _digest_document(value: object) -> str:
    encoded = StrictPluginJsonCodec.encode(value)
    return sha256(encoded).hexdigest()


__all__ = [
    "PLUGIN_EFFECTIVE_CONFIGURATION_SET_VERSION",
    "PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION",
    "PLUGIN_EXECUTION_DECISION_RECORD_VERSION",
    "PLUGIN_PREFLIGHT_CONTEXT_VERSION",
    "PLUGIN_SELECTION_PLAN_VERSION",
    "PLUGIN_SOURCE_TRUST_SNAPSHOT_VERSION",
    "PendingOnlyPluginExecutionDecisionLookup",
    "PluginContributionCandidate",
    "PluginContributionRef",
    "PluginDeclarationDataOnlyDisposition",
    "PluginDeclarationExecutionSubjectDisposition",
    "PluginDeclarationReservation",
    "PluginDeclarationSourceDisposition",
    "PluginDeclarationSourceProposal",
    "PluginEffectiveConfigurationEntry",
    "PluginEffectiveConfigurationSetV1",
    "PluginExecutionApprovalSubject",
    "PluginExecutionDecisionCurrent",
    "PluginExecutionDecisionLookupPort",
    "PluginExecutionDecisionLookupResult",
    "PluginExecutionDecisionMissing",
    "PluginExecutionDecisionRecord",
    "PluginInstanceRevisionRef",
    "PluginPreflight",
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
    "build_execution_approval_subject",
]
