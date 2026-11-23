"""Connect admitted Tool packs to existing Session and registration owners."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from functools import partial
from typing import ClassVar, Generic, ParamSpec, Protocol, TypeVar, cast

from loushang.harness.capabilities.component_host import (
    CapabilityComponentAdmissionStart,
)
from loushang.harness.capabilities.contracts import (
    CapabilityDefinition,
    CapabilityRequirement,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
)
from loushang.harness.capabilities.graph_binding import RuntimeCapabilityGraphBinder
from loushang.harness.capabilities.graph_planning import (
    CapabilityGraphPlanRequest,
    RuntimeCapabilityGraphPlanner,
)
from loushang.harness.capabilities.graph_runtime import (
    CapabilityFacetSet,
    RuntimeCapabilityGraphRuntime,
)
from loushang.harness.capabilities.provider_binding import (
    CapabilityBundleProviderBinding,
)
from loushang.harness.capabilities.workspace_contracts import (
    WORKSPACE_CAPABILITY_DEFINITION,
    WORKSPACE_EDIT_FACET,
    WORKSPACE_LIST_FACET,
    WORKSPACE_PROCESS_LAUNCH_FACET,
    WORKSPACE_READ_FACET,
    WORKSPACE_SEARCH_FACET,
    WORKSPACE_WRITE_FACET,
)
from loushang.harness.config.agent import CapabilityMountMode
from loushang.harness.runtime._owned_tasks import _await_cancellation_atomic
from loushang.harness.runtime.registration import (
    OwnerGenerationRetirementReceipt,
    RegistrationLease,
    RegistrationOwner,
    RegistrationScope,
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
    PreparedSessionCapabilityComponent,
    RegistrationScopeGeneration,
    SessionCapabilityComponentRequest,
    SessionCapabilityConsumerCapture,
    SessionCapabilityOwnerAdmissionStart,
    SessionCapabilityOwnerAuthorityGate,
    SessionCapabilityOwnerGenerationBinding,
    SessionCapabilityOwnerGenerationStagingError,
    StagedSessionCapabilityOwnerGeneration,
    bind_owner_registration_scope,
    capture_owner_generation_receipts,
    commit_session_capability_owner_generations,
    dispose_session_capability_owner_generations,
    product_contribution_registration_owner,
    stage_session_capability_owner_generations,
)
from .command_controller import SessionCommandGenerationRegistry
from .plugin_lifecycle._composition_cleanup import _PublishedCapabilityComposition


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
class PreparedOwnerBindings:
    generations: tuple[SessionCapabilityOwnerGenerationBinding, ...]
    command_registry: SessionCommandGenerationRegistry | None
    tool_slots: tuple[DeferredToolRegistrationSlot, ...]


_ToolOwnerBinding = tuple[
    Callable[[DeferredToolRegistrationSlot], SessionCapabilityOwnerGenerationBinding],
    type[DeferredToolRegistrationSlot],
]


def prepare_session_owner_bindings(
    *,
    require_command_registry: bool,
    base_tool: _ToolOwnerBinding | None,
    base_command: Callable[
        [SessionCommandGenerationRegistry], SessionCapabilityOwnerGenerationBinding
    ] | None,
    capability_tools: tuple[_ToolOwnerBinding, ...],
) -> PreparedOwnerBindings:
    """Prepare exact generation bindings before any Session registration is published."""
    command_registry = (
        SessionCommandGenerationRegistry() if require_command_registry else None
    )
    generations: list[SessionCapabilityOwnerGenerationBinding] = []
    base_slot = None
    if base_tool is not None:
        bind, slot_type = base_tool
        base_slot = slot_type()
        generations.append(bind(base_slot))
    if base_command is not None:
        assert command_registry is not None
        generations.append(base_command(command_registry))

    slots: list[DeferredToolRegistrationSlot] = []
    for bind, slot_type in capability_tools:
        slot = slot_type()
        generations.append(bind(slot))
        slots.append(slot)
    if base_slot is not None:
        slots.append(base_slot)
    return PreparedOwnerBindings(tuple(generations), command_registry, tuple(slots))

@dataclass(frozen=True, slots=True)
class _ToolPackSourceInfo:
    plugin_id: str
    contribution_id: str
    admission_fingerprint: str


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

    def stage(
        captures: tuple[SessionCapabilityConsumerCapture, ...],
    ) -> RegistrationScopeGeneration:
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
        return RegistrationScopeGeneration(scope, generation_family)

    return bind_owner_registration_scope(
        bound_admission,
        authority_gate,
        stage=stage,
        generation_family=generation_family,
        label=label,
        disposal_error=disposal_error,
        retirement_contribution_id=lambda: inputs.admission.contribution_id,
    )


def _require_tool_consumer(
    captures: tuple[SessionCapabilityConsumerCapture, ...],
    admission: OwnerContributionAdmissionRecord,
    requirement: CapabilityRequirement,
    *,
    label: str,
    invalid_capture_type_error: bool = True,
) -> SessionCapabilityConsumerCapture:
    if len(captures) != 1:
        raise ValueError(f"{label} owner requires one Consumer capture")
    [capture] = captures
    if not isinstance(capture, SessionCapabilityConsumerCapture):
        if invalid_capture_type_error:
            raise TypeError(f"{label} owner Consumer capture is invalid")
        raise ValueError(f"{label} owner received another Consumer")
    if (
        capture.entry.admission_fingerprint != admission.fingerprint
        or capture.entry.requirement != requirement
    ):
        raise ValueError(f"{label} owner received another Consumer")
    return capture


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


def stage_workspace_tool_generation(
    admission: OwnerContributionAdmissionRecord,
    scope_id: str,
    captures: tuple[SessionCapabilityConsumerCapture, ...],
    *,
    requirement: CapabilityRequirement,
    options: ToolsOptions,
    tool_names: Callable[[], tuple[str, ...]],
    registration: SessionToolRegistrationPort,
    build_definitions: Callable[[ToolsOptions], list[ToolDefinition]],
    generation_family: object,
    label: str,
    stale_generation_message: str,
    failed_generation_message: str,
) -> RegistrationScopeGeneration:
    """Capture admitted operations and stage one revocable registration generation."""
    capture = _require_tool_consumer(
        captures, admission, requirement, label=label, invalid_capture_type_error=False
    )
    options, operation_set = workspace_options_from_capture(
        options, capture, label=label, stale_message=stale_generation_message
    )
    names = tool_names()
    scope = RegistrationScope(
        product_contribution_registration_owner(admission, scope_id)
    )
    source_info = _ToolPackSourceInfo(
        admission.plugin_id, admission.contribution_id, admission.fingerprint
    )
    try:
        by_name = {item.name: item for item in build_definitions(options)}
        if set(by_name) != set(names):
            raise RuntimeError(f"{label} catalog changed admitted identities")
        for name in names:
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
    return RegistrationScopeGeneration(
        scope,
        generation_family,
        invalidate=partial(operation_set.invalidate, stale_generation_message),
    )


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
    _generation_family: ClassVar[Callable[[], object]]

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

    def bind(
        self,
        registration: SessionToolRegistrationPort,
    ) -> SessionCapabilityOwnerGenerationBinding:
        """Claim registration once; the Graph still stages the complete pack."""
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
            definitions_from_captures=self._definitions_from_captures,
            generation_family=type(self)._generation_family(),
            label=self._label,
            disposal_error=type(self)._disposal_error,
        )

    def _tool_definitions(
        self, facets: CapabilityFacetSet
    ) -> tuple[ToolDefinition, ...]:
        raise NotImplementedError

    def _definitions_from_captures(
        self,
        captures: tuple[SessionCapabilityConsumerCapture, ...],
    ) -> tuple[ToolDefinition, ...]:
        capture = _require_tool_consumer(
            captures, self.admission, self._requirement, label=self._label
        )
        definitions = self._tool_definitions(capture.facets)
        if tuple(item.name for item in definitions) != self._tool_names:
            raise RuntimeError(f"{self._label} factories changed admitted identities")
        return definitions


_DeferredAssemblyT = TypeVar(
    "_DeferredAssemblyT", bound=_PublishedCapabilityComposition
)
_DeferredAccessT = TypeVar("_DeferredAccessT")
_DeferredOperation = ParamSpec("_DeferredOperation")
_DeferredResult = TypeVar("_DeferredResult")


@dataclass(slots=True)
class _DeferredSessionCapabilityGeneration(
    Generic[_DeferredAssemblyT, _DeferredAccessT]
):
    """Publish one admitted plugin in a child graph borrowing the Session workspace."""

    _product_id: ClassVar[str]
    _plugin_id: ClassVar[str]
    _label: ClassVar[str]
    _runtime_claim_prefix: ClassVar[str]
    _child_runtime_prefix: ClassVar[str]
    _capability: ClassVar[CapabilityDefinition]
    _tool_requirement: ClassVar[CapabilityRequirement]
    _session_requirement: ClassVar[CapabilityRequirement]
    _tool_owner_type: ClassVar[type[_ReservedToolPackOwner]]

    session_id: str
    profile_fingerprint: str
    workspace_binding: CapabilityBundleProviderBinding
    registration: SessionToolRegistrationPort
    assembly_factory: Callable[[], Awaitable[_DeferredAssemblyT]] = field(repr=False)
    current_selection_check: Callable[[], None] | None = field(default=None, repr=False)
    assembly: _DeferredAssemblyT | None = field(default=None, init=False, repr=False)
    graph: RuntimeCapabilityGraphRuntime | None = field(
        default=None, init=False, repr=False
    )
    prepared_component: PreparedSessionCapabilityComponent | None = field(
        default=None, init=False, repr=False
    )
    generations: tuple[StagedSessionCapabilityOwnerGeneration, ...] = field(
        default=(), init=False, repr=False
    )
    capture: CapabilityFacetSet | None = field(default=None, init=False, repr=False)
    access: _DeferredAccessT | None = field(default=None, init=False, repr=False)
    receipts: dict[str, tuple[OwnerGenerationRetirementReceipt, ...]] = field(
        default_factory=dict, init=False, repr=False
    )
    _binder: RuntimeCapabilityGraphBinder = field(
        default_factory=RuntimeCapabilityGraphBinder, init=False, repr=False
    )
    _published: bool = field(default=False, init=False, repr=False)
    _closed: bool = field(default=False, init=False, repr=False)
    _component_start: CapabilityComponentAdmissionStart | None = field(
        default=None, init=False, repr=False
    )
    _owner_start: SessionCapabilityOwnerAdmissionStart | None = field(
        default=None, init=False, repr=False
    )

    async def prepare(self) -> None:
        if self.assembly is not None or self.graph is not None:
            raise RuntimeError(
                f"deferred {self._label} generation was already prepared"
            )
        assembly = await self.assembly_factory()
        self.assembly = assembly
        self.assert_current()
        if set(assembly.tool_owners) != {self._plugin_id}:
            raise ValueError(
                f"deferred {self._label} generation requires one selected Tool owner"
            )
        owner = assembly.tool_owners.get(self._plugin_id)
        if not isinstance(owner, self._tool_owner_type):
            raise TypeError(f"deferred {self._label} Tool owner is invalid")
        requests = assembly.session_inputs.component_requests
        if len(requests) != 1:
            raise ValueError(f"deferred {self._label} requires one Component request")
        request = requests[0]
        if not isinstance(request, SessionCapabilityComponentRequest):
            raise ValueError(f"deferred {self._label} requires one Component request")
        if request.capability_id != self._capability.capability_id:
            raise ValueError(f"deferred Component request is not {self._label}")
        admissions = tuple(
            item
            for item in assembly.session_inputs.product_composition.catalog_admissions
            if item.plugin_id == self._plugin_id
        )
        if len(admissions) != 1:
            raise ValueError(f"deferred {self._label} requires one Tool admission")
        [admission] = admissions
        if self.workspace_binding.visibility_gates:
            raise ValueError(
                f"deferred {self._label} requires an ungated workspace binding"
            )
        await _run_sync(
            assembly.claim_runtime,
            f"{self._runtime_claim_prefix}:{self.session_id}",
        )
        component_host = assembly.component_host
        self._component_start = request.begin_admission(component_host)
        binding = owner.bind(self.registration)
        self._owner_start = binding.authority_gate.begin(admission)
        self.prepared_component = await _run_sync(
            request.prepare_component, component_host, self._component_start
        )
        graph = RuntimeCapabilityGraphRuntime(
            product_id=self._product_id,
            runtime_id=f"{self._child_runtime_prefix}:{self.session_id}",
            profile_fingerprint=self.profile_fingerprint,
        )
        self.graph = graph
        plan = RuntimeCapabilityGraphPlanner().plan(
            CapabilityGraphPlanRequest(
                product_id=self._product_id,
                roots=(self._capability.capability_id,),
                definitions=(
                    WORKSPACE_CAPABILITY_DEFINITION,
                    self._capability,
                ),
                providers=(
                    self.workspace_binding.provider,
                    request.resolved.provider,
                ),
            )
        )
        await self._binder.bind(
            graph,
            plan,
            (
                replace(self.workspace_binding, dispose=None),
                self.prepared_component.binding,
            ),
        )
        self.prepared_component.commit_after_graph_publication()
        entries = tuple(
            item
            for item in assembly.session_inputs.product_composition.consumer_requirements.satisfied_entries
            if item.admission_fingerprint == admission.fingerprint
        )
        if len(entries) != 1 or entries[0].requirement != self._tool_requirement:
            raise ValueError(f"deferred {self._label} Tool Consumer entry changed")
        capture = SessionCapabilityConsumerCapture(
            entry=entries[0],
            facets=graph.capture(self._tool_requirement),
        )
        try:
            self.generations = await stage_session_capability_owner_generations(
                admissions=(admission,),
                bindings=(binding,),
                captures=(capture,),
                started_admissions=(self._owner_start,),
            )
        except SessionCapabilityOwnerGenerationStagingError as error:
            self.generations = error.pending_generations
            raise
        self.capture = graph.capture(self._session_requirement)
        self.access = self._access_from(self.capture)
        self.receipts = {
            plugin_id: tuple(
                capture_owner_generation_receipts(
                    self.generations, plugin_id, prepared=True
                )
            )
            for plugin_id in assembly.management_leases
        }
        await _run_sync(assembly.prepare_owner_generations, self.receipts)

    def _access_from(self, capture: CapabilityFacetSet) -> _DeferredAccessT:
        raise NotImplementedError

    def publish(self) -> None:
        if self.assembly is None or self.access is None or not self.generations:
            raise RuntimeError(f"deferred {self._label} generation is not prepared")
        if self._published:
            return
        self.assert_current()
        commit_session_capability_owner_generations(self.generations)
        self.assembly.publish_owner_generations(self.receipts)
        self._published = True
        self.assembly.close()
        self._release_starts()

    def assert_current(self) -> None:
        check = self.current_selection_check
        if check is not None:
            check()

    async def dispose(self) -> None:
        if self._closed:
            return
        self._release_starts()
        if self.generations:
            await dispose_session_capability_owner_generations(self.generations)
            self.generations = ()
        graph = self.graph
        if graph is not None:
            codes = await self._binder.dispose(graph)
            if codes or graph.has_pending_retirements:
                raise RuntimeError(
                    f"deferred {self._label} graph retirement remains incomplete: "
                    + ", ".join(codes)
                )
        component = self.prepared_component
        if component is not None:
            await component.abort_uncommitted()
            self.prepared_component = None
        assembly = self.assembly
        if assembly is not None:
            assembly.close()
            if self.receipts:
                assembly.retire_owner_generations(self.receipts)
                self.receipts = {}
            assembly.confirm_runtime_retirement(
                graph_closed=graph is None or graph.is_closed,
                runtime_was_published=graph is not None and graph.snapshot is not None,
                graph_has_pending_retirements=(
                    graph.has_pending_retirements if graph is not None else False
                ),
                owner_generations_remaining=bool(self.generations),
                component_generations_remaining=False,
            )
            assembly.release_management()
            assembly.cleanup_private_state()
        self.capture = None
        self.access = None
        self._closed = True

    def _release_starts(self) -> None:
        component_start = self._component_start
        if component_start is not None:
            component_start.host.abort_admission_start(component_start)
            self._component_start = None
        owner_start = self._owner_start
        if owner_start is not None:
            owner_start.authority_gate.abort(owner_start)
            self._owner_start = None


async def _run_sync(
    func: Callable[_DeferredOperation, _DeferredResult],
    *args: _DeferredOperation.args,
    **kwargs: _DeferredOperation.kwargs,
) -> _DeferredResult:
    task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
    return await _await_cancellation_atomic(task)
