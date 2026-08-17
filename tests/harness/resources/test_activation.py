from __future__ import annotations

from pathlib import Path

from loushang.harness.resources.activation import (
    ResourceActivation,
    apply_disabled_skills,
)
from loushang.harness.resources.types import (
    PromptFragmentDescriptor,
    ResourceBundle,
    SkillDescriptor,
)


def _bundle(tmp_path: Path) -> ResourceBundle:
    project_context = PromptFragmentDescriptor(
        name="AGENTS",
        source_path=tmp_path / "AGENTS.md",
        text="Follow the project rules.",
        prompt_kind="agents_md",
    )
    prompt = PromptFragmentDescriptor(
        name="review",
        id="prompt.review",
        source_path=tmp_path / "prompts" / "review.md",
        text="Review this change.",
    )
    duplicate_prompt = PromptFragmentDescriptor(
        name="review-copy",
        source_path=prompt.source_path,
        text=prompt.text,
    )
    return ResourceBundle(
        cwd=tmp_path,
        prompt_descriptors=[project_context, prompt, duplicate_prompt],
        prompts=[prompt],
        skills=[
            SkillDescriptor(
                name="testing",
                id="skill.testing",
                source_path=tmp_path / "skills" / "testing" / "SKILL.md",
                description="Run focused tests.",
            ),
            SkillDescriptor(
                name="hidden",
                source_path=tmp_path / "skills" / "hidden" / "SKILL.md",
                description="Do not announce this skill.",
                disable_model_invocation=True,
            ),
        ],
    )


def test_resource_activation_projects_active_context_prompts_skills_and_fragments(
    tmp_path: Path,
) -> None:
    activation = ResourceActivation(_bundle(tmp_path))

    assert [item.name for item in activation.context_prompts()] == ["AGENTS"]
    assert activation.prompt_fragments() == ("Review this change.",)
    assert [item.name for item in activation.active_skills()] == ["testing", "hidden"]
    assert [item.name for item in activation.model_visible_skills()] == ["testing"]
    assert activation.find_prompt("prompt.review") is not None
    assert activation.find_skill("skill.testing") is not None


def test_disabled_skills_match_stable_resource_id_or_source_path(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    disabled = apply_disabled_skills(
        bundle,
        ["skill.testing", (tmp_path / "skills" / "hidden" / "SKILL.md").as_posix()],
    )

    assert [skill.enabled for skill in disabled.skills] == [False, False]
    assert [skill.enabled for skill in bundle.skills] == [True, True]
    assert ResourceActivation(disabled).find_skill("testing") is None
