"""Durable, default-dark Coding Product decisions for local Worker candidates.

The journal records a per-Plugin operator decision. It grants no Package
selection, activation receipt, native launch, or Capability publication.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from loushang.harness.journal import (
    SORTED_UNICODE_JSONL_FORMAT,
    FunctionalJournalRecordCodec,
    JournalCodecError,
    JournalFormatProfile,
    JournalRecordCodec,
)
from loushang.harness.plugin_management.package_gc_reservation import (
    PluginPackageGcReservationJournal,
)
from loushang.harness.worker.history._opt_in import (
    _DIGEST as _DIGEST,
)
from loushang.harness.worker.history._opt_in import (
    _MAX_EVENTS,
    _MAX_SEGMENT_BYTES,
    _OptInDecisionMethods,
    decode_opt_in_history,
    fold_opt_in_events,
    opt_in_line,
)
from loushang.harness.worker.history._opt_in import (
    _OPAQUE as _OPAQUE,
)
from loushang.harness.worker.history._opt_in_store import OptInJournal

from .package_product_worker_policy import CodingWorkerOptInV1

if TYPE_CHECKING:
    pass

_STEM = "worker-opt-in"


class CodingWorkerOptInJournalError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingWorkerOptInDecisionV1(_OptInDecisionMethods):
    journal_revision: int
    scope_id: str
    plugin_id: str
    operation_id: str
    generation: int
    kill_switch_generation: int
    action: Literal["allow", "revoke"]
    opt_in: CodingWorkerOptInV1 | None
    decision_digest: str
    record_version: int = 1

    _opt_in_type = CodingWorkerOptInV1


def _decode(value: object) -> CodingWorkerOptInDecisionV1:
    try:
        return CodingWorkerOptInDecisionV1.from_dict(value)
    except (TypeError, ValueError) as exc:
        raise JournalCodecError(
            "Coding Worker opt-in decision record is invalid",
            code="coding_worker_opt_in_record_invalid",
        ) from exc


_CODEC: FunctionalJournalRecordCodec[CodingWorkerOptInDecisionV1] = (
    FunctionalJournalRecordCodec(
        encoder=CodingWorkerOptInDecisionV1.to_dict,
        decoder=_decode,
    )
)


def _decode_coding_worker_opt_in_history(
    raw: bytes,
    *,
    path: Path,
    scope_id: str,
) -> tuple[CodingWorkerOptInDecisionV1, ...]:
    return decode_opt_in_history(
        raw,
        path=path,
        scope_id=scope_id,
        record_codec=_CODEC,
        error_type=CodingWorkerOptInJournalError,
        max_events=_MAX_EVENTS,
        max_segment_bytes=_MAX_SEGMENT_BYTES,
    )


def _validate_opt_in_events(
    events: tuple[CodingWorkerOptInDecisionV1, ...], *, scope_id: str
) -> None:
    _fold_opt_in_events(events, scope_id=scope_id)


def _fold_opt_in_events(
    events: tuple[CodingWorkerOptInDecisionV1, ...],
    *,
    scope_id: str,
    start_revision: int = 1,
    initial_latest: Mapping[str, CodingWorkerOptInDecisionV1] | None = None,
    initial_operations: frozenset[str] = frozenset(),
) -> tuple[dict[str, CodingWorkerOptInDecisionV1], frozenset[str]]:
    return fold_opt_in_events(
        events,
        scope_id=scope_id,
        start_revision=start_revision,
        initial_latest=initial_latest,
        initial_operations=initial_operations,
        error_type=CodingWorkerOptInJournalError,
    )


@dataclass(frozen=True, slots=True)
class CodingWorkerOptInRetentionProjectionV1:
    """Decisions still needed to join retained receipts after V2 cutover."""

    reference_decisions: tuple[CodingWorkerOptInDecisionV1, ...]
    latest_decisions: tuple[CodingWorkerOptInDecisionV1, ...]
    operation_ids: tuple[str, ...]
    revision: int


class CodingWorkerOptInJournal(
    OptInJournal[
        CodingWorkerOptInDecisionV1,
        CodingWorkerOptInRetentionProjectionV1,
        CodingWorkerOptInV1,
    ]
):
    """Original Code value family over the shared opt-in history mechanism."""

    def __init__(
        self,
        path: Path,
        *,
        scope_id: str,
        gc_gate: PluginPackageGcReservationJournal,
        store_id: str | None = None,
    ) -> None:
        from .package_product_worker_history_read_v2 import _HISTORY_READER

        super().__init__(
            path,
            scope_id=scope_id,
            gc_gate=gc_gate,
            store_id=store_id,
            history_reader=_HISTORY_READER,
            projection_type=CodingWorkerOptInRetentionProjectionV1,
            error_type=CodingWorkerOptInJournalError,
        )

    @property
    def _record_codec(self) -> JournalRecordCodec[CodingWorkerOptInDecisionV1]:
        return _CODEC

    @property
    def _record_format(self) -> JournalFormatProfile:
        return SORTED_UNICODE_JSONL_FORMAT

    def _max_history_bytes(self) -> int:
        return _MAX_SEGMENT_BYTES

    def _max_history_records(self) -> int:
        return _MAX_EVENTS

    def change(
        self,
        *,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
        action: Literal["allow", "revoke"],
        opt_in: CodingWorkerOptInV1 | None,
    ) -> CodingWorkerOptInDecisionV1:
        return super().change(
            plugin_id=plugin_id,
            operation_id=operation_id,
            expected_generation=expected_generation,
            action=action,
            opt_in=opt_in,
        )


_opt_in_line = opt_in_line


__all__ = [
    "CodingWorkerOptInDecisionV1",
    "CodingWorkerOptInJournal",
    "CodingWorkerOptInJournalError",
    "CodingWorkerOptInRetentionProjectionV1",
]
