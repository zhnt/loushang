from __future__ import annotations

import pytest

from loushang.harness.runtime import ProductRuntimeBindings, RuntimeBindingState


def test_product_runtime_bindings_default_tool_registration_fails_closed() -> None:
    async def set_active_tools(names: list[str]) -> None:
        del names

    async def set_model(model: object) -> None:
        del model

    bindings = ProductRuntimeBindings(
        cwd="/workspace",
        get_active_tool_names=lambda: [],
        get_model_selection=lambda: None,
        set_active_tools=set_active_tools,
        set_model=set_model,
        request_resource_refresh=lambda: None,
        shutdown=lambda: None,
        record_diagnostic=lambda diagnostic: None,
    )

    with pytest.raises(RuntimeError, match="live tool registration is not bound"):
        bindings.register_tool(object(), {"owner": "extension"})
    assert bindings.get_all_tools() == []


def test_product_runtime_bindings_preserves_existing_optional_positionals() -> None:
    async def set_active_tools(names: list[str]) -> None:
        del names

    async def set_model(model: object) -> None:
        del model

    bindings = ProductRuntimeBindings(
        "/workspace",
        lambda: [],
        lambda: None,
        set_active_tools,
        set_model,
        lambda: None,
        lambda: None,
        lambda _diagnostic: None,
        lambda _tool, _source_info: None,
        lambda: ["existing-tool"],
    )

    assert bindings.get_all_tools() == ["existing-tool"]
    assert bindings.bind_tool is None


def test_binding_lease_reads_refreshed_bindings_until_invalidated() -> None:
    state = RuntimeBindingState[dict[str, int]](
        unbound_message="not bound",
        stale_message="stale",
    )

    with pytest.raises(RuntimeError, match="not bound"):
        state.require()

    state.bind({"version": 1})
    lease = state.capture()
    state.refresh({"version": 2})

    assert state.is_bound is True
    assert lease.is_current is True
    assert lease.require() == {"version": 2}


def test_binding_invalidation_stales_old_leases_and_allows_new_ones() -> None:
    state = RuntimeBindingState("first", stale_message="old context")
    old = state.capture()

    state.invalidate()
    current = state.capture()

    assert old.is_current is False
    with pytest.raises(RuntimeError, match="old context"):
        old.require()
    assert current.require() == "first"


def test_binding_invalidation_can_replace_the_stale_diagnostic() -> None:
    state = RuntimeBindingState(object())
    lease = state.capture()

    state.invalidate("session replaced")

    with pytest.raises(RuntimeError, match="session replaced"):
        lease.require()
