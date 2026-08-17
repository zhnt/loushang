from __future__ import annotations

import json
from dataclasses import asdict, fields

from loushang.harness.continuity import ContinuitySummary, ContinuityTarget


def test_common_summary_is_a_fixed_json_safe_product_neutral_envelope() -> None:
    summary = ContinuitySummary(
        target=ContinuityTarget(
            provider_id="presentation.decks",
            opaque_id="opaque-deck-id",
            revision="revision-7",
        ),
        domain_ids=("presentation",),
        primary_domain_id="presentation",
        title="Quarterly review",
        updated_at="2026-07-24T10:00:00+00:00",
        created_at="2026-07-20T09:00:00+00:00",
        subtitle="Draft",
        excerpt="Review the latest narrative.",
        status="active",
    )

    assert tuple(field.name for field in fields(ContinuitySummary)) == (
        "target",
        "domain_ids",
        "primary_domain_id",
        "title",
        "updated_at",
        "created_at",
        "subtitle",
        "excerpt",
        "status",
    )
    encoded = json.dumps(asdict(summary))
    for product_field in (
        "branch",
        "worktree",
        "repository",
        "model",
        "slide_count",
        "canvas_team",
        "renderer",
    ):
        assert product_field not in encoded
