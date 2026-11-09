"""Five-stream prepared values and reference closure, without publication."""

from __future__ import annotations

from collections.abc import Callable
from hashlib import sha256
from typing import ClassVar, Protocol, Self, cast

from .._segmented_history import (
    CodingWorkerSegmentedHistoryV1,
)
from ..activation_state_journal import _StateRecord
from ..journal import WorkerAttemptRecordV1
from ._activation import _RetainedAttemptFields, project_retained_attempts
from ._activation_base import _ActivationBaseMethods, _parse_c5_segment
from ._anchor import _AnchorMethods
from ._checkpoint import _CheckpointMethods, checkpoint_chain_matches
from ._cutover import _IndexMethods, _StreamCutoverMethods
from ._no_effect import _NoEffectArchiveMethods
from ._opt_in import _OptInBaseMethods, _OptInDecisionMethods, parse_opt_in_segment
from ._preview import _PreviewMethods
from ._receipts import _ReceiptBaseMethods, _ReceiptRecordMethods
from ._snapshot import CODING_WORKER_HISTORY_STREAM_STEMS
from ._start_gate import (
    _StartGateBaseMethods,
    _StartGateRecordMethods,
    parse_start_gate_segment,
)
from ._supervisor import _parse_supervisor_segment, _SupervisorBaseMethods

_TypedBasesV2 = tuple[
    _OptInBaseMethods,
    _ReceiptBaseMethods,
    _ActivationBaseMethods,
    _StartGateBaseMethods,
    _SupervisorBaseMethods,
]


class _SemanticBaseV2(Protocol):
    @property
    def scope_id(self) -> str: ...
    def to_bytes(self) -> bytes: ...


def require_retained_reference_closure(
    *,
    opt_in_base: _OptInBaseMethods,
    opt_in_segments: tuple[bytes, ...],
    retained_receipts: tuple[_ReceiptRecordMethods, ...],
) -> None:
    """Refuse a cutoff that loses an allow still named by a retained receipt."""

    opt_in_base.replay_retained(opt_in_segments)
    decisions = (
        *opt_in_base.latest_decisions,
        *(
            decision
            for raw in opt_in_segments
            for decision in parse_opt_in_segment(
                raw, decision_type=opt_in_base._decision_type
            )
        ),
    )
    by_digest: dict[str, list[_OptInDecisionMethods]] = {}
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


class _PreparedMethods:
    __slots__ = ()

    index: _IndexMethods
    streams: tuple[_StreamCutoverMethods, ...]
    semantic_bases: _TypedBasesV2
    no_effect_archive: _NoEffectArchiveMethods | None = None

    _retained_type: ClassVar[type[_RetainedAttemptFields]]
    _activation_type: ClassVar[type[_ActivationBaseMethods]]
    _anchor_type: ClassVar[type[_AnchorMethods]]
    _checkpoint_type: ClassVar[type[_CheckpointMethods]]
    _archive_type: ClassVar[type[_NoEffectArchiveMethods]]
    _opt_in_type: ClassVar[type[_OptInBaseMethods]]
    _preview_type: ClassVar[type[_PreviewMethods]]
    _index_type: ClassVar[type[_IndexMethods]]
    _receipt_type: ClassVar[type[_ReceiptBaseMethods]]
    _gate_type: ClassVar[type[_StartGateBaseMethods]]
    _stream_type: ClassVar[type[_StreamCutoverMethods]]
    _supervisor_type: ClassVar[type[_SupervisorBaseMethods]]

    def __post_init__(self) -> None:
        bases = cast(tuple[_SemanticBaseV2, ...], self.semantic_bases)
        if (
            type(self.index) is not self._index_type
            or type(self.streams) is not tuple
            or tuple(type(item) for item in self.streams) != (self._stream_type,) * 5
            or tuple(item.stem for item in self.streams)
            != CODING_WORKER_HISTORY_STREAM_STEMS
            or type(self.semantic_bases) is not tuple
            or tuple(type(item) for item in self.semantic_bases)
            != (
                self._opt_in_type,
                self._receipt_type,
                self._activation_type,
                self._gate_type,
                self._supervisor_type,
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
                    type(self.no_effect_archive) is not self._archive_type
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
        checkpoints: tuple[_CheckpointMethods, ...],
        anchor: _AnchorMethods,
        histories: tuple[CodingWorkerSegmentedHistoryV1, ...],
        first_retained_generations: tuple[int, ...],
        no_effect_archive: _NoEffectArchiveMethods | None = None,
    ) -> Self:
        """Reproject and replay all five streams before forming one index."""

        if (
            type(checkpoints) is not tuple
            or not checkpoints
            or any(type(item) is not cls._checkpoint_type for item in checkpoints)
            or type(anchor) is not cls._anchor_type
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
                and type(no_effect_archive) is not cls._archive_type
            )
        ):
            raise ValueError("Coding Worker typed Product sources are invalid")
        checkpoint = checkpoints[-1]
        if (
            checkpoint.scope_id != anchor.scope_id
            or checkpoint.store_id != anchor.store_id
            or checkpoint.journal_revision != anchor.latest_revision
            or checkpoint.record_digest != anchor.latest_digest
            or not checkpoint_chain_matches(checkpoints, checkpoint)
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
            else cls._require_archive_sources(
                archive=no_effect_archive,
                histories=histories,
                retired_attempt_ids=retired_attempt_ids,
            )
        )
        supervisor_retired_ids = tuple(
            item for item in retired_attempt_ids if item not in no_effect_ids
        )
        previews = tuple(
            cls._preview_type._from_sources(
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
        bases: _TypedBasesV2 = (
            cls._opt_in_type.from_v1_history(
                history=histories[0],
                scope_id=checkpoint.scope_id,
                first_retained_generation=first_retained_generations[0],
            ),
            cls._receipt_type.from_v1_history(
                history=histories[1],
                scope_id=checkpoint.scope_id,
                first_retained_generation=first_retained_generations[1],
            ),
            cls._activation_type.from_v1_history(
                history=histories[2],
                scope_id=checkpoint.scope_id,
                first_retained_generation=first_retained_generations[2],
            ),
            cls._gate_type.from_v1_history(
                history=histories[3],
                scope_id=checkpoint.scope_id,
                first_retained_generation=first_retained_generations[3],
                retired_attempt_ids=retired_attempt_ids,
            ),
            cls._supervisor_type.from_v1_history(
                history=histories[4],
                scope_id=checkpoint.scope_id,
                first_retained_generation=first_retained_generations[4],
                retired_attempt_ids=supervisor_retired_ids,
            ),
        )
        require_retained_reference_closure(
            opt_in_base=bases[0],
            opt_in_segments=histories[0].segments[first_retained_generations[0] :],
            retained_receipts=bases[1]
            .replay_retained(histories[1].segments[first_retained_generations[1] :])
            .retained_records,
        )
        streams = (
            cls._stream_type.from_opt_in_base(
                checkpoint=checkpoint,
                preview=previews[0],
                history=histories[0],
                semantic_base=bases[0],
            ),
            cls._stream_type.from_receipt_base(
                checkpoint=checkpoint,
                preview=previews[1],
                history=histories[1],
                semantic_base=bases[1],
            ),
            cls._stream_type.from_activation_base(
                checkpoint=checkpoint,
                preview=previews[2],
                history=histories[2],
                semantic_base=bases[2],
            ),
            cls._stream_type.from_start_gate_base(
                checkpoints=checkpoints,
                preview=previews[3],
                history=histories[3],
                semantic_base=bases[3],
            ),
            cls._stream_type.from_supervisor_base(
                checkpoints=checkpoints,
                preview=previews[4],
                history=histories[4],
                semantic_base=bases[4],
                no_effect_attempt_ids=no_effect_ids,
            ),
        )
        return cast(Callable[..., Self], cls)(
            index=cls._index_type.from_streams(
                checkpoint=checkpoint,
                anchor=anchor,
                streams=streams,
                no_effect_archive=no_effect_archive,
            ),
            streams=streams,
            semantic_bases=bases,
            no_effect_archive=no_effect_archive,
        )

    @classmethod
    def _require_archive_sources(
        cls,
        *,
        archive: _NoEffectArchiveMethods,
        histories: tuple[CodingWorkerSegmentedHistoryV1, ...],
        retired_attempt_ids: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Prove every archived record against the five exact V1 sources."""

        archived_ids = tuple(item.attempt_id for item in archive.proofs)
        if not archived_ids or not set(archived_ids) <= set(retired_attempt_ids):
            raise ValueError("Coding Worker no-effect V2 archive attempts differ")
        opt_in = tuple(
            record
            for raw in histories[0].segments
            for record in parse_opt_in_segment(
                raw, decision_type=cls._opt_in_type._decision_type
            )
        )
        receipts: list[_ReceiptRecordMethods] = []
        for raw in histories[1].segments:
            receipts.extend(
                cls._receipt_type._decode_segment(
                    raw, scope_id=archive.scope_id, first_revision=len(receipts) + 1
                )
            )
        c5_records: list[_StateRecord] = []
        for raw in histories[2].segments:
            c5_records.extend(
                _parse_c5_segment(raw, first_revision=len(c5_records) + 1)
            )
        activation = project_retained_attempts(
            tuple(c5_records), record_type=cls._retained_type
        )
        gates: list[_StartGateRecordMethods] = []
        for raw in histories[3].segments:
            gates.extend(
                parse_start_gate_segment(
                    raw,
                    first_revision=len(gates) + 1,
                    record_type=cls._gate_type._record_type,
                )
            )
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
