from __future__ import annotations

import pytest

from loushang.coding.composition_sets import (
    CODING_KERNEL_PROMPT_REVISION,
    CodingCompositionPluginRequest,
    CodingCompositionSetPlan,
    resolve_coding_composition_set,
)


def test_minimal_set_has_kernel_and_no_optional_plugin_claims() -> None:
    plan = resolve_coding_composition_set("coding-minimal")

    assert plan.composition_chain == ("coding-minimal",)
    assert plan.plugin_requests == ()
    assert plan.kernel_prompt_revision == CODING_KERNEL_PROMPT_REVISION
    assert len(plan.fingerprint) == 64


def test_standard_set_requests_base_and_lazy_lsp_without_live_authority() -> None:
    plan = resolve_coding_composition_set()

    assert plan.set_id == "coding-standard"
    assert plan.composition_chain == ("coding-minimal", "coding-standard")
    assert [item.to_dict() for item in plan.plugin_requests] == [
        {
            "capabilityId": None,
            "mountMode": None,
            "pluginId": "coding.base",
            "pluginKind": "resource",
            "required": True,
        },
        {
            "capabilityId": "coding.lsp",
            "mountMode": "on_demand",
            "pluginId": "coding.lsp.default",
            "pluginKind": "capability_provider",
            "required": False,
        },
    ]
    assert plan.to_dict()["fingerprint"] == plan.fingerprint


def test_architecture_set_is_one_flattened_superset_with_exact_provenance() -> None:
    standard = resolve_coding_composition_set("coding-standard")
    architecture = resolve_coding_composition_set("coding-architecture")

    assert architecture.composition_chain == (
        "coding-minimal",
        "coding-standard",
        "coding-architecture",
    )
    assert {item.plugin_id for item in architecture.plugin_requests} == {
        "coding.base",
        "coding.lsp.default",
        "coding.arch.default",
    }
    assert set(standard.plugin_requests) < set(architecture.plugin_requests)
    assert architecture.fingerprint != standard.fingerprint


@pytest.mark.parametrize(
    "value",
    ["", "standard", "CODING-STANDARD", " unknown ", " coding-standard "],
)
def test_composition_set_rejects_aliases_and_unknown_values(value: str) -> None:
    with pytest.raises(ValueError, match="Unsupported Coding composition set"):
        resolve_coding_composition_set(value)


def test_resource_plugin_request_cannot_smuggle_a_capability_mount() -> None:
    with pytest.raises(
        ValueError,
        match="Resource Plugin cannot declare a Capability mount",
    ):
        CodingCompositionPluginRequest(
            plugin_id="coding.base",
            plugin_kind="resource",
            required=True,
            capability_id="coding.base",
            mount_mode="always",
        )


def test_composition_plan_rejects_duplicate_plugin_or_capability_authority() -> None:
    base = CodingCompositionPluginRequest(
        plugin_id="coding.base",
        plugin_kind="resource",
        required=True,
    )
    with pytest.raises(ValueError, match="Plugin requests must be unique"):
        CodingCompositionSetPlan(
            set_id="coding-standard",
            composition_chain=("coding-minimal", "coding-standard"),
            plugin_requests=(base, base),
        )


def test_composition_set_resolution_is_inert_and_reuses_immutable_plan() -> None:
    first = resolve_coding_composition_set()
    second = resolve_coding_composition_set("coding-standard")

    assert first is second
    assert first.fingerprint == second.fingerprint
