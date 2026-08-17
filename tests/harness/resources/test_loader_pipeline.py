from __future__ import annotations

from pathlib import Path
from types import MappingProxyType

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._loader_pipeline import (
    _ResourceDiscoveries,
    _ResourceDiscoveryRequest,
)
from loushang.harness.resources._loader_types import _SourceDiscovery
from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.resources.packages.source import PackageSourceConfig
from loushang.harness.resources.types import (
    ExtensionDescriptor,
    PromptFragmentDescriptor,
    ResourceSnapshot,
    ResourceSourceKind,
    SkillDescriptor,
    ThemeDescriptor,
)


def _source_discovery(source_kind: ResourceSourceKind) -> _SourceDiscovery:
    name = str(source_kind)
    path = Path(f"/{name}")
    return _SourceDiscovery(
        prompts=[
            PromptFragmentDescriptor(
                name=name,
                source_path=path / "prompt.md",
                text=name,
                source_kind=source_kind,
            )
        ],
        skills=[
            SkillDescriptor(
                name=name,
                source_path=path / "SKILL.md",
                source_kind=source_kind,
            )
        ],
        extensions=[
            ExtensionDescriptor(
                name=name,
                source_path=path / "extension.py",
                source_kind=source_kind,
            )
        ],
        themes=[
            ThemeDescriptor(
                name=name,
                source_path=path / "theme.json",
                source_kind=source_kind,
            )
        ],
        diagnostics=[DiagnosticDraft(code=name, message=name)],
    )


def test_resource_discoveries_centralize_candidate_and_diagnostic_order() -> None:
    by_kind = {
        source_kind: _source_discovery(source_kind)
        for source_kind in (
            "temporary",
            "built_in",
            "external_package",
            "user_global",
            "project_local",
        )
    }
    candidate_order = (
        "temporary",
        "built_in",
        "external_package",
        "user_global",
        "project_local",
    )
    diagnostic_order = (
        "built_in",
        "external_package",
        "user_global",
        "project_local",
        "temporary",
    )
    discoveries = _ResourceDiscoveries(
        candidate_order=tuple(by_kind[source_kind] for source_kind in candidate_order),
        diagnostic_order=tuple(
            by_kind[source_kind] for source_kind in diagnostic_order
        ),
    )

    assert tuple(descriptor.name for descriptor in discoveries.prompts) == (
        candidate_order
    )
    assert tuple(descriptor.name for descriptor in discoveries.skills) == (
        candidate_order
    )
    assert tuple(descriptor.name for descriptor in discoveries.extensions) == (
        candidate_order
    )
    assert tuple(descriptor.name for descriptor in discoveries.themes) == (
        candidate_order
    )
    assert tuple(diagnostic.code for diagnostic in discoveries.diagnostics) == (
        diagnostic_order
    )


def test_resource_loader_passes_one_immutable_discovery_request(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import loushang.harness.resources.loader as loader_module

    package_root = tmp_path / "package"
    user_root = tmp_path / "user"
    workspace = tmp_path / "workspace"
    package_filter = PackageSourceConfig(
        source=str(package_root),
        prompts=("review.md",),
    )
    captured: list[_ResourceDiscoveryRequest] = []

    def discover(request: _ResourceDiscoveryRequest) -> ResourceSnapshot:
        captured.append(request)
        return ResourceSnapshot(cwd=request.cwd)

    monkeypatch.setattr(loader_module, "_discover_snapshot", discover)
    loader = ResourceLoader(
        package_roots=(package_root,),
        package_source_filters={package_root: package_filter},
        user_resource_roots=(user_root,),
        additional_extension_paths=("review.py",),
        additional_skill_paths=("review-skill",),
        additional_prompt_template_paths=("review.md",),
        additional_theme_paths=("dark.json",),
        no_extensions=True,
        no_skills=True,
        no_prompt_templates=True,
        no_themes=True,
        no_context_files=True,
        built_in_resource_packages=("loushang.builtin",),
        context_file_names=("PROJECT.md",),
        workspace_root=workspace,
    )
    loader.set_user_resource_roots((user_root,), explicit_roots=(user_root,))

    loader.discover_resources(workspace)

    assert len(captured) == 1
    request = captured[0]
    assert request.cwd == workspace
    assert request.package_roots == (package_root.resolve(),)
    assert request.package_source_filters == {
        package_root.resolve(): package_filter
    }
    assert isinstance(request.package_source_filters, MappingProxyType)
    assert request.user_resource_roots == (user_root.resolve(),)
    assert request.explicit_user_roots == frozenset({user_root.resolve()})
    assert request.additional_extension_paths == (Path("review.py"),)
    assert request.additional_skill_paths == (Path("review-skill"),)
    assert request.additional_prompt_template_paths == (Path("review.md"),)
    assert request.additional_theme_paths == (Path("dark.json"),)
    assert request.no_extensions is True
    assert request.no_skills is True
    assert request.no_prompt_templates is True
    assert request.no_themes is True
    assert request.no_context_files is True
    assert request.built_in_resource_packages == ("loushang.builtin",)
    assert request.context_file_names == ("PROJECT.md",)
    assert request.project_resource_root == workspace.resolve() / ".loushang"
