from __future__ import annotations

import asyncio

from loushang.harness.host.remote_ui import RemoteUiContext


def test_remote_ui_context_records_state_and_emits_requests() -> None:
    emitted: list[dict[str, object]] = []
    context = RemoteUiContext(emitted.append)

    context.notify("Ready", "info")
    context.set_status("session", "active")
    context.set_widget("status", ["line 1"], placement="footer")
    context.set_title("Loushang")
    context.set_editor_text("draft")

    assert emitted == [
        {
            "type": "remote_ui_request",
            "id": emitted[0]["id"],
            "method": "notify",
            "message": "Ready",
            "notifyType": "info",
        },
        {
            "type": "remote_ui_request",
            "id": emitted[1]["id"],
            "method": "setStatus",
            "statusKey": "session",
            "statusText": "active",
        },
        {
            "type": "remote_ui_request",
            "id": emitted[2]["id"],
            "method": "setWidget",
            "widgetKey": "status",
            "widgetLines": ["line 1"],
            "widgetPlacement": "footer",
        },
        {
            "type": "remote_ui_request",
            "id": emitted[3]["id"],
            "method": "setTitle",
            "title": "Loushang",
        },
        {
            "type": "remote_ui_request",
            "id": emitted[4]["id"],
            "method": "set_editor_text",
            "text": "draft",
        },
    ]
    assert context.get_editor_text() == "draft"
    assert context.get_snapshot() == {
        "notifications": [{"message": "Ready", "notifyType": "info"}],
        "statuses": {"session": "active"},
        "widgets": {"status": {"lines": ["line 1"], "placement": "footer"}},
        "title": "Loushang",
        "editorText": "draft",
    }


def test_remote_ui_context_resolves_and_times_out_dialogs() -> None:
    emitted: list[dict[str, object]] = []
    context = RemoteUiContext(emitted.append)

    async def scenario() -> tuple[str | None, bool, str | None]:
        select = asyncio.create_task(context.select("Pick", ["one", "two"]))
        await asyncio.sleep(0)
        context.resolve_response({"id": emitted[-1]["id"], "value": "two"})
        confirmed = await context.confirm("Confirm", "Continue?", timeout=0.01)
        entered = await context.input("Name", timeout=0.01)
        return await select, confirmed, entered

    assert asyncio.run(scenario()) == ("two", False, None)


def test_remote_ui_context_accepts_a_synchronous_dialog_response() -> None:
    context: RemoteUiContext

    def emit(payload: dict[str, object]) -> None:
        context.resolve_response({"id": payload["id"], "value": "accepted"})

    context = RemoteUiContext(emit)

    assert asyncio.run(context.input("Name")) == "accepted"
