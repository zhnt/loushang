from __future__ import annotations

from pathlib import Path

from loushang.harness.resources._loader_descriptor_parsing import (
    _prompt_descriptor_from_text,
    _skill_descriptor_from_text,
)


def test_prompt_descriptor_parsing_owns_frontmatter_projection() -> None:
    source_path = Path("resources/prompts/review.md")

    descriptor, diagnostics = _prompt_descriptor_from_text(
        name="review",
        source_path=source_path,
        text=(
            "---\n"
            "description: Review pull requests\n"
            'argument-hint: "<PR-URL>"\n'
            "---\n\n"
            "Review $1 and summarize risks."
        ),
        canonical_name="review.md",
        source_kind="built_in",
        source_scope="builtin",
        source="package_resource",
        source_root=Path("resources/prompts"),
    )

    assert diagnostics == []
    assert descriptor is not None
    assert descriptor.description == "Review pull requests"
    assert descriptor.argument_hint == "<PR-URL>"
    assert descriptor.metadata["body"] == "Review $1 and summarize risks."
    assert descriptor.source_kind == "built_in"


def test_skill_descriptor_parsing_owns_validation_and_projection() -> None:
    source_path = Path("resources/skills/Debugging/SKILL.md")

    descriptor, diagnostics = _skill_descriptor_from_text(
        parent_name="Debugging",
        source_path=source_path,
        content="---\nname: Bad_Name\n---\n\nTrace the narrowest failure.",
        canonical_name="Debugging/SKILL.md",
        source_kind="project_local",
        source_scope="project",
        source="filesystem",
        source_root=Path("resources/skills"),
    )

    assert descriptor is not None
    assert descriptor.name == "Bad_Name"
    assert descriptor.metadata["body"] == "Trace the narrowest failure."
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "invalid_skill_description",
        "invalid_skill_name",
        "invalid_skill_name",
    ]
    assert {
        diagnostic.details["metadata"]["field"] for diagnostic in diagnostics
    } == {"description", "name"}


def test_descriptor_parsing_rejects_invalid_frontmatter_without_io() -> None:
    descriptor, diagnostics = _skill_descriptor_from_text(
        parent_name="broken",
        source_path=Path("resources/skills/broken/SKILL.md"),
        content="---\ndescription: [broken\n---\n\nBroken body.",
        canonical_name="broken/SKILL.md",
        source_kind="external_package",
        source_scope="package",
        source="package_resource",
        source_root=Path("resources/skills"),
    )

    assert descriptor is None
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "invalid_skill_frontmatter"
    ]
    assert diagnostics[0].details["source_kind"] == "external_package"
