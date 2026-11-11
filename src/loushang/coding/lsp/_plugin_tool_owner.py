"""Private exact-owner adapter for the ``coding.lsp.default`` Tool pack."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Protocol

from loushang.coding.lsp._provider_api import (
    CODING_LSP_TOOL_RUNTIME_REQUIREMENT,
    CodingLspToolRuntimeCapabilityConsumer,
    CodingLspToolRuntimePort,
)
from loushang.coding.lsp.tools import (
    DOCUMENT_OUTLINE_TOOL_NAME,
    INSPECT_SYMBOL_TOOL_NAME,
    create_document_outline_tool_definition,
    create_inspect_symbol_tool_definition,
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

_PLUGIN_ID = "coding.lsp.default"
_CONTRIBUTION_ID = "coding-lsp-tools"
_OWNER_ID = "coding.tools"
_CONTRIBUTION_KIND = "tool_pack"
_CATALOG_ID = "coding.lsp.tools"
_TOOL_NAMES = (DOCUMENT_OUTLINE_TOOL_NAME, INSPECT_SYMBOL_TOOL_NAME)


class CodingLspToolRegistrationPort(SessionToolRegistrationPort, Protocol):
    """Product-compatible name for the shared narrow registration port."""


@dataclass(slots=True)
class CodingLspToolRegistrationSlot(DeferredToolRegistrationSlot):
    label: ClassVar[str] = "Coding LSP Tool"


class CodingLspToolOwnerError(RuntimeError):
    """Stable Product error for one exact LSP Tool owner generation."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class CodingLspToolOwner:
    """Bind one admitted Tool pack to one future live Session registration port."""

    admission: OwnerContributionAdmissionRecord
    authority_gate: SessionCapabilityOwnerAuthorityGate = field(repr=False)
    mode: CapabilityMountMode
    scope_id: str
    _bound: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.admission, OwnerContributionAdmissionRecord):
            raise TypeError("Coding LSP Tool owner requires an exact admission")
        admission = self.admission
        if (
            admission.owner_id != _OWNER_ID
            or admission.contribution_kind != _CONTRIBUTION_KIND
            or admission.plugin_id != _PLUGIN_ID
            or admission.contribution_id != _CONTRIBUTION_ID
            or admission.candidate.contribution.collection_id != _CATALOG_ID
            or admission.admitted_identities != _TOOL_NAMES
            or admission.requirements != (CODING_LSP_TOOL_RUNTIME_REQUIREMENT,)
        ):
            raise ValueError("Coding LSP Tool owner admission is not the reserved pack")
        if not isinstance(self.authority_gate, SessionCapabilityOwnerAuthorityGate):
            raise TypeError("Coding LSP Tool owner requires an authority gate")
        if self.mode not in {"on_demand", "always"}:
            raise ValueError("Coding LSP Tool owner requires an enabled mount mode")
        if not isinstance(self.scope_id, str) or not self.scope_id.strip():
            raise ValueError("Coding LSP Tool owner scope id must not be empty")
        if admission.candidate.scope_id != self.scope_id:
            raise ValueError("Coding LSP Tool owner scope does not match admission")

    def bind(
        self,
        registration: CodingLspToolRegistrationPort,
    ) -> SessionCapabilityOwnerGenerationBinding:
        """Bind the exact live registration port once without staging early."""

        if self._bound:
            raise RuntimeError("Coding LSP Tool owner was already bound")
        if not callable(getattr(registration, "stage_runtime_tool", None)):
            raise TypeError("Coding LSP Tool owner registration port is invalid")
        self._bound = True
        return bind_admitted_tool_pack(
            self,
            self.authority_gate,
            registration=registration,
            definitions_from_captures=lambda captures: _tool_definitions(
                self._runtime_from_captures(captures)
            ),
            generation_family=CodingLspToolOwner,
            label="Coding LSP Tool",
            disposal_error=lambda: CodingLspToolOwnerError(
                "Coding LSP Tool generation disposal remains incomplete.",
                code="coding_lsp_tool_generation_disposal_failed",
            ),
        )

    def _runtime_from_captures(
        self,
        captures: tuple[SessionCapabilityConsumerCapture, ...],
    ) -> CodingLspToolRuntimePort:
        if len(captures) != 1:
            raise ValueError("Coding LSP Tool owner requires one Consumer capture")
        [capture] = captures
        if not isinstance(capture, SessionCapabilityConsumerCapture):
            raise TypeError("Coding LSP Tool owner Consumer capture is invalid")
        if (
            capture.entry.admission_fingerprint != self.admission.fingerprint
            or capture.entry.requirement != CODING_LSP_TOOL_RUNTIME_REQUIREMENT
        ):
            raise ValueError("Coding LSP Tool owner received another Consumer")
        return CodingLspToolRuntimeCapabilityConsumer(capture.facets).runtime


def _tool_definitions(
    runtime: CodingLspToolRuntimePort,
) -> tuple[ToolDefinition, ...]:
    definitions = (
        create_document_outline_tool_definition(runtime),
        create_inspect_symbol_tool_definition(runtime),
    )
    if tuple(item.name for item in definitions) != _TOOL_NAMES:
        raise RuntimeError("Coding LSP Tool factories changed admitted identities")
    return definitions


__all__ = [
    "CodingLspToolOwner",
    "CodingLspToolOwnerError",
    "CodingLspToolRegistrationPort",
    "CodingLspToolRegistrationSlot",
]
