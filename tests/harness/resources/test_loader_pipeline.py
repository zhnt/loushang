from __future__ import annotations

from pathlib import Path

import pytest

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._loader_pipeline import (
    _ResourceDiscoveries,
    _ResourceDiscoveryRequest,
)
from loushang.harness.resources._loader_types import _SourceDiscovery
from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.resources.packages.mounts import PackageResourceMount
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
    assert request.package_mounts == (
        PackageResourceMount(root=package_root, source_filter=package_filter),
    )
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


def test_resource_loader_does_not_commit_snapshot_when_revision_changes_during_discovery(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import loushang.harness.resources.loader as loader_module

    class RevisionHandle:
        def __init__(self, root: Path) -> None:
            self.root = root
            self.content_digest = "a" * 64
            self.verifications = 0
            self.closed = False

        def verify(self) -> None:
            self.verifications += 1
            if self.verifications > 2:
                raise RuntimeError("revision changed")

        def close(self) -> None:
            self.closed = True

    loader = ResourceLoader(user_resource_roots=())
    loader.discover_resources(tmp_path)
    previous = loader.get_resource_snapshot()
    handle = RevisionHandle(tmp_path)
    mount = PackageResourceMount(
        root=tmp_path,
        content_digest=handle.content_digest,
        revision_handle=handle,  # type: ignore[arg-type]
    )
    loader.set_package_mounts((mount,))
    candidate = ResourceSnapshot(cwd=tmp_path / "candidate")
    monkeypatch.setattr(loader_module, "_discover_snapshot", lambda request: candidate)

    with pytest.raises(RuntimeError, match="revision changed"):
        loader.discover_resources(tmp_path)

    assert loader.get_resource_snapshot() is previous
    loader.close()
    assert handle.closed is True


def test_resource_loader_mount_swap_is_atomic_and_closes_replaced_lease(
    tmp_path: Path,
) -> None:
    class RevisionHandle:
        def __init__(self, root: Path, digest: str) -> None:
            self.root = root
            self.content_digest = digest
            self.fail = False
            self.closed = False

        def verify(self) -> None:
            if self.fail:
                raise RuntimeError("candidate revision changed")

        def close(self) -> None:
            self.closed = True

    first_handle = RevisionHandle(tmp_path / "first", "a" * 64)
    candidate_handle = RevisionHandle(tmp_path / "candidate", "b" * 64)
    first = PackageResourceMount(
        root=first_handle.root,
        content_digest=first_handle.content_digest,
        revision_handle=first_handle,  # type: ignore[arg-type]
    )
    candidate = PackageResourceMount(
        root=candidate_handle.root,
        content_digest=candidate_handle.content_digest,
        revision_handle=candidate_handle,  # type: ignore[arg-type]
    )
    loader = ResourceLoader(user_resource_roots=())
    loader.set_package_mounts((first,))
    candidate_handle.fail = True

    with pytest.raises(RuntimeError, match="candidate revision changed"):
        loader.set_package_mounts((candidate,))

    assert loader._package_mounts == (first,)
    assert first_handle.closed is False
    assert candidate_handle.closed is False

    candidate_handle.fail = False
    loader.set_package_mounts((candidate,))
    assert first_handle.closed is True
    assert candidate_handle.closed is False
    loader.close()
    assert candidate_handle.closed is True
