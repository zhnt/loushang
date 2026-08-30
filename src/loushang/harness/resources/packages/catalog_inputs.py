"""Public package evidence passed into Resource Catalog ingestion."""

from __future__ import annotations

from dataclasses import dataclass

from loushang.harness.resources.plugins.types import (
    PluginSourceBinding,
    PublishedPluginPackage,
)


@dataclass(frozen=True, slots=True)
class CatalogPluginPackageInput:
    """Published Plugin evidence bound to one ordered discovery mount."""

    package: PublishedPluginPackage
    binding: PluginSourceBinding
    source_root_order: int

    def __post_init__(self) -> None:
        if not isinstance(self.package, PublishedPluginPackage):
            raise TypeError("Catalog Plugin package input requires a published package")
        if not isinstance(self.binding, PluginSourceBinding):
            raise TypeError("Catalog Plugin package input requires a source binding")
        if self.binding.plugin_id != self.package.manifest.name:
            raise ValueError("Catalog Plugin package binding does not match its package")
        if (
            self.binding.content_digest != self.package.content_digest
            or self.binding.manifest_digest != self.package.manifest_digest
            or self.binding.dependency_lock != self.package.dependency_lock
        ):
            raise ValueError("Catalog Plugin package binding lineage is invalid")
        if (
            isinstance(self.source_root_order, bool)
            or not isinstance(self.source_root_order, int)
            or self.source_root_order < 0
        ):
            raise ValueError("Catalog Plugin package root order is invalid")


__all__ = ["CatalogPluginPackageInput"]
