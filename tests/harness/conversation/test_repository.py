from __future__ import annotations

from dataclasses import dataclass

import pytest

from loushang.harness.conversation import (
    BranchGraphError,
    ConversationLoadResult,
    ConversationRepository,
    ConversationSnapshot,
    ConversationSourceDiagnostic,
)


@dataclass(frozen=True)
class _Header:
    transcript_id: str


@dataclass(frozen=True)
class _Record:
    record_id: str
    parent_id: str | None
    text: str


def _repository(
    *,
    header: _Header | None = None,
    records: tuple[_Record, ...] = (),
) -> ConversationRepository[_Header, _Record]:
    return ConversationRepository.create(
        header=header or _Header("t1"),
        records=records,
        record_id=lambda record: record.record_id,
        parent_id=lambda record: record.parent_id,
    )


def test_repository_tracks_active_branch_in_memory() -> None:
    repository = _repository()
    repository.append(_Record("root", None, "one"))
    repository.append(_Record("left", "root", "two"))
    repository.branch("root")
    repository.append(_Record("right", "root", "three"))

    assert repository.leaf_id == "right"
    assert repository.active_records() == (
        _Record("root", None, "one"),
        _Record("right", "root", "three"),
    )
    assert repository.children("root") == (
        _Record("left", "root", "two"),
        _Record("right", "root", "three"),
    )


def test_repository_forks_selected_path_without_source_mutation() -> None:
    source = _repository(
        header=_Header("source"),
        records=(
            _Record("root", None, "one"),
            _Record("left", "root", "two"),
            _Record("right", "root", "three"),
        ),
    )

    forked = source.fork(header=_Header("fork"), leaf_id="left")

    assert forked.header == _Header("fork")
    assert forked.records == (
        _Record("root", None, "one"),
        _Record("left", "root", "two"),
    )
    assert forked.leaf_id == "left"
    assert source.records[-1].record_id == "right"


def test_repository_does_not_mutate_when_candidate_is_invalid() -> None:
    repository = _repository(records=(_Record("root", None, "one"),))

    with pytest.raises(BranchGraphError, match="missing parent"):
        repository.append(_Record("next", "missing", "two"))

    assert repository.records == (_Record("root", None, "one"),)
    assert repository.leaf_id == "root"


def test_repository_with_appended_keeps_selected_branch_and_source_detached() -> None:
    root = _Record("root", None, "root")
    left = _Record("left", "root", "left")
    right = _Record("right", "root", "right")
    source = _repository(records=(root, left))
    source.branch("root")
    candidate = source.with_appended(right)

    assert candidate.records == (root, left, right)
    assert candidate.active_records() == (root, right)
    assert candidate.children("root") == (left, right)
    assert source.records == (root, left)
    assert source.active_records() == (root,)
    assert source.children("root") == (left,)
    source.append(_Record("later", "root", "later"))
    assert candidate.children("root") == (left, right)

    with pytest.raises(BranchGraphError, match="missing parent"):
        source.with_appended(_Record("invalid", "missing", "invalid"))
    assert source.leaf_id == "later"


def test_repository_batch_candidates_preserve_source_and_empty_selection() -> None:
    root = _Record("root", None, "root")
    source = _repository(records=(root,))
    source.reset_branch()
    empty = source.with_appended_records(())
    empty.branch("root")
    assert source.leaf_id is None
    child = _Record("child", "root", "child")
    tail = _Record("tail", "child", "tail")
    candidate = source.with_appended_records((child, tail))
    assert candidate.active_records() == (root, child, tail)
    assert source.records == (root,)
    assert source.leaf_id is None


def test_incremental_publish_waits_for_receipt_and_preserves_detached_graph() -> None:
    root = _Record("root", None, "root")
    left = _Record("left", "root", "left")
    right = _Record("right", "root", "right")
    tail = _Record("tail", "right", "tail")
    source = _repository(records=(root, left))
    source.branch("root")
    detached = source.with_appended(_Record("candidate", "root", "candidate"))

    plan = source.prepare_incremental_append((right, tail))
    assert plan is not None
    assert source.records == (root, left)
    assert source.children("root") == (left,)
    source.publish_incremental_append(plan)
    assert source.records == (root, left, right, tail)
    assert source.active_records() == (root, right, tail)
    assert source.children("root") == (left, right)
    assert detached.children("root") == (
        left,
        _Record("candidate", "root", "candidate"),
    )
    with pytest.raises(BranchGraphError, match="missing parent"):
        source.prepare_incremental_append((_Record("bad", "missing", "bad"),))
    assert source.records == (root, left, right, tail)


def test_incremental_publish_rejects_changed_selection() -> None:
    root = _Record("root", None, "root")
    source = _repository(records=(root,))
    plan = source.prepare_incremental_append((_Record("child", "root", "child"),))
    assert plan is not None
    source.reset_branch()
    with pytest.raises(RuntimeError, match="selection changed"):
        source.publish_incremental_append(plan)
    assert source.records == (root,)


def test_incremental_publish_matches_detached_graph_for_out_of_order_suffix() -> None:
    root = _Record("root", None, "root")
    source = _repository(records=(root,))
    appended = (
        _Record("child", "parent", "child"),
        _Record("parent", "root", "parent"),
        _Record("sibling", "parent", "sibling"),
    )
    expected = source.with_appended_records(appended)
    plan = source.prepare_incremental_append(appended)
    assert plan is not None
    source.publish_incremental_append(plan)
    assert source.records == expected.records
    assert source.active_records() == expected.active_records()
    assert source.tree() == expected.tree()
    for record in (root, *appended):
        assert source.children(record.record_id) == expected.children(record.record_id)


def test_repository_open_preserves_store_and_semantic_diagnostics() -> None:
    load_diagnostic = ConversationSourceDiagnostic(
        code="partial_journal_tail",
        message="A partial tail was ignored.",
    )
    result = ConversationRepository.open(
        ConversationLoadResult(
            snapshot=ConversationSnapshot(
                header=_Header("source"),
                records=(_Record("orphan", "missing", "compatible"),),
                revision=1,
            ),
            diagnostics=(load_diagnostic,),
        ),
        record_id=lambda record: record.record_id,
        parent_id=lambda record: record.parent_id,
        mode="compatible",
    )

    assert result.repository.records[0].record_id == "orphan"
    assert result.diagnostics[0] == load_diagnostic
    assert result.diagnostics[1].code == "dangling_branch_parent"
