from __future__ import annotations

from dataclasses import dataclass

import pytest

from loushang.harness.conversation import (
    ConversationCheckpoint,
    ConversationReplayFolder,
    ConversationReplayPorts,
    ConversationRepository,
    MissingCheckpointPolicy,
)


@dataclass(frozen=True)
class ResearchRecord:
    record_id: str
    parent_id: str | None
    kind: str
    text: str
    first_kept_record_id: str | None = None


@dataclass(frozen=True)
class ResearchState:
    visited_record_ids: tuple[str, ...] = ()
    evidence_count: int = 0


def _replay_folder(
    *,
    missing_checkpoint: MissingCheckpointPolicy = "summary_only",
) -> ConversationReplayFolder[
    ResearchRecord, str, ResearchState
]:
    def resolve_checkpoint(
        record: ResearchRecord,
    ) -> ConversationCheckpoint[str] | None:
        if record.kind != "checkpoint":
            return None
        assert record.first_kept_record_id is not None
        return ConversationCheckpoint(
            first_kept_record_id=record.first_kept_record_id,
            summary_item=f"summary:{record.text}",
        )

    def reduce_state(
        state: ResearchState,
        record: ResearchRecord,
    ) -> ResearchState:
        return ResearchState(
            visited_record_ids=(*state.visited_record_ids, record.record_id),
            evidence_count=state.evidence_count + (record.kind == "evidence"),
        )

    return ConversationReplayFolder(
        ConversationReplayPorts(
            record_id=lambda record: record.record_id,
            project_visible_item=lambda record: (
                f"{record.kind}:{record.text}"
                if record.kind in {"question", "evidence", "note"}
                else None
            ),
            initialize_state=ResearchState,
            reduce_state=reduce_state,
            resolve_checkpoint=resolve_checkpoint,
        ),
        missing_checkpoint=missing_checkpoint,
    )


def _record(
    record_id: str,
    parent_id: str | None,
    kind: str,
    text: str,
    *,
    first_kept_record_id: str | None = None,
) -> ResearchRecord:
    return ResearchRecord(
        record_id=record_id,
        parent_id=parent_id,
        kind=kind,
        text=text,
        first_kept_record_id=first_kept_record_id,
    )


def test_multiple_checkpoints_rebuild_items_without_compacting_product_state() -> None:
    records = (
        _record("q", None, "question", "How is demand changing?"),
        _record("e1", "q", "evidence", "Read filings"),
        _record("n1", "e1", "note", "Demand is rising"),
        _record(
            "c1",
            "n1",
            "checkpoint",
            "Initial evidence",
            first_kept_record_id="e1",
        ),
        _record("e2", "c1", "evidence", "Run interviews"),
        _record(
            "c2",
            "e2",
            "checkpoint",
            "Cross-checked evidence",
            first_kept_record_id="n1",
        ),
        _record("n2", "c2", "note", "Demand is regional"),
    )

    projection = _replay_folder().replay(records)

    assert projection.items == (
        "summary:Cross-checked evidence",
        "note:Demand is rising",
        "evidence:Run interviews",
        "note:Demand is regional",
    )
    assert projection.item_record_ids == ("c2", "n1", "e2", "n2")
    assert projection.state == ResearchState(
        visited_record_ids=("q", "e1", "n1", "c1", "e2", "c2", "n2"),
        evidence_count=2,
    )


def test_latest_checkpoint_skips_superseded_projection_but_folds_all_state() -> None:
    records = (
        _record("old", None, "question", "Malformed historical question"),
        _record("kept", "old", "evidence", "Retained evidence"),
        _record(
            "old-checkpoint",
            "kept",
            "checkpoint",
            "Malformed historical checkpoint",
            first_kept_record_id="kept",
        ),
        _record("note", "old-checkpoint", "note", "Retained note"),
        _record(
            "latest-checkpoint",
            "note",
            "checkpoint",
            "Current summary",
            first_kept_record_id="note",
        ),
        _record("tail", "latest-checkpoint", "note", "New note"),
    )
    projected_ids: list[str] = []
    checkpoint_resolver_ids: list[str] = []

    def project_visible_item(record: ResearchRecord) -> str | None:
        projected_ids.append(record.record_id)
        if record.record_id == "old":
            raise AssertionError("superseded record must not be projected")
        if record.kind == "checkpoint":
            return None
        return f"{record.kind}:{record.text}"

    def resolve_checkpoint(
        record: ResearchRecord,
    ) -> ConversationCheckpoint[str] | None:
        checkpoint_resolver_ids.append(record.record_id)
        if record.record_id == "old-checkpoint":
            raise AssertionError("superseded checkpoint must not be resolved")
        if record.kind != "checkpoint":
            return None
        assert record.first_kept_record_id is not None
        return ConversationCheckpoint(
            first_kept_record_id=record.first_kept_record_id,
            summary_item=f"summary:{record.text}",
        )

    folder = ConversationReplayFolder(
        ConversationReplayPorts(
            record_id=lambda record: record.record_id,
            project_visible_item=project_visible_item,
            initialize_state=ResearchState,
            reduce_state=lambda state, record: ResearchState(
                visited_record_ids=(*state.visited_record_ids, record.record_id),
                evidence_count=state.evidence_count
                + (record.kind == "evidence"),
            ),
            resolve_checkpoint=resolve_checkpoint,
        )
    )

    projection = folder.replay(records)

    assert projection.items == (
        "summary:Current summary",
        "note:Retained note",
        "note:New note",
    )
    assert projection.state.visited_record_ids == tuple(
        record.record_id for record in records
    )
    assert projected_ids == ["note", "tail"]
    assert checkpoint_resolver_ids == ["tail", "latest-checkpoint"]


def test_missing_checkpoint_boundary_keeps_summary_then_appends_later_items() -> None:
    records = (
        _record("q", None, "question", "What changed?"),
        _record(
            "c1",
            "q",
            "checkpoint",
            "Prior work unavailable",
            first_kept_record_id="missing",
        ),
        _record("e1", "c1", "evidence", "New filing"),
    )

    projection = _replay_folder().replay(records)

    assert projection.items == (
        "summary:Prior work unavailable",
        "evidence:New filing",
    )
    assert projection.item_record_ids == ("c1", "e1")
    assert projection.state.visited_record_ids == ("q", "c1", "e1")
    assert projection.state.evidence_count == 1


def test_missing_checkpoint_boundary_is_strict_by_default() -> None:
    strict = _replay_folder(missing_checkpoint="error")
    records = (
        _record("q", None, "question", "What changed?"),
        _record(
            "c1",
            "q",
            "checkpoint",
            "Prior work unavailable",
            first_kept_record_id="missing",
        ),
    )

    with pytest.raises(ValueError, match="missing record missing"):
        strict.replay(records)


def test_replay_folds_only_the_repository_active_path() -> None:
    repository = ConversationRepository.create(
        header={"id": "research"},
        records=(
            _record("q", None, "question", "What changed?"),
            _record("left", "q", "evidence", "Filing evidence"),
            _record("right", "q", "evidence", "Interview evidence"),
        ),
        record_id=lambda record: record.record_id,
        parent_id=lambda record: record.parent_id,
        leaf_id="left",
    )

    projection = _replay_folder().replay(repository.active_records())

    assert projection.items == (
        "question:What changed?",
        "evidence:Filing evidence",
    )
    assert projection.item_record_ids == ("q", "left")
    assert projection.state.visited_record_ids == ("q", "left")


def test_replay_rejects_duplicate_ids_and_invalid_checkpoint_results() -> None:
    duplicate = _record("same", None, "question", "one")
    with pytest.raises(ValueError, match="duplicate conversation record id"):
        _replay_folder().replay((duplicate, duplicate))

    invalid_folder = ConversationReplayFolder(
        ConversationReplayPorts[
            ResearchRecord,
            str,
            ResearchState,
        ](
            record_id=lambda record: record.record_id,
            project_visible_item=lambda record: record.text,
            initialize_state=ResearchState,
            reduce_state=lambda state, record: state,
            resolve_checkpoint=lambda record: "invalid",  # type: ignore[arg-type,return-value]
        )
    )
    with pytest.raises(TypeError, match="checkpoint resolver"):
        invalid_folder.replay((_record("q", None, "question", "one"),))
