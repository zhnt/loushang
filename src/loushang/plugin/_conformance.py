"""Explicit developer-only execution conformance, separate from inert validation."""

from __future__ import annotations

import runpy
from dataclasses import dataclass
from pathlib import Path

from loushang.harness.resources.plugins.locators import parse_plugin_entrypoint
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.plugin._validation import PluginValidationResult, validate_package


class PluginExecutionConformanceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class PluginExecutionConformanceResult:
    package_root: str
    plugin_id: str
    executed_sources: tuple[str, ...]
    resolved_entrypoints: tuple[str, ...]


def run_execution_conformance(
    path: str | Path,
    *,
    execution_approved: bool = False,
) -> PluginExecutionConformanceResult:
    """Import exact Definition files only after an explicit developer approval."""

    validation = validate_package(path)
    _require_valid(validation)
    if execution_approved is not True:
        raise PluginExecutionConformanceError(
            "Execution conformance requires explicit --approve-execution"
        )
    package = PluginManifestParser().parse(path)
    entrypoints = tuple(
        sorted(
            {
                reservation.declaration_source.entrypoint
                for reservation in package.contribution_index.items
                if reservation.declaration_source.kind == "in_process"
                and reservation.declaration_source.entrypoint is not None
            }
        )
    )
    resolved: list[str] = []
    executed: list[str] = []
    for entrypoint in entrypoints:
        relative_path, symbol = parse_plugin_entrypoint(entrypoint)
        source_path = package.package_root / relative_path
        namespace = runpy.run_path(
            str(source_path),
            run_name=(
                "_loushang_plugin_conformance_"
                + package.manifest.name.replace("-", "_").replace(".", "_")
            ),
        )
        value: object = namespace
        for part in symbol.split("."):
            if not isinstance(value, dict):
                value = getattr(value, part)
            else:
                value = value[part]
        if not callable(value):
            raise PluginExecutionConformanceError(
                f"Plugin Definition entrypoint is not callable: {entrypoint}"
            )
        executed.append(relative_path.as_posix())
        resolved.append(entrypoint)
    return PluginExecutionConformanceResult(
        package_root=str(package.package_root),
        plugin_id=package.manifest.name,
        executed_sources=tuple(executed),
        resolved_entrypoints=tuple(resolved),
    )


def _require_valid(result: PluginValidationResult) -> None:
    if result.valid:
        return
    codes = ", ".join(item.code for item in result.diagnostics)
    raise PluginExecutionConformanceError(
        "Plugin package failed inert validation before execution conformance: " + codes
    )


__all__ = [
    "PluginExecutionConformanceError",
    "PluginExecutionConformanceResult",
    "run_execution_conformance",
]
