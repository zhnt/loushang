from __future__ import annotations

import pytest

from loushang.harnesstui.settings.schema import (
    BooleanSettingApplyOutcome,
    BooleanSettingBinding,
    BooleanSettingCopy,
    BooleanSettingFact,
    apply_boolean_setting,
    boolean_setting_facts,
)

_BINDINGS = (
    BooleanSettingBinding("feature.one", "Feature one", "get_one", "set_one", "One"),
    BooleanSettingBinding("feature.two", "Feature two", "get_two", "set_two", "Two"),
)
_COPY = BooleanSettingCopy(
    unknown=lambda item_id: f"missing<{item_id}>",
    invalid=lambda binding: f"invalid<{binding.label}>",
    unavailable=lambda binding: f"unavailable<{binding.status_label}>",
    applied=lambda binding, enabled: f"applied<{binding.id}:{enabled}>",
)


class _Manager:
    def __init__(self) -> None:
        self.one = False
        self.calls: list[bool] = []

    def get_one(self) -> bool:
        return self.one

    def set_one(self, enabled: bool) -> None:
        self.one = enabled
        self.calls.append(enabled)


def test_boolean_setting_facts_read_only_available_product_bindings() -> None:
    assert boolean_setting_facts(_Manager(), _BINDINGS) == (
        BooleanSettingFact("feature.one", "Feature one", "false"),
    )
    assert boolean_setting_facts(None, _BINDINGS) == ()


@pytest.mark.parametrize("value", ("true", "TRUE"))
def test_apply_boolean_setting_parses_and_applies_with_product_copy(value: str) -> None:
    manager = _Manager()

    outcome = apply_boolean_setting(
        manager,
        "feature.one",
        value,
        bindings=_BINDINGS,
        copy=_COPY,
    )

    assert outcome == BooleanSettingApplyOutcome(
        matched=True,
        message="applied<feature.one:True>",
    )
    assert manager.calls == [True]


def test_apply_boolean_setting_preserves_unmatched_invalid_and_unavailable_states() -> (
    None
):
    manager = _Manager()

    unmatched = apply_boolean_setting(
        manager,
        "feature.missing",
        "true",
        bindings=_BINDINGS,
        copy=_COPY,
    )
    invalid = apply_boolean_setting(
        manager,
        "feature.one",
        "yes",
        bindings=_BINDINGS,
        copy=_COPY,
    )
    unavailable = apply_boolean_setting(
        manager,
        "feature.two",
        "false",
        bindings=_BINDINGS,
        copy=_COPY,
    )

    assert unmatched == BooleanSettingApplyOutcome(False, "missing<feature.missing>")
    assert invalid == BooleanSettingApplyOutcome(True, "invalid<Feature one>")
    assert unavailable == BooleanSettingApplyOutcome(True, "unavailable<Two>")
    assert manager.calls == []
