"""Pure Skill ignore-pattern normalization shared by Resource discovery paths."""

from __future__ import annotations

from fnmatch import fnmatch
from pathlib import Path


def normalize_skill_ignore_pattern(raw_line: str, *, prefix: str) -> str | None:
    line = raw_line.strip()
    if not line or line.startswith("#") or line.startswith("!"):
        return None
    if line.startswith("\\#") or line.startswith("\\!"):
        line = line[1:]
    if line.startswith("/"):
        line = line[1:]
    if prefix:
        line = f"{prefix}/{line}"
    return line


def is_skill_path_ignored(
    path: Path,
    *,
    root_dir: Path,
    patterns: tuple[str, ...],
) -> bool:
    if not patterns:
        return False
    relative_path = path.relative_to(root_dir).as_posix()
    directory_path = f"{relative_path}/"
    for pattern in patterns:
        normalized = pattern.rstrip("/")
        if pattern.endswith("/") and (
            relative_path == normalized or directory_path.startswith(pattern)
        ):
            return True
        if relative_path == normalized or relative_path.startswith(f"{normalized}/"):
            return True
        if fnmatch(relative_path, normalized) or fnmatch(directory_path, pattern):
            return True
    return False


__all__ = ["is_skill_path_ignored", "normalize_skill_ignore_pattern"]
