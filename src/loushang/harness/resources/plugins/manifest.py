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
        unresolved_root = Path(root).expanduser()
        try:
            resolved_root = unresolved_root.resolve()
        except (OSError, RuntimeError) as exc:
            raise PluginManifestError(
                f"Plugin source path could not be resolved: {unresolved_root}: {exc}",
                code="invalid_plugin_manifest",
                path=unresolved_root,
            ) from exc
        if not resolved_root.is_dir():
            raise FileNotFoundError(
                f"Plugin source is not a directory: {resolved_root}"
            )

        resolved_source = _resolved_source(resolved_root, source)
        root_identity = _path_identity(resolved_root)
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
                root_identity=root_identity,
                package_root_identity=root_identity,
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

        package_root, package_root_relative = _package_root(
            resolved_root,
            resolved_manifest_path,
            payload,
        )
        enabled = _enabled_value(payload, resolved_manifest_path)
        name = _manifest_string(
            payload,
            "name",
            resolved_manifest_path,
            default=resolved_root.name,
        )
        version = _manifest_string(
            payload,
            "version",
            resolved_manifest_path,
            default=None,
        )
        assert name is not None
        manifest = PluginManifest(
            name=name,
            root=resolved_root,
            version=version,
            enabled=enabled,
            package_root=package_root,
            metadata=_canonical_metadata(payload, name=name, version=version),
        )
        return ResolvedPluginPackage(
            root=resolved_root,
            package_root=package_root,
            manifest=manifest,
            source=resolved_source,
            manifest_path=resolved_manifest_path,
            manifest_digest=sha256(encoded).hexdigest(),
            package_root_relative=package_root_relative,
            root_identity=root_identity,
            package_root_identity=_path_identity(package_root),
        )

    def revalidate(self, package: ResolvedPluginPackage) -> ResolvedPluginPackage:
        """Fail closed when a resolved local package changed before mounting."""

        if package.root_identity is None:
            _raise_changed(package.root, "Plugin package has no root identity.")
        if _path_identity(package.root) != package.root_identity:
            _raise_changed(package.root, "Plugin package root identity changed.")

        expected_manifest_path = package.root / "plugin.json"
        if package.manifest_digest is None:
            if package.manifest_path is not None:
                _raise_changed(
                    expected_manifest_path,
                    "Plugin manifest identity is incomplete.",
                )
            if expected_manifest_path.exists() or expected_manifest_path.is_symlink():
                _raise_changed(
                    expected_manifest_path,
                    "Plugin manifest appeared after package resolution.",
                )
        else:
            if package.manifest_path != expected_manifest_path:
                _raise_changed(
                    expected_manifest_path,
                    "Plugin manifest path changed after package resolution.",
                )
            if expected_manifest_path.is_symlink() or not expected_manifest_path.is_file():
                _raise_changed(
                    expected_manifest_path,
                    "Plugin manifest disappeared or became a symbolic link.",
                )
            try:
                encoded = expected_manifest_path.read_bytes()
            except OSError as exc:
                raise PluginManifestError(
                    f"Plugin manifest could not be revalidated: "
                    f"{expected_manifest_path}: {exc}",
                    code="plugin_package_changed",
                    path=expected_manifest_path,
                ) from exc
            if sha256(encoded).hexdigest() != package.manifest_digest:
                _raise_changed(
                    expected_manifest_path,
                    "Plugin manifest content changed after package resolution.",
                )

        candidate = package.root / package.package_root_relative
        try:
            resolved_candidate = candidate.resolve()
        except (OSError, RuntimeError) as exc:
            raise PluginManifestError(
                f"Plugin packageRoot could not be revalidated: {candidate}: {exc}",
                code="plugin_package_changed",
                path=candidate,
            ) from exc
        try:
            resolved_candidate.relative_to(package.root)
        except ValueError:
            _raise_changed(
                candidate,
                "Plugin packageRoot escaped after package resolution.",
            )
        if resolved_candidate != package.package_root:
            _raise_changed(
                candidate,
                "Plugin packageRoot target changed after package resolution.",
            )
        if _path_identity(resolved_candidate) != package.package_root_identity:
            _raise_changed(
                candidate,
                "Plugin packageRoot identity changed after package resolution.",
            )
        return package


def _resolved_source(root: Path, source: PluginSource | None) -> PluginSource:
    if source is None:
        return PluginSource(path=root)
    if source.kind == "local":
        return PluginSource(path=root, enabled=source.enabled)
    return PluginSource(
        path=root,
        url=source.url,
        kind="remote",
        enabled=source.enabled,
    )


def _package_root(
    root: Path,
    manifest_path: Path,
    payload: Mapping[str, object],
) -> tuple[Path, Path]:
    camel_present = "packageRoot" in payload
    snake_present = "package_root" in payload
    if (
        camel_present
        and snake_present
        and payload["packageRoot"] != payload["package_root"]
    ):
        raise PluginManifestError(
            f"Plugin packageRoot aliases must have the same value: {manifest_path}",
            code="invalid_plugin_manifest",
            path=manifest_path,
        )
    value = (
        payload["packageRoot"]
        if camel_present
        else payload.get("package_root", ".")
    )
    if value in (None, ""):
        return root, Path(".")
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
    try:
        resolved = (root / relative).resolve()
    except (OSError, RuntimeError) as exc:
        raise PluginManifestError(
            f"Plugin packageRoot could not be resolved: {manifest_path}: {exc}",
            code="invalid_plugin_manifest",
            path=manifest_path,
        ) from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PluginManifestError(
            f"Plugin packageRoot must stay inside the package root: {manifest_path}",
            code="invalid_plugin_manifest",
            path=manifest_path,
        ) from exc
    return resolved, resolved.relative_to(root)


def _enabled_value(
    payload: Mapping[str, object],
    manifest_path: Path,
) -> bool:
    value = payload.get("enabled", True)
    if not isinstance(value, bool):
        raise PluginManifestError(
            f"Plugin enabled must be a boolean: {manifest_path}",
            code="invalid_plugin_manifest",
            path=manifest_path,
        )
    return value


def _path_identity(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_dev, stat.st_ino


def _raise_changed(path: Path, message: str) -> None:
    raise PluginManifestError(
        f"{message} {path}",
        code="plugin_package_changed",
        path=path,
    )


def _manifest_string(
    payload: Mapping[str, object],
    field: str,
    manifest_path: Path,
    *,
    default: str | None,
) -> str | None:
    if field not in payload:
        return default
    value = payload[field]
    if not isinstance(value, str):
        raise PluginManifestError(
            f"Plugin {field} must be a non-empty string: {manifest_path}",
            code="invalid_plugin_manifest",
            path=manifest_path,
        )
    normalized = value.strip()
    if not normalized:
        raise PluginManifestError(
            f"Plugin {field} must be a non-empty string: {manifest_path}",
            code="invalid_plugin_manifest",
            path=manifest_path,
        )
    return normalized


def _canonical_metadata(
    payload: Mapping[str, object],
    *,
    name: str,
    version: str | None,
) -> Mapping[str, object]:
    normalized = dict(payload)
    if "name" in normalized:
        normalized["name"] = name
    if "version" in normalized:
        normalized["version"] = version
    if "package_root" in normalized:
        alias = normalized.pop("package_root")
        normalized.setdefault("packageRoot", alias)
    return _freeze_mapping(normalized)


def _freeze_mapping(value: Mapping[str, object]) -> Mapping[str, object]:
    return MappingProxyType({key: _freeze_value(item) for key, item in value.items()})


def _freeze_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, list | tuple):
        return tuple(_freeze_value(item) for item in value)
    return value


__all__ = ["PluginManifestError", "PluginManifestParser"]
