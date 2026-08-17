from __future__ import annotations

from pathlib import Path


def test_coding_package_stays_within_wave_a_budget() -> None:
    """Freeze the post-migration Coding package size at the Wave A ceiling."""

    root = Path("src/loushang/coding")
    line_counts = {
        path.relative_to(root).as_posix(): len(
            path.read_text(encoding="utf-8").splitlines()
        )
        for path in sorted(root.rglob("*.py"))
    }

    assert sum(line_counts.values()) <= 33_800, line_counts
