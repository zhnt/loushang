from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from loushang.harness.events.session import (
    QueuedMessageSnapshot,
    QueueKind,
    QueueSnapshot,
)
from loushang.harness.runtime.types import QueueMode

T = TypeVar("T")


@dataclass(frozen=True)
class _QueuedInput(Generic[T]):
    snapshot: QueuedMessageSnapshot
    payload: T = field(compare=False, repr=False)
    payload_identity: int = field(compare=False, repr=False)


class HostInputQueue(Generic[T]):
    def __init__(self) -> None:
        self._steering: list[_QueuedInput[T]] = []
        self._follow_up: list[_QueuedInput[T]] = []
        self._next_turn: list[T] = []
        self._next_queue_id = 1

    @property
    def pending_count(self) -> int:
        return len(self._steering) + len(self._follow_up)

    def has_pending(self) -> bool:
        return self.pending_count > 0

    def texts(self, kind: QueueKind) -> list[str]:
        return [item.snapshot.text for item in self._items(kind)]

    def snapshot(self) -> QueueSnapshot:
        return QueueSnapshot(
            steering=tuple(item.snapshot for item in self._steering),
            follow_up=tuple(item.snapshot for item in self._follow_up),
        )

    def enqueue(
        self,
        kind: QueueKind,
        *,
        text: str,
        payload: T,
    ) -> QueuedMessageSnapshot:
        snapshot = QueuedMessageSnapshot(
            id=f"q{self._next_queue_id}",
            kind=kind,
            text=text,
        )
        self._next_queue_id += 1
        self._items(kind).append(
            _QueuedInput(
                snapshot=snapshot,
                payload=payload,
                payload_identity=id(payload),
            )
        )
        return snapshot

    def consume(
        self,
        payload: object,
        *,
        fallback_text: str | None = None,
    ) -> QueuedMessageSnapshot | None:
        payload_identity = id(payload)
        consumed = self._pop_first(
            self._steering,
            lambda item: item.payload_identity == payload_identity,
        )
        if consumed is None:
            consumed = self._pop_first(
                self._follow_up,
                lambda item: item.payload_identity == payload_identity,
            )
        if consumed is not None:
            return consumed.snapshot
        if not fallback_text:
            return None
        consumed = self._pop_first(
            self._steering,
            lambda item: item.snapshot.text == fallback_text,
        )
        if consumed is None:
            consumed = self._pop_first(
                self._follow_up,
                lambda item: item.snapshot.text == fallback_text,
            )
        return consumed.snapshot if consumed is not None else None

    def drain(
        self,
        kind: QueueKind,
        mode: QueueMode,
    ) -> tuple[QueuedMessageSnapshot, ...]:
        items = self._items(kind)
        if not items:
            return ()
        if mode == "all":
            drained = list(items)
            items.clear()
        elif mode == "one-at-a-time":
            drained = [items.pop(0)]
        else:
            raise ValueError("queue mode must be 'all' or 'one-at-a-time'")
        return tuple(item.snapshot for item in drained)

    def clear(self) -> QueueSnapshot:
        previous = self.snapshot()
        self._steering.clear()
        self._follow_up.clear()
        return previous

    def append_next_turn(self, payload: T) -> None:
        self._next_turn.append(payload)

    def drain_next_turn(self) -> list[T]:
        drained = list(self._next_turn)
        self._next_turn.clear()
        return drained

    def _items(self, kind: QueueKind) -> list[_QueuedInput[T]]:
        if kind == "steering":
            return self._steering
        if kind == "follow_up":
            return self._follow_up
        raise ValueError("queue kind must be 'steering' or 'follow_up'")

    @staticmethod
    def _pop_first(
        items: list[_QueuedInput[T]],
        predicate,
    ) -> _QueuedInput[T] | None:
        for index, item in enumerate(items):
            if predicate(item):
                return items.pop(index)
        return None
