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
