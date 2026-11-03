"""Capability-owner facet policy for a selected read-only Worker attempt.

This owner policy grants calls, not Provider graph publication. The existing
in-process Provider binding spec cannot represent a local Worker.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from types import MappingProxyType

from loushang.harness.capabilities.contracts import CapabilityDefinition
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerAuthority,
    CapabilityProviderOwnerSnapshot,
)

from .capability_query import (
    CapabilityWorkerAuthorityV1,
    CapabilityWorkerBindingV1,
    CapabilityWorkerFacetGrantV1,
)


class CapabilityWorkerFacetOwnerError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CapabilityWorkerFacetOwnerPolicy:
    """Bind exact owner facets and decoders to one Worker authority generation."""

    def __init__(
        self,
        *,
        definition: CapabilityDefinition,
        provider_owner: CapabilityProviderOwnerAuthority,
        binding: CapabilityWorkerBindingV1,
        facet_decoders: Mapping[str, Callable[[object], object]],
        current_owner_snapshot: Callable[[], CapabilityProviderOwnerSnapshot],
    ) -> None:
        if (
            not isinstance(definition, CapabilityDefinition)
            or not isinstance(provider_owner, CapabilityProviderOwnerAuthority)
            or not isinstance(binding, CapabilityWorkerBindingV1)
            or not isinstance(facet_decoders, Mapping)
            or not callable(current_owner_snapshot)
        ):
            raise TypeError("Capability Worker facet owner inputs are invalid")
        policy = provider_owner.policy
        if (
            definition.capability_id != policy.capability_id
            or definition.owner_id != policy.owner_id
            or binding.owner_id != definition.owner_id
            or binding.allowed_capability_ids != (definition.capability_id,)
            or binding.authority.owner_policy_revision != policy.policy_revision
            or binding.authority.revocation_epoch != policy.revocation_epoch
            or "local-worker-candidate" not in policy.allowed_source_trust_classes
            or definition.scope != "session"
            or definition.refresh_boundary != "sealed"
            or definition.phase != "final"
            or definition.authority_ceiling
            or policy.authority_ceiling
        ):
            raise CapabilityWorkerFacetOwnerError("worker_facet_owner_policy_mismatch")
        decoders = dict(facet_decoders)
        if set(decoders) != set(definition.facets) or any(
            not callable(decoder) for decoder in decoders.values()
        ):
            raise CapabilityWorkerFacetOwnerError(
                "worker_facet_owner_decoder_policy_invalid"
            )
        snapshot = provider_owner.snapshot()
        if current_owner_snapshot() != snapshot:
            raise CapabilityWorkerFacetOwnerError("worker_facet_owner_stale")
        self._definition = definition
        self._binding = binding
        self._current_owner_snapshot = current_owner_snapshot
        self._decoders = MappingProxyType(decoders)

    @property
    def binding(self) -> CapabilityWorkerBindingV1:
        return self._binding

    def current_authority(self) -> CapabilityWorkerAuthorityV1:
        try:
            snapshot = self._current_owner_snapshot()
        except Exception as exc:
            raise CapabilityWorkerFacetOwnerError(
                "worker_facet_owner_unavailable"
            ) from exc
        if (
            not isinstance(snapshot, CapabilityProviderOwnerSnapshot)
            or snapshot.capability_id != self._definition.capability_id
            or snapshot.owner_id != self._definition.owner_id
        ):
            raise CapabilityWorkerFacetOwnerError("worker_facet_owner_unavailable")
        return replace(
            self._binding.authority,
            owner_policy_revision=snapshot.policy_revision,
            revocation_epoch=snapshot.revocation_epoch,
        )

    def issue_read_only_facet(
        self, *, capability_id: str, facet_id: str
    ) -> tuple[CapabilityWorkerFacetGrantV1, Callable[[object], object]]:
        if capability_id != self._definition.capability_id:
            raise CapabilityWorkerFacetOwnerError(
                "worker_facet_owner_capability_unapproved"
            )
        decoder = self._decoders.get(facet_id)
        if decoder is None:
            raise CapabilityWorkerFacetOwnerError("worker_facet_owner_facet_unapproved")
        current = self.current_authority()
        if current != self._binding.authority:
            raise CapabilityWorkerFacetOwnerError("worker_facet_owner_stale")
        return (
            CapabilityWorkerFacetGrantV1(
                capability_id=capability_id,
                facet_id=facet_id,
                binding_fingerprint=self._binding.fingerprint,
                authority_fingerprint=current.fingerprint,
                owner_policy_revision=current.owner_policy_revision,
            ),
            decoder,
        )


__all__ = ["CapabilityWorkerFacetOwnerError", "CapabilityWorkerFacetOwnerPolicy"]
