from __future__ import annotations

from loushang.method import MethodLoader


def test_method_loader_discovers_skill_backed_methods_without_mutating_cache(tmp_path) -> None:
    project = tmp_path / "project"
    skill_dir = project / "skills" / "review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: review\n"
        "description: Review code.\n"
        "type: task\n"
        "domain: coding\n"
        "---\n\n"
        "Review code changes.",
        encoding="utf-8",
    )
    loader = MethodLoader(skill_authority="legacy_explicit")

    methods = loader.discover_methods(project)

    assert loader.list_methods() == []
    assert [method.id for method in methods] == ["skill:review"]
    method = methods[0]
    assert method.kind == "skill_backed"
    assert method.element_type == "task"
    assert method.domain == "coding"


def test_method_loader_reload_replaces_cached_snapshot(tmp_path) -> None:
    project = tmp_path / "project"
    skill_dir = project / "skills" / "debug"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("Debug failures.", encoding="utf-8")
    loader = MethodLoader(skill_authority="legacy_explicit")

    loaded = loader.reload_methods(project)

    assert loader.list_methods() == loaded
    assert loader.get_method("skill:debug") == loaded[0]
    assert loader.get_method("debug") == loaded[0]

    second_project = tmp_path / "second"
    second_skill_dir = second_project / "skills" / "review"
    second_skill_dir.mkdir(parents=True)
    (second_skill_dir / "SKILL.md").write_text("Review code.", encoding="utf-8")

    reloaded = loader.reload_methods(second_project)

    assert [method.name for method in reloaded] == ["review"]
    assert loader.get_method("debug") is None


def test_method_loader_discovers_method_resources_and_ignores_future_manifests(tmp_path) -> None:
    project = tmp_path / "project"
    method_dir = project / "methods" / "task" / "review"
    method_dir.mkdir(parents=True)
    (method_dir / "SKILL.md").write_text(
        "---\n"
        "name: review\n"
        "description: Method review.\n"
        "type: task\n"
        "domain: coding\n"
        "domains:\n"
        "  - coding\n"
        "  - research\n"
        "task_types:\n"
        "  - reviewing\n"
        "contexts:\n"
        "  - oss-library\n"
        "artifact_types:\n"
        "  - code\n"
        "modalities:\n"
        "  - text\n"
        "toolchains:\n"
        "  - python\n"
        "lifecycle:\n"
        "  - maintenance\n"
        "capabilities:\n"
        "  - diff-review\n"
        "complexity: standard\n"
        "risk: medium\n"
        "tags:\n"
        "  method_family:\n"
        "    - review-first\n"
        "meta_role: VALIDATOR\n"
        "phase: VERIFY\n"
        "version: 1\n"
        "---\n\n"
        "Use method review guidance.",
        encoding="utf-8",
    )
    (project / "methods" / "METHOD.md").write_text("Future manifest.", encoding="utf-8")
    (project / "methods" / "SOUR.md").write_text("Future source role.", encoding="utf-8")

    methods = MethodLoader().discover_methods(project)

    assert [method.id for method in methods] == ["method:task:review"]
    method = methods[0]
    assert method.name == "review"
    assert method.kind == "method_resource"
    assert method.element_type == "task"
    assert method.domain == "coding"
    assert method.applicability.domains == ("coding", "research")
    assert method.applicability.task_types == ("reviewing",)
    assert method.applicability.contexts == ("oss-library",)
    assert method.applicability.artifact_types == ("code",)
    assert method.applicability.modalities == ("text",)
    assert method.applicability.toolchains == ("python",)
    assert method.applicability.lifecycle == ("maintenance",)
    assert method.applicability.capabilities == ("diff-review",)
    assert method.applicability.complexity == "standard"
    assert method.applicability.risk == "medium"
    assert method.applicability.tags == {"method_family": ("review-first",)}
    assert method.meta_role == "VALIDATOR"
    assert method.phase == "VERIFY"
    assert method.version == "1"
    assert method.metadata["body"] == "Use method review guidance."


def test_method_loader_default_does_not_create_a_peer_skill_authority(
    tmp_path,
) -> None:
    project = tmp_path / "project"
    skill_dir = project / "skills" / "review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("Legacy Skill body.", encoding="utf-8")

    assert MethodLoader().discover_methods(project) == []


def test_method_loader_method_resource_overrides_skill_with_same_name(tmp_path) -> None:
    project = tmp_path / "project"
    skill_dir = project / "skills" / "review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("Skill review.", encoding="utf-8")
    method_dir = project / "methods" / "task" / "review"
    method_dir.mkdir(parents=True)
    (method_dir / "SKILL.md").write_text(
        "---\nname: review\n---\n\nMethod review.",
        encoding="utf-8",
    )

    methods = MethodLoader(
        skill_authority="legacy_explicit"
    ).discover_methods(project)

    assert [method.id for method in methods] == ["method:task:review"]
    assert methods[0].kind == "method_resource"
    assert methods[0].content == "---\nname: review\n---\n\nMethod review."
