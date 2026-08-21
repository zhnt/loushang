from __future__ import annotations

import json
import secrets
import threading
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Literal

from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclaration,
)
from loushang.harness.resources.plugins.types import (
    PluginSource,
    PluginSourceBinding,
    PublishedPluginPackage,
)

PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION = 1


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
    trusted: bool

    def __post_init__(self) -> None:
        _require_nonempty(self.plugin_id, name="Plugin id")
        _require_nonempty(self.source_identity, name="source identity")
        _require_nonempty(self.trust_class, name="source trust class")
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
        authorities = _sorted_unique_strings(
            self.allowed_authorities,
            name="allowed authorities",
        )
        object.__setattr__(self, "selected_plugin_ids", plugin_ids)
        object.__setattr__(self, "selected_contributions", contributions)
        object.__setattr__(self, "source_trust", trust)
        object.__setattr__(self, "allowed_authorities", authorities)


@dataclass(frozen=True, slots=True)
class PluginExecutionApprovalSubject:
    plugin_id: str
    package_content_digest: str
    dependency_lock_digest: str
    contribution_id: str
    reservation_fingerprint: str
    execution_model: str
    entrypoint: str
    source_identity: str
    source_trust_class: str
    product_id: str
    scope_id: str
    policy_revision: str
    ambient_host_authority: bool
    configuration_fingerprint: str
    requested_authorities: tuple[str, ...]
    schema_version: int = PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION

    def __post_init__(self) -> None:
        for name, value in (
            ("Plugin id", self.plugin_id),
            ("contribution id", self.contribution_id),
            ("execution model", self.execution_model),
            ("entrypoint", self.entrypoint),
            ("source identity", self.source_identity),
            ("source trust class", self.source_trust_class),
            ("Product id", self.product_id),
            ("scope id", self.scope_id),
            ("policy revision", self.policy_revision),
        ):
            _require_nonempty(value, name=name)
        for name, value in (
            ("package content digest", self.package_content_digest),
            ("dependency lock digest", self.dependency_lock_digest),
            ("reservation fingerprint", self.reservation_fingerprint),
            ("configuration fingerprint", self.configuration_fingerprint),
        ):
            _require_sha256(value, name=name)
        if not isinstance(self.ambient_host_authority, bool):
            raise TypeError("ambient host authority must be a boolean")
        if self.schema_version != PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION:
            raise ValueError("Unsupported Plugin execution approval subject version")
        object.__setattr__(
            self,
            "requested_authorities",
            _sorted_unique_strings(
                self.requested_authorities,
                name="requested authorities",
            ),
        )

    @property
    def digest(self) -> str:
        return _digest_document(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "ambientHostAuthority": self.ambient_host_authority,
            "configurationFingerprint": self.configuration_fingerprint,
            "contributionId": self.contribution_id,
            "dependencyLockDigest": self.dependency_lock_digest,
            "entrypoint": self.entrypoint,
            "executionModel": self.execution_model,
            "packageContentDigest": self.package_content_digest,
            "pluginId": self.plugin_id,
            "policyRevision": self.policy_revision,
            "productId": self.product_id,
            "requestedAuthorities": list(self.requested_authorities),
            "reservationFingerprint": self.reservation_fingerprint,
            "scopeId": self.scope_id,
            "schemaVersion": self.schema_version,
            "sourceIdentity": self.source_identity,
            "sourceTrustClass": self.source_trust_class,
        }


@dataclass(frozen=True, slots=True)
class PluginExecutionDecisionRecord:
    decision_id: str
    subject_digest: str
    policy_revision: str
    disposition: Literal["approved", "denied"]

    def __post_init__(self) -> None:
        _require_nonempty(self.decision_id, name="decision id")
        _require_sha256(self.subject_digest, name="decision subject digest")
        _require_nonempty(self.policy_revision, name="decision policy revision")
        if self.disposition not in {"approved", "denied"}:
            raise ValueError("Unsupported Plugin execution decision disposition")


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
    return PluginExecutionApprovalSubject(
        plugin_id=package.manifest.name,
        package_content_digest=package.content_digest,
        dependency_lock_digest=package.dependency_lock.digest,
        contribution_id=contribution.contribution_id,
        reservation_fingerprint=contribution.fingerprint,
        execution_model=contribution.execution_model,
        entrypoint=contribution.entrypoint,
        source_identity=binding.source_identity,
        source_trust_class=source_trust.trust_class,
        product_id=plan.product_id,
        scope_id=plan.scope_id,
        policy_revision=plan.policy_revision,
        ambient_host_authority=contribution.execution_model == "in_process",
        configuration_fingerprint=contribution.configuration_fingerprint,
        requested_authorities=contribution.requested_authorities,
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
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


__all__ = [
    "PLUGIN_EXECUTION_APPROVAL_SUBJECT_VERSION",
    "PluginContributionCandidate",
    "PluginContributionRef",
    "PluginDeclarationReservation",
    "PluginExecutionApprovalSubject",
    "PluginExecutionDecisionRecord",
    "PluginPreflight",
    "PluginSelection",
    "PluginSelectionError",
    "PluginSelectionPlan",
    "PluginSelectionResolver",
    "PluginSourceTrust",
    "build_execution_approval_subject",
]
