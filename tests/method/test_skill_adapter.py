from __future__ import annotations

from pathlib import Path

from loushang.harness.resources.types import SkillDescriptor
from loushang.method import method_from_skill


def test_method_from_skill_preserves_content_and_frontmatter_hints() -> None:
    skill = SkillDescriptor(
        name="code-review",
        source_path=Path("skills/code-review/SKILL.md"),
        content="Review code changes.",
        description="Review code",
        metadata={
            "frontmatter": {
                "type": "task",
                "domain": "coding",
                "domains": ["coding", "research"],
                "task_types": ["reviewing", "verifying"],
                "contexts": ["oss-library"],
                "artifact_types": ["code", "test-report"],
                "modalities": ["text", "code"],
                "toolchains": ["python", "pytest"],
                "lifecycle": ["maintenance"],
                "capabilities": ["diff-review"],
                "complexity": "standard",
                "risk": "medium",
                "tags": {
                    "method_family": ["review-first"],
                    "domain_app": "coding",
                },
                "meta_role": "VALIDATOR",
                "phase": "VERIFY",
                "temperature": 0.2,
                "version": "1",
            },
            "body": "Review code changes.",
        },
    )

    method = method_from_skill(skill)

    assert method.id == "skill:code-review"
    assert method.name == "code-review"
    assert method.description == "Review code"
    assert method.content == "Review code changes."
    assert method.kind == "skill_backed"
    assert method.element_type == "task"
    assert method.domain == "coding"
    assert method.applicability.domains == ("coding", "research")
    assert method.applicability.task_types == ("reviewing", "verifying")
    assert method.applicability.contexts == ("oss-library",)
    assert method.applicability.artifact_types == ("code", "test-report")
    assert method.applicability.modalities == ("text", "code")
    assert method.applicability.toolchains == ("python", "pytest")
    assert method.applicability.lifecycle == ("maintenance",)
    assert method.applicability.capabilities == ("diff-review",)
    assert method.applicability.complexity == "standard"
    assert method.applicability.risk == "medium"
    assert method.applicability.tags == {
        "method_family": ("review-first",),
        "domain_app": ("coding",),
    }
    assert method.meta_role == "VALIDATOR"
    assert method.phase == "VERIFY"
    assert method.version == "1"
    assert method.source_path == "skills/code-review/SKILL.md"
    assert method.metadata["frontmatter"] == skill.metadata["frontmatter"]
    assert method.metadata["body"] == "Review code changes."
    assert method.metadata["source_kind"] == "project_local"


def test_method_from_skill_avoids_double_skill_prefix() -> None:
    skill = SkillDescriptor(
        name="skill:existing",
        source_path=Path("skills/existing/SKILL.md"),
        content="Existing content.",
    )

    method = method_from_skill(skill)

    assert method.id == "skill:existing"
    assert method.name == "skill:existing"


def test_method_from_skill_accepts_missing_optional_skill_fields() -> None:
    skill = SkillDescriptor(
        name="minimal",
        source_path=Path("skills/minimal/SKILL.md"),
        content=None,
        description=None,
        metadata={"frontmatter": {"role": "DESIGNER"}},
    )

    method = method_from_skill(skill)

    assert method.id == "skill:minimal"
    assert method.description == ""
    assert method.content == ""
    assert method.meta_role == "DESIGNER"
    assert method.element_type is None
    assert method.applicability.domains == ()


def test_method_from_skill_maps_legacy_domain_into_applicability_domains() -> None:
    skill = SkillDescriptor(
        name="legacy-domain",
        source_path=Path("skills/legacy-domain/SKILL.md"),
        content="Legacy domain content.",
        metadata={"frontmatter": {"domain": "coding"}},
    )

    method = method_from_skill(skill)

    assert method.domain == "coding"
    assert method.applicability.domains == ("coding",)
