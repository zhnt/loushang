"""Versioned ontology schema compiler contracts."""

from __future__ import annotations

import json

import pytest

from loushang.ontology.schema import (
    LinkTypeDefinition,
    ObjectTypeDefinition,
    OntologyCompiler,
    OntologyPackageDraft,
    PropertyDefinition,
    SchemaCompilationError,
    SchemaVersion,
    StateAuthority,
    ValueType,
)


def _project_draft(*, default: object = None) -> OntologyPackageDraft:
    return OntologyPackageDraft(
        package_id="example.project",
        namespace="urn:example:project",
        version=SchemaVersion("1.0.0"),
        object_types=[
            ObjectTypeDefinition(
                name="Project",
                semantic_id="project",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
                properties=[
                    PropertyDefinition(
                        name="name",
                        value_type=ValueType.STRING,
                        semantic_id="project.name",
                        state_authority=StateAuthority.SOURCE_BACKED,
                        required=True,
                        default=default,
                    )
                ],
            ),
            ObjectTypeDefinition(
                name="Task",
                semantic_id="task",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
            ),
        ],
        link_types=[
            LinkTypeDefinition(
                name="contains",
                source_type="Project",
                target_type="Task",
                semantic_id="project.contains_task",
                state_authority=StateAuthority.SOURCE_BACKED,
                cardinality="one_to_many",
            )
        ],
    )


def test_compiler_emits_deterministic_strict_json_and_round_trips() -> None:
    compiler = OntologyCompiler()
    compiled = compiler.compile(_project_draft())

    assert compiled.to_json() == compiler.compile(_project_draft()).to_json()
    assert compiler.load_json(compiled.to_json()) == compiled
    assert compiled.object_type("Project") is not None
    assert compiled.object_type_by_id("project").name == "Project"  # type: ignore[union-attr]
    assert compiled.object_type("Project").property_by_id("project.name") is not None  # type: ignore[union-attr]
    assert compiled.link_type("contains") is not None
    assert compiled.link_type_by_id("project.contains_task") is not None
    assert compiled.object_type_by_id("project").state_authority is (  # type: ignore[union-attr]
        StateAuthority.ONTOLOGY_OWNED
    )
    assert compiled.object_type_by_id("project").property_by_id(  # type: ignore[union-attr]
        "project.name"
    ).state_authority is StateAuthority.SOURCE_BACKED  # type: ignore[union-attr]
    assert compiled.format == "loushang.ontology.schema/v4"


def test_compiled_schema_does_not_share_mutable_default_values() -> None:
    default = {"labels": ["planned"]}
    compiled = OntologyCompiler().compile(_project_draft(default=default))

    default["labels"].append("changed")

    project = compiled.object_type("Project")
    assert project is not None
    assert project.properties[0].default == {"labels": ["planned"]}

    exposed_default = project.properties[0].default
    assert isinstance(exposed_default, dict)
    exposed_default["labels"] = []
    assert project.properties[0].default == {"labels": ["planned"]}


def test_compiler_reports_all_structural_errors_with_stable_codes() -> None:
    draft = OntologyPackageDraft(
        package_id="invalid package",
        namespace="urn:example:invalid",
        version="1.0.0",
        object_types=[
            ObjectTypeDefinition(
                name="Bad Type",
                semantic_id="bad-type",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
                properties=[
                    PropertyDefinition(
                        "payload",
                        "blob",
                        semantic_id="payload",
                        state_authority=StateAuthority.ONTOLOGY_OWNED,
                    ),
                    PropertyDefinition(
                        "payload",
                        ValueType.JSON,
                        semantic_id="payload-copy",
                        state_authority=StateAuthority.ONTOLOGY_OWNED,
                    ),
                ],
            ),
            ObjectTypeDefinition(
                name="Bad Type",
                semantic_id="bad-type-copy",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
            ),
        ],
        link_types=[
            LinkTypeDefinition(
                name="broken",
                source_type="Missing",
                target_type="Bad Type",
                semantic_id="broken",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
                cardinality="sometimes",
            )
        ],
    )

    with pytest.raises(SchemaCompilationError) as captured:
        OntologyCompiler().compile(draft)

    codes = {diagnostic.code for diagnostic in captured.value.diagnostics}
    assert {
        "duplicate_object_type",
        "duplicate_property",
        "invalid_cardinality",
        "invalid_identifier",
        "unknown_link_endpoint",
        "unsupported_value_type",
    } <= codes


def test_compiler_rejects_parent_type_cycles() -> None:
    draft = OntologyPackageDraft(
        package_id="test.parent-cycle",
        namespace="urn:test:parent-cycle",
        version="1.0.0",
        object_types=[
            ObjectTypeDefinition(
                name="A",
                semantic_id="a",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
                parent_types=["B"],
            ),
            ObjectTypeDefinition(
                name="B",
                semantic_id="b",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
                parent_types=["A"],
            ),
        ],
    )

    with pytest.raises(SchemaCompilationError) as captured:
        OntologyCompiler().compile(draft)

    assert [item.code for item in captured.value.diagnostics] == [
        "parent_type_cycle"
    ]


def test_compiler_requires_unique_package_local_semantic_ids() -> None:
    draft = OntologyPackageDraft(
        package_id="test.semantic-ids",
        namespace="urn:test:semantic-ids",
        version="1.0.0",
        object_types=[
            ObjectTypeDefinition(
                "Asset",
                semantic_id="shared",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
                properties=[
                    PropertyDefinition(
                        "code",
                        ValueType.STRING,
                        semantic_id="shared",
                        state_authority=StateAuthority.ONTOLOGY_OWNED,
                    )
                ],
            ),
            ObjectTypeDefinition(
                "MissingId",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
            ),
        ],
    )

    diagnostics = OntologyCompiler().validate(draft)

    assert [(item.code, item.path) for item in diagnostics] == [
        ("duplicate_semantic_id", "$.object_types[0].properties[0].semantic_id"),
        ("invalid_semantic_id", "$.object_types[1].semantic_id"),
    ]


def test_schema_v3_documents_are_not_loaded_as_v4() -> None:
    compiler = OntologyCompiler()
    payload = json.loads(compiler.compile(_project_draft()).to_json())
    payload["format"] = "loushang.ontology.schema/v3"

    with pytest.raises(SchemaCompilationError, match="schema/v4"):
        compiler.load_json(json.dumps(payload))


def test_compiler_requires_explicit_state_authority() -> None:
    draft = OntologyPackageDraft(
        package_id="test.authority",
        namespace="urn:test:authority",
        version="1.0.0",
        object_types=[
            ObjectTypeDefinition(
                "Asset",
                semantic_id="asset",
                properties=[
                    PropertyDefinition(
                        "status",
                        ValueType.STRING,
                        semantic_id="asset.status",
                        state_authority="external",
                    )
                ],
            )
        ],
    )

    assert [
        (item.code, item.path) for item in OntologyCompiler().validate(draft)
    ] == [
        ("invalid_state_authority", "$.object_types[0].state_authority"),
        (
            "invalid_state_authority",
            "$.object_types[0].properties[0].state_authority",
        ),
    ]
