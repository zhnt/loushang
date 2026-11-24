"""Private exact-owner adapter for the ``coding.arch.default`` Tool pack."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Protocol

from loushang.coding.arch._provider_api import (
    CODING_ARCH_TOOL_RUNTIME_REQUIREMENT,
    CodingArchToolRuntimeCapabilityConsumer,
)
from loushang.coding.arch.tool import (
    INSPECT_IMPORT_GRAPH_TOOL_NAME,
    create_inspect_import_graph_tool_definition,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
)
from loushang.harness.capabilities.graph_runtime import CapabilityFacetSet
from loushang.harness.config.agent import CapabilityMountMode
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityOwnerAuthorityGate,
)
from loushang.harness.session.tool_owner_binding import (
    DeferredToolRegistrationSlot,
    SessionToolRegistrationPort,
    _ReservedToolPackOwner,
)
from loushang.harness.tools.core import ToolDefinition

_TOOL_NAMES = (INSPECT_IMPORT_GRAPH_TOOL_NAME,)


class CodingArchToolRegistrationPort(SessionToolRegistrationPort, Protocol):
    """Product-compatible name for the shared narrow registration port."""


@dataclass(slots=True)
class CodingArchToolRegistrationSlot(DeferredToolRegistrationSlot):
    label: ClassVar[str] = "Coding Arch Tool"


class CodingArchToolOwnerError(RuntimeError):
    """Stable Product error for one exact Arch Tool owner generation."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class CodingArchToolOwner(_ReservedToolPackOwner):
    """Bind one admitted Arch Tool pack to a future Session registration port."""

    _owner_id = "coding.tools"
    _plugin_id = "coding.arch.default"
    _contribution_id = "coding-arch-tools"
    _catalog_id = "coding.arch.tools"
    _tool_names = _TOOL_NAMES
    _requirement = CODING_ARCH_TOOL_RUNTIME_REQUIREMENT
    _label = "Coding Arch Tool"
    _generation_family = staticmethod(lambda: CodingArchToolOwner)
    _disposal_error = staticmethod(
        lambda: CodingArchToolOwnerError(
            "Coding Arch Tool generation disposal remains incomplete.",
            code="coding_arch_tool_generation_disposal_failed",
        )
    )

    admission: OwnerContributionAdmissionRecord
    authority_gate: SessionCapabilityOwnerAuthorityGate = field(repr=False)
    mode: CapabilityMountMode
    scope_id: str
    _bound: bool = field(default=False, init=False, repr=False)

    def _tool_definitions(
        self, facets: CapabilityFacetSet
    ) -> tuple[ToolDefinition, ...]:
        runtime = CodingArchToolRuntimeCapabilityConsumer(facets).runtime
        return (create_inspect_import_graph_tool_definition(runtime=runtime),)


__all__ = [
    "CodingArchToolOwner",
    "CodingArchToolOwnerError",
    "CodingArchToolRegistrationPort",
    "CodingArchToolRegistrationSlot",
]
