from __future__ import annotations

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
from loushang.ontology.projection import materialize_projection
from loushang.ontology.query import (
    PropertyFilter,
    QueryBuilder,
    QueryRequest,
    StartFromType,
)
from loushang.ontology.query.engine import execute_query
from loushang.ontology.schema import (
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

SELECTED_ID = UUID("00000000-0000-0000-0000-000000000001")
OTHER_ID = UUID("00000000-0000-0000-0000-000000000002")
OWNER_ID = UUID("00000000-0000-0000-0000-000000000003")
SCHEMA_IDENTITY = SchemaIdentity("test.query", "urn:test:query", "2.0.0")


def _projected_assets():
    schema = OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id="test.query",
            namespace="urn:test:query",
            version="2.0.0",
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
                            indexed=True,
                        ),
                        PropertyDefinition(
                            "score",
                            ValueType.INTEGER,
                            semantic_id="asset.score",
                            state_authority=StateAuthority.ONTOLOGY_OWNED,
                        ),
                    ],
                ),
                ObjectTypeDefinition(
                    "Owner",
                    semantic_id="owner",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                    properties=[
                        PropertyDefinition(
                            "name",
                            ValueType.STRING,
                            semantic_id="owner.name",
                            state_authority=StateAuthority.ONTOLOGY_OWNED,
                        )
                    ],
                ),
            ],
            link_types=[
                LinkTypeDefinition(
                    "owned_by",
                    "Asset",
                    "Owner",
                    semantic_id="asset.owned_by",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                )
            ],
        )
    )
    records = [
        _fact(1, SELECTED_ID, ObjectAssertion("asset")),
        _fact(2, SELECTED_ID, PropertyAssertion("asset.code", "A-1")),
        _fact(3, SELECTED_ID, PropertyAssertion("asset.score", 5)),
        _fact(4, OTHER_ID, ObjectAssertion("asset")),
        _fact(5, OTHER_ID, PropertyAssertion("asset.code", "A-2")),
        _fact(6, OTHER_ID, PropertyAssertion("asset.score", 1)),
        _fact(7, OWNER_ID, ObjectAssertion("owner")),
        _fact(8, OWNER_ID, PropertyAssertion("owner.name", "Operations")),
        _fact(9, SELECTED_ID, LinkAssertion("asset.owned_by", OWNER_ID)),
    ]
    facts = MemoryFactStore()
    facts.commit_fact_batch(FactBatch("query-fixture", records))
    return materialize_projection(
        facts.select_facts(valid_at=10, recorded_at=10),
        schema,
    )


def _fact(suffix: int, subject_id: UUID, assertion: object) -> FactRecord:
    return FactRecord(
        fact_id=UUID(f"10000000-0000-0000-0000-{suffix:012d}"),
        subject_id=subject_id,
        schema_identity=SCHEMA_IDENTITY,
        assertion=assertion,  # type: ignore[arg-type]
        assertion_kind=AssertionKind.ASSERTED,
        source_ref="source.query-fixture",
        source_record_ref=f"record:{suffix}",
        valid_from=0,
        recorded_at=1,
    )


def test_typed_query_reports_schema_and_projection_build_coordinates() -> None:
    projection = _projected_assets()

    result = execute_query(
        projection,
        QueryRequest(
            schema_identity=SCHEMA_IDENTITY,
            steps=(
                StartFromType("Asset"),
                PropertyFilter("score", ">=", 5),
            ),
        ),
    )

    assert result.object_ids == (SELECTED_ID,)
    assert result.schema_identity == projection.state.schema_identity
    assert result.projection.fact_watermark == 9
    assert result.diagnostics == ()


def test_query_schema_mismatch_is_visible_without_returning_objects() -> None:
    projection = _projected_assets()

    result = execute_query(
        projection,
        QueryRequest(
            schema_identity=SchemaIdentity(
                "another.package",
                "urn:another:package",
                "2.0.0",
            ),
            steps=(StartFromType("Asset"),),
        ),
    )

    assert result.object_ids == ()
    assert [diagnostic.code for diagnostic in result.diagnostics] == [
        "schema_identity_mismatch"
    ]


def test_query_builder_operates_only_on_a_projection_view() -> None:
    projection = _projected_assets()

    result = (
        QueryBuilder(projection)
        .start_from_type("Asset")
        .where("score", ">", 1)
        .execute_result()
    )

    assert result.object_ids == (SELECTED_ID,)
    assert result.projection.fact_watermark == 9


def test_query_builder_covers_read_only_traversal_sort_and_window_operations() -> None:
    projection = _projected_assets()
    selected = projection.get(SELECTED_ID)
    assert selected is not None

    owners = (
        QueryBuilder(projection)
        .start_from(selected)
        .follow("owned_by")
        .where("name", "==", "Operations")
    )
    assert owners.execute_ids() == [OWNER_ID]
    assert owners.execute_count() == 1
    assert owners.execute_exists() is True
    assert owners.execute_first() == projection.get(OWNER_ID)

    window = (
        QueryBuilder(projection)
        .start_all()
        .where_type("Asset")
        .sort_by("score", ascending=False)
        .offset(1)
        .limit(1)
    )
    assert window.execute_ids() == [OTHER_ID]

    incoming = (
        QueryBuilder(projection)
        .start_from(OWNER_ID)
        .follow("owned_by", direction="incoming")
        .execute_ids()
    )
    assert incoming == [SELECTED_ID]


@pytest.mark.parametrize(
    ("operator", "value", "expected"),
    [
        ("!=", "A-1", (OTHER_ID,)),
        ("<", 5, (OTHER_ID,)),
        ("<=", 1, (OTHER_ID,)),
        (">", 1, (SELECTED_ID,)),
        (">=", 5, (SELECTED_ID,)),
        ("in", ("A-1",), (SELECTED_ID,)),
        ("contains", "A-", (SELECTED_ID, OTHER_ID)),
    ],
)
def test_query_property_operators(
    operator: str,
    value: object,
    expected: tuple[UUID, ...],
) -> None:
    projection = _projected_assets()
    property_name = "score" if operator in {"<", "<=", ">", ">="} else "code"

    result = execute_query(
        projection,
        QueryRequest(
            steps=(
                StartFromType("Asset"),
                PropertyFilter(property_name, operator, value),
            )
        ),
    )

    assert result.object_ids == expected


def test_query_rejects_an_unknown_operator() -> None:
    projection = _projected_assets()

    with pytest.raises(ValueError, match="Unsupported operator"):
        execute_query(
            projection,
            QueryRequest(
                steps=(
                    StartFromType("Asset"),
                    PropertyFilter("score", "approximately", 5),
                )
            ),
        )
