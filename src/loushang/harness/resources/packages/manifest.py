from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loushang.harness.resources.plugins.authority import (
    PluginResolutionAuthority,
    PluginResolutionDiagnostic,
)
from loushang.harness.resources.plugins.types import (
    PluginSource,
    ResolvedPluginPackage,
)


@dataclass(frozen=True)
class PackageManifestInfo:
    root: Path
    package_root: Path
    manifest_path: Path | None = None
    version: str = ""
    diagnostics: tuple[dict[str, object], ...] = ()
    resolved_plugin_package: ResolvedPluginPackage | None = None


def resolve_package_manifest(
    root: str | Path,
    *,
    installed: bool = True,
    resolved_plugin_package: ResolvedPluginPackage | None = None,
    plugin_source: PluginSource | None = None,
) -> PackageManifestInfo:
    package_root = Path(root).expanduser().resolve()
    if not installed:
        return PackageManifestInfo(root=package_root, package_root=package_root)
    if resolved_plugin_package is not None:
        if resolved_plugin_package.root != package_root:
            raise ValueError(
                "Resolved plugin package root does not match package manifest root: "
                f"{resolved_plugin_package.root} != {package_root}"
            )
        return _project_plugin_package(resolved_plugin_package)
    if not package_root.is_dir():
        return PackageManifestInfo(
            root=package_root,
            package_root=package_root,
            diagnostics=(
                {
                    "code": "plugin_source_unresolved",
                    "message": f"Plugin source is not a directory: {package_root}",
                    "path": str(package_root),
                },
            )
            if plugin_source is not None
            else (),
        )
    if plugin_source is not None:
        return _resolve_plugin_manifest(package_root, source=plugin_source)

    manifest_path = _manifest_path(package_root)
    if manifest_path is None:
        return PackageManifestInfo(root=package_root, package_root=package_root)
    if manifest_path.name == "plugin.json":
        return _resolve_plugin_manifest(package_root)

    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return PackageManifestInfo(
            root=package_root,
            package_root=package_root,
            manifest_path=manifest_path,
            diagnostics=(
                {
                    "code": "invalid_package_manifest",
                    "message": f"Invalid package manifest JSON: {exc.msg}",
                    "path": str(manifest_path),
                },
            ),
        )
    except Exception as exc:
        return PackageManifestInfo(
            root=package_root,
            package_root=package_root,
            manifest_path=manifest_path,
            diagnostics=(
                {
                    "code": "unreadable_package_manifest",
                    "message": f"Package manifest could not be read: {exc}",
                    "path": str(manifest_path),
                },
            ),
        )
    if not isinstance(payload, dict):
        return PackageManifestInfo(
            root=package_root,
            package_root=package_root,
            manifest_path=manifest_path,
            diagnostics=(
                {
                    "code": "invalid_package_manifest",
                    "message": "Package manifest must be a JSON object.",
                    "path": str(manifest_path),
                },
            ),
        )

    version = _string_value(payload.get("version")) or ""
    resolved_root, diagnostics = _package_root_from_manifest(
        package_root, manifest_path, payload
    )
    return PackageManifestInfo(
        root=package_root,
        package_root=resolved_root,
        manifest_path=manifest_path,
        version=version,
        diagnostics=diagnostics,
    )


def _project_plugin_package(
    descriptor: ResolvedPluginPackage,
) -> PackageManifestInfo:
    return PackageManifestInfo(
        root=descriptor.root,
        package_root=descriptor.package_root,
        manifest_path=descriptor.manifest_path,
        version=descriptor.manifest.version or "",
        resolved_plugin_package=descriptor,
    )


def _resolve_plugin_manifest(
    root: Path,
    *,
    source: PluginSource | None = None,
) -> PackageManifestInfo:
    inspection = PluginResolutionAuthority().inspect(source or PluginSource(path=root))
    if inspection.package is None:
        diagnostics = project_plugin_diagnostics(inspection.diagnostics)
        return PackageManifestInfo(
            root=root,
            package_root=root,
            manifest_path=(
                inspection.diagnostics[0].path if inspection.diagnostics else None
            ),
            diagnostics=diagnostics,
        )
    return _project_plugin_package(inspection.package)


def _package_plugin_diagnostic_code(code: str) -> str:
    if code == "unreadable_plugin_manifest":
        return "unreadable_package_manifest"
    if code == "invalid_plugin_manifest":
        return "invalid_package_manifest"
    return code


def project_plugin_diagnostics(
    diagnostics: Sequence[PluginResolutionDiagnostic],
) -> tuple[dict[str, object], ...]:
    """Project Plugin diagnostics into the Package inventory vocabulary."""

    return tuple(
        {
            "code": _package_plugin_diagnostic_code(diagnostic.code),
            "message": diagnostic.message,
            "path": str(diagnostic.path),
        }
        for diagnostic in diagnostics
    )


def _manifest_path(root: Path) -> Path | None:
    for filename in ("loushang-package.json", "plugin.json"):
        path = root / filename
        if path.is_file() or path.is_symlink():
            return path
    return None


def _package_root_from_manifest(
    root: Path,
    manifest_path: Path,
    payload: dict[str, Any],
) -> tuple[Path, tuple[dict[str, object], ...]]:
    value = payload.get("packageRoot", payload.get("package_root", "."))
    if value in (None, ""):
        return root, ()
    if not isinstance(value, str):
        return root, (
            _invalid_package_root_diagnostic(
                manifest_path, "Package packageRoot must be a string."
            ),
        )
    relative = Path(value).expanduser()
    if relative.is_absolute():
        return root, (
            _invalid_package_root_diagnostic(
                manifest_path, "Package packageRoot must be relative."
            ),
        )
    try:
        resolved = (root / relative).resolve()
    except (OSError, RuntimeError) as exc:
        return root, (
            _invalid_package_root_diagnostic(
                manifest_path,
                f"Package packageRoot could not be resolved: {exc}",
            ),
        )
    try:
        resolved.relative_to(root)
    except ValueError:
        return root, (
            _invalid_package_root_diagnostic(
                manifest_path, "Package packageRoot must stay inside the package root."
            ),
        )
    if not resolved.is_dir():
        return root, (
            _invalid_package_root_diagnostic(
                manifest_path,
                "Package packageRoot must be an existing directory.",
            ),
        )
    return resolved, ()


def _invalid_package_root_diagnostic(
    manifest_path: Path, message: str
) -> dict[str, object]:
    return {
        "code": "invalid_package_manifest",
        "message": message,
        "path": str(manifest_path),
    }


def _string_value(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None
