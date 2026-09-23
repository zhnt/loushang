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
    return nullcontext(frozenset()) if gate is None else gate.guard()


__all__ = ["PluginPackageGcReferenceGatePort", "gc_reference_guard"]
