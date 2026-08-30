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
CONTINUITY_ROOT_PATH = Path("src/loushang/harness/continuity/__init__.py")
CONTINUITY_RUNTIME_PATH = Path(
    "src/loushang/harness/continuity/plugin_runtime.py"
)
CONTINUITY_ADAPTER_PATH = Path(
    "src/loushang/harness/plugin_management/continuity_adapter.py"
)
INSTANCE_RUNTIME_PATH = Path(
    "src/loushang/harness/plugin_management/instance_runtime.py"
)
PACKAGE_LIFECYCLE_PATH = Path(
    "src/loushang/harness/plugin_management/package_lifecycle.py"
)
CONTINUITY_WIRE_PATH = Path(
    "src/loushang/harness/resources/plugins/continuity_provider.py"
)
PLUGIN_AUTHORING_PATHS = (
    Path("src/loushang/harness/plugin_authoring/builder.py"),
    Path("src/loushang/harness/plugin_authoring/semantic_fingerprint.py"),
)


def _contract() -> str:
    return CONTRACT_PATH.read_text(encoding="utf-8")


def test_phase5c_contract_is_indexed_and_marks_runtime_implemented() -> None:
    contract = _contract()
    readme = PLUGIN_README_PATH.read_text(encoding="utf-8")
    declarations = DECLARATIONS_PATH.read_text(encoding="utf-8")

    assert (
        "[Phase 5C Continuity Provider Plugin Lifecycle]"
        "(continuity-provider-phase5c-contract.md)"
    ) in readme
    assert "Current implementation status: implemented" in contract
    assert "runtime slices are not implemented yet" not in readme
    assert '"continuity_provider"' in declarations


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
    assert "architecture, security/lifecycle, and product/test\nreview" in contract


def test_phase5c_keeps_owner_lifecycle_private_and_dependencies_one_way() -> None:
    contract = _contract()
    root = CONTINUITY_ROOT_PATH.read_text(encoding="utf-8")
    runtime = CONTINUITY_RUNTIME_PATH.read_text(encoding="utf-8")
    adapter = CONTINUITY_ADAPTER_PATH.read_text(encoding="utf-8")
    instance_runtime = INSTANCE_RUNTIME_PATH.read_text(encoding="utf-8")
    package_lifecycle = PACKAGE_LIFECYCLE_PATH.read_text(encoding="utf-8")
    wire = CONTINUITY_WIRE_PATH.read_text(encoding="utf-8")

    for private_name in (
        "ContinuityPluginGeneration",
        "ContinuityPluginPublication",
        "ResolvedContinuityPluginSelection",
        "construct_continuity_plugin_generation",
        "publish_continuity_plugin_generation",
        "resolve_continuity_plugin_selection",
    ):
        assert private_name not in root
    assert "loushang.harness.plugin_management" not in runtime
    assert "_ACTIVE_GENERATION_RESERVATIONS" not in runtime
    assert "class ContinuityPluginGenerationAuthority" in runtime
    assert "PluginContinuitySecurityRetirementJournal" in adapter
    assert "PluginInstanceLedgerContinuitySecurityRetirementAuthority" in adapter
    assert "plugin_instance_security_acceptance_journal_path" in instance_runtime
    assert (
        "security_acceptances: PluginInstanceSecurityAcceptanceSourcePort,"
        in instance_runtime
    )
    assert "apply_accepted_security_revocations" in instance_runtime
    assert "instance_runtime_journal_path" in package_lifecycle
    assert "handoff_cleanup_and_release" in adapter
    assert "class ContinuityProviderDeclarationWirePayloadV1" in wire
    for path in PLUGIN_AUTHORING_PATHS:
        source = path.read_text(encoding="utf-8")
        assert "from loushang.harness.continuity" not in source
    semantic = PLUGIN_AUTHORING_PATHS[1].read_text(encoding="utf-8")
    assert "decode_continuity_provider_declaration_payload" in semantic
    assert "`CapabilityComponentCandidate` v2" in contract
    assert "existing first-party and legacy plugin candidates remain v1" in (
        contract.lower()
    )
