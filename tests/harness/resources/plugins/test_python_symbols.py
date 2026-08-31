from __future__ import annotations

import importlib.metadata
import json
import sys
from pathlib import Path

import pytest

from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
    PluginPythonDistributionLock,
    lock_plugin_dependency_closure,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.python_symbols import (
    load_verified_plugin_python_module,
)
from loushang.harness.resources.plugins.revisions import PluginRevisionStore


def test_verified_loader_rejects_mutable_stdlib_shadow_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marker = tmp_path / "shadow-executed"
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    (shadow / "wave.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(shadow))
    monkeypatch.delitem(sys.modules, "wave", raising=False)
    handle = _revision(tmp_path, "import wave\n")
    dependency_lock = lock_plugin_dependency_closure(
        package_content_digest=handle.content_digest,
        installed_distributions=(),
    )

    with pytest.raises(ImportError, match="origin is mutable"):
        load_verified_plugin_python_module(
            revision_handle=handle.revision_handle,
            dependency_lock=dependency_lock,
            relative_path="provider.py",
            module_name="_shadow_test",
            host_api_prefixes=("loushang.harness.capabilities",),
        )

    assert marker.exists() is False


def test_verified_loader_rejects_dynamic_import_facilities(tmp_path: Path) -> None:
    handle = _revision(tmp_path, "import importlib\n")
    dependency_lock = lock_plugin_dependency_closure(
        package_content_digest=handle.content_digest,
        installed_distributions=(),
    )

    with pytest.raises(ImportError, match="Dynamic import facilities"):
        load_verified_plugin_python_module(
            revision_handle=handle.revision_handle,
            dependency_lock=dependency_lock,
            relative_path="provider.py",
            module_name="_dynamic_import_test",
            host_api_prefixes=("loushang.harness.capabilities",),
        )


def test_verified_loader_rejects_locked_distribution_version_drift(
    tmp_path: Path,
) -> None:
    handle = _revision(tmp_path, "VALUE = 1\n")
    installed = importlib.metadata.version("pytest")
    dependency_lock = PluginDependencyClosureLock(
        package_content_digest=handle.content_digest,
        python_distributions=(
            PluginPythonDistributionLock(
                name="pytest",
                version=installed + ".drift",
            ),
        ),
    )

    with pytest.raises(ImportError, match="version drifted"):
        load_verified_plugin_python_module(
            revision_handle=handle.revision_handle,
            dependency_lock=dependency_lock,
            relative_path="provider.py",
            module_name="_version_drift_test",
            host_api_prefixes=("loushang.harness.capabilities",),
        )


def test_verified_loader_accepts_exact_locked_distribution_file_origin(
    tmp_path: Path,
) -> None:
    handle = _revision(tmp_path, "import pytest\nVALUE = pytest.__name__\n")
    dependency_lock = PluginDependencyClosureLock(
        package_content_digest=handle.content_digest,
        python_distributions=(
            PluginPythonDistributionLock(
                name="pytest",
                version=importlib.metadata.version("pytest"),
            ),
        ),
    )

    module = load_verified_plugin_python_module(
        revision_handle=handle.revision_handle,
        dependency_lock=dependency_lock,
        relative_path="provider.py",
        module_name="_exact_distribution_origin_test",
        host_api_prefixes=("loushang.harness.capabilities",),
    )

    assert module.resolve("VALUE") == "pytest"


def test_verified_loader_exact_host_module_does_not_admit_its_package(
    tmp_path: Path,
) -> None:
    exact = _revision(
        tmp_path,
        "from loushang.plugin.provider_runtime import CapabilityBundleValue\n"
        "VALUE = CapabilityBundleValue\n",
    )
    exact_lock = lock_plugin_dependency_closure(
        package_content_digest=exact.content_digest,
        installed_distributions=(),
    )

    module = load_verified_plugin_python_module(
        revision_handle=exact.revision_handle,
        dependency_lock=exact_lock,
        relative_path="provider.py",
        module_name="_exact_host_module_test",
        host_api_prefixes=(),
        host_api_exports={
            "loushang.plugin.provider_runtime": ("CapabilityBundleValue",)
        },
    )

    assert module.resolve("VALUE").__name__ == "CapabilityBundleValue"

    denied_sources = (
        "from loushang.plugin import capability_provider\n",
        "import loushang.plugin.provider_runtime\n",
        "from loushang.plugin.provider_runtime import __dict__\n",
        "from loushang.plugin.provider_runtime import *\n",
        "abi = __import__(\n"
        "    'loushang.plugin.provider_runtime',\n"
        "    fromlist=('CapabilityBundleValue',),\n"
        ")\n"
        "abi.__dict__['__builtins__']['__import__'](\n"
        "    'loushang.harness.capabilities',\n"
        "    fromlist=('RuntimeCapabilityGraphRuntime',),\n"
        ")\n",
    )
    for source in denied_sources:
        sibling = _revision(tmp_path, source)
        sibling_lock = lock_plugin_dependency_closure(
            package_content_digest=sibling.content_digest,
            installed_distributions=(),
        )
        with pytest.raises(ImportError):
            load_verified_plugin_python_module(
                revision_handle=sibling.revision_handle,
                dependency_lock=sibling_lock,
                relative_path="provider.py",
                module_name="_sibling_host_module_test",
                host_api_prefixes=(),
                host_api_exports={
                    "loushang.plugin.provider_runtime": (
                        "CapabilityBundleValue",
                    )
                },
            )


def _revision(tmp_path: Path, source: str):  # type: ignore[no-untyped-def]
    root = tmp_path / ("plugin-" + str(len(tuple(tmp_path.iterdir()))))
    root.mkdir()
    (root / "plugin.json").write_text(
        json.dumps({"name": "verified-loader-sample"}),
        encoding="utf-8",
    )
    (root / "provider.py").write_text(source, encoding="utf-8")
    return PluginRevisionStore(tmp_path / "revisions").publish(
        PluginManifestParser().parse(root)
    )
