"""Coding Product binding for transport-neutral Plugin management CLI ports."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loushang.coding._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    build_coding_plugin_management_application,
    project_coding_plugin_enablement_compatibility,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.product_plan import CODING_PRODUCT_ID
from loushang.harness.cli.plugin_management import PluginManagementCliBinding
from loushang.harness.plugin_management import (
    PluginInstallationKeyV1,
    PluginManagementSourceRecordV1,
    PluginManagementSourceSnapshotV1,
)
from loushang.harness.resources.plugins import (
    PluginResolutionAuthority,
    PluginSource,
    is_remote_plugin_source,
    remote_plugin_name,
)
from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec

_CLI_ACTOR_ID = "coding:cli"
_CLI_POLICY_REVISION = "coding-plugin-management-cli-v1"


class CodingPluginManagementCliError(RuntimeError):
    """Stable Product failure while projecting configured Plugin Sources."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class CodingConfiguredPluginSourceProjection:
    settings_manager: object | None
    scope_id: str
    workspace_root: Path

    def snapshot(self) -> PluginManagementSourceSnapshotV1:
        raw_sources = self._configured_sources()
        authority = PluginResolutionAuthority()
        records: dict[PluginInstallationKeyV1, PluginManagementSourceRecordV1] = {}
        for raw_source in raw_sources:
            remote = is_remote_plugin_source(raw_source)
            local_path: Path | None = None
            if remote:
                source = PluginSource(url=raw_source, kind="remote")
            else:
                local_path = self._local_path(raw_source)
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
                availability = (
                    "available" if not inspection.diagnostics else "unavailable"
                )
                version = plugin.manifest.version
                manifest_default = plugin.manifest.enabled
            key = PluginInstallationKeyV1(
                product_id=CODING_PRODUCT_ID,
                installation_scope="workspace",
                scope_id=self.scope_id,
                plugin_id=plugin_id,
            )
            if key in records:
                raise CodingPluginManagementCliError(
                    f"multiple configured Plugin Sources resolve to {plugin_id}",
                    code="coding_plugin_source_identity_conflict",
                )
            if remote:
                location = raw_source
            else:
                assert local_path is not None
                location = str(local_path)
            records[key] = PluginManagementSourceRecordV1(
                installation_key=key,
                source_identity=(
                    f"remote:{raw_source}" if remote else f"local:{location}"
                ),
                source_kind="remote" if remote else "local",
                availability=availability,
                source_location=location,
                plugin_version=version,
                manifest_enabled_default=manifest_default,
            )
        ordered = tuple(
            sorted(records.values(), key=lambda item: item.installation_key)
        )
        revision = hashlib.sha256(
            StrictPluginJsonCodec.encode(
                {
                    "records": [item.to_dict() for item in ordered],
                    "sources": list(raw_sources),
                }
            )
        ).hexdigest()
        return PluginManagementSourceSnapshotV1(
            owner_revision=f"coding-settings:{revision}",
            records=ordered,
        )

    def _configured_sources(self) -> tuple[str, ...]:
        get_settings = getattr(self.settings_manager, "get_settings", None)
        if not callable(get_settings):
            return ()
        settings = get_settings()
        raw_sources = getattr(settings, "plugin_sources", ())
        if not isinstance(raw_sources, (list, tuple)) or any(
            not isinstance(item, str) or not item for item in raw_sources
        ):
            raise CodingPluginManagementCliError(
                "configured Plugin Sources are invalid",
                code="coding_plugin_sources_invalid",
            )
        return tuple(sorted(set(raw_sources)))

    def _local_path(self, raw_source: str) -> Path:
        path = Path(raw_source).expanduser()
        if not path.is_absolute():
            path = self.workspace_root / path
        return path.resolve(strict=False)


def build_coding_plugin_management_cli_binding(
    cwd: str | Path,
    settings_manager: object | None,
) -> PluginManagementCliBinding:
    layout = resolve_coding_plugin_lifecycle_state_layout(cwd)
    source = CodingConfiguredPluginSourceProjection(
        settings_manager=settings_manager,
        scope_id=layout.scope_id,
        workspace_root=Path(cwd).resolve(),
    )
    ports = build_coding_plugin_management_application(layout, source=source)
    return PluginManagementCliBinding(
        ports=ports,
        product_id=CODING_PRODUCT_ID,
        installation_scope="workspace",
        scope_id=layout.scope_id,
        actor_id=_CLI_ACTOR_ID,
        policy_revision=_CLI_POLICY_REVISION,
        publish_compatibility_projection=_compatibility_publisher(
            layout=layout,
            settings_manager=settings_manager,
        ),
    )


def _compatibility_publisher(
    *,
    layout: CodingPluginLifecycleStateLayout,
    settings_manager: object | None,
) -> Callable[[], None] | None:
    get_settings = getattr(settings_manager, "get_settings", None)
    set_disabled_plugins = getattr(settings_manager, "set_disabled_plugins", None)
    if not callable(get_settings) or not callable(set_disabled_plugins):
        return None

    def publish() -> None:
        projection, migrated = project_coding_plugin_enablement_compatibility(layout)
        current = getattr(get_settings(), "disabled_plugins", ())
        retained = {
            item
            for item in current
            if isinstance(item, str) and item and item not in migrated
        }
        disabled = tuple(sorted(retained | set(projection.disabled_plugin_ids)))
        if disabled != tuple(current):
            set_disabled_plugins(disabled, scope="project")

    return publish


__all__ = [
    "CodingConfiguredPluginSourceProjection",
    "CodingPluginManagementCliError",
    "build_coding_plugin_management_cli_binding",
]
