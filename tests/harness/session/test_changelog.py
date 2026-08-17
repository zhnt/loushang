from __future__ import annotations

from pathlib import Path

from loushang.harness.session.changelog import (
    ChangelogProfile,
    find_changelog_path,
    format_changelog_entries,
    parse_changelog,
    read_changelog_for_cwd,
)


def test_parse_changelog_extracts_markdown_entries(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "# Changelog\n\n"
        "## [1.2.0] - 2026-05-01\n\n"
        "- Added builtin commands.\n"
        "- Fixed config resolution.\n\n"
        "## Unreleased\n\n"
        "- Work in progress.\n",
        encoding="utf-8",
    )

    entries = parse_changelog(changelog)

    assert [(entry.version, entry.date, entry.body) for entry in entries] == [
        ("1.2.0", "2026-05-01", "- Added builtin commands.\n- Fixed config resolution."),
        ("Unreleased", None, "- Work in progress."),
    ]
    assert format_changelog_entries(entries, limit=1) == (
        "## [1.2.0] - 2026-05-01\n\n"
        "- Added builtin commands.\n"
        "- Fixed config resolution."
    )


def test_profile_selects_filename_and_projected_entry_limit(tmp_path: Path) -> None:
    project = tmp_path / "project"
    nested = project / "slides"
    nested.mkdir(parents=True)
    changelog = project / "RELEASES.md"
    changelog.write_text(
        "## 2.0\n\nSecond release.\n\n## 1.0\n\nFirst release.\n",
        encoding="utf-8",
    )
    profile = ChangelogProfile(filename="RELEASES.md", entry_limit=1)

    assert find_changelog_path(nested, profile=profile) == changelog
    assert read_changelog_for_cwd(nested, profile=profile) == {
        "path": changelog.as_posix(),
        "entries": [{"version": "2.0", "body": "Second release.", "date": None}],
        "text": "## 2.0\n\nSecond release.",
    }
