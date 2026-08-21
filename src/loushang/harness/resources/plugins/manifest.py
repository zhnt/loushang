from __future__ import annotations

import json
from collections.abc import Mapping
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType

from loushang.harness.resources.plugins.types import (
    PluginManifest,
    PluginSource,
    ResolvedPluginPackage,
)


class PluginManifestError(ValueError):
    """Structured failure emitted by the canonical Plugin manifest parser."""

    def __init__(self, message: str, *, code: str, path: Path) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


class PluginManifestParser:
    """Parse one local ``plugin.json`` into an inert resolved descriptor."""

    def parse(
        self,
        root: str | Path,
        *,
        source: PluginSource | None = None,
    ) -> ResolvedPluginPackage:
        resolved_root = Path(root).expanduser().resolve()
        if not resolved_root.is_dir():
            raise FileNotFoundError(
                f"Plugin source is not a directory: {resolved_root}"
            )

        resolved_source = _resolved_source(resolved_root, source)
        manifest_path = resolved_root / "plugin.json"
        if manifest_path.is_symlink():
            raise PluginManifestError(
                f"Plugin manifest must not be a symbolic link: {manifest_path}",
                code="invalid_plugin_manifest",
                path=manifest_path,
            )
        if not manifest_path.is_file():
            manifest = PluginManifest(
                name=resolved_root.name,
                root=resolved_root,
                package_root=resolved_root,
            )
            return ResolvedPluginPackage(
                root=resolved_root,
                package_root=resolved_root,
                manifest=manifest,
                source=resolved_source,
            )

        resolved_manifest_path = manifest_path.resolve()
        try:
            encoded = resolved_manifest_path.read_bytes()
        except OSError as exc:
            raise PluginManifestError(
                f"Plugin manifest could not be read: {resolved_manifest_path}: {exc}",
                code="unreadable_plugin_manifest",
                path=resolved_manifest_path,
            ) from exc
        try:
            payload = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            detail = exc.msg if isinstance(exc, json.JSONDecodeError) else str(exc)
            raise PluginManifestError(
                f"Invalid plugin manifest JSON: {resolved_manifest_path}: {detail}",
                code="invalid_plugin_manifest",
                path=resolved_manifest_path,
            ) from exc
        if not isinstance(payload, dict):
            raise PluginManifestError(
                f"Plugin manifest must be a JSON object: {resolved_manifest_path}",
                code="invalid_plugin_manifest",
                path=resolved_manifest_path,
            )

        package_root = _package_root(
            resolved_root,
            resolved_manifest_path,
            payload,
        )
        manifest = PluginManifest(
            name=_string_value(payload.get("name")) or resolved_root.name,
            root=resolved_root,
            version=_string_value(payload.get("version")),
            enabled=bool(payload.get("enabled", True)),
            package_root=package_root,
            metadata=_freeze_mapping(payload),
        )
        return ResolvedPluginPackage(
            root=resolved_root,
            package_root=package_root,
            manifest=manifest,
            source=resolved_source,
            manifest_path=resolved_manifest_path,
            manifest_digest=sha256(encoded).hexdigest(),
        )


def _resolved_source(root: Path, source: PluginSource | None) -> PluginSource:
    if source is None:
        return PluginSource(path=root)
    if source.kind == "local":
        return PluginSource(path=root, enabled=source.enabled)
    return source


def _package_root(
    root: Path,
    manifest_path: Path,
    payload: Mapping[str, object],
) -> Path:
    value = payload.get("packageRoot", payload.get("package_root", "."))
    if value in (None, ""):
        return root
    if not isinstance(value, str):
        raise PluginManifestError(
            f"Plugin packageRoot must be a string: {manifest_path}",
            code="invalid_plugin_manifest",
            path=manifest_path,
        )
    relative = Path(value).expanduser()
    if relative.is_absolute():
        raise PluginManifestError(
            f"Plugin packageRoot must be relative: {manifest_path}",
            code="invalid_plugin_manifest",
            path=manifest_path,
        )
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PluginManifestError(
            f"Plugin packageRoot must stay inside the package root: {manifest_path}",
            code="invalid_plugin_manifest",
            path=manifest_path,
        ) from exc
    return resolved


def _string_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    return value


__all__ = ["PluginManifestError", "PluginManifestParser"]
