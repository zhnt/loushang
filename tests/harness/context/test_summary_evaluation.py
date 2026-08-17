from __future__ import annotations

import json

import pytest

from loushang.harness.context import (
    STANDARD_SUMMARY_RESOURCE_OPERATION_TAGS,
    SummaryEvaluationCase,
    SummaryProfile,
    SummaryResourceOperations,
    SummaryResourceOperationTag,
    SummarySection,
    evaluate_summary_case,
    evaluate_summary_fixture,
    extract_summary_resource_operations,
)


def _profile(
    profile_id: str = "research.checkpoint",
    *,
    section: str = "Findings",
    resource_operation_tags: tuple[SummaryResourceOperationTag, ...] = (
        STANDARD_SUMMARY_RESOURCE_OPERATION_TAGS
    ),
) -> SummaryProfile:
    return SummaryProfile(
        profile_id=profile_id,
        system_prompt="Summarize the work.",
        prompts={"initial": "Produce a checkpoint."},
        sections=(SummarySection("Goal"), SummarySection(section)),
        resource_operation_tags=resource_operation_tags,
    )


def test_evaluation_extracts_profile_declared_resource_operations() -> None:
    profile = _profile()
    summary = """## Goal
Record research evidence.

## Findings
- The report is complete.

<read-files>
## Evidence inventory
notes.md
notes.md
</read-files>

<modified-files>
report.md
</modified-files>"""

    result = evaluate_summary_case(
        SummaryEvaluationCase(
            name="resource-evidence",
            summary=summary,
            profile_id=profile.profile_id,
            expected_resource_operations=SummaryResourceOperations.from_mapping(
                {
                    "read": ("## Evidence inventory", "notes.md"),
                    "modified": ("report.md",),
                }
            ),
        ),
        profile=profile,
    )

    assert result.ok is True
    assert result.validation.ok is True
    assert result.resource_operations.to_dict() == {
        "read": ["## Evidence inventory", "notes.md"],
        "modified": ["report.md"],
    }


def test_evaluation_supports_product_defined_operation_names() -> None:
    profile = _profile(
        resource_operation_tags=(
            SummaryResourceOperationTag(operation="cited", tag="citations"),
        )
    )
    summary = """## Goal
Record sources.

## Findings
- A claim is supported.

<citations>
annual-report.pdf
</citations>"""

    operations = extract_summary_resource_operations(summary, profile)

    assert operations.to_dict() == {"cited": ["annual-report.pdf"]}


def test_resource_operation_contract_rejects_invalid_public_inputs() -> None:
    with pytest.raises(TypeError, match="must be a mapping"):
        SummaryResourceOperations.from_mapping([("read", ["notes.md"])])  # type: ignore[arg-type]

    with pytest.raises(TypeError, match="sequence of strings"):
        SummaryResourceOperations.from_mapping({"read": "notes.md"})

    with pytest.raises(TypeError, match="SummaryResourceOperationTag"):
        _profile(resource_operation_tags=("read-files",))  # type: ignore[arg-type]


def test_fixture_resolves_profiles_independently_and_rejects_unknown_profile(
    tmp_path,
) -> None:
    fixture = tmp_path / "summary-evaluation.json"
    fixture.write_text(
        json.dumps(
            {
                "cases": [
                    {
                        "name": "research",
                        "profile_id": "research.checkpoint",
                        "summary": "## Goal\nResearch.\n\n## Findings\nDone.",
                    },
                    {
                        "name": "slides",
                        "profile_id": "ppt.revision",
                        "summary": "## Goal\nRevise slides.\n\n## Changes\nDone.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    result = evaluate_summary_fixture(
        fixture,
        profiles={
            "research.checkpoint": _profile(),
            "ppt.revision": _profile("ppt.revision", section="Changes"),
        },
    )

    assert result.ok is True
    assert tuple(item.profile_id for item in result.results) == (
        "research.checkpoint",
        "ppt.revision",
    )

    with pytest.raises(ValueError, match="unknown profile"):
        evaluate_summary_fixture(fixture, profiles={})
