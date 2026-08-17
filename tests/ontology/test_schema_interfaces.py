from __future__ import annotations

import pytest

from loushang.ontology.schema import (
    ChangeImpact,
    InterfaceTypeDefinition,
    ObjectTypeDefinition,
    OntologyCompiler,
    OntologyPackageDraft,
    PropertyDefinition,
    SchemaCompilationError,
    StateAuthority,
    ValueType,
    compare_schemas,
)


def test_interface_contract_round_trips_and_accepts_inherited_properties() -> None:
    compiler = OntologyCompiler()
    schema = compiler.compile(
        OntologyPackageDraft(
            package_id="test.interfaces",
            namespace="urn:test:interfaces",
            version="1.0.0",
            interface_types=[
                InterfaceTypeDefinition(
                    "Identified",
                    properties=[
                        PropertyDefinition("code", ValueType.STRING, required=True)
                    ],
                )
            ],
            object_types=[
                ObjectTypeDefinition(
                    "Base",
                    semantic_id="base",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                    properties=[
                        PropertyDefinition(
                            "code",
                            ValueType.STRING,
                            semantic_id="base.code",
                            state_authority=StateAuthority.ONTOLOGY_OWNED,
                            required=True,
                        )
                    ],
                    abstract=True,
                ),
                ObjectTypeDefinition(
                    "Asset",
                    semantic_id="asset",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                    parent_types=["Base"],
                    interfaces=["Identified"],
                ),
            ],
        )
    )

    loaded = compiler.load_json(schema.to_json())

    assert loaded == schema
    assert loaded.interface_type("Identified") is not None
    assert loaded.object_type("Asset").interfaces == ("Identified",)  # type: ignore[union-attr]


def test_new_interface_fields_preserve_existing_positional_draft_construction() -> None:
    draft = OntologyPackageDraft(
        "test.positional",
        "urn:test:positional",
        "1.0.0",
        [
            ObjectTypeDefinition(
                "Asset",
                semantic_id="asset",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
            )
        ],
        [],
    )

    schema = OntologyCompiler().compile(draft)

    assert [item.name for item in schema.object_types] == ["Asset"]
    assert schema.interface_types == ()


def test_interface_schema_diff_classifies_contract_and_description_changes() -> None:
    compiler = OntologyCompiler()
    old = compiler.compile(
        OntologyPackageDraft(
            package_id="test.interface-diff",
            namespace="urn:test:interface-diff",
            version="1.0.0",
            interface_types=[
                InterfaceTypeDefinition(
                    "Identified",
                    [PropertyDefinition("code", ValueType.STRING)],
                    description="old",
                )
            ],
        )
    )
    new = compiler.compile(
        OntologyPackageDraft(
            package_id="test.interface-diff",
            namespace="urn:test:interface-diff",
            version="2.0.0",
            interface_types=[
                InterfaceTypeDefinition(
                    "Identified",
                    [PropertyDefinition("code", ValueType.STRING, required=True)],
                    description="new",
                )
            ],
        )
    )

    changes = {item.code: item.impact for item in compare_schemas(old, new).changes}

    assert changes == {
        "interface_contract_changed": ChangeImpact.BREAKING,
        "interface_description_changed": ChangeImpact.BEHAVIORAL,
    }


def test_interface_property_rejects_operational_identity_and_authority() -> None:
    interface = InterfaceTypeDefinition(
        "Identified",
        properties=[
            PropertyDefinition(
                "code",
                ValueType.STRING,
                semantic_id="identified.code",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
            )
        ],
    )

    with pytest.raises(SchemaCompilationError) as exc_info:
        OntologyCompiler().compile(
            OntologyPackageDraft(
                package_id="test.interface-identity",
                namespace="urn:test:interface-identity",
                version="1.0.0",
                interface_types=[interface],
            )
        )

    assert [item.code for item in exc_info.value.diagnostics] == [
        "interface_property_semantic_id_unsupported",
        "interface_property_state_authority_unsupported",
    ]


@pytest.mark.parametrize(
    ("object_type", "code"),
    [
        (
            ObjectTypeDefinition(
                "Asset",
                semantic_id="asset",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
                interfaces=["Missing"],
            ),
            "unknown_interface",
        ),
        (
            ObjectTypeDefinition(
                "Asset",
                semantic_id="asset",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
                interfaces=["Identified"],
            ),
            "interface_property_missing",
        ),
        (
            ObjectTypeDefinition(
                "Asset",
                semantic_id="asset",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
                interfaces=["Identified"],
                properties=[
                    PropertyDefinition(
                        "code",
                        ValueType.INTEGER,
                        semantic_id="asset.code",
                        state_authority=StateAuthority.ONTOLOGY_OWNED,
                        required=True,
                    )
                ],
            ),
            "interface_property_type_mismatch",
        ),
        (
            ObjectTypeDefinition(
                "Asset",
                semantic_id="asset",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
                interfaces=["Identified"],
                properties=[
                    PropertyDefinition(
                        "code",
                        ValueType.STRING,
                        semantic_id="asset.code",
                        state_authority=StateAuthority.ONTOLOGY_OWNED,
                    )
                ],
            ),
            "interface_property_requiredness_mismatch",
        ),
    ],
)
def test_interface_conformance_failures_are_compiler_diagnostics(
    object_type: ObjectTypeDefinition,
    code: str,
) -> None:
    interface = InterfaceTypeDefinition(
        "Identified",
        properties=[PropertyDefinition("code", ValueType.STRING, required=True)],
    )

    with pytest.raises(SchemaCompilationError) as exc_info:
        OntologyCompiler().compile(
            OntologyPackageDraft(
                package_id="test.interfaces",
                namespace="urn:test:interfaces",
                version="1.0.0",
                interface_types=[interface],
                object_types=[object_type],
            )
        )

    assert code in {item.code for item in exc_info.value.diagnostics}
