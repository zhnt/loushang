from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

RecordT = TypeVar("RecordT")
ItemT = TypeVar("ItemT")
StateT = TypeVar("StateT")
MissingCheckpointPolicy = Literal["error", "summary_only"]


@dataclass(frozen=True)
class ConversationCheckpoint(Generic[ItemT]):
    first_kept_record_id: str
    summary_item: ItemT

    def __post_init__(self) -> None:
        _require_record_id(
            self.first_kept_record_id,
            name="checkpoint first kept record id",
        )


@dataclass(frozen=True)
class ConversationReplayPorts(Generic[RecordT, ItemT, StateT]):
    record_id: Callable[[RecordT], str]
    project_visible_item: Callable[[RecordT], ItemT | None]
    initialize_state: Callable[[], StateT]
    reduce_state: Callable[[StateT, RecordT], StateT]
    resolve_checkpoint: (
        Callable[[RecordT], ConversationCheckpoint[ItemT] | None] | None
    ) = None


@dataclass(frozen=True)
class ConversationReplayProjection(Generic[ItemT, StateT]):
    items: tuple[ItemT, ...]
    state: StateT


class ConversationReplayFolder(Generic[RecordT, ItemT, StateT]):
    """Fold an active conversation path into context items and product state."""

    def __init__(
        self,
        ports: ConversationReplayPorts[RecordT, ItemT, StateT],
        *,
        missing_checkpoint: MissingCheckpointPolicy = "error",
    ) -> None:
        if missing_checkpoint not in {"error", "summary_only"}:
            raise ValueError(
                "missing checkpoint policy must be 'error' or 'summary_only'"
            )
        self._ports = ports
        self._missing_checkpoint = missing_checkpoint

    def replay(
        self,
        records: Sequence[RecordT],
    ) -> ConversationReplayProjection[ItemT, StateT]:
        all_records = tuple(records)
        state = self._ports.initialize_state()
        record_positions: dict[str, int] = {}

        for position, record in enumerate(all_records):
            record_id = self._ports.record_id(record)
            _require_record_id(record_id, name="conversation record id")
            if record_id in record_positions:
                raise ValueError(f"duplicate conversation record id: {record_id}")
            record_positions[record_id] = position
            state = self._ports.reduce_state(state, record)

        resolved = self._latest_checkpoint(all_records)
        if resolved is None:
            return ConversationReplayProjection(
                items=self._project_items(all_records),
                state=state,
            )

        checkpoint_index, checkpoint = resolved
        boundary_index = record_positions.get(checkpoint.first_kept_record_id)
        if boundary_index is None or boundary_index >= checkpoint_index:
            if self._missing_checkpoint == "error":
                raise ValueError(
                    "conversation checkpoint refers to missing record "
                    f"{checkpoint.first_kept_record_id}"
                )
            kept_records: tuple[RecordT, ...] = ()
        else:
            kept_records = all_records[boundary_index:checkpoint_index]

        items = [checkpoint.summary_item]
        items.extend(self._project_items(kept_records))
        items.extend(self._project_items(all_records[checkpoint_index + 1 :]))
        return ConversationReplayProjection(items=tuple(items), state=state)

    def _latest_checkpoint(
        self,
        records: tuple[RecordT, ...],
    ) -> tuple[int, ConversationCheckpoint[ItemT]] | None:
        for index in range(len(records) - 1, -1, -1):
            record = records[index]
            checkpoint = self._resolve_checkpoint(record)
            if checkpoint is not None:
                return index, checkpoint
        return None

    def _project_items(self, records: Sequence[RecordT]) -> tuple[ItemT, ...]:
        items: list[ItemT] = []
        for record in records:
            visible_item = self._ports.project_visible_item(record)
            if visible_item is not None:
                items.append(visible_item)
        return tuple(items)

    def _resolve_checkpoint(
        self, record: RecordT
    ) -> ConversationCheckpoint[ItemT] | None:
        resolver = self._ports.resolve_checkpoint
        if resolver is None:
            return None
        checkpoint = resolver(record)
        if checkpoint is not None and not isinstance(
            checkpoint, ConversationCheckpoint
        ):
            raise TypeError(
                "conversation checkpoint resolver must return "
                "ConversationCheckpoint or None"
            )
        return checkpoint


def _require_record_id(value: object, *, name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")


__all__ = [
    "ConversationCheckpoint",
    "MissingCheckpointPolicy",
    "ConversationReplayFolder",
    "ConversationReplayPorts",
    "ConversationReplayProjection",
]
