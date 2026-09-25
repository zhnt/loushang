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
    # Interactive startup delta from 7f4b27f4: entry +15, application -29,
    # Linux screen adapter +17, canonical early route +98. Worker/terminal
    # ownership remains in HarnessTUI/TUI; no new Coding path is exempt.
    interactive_startup_allowance = 15 - 29 + 17 + 98
    # Reviewed LMUX-M0 owned-factory binding in original owners (+42/+77),
    # offset by moving the original theme to shared Harnesstui (-24).
    # Keep these existing files in core, including its original 14-line margin.
    lmux_owned_core_allowance = 42 + 77 - 24
    # Reviewed capability composition versus the validated da820585 wheel:
    # ui/mode.py +17 current-binding provider; ui/screen_input.py +50 Product
    # declaration projection. Both remain core; preserve its six-line margin.
    capability_projection_allowance = 17 + 50
    # LMUX reviewed default-owned wiring: bootstrap +7, runtime +5,
    # manager +1 versus da820585. Keep all three in core and its six-line margin.
    lmux_default_owned_allowance = 7 + 5 + 1
    # Canonical legacy-store enrollment stays in the same three Product owners:
    # bootstrap +5, runtime +6 and manager +4. Preserve the existing margin.
    canonical_legacy_enrollment_allowance = 5 + 6 + 4
    # PLC9D's dark writer seal stays in the existing Coding lifecycle owner:
    # _plugin_lifecycle.py +43/-2; no new Coding path is exempt.
    plc9d_writer_fence_allowance = 43 - 2
    # PLC9B's Session-bound Product factory uses the existing Coding bootstrap:
    # bootstrap.py +53/-6; no new Coding path is exempt.
    plc9b_session_inventory_allowance = 53 - 6
    # PLC9B startup ingress: lifecycle +142/-67, bootstrap +14/-5,
    # Continuity +48/-3, new epoch layout +96, management CLI +38/-21.
    # All five paths stay in core; retain the prior one-line margin.
    plc9b_startup_ingress_allowance = (142 - 67) + (14 - 5) + (48 - 3) + 96 + (38 - 21)
    # PLC9B pre-B snapshot domains extend the exact epoch layout +206/-1;
    # the path remains in core and retains the one-line margin.
    plc9b_snapshot_domains_allowance = 206 - 1
    # PLC9B cutover preparation: bootstrap +70/-37, pre-B state snapshot
    # +147, and settings-locked Source snapshot +231. Exact paths stay core.
    plc9b_cutover_transaction_allowance = (70 - 37) + 147 + 231
    # PLC9B selected manifest extends the existing base Plugin owner +142/-21.
    plc9b_selected_manifest_allowance = 142 - 21
    # PLC9B selected Resources: base Plugin +11/-4 and new exact Product
    # composition +403. Both remain counted in core.
    plc9b_selected_resources_allowance = (11 - 4) + 403
    # PLC9B hosted routing keeps these existing core owners bounded: base
    # Plugin +48/-12, Product composition +110/-7, Resource shadow +26/-1,
    # bootstrap +189/-28, and agent Session +151/-40.
    plc9b_hosted_routing_allowance = (
        (48 - 12) + (110 - 7) + (26 - 1) + (189 - 28) + (151 - 40)
    )
    # PLC9B fenced owner adds exact new Coding Product modules: built-in Wheel
    # +232 and runtime +213, plus pre-B snapshot +17. All remain core.
    plc9b_fenced_owner_allowance = 232 + 213 + 17
    assert (
        sum(groups["core"].values())
        <= 33_686 + g18_core_allowance + interactive_startup_allowance + lmux_owned_core_allowance
        + capability_projection_allowance + lmux_default_owned_allowance
        + canonical_legacy_enrollment_allowance + plc9d_writer_fence_allowance
        + plc9b_session_inventory_allowance
        + plc9b_startup_ingress_allowance
        + plc9b_snapshot_domains_allowance
        + plc9b_cutover_transaction_allowance
        + plc9b_selected_manifest_allowance
        + plc9b_selected_resources_allowance
        + plc9b_hosted_routing_allowance
        + plc9b_fenced_owner_allowance
    ), groups["core"]
    assert sum(groups["g10"].values()) <= 1_800, groups["g10"]
    # Preserve main's optional execution projection allowance.
    assert sum(groups["g11"].values()) <= 420, groups["g11"]
    # LMUX-M0: original Product/catalog cleanup and managed activation (+84).
    assert sum(groups["g12"].values()) <= 800 + 84, groups["g12"]
    assert sum(groups["g13"].values()) <= 350, groups["g13"]
    # LMUX-M0: original catalog ownership, readonly hooks and validation (+205).
    assert sum(groups["g14"].values()) <= 1_300 + 205, groups["g14"]
    assert sum(groups["g16"].values()) <= 900, groups["g16"]
    assert sum(groups["g17"].values()) <= 450, groups["g17"]
    assert sum(groups["g18"].values()) <= 200, groups["g18"]
    assert sum(groups["execution"].values()) <= 400, groups["execution"]
    assert max(groups["execution"].values()) <= 250, groups["execution"]
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
    assert sum(groups["lmux"].values()) <= (
        1_579 + 13 + managed_composition_allowance + creation_recovery_composition_allowance
        + child_import_boundary_allowance + plc9b_hosted_lmux_allowance
    ), groups["lmux"]


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
