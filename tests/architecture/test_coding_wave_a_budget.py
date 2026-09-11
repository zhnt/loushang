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
G18_FACADE_SLICE = frozenset({"__init__.py"})

APPROVED_SLICES = {
    "g10": G10_PRODUCT_SLICE,
    "g11": G11_PRODUCT_SLICE,
    "g12": G12_PRODUCT_SLICE,
    "g13": G13_PRODUCT_SLICE,
    "g14": G14_PRODUCT_SLICE,
    "g16": G16_PRODUCT_SLICE,
    "g17": G17_PRODUCT_SLICE,
    "g18": G18_FACADE_SLICE,
}


def _partition_line_counts(
    line_counts: dict[str, int],
) -> dict[str, dict[str, int]]:
    # Only the root facade is approved, never a basename or directory exemption.
    assert G18_FACADE_SLICE == frozenset({"__init__.py"})
    approved: set[str] = set()
    for paths in APPROVED_SLICES.values():
        assert approved.isdisjoint(paths), (approved, paths)
        approved.update(paths)
    assert approved <= line_counts.keys(), line_counts
    partitions = {
        "core": {
            path: count for path, count in line_counts.items() if path not in approved
        },
        **{
            name: {path: line_counts[path] for path in sorted(paths)}
            for name, paths in APPROVED_SLICES.items()
        },
    }
    assert sum(len(group) for group in partitions.values()) == len(line_counts)
    assert set().union(*partitions.values()) == line_counts.keys()
    return partitions


def test_coding_package_stays_within_wave_a_budget() -> None:
    """Bound non-facade core, hosted Product slices and the exact root facade."""

    root = Path("src/loushang/coding")
    line_counts = {
        path.relative_to(root).as_posix(): len(
            path.read_text(encoding="utf-8").splitlines()
        )
        for path in sorted(root.rglob("*.py"))
    }

    groups = _partition_line_counts(line_counts)
    # Baseline 9bc69361494293595ae424be225c61e3226a9996 facade: 114 lines.
    # Preserve the non-facade allowance: 33_800 - 114 = 33_686.
    # Approved G18 net additions outside the facade (relative to 9bc69361):
    # CLI split/lazy entry and startup wiring 87; screen owner 185;
    # UI attachment 16; continuity inode-ownership cleanup 11. No path is exempt.
    g18_core_allowance = 87 + 185 + 16 + 11
    assert sum(groups["core"].values()) <= 33_686 + g18_core_allowance, groups["core"]
    assert sum(groups["g10"].values()) <= 1_800, groups["g10"]
    assert sum(groups["g11"].values()) <= 400, groups["g11"]
    assert sum(groups["g12"].values()) <= 800, groups["g12"]
    assert sum(groups["g13"].values()) <= 350, groups["g13"]
    assert sum(groups["g14"].values()) <= 1_300, groups["g14"]
    assert sum(groups["g16"].values()) <= 900, groups["g16"]
    assert sum(groups["g17"].values()) <= 450, groups["g17"]
    assert sum(groups["g18"].values()) <= 200, groups["g18"]


def test_unapproved_files_stay_in_core_and_every_file_is_counted_once() -> None:
    approved = set().union(*APPROVED_SLICES.values())
    line_counts = {path: index + 1 for index, path in enumerate(sorted(approved))}
    unapproved = {
        "new_feature.py": 101,
        "cli/__init__.py": 103,
        "nested/__init__.py": 107,
        "nested/new_feature.py": 109,
    }
    line_counts.update(unapproved)

    groups = _partition_line_counts(line_counts)

    assert groups["core"] == unapproved
    assert groups["g18"] == {"__init__.py": line_counts["__init__.py"]}
    flattened = [path for group in groups.values() for path in group]
    assert len(flattened) == len(set(flattened)) == len(line_counts)
    assert set(flattened) == line_counts.keys()
    assert sum(sum(group.values()) for group in groups.values()) == sum(
        line_counts.values()
    )
