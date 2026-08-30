from __future__ import annotations

from pathlib import Path

from loushang.harness.commands import list_resource_command_descriptors
from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    ResourceBundle,
    SkillDescriptor,
)


def test_resource_command_descriptors_project_enabled_prompts_and_skills() -> None:
    bundle = ResourceBundle(
        cwd=Path("/tmp/project"),
        prompts=[
            PromptFragmentDescriptor(
                name="review",
                source_path=Path("/tmp/project/prompts/review.md"),
                text="---\ndescription: ignored\n---\nReview the diff",
                argument_hint="<target>",
            ),
            PromptFragmentDescriptor(
                name="plan",
                source_path=Path("/tmp/project/prompts/plan.md"),
                text="Plan work",
                description="Plan a change",
            ),
        ],
        skills=[
            SkillDescriptor(
                name="verify",
                source_path=Path("/tmp/project/skills/verify/SKILL.md"),
                content="---\nname: verify\n---\nRun checks",
            ),
            SkillDescriptor(
                name="disabled",
                source_path=Path("/tmp/project/skills/disabled/SKILL.md"),
                content="Not visible",
                enabled=False,
            ),
        ],
    )

    commands = list_resource_command_descriptors(
        bundle,
        allow_legacy_skill_body=True,
    )

    assert [
        (command.name, command.description, command.source) for command in commands
    ] == [
        ("review", "Review the diff", "prompt"),
        ("plan", "Plan a change", "prompt"),
        ("skill:verify", "Run checks", "skill"),
    ]
    assert commands[0].argument_hint == "<target>"
    assert commands[2].source_info.path.endswith("skills/verify/SKILL.md")


def test_resource_command_descriptors_accept_absent_resources() -> None:
    assert list_resource_command_descriptors(None) == []


def test_effective_skill_summary_never_uses_descriptor_body_as_description() -> None:
    skill = SkillDescriptor(
        name="review",
        source_path=Path("/catalog/skills/review/SKILL.md"),
        content="FORGED EAGER BODY",
        description=None,
    )

    for allow_legacy_skill_body in (False, True):
        commands = list_resource_command_descriptors(
            None,
            effective_skills=(skill,),
            allow_legacy_skill_body=allow_legacy_skill_body,
        )

        assert [(command.name, command.description) for command in commands] == [
            ("skill:review", None)
        ]
