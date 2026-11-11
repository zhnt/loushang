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
EXECUTION_PRODUCT_SLICE = frozenset({"hosted_execution.py", "_hosted_execution_work.py"})
LMUX_PRODUCT_SLICE = frozenset({
    "managed_process.py", "managed_local.py", "managed_bootstrap.py", "managed_catalog.py",
    "cli/lmux.py", "cli/lmux_command.py", "cli/lmux_stop_all.py",
})

APPROVED_SLICES = {
    "g10": G10_PRODUCT_SLICE,
    "g11": G11_PRODUCT_SLICE,
    "g12": G12_PRODUCT_SLICE,
    "g13": G13_PRODUCT_SLICE,
    "g14": G14_PRODUCT_SLICE,
    "g16": G16_PRODUCT_SLICE,
    "g17": G17_PRODUCT_SLICE,
    "g18": G18_FACADE_SLICE,
    "execution": EXECUTION_PRODUCT_SLICE,
    "lmux": LMUX_PRODUCT_SLICE,
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


def test_coding_product_slices_stay_within_wave_a_budget() -> None:
    """Bound hosted Product slices while counting every Coding file once."""

    root = Path("src/loushang/coding")
    line_counts = {
        path.relative_to(root).as_posix(): len(
            path.read_text(encoding="utf-8").splitlines()
        )
        for path in sorted(root.rglob("*.py"))
    }

    groups = _partition_line_counts(line_counts)
    assert sum(groups["g10"].values()) <= 1_800, groups["g10"]
    # Hosted execution plus redacted, session-local model control stay in the
    # existing AppService adapter owner.
    assert sum(groups["g11"].values()) <= 470, groups["g11"]
    # LMUX-M0: original Product/catalog cleanup and managed activation (+84).
    # PLC9B: Product Session ownership closes the injected factory (+7).
    # Hosted SDK Method and bounded Goal integration add a net 55 lines on main.
    assert sum(groups["g12"].values()) <= 800 + 84 + 7 + 55, groups["g12"]
    assert sum(groups["g13"].values()) <= 350, groups["g13"]
    # LMUX-M0: original catalog ownership, readonly hooks and validation (+205).
    # P3: seal canonical composition before Hosted candidate materialization (+8).
    # PLC9: admit the Windows ordinary Product route in Hosted construction (+3).
    # ARD-004/005/006 R2.1: detached history, source-fenced recovery reads,
    # stable first-input execution and narrow adapter data validation stay on
    # these same original owners. Exact net delta from current main: catalog
    # +334, session +195 and CLI +34. The catalog delta includes the
    # lifecycle-observation proxies required by the Resume wrapper.
    # Issue #696 correction: share the 64 MiB verified-history cap (+1).
    # Hosted SDK Method and bounded Goal integration add 29 session lines.
    # See foreground-stdio-hosted-app-g14.md, R2.1 reviewability supplement.
    assert sum(groups["g14"].values()) <= 1_300 + 205 + 8 + 3 + 334 + 195 + 34 + 1 + 29, groups["g14"]
    for path, limit in {
        "cli/hosted.py": 290,
        "hosted_catalog.py": 1_221,
        # Main 794156c3b contains 714 lines after GUI model persistence.
        "hosted_session.py": 714,
    }.items():
        assert groups["g14"][path] <= limit, (path, groups["g14"][path], limit)
    # R2.1 extends the existing detachable owners with explicit execution
    # composition and admitted owned-root preparation. Exact net delta from
    # current main: mux +1, bootstrap +37 and local command +15.
    # Hosted SDK Method and bounded Goal integration add 29 bootstrap lines.
    assert sum(groups["g16"].values()) <= 900 + 53 + 29, groups["g16"]
    for path, limit in {
        "cli/mux.py": 258,
        "hosted_bootstrap.py": 288 + 29,
        "hosted_local.py": 402,
    }.items():
        assert groups["g16"][path] <= limit, (path, groups["g16"][path], limit)
    assert sum(groups["g17"].values()) <= 450, groups["g17"]
    assert sum(groups["g18"].values()) <= 200, groups["g18"]
    # Stage 1A adds exactly 73 lines to the existing adapter: resolver-sealed
    # identity projection, exact-owner checks and named port selection. See
    # execution-service-delivery.md, post-merge budget review (2026-11-09).
    # Main 794156c3b contains 568 execution lines.
    assert sum(groups["execution"].values()) <= 568, groups["execution"]
    # R2.1 deferred and read-only bindings add eight lines above the original
    # per-file ceiling; Hosted SDK Method integration adds another seven.
    # Main 794156c3b's larger execution file has 354 lines.
    assert max(groups["execution"].values()) <= 354, groups["execution"]
    # Exact reviewed optional Product composition baseline; not an exemption
    # for any future managed/CLI module, nor a general core-budget increase.
    # Reviewed single-candidate selection adds 13 lines to the same CLI owner.
    # Reviewed capture/trace composition: process +23, local +20, bootstrap +3,
    # parser +4; command probe/trace composition +108 minus obsolete selector 29.
    # Authentication and candidate truth remain in AppHost, not this CLI slice.
    managed_composition_allowance = 23 + 20 + 3 + 4 + 108 - 29
    # Reviewed creation-receipt recovery: parser +14, command +75.
    # The removed selector -29 is already counted above, not deducted twice.
    creation_recovery_composition_allowance = 14 + 75
    # Reviewed child-only backend import and ownership explanation: net +3.
    child_import_boundary_allowance = 3
    # PLC9B hosted routing adds managed-bootstrap +7 and managed-local +12/-2
    # for the same Product Session binding; no new LMUX path is approved.
    plc9b_hosted_lmux_allowance = 7 + (12 - 2)
    # R2.1 passes execution through the installed client (+1) and keeps managed
    # startup outside the ordinary owned-root/execution path (+7).
    r21_resume_lmux_allowance = 1 + 7
    assert sum(groups["lmux"].values()) <= (
        1_579 + 13 + managed_composition_allowance + creation_recovery_composition_allowance
        + child_import_boundary_allowance + plc9b_hosted_lmux_allowance
        + r21_resume_lmux_allowance
    ), groups["lmux"]
    for path, limit in {
        "cli/lmux_command.py": 811,
        "managed_local.py": 172,
    }.items():
        assert groups["lmux"][path] <= limit, (path, groups["lmux"][path], limit)

def test_unapproved_files_stay_in_core_and_every_file_is_counted_once() -> None:
    approved = set().union(*APPROVED_SLICES.values())
    line_counts = {path: index + 1 for index, path in enumerate(sorted(approved))}
    unapproved = {
        "new_feature.py": 101,
        "cli/__init__.py": 103,
        "nested/__init__.py": 107,
        "nested/new_feature.py": 109,
        "managed_unreviewed.py": 113,
        "cli/lmux_unreviewed.py": 127,
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
