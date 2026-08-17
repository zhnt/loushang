from __future__ import annotations

from datetime import date
from pathlib import Path


def _runtime_footer(cwd: Path) -> str:
    return f"Current date: {date.today().isoformat()}\nCurrent working directory: {cwd.as_posix()}"


def test_loader_exports_snapshot_and_theme_symbols() -> None:
    from loushang.harness.resources.types import (
        ResourceSnapshot,
        ThemeDescriptor,
    )

    assert ResourceSnapshot is not None
    assert ThemeDescriptor is not None


def test_resource_snapshot_to_bundle_preserves_agents_and_active_prompt_order() -> None:
    from loushang.harness.resources.types import (
        PromptFragmentDescriptor,
        ResourceSnapshot,
    )

    agents = PromptFragmentDescriptor(
        name="AGENTS.md",
        source_path=Path("/tmp/project/AGENTS.md"),
        text="Project guidance",
        id="project.agents",
        canonical_name="AGENTS.md",
        prompt_kind="agents_md",
    )
    built_in_prompt = PromptFragmentDescriptor(
        name="base",
        source_path=Path("/tmp/package/prompts/base.md"),
        text="Built-in prompt",
        id="base.md",
        canonical_name="base.md",
        source_kind="built_in",
        source_scope="builtin",
        source="package_resource",
    )
    project_prompt = PromptFragmentDescriptor(
        name="repo",
        source_path=Path("/tmp/project/prompts/repo.md"),
        text="Project prompt",
        id="repo.md",
        canonical_name="repo.md",
    )
    snapshot = ResourceSnapshot(
        cwd=Path("/tmp/project"),
        source_kinds=("built_in", "project_local"),
        active_agents_descriptor=agents,
        candidate_agents_descriptors=(agents,),
        active_prompt_descriptors=(built_in_prompt, project_prompt),
        candidate_prompt_descriptors=(built_in_prompt, project_prompt),
    )

    bundle = snapshot.to_bundle()

    assert bundle.agents_path == Path("/tmp/project/AGENTS.md")
    assert bundle.agents_md == "Project guidance"
    assert bundle.prompt_fragments == [
        "Project guidance",
        "Project prompt",
        "Built-in prompt",
    ]
    assert bundle.prompt_descriptors == [agents, project_prompt, built_in_prompt]
    assert bundle.prompts == [project_prompt, built_in_prompt]


def test_default_resource_loader_discovers_agents_md_from_parent_dirs(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    project_root = tmp_path / "project"
    nested = project_root / "src" / "feature"
    nested.mkdir(parents=True)
    agents_file = project_root / "AGENTS.md"
    agents_file.write_text("Project guidance", encoding="utf-8")

    loader = DefaultResourceLoader()
    bundle = loader.discover_resources(nested)

    assert bundle.cwd == nested
    assert bundle.agents_path == agents_file
    assert bundle.agents_md == "Project guidance"
    assert bundle.prompt_fragments == ["Project guidance"]
    assert len(bundle.prompt_descriptors) == 1
    assert bundle.prompt_descriptors[0].id == "project.agents"
    assert bundle.prompt_descriptors[0].prompt_kind == "agents_md"
    snapshot = loader.get_resource_snapshot()
    assert snapshot.active_agents_descriptor is not None
    assert snapshot.active_agents_descriptor.source_path == agents_file
    assert snapshot.source_kinds == ("built_in", "project_local")


def test_default_resource_loader_stacks_global_and_ancestor_context_files(
    tmp_path,
) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    user_root = tmp_path / "user"
    workspace_root = tmp_path / "workspace"
    project_root = workspace_root / "project"
    nested = project_root / "src" / "feature"
    user_root.mkdir()
    nested.mkdir(parents=True)
    global_agents = user_root / "AGENTS.md"
    workspace_agents = workspace_root / "AGENTS.md"
    project_claude = project_root / "CLAUDE.md"
    global_agents.write_text("Global guidance", encoding="utf-8")
    workspace_agents.write_text("Workspace guidance", encoding="utf-8")
    project_claude.write_text("Project Claude guidance", encoding="utf-8")

    loader = DefaultResourceLoader(user_resource_roots=[user_root])
    bundle = loader.discover_resources(nested)

    assert bundle.prompt_fragments == [
        "Global guidance",
        "Workspace guidance",
        "Project Claude guidance",
    ]
    assert [descriptor.source_path for descriptor in bundle.prompt_descriptors] == [
        global_agents,
        workspace_agents,
        project_claude,
    ]
    assert [descriptor.source_kind for descriptor in bundle.prompt_descriptors] == [
        "user_global",
        "project_local",
        "project_local",
    ]
    assert [descriptor.prompt_kind for descriptor in bundle.prompt_descriptors] == [
        "agents_md",
        "agents_md",
        "claude_md",
    ]
    assert loader.get_agents_files() == {
        "agents_files": [
            {"path": str(global_agents), "content": "Global guidance"},
            {"path": str(workspace_agents), "content": "Workspace guidance"},
            {"path": str(project_claude), "content": "Project Claude guidance"},
        ]
    }
    assert bundle.agents_path == project_claude
    assert bundle.agents_md == "Project Claude guidance"


def test_default_resource_loader_can_disable_context_files(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    project_root = tmp_path / "project"
    nested = project_root / "src" / "feature"
    nested.mkdir(parents=True)
    (project_root / "AGENTS.md").write_text("Project guidance", encoding="utf-8")

    loader = DefaultResourceLoader(no_context_files=True)
    bundle = loader.discover_resources(nested)

    assert bundle.agents_path is None
    assert bundle.agents_md is None
    assert bundle.prompt_fragments == []
    assert bundle.prompt_descriptors == []


def test_default_resource_loader_exposes_user_global_skill_candidates_and_project_precedence(
    tmp_path,
) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    user_root = tmp_path / "user"
    project_root = tmp_path / "project"
    user_skill = user_root / "skills" / "review"
    project_skill = project_root / "skills" / "review"
    user_skill.mkdir(parents=True)
    project_skill.mkdir(parents=True)
    (user_skill / "SKILL.md").write_text("Global review rules", encoding="utf-8")
    (project_skill / "SKILL.md").write_text("Project review rules", encoding="utf-8")

    loader = DefaultResourceLoader(user_resource_roots=[user_root])
    bundle = loader.discover_resources(project_root)
    snapshot = loader.get_resource_snapshot()

    assert [skill.content for skill in bundle.skills] == ["Project review rules"]
    assert [skill.source_kind for skill in bundle.skills] == ["project_local"]
    assert [skill.source_scope for skill in bundle.skills] == ["project"]
    assert [skill.source_root for skill in bundle.skills] == [project_root / "skills"]
    assert [
        (skill.name, skill.source_kind, skill.source_root)
        for skill in snapshot.candidate_skill_descriptors
    ] == [
        ("review", "user_global", user_root / "skills"),
        ("review", "project_local", project_root / "skills"),
    ]
    assert any(
        decision.logical_id == "review/SKILL.md"
        and decision.winner_source_kind == "project_local"
        and decision.candidate_source_kinds == ("project_local", "user_global")
        for decision in snapshot.merge_decisions
    )


def test_default_resource_loader_loads_explicit_resource_paths_when_defaults_disabled(
    tmp_path,
) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    project_root = tmp_path / "project"
    project_root.mkdir()
    (project_root / "skills" / "project").mkdir(parents=True)
    (project_root / "skills" / "project" / "SKILL.md").write_text(
        "Project skill", encoding="utf-8"
    )
    (project_root / "prompts").mkdir()
    (project_root / "prompts" / "project.md").write_text(
        "Project prompt", encoding="utf-8"
    )
    (project_root / "extensions").mkdir()
    (project_root / "extensions" / "project.py").write_text(
        "def register(api): pass\n", encoding="utf-8"
    )
    (project_root / "themes").mkdir()
    (project_root / "themes" / "project.json").write_text("{}", encoding="utf-8")

    explicit_skill = tmp_path / "explicit-skill"
    explicit_skill.mkdir()
    (explicit_skill / "SKILL.md").write_text(
        "---\nname: explicit\n---\n\nExplicit skill",
        encoding="utf-8",
    )
    explicit_prompt = tmp_path / "explicit.md"
    explicit_prompt.write_text("Explicit prompt", encoding="utf-8")
    explicit_extension = tmp_path / "explicit_ext.py"
    explicit_extension.write_text("def register(api): pass\n", encoding="utf-8")
    explicit_theme = tmp_path / "explicit.json"
    explicit_theme.write_text("{}", encoding="utf-8")

    loader = DefaultResourceLoader(
        additional_skill_paths=[explicit_skill],
        additional_prompt_template_paths=[explicit_prompt],
        additional_extension_paths=[explicit_extension],
        additional_theme_paths=[explicit_theme],
        no_skills=True,
        no_prompt_templates=True,
        no_extensions=True,
        no_themes=True,
    )
    bundle = loader.discover_resources(project_root)
    snapshot = loader.get_resource_snapshot()

    assert [skill.name for skill in bundle.skills] == ["explicit"]
    assert [prompt.name for prompt in bundle.prompts] == ["explicit"]
    assert [extension.name for extension in bundle.extensions] == ["explicit_ext"]
    assert [theme.name for theme in bundle.themes] == ["explicit"]
    assert [skill.source_kind for skill in bundle.skills] == ["temporary"]
    assert [prompt.source_kind for prompt in bundle.prompts] == ["temporary"]
    assert [extension.source_kind for extension in bundle.extensions] == ["temporary"]
    assert [theme.source_kind for theme in bundle.themes] == ["temporary"]
    assert "project" not in [
        skill.name for skill in snapshot.candidate_skill_descriptors
    ]
    assert "project" not in [
        prompt.name for prompt in snapshot.candidate_prompt_descriptors
    ]
    assert "project" not in [
        extension.name for extension in snapshot.candidate_extension_descriptors
    ]
    assert "project" not in [
        theme.name for theme in snapshot.candidate_theme_descriptors
    ]


def test_default_resource_loader_resolves_system_prompt_sources_as_text_or_files(
    tmp_path,
) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    append_file = tmp_path / "append.txt"
    append_file.write_text("Append from file", encoding="utf-8")

    loader = DefaultResourceLoader(
        system_prompt="Inline system",
        append_system_prompt=[str(append_file), "Inline append"],
    )
    loader.discover_resources(tmp_path)

    assert loader.get_system_prompt_override() == "Inline system"
    assert loader.get_append_system_prompt_overrides() == [
        "Append from file",
        "Inline append",
    ]


def test_default_resource_loader_discovers_extension_descriptors_and_reports_invalid_entries(
    tmp_path,
) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    project_root = tmp_path / "project"
    nested = project_root / "src" / "feature"
    extensions_dir = project_root / "extensions"
    nested.mkdir(parents=True)
    (extensions_dir / "sample_ext").mkdir(parents=True)
    (extensions_dir / "sample_ext" / "extension.py").write_text(
        "EXTENSION = object()\n", encoding="utf-8"
    )
    (extensions_dir / "file_ext.py").write_text(
        "EXTENSION = object()\n", encoding="utf-8"
    )
    (extensions_dir / "broken_ext").mkdir(parents=True)
    (extensions_dir / "README.txt").write_text(
        "not a directory entry", encoding="utf-8"
    )
    (project_root / "AGENTS.md").write_text("Project guidance", encoding="utf-8")

    loader = DefaultResourceLoader()
    bundle = loader.discover_resources(nested)

    assert [descriptor.name for descriptor in bundle.extensions] == [
        "file_ext",
        "sample_ext",
    ]
    assert [descriptor.id for descriptor in bundle.extensions] == [
        "file_ext.py",
        "sample_ext",
    ]
    assert [diagnostic.code for diagnostic in bundle.diagnostics] == [
        "missing_extension_entry",
        "unsupported_extension_entry",
    ]
    assert bundle.diagnostics[0].source_path == extensions_dir / "broken_ext"
    assert bundle.diagnostics[1].source_path == extensions_dir / "README.txt"
    snapshot = loader.get_resource_snapshot()
    assert [
        descriptor.name for descriptor in snapshot.candidate_extension_descriptors
    ] == ["sample_ext", "file_ext"]
    assert [
        descriptor.name for descriptor in snapshot.active_extension_descriptors
    ] == ["file_ext", "sample_ext"]


def test_default_resource_loader_discovers_prompt_and_skill_descriptors_into_snapshot_and_bundle(
    tmp_path,
) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    project_root = tmp_path / "project"
    nested = project_root / "src" / "feature"
    prompts_dir = project_root / "prompts"
    skills_dir = project_root / "skills"
    nested.mkdir(parents=True)
    prompts_dir.mkdir(parents=True)
    (skills_dir / "review").mkdir(parents=True)
    (project_root / "AGENTS.md").write_text("Project guidance", encoding="utf-8")
    (prompts_dir / "repo.md").write_text("Prompt rules", encoding="utf-8")
    (skills_dir / "review" / "SKILL.md").write_text("Review rules", encoding="utf-8")

    loader = DefaultResourceLoader()
    bundle = loader.discover_resources(nested)
    snapshot = loader.get_resource_snapshot()

    assert bundle.prompt_fragments == ["Project guidance", "Prompt rules"]
    assert [descriptor.name for descriptor in bundle.prompts] == ["repo"]
    assert [descriptor.id for descriptor in bundle.prompts] == ["repo.md"]
    assert [descriptor.source_kind for descriptor in bundle.prompts] == [
        "project_local"
    ]
    assert [descriptor.name for descriptor in bundle.skills] == ["review"]
    assert [descriptor.id for descriptor in bundle.skills] == ["review/SKILL.md"]
    prompts = loader.get_prompts()
    assert prompts["prompts"] == bundle.prompts
    assert loader.get_agents_files() == {
        "agents_files": [
            {"path": str(project_root / "AGENTS.md"), "content": "Project guidance"}
        ]
    }
    assert loader.get_append_system_prompt() == ["Project guidance", "Prompt rules"]
    assert loader.get_system_prompt(base_prompt="Base") == (
        "Base\n\n"
        "# Project Context\n\n"
        "Project-specific instructions and guidelines:\n\n"
        f"## {project_root / 'AGENTS.md'}\n\n"
        "Project guidance\n\n"
        "Prompt rules\n\n"
        f"{_runtime_footer(nested)}"
    )
    assert loader.get_skills() == bundle.skills
    assert snapshot.active_agents_descriptor is not None
    assert [descriptor.id for descriptor in snapshot.active_prompt_descriptors] == [
        "repo.md"
    ]
    assert [descriptor.id for descriptor in snapshot.active_skill_descriptors] == [
        "review/SKILL.md"
    ]


def test_default_resource_loader_parses_skill_frontmatter_metadata(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    project_root = tmp_path / "project"
    skill_dir = project_root / "skills" / "debugging"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: debugging\n"
        "description: Debug failures by tracing the narrowest failing path.\n"
        "disable-model-invocation: true\n"
        "---\n\n"
        "Check the failing path first.",
        encoding="utf-8",
    )

    loader = DefaultResourceLoader()
    bundle = loader.discover_resources(project_root)

    assert len(bundle.skills) == 1
    skill = bundle.skills[0]
    assert skill.name == "debugging"
    assert skill.description == "Debug failures by tracing the narrowest failing path."
    assert skill.disable_model_invocation is True
    assert skill.metadata["frontmatter"]["name"] == "debugging"
    assert skill.metadata["body"] == "Check the failing path first."


def test_default_resource_loader_parses_prompt_argument_hint_frontmatter(
    tmp_path,
) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    project_root = tmp_path / "project"
    prompts_dir = project_root / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "review.md").write_text(
        "---\n"
        "description: Review pull requests\n"
        'argument-hint: "<PR-URL>"\n'
        "---\n\n"
        "Review $1 and summarize risks.",
        encoding="utf-8",
    )

    loader = DefaultResourceLoader()
    bundle = loader.discover_resources(project_root)

    assert len(bundle.prompts) == 1
    prompt = bundle.prompts[0]
    assert prompt.argument_hint == "<PR-URL>"
    assert prompt.metadata["frontmatter"]["description"] == "Review pull requests"
    assert prompt.metadata["body"] == "Review $1 and summarize risks."


def test_default_resource_loader_reports_invalid_prompt_frontmatter(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    project_root = tmp_path / "project"
    prompts_dir = project_root / "prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "broken.md").write_text(
        "---\ndescription: [broken\n---\n\nReview $1.",
        encoding="utf-8",
    )

    loader = DefaultResourceLoader()
    bundle = loader.discover_resources(project_root)

    assert bundle.prompts == []
    assert [diagnostic.code for diagnostic in bundle.diagnostics] == [
        "invalid_prompt_frontmatter"
    ]
    diagnostic = bundle.diagnostics[0]
    assert diagnostic.details["resource_type"] == "prompt"
    assert diagnostic.source_path == prompts_dir / "broken.md"
    assert "line 1" in diagnostic.message


def test_default_resource_loader_reports_invalid_skill_frontmatter_without_loading_skill(
    tmp_path,
) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    project_root = tmp_path / "project"
    skill_dir = project_root / "skills" / "broken"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\ndescription: [broken\n---\n\nBroken skill body.",
        encoding="utf-8",
    )

    loader = DefaultResourceLoader()
    bundle = loader.discover_resources(project_root)
    snapshot = loader.get_resource_snapshot()

    assert bundle.skills == []
    assert snapshot.candidate_skill_descriptors == ()
    assert [diagnostic.code for diagnostic in bundle.diagnostics] == [
        "invalid_skill_frontmatter"
    ]
    diagnostic = bundle.diagnostics[0]
    assert diagnostic.details["resource_type"] == "skill"
    assert diagnostic.details["source_kind"] == "project_local"
    assert diagnostic.source_path == skill_dir / "SKILL.md"
    assert "line 1" in diagnostic.message


def test_default_resource_loader_reports_skill_frontmatter_validation_diagnostics(
    tmp_path,
) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    project_root = tmp_path / "project"
    skill_dir = project_root / "skills" / "Debugging"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: Bad_Name\n---\n\nCheck the failing path first.",
        encoding="utf-8",
    )

    loader = DefaultResourceLoader()
    bundle = loader.discover_resources(project_root)

    assert [diagnostic.code for diagnostic in bundle.diagnostics] == [
        "invalid_skill_description",
        "invalid_skill_name",
        "invalid_skill_name",
    ]
    assert [
        diagnostic.details["resource_type"] for diagnostic in bundle.diagnostics
    ] == [
        "skill",
        "skill",
        "skill",
    ]
    assert {
        diagnostic.details["metadata"]["field"] for diagnostic in bundle.diagnostics
    } == {"description", "name"}


def test_default_resource_loader_recursively_discovers_skills_and_skips_ignored_directories(
    tmp_path,
) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    project_root = tmp_path / "project"
    nested_skill = project_root / "skills" / "workflows" / "debugging"
    nested_skill.mkdir(parents=True)
    (nested_skill / "SKILL.md").write_text(
        "---\n"
        "name: debugging\n"
        "description: Debug failures.\n"
        "---\n\n"
        "Check the failing path first.",
        encoding="utf-8",
    )
    parent_skill = project_root / "skills" / "parent"
    child_skill = parent_skill / "child"
    child_skill.mkdir(parents=True)
    (parent_skill / "SKILL.md").write_text(
        "---\nname: parent\n"
        "description: Parent workflow.\n"
        "---\n\n"
        "Use parent instructions.",
        encoding="utf-8",
    )
    (child_skill / "SKILL.md").write_text(
        "---\nname: child\n"
        "description: Should not be loaded because parent is a skill root.\n"
        "---\n\n"
        "Ignored.",
        encoding="utf-8",
    )
    ignored_skill = project_root / "skills" / "node_modules" / "ignored"
    hidden_skill = project_root / "skills" / ".hidden" / "ignored"
    ignored_skill.mkdir(parents=True)
    hidden_skill.mkdir(parents=True)
    (ignored_skill / "SKILL.md").write_text(
        "---\nname: ignored\n---\n\nIgnored.", encoding="utf-8"
    )
    (hidden_skill / "SKILL.md").write_text(
        "---\nname: hidden\n---\n\nIgnored.", encoding="utf-8"
    )

    loader = DefaultResourceLoader()
    bundle = loader.discover_resources(project_root)

    assert [skill.name for skill in bundle.skills] == ["parent", "debugging"]
    assert [skill.canonical_name for skill in bundle.skills] == [
        "parent/SKILL.md",
        "workflows/debugging/SKILL.md",
    ]


def test_default_resource_loader_applies_skill_ignore_files(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    project_root = tmp_path / "project"
    skills_dir = project_root / "skills"
    included_skill = skills_dir / "included"
    ignored_skill = skills_dir / "ignored"
    nested_ignored_skill = skills_dir / "workflows" / "generated"
    included_skill.mkdir(parents=True)
    ignored_skill.mkdir(parents=True)
    nested_ignored_skill.mkdir(parents=True)
    (skills_dir / ".gitignore").write_text(
        "ignored/\nworkflows/generated/\n", encoding="utf-8"
    )
    (included_skill / "SKILL.md").write_text(
        "---\nname: included\n"
        "description: Included workflow.\n"
        "---\n\n"
        "Use included instructions.",
        encoding="utf-8",
    )
    (ignored_skill / "SKILL.md").write_text(
        "---\nname: ignored\ndescription: Ignored workflow.\n---\n\nIgnored.",
        encoding="utf-8",
    )
    (nested_ignored_skill / "SKILL.md").write_text(
        "---\nname: generated\ndescription: Generated workflow.\n---\n\nIgnored.",
        encoding="utf-8",
    )

    loader = DefaultResourceLoader()
    bundle = loader.discover_resources(project_root)

    assert [skill.name for skill in bundle.skills] == ["included"]
    assert bundle.diagnostics == []


def test_default_resource_loader_prefers_project_local_prompt_when_built_in_candidate_collides(
    tmp_path, monkeypatch
) -> None:
    import loushang.harness.resources._loader_discovery_builtin as discovery_module
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.harness.resources.types import PromptFragmentDescriptor

    project_root = tmp_path / "project"
    prompts_dir = project_root / "prompts"
    prompts_dir.mkdir(parents=True)
    (project_root / "AGENTS.md").write_text("Project guidance", encoding="utf-8")
    (prompts_dir / "repo.md").write_text("Project rules", encoding="utf-8")

    built_in_prompt = PromptFragmentDescriptor(
        name="repo",
        source_path=Path("/tmp/package/prompts/repo.md"),
        text="Built-in rules",
        id="repo.md",
        canonical_name="repo.md",
        source_kind="built_in",
        source_scope="builtin",
        source="package_resource",
    )

    monkeypatch.setattr(
        discovery_module,
        "_discover_built_in_prompts",
        lambda _package, *, source_root_order: ([built_in_prompt], []),
    )

    loader = DefaultResourceLoader()
    bundle = loader.discover_resources(project_root)
    snapshot = loader.get_resource_snapshot()

    assert bundle.prompt_fragments == ["Project guidance", "Project rules"]
    assert [descriptor.source_kind for descriptor in bundle.prompts] == [
        "project_local"
    ]
    assert [
        descriptor.source_kind for descriptor in snapshot.candidate_prompt_descriptors
    ] == [
        "built_in",
        "project_local",
    ]
    assert [diagnostic.code for diagnostic in snapshot.diagnostics] == [
        "resource_collision"
    ]
    metadata = snapshot.diagnostics[0].details["metadata"]
    assert metadata["winner_path"] == str(prompts_dir / "repo.md")
    assert metadata["candidate_paths"] == (
        str(prompts_dir / "repo.md"),
        "/tmp/package/prompts/repo.md",
    )
    assert metadata["loser_paths"] == ("/tmp/package/prompts/repo.md",)
    assert any(
        decision.logical_id == "repo.md"
        and decision.winner_id == "repo.md"
        and decision.reason == "source_precedence"
        for decision in snapshot.merge_decisions
    )


def test_default_resource_loader_discovers_external_package_resources_before_built_in(
    tmp_path,
) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    project_root = tmp_path / "project"
    package_root = tmp_path / "packages" / "review-pack"
    prompts_dir = package_root / "prompts"
    project_root.mkdir()
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "review.md").write_text("Package review rules", encoding="utf-8")

    loader = DefaultResourceLoader(package_roots=[package_root])
    bundle = loader.discover_resources(project_root)
    snapshot = loader.get_resource_snapshot()

    assert "external_package" in snapshot.source_kinds
    assert [descriptor.source_kind for descriptor in bundle.prompts] == [
        "external_package"
    ]
    assert bundle.prompt_fragments == ["Package review rules"]
    assert bundle.prompts[0].source_root_order == 0


def test_default_resource_loader_reports_missing_invalid_and_empty_package_roots(
    tmp_path,
) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    project_root = tmp_path / "project"
    missing_root = tmp_path / "packages" / "missing-pack"
    file_root = tmp_path / "packages" / "file-pack"
    empty_root = tmp_path / "packages" / "empty-pack"
    project_root.mkdir()
    file_root.parent.mkdir(parents=True)
    file_root.write_text("not a package directory", encoding="utf-8")
    empty_root.mkdir()

    loader = DefaultResourceLoader(package_roots=[missing_root, file_root, empty_root])
    loader.discover_resources(project_root)

    diagnostics = loader.get_resource_diagnostics(
        source_kind="external_package", resource_type="package"
    )
    assert [diagnostic.code for diagnostic in diagnostics] == [
        "missing_package_root",
        "invalid_package_root",
        "empty_package_root",
    ]
    assert [diagnostic.source_path for diagnostic in diagnostics] == [
        missing_root.resolve(),
        file_root.resolve(),
        empty_root.resolve(),
    ]
    assert diagnostics[0].details["metadata"]["package_root"] == str(
        missing_root.resolve()
    )


def test_default_resource_loader_exposes_package_resource_summaries_and_filtered_diagnostics(
    tmp_path,
) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.harness.resources.types import PackageResourceSummary

    project_root = tmp_path / "project"
    package_root = tmp_path / "packages" / "review-pack"
    prompts_dir = package_root / "prompts"
    skills_dir = package_root / "skills" / "review"
    extensions_dir = package_root / "extensions"
    themes_dir = package_root / "themes"
    project_root.mkdir()
    prompts_dir.mkdir(parents=True)
    skills_dir.mkdir(parents=True)
    extensions_dir.mkdir(parents=True)
    themes_dir.mkdir(parents=True)
    (prompts_dir / "review.md").write_text("Package review rules", encoding="utf-8")
    (skills_dir / "SKILL.md").write_text("Review skill", encoding="utf-8")
    (extensions_dir / "README.txt").write_text("unsupported", encoding="utf-8")
    (themes_dir / "clean.json").write_text("{}", encoding="utf-8")

    loader = DefaultResourceLoader(package_roots=[package_root])
    loader.discover_resources(project_root)

    summaries = loader.get_package_resource_summaries()
    assert summaries == [
        PackageResourceSummary(
            source_root=package_root.resolve(),
            prompt_count=1,
            skill_count=1,
            extension_count=0,
            theme_count=1,
            diagnostic_count=1,
        )
    ]
    extension_diagnostics = loader.get_resource_diagnostics(
        source_kind="external_package",
        resource_type="extension",
        code="unsupported_extension_entry",
    )
    assert [diagnostic.source_path for diagnostic in extension_diagnostics] == [
        extensions_dir / "README.txt"
    ]


def test_default_resource_loader_reload_resources_refreshes_cached_bundle(
    tmp_path,
) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    project_root = tmp_path / "project"
    project_root.mkdir()
    agents_file = project_root / "AGENTS.md"
    agents_file.write_text("First version", encoding="utf-8")

    loader = DefaultResourceLoader()
    first = loader.discover_resources(project_root)
    first_snapshot = loader.get_resource_snapshot()
    agents_file.write_text("Updated version", encoding="utf-8")
    second = loader.reload_resources()
    second_snapshot = loader.get_resource_snapshot()

    assert first.agents_md == "First version"
    assert second.agents_md == "Updated version"
    assert second.prompt_descriptors[0].text == "Updated version"
    assert loader.get_resource_bundle() == second
    assert first_snapshot is not second_snapshot
    assert second_snapshot.active_agents_descriptor is not None
    assert second_snapshot.active_agents_descriptor.text == "Updated version"


def test_default_resource_loader_returns_empty_bundle_when_no_agents_md_exists(
    tmp_path,
) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    loader = DefaultResourceLoader()
    bundle = loader.discover_resources(tmp_path)

    assert bundle.cwd == tmp_path
    assert bundle.agents_path is None
    assert bundle.agents_md is None
    assert bundle.prompt_fragments == []
    assert bundle.prompt_descriptors == []
    assert bundle.diagnostics == []
    assert loader.get_skills() == []
    assert loader.get_extensions() == []
    assert loader.get_resource_snapshot().source_kinds == ("built_in", "project_local")


def test_prompt_same_precedence_collision_disables_only_that_prompt_identity(
    tmp_path, monkeypatch
) -> None:
    import loushang.harness.resources._loader_pipeline as pipeline_module
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.harness.resources._loader_types import _SourceDiscovery
    from loushang.harness.resources.types import PromptFragmentDescriptor

    root = tmp_path / "project"
    root.mkdir()
    (root / "AGENTS.md").write_text("repo guidance", encoding="utf-8")

    prompt_a = PromptFragmentDescriptor(
        name="repo",
        source_path=root / "prompts" / "a.md",
        text="A",
        id="repo.md",
        canonical_name="repo.md",
    )
    prompt_b = PromptFragmentDescriptor(
        name="repo",
        source_path=root / "prompts" / "b.md",
        text="B",
        id="repo.md",
        canonical_name="repo.md",
    )

    monkeypatch.setattr(
        pipeline_module,
        "_discover_built_in_resources",
        lambda _packages: _SourceDiscovery(),
    )
    monkeypatch.setattr(
        pipeline_module,
        "_discover_project_resources",
        lambda _root: _SourceDiscovery(prompts=[prompt_a, prompt_b]),
    )

    loader = DefaultResourceLoader()
    bundle = loader.discover_resources(root)
    snapshot = loader.get_resource_snapshot()

    assert bundle.prompt_fragments == ["repo guidance"]
    assert snapshot.active_prompt_descriptors == ()
    assert any(
        decision.logical_id == "repo.md" and decision.winner_id is None
        for decision in snapshot.merge_decisions
    )


def test_skill_same_precedence_collision_disables_only_that_skill_identity(
    tmp_path, monkeypatch
) -> None:
    import loushang.harness.resources._loader_pipeline as pipeline_module
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.harness.resources._loader_types import _SourceDiscovery
    from loushang.harness.resources.types import SkillDescriptor

    root = tmp_path / "project"
    root.mkdir()

    skill_a = SkillDescriptor(
        name="review",
        source_path=root / "skills" / "review" / "SKILL.md",
        content="A",
        id="review/SKILL.md",
        canonical_name="review/SKILL.md",
    )
    skill_b = SkillDescriptor(
        name="review",
        source_path=root / "skills" / "review-copy" / "SKILL.md",
        content="B",
        id="review/SKILL.md",
        canonical_name="review/SKILL.md",
    )

    monkeypatch.setattr(
        pipeline_module,
        "_discover_built_in_resources",
        lambda _packages: _SourceDiscovery(),
    )
    monkeypatch.setattr(
        pipeline_module,
        "_discover_project_resources",
        lambda _root: _SourceDiscovery(skills=[skill_a, skill_b]),
    )

    loader = DefaultResourceLoader()
    loader.discover_resources(root)
    snapshot = loader.get_resource_snapshot()

    assert snapshot.active_skill_descriptors == ()
    assert any(
        decision.logical_id == "review/SKILL.md"
        and decision.winner_id is None
        and decision.reason == "same_precedence_conflict"
        for decision in snapshot.merge_decisions
    )


def test_theme_same_precedence_collision_keeps_first_winner_and_records_loser(
    tmp_path, monkeypatch
) -> None:
    import loushang.harness.resources._loader_pipeline as pipeline_module
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.harness.resources._loader_types import _SourceDiscovery
    from loushang.harness.resources.types import ThemeDescriptor

    root = tmp_path / "project"
    root.mkdir()

    theme_a = ThemeDescriptor(
        name="clean", source_path=root / "themes" / "a.json", canonical_name="clean"
    )
    theme_b = ThemeDescriptor(
        name="clean", source_path=root / "themes" / "b.json", canonical_name="clean"
    )

    monkeypatch.setattr(
        pipeline_module,
        "_discover_built_in_resources",
        lambda _packages: _SourceDiscovery(),
    )
    monkeypatch.setattr(
        pipeline_module,
        "_discover_project_resources",
        lambda _root: _SourceDiscovery(themes=[theme_a, theme_b]),
    )

    loader = DefaultResourceLoader()
    loader.discover_resources(root)
    snapshot = loader.get_resource_snapshot()

    assert [
        descriptor.source_path.name for descriptor in snapshot.active_theme_descriptors
    ] == ["a.json"]
    assert [
        descriptor.source_path.name
        for descriptor in snapshot.candidate_theme_descriptors
    ] == ["a.json", "b.json"]
    assert any(
        diagnostic.details["resource_type"] == "theme"
        for diagnostic in snapshot.diagnostics
    )


def test_theme_discovery_skips_non_json_entries_and_records_diagnostic(
    tmp_path, monkeypatch
) -> None:
    import loushang.harness.resources._loader_pipeline as pipeline_module
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.harness.resources._loader_types import _SourceDiscovery

    root = tmp_path / "project"
    themes_dir = root / "themes"
    themes_dir.mkdir(parents=True)
    (themes_dir / "clean.json").write_text("{}", encoding="utf-8")
    (themes_dir / "README.md").write_text("not a theme", encoding="utf-8")

    monkeypatch.setattr(
        pipeline_module,
        "_discover_built_in_resources",
        lambda _packages: _SourceDiscovery(),
    )

    loader = DefaultResourceLoader()
    loader.discover_resources(root)
    snapshot = loader.get_resource_snapshot()

    assert [
        descriptor.canonical_name for descriptor in snapshot.candidate_theme_descriptors
    ] == ["clean.json"]
    assert [diagnostic.code for diagnostic in snapshot.diagnostics] == [
        "unsupported_theme_entry"
    ]
    assert snapshot.diagnostics[0].details["resource_type"] == "theme"
    assert snapshot.diagnostics[0].source_path == themes_dir / "README.md"


def test_theme_discovery_reports_invalid_json_theme_diagnostic(
    tmp_path, monkeypatch
) -> None:
    import loushang.harness.resources._loader_pipeline as pipeline_module
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.harness.resources._loader_types import _SourceDiscovery

    root = tmp_path / "project"
    themes_dir = root / "themes"
    themes_dir.mkdir(parents=True)
    (themes_dir / "clean.json").write_text('{"colors": {}}', encoding="utf-8")
    (themes_dir / "broken.json").write_text("{not json", encoding="utf-8")

    monkeypatch.setattr(
        pipeline_module,
        "_discover_built_in_resources",
        lambda _packages: _SourceDiscovery(),
    )

    loader = DefaultResourceLoader()
    loader.discover_resources(root)
    snapshot = loader.get_resource_snapshot()

    assert [
        descriptor.canonical_name for descriptor in snapshot.candidate_theme_descriptors
    ] == ["clean.json"]
    assert [diagnostic.code for diagnostic in snapshot.diagnostics] == [
        "invalid_theme_json"
    ]
    assert snapshot.diagnostics[0].details["resource_type"] == "theme"
    assert snapshot.diagnostics[0].source_path == themes_dir / "broken.json"


def test_theme_discovery_reports_non_object_theme_schema_diagnostic(
    tmp_path, monkeypatch
) -> None:
    import loushang.harness.resources._loader_pipeline as pipeline_module
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.harness.resources._loader_types import _SourceDiscovery

    root = tmp_path / "project"
    themes_dir = root / "themes"
    themes_dir.mkdir(parents=True)
    (themes_dir / "clean.json").write_text('{"colors": {}}', encoding="utf-8")
    (themes_dir / "array.json").write_text("[]", encoding="utf-8")

    monkeypatch.setattr(
        pipeline_module,
        "_discover_built_in_resources",
        lambda _packages: _SourceDiscovery(),
    )

    loader = DefaultResourceLoader()
    loader.discover_resources(root)
    snapshot = loader.get_resource_snapshot()

    assert [
        descriptor.canonical_name for descriptor in snapshot.candidate_theme_descriptors
    ] == ["clean.json"]
    assert [diagnostic.code for diagnostic in snapshot.diagnostics] == [
        "invalid_theme_schema"
    ]
    assert snapshot.diagnostics[0].details["resource_type"] == "theme"
    assert snapshot.diagnostics[0].source_path == themes_dir / "array.json"


def test_extension_same_name_candidates_remain_active_after_precedence_sort(
    tmp_path, monkeypatch
) -> None:
    import loushang.harness.resources._loader_pipeline as pipeline_module
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.harness.resources._loader_types import _SourceDiscovery
    from loushang.harness.resources.types import ExtensionDescriptor

    root = tmp_path / "project"
    root.mkdir()

    built_in_ext = ExtensionDescriptor(
        name="guard",
        source_path=Path("/tmp/builtin/extensions/guard.py"),
        entry_path=Path("/tmp/builtin/extensions/guard.py"),
        id="guard",
        canonical_name="guard",
        source_kind="built_in",
        source_scope="builtin",
        source="package_resource",
    )
    project_ext = ExtensionDescriptor(
        name="guard",
        source_path=root / "extensions" / "guard.py",
        entry_path=root / "extensions" / "guard.py",
        id="guard",
        canonical_name="guard",
    )

    monkeypatch.setattr(
        pipeline_module,
        "_discover_built_in_resources",
        lambda _packages: _SourceDiscovery(extensions=[built_in_ext]),
    )
    monkeypatch.setattr(
        pipeline_module,
        "_discover_project_resources",
        lambda _root: _SourceDiscovery(extensions=[project_ext]),
    )

    loader = DefaultResourceLoader()
    loader.discover_resources(root)
    snapshot = loader.get_resource_snapshot()

    assert [
        descriptor.source_kind for descriptor in snapshot.active_extension_descriptors
    ] == [
        "project_local",
        "built_in",
    ]
    assert [
        descriptor.source_kind
        for descriptor in snapshot.candidate_extension_descriptors
    ] == [
        "built_in",
        "project_local",
    ]


def test_agents_md_stays_outside_named_prompt_collision_model(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )

    root = tmp_path / "project"
    prompts_dir = root / "prompts"
    prompts_dir.mkdir(parents=True)
    (root / "AGENTS.md").write_text("repo guidance", encoding="utf-8")
    (prompts_dir / "AGENTS.md").write_text("prompt payload", encoding="utf-8")

    loader = DefaultResourceLoader()
    bundle = loader.discover_resources(root)

    assert bundle.agents_md == "repo guidance"
    assert [descriptor.name for descriptor in bundle.prompts] == ["AGENTS"]


def test_project_local_precedes_external_package_and_built_in() -> None:
    from loushang.harness.resources._loader_precedence import (
        _source_precedence_rank,
    )

    assert _source_precedence_rank("project_local") < _source_precedence_rank(
        "external_package"
    )
    assert _source_precedence_rank("external_package") < _source_precedence_rank(
        "built_in"
    )


def test_same_tier_candidates_are_sorted_by_source_root_order_then_canonical_path() -> (
    None
):
    from loushang.harness.resources._loader_precedence import _candidate_sort_key
    from loushang.harness.resources.types import PromptFragmentDescriptor

    a = PromptFragmentDescriptor(
        name="repo",
        source_path=Path("/tmp/project/prompts/a.md"),
        text="A",
        canonical_name="repo.md",
        source_root_order=0,
    )
    b = PromptFragmentDescriptor(
        name="repo",
        source_path=Path("/tmp/project/prompts/b.md"),
        text="B",
        canonical_name="repo.md",
        source_root_order=1,
    )

    assert _candidate_sort_key(a) < _candidate_sort_key(b)


def test_resource_loader_applies_package_source_filters(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.harness.resources.packages.source import PackageSourceConfig

    package_root = tmp_path / "packages" / "review-pack"
    (package_root / "prompts").mkdir(parents=True)
    (package_root / "skills" / "review").mkdir(parents=True)
    (package_root / "skills" / "debug").mkdir(parents=True)
    (package_root / "prompts" / "review.md").write_text(
        "Review prompt", encoding="utf-8"
    )
    (package_root / "prompts" / "debug.md").write_text("Debug prompt", encoding="utf-8")
    (package_root / "skills" / "review" / "SKILL.md").write_text(
        "Review skill", encoding="utf-8"
    )
    (package_root / "skills" / "debug" / "SKILL.md").write_text(
        "Debug skill", encoding="utf-8"
    )

    loader = DefaultResourceLoader(
        package_roots=(package_root,),
        package_source_filters={
            package_root: PackageSourceConfig(
                source=str(package_root), prompts=("review.md",), skills=("review",)
            )
        },
    )
    bundle = loader.discover_resources(tmp_path)

    assert [prompt.name for prompt in bundle.prompts] == ["review"]
    assert [skill.name for skill in bundle.skills] == ["review"]
    summary = loader.get_package_resource_summaries()[0]
    assert summary.prompt_count == 1
    assert summary.skill_count == 1


def test_resource_loader_applies_package_filter_override_patterns(tmp_path) -> None:
    from loushang.coding.resource_runtime import (
        CodingResourceLoader as DefaultResourceLoader,
    )
    from loushang.harness.resources.packages.source import PackageSourceConfig

    package_root = tmp_path / "packages" / "review-pack"
    (package_root / "prompts").mkdir(parents=True)
    (package_root / "skills" / "review").mkdir(parents=True)
    (package_root / "skills" / "debug").mkdir(parents=True)
    (package_root / "prompts" / "review.md").write_text(
        "Review prompt", encoding="utf-8"
    )
    (package_root / "prompts" / "debug.md").write_text("Debug prompt", encoding="utf-8")
    (package_root / "skills" / "review" / "SKILL.md").write_text(
        "Review skill", encoding="utf-8"
    )
    (package_root / "skills" / "debug" / "SKILL.md").write_text(
        "Debug skill", encoding="utf-8"
    )

    loader = DefaultResourceLoader(
        package_roots=(package_root,),
        package_source_filters={
            package_root: PackageSourceConfig(
                source=str(package_root),
                prompts=("*.md", "!debug.md", "+debug.md", "-review.md"),
                skills=("*", "!debug", "+debug", "-review"),
            )
        },
    )
    bundle = loader.discover_resources(tmp_path)

    assert [prompt.name for prompt in bundle.prompts] == ["debug"]
    assert [skill.name for skill in bundle.skills] == ["debug"]
