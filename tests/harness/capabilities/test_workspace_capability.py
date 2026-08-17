from __future__ import annotations

import hashlib

import pytest

from loushang.harness.capabilities.graph_binding import RuntimeCapabilityGraphBinder
from loushang.harness.capabilities.graph_planning import (
    CapabilityGraphPlanRequest,
    RuntimeCapabilityGraphPlanner,
)
from loushang.harness.capabilities.graph_runtime import RuntimeCapabilityGraphRuntime
from loushang.harness.capabilities.workspace_contracts import (
    WORKSPACE_CAPABILITY_DEFINITION,
    WORKSPACE_PROCESS_REQUIREMENT,
    WORKSPACE_TOOL_REQUIREMENT,
)
from loushang.harness.capabilities.workspace_process_consumer import (
    WorkspaceProcessCapabilityConsumer,
)
from loushang.harness.capabilities.workspace_provider import (
    workspace_capability_provider_binding,
)
from loushang.harness.capabilities.workspace_tool_consumer import (
    WorkspaceToolCapabilityConsumer,
)
from loushang.harness.workspace.operations import LocalToolOperations, resolve_operation


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class _AuthorizedLauncher:
    async def start(self, request, *, correlation_id, signal=None):  # type: ignore[no-untyped-def]
        del request, correlation_id, signal
        raise AssertionError("the authority seam is tested without starting a process")


def test_non_coding_product_swaps_workspace_provider_without_consumer_changes(
    tmp_path,
) -> None:
    import asyncio

    asyncio.run(
        _non_coding_product_swaps_workspace_provider_without_consumer_changes(tmp_path)
    )


async def _non_coding_product_swaps_workspace_provider_without_consumer_changes(
    tmp_path,
) -> None:
    first_operations = LocalToolOperations()
    second_operations = LocalToolOperations()
    first_launcher = _AuthorizedLauncher()
    second_launcher = _AuthorizedLauncher()
    first_binding = workspace_capability_provider_binding(
        operations=first_operations,
        process_launcher=first_launcher,
        scope_instance_id=f"workspace:{tmp_path}",
        binding_input_fingerprint=_sha("virtual-workspace-v1"),
        provider_id="research.virtual-workspace.v1",
        source_id="research-test",
    )
    planner = RuntimeCapabilityGraphPlanner()
    first_plan = planner.plan(
        CapabilityGraphPlanRequest(
            product_id="research",
            roots=("harness.workspace",),
            definitions=(WORKSPACE_CAPABILITY_DEFINITION,),
            providers=(first_binding.provider,),
        )
    )
    runtime = RuntimeCapabilityGraphRuntime(
        product_id="research",
        runtime_id="research-session",
        profile_fingerprint=_sha("existing-runtime-profile"),
    )
    binder = RuntimeCapabilityGraphBinder()
    await binder.bind(runtime, first_plan, (first_binding,))

    first_facets = runtime.capture(WORKSPACE_TOOL_REQUIREMENT)
    first_consumer = WorkspaceToolCapabilityConsumer(first_facets)
    first_options = first_consumer.apply()
    process_consumer = WorkspaceProcessCapabilityConsumer(
        runtime.capture(WORKSPACE_PROCESS_REQUIREMENT)
    )

    sample = tmp_path / "sample.txt"
    sample.write_text("virtual content", encoding="utf-8")
    assert first_options.read_operations is not None
    assert (
        await resolve_operation(first_options.read_operations.read_bytes(sample))
        == b"virtual content"
    )
    assert not hasattr(first_options.read_operations, "write_text")
    assert first_options.ls_operations is not None
    assert first_options.find_operations is first_options.grep_operations
    assert first_options.write_operations is not None
    assert first_options.edit_operations is not None
    assert process_consumer.launcher is not first_launcher
    assert not hasattr(process_consumer, "process_host")
    assert not hasattr(process_consumer, "sandbox_backend")

    second_binding = workspace_capability_provider_binding(
        operations=second_operations,
        process_launcher=second_launcher,
        scope_instance_id=f"workspace:{tmp_path}",
        binding_input_fingerprint=_sha("virtual-workspace-v2"),
        provider_id="research.virtual-workspace.v2",
        source_id="research-test",
    )
    second_plan = planner.plan(
        CapabilityGraphPlanRequest(
            product_id="research",
            roots=("harness.workspace",),
            definitions=(WORKSPACE_CAPABILITY_DEFINITION,),
            providers=(second_binding.provider,),
        )
    )
    await binder.bind(runtime, second_plan, (second_binding,))

    with pytest.raises(RuntimeError, match="stale"):
        first_facets.require("read")
    second_consumer = WorkspaceToolCapabilityConsumer(
        runtime.capture(WORKSPACE_TOOL_REQUIREMENT)
    )
    second_options = second_consumer.apply()
    assert second_options.read_operations is not None
    assert second_options.read_operations is not first_options.read_operations
