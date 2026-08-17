"""Focused legacy binding for the Session-owned side-question Provider factory.

The binding intentionally remains Profile-backed until ``harness.session`` is
migrated.  It is separate from ``harness.resources`` and has one owner: the
live Product Session that binds the selected factory to its context.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import cast

from loushang.harness.capabilities.composition_runtime import (
    standard_capability_composition_implementations,
)
from loushang.harness.runtime import (
    SIDE_QUESTION_PROVIDER_SLOT,
    ResolvedRuntimeProfile,
    RuntimeCapabilityImplementation,
    RuntimeCapabilityRegistry,
    RuntimeProfileBinder,
    RuntimeProfileBinding,
    SideQuestionProviderFactory,
)


@dataclass
class LegacySideQuestionBinding:
    """Own exactly one selected side-question factory for one Session."""

    _binding: RuntimeProfileBinding
    _binder: RuntimeProfileBinder

    @property
    def provider_factory(self) -> SideQuestionProviderFactory | None:
        value = self._binding.values().get(SIDE_QUESTION_PROVIDER_SLOT.key)
        if value is None:
            return None
        if not callable(getattr(value, "bind", None)):
            raise TypeError(
                "interaction.side_question returned an invalid Provider factory"
            )
        return cast(SideQuestionProviderFactory, value)

    @property
    def is_closed(self) -> bool:
        return self._binding.is_closed

    def dispose(self) -> None:
        self._binder.dispose_sync(self._binding)


def bind_legacy_side_question(
    profile: ResolvedRuntimeProfile,
    *,
    additional_implementations: Iterable[RuntimeCapabilityImplementation] = (),
) -> LegacySideQuestionBinding:
    """Bind only ``interaction.side_question`` from a full resolved Profile."""

    focused_profile = ResolvedRuntimeProfile(
        product_id=profile.product_id,
        capabilities=tuple(
            capability
            for capability in profile.capabilities
            if capability.slot.key == SIDE_QUESTION_PROVIDER_SLOT.key
        ),
        schema_version=profile.schema_version,
    )
    binder = RuntimeProfileBinder(
        RuntimeCapabilityRegistry(
            (
                *(
                    implementation
                    for implementation in standard_capability_composition_implementations()
                    if implementation.slot == SIDE_QUESTION_PROVIDER_SLOT.key
                ),
                *(
                    implementation
                    for implementation in additional_implementations
                    if implementation.slot == SIDE_QUESTION_PROVIDER_SLOT.key
                ),
            )
        )
    )
    return LegacySideQuestionBinding(
        _binding=binder.bind_sync(focused_profile),
        _binder=binder,
    )


__all__ = ["LegacySideQuestionBinding", "bind_legacy_side_question"]
