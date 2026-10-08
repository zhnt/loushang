"""Safe, inert materialization of a compiled public Plugin package."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from loushang.harness.resources.plugins.locators import (
    canonical_plugin_relative_path,
)
from loushang.plugin._package import PluginPackageSpec
from loushang.plugin._validation import PluginValidationResult, validate_package


def write_package_tree(
    directory: str | Path,
    spec: PluginPackageSpec,
    *,
    content_files: Mapping[str, bytes] | None = None,
) -> PluginValidationResult:
    """Create a new package tree and inspect it without executing Plugin code.

    The destination must be absent. Generated files and supplied content cannot
    replace one another, escape the package, or turn a file into a directory.
    An invalid declaration remains available for the author to inspect and fix.
    """

    if not isinstance(spec, PluginPackageSpec):
        raise TypeError("A compiled Plugin package is required")
    files: dict[str, bytes] = {}
    for artifact in spec.artifacts:
        _add_file(files, artifact.path, artifact.content)
    if content_files is not None:
        if not isinstance(content_files, Mapping):
            raise TypeError("Plugin content files must be a mapping")
        for path, body in content_files.items():
            _add_file(files, path, body)
    paths = set(files)
    for path in paths:
        parent = canonical_plugin_relative_path(path).parent
        while parent.as_posix() != ".":
            if parent.as_posix() in paths:
                raise ValueError("Plugin file and directory paths conflict")
            parent = parent.parent

    root = Path(directory).expanduser()
    root.mkdir(mode=0o700)
    for path, body in sorted(files.items()):
        target = root.joinpath(*canonical_plugin_relative_path(path).parts)
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with target.open("xb") as output:
            output.write(body)
    return validate_package(root)


def _add_file(files: dict[str, bytes], path: str, body: bytes) -> None:
    canonical = canonical_plugin_relative_path(path).as_posix()
    if type(body) is not bytes:
        raise TypeError("Plugin author content must be bytes")
    if canonical in files:
        raise ValueError(f"Plugin package repeats file: {canonical}")
    files[canonical] = body


__all__ = ["write_package_tree"]
