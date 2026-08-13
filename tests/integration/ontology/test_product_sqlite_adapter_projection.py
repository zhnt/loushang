from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from loushang.ontology.deployment import (
    DeploymentProfile,
    SourceInstanceSelection,
    lock_identity_crosswalk,
    lock_schema_artifact,
    lock_source_adapter_artifact,
    validate_deployment_profile,
)
from loushang.ontology.facts import (
    AssertionKind,
    FactBatch,
    FactRecord,
    PropertyAssertion,
)
from loushang.ontology.identity import (
    IdentityCrosswalkSnapshot,
    IdentityResolution,
    IdentityResolutionError,
    IdentityResolutionStatus,
)
from loushang.ontology.projection import (
    FactOrigin,
    ProjectionFreshnessStatus,
    SchemaDefaultOrigin,
    SourceOrigin,
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
    StateAuthority,
    ValueType,
)
from loushang.ontology.source import SourceAdapter, validate_source_adapter_outputs
from loushang.ontology.storage import MemoryFactStore, SQLiteProjectionStore
from tests.integration.ontology.fixtures.sqlite_erp_adapter import (
    ERP_BINDING_ID,
    TARGET_SCHEMA_IDENTITY,
    SQLiteErpAssetAdapter,
    advance_sqlite_erp_source,
    erp_asset_source_identity,
    erp_owner_source_identity,
    initialize_sqlite_erp_source,
)
from tests.integration.ontology.fixtures.sqlite_maintenance_adapter import (
    MAINTENANCE_BINDING_ID,
    SQLiteMaintenanceAssetAdapter,
    initialize_sqlite_maintenance_source,
    maintenance_asset_source_identity,
)

ERP_SOURCE_INSTANCE_ID = "erp:reference-bureau"
MAINTENANCE_SOURCE_INSTANCE_ID = "maintenance:reference-bureau"
ASSET_ID = UUID("00000000-0000-0000-0000-000000000101")
OWNER_ID = UUID("00000000-0000-0000-0000-000000000102")
OTHER_ASSET_ID = UUID("00000000-0000-0000-0000-000000000103")
REVIEW_FACT_ID = UUID("10000000-0000-0000-0000-000000000101")


def _schema():
    return OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id=TARGET_SCHEMA_IDENTITY.package_id,
            namespace=TARGET_SCHEMA_IDENTITY.namespace,
            version=TARGET_SCHEMA_IDENTITY.version,
            object_types=(
                ObjectTypeDefinition(
                    "Asset",
                    semantic_id="asset",
                    state_authority=StateAuthority.SOURCE_BACKED,
                    properties=(
                        PropertyDefinition(
                            "code",
                            ValueType.STRING,
                            semantic_id="asset.code",
                            state_authority=StateAuthority.SOURCE_BACKED,
                            required=True,
                            indexed=True,
                        ),
                        PropertyDefinition(
                            "maintenance_status",
                            ValueType.STRING,
                            semantic_id="asset.maintenance-status",
                            state_authority=StateAuthority.SOURCE_BACKED,
                            required=True,
                        ),
                        PropertyDefinition(
                            "review_status",
                            ValueType.STRING,
                            semantic_id="asset.review-status",
                            state_authority=StateAuthority.ONTOLOGY_OWNED,
                            required=True,
                        ),
                        PropertyDefinition(
                            "classification",
                            ValueType.STRING,
                            semantic_id="asset.classification",
                            state_authority=StateAuthority.ONTOLOGY_OWNED,
                            default="unclassified",
                        ),
                    ),
                ),
                ObjectTypeDefinition(
                    "Owner",
                    semantic_id="owner",
                    state_authority=StateAuthority.SOURCE_BACKED,
                    properties=(
                        PropertyDefinition(
                            "name",
                            ValueType.STRING,
                            semantic_id="owner.name",
                            state_authority=StateAuthority.SOURCE_BACKED,
                            required=True,
                        ),
                    ),
                ),
            ),
            link_types=(
                LinkTypeDefinition(
                    "owned_by",
                    "Asset",
                    "Owner",
                    semantic_id="asset.owned-by",
                    state_authority=StateAuthority.SOURCE_BACKED,
                ),
            ),
        )
    )


def _fact_selection():
    facts = MemoryFactStore()
    facts.commit_fact_batch(
        FactBatch(
            "reference-review",
            (
                FactRecord(
                    fact_id=REVIEW_FACT_ID,
                    subject_id=ASSET_ID,
                    schema_identity=TARGET_SCHEMA_IDENTITY,
                    assertion=PropertyAssertion(
                        "asset.review-status",
                        "approved",
                    ),
                    assertion_kind=AssertionKind.ASSERTED,
                    source_ref="reference.review-office",
                    source_record_ref="approval:101",
                    valid_from=2,
                    recorded_at=3,
                    author_ref="user:reviewer",
                ),
            ),
        )
    )
    return facts.select_facts(valid_at=10, recorded_at=10)


def _identity_crosswalk() -> IdentityCrosswalkSnapshot:
    return IdentityCrosswalkSnapshot(
        deployment_id="reference-bureau",
        identity_namespace="urn:loushang:reference-bureau",
        revision="identity-revision:1",
        entries=(
            IdentityResolution(
                source_identity=erp_asset_source_identity(
                    ERP_SOURCE_INSTANCE_ID,
                    "A-1",
                ),
                status=IdentityResolutionStatus.CONFIRMED,
                canonical_object_id=ASSET_ID,
                resolution_ref="identity-decision:asset-A-1",
            ),
            IdentityResolution(
                source_identity=erp_owner_source_identity(
                    ERP_SOURCE_INSTANCE_ID,
                    "O-1",
                ),
                status=IdentityResolutionStatus.CONFIRMED,
                canonical_object_id=OWNER_ID,
                resolution_ref="identity-decision:owner-O-1",
            ),
            IdentityResolution(
                source_identity=maintenance_asset_source_identity(
                    MAINTENANCE_SOURCE_INSTANCE_ID,
                    "EQ-009",
                ),
                status=IdentityResolutionStatus.CONFIRMED,
                canonical_object_id=ASSET_ID,
                resolution_ref="identity-decision:equipment-EQ-009",
            ),
        ),
    )


def test_product_sqlite_adapter_reaches_a_restartable_typed_projection(
    tmp_path: Path,
) -> None:
    source_database = tmp_path / "erp.sqlite3"
    maintenance_database = tmp_path / "maintenance.sqlite3"
    projection_database = tmp_path / "ontology.sqlite3"
    initialize_sqlite_erp_source(source_database)
    initialize_sqlite_maintenance_source(maintenance_database)
    identity_crosswalk = _identity_crosswalk()
    erp_adapter = SQLiteErpAssetAdapter(
        source_database,
        source_instance_id=ERP_SOURCE_INSTANCE_ID,
        identity_resolver=identity_crosswalk,
    )
    maintenance_adapter = SQLiteMaintenanceAssetAdapter(
        maintenance_database,
        source_instance_id=MAINTENANCE_SOURCE_INSTANCE_ID,
        identity_resolver=identity_crosswalk,
    )
    adapters = (erp_adapter, maintenance_adapter)
    schema = _schema()
    assert all(isinstance(adapter, SourceAdapter) for adapter in adapters)
    assert str(source_database) not in erp_adapter.manifest.to_json()
    assert str(maintenance_database) not in maintenance_adapter.manifest.to_json()
    assert identity_crosswalk.deployment_id == "reference-bureau"
    profile = DeploymentProfile(
        deployment_id="reference-bureau",
        schema_lock=lock_schema_artifact(schema),
        adapter_locks=tuple(
            lock_source_adapter_artifact(adapter.manifest) for adapter in adapters
        ),
        source_instances=(
            SourceInstanceSelection(
                ERP_SOURCE_INSTANCE_ID,
                erp_adapter.manifest.adapter_id,
                (ERP_BINDING_ID,),
            ),
            SourceInstanceSelection(
                MAINTENANCE_SOURCE_INSTANCE_ID,
                maintenance_adapter.manifest.adapter_id,
                (MAINTENANCE_BINDING_ID,),
            ),
        ),
        identity_crosswalk_lock=lock_identity_crosswalk(identity_crosswalk),
        fact_store_ref="store:reference-facts",
        projection_store_ref="store:reference-projection",
    )
    source_bindings = validate_deployment_profile(
        profile,
        schema=schema,
        adapter_manifests=tuple(adapter.manifest for adapter in adapters),
        identity_crosswalk=identity_crosswalk,
    )

    source_inputs = tuple(
        adapter.read_snapshot(binding.binding_id)
        for adapter in adapters
        for binding in adapter.manifest.bindings
    )
    observed_heads = tuple(
        adapter.observe_head(binding.binding_id)
        for adapter in adapters
        for binding in adapter.manifest.bindings
    )
    for adapter in adapters:
        binding_ids = {binding.binding_id for binding in adapter.manifest.bindings}
        validate_source_adapter_outputs(
            adapter.manifest,
            source_inputs=tuple(
                item for item in source_inputs if item.binding_id in binding_ids
            ),
            observed_heads=tuple(
                item for item in observed_heads if item.binding_id in binding_ids
            ),
        )

    selection = _fact_selection()
    snapshot = materialize_projection(
        selection,
        schema,
        source_bindings=source_bindings,
        source_inputs=source_inputs,
        built_at=11,
    )
    assert (
        materialize_projection(
            selection,
            schema,
            source_bindings=tuple(reversed(source_bindings)),
            source_inputs=tuple(reversed(source_inputs)),
            built_at=11,
        )
        == snapshot
    )
    installed = SQLiteProjectionStore(projection_database)
    installed.replace(snapshot)
    installed.close()

    reopened = SQLiteProjectionStore(
        projection_database,
        expected_schema=schema,
    )
    assert reopened.read_snapshot() == snapshot
    asset = (
        QueryBuilder(reopened)
        .start_from_type("Asset")
        .where("code", "==", "A-1")
        .execute_first()
    )
    assert asset is not None
    assert asset.id == ASSET_ID
    assert asset.get("maintenance_status") == "serviceable"
    assert asset.get("review_status") == "approved"
    assert asset.get("classification") == "unclassified"
    assert isinstance(asset.origin, SourceOrigin)
    review_status = asset.property("review_status")
    classification = asset.property("classification")
    maintenance_status = asset.property("maintenance_status")
    assert review_status is not None
    assert review_status.origin == FactOrigin(REVIEW_FACT_ID)
    assert classification is not None
    assert classification.origin == SchemaDefaultOrigin(TARGET_SCHEMA_IDENTITY)
    assert maintenance_status is not None
    assert maintenance_status.origin == SourceOrigin(
        binding_id=MAINTENANCE_BINDING_ID,
        mapping_version="reference-maintenance-mapping/v1",
        source_revision="maintenance-transaction:3",
        source_record_ref="equipment:EQ-009",
        field_ref="maintenance_assets.maintenance_status",
    )
    owner = QueryBuilder(reopened).start_from(asset).follow("owned_by").execute_first()
    assert owner is not None
    assert owner.id == OWNER_ID
    assert owner.get("name") == "Operations"

    advance_sqlite_erp_source(source_database)
    freshness = evaluate_projection_freshness(
        reopened.projection_state,
        observed_fact_watermark=selection.fact_watermark,
        observed_source_heads=(
            erp_adapter.observe_head(ERP_BINDING_ID),
            maintenance_adapter.observe_head(MAINTENANCE_BINDING_ID),
        ),
        observed_at=12,
    )
    assert freshness.status is ProjectionFreshnessStatus.STALE
    installed_asset = reopened.get(ASSET_ID)
    assert installed_asset is not None
    assert installed_asset.get("code") == "A-1"
    reopened.close()


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (IdentityResolutionStatus.UNRESOLVED, "identity_unresolved"),
        (IdentityResolutionStatus.CONFLICT, "identity_conflict"),
    ],
)
def test_product_adapter_refuses_unresolved_or_conflicting_identity(
    tmp_path: Path,
    status: IdentityResolutionStatus,
    code: str,
) -> None:
    database = tmp_path / f"maintenance-{status.value}.sqlite3"
    initialize_sqlite_maintenance_source(database)
    source_identity = maintenance_asset_source_identity(
        MAINTENANCE_SOURCE_INSTANCE_ID,
        "EQ-009",
    )
    resolution = IdentityResolution(
        source_identity=source_identity,
        status=status,
        candidate_object_ids=(ASSET_ID, OTHER_ASSET_ID)
        if status is IdentityResolutionStatus.CONFLICT
        else (),
        resolution_ref=f"identity-review:{status.value}",
    )
    adapter = SQLiteMaintenanceAssetAdapter(
        database,
        source_instance_id=MAINTENANCE_SOURCE_INSTANCE_ID,
        identity_resolver=IdentityCrosswalkSnapshot(
            deployment_id="reference-bureau",
            identity_namespace="urn:loushang:reference-bureau",
            revision="identity-revision:ambiguous",
            entries=(resolution,),
        ),
    )

    with pytest.raises(IdentityResolutionError) as exc_info:
        adapter.read_snapshot(MAINTENANCE_BINDING_ID)

    assert exc_info.value.code == code


def test_same_source_key_in_another_instance_does_not_reuse_identity(
    tmp_path: Path,
) -> None:
    database = tmp_path / "maintenance-other-instance.sqlite3"
    initialize_sqlite_maintenance_source(database)
    adapter = SQLiteMaintenanceAssetAdapter(
        database,
        source_instance_id="maintenance:another-bureau",
        identity_resolver=_identity_crosswalk(),
    )

    with pytest.raises(IdentityResolutionError) as exc_info:
        adapter.read_snapshot(MAINTENANCE_BINDING_ID)

    assert exc_info.value.code == "identity_missing"
