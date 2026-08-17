from __future__ import annotations

import asyncio

import pytest

from loushang.harness.resources.source import SourceInfo
from loushang.harness.runtime import (
    BoundProductRuntimeContext,
    ProductRuntimeBindings,
    RegistrationIdentity,
    RegistrationLease,
    RegistrationOwner,
    RuntimeBindingState,
    UnboundProductRuntimeContext,
)


def _research_bindings(
    *, cwd: str, active_tools: list[str], calls: list[tuple[str, object]]
) -> ProductRuntimeBindings:
    async def set_active_tools(names: list[str]) -> None:
        calls.append(("tools", names))

    async def set_model(selection: object) -> None:
        calls.append(("model", selection))

    async def append_entry(custom_type: str, data: object | None) -> None:
        calls.append(("entry", (custom_type, data)))

    async def set_session_name(name: str | None) -> None:
        calls.append(("session_name", name))

    async def set_label(entry_id: str, label: str | None) -> None:
        calls.append(("label", (entry_id, label)))

    async def set_thinking_level(level: str) -> None:
        calls.append(("thinking", level))

    async def compact(instructions: str | None) -> object:
        calls.append(("compact", instructions))
        return {"summary": "research summary"}

    return ProductRuntimeBindings(
        cwd=cwd,
        get_active_tool_names=lambda: list(active_tools),
        get_model_selection=lambda: {"provider": "example", "model": "research"},
        set_active_tools=set_active_tools,
        set_model=set_model,
        append_entry=append_entry,
        set_session_name=set_session_name,
        set_label=set_label,
        set_thinking_level=set_thinking_level,
        request_resource_refresh=lambda: calls.append(("refresh", None)),
        shutdown=lambda: calls.append(("shutdown", None)),
        record_diagnostic=lambda diagnostic: calls.append(("diagnostic", diagnostic)),
        compact=compact,
        get_system_prompt=lambda: "You are a research assistant.",
    )


def test_bound_context_exposes_live_product_capabilities_without_coding() -> None:
    calls: list[tuple[str, object]] = []
    state = RuntimeBindingState(
        _research_bindings(cwd="/tmp/research", active_tools=["search"], calls=calls)
    )
    context = BoundProductRuntimeContext(
        state.capture(), get_flag_value={"citations": True}.get
    )

    async def scenario() -> None:
        await context.set_active_tools(["search", "read"])
        await context.set_model({"provider": "example", "model": "deep-research"})
        await context.append_entry("research.note", {"text": "finding"})
        await context.set_session_name("Research")
        await context.set_label("entry-1", "source")
        await context.set_thinking_level("high")
        result = await context.compact({"customInstructions": "preserve citations"})
        assert result == {"summary": "research summary"}

    asyncio.run(scenario())

    assert context.cwd == "/tmp/research"
    assert context.get_active_tool_names() == ["search"]
    assert context.get_flag("citations") is True
    assert context.get_system_prompt() == "You are a research assistant."
    assert calls == [
        ("tools", ["search", "read"]),
        ("model", {"provider": "example", "model": "deep-research"}),
        ("entry", ("research.note", {"text": "finding"})),
        ("session_name", "Research"),
        ("label", ("entry-1", "source")),
        ("thinking", "high"),
        ("compact", "preserve citations"),
    ]


def test_bound_context_reads_refreshes_and_honors_invalidation() -> None:
    calls: list[tuple[str, object]] = []
    state = RuntimeBindingState(
        _research_bindings(cwd="/tmp/first", active_tools=["search"], calls=calls),
        stale_message="research session replaced",
    )
    context = BoundProductRuntimeContext(state.capture())

    state.refresh(
        _research_bindings(
            cwd="/tmp/second", active_tools=["search", "read"], calls=calls
        )
    )
    assert context.cwd == "/tmp/second"
    assert context.get_active_tool_names() == ["search", "read"]

    state.invalidate()
    with pytest.raises(RuntimeError, match="research session replaced"):
        _ = context.cwd


def test_bound_context_prefers_owner_aware_live_tool_binding() -> None:
    calls: list[tuple[object, str, object | None]] = []
    owner = RegistrationOwner(
        owner_kind="extension",
        owner_id="demo",
        runtime_id="session-1",
        generation=0,
    )

    def bind_tool(
        tool: object,
        owner_id: str,
        source_info: object | None,
    ) -> RegistrationLease:
        calls.append((tool, owner_id, source_info))
        return RegistrationLease(
            owner=owner,
            identity=RegistrationIdentity.create(
                surface="tool",
                public_key="dynamic",
            ),
            dispose=lambda: None,
        )

    bindings = _research_bindings(cwd="/tmp/research", active_tools=[], calls=[])
    bindings.bind_tool = bind_tool
    bindings.register_tool = lambda _tool, _source_info: pytest.fail(
        "legacy tool registration must not be used"
    )
    source_info = SourceInfo(path="<inline:demo>")
    context = BoundProductRuntimeContext(
        RuntimeBindingState(bindings).capture(),
        source_info,
        tool_owner_id="demo",
    )
    tool = object()

    context.register_tool(tool)

    assert calls == [(tool, "demo", source_info)]


def test_unbound_context_has_conservative_defaults() -> None:
    context = UnboundProductRuntimeContext(
        cwd="/tmp/research",
        get_flag_value={"citations": "required"}.get,
    )

    assert context.cwd == "/tmp/research"
    assert context.get_flag("citations") == "required"
    assert context.get_all_tools() == []
    assert context.has_ui is False
    assert context.get_editor_text() == ""
    asyncio.run(context.append_entry("ignored"))
    asyncio.run(context.set_session_name("ignored"))
    asyncio.run(context.set_label("entry-1", "ignored"))
    asyncio.run(context.set_thinking_level("high"))
    with pytest.raises(RuntimeError, match="Extension runtime is not bound"):
        asyncio.run(context.exec_command("pwd"))


def test_product_runtime_binding_mutation_defaults_are_awaitable() -> None:
    async def set_active_tools(names: list[str]) -> None:
        del names

    async def set_model(selection: object) -> None:
        del selection

    bindings = ProductRuntimeBindings(
        cwd="/tmp/research",
        get_active_tool_names=lambda: [],
        get_model_selection=lambda: None,
        set_active_tools=set_active_tools,
        set_model=set_model,
        request_resource_refresh=lambda: None,
        shutdown=lambda: None,
        record_diagnostic=lambda diagnostic: None,
    )

    async def scenario() -> None:
        await bindings.append_entry("ignored", None)
        await bindings.set_session_name("ignored")
        await bindings.set_label("entry-1", "ignored")
        await bindings.set_thinking_level("high")

    asyncio.run(scenario())
