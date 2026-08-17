from __future__ import annotations

from pathlib import Path

from loushang.harness.resources._loader_discovery_filesystem import (
    _discover_extensions_from_dir,
    _discover_prompts_from_dir,
    _discover_skills_from_dir,
    _discover_themes_from_dir,
)


def test_filesystem_discovery_scans_each_standard_resource_category(
    tmp_path: Path,
) -> None:
    prompts_dir = tmp_path / "prompts"
    skill_dir = tmp_path / "skills" / "review"
    extension_dir = tmp_path / "extensions" / "review"
    themes_dir = tmp_path / "themes"
    prompts_dir.mkdir()
    skill_dir.mkdir(parents=True)
    extension_dir.mkdir(parents=True)
    themes_dir.mkdir()
    (prompts_dir / "review.md").write_text(
        "---\ndescription: Review changes\n---\n\nReview carefully.",
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review changes.\n---\n\nReview carefully.",
        encoding="utf-8",
    )
    (extension_dir / "extension.py").write_text("", encoding="utf-8")
    (themes_dir / "dark.json").write_text("{}", encoding="utf-8")

    common = {
        "source_kind": "project_local",
        "source_scope": "project",
        "source_label": "filesystem",
    }
    prompts, prompt_diagnostics = _discover_prompts_from_dir(prompts_dir, **common)
    skills, skill_diagnostics = _discover_skills_from_dir(
        tmp_path / "skills", **common
    )
    extensions, extension_diagnostics = _discover_extensions_from_dir(
        tmp_path / "extensions", **common
    )
    themes, theme_diagnostics = _discover_themes_from_dir(themes_dir, **common)

    assert [descriptor.canonical_name for descriptor in prompts] == ["review.md"]
    assert [descriptor.canonical_name for descriptor in skills] == [
        "review/SKILL.md"
    ]
    assert [descriptor.canonical_name for descriptor in extensions] == ["review"]
    assert [descriptor.canonical_name for descriptor in themes] == ["dark.json"]
    assert [
        *prompt_diagnostics,
        *skill_diagnostics,
        *extension_diagnostics,
        *theme_diagnostics,
    ] == []


def test_filesystem_discovery_owns_skill_ignore_and_theme_validation(
    tmp_path: Path,
) -> None:
    skills_dir = tmp_path / "skills"
    ignored_skill = skills_dir / "ignored"
    active_skill = skills_dir / "active"
    themes_dir = tmp_path / "themes"
    ignored_skill.mkdir(parents=True)
    active_skill.mkdir()
    themes_dir.mkdir()
    (skills_dir / ".gitignore").write_text("ignored/\n", encoding="utf-8")
    (ignored_skill / "SKILL.md").write_text("Ignored", encoding="utf-8")
    (active_skill / "SKILL.md").write_text("Active", encoding="utf-8")
    (themes_dir / "broken.json").write_text("[]", encoding="utf-8")

    common = {
        "source_kind": "external_package",
        "source_scope": "package",
        "source_label": "package_resource",
    }
    skills, skill_diagnostics = _discover_skills_from_dir(skills_dir, **common)
    themes, theme_diagnostics = _discover_themes_from_dir(themes_dir, **common)

    assert [descriptor.name for descriptor in skills] == ["active"]
    assert skill_diagnostics == []
    assert themes == []
    assert [diagnostic.code for diagnostic in theme_diagnostics] == [
        "invalid_theme_schema"
    ]
