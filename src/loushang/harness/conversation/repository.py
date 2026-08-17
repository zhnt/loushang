from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, TypeVar

from loushang.harness.conversation.branch import BranchGraph, BranchMode
from loushang.harness.conversation.diagnostics import ConversationDiagnostic
from loushang.harness.conversation.ports import ConversationFolder
from loushang.harness.conversation.store import (
    ConversationLoadResult,
    ConversationSnapshot,
    ConversationSourceDiagnostic,
)
from loushang.harness.conversation.types import BranchDelta, ConversationTreeNode

H = TypeVar("H")
R = TypeVar("R")
S = TypeVar("S")


class ConversationRepository(Generic[H, R]):
    """Pure in-memory parent-linked conversation state."""

    def __init__(
        self,
        *,
        header: H,
        records: Sequence[R],
        record_id: Callable[[R], str],
        parent_id: Callable[[R], str | None],
        mode: BranchMode = "strict",
        leaf_id: str | None = None,
    ) -> None:
        self._header = header
        self._records = list(records)
        self._record_id = record_id
        self._parent_id = parent_id
        self._mode = mode
        self._graph = self._build_graph(self._records)
        self._leaf_id = self._resolve_initial_leaf(leaf_id)

    @classmethod
    def create(
        cls,
        *,
        header: H,
        records: Sequence[R] = (),
        record_id: Callable[[R], str],
        parent_id: Callable[[R], str | None],
        mode: BranchMode = "strict",
        leaf_id: str | None = None,
    ) -> ConversationRepository[H, R]:
        return cls(
            header=header,
            records=records,
            record_id=record_id,
            parent_id=parent_id,
            mode=mode,
            leaf_id=leaf_id,
        )

    @classmethod
    def from_snapshot(
        cls,
        snapshot: ConversationSnapshot[H, R],
        *,
        record_id: Callable[[R], str],
        parent_id: Callable[[R], str | None],
        mode: BranchMode = "strict",
        leaf_id: str | None = None,
    ) -> ConversationRepository[H, R]:
        return cls.create(
            header=snapshot.header,
            records=snapshot.records,
            record_id=record_id,
            parent_id=parent_id,
            mode=mode,
            leaf_id=leaf_id,
        )

    @classmethod
    def open(
        cls,
        load_result: ConversationLoadResult[H, R],
        *,
        record_id: Callable[[R], str],
        parent_id: Callable[[R], str | None],
        mode: BranchMode = "strict",
        leaf_id: str | None = None,
    ) -> ConversationOpenResult[H, R]:
        repository = cls.from_snapshot(
            load_result.snapshot,
            record_id=record_id,
            parent_id=parent_id,
            mode=mode,
            leaf_id=leaf_id,
        )
        return ConversationOpenResult(
            repository=repository,
            diagnostics=(*load_result.diagnostics, *repository.diagnostics),
        )

    @property
    def header(self) -> H:
        return self._header

    @property
    def records(self) -> tuple[R, ...]:
        return tuple(self._records)

    @property
    def leaf_id(self) -> str | None:
        return self._leaf_id

    @property
    def diagnostics(self) -> tuple[ConversationDiagnostic, ...]:
        return self._graph.diagnostics

    def append(self, record: R) -> str:
        candidate_records = [*self._records, record]
        candidate_graph = self._build_graph(candidate_records)
        record_id = self._record_id(record)
        if not isinstance(record_id, str) or not record_id:
            raise ValueError("Conversation record id must be a non-empty string")
        self._records = candidate_records
        self._graph = candidate_graph
        self._leaf_id = record_id
        return record_id

    def set_header(self, header: H) -> None:
        self._header = header

    def get(self, record_id: str) -> R | None:
        return self._graph.get(record_id)

    def leaf(self) -> R | None:
        return self.get(self._leaf_id) if self._leaf_id is not None else None

    def children(self, record_id: str) -> tuple[R, ...]:
        if self._graph.get(record_id) is None:
            return ()
        return self._graph.children(record_id)

    def branch(self, record_id: str) -> None:
        if self._graph.get(record_id) is None:
            raise ValueError(f"Conversation record {record_id} not found")
        self._leaf_id = record_id

    def reset_branch(self) -> None:
        self._leaf_id = None

    def active_records(self) -> tuple[R, ...]:
        return self._path_to()

    def records_to(self, record_id: str) -> tuple[R, ...]:
        return self._path_to(record_id)

    def lowest_common_ancestor(self, left_id: str, right_id: str) -> R | None:
        return self._graph.lowest_common_ancestor(left_id, right_id)

    def branch_delta(self, from_id: str, target_id: str) -> BranchDelta[R]:
        ancestor = self.lowest_common_ancestor(from_id, target_id)
        ancestor_id = self._record_id(ancestor) if ancestor is not None else None
        path = self.records_to(from_id)
        divergent_records = path
        if ancestor_id is not None:
            ancestor_position = next(
                index
                for index, record in enumerate(path)
                if self._record_id(record) == ancestor_id
            )
            divergent_records = path[ancestor_position + 1 :]
        return BranchDelta(
            from_id=from_id,
            target_id=target_id,
            common_ancestor_id=ancestor_id,
            divergent_records=divergent_records,
        )

    def tree(self) -> tuple[ConversationTreeNode[R], ...]:
        roots = self._graph.roots()
        nodes: dict[str, ConversationTreeNode[R]] = {}
        stack = [(root, False) for root in reversed(roots)]
        while stack:
            record, expanded = stack.pop()
            record_id = self._record_id(record)
            children = self.children(record_id)
            if expanded:
                nodes[record_id] = ConversationTreeNode(
                    record=record,
                    children=tuple(nodes[self._record_id(child)] for child in children),
                )
                continue
            stack.append((record, True))
            stack.extend((child, False) for child in reversed(children))
        return tuple(nodes[self._record_id(root)] for root in roots)

    def fold_active(self, folder: ConversationFolder[R, S]) -> S:
        return fold_records(self.active_records(), folder)

    def fold_all(self, folder: ConversationFolder[R, S]) -> S:
        return fold_records(self.records, folder)

    def fork(
        self,
        *,
        header: H,
        leaf_id: str | None = None,
    ) -> ConversationRepository[H, R]:
        selected_id = self._leaf_id if leaf_id is None else leaf_id
        records = self._path_to(selected_id) if selected_id is not None else ()
        return type(self).create(
            header=header,
            records=records,
            record_id=self._record_id,
            parent_id=self._parent_id,
            mode=self._mode,
        )

    def _build_graph(self, records: Sequence[R]) -> BranchGraph[R]:
        return BranchGraph(
            records,
            record_id=self._record_id,
            parent_id=self._parent_id,
            mode=self._mode,
        )

    def _path_to(self, record_id: str | None = None) -> tuple[R, ...]:
        selected_id = self._leaf_id if record_id is None else record_id
        if selected_id is None:
            return ()
        return self._graph.path(selected_id)

    def _resolve_initial_leaf(self, leaf_id: str | None) -> str | None:
        if leaf_id is not None:
            if self._graph.get(leaf_id) is None:
                raise ValueError(f"Conversation record {leaf_id} not found")
            return leaf_id
        if not self._records:
            return None
        candidate = self._record_id(self._records[-1])
        return candidate if self._graph.get(candidate) is not None else None


@dataclass(frozen=True)
class ConversationOpenResult(Generic[H, R]):
    repository: ConversationRepository[H, R]
    diagnostics: tuple[
        ConversationSourceDiagnostic | ConversationDiagnostic,
        ...,
    ] = ()


def fold_records(
    records: Sequence[R],
    folder: ConversationFolder[R, S],
) -> S:
    state = folder.initial()
    for record in records:
        state = folder.apply(state, record)
    return state


__all__ = ["ConversationOpenResult", "ConversationRepository", "fold_records"]
