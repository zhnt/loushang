"""Strict Capability Provider Plugin payload contracts."""

from __future__ import annotations

from copy import deepcopy

import pytest

from loushang.harness.capabilities import (
    CapabilityBundleProvider,
    CapabilityContractRange,
    CapabilityRequirement,
)
from loushang.harness.plugin_authoring.capability_provider import (
    CAPABILITY_PROVIDER_PAYLOAD_VERSION,
    CapabilityProviderDeclarationPayload,
    PluginSymbolReference,
    capability_bundle_provider_from_dict,
    capability_bundle_provider_to_dict,
    capability_contract_range_from_dict,
    capability_contract_range_to_dict,
    capability_requirement_from_dict,
    capability_requirement_to_dict,
)
from loushang.harness.resources.plugins.declarations import PluginDeclaration


def test_capability_contract_and_requirement_codecs_are_strict_and_canonical() -> None:
    contract = CapabilityContractRange(minimum=1, maximum=2)
    requirement = CapabilityRequirement(
        capability="harness.workspace",
        facets=("process.launch", "read"),
        compatible_contract=contract,
        optional=True,
        binding="stable_reference",
    )

    contract_document = {"maximum": 2, "minimum": 1}
    requirement_document = {
        "binding": "stable_reference",
        "capability": "harness.workspace",
        "compatibleContract": contract_document,
        "facets": ["process.launch", "read"],
        "optional": True,
    }

    assert capability_contract_range_to_dict(contract) == contract_document
    assert capability_contract_range_from_dict(contract_document) == contract
    assert capability_requirement_to_dict(requirement) == requirement_document
    assert capability_requirement_from_dict(requirement_document) == requirement

    with pytest.raises(ValueError, match="fields"):
        capability_contract_range_from_dict({**contract_document, "unknown": 1})
    with pytest.raises(ValueError, match="canonical sorted order"):
        capability_requirement_from_dict(
            {**requirement_document, "facets": ["read", "process.launch"]}
        )
    with pytest.raises(ValueError, match="fields"):
        capability_requirement_from_dict(
            {**requirement_document, "unknown": True}
        )


def test_provider_and_payload_codecs_roundtrip_exact_semantic_types() -> None:
    provider = _provider()
    provider_document = _provider_document()
    payload_document = _payload_document()

    assert capability_bundle_provider_to_dict(provider) == provider_document
    assert capability_bundle_provider_from_dict(provider_document) == provider

    payload = CapabilityProviderDeclarationPayload.from_dict(payload_document)

    assert payload.provider == provider
    assert payload.to_dict() == payload_document
    assert CapabilityProviderDeclarationPayload.from_dict(payload.to_dict()) == payload
    assert (
        payload.fingerprint
        == "c81e94aad73a9840a14ac53887f6e8c194a45020e1e8d238fc42c376bfc8ed41"
    )
    assert (
        payload.binding_input_fingerprint
        == "cceb5d9f67c407f9ef9328f5eec7ce7138d2957fc169ac3418b0fe687eeac7f5"
    )
    with pytest.raises(TypeError):
        payload.binding_inputs["mode"] = "changed"  # type: ignore[index]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update({"unknown": True}), "fields"),
        (
            lambda value: value["provider"].update({"unknown": True}),
            "fields",
        ),
        (
            lambda value: value["provider"].update(
                {"facets": ["tools", "semantic", "diagnostics"]}
            ),
            "canonical sorted order",
        ),
        (
            lambda value: value["provider"].update(
                {
                    "requirements": [
                        value["provider"]["requirements"][0],
                        value["provider"]["requirements"][0],
                    ]
                }
            ),
            "repeat a capability identity",
        ),
        (
            lambda value: value["factory"].update({"path": "../provider.py"}),
            "contained relative Python path",
        ),
        (
            lambda value: value["factory"].update({"path": "/provider.py"}),
            "contained relative Python path",
        ),
        (
            lambda value: value["factory"].update({"packageDigest": "bad"}),
            "SHA-256",
        ),
        (
            lambda value: value["factory"].update({"executionModel": "worker"}),
            "execution model",
        ),
        (
            lambda value: value.update(
                {"configurationFingerprint": "not-a-digest"}
            ),
            "SHA-256",
        ),
        (
            lambda value: value.update({"payloadVersion": 2}),
            "payload version",
        ),
    ],
)
def test_capability_provider_payload_rejects_noncanonical_documents(
    mutation: object,
    message: str,
) -> None:
    document = deepcopy(_payload_document())
    assert callable(mutation)
    mutation(document)

    with pytest.raises((TypeError, ValueError), match=message):
        CapabilityProviderDeclarationPayload.from_dict(document)


def test_payload_rejects_callable_and_non_json_binding_inputs() -> None:
    provider = _provider()
    factory = PluginSymbolReference(
        path="provider.py",
        symbol="create_provider",
        package_digest="a" * 64,
        execution_model="in_process",
    )

    with pytest.raises(ValueError, match="JSON"):
        CapabilityProviderDeclarationPayload(
            provider=provider,
            factory=factory,
            disposer=None,
            binding_inputs={"factory": lambda: None},
            configuration_fingerprint="b" * 64,
        )
    with pytest.raises(ValueError, match="canonical JSON"):
        CapabilityProviderDeclarationPayload(
            provider=provider,
            factory=factory,
            disposer=None,
            binding_inputs={"notFinite": float("nan")},
            configuration_fingerprint="b" * 64,
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("capabilityId", "coding.arch", "owner"),
        ("sourceId", "plugin:forged", "source id"),
        ("selectionRule", "forged", "selection rule"),
    ],
)
def test_plugin_declaration_rejects_payload_identity_mismatch(
    field: str,
    value: str,
    message: str,
) -> None:
    payload = _payload_document()
    provider = payload["provider"]
    assert isinstance(provider, dict)
    provider[field] = value

    declaration = PluginDeclaration(
        plugin_id="review-pack",
        contribution_id="review-provider",
        kind="capability_provider",
        owner="coding.lsp",
        reservation_fingerprint="d" * 64,
        payload=payload,
    )

    with pytest.raises(ValueError, match=message):
        CapabilityProviderDeclarationPayload.from_declaration(declaration)


def _provider() -> CapabilityBundleProvider:
    return CapabilityBundleProvider(
        capability_id="coding.lsp",
        provider_id="org.loushang.coding-lsp/default",
        implementation_version=1,
        compatible_contract=CapabilityContractRange.exact(1),
        facets=("diagnostics", "semantic", "tools"),
        requirements=(
            CapabilityRequirement(
                capability="harness.workspace",
                facets=("process.launch", "read"),
                compatible_contract=CapabilityContractRange.exact(1),
            ),
        ),
        required_authorities=frozenset({"process"}),
        source_id="plugin:review-pack",
        selection_rule="Plugin declaration candidate",
    )


def _provider_document() -> dict[str, object]:
    return {
        "capabilityId": "coding.lsp",
        "compatibleContract": {"maximum": 1, "minimum": 1},
        "facets": ["diagnostics", "semantic", "tools"],
        "implementationVersion": 1,
        "providerId": "org.loushang.coding-lsp/default",
        "requiredAuthorities": ["process"],
        "requirements": [
            {
                "binding": "direct",
                "capability": "harness.workspace",
                "compatibleContract": {"maximum": 1, "minimum": 1},
                "facets": ["process.launch", "read"],
                "optional": False,
            }
        ],
        "selectionRule": "Plugin declaration candidate",
        "sourceId": "plugin:review-pack",
    }


def _payload_document() -> dict[str, object]:
    return {
        "bindingInputs": {"mode": "review"},
        "configurationFingerprint": "b" * 64,
        "disposer": {
            "executionModel": "in_process",
            "packageDigest": "a" * 64,
            "path": "provider.py",
            "symbol": "dispose_provider",
        },
        "factory": {
            "executionModel": "in_process",
            "packageDigest": "a" * 64,
            "path": "provider.py",
            "symbol": "create_provider",
        },
        "payloadVersion": CAPABILITY_PROVIDER_PAYLOAD_VERSION,
        "provider": _provider_document(),
    }
