from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from loushang.coding.interaction.settings_profile import (
    CODING_SETTING_BINDINGS,
    CODING_SETTING_COPY,
)
from loushang.harnesstui.settings.schema import (
    BooleanSettingApplyOutcome,
    BooleanSettingFact,
    apply_boolean_setting,
    boolean_setting_facts,
)


class _SettingsManager:
    def __init__(self) -> None:
        self.values = {
            "terminal_progress": False,
            "show_images": True,
            "clear_on_shrink": False,
            "image_auto_resize": True,
            "block_images": False,
            "retry_enabled": True,
        }
        self.calls: list[tuple[str, bool]] = []

    def _set(self, name: str, enabled: bool) -> None:
        self.calls.append((name, enabled))
        self.values[name] = enabled

    def get_show_terminal_progress(self) -> bool:
        return self.values["terminal_progress"]

    def set_show_terminal_progress(self, enabled: bool) -> None:
        self._set("terminal_progress", enabled)

    def get_show_images(self) -> bool:
        return self.values["show_images"]

    def set_show_images(self, enabled: bool) -> None:
        self._set("show_images", enabled)

    def get_clear_on_shrink(self) -> bool:
        return self.values["clear_on_shrink"]

    def set_clear_on_shrink(self, enabled: bool) -> None:
        self._set("clear_on_shrink", enabled)

    def get_image_auto_resize(self) -> bool:
        return self.values["image_auto_resize"]

    def set_image_auto_resize(self, enabled: bool) -> None:
        self._set("image_auto_resize", enabled)

    def get_block_images(self) -> bool:
        return self.values["block_images"]

    def set_block_images(self, enabled: bool) -> None:
        self._set("block_images", enabled)

    def get_retry_enabled(self) -> bool:
        return self.values["retry_enabled"]

    def set_retry_enabled(self, enabled: bool) -> None:
        self._set("retry_enabled", enabled)


_SETTINGS = (
    (
        "terminal.progress",
        "Terminal progress",
        "terminal_progress",
        "true",
        "Terminal progress: on",
    ),
    ("terminal.show_images", "Show images", "show_images", "false", "Show images: off"),
    (
        "terminal.clear_on_shrink",
        "Clear on shrink",
        "clear_on_shrink",
        "true",
        "Clear on shrink: on",
    ),
    (
        "images.auto_resize",
        "Image auto-resize",
        "image_auto_resize",
        "false",
        "Image auto-resize: off",
    ),
    ("images.block_images", "Block images", "block_images", "true", "Block images: on"),
    ("retry.enabled", "Retry", "retry_enabled", "false", "Retry: off"),
)


def test_coding_settings_facts_read_all_available_manager_values() -> None:
    manager = _SettingsManager()

    facts = boolean_setting_facts(manager, CODING_SETTING_BINDINGS)

    assert facts == (
        BooleanSettingFact("terminal.progress", "Terminal progress", "false"),
        BooleanSettingFact("terminal.show_images", "Show images", "true"),
        BooleanSettingFact("terminal.clear_on_shrink", "Clear on shrink", "false"),
        BooleanSettingFact("images.auto_resize", "Image auto-resize", "true"),
        BooleanSettingFact("images.block_images", "Block images", "false"),
        BooleanSettingFact("retry.enabled", "Retry", "true"),
    )
    with pytest.raises(FrozenInstanceError):
        facts[0].value = "true"  # type: ignore[misc]


def test_coding_settings_facts_omit_unavailable_getters() -> None:
    assert boolean_setting_facts(None, CODING_SETTING_BINDINGS) == ()
    assert boolean_setting_facts(object(), CODING_SETTING_BINDINGS) == ()


@pytest.mark.parametrize(("item_id", "label", "field", "value", "message"), _SETTINGS)
def test_apply_coding_setting_writes_each_manager_setting(
    item_id: str,
    label: str,
    field: str,
    value: str,
    message: str,
) -> None:
    del label
    manager = _SettingsManager()

    outcome = apply_boolean_setting(
        manager,
        item_id,
        value,
        bindings=CODING_SETTING_BINDINGS,
        copy=CODING_SETTING_COPY,
    )

    enabled = value == "true"
    assert outcome == BooleanSettingApplyOutcome(matched=True, message=message)
    assert manager.values[field] is enabled
    assert manager.calls == [(field, enabled)]


@pytest.mark.parametrize(("item_id", "label", "field", "value", "message"), _SETTINGS)
def test_apply_coding_setting_rejects_invalid_values_without_writing(
    item_id: str,
    label: str,
    field: str,
    value: str,
    message: str,
) -> None:
    del field, value, message
    manager = _SettingsManager()

    outcome = apply_boolean_setting(
        manager,
        item_id,
        "yes",
        bindings=CODING_SETTING_BINDINGS,
        copy=CODING_SETTING_COPY,
    )

    assert outcome == BooleanSettingApplyOutcome(
        matched=True,
        message=f"Invalid {label} value.",
    )
    assert manager.calls == []


@pytest.mark.parametrize(("item_id", "label", "field", "value", "message"), _SETTINGS)
def test_apply_coding_setting_reports_unavailable_setters(
    item_id: str,
    label: str,
    field: str,
    value: str,
    message: str,
) -> None:
    del field, value, message

    assert apply_boolean_setting(
        None,
        item_id,
        "true",
        bindings=CODING_SETTING_BINDINGS,
        copy=CODING_SETTING_COPY,
    ) == BooleanSettingApplyOutcome(matched=True, message=f"{label} is not available.")


def test_apply_coding_setting_reports_unknown_ids_as_unmatched() -> None:
    manager = _SettingsManager()

    outcome = apply_boolean_setting(
        manager,
        "model.current",
        "true",
        bindings=CODING_SETTING_BINDINGS,
        copy=CODING_SETTING_COPY,
    )

    assert outcome == BooleanSettingApplyOutcome(
        matched=False,
        message="Unknown setting: model.current",
    )
    assert manager.calls == []


def test_apply_coding_setting_accepts_case_insensitive_boolean_values() -> None:
    manager = _SettingsManager()

    outcome = apply_boolean_setting(
        manager,
        "terminal.progress",
        "TRUE",
        bindings=CODING_SETTING_BINDINGS,
        copy=CODING_SETTING_COPY,
    )

    assert outcome.message == "Terminal progress: on"
    assert manager.values["terminal_progress"] is True
