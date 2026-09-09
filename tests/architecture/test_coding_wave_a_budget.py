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
G11_PRODUCT_SLICE = frozenset({"appservice_adapter.py"})
G12_PRODUCT_SLICE = frozenset({"hosted_application.py"})
G13_PRODUCT_SLICE = frozenset({"hosted_continuity.py"})
G14_PRODUCT_SLICE = frozenset(
    {"cli/hosted.py", "hosted_catalog.py", "hosted_session.py"}
)
G16_PRODUCT_SLICE = frozenset({"hosted_bootstrap.py", "hosted_local.py", "cli/mux.py"})
G17_PRODUCT_SLICE = frozenset({"cli/hosted_client.py"})
EXECUTION_PRODUCT_SLICE = frozenset({"hosted_execution.py", "_hosted_execution_work.py"})


def test_coding_package_stays_within_wave_a_budget() -> None:
    """Keep Wave A core and approved hosted Product slices independently bounded."""

    root = Path("src/loushang/coding")
    line_counts = {
        path.relative_to(root).as_posix(): len(
            path.read_text(encoding="utf-8").splitlines()
        )
        for path in sorted(root.rglob("*.py"))
    }

    approved = (
        G10_PRODUCT_SLICE
        | G11_PRODUCT_SLICE
        | G12_PRODUCT_SLICE
        | G13_PRODUCT_SLICE
        | G14_PRODUCT_SLICE
        | G16_PRODUCT_SLICE
        | G17_PRODUCT_SLICE
        | EXECUTION_PRODUCT_SLICE
    )
    assert approved <= line_counts.keys(), line_counts
    core_line_counts = {
        path: count
        for path, count in line_counts.items()
        if path not in approved
    }
    g10_line_counts = {
        path: line_counts[path] for path in sorted(G10_PRODUCT_SLICE)
    }
    g11_line_counts = {
        path: line_counts[path] for path in sorted(G11_PRODUCT_SLICE)
    }
    g12_line_counts = {
        path: line_counts[path] for path in sorted(G12_PRODUCT_SLICE)
    }
    g13_line_counts = {
        path: line_counts[path] for path in sorted(G13_PRODUCT_SLICE)
    }
    g14_line_counts = {
        path: line_counts[path] for path in sorted(G14_PRODUCT_SLICE)
    }

    assert sum(core_line_counts.values()) <= 33_800, core_line_counts
    assert sum(g10_line_counts.values()) <= 1_800, g10_line_counts
    # Optional execution needs omission metadata and one synchronous projection
    # observation seam; legacy protocol and default composition remain intact.
    assert sum(g11_line_counts.values()) <= 420, g11_line_counts
    assert sum(g12_line_counts.values()) <= 800, g12_line_counts
    assert sum(g13_line_counts.values()) <= 350, g13_line_counts
    assert sum(g14_line_counts.values()) <= 1_300, g14_line_counts
    g16_line_counts = {path: line_counts[path] for path in sorted(G16_PRODUCT_SLICE)}
    assert sum(g16_line_counts.values()) <= 900, g16_line_counts
    g17_line_counts = {path: line_counts[path] for path in sorted(G17_PRODUCT_SLICE)}
    assert sum(g17_line_counts.values()) <= 450, g17_line_counts
    execution_line_counts = {path: line_counts[path] for path in sorted(EXECUTION_PRODUCT_SLICE)}
    assert sum(execution_line_counts.values()) <= 400, execution_line_counts
    assert max(execution_line_counts.values()) <= 250, execution_line_counts
