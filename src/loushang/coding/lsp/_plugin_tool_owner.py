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
    _ReservedToolPackOwner,
)
from loushang.harness.tools.core import ToolDefinition

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
class CodingLspToolOwner(_ReservedToolPackOwner):
    """Bind one admitted Tool pack to one future live Session registration port."""

    _owner_id = "coding.tools"
    _plugin_id = "coding.lsp.default"
    _contribution_id = "coding-lsp-tools"
    _catalog_id = "coding.lsp.tools"
    _tool_names = _TOOL_NAMES
    _requirement = CODING_LSP_TOOL_RUNTIME_REQUIREMENT
    _label = "Coding LSP Tool"
    _disposal_error = staticmethod(
        lambda: CodingLspToolOwnerError(
            "Coding LSP Tool generation disposal remains incomplete.",
            code="coding_lsp_tool_generation_disposal_failed",
        )
    )

    admission: OwnerContributionAdmissionRecord
    authority_gate: SessionCapabilityOwnerAuthorityGate = field(repr=False)
    mode: CapabilityMountMode
    scope_id: str
    _bound: bool = field(default=False, init=False, repr=False)

    def bind(
        self,
        registration: CodingLspToolRegistrationPort,
    ) -> SessionCapabilityOwnerGenerationBinding:
        """Bind the exact live registration port once without staging early."""

        return self._bind_reserved_pack(
            registration,
            definitions_from_captures=lambda captures: _tool_definitions(
                self._runtime_from_captures(captures)
            ),
            generation_family=lambda: CodingLspToolOwner,
        )

    def _runtime_from_captures(
        self,
        captures: tuple[SessionCapabilityConsumerCapture, ...],
    ) -> CodingLspToolRuntimePort:
        capture = self._checked_runtime_capture(captures)
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
