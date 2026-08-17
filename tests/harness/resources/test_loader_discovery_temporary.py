from __future__ import annotations

from pathlib import Path

from loushang.harness.resources._loader_discovery_temporary import (
    _discover_temporary_resources,
)


def test_temporary_discovery_resolves_relative_single_file_inputs(
    tmp_path: Path,
) -> None:
    cwd = tmp_path / "workspace"
    skill_dir = cwd / "skills" / "review"
    cwd.mkdir()
    skill_dir.mkdir(parents=True)
    (cwd / "review.md").write_text(
        "---\ndescription: Review changes\n---\n\nReview carefully.",
        encoding="utf-8",
    )
    (skill_dir / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review changes.\n---\n\nReview carefully.",
        encoding="utf-8",
    )
    (cwd / "review.py").write_text("", encoding="utf-8")
    (cwd / "dark.json").write_text("{}", encoding="utf-8")

    discovered = _discover_temporary_resources(
        cwd,
        extension_paths=(Path("review.py"),),
        skill_paths=(Path("skills/review/SKILL.md"),),
        prompt_paths=(Path("review.md"),),
        theme_paths=(Path("dark.json"),),
    )

    assert discovered.diagnostics == []
    assert [descriptor.name for descriptor in discovered.prompts] == ["review"]
    assert [descriptor.name for descriptor in discovered.skills] == ["review"]
    assert [descriptor.name for descriptor in discovered.extensions] == ["review"]
    assert [descriptor.name for descriptor in discovered.themes] == ["dark"]
    assert discovered.prompts[0].source_path == (cwd / "review.md").resolve()
    assert discovered.skills[0].source_path == (skill_dir / "SKILL.md").resolve()
    assert discovered.extensions[0].entry_path == (cwd / "review.py").resolve()
    assert discovered.themes[0].source_path == (cwd / "dark.json").resolve()
    assert {
        descriptor.source_kind
        for descriptor in [
            *discovered.prompts,
            *discovered.skills,
            *discovered.extensions,
            *discovered.themes,
        ]
    } == {"temporary"}
    assert {
        descriptor.source_root_order
        for descriptor in [
            *discovered.prompts,
            *discovered.skills,
            *discovered.extensions,
            *discovered.themes,
        ]
    } == {0}


def test_temporary_discovery_preserves_directory_scanning_contract(
    tmp_path: Path,
) -> None:
    prompts_dir = tmp_path / "prompt-inputs"
    skills_dir = tmp_path / "skill-inputs"
    extensions_dir = tmp_path / "extension-inputs"
    themes_dir = tmp_path / "theme-inputs"
    prompts_dir.mkdir()
    (skills_dir / "review").mkdir(parents=True)
    (extensions_dir / "review").mkdir(parents=True)
    themes_dir.mkdir()
    (prompts_dir / "review.md").write_text("Review carefully.", encoding="utf-8")
    (skills_dir / "review" / "SKILL.md").write_text(
        "Review carefully.", encoding="utf-8"
    )
    (extensions_dir / "inline.py").write_text("", encoding="utf-8")
    (extensions_dir / "review" / "extension.py").write_text("", encoding="utf-8")
    (themes_dir / "dark.json").write_text("{}", encoding="utf-8")

    discovered = _discover_temporary_resources(
        tmp_path,
        extension_paths=(extensions_dir,),
        skill_paths=(skills_dir,),
        prompt_paths=(prompts_dir,),
        theme_paths=(themes_dir,),
    )

    assert discovered.diagnostics == []
    assert [descriptor.canonical_name for descriptor in discovered.prompts] == [
        "review.md"
    ]
    assert [descriptor.canonical_name for descriptor in discovered.skills] == [
        "review/SKILL.md"
    ]
    assert [descriptor.canonical_name for descriptor in discovered.extensions] == [
        "review",
        "inline.py",
    ]
    assert [descriptor.canonical_name for descriptor in discovered.themes] == [
        "dark.json"
    ]


def test_temporary_discovery_preserves_path_and_validation_diagnostics(
    tmp_path: Path,
) -> None:
    unsupported_prompt = tmp_path / "prompt.txt"
    unsupported_skill = tmp_path / "README.md"
    unsupported_extension = tmp_path / "extension.txt"
    unsupported_theme = tmp_path / "theme.txt"
    invalid_theme = tmp_path / "broken.json"
    for path in (
        unsupported_prompt,
        unsupported_skill,
        unsupported_extension,
        unsupported_theme,
    ):
        path.write_text("unsupported", encoding="utf-8")
    invalid_theme.write_text("[]", encoding="utf-8")

    discovered = _discover_temporary_resources(
        tmp_path,
        extension_paths=(Path("missing.py"), Path("extension.txt")),
        skill_paths=(Path("missing-skill"), Path("README.md")),
        prompt_paths=(Path("missing.md"), Path("prompt.txt")),
        theme_paths=(Path("missing.json"), Path("theme.txt"), Path("broken.json")),
    )

    assert discovered.prompts == []
    assert discovered.skills == []
    assert discovered.extensions == []
    assert discovered.themes == []
    assert [diagnostic.code for diagnostic in discovered.diagnostics] == [
        "missing_prompt_path",
        "unsupported_prompt_path",
        "missing_skill_path",
        "unsupported_skill_path",
        "missing_extension_path",
        "unsupported_extension_path",
        "missing_theme_path",
        "unsupported_theme_path",
        "invalid_theme_schema",
    ]
    assert all(
        diagnostic.details["source_kind"] == "temporary"
        for diagnostic in discovered.diagnostics
    )


def test_temporary_discovery_preserves_unreadable_prompt_diagnostic(
    tmp_path: Path,
    monkeypatch,
) -> None:
    prompt_path = tmp_path / "review.md"
    prompt_path.write_text("Review carefully.", encoding="utf-8")

    def raise_unreadable(*args, **kwargs) -> str:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", raise_unreadable)

    discovered = _discover_temporary_resources(
        tmp_path,
        extension_paths=(),
        skill_paths=(),
        prompt_paths=(prompt_path,),
        theme_paths=(),
    )

    assert discovered.prompts == []
    assert [diagnostic.code for diagnostic in discovered.diagnostics] == [
        "unreadable_prompt_entry"
    ]
    assert discovered.diagnostics[0].source_path == prompt_path
    assert "permission denied" in discovered.diagnostics[0].message
