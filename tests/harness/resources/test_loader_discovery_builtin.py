from __future__ import annotations

from pathlib import Path

from loushang.harness.resources._loader_discovery_builtin import (
    _discover_built_in_resources,
)


def test_builtin_discovery_scans_standard_categories_with_logical_paths(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_name = "complete_builtin_resources"
    package_root = tmp_path / package_name
    prompt_dir = package_root / "prompts"
    skill_dir = package_root / "skills" / "review"
    extension_dir = package_root / "extensions" / "review"
    theme_dir = package_root / "themes"
    prompt_dir.mkdir(parents=True)
    skill_dir.mkdir(parents=True)
    extension_dir.mkdir(parents=True)
    theme_dir.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (prompt_dir / "review.md").write_text(
        "---\ndescription: Review changes\n---\n\nReview carefully.",
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review changes.\n---\n\nReview carefully.",
        encoding="utf-8",
    )
    (package_root / "extensions" / "inline.py").write_text("", encoding="utf-8")
    (extension_dir / "extension.py").write_text("", encoding="utf-8")
    (theme_dir / "dark.json").write_text("{}", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    discovered = _discover_built_in_resources((package_name,))

    assert discovered.diagnostics == []
    assert [descriptor.name for descriptor in discovered.prompts] == ["review"]
    assert [descriptor.name for descriptor in discovered.skills] == ["review"]
    assert [descriptor.name for descriptor in discovered.extensions] == [
        "inline",
        "review",
    ]
    assert [descriptor.name for descriptor in discovered.themes] == ["dark"]
    assert discovered.prompts[0].source_path == Path(
        f"{package_name}/prompts/review.md"
    )
    assert discovered.skills[0].source_root == Path(f"{package_name}/skills")
    assert discovered.extensions[1].entry_path == Path(
        f"{package_name}/extensions/review/extension.py"
    )
    assert {
        descriptor.source_root_order
        for descriptor in [
            *discovered.prompts,
            *discovered.skills,
            *discovered.extensions,
            *discovered.themes,
        ]
    } == {0}


def test_builtin_discovery_preserves_diagnostics_and_theme_entry_behavior(
    tmp_path: Path,
    monkeypatch,
) -> None:
    package_name = "invalid_builtin_resources"
    package_root = tmp_path / package_name
    prompts_dir = package_root / "prompts"
    skills_dir = package_root / "skills"
    extensions_dir = package_root / "extensions"
    themes_dir = package_root / "themes"
    prompts_dir.mkdir(parents=True)
    (skills_dir / "invalid").mkdir(parents=True)
    (skills_dir / "missing").mkdir()
    (extensions_dir / "missing").mkdir(parents=True)
    themes_dir.mkdir(parents=True)
    (package_root / "__init__.py").write_text("", encoding="utf-8")
    (prompts_dir / "README.txt").write_text("unsupported", encoding="utf-8")
    (skills_dir / "invalid" / "SKILL.md").write_text(
        "---\ndescription: [broken\n---\n\nBroken.",
        encoding="utf-8",
    )
    (skills_dir / "README.md").write_text("unsupported", encoding="utf-8")
    (extensions_dir / "README.txt").write_text("unsupported", encoding="utf-8")
    (themes_dir / "plain.txt").write_text("not validated", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))

    discovered = _discover_built_in_resources((package_name, "missing_package"))

    assert discovered.prompts == []
    assert discovered.skills == []
    assert discovered.extensions == []
    assert [descriptor.name for descriptor in discovered.themes] == ["plain.txt"]
    assert [diagnostic.code for diagnostic in discovered.diagnostics] == [
        "unsupported_prompt_entry",
        "unsupported_skill_entry",
        "invalid_skill_frontmatter",
        "missing_skill_entry",
        "unsupported_extension_entry",
        "missing_extension_entry",
    ]
    assert all(
        diagnostic.details["source_kind"] == "built_in"
        for diagnostic in discovered.diagnostics
    )
