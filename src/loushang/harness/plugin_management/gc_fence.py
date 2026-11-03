"""Neutral reference-writer fence for a future executable Package GC owner."""

from __future__ import annotations

from contextlib import AbstractContextManager, nullcontext
from typing import Protocol

from loushang.harness.plugin_management.records import PluginPackageRevisionRefV1


class PluginPackageGcReferenceGatePort(Protocol):
    def guard(
        self,
    ) -> AbstractContextManager[frozenset[PluginPackageRevisionRefV1]]: ...


def gc_reference_guard(
    gate: PluginPackageGcReferenceGatePort | None,
) -> AbstractContextManager[frozenset[PluginPackageRevisionRefV1]]:
    if gate is None:
        return nullcontext(frozenset())
    # Import here because Package lifecycle owns this neutral port and the
    # concrete reservation journal imports that lifecycle owner.
    from .package_gc_reservation import PluginPackageGcReservationJournal

    if isinstance(gate, PluginPackageGcReservationJournal):
        return gate.guard(require_write=True)
    return gate.guard()


__all__ = ["PluginPackageGcReferenceGatePort", "gc_reference_guard"]
