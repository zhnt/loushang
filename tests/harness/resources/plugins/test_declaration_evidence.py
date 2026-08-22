from __future__ import annotations

from dataclasses import fields

import pytest

from loushang.harness.resources.plugins.selection import (
    PluginContributionCandidate,
    PluginDeclarationBatch,
    PluginDocumentDecodedEvidence,
)


def test_document_evidence_and_batch_field_ownership_is_exact() -> None:
    assert tuple(item.name for item in fields(PluginDocumentDecodedEvidence)) == (
        "declaration_set_fingerprint",
        "document_bytes_digest",
        "document_schema_version",
        "evidence_version",
        "kind",
        "package_content_digest",
        "preflight_use_id",
        "reservation_closure_fingerprint",
        "source_descriptor_fingerprint",
        "source_group_fingerprint",
        "source_group_id",
    )
    assert tuple(item.name for item in fields(PluginDeclarationBatch)) == (
        "preflight_use_id",
        "source_group_id",
        "source_group_fingerprint",
        "declarations",
        "evidence",
    )


def test_candidate_owns_exact_declaration_and_evidence_without_decision_peer() -> None:
    assert tuple(item.name for item in fields(PluginContributionCandidate)) == (
        "package",
        "declaration",
        "evidence",
        "fingerprint",
    )
    candidate_fields = {
        item.name for item in fields(PluginContributionCandidate)
    }
    assert not {
        "decision_id",
        "approval_subject",
        "receipt",
        "source_group_fingerprint",
    }.intersection(candidate_fields)


@pytest.mark.parametrize(
    "record_type",
    (
        PluginDocumentDecodedEvidence,
        PluginDeclarationBatch,
        PluginContributionCandidate,
    ),
)
def test_declaration_evidence_records_have_no_public_constructor(
    record_type: type[object],
) -> None:
    with pytest.raises(TypeError, match="Host-constructed"):
        record_type()
