from __future__ import annotations

import asyncio

from loushang.ai.model import ModelSelection
from loushang.harness.extensions.runtime_bindings import (
    ExtensionRuntimeBindingFactory,
)
from loushang.harness.session.inspection import ContextUsage


def test_extension_runtime_binding_factory_wires_session_callbacks_and_ui_error_handler() -> (
    None
):
    calls: list[tuple[str, object]] = []

    class UiContext:
        def emit_extension_error(self, payload):
            calls.append(("error", payload))

    async def _set_active_tools(tool_names: list[str]) -> None:
        calls.append(("tools", list(tool_names)))

    async def _set_model(selection: ModelSelection) -> None:
        calls.append(("model", selection))

    async def _append_entry(custom_type: str, data: object | None = None) -> None:
        calls.append(("append", (custom_type, data)))

    async def _set_session_name(name: str | None) -> None:
        calls.append(("name", name))

    async def _set_label(entry_id: str, label: str | None) -> None:
        calls.append(("label", (entry_id, label)))

    async def _set_thinking_level(level: str) -> None:
        calls.append(("thinking", level))

    async def _send_message(message: object, options: object | None = None) -> None:
        calls.append(("message", (message, options)))

    async def _send_user_message(
        content: object, options: object | None = None
    ) -> None:
        calls.append(("user", (content, options)))

    factory = ExtensionRuntimeBindingFactory(
        get_cwd=lambda: "/tmp/project",
        session_manager="manager",
        model_registry="registry",
        get_active_tool_names=lambda: ["read"],
        get_all_tools=lambda: ["read-tool"],
        get_model_selection=lambda: ModelSelection(
            endpoint_id="test-endpoint", provider="faux", model_id="alpha"
        ),
        set_active_tools=_set_active_tools,
        set_model=_set_model,
        register_tool=lambda tool, source_info=None: calls.append(
            ("tool", (tool, source_info))
        ),
        append_entry=_append_entry,
        send_message=_send_message,
        send_user_message=_send_user_message,
        get_signal=lambda: "signal",
        set_session_name=_set_session_name,
        get_session_name=lambda: "Demo",
        set_label=_set_label,
        list_commands=lambda: ["cmd"],
        request_resource_refresh=lambda: calls.append(("refresh", None)),
        shutdown=lambda: calls.append(("shutdown", None)),
        record_diagnostic=lambda diagnostic: calls.append(("diagnostic", diagnostic)),
        abort=lambda: calls.append(("abort", None)),
        is_idle=lambda: False,
        has_pending_messages=lambda: True,
        get_context_usage=lambda: ContextUsage(
            message_count=1,
            assistant_message_count=0,
            user_message_count=1,
            tool_call_count=0,
            tool_result_count=0,
            custom_message_count=0,
            estimated_context_tokens=12,
            has_compaction=False,
            branch_depth=1,
            leaf_entry_id="entry-1",
            tokens=12,
            context_window=100,
            percent=12.0,
            reserve_tokens=10,
            compact_percent=80.0,
            keep_recent_tokens=5,
            percent_threshold_tokens=80,
            reserve_threshold_tokens=90,
            threshold_tokens=80,
            threshold_reason="compact_percent",
            source="assistant_usage",
            last_usage_index=0,
            stale_after_compaction=False,
            compactable=False,
            reason="usage below threshold",
        ),
        get_thinking_level=lambda: "high",
        set_thinking_level=_set_thinking_level,
        register_provider=lambda name, config: calls.append(
            ("register", (name, config))
        ),
        unregister_provider=lambda name: calls.append(("unregister", name)),
        set_extension_status=lambda key, text: calls.append(("status", (key, text))),
        get_footer_data_provider=lambda: "footer",
        compact=lambda instructions=None: asyncio.sleep(0),
        get_system_prompt=lambda: "system",
        wait_for_idle=lambda: asyncio.sleep(0),
        reload=lambda: asyncio.sleep(0),
        navigate_tree=lambda target_id, options=None: asyncio.sleep(
            0, result={"target": target_id, "options": options}
        ),
        fork=lambda entry_id, options=None: asyncio.sleep(
            0, result={"entry": entry_id, "options": options}
        ),
        new_session=lambda options=None: asyncio.sleep(0, result={"options": options}),
        switch_session=lambda path, options=None: asyncio.sleep(
            0, result={"path": path, "options": options}
        ),
        get_ui_context=UiContext,
    )

    bindings = factory.build()

    assert bindings.cwd == "/tmp/project"
    assert bindings.session_manager == "manager"
    assert bindings.model_registry == "registry"
    assert bindings.get_active_tool_names() == ["read"]
    assert bindings.get_all_tools() == ["read-tool"]
    assert bindings.get_model_selection() == ModelSelection(
        endpoint_id="test-endpoint", provider="faux", model_id="alpha"
    )
    assert bindings.get_signal() == "signal"
    assert bindings.is_idle() is False
    assert bindings.has_pending_messages() is True
    assert bindings.get_context_usage() == {
        "messageCount": 1,
        "assistantMessageCount": 0,
        "userMessageCount": 1,
        "toolCallCount": 0,
        "toolResultCount": 0,
        "customMessageCount": 0,
        "estimatedContextTokens": 12,
        "hasCompaction": False,
        "branchDepth": 1,
        "leafEntryId": "entry-1",
        "tokens": 12,
        "contextWindow": 100,
        "percent": 12.0,
        "reserveTokens": 10,
        "compactPercent": 80.0,
        "keepRecentTokens": 5,
        "percentThresholdTokens": 80,
        "reserveThresholdTokens": 90,
        "thresholdTokens": 80,
        "thresholdReason": "compact_percent",
        "source": "assistant_usage",
        "lastUsageIndex": 0,
        "staleAfterCompaction": False,
        "compactable": False,
        "reason": "usage below threshold",
    }
    assert bindings.get_thinking_level() == "high"
    assert bindings.get_system_prompt() == "system"
    assert bindings.footer_data_provider == "footer"

    assert bindings.on_error is not None
    bindings.on_error({"message": "boom"})
    asyncio.run(bindings.set_active_tools(["bash"]))
    bindings.register_tool("dynamic-tool", {"source": "test"})
    asyncio.run(bindings.send_user_message("hi", {"deliverAs": "steer"}))
    asyncio.run(bindings.set_label("entry-1", "label"))

    assert calls == [
        ("error", {"message": "boom"}),
        ("tools", ["bash"]),
        ("tool", ("dynamic-tool", {"source": "test"})),
        ("user", ("hi", {"deliverAs": "steer"})),
        ("label", ("entry-1", "label")),
    ]
