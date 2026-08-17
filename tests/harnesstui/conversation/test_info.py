from __future__ import annotations

import asyncio

from loushang.harnesstui.conversation.info import ConversationInfoPresenter
from loushang.tui import InfoPanel


def test_info_presenter_prefers_handled_modal_without_inline_write() -> None:
    labels: list[str] = []
    panels: list[InfoPanel] = []

    async def emit(write, *, label: str) -> None:
        labels.append(label)
        write()

    async def present(panel: InfoPanel) -> bool:
        panels.append(panel)
        return True

    presenter = ConversationInfoPresenter(
        emit=emit,
        render_status=lambda _text: None,
        present_panel=present,
    )

    asyncio.run(
        presenter.show("Hotkeys", "Esc: abort", label="hotkeys:show", modal=True)
    )

    assert labels == []
    assert panels[0].title == "Hotkeys"
    assert panels[0].footer == "Press Enter to continue."


def test_info_presenter_falls_back_to_inline_panel_or_status() -> None:
    labels: list[str] = []
    panels: list[InfoPanel] = []
    statuses: list[str] = []

    async def emit(write, *, label: str) -> None:
        labels.append(label)
        write()

    async def decline(_panel: InfoPanel) -> bool:
        return False

    with_panel = ConversationInfoPresenter(
        emit=emit,
        render_status=statuses.append,
        render_panel=panels.append,
        present_panel=decline,
    )
    status_only = ConversationInfoPresenter(
        emit=emit,
        render_status=statuses.append,
    )

    asyncio.run(with_panel.show("Models", "kimi", label="models:show", modal=True))
    asyncio.run(status_only.show("Settings", "compact", label="settings:show"))

    assert labels == ["models:show", "settings:show"]
    assert [(panel.title, panel.footer) for panel in panels] == [("Models", "")]
    assert statuses == ["compact"]
