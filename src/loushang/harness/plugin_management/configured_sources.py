"""Product configured Plugin Sources projected into the management read model."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.harness.plugin_management.application import (
    PluginManagementSourceRecordV1,
    PluginManagementSourceSnapshotV1,
)
from loushang.harness.plugin_management.records import PluginInstallationKeyV1
from loushang.harness.resources.plugins import (
    PluginResolutionAuthority,
    PluginSource,
    is_remote_plugin_source,
    remote_plugin_name,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec


class ConfiguredPluginSourceIdentityConflict(ValueError):
    def __init__(self, plugin_id: str) -> None:
        super().__init__(f"multiple configured Plugin Sources resolve to {plugin_id}")
        self.plugin_id = plugin_id


@dataclass(frozen=True, slots=True)
class ConfiguredPluginSourceProfile:
    """The Product supplied identity, root and current configured sources."""

    product_id: str
    installation_scope: Literal["process", "tenant", "workspace"]
    scope_id: str
    workspace_root: Path
    source_strings: tuple[str, ...]
    owner_revision_namespace: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.product_id, "Product id"),
            (self.scope_id, "scope id"),
            (self.owner_revision_namespace, "Configured Source revision namespace"),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty")
        if self.installation_scope not in {"process", "tenant", "workspace"}:
            raise ValueError("Unsupported Plugin Installation scope")
        if (
            not isinstance(self.workspace_root, Path)
            or not self.workspace_root.is_absolute()
        ):
            raise ValueError("Configured Source workspace root must be absolute")
        if not isinstance(self.source_strings, tuple) or any(
            not isinstance(value, str) or not value for value in self.source_strings
        ):
            raise ValueError("Configured Plugin Sources must be non-empty strings")


def project_configured_plugin_sources(
    profile: ConfiguredPluginSourceProfile,
) -> PluginManagementSourceSnapshotV1:
    """Inspect configured Sources without publishing or modifying owner state."""

    raw_sources = tuple(sorted(set(profile.source_strings)))
    authority = PluginResolutionAuthority()
    records: dict[PluginInstallationKeyV1, PluginManagementSourceRecordV1] = {}
    for raw_source in raw_sources:
        remote = is_remote_plugin_source(raw_source)
        local_path: Path | None = None
        if remote:
            source = PluginSource(url=raw_source, kind="remote")
        else:
            local_path = Path(raw_source).expanduser()
            if not local_path.is_absolute():
                local_path = profile.workspace_root / local_path
            local_path = local_path.resolve(strict=False)
            source = PluginSource(path=local_path)
        inspection = authority.inspect(source)
        plugin = inspection.plugin
        if plugin is None:
            if remote:
                plugin_id = remote_plugin_name(raw_source)
            else:
                assert local_path is not None
                plugin_id = local_path.name
            availability: Literal["available", "unavailable"] = "unavailable"
            version = None
            manifest_default = None
        else:
            plugin_id = plugin.manifest.name
            availability = "available" if not inspection.diagnostics else "unavailable"
            version = plugin.manifest.version
            manifest_default = plugin.manifest.enabled
        key = PluginInstallationKeyV1(
            product_id=profile.product_id,
            installation_scope=profile.installation_scope,
            scope_id=profile.scope_id,
            plugin_id=plugin_id,
        )
        if key in records:
            raise ConfiguredPluginSourceIdentityConflict(plugin_id)
        if remote:
            location = raw_source
        else:
            assert local_path is not None
            location = str(local_path)
        records[key] = PluginManagementSourceRecordV1(
            installation_key=key,
            source_identity=(f"remote:{raw_source}" if remote else f"local:{location}"),
            source_kind="remote" if remote else "local",
            availability=availability,
            source_location=location,
            plugin_version=version,
            manifest_enabled_default=manifest_default,
        )
    ordered = tuple(sorted(records.values(), key=lambda item: item.installation_key))
    revision = hashlib.sha256(
        StrictPluginJsonCodec.encode(
            {
                "records": [item.to_dict() for item in ordered],
                "sources": list(raw_sources),
            }
        )
    ).hexdigest()
    return PluginManagementSourceSnapshotV1(
        owner_revision=f"{profile.owner_revision_namespace}:{revision}",
        records=ordered,
    )


__all__ = [
    "ConfiguredPluginSourceIdentityConflict",
    "ConfiguredPluginSourceProfile",
    "project_configured_plugin_sources",
]
