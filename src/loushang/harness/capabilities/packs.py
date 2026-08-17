"""Deterministic composition of already-admitted capability packs."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

T = TypeVar("T")
CapabilityPackSource = Literal["product", "oem", "extension", "session"]
_SOURCES = frozenset({"product", "oem", "extension", "session"})


@dataclass(frozen=True)
class CapabilityPack(Generic[T]):
    """One Product-approved, ordered contribution group.

    A pack contains live Product values only after runtime-profile admission
    has completed. This class neither discovers extensions nor grants them
    authority.
    """

    pack_id: str
    source: CapabilityPackSource
    items: tuple[T, ...]
    priority: int = 0
    enabled: bool = True

    def __post_init__(self) -> None:
        if not isinstance(self.pack_id, str) or not self.pack_id:
            raise ValueError("capability pack id must be a non-empty string")
        if self.source not in _SOURCES:
            raise ValueError("capability pack source must be a known runtime source")
        if type(self.priority) is not int:
            raise TypeError("capability pack priority must be an integer")
        if type(self.enabled) is not bool:
            raise TypeError("capability pack enabled must be a bool")
        object.__setattr__(self, "items", tuple(self.items))


@dataclass(frozen=True)
class CapabilityPackTraceEntry:
    pack_id: str
    source: CapabilityPackSource
    priority: int
    input_index: int
    output_index: int


@dataclass(frozen=True)
class CapabilityPackComposition(Generic[T]):
    items: tuple[T, ...]
    trace: tuple[CapabilityPackTraceEntry, ...]


@dataclass(frozen=True)
class CapabilityPackComposer:
    """A selectable, pure ordered-pack composition implementation."""

    def compose(
        self,
        packs: Iterable[CapabilityPack[T]],
    ) -> CapabilityPackComposition[T]:
        return compose_capability_packs(packs)


def compose_capability_packs(
    packs: Iterable[CapabilityPack[T]],
) -> CapabilityPackComposition[T]:
    """Flatten enabled packs by descending priority and stable input order."""

    supplied = tuple(packs)
    if any(not isinstance(pack, CapabilityPack) for pack in supplied):
        raise TypeError("capability packs must contain CapabilityPack values")
    identities = [(pack.source, pack.pack_id) for pack in supplied]
    if len(identities) != len(set(identities)):
        raise ValueError("capability packs must have unique source and pack ids")

    ordered = sorted(
        enumerate(supplied),
        key=lambda indexed: (-indexed[1].priority, indexed[0]),
    )
    items: list[T] = []
    trace: list[CapabilityPackTraceEntry] = []
    for input_index, pack in ordered:
        if not pack.enabled:
            continue
        first_output_index = len(items)
        items.extend(pack.items)
        trace.append(
            CapabilityPackTraceEntry(
                pack_id=pack.pack_id,
                source=pack.source,
                priority=pack.priority,
                input_index=input_index,
                output_index=first_output_index,
            )
        )
    return CapabilityPackComposition(items=tuple(items), trace=tuple(trace))


__all__ = [
    "CapabilityPack",
    "CapabilityPackComposer",
    "CapabilityPackComposition",
    "CapabilityPackSource",
    "CapabilityPackTraceEntry",
    "compose_capability_packs",
]
