"""Exact Tool and Command owner adapters for the data-only ``coding.base``."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import partial
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
from loushang.harness.session.capability_composition_inputs import (
    RegistrationScopeGeneration,
    SessionCapabilityConsumerCapture,
    SessionCapabilityOwnerAuthorityGate,
    SessionCapabilityOwnerGenerationBinding,
    bind_owner_registration_scope,
)
from loushang.harness.session.command_controller import (
    SessionCommandGenerationRegistry,
)
from loushang.harness.session.tool_owner_binding import (
    DeferredToolRegistrationSlot,
    SessionToolRegistrationPort,
    stage_workspace_tool_generation,
)
from loushang.harness.tools.workspace.factory import ToolsOptions

_PLUGIN_ID = "coding.base"
_REGISTRATION_LABEL = "Coding base"
_TOOL_LABEL = f"{_REGISTRATION_LABEL} Tool"
_COMMAND_LABEL = f"{_REGISTRATION_LABEL} Command"
_TOOL_GENERATION = object()
_COMMAND_GENERATION = object()
_INACTIVE_RETIREMENT_MESSAGE = (
    "Coding base retirement evidence requires a live generation"
)
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
        return bind_owner_registration_scope(
            self.admission,
            self.authority_gate,
            stage=partial(self._stage, registration=registration),
            generation_family=_TOOL_GENERATION,
            label=_REGISTRATION_LABEL,
            disposal_label=_TOOL_LABEL,
            disposal_error=partial(_generation_disposal_error, "tool"),
            inactive_retirement_message=_INACTIVE_RETIREMENT_MESSAGE,
        )

    def _stage(
        self,
        captures: tuple[SessionCapabilityConsumerCapture, ...],
        *,
        registration: CodingBaseToolRegistrationPort,
    ) -> RegistrationScopeGeneration:
        return stage_workspace_tool_generation(
            self.admission,
            self.scope_id,
            captures,
            requirement=_WORKSPACE_REQUIREMENT,
            options=self.options,
            tool_names=lambda: _tool_identities(self.admission.contribution_id),
            registration=registration,
            build_definitions=lambda options: create_coding_builtin_tool_definitions(
                options=options
            ),
            generation_family=_TOOL_GENERATION,
            label=_TOOL_LABEL,
            stale_generation_message=_STALE_WORKSPACE_GENERATION,
            failed_generation_message=_FAILED_WORKSPACE_GENERATION,
        )


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
        return bind_owner_registration_scope(
            self.admission,
            self.authority_gate,
            stage=partial(self._stage, registry=registry),
            generation_family=_COMMAND_GENERATION,
            label=_REGISTRATION_LABEL,
            disposal_label=_COMMAND_LABEL,
            disposal_error=partial(_generation_disposal_error, "command"),
            inactive_retirement_message=_INACTIVE_RETIREMENT_MESSAGE,
        )

    def _stage(
        self,
        captures: tuple[SessionCapabilityConsumerCapture, ...],
        *,
        registry: SessionCommandGenerationRegistry,
    ) -> RegistrationScopeGeneration:
        if captures:
            raise ValueError(f"{_COMMAND_LABEL} owner declares no Consumers")
        scope = registry.stage_standard_pack_scope(
            self.admission,
            scope_id=self.scope_id,
            pack_id=_COMMAND_CATALOG_ID,
            expected_names=_COMMAND_NAMES,
            label=_COMMAND_LABEL,
        )
        return RegistrationScopeGeneration(scope, _COMMAND_GENERATION)


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
