from __future__ import annotations

from hashlib import sha256

import pytest

from loushang.harness.resources.plugins._strict_json import StrictPluginJsonCodec
from loushang.harness.resources.plugins.declarations import (
    MAX_PLUGIN_DECLARATION_DOCUMENT_BYTES,
    MAX_PLUGIN_DECLARATIONS_PER_DOCUMENT,
    PLUGIN_CONTRIBUTION_INDEX_VERSION,
    PLUGIN_DECLARATION_IR_VERSION,
    PluginContributionIndex,
    PluginContributionReservation,
    PluginDeclaration,
    PluginDeclarationCodecError,
    PluginDeclarationDocument,
    PluginDeclarationDocumentCodec,
    PluginDeclarationSource,
)


def test_source_v1_arms_have_exact_canonical_records_and_stable_fingerprints() -> None:
    document = PluginDeclarationSource.document("declarations/providers.json")
    in_process = PluginDeclarationSource.in_process("provider.py:declare")

    assert document.to_dict() == {
        "kind": "document",
        "locator": "declarations/providers.json",
        "mediaType": "application/vnd.loushang.plugin-declarations+json",
        "schemaId": "loushang.plugin-declaration-document",
        "schemaVersion": 1,
        "sourceVersion": 1,
    }
    assert in_process.to_dict() == {
        "entrypoint": "provider.py:declare",
        "kind": "in_process",
        "sourceVersion": 1,
    }
    assert PluginDeclarationSource.from_dict(document.to_dict()) == document
    assert PluginDeclarationSource.from_dict(in_process.to_dict()) == in_process
    assert document.fingerprint == "f9601a3fabeca727e05d96621c74ea5eb6a1382df4dba3d7796ff15d6b929ce5"
    assert in_process.fingerprint == "d350539f9531be59386163f7427d502677cee4b924a385e7f098a1f69bf64c7f"


def test_index_v2_uses_source_and_independent_contribution_execution_model() -> None:
    source = PluginDeclarationSource.document("declarations/providers.json")
    reservation = PluginContributionReservation(
        contribution_id="review-provider",
        kind="capability_provider",
        owner="coding.lsp",
        declaration_source=source,
        contribution_execution_model="in_process",
        requested_authorities=("process", "workspace.read"),
        configuration={"mode": "review"},
    )
    index = PluginContributionIndex(items=(reservation,))

    assert PLUGIN_CONTRIBUTION_INDEX_VERSION == 2
    assert index.to_dict() == {
        "items": [
            {
                "configuration": {"mode": "review"},
                "contributionExecutionModel": "in_process",
                "declarationSource": source.to_dict(),
                "id": "review-provider",
                "kind": "capability_provider",
                "owner": "coding.lsp",
                "requestedAuthorities": ["process", "workspace.read"],
                "required": True,
            }
        ],
        "version": 2,
    }
    assert PluginContributionIndex.from_dict(index.to_dict()) == index
    assert index.fingerprint == "6e1fdf8680d55d527a32c74989c1a11b9b5605c9d19e180fe0bb188004a52a2a"
    assert reservation.fingerprint == "10e6d52df6a25ad34ef01982c670f4ed5322a3928f77b6705e7e671b6f045944"


def test_declaration_v2_and_document_v1_have_exact_canonical_bytes() -> None:
    source = PluginDeclarationSource.document("declarations/providers.json")
    reservation = PluginContributionReservation(
        contribution_id="review-provider",
        kind="capability_provider",
        owner="coding.lsp",
        declaration_source=source,
        contribution_execution_model="in_process",
        requested_authorities=(),
        configuration={},
    )
    declaration = PluginDeclaration(
        plugin_id="review-pack",
        contribution_id=reservation.contribution_id,
        kind=reservation.kind,
        owner=reservation.owner,
        reservation_fingerprint=reservation.fingerprint,
        source_descriptor_fingerprint=source.fingerprint,
        source_kind=source.kind,
        payload={"payloadVersion": 2},
    )
    document = PluginDeclarationDocument(declarations=(declaration,))
    expected_bytes = StrictPluginJsonCodec.encode(
        {
            "declarations": [declaration.to_dict()],
            "documentVersion": 1,
        }
    )

    assert PLUGIN_DECLARATION_IR_VERSION == 2
    assert PluginDeclaration.from_dict(declaration.to_dict()) == declaration
    assert PluginDeclarationDocumentCodec.encode_bytes(document) == expected_bytes
    assert PluginDeclarationDocumentCodec.decode_bytes(expected_bytes) == document
    assert document.bytes_digest == sha256(expected_bytes).hexdigest()


@pytest.mark.parametrize(
    ("document", "code"),
    [
        (
            {
                "version": 1,
                "items": [],
            },
            "unsupported_plugin_contribution_index_version",
        ),
        (
            {
                "items": [],
            },
            "unsupported_plugin_contribution_index_version",
        ),
    ],
)
def test_index_v1_and_unversioned_shapes_fail_the_exact_version_code(
    document: dict[str, object],
    code: str,
) -> None:
    with pytest.raises(PluginDeclarationCodecError) as caught:
        PluginContributionIndex.from_dict(document)

    assert caught.value.code == code


def test_declaration_and_document_versions_fail_their_own_codes() -> None:
    with pytest.raises(PluginDeclarationCodecError) as caught:
        PluginDeclaration.from_dict({"irVersion": 1})
    assert caught.value.code == "unsupported_plugin_declaration_ir_version"

    with pytest.raises(PluginDeclarationCodecError) as caught:
        PluginDeclarationDocument.from_dict(
            {"declarations": [], "documentVersion": 3}
        )
    assert caught.value.code == "unsupported_plugin_declaration_document_version"


def test_index_rejects_unsorted_items_without_normalizing_wire_order() -> None:
    source = PluginDeclarationSource.in_process("provider.py:declare")

    def item(contribution_id: str) -> dict[str, object]:
        return {
            "configuration": {},
            "contributionExecutionModel": "in_process",
            "declarationSource": source.to_dict(),
            "id": contribution_id,
            "kind": "capability_provider",
            "owner": "coding.lsp",
            "requestedAuthorities": [],
            "required": True,
        }

    with pytest.raises(PluginDeclarationCodecError) as caught:
        PluginContributionIndex.from_dict(
            {"items": [item("z-provider"), item("a-provider")], "version": 2}
        )

    assert caught.value.code == "plugin_contribution_index_unsorted"


def test_document_codec_rejects_duplicate_keys_and_noncanonical_bytes() -> None:
    with pytest.raises(PluginDeclarationCodecError) as caught:
        PluginDeclarationDocumentCodec.decode_bytes(
            b'{"declarations":[],"documentVersion":1,"documentVersion":1}'
        )
    assert caught.value.code == "plugin_declaration_duplicate_json_key"

    source = PluginDeclarationSource.document("declarations/providers.json")
    declaration = PluginDeclaration(
        plugin_id="review-pack",
        contribution_id="review-provider",
        kind="capability_provider",
        owner="coding.lsp",
        reservation_fingerprint="a" * 64,
        source_descriptor_fingerprint=source.fingerprint,
        source_kind=source.kind,
        payload={"payloadVersion": 2},
    )
    canonical = PluginDeclarationDocumentCodec.encode_bytes(
        PluginDeclarationDocument(declarations=(declaration,))
    )
    with pytest.raises(PluginDeclarationCodecError) as caught:
        PluginDeclarationDocumentCodec.decode_bytes(b" " + canonical)
    assert caught.value.code == "plugin_declaration_noncanonical_bytes"


def test_document_codec_enforces_frozen_byte_and_declaration_count_limits() -> None:
    with pytest.raises(PluginDeclarationCodecError) as caught:
        PluginDeclarationDocumentCodec.decode_bytes(
            b" " * (MAX_PLUGIN_DECLARATION_DOCUMENT_BYTES + 1)
        )
    assert caught.value.code == "plugin_declaration_document_too_large"

    source = PluginDeclarationSource.document("declarations/providers.json")
    declaration = PluginDeclaration(
        plugin_id="review-pack",
        contribution_id="review-provider",
        kind="capability_provider",
        owner="coding.lsp",
        reservation_fingerprint="a" * 64,
        source_descriptor_fingerprint=source.fingerprint,
        source_kind=source.kind,
        payload={"payloadVersion": 2},
    )
    encoded = StrictPluginJsonCodec.encode(
        {
            "declarations": [
                declaration.to_dict()
                for _ in range(MAX_PLUGIN_DECLARATIONS_PER_DOCUMENT + 1)
            ],
            "documentVersion": 1,
        }
    )
    with pytest.raises(PluginDeclarationCodecError) as caught:
        PluginDeclarationDocumentCodec.decode_bytes(encoded)
    assert caught.value.code == "plugin_declaration_document_too_many_declarations"
