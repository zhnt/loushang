"""Product-owned ingress and classification for explicitly pinned local Wheels.

Unknown Sources remain indeterminate. This policy has no non-Plugin authority
and never grants a materializer fallback from an unrecognized input.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

from loushang.harness.resources.packages.plugin_lifecycle.local_source import (
    PackagePinnedLocalWheelSourceAuthority,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageClassificationBasisFactV1,
    PackageClassificationBasisKind,
    PackageClassificationFactsV1,
    PackageLifecycleIngressRequestV1,
    PackageLifecycleRequestV1,
    PluginBoundPackageClassificationV1,
    canonical_json_bytes,
    canonicalize_source_identity,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1,
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_LOCAL_WHEEL_ACTIONS = frozenset({"materialize", "install", "update"})
_FACT_KINDS: tuple[PackageClassificationBasisKind, ...] = (
    "explicit_plugin_intent",
    "existing_plugin_binding",
    "existing_plugin_history",
    "independent_non_plugin_authority",
)


@dataclass(frozen=True, slots=True)
class PackageProductLocalWheelBindingV1:
    """One Product-reviewed Source, requested Package, and Plugin identity."""

    source_identity: str
    requested_package: str
    plugin_id: str
    artifact_digest: str

    def __post_init__(self) -> None:
        source = self.source_identity
        if (
            not isinstance(source, str)
            or canonicalize_source_identity(source) != source
            or not Path(source).is_absolute()
            or Path(source).suffix != ".whl"
        ):
            raise ValueError("Product local Wheel Source must be canonical")
        if (
            not isinstance(self.requested_package, str)
            or not self.requested_package
            or len(self.requested_package) > 256
            or any(char in self.requested_package for char in ("/", "\\", "@", "?", "#"))
        ):
            raise ValueError("Product requested Package identity is invalid")
        if not isinstance(self.plugin_id, str) or _SAFE_ID.fullmatch(self.plugin_id) is None:
            raise ValueError("Product Plugin identity is invalid")
        if (
            not isinstance(self.artifact_digest, str)
            or _SHA256.fullmatch(self.artifact_digest) is None
        ):
            raise ValueError("Product local Wheel digest is invalid")


@dataclass(frozen=True, slots=True)
class PackageProductLocalWheelPolicy:
    """One immutable Product authority for ingress, facts, recheck, and Source."""

    product_id: str
    project_scope_id: str
    source_root: Path
    bindings: tuple[PackageProductLocalWheelBindingV1, ...]
    policy_revision: str
    quota_profile_revision: str
    resolution_environment_fingerprint: str
    authority_id: str
    classifier_epoch: int = 1

    def __post_init__(self) -> None:
        for value, name in (
            (self.product_id, "Product identity"),
            (self.project_scope_id, "Product project scope"),
            (self.policy_revision, "Product policy revision"),
            (self.quota_profile_revision, "Product quota revision"),
            (self.authority_id, "Product classification authority"),
        ):
            if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
                raise ValueError(f"{name} is invalid")
        if (
            not isinstance(self.source_root, Path)
            or not self.source_root.is_absolute()
            or ".." in self.source_root.parts
        ):
            raise ValueError("Product local Wheel Source root is invalid")
        if (
            type(self.bindings) is not tuple
            or len(self.bindings) > 128
            or any(
                not isinstance(binding, PackageProductLocalWheelBindingV1)
                for binding in self.bindings
            )
        ):
            raise ValueError("Product local Wheel bindings are invalid")
        identities = tuple(binding.source_identity for binding in self.bindings)
        if identities != tuple(sorted(set(identities))):
            raise ValueError("Product local Wheel bindings must be uniquely ordered")
        if (
            not isinstance(self.resolution_environment_fingerprint, str)
            or _SHA256.fullmatch(self.resolution_environment_fingerprint) is None
        ):
            raise ValueError("Product resolution environment identity is invalid")
        if type(self.classifier_epoch) is not int or self.classifier_epoch < 1:
            raise ValueError("Product classifier epoch is invalid")
        # Source Authority validates that every exact path is below the root.
        self.source_authority()

    @property
    def authority_revision(self) -> str:
        values = {
            "authorityId": self.authority_id,
            "bindings": [
                {
                    "artifactDigest": item.artifact_digest,
                    "pluginId": item.plugin_id,
                    "requestedPackage": item.requested_package,
                    "sourceIdentity": item.source_identity,
                }
                for item in self.bindings
            ],
            "classifierEpoch": self.classifier_epoch,
            "policyRevision": self.policy_revision,
            "productId": self.product_id,
            "projectScopeId": self.project_scope_id,
            "sourceRoot": str(self.source_root),
        }
        return sha256(canonical_json_bytes(values)).hexdigest()

    def source_authority(self) -> PackagePinnedLocalWheelSourceAuthority:
        """Issue the same exact digest allowlist used by Product classification."""

        return PackagePinnedLocalWheelSourceAuthority(
            source_root=self.source_root,
            allowed_digests={
                item.source_identity: item.artifact_digest for item in self.bindings
            },
            policy_revision=self.policy_revision,
            authority_id=self.authority_id,
            capture_epoch=self.classifier_epoch,
        )

    def scope_id(self, intent: PackageProductLifecycleIntentV1) -> str:
        if not isinstance(intent, PackageProductLifecycleIntentV1):
            raise TypeError("Package Product intent is required")
        if intent.scope == "project":
            return self.project_scope_id
        return f"unsupported:{intent.scope}:{self.project_scope_id}"

    def create(
        self, intent: PackageProductLifecycleIntentV1
    ) -> PackageLifecycleIngressRequestV1:
        if not isinstance(intent, PackageProductLifecycleIntentV1):
            raise TypeError("Package Product intent is required")
        binding = self._binding(intent.source) if intent.scope == "project" else None
        return PackageLifecycleIngressRequestV1(
            operation_id=intent.operation_id,
            action=intent.action,
            product_id=self.product_id,
            scope_id=self.scope_id(intent),
            requested_package=(
                "unclassified-wheel" if binding is None else binding.requested_package
            ),
            requested_plugin_id=None if binding is None else binding.plugin_id,
            source_locator=intent.source,
            policy_revision=self.policy_revision,
            quota_profile_revision=self.quota_profile_revision,
            resolution_environment_fingerprint=(
                self.resolution_environment_fingerprint
            ),
        )

    def classification_facts(
        self, request: PackageLifecycleIngressRequestV1
    ) -> PackageClassificationFactsV1:
        if not isinstance(request, PackageLifecycleIngressRequestV1):
            raise TypeError("Package ingress request is required")
        binding = self._binding(request.source_locator)
        explicit = bool(
            binding is not None
            and request.action in _LOCAL_WHEEL_ACTIONS
            and request.product_id == self.product_id
            and request.scope_id == self.project_scope_id
            and request.requested_package == binding.requested_package
            and request.requested_plugin_id == binding.plugin_id
            and request.policy_revision == self.policy_revision
            and request.quota_profile_revision == self.quota_profile_revision
            and request.resolution_environment_fingerprint
            == self.resolution_environment_fingerprint
        )
        return PackageClassificationFactsV1(
            facts=tuple(
                PackageClassificationBasisFactV1(
                    kind=kind,
                    present=kind == "explicit_plugin_intent" and explicit,
                    authority_id=f"{self.authority_id}:{kind}",
                    owner_revision=self.authority_revision,
                )
                for kind in _FACT_KINDS
            ),
            policy_revision=self.policy_revision,
            classifier_epoch=self.classifier_epoch,
        )

    def recheck(
        self,
        request: PackageLifecycleRequestV1,
        prior: PluginBoundPackageClassificationV1,
    ) -> PluginBoundPackageClassificationV1:
        if not isinstance(request, PackageLifecycleRequestV1) or not isinstance(
            prior, PluginBoundPackageClassificationV1
        ):
            raise TypeError("Package classification recheck requires exact evidence")
        if request.request_fingerprint != prior.request_fingerprint:
            raise ValueError("Package classification request changed")
        facts = self.classification_facts(
            PackageLifecycleIngressRequestV1(
                operation_id=request.operation_id,
                action=request.action,
                product_id=request.product_id,
                scope_id=request.scope_id,
                requested_package=request.requested_package,
                requested_plugin_id=request.requested_plugin_id,
                source_locator=request.canonical_source_identity,
                policy_revision=request.policy_revision,
                quota_profile_revision=request.quota_profile_revision,
                resolution_environment_fingerprint=(
                    request.resolution_environment_fingerprint
                ),
            )
        )
        return PluginBoundPackageClassificationV1(
            decision=(
                "plugin_bound"
                if prior.decision == "plugin_bound" and facts.facts[0].present
                else "indeterminate"
            ),
            request_fingerprint=prior.request_fingerprint,
            basis_facts=facts,
            policy_revision=facts.policy_revision,
            classifier_epoch=facts.classifier_epoch,
            canonical_source_identity=request.canonical_source_identity,
        )

    def _binding(self, source: str) -> PackageProductLocalWheelBindingV1 | None:
        # An alias with a query, fragment, or URL spelling is not an authorized
        # local path even if canonicalization would erase the extra bytes.
        return next(
            (item for item in self.bindings if item.source_identity == source),
            None,
        )


__all__ = [
    "PackageProductLocalWheelBindingV1",
    "PackageProductLocalWheelPolicy",
]
