from pathlib import Path

from loushang.harness.extensions.resources import ExtensionResourceRuntime
from loushang.harness.extensions.types import (
    ExtensionResourceContribution,
    LoadedExtension,
)
from loushang.harness.resources._loader_resolution import (
    _resolve_candidates,
    _resolve_extension_candidates,
    _resolve_strict_named_candidates,
)
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    ResourceBundle,
    ResourceSourceKind,
    SkillDescriptor,
    ThemeDescriptor,
)


def _skill(source_kind: ResourceSourceKind, *, root_order: int = 0) -> SkillDescriptor:
    return SkillDescriptor(
        name="review",
        source_path=Path(source_kind) / "review" / "SKILL.md",
        source_kind=source_kind,
        source_root_order=root_order,
    )


def test_rcp0_precedence_parity_covers_all_implemented_source_classes() -> None:
    candidates = [
        _skill("built_in"),
        _skill("external_package"),
        _skill("user_global"),
        _skill("project_local"),
        _skill("temporary"),
    ]

    active, diagnostics, decisions = _resolve_strict_named_candidates(
        candidates,
        resource_type="skill",
    )

    assert [candidate.source_kind for candidate in active] == ["temporary"]
    assert [diagnostic.code for diagnostic in diagnostics] == ["resource_collision"]
    assert len(decisions) == 1
    decision = decisions[0]
    assert decision.winner_source_kind == "temporary"
    assert decision.candidate_source_kinds == (
        "temporary",
        "project_local",
        "user_global",
        "external_package",
        "built_in",
    )
    assert decision.reason == "source_precedence"


def test_rcp0_strict_skill_parity_rejects_same_precedence_candidates() -> None:
    later = _skill("project_local", root_order=2)
    earlier = _skill("project_local", root_order=1)

    active, diagnostics, decisions = _resolve_strict_named_candidates(
        [later, earlier],
        resource_type="skill",
    )

    assert active == []
    assert [diagnostic.code for diagnostic in diagnostics] == ["resource_collision"]
    assert decisions[0].candidate_ids == ("review", "review")
    assert decisions[0].winner_id is None
    assert decisions[0].reason == "same_precedence_conflict"


def test_rcp0_permissive_theme_parity_prefers_lower_root_order() -> None:
    later = ThemeDescriptor(
        name="clean",
        source_path=Path("later") / "clean.json",
        source_root_order=2,
    )
    earlier = ThemeDescriptor(
        name="clean",
        source_path=Path("earlier") / "clean.json",
        source_root_order=1,
    )

    active, diagnostics, decisions = _resolve_candidates(
        [later, earlier],
        resource_type="theme",
    )

    assert active == [earlier]
    assert [diagnostic.code for diagnostic in diagnostics] == ["resource_collision"]
    assert decisions[0].winner_id == "clean"
    assert decisions[0].reason == "precedence_and_tiebreak"


def test_rcp0_extension_descriptor_parity_keeps_all_enabled_candidates() -> None:
    built_in = ExtensionDescriptor(
        name="guard",
        source_path=Path("built_in") / "guard.py",
        source_kind="built_in",
    )
    project = ExtensionDescriptor(
        name="guard",
        source_path=Path("project") / "guard.py",
        source_kind="project_local",
    )

    active, diagnostics, decisions = _resolve_extension_candidates(
        [built_in, project],
        resource_type="extension",
    )

    assert [candidate.source_kind for candidate in active] == [
        "project_local",
        "built_in",
    ]
    assert diagnostics == []
    assert decisions[0].candidate_source_kinds == ("project_local", "built_in")
    assert decisions[0].reason == "all_enabled_candidates_active"


def test_rcp0_extension_resource_parity_preserves_duplicate_route_order_and_disabled(
    tmp_path: Path,
) -> None:
    base_skill = SkillDescriptor(
        name="review",
        source_path=tmp_path / "base" / "SKILL.md",
    )
    first_extension_skill = SkillDescriptor(
        name="review",
        source_path=tmp_path / "extension-a" / "SKILL.md",
    )
    disabled_extension_skill = SkillDescriptor(
        name="review",
        source_path=tmp_path / "extension-b" / "SKILL.md",
        enabled=False,
    )
    base = ResourceBundle(cwd=tmp_path, skills=[base_skill])
    seen: list[tuple[str, ...]] = []

    def discover_first(
        bundle: ResourceBundle,
        context: object,
    ) -> ExtensionResourceContribution:
        seen.append(tuple(skill.source_path.parent.name for skill in bundle.skills))
        assert context == {"reason": "rcp0-parity"}
        return ExtensionResourceContribution(skills=[first_extension_skill])

    def discover_second(
        bundle: ResourceBundle,
        context: object,
    ) -> ExtensionResourceContribution:
        seen.append(tuple(skill.source_path.parent.name for skill in bundle.skills))
        assert context == {"reason": "rcp0-parity"}
        return ExtensionResourceContribution(skills=[disabled_extension_skill])

    first_extension = LoadedExtension(
        name="resource-parity-a",
        source_path=tmp_path / "extension-a.py",
        hooks={"resources_discover": [discover_first]},
    )
    second_extension = LoadedExtension(
        name="resource-parity-b",
        source_path=tmp_path / "extension-b.py",
        hooks={"resources_discover": [discover_second]},
    )
    diagnostics = []

    discovered = ExtensionResourceRuntime(
        [first_extension, second_extension],
        diagnostics=diagnostics,
    ).discover(base, context={"reason": "rcp0-parity"})

    assert discovered is not base
    assert seen == [("base",), ("base", "extension-a")]
    assert [skill.name for skill in discovered.skills] == [
        "review",
        "review",
        "review",
    ]
    assert [skill.enabled for skill in discovered.skills] == [True, True, False]
    assert [skill.name for skill in base.skills] == ["review"]
    assert diagnostics == []
