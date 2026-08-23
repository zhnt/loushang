from __future__ import annotations


def test_format_hotkeys_documents_current_inline_bindings() -> None:
    from loushang.coding.ui.hotkeys import format_hotkeys

    text = format_hotkeys()

    assert text == (
        "Hotkeys:\n"
        "Idle Enter: submit prompt\n"
        "Running Enter: steer current run\n"
        "Running Alt+Enter: queue follow-up\n"
        "Ctrl+J: insert newline\n"
        "Esc/Ctrl-C: abort running request\n"
        "Alt-Up: edit queued messages\n"
        "/quit or /exit: quit"
    )


def test_format_hotkeys_uses_resolved_conversation_followup_binding() -> None:
    from loushang.coding.ui.hotkeys import format_hotkeys

    text = format_hotkeys({"conversation.input.followUp": ("ctrl+enter",)})

    assert "Running Ctrl+Enter: queue follow-up" in text
    assert "Running Alt+Enter: queue follow-up" not in text


def test_format_hotkeys_reports_an_unavailable_followup_capability() -> None:
    from loushang.coding.ui.hotkeys import format_hotkeys
    from loushang.harnesstui.conversation.input_policy import (
        ConversationInputCapabilities,
    )

    text = format_hotkeys(
        capabilities=ConversationInputCapabilities(steer=True, follow_up=False)
    )

    assert "Running Enter: steer current run" in text
    assert "Running Alt+Enter: follow-up unavailable" in text
