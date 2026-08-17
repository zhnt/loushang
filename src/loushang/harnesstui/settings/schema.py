from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BooleanSettingFact:
    """Renderer-neutral value read from a product boolean setting."""

    id: str
    label: str
    value: str


@dataclass(frozen=True, slots=True)
class BooleanSettingApplyOutcome:
    """Result of matching and applying one product boolean setting."""

    matched: bool
    message: str


@dataclass(frozen=True, slots=True)
class BooleanSettingBinding:
    """Product-declared manager accessors for a boolean setting."""

    id: str
    label: str
    getter: str
    setter: str
    status_label: str


@dataclass(frozen=True, slots=True)
class BooleanSettingCopy:
    """Product messages emitted by the shared boolean-setting mechanism."""

    unknown: Callable[[str], str]
    invalid: Callable[[BooleanSettingBinding], str]
    unavailable: Callable[[BooleanSettingBinding], str]
    applied: Callable[[BooleanSettingBinding, bool], str]


def boolean_setting_facts(
    manager: object | None,
    bindings: Sequence[BooleanSettingBinding],
) -> tuple[BooleanSettingFact, ...]:
    """Read every available product-declared boolean setting."""

    if manager is None:
        return ()
    facts = []
    for binding in bindings:
        getter = getattr(manager, binding.getter, None)
        if callable(getter):
            facts.append(
                BooleanSettingFact(
                    id=binding.id,
                    label=binding.label,
                    value="true" if bool(getter()) else "false",
                )
            )
    return tuple(facts)


def apply_boolean_setting(
    manager: object | None,
    item_id: str,
    value: str,
    *,
    bindings: Sequence[BooleanSettingBinding],
    copy: BooleanSettingCopy,
) -> BooleanSettingApplyOutcome:
    """Match, parse, and apply one product-declared boolean setting."""

    binding = next((item for item in bindings if item.id == item_id), None)
    if binding is None:
        return BooleanSettingApplyOutcome(False, copy.unknown(item_id))

    enabled = _parse_boolean(value)
    if enabled is None:
        return BooleanSettingApplyOutcome(True, copy.invalid(binding))

    setter = getattr(manager, binding.setter, None)
    if not callable(setter):
        return BooleanSettingApplyOutcome(True, copy.unavailable(binding))

    setter(enabled)
    return BooleanSettingApplyOutcome(True, copy.applied(binding, enabled))


def _parse_boolean(value: str) -> bool | None:
    normalized = value.casefold()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


__all__ = [
    "BooleanSettingApplyOutcome",
    "BooleanSettingBinding",
    "BooleanSettingCopy",
    "BooleanSettingFact",
    "apply_boolean_setting",
    "boolean_setting_facts",
]
