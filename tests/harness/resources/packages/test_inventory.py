from __future__ import annotations

from pathlib import Path

from loushang.harness.resources.packages.inventory import (
    summarize_package_inventory,
)


def _skill(path: Path, *, name: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {name} description\n---\n",
        encoding="utf-8",
    )


def test_package_inventory_preserves_skill_ignore_and_nested_stop_semantics(
    tmp_path: Path,
) -> None:
    root = tmp_path / "package"
    _skill(root / "skills" / "parent" / "SKILL.md", name="parent")
    _skill(
        root / "skills" / "parent" / "nested" / "SKILL.md",
        name="nested-hidden-by-parent",
    )
    _skill(root / "skills" / "ignored" / "SKILL.md", name="ignored")
    _skill(root / "skills" / "visible" / "SKILL.md", name="visible")
    (root / "skills" / ".ignore").write_text("ignored\n", encoding="utf-8")

    summary = summarize_package_inventory(root)

    assert summary.skill_count == 2
    assert summary.diagnostic_count == 0


def test_package_inventory_rejects_symlink_reads_and_invalid_theme_json(
    tmp_path: Path,
    symlink_or_skip,
) -> None:
    root = tmp_path / "package"
    prompts = root / "prompts"
    themes = root / "themes"
    prompts.mkdir(parents=True)
    themes.mkdir(parents=True)
    outside_prompt = tmp_path / "outside.md"
    outside_prompt.write_text("outside", encoding="utf-8")
    symlink_or_skip(prompts / "outside.md", outside_prompt)
    (themes / "valid.json").write_text("{}", encoding="utf-8")
    (themes / "invalid.json").write_text("[]", encoding="utf-8")

    summary = summarize_package_inventory(root)

    assert summary.prompt_count == 0
    assert summary.theme_count == 1
    assert summary.diagnostic_count == 2
