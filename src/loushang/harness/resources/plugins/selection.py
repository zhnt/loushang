from __future__ import annotations

import secrets
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Literal, cast

from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclaration,
    PluginDeclarationCodecError,
    PluginDeclarationSource,
)
from loushang.harness.resources.plugins.locators import parse_plugin_entrypoint
from loushang.harness.resources.plugins.types import (
    PluginSource,
    PluginSourceBinding,
    PublishedPluginPackage,
)

PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION = 2
PLUGIN_EXECUTION_DECISION_RECORD_VERSION = 2


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


@dataclass(frozen=True, order=True, slots=True)
class PluginSourceTrust:
    plugin_id: str
    source_identity: str
    trust_class: str
    trust_policy_revision: str
    trusted: bool

    def __post_init__(self) -> None:
        _require_nonempty(self.plugin_id, name="Plugin id")
        _require_nonempty(self.source_identity, name="source identity")
        _require_nonempty(self.trust_class, name="source trust class")
        _require_nonempty(
            self.trust_policy_revision, name="source trust policy revision"
        )
        if not isinstance(self.trusted, bool):
            raise TypeError("Plugin source trust decision must be a boolean")


@dataclass(frozen=True, slots=True)
class PluginSelectionPlan:
    """Product/scope selection and policy facts consumed by inert preflight."""

    product_id: str
    scope_id: str
    policy_revision: str
    selected_plugin_ids: tuple[str, ...]
    selected_contributions: tuple[PluginContributionRef, ...]
    source_trust: tuple[PluginSourceTrust, ...]
    instance_revision_refs: tuple[PluginInstanceRevisionRef, ...]
    allowed_authorities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_nonempty(self.product_id, name="Product id")
        _require_nonempty(self.scope_id, name="scope id")
        _require_nonempty(self.policy_revision, name="policy revision")
        plugin_ids = _sorted_unique_strings(
            self.selected_plugin_ids,
            name="selected Plugin ids",
        )
        contributions = tuple(sorted(self.selected_contributions))
        if len(contributions) != len(set(contributions)):
            raise ValueError("Selected Plugin contributions must be unique")
        trust = tuple(sorted(self.source_trust))
        trust_ids = [item.plugin_id for item in trust]
        if len(trust_ids) != len(set(trust_ids)):
            raise ValueError("Plugin source trust facts must be unique per Plugin")
        if any(
            not isinstance(item, PluginInstanceRevisionRef)
            for item in self.instance_revision_refs
        ):
            raise TypeError("Plugin instance revision refs have an invalid type")
        instance_refs = tuple(
            sorted(
                self.instance_revision_refs,
                key=lambda item: (item.plugin_id, item.instance_id, item.revision),
            )
        )
        instance_plugin_ids = tuple(item.plugin_id for item in instance_refs)
        instance_ids = tuple(item.instance_id for item in instance_refs)
        if (
            len(instance_plugin_ids) != len(set(instance_plugin_ids))
            or len(instance_ids) != len(set(instance_ids))
        ):
            raise ValueError("Plugin instance revision refs must be unique")
        if set(instance_plugin_ids) != set(plugin_ids):
            raise ValueError("Plugin instance revision refs must cover selected Plugins")
        authorities = _sorted_unique_strings(
            self.allowed_authorities,
            name="allowed authorities",
        )
        object.__setattr__(self, "selected_plugin_ids", plugin_ids)
        object.__setattr__(self, "selected_contributions", contributions)
        object.__setattr__(self, "source_trust", trust)
        object.__setattr__(self, "instance_revision_refs", instance_refs)
        object.__setattr__(self, "allowed_authorities", authorities)


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
        if self.schema_version != PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION:
            raise ValueError("Unsupported Plugin execution approval subject version")
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
                plugin_id=_selection_wire_string(document["pluginId"], name="Plugin id"),
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
        if self.decision_record_version != PLUGIN_EXECUTION_DECISION_RECORD_VERSION:
            raise ValueError("Unsupported Plugin execution decision record version")
        if self.subject_schema_version != PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION:
            raise ValueError("Unsupported Plugin execution approval subject version")

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
    plan: PluginSelectionPlan
    reservations: tuple[PluginDeclarationReservation, ...]
    _token: str = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class PluginContributionCandidate:
    package: PublishedPluginPackage = field(repr=False)
    declaration: PluginDeclaration
    decision_id: str
    fingerprint: str


@dataclass(frozen=True, slots=True)
class PluginSelection:
    plan: PluginSelectionPlan
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
        plan: PluginSelectionPlan,
        decisions: tuple[PluginExecutionDecisionRecord, ...],
    ) -> PluginPreflight:
        packages_by_id = _packages_by_id(packages)
        bindings_by_id = _bindings_by_id(bindings)
        selected_ids = set(plan.selected_plugin_ids)
        if set(packages_by_id) != selected_ids or set(bindings_by_id) != selected_ids:
            raise PluginSelectionError(
                "Published Plugin/binding set does not exactly match Product selection.",
                code="plugin_selection_package_mismatch",
            )
        trust_by_id = {item.plugin_id: item for item in plan.source_trust}
        if set(trust_by_id) != selected_ids:
            raise PluginSelectionError(
                "Plugin source trust facts do not exactly match Product selection.",
                code="plugin_selection_trust_mismatch",
            )
        decisions_by_subject: dict[str, PluginExecutionDecisionRecord] = {}
        for decision in decisions:
            if decision.subject_digest in decisions_by_subject:
                raise PluginSelectionError(
                    "Multiple execution decisions target the same approval subject.",
                    code="duplicate_plugin_execution_decision",
                )
            decisions_by_subject[decision.subject_digest] = decision

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
                trust.source_identity != binding.source_identity
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

        reservations: list[PluginDeclarationReservation] = []
        allowed_authorities = set(plan.allowed_authorities)
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
            subject = build_execution_approval_subject(
                package,
                contribution,
                plan=plan,
                source_trust=trust_by_id[ref.plugin_id],
                binding=bindings_by_id[ref.plugin_id],
            )
            matched_decision = decisions_by_subject.get(subject.digest)
            if matched_decision is None:
                raise PluginSelectionError(
                    f"Plugin execution approval is pending: {ref}",
                    code="plugin_execution_approval_required",
                    path=package.root,
                )
            if (
                matched_decision.disposition != "approved"
                or matched_decision.policy_revision != plan.policy_revision
            ):
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
    plan: PluginSelectionPlan,
    source_trust: PluginSourceTrust,
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
    if (
        source_trust.plugin_id != package.manifest.name
        or source_trust.source_identity != binding.source_identity
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
            {
                authority
                for item in closure
                for authority in item.requested_authorities
            }
        )
    )
    if not set(requested_authorities).issubset(plan.allowed_authorities):
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
        source_trust_class=source_trust.trust_class,
        source_trust_policy_revision=source_trust.trust_policy_revision,
        product_id=plan.product_id,
        scope_id=plan.scope_id,
        policy_revision=plan.policy_revision,
        ambient_host_authority=(
            contribution.contribution_execution_model == "in_process"
        ),
        configuration_map_fingerprint=_configuration_map_fingerprint(
            package.manifest.name,
            closure,
        ),
        requested_authorities=requested_authorities,
        allowed_authority_ceiling=plan.allowed_authorities,
        reservation_closure_fingerprint=_reservation_closure_fingerprint(closure),
        source_descriptor_fingerprint=contribution.source_descriptor_fingerprint,
        instance_revision_ref={
            item.plugin_id: item for item in plan.instance_revision_refs
        }[package.manifest.name],
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
    reservation: PluginDeclarationReservation,
    declaration: PluginDeclaration,
    *,
    plan: PluginSelectionPlan,
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
            "policyRevision": plan.policy_revision,
            "productId": plan.product_id,
            "reservationFingerprint": reservation.contribution.fingerprint,
            "scopeId": plan.scope_id,
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


def _configuration_map_fingerprint(
    plugin_id: str,
    closure: tuple[PluginContributionReservation, ...],
) -> str:
    return _digest_document(
        {
            "configurations": [
                {
                    "configuration": item.to_dict()["configuration"],
                    "contributionId": item.contribution_id,
                    "pluginId": plugin_id,
                }
                for item in closure
            ],
            "domain": "loushang.plugin-group-configuration/v1",
        }
    )


def _sorted_unique_strings(values: tuple[str, ...], *, name: str) -> tuple[str, ...]:
    if any(
        not isinstance(value, str) or not value or value != value.strip()
        for value in values
    ):
        raise ValueError(f"{name} must contain non-empty strings")
    normalized = tuple(sorted(values))
    if len(normalized) != len(set(normalized)):
        raise ValueError(f"{name} must be unique")
    return normalized


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
    "PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION",
    "PLUGIN_EXECUTION_DECISION_RECORD_VERSION",
    "PluginContributionCandidate",
    "PluginContributionRef",
    "PluginDeclarationReservation",
    "PluginExecutionApprovalSubject",
    "PluginExecutionDecisionRecord",
    "PluginInstanceRevisionRef",
    "PluginPreflight",
    "PluginSelection",
    "PluginSelectionError",
    "PluginSelectionPlan",
    "PluginSelectionResolver",
    "PluginSourceTrust",
    "build_execution_approval_subject",
]
