from __future__ import annotations

from pathlib import Path

from loushang.harness.resources._loader_discovery_context import (
    _discover_context_descriptors,
)


def test_context_discovery_stacks_user_and_ancestor_descriptors(tmp_path: Path) -> None:
    user_root = tmp_path / "user"
    workspace_root = tmp_path / "workspace"
    project_root = workspace_root / "project"
    nested = project_root / "src" / "feature"
    user_root.mkdir()
    nested.mkdir(parents=True)
    user_context = user_root / "AGENTS.md"
    workspace_context = workspace_root / "AGENTS.md"
    project_context = project_root / "CLAUDE.md"
    user_context.write_text("Global guidance", encoding="utf-8")
    workspace_context.write_text("Workspace guidance", encoding="utf-8")
    project_context.write_text("Project guidance", encoding="utf-8")

    descriptors, nearest, diagnostics = _discover_context_descriptors(
        nested,
        user_resource_roots=(user_root,),
        context_file_names=("AGENTS.md", "CLAUDE.md"),
    )

    assert diagnostics == []
    assert [descriptor.source_path for descriptor in descriptors] == [
        user_context,
        workspace_context,
        project_context,
    ]
    assert [descriptor.text for descriptor in descriptors] == [
        "Global guidance",
        "Workspace guidance",
        "Project guidance",
    ]
    assert [descriptor.source_kind for descriptor in descriptors] == [
        "user_global",
        "project_local",
        "project_local",
    ]
    assert [descriptor.source_scope for descriptor in descriptors] == [
        "user",
        "project",
        "project",
    ]
    assert [descriptor.id for descriptor in descriptors] == [
        "user.agents",
        "project.agents",
        "project.claude",
    ]
    assert [descriptor.prompt_kind for descriptor in descriptors] == [
        "agents_md",
        "agents_md",
        "claude_md",
    ]
    assert [descriptor.source_root_order for descriptor in descriptors] == [
        0,
        len(workspace_root.parents),
        len(project_root.parents),
    ]
    assert nearest is descriptors[-1]


def test_context_discovery_uses_configured_filename_precedence(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    nested_file = project_root / "src" / "module.py"
    nested_file.parent.mkdir(parents=True)
    nested_file.touch()
    agents_context = project_root / "AGENTS.md"
    claude_context = project_root / "CLAUDE.md"
    agents_context.write_text("Agent guidance", encoding="utf-8")
    claude_context.write_text("Compatibility guidance", encoding="utf-8")

    descriptors, nearest, diagnostics = _discover_context_descriptors(
        nested_file,
        user_resource_roots=(),
        context_file_names=("CLAUDE.md", "AGENTS.md"),
    )

    assert diagnostics == []
    assert [descriptor.source_path for descriptor in descriptors] == [claude_context]
    assert descriptors[0].canonical_name == "CLAUDE.md"
    assert descriptors[0].prompt_kind == "claude_md"
    assert nearest is descriptors[0]


def test_context_discovery_falls_back_to_last_user_root(tmp_path: Path) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    project_root = tmp_path / "project"
    first_root.mkdir()
    second_root.mkdir()
    project_root.mkdir()
    first_context = first_root / "AGENTS.md"
    second_context = second_root / "AGENTS.md"
    first_context.write_text("First", encoding="utf-8")
    second_context.write_text("Second", encoding="utf-8")

    descriptors, nearest, diagnostics = _discover_context_descriptors(
        project_root,
        user_resource_roots=(first_root, second_root),
        context_file_names=("AGENTS.md",),
    )

    assert diagnostics == []
    assert [descriptor.source_path for descriptor in descriptors] == [
        first_context,
        second_context,
    ]
    assert nearest is descriptors[-1]


def test_context_discovery_reports_unreadable_context_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    context_path = project_root / "AGENTS.md"
    context_path.write_text("Unreadable", encoding="utf-8")
    original_read_text = Path.read_text

    def fail_context_read(path: Path, *args, **kwargs):
        if path == context_path:
            raise OSError("permission denied")
        return original_read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", fail_context_read)

    descriptors, nearest, diagnostics = _discover_context_descriptors(
        project_root,
        user_resource_roots=(),
        context_file_names=("AGENTS.md",),
    )

    assert descriptors == []
    assert nearest is None
    assert len(diagnostics) == 1
    assert diagnostics[0].code == "unreadable_agents_file"
    assert diagnostics[0].source_path == context_path
    assert diagnostics[0].message.startswith("Failed to read AGENTS.md: ")
