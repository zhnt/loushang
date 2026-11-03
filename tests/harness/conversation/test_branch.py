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


def test_repeated_paths_and_strict_extensions_do_not_walk_the_old_prefix() -> None:
    class ParentReads(dict):
        reads = 0

        def __getitem__(self, key):
            self.reads += 1
            return super().__getitem__(key)

    records = tuple(
        _Record(str(index), str(index - 1) if index else None)
        for index in range(2000)
    )
    graph = _graph(records)
    parents = ParentReads(graph._parents)
    graph._parents = parents
    assert graph.path("1999") == records
    parents.reads = 0
    assert graph.path("1999") == records
    assert parents.reads == 0, "repeated path walked the complete history"

    extended = graph.with_appended(_Record("tail", "1999"))
    extended_parents = ParentReads(extended._parents)
    extended._parents = extended_parents
    assert extended.path("tail") == (*records, _Record("tail", "1999"))
    assert extended_parents.reads == 1, "append walked the unchanged prefix"
    assert graph.path("1999") == records
    assert graph.get("tail") is None
    right = extended.with_appended(_Record("right", "0"))
    assert right.path("right") == (records[0], _Record("right", "0"))
    assert right.path("tail") == extended.path("tail")


def test_compatible_extension_rebuilds_a_previously_cached_repaired_path() -> None:
    graph = _graph((_Record("tail", "missing"),), mode="compatible")
    assert graph.path("tail") == (_Record("tail", "missing"),)
    repaired = graph.with_appended(_Record("missing", None))
    assert repaired.path("tail") == (
        _Record("missing", None), _Record("tail", "missing")
    )
    replaced = repaired.with_appended(_Record("tail", None, "replacement"))
    assert replaced.path("tail") == (_Record("tail", None, "replacement"),)
    assert graph.path("tail") == (_Record("tail", "missing"),)


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


def test_appended_graph_preserves_existing_snapshots_without_rechecking_history() -> (
    None
):
    from loushang.harness.conversation import BranchGraph

    reads: list[str] = []
    records = tuple(_Record(str(i), str(i - 1) if i else None) for i in range(2000))

    def record_id(record: _Record) -> str:
        reads.append(record.record_id)
        return record.record_id

    graph = BranchGraph(records, record_id=record_id, parent_id=lambda r: r.parent_id)
    reads.clear()
    next_record = _Record("next", "1999")
    candidate = graph.with_appended(next_record)

    assert reads == ["next"]
    assert candidate.path("next") == (*records, next_record)
    assert graph.get("next") is None
    assert graph.children("1999") == ()
    assert candidate.children("1999") == (next_record,)
    sibling = graph.with_appended(_Record("sibling", "1999"))
    assert candidate.children("1999") == (next_record,)
    assert sibling.children("1999") == (_Record("sibling", "1999"),)


def test_appended_graph_matches_rebuild_for_invalid_and_compatible_records() -> None:
    import pytest

    from loushang.harness.conversation import BranchGraphError

    records = (_Record("root", None),)
    graph = _graph(records)
    for record in (
        _Record("", None),
        _Record("root", None),
        _Record("self", "self"),
        _Record("next", "missing"),
    ):
        with pytest.raises(BranchGraphError) as expected:
            _graph((*records, record))
        with pytest.raises(BranchGraphError) as actual:
            graph.with_appended(record)
        assert (actual.value.code, actual.value.record_id) == (
            expected.value.code,
            expected.value.record_id,
        )
        assert graph.records == records

    # Compatible input can contain a forward reference. Adding its missing
    # parent must re-normalize the old edge instead of freezing its old repair.
    orphan = _Record("orphan", "parent")
    compatible = _graph((orphan,), mode="compatible")
    parent = _Record("parent", None)
    candidate = compatible.with_appended(parent)
    rebuilt = _graph((orphan, parent), mode="compatible")
    assert candidate.path("orphan") == rebuilt.path("orphan") == (parent, orphan)
    assert candidate.diagnostics == rebuilt.diagnostics == ()
    assert compatible.path("orphan") == (orphan,)


def test_batch_extension_reuses_prefix_links_and_detaches_changed_children() -> None:
    from loushang.harness.conversation import BranchGraph

    reads: list[str] = []
    records = tuple(_Record(str(i), str(i - 1) if i else None) for i in range(2000))

    def record_id(record: _Record) -> str:
        reads.append(record.record_id)
        return record.record_id

    graph = BranchGraph(records, record_id=record_id, parent_id=lambda r: r.parent_id)
    reads.clear()
    # Forward references within a batch are valid, as in the full constructor.
    child = _Record("child", "parent")
    parent = _Record("parent", "1999")
    sibling = _Record("sibling", "1999")
    candidate = graph.with_appended_records((child, parent, sibling))

    assert reads == ["child", "parent", "sibling"]
    assert candidate.path("child") == (*records, parent, child)
    assert candidate.children("1999") == (parent, sibling)
    assert graph.children("1999") == ()
    assert graph.get("child") is None
    next_candidate = candidate.with_appended(_Record("other", "parent"))
    assert next_candidate.children("parent") == (child, _Record("other", "parent"))
    assert candidate.children("parent") == (child,)


def test_batch_extension_rejects_corruption_before_publishing_any_node() -> None:
    import pytest

    from loushang.harness.conversation import BranchGraphError

    records = (_Record("root", None),)
    graph = _graph(records)
    batches = (
        (_Record("a", "b"), _Record("b", "a")),
        (_Record("a", "missing"), _Record("a", None)),
        (_Record("a", "root"), _Record("root", None)),
        (_Record("a", "root"), _Record("b", "missing")),
        (_Record("a", "root"), _Record("", None)),
    )
    for batch in batches:
        with pytest.raises(BranchGraphError) as expected:
            _graph((*records, *batch))
        with pytest.raises(BranchGraphError) as actual:
            graph.with_appended_records(batch)
        assert (actual.value.code, actual.value.record_id) == (
            expected.value.code,
            expected.value.record_id,
        )
        assert graph.records == records
        assert graph.children("root") == ()
