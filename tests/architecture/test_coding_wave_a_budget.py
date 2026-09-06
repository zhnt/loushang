from __future__ import annotations

from pathlib import Path

G10_PRODUCT_SLICE = frozenset(
    {
        "_apphost_canary_child.py",
        "_apphost_canary_control.py",
        "apphost_canary.py",
        "cli/apphost.py",
    }
)


def test_coding_package_stays_within_wave_a_budget() -> None:
    """Keep Wave A core and the approved G10 Product slice independently bounded."""

    root = Path("src/loushang/coding")
    line_counts = {
        path.relative_to(root).as_posix(): len(
            path.read_text(encoding="utf-8").splitlines()
        )
        for path in sorted(root.rglob("*.py"))
    }

    assert G10_PRODUCT_SLICE <= line_counts.keys(), line_counts
    core_line_counts = {
        path: count
        for path, count in line_counts.items()
        if path not in G10_PRODUCT_SLICE
    }
    g10_line_counts = {
        path: line_counts[path] for path in sorted(G10_PRODUCT_SLICE)
    }

    assert sum(core_line_counts.values()) <= 33_800, core_line_counts
    assert sum(g10_line_counts.values()) <= 1_800, g10_line_counts
