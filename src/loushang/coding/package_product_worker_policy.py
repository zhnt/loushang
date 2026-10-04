"""Default-dark Product policy derivation from one selected Worker Wheel.

This module returns an authority-free Worker policy. It cannot issue an
activation receipt, reserve a native profile, or publish a Capability owner.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from loushang.harness.package_product.product_local_wheel_runtime import (
    PackageProductSelectedPluginManifestV1,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeBindingV1,
)
from loushang.harness.package_product.product_worker_candidate import (
    verify_product_selected_worker_candidate,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWheelPolicy,
)
from loushang.harness.transcript.discovery import SessionDiscoveryMetadata
from loushang.harness.worker.product_activation import ProductWorkerActivationPolicyV1

from ._product_worker_canary import (
    CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID,
    CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID,
    coding_product_worker_session_fingerprint,
)

_IDENTIFIER = re.compile(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?\Z")
_OPAQUE = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._:@+-]*[A-Za-z0-9])?\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_MAX_TEXT = 128
_NATIVE_PROFILES = {
    "linux-x86_64": CODING_PRODUCT_WORKER_NATIVE_PROFILE_ID,
    "windows-amd64": CODING_PRODUCT_WORKER_WINDOWS_NATIVE_PROFILE_ID,
}


class CodingWorkerPolicySelectionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CodingWorkerNativeClosureReadError(RuntimeError):
    """The Product-bound native closure is unavailable or changed."""


@dataclass(frozen=True, slots=True)
class CodingWorkerOptInV1:
    """An exact per-install decision input; this record grants no authority."""

    plugin_id: str
    contribution_id: str
    owner_id: str
    artifact_digest: str
    native_platform: str
    owner_selection_generation: int
    kill_switch_generation: int
    require_worker: bool

    def __post_init__(self) -> None:
        for value in (self.plugin_id, self.contribution_id, self.owner_id):
            if (
                not isinstance(value, str)
                or len(value) > _MAX_TEXT
                or _IDENTIFIER.fullmatch(value) is None
            ):
                raise ValueError("Coding Worker opt-in identity is invalid")
        if (
            not isinstance(self.artifact_digest, str)
            or _DIGEST.fullmatch(self.artifact_digest) is None
        ):
            raise ValueError("Coding Worker opt-in digest is invalid")
        if (
            not isinstance(self.native_platform, str)
            or self.native_platform not in _NATIVE_PROFILES
        ):
            raise ValueError("Coding Worker opt-in platform is unsupported")
        if (
            type(self.owner_selection_generation) is not int
            or self.owner_selection_generation < 1
            or type(self.kill_switch_generation) is not int
            or self.kill_switch_generation < 0
            or type(self.require_worker) is not bool
        ):
            raise ValueError(
                "Coding Worker opt-in generation or requiredness is invalid"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "artifactDigest": self.artifact_digest,
            "contributionId": self.contribution_id,
            "killSwitchGeneration": self.kill_switch_generation,
            "nativePlatform": self.native_platform,
            "ownerId": self.owner_id,
            "ownerSelectionGeneration": self.owner_selection_generation,
            "pluginId": self.plugin_id,
            "requireWorker": self.require_worker,
        }

    @classmethod
    def from_dict(cls, value: object) -> CodingWorkerOptInV1:
        fields = {
            "artifactDigest",
            "contributionId",
            "killSwitchGeneration",
            "nativePlatform",
            "ownerId",
            "ownerSelectionGeneration",
            "pluginId",
            "requireWorker",
        }
        if type(value) is not dict or set(value) != fields:
            raise ValueError("Coding Worker opt-in record is invalid")
        return cls(
            plugin_id=value["pluginId"],
            contribution_id=value["contributionId"],
            owner_id=value["ownerId"],
            artifact_digest=value["artifactDigest"],
            native_platform=value["nativePlatform"],
            owner_selection_generation=value["ownerSelectionGeneration"],
            kill_switch_generation=value["killSwitchGeneration"],
            require_worker=value["requireWorker"],
        )


@dataclass(frozen=True, slots=True)
class CodingWorkerNativeClosureV1:
    """Authority-free native facts supplied by a separate Product owner."""

    native_platform: str
    native_profile_catalog_revision: str
    containment_launcher_digest: str
    containment_profile_digest: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.native_platform, str)
            or self.native_platform not in _NATIVE_PROFILES
            or not isinstance(self.native_profile_catalog_revision, str)
            or len(self.native_profile_catalog_revision) > _MAX_TEXT
            or _OPAQUE.fullmatch(self.native_profile_catalog_revision) is None
        ):
            raise ValueError("Coding Worker native closure identity is invalid")
        for value in (
            self.containment_launcher_digest,
            self.containment_profile_digest,
        ):
            if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
                raise ValueError("Coding Worker native closure digest is invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "nativePlatform": self.native_platform,
            "nativeProfileCatalogRevision": self.native_profile_catalog_revision,
            "containmentLauncherDigest": self.containment_launcher_digest,
            "containmentProfileDigest": self.containment_profile_digest,
        }


def coding_worker_session_scope_id(session_id: str) -> str:
    """Derive the exact Worker scope carried by a Product Session receipt."""

    if not isinstance(session_id, str) or not session_id:
        raise ValueError("Coding Worker Session identity is invalid")
    return (
        "session."
        + sha256(
            b"loushang.coding-worker-session-scope/v1\0" + session_id.encode("utf-8")
        ).hexdigest()
    )


def derive_coding_selected_worker_policy(
    *,
    runtime: PackageProductRuntimeBindingV1,
    product_policy: PackageProductLocalWheelPolicy,
    selected: PackageProductSelectedPluginManifestV1,
    session_id: str,
    product_runtime_id: str,
    opt_in: CodingWorkerOptInV1 | None,
    native_closure: CodingWorkerNativeClosureV1 | None = None,
    session_discovery: SessionDiscoveryMetadata | None = None,
) -> ProductWorkerActivationPolicyV1 | None:
    """Recheck Product selection and derive one explicit, authority-free policy."""

    if opt_in is None:
        return None
    if (
        not isinstance(runtime, PackageProductRuntimeBindingV1)
        or not isinstance(product_policy, PackageProductLocalWheelPolicy)
        or not isinstance(selected, PackageProductSelectedPluginManifestV1)
        or not isinstance(opt_in, CodingWorkerOptInV1)
        or not isinstance(native_closure, CodingWorkerNativeClosureV1)
        or opt_in.native_platform != native_closure.native_platform
        or runtime.product_id != "coding"
        or runtime.session_id != session_id
        or runtime.product_runtime_id != product_runtime_id
        or product_policy.product_id != "coding"
        or selected.snapshot.installation_key.product_id != "coding"
        or selected.snapshot.installation_key.scope_id
        != product_policy.project_scope_id
        or selected.snapshot.installation_key.plugin_id != opt_in.plugin_id
        or selected.snapshot.root_ref.artifact_digest != opt_in.artifact_digest
        or not isinstance(session_id, str)
        or not session_id
        or not isinstance(product_runtime_id, str)
        or not product_runtime_id
    ):
        raise CodingWorkerPolicySelectionError(
            "coding_worker_product_selection_invalid"
        )
    trust = selected.source_trust_snapshot
    if selected.snapshot.committed_record.closure_lock.node_count != 1:
        raise CodingWorkerPolicySelectionError(
            "coding_worker_dependency_activation_unsupported"
        )
    if (
        trust is None
        or not trust.trusted
        or trust.source_trust_class != "local-worker-candidate"
        or trust.source_trust_policy_revision != product_policy.authority_revision
    ):
        raise CodingWorkerPolicySelectionError("coding_worker_product_trust_changed")
    bindings = tuple(
        binding
        for binding in product_policy.bindings
        if binding.plugin_id == opt_in.plugin_id
        and binding.source_identity
        == selected.snapshot.package_revision.package_source_identity
        and binding.artifact_digest == opt_in.artifact_digest
        and binding.source_trust_class == "local-worker-candidate"
    )
    if len(bindings) != 1:
        raise CodingWorkerPolicySelectionError("coding_worker_product_binding_changed")
    admitted = bindings[0].worker_admission
    if (
        admitted is None
        or admitted.contribution_id != opt_in.contribution_id
        or admitted.owner_id != opt_in.owner_id
        or admitted.native_platform != opt_in.native_platform
    ):
        raise CodingWorkerPolicySelectionError("coding_worker_product_binding_changed")
    candidate = verify_product_selected_worker_candidate(
        selected,
        contribution_id=opt_in.contribution_id,
        native_platform=admitted.native_platform,
    )
    if candidate.owner_id != opt_in.owner_id:
        raise CodingWorkerPolicySelectionError("coding_worker_product_binding_changed")
    session_route: Literal["new", "selected"]
    if session_discovery is None:
        session_route = "new"
        locator_fingerprint = None
        locator_revision = "new-session-v1"
    else:
        if (
            not isinstance(session_discovery, SessionDiscoveryMetadata)
            or not session_discovery.resumable
            or session_discovery.conflicts
            or session_discovery.locator.conversation_id != session_id
        ):
            raise CodingWorkerPolicySelectionError("coding_worker_session_invalid")
        session_route = "selected"
        locator_fingerprint = coding_product_worker_session_fingerprint(
            session_discovery
        )
        locator_revision = session_discovery.locator.revision
    runtime.assert_selected_plugin_manifest_current(selected)
    native_profile_id = _NATIVE_PROFILES[opt_in.native_platform]
    closure = ProductWorkerActivationPolicyV1.native_policy_closure_fingerprint(
        native_profile_catalog_revision=native_closure.native_profile_catalog_revision,
        native_profile_id=native_profile_id,
        payload_sha256=candidate.executable_digest,
        containment_launcher_sha256=native_closure.containment_launcher_digest,
        containment_profile_sha256=native_closure.containment_profile_digest,
    )
    policy_revision = sha256(
        canonical_json_bytes(
            {
                "packagePolicy": product_policy.authority_revision,
                "optIn": opt_in.to_dict(),
                "nativeClosure": native_closure.to_dict(),
            }
        )
    ).hexdigest()
    return ProductWorkerActivationPolicyV1(
        product_id="coding",
        product_runtime_id=product_runtime_id,
        product_scope_id=coding_worker_session_scope_id(session_id),
        session_id=session_id,
        session_route=session_route,
        selected_locator_fingerprint=locator_fingerprint,
        selected_locator_revision=locator_revision,
        plugin_id=candidate.plugin_id,
        plugin_revision_digest=selected.snapshot.root_ref.artifact_digest,
        contribution_id=candidate.contribution_id,
        reservation_fingerprint=candidate.reservation_fingerprint,
        declaration_fingerprint=candidate.declaration_fingerprint,
        worker_configuration_fingerprint=candidate.worker_configuration_fingerprint,
        declared_required=candidate.declared_required,
        effective_required=candidate.declared_required or opt_in.require_worker,
        enabled=True,
        allowed_product_ids=("coding",),
        allowed_contribution_ids=(candidate.contribution_id,),
        requested_owner="hosting",
        owner_selection_generation=opt_in.owner_selection_generation,
        no_fallback=True,
        native_profile_id=native_profile_id,
        native_profile_catalog_revision=native_closure.native_profile_catalog_revision,
        allowed_native_profile_ids=(native_profile_id,),
        expected_native_policy_closure_fingerprint=closure,
        product_policy_revision=policy_revision,
        kill_switch_generation=opt_in.kill_switch_generation,
    )


__all__ = [
    "CodingWorkerOptInV1",
    "CodingWorkerNativeClosureV1",
    "CodingWorkerPolicySelectionError",
    "coding_worker_session_scope_id",
    "derive_coding_selected_worker_policy",
]
