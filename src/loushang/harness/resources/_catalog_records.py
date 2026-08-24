"""Immutable Resource Catalog v2 records used by the RCP1 shadow core.

This module is intentionally private.  RCP1 does not publish a Plugin SDK or
change the authority of the existing resource loader.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal, TypeAlias

from loushang.harness.resources.types import ResourceSourceKind

NO_BODY_MEDIA_TYPE = "application/vnd.loushang.resource.no-body"

ResourceMergeStrategy = Literal[
    "strict_exclusive",
    "permissive_exclusive",
    "ordered_additive",
]


def fingerprint_catalog_value(domain: str, value: object) -> str:
    """Return a domain-separated fingerprint for a JSON-compatible value."""

    if not domain:
        raise ValueError("Catalog fingerprint domain must be non-empty.")
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(domain.encode("utf-8") + b"\0" + encoded).hexdigest()


@dataclass(frozen=True, order=True)
class ResourceIdentity:
    resource_kind: str
    schema_id: str
    schema_version: int
    public_id: str

    def __post_init__(self) -> None:
        _require_non_empty(self.resource_kind, name="Resource kind")
        _require_non_empty(self.schema_id, name="Resource schema id")
        if self.schema_version < 1:
            raise ValueError("Resource schema version must be positive.")
        _require_non_empty(self.public_id, name="Resource public id")

    def to_payload(self) -> dict[str, object]:
        return {
            "publicId": self.public_id,
            "resourceKind": self.resource_kind,
            "schemaId": self.schema_id,
            "schemaVersion": self.schema_version,
        }


@dataclass(frozen=True)
class ResourceComponentProducer:
    component_contribution_id: str
    component_candidate_fingerprint: str
    component_admission_fingerprint: str
    binding_fingerprint: str
    plugin_instance_revision_ref: str
    package_content_digest: str

    def __post_init__(self) -> None:
        _require_non_empty(
            self.component_contribution_id,
            name="Resource component contribution id",
        )
        _require_digest(
            self.component_candidate_fingerprint,
            name="Resource component candidate fingerprint",
        )
        _require_digest(
            self.component_admission_fingerprint,
            name="Resource component admission fingerprint",
        )
        _require_digest(self.binding_fingerprint, name="Resource binding fingerprint")
        _require_non_empty(
            self.plugin_instance_revision_ref,
            name="Plugin instance revision ref",
        )
        _require_digest(
            self.package_content_digest,
            name="Resource component package content digest",
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "bindingFingerprint": self.binding_fingerprint,
            "componentAdmissionFingerprint": self.component_admission_fingerprint,
            "componentCandidateFingerprint": self.component_candidate_fingerprint,
            "componentContributionId": self.component_contribution_id,
            "packageContentDigest": self.package_content_digest,
            "pluginInstanceRevisionRef": self.plugin_instance_revision_ref,
            "type": "resource_component",
        }


@dataclass(frozen=True)
class ExtensionOwnerProducer:
    runtime_id: str
    extension_generation: str
    extension_set_fingerprint: str
    extension_owner_fingerprint: str

    def __post_init__(self) -> None:
        _require_non_empty(self.runtime_id, name="Extension runtime id")
        _require_non_empty(
            self.extension_generation,
            name="Extension generation",
        )
        _require_digest(
            self.extension_set_fingerprint,
            name="Extension set fingerprint",
        )
        _require_digest(
            self.extension_owner_fingerprint,
            name="Extension owner fingerprint",
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "extensionGeneration": self.extension_generation,
            "extensionOwnerFingerprint": self.extension_owner_fingerprint,
            "extensionSetFingerprint": self.extension_set_fingerprint,
            "runtimeId": self.runtime_id,
            "type": "extension_owner",
        }


ResourceSourceProducer: TypeAlias = ResourceComponentProducer | ExtensionOwnerProducer


@dataclass(frozen=True)
class ResourceSourceGenerationRef:
    source_id: str
    product_id: str
    generation: str
    source_policy_fingerprint: str
    producer: ResourceSourceProducer

    def __post_init__(self) -> None:
        _require_non_empty(self.source_id, name="Resource source id")
        _require_non_empty(self.product_id, name="Resource Product id")
        _require_non_empty(self.generation, name="Resource source generation")
        _require_digest(
            self.source_policy_fingerprint,
            name="Resource source policy fingerprint",
        )
        if not isinstance(
            self.producer,
            ResourceComponentProducer | ExtensionOwnerProducer,
        ):
            raise TypeError("Resource source producer must use one tagged variant.")

    def to_payload(self) -> dict[str, object]:
        return {
            "generation": self.generation,
            "producer": self.producer.to_payload(),
            "productId": self.product_id,
            "sourceId": self.source_id,
            "sourcePolicyFingerprint": self.source_policy_fingerprint,
        }


@dataclass(frozen=True)
class VerifiedPluginResourceOrigin:
    resource_contribution_id: str
    resource_admission_fingerprint: str
    plugin_instance_revision_ref: str
    package_content_digest: str

    def __post_init__(self) -> None:
        _require_non_empty(
            self.resource_contribution_id,
            name="Resource contribution id",
        )
        _require_digest(
            self.resource_admission_fingerprint,
            name="Resource admission fingerprint",
        )
        _require_non_empty(
            self.plugin_instance_revision_ref,
            name="Plugin instance revision ref",
        )
        _require_digest(
            self.package_content_digest,
            name="Resource package content digest",
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "packageContentDigest": self.package_content_digest,
            "pluginInstanceRevisionRef": self.plugin_instance_revision_ref,
            "resourceAdmissionFingerprint": self.resource_admission_fingerprint,
            "resourceContributionId": self.resource_contribution_id,
            "type": "verified_plugin_resource",
        }


@dataclass(frozen=True)
class NativeHostOrigin:
    host_root_handle_id: str
    root_policy_fingerprint: str
    workspace_or_user_scope: str

    def __post_init__(self) -> None:
        _require_non_empty(self.host_root_handle_id, name="Host root handle id")
        _require_digest(
            self.root_policy_fingerprint,
            name="Host root policy fingerprint",
        )
        if self.workspace_or_user_scope not in {"workspace", "user", "temporary"}:
            raise ValueError(
                "Native Host origin scope must be workspace, user, or temporary."
            )

    def to_payload(self) -> dict[str, object]:
        return {
            "hostRootHandleId": self.host_root_handle_id,
            "rootPolicyFingerprint": self.root_policy_fingerprint,
            "type": "native_host",
            "workspaceOrUserScope": self.workspace_or_user_scope,
        }


@dataclass(frozen=True)
class EmbeddedOemOrigin:
    embedded_collection_id: str
    embedded_revision: str
    collection_content_digest: str

    def __post_init__(self) -> None:
        _require_non_empty(
            self.embedded_collection_id,
            name="Embedded collection id",
        )
        _require_non_empty(self.embedded_revision, name="Embedded revision")
        _require_digest(
            self.collection_content_digest,
            name="Embedded collection content digest",
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "collectionContentDigest": self.collection_content_digest,
            "embeddedCollectionId": self.embedded_collection_id,
            "embeddedRevision": self.embedded_revision,
            "type": "embedded_oem",
        }


@dataclass(frozen=True)
class ExtensionOutputOrigin:
    extension_generation_ref: str
    extension_id: str
    route_id: str
    route_set_fingerprint: str
    hook_snapshot_fingerprint: str

    def __post_init__(self) -> None:
        _require_non_empty(
            self.extension_generation_ref,
            name="Extension generation ref",
        )
        _require_non_empty(self.extension_id, name="Extension id")
        _require_non_empty(self.route_id, name="Extension route id")
        _require_digest(
            self.route_set_fingerprint,
            name="Extension route-set fingerprint",
        )
        _require_digest(
            self.hook_snapshot_fingerprint,
            name="Extension hook snapshot fingerprint",
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "extensionGenerationRef": self.extension_generation_ref,
            "extensionId": self.extension_id,
            "hookSnapshotFingerprint": self.hook_snapshot_fingerprint,
            "routeId": self.route_id,
            "routeSetFingerprint": self.route_set_fingerprint,
            "type": "extension_output",
        }


ResourceContentOrigin: TypeAlias = (
    VerifiedPluginResourceOrigin
    | NativeHostOrigin
    | EmbeddedOemOrigin
    | ExtensionOutputOrigin
)


@dataclass(frozen=True)
class ResourceInvocationPolicy:
    enabled: bool
    model_invocable: bool
    reason: str

    def __post_init__(self) -> None:
        _require_non_empty(self.reason, name="Resource invocation-policy reason")

    def to_payload(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "modelInvocable": self.model_invocable,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ResourceCatalogDiagnostic:
    code: str
    reason: str
    identity: ResourceIdentity | None = None
    source_id: str | None = None
    details: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty(self.code, name="Resource diagnostic code")
        _require_non_empty(self.reason, name="Resource diagnostic reason")
        if self.source_id is not None:
            _require_non_empty(self.source_id, name="Resource diagnostic source id")
        if tuple(sorted(self.details)) != self.details:
            raise ValueError("Resource diagnostic details must be canonical.")
        if len({key for key, _value in self.details}) != len(self.details):
            raise ValueError("Resource diagnostic detail keys must be unique.")

    def canonical_sort_key(self) -> tuple[object, ...]:
        identity_key: tuple[object, ...] = (
            (
                self.identity.resource_kind,
                self.identity.schema_id,
                self.identity.schema_version,
                self.identity.public_id,
            )
            if self.identity is not None
            else ("", "", 0, "")
        )
        return (
            *identity_key,
            self.code,
            self.reason,
            self.source_id or "",
            self.details,
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "code": self.code,
            "details": list(self.details),
            "identity": self.identity.to_payload()
            if self.identity is not None
            else None,
            "reason": self.reason,
            "sourceId": self.source_id,
        }


@dataclass(frozen=True)
class ResourceCandidateSummary:
    identity: ResourceIdentity
    canonical_name: str
    description: str | None
    media_type: str
    invocation_policy: ResourceInvocationPolicy
    source_generation_ref: ResourceSourceGenerationRef
    source_class: ResourceSourceKind
    scope_id: str
    source_root_order: int
    content_origin: ResourceContentOrigin
    opaque_locator: str
    discovery_fingerprint: str
    candidate_fingerprint: str
    expected_content_digest: str | None
    expected_content_length: int | None
    diagnostics: tuple[ResourceCatalogDiagnostic, ...]

    def __post_init__(self) -> None:
        _require_non_empty(self.canonical_name, name="Resource canonical name")
        _require_non_empty(self.media_type, name="Resource media type")
        if self.source_class not in {
            "built_in",
            "external_package",
            "project_local",
            "temporary",
            "user_global",
        }:
            raise ValueError("Resource source class is unsupported.")
        _require_non_empty(self.scope_id, name="Resource scope id")
        if self.source_root_order < 0:
            raise ValueError("Resource source root order cannot be negative.")
        if not isinstance(
            self.content_origin,
            VerifiedPluginResourceOrigin
            | NativeHostOrigin
            | EmbeddedOemOrigin
            | ExtensionOutputOrigin,
        ):
            raise TypeError("Resource content origin must use one tagged variant.")
        _validate_content_origin(
            source_class=self.source_class,
            content_origin=self.content_origin,
        )
        _require_non_empty(self.opaque_locator, name="Resource opaque locator")
        _require_opaque_locator(self.opaque_locator)
        _require_digest(
            self.discovery_fingerprint,
            name="Resource discovery fingerprint",
        )
        _require_digest(
            self.candidate_fingerprint, name="Resource candidate fingerprint"
        )
        if self.expected_content_digest is None:
            if self.expected_content_length is not None:
                raise ValueError("No-body Resource length must be absent.")
            if self.media_type != NO_BODY_MEDIA_TYPE:
                raise ValueError(
                    "A Resource without a body must use the no-body media type."
                )
        else:
            _require_digest(
                self.expected_content_digest,
                name="Expected Resource content digest",
            )
            if self.expected_content_length is None or self.expected_content_length < 0:
                raise ValueError(
                    "Expected Resource content length must be non-negative."
                )
            if self.media_type == NO_BODY_MEDIA_TYPE:
                raise ValueError("The no-body media type cannot declare body identity.")
        if (
            tuple(sorted(self.diagnostics, key=lambda item: item.canonical_sort_key()))
            != self.diagnostics
        ):
            raise ValueError("Resource candidate diagnostics must be canonical.")
        expected_candidate_fingerprint = fingerprint_catalog_value(
            "loushang.resource-candidate/v2",
            _candidate_payload(
                identity=self.identity,
                canonical_name=self.canonical_name,
                description=self.description,
                media_type=self.media_type,
                invocation_policy=self.invocation_policy,
                source_generation_ref=self.source_generation_ref,
                source_class=self.source_class,
                scope_id=self.scope_id,
                source_root_order=self.source_root_order,
                content_origin=self.content_origin,
                opaque_locator=self.opaque_locator,
                discovery_fingerprint=self.discovery_fingerprint,
                expected_content_digest=self.expected_content_digest,
                expected_content_length=self.expected_content_length,
                diagnostics=self.diagnostics,
            ),
        )
        if self.candidate_fingerprint != expected_candidate_fingerprint:
            raise ValueError("Resource candidate fingerprint is invalid.")

    @property
    def has_body(self) -> bool:
        return self.expected_content_digest is not None

    def canonical_sort_key(self) -> tuple[object, ...]:
        return (
            self.identity.resource_kind,
            self.identity.schema_id,
            self.identity.schema_version,
            self.identity.public_id,
            self.candidate_fingerprint,
        )

    def to_payload(self) -> dict[str, object]:
        return _candidate_payload(
            identity=self.identity,
            canonical_name=self.canonical_name,
            description=self.description,
            media_type=self.media_type,
            invocation_policy=self.invocation_policy,
            source_generation_ref=self.source_generation_ref,
            source_class=self.source_class,
            scope_id=self.scope_id,
            source_root_order=self.source_root_order,
            content_origin=self.content_origin,
            opaque_locator=self.opaque_locator,
            discovery_fingerprint=self.discovery_fingerprint,
            expected_content_digest=self.expected_content_digest,
            expected_content_length=self.expected_content_length,
            diagnostics=self.diagnostics,
        ) | {"candidateFingerprint": self.candidate_fingerprint}


def build_candidate_summary(
    *,
    identity: ResourceIdentity,
    canonical_name: str,
    description: str | None,
    media_type: str,
    invocation_policy: ResourceInvocationPolicy,
    source_generation_ref: ResourceSourceGenerationRef,
    source_class: ResourceSourceKind,
    scope_id: str,
    source_root_order: int,
    content_origin: ResourceContentOrigin,
    opaque_locator: str,
    discovery_fingerprint: str,
    expected_content_digest: str | None,
    expected_content_length: int | None,
    diagnostics: tuple[ResourceCatalogDiagnostic, ...] = (),
) -> ResourceCandidateSummary:
    canonical_diagnostics = tuple(
        sorted(diagnostics, key=lambda item: item.canonical_sort_key())
    )
    payload = _candidate_payload(
        identity=identity,
        canonical_name=canonical_name,
        description=description,
        media_type=media_type,
        invocation_policy=invocation_policy,
        source_generation_ref=source_generation_ref,
        source_class=source_class,
        scope_id=scope_id,
        source_root_order=source_root_order,
        content_origin=content_origin,
        opaque_locator=opaque_locator,
        discovery_fingerprint=discovery_fingerprint,
        expected_content_digest=expected_content_digest,
        expected_content_length=expected_content_length,
        diagnostics=canonical_diagnostics,
    )
    return ResourceCandidateSummary(
        identity=identity,
        canonical_name=canonical_name,
        description=description,
        media_type=media_type,
        invocation_policy=invocation_policy,
        source_generation_ref=source_generation_ref,
        source_class=source_class,
        scope_id=scope_id,
        source_root_order=source_root_order,
        content_origin=content_origin,
        opaque_locator=opaque_locator,
        discovery_fingerprint=discovery_fingerprint,
        candidate_fingerprint=fingerprint_catalog_value(
            "loushang.resource-candidate/v2",
            payload,
        ),
        expected_content_digest=expected_content_digest,
        expected_content_length=expected_content_length,
        diagnostics=canonical_diagnostics,
    )


@dataclass(frozen=True)
class ResourceSourceSnapshot:
    source_generation_ref: ResourceSourceGenerationRef
    discovery_request_fingerprint: str
    candidate_summaries: tuple[ResourceCandidateSummary, ...]
    diagnostics: tuple[ResourceCatalogDiagnostic, ...]
    complete: bool
    snapshot_fingerprint: str

    def __post_init__(self) -> None:
        _require_digest(
            self.discovery_request_fingerprint,
            name="Resource discovery request fingerprint",
        )
        _require_digest(
            self.snapshot_fingerprint,
            name="Resource source snapshot fingerprint",
        )
        if any(
            candidate.source_generation_ref != self.source_generation_ref
            for candidate in self.candidate_summaries
        ):
            raise ValueError(
                "Every candidate must refer to the same source generation."
            )
        canonical_candidates = tuple(
            sorted(self.candidate_summaries, key=lambda item: item.canonical_sort_key())
        )
        if canonical_candidates != self.candidate_summaries:
            raise ValueError("Resource source candidates must be canonical.")
        candidate_keys = [
            (candidate.candidate_fingerprint, candidate.opaque_locator)
            for candidate in self.candidate_summaries
        ]
        if len(set(candidate_keys)) != len(candidate_keys):
            raise ValueError("Resource source snapshot contains a duplicate candidate.")
        if (
            tuple(sorted(self.diagnostics, key=lambda item: item.canonical_sort_key()))
            != self.diagnostics
        ):
            raise ValueError("Resource source diagnostics must be canonical.")
        expected = _source_snapshot_fingerprint(
            source_generation_ref=self.source_generation_ref,
            discovery_request_fingerprint=self.discovery_request_fingerprint,
            candidate_summaries=self.candidate_summaries,
            diagnostics=self.diagnostics,
            complete=self.complete,
        )
        if self.snapshot_fingerprint != expected:
            raise ValueError("Resource source snapshot fingerprint is invalid.")


def build_source_snapshot(
    *,
    source_generation_ref: ResourceSourceGenerationRef,
    discovery_request_fingerprint: str,
    candidate_summaries: tuple[ResourceCandidateSummary, ...]
    | list[ResourceCandidateSummary],
    diagnostics: tuple[ResourceCatalogDiagnostic, ...]
    | list[ResourceCatalogDiagnostic] = (),
    complete: bool = True,
) -> ResourceSourceSnapshot:
    candidates = tuple(
        sorted(candidate_summaries, key=lambda item: item.canonical_sort_key())
    )
    canonical_diagnostics = tuple(
        sorted(diagnostics, key=lambda item: item.canonical_sort_key())
    )
    snapshot_fingerprint = _source_snapshot_fingerprint(
        source_generation_ref=source_generation_ref,
        discovery_request_fingerprint=discovery_request_fingerprint,
        candidate_summaries=candidates,
        diagnostics=canonical_diagnostics,
        complete=complete,
    )
    return ResourceSourceSnapshot(
        source_generation_ref=source_generation_ref,
        discovery_request_fingerprint=discovery_request_fingerprint,
        candidate_summaries=candidates,
        diagnostics=canonical_diagnostics,
        complete=complete,
        snapshot_fingerprint=snapshot_fingerprint,
    )


@dataclass(frozen=True, order=True)
class ResourceKindMergePolicy:
    resource_kind: str
    strategy: ResourceMergeStrategy

    def __post_init__(self) -> None:
        _require_non_empty(self.resource_kind, name="Resource merge-policy kind")
        if self.strategy not in {
            "strict_exclusive",
            "permissive_exclusive",
            "ordered_additive",
        }:
            raise ValueError("Resource merge strategy is unsupported.")

    def to_payload(self) -> dict[str, object]:
        return {"resourceKind": self.resource_kind, "strategy": self.strategy}


@dataclass(frozen=True)
class ResourceMergePolicySnapshot:
    policy_revision: str
    kind_policies: tuple[ResourceKindMergePolicy, ...]
    merge_policy_fingerprint: str

    def __post_init__(self) -> None:
        _require_non_empty(self.policy_revision, name="Resource merge-policy revision")
        if tuple(sorted(self.kind_policies)) != self.kind_policies:
            raise ValueError("Resource kind merge policies must be canonical.")
        kinds = [policy.resource_kind for policy in self.kind_policies]
        if len(set(kinds)) != len(kinds):
            raise ValueError("Resource kind merge policies must be unique.")
        _require_digest(
            self.merge_policy_fingerprint,
            name="Resource merge-policy fingerprint",
        )
        expected = fingerprint_catalog_value(
            "loushang.resource-merge-policy/v2",
            {
                "kindPolicies": [policy.to_payload() for policy in self.kind_policies],
                "policyRevision": self.policy_revision,
            },
        )
        if self.merge_policy_fingerprint != expected:
            raise ValueError("Resource merge-policy fingerprint is invalid.")

    def strategy_for(self, resource_kind: str) -> ResourceMergeStrategy:
        for policy in self.kind_policies:
            if policy.resource_kind == resource_kind:
                return policy.strategy
        raise KeyError(resource_kind)


def build_merge_policy_snapshot(
    *,
    policy_revision: str,
    kind_policies: tuple[ResourceKindMergePolicy, ...] | list[ResourceKindMergePolicy],
) -> ResourceMergePolicySnapshot:
    policies = tuple(sorted(kind_policies))
    fingerprint = fingerprint_catalog_value(
        "loushang.resource-merge-policy/v2",
        {
            "kindPolicies": [policy.to_payload() for policy in policies],
            "policyRevision": policy_revision,
        },
    )
    return ResourceMergePolicySnapshot(
        policy_revision=policy_revision,
        kind_policies=policies,
        merge_policy_fingerprint=fingerprint,
    )


@dataclass(frozen=True)
class ResourceActivationPolicySnapshot:
    policy_revision: str
    disabled_identities: tuple[ResourceIdentity, ...]
    model_invocation_disabled_identities: tuple[ResourceIdentity, ...]
    activation_policy_fingerprint: str

    def __post_init__(self) -> None:
        _require_non_empty(
            self.policy_revision,
            name="Resource activation-policy revision",
        )
        for values, name in (
            (self.disabled_identities, "disabled Resource identities"),
            (
                self.model_invocation_disabled_identities,
                "model-invocation-disabled Resource identities",
            ),
        ):
            if tuple(sorted(values)) != values or len(set(values)) != len(values):
                raise ValueError(f"{name} must be canonical and unique.")
        _require_digest(
            self.activation_policy_fingerprint,
            name="Resource activation-policy fingerprint",
        )
        expected = _activation_policy_fingerprint(
            policy_revision=self.policy_revision,
            disabled_identities=self.disabled_identities,
            model_invocation_disabled_identities=(
                self.model_invocation_disabled_identities
            ),
        )
        if self.activation_policy_fingerprint != expected:
            raise ValueError("Resource activation-policy fingerprint is invalid.")


def build_activation_policy_snapshot(
    *,
    policy_revision: str,
    disabled_identities: tuple[ResourceIdentity, ...] | list[ResourceIdentity] = (),
    model_invocation_disabled_identities: tuple[ResourceIdentity, ...]
    | list[ResourceIdentity] = (),
) -> ResourceActivationPolicySnapshot:
    disabled = tuple(sorted(set(disabled_identities)))
    model_disabled = tuple(sorted(set(model_invocation_disabled_identities)))
    return ResourceActivationPolicySnapshot(
        policy_revision=policy_revision,
        disabled_identities=disabled,
        model_invocation_disabled_identities=model_disabled,
        activation_policy_fingerprint=_activation_policy_fingerprint(
            policy_revision=policy_revision,
            disabled_identities=disabled,
            model_invocation_disabled_identities=model_disabled,
        ),
    )


@dataclass(frozen=True)
class ResourceMergeDecision:
    identity: ResourceIdentity
    candidate_fingerprints: tuple[str, ...]
    effective_candidate_fingerprints: tuple[str, ...]
    winner_candidate_fingerprint: str | None
    rejected: bool
    policy_revision: str
    reason: str

    def __post_init__(self) -> None:
        if not self.candidate_fingerprints:
            raise ValueError("A Resource merge decision must name candidates.")
        for fingerprint in self.candidate_fingerprints:
            _require_digest(fingerprint, name="Merge-decision candidate fingerprint")
        if len(set(self.candidate_fingerprints)) != len(self.candidate_fingerprints):
            raise ValueError("Merge-decision candidates must be unique.")
        if any(
            fingerprint not in self.candidate_fingerprints
            for fingerprint in self.effective_candidate_fingerprints
        ):
            raise ValueError("Effective candidates must belong to the merge decision.")
        if (
            self.winner_candidate_fingerprint is not None
            and self.winner_candidate_fingerprint
            not in self.effective_candidate_fingerprints
        ):
            raise ValueError("Merge-decision winner must be effective.")
        if self.rejected and self.effective_candidate_fingerprints:
            raise ValueError(
                "A rejected merge decision cannot have effective candidates."
            )
        _require_non_empty(self.policy_revision, name="Merge-decision policy revision")
        _require_non_empty(self.reason, name="Merge-decision reason")

    def canonical_sort_key(self) -> tuple[object, ...]:
        return (*_identity_sort_key(self.identity), self.reason)

    def to_payload(self) -> dict[str, object]:
        return {
            "candidateFingerprints": list(self.candidate_fingerprints),
            "effectiveCandidateFingerprints": list(
                self.effective_candidate_fingerprints
            ),
            "identity": self.identity.to_payload(),
            "policyRevision": self.policy_revision,
            "reason": self.reason,
            "rejected": self.rejected,
            "winnerCandidateFingerprint": self.winner_candidate_fingerprint,
        }


@dataclass(frozen=True)
class ResourceEffectiveEntry:
    identity: ResourceIdentity
    candidate_fingerprints: tuple[str, ...]
    primary_candidate_fingerprint: str
    enabled: bool
    model_invocable: bool

    def __post_init__(self) -> None:
        if not self.candidate_fingerprints:
            raise ValueError("A Resource effective entry must name candidates.")
        for fingerprint in self.candidate_fingerprints:
            _require_digest(fingerprint, name="Effective candidate fingerprint")
        if self.primary_candidate_fingerprint not in self.candidate_fingerprints:
            raise ValueError("Primary candidate must belong to the effective entry.")
        if not self.enabled:
            raise ValueError("A disabled Resource cannot be an effective entry.")

    def canonical_sort_key(self) -> tuple[object, ...]:
        return _identity_sort_key(self.identity)

    def to_payload(self) -> dict[str, object]:
        return {
            "candidateFingerprints": list(self.candidate_fingerprints),
            "enabled": self.enabled,
            "identity": self.identity.to_payload(),
            "modelInvocable": self.model_invocable,
            "primaryCandidateFingerprint": self.primary_candidate_fingerprint,
        }


@dataclass(frozen=True)
class ResourceCatalogSnapshot:
    catalog_contract_version: int
    catalog_generation: int
    engine_binding_fingerprint: str
    source_generation_fingerprints: tuple[str, ...]
    merge_policy_revision: str
    activation_policy_fingerprint: str
    candidate_summaries: tuple[ResourceCandidateSummary, ...]
    effective_entries: tuple[ResourceEffectiveEntry, ...]
    merge_decisions: tuple[ResourceMergeDecision, ...]
    diagnostics: tuple[ResourceCatalogDiagnostic, ...]
    complete: bool
    snapshot_fingerprint: str

    def __post_init__(self) -> None:
        if self.catalog_contract_version != 2:
            raise ValueError("Resource Catalog contract version must be 2.")
        if self.catalog_generation < 1:
            raise ValueError("Resource Catalog generation must be positive.")
        _require_digest(
            self.engine_binding_fingerprint,
            name="Catalog engine binding fingerprint",
        )
        if (
            tuple(sorted(self.source_generation_fingerprints))
            != self.source_generation_fingerprints
        ):
            raise ValueError("Source generation fingerprints must be canonical.")
        if len(set(self.source_generation_fingerprints)) != len(
            self.source_generation_fingerprints
        ):
            raise ValueError("Source generation fingerprints must be unique.")
        for fingerprint in self.source_generation_fingerprints:
            _require_digest(fingerprint, name="Source generation fingerprint")
        _require_non_empty(
            self.merge_policy_revision,
            name="Resource merge-policy revision",
        )
        _require_digest(
            self.activation_policy_fingerprint,
            name="Resource activation-policy fingerprint",
        )
        if (
            tuple(
                sorted(
                    self.candidate_summaries, key=lambda item: item.canonical_sort_key()
                )
            )
            != self.candidate_summaries
        ):
            raise ValueError("Catalog candidates must be canonical.")
        candidate_fingerprints = [
            candidate.candidate_fingerprint for candidate in self.candidate_summaries
        ]
        if len(set(candidate_fingerprints)) != len(candidate_fingerprints):
            raise ValueError("Catalog candidates must be unique.")
        if (
            tuple(
                sorted(
                    self.effective_entries, key=lambda item: item.canonical_sort_key()
                )
            )
            != self.effective_entries
        ):
            raise ValueError("Catalog effective entries must be canonical.")
        if (
            tuple(
                sorted(self.merge_decisions, key=lambda item: item.canonical_sort_key())
            )
            != self.merge_decisions
        ):
            raise ValueError("Catalog merge decisions must be canonical.")
        _validate_catalog_accounting(
            candidates=self.candidate_summaries,
            effective_entries=self.effective_entries,
            merge_decisions=self.merge_decisions,
        )
        if (
            tuple(sorted(self.diagnostics, key=lambda item: item.canonical_sort_key()))
            != self.diagnostics
        ):
            raise ValueError("Catalog diagnostics must be canonical.")
        _require_digest(self.snapshot_fingerprint, name="Catalog snapshot fingerprint")
        expected = catalog_snapshot_fingerprint(
            catalog_contract_version=self.catalog_contract_version,
            catalog_generation=self.catalog_generation,
            engine_binding_fingerprint=self.engine_binding_fingerprint,
            source_generation_fingerprints=self.source_generation_fingerprints,
            merge_policy_revision=self.merge_policy_revision,
            activation_policy_fingerprint=self.activation_policy_fingerprint,
            candidate_summaries=self.candidate_summaries,
            effective_entries=self.effective_entries,
            merge_decisions=self.merge_decisions,
            diagnostics=self.diagnostics,
            complete=self.complete,
        )
        if self.snapshot_fingerprint != expected:
            raise ValueError("Resource Catalog snapshot fingerprint is invalid.")

    def candidate_by_fingerprint(self, fingerprint: str) -> ResourceCandidateSummary:
        for candidate in self.candidate_summaries:
            if candidate.candidate_fingerprint == fingerprint:
                return candidate
        raise KeyError(fingerprint)


def catalog_snapshot_fingerprint(
    *,
    catalog_contract_version: int,
    catalog_generation: int,
    engine_binding_fingerprint: str,
    source_generation_fingerprints: tuple[str, ...],
    merge_policy_revision: str,
    activation_policy_fingerprint: str,
    candidate_summaries: tuple[ResourceCandidateSummary, ...],
    effective_entries: tuple[ResourceEffectiveEntry, ...],
    merge_decisions: tuple[ResourceMergeDecision, ...],
    diagnostics: tuple[ResourceCatalogDiagnostic, ...],
    complete: bool,
) -> str:
    return fingerprint_catalog_value(
        "loushang.resource-catalog-snapshot/v2",
        {
            "activationPolicyFingerprint": activation_policy_fingerprint,
            "candidateSummaries": [item.to_payload() for item in candidate_summaries],
            "catalogContractVersion": catalog_contract_version,
            "catalogGeneration": catalog_generation,
            "complete": complete,
            "diagnostics": [item.to_payload() for item in diagnostics],
            "effectiveEntries": [item.to_payload() for item in effective_entries],
            "engineBindingFingerprint": engine_binding_fingerprint,
            "mergeDecisions": [item.to_payload() for item in merge_decisions],
            "mergePolicyRevision": merge_policy_revision,
            "sourceGenerationFingerprints": list(source_generation_fingerprints),
        },
    )


@dataclass(frozen=True)
class ResourceCatalogHandle:
    catalog_generation: int
    snapshot_fingerprint: str
    identity: ResourceIdentity
    candidate_fingerprint: str

    def __post_init__(self) -> None:
        if self.catalog_generation < 1:
            raise ValueError("Resource Catalog handle generation must be positive.")
        _require_digest(self.snapshot_fingerprint, name="Catalog handle fingerprint")
        _require_digest(self.candidate_fingerprint, name="Catalog handle candidate")


@dataclass(frozen=True)
class ResourceLoadHandle:
    catalog_generation: int
    snapshot_fingerprint: str
    identity: ResourceIdentity
    candidate_fingerprint: str
    source_generation_ref: ResourceSourceGenerationRef
    opaque_locator: str
    expected_content_digest: str
    expected_content_length: int
    schema_id: str
    schema_version: int
    media_type: str

    @classmethod
    def from_catalog(
        cls,
        *,
        catalog_handle: ResourceCatalogHandle,
        candidate: ResourceCandidateSummary,
    ) -> ResourceLoadHandle:
        if candidate.identity != catalog_handle.identity:
            raise ValueError("Catalog handle identity does not match the candidate.")
        if candidate.candidate_fingerprint != catalog_handle.candidate_fingerprint:
            raise ValueError("Catalog handle does not select the candidate.")
        if not candidate.has_body:
            raise ValueError("A no-body Resource cannot produce a load handle.")
        assert candidate.expected_content_digest is not None
        assert candidate.expected_content_length is not None
        return cls(
            catalog_generation=catalog_handle.catalog_generation,
            snapshot_fingerprint=catalog_handle.snapshot_fingerprint,
            identity=candidate.identity,
            candidate_fingerprint=candidate.candidate_fingerprint,
            source_generation_ref=candidate.source_generation_ref,
            opaque_locator=candidate.opaque_locator,
            expected_content_digest=candidate.expected_content_digest,
            expected_content_length=candidate.expected_content_length,
            schema_id=candidate.identity.schema_id,
            schema_version=candidate.identity.schema_version,
            media_type=candidate.media_type,
        )

    def __post_init__(self) -> None:
        if self.catalog_generation < 1:
            raise ValueError("Resource load handle generation must be positive.")
        _require_digest(self.snapshot_fingerprint, name="Load snapshot fingerprint")
        _require_digest(self.candidate_fingerprint, name="Load candidate fingerprint")
        _require_non_empty(self.opaque_locator, name="Load opaque locator")
        _require_digest(
            self.expected_content_digest,
            name="Load expected content digest",
        )
        if self.expected_content_length < 0:
            raise ValueError("Load expected content length cannot be negative.")
        if self.schema_id != self.identity.schema_id:
            raise ValueError("Load schema id must match the Resource identity.")
        if self.schema_version != self.identity.schema_version:
            raise ValueError("Load schema version must match the Resource identity.")
        if self.media_type == NO_BODY_MEDIA_TYPE:
            raise ValueError("A no-body Resource cannot produce a load handle.")


@dataclass(frozen=True)
class ResourceBodyRead:
    source_generation_ref: ResourceSourceGenerationRef
    opaque_locator: str
    body: bytes
    observed_content_digest: str
    observed_content_length: int

    def __post_init__(self) -> None:
        _require_non_empty(self.opaque_locator, name="Body-read opaque locator")
        _require_digest(
            self.observed_content_digest,
            name="Observed Resource content digest",
        )
        if self.observed_content_length < 0:
            raise ValueError("Observed Resource content length cannot be negative.")


@dataclass(frozen=True)
class ResourceLoadReceipt:
    catalog_generation: int
    snapshot_fingerprint: str
    candidate_fingerprint: str
    source_generation_ref: ResourceSourceGenerationRef
    schema_id: str
    schema_version: int
    media_type: str
    content_digest: str
    content_length: int

    @classmethod
    def from_validated_read(
        cls,
        *,
        load_handle: ResourceLoadHandle,
        body_read: ResourceBodyRead,
    ) -> ResourceLoadReceipt:
        if body_read.source_generation_ref != load_handle.source_generation_ref:
            raise ValueError("Body read came from a foreign source generation.")
        if body_read.opaque_locator != load_handle.opaque_locator:
            raise ValueError("Body read came from a foreign opaque locator.")
        actual_digest = hashlib.sha256(body_read.body).hexdigest()
        actual_length = len(body_read.body)
        if (
            body_read.observed_content_digest != actual_digest
            or body_read.observed_content_length != actual_length
            or actual_digest != load_handle.expected_content_digest
            or actual_length != load_handle.expected_content_length
        ):
            raise ValueError("Body read does not match the expected content identity.")
        return cls(
            catalog_generation=load_handle.catalog_generation,
            snapshot_fingerprint=load_handle.snapshot_fingerprint,
            candidate_fingerprint=load_handle.candidate_fingerprint,
            source_generation_ref=load_handle.source_generation_ref,
            schema_id=load_handle.schema_id,
            schema_version=load_handle.schema_version,
            media_type=load_handle.media_type,
            content_digest=actual_digest,
            content_length=actual_length,
        )

    def __post_init__(self) -> None:
        if self.catalog_generation < 1:
            raise ValueError("Resource load receipt generation must be positive.")
        _require_digest(self.snapshot_fingerprint, name="Load receipt snapshot")
        _require_digest(self.candidate_fingerprint, name="Load receipt candidate")
        _require_non_empty(self.schema_id, name="Load receipt schema id")
        if self.schema_version < 1:
            raise ValueError("Load receipt schema version must be positive.")
        _require_non_empty(self.media_type, name="Load receipt media type")
        _require_digest(self.content_digest, name="Load receipt content digest")
        if self.content_length < 0:
            raise ValueError("Load receipt content length cannot be negative.")


@dataclass(frozen=True)
class LoadedResource:
    receipt: ResourceLoadReceipt
    body: bytes

    def __post_init__(self) -> None:
        if len(self.body) != self.receipt.content_length:
            raise ValueError("Loaded Resource length does not match its receipt.")
        if hashlib.sha256(self.body).hexdigest() != self.receipt.content_digest:
            raise ValueError("Loaded Resource digest does not match its receipt.")


def _candidate_payload(
    *,
    identity: ResourceIdentity,
    canonical_name: str,
    description: str | None,
    media_type: str,
    invocation_policy: ResourceInvocationPolicy,
    source_generation_ref: ResourceSourceGenerationRef,
    source_class: ResourceSourceKind,
    scope_id: str,
    source_root_order: int,
    content_origin: ResourceContentOrigin,
    opaque_locator: str,
    discovery_fingerprint: str,
    expected_content_digest: str | None,
    expected_content_length: int | None,
    diagnostics: tuple[ResourceCatalogDiagnostic, ...],
) -> dict[str, object]:
    return {
        "canonicalName": canonical_name,
        "contentOrigin": content_origin.to_payload(),
        "description": description,
        "diagnostics": [diagnostic.to_payload() for diagnostic in diagnostics],
        "discoveryFingerprint": discovery_fingerprint,
        "expectedContentDigest": expected_content_digest,
        "expectedContentLength": expected_content_length,
        "identity": identity.to_payload(),
        "invocationPolicy": invocation_policy.to_payload(),
        "mediaType": media_type,
        "opaqueLocator": opaque_locator,
        "scopeId": scope_id,
        "sourceClass": source_class,
        "sourceGenerationRef": source_generation_ref.to_payload(),
        "sourceRootOrder": source_root_order,
    }


def _source_snapshot_fingerprint(
    *,
    source_generation_ref: ResourceSourceGenerationRef,
    discovery_request_fingerprint: str,
    candidate_summaries: tuple[ResourceCandidateSummary, ...],
    diagnostics: tuple[ResourceCatalogDiagnostic, ...],
    complete: bool,
) -> str:
    return fingerprint_catalog_value(
        "loushang.resource-source-snapshot/v2",
        {
            "candidateFingerprints": [
                candidate.candidate_fingerprint for candidate in candidate_summaries
            ],
            "complete": complete,
            "diagnostics": [diagnostic.to_payload() for diagnostic in diagnostics],
            "discoveryRequestFingerprint": discovery_request_fingerprint,
            "sourceGenerationRef": source_generation_ref.to_payload(),
        },
    )


def _activation_policy_fingerprint(
    *,
    policy_revision: str,
    disabled_identities: tuple[ResourceIdentity, ...],
    model_invocation_disabled_identities: tuple[ResourceIdentity, ...],
) -> str:
    return fingerprint_catalog_value(
        "loushang.resource-activation-policy/v2",
        {
            "disabledIdentities": [item.to_payload() for item in disabled_identities],
            "modelInvocationDisabledIdentities": [
                item.to_payload() for item in model_invocation_disabled_identities
            ],
            "policyRevision": policy_revision,
        },
    )


def _identity_sort_key(identity: ResourceIdentity) -> tuple[object, ...]:
    return (
        identity.resource_kind,
        identity.schema_id,
        identity.schema_version,
        identity.public_id,
    )


def _validate_content_origin(
    *,
    source_class: ResourceSourceKind,
    content_origin: ResourceContentOrigin,
) -> None:
    if isinstance(content_origin, ExtensionOutputOrigin):
        return
    allowed = (
        isinstance(content_origin, VerifiedPluginResourceOrigin)
        if source_class == "external_package"
        else isinstance(content_origin, EmbeddedOemOrigin)
        if source_class == "built_in"
        else isinstance(content_origin, NativeHostOrigin)
    )
    if not allowed:
        raise ValueError("Resource content origin does not match its source class.")


def _require_opaque_locator(value: str) -> None:
    normalized = value.replace("\\", "/")
    if (
        "\0" in value
        or normalized.startswith("/")
        or re.match(r"^[A-Za-z]:/", normalized)
        or ".." in normalized.split("/")
    ):
        raise ValueError("Resource opaque locator must not contain a host path escape.")


def _validate_catalog_accounting(
    *,
    candidates: tuple[ResourceCandidateSummary, ...],
    effective_entries: tuple[ResourceEffectiveEntry, ...],
    merge_decisions: tuple[ResourceMergeDecision, ...],
) -> None:
    candidates_by_identity: dict[ResourceIdentity, set[str]] = {}
    for candidate in candidates:
        candidates_by_identity.setdefault(candidate.identity, set()).add(
            candidate.candidate_fingerprint
        )
    decisions_by_identity = {
        decision.identity: decision for decision in merge_decisions
    }
    if len(decisions_by_identity) != len(merge_decisions):
        raise ValueError("Catalog merge decisions must have unique identities.")
    if set(decisions_by_identity) != set(candidates_by_identity):
        raise ValueError(
            "Catalog merge decisions must account for every candidate identity."
        )
    for identity, candidate_values in candidates_by_identity.items():
        if (
            set(decisions_by_identity[identity].candidate_fingerprints)
            != candidate_values
        ):
            raise ValueError(
                "Catalog merge decision has foreign or omitted candidates."
            )

    entries_by_identity = {entry.identity: entry for entry in effective_entries}
    if len(entries_by_identity) != len(effective_entries):
        raise ValueError("Catalog effective entries must have unique identities.")
    for identity, decision in decisions_by_identity.items():
        entry = entries_by_identity.get(identity)
        if not decision.effective_candidate_fingerprints:
            if entry is not None:
                raise ValueError(
                    "Catalog published an entry without an effective decision."
                )
            continue
        if entry is None:
            raise ValueError("Catalog omitted an effective merge decision.")
        if entry.candidate_fingerprints != decision.effective_candidate_fingerprints:
            raise ValueError("Catalog entry does not match its merge decision.")
        if entry.primary_candidate_fingerprint != decision.winner_candidate_fingerprint:
            raise ValueError(
                "Catalog entry primary candidate does not match its decision."
            )


def _require_non_empty(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string.")


def _require_digest(value: str, *, name: str) -> None:
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise ValueError(f"{name} must be a SHA-256 digest.")


__all__ = [
    "EmbeddedOemOrigin",
    "ExtensionOutputOrigin",
    "ExtensionOwnerProducer",
    "LoadedResource",
    "NO_BODY_MEDIA_TYPE",
    "NativeHostOrigin",
    "ResourceActivationPolicySnapshot",
    "ResourceBodyRead",
    "ResourceCandidateSummary",
    "ResourceCatalogDiagnostic",
    "ResourceCatalogHandle",
    "ResourceCatalogSnapshot",
    "ResourceComponentProducer",
    "ResourceContentOrigin",
    "ResourceEffectiveEntry",
    "ResourceIdentity",
    "ResourceInvocationPolicy",
    "ResourceKindMergePolicy",
    "ResourceLoadHandle",
    "ResourceLoadReceipt",
    "ResourceMergeDecision",
    "ResourceMergePolicySnapshot",
    "ResourceMergeStrategy",
    "ResourceSourceGenerationRef",
    "ResourceSourceSnapshot",
    "VerifiedPluginResourceOrigin",
    "build_activation_policy_snapshot",
    "build_candidate_summary",
    "build_merge_policy_snapshot",
    "build_source_snapshot",
    "catalog_snapshot_fingerprint",
    "fingerprint_catalog_value",
]
