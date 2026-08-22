from __future__ import annotations

from pathlib import Path
from typing import Protocol

import loushang.harness.resources.plugins as public_plugins
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
)
from loushang.harness.resources.plugins.types import (
    PluginSourceBinding,
    PublishedPluginPackage,
)


class _PublishedSyntheticPlugin(Protocol):
    package: PublishedPluginPackage
    binding: PluginSourceBinding
    contribution: PluginContributionReservation
    import_marker: Path


def test_published_synthetic_plugin_is_revision_locked_but_inert(
    published_synthetic_plugin: _PublishedSyntheticPlugin,
) -> None:
    fixture = published_synthetic_plugin

    assert isinstance(fixture.package, PublishedPluginPackage)
    assert fixture.package.revision_handle.verify() is None
    assert fixture.binding.plugin_id == fixture.package.manifest.name
    assert fixture.binding.content_digest == fixture.package.content_digest
    assert fixture.contribution.entrypoint == "provider.py:declare"
    assert fixture.import_marker.exists() is False
    assert "PluginDefinitionEvaluator" not in public_plugins.__all__
    assert not hasattr(public_plugins, "PluginDefinitionEvaluator")
