"""Prepare all five typed Worker history cutovers from one anchored V1 view.

Preparation is read-only. Product publication must reopen the sources under
its runtime and GC gates before making the cutover index authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, cast

from loushang.harness.worker.activation_state_journal import _StateRecord
from loushang.harness.worker.journal import WorkerAttemptRecordV1

from .package_product_worker_activation_base_v2 import (
    CodingWorkerActivationSemanticBaseV2,
    _parse_c5_segment,
)
from .package_product_worker_activation_history import (
    project_coding_worker_retained_attempts,
)
from .package_product_worker_history_checkpoint import (
    CodingWorkerHistoryCheckpointV1,
)
from .package_product_worker_history_checkpoint_anchor import (
    CodingWorkerCheckpointAnchorV1,
)
from .package_product_worker_history_cutover_v2 import (
    CodingWorkerProductCutoverIndexV2,
    CodingWorkerStreamCutoverV2,
)
from .package_product_worker_history_retirement_preview import (
    preview_first_coding_worker_stream_retirement_v2,
)
from .package_product_worker_history_segments import (
    CodingWorkerSegmentedHistoryV1,
)
from .package_product_worker_history_stream_snapshot import (
    CODING_WORKER_HISTORY_STREAM_STEMS,
)
from .package_product_worker_no_effect_archive_v2 import (
    CodingWorkerNoEffectArchiveV2,
)
from .package_product_worker_opt_in import CodingWorkerOptInDecisionV1
from .package_product_worker_opt_in_base_v2 import (
    CodingWorkerOptInSemanticBaseV2,
    _parse_opt_in_segment,
)
from .package_product_worker_receipt import CodingWorkerReceiptRecordV1
from .package_product_worker_receipt_base_v2 import (
    CodingWorkerReceiptSemanticBaseV2,
    _parse_receipt_segment,
)
from .package_product_worker_start_gate_base_v2 import (
    CodingWorkerStartGateSemanticBaseV2,
    _parse_start_gate_segment,
)
from .package_product_worker_start_gate_journal import (
    CodingWorkerStartGateRecordV1,
)
from .package_product_worker_supervisor_base_v2 import (
    CodingWorkerSupervisorSemanticBaseV2,
    _parse_supervisor_segment,
)

CodingWorkerTypedBasesV2 = tuple[
    CodingWorkerOptInSemanticBaseV2,
    CodingWorkerReceiptSemanticBaseV2,
    CodingWorkerActivationSemanticBaseV2,
    CodingWorkerStartGateSemanticBaseV2,
    CodingWorkerSupervisorSemanticBaseV2,
]


class _SemanticBaseV2(Protocol):
    @property
    def scope_id(self) -> str: ...

    def to_bytes(self) -> bytes: ...


def require_coding_worker_v2_retained_reference_closure(
    *,
    opt_in_base: CodingWorkerOptInSemanticBaseV2,
    opt_in_segments: tuple[bytes, ...],
    retained_receipts: tuple[CodingWorkerReceiptRecordV1, ...],
) -> None:
    """Refuse a cutoff that loses an allow still named by a retained receipt."""

    opt_in_base.replay_retained(opt_in_segments)
    decisions = (
        *opt_in_base.latest_decisions,
        *(
            decision
            for raw in opt_in_segments
            for decision in _parse_opt_in_segment(raw)
        ),
    )
    by_digest: dict[str, list[CodingWorkerOptInDecisionV1]] = {}
    for decision in decisions:
        by_digest.setdefault(decision.decision_digest, []).append(decision)
    for record in retained_receipts:
        policy = record.receipt.policy
        matching = by_digest.get(record.opt_in_decision_digest, [])
        if (
            len(matching) != 1
            or matching[0].action != "allow"
            or matching[0].plugin_id != policy.plugin_id
            or matching[0].scope_id != record.scope_id
            or matching[0].generation != policy.owner_selection_generation
            or matching[0].kill_switch_generation != policy.kill_switch_generation
        ):
            raise ValueError("Coding Worker V2 retained receipt opt-in unproved")


def require_coding_worker_no_effect_archive_sources(
    *,
    archive: CodingWorkerNoEffectArchiveV2,
    histories: tuple[CodingWorkerSegmentedHistoryV1, ...],
    retired_attempt_ids: tuple[str, ...],
) -> tuple[str, ...]:
    """Prove every archived record against the five exact V1 sources."""

    archived_ids = tuple(item.attempt_id for item in archive.proofs)
    if not archived_ids or not set(archived_ids) <= set(retired_attempt_ids):
        raise ValueError("Coding Worker no-effect V2 archive attempts differ")
    opt_in = tuple(
        record for raw in histories[0].segments for record in _parse_opt_in_segment(raw)
    )
    receipts: list[CodingWorkerReceiptRecordV1] = []
    for raw in histories[1].segments:
        receipts.extend(
            _parse_receipt_segment(
                raw, scope_id=archive.scope_id, first_revision=len(receipts) + 1
            )
        )
    c5_records: list[_StateRecord] = []
    for raw in histories[2].segments:
        c5_records.extend(_parse_c5_segment(raw, first_revision=len(c5_records) + 1))
    activation = project_coding_worker_retained_attempts(tuple(c5_records))
    gates: list[CodingWorkerStartGateRecordV1] = []
    for raw in histories[3].segments:
        gates.extend(_parse_start_gate_segment(raw, first_revision=len(gates) + 1))
    supervisor: list[WorkerAttemptRecordV1] = []
    for raw in histories[4].segments:
        supervisor.extend(
            _parse_supervisor_segment(raw, first_revision=len(supervisor) + 1)
        )
    latest_gates = {item.attempt_id: item for item in gates}
    receipt_by_fingerprint = {item.receipt.fingerprint: item for item in receipts}
    activation_by_id = {item.attempt_id: item for item in activation}
    opt_in_by_digest = {item.decision_digest: item for item in opt_in}
    supervisor_ids = {item.attempt_id for item in supervisor}
    if any(
        latest_gates.get(proof.attempt_id) != proof.gate
        or receipt_by_fingerprint.get(proof.receipt.receipt.fingerprint)
        != proof.receipt
        or activation_by_id.get(proof.attempt_id) != proof.activation
        or opt_in_by_digest.get(proof.historical_allow.decision_digest)
        != proof.historical_allow
        or proof.attempt_id in supervisor_ids
        for proof in archive.proofs
    ):
        raise ValueError("Coding Worker no-effect V2 archive source differs")
    return archived_ids


@dataclass(frozen=True, slots=True)
class CodingWorkerPreparedProductCutoverV2:
    index: CodingWorkerProductCutoverIndexV2
    streams: tuple[CodingWorkerStreamCutoverV2, ...]
    semantic_bases: CodingWorkerTypedBasesV2
    no_effect_archive: CodingWorkerNoEffectArchiveV2 | None = None

    def __post_init__(self) -> None:
        bases = cast(tuple[_SemanticBaseV2, ...], self.semantic_bases)
        if (
            type(self.index) is not CodingWorkerProductCutoverIndexV2
            or type(self.streams) is not tuple
            or tuple(type(item) for item in self.streams)
            != (CodingWorkerStreamCutoverV2,) * 5
            or tuple(item.stem for item in self.streams)
            != CODING_WORKER_HISTORY_STREAM_STEMS
            or type(self.semantic_bases) is not tuple
            or tuple(type(item) for item in self.semantic_bases)
            != (
                CodingWorkerOptInSemanticBaseV2,
                CodingWorkerReceiptSemanticBaseV2,
                CodingWorkerActivationSemanticBaseV2,
                CodingWorkerStartGateSemanticBaseV2,
                CodingWorkerSupervisorSemanticBaseV2,
            )
            or any(
                base.scope_id != self.index.scope_id
                or stream.checkpoint_revision != self.index.checkpoint_revision
                or stream.checkpoint_digest != self.index.checkpoint_digest
                or stream.semantic_base_digest != sha256(base.to_bytes()).hexdigest()
                for stream, base in zip(self.streams, bases, strict=True)
            )
            or self.index.stream_digests
            != tuple(
                (stream.stem, sha256(stream.to_bytes()).hexdigest())
                for stream in self.streams
            )
            or (
                self.no_effect_archive is None
                and self.index.no_effect_archive_digest is not None
            )
            or (
                self.no_effect_archive is not None
                and (
                    type(self.no_effect_archive) is not CodingWorkerNoEffectArchiveV2
                    or not self.no_effect_archive.proofs
                    or self.no_effect_archive.scope_id != self.index.scope_id
                    or self.no_effect_archive.store_id != self.index.store_id
                    or self.no_effect_archive.checkpoint_digest
                    != self.index.checkpoint_digest
                    or self.index.no_effect_archive_digest
                    != sha256(self.no_effect_archive.to_bytes()).hexdigest()
                    or not {
                        proof.attempt_id for proof in self.no_effect_archive.proofs
                    }.issubset(self.semantic_bases[3].retired_attempt_ids)
                    or bool(
                        {proof.attempt_id for proof in self.no_effect_archive.proofs}
                        & {
                            *self.semantic_bases[4].retired_attempt_ids,
                            *(
                                item.attempt_id
                                for item in self.semantic_bases[4].current_attempts
                            ),
                        }
                    )
                )
            )
        ):
            raise ValueError("Coding Worker typed Product cutover differs")

    @classmethod
    def from_v1_histories(
        cls,
        *,
        checkpoints: tuple[CodingWorkerHistoryCheckpointV1, ...],
        anchor: CodingWorkerCheckpointAnchorV1,
        histories: tuple[CodingWorkerSegmentedHistoryV1, ...],
        first_retained_generations: tuple[int, ...],
        no_effect_archive: CodingWorkerNoEffectArchiveV2 | None = None,
    ) -> CodingWorkerPreparedProductCutoverV2:
        """Reproject and replay all five streams before forming one index."""

        if (
            type(checkpoints) is not tuple
            or not checkpoints
            or any(
                type(item) is not CodingWorkerHistoryCheckpointV1
                for item in checkpoints
            )
            or type(anchor) is not CodingWorkerCheckpointAnchorV1
            or type(histories) is not tuple
            or len(histories) != len(CODING_WORKER_HISTORY_STREAM_STEMS)
            or any(
                type(item) is not CodingWorkerSegmentedHistoryV1 for item in histories
            )
            or type(first_retained_generations) is not tuple
            or len(first_retained_generations) != len(histories)
            or any(type(item) is not int for item in first_retained_generations)
            or (
                no_effect_archive is not None
                and type(no_effect_archive) is not CodingWorkerNoEffectArchiveV2
            )
        ):
            raise ValueError("Coding Worker typed Product sources are invalid")
        checkpoint = checkpoints[-1]
        if (
            checkpoint.scope_id != anchor.scope_id
            or checkpoint.store_id != anchor.store_id
            or checkpoint.journal_revision != anchor.latest_revision
            or checkpoint.record_digest != anchor.latest_digest
            or any(
                item.journal_revision != ordinal
                or item.scope_id != checkpoint.scope_id
                or item.store_id != checkpoint.store_id
                or item.previous_digest
                != ("" if ordinal == 1 else checkpoints[ordinal - 2].record_digest)
                for ordinal, item in enumerate(checkpoints, 1)
            )
        ):
            raise ValueError("Coding Worker typed Product checkpoint chain differs")
        retired_attempt_ids = tuple(
            sorted({value for item in checkpoints for value in item.new_attempt_ids})
        )
        for values in (
            tuple(value for item in checkpoints for value in item.new_attempt_ids),
            tuple(
                value for item in checkpoints for value in item.new_opt_in_operation_ids
            ),
            tuple(
                value for item in checkpoints for value in item.new_receipt_fingerprints
            ),
        ):
            if len(values) != len(set(values)):
                raise ValueError("Coding Worker typed Product checkpoint IDs repeat")
        no_effect_ids = (
            ()
            if no_effect_archive is None
            else require_coding_worker_no_effect_archive_sources(
                archive=no_effect_archive,
                histories=histories,
                retired_attempt_ids=retired_attempt_ids,
            )
        )
        supervisor_retired_ids = tuple(
            item for item in retired_attempt_ids if item not in no_effect_ids
        )
        previews = tuple(
            preview_first_coding_worker_stream_retirement_v2(
                checkpoint=checkpoint,
                anchor=anchor,
                history=history,
                stem=stem,
                first_retained_generation=cutoff,
            )
            for stem, history, cutoff in zip(
                CODING_WORKER_HISTORY_STREAM_STEMS,
                histories,
                first_retained_generations,
                strict=True,
            )
        )
        bases: CodingWorkerTypedBasesV2 = (
            CodingWorkerOptInSemanticBaseV2.from_v1_history(
                history=histories[0],
                scope_id=checkpoint.scope_id,
                first_retained_generation=first_retained_generations[0],
            ),
            CodingWorkerReceiptSemanticBaseV2.from_v1_history(
                history=histories[1],
                scope_id=checkpoint.scope_id,
                first_retained_generation=first_retained_generations[1],
            ),
            CodingWorkerActivationSemanticBaseV2.from_v1_history(
                history=histories[2],
                scope_id=checkpoint.scope_id,
                first_retained_generation=first_retained_generations[2],
            ),
            CodingWorkerStartGateSemanticBaseV2.from_v1_history(
                history=histories[3],
                scope_id=checkpoint.scope_id,
                first_retained_generation=first_retained_generations[3],
                retired_attempt_ids=retired_attempt_ids,
            ),
            CodingWorkerSupervisorSemanticBaseV2.from_v1_history(
                history=histories[4],
                scope_id=checkpoint.scope_id,
                first_retained_generation=first_retained_generations[4],
                retired_attempt_ids=supervisor_retired_ids,
            ),
        )
        require_coding_worker_v2_retained_reference_closure(
            opt_in_base=bases[0],
            opt_in_segments=histories[0].segments[first_retained_generations[0] :],
            retained_receipts=bases[1]
            .replay_retained(histories[1].segments[first_retained_generations[1] :])
            .retained_records,
        )
        streams = (
            CodingWorkerStreamCutoverV2.from_opt_in_base(
                checkpoint=checkpoint,
                preview=previews[0],
                history=histories[0],
                semantic_base=bases[0],
            ),
            CodingWorkerStreamCutoverV2.from_receipt_base(
                checkpoint=checkpoint,
                preview=previews[1],
                history=histories[1],
                semantic_base=bases[1],
            ),
            CodingWorkerStreamCutoverV2.from_activation_base(
                checkpoint=checkpoint,
                preview=previews[2],
                history=histories[2],
                semantic_base=bases[2],
            ),
            CodingWorkerStreamCutoverV2.from_start_gate_base(
                checkpoints=checkpoints,
                preview=previews[3],
                history=histories[3],
                semantic_base=bases[3],
            ),
            CodingWorkerStreamCutoverV2.from_supervisor_base(
                checkpoints=checkpoints,
                preview=previews[4],
                history=histories[4],
                semantic_base=bases[4],
                no_effect_attempt_ids=no_effect_ids,
            ),
        )
        return cls(
            index=CodingWorkerProductCutoverIndexV2.from_streams(
                checkpoint=checkpoint,
                anchor=anchor,
                streams=streams,
                no_effect_archive=no_effect_archive,
            ),
            streams=streams,
            semantic_bases=bases,
            no_effect_archive=no_effect_archive,
        )


__all__ = [
    "CodingWorkerPreparedProductCutoverV2",
    "CodingWorkerTypedBasesV2",
    "require_coding_worker_v2_retained_reference_closure",
]
