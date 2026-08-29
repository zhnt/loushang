from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.harness.cli.skill_listing import SkillListingError, list_skill_records


def test_skill_listing_requires_exact_v4_session_capture_without_loader_fallback(
) -> None:
    legacy_session = SimpleNamespace(
        resource_bundle=SimpleNamespace(skills=[SimpleNamespace(name="legacy")]),
        resource_loader=SimpleNamespace(
            get_skills=lambda: [SimpleNamespace(name="rediscovered")]
        ),
    )

    with pytest.raises(SkillListingError, match="v4 capture is not available"):
        list_skill_records(legacy_session)


def test_skill_listing_rejects_non_tuple_catalog_response() -> None:
    session = SimpleNamespace(
        list_skill_statuses=lambda: [
            SimpleNamespace(
                name="review",
                status="effective",
                source_path=Path("/skills/review/SKILL.md"),
            )
        ]
    )

    with pytest.raises(SkillListingError, match="invalid response"):
        list_skill_records(session)


def test_skill_listing_rejects_malformed_catalog_status_record() -> None:
    session = SimpleNamespace(
        list_skill_statuses=lambda: (
            SimpleNamespace(name="review", status=None),
        )
    )

    with pytest.raises(SkillListingError, match="invalid status record"):
        list_skill_records(session)
