"""Source-neutral Plugin contribution semantic fingerprint v1."""

from __future__ import annotations

from dataclasses import replace

import pytest

from loushang.harness.capabilities import (
    CapabilityBundleProvider,
    CapabilityContractRange,
)
from loushang.harness.plugin_authoring.capability_provider import (
    CapabilityProviderDeclarationPayload,
    PluginSymbolReference,
)
from loushang.harness.plugin_authoring.consumer_pack import (
    ToolPackDeclarationPayload,
)
from loushang.harness.plugin_authoring.resource_item import (
    ResourceItemDeclarationPayload,
)
from loushang.harness.plugin_authoring.semantic_fingerprint import (
    PLUGIN_CONTRIBUTION_SEMANTIC_FINGERPRINT_VERSION,
    PluginContributionSemanticFingerprint,
    compile_plugin_contribution_semantic_fingerprint,
)
from loushang.harness.resources.plugins._strict_json import PluginJsonCodecError
from loushang.harness.resources.plugins.declarations import (
    PluginDeclaration,
    PluginDeclarationCodecError,
)

_ZERO_DIGEST = "0" * 64
_ONE_DIGEST = "1" * 64


def test_semantic_fingerprint_compiles_the_exact_resource_record() -> None:
    declaration = _resource_declaration("prompts/编码.md")

    fingerprint = compile_plugin_contribution_semantic_fingerprint(declaration)

    assert PLUGIN_CONTRIBUTION_SEMANTIC_FINGERPRINT_VERSION == 1
    assert fingerprint.to_dict() == {
        "catalogRevisions": [],
        "domain": "loushang.plugin-contribution-semantic/v1",
        "kind": "resource_item",
        "owner": "resources.prompt",
        "payload": declaration.to_dict()["payload"],
        "payloadSchema": {
            "id": "loushang.resource.prompt",
            "version": 1,
        },
    }
    assert fingerprint.digest == (
        "4f2924b72efe84918324a0b37a3c70921b6584a8c390d343bd702d9791e4e1b1"
    )
    assert fingerprint.canonical_bytes.decode("ascii") == (
        '{"catalogRevisions":[],"domain":'
        '"loushang.plugin-contribution-semantic/v1","kind":"resource_item",'
        '"owner":"resources.prompt","payload":{"locator":"prompts/'
        '\\u7f16\\u7801.md","locatorKind":"file","mediaType":"text/markdown",'
        '"ownerNamespace":"resources.prompt","payloadVersion":1,'
        '"resourceKind":"prompt","schemaId":"loushang.resource.prompt",'
        '"schemaVersion":1},"payloadSchema":{"id":'
        '"loushang.resource.prompt","version":1}}'
    )


def test_semantic_fingerprint_excludes_source_and_reservation_provenance() -> None:
    document = _resource_declaration("prompts/standard.md")
    in_process = replace(
        document,
        plugin_id="coding.base.builder",
        contribution_id="prompt-from-builder",
        reservation_fingerprint=_ONE_DIGEST,
        source_descriptor_fingerprint=_ONE_DIGEST,
        source_kind="in_process",
    )

    document_semantic = compile_plugin_contribution_semantic_fingerprint(document)
    in_process_semantic = compile_plugin_contribution_semantic_fingerprint(in_process)

    assert document_semantic.digest == in_process_semantic.digest
    assert document_semantic.canonical_bytes == in_process_semantic.canonical_bytes
    assert document.fingerprint != in_process.fingerprint


def test_catalog_schema_and_revision_are_compiler_derived_from_typed_payload() -> None:
    payload = ToolPackDeclarationPayload(
        catalog_id="harness.workspace.core",
        catalog_revision=7,
        item_ids=("read",),
        owner_namespace="tools.workspace",
    )
    declaration = PluginDeclaration(
        plugin_id="coding.base",
        contribution_id="tool-builtin",
        kind="tool_pack",
        owner="tools.workspace",
        reservation_fingerprint=_ZERO_DIGEST,
        source_descriptor_fingerprint=_ZERO_DIGEST,
        source_kind="document",
        payload=payload.to_dict(),
    )

    fingerprint = compile_plugin_contribution_semantic_fingerprint(declaration)

    assert fingerprint.to_dict()["payloadSchema"] == {
        "id": "tools.workspace.tool-pack",
        "version": 1,
    }
    assert fingerprint.to_dict()["catalogRevisions"] == [
        {"catalog": "harness.workspace.core", "revision": 7}
    ]


def test_semantic_compiler_cannot_bypass_the_strict_kind_payload_codec() -> None:
    payload = ToolPackDeclarationPayload(
        catalog_id="harness.workspace.core",
        catalog_revision=1,
        item_ids=("read",),
        owner_namespace="tools.workspace",
    ).to_dict()
    payload["forgedSchema"] = "caller-owned"
    declaration = PluginDeclaration(
        plugin_id="coding.base",
        contribution_id="coding.builtin",
        kind="tool_pack",
        owner="tools.workspace",
        reservation_fingerprint=_ZERO_DIGEST,
        source_descriptor_fingerprint=_ZERO_DIGEST,
        source_kind="document",
        payload=payload,
    )

    with pytest.raises(PluginDeclarationCodecError) as caught:
        compile_plugin_contribution_semantic_fingerprint(declaration)

    assert caught.value.code == "plugin_declaration_exact_field_mismatch"


def test_capability_provider_uses_owner_qualified_payload_schema() -> None:
    payload = CapabilityProviderDeclarationPayload(
        provider=CapabilityBundleProvider(
            capability_id="coding.lsp",
            provider_id="coding.lsp.default",
            implementation_version=1,
            compatible_contract=CapabilityContractRange.exact(1),
            facets=("semantic",),
            source_id="plugin:coding.lsp.default",
            selection_rule="Plugin declaration candidate",
        ),
        factory=PluginSymbolReference(
            path="provider.py",
            symbol="create_provider",
            execution_model="in_process",
        ),
        disposer=None,
    )
    declaration = PluginDeclaration(
        plugin_id="coding.lsp.default",
        contribution_id="provider",
        kind="capability_provider",
        owner="coding.lsp",
        reservation_fingerprint=_ZERO_DIGEST,
        source_descriptor_fingerprint=_ZERO_DIGEST,
        source_kind="in_process",
        payload=payload.to_dict(),
    )

    fingerprint = compile_plugin_contribution_semantic_fingerprint(declaration)

    assert fingerprint.to_dict()["payloadSchema"] == {
        "id": "coding.lsp.capability-provider",
        "version": 2,
    }
    assert fingerprint.to_dict()["catalogRevisions"] == []


def test_semantic_fingerprint_preserves_unicode_code_points_without_normalizing() -> None:
    precomposed = compile_plugin_contribution_semantic_fingerprint(
        _resource_declaration("prompts/café.md")
    )
    combining = compile_plugin_contribution_semantic_fingerprint(
        _resource_declaration("prompts/cafe\N{COMBINING ACUTE ACCENT}.md")
    )

    assert precomposed.digest == (
        "ca6d0cda904d6289148c26acb48996a90dcfea9012b98ab4002bd3c7b5072928"
    )
    assert combining.digest == (
        "df8f5399b527fa31a2a99fac3e7fb61e04ec057ed92a1fb2e7114f767c8d1023"
    )
    assert precomposed.digest != combining.digest


def test_unpaired_surrogate_cannot_reach_semantic_hashing() -> None:
    payload = ResourceItemDeclarationPayload(
        locator="prompts/invalid\ud800.md",
        locator_kind="file",
        media_type="text/markdown",
        owner_namespace="resources.prompt",
        resource_kind="prompt",
        schema_id="loushang.resource.prompt",
        schema_version=1,
    )

    with pytest.raises(PluginJsonCodecError) as caught:
        PluginDeclaration(
            plugin_id="coding.base",
            contribution_id="prompt-standard",
            kind="resource_item",
            owner="resources.prompt",
            reservation_fingerprint=_ZERO_DIGEST,
            source_descriptor_fingerprint=_ZERO_DIGEST,
            source_kind="document",
            payload=payload.to_dict(),
        )

    assert caught.value.code == "plugin_declaration_field_value_mismatch"


def test_semantic_fingerprint_cannot_be_caller_forged() -> None:
    with pytest.raises(TypeError, match="compiler constructed"):
        PluginContributionSemanticFingerprint()


def _resource_declaration(locator: str) -> PluginDeclaration:
    payload = ResourceItemDeclarationPayload(
        locator=locator,
        locator_kind="file",
        media_type="text/markdown",
        owner_namespace="resources.prompt",
        resource_kind="prompt",
        schema_id="loushang.resource.prompt",
        schema_version=1,
    )
    return PluginDeclaration(
        plugin_id="coding.base",
        contribution_id="prompt-standard",
        kind="resource_item",
        owner="resources.prompt",
        reservation_fingerprint=_ZERO_DIGEST,
        source_descriptor_fingerprint=_ZERO_DIGEST,
        source_kind="document",
        payload=payload.to_dict(),
    )
