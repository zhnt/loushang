"""Small, no-replace source scaffolds for Coding's admitted data profiles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

CodingDataKind = Literal["skill", "prompt"]

_SIMPLE_ID = re.compile(r"[a-z][a-z0-9]*\Z")
_RESOURCE_NAME = re.compile(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*\Z")
_VERSION = re.compile(r"[0-9]+(?:\.[0-9]+){0,2}\Z")


@dataclass(frozen=True, slots=True)
class CodingDataScaffold:
    kind: CodingDataKind
    plugin_id: str
    version: str
    resource_name: str
    source_path: Path
    build_command: tuple[str, ...]
    smoke_command: tuple[str, ...]


def create_coding_data_scaffold(
    destination: str | Path,
    *,
    kind: CodingDataKind,
    plugin_id: str | None = None,
    resource_name: str | None = None,
    version: str = "1",
) -> CodingDataScaffold:
    """Create one editable source tree without replacing an existing directory.

    This author convenience has no Package or Product authority. Its output is
    deliberately limited to the currently admitted Skill and Prompt profiles.
    """

    if kind not in {"skill", "prompt"}:
        raise ValueError("Coding data scaffold kind must be skill or prompt")
    root = Path(destination).expanduser().absolute()
    resolved_plugin_id = plugin_id if plugin_id is not None else root.name
    if _SIMPLE_ID.fullmatch(resolved_plugin_id) is None:
        raise ValueError("Coding data Plugin ID must be simple lowercase ASCII")
    name = resource_name if resource_name is not None else resolved_plugin_id
    if _RESOURCE_NAME.fullmatch(name) is None:
        raise ValueError("Coding data Resource name must be lowercase kebab-case")
    if _VERSION.fullmatch(version) is None:
        raise ValueError("Coding data version must be numeric")
    if root.exists() or root.is_symlink():
        raise FileExistsError(f"Author source directory already exists: {root}")

    relative_source = (
        Path("skills") / name / "SKILL.md"
        if kind == "skill"
        else Path("prompts") / f"{name}.md"
    )
    source = root / relative_source
    source_body = (
        f"---\nname: {name}\ndescription: Describe when to use this Skill.\n"
        f"---\n# {name}\n\nWrite the steps this Skill should guide.\n"
        if kind == "skill"
        else f"# {name}\n\nWrite the task and expected output here.\n"
    )
    root.mkdir(mode=0o700)
    source.parent.mkdir(parents=True)
    source.write_text(source_body, encoding="utf-8")
    command = (
        "loushang-plugin",
        f"build-coding-{kind}",
        str(source),
        "--plugin-id",
        resolved_plugin_id,
        "--version",
        version,
        "--output-dir",
        str(root / "dist"),
    )
    wheel_path = root / "dist" / f"{resolved_plugin_id}-{version}-py3-none-any.whl"
    smoke_command = (
        "loushang-coding-plugin-smoke",
        str(wheel_path),
        "--kind",
        kind,
        "--plugin-id",
        resolved_plugin_id,
        "--resource-name",
        name,
    )
    return CodingDataScaffold(
        kind=kind,
        plugin_id=resolved_plugin_id,
        version=version,
        resource_name=name,
        source_path=source,
        build_command=command,
        smoke_command=smoke_command,
    )


__all__ = ["CodingDataKind", "CodingDataScaffold", "create_coding_data_scaffold"]
