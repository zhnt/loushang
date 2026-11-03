from __future__ import annotations

from dataclasses import replace

import pytest

from loushang.coding.composition_provenance import CodingCompositionProvenanceV1
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.resume_composition_comparison import (
    compare_coding_resume_composition,
)
from loushang.coding.resume_history import (
    CodingResumeHeaderPreview,
    CodingResumeHistoryPreview,
)
from loushang.harness.conversation import ConversationHeader


def _history() -> CodingResumeHistoryPreview:
    standard = resolve_coding_composition_set("coding-standard")
    return CodingResumeHistoryPreview(
        header_preview=CodingResumeHeaderPreview(
            header=ConversationHeader(
                conversation_id="session-1", version=1,
                created_at="2026-10-12T00:00:00Z",
            ),
            product_identity="coding",
            composition=CodingCompositionProvenanceV1(
                standard.set_id, standard.fingerprint,
            ),
        ),
        records=(), selected_records=(), selected_leaf_id=None,
        startup=None, provenance_conflict=False,
        binding_status="none", binding=None,
        selected_ancestry_digest="a" * 64,
        source_fingerprint="stat-v1:fixture",
        source_content_digest="b" * 64,
    )


def test_comparison_separates_exact_choice_from_changed_set_and_definition() -> None:
    history = _history()
    standard = resolve_coding_composition_set("coding-standard")
    minimal = resolve_coding_composition_set("coding-minimal")

    assert compare_coding_resume_composition(history, standard).status == "same"
    changed = compare_coding_resume_composition(history, minimal)
    assert changed.status == "changed"
    assert changed.difference_codes == ("composition.set_changed",)

    revised_header = replace(
        history.header_preview,
        composition=CodingCompositionProvenanceV1(
            standard.set_id, "b" * 64,
        ),
    )
    revised = compare_coding_resume_composition(
        replace(history, header_preview=revised_header), standard,
    )
    assert revised.status == "changed"
    assert revised.difference_codes == ("composition.definition_changed",)


def test_comparison_keeps_legacy_and_unverified_evidence_distinct() -> None:
    history = _history()
    standard = resolve_coding_composition_set("coding-standard")
    legacy = replace(
        history, header_preview=replace(history.header_preview, composition=None),
    )
    assert compare_coding_resume_composition(
        legacy, standard,
    ).status == "legacy_unknown"

    for changed in (
        replace(history, provenance_conflict=True),
        replace(history, selected_ancestry_digest=None),
        replace(history, binding_status="unknown_version"),
        replace(history, binding_status="invalid"),
        replace(
            history,
            header_preview=replace(history.header_preview, product_identity="unknown"),
        ),
    ):
        result = compare_coding_resume_composition(changed, standard)
        assert result.status == "unavailable"
        assert len(result.reason_codes) == 1


def test_comparison_rejects_noncanonical_current_selection() -> None:
    history = _history()
    standard = resolve_coding_composition_set("coding-standard")
    altered = replace(standard, plugin_requests=())
    with pytest.raises(ValueError, match="canonical"):
        compare_coding_resume_composition(history, altered)
