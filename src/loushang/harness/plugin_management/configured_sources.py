"""Product configured Plugin Sources projected into the management read model."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping
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


def resolve_configured_plugin_local_path(
    source: str,
    cwd: str | Path,
    *,
    settings_manager: object | None = None,
) -> Path:
    """Resolve local input against its declaring settings layer or the workspace."""
    path = Path(source).expanduser()
    if path.is_absolute():
        return path.resolve()
    base = None
    if settings_manager is not None:
        # Session-relative paths are anchored at the workspace. Project and
        # global paths use the root of the settings file that declared them.
        for getter_name, base_name in (
            ("get_session_settings", None),
            ("get_project_settings", "project_base_dir"),
            ("get_global_settings", "global_base_dir"),
        ):
            getter = getattr(settings_manager, getter_name, None)
            patch = getter() if callable(getter) else None
            if not isinstance(patch, Mapping):
                continue
            values = patch.get("plugin_sources")
            if not isinstance(values, list | tuple) or source not in values:
                continue
            root = getattr(settings_manager, base_name, None) if base_name is not None else None
            if root is not None:
                base = Path(root).expanduser().resolve()
            break
    return ((base or Path(cwd)) / path).expanduser().resolve()


def configured_plugin_strings(
    raw: object,
    *,
    invalid: Callable[[], Exception],
    trim: bool = False,
) -> tuple[str, ...]:
    """Validate a settings list with the caller's whitespace contract."""
    if not isinstance(raw, (list, tuple)):
        raise invalid()
    result: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise invalid()
        value = item.strip() if trim else item
        if not value:
            raise invalid()
        result.append(value)
    return tuple(result)


def read_configured_plugin_selection(
    settings_manager: object | None,
    *,
    cwd: str | Path,
    invalid: Callable[[str], Exception],
) -> tuple[tuple[str, ...], frozenset[str]]:
    """Resolve ordered source input and disabled ids from one settings snapshot."""
    get_settings = getattr(settings_manager, "get_settings", None)
    if not callable(get_settings):
        return (), frozenset()
    settings = get_settings()
    raw_sources = getattr(settings, "plugin_sources", ())
    raw_disabled = getattr(settings, "disabled_plugins", ())
    sources = configured_plugin_strings(
        raw_sources, trim=True, invalid=lambda: invalid("plugin_sources_invalid")
    )
    disabled = configured_plugin_strings(
        raw_disabled, trim=True, invalid=lambda: invalid("disabled_plugins_invalid")
    )
    resolved = dict.fromkeys(
        source
        if is_remote_plugin_source(source)
        else str(
            resolve_configured_plugin_local_path(
                source, cwd, settings_manager=settings_manager
            )
        )
        for source in sources
    )
    return tuple(resolved), frozenset(disabled)


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
            local_path = resolve_configured_plugin_local_path(raw_source, profile.workspace_root)
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
