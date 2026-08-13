from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import UUID

from loushang.ontology.facts import (
    AssertionKind,
    FactBatch,
    FactRecord,
    ObjectAssertion,
    PropertyAssertion,
)
from loushang.ontology.projection import (
    MaterializationCut,
    ProjectionFreshnessStatus,
    ProjectionState,
    evaluate_projection_freshness,
    materialize_projection,
)
from loushang.ontology.schema import (
    ObjectTypeDefinition,
    OntologyCompiler,
    OntologyPackageDraft,
    PropertyDefinition,
    SchemaIdentity,
    StateAuthority,
    ValueType,
)
from loushang.ontology.storage import SQLiteFactStore, SQLiteProjectionStore

ASSET_ID = UUID("00000000-0000-0000-0000-000000000001")
INITIAL_FACT_ID = UUID("10000000-0000-0000-0000-000000000001")
STATUS_FACT_ID = UUID("10000000-0000-0000-0000-000000000002")
UPDATED_STATUS_FACT_ID = UUID("10000000-0000-0000-0000-000000000003")
SCHEMA_IDENTITY = SchemaIdentity(
    "test.materialization-correctness",
    "urn:test:materialization-correctness",
    "1.0.0",
)


def _schema():
    return OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id="test.materialization-correctness",
            namespace="urn:test:materialization-correctness",
            version="1.0.0",
            object_types=[
                ObjectTypeDefinition(
                    "Asset",
                    semantic_id="asset",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                    properties=[
                        PropertyDefinition(
                            "status",
                            ValueType.STRING,
                            semantic_id="asset.status",
                            state_authority=StateAuthority.ONTOLOGY_OWNED,
                        )
                    ],
                )
            ],
        )
    )


def _initial_batch() -> FactBatch:
    return FactBatch(
        "initial",
        [
            FactRecord(
                fact_id=INITIAL_FACT_ID,
                subject_id=ASSET_ID,
                schema_identity=SCHEMA_IDENTITY,
                assertion=ObjectAssertion("asset"),
                assertion_kind=AssertionKind.ASSERTED,
                source_ref="source.erp",
                source_record_ref="asset:A-1",
                valid_from=0,
                recorded_at=1,
            ),
            FactRecord(
                fact_id=STATUS_FACT_ID,
                subject_id=ASSET_ID,
                schema_identity=SCHEMA_IDENTITY,
                assertion=PropertyAssertion("asset.status", "planned"),
                assertion_kind=AssertionKind.ASSERTED,
                source_ref="source.erp",
                source_record_ref="asset:A-1:status",
                valid_from=0,
                recorded_at=1,
            ),
        ],
    )


def _update_batch() -> FactBatch:
    return FactBatch(
        "update",
        [
            FactRecord(
                fact_id=UPDATED_STATUS_FACT_ID,
                subject_id=ASSET_ID,
                schema_identity=SCHEMA_IDENTITY,
                assertion=PropertyAssertion("asset.status", "active"),
                assertion_kind=AssertionKind.ASSERTED,
                source_ref="source.erp",
                source_record_ref="asset:A-1:status",
                valid_from=0,
                recorded_at=20,
                supersedes=STATUS_FACT_ID,
            )
        ],
    )


def _enable_wal(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode = WAL").fetchone() == ("wal",)


def test_projection_freshness_is_a_pure_comparison_over_build_coordinates() -> None:
    schema_identity = SchemaIdentity(
        "test.materialization-correctness",
        "urn:test:materialization-correctness",
        "1.0.0",
    )
    state = ProjectionState(
        schema_identity=schema_identity,
        projection_version=1,
        materialization_cut=MaterializationCut(
            schema_identity=schema_identity,
            source_inputs=(),
            fact_watermark=2,
            valid_at=10,
            recorded_at=10,
        ),
        built_at=10,
    )

    unknown = evaluate_projection_freshness(
        state,
        observed_fact_watermark=None,
        observed_at=11,
    )
    current = evaluate_projection_freshness(
        state,
        observed_fact_watermark=2,
        observed_at=12,
    )
    stale = evaluate_projection_freshness(
        state,
        observed_fact_watermark=3,
        observed_at=13,
    )
    degraded = evaluate_projection_freshness(
        state,
        observed_fact_watermark=1,
        observed_at=14,
    )

    assert unknown.status is ProjectionFreshnessStatus.UNKNOWN
    assert current.status is ProjectionFreshnessStatus.CURRENT
    assert stale.status is ProjectionFreshnessStatus.STALE
    assert degraded.status is ProjectionFreshnessStatus.DEGRADED
    assert degraded.diagnostics == (
        "observed Fact watermark is behind the projection build watermark",
    )
    assert state.fact_watermark == 2


def test_sqlite_fact_selection_keeps_facts_and_watermark_in_one_read_snapshot(
    tmp_path: Path,
) -> None:
    database = tmp_path / "facts.sqlite3"
    schema = _schema()
    initializer = SQLiteFactStore(database)
    initializer.bind_schema(schema)
    initializer.commit_fact_batch(_initial_batch())
    initializer.close()
    _enable_wal(database)

    reader = SQLiteFactStore(database, expected_schema=schema)
    writer = SQLiteFactStore(database, expected_schema=schema)
    interleaved = False

    def commit_between_selection_reads(statement: str) -> None:
        nonlocal interleaved
        if interleaved or "key = 'fact_watermark'" not in statement:
            return
        interleaved = True
        writer.commit_fact_batch(_update_batch())

    reader._connection.set_trace_callback(commit_between_selection_reads)
    selection = reader.select_facts(valid_at=10, recorded_at=10)
    reader._connection.set_trace_callback(None)

    assert interleaved is True
    assert selection.fact_watermark == 2
    assert [item.fact.fact_id for item in selection.facts] == [
        INITIAL_FACT_ID,
        STATUS_FACT_ID,
    ]
    assert writer.fact_watermark == 3
    reader.close()
    writer.close()


def test_sqlite_projection_reconstruction_reads_one_projection_version(
    tmp_path: Path,
) -> None:
    database = tmp_path / "projection.sqlite3"
    schema = _schema()
    facts = SQLiteFactStore(database)
    facts.bind_schema(schema)
    facts.commit_fact_batch(_initial_batch())
    first = materialize_projection(
        facts.select_facts(valid_at=10, recorded_at=10),
        schema,
    )
    projection = SQLiteProjectionStore(database)
    projection.replace(first)
    projection.close()
    facts.close()
    _enable_wal(database)

    facts = SQLiteFactStore(database, expected_schema=schema)
    facts.commit_fact_batch(_update_batch())
    second = materialize_projection(
        facts.select_facts(valid_at=30, recorded_at=30),
        schema,
        projection_version=2,
    )
    writer = SQLiteProjectionStore(database, expected_schema=schema)
    reader = SQLiteProjectionStore(database, expected_schema=schema)
    interleaved = False

    def replace_between_projection_reads(statement: str) -> None:
        nonlocal interleaved
        if interleaved or "SELECT COUNT(*) FROM projection_objects" not in statement:
            return
        interleaved = True
        writer.replace(second)

    reader._connection.set_trace_callback(replace_between_projection_reads)
    captured = reader.read_snapshot()
    reader._connection.set_trace_callback(None)

    assert interleaved is True
    assert captured.state.projection_version == 1
    assert captured.get(ASSET_ID).get("status") == "planned"  # type: ignore[union-attr]
    assert writer.read_snapshot().state.projection_version == 2
    assert writer.get(ASSET_ID).get("status") == "active"  # type: ignore[union-attr]
    reader.close()
    writer.close()
    facts.close()
