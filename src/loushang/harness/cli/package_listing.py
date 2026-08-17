"""Shared CLI package catalog output projection."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from typing import TextIO

PackageRecord = Mapping[str, object]
PackageRecordLoader = Callable[[], list[PackageRecord]]


def format_package_records(
    packages: list[PackageRecord],
    output_format: str,
) -> str:
    """Render package records without choosing how Products discover them."""

    if output_format == "json":
        return json.dumps(packages, ensure_ascii=False) + "\n"
    if output_format == "tsv":
        return "".join(
            f"{package['name']}\t{package['kind']}\t{package['scope']}\t"
            f"{package['version']}\t{package['source']}\t{package['path']}\t"
            f"{package['enabled']}\t{package['prompts']}\t{package['skills']}\t"
            f"{package['extensions']}\t{package['themes']}\t"
            f"{package['diagnostics']}\n"
            for package in packages
        )
    if not packages:
        return "No packages.\n"
    scope_order = ("user", "project", "session", "merged", "catalog")
    scopes = {str(package.get("scope", "")) for package in packages}
    ordered_scopes = [scope for scope in scope_order if scope in scopes]
    ordered_scopes.extend(sorted(scope for scope in scopes if scope not in scope_order))
    groups: list[str] = []
    for scope in ordered_scopes:
        scoped_packages = [
            package
            for package in packages
            if str(package.get("scope", "")) == scope
        ]
        if not scoped_packages:
            continue
        lines = [_package_scope_title(scope) + ":"]
        for package in scoped_packages:
            lines.append(f"  {_format_package_summary_line(package)}")
            source = str(package.get("source", ""))
            path = str(package.get("path", ""))
            if source:
                lines.append(f"    source: {source}")
            if path:
                lines.append(f"    path: {path}")
            resources = _format_package_resources(package)
            if resources:
                lines.append(f"    resources: {resources}")
        groups.append("\n".join(lines))
    return "\n\n".join(groups) + "\n"


def run_package_listing_operation(
    *,
    requested: bool,
    output_format: str,
    list_records: PackageRecordLoader | None,
    fallback_records: PackageRecordLoader | None,
    stdout: TextIO,
    stderr: TextIO,
    format_error: Callable[[BaseException], str] = str,
) -> int | None:
    """Run a standard package listing with an optional Product fallback."""

    if not requested:
        return None
    if list_records is None:
        stderr.write("Error: package listing is not available.\n")
        return 1
    try:
        packages = list_records()
        if not packages and fallback_records is not None:
            packages = fallback_records()
    except Exception as error:
        stderr.write(f"Error: {format_error(error)}\n")
        return 1
    stdout.write(format_package_records(packages, output_format))
    return 0


def _package_scope_title(scope: str) -> str:
    labels = {
        "user": "User packages",
        "project": "Project packages",
        "session": "Session packages",
        "merged": "Merged packages",
        "catalog": "Catalog packages",
    }
    return labels.get(scope, f"{scope.title()} packages")


def _format_package_summary_line(package: Mapping[str, object]) -> str:
    parts = [str(package.get("name", ""))]
    version = str(package.get("version", ""))
    if version:
        parts.append(version)
    kind = str(package.get("kind", ""))
    if kind:
        parts.append(f"[{kind}]")
    status: list[str] = []
    if package.get("enabled") is False:
        status.append("disabled")
    if package.get("filtered") is True:
        status.append("filtered")
    lifecycle = str(package.get("lifecycle", ""))
    if lifecycle and lifecycle not in {"installed", "remote_registered"}:
        status.append(lifecycle)
    if str(package.get("security", "")) == "denied":
        status.append("denied")
    if status:
        parts.append(", ".join(status))
    return " ".join(part for part in parts if part)


def _format_package_resources(package: Mapping[str, object]) -> str:
    parts: list[str] = []
    for key in ("prompts", "skills", "extensions", "themes", "diagnostics"):
        value = package.get(key)
        if isinstance(value, int) and value > 0:
            parts.append(f"{key}={value}")
    return " ".join(parts)


__all__ = [
    "PackageRecord",
    "PackageRecordLoader",
    "format_package_records",
    "run_package_listing_operation",
]
