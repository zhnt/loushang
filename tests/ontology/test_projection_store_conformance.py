from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
from threading import Barrier, BrokenBarrierError
from typing import Any
from uuid import UUID

import pytest

from loushang.ontology.facts import (
    AssertionKind,
    FactBatch,
    FactRecord,
    FactStore,
    LinkAssertion,
    ObjectAssertion,
    PropertyAssertion,
)
from loushang.ontology.projection import (
    ProjectionFreshnessStatus,
    ProjectionReadStore,
    ProjectionStore,
    ProjectionUnavailableError,
    evaluate_projection_freshness,
    materialize_projection,
)
from loushang.ontology.query import QueryBuilder
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
from loushang.ontology.storage import (
    MemoryFactStore,
    MemoryProjectionStore,
    SQLiteFactStore,
    SQLiteProjectionStore,
    SQLiteStorageFormatError,
)

ASSET_ID = UUID("00000000-0000-0000-0000-000000000001")
OWNER_ID = UUID("00000000-0000-0000-0000-000000000002")
SCORE_ID = UUID("10000000-0000-0000-0000-000000000003")
SCHEMA_IDENTITY = SchemaIdentity(
    "test.projection-store",
    "urn:test:projection-store",
    "1.0.0",
)


def _schema():
    return OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id="test.projection-store",
            namespace="urn:test:projection-store",
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


def _fact(
    suffix: int,
    subject_id: UUID,
    assertion: object,
    *,
    source_record_ref: str | None = None,
    recorded_at: float = 1,
    supersedes: UUID | None = None,
) -> FactRecord:
    return FactRecord(
        fact_id=UUID(f"10000000-0000-0000-0000-{suffix:012d}"),
        subject_id=subject_id,
        schema_identity=SCHEMA_IDENTITY,
        assertion=assertion,  # type: ignore[arg-type]
        assertion_kind=AssertionKind.ASSERTED,
        source_ref="source.erp",
        source_record_ref=source_record_ref or f"record:{suffix}",
        valid_from=0,
        recorded_at=recorded_at,
        supersedes=supersedes,
    )


def _initial_batch() -> FactBatch:
    return FactBatch(
        "initial",
        [
            _fact(1, ASSET_ID, ObjectAssertion("asset")),
            _fact(2, ASSET_ID, PropertyAssertion("asset.code", "A-1")),
            _fact(
                3,
                ASSET_ID,
                PropertyAssertion("asset.score", 1),
                source_record_ref="asset:A-1:score",
            ),
            _fact(4, OWNER_ID, ObjectAssertion("owner")),
            _fact(5, ASSET_ID, LinkAssertion("asset.owned_by", OWNER_ID)),
        ],
    )


def _score_update() -> FactBatch:
    return FactBatch(
        "score-update",
        [
            _fact(
                6,
                ASSET_ID,
                PropertyAssertion("asset.score", 2),
                source_record_ref="asset:A-1:score",
                recorded_at=20,
                supersedes=SCORE_ID,
            )
        ],
    )


@pytest.fixture(params=("memory", "sqlite"))
def stores(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> Iterator[tuple[FactStore, ProjectionStore]]:
    if request.param == "memory":
        yield MemoryFactStore(), MemoryProjectionStore()
        return
    database = tmp_path / "ontology.sqlite3"
    facts = SQLiteFactStore(database)
    projections = SQLiteProjectionStore(database)
    try:
        yield facts, projections
    finally:
        projections.close()
        facts.close()


def test_projection_adapters_share_the_atomic_replacement_read_contract(
    stores: tuple[FactStore, ProjectionStore],
) -> None:
    facts, projections = stores
    schema = _schema()
    if isinstance(facts, SQLiteFactStore):
        facts.bind_schema(schema)
    facts.commit_fact_batch(_initial_batch())
    snapshot = materialize_projection(
        facts.select_facts(valid_at=10, recorded_at=10),
        schema,
    )

    with pytest.raises(ProjectionUnavailableError):
        projections.all_objects()
    state = projections.replace(snapshot)

    assert isinstance(projections, ProjectionReadStore)
    assert isinstance(projections, ProjectionStore)
    assert state.fact_watermark == 5
    assert projections.read_snapshot().projection_state == state
    assert projections.get(ASSET_ID).get("score") == 1  # type: ignore[union-attr]
    assert projections.find_neighbors(ASSET_ID, "owned_by") == (
        projections.get(OWNER_ID),
    )
    assert QueryBuilder(projections).start_from_type("Asset").execute_ids() == [
        ASSET_ID
    ]
    assert not hasattr(projections, "create")
    assert not hasattr(projections, "set_property")
    assert not hasattr(projections, "link_objects")


def test_projection_rebuild_replaces_the_whole_snapshot_monotonically(
    stores: tuple[FactStore, ProjectionStore],
) -> None:
    facts, projections = stores
    schema = _schema()
    if isinstance(facts, SQLiteFactStore):
        facts.bind_schema(schema)
    facts.commit_fact_batch(_initial_batch())
    first = materialize_projection(
        facts.select_facts(valid_at=10, recorded_at=10),
        schema,
    )
    projections.replace(first)

    rebuilt = materialize_projection(
        facts.select_facts(valid_at=10, recorded_at=10),
        schema,
        projection_version=2,
    )
    projections.replace(rebuilt)

    assert projections.projection_state.projection_version == 2
    assert projections.all_objects() == rebuilt.objects
    with pytest.raises(ValueError, match="projection_version must be 3"):
        projections.replace(rebuilt)


def test_memory_projection_replacement_serializes_competing_writers() -> None:
    facts = MemoryFactStore()
    facts.commit_fact_batch(_initial_batch())
    store = MemoryProjectionStore()
    store.replace(
        materialize_projection(
            facts.select_facts(valid_at=10, recorded_at=10),
            _schema(),
        )
    )
    facts.commit_fact_batch(_score_update())
    first = materialize_projection(
        facts.select_facts(valid_at=30, recorded_at=30),
        _schema(),
        projection_version=2,
        built_at=30,
    )
    second = materialize_projection(
        facts.select_facts(valid_at=30, recorded_at=30),
        _schema(),
        projection_version=2,
        built_at=31,
    )

    barrier = Barrier(2)
    installed = store.read_snapshot()

    class CoordinatedInstalledSnapshot:
        @property
        def state(self):
            with suppress(BrokenBarrierError):
                barrier.wait(timeout=0.5)
            return installed.state

        @property
        def schema(self):
            return installed.schema

    store._snapshot = CoordinatedInstalledSnapshot()  # type: ignore[assignment]

    def replace(snapshot: Any) -> object:
        try:
            return store.replace(snapshot)
        except ValueError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(replace, (first, second)))

    assert sum(not isinstance(item, Exception) for item in outcomes) == 1
    assert sum(isinstance(item, ValueError) for item in outcomes) == 1
    assert store.projection_state.projection_version == 2


def test_projection_state_is_immutable_and_freshness_is_an_explicit_observation(
    stores: tuple[FactStore, ProjectionStore],
) -> None:
    facts, projection = stores
    schema = _schema()
    if isinstance(facts, SQLiteFactStore):
        facts.bind_schema(schema)
    facts.commit_fact_batch(_initial_batch())
    installed = projection.replace(
        materialize_projection(
            facts.select_facts(valid_at=10, recorded_at=10),
            schema,
        )
    )

    facts.commit_fact_batch(_score_update())
    freshness = evaluate_projection_freshness(
        projection.projection_state,
        observed_fact_watermark=facts.fact_watermark,
        observed_at=30,
    )

    assert projection.projection_state == installed
    assert projection.projection_state.fact_watermark == 5
    assert freshness.status is ProjectionFreshnessStatus.STALE
    assert projection.get(ASSET_ID).get("score") == 1  # type: ignore[union-attr]


def test_projection_installation_has_no_adapter_local_freshness_policy(
    stores: tuple[FactStore, ProjectionStore],
) -> None:
    facts, projection = stores
    schema = _schema()
    if isinstance(facts, SQLiteFactStore):
        facts.bind_schema(schema)
    facts.commit_fact_batch(_initial_batch())
    detached = materialize_projection(
        facts.select_facts(valid_at=10, recorded_at=10),
        schema,
    )
    facts.commit_fact_batch(_score_update())

    installed = projection.replace(detached)

    assert installed == detached.state
    assert evaluate_projection_freshness(
        installed,
        observed_fact_watermark=facts.fact_watermark,
        observed_at=30,
    ).status is ProjectionFreshnessStatus.STALE


def test_fact_commit_survives_projection_replacement_failure(tmp_path: Path) -> None:
    database = tmp_path / "ontology.sqlite3"
    schema = _schema()
    facts = SQLiteFactStore(database)
    facts.bind_schema(schema)
    facts.commit_fact_batch(_initial_batch())
    projection = SQLiteProjectionStore(database)
    projection.replace(
        materialize_projection(
            facts.select_facts(valid_at=10, recorded_at=10),
            schema,
        )
    )

    facts.commit_fact_batch(_score_update())
    replacement = materialize_projection(
        facts.select_facts(valid_at=30, recorded_at=30),
        schema,
        projection_version=2,
    )
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TRIGGER reject_projection
            BEFORE UPDATE ON projection_metadata
            BEGIN
                SELECT RAISE(ABORT, 'projection rejected');
            END;
            """
        )

    with pytest.raises(sqlite3.IntegrityError, match="projection rejected"):
        projection.replace(replacement)

    assert facts.fact_watermark == 6
    assert facts.get_fact(UUID("10000000-0000-0000-0000-000000000006"))
    assert projection.get(ASSET_ID).get("score") == 1  # type: ignore[union-attr]
    assert projection.projection_state.projection_version == 1
    assert projection.projection_state.fact_watermark == 5
    assert evaluate_projection_freshness(
        projection.projection_state,
        observed_fact_watermark=facts.fact_watermark,
        observed_at=30,
    ).status is ProjectionFreshnessStatus.STALE

    with sqlite3.connect(database) as connection:
        connection.execute("DROP TRIGGER reject_projection")
    projection.replace(replacement)
    assert projection.get(ASSET_ID).get("score") == 2  # type: ignore[union-attr]
    projection.close()
    facts.close()


def test_sqlite_rejects_corrupt_projection_rows_on_reopen(tmp_path: Path) -> None:
    database = tmp_path / "ontology.sqlite3"
    schema = _schema()
    facts = SQLiteFactStore(database)
    facts.bind_schema(schema)
    facts.commit_fact_batch(_initial_batch())
    projection = SQLiteProjectionStore(database)
    projection.replace(
        materialize_projection(
            facts.select_facts(valid_at=10, recorded_at=10),
            schema,
        )
    )
    projection.close()
    facts.close()
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE projection_properties SET value_json = '{not-json' "
            "WHERE property_name = 'score'"
        )

    with pytest.raises(SQLiteStorageFormatError, match="runtime data"):
        SQLiteProjectionStore(database)
