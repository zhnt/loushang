from __future__ import annotations

import json
from pathlib import Path

import pytest

from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.resources._catalog_input_receipt import (
    ResourceCatalogInputReceipt,
)
from loushang.harness.resources._loader_pipeline import (
    _ResourceDiscoveries,
    _ResourceDiscoveryRequest,
    _ResourceDiscoveryResult,
)
from loushang.harness.resources._loader_types import _SourceDiscovery
from loushang.harness.resources.loader import ResourceLoader
from loushang.harness.resources.packages.mounts import PackageResourceMount
from loushang.harness.resources.packages.source import PackageSourceConfig
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.revisions import PluginRevisionStore
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


def _discovery_result(request: _ResourceDiscoveryRequest) -> _ResourceDiscoveryResult:
    project_root = request.project_resource_root or request.cwd
    return _ResourceDiscoveryResult(
        snapshot=ResourceSnapshot(cwd=request.cwd),
        catalog_input_receipt=ResourceCatalogInputReceipt(
            cwd=request.cwd,
            project_resource_root=project_root,
            project_context_roots=(),
            package_mounts=request.package_mounts,
            package_resource_candidates=(),
            package_diagnostic_codes=(),
            user_resource_roots=request.user_resource_roots,
            explicit_user_resource_roots=request.explicit_user_roots,
            additional_extension_paths=request.additional_extension_paths,
            additional_skill_paths=request.additional_skill_paths,
            additional_prompt_template_paths=(request.additional_prompt_template_paths),
            additional_theme_paths=request.additional_theme_paths,
            no_extensions=request.no_extensions,
            no_skills=request.no_skills,
            no_prompt_templates=request.no_prompt_templates,
            no_themes=request.no_themes,
            no_context_files=request.no_context_files,
            built_in_resource_packages=request.built_in_resource_packages,
            context_file_names=request.context_file_names,
        ),
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

    def discover(request: _ResourceDiscoveryRequest) -> _ResourceDiscoveryResult:
        captured.append(request)
        return _discovery_result(request)

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

    def discover(request: _ResourceDiscoveryRequest) -> _ResourceDiscoveryResult:
        result = _discovery_result(request)
        return _ResourceDiscoveryResult(
            snapshot=candidate,
            catalog_input_receipt=result.catalog_input_receipt,
        )

    monkeypatch.setattr(loader_module, "_discover_snapshot", discover)

    with pytest.raises(RuntimeError, match="revision changed"):
        loader.discover_resources(tmp_path)

    assert loader.get_resource_snapshot() is previous
    loader.close()
    assert handle.closed is True


def test_resource_loader_transfers_one_exact_catalog_input_receipt(
    tmp_path: Path,
) -> None:
    user_root = tmp_path / "user"
    project_root = tmp_path / "project"
    nested = project_root / "src"
    user_root.mkdir()
    nested.mkdir(parents=True)
    (project_root / "AGENTS.md").write_text("Project", encoding="utf-8")
    loader = ResourceLoader(
        user_resource_roots=(user_root,),
        built_in_resource_packages=("loushang.coding.resources",),
        context_file_names=("AGENTS.md",),
        project_resource_mode="legacy",
    )

    loader.discover_resources(nested)
    receipt = loader._take_initial_resource_catalog_input_receipt()

    assert receipt.cwd == nested
    assert receipt.project_resource_root == project_root
    assert receipt.project_context_roots[-1] == nested
    assert project_root in receipt.project_context_roots
    assert receipt.user_resource_roots == (user_root.resolve(),)
    assert receipt.built_in_resource_packages == ("loushang.coding.resources",)
    assert receipt.context_file_names == ("AGENTS.md",)
    assert receipt.package_roots == ()
    assert receipt.has_temporary_inputs is False
    assert receipt.has_resource_kind_switches is False
    with pytest.raises(RuntimeError, match="No unclaimed"):
        loader._take_initial_resource_catalog_input_receipt()

    loader.discover_resources(nested)
    loader.set_workspace_root(project_root)
    with pytest.raises(RuntimeError, match="No unclaimed"):
        loader._take_initial_resource_catalog_input_receipt()


def test_resource_loader_receipt_carries_verified_package_candidate_facts(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    skill = source / "skills" / "review" / "SKILL.md"
    project = tmp_path / "project"
    skill.parent.mkdir(parents=True)
    project.mkdir()
    skill.write_text(
        "---\nname: review\ndescription: Package review\n---\nReview.\n",
        encoding="utf-8",
    )
    (source / "plugin.json").write_text(
        json.dumps({"name": "review-package", "version": "1"}),
        encoding="utf-8",
    )
    published = PluginRevisionStore(tmp_path / "revisions").publish(
        PluginManifestParser().parse(source)
    )
    handle = published.revision_handle
    mount = PackageResourceMount(
        root=handle.root,
        content_digest=handle.content_digest,
        revision_handle=handle,
    )
    loader = ResourceLoader()
    loader.set_package_mounts((mount,))
    try:
        loader.discover_resources(project)
        receipt = loader._take_initial_resource_catalog_input_receipt()

        assert receipt.package_mounts == (mount,)
        assert receipt.package_roots == (handle.root,)
        assert receipt.package_diagnostic_codes == ()
        [candidate] = receipt.package_resource_candidates
        assert candidate.resource_kind == "skill"
        assert candidate.source_path == handle.root / "skills/review/SKILL.md"
        assert candidate.source_root_order == 0
        assert candidate.package_content_digest == handle.content_digest
    finally:
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
