"""Private exact-owner adapter for the ``coding.lsp.default`` Tool pack."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

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
from loushang.harness.runtime.registration import (
    OwnerGenerationRetirementReceipt,
    RegistrationLease,
    RegistrationOwner,
    RegistrationScope,
    registration_scope_retirement_receipt,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityConsumerCapture,
    SessionCapabilityOwnerAuthorityGate,
    SessionCapabilityOwnerGenerationBinding,
)
from loushang.harness.tools.core import ToolDefinition

_PLUGIN_ID = "coding.lsp.default"
_CONTRIBUTION_ID = "coding-lsp-tools"
_OWNER_ID = "coding.tools"
_CONTRIBUTION_KIND = "tool_pack"
_CATALOG_ID = "coding.lsp.tools"
_TOOL_NAMES = (DOCUMENT_OUTLINE_TOOL_NAME, INSPECT_SYMBOL_TOOL_NAME)


class CodingLspToolRegistrationPort(Protocol):
    """Narrow live Session port used only after Graph Consumer capture."""

    def stage_runtime_tool(
        self,
        tool: object,
        *,
        owner: RegistrationOwner,
        enabled: bool = True,
        source_info: object | None = None,
    ) -> RegistrationLease: ...


@dataclass(slots=True)
class CodingLspToolRegistrationSlot:
    """Bind one live Session Tool-registration port after construction."""

    _port: CodingLspToolRegistrationPort | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def bind(self, port: CodingLspToolRegistrationPort) -> None:
        if self._port is not None:
            raise RuntimeError("Coding LSP Tool registration is already bound")
        if not callable(getattr(port, "stage_runtime_tool", None)):
            raise TypeError("Coding LSP Tool registration port is invalid")
        self._port = port

    def stage_runtime_tool(
        self,
        tool: object,
        *,
        owner: RegistrationOwner,
        enabled: bool = True,
        source_info: object | None = None,
    ) -> RegistrationLease:
        port = self._port
        if port is None:
            raise RuntimeError("Coding LSP Tool registration is not yet bound")
        return port.stage_runtime_tool(
            tool,
            owner=owner,
            enabled=enabled,
            source_info=source_info,
        )


class CodingLspToolOwnerError(RuntimeError):
    """Stable Product error for one exact LSP Tool owner generation."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class _CodingLspToolSourceInfo:
    plugin_id: str
    contribution_id: str
    admission_fingerprint: str


@dataclass(slots=True)
class _CodingLspToolGeneration:
    scope: RegistrationScope = field(repr=False)

    def commit(self) -> None:
        self.scope.commit()

    def rollback_commit(self) -> None:
        self.scope.rollback_commit()

    async def dispose(self) -> None:
        report = await self.scope.dispose()
        if report.has_failures:
            raise CodingLspToolOwnerError(
                "Coding LSP Tool generation disposal remains incomplete.",
                code="coding_lsp_tool_generation_disposal_failed",
            )


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
        return SessionCapabilityOwnerGenerationBinding(
            owner_id=self.admission.owner_id,
            contribution_kind=self.admission.contribution_kind,
            plugin_id=self.admission.plugin_id,
            contribution_id=self.admission.contribution_id,
            admission_fingerprint=self.admission.fingerprint,
            authority_gate=self.authority_gate,
            stage=lambda captures: self._stage(captures, registration=registration),
            dispose=self._dispose,
            retirement_receipt=self._retirement_receipt,
            commit=self._commit,
            rollback_commit=self._rollback_commit,
        )

    def _stage(
        self,
        captures: tuple[SessionCapabilityConsumerCapture, ...],
        *,
        registration: CodingLspToolRegistrationPort,
    ) -> _CodingLspToolGeneration:
        runtime = self._runtime_from_captures(captures)
        definitions = _tool_definitions(runtime)
        owner = RegistrationOwner(
            owner_kind="product",
            owner_id=self.admission.owner_id,
            runtime_id=(
                f"{self.scope_id}:{self.admission.plugin_id}:"
                f"{self.admission.contribution_id}"
            ),
            generation=(self.admission.candidate.instance_revision_ref.revision),
        )
        scope = RegistrationScope(owner)
        source_info = _CodingLspToolSourceInfo(
            plugin_id=self.admission.plugin_id,
            contribution_id=self.admission.contribution_id,
            admission_fingerprint=self.admission.fingerprint,
        )
        try:
            for definition in definitions:
                scope.add(
                    registration.stage_runtime_tool(
                        definition,
                        owner=owner,
                        enabled=self.mode == "always",
                        source_info=source_info,
                    )
                )
        except BaseException as error:
            if scope.state == "committed":
                scope.rollback_commit()
            if scope.state == "open":
                rollback = scope.rollback_admission()
                if rollback.has_failures:
                    error.add_note(
                        "Coding LSP Tool staging rollback remains incomplete"
                    )
            raise
        return _CodingLspToolGeneration(scope)

    def _commit(self, value: object) -> None:
        if not isinstance(value, _CodingLspToolGeneration):
            raise TypeError("Coding LSP Tool owner received a foreign generation")
        value.commit()

    def _rollback_commit(self, value: object) -> None:
        if not isinstance(value, _CodingLspToolGeneration):
            raise TypeError("Coding LSP Tool owner received a foreign generation")
        value.rollback_commit()

    async def _dispose(self, value: object) -> None:
        if not isinstance(value, _CodingLspToolGeneration):
            raise TypeError("Coding LSP Tool owner received a foreign generation")
        await value.dispose()

    def _retirement_receipt(
        self,
        value: object,
    ) -> OwnerGenerationRetirementReceipt:
        if not isinstance(value, _CodingLspToolGeneration):
            raise TypeError("Coding LSP Tool owner received a foreign generation")
        return registration_scope_retirement_receipt(
            value.scope,
            contribution_ids=(self.admission.contribution_id,),
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
