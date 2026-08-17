#!/usr/bin/env python3
"""Report local worktree-lane health without changing repository state."""

from __future__ import annotations

import argparse
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

EXPECTED_LANES = ("tui", "code", "harness", "method", "ai", "agent", "ontology")


@dataclass(frozen=True)
class WorktreeRecord:
    path: Path
    branch: str | None = None
    detached: bool = False
    prunable: str | None = None


@dataclass(frozen=True)
class LaneStatus:
    name: str
    path: Path
    state: str
    branch: str | None = None
    dirty: bool | None = None
    ahead: int | None = None
    behind: int | None = None
    note: str | None = None


def parse_worktree_porcelain(output: str) -> tuple[WorktreeRecord, ...]:
    records: list[WorktreeRecord] = []
    fields: dict[str, str] = {}

    def append_record() -> None:
        raw_path = fields.get("worktree")
        if raw_path is None:
            return
        raw_branch = fields.get("branch")
        branch = (
            raw_branch.removeprefix("refs/heads/") if raw_branch is not None else None
        )
        records.append(
            WorktreeRecord(
                path=Path(raw_path).resolve(),
                branch=branch,
                detached="detached" in fields,
                prunable=fields.get("prunable"),
            )
        )

    for line in (*output.splitlines(), ""):
        if not line:
            append_record()
            fields = {}
            continue
        key, _, value = line.partition(" ")
        fields[key] = value
    return tuple(records)


def collect_lane_statuses(repo: Path) -> tuple[LaneStatus, ...]:
    root = _repo_root(repo)
    worktrees = parse_worktree_porcelain(
        _git(root, "worktree", "list", "--porcelain").stdout
    )
    by_path = {record.path: record for record in worktrees}
    expected_paths = {
        "control": root,
        **{name: root / ".worktrees" / name for name in EXPECTED_LANES},
    }
    statuses = [
        _lane_status(name, path.resolve(), by_path.get(path.resolve()))
        for name, path in expected_paths.items()
    ]
    expected_set = {path.resolve() for path in expected_paths.values()}
    for record in worktrees:
        if record.path in expected_set:
            continue
        statuses.append(_lane_status("extra", record.path, record))
    return tuple(statuses)


def render_lane_status(statuses: Sequence[LaneStatus]) -> str:
    rows = [
        (
            status.name,
            status.branch or "-",
            status.state,
            _yes_no(status.dirty),
            _number(status.ahead),
            _number(status.behind),
            str(status.path),
            status.note or "",
        )
        for status in statuses
    ]
    headers = (
        "LANE",
        "BRANCH",
        "STATE",
        "DIRTY",
        "AHEAD",
        "BEHIND",
        "PATH",
        "NOTE",
    )
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]

    def format_row(row: Sequence[str]) -> str:
        return "  ".join(
            value.ljust(widths[index]) for index, value in enumerate(row)
        ).rstrip()

    dirty_count = sum(status.dirty is True for status in statuses)
    behind_count = sum(bool(status.behind) for status in statuses)
    extra_count = sum(status.name == "extra" for status in statuses)
    prunable_count = sum(status.state == "prunable" for status in statuses)
    active_count = sum(status.state in {"registered", "prunable"} for status in statuses)
    return "\n".join(
        (
            "Lane status (read-only; compared with the local origin/main ref)",
            format_row(headers),
            format_row(tuple("-" * width for width in widths)),
            *(format_row(row) for row in rows),
            "",
            (
                f"Summary: active={active_count} dirty={dirty_count} "
                f"behind={behind_count} extra={extra_count} prunable={prunable_count}"
            ),
        )
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=Path.cwd(),
        help="repository or linked-worktree path (default: current directory)",
    )
    args = parser.parse_args(argv)
    print(render_lane_status(collect_lane_statuses(args.repo)))
    return 0


def _lane_status(
    name: str,
    path: Path,
    record: WorktreeRecord | None,
) -> LaneStatus:
    if record is None:
        state = "unregistered" if path.exists() else "absent"
        return LaneStatus(name=name, path=path, state=state)
    if record.prunable is not None:
        return LaneStatus(
            name=name,
            path=path,
            state="prunable",
            branch=record.branch,
            note=record.prunable or "prunable",
        )
    if not path.exists():
        return LaneStatus(
            name=name,
            path=path,
            state="missing",
            branch=record.branch,
        )
    dirty_result = _git(path, "status", "--porcelain")
    dirty = bool(dirty_result.stdout.strip()) if dirty_result.returncode == 0 else None
    ahead, behind = _ahead_behind(path)
    branch = record.branch or ("(detached)" if record.detached else None)
    note = None if dirty_result.returncode == 0 else _error_note(dirty_result)
    return LaneStatus(
        name=name,
        path=path,
        state="registered",
        branch=branch,
        dirty=dirty,
        ahead=ahead,
        behind=behind,
        note=note,
    )


def _ahead_behind(path: Path) -> tuple[int | None, int | None]:
    result = _git(path, "rev-list", "--left-right", "--count", "origin/main...HEAD")
    if result.returncode != 0:
        return None, None
    parts = result.stdout.split()
    if len(parts) != 2 or not all(part.isdecimal() for part in parts):
        return None, None
    behind, ahead = (int(part) for part in parts)
    return ahead, behind


def _repo_root(path: Path) -> Path:
    result = _git(path, "rev-parse", "--show-toplevel")
    if result.returncode != 0 or not result.stdout.strip():
        raise SystemExit(_error_note(result) or f"not a git repository: {path}")
    root = Path(result.stdout.strip()).resolve()
    common = _git(root, "rev-parse", "--git-common-dir")
    if common.returncode != 0 or not common.stdout.strip():
        return root
    common_dir = Path(common.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = (root / common_dir).resolve()
    return common_dir.parent if common_dir.name == ".git" else root


def _git(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-C", str(path), *args),
        text=True,
        capture_output=True,
        check=False,
    )


def _yes_no(value: bool | None) -> str:
    if value is None:
        return "-"
    return "yes" if value else "no"


def _number(value: int | None) -> str:
    return "-" if value is None else str(value)


def _error_note(result: subprocess.CompletedProcess[str]) -> str:
    return (result.stderr or result.stdout).strip().splitlines()[0]


if __name__ == "__main__":
    raise SystemExit(main())
