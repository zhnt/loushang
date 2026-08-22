from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.plugins.authority import (
    PluginResolutionAuthority,
    PluginRuntimeResolution,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
)
from loushang.harness.resources.plugins.types import (
    PluginSource,
    PluginSourceBinding,
    PublishedPluginPackage,
)


@dataclass(frozen=True, slots=True)
class PublishedSyntheticPlugin:
    """Published executable-shaped Plugin fixture with no evaluation path."""

    runtime: PluginRuntimeResolution
    package: PublishedPluginPackage
    binding: PluginSourceBinding
    contribution: PluginContributionReservation
    import_marker: Path


@pytest.fixture
def published_synthetic_plugin(tmp_path: Path) -> Iterator[PublishedSyntheticPlugin]:
    source_root = tmp_path / "source" / "synthetic-provider"
    source_root.mkdir(parents=True)
    import_marker = tmp_path / "entrypoint-imported.txt"
    (source_root / "provider.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(import_marker)!r}).write_text('imported', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (source_root / "plugin.json").write_text(
        json.dumps(
            {
                "name": "synthetic-provider",
                "version": "1",
                "contributionIndex": {
                    "version": 1,
                    "items": [
                        {
                            "id": "synthetic-provider",
                            "kind": "capability_provider",
                            "owner": "synthetic.capability",
                            "entrypoint": "provider.py:declare",
                            "executionModel": "in_process",
                            "requestedAuthorities": [],
                            "configuration": {},
                            "required": True,
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=source_root))
    materializer = PackageMaterializer(
        install_root=tmp_path / "installed",
        plugin_revision_root=tmp_path / "revisions",
    )
    runtime = authority.publish_runtime(
        (inspection,),
        binding_store=materializer,
    )
    [package] = runtime.packages
    [binding] = runtime.bindings
    [contribution] = package.contribution_index.items
    fixture = PublishedSyntheticPlugin(
        runtime=runtime,
        package=package,
        binding=binding,
        contribution=contribution,
        import_marker=import_marker,
    )
    assert import_marker.exists() is False
    try:
        yield fixture
    finally:
        runtime.close()
