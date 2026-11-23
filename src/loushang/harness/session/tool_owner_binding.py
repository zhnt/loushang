"""Connect admitted Tool packs to existing Session and registration owners."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import ClassVar, Protocol, cast

from loushang.harness.capabilities.contracts import CapabilityRequirement
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
from loushang.harness.config.agent import CapabilityMountMode
from loushang.harness.runtime.registration import (
    RegistrationLease,
    RegistrationOwner,
    RegistrationScope,
    registration_scope_retirement_receipt,
    rollback_registration_scope,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.workspace.bash import BashOperations
from loushang.harness.tools.workspace.factory import ToolsOptions
from loushang.harness.workspace.exec import AuthorizedProcessExecBackend, ExecService
from loushang.harness.workspace.generation_bindings import GenerationBoundOperationSet
from loushang.harness.workspace.operations import (
    EditOperations,
    FindOperations,
    GrepOperations,
    LsOperations,
    ReadOperations,
    WriteOperations,
)
from loushang.harness.workspace.process import AuthorizedProcessLauncher

from .capability_composition_inputs import (
    SessionCapabilityConsumerCapture,
    SessionCapabilityOwnerAuthorityGate,
    SessionCapabilityOwnerGenerationBinding,
    product_contribution_registration_owner,
)


class SessionToolRegistrationPort(Protocol):
    def stage_runtime_tool(
        self,
        tool: object,
        *,
        owner: RegistrationOwner,
        enabled: bool = True,
        source_info: object | None = None,
    ) -> RegistrationLease: ...


@dataclass(slots=True)
class DeferredToolRegistrationSlot:
    """Bind the original controller once after Session construction."""

    label: ClassVar[str] = "Session Tool"
    _port: SessionToolRegistrationPort | None = field(
        default=None, init=False, repr=False
    )

    def bind(self, port: SessionToolRegistrationPort) -> None:
        if self._port is not None:
            raise RuntimeError(f"{self.label} registration is already bound")
        if not callable(getattr(port, "stage_runtime_tool", None)):
            raise TypeError(f"{self.label} registration port is invalid")
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
            raise RuntimeError(f"{self.label} registration is not yet bound")
        return port.stage_runtime_tool(
            tool, owner=owner, enabled=enabled, source_info=source_info
        )


@dataclass(frozen=True, slots=True)
class _ToolPackSourceInfo:
    plugin_id: str
    contribution_id: str
    admission_fingerprint: str


@dataclass(frozen=True, slots=True)
class _ToolPackGeneration:
    scope: RegistrationScope = field(repr=False)
    family: object = field(repr=False)


class ToolPackBindingInputs(Protocol):
    """Read the original mutable fields at their original lifecycle points."""

    @property
    def admission(self) -> OwnerContributionAdmissionRecord: ...

    @property
    def scope_id(self) -> str: ...

    @property
    def mode(self) -> CapabilityMountMode: ...


def bind_admitted_tool_pack(
    inputs: ToolPackBindingInputs,
    authority_gate: SessionCapabilityOwnerAuthorityGate,
    *,
    registration: SessionToolRegistrationPort,
    definitions_from_captures: Callable[
        [tuple[SessionCapabilityConsumerCapture, ...]], tuple[ToolDefinition, ...]
    ],
    generation_family: object,
    label: str,
    disposal_error: Callable[[], Exception],
) -> SessionCapabilityOwnerGenerationBinding:
    """Wire one already-admitted pack; the Graph still drives its lifecycle."""
    bound_admission = inputs.admission

    def require_generation(value: object) -> _ToolPackGeneration:
        if (
            not isinstance(value, _ToolPackGeneration)
            or value.family is not generation_family
        ):
            raise TypeError(f"{label} owner received a foreign generation")
        return value

    def stage(
        captures: tuple[SessionCapabilityConsumerCapture, ...],
    ) -> _ToolPackGeneration:
        definitions = tuple(definitions_from_captures(captures))
        admission = inputs.admission
        owner = product_contribution_registration_owner(admission, inputs.scope_id)
        scope = RegistrationScope(owner)
        source_info = _ToolPackSourceInfo(
            admission.plugin_id, admission.contribution_id, admission.fingerprint
        )
        try:
            for definition in definitions:
                scope.add(
                    registration.stage_runtime_tool(
                        definition,
                        owner=owner,
                        enabled=inputs.mode == "always",
                        source_info=source_info,
                    )
                )
        except BaseException as error:
            rollback_registration_scope(
                scope, error, incomplete_note=f"{label} staging rollback remains incomplete"
            )
            raise
        return _ToolPackGeneration(scope, generation_family)

    async def dispose(value: object) -> None:
        report = await require_generation(value).scope.dispose()
        if report.has_failures:
            raise disposal_error()

    return SessionCapabilityOwnerGenerationBinding(
        owner_id=bound_admission.owner_id,
        contribution_kind=bound_admission.contribution_kind,
        plugin_id=bound_admission.plugin_id,
        contribution_id=bound_admission.contribution_id,
        admission_fingerprint=bound_admission.fingerprint,
        authority_gate=authority_gate,
        stage=stage,
        dispose=dispose,
        retirement_receipt=lambda value: registration_scope_retirement_receipt(
            require_generation(value).scope,
            contribution_ids=(inputs.admission.contribution_id,),
            allow_open=True,
        ),
        commit=lambda value: require_generation(value).scope.commit(),
        rollback_commit=lambda value: require_generation(value).scope.rollback_commit(),
    )


def workspace_options_from_capture(
    options: ToolsOptions,
    capture: SessionCapabilityConsumerCapture,
    *,
    label: str,
    stale_message: str,
) -> tuple[ToolsOptions, GenerationBoundOperationSet]:
    """Capture the admitted facets into one revocable workspace binding."""
    facets = capture.facets
    launcher = facets.require(WORKSPACE_PROCESS_LAUNCH_FACET)
    if not callable(getattr(launcher, "start", None)):
        raise TypeError(f"{label} process facet is invalid")
    process_operations = ExecService(
        backend=AuthorizedProcessExecBackend(cast(AuthorizedProcessLauncher, launcher))
    )
    operation_set = GenerationBoundOperationSet(
        {
            "process": process_operations,
            "read": facets.require(WORKSPACE_READ_FACET),
            "list": facets.require(WORKSPACE_LIST_FACET),
            "search": facets.require(WORKSPACE_SEARCH_FACET),
            "write": facets.require(WORKSPACE_WRITE_FACET),
            "edit": facets.require(WORKSPACE_EDIT_FACET),
        },
        stale_message=stale_message,
    )
    return replace(
        options,
        exec_service=None,
        bash_operations=cast(BashOperations, operation_set.capture("process")),
        shell_operations=cast(BashOperations, operation_set.capture("process")),
        read_operations=cast(ReadOperations, operation_set.capture("read")),
        ls_operations=cast(LsOperations, operation_set.capture("list")),
        find_operations=cast(FindOperations, operation_set.capture("search")),
        grep_operations=cast(GrepOperations, operation_set.capture("search")),
        write_operations=cast(WriteOperations, operation_set.capture("write")),
        edit_operations=cast(EditOperations, operation_set.capture("edit")),
    ), operation_set


def stage_workspace_tool_scope(
    scope: RegistrationScope,
    operation_set: GenerationBoundOperationSet,
    tool_names: tuple[str, ...],
    *,
    registration: SessionToolRegistrationPort,
    source_info: object,
    build_definitions: Callable[[], list[ToolDefinition]],
    label: str,
    failed_generation_message: str,
) -> None:
    """Stage the complete admitted pack under one revocable scope."""

    try:
        by_name = {item.name: item for item in build_definitions()}
        if set(by_name) != set(tool_names):
            raise RuntimeError(f"{label} catalog changed admitted identities")
        for name in tool_names:
            scope.add(
                registration.stage_runtime_tool(
                    by_name[name], owner=scope.owner, source_info=source_info
                )
            )
    except BaseException as error:
        operation_set.invalidate(failed_generation_message)
        rollback_registration_scope(
            scope, error, incomplete_note=f"{label} rollback remains incomplete"
        )
        raise


class _ToolOwnerBoundState(Protocol):
    _bound: bool


class _ReservedToolPackOwner:
    """Validate and bind one reserved Tool pack using its Product's facts."""

    __slots__ = ()
    admission: OwnerContributionAdmissionRecord
    authority_gate: SessionCapabilityOwnerAuthorityGate
    mode: CapabilityMountMode
    scope_id: str
    _bound: bool
    _owner_id: ClassVar[str]
    _plugin_id: ClassVar[str]
    _contribution_id: ClassVar[str]
    _catalog_id: ClassVar[str]
    _tool_names: ClassVar[tuple[str, ...]]
    _requirement: ClassVar[CapabilityRequirement]
    _label: ClassVar[str]
    _disposal_error: ClassVar[Callable[[], Exception]]

    def __post_init__(self) -> None:
        if not isinstance(self.admission, OwnerContributionAdmissionRecord):
            raise TypeError(f"{self._label} owner requires an exact admission")
        admission = self.admission
        if (
            admission.owner_id != self._owner_id
            or admission.contribution_kind != "tool_pack"
            or admission.plugin_id != self._plugin_id
            or admission.contribution_id != self._contribution_id
            or admission.candidate.contribution.collection_id != self._catalog_id
            or admission.admitted_identities != self._tool_names
            or admission.requirements != (self._requirement,)
        ):
            raise ValueError(f"{self._label} owner admission is not the reserved pack")
        if not isinstance(self.authority_gate, SessionCapabilityOwnerAuthorityGate):
            raise TypeError(f"{self._label} owner requires an authority gate")
        if self.mode not in {"on_demand", "always"}:
            raise ValueError(f"{self._label} owner requires an enabled mount mode")
        if not isinstance(self.scope_id, str) or not self.scope_id.strip():
            raise ValueError(f"{self._label} owner scope id must not be empty")
        if admission.candidate.scope_id != self.scope_id:
            raise ValueError(f"{self._label} owner scope does not match admission")

    def _bind_reserved_pack(
        self,
        registration: SessionToolRegistrationPort,
        *,
        definitions_from_captures: Callable[
            [tuple[SessionCapabilityConsumerCapture, ...]], tuple[ToolDefinition, ...]
        ],
        generation_family: Callable[[], object],
    ) -> SessionCapabilityOwnerGenerationBinding:
        if self._bound:
            raise RuntimeError(f"{self._label} owner was already bound")
        if not callable(getattr(registration, "stage_runtime_tool", None)):
            raise TypeError(f"{self._label} owner registration port is invalid")
        state: _ToolOwnerBoundState = self
        state._bound = True
        return bind_admitted_tool_pack(
            self,
            self.authority_gate,
            registration=registration,
            definitions_from_captures=definitions_from_captures,
            generation_family=generation_family(),
            label=self._label,
            disposal_error=type(self)._disposal_error,
        )

    def _checked_runtime_capture(
        self,
        captures: tuple[SessionCapabilityConsumerCapture, ...],
    ) -> SessionCapabilityConsumerCapture:
        if len(captures) != 1:
            raise ValueError(f"{self._label} owner requires one Consumer capture")
        [capture] = captures
        if not isinstance(capture, SessionCapabilityConsumerCapture):
            raise TypeError(f"{self._label} owner Consumer capture is invalid")
        if (
            capture.entry.admission_fingerprint != self.admission.fingerprint
            or capture.entry.requirement != self._requirement
        ):
            raise ValueError(f"{self._label} owner received another Consumer")
        return capture
