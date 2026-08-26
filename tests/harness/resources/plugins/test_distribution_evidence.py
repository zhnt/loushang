from __future__ import annotations

import importlib.metadata
import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

import loushang
from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
    PluginPythonDistributionLock,
)
from loushang.harness.resources.plugins.distribution_evidence import (
    InstalledPythonDistributionEvidenceError,
    InstalledPythonDistributionEvidenceResolver,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.python_symbols import (
    load_verified_plugin_python_module,
)
from loushang.harness.resources.plugins.revisions import PluginRevisionStore


@dataclass(frozen=True)
class _FakeDistribution:
    root: Path
    name: str
    version: str
    files: tuple[Path, ...] | None
    direct_url: str | None = None

    @property
    def metadata(self) -> dict[str, str]:
        return {"Name": self.name}

    def locate_file(self, path: object) -> Path:
        return self.root / Path(str(path))

    def read_text(self, filename: str) -> str | None:
        if filename == "direct_url.json":
            return self.direct_url
        return None


def test_record_evidence_locks_exact_identity_and_recorded_origins(
    tmp_path: Path,
) -> None:
    install_root = tmp_path / "site-packages"
    package_root = install_root / "sample_pkg"
    package_root.mkdir(parents=True)
    init_path = package_root / "__init__.py"
    module_path = package_root / "module.py"
    init_path.write_text("", encoding="utf-8")
    module_path.write_text("VALUE = 1\n", encoding="utf-8")
    distribution = _FakeDistribution(
        root=install_root,
        name="Sample_Dist",
        version="1.2.3",
        files=(Path("sample_pkg/__init__.py"), Path("sample_pkg/module.py")),
    )
    resolver = InstalledPythonDistributionEvidenceResolver(
        distributions_reader=lambda name: (distribution,),
        packages_distributions_reader=lambda: {"sample_pkg": ["sample-dist"]},
    )

    evidence = resolver.resolve(
        PluginPythonDistributionLock(name="sample-dist", version="1.2.3")
    )

    assert evidence.distribution == PluginPythonDistributionLock(
        name="sample-dist",
        version="1.2.3",
    )
    assert evidence.install_mode == "record"
    assert evidence.top_level_packages == ("sample_pkg",)
    evidence.require_import_origin("sample_pkg.module", (module_path,))
    assert evidence.contains_distribution_path(init_path)
    assert evidence.contains_distribution_path(package_root) is False

    unrecorded = package_root / "injected.py"
    unrecorded.write_text("", encoding="utf-8")
    with pytest.raises(
        InstalledPythonDistributionEvidenceError,
        match="outside its lock",
    ) as captured:
        evidence.require_import_origin("sample_pkg.injected", (unrecorded,))
    assert captured.value.code == "plugin_dependency_import_origin_outside_evidence"


def test_current_loushang_install_has_verifiable_origin_evidence() -> None:
    lock = PluginPythonDistributionLock(
        name="loushang",
        version=importlib.metadata.version("loushang"),
    )

    evidence = InstalledPythonDistributionEvidenceResolver(
        allow_editable=True,
    ).resolve(lock, required_paths=(Path(loushang.__file__),))

    assert evidence.install_mode in {"record", "editable"}
    assert loushang.__file__ is not None
    evidence.require_import_origin("loushang", (Path(loushang.__file__),))


def test_verified_loader_selects_current_loushang_origin_from_same_name_candidates(
    tmp_path: Path,
) -> None:
    revision = _revision(
        tmp_path,
        "import loushang\nVALUE = loushang.__name__\n",
    )
    dependency_lock = PluginDependencyClosureLock(
        package_content_digest=revision.content_digest,
        python_distributions=(
            PluginPythonDistributionLock(
                name="loushang",
                version=importlib.metadata.version("loushang"),
            ),
        ),
    )

    module = load_verified_plugin_python_module(
        revision_handle=revision.revision_handle,
        dependency_lock=dependency_lock,
        relative_path="provider.py",
        module_name="_current_loushang_distribution_evidence_test",
        host_api_prefixes=("loushang.harness.capabilities",),
        distribution_evidence_resolver=InstalledPythonDistributionEvidenceResolver(
            allow_editable=True,
        ),
    )

    assert module.resolve("VALUE") == "loushang"


def test_resolver_requires_source_evidence_for_same_version_installations(
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_path = first_root / "sample_pkg" / "__init__.py"
    second_path = second_root / "sample_pkg" / "__init__.py"
    first_path.parent.mkdir(parents=True)
    second_path.parent.mkdir(parents=True)
    first_path.write_text("", encoding="utf-8")
    second_path.write_text("", encoding="utf-8")
    candidates = (
        _FakeDistribution(
            root=first_root,
            name="sample-dist",
            version="1.0.0",
            files=(Path("sample_pkg/__init__.py"),),
        ),
        _FakeDistribution(
            root=second_root,
            name="sample-dist",
            version="1.0.0",
            files=(Path("sample_pkg/__init__.py"),),
        ),
    )
    resolver = InstalledPythonDistributionEvidenceResolver(
        distributions_reader=lambda name: candidates,
        packages_distributions_reader=lambda: {"sample_pkg": ["sample-dist"]},
    )
    lock = PluginPythonDistributionLock(name="sample-dist", version="1.0.0")

    with pytest.raises(
        InstalledPythonDistributionEvidenceError,
        match="installation is ambiguous",
    ) as captured:
        resolver.resolve(lock)
    assert captured.value.code == "plugin_dependency_distribution_ambiguous"

    selected = resolver.resolve(lock, required_paths=(first_path,))
    assert selected.contains_distribution_path(first_path)
    assert selected.contains_distribution_path(second_path) is False


def test_resolver_rejects_locked_distribution_version_drift(tmp_path: Path) -> None:
    distribution = _FakeDistribution(
        root=tmp_path,
        name="sample-dist",
        version="2.0.0",
        files=(),
    )
    resolver = InstalledPythonDistributionEvidenceResolver(
        distributions_reader=lambda name: (distribution,),
        packages_distributions_reader=lambda: {},
    )

    with pytest.raises(
        InstalledPythonDistributionEvidenceError,
        match="version drifted",
    ) as captured:
        resolver.resolve(
            PluginPythonDistributionLock(name="sample-dist", version="1.0.0")
        )

    assert captured.value.code == "plugin_dependency_distribution_version_drift"


def test_editable_evidence_requires_explicit_policy_and_local_pep610_root(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    package_root = project_root / "src" / "sample_pkg"
    package_root.mkdir(parents=True)
    init_path = package_root / "__init__.py"
    init_path.write_text("", encoding="utf-8")
    distribution = _FakeDistribution(
        root=tmp_path / "site-packages",
        name="sample-dist",
        version="1.0.0",
        files=(Path("__editable__.sample-dist.pth"),),
        direct_url=json.dumps(
            {
                "dir_info": {"editable": True},
                "url": project_root.as_uri(),
            }
        ),
    )
    package_spec = importlib.util.spec_from_file_location(
        "sample_pkg",
        init_path,
        submodule_search_locations=[str(package_root)],
    )

    denied = InstalledPythonDistributionEvidenceResolver(
        distributions_reader=lambda name: (distribution,),
        packages_distributions_reader=lambda: {"sample_pkg": ["sample-dist"]},
        module_spec_reader=lambda name: package_spec,
    )
    with pytest.raises(
        InstalledPythonDistributionEvidenceError,
        match="editable install is not permitted",
    ) as captured:
        denied.resolve("sample-dist")
    assert captured.value.code == "plugin_dependency_editable_disallowed"

    allowed = InstalledPythonDistributionEvidenceResolver(
        allow_editable=True,
        distributions_reader=lambda name: (distribution,),
        packages_distributions_reader=lambda: {"sample_pkg": ["sample-dist"]},
        module_spec_reader=lambda name: package_spec,
    )
    evidence = allowed.resolve("sample-dist", expected_version="1.0.0")

    assert evidence.install_mode == "editable"
    assert evidence.editable_project_root == project_root
    evidence.require_import_origin("sample_pkg", (init_path, package_root))
    assert evidence.contains_distribution_path(package_root)


def test_editable_evidence_rejects_remote_direct_url(tmp_path: Path) -> None:
    distribution = _FakeDistribution(
        root=tmp_path,
        name="sample-dist",
        version="1.0.0",
        files=(Path("__editable__.sample-dist.pth"),),
        direct_url=json.dumps(
            {
                "dir_info": {"editable": True},
                "url": "https://example.invalid/sample-dist",
            }
        ),
    )
    resolver = InstalledPythonDistributionEvidenceResolver(
        allow_editable=True,
        distributions_reader=lambda name: (distribution,),
        packages_distributions_reader=lambda: {},
    )

    with pytest.raises(
        InstalledPythonDistributionEvidenceError,
        match="editable metadata is invalid",
    ) as captured:
        resolver.resolve("sample-dist")

    assert captured.value.code == "plugin_dependency_editable_metadata_invalid"


def test_editable_evidence_rejects_duplicate_metadata_fields(tmp_path: Path) -> None:
    distribution = _FakeDistribution(
        root=tmp_path,
        name="sample-dist",
        version="1.0.0",
        files=(Path("__editable__.sample-dist.pth"),),
        direct_url=(
            '{"dir_info":{"editable":true},'
            '"url":"file:///first","url":"file:///second"}'
        ),
    )
    resolver = InstalledPythonDistributionEvidenceResolver(
        allow_editable=True,
        distributions_reader=lambda name: (distribution,),
        packages_distributions_reader=lambda: {},
    )

    with pytest.raises(
        InstalledPythonDistributionEvidenceError,
        match="editable metadata is invalid",
    ) as captured:
        resolver.resolve("sample-dist")

    assert captured.value.code == "plugin_dependency_editable_metadata_invalid"


def test_verified_loader_uses_editable_distribution_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    package_root = project_root / "src" / "sample_pkg"
    package_root.mkdir(parents=True)
    (package_root / "__init__.py").write_text("VALUE = 7\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(project_root / "src"))
    distribution = _FakeDistribution(
        root=tmp_path / "site-packages",
        name="sample-dist",
        version="1.0.0",
        files=(Path("__editable__.sample-dist.pth"),),
        direct_url=json.dumps(
            {
                "dir_info": {"editable": True},
                "url": project_root.as_uri(),
            }
        ),
    )
    resolver = InstalledPythonDistributionEvidenceResolver(
        allow_editable=True,
        distributions_reader=lambda name: (distribution,),
        packages_distributions_reader=lambda: {"sample_pkg": ["sample-dist"]},
    )
    revision = _revision(
        tmp_path,
        "import sample_pkg\nVALUE = sample_pkg.VALUE\n",
    )
    dependency_lock = PluginDependencyClosureLock(
        package_content_digest=revision.content_digest,
        python_distributions=(
            PluginPythonDistributionLock(name="sample-dist", version="1.0.0"),
        ),
    )

    module = load_verified_plugin_python_module(
        revision_handle=revision.revision_handle,
        dependency_lock=dependency_lock,
        relative_path="provider.py",
        module_name="_editable_distribution_evidence_test",
        host_api_prefixes=("loushang.harness.capabilities",),
        distribution_evidence_resolver=resolver,
    )

    assert module.resolve("VALUE") == 7


def _revision(tmp_path: Path, source: str):  # type: ignore[no-untyped-def]
    root = tmp_path / ("plugin-evidence-" + str(len(tuple(tmp_path.iterdir()))))
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"name": "distribution-evidence-sample"}),
        encoding="utf-8",
    )
    (root / "provider.py").write_text(source, encoding="utf-8")
    return PluginRevisionStore(tmp_path / "revisions").publish(
        PluginManifestParser().parse(root)
    )
