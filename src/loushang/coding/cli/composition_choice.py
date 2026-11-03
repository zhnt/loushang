"""Resolve the ordinary Coding CLI's canonical new-Session composition choice."""

from __future__ import annotations

from loushang.coding.composition_sets import (
    CodingCompositionSetId,
    infer_coding_composition_set,
    resolve_coding_composition_set,
)


def resolve_cli_composition_choice(
    explicit: str | None,
    configured_capabilities: object,
) -> CodingCompositionSetId:
    """Honor explicit CLI intent before the historical Arch-key inference."""

    if explicit is not None:
        return resolve_coding_composition_set(explicit).set_id
    return infer_coding_composition_set(configured_capabilities)


__all__ = ["resolve_cli_composition_choice"]
