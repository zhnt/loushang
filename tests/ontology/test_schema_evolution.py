"""Deterministic, offline ontology schema evolution tests."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from loushang.ontology.schema import (
    ChangeImpact,
    CompiledOntologySchema,
    LinkTypeDefinition,
    ObjectTypeDefinition,
    OntologyCompiler,
    OntologyPackageDraft,
    PropertyDefinition,
    SchemaLineageError,
    StateAuthority,
    ValueType,
    compare_schemas,
)


def _compiled(
    *,
    package_id: str = "test.evolution",
    namespace: str = "urn:test:evolution",
    version: str = "1.0.0",
    object_types: list[ObjectTypeDefinition] | None = None,
    link_types: list[LinkTypeDefinition] | None = None,
) -> CompiledOntologySchema:
    object_types = [
        replace(
            object_type,
            semantic_id=object_type.semantic_id or object_type.name,
            state_authority=(
                object_type.state_authority or StateAuthority.ONTOLOGY_OWNED
            ),
            properties=tuple(
                replace(
                    prop,
                    semantic_id=prop.semantic_id or prop.name,
                    state_authority=(
                        prop.state_authority or StateAuthority.ONTOLOGY_OWNED
                    ),
                )
                for prop in object_type.properties
            ),
        )
        for object_type in (object_types or [])
    ]
    link_types = [
        replace(
            link,
            semantic_id=link.semantic_id or link.name,
            state_authority=(
                link.state_authority or StateAuthority.ONTOLOGY_OWNED
            ),
        )
        for link in (link_types or [])
    ]
    compiler = OntologyCompiler()
    schema = compiler.compile(
        OntologyPackageDraft(
            package_id=package_id,
            namespace=namespace,
            version=version,
            object_types=object_types or [],
            link_types=link_types or [],
        )
    )
    return compiler.load_json(schema.to_json())


def test_equal_loaded_schemas_produce_an_empty_diff() -> None:
    old = _compiled(
        version="1.0.0",
        object_types=[
            ObjectTypeDefinition(
                "Project",
                properties=[PropertyDefinition("name", ValueType.STRING)],
            )
        ],
    )
    new = _compiled(
        version="1.1.0",
        object_types=[
            ObjectTypeDefinition(
                "Project",
                properties=[PropertyDefinition("name", ValueType.STRING)],
            )
        ],
    )

    diff = compare_schemas(old, new)

    assert diff.is_empty
    assert diff.changes == ()
    assert diff.highest_impact is None
    assert diff.has_breaking_changes is False
    assert diff.from_version.value == "1.0.0"
    assert diff.to_version.value == "1.1.0"
    assert json.loads(diff.to_json())["changes"] == []


def test_declaration_order_does_not_affect_diff_or_json() -> None:
    project = ObjectTypeDefinition(
        "Project",
        properties=[
            PropertyDefinition("name", ValueType.STRING),
            PropertyDefinition("budget", ValueType.NUMBER),
        ],
    )
    task = ObjectTypeDefinition("Task")
    milestone = ObjectTypeDefinition("Milestone")
    contains = LinkTypeDefinition("contains", "Project", "Task")
    tracks = LinkTypeDefinition("tracks", "Project", "Milestone")
    old = _compiled(
        object_types=[project, task, milestone],
        link_types=[contains, tracks],
    )
    reordered = _compiled(
        version="1.1.0",
        object_types=[
            milestone,
            task,
            ObjectTypeDefinition(
                "Project",
                properties=[
                    PropertyDefinition("budget", ValueType.NUMBER),
                    PropertyDefinition("name", ValueType.STRING),
                ],
            ),
        ],
        link_types=[tracks, contains],
    )

    first = compare_schemas(old, reordered)
    second = compare_schemas(old, reordered)

    assert first.is_empty
    assert first.to_json() == second.to_json()


def test_stable_ids_distinguish_renames_from_identity_replacement() -> None:
    old = _compiled(
        object_types=[
            ObjectTypeDefinition(
                "Project",
                semantic_id="project-type",
                properties=[
                    PropertyDefinition(
                        "name",
                        ValueType.STRING,
                        semantic_id="project-name",
                    )
                ],
            )
        ]
    )
    renamed_type = _compiled(
        version="2.0.0",
        object_types=[
            ObjectTypeDefinition(
                "Initiative",
                semantic_id="project-type",
                properties=[
                    PropertyDefinition(
                        "name",
                        ValueType.STRING,
                        semantic_id="project-name",
                    )
                ],
            )
        ],
    )
    renamed_property = _compiled(
        version="2.0.0",
        object_types=[
            ObjectTypeDefinition(
                "Project",
                semantic_id="project-type",
                properties=[
                    PropertyDefinition(
                        "title",
                        ValueType.STRING,
                        semantic_id="project-name",
                    )
                ],
            )
        ],
    )

    assert [change.code for change in compare_schemas(old, renamed_type).changes] == [
        "object_type_name_changed",
    ]
    assert [change.code for change in compare_schemas(old, renamed_property).changes] == [
        "property_name_changed",
    ]

    replaced_identity = _compiled(
        version="2.0.0",
        object_types=[ObjectTypeDefinition("Project", semantic_id="replacement")],
    )
    assert [
        change.code for change in compare_schemas(old, replaced_identity).changes
    ] == ["object_type_removed", "object_type_added"]


def test_link_type_rename_is_matched_by_stable_id() -> None:
    object_types = [ObjectTypeDefinition("Project"), ObjectTypeDefinition("Task")]
    old = _compiled(
        object_types=object_types,
        link_types=[
            LinkTypeDefinition(
                "contains",
                "Project",
                "Task",
                semantic_id="project-task-link",
            )
        ],
    )
    new = _compiled(
        version="2.0.0",
        object_types=object_types,
        link_types=[
            LinkTypeDefinition(
                "includes",
                "Project",
                "Task",
                semantic_id="project-task-link",
            )
        ],
    )

    changes = compare_schemas(old, new).changes

    assert [(item.code, item.impact) for item in changes] == [
        ("link_type_name_changed", ChangeImpact.BREAKING)
    ]


def test_state_authority_changes_are_explicit_and_breaking() -> None:
    old = _compiled(
        object_types=[
            ObjectTypeDefinition(
                "Project",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
                properties=[
                    PropertyDefinition(
                        "status",
                        ValueType.STRING,
                        state_authority=StateAuthority.SOURCE_BACKED,
                    )
                ],
            ),
            ObjectTypeDefinition("Task"),
        ],
        link_types=[
            LinkTypeDefinition(
                "contains",
                "Project",
                "Task",
                state_authority=StateAuthority.SOURCE_BACKED,
            )
        ],
    )
    new = _compiled(
        version="2.0.0",
        object_types=[
            ObjectTypeDefinition(
                "Project",
                state_authority=StateAuthority.SOURCE_BACKED,
                properties=[
                    PropertyDefinition(
                        "status",
                        ValueType.STRING,
                        state_authority=StateAuthority.DERIVED,
                    )
                ],
            ),
            ObjectTypeDefinition("Task"),
        ],
        link_types=[
            LinkTypeDefinition(
                "contains",
                "Project",
                "Task",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
            )
        ],
    )

    changes = compare_schemas(old, new).changes

    assert {(item.code, item.impact) for item in changes} == {
        ("object_existence_authority_changed", ChangeImpact.BREAKING),
        ("property_state_authority_changed", ChangeImpact.BREAKING),
        ("link_state_authority_changed", ChangeImpact.BREAKING),
    }


def test_different_packages_cannot_be_compared() -> None:
    old = _compiled(package_id="test.old")
    new = _compiled(package_id="test.new", version="2.0.0")

    with pytest.raises(SchemaLineageError, match="test.old.*test.new"):
        compare_schemas(old, new)


def test_breaking_changes_have_stable_codes_and_paths() -> None:
    old = _compiled(
        object_types=[
            ObjectTypeDefinition(
                "Project",
                properties=[PropertyDefinition("name", ValueType.STRING)],
            ),
            ObjectTypeDefinition("Removed"),
            ObjectTypeDefinition("Target"),
            ObjectTypeDefinition("Other"),
        ],
        link_types=[
            LinkTypeDefinition(
                "contains",
                "Project",
                "Target",
                cardinality="one_to_many",
            )
        ],
    )
    new = _compiled(
        version="2.0.0",
        object_types=[
            ObjectTypeDefinition(
                "Project",
                properties=[
                    PropertyDefinition(
                        "name",
                        ValueType.INTEGER,
                        required=True,
                    )
                ],
                parent_types=["Target"],
                abstract=True,
            ),
            ObjectTypeDefinition("Target"),
            ObjectTypeDefinition("Other"),
        ],
        link_types=[
            LinkTypeDefinition(
                "contains",
                "Other",
                "Project",
                cardinality="one_to_one",
            )
        ],
    )

    changes = {
        (change.code, change.path, change.impact)
        for change in compare_schemas(old, new).changes
    }

    assert {
        (
            "object_type_removed",
            '$.object_types["Removed"]',
            ChangeImpact.BREAKING,
        ),
        (
            "object_type_abstract_tightened",
            '$.object_types["Project"].abstract',
            ChangeImpact.BREAKING,
        ),
        (
            "object_type_parents_changed",
            '$.object_types["Project"].parent_types',
            ChangeImpact.BREAKING,
        ),
        (
            "property_value_type_changed",
            '$.object_types["Project"].properties["name"].value_type',
            ChangeImpact.BREAKING,
        ),
        (
            "property_required_tightened",
            '$.object_types["Project"].properties["name"].required',
            ChangeImpact.BREAKING,
        ),
        (
            "link_source_type_changed",
            '$.link_types["contains"].source_type',
            ChangeImpact.BREAKING,
        ),
        (
            "link_target_type_changed",
            '$.link_types["contains"].target_type',
            ChangeImpact.BREAKING,
        ),
        (
            "link_cardinality_changed",
            '$.link_types["contains"].cardinality',
            ChangeImpact.BREAKING,
        ),
    } <= changes
    assert compare_schemas(old, new).has_breaking_changes is True
    assert compare_schemas(old, new).highest_impact is ChangeImpact.BREAKING


def test_non_breaking_and_behavioral_changes_are_classified() -> None:
    old = _compiled(
        object_types=[
            ObjectTypeDefinition(
                "Project",
                properties=[
                    PropertyDefinition(
                        "name",
                        ValueType.STRING,
                        required=True,
                    )
                ],
                abstract=True,
            ),
            ObjectTypeDefinition("Task"),
        ],
        link_types=[
            LinkTypeDefinition("contains", "Project", "Task", required=True)
        ],
    )
    new = _compiled(
        version="1.1.0",
        object_types=[
            ObjectTypeDefinition(
                "Project",
                properties=[
                    PropertyDefinition(
                        "name",
                        ValueType.STRING,
                        required=False,
                        default="untitled",
                        indexed=True,
                        description="Display name",
                    ),
                    PropertyDefinition("budget", ValueType.NUMBER),
                ],
                abstract=False,
                icon="project",
                description="A project",
                display_name_property="name",
            ),
            ObjectTypeDefinition("Task"),
            ObjectTypeDefinition("Milestone"),
        ],
        link_types=[
            LinkTypeDefinition(
                "contains",
                "Project",
                "Task",
                inverse_name="part_of",
                temporal=False,
                description="Contains tasks",
            ),
            LinkTypeDefinition("tracks", "Project", "Milestone"),
        ],
    )

    changes = compare_schemas(old, new).changes
    impacts = {change.code: change.impact for change in changes}

    assert impacts["object_type_added"] is ChangeImpact.NON_BREAKING
    assert impacts["property_added"] is ChangeImpact.NON_BREAKING
    assert impacts["property_required_relaxed"] is ChangeImpact.NON_BREAKING
    assert impacts["object_type_abstract_relaxed"] is ChangeImpact.NON_BREAKING
    assert impacts["link_type_added"] is ChangeImpact.NON_BREAKING
    assert impacts["property_default_changed"] is ChangeImpact.BEHAVIORAL
    assert impacts["property_indexed_changed"] is ChangeImpact.BEHAVIORAL
    assert impacts["property_description_changed"] is ChangeImpact.BEHAVIORAL
    assert impacts["object_type_icon_changed"] is ChangeImpact.BEHAVIORAL
    assert impacts["object_type_description_changed"] is ChangeImpact.BEHAVIORAL
    assert impacts["object_type_display_name_changed"] is ChangeImpact.BEHAVIORAL
    assert impacts["link_inverse_name_changed"] is ChangeImpact.BEHAVIORAL
    assert impacts["link_temporal_changed"] is ChangeImpact.BEHAVIORAL
    assert impacts["link_description_changed"] is ChangeImpact.BEHAVIORAL
    assert impacts["link_required_relaxed"] is ChangeImpact.NON_BREAKING
    assert compare_schemas(old, new).highest_impact is ChangeImpact.BEHAVIORAL


def test_unique_tightening_is_breaking_and_relaxing_is_non_breaking() -> None:
    without_unique = _compiled(
        object_types=[
            ObjectTypeDefinition(
                "Project",
                properties=[PropertyDefinition("name", ValueType.STRING)],
            )
        ]
    )
    with_unique = _compiled(
        version="2.0.0",
        object_types=[
            ObjectTypeDefinition(
                "Project",
                properties=[
                    PropertyDefinition("name", ValueType.STRING, unique=True)
                ],
            )
        ],
    )

    tightened = compare_schemas(without_unique, with_unique).changes
    relaxed = compare_schemas(with_unique, without_unique).changes

    assert [(item.code, item.impact) for item in tightened] == [
        ("property_unique_changed", ChangeImpact.BREAKING)
    ]
    assert [(item.code, item.impact) for item in relaxed] == [
        ("property_unique_changed", ChangeImpact.NON_BREAKING)
    ]


def test_remaining_breaking_changes_have_stable_codes_and_paths() -> None:
    old = _compiled(
        namespace="urn:test:old",
        object_types=[
            ObjectTypeDefinition(
                "Project",
                properties=[PropertyDefinition("legacy", ValueType.STRING)],
            ),
            ObjectTypeDefinition("Task"),
            ObjectTypeDefinition("Milestone"),
        ],
        link_types=[
            LinkTypeDefinition("contains", "Project", "Task"),
            LinkTypeDefinition("removed_link", "Project", "Milestone"),
        ],
    )
    new = _compiled(
        namespace="urn:test:new",
        version="2.0.0",
        object_types=[
            ObjectTypeDefinition(
                "Project",
                properties=[
                    PropertyDefinition(
                        "required_new",
                        ValueType.STRING,
                        required=True,
                    )
                ],
            ),
            ObjectTypeDefinition("Task"),
            ObjectTypeDefinition("Milestone"),
        ],
        link_types=[
            LinkTypeDefinition(
                "contains",
                "Project",
                "Task",
                required=True,
            ),
            LinkTypeDefinition(
                "required_new_link",
                "Project",
                "Milestone",
                required=True,
            ),
        ],
    )

    changes = {
        (change.code, change.path, change.impact)
        for change in compare_schemas(old, new).changes
    }

    assert {
        ("namespace_changed", "$.namespace", ChangeImpact.BREAKING),
        (
            "property_removed",
            '$.object_types["Project"].properties["legacy"]',
            ChangeImpact.BREAKING,
        ),
        (
            "required_property_added",
            '$.object_types["Project"].properties["required_new"]',
            ChangeImpact.BREAKING,
        ),
        (
            "link_required_tightened",
            '$.link_types["contains"].required',
            ChangeImpact.BREAKING,
        ),
        (
            "link_type_removed",
            '$.link_types["removed_link"]',
            ChangeImpact.BREAKING,
        ),
        (
            "required_link_type_added",
            '$.link_types["required_new_link"]',
            ChangeImpact.BREAKING,
        ),
    } <= changes


def test_diff_json_is_strict_stable_and_detached() -> None:
    old = _compiled(
        object_types=[ObjectTypeDefinition("Project")],
    )
    new = _compiled(
        version="1.1.0",
        object_types=[
            ObjectTypeDefinition(
                "Project",
                properties=[
                    PropertyDefinition(
                        "labels",
                        ValueType.JSON,
                        default={"items": ["planned"]},
                    )
                ],
            )
        ],
    )

    diff = compare_schemas(old, new)
    payload = diff.to_json()
    exposed = diff.changes[0].after
    assert isinstance(exposed, dict)
    exposed["default"] = None

    assert diff.to_json() == payload
    assert json.loads(payload)["format"] == "loushang.ontology.schema-diff/v4"
    assert json.loads(payload)["package_id"] == "test.evolution"
