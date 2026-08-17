from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from uuid import UUID

import pytest

from loushang.ontology.facts import (
    AssertionKind,
    FactBatch,
    FactRecord,
    ObjectAssertion,
    PropertyAssertion,
)
from loushang.ontology.projection import (
    FactSchemaRevalidationReceipt,
    FactSchemaRevalidationStatus,
    ProjectionMaterializationError,
    materialize_projection,
    revalidate_fact_selection,
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
from loushang.ontology.storage import MemoryFactStore, SQLiteProjectionStore

ASSET_ID = UUID("00000000-0000-0000-0000-000000000001")
OLD_IDENTITY = SchemaIdentity(
    "test.fact-revalidation",
    "urn:test:fact-revalidation",
    "1.0.0",
)


def _schema(
    *,
    version: str,
    namespace: str = "urn:test:fact-revalidation",
    object_name: str = "Asset",
    property_name: str = "code",
    require_status: bool = False,
):
    properties = [
        PropertyDefinition(
            property_name,
            ValueType.STRING,
            semantic_id="asset.code",
            state_authority=StateAuthority.ONTOLOGY_OWNED,
        )
    ]
    if require_status:
        properties.append(
            PropertyDefinition(
                "status",
                ValueType.STRING,
                semantic_id="asset.status",
                state_authority=StateAuthority.ONTOLOGY_OWNED,
                required=True,
            )
        )
    return OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id="test.fact-revalidation",
            namespace=namespace,
            version=version,
            object_types=[
                ObjectTypeDefinition(
                    object_name,
                    semantic_id="asset",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                    properties=properties,
                )
            ],
        )
    )


def _selection():
    store = MemoryFactStore()
    store.commit_fact_batch(
        FactBatch(
            "asset",
            [
                FactRecord(
                    fact_id=UUID("10000000-0000-0000-0000-000000000001"),
                    subject_id=ASSET_ID,
                    schema_identity=OLD_IDENTITY,
                    assertion=ObjectAssertion("asset"),
                    assertion_kind=AssertionKind.ASSERTED,
                    source_ref="test",
                    source_record_ref="asset:A-1",
                    valid_from=0,
                    recorded_at=1,
                ),
                FactRecord(
                    fact_id=UUID("10000000-0000-0000-0000-000000000002"),
                    subject_id=ASSET_ID,
                    schema_identity=OLD_IDENTITY,
                    assertion=PropertyAssertion("asset.code", "A-1"),
                    assertion_kind=AssertionKind.ASSERTED,
                    source_ref="test",
                    source_record_ref="asset:A-1:code",
                    valid_from=0,
                    recorded_at=1,
                ),
            ],
        )
    )
    return store.select_facts(valid_at=10, recorded_at=10)


def test_rename_only_upgrade_reuses_original_facts_with_an_exact_receipt(
    tmp_path: Path,
) -> None:
    source = _schema(version="1.0.0")
    target = _schema(
        version="2.0.0",
        object_name="Equipment",
        property_name="serial_number",
    )
    selection = _selection()

    receipt = revalidate_fact_selection(selection, source, target)

    assert receipt.status is FactSchemaRevalidationStatus.ACCEPTED
    assert receipt.diagnostics == ()
    assert receipt.schema_change_codes == (
        "object_type_name_changed",
        "property_name_changed",
    )
    assert FactSchemaRevalidationReceipt.from_json(receipt.to_json()) == receipt
    assert all(
        item.fact.schema_identity == OLD_IDENTITY for item in selection.facts
    )
    with pytest.raises(ProjectionMaterializationError) as missing_receipt:
        materialize_projection(selection, target)
    assert {item.code for item in missing_receipt.value.diagnostics} == {
        "fact_schema_identity_mismatch"
    }

    snapshot = materialize_projection(
        selection,
        target,
        fact_revalidation=receipt,
    )
    asset = snapshot.get(ASSET_ID)
    assert asset is not None
    assert asset.object_type == "Equipment"
    assert asset.get("serial_number") == "A-1"
    assert (
        snapshot.state.materialization_cut.fact_revalidation_digest
        == receipt.receipt_digest
    )

    database = tmp_path / "projection.sqlite3"
    stored = SQLiteProjectionStore(database)
    stored.replace(snapshot)
    stored.close()
    reopened = SQLiteProjectionStore(database, expected_schema=target)
    assert reopened.read_snapshot() == snapshot
    reopened.close()


def test_upgrade_blocks_data_that_does_not_satisfy_the_target_schema() -> None:
    source = _schema(version="1.0.0")
    target = _schema(version="2.0.0", require_status=True)
    selection = _selection()

    receipt = revalidate_fact_selection(selection, source, target)

    assert receipt.status is FactSchemaRevalidationStatus.BLOCKED
    assert {item.code for item in receipt.diagnostics} == {
        "required_property_missing"
    }
    with pytest.raises(ProjectionMaterializationError) as exc_info:
        materialize_projection(
            selection,
            target,
            fact_revalidation=receipt,
        )
    assert [item.code for item in exc_info.value.diagnostics] == [
        "fact_revalidation_invalid"
    ]


def test_receipt_is_bound_to_the_exact_selection_and_target_content() -> None:
    source = _schema(version="1.0.0")
    target = _schema(version="2.0.0")
    selection = _selection()
    receipt = revalidate_fact_selection(selection, source, target)

    changed_cut = replace(selection, recorded_at=11)
    with pytest.raises(ProjectionMaterializationError, match="coordinates"):
        materialize_projection(
            changed_cut,
            target,
            fact_revalidation=receipt,
        )
    changed_target_content = _schema(
        version="2.0.0",
        object_name="Equipment",
    )
    with pytest.raises(ProjectionMaterializationError, match="content"):
        materialize_projection(
            selection,
            changed_target_content,
            fact_revalidation=receipt,
        )


def test_namespace_change_is_blocked_and_unversioned_content_change_is_invalid() -> (
    None
):
    source = _schema(version="1.0.0")
    namespace_target = _schema(
        version="2.0.0",
        namespace="urn:test:other-fact-revalidation",
    )
    receipt = revalidate_fact_selection(_selection(), source, namespace_target)
    assert receipt.status is FactSchemaRevalidationStatus.BLOCKED
    assert [item.code for item in receipt.diagnostics] == ["namespace_changed"]

    same_identity_changed_content = _schema(
        version="1.0.0",
        object_name="Equipment",
    )
    with pytest.raises(ValueError, match="without changing.*schema identity"):
        revalidate_fact_selection(
            _selection(),
            source,
            same_identity_changed_content,
        )
