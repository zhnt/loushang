"""Exact Tool and Command owner adapters for the data-only ``coding.base``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Protocol

from loushang.coding.resources.tool_pack import (
    create_coding_builtin_tool_definitions as create_coding_builtin_tool_definitions,
)
from loushang.harness.capabilities.contracts import (
    CapabilityContractRange,
    CapabilityRequirement,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
)
from loushang.harness.capabilities.workspace_contracts import (
    WORKSPACE_EDIT_FACET,
    WORKSPACE_LIST_FACET,
    WORKSPACE_PROCESS_LAUNCH_FACET,
    WORKSPACE_READ_FACET,
    WORKSPACE_SEARCH_FACET,
    WORKSPACE_WRITE_FACET,
)
from loushang.harness.runtime.registration import (
    OwnerGenerationRetirementReceipt,
    RegistrationScope,
    registration_scope_retirement_receipt,
)
from loushang.harness.session.capability_composition_inputs import (
    OwnerGenerationDispose,
    OwnerGenerationStage,
    SessionCapabilityConsumerCapture,
    SessionCapabilityOwnerAuthorityGate,
    SessionCapabilityOwnerGenerationBinding,
    product_contribution_registration_owner,
)
from loushang.harness.session.command_controller import (
    SessionCommandGenerationRegistry,
)
from loushang.harness.session.tool_owner_binding import (
    DeferredToolRegistrationSlot,
    SessionToolRegistrationPort,
    stage_workspace_tool_scope,
    workspace_options_from_capture,
)
from loushang.harness.tools.workspace.factory import ToolsOptions
from loushang.harness.workspace.generation_bindings import (
    GenerationBoundOperationSet,
)

_PLUGIN_ID = "coding.base"
_REGISTRATION_LABEL = "Coding base"
_TOOL_LABEL = f"{_REGISTRATION_LABEL} Tool"
_COMMAND_LABEL = f"{_REGISTRATION_LABEL} Command"
_STALE_WORKSPACE_GENERATION = "Coding base workspace operation generation is stale."
_FAILED_WORKSPACE_GENERATION = (
    "Coding base workspace operation generation failed staging."
)
_TOOL_OWNER_ID = "tools.workspace"
_TOOL_CATALOG_ID = "harness.workspace.core"
_COMMAND_CONTRIBUTION_ID = "coding.standard"
_COMMAND_OWNER_ID = "commands.session"
_COMMAND_CATALOG_ID = "harness.session.standard"
_TOOL_PACK_IDENTITIES = {
    "coding.builtin": ("bash", "edit", "find", "grep", "ls", "read", "write"),
    "coding.builtin.windows": (
        "edit",
        "find",
        "grep",
        "ls",
        "read",
        "shell",
        "write",
    ),
}
_COMMAND_NAMES = (
    "branch",
    "changelog",
    "clone",
    "compact",
    "copy",
    "delete",
    "export",
    "extensions",
    "fork",
    "import",
    "new",
    "reload",
    "rename",
    "resume",
    "session",
    "tools",
    "tree",
)
_WORKSPACE_REQUIREMENT = CapabilityRequirement(
    capability="harness.workspace",
    facets=(
        WORKSPACE_EDIT_FACET,
        WORKSPACE_LIST_FACET,
        WORKSPACE_PROCESS_LAUNCH_FACET,
        WORKSPACE_READ_FACET,
        WORKSPACE_SEARCH_FACET,
        WORKSPACE_WRITE_FACET,
    ),
    compatible_contract=CapabilityContractRange.exact(1),
)


class CodingBaseToolRegistrationPort(SessionToolRegistrationPort, Protocol):
    """Product-compatible name for the shared narrow registration port."""


@dataclass(slots=True)
class CodingBaseToolRegistrationSlot(DeferredToolRegistrationSlot):
    label: ClassVar[str] = "Coding base Tool"


class CodingBaseOwnerError(RuntimeError):
    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class _CodingBaseSourceInfo:
    plugin_id: str
    contribution_id: str
    admission_fingerprint: str


@dataclass(slots=True)
class _CodingBaseGeneration:
    scope: RegistrationScope = field(repr=False)
    kind: str
    operation_set: GenerationBoundOperationSet | None = field(
        default=None,
        repr=False,
    )

    def commit(self) -> None:
        self.scope.commit()

    def rollback_commit(self) -> None:
        self.scope.rollback_commit()

    async def dispose(self) -> None:
        if self.operation_set is not None:
            self.operation_set.invalidate(_STALE_WORKSPACE_GENERATION)
        report = await self.scope.dispose()
        if report.has_failures:
            raise _generation_disposal_error(self.kind)

    def retirement_receipt(
        self,
        *,
        contribution_id: str,
    ) -> OwnerGenerationRetirementReceipt:
        if self.scope.state not in {"open", "committed"}:
            raise RuntimeError(
                "Coding base retirement evidence requires a live generation"
            )
        return registration_scope_retirement_receipt(
            self.scope,
            contribution_ids=(contribution_id,),
            allow_open=True,
        )


@dataclass(slots=True)
class CodingBaseToolOwner:
    admission: OwnerContributionAdmissionRecord
    authority_gate: SessionCapabilityOwnerAuthorityGate = field(repr=False)
    options: ToolsOptions = field(default_factory=ToolsOptions, repr=False)
    scope_id: str = ""
    _bound: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        tool_names = _tool_identities(self.admission.contribution_id)
        _validate_admission(
            self.admission,
            owner_id=_TOOL_OWNER_ID,
            contribution_kind="tool_pack",
            contribution_id=self.admission.contribution_id,
            catalog_id=_TOOL_CATALOG_ID,
            identities=tool_names,
            requirements=(_WORKSPACE_REQUIREMENT,),
        )
        if not isinstance(self.options, ToolsOptions):
            raise TypeError("Coding base Tool owner options are invalid")
        _validate_owner_common(self.admission, self.authority_gate, self.scope_id)

    def bind(
        self,
        registration: CodingBaseToolRegistrationPort,
    ) -> SessionCapabilityOwnerGenerationBinding:
        if self._bound:
            raise RuntimeError("Coding base Tool owner was already bound")
        if not callable(getattr(registration, "stage_runtime_tool", None)):
            raise TypeError("Coding base Tool owner registration port is invalid")
        self._bound = True
        return _bind_registration_owner(
            self.admission,
            self.authority_gate,
            stage=lambda captures: self._stage(captures, registration=registration),
            dispose=self._dispose,
            label=_REGISTRATION_LABEL,
        )

    def _stage(
        self,
        captures: tuple[SessionCapabilityConsumerCapture, ...],
        *,
        registration: CodingBaseToolRegistrationPort,
    ) -> _CodingBaseGeneration:
        options, operation_set = self._options_from_capture(captures)
        tool_names = _tool_identities(self.admission.contribution_id)
        scope = RegistrationScope(
            product_contribution_registration_owner(self.admission, self.scope_id)
        )
        source_info = _CodingBaseSourceInfo(
            plugin_id=self.admission.plugin_id,
            contribution_id=self.admission.contribution_id,
            admission_fingerprint=self.admission.fingerprint,
        )
        stage_workspace_tool_scope(
            scope,
            operation_set,
            tool_names,
            registration=registration,
            source_info=source_info,
            build_definitions=lambda: create_coding_builtin_tool_definitions(
                options=options
            ),
            label=_TOOL_LABEL,
            failed_generation_message=_FAILED_WORKSPACE_GENERATION,
        )
        return _CodingBaseGeneration(
            scope=scope, kind="tool", operation_set=operation_set
        )

    def _options_from_capture(
        self,
        captures: tuple[SessionCapabilityConsumerCapture, ...],
    ) -> tuple[ToolsOptions, GenerationBoundOperationSet]:
        if len(captures) != 1:
            raise ValueError("Coding base Tool owner requires one Consumer capture")
        [capture] = captures
        if (
            not isinstance(capture, SessionCapabilityConsumerCapture)
            or capture.entry.admission_fingerprint != self.admission.fingerprint
            or capture.entry.requirement != _WORKSPACE_REQUIREMENT
        ):
            raise ValueError("Coding base Tool owner received another Consumer")
        return workspace_options_from_capture(
            self.options,
            capture,
            label=_TOOL_LABEL,
            stale_message=_STALE_WORKSPACE_GENERATION,
        )

    async def _dispose(self, value: object) -> None:
        if not isinstance(value, _CodingBaseGeneration) or value.kind != "tool":
            raise TypeError("Coding base Tool owner received a foreign generation")
        await value.dispose()


@dataclass(slots=True)
class CodingBaseCommandOwner:
    admission: OwnerContributionAdmissionRecord
    authority_gate: SessionCapabilityOwnerAuthorityGate = field(repr=False)
    scope_id: str
    _bound: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        _validate_admission(
            self.admission,
            owner_id=_COMMAND_OWNER_ID,
            contribution_kind="command_pack",
            contribution_id=_COMMAND_CONTRIBUTION_ID,
            catalog_id=_COMMAND_CATALOG_ID,
            identities=_COMMAND_NAMES,
            requirements=(),
        )
        _validate_owner_common(self.admission, self.authority_gate, self.scope_id)

    def bind(
        self,
        registry: SessionCommandGenerationRegistry,
    ) -> SessionCapabilityOwnerGenerationBinding:
        if self._bound:
            raise RuntimeError("Coding base Command owner was already bound")
        if not isinstance(registry, SessionCommandGenerationRegistry):
            raise TypeError("Coding base Command registration port is invalid")
        self._bound = True
        return _bind_registration_owner(
            self.admission,
            self.authority_gate,
            stage=lambda captures: self._stage(captures, registry=registry),
            dispose=self._dispose,
            label=_REGISTRATION_LABEL,
        )

    def _stage(
        self,
        captures: tuple[SessionCapabilityConsumerCapture, ...],
        *,
        registry: SessionCommandGenerationRegistry,
    ) -> _CodingBaseGeneration:
        if captures:
            raise ValueError(f"{_COMMAND_LABEL} owner declares no Consumers")
        scope = registry.stage_standard_pack_scope(
            self.admission,
            scope_id=self.scope_id,
            pack_id=_COMMAND_CATALOG_ID,
            expected_names=_COMMAND_NAMES,
            label=_COMMAND_LABEL,
        )
        return _CodingBaseGeneration(scope=scope, kind="command")

    async def _dispose(self, value: object) -> None:
        if not isinstance(value, _CodingBaseGeneration) or value.kind != "command":
            raise TypeError("Coding base Command owner received a foreign generation")
        await value.dispose()


def _bind_registration_owner(
    admission: OwnerContributionAdmissionRecord,
    authority_gate: SessionCapabilityOwnerAuthorityGate,
    *,
    stage: OwnerGenerationStage,
    dispose: OwnerGenerationDispose,
    label: str,
) -> SessionCapabilityOwnerGenerationBinding:
    """Hand the staged scope to the existing capability Graph lifecycle."""

    def require_generation(value: object) -> _CodingBaseGeneration:
        if not isinstance(value, _CodingBaseGeneration):
            raise TypeError(f"{label} owner received a foreign generation")
        return value

    return SessionCapabilityOwnerGenerationBinding(
        owner_id=admission.owner_id,
        contribution_kind=admission.contribution_kind,
        plugin_id=admission.plugin_id,
        contribution_id=admission.contribution_id,
        admission_fingerprint=admission.fingerprint,
        authority_gate=authority_gate,
        stage=stage,
        dispose=dispose,
        retirement_receipt=lambda value: require_generation(value).retirement_receipt(
            contribution_id=admission.contribution_id,
        ),
        commit=lambda value: require_generation(value).commit(),
        rollback_commit=lambda value: require_generation(value).rollback_commit(),
    )


def _generation_disposal_error(kind: str) -> CodingBaseOwnerError:
    return CodingBaseOwnerError(
        f"Coding base {kind} generation disposal remains incomplete",
        code=f"coding_base_{kind}_generation_disposal_failed",
    )


def _tool_identities(contribution_id: str) -> tuple[str, ...]:
    identities = _TOOL_PACK_IDENTITIES.get(contribution_id)
    if identities is None:
        raise ValueError("Coding base Tool owner admission is not a reserved pack")
    return identities


def _validate_admission(
    admission: OwnerContributionAdmissionRecord,
    *,
    owner_id: str,
    contribution_kind: str,
    contribution_id: str,
    catalog_id: str,
    identities: tuple[str, ...],
    requirements: tuple[CapabilityRequirement, ...],
) -> None:
    if not isinstance(admission, OwnerContributionAdmissionRecord):
        raise TypeError("Coding base owner requires an exact admission")
    if (
        admission.owner_id != owner_id
        or admission.contribution_kind != contribution_kind
        or admission.plugin_id != _PLUGIN_ID
        or admission.contribution_id != contribution_id
        or admission.candidate.contribution.collection_id != catalog_id
        or admission.admitted_identities != identities
        or admission.requirements != requirements
    ):
        raise ValueError("Coding base owner admission is not the reserved pack")


def _validate_owner_common(
    admission: OwnerContributionAdmissionRecord,
    authority_gate: SessionCapabilityOwnerAuthorityGate,
    scope_id: str,
) -> None:
    if not isinstance(authority_gate, SessionCapabilityOwnerAuthorityGate):
        raise TypeError("Coding base owner requires an authority gate")
    if not isinstance(scope_id, str) or not scope_id.strip():
        raise ValueError("Coding base owner scope id must not be empty")
    if admission.candidate.scope_id != scope_id:
        raise ValueError("Coding base owner scope does not match admission")


__all__ = [
    "CodingBaseCommandOwner",
    "CodingBaseOwnerError",
    "CodingBaseToolOwner",
    "CodingBaseToolRegistrationPort",
    "CodingBaseToolRegistrationSlot",
]
