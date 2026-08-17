from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from uuid import UUID

import pytest

from loushang.ontology.facts import (
    AssertionKind,
    FactBatch,
    FactRecord,
    LinkAssertion,
    ObjectAssertion,
    PropertyAssertion,
)
from loushang.ontology.projection import (
    FactOrigin,
    ProjectionMaterializationError,
    materialize_projection,
)
from loushang.ontology.schema import (
    LinkCardinality,
    LinkTypeDefinition,
    ObjectTypeDefinition,
    OntologyCompiler,
    OntologyPackageDraft,
    PropertyDefinition,
    SchemaIdentity,
    StateAuthority,
    ValueType,
)
from loushang.ontology.storage import MemoryFactStore

ASSET_ID = UUID("00000000-0000-0000-0000-000000000001")
OWNER_ID = UUID("00000000-0000-0000-0000-000000000002")
OTHER_ID = UUID("00000000-0000-0000-0000-000000000003")
DEFAULT_SCHEMA_IDENTITY = SchemaIdentity(
    "test.fact-projection",
    "urn:test:fact-projection",
    "1.0.0",
)


def _schema():
    return OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id="test.fact-projection",
            namespace="urn:test:fact-projection",
            version="1.0.0",
            object_types=[
                ObjectTypeDefinition(
                    "Asset",
                    semantic_id="asset",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                    properties=[
                        PropertyDefinition(
                            "code",
                            ValueType.STRING,
                            semantic_id="asset.code",
                            state_authority=StateAuthority.ONTOLOGY_OWNED,
                            required=True,
                            unique=True,
                        ),
                        PropertyDefinition(
                            "score",
                            ValueType.INTEGER,
                            semantic_id="asset.score",
                            state_authority=StateAuthority.ONTOLOGY_OWNED,
                        ),
                        PropertyDefinition(
                            "observed_at",
                            ValueType.DATETIME,
                            semantic_id="asset.observed_at",
                            state_authority=StateAuthority.ONTOLOGY_OWNED,
                        ),
                        PropertyDefinition(
                            "payload",
                            ValueType.JSON,
                            semantic_id="asset.payload",
                            state_authority=StateAuthority.ONTOLOGY_OWNED,
                        ),
                    ],
                ),
                ObjectTypeDefinition(
                    "Owner",
                    semantic_id="owner",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                ),
            ],
            link_types=[
                LinkTypeDefinition(
                    "owned_by",
                    "Asset",
                    "Owner",
                    semantic_id="asset.owned_by",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                    cardinality=LinkCardinality.MANY_TO_ONE,
                )
            ],
        )
    )


def _fact(
    suffix: int,
    subject_id: UUID,
    assertion: object,
    *,
    source_ref: str = "source.erp",
    recorded_at: float = 10.0,
) -> FactRecord:
    return FactRecord(
        fact_id=UUID(f"10000000-0000-0000-0000-{suffix:012d}"),
        subject_id=subject_id,
        schema_identity=DEFAULT_SCHEMA_IDENTITY,
        assertion=assertion,  # type: ignore[arg-type]
        assertion_kind=AssertionKind.ASSERTED,
        source_ref=source_ref,
        source_record_ref=f"record:{suffix}",
        valid_from=0,
        recorded_at=recorded_at,
    )


def _complete_facts() -> list[FactRecord]:
    return [
        _fact(1, ASSET_ID, ObjectAssertion("asset")),
        _fact(2, ASSET_ID, PropertyAssertion("asset.code", "A-1")),
        _fact(3, ASSET_ID, PropertyAssertion("asset.score", 7)),
        _fact(
            4,
            ASSET_ID,
            PropertyAssertion("asset.observed_at", "2026-08-09T00:00:00+00:00"),
        ),
        _fact(5, OWNER_ID, ObjectAssertion("owner")),
        _fact(
            6,
            ASSET_ID,
            LinkAssertion("asset.owned_by", OWNER_ID, {"source": "erp"}),
        ),
    ]


def _materialize(records: list[FactRecord], *, schema=None):
    selected_schema = _schema() if schema is None else schema
    schema_identity = SchemaIdentity.from_schema(selected_schema)
    selected_records = [
        replace(record, schema_identity=schema_identity) for record in records
    ]
    store = MemoryFactStore()
    store.commit_fact_batch(FactBatch("fixture", selected_records))
    return materialize_projection(
        store.select_facts(valid_at=20, recorded_at=20),
        selected_schema,
    )


def test_materializer_builds_an_immutable_reproducible_snapshot() -> None:
    snapshot = _materialize(_complete_facts())

    asset = snapshot.get(ASSET_ID)
    owner = snapshot.get(OWNER_ID)
    assert asset is not None
    assert owner is not None
    assert asset.get("code") == "A-1"
    assert asset.get("score") == 7
    assert asset.get("observed_at") == datetime(2026, 8, 9, tzinfo=UTC)
    assert snapshot.find_neighbors(ASSET_ID, "owned_by") == (owner,)
    assert snapshot.state.fact_watermark == 6
    assert snapshot.state.schema_version == "1.0.0"
    assert snapshot.state.valid_at == 20
    assert snapshot.state.recorded_at == 20
    assert snapshot.fact_ids == tuple(item.fact_id for item in _complete_facts())
    assert asset.origin == FactOrigin(_complete_facts()[0].fact_id)
    assert owner.origin == FactOrigin(_complete_facts()[4].fact_id)
    assert snapshot.links[0].origin == FactOrigin(_complete_facts()[5].fact_id)
    assert asset.property("code").valid_from == 0  # type: ignore[union-attr]
    assert not hasattr(asset, "set")
    assert not hasattr(snapshot, "create")
    with pytest.raises(FrozenInstanceError):
        asset.object_type = "Changed"  # type: ignore[misc]


def test_fact_semantic_ids_survive_api_name_changes() -> None:
    renamed_schema = OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id="test.fact-projection",
            namespace="urn:test:fact-projection",
            version="1.0.0",
            object_types=[
                ObjectTypeDefinition(
                    "Equipment",
                    semantic_id="asset",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                    properties=[
                        PropertyDefinition(
                            "serial_number",
                            ValueType.STRING,
                            semantic_id="asset.code",
                            state_authority=StateAuthority.ONTOLOGY_OWNED,
                        )
                    ],
                )
            ],
        )
    )

    snapshot = _materialize(
        [
            _fact(1, ASSET_ID, ObjectAssertion("asset")),
            _fact(2, ASSET_ID, PropertyAssertion("asset.code", "A-1")),
        ],
        schema=renamed_schema,
    )

    asset = snapshot.get(ASSET_ID)
    assert asset is not None
    assert asset.object_type == "Equipment"
    assert asset.get("serial_number") == "A-1"


def test_materializer_rejects_facts_for_another_schema_identity() -> None:
    foreign_fact = replace(
        _fact(1, ASSET_ID, ObjectAssertion("asset")),
        schema_identity=SchemaIdentity(
            "test.other-fact-projection",
            "urn:test:other-fact-projection",
            "1.0.0",
        ),
    )
    store = MemoryFactStore()
    store.commit_fact_batch(FactBatch("foreign", [foreign_fact]))

    with pytest.raises(ProjectionMaterializationError) as exc_info:
        materialize_projection(
            store.select_facts(valid_at=20, recorded_at=20),
            _schema(),
        )

    assert {item.code for item in exc_info.value.diagnostics} == {
        "fact_schema_identity_mismatch"
    }


def test_projection_json_values_are_detached_and_deterministic() -> None:
    records = _complete_facts()
    records.append(
        _fact(7, ASSET_ID, PropertyAssertion("asset.payload", {"items": [1]}))
    )
    first = _materialize(records)
    second = _materialize(list(reversed(records)))

    first_asset = first.get(ASSET_ID)
    assert first_asset is not None
    exposed = first_asset.get("payload")
    assert isinstance(exposed, dict)
    exposed["items"].append(2)  # type: ignore[union-attr]
    assert first_asset.get("payload") == {"items": [1]}
    assert first.objects == second.objects
    assert first.links == second.links


def test_projection_rejects_conflicting_or_orphaned_facts() -> None:
    records = _complete_facts()
    records.append(
        _fact(
            7,
            ASSET_ID,
            PropertyAssertion("asset.score", 9),
            source_ref="source.other",
        )
    )
    with pytest.raises(ProjectionMaterializationError) as conflict:
        _materialize(records)
    assert "property_fact_conflict" in {
        item.code for item in conflict.value.diagnostics
    }

    with pytest.raises(ProjectionMaterializationError) as orphan:
        _materialize([_fact(1, ASSET_ID, PropertyAssertion("asset.score", 1))])
    assert {item.code for item in orphan.value.diagnostics} == {
        "property_subject_missing"
    }


def test_projection_reports_shape_property_and_endpoint_failures_together() -> None:
    records = [
        _fact(1, ASSET_ID, ObjectAssertion("asset")),
        _fact(2, ASSET_ID, ObjectAssertion("owner"), source_ref="source.other"),
        _fact(3, OWNER_ID, ObjectAssertion("unknown")),
        _fact(4, OTHER_ID, PropertyAssertion("unknown.orphan", 1)),
        _fact(5, ASSET_ID, LinkAssertion("unknown", OWNER_ID)),
    ]
    with pytest.raises(ProjectionMaterializationError) as exc_info:
        _materialize(records)

    assert {item.code for item in exc_info.value.diagnostics} == {
        "link_endpoint_missing",
        "object_type_fact_conflict",
        "property_subject_missing",
        "unknown_object_type",
    }


@pytest.mark.parametrize(
    ("definition", "value"),
    [
        (
            PropertyDefinition(
                "value",
                ValueType.STRING,
                semantic_id="value",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
            ),
            1,
        ),
        (
            PropertyDefinition(
                "value",
                ValueType.INTEGER,
                semantic_id="value",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
            ),
            True,
        ),
        (
            PropertyDefinition(
                "value",
                ValueType.NUMBER,
                semantic_id="value",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
            ),
            "1",
        ),
        (
            PropertyDefinition(
                "value",
                ValueType.BOOLEAN,
                semantic_id="value",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
            ),
            1,
        ),
        (
            PropertyDefinition(
                "value",
                ValueType.DATETIME,
                semantic_id="value",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
            ),
            "not-a-date",
        ),
    ],
)
def test_projection_validates_schema_value_types(
    definition: PropertyDefinition,
    value: object,
) -> None:
    schema = OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id="test.values",
            namespace="urn:test:values",
            version="1.0.0",
            object_types=[
                ObjectTypeDefinition(
                    "Value",
                    semantic_id="value-object",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                    properties=[definition],
                )
            ],
        )
    )
    records = [
        _fact(1, ASSET_ID, ObjectAssertion("value-object")),
        _fact(2, ASSET_ID, PropertyAssertion("value", value)),
    ]

    with pytest.raises(ProjectionMaterializationError) as exc_info:
        _materialize(records, schema=schema)

    assert exc_info.value.diagnostics[0].code == "property_fact_value_invalid"


def test_projection_enforces_required_unique_abstract_and_inherited_properties() -> (
    None
):
    schema = OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id="test.integrity",
            namespace="urn:test:integrity",
            version="1.0.0",
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
                            unique=True,
                        )
                    ],
                    abstract=True,
                ),
                ObjectTypeDefinition(
                    "Asset",
                    semantic_id="asset",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                    parent_types=["Base"],
                ),
            ],
        )
    )
    records = [
        _fact(1, ASSET_ID, ObjectAssertion("asset")),
        _fact(2, OWNER_ID, ObjectAssertion("asset")),
        _fact(3, ASSET_ID, PropertyAssertion("base.code", "same")),
        _fact(4, OWNER_ID, PropertyAssertion("base.code", "same")),
        _fact(5, OTHER_ID, ObjectAssertion("base")),
    ]

    with pytest.raises(ProjectionMaterializationError) as exc_info:
        _materialize(records, schema=schema)

    assert {item.code for item in exc_info.value.diagnostics} == {
        "abstract_object_type",
        "unique_property_conflict",
    }


@pytest.mark.parametrize(
    ("cardinality", "second_source", "second_target", "should_fail"),
    [
        (LinkCardinality.ONE_TO_ONE, True, False, True),
        (LinkCardinality.ONE_TO_MANY, True, False, True),
        (LinkCardinality.MANY_TO_ONE, False, True, True),
        (LinkCardinality.MANY_TO_MANY, True, True, False),
    ],
)
def test_projection_enforces_link_cardinality(
    cardinality: LinkCardinality,
    second_source: bool,
    second_target: bool,
    should_fail: bool,
) -> None:
    target_2 = UUID("00000000-0000-0000-0000-000000000004")
    schema = OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id="test.cardinality",
            namespace="urn:test:cardinality",
            version="1.0.0",
            object_types=[
                ObjectTypeDefinition(
                    "Source",
                    semantic_id="source",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                ),
                ObjectTypeDefinition(
                    "Target",
                    semantic_id="target",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                ),
            ],
            link_types=[
                LinkTypeDefinition(
                    "relates",
                    "Source",
                    "Target",
                    cardinality,
                    semantic_id="source.relates",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                )
            ],
        )
    )
    records = [
        _fact(1, ASSET_ID, ObjectAssertion("source")),
        _fact(2, OTHER_ID, ObjectAssertion("source")),
        _fact(3, OWNER_ID, ObjectAssertion("target")),
        _fact(4, target_2, ObjectAssertion("target")),
        _fact(5, ASSET_ID, LinkAssertion("source.relates", OWNER_ID)),
    ]
    if second_source:
        records.append(
            _fact(6, OTHER_ID, LinkAssertion("source.relates", OWNER_ID))
        )
    if second_target:
        records.append(
            _fact(7, ASSET_ID, LinkAssertion("source.relates", target_2))
        )

    if should_fail:
        with pytest.raises(ProjectionMaterializationError) as exc_info:
            _materialize(records, schema=schema)
        assert exc_info.value.diagnostics[0].code == "link_cardinality_violation"
    else:
        assert len(_materialize(records, schema=schema).links) == 3


def test_projection_enforces_required_links() -> None:
    schema = OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id="test.required-link",
            namespace="urn:test:required-link",
            version="1.0.0",
            object_types=[
                ObjectTypeDefinition(
                    "Source",
                    semantic_id="source",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                ),
                ObjectTypeDefinition(
                    "Target",
                    semantic_id="target",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                ),
            ],
            link_types=[
                LinkTypeDefinition(
                    "target",
                    "Source",
                    "Target",
                    semantic_id="source.target",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                    required=True,
                )
            ],
        )
    )

    with pytest.raises(ProjectionMaterializationError) as exc_info:
        _materialize(
            [_fact(1, ASSET_ID, ObjectAssertion("source"))],
            schema=schema,
        )

    assert exc_info.value.diagnostics[0].code == "required_link_missing"
