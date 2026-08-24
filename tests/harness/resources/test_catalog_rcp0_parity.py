from pathlib import Path

from loushang.harness.extensions.resources import ExtensionResourceRuntime
from loushang.harness.extensions.types import (
    ExtensionResourceContribution,
    LoadedExtension,
)
from loushang.harness.resources._loader_resolution import _resolve_candidates
from loushang.harness.resources.types import (
    ResourceBundle,
    ResourceSourceKind,
    SkillDescriptor,
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

    active, diagnostics, decisions = _resolve_candidates(
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
    assert decision.reason == "precedence_and_tiebreak"


def test_rcp0_same_source_parity_prefers_lower_root_order() -> None:
    later = _skill("project_local", root_order=2)
    earlier = _skill("project_local", root_order=1)

    active, _, decisions = _resolve_candidates(
        [later, earlier],
        resource_type="skill",
    )

    assert active == [earlier]
    assert decisions[0].candidate_ids == ("review", "review")
    assert decisions[0].winner_source_kind == "project_local"


def test_rcp0_extension_resource_parity_appends_without_mutating_base_bundle(
    tmp_path: Path,
) -> None:
    base_skill = SkillDescriptor(
        name="base",
        source_path=tmp_path / "base" / "SKILL.md",
    )
    extension_skill = SkillDescriptor(
        name="extension",
        source_path=tmp_path / "extension" / "SKILL.md",
    )
    base = ResourceBundle(cwd=tmp_path, skills=[base_skill])

    def discover(
        bundle: ResourceBundle, context: object
    ) -> ExtensionResourceContribution:
        assert bundle is base
        assert context == {"reason": "rcp0-parity"}
        return ExtensionResourceContribution(skills=[extension_skill])

    extension = LoadedExtension(
        name="resource-parity",
        source_path=tmp_path / "extension.py",
        hooks={"resources_discover": [discover]},
    )
    diagnostics = []

    discovered = ExtensionResourceRuntime(
        [extension],
        diagnostics=diagnostics,
    ).discover(base, context={"reason": "rcp0-parity"})

    assert discovered is not base
    assert [skill.name for skill in discovered.skills] == ["base", "extension"]
    assert [skill.name for skill in base.skills] == ["base"]
    assert diagnostics == []
