from __future__ import annotations


def test_skill_loader_discovers_and_toggles_skills(tmp_path) -> None:
    from loushang.coding.resource_runtime import CodingSkillLoader as SkillLoader

    project = tmp_path / "project"
    skill_dir = project / "skills" / "review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("Review rules", encoding="utf-8")

    loader = SkillLoader()
    skills = loader.discover_skills(project)

    assert [skill.name for skill in skills] == ["review"]
    assert loader.get_skill("review").content == "Review rules"
    assert loader.load_skill("review/SKILL.md").name == "review"

    disabled = loader.disable_skill("review")

    assert disabled.name == "review"
    assert loader.list_enabled_skills() == []
    assert loader.enable_skill("review").name == "review"
    assert [skill.name for skill in loader.list_enabled_skills()] == ["review"]


def test_skill_loader_accepts_initial_disabled_skills(tmp_path) -> None:
    from loushang.coding.resource_runtime import CodingSkillLoader as SkillLoader

    skill_dir = tmp_path / "skills" / "review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("Review rules", encoding="utf-8")

    loader = SkillLoader(disabled_skills=("review",))
    loader.discover_skills(tmp_path)

    assert [skill.name for skill in loader.list_skills()] == ["review"]
    assert loader.list_enabled_skills() == []


def test_skill_loader_can_synchronize_disabled_skills_with_settings(tmp_path) -> None:
    from loushang.coding.control import SettingsManager
    from loushang.coding.resource_runtime import CodingSkillLoader as SkillLoader

    skill_dir = tmp_path / "skills" / "review"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("Review rules", encoding="utf-8")

    settings = SettingsManager(global_settings_path=tmp_path / "settings.json")
    settings.disable_skill("review", scope="global")

    loader = SkillLoader(settings_manager=settings, settings_scope="global")
    loader.discover_skills(tmp_path)

    assert loader.list_enabled_skills() == []
    loader.enable_skill("review")
    assert settings.get_disabled_skills() == []
    assert [skill.name for skill in loader.list_enabled_skills()] == ["review"]
    loader.disable_skill("review")
    assert settings.get_disabled_skills() == ["review"]
    assert loader.list_enabled_skills() == []


def test_skill_loader_load_missing_skill_raises_key_error(tmp_path) -> None:
    import pytest

    from loushang.coding.resource_runtime import CodingSkillLoader as SkillLoader

    loader = SkillLoader()
    loader.discover_skills(tmp_path)

    with pytest.raises(KeyError, match="missing"):
        loader.load_skill("missing")


def test_skill_loader_is_exported_from_coding_package() -> None:
    from loushang.coding import SkillLoader

    assert SkillLoader is not None
