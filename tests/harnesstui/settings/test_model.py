from __future__ import annotations

from loushang.harnesstui.selection.catalog import ModelChoice
from loushang.harnesstui.settings.model import ModelPage
from loushang.tui import InputEvent, InputIntent, RenderConstraints
from loushang.tui.cell_width import strip_control_sequences


def _choice(value: str, *, description: str = "") -> ModelChoice:
    return ModelChoice(
        label=value,
        value=value,
        selection=object(),
        description=description,
    )


def test_model_page_filters_and_returns_neutral_setting_intent() -> None:
    page = ModelPage(
        (_choice("provider/first"), _choice("provider/second")),
        current_value="provider/first",
    )
    page.focus()

    assert page.handle_input(InputEvent(kind="text", text="second")) is True
    assert page.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="setting",
        text="model.current",
        note="provider/second",
    )


def test_model_page_updates_choices_without_replacing_public_list() -> None:
    page = ModelPage((_choice("provider/first"),))
    public_list = page.models

    page.set_choices(
        (_choice("provider/second", description="Second model"),),
        current_value="provider/second",
    )

    assert page.models is public_list
    assert page.models.active_item is not None
    assert page.models.active_item.key == "provider/second"
    assert page.models.active_item.value == "current"


def test_model_page_preserves_unavailable_copy_and_tab_fallback() -> None:
    page = ModelPage((), error="catalog failed")

    lines = tuple(
        strip_control_sequences(line.text)
        for line in page.render(RenderConstraints(width=40, max_height=4)).lines
    )

    assert lines == ("Model selection unavailable", "catalog failed")
    assert page.editor_input_target() is None
    assert page.handle_input(InputEvent(kind="key", key="left")) is True
