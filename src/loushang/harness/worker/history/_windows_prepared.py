"""Common source-bound reconstruction over already proved preparation facts.

This helper neither captures IO nor skips per-stream preparation checks. Each
ledger retains its own existing fold and exact nominal preparation binding.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar, Self

from loushang.harness.resources.packages.plugin_lifecycle._record_schema import (
    RecordField,
    RecordSchema,
)

from ._base_codec import _SourceBoundBaseWireMethods, _unchanged
from ._windows_semantic_contracts import (
    _RecoveryFacts,
    _SourceFacts,
    _WindowsHistorySemanticFacts,
    _WindowsPreparationFacts,
)
from ._windows_sources import WINDOWS_WORKER_SEMANTIC_BASE_MAX_BYTES


def _record_tuple_field(
    attribute: str, decode_item: Callable[[object], object]
) -> RecordField:
    return RecordField(
        attribute,
        decoder=lambda items: tuple(decode_item(item) for item in items),
        encoder=lambda values: [value.to_dict() for value in values],
    )


class _WindowsPreparationBinding:
    __slots__ = ()
    _preparation_type: ClassVar[type[_WindowsPreparationFacts]]


class _WindowsPreparedSourceMethods(
    _WindowsPreparationBinding, _SourceBoundBaseWireMethods
):
    __slots__ = ()
    _preparation_label: ClassVar[str]
    _wire_max_bytes = WINDOWS_WORKER_SEMANTIC_BASE_MAX_BYTES

    @classmethod
    def _bind_windows_wire_schema(cls, *overrides: RecordField) -> None:
        cls._bind_wire_schema(RecordSchema.for_dataclass(cls, _unchanged, *overrides))

    @classmethod
    def from_semantic_read(
        cls, prepared: _WindowsPreparationFacts, semantic: _WindowsHistorySemanticFacts
    ) -> Self:
        """Reconstruct through the ledger's original preparation and source proof."""
        return cls._from_prepared_history(prepared, semantic)

    @classmethod
    def _from_prepared_history(
        cls, prepared: _WindowsPreparationFacts, semantic: _WindowsHistorySemanticFacts
    ) -> Self:
        if type(prepared) is not cls._preparation_type:
            raise ValueError(
                f"Windows Worker {cls._preparation_label} preparation is invalid"
            )
        prepared._require_semantic_read(semantic)
        return cls._from_source_read(
            semantic.source_snapshot, semantic.offline_recovery
        )

    @classmethod
    def _from_source_read(cls, source: _SourceFacts, recovery: _RecoveryFacts) -> Self:
        raise NotImplementedError
