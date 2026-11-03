"""One freshly admitted LSP Provider in a Session-owned child graph."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from typing import Never

from loushang.coding._capability_plugin_composition import (
    CodingCapabilityPluginCompositionAssembly,
)
from loushang.coding.lsp._plugin_tool_owner import (
    CodingLspToolOwner,
    CodingLspToolRegistrationPort,
)
from loushang.coding.lsp._provider_api import (
    CODING_LSP_CAPABILITY_DEFINITION,
    CODING_LSP_SESSION_REQUIREMENT,
    CODING_LSP_TOOL_RUNTIME_REQUIREMENT,
    CodingLspSessionCapabilityConsumer,
)
from loushang.coding.lsp.runtime import CodingLspSessionAccess
from loushang.coding.lsp.tools import (
    create_document_outline_tool_definition,
    create_inspect_symbol_tool_definition,
)
from loushang.coding.product_plan import CODING_PRODUCT_ID
from loushang.harness.capabilities.component_host import (
    CapabilityComponentAdmissionStart,
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
)
from loushang.harness.runtime._owned_tasks import _await_cancellation_atomic
from loushang.harness.runtime.registration import OwnerGenerationRetirementReceipt
from loushang.harness.session.capability_composition_inputs import (
    PreparedSessionCapabilityComponent,
    SessionCapabilityComponentRequest,
    SessionCapabilityConsumerCapture,
    SessionCapabilityOwnerAdmissionStart,
    SessionCapabilityOwnerGenerationBinding,
    SessionCapabilityOwnerGenerationStagingError,
    StagedSessionCapabilityOwnerGeneration,
    commit_session_capability_owner_generations,
    dispose_session_capability_owner_generations,
    stage_session_capability_owner_generations,
)
from loushang.harness.tools.core import project_tool_definition

_PLUGIN_ID = "coding.lsp.default"


def dormant_lsp_tool_infos() -> list[dict[str, object]]:
    """Product-owned discovery metadata without creating a Provider or Tool lease."""

    runtime = _DormantLspToolRuntime()
    return [
        {
            **project_tool_definition(definition),
            "sourceInfo": {
                "path": f"<coding.lsp.default:{definition.name}>",
                "source": "plugin",
                "scope": "project",
                "origin": "top-level",
                "baseDir": None,
            },
        }
        for definition in (
            create_document_outline_tool_definition(runtime),
            create_inspect_symbol_tool_definition(runtime),
        )
    ]


class _DormantLspToolRuntime:
    async def inspect_symbol(self, **_kwargs: object) -> Never:
        raise RuntimeError("activate the LSP tools before calling them")

    async def document_outline(self, **_kwargs: object) -> Never:
        raise RuntimeError("activate the LSP tools before calling them")


@dataclass(slots=True)
class CodingDeferredLspGeneration:
    """Own selection through retirement without mutating the parent graph."""

    session_id: str
    profile_fingerprint: str
    workspace_binding: CapabilityBundleProviderBinding
    registration: CodingLspToolRegistrationPort
    assembly_factory: Callable[
        [], Awaitable[CodingCapabilityPluginCompositionAssembly]
    ] = field(repr=False)
    current_selection_check: Callable[[], None] | None = field(
        default=None, repr=False
    )
    assembly: CodingCapabilityPluginCompositionAssembly | None = field(
        default=None, init=False, repr=False
    )
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
    access: CodingLspSessionAccess | None = field(default=None, init=False, repr=False)
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
    _owner_binding: SessionCapabilityOwnerGenerationBinding | None = field(
        default=None, init=False, repr=False
    )
    _owner_start: SessionCapabilityOwnerAdmissionStart | None = field(
        default=None, init=False, repr=False
    )

    async def prepare(self) -> None:
        if self.assembly is not None or self.graph is not None:
            raise RuntimeError("deferred LSP generation was already prepared")
        assembly = await self.assembly_factory()
        self.assembly = assembly
        self.assert_current()
        if set(assembly.tool_owners) != {_PLUGIN_ID}:
            raise ValueError("deferred LSP generation requires one selected Tool owner")
        owner = assembly.tool_owner_for(_PLUGIN_ID)
        if not isinstance(owner, CodingLspToolOwner):
            raise TypeError("deferred LSP Tool owner is invalid")
        requests = assembly.session_inputs.component_requests
        if len(requests) != 1:
            raise ValueError("deferred LSP requires one Component request")
        request = requests[0]
        if not isinstance(request, SessionCapabilityComponentRequest):
            raise ValueError("deferred LSP requires one Component request")
        if request.capability_id != CODING_LSP_CAPABILITY_DEFINITION.capability_id:
            raise ValueError("deferred Component request is not LSP")
        admissions = tuple(
            item
            for item in assembly.session_inputs.product_composition.catalog_admissions
            if item.plugin_id == _PLUGIN_ID
        )
        if len(admissions) != 1:
            raise ValueError("deferred LSP requires one Tool admission")
        [admission] = admissions
        if self.workspace_binding.visibility_gates:
            raise ValueError("deferred LSP requires an ungated workspace binding")
        await _run_sync(
            assembly.claim_runtime,
            f"coding-session-runtime:{self.session_id}",
        )
        component_host = assembly.component_host
        self._component_start = component_host.begin_admission(
            request.resolved,
            owner_snapshot=request.owner_snapshot,
            trust_snapshot=request.trust_snapshot,
            decision_id=request.activation_decision_id,
        )
        binding = owner.bind(self.registration)
        self._owner_binding = binding
        self._owner_start = binding.authority_gate.begin(admission)
        self.prepared_component = await _run_sync(
            component_host.prepare_component,
            request.resolved,
            package=request.package,
            owner_snapshot=request.owner_snapshot,
            trust_snapshot=request.trust_snapshot,
            decision_id=request.activation_decision_id,
            admission_start=self._component_start,
        )
        graph = RuntimeCapabilityGraphRuntime(
            product_id=CODING_PRODUCT_ID,
            runtime_id=f"coding-lsp:{self.session_id}",
            profile_fingerprint=self.profile_fingerprint,
        )
        self.graph = graph
        plan = RuntimeCapabilityGraphPlanner().plan(
            CapabilityGraphPlanRequest(
                product_id=CODING_PRODUCT_ID,
                roots=(CODING_LSP_CAPABILITY_DEFINITION.capability_id,),
                definitions=(
                    WORKSPACE_CAPABILITY_DEFINITION,
                    CODING_LSP_CAPABILITY_DEFINITION,
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
        if (
            len(entries) != 1
            or entries[0].requirement != CODING_LSP_TOOL_RUNTIME_REQUIREMENT
        ):
            raise ValueError("deferred LSP Tool Consumer entry changed")
        capture = SessionCapabilityConsumerCapture(
            entry=entries[0],
            facets=graph.capture(CODING_LSP_TOOL_RUNTIME_REQUIREMENT),
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
        self.capture = graph.capture(CODING_LSP_SESSION_REQUIREMENT)
        self.access = CodingLspSessionCapabilityConsumer(self.capture).access
        self.receipts = {
            plugin_id: tuple(
                generation.capture_prepared_retirement_receipt()
                for generation in self.generations
                if generation.binding.plugin_id == plugin_id
            )
            for plugin_id in assembly.management_leases
        }
        await _run_sync(assembly.prepare_owner_generations, self.receipts)

    def publish(self) -> None:
        if self.assembly is None or self.access is None or not self.generations:
            raise RuntimeError("deferred LSP generation is not prepared")
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
                    "deferred LSP graph retirement remains incomplete: "
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
        assembly = self.assembly
        component_start = self._component_start
        if assembly is not None and component_start is not None:
            assembly.component_host.abort_admission_start(component_start)
            self._component_start = None
        binding = self._owner_binding
        owner_start = self._owner_start
        if binding is not None and owner_start is not None:
            binding.authority_gate.abort(owner_start)
            self._owner_start = None


async def _run_sync(func: Callable[..., object], *args: object, **kwargs: object):
    task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
    return await _await_cancellation_atomic(task)
