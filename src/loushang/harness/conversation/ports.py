from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from loushang.harness.conversation.store import ConversationLocator
from loushang.harness.journal import (
    FunctionalJournalHeaderCodec as FunctionalConversationHeaderCodec,
)
from loushang.harness.journal import (
    FunctionalJournalRecordCodec as FunctionalConversationRecordCodec,
)
from loushang.harness.journal import JournalHeaderCodec as ConversationHeaderCodec
from loushang.harness.journal import JournalRecordCodec as ConversationRecordCodec

H = TypeVar("H")
R = TypeVar("R")
S = TypeVar("S")
P = TypeVar("P")
H_contra = TypeVar("H_contra", contravariant=True)
R_contra = TypeVar("R_contra", contravariant=True)
P_co = TypeVar("P_co", covariant=True)


class ConversationProjector(Protocol[H_contra, R_contra, P_co]):
    def project(
        self,
        *,
        header: H_contra,
        records: Sequence[R_contra],
        leaf_id: str | None,
        locator: ConversationLocator,
    ) -> P_co: ...


class ConversationFolder(Protocol[R_contra, S]):
    def initial(self) -> S: ...

    def apply(self, state: S, record: R_contra) -> S: ...


@dataclass(frozen=True)
class FunctionalConversationProjector(Generic[H, R, P]):
    projection: Callable[[H, Sequence[R], str | None, ConversationLocator], P]

    def project(
        self,
        *,
        header: H,
        records: Sequence[R],
        leaf_id: str | None,
        locator: ConversationLocator,
    ) -> P:
        return self.projection(header, records, leaf_id, locator)


@dataclass(frozen=True)
class FunctionalConversationFolder(Generic[R, S]):
    initial_state: Callable[[], S]
    reducer: Callable[[S, R], S]

    def initial(self) -> S:
        return self.initial_state()

    def apply(self, state: S, record: R) -> S:
        return self.reducer(state, record)


__all__ = [
    "ConversationFolder",
    "ConversationHeaderCodec",
    "ConversationProjector",
    "ConversationRecordCodec",
    "FunctionalConversationFolder",
    "FunctionalConversationHeaderCodec",
    "FunctionalConversationProjector",
    "FunctionalConversationRecordCodec",
]
