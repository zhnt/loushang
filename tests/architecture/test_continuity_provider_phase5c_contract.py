from __future__ import annotations

from pathlib import Path

CONTRACT_PATH = Path(
    "docs/internals/architecture/harness/plugin/"
    "continuity-provider-phase5c-contract.md"
)
PLUGIN_README_PATH = Path("docs/internals/architecture/harness/plugin/README.md")
DECLARATIONS_PATH = Path(
    "src/loushang/harness/resources/plugins/declarations.py"
)
PROFILE_PATH = Path("src/loushang/harness/runtime/_profile_standard.py")


def _contract() -> str:
    return CONTRACT_PATH.read_text(encoding="utf-8")


def test_phase5c_contract_is_indexed_and_marks_runtime_not_implemented() -> None:
    contract = _contract()
    readme = PLUGIN_README_PATH.read_text(encoding="utf-8")
    declarations = DECLARATIONS_PATH.read_text(encoding="utf-8")

    assert (
        "[Phase 5C Continuity Provider Plugin Lifecycle]"
        "(continuity-provider-phase5c-contract.md)"
    ) in readme
    assert "the installed-Plugin path described here is not implemented yet" in contract
    assert '"continuity_provider"' not in declarations


def test_phase5c_contract_preserves_exact_owner_and_existing_runtime_slot() -> None:
    contract = _contract()
    normalized_contract = " ".join(contract.split())
    profile = PROFILE_PATH.read_text(encoding="utf-8")

    for required in (
        "finalized `PluginContributionCandidate` is the only legal decoder input",
        "CapabilityOwnerComponentHost",
        "CapabilityOwnerComponentRuntime",
        "`owner_generation` family",
        "does not contribute a Runtime Profile layer",
        "Continuity remains outside the Session Graph",
        "The component ID is not a declaration field",
    ):
        assert required in normalized_contract
    slot = profile[profile.index("CONTINUITY_PROVIDER_PACKS_SLOT"):]
    assert 'allowed_sources=frozenset({"product", "oem"})' in slot


def test_phase5c_contract_freezes_revocation_and_activation_order() -> None:
    contract = _contract()

    ordered_steps = (
        "durably accept the Plugin management operation",
        "synchronously mark the affected generation security-closing",
        "abort every issued-but-unconsumed activation lease",
        "join calls and consumes that linearized before the close mark",
        "durably enter Plugin Instance `REVOKING`",
        "dispose the Continuity owner generation",
        "release its `owner_generation` family only after disposal succeeds",
    )
    positions = tuple(contract.index(step) for step in ordered_steps)
    assert positions == tuple(sorted(positions))
    assert "A revoke\nadmitted first prevents that lease from publishing" in contract
    assert "does not retroactively delete it" in contract
    assert "the Product process must terminate or restart" in contract


def test_phase5c_contract_has_bounded_reviewable_delivery_slices() -> None:
    contract = _contract()

    for delivery_slice in (
        "5C1 — inert contract",
        "5C2 — owner lifecycle",
        "5C3 — composition and activation",
        "5C4 — retirement integration",
    ):
        assert delivery_slice in contract
    assert "Each slice requires architecture, security/lifecycle, and product/test review" in contract
