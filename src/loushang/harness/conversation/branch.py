from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

from loushang.harness.conversation.diagnostics import ConversationDiagnostic

R = TypeVar("R")
BranchMode = Literal["strict", "compatible"]


class BranchGraphError(ValueError):
    def __init__(self, message: str, *, code: str, record_id: str) -> None:
        super().__init__(message)
        self.code = code
        self.record_id = record_id


@dataclass(frozen=True)
class ForkPlan(Generic[R]):
    selected_id: str
    records: tuple[R, ...]


class BranchGraph(Generic[R]):
    def __init__(
        self,
        records: Sequence[R],
        *,
        record_id: Callable[[R], str],
        parent_id: Callable[[R], str | None],
        mode: BranchMode = "strict",
    ) -> None:
        self._records = tuple(records)
        self._record_id = record_id
        self._parent_id = parent_id
        self._mode = mode
        self._diagnostics: list[ConversationDiagnostic] = []
        self._by_id: dict[str, R] = {}
        self._source_order: list[str] = []
        self._build_lookup()
        self._parents = self._normalize_parents()
        self._children = self._build_children()

    @property
    def diagnostics(self) -> tuple[ConversationDiagnostic, ...]:
        return tuple(self._diagnostics)

    @property
    def records(self) -> tuple[R, ...]:
        return tuple(self._by_id[record_id] for record_id in self._source_order)

    def get(self, record_id: str) -> R | None:
        return self._by_id.get(record_id)

    def roots(self) -> tuple[R, ...]:
        return tuple(
            self._by_id[record_id]
            for record_id in self._source_order
            if self._parents[record_id] is None
        )

    def leaves(self) -> tuple[R, ...]:
        return tuple(
            self._by_id[record_id]
            for record_id in self._source_order
            if not self._children[record_id]
        )

    def children(self, record_id: str) -> tuple[R, ...]:
        self._require_record(record_id)
        return tuple(self._by_id[child_id] for child_id in self._children[record_id])

    def path(self, record_id: str) -> tuple[R, ...]:
        self._require_record(record_id)
        ids: list[str] = []
        seen: set[str] = set()
        current_id: str | None = record_id
        while current_id is not None and current_id not in seen:
            seen.add(current_id)
            ids.append(current_id)
            current_id = self._parents[current_id]
        ids.reverse()
        return tuple(self._by_id[item_id] for item_id in ids)

    def ancestors(self, record_id: str) -> tuple[R, ...]:
        path = self.path(record_id)
        return path[:-1]

    def lowest_common_ancestor(self, left_id: str, right_id: str) -> R | None:
        left_path = [self._record_id(record) for record in self.path(left_id)]
        right_path = [self._record_id(record) for record in self.path(right_id)]
        common_id: str | None = None
        for left, right in zip(left_path, right_path, strict=False):
            if left != right:
                break
            common_id = left
        return self._by_id.get(common_id) if common_id is not None else None

    def fork_plan(self, selected_id: str) -> ForkPlan[R]:
        return ForkPlan(selected_id=selected_id, records=self.path(selected_id))

    def _build_lookup(self) -> None:
        positions: dict[str, int] = {}
        for position, record in enumerate(self._records):
            record_id = self._record_id(record)
            if not isinstance(record_id, str) or not record_id:
                self._problem(
                    "invalid_branch_record_id",
                    "Branch record id must be a non-empty string.",
                    record_id=str(record_id),
                )
                continue
            if record_id in self._by_id:
                self._problem(
                    "duplicate_branch_record_id",
                    f"Duplicate branch record id: {record_id}",
                    record_id=record_id,
                )
            self._by_id[record_id] = record
            positions[record_id] = position
        self._source_order = sorted(positions, key=positions.__getitem__)

    def _normalize_parents(self) -> dict[str, str | None]:
        parents: dict[str, str | None] = {}
        for record_id in self._source_order:
            parent = self._parent_id(self._by_id[record_id])
            if parent is None:
                parents[record_id] = None
            elif parent == record_id:
                self._problem(
                    "self_parent_branch_record",
                    f"Branch record {record_id} refers to itself as parent.",
                    record_id=record_id,
                )
                parents[record_id] = None
            elif parent not in self._by_id:
                self._problem(
                    "dangling_branch_parent",
                    f"Branch record {record_id} refers to missing parent {parent}.",
                    record_id=record_id,
                )
                parents[record_id] = None
            else:
                parents[record_id] = parent

        while True:
            cycle = _find_cycle(self._source_order, parents)
            if cycle is None:
                break
            cut_id = cycle[0]
            self._problem(
                "branch_parent_cycle",
                f"Branch parent cycle detected at {cut_id}.",
                record_id=cut_id,
            )
            parents[cut_id] = None
        return parents

    def _build_children(self) -> dict[str, list[str]]:
        children: dict[str, list[str]] = {
            record_id: [] for record_id in self._source_order
        }
        for record_id in self._source_order:
            parent = self._parents[record_id]
            if parent is not None:
                children[parent].append(record_id)
        return children

    def _problem(self, code: str, message: str, *, record_id: str) -> None:
        if self._mode == "strict":
            raise BranchGraphError(message, code=code, record_id=record_id)
        self._diagnostics.append(
            ConversationDiagnostic(
                code=code,
                message=message,
                record_id=record_id,
                details={"record_id": record_id},
            )
        )

    def _require_record(self, record_id: str) -> None:
        if record_id not in self._by_id:
            raise ValueError(f"Branch record {record_id} not found")


def _find_cycle(
    source_order: Sequence[str],
    parents: dict[str, str | None],
) -> list[str] | None:
    fully_visited: set[str] = set()
    for start_id in source_order:
        if start_id in fully_visited:
            continue
        path: list[str] = []
        positions: dict[str, int] = {}
        current_id: str | None = start_id
        while current_id is not None and current_id not in fully_visited:
            if current_id in positions:
                return path[positions[current_id] :]
            positions[current_id] = len(path)
            path.append(current_id)
            current_id = parents[current_id]
        fully_visited.update(path)
    return None


__all__ = [
    "BranchGraph",
    "BranchGraphError",
    "BranchMode",
    "ForkPlan",
]
