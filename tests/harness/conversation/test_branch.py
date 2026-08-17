from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _Record:
    record_id: str
    parent_id: str | None
    value: str = ""


def _graph(records, *, mode="strict"):
    from loushang.harness.conversation import BranchGraph

    return BranchGraph(
        records,
        record_id=lambda record: record.record_id,
        parent_id=lambda record: record.parent_id,
        mode=mode,
    )


def test_branch_graph_paths_children_lca_and_fork_plan() -> None:
    records = (
        _Record("root", None),
        _Record("left", "root"),
        _Record("left-tail", "left"),
        _Record("right", "root"),
    )
    graph = _graph(records)

    assert [record.record_id for record in graph.roots()] == ["root"]
    assert [record.record_id for record in graph.children("root")] == [
        "left",
        "right",
    ]
    assert [record.record_id for record in graph.leaves()] == [
        "left-tail",
        "right",
    ]
    assert [record.record_id for record in graph.path("left-tail")] == [
        "root",
        "left",
        "left-tail",
    ]
    assert graph.lowest_common_ancestor("left-tail", "right") == records[0]
    assert graph.fork_plan("left-tail").records == records[:3]


def test_compatible_graph_uses_last_duplicate_and_promotes_invalid_parents() -> None:
    graph = _graph(
        (
            _Record("duplicate", None, "old"),
            _Record("dangling", "missing"),
            _Record("self", "self"),
            _Record("duplicate", None, "new"),
        ),
        mode="compatible",
    )

    assert graph.get("duplicate") == _Record("duplicate", None, "new")
    assert [record.record_id for record in graph.roots()] == [
        "dangling",
        "self",
        "duplicate",
    ]
    assert [diagnostic.code for diagnostic in graph.diagnostics] == [
        "duplicate_branch_record_id",
        "dangling_branch_parent",
        "self_parent_branch_record",
    ]


def test_compatible_graph_cuts_cycles_deterministically() -> None:
    graph = _graph(
        (
            _Record("a", "c"),
            _Record("b", "a"),
            _Record("c", "b"),
        ),
        mode="compatible",
    )

    assert [record.record_id for record in graph.roots()] == ["a"]
    assert [record.record_id for record in graph.path("c")] == ["a", "b", "c"]
    assert graph.diagnostics[-1].code == "branch_parent_cycle"


def test_strict_graph_rejects_corruption() -> None:
    import pytest

    from loushang.harness.conversation import BranchGraphError

    with pytest.raises(BranchGraphError) as exc_info:
        _graph((_Record("child", "missing"),))

    assert exc_info.value.code == "dangling_branch_parent"
