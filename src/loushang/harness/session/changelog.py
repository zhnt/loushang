"""Standard changelog provider for shared session commands."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChangelogEntry:
    version: str
    body: str
    date: str | None = None


@dataclass(frozen=True)
class ChangelogProfile:
    filename: str = "CHANGELOG.md"
    entry_limit: int = 3

    def __post_init__(self) -> None:
        if not self.filename or Path(self.filename).name != self.filename:
            raise ValueError("changelog filename must be one plain file name")
        if self.entry_limit < 1:
            raise ValueError("changelog entry limit must be positive")


STANDARD_CHANGELOG_PROFILE = ChangelogProfile()

_HEADING_RE = re.compile(r"^##\s+(?P<title>.+?)\s*$")
_DATED_TITLE_RE = re.compile(
    r"^\[?(?P<version>[^\]\-]+?)\]?\s+-\s+(?P<date>\d{4}-\d{2}-\d{2})$"
)


def parse_changelog(path: str | Path) -> list[ChangelogEntry]:
    text = Path(path).read_text(encoding="utf-8")
    entries: list[ChangelogEntry] = []
    current_title: str | None = None
    current_body: list[str] = []

    for line in text.splitlines():
        heading = _HEADING_RE.match(line)
        if heading is not None:
            _append_entry(entries, current_title, current_body)
            current_title = heading.group("title").strip()
            current_body = []
            continue
        if current_title is not None:
            current_body.append(line)

    _append_entry(entries, current_title, current_body)
    return entries


def find_changelog_path(
    start: str | Path,
    *,
    profile: ChangelogProfile = STANDARD_CHANGELOG_PROFILE,
) -> Path | None:
    path = Path(start).resolve()
    current = path if path.is_dir() else path.parent
    for directory in (current, *current.parents):
        candidate = directory / profile.filename
        if candidate.is_file():
            return candidate
    return None


def format_changelog_entries(
    entries: list[ChangelogEntry],
    *,
    limit: int | None = None,
) -> str:
    selected = entries[:limit] if limit is not None else entries
    parts: list[str] = []
    for entry in selected:
        title = f"[{entry.version}] - {entry.date}" if entry.date else entry.version
        body = entry.body.strip()
        heading = f"## {title}"
        parts.append(f"{heading}\n\n{body}" if body else heading)
    return "\n\n".join(parts)


def read_changelog_for_cwd(
    cwd: str | Path,
    args: str = "",
    *,
    profile: ChangelogProfile = STANDARD_CHANGELOG_PROFILE,
) -> dict[str, object]:
    """Read the nearest changelog for the standard session command."""

    del args
    path = find_changelog_path(cwd, profile=profile)
    if path is None:
        return {"path": None, "entries": [], "text": ""}
    entries = parse_changelog(path)
    selected = entries[: profile.entry_limit]
    return {
        "path": path.as_posix(),
        "entries": [asdict(entry) for entry in selected],
        "text": format_changelog_entries(entries, limit=profile.entry_limit),
    }


def _append_entry(
    entries: list[ChangelogEntry],
    title: str | None,
    body_lines: list[str],
) -> None:
    if title is None:
        return
    match = _DATED_TITLE_RE.match(title)
    if match is None:
        version = title.strip()
        date = None
    else:
        version = match.group("version").strip()
        date = match.group("date")
    body = "\n".join(body_lines).strip()
    entries.append(ChangelogEntry(version=version, date=date, body=body))


__all__ = [
    "STANDARD_CHANGELOG_PROFILE",
    "ChangelogEntry",
    "ChangelogProfile",
    "find_changelog_path",
    "format_changelog_entries",
    "parse_changelog",
    "read_changelog_for_cwd",
]
