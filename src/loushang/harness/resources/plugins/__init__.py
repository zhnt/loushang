from loushang.harness.resources.plugins.lifecycle import (
    is_remote_plugin_source,
    remote_plugin_name,
)
from loushang.harness.resources.plugins.manager import PluginManager
from loushang.harness.resources.plugins.registry import PluginRegistry
from loushang.harness.resources.plugins.resolver import PluginResolver
from loushang.harness.resources.plugins.types import (
    InstalledPlugin,
    PluginManifest,
    PluginResolvedResources,
    PluginSource,
)


def project_installed_plugin(plugin: object) -> dict[str, object]:
    """Project plugin identity and activation state for resource listings."""

    manifest = _safe_plugin_getattr(plugin, "manifest", None)
    source = _safe_plugin_getattr(plugin, "source", None)
    source_kind = _safe_plugin_getattr(source, "kind", "local")
    source_value = (
        _safe_plugin_getattr(source, "url", None)
        if source_kind == "remote"
        else _safe_plugin_getattr(source, "path", "")
    )
    return {
        "name": _safe_plugin_string(_safe_plugin_getattr(manifest, "name", "")),
        "version": _safe_plugin_string(
            _safe_plugin_getattr(manifest, "version", "")
        ),
        "path": "" if source_kind == "remote" else _safe_plugin_string(source_value),
        "source": _safe_plugin_string(source_value),
        "kind": source_kind if isinstance(source_kind, str) else "local",
        "enabled": bool(_safe_plugin_getattr(plugin, "enabled", False)),
    }


def _safe_plugin_getattr(target: object, name: str, default: object) -> object:
    try:
        return getattr(target, name)
    except Exception:
        return default


def _safe_plugin_string(value: object) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        try:
            return repr(value)
        except Exception:
            return ""

__all__ = [
    "InstalledPlugin",
    "PluginManager",
    "PluginManifest",
    "PluginRegistry",
    "PluginResolvedResources",
    "PluginResolver",
    "PluginSource",
    "is_remote_plugin_source",
    "project_installed_plugin",
    "remote_plugin_name",
]
