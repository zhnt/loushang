"""Coding-owned, explicit read-only Consumer for a selected query Worker.

The contract is deliberately separate from ``coding.lsp``. A Worker that only
answers bounded symbol queries cannot provide LSP session, Tool, or diagnostics
facets. Product routing stays opt-in through a selected Worker composition.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityDefinition,
    CapabilityRequirement,
)
from loushang.harness.capabilities.graph_runtime import CapabilityFacetSet
from loushang.harness.capabilities.provider_admission import (
    CapabilityProviderOwnerAuthority,
    CapabilityProviderOwnerPolicy,
    CapabilityProviderOwnerSnapshot,
)
from loushang.harness.session.agent_product import AgentProductSession
from loushang.harness.worker.capability_query import CapabilityWorkerBindingV1
from loushang.harness.worker.facet_owner import CapabilityWorkerFacetOwnerPolicy
from loushang.harness.worker.facet_proxy import CapabilityWorkerReadOnlyFacetProxy

CODING_WORKER_QUERY_CAPABILITY_ID = "coding.worker.query"
CODING_WORKER_QUERY_FACET_ID = "query"
CODING_WORKER_QUERY_PROVIDER_ID = "worker.query"
CODING_WORKER_QUERY_OWNER_POLICY_REVISION = "coding-worker-query-v1"

CODING_WORKER_QUERY_DEFINITION = CapabilityDefinition(
    capability_id=CODING_WORKER_QUERY_CAPABILITY_ID,
    owner_id="coding",
    contract_version=1,
    facets=(CODING_WORKER_QUERY_FACET_ID,),
    scope="session",
    refresh_boundary="sealed",
    phase="final",
    authority_ceiling=frozenset(),
)
CODING_WORKER_QUERY_REQUIREMENT = CapabilityRequirement(
    capability=CODING_WORKER_QUERY_CAPABILITY_ID,
    facets=(CODING_WORKER_QUERY_FACET_ID,),
    compatible_contract=CapabilityContractRange.exact(1),
)

_SYMBOL = re.compile(r"[A-Za-z_][A-Za-z0-9_.]{0,127}\Z")


def validate_coding_worker_query_symbol(symbol: str) -> str:
    if not isinstance(symbol, str) or _SYMBOL.fullmatch(symbol) is None:
        raise ValueError("Coding Worker query symbol is invalid")
    return symbol


def coding_worker_query_owner_authority() -> CapabilityProviderOwnerAuthority:
    """Return the exact first-party owner policy for this one Worker contract."""

    return CapabilityProviderOwnerAuthority(
        CapabilityProviderOwnerPolicy(
            capability_id=CODING_WORKER_QUERY_CAPABILITY_ID,
            owner_id="coding",
            policy_revision=CODING_WORKER_QUERY_OWNER_POLICY_REVISION,
            revocation_epoch=0,
            allowed_provider_ids=(CODING_WORKER_QUERY_PROVIDER_ID,),
            allowed_source_trust_classes=("local-worker-candidate",),
            authority_ceiling=(),
            allowed_execution_models=("local_worker",),
        )
    )


def decode_coding_worker_query_result(value: object) -> str:
    """Decode only the bounded text result promised to Coding Consumers."""

    if type(value) is not dict or set(value) != {"text"}:
        raise ValueError("Coding Worker query result is invalid")
    result = value["text"]
    if not isinstance(result, str) or not result or len(result) > 4096:
        raise ValueError("Coding Worker query text is invalid")
    return result


def bind_coding_worker_query_facet_owner(
    *,
    binding: CapabilityWorkerBindingV1,
    provider_owner: CapabilityProviderOwnerAuthority,
    current_owner_snapshot: Callable[[], CapabilityProviderOwnerSnapshot],
) -> CapabilityWorkerFacetOwnerPolicy:
    """Bind the Coding decoder only under the exact production owner policy."""

    if provider_owner.policy != coding_worker_query_owner_authority().policy:
        raise ValueError("Coding Worker query owner policy is not approved")
    return CapabilityWorkerFacetOwnerPolicy(
        definition=CODING_WORKER_QUERY_DEFINITION,
        provider_owner=provider_owner,
        binding=binding,
        facet_decoders={
            CODING_WORKER_QUERY_FACET_ID: decode_coding_worker_query_result
        },
        current_owner_snapshot=current_owner_snapshot,
    )


@dataclass(frozen=True, slots=True)
class CodingWorkerQueryCapabilityConsumer:
    """One generation-scoped Product view of the admitted query facet."""

    facets: CapabilityFacetSet

    def __post_init__(self) -> None:
        if self.facets.requirement != CODING_WORKER_QUERY_REQUIREMENT:
            raise ValueError("Coding Worker query Consumer received wrong facets")
        if not isinstance(
            self.facets.require(CODING_WORKER_QUERY_FACET_ID),
            CapabilityWorkerReadOnlyFacetProxy,
        ):
            raise TypeError("Coding Worker query requires a Worker facet proxy")

    async def query(self, *, symbol: str) -> str:
        symbol = validate_coding_worker_query_symbol(symbol)
        facet = self.facets.require(CODING_WORKER_QUERY_FACET_ID)
        assert isinstance(facet, CapabilityWorkerReadOnlyFacetProxy)
        result = await facet.invoke({"symbol": symbol})
        if not isinstance(result, str):
            raise TypeError("Coding Worker query decoder returned wrong type")
        return result


def bind_coding_worker_query_consumer(
    session: AgentProductSession,
) -> CodingWorkerQueryCapabilityConsumer:
    """Capture the explicit selected Worker from a prepared Product Session."""

    if not isinstance(session, AgentProductSession):
        raise TypeError("Coding Worker query requires a Product Session")
    return CodingWorkerQueryCapabilityConsumer(
        session.capture_host_product_consumer(CODING_WORKER_QUERY_REQUIREMENT)
    )


__all__ = [
    "CODING_WORKER_QUERY_CAPABILITY_ID",
    "CODING_WORKER_QUERY_DEFINITION",
    "CODING_WORKER_QUERY_FACET_ID",
    "CODING_WORKER_QUERY_OWNER_POLICY_REVISION",
    "CODING_WORKER_QUERY_PROVIDER_ID",
    "CODING_WORKER_QUERY_REQUIREMENT",
    "CodingWorkerQueryCapabilityConsumer",
    "bind_coding_worker_query_consumer",
    "bind_coding_worker_query_facet_owner",
    "coding_worker_query_owner_authority",
    "decode_coding_worker_query_result",
    "validate_coding_worker_query_symbol",
]
