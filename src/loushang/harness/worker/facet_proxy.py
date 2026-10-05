"""Staged, attempt-bound read-only Worker facet for a future Provider graph."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Literal

from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleVisibilityError,
    CapabilityBundleVisibilityGate,
)

from .capability_query import (
    CapabilityQueryWorkerAdapter,
    CapabilityWorkerAdmissionV1,
    CapabilityWorkerFacetGrantV1,
)

FacetProxyState = Literal["staged", "visible", "retired"]


class CapabilityWorkerFacetProxyError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class CapabilityWorkerReadOnlyFacetProxy:
    """Hide a Worker facet until an owner commits its exact graph generation."""

    def __init__(
        self,
        *,
        adapter: CapabilityQueryWorkerAdapter,
        admission: CapabilityWorkerAdmissionV1,
        capability_id: str,
        facet_id: str,
        owner_generation: int,
        graph_generation: int,
        issue_grant: Callable[
            [], tuple[CapabilityWorkerFacetGrantV1, Callable[[object], object]]
        ],
    ) -> None:
        if (
            not isinstance(adapter, CapabilityQueryWorkerAdapter)
            or not isinstance(admission, CapabilityWorkerAdmissionV1)
            or not isinstance(capability_id, str)
            or not capability_id
            or not isinstance(facet_id, str)
            or not facet_id
            or type(owner_generation) is not int
            or owner_generation < 1
            or type(graph_generation) is not int
            or graph_generation < 1
            or not callable(issue_grant)
        ):
            raise TypeError("Capability Worker facet proxy inputs are invalid")
        descriptors = adapter.descriptors
        if (
            adapter.admission != admission
            or adapter.binding.authority.owner_generation != owner_generation
            or capability_id not in adapter.binding.allowed_capability_ids
            or descriptors is None
            or not any(
                item.capability_id == capability_id and facet_id in item.facet_ids
                for item in descriptors
            )
        ):
            raise CapabilityWorkerFacetProxyError(
                "worker_capability_facet_proxy_admission_mismatch"
            )
        self._adapter = adapter
        self._admission = admission
        self._capability_id = capability_id
        self._facet_id = facet_id
        self._owner_generation = owner_generation
        self._graph_generation = graph_generation
        self._issue_grant = issue_grant
        self._visibility_gate = CapabilityBundleVisibilityGate(
            graph_generation=graph_generation,
            validate_current=self._validate_publication,
        )

    @property
    def state(self) -> FacetProxyState:
        return self._visibility_gate.state

    @property
    def visibility_gate(self) -> CapabilityBundleVisibilityGate:
        """Give the graph Binder the exact gate for this attempt-bound facet."""

        return self._visibility_gate

    def publish(
        self, *, admission: CapabilityWorkerAdmissionV1, owner_generation: int
    ) -> None:
        """Commit visibility synchronously after Product graph staging succeeds."""

        if (
            admission != self._admission
            or self._adapter.admission != admission
            or owner_generation != self._owner_generation
        ):
            raise CapabilityWorkerFacetProxyError(
                "worker_capability_facet_proxy_publish_stale"
            )
        try:
            self._visibility_gate.publish(graph_generation=self._graph_generation)
        except CapabilityBundleVisibilityError as exc:
            raise CapabilityWorkerFacetProxyError(
                "worker_capability_facet_proxy_publish_stale"
            ) from exc

    def retire(self) -> None:
        """Revoke visibility before Worker attempt drain or graph retirement."""

        self._visibility_gate.retire()

    async def invoke(self, request: Mapping[str, object]) -> object:
        if self._visibility_gate.state != "visible":
            raise CapabilityWorkerFacetProxyError(
                "worker_capability_facet_proxy_not_visible"
            )
        try:
            grant, decoder = self._current_grant()
        except Exception as exc:
            await self._adapter.fence(code="worker_capability_facet_owner_unavailable")
            raise CapabilityWorkerFacetProxyError(
                "worker_capability_facet_proxy_owner_unavailable"
            ) from exc
        result = await self._adapter.invoke_read_only_facet(
            grant=grant, request=request, decode_result=decoder
        )
        if self._visibility_gate.state != "visible":
            raise CapabilityWorkerFacetProxyError(
                "worker_capability_facet_proxy_retired_during_call"
            )
        return result

    def _validate_publication(self) -> None:
        self._adapter.assert_admitted_current(self._admission)
        self._current_grant()

    def _current_grant(
        self,
    ) -> tuple[CapabilityWorkerFacetGrantV1, Callable[[object], object]]:
        grant, decoder = self._issue_grant()
        if (
            not isinstance(grant, CapabilityWorkerFacetGrantV1)
            or grant.capability_id != self._capability_id
            or grant.facet_id != self._facet_id
            or grant.binding_fingerprint != self._admission.binding_fingerprint
            or grant.authority_fingerprint != self._admission.authority_fingerprint
            or not callable(decoder)
        ):
            raise CapabilityWorkerFacetProxyError(
                "worker_capability_facet_proxy_grant_invalid"
            )
        return grant, decoder


__all__ = [
    "CapabilityWorkerFacetProxyError",
    "CapabilityWorkerReadOnlyFacetProxy",
]
