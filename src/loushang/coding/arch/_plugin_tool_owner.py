"""Private exact-owner adapter for the ``coding.arch.default`` Tool pack."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Protocol

from loushang.coding.arch._provider_api import (
    CODING_ARCH_TOOL_RUNTIME_REQUIREMENT,
    CodingArchToolRuntimeCapabilityConsumer,
    CodingArchToolRuntimePort,
)
from loushang.coding.arch.tool import (
    INSPECT_IMPORT_GRAPH_TOOL_NAME,
    create_inspect_import_graph_tool_definition,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
)
from loushang.harness.config.agent import CapabilityMountMode
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityConsumerCapture,
    SessionCapabilityOwnerAuthorityGate,
    SessionCapabilityOwnerGenerationBinding,
)
from loushang.harness.session.tool_owner_binding import (
    DeferredToolRegistrationSlot,
    SessionToolRegistrationPort,
    bind_admitted_tool_pack,
)
from loushang.harness.tools.core import ToolDefinition

_PLUGIN_ID = "coding.arch.default"
_CONTRIBUTION_ID = "coding-arch-tools"
_OWNER_ID = "coding.tools"
_CONTRIBUTION_KIND = "tool_pack"
_CATALOG_ID = "coding.arch.tools"
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
class CodingArchToolOwner:
    """Bind one admitted Arch Tool pack to a future Session registration port."""

    admission: OwnerContributionAdmissionRecord
    authority_gate: SessionCapabilityOwnerAuthorityGate = field(repr=False)
    mode: CapabilityMountMode
    scope_id: str
    _bound: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.admission, OwnerContributionAdmissionRecord):
            raise TypeError("Coding Arch Tool owner requires an exact admission")
        admission = self.admission
        if (
            admission.owner_id != _OWNER_ID
            or admission.contribution_kind != _CONTRIBUTION_KIND
            or admission.plugin_id != _PLUGIN_ID
            or admission.contribution_id != _CONTRIBUTION_ID
            or admission.candidate.contribution.collection_id != _CATALOG_ID
            or admission.admitted_identities != _TOOL_NAMES
            or admission.requirements != (CODING_ARCH_TOOL_RUNTIME_REQUIREMENT,)
        ):
            raise ValueError(
                "Coding Arch Tool owner admission is not the reserved pack"
            )
        if not isinstance(self.authority_gate, SessionCapabilityOwnerAuthorityGate):
            raise TypeError("Coding Arch Tool owner requires an authority gate")
        if self.mode not in {"on_demand", "always"}:
            raise ValueError("Coding Arch Tool owner requires an enabled mount mode")
        if not isinstance(self.scope_id, str) or not self.scope_id.strip():
            raise ValueError("Coding Arch Tool owner scope id must not be empty")
        if admission.candidate.scope_id != self.scope_id:
            raise ValueError("Coding Arch Tool owner scope does not match admission")

    def bind(
        self,
        registration: CodingArchToolRegistrationPort,
    ) -> SessionCapabilityOwnerGenerationBinding:
        """Bind the exact live registration port once without staging early."""

        if self._bound:
            raise RuntimeError("Coding Arch Tool owner was already bound")
        if not callable(getattr(registration, "stage_runtime_tool", None)):
            raise TypeError("Coding Arch Tool owner registration port is invalid")
        self._bound = True
        return bind_admitted_tool_pack(
            self,
            self.authority_gate,
            registration=registration,
            definitions_from_captures=lambda captures: _tool_definitions(
                self._runtime_from_captures(captures)
            ),
            generation_family=CodingArchToolOwner,
            label="Coding Arch Tool",
            disposal_error=lambda: CodingArchToolOwnerError(
                "Coding Arch Tool generation disposal remains incomplete.",
                code="coding_arch_tool_generation_disposal_failed",
            ),
        )

    def _runtime_from_captures(
        self,
        captures: tuple[SessionCapabilityConsumerCapture, ...],
    ) -> CodingArchToolRuntimePort:
        if len(captures) != 1:
            raise ValueError("Coding Arch Tool owner requires one Consumer capture")
        [capture] = captures
        if not isinstance(capture, SessionCapabilityConsumerCapture):
            raise TypeError("Coding Arch Tool owner Consumer capture is invalid")
        if (
            capture.entry.admission_fingerprint != self.admission.fingerprint
            or capture.entry.requirement != CODING_ARCH_TOOL_RUNTIME_REQUIREMENT
        ):
            raise ValueError("Coding Arch Tool owner received another Consumer")
        return CodingArchToolRuntimeCapabilityConsumer(capture.facets).runtime


def _tool_definitions(
    runtime: CodingArchToolRuntimePort,
) -> tuple[ToolDefinition, ...]:
    definitions = (create_inspect_import_graph_tool_definition(runtime=runtime),)
    if tuple(item.name for item in definitions) != _TOOL_NAMES:
        raise RuntimeError("Coding Arch Tool factories changed admitted identities")
    return definitions


__all__ = [
    "CodingArchToolOwner",
    "CodingArchToolOwnerError",
    "CodingArchToolRegistrationPort",
    "CodingArchToolRegistrationSlot",
]
