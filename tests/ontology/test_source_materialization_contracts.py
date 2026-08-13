from __future__ import annotations

from uuid import UUID

import pytest

from loushang.ontology.facts import (
    AssertionKind,
    FactBatch,
    FactRecord,
    FactSelection,
    LinkAssertion,
    ObjectAssertion,
    PropertyAssertion,
)
from loushang.ontology.projection import (
    MaterializationCut,
    ProjectionFreshnessStatus,
    ProjectionMaterializationError,
    ProjectionState,
    SourceOrigin,
    evaluate_projection_freshness,
    materialize_projection,
)
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
from loushang.ontology.source import (
    MappedSourceInput,
    MappedSourceLink,
    MappedSourceObject,
    MappedSourceProperty,
    MappedSourceSnapshot,
    SourceBinding,
    SourceCoverage,
    SourceInputCut,
    SourceInputRevision,
)
from loushang.ontology.storage import MemoryFactStore

ASSET_ID = UUID("00000000-0000-0000-0000-000000000001")
OWNER_ID = UUID("00000000-0000-0000-0000-000000000002")
SOURCE_SCHEMA_IDENTITY = SchemaIdentity(
    "test.source-contracts",
    "urn:test:source-contracts",
    "1.0.0",
)


def _empty_selection() -> FactSelection:
    return FactSelection(facts=(), fact_watermark=0, valid_at=10, recorded_at=10)


def _source_schema():
    return OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id="test.source-contracts",
            namespace="urn:test:source-contracts",
            version="1.0.0",
            object_types=[
                ObjectTypeDefinition(
                    "Asset",
                    semantic_id="asset",
                    state_authority=StateAuthority.SOURCE_BACKED,
                    properties=[
                        PropertyDefinition(
                            "code",
                            ValueType.STRING,
                            semantic_id="asset.code",
                            state_authority=StateAuthority.SOURCE_BACKED,
                        )
                    ],
                ),
                ObjectTypeDefinition(
                    "Owner",
                    semantic_id="owner",
                    state_authority=StateAuthority.SOURCE_BACKED,
                ),
            ],
            link_types=[
                LinkTypeDefinition(
                    "owned_by",
                    "Asset",
                    "Owner",
                    semantic_id="asset.owned-by",
                    state_authority=StateAuthority.SOURCE_BACKED,
                )
            ],
        )
    )


def _empty_input(
    binding_id: str,
    *,
    mapping_version: str,
) -> MappedSourceInput:
    return MappedSourceInput(
        binding_id=binding_id,
        mapping_version=mapping_version,
        source_revision="revision-1",
        coverage=SourceCoverage.COMPLETE,
        payload=MappedSourceSnapshot(),
    )


def _codes(call) -> set[str]:
    with pytest.raises(ProjectionMaterializationError) as exc_info:
        call()
    return {item.code for item in exc_info.value.diagnostics}


def test_binding_input_and_stable_id_failures_are_explicit() -> None:
    schema = _source_schema()
    binding = SourceBinding(
        "erp.assets",
        "mapping-v1",
        SOURCE_SCHEMA_IDENTITY,
        object_existence_ids=("asset",),
    )

    assert _codes(
        lambda: materialize_projection(
            _empty_selection(),
            schema,
            source_bindings=(binding,),
        )
    ) == {"source_input_missing"}
    assert _codes(
        lambda: materialize_projection(
            _empty_selection(),
            schema,
            source_bindings=(binding,),
            source_inputs=(_empty_input("erp.assets", mapping_version="mapping-v2"),),
        )
    ) == {"source_mapping_version_mismatch"}

    name_bound_as_if_it_were_an_id = SourceBinding(
        "erp.by-name",
        "mapping-v1",
        SOURCE_SCHEMA_IDENTITY,
        object_existence_ids=("Asset",),
        property_ids=("code",),
        link_type_ids=("owned_by",),
    )
    with pytest.raises(ProjectionMaterializationError) as name_error:
        materialize_projection(
            _empty_selection(),
            schema,
            source_bindings=(name_bound_as_if_it_were_an_id,),
            source_inputs=(_empty_input("erp.by-name", mapping_version="mapping-v1"),),
        )
    assert [item.code for item in name_error.value.diagnostics] == [
        "unknown_source_authority_target",
        "unknown_source_authority_target",
        "unknown_source_authority_target",
    ]


def test_source_binding_must_target_the_selected_schema_identity() -> None:
    binding = SourceBinding(
        "erp.assets",
        "mapping-v1",
        SchemaIdentity(
            "test.other-source-contracts",
            "urn:test:other-source-contracts",
            "1.0.0",
        ),
        object_existence_ids=("asset",),
    )

    assert _codes(
        lambda: materialize_projection(
            _empty_selection(),
            _source_schema(),
            source_bindings=(binding,),
            source_inputs=(_empty_input("erp.assets", mapping_version="mapping-v1"),),
        )
    ) == {"source_binding_schema_identity_mismatch"}


@pytest.mark.parametrize("coverage", [SourceCoverage.PARTIAL, SourceCoverage.UNKNOWN])
def test_whole_snapshot_materialization_rejects_incomplete_source_coverage(
    coverage: SourceCoverage,
) -> None:
    binding = SourceBinding(
        "erp.assets",
        "mapping-v1",
        SOURCE_SCHEMA_IDENTITY,
        object_existence_ids=("asset",),
        coverage=coverage,
    )
    source_input = MappedSourceInput(
        binding_id="erp.assets",
        mapping_version="mapping-v1",
        source_revision="revision-1",
        coverage=coverage,
        payload=MappedSourceSnapshot(),
    )

    assert _codes(
        lambda: materialize_projection(
            _empty_selection(),
            _source_schema(),
            source_bindings=(binding,),
            source_inputs=(source_input,),
        )
    ) == {"source_coverage_unsupported"}


def test_source_input_coverage_must_match_its_binding_contract() -> None:
    binding = SourceBinding(
        "erp.assets",
        "mapping-v1",
        SOURCE_SCHEMA_IDENTITY,
        object_existence_ids=("asset",),
    )
    source_input = MappedSourceInput(
        binding_id="erp.assets",
        mapping_version="mapping-v1",
        source_revision="revision-1",
        coverage=SourceCoverage.PARTIAL,
        payload=MappedSourceSnapshot(),
    )

    assert _codes(
        lambda: materialize_projection(
            _empty_selection(),
            _source_schema(),
            source_bindings=(binding,),
            source_inputs=(source_input,),
        )
    ) == {"source_coverage_mismatch"}


def test_source_binding_cannot_claim_ontology_owned_state() -> None:
    schema = OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id="test.ontology-owned-binding",
            namespace="urn:test:ontology-owned-binding",
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
                        )
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
                    semantic_id="asset.owned-by",
                    state_authority=StateAuthority.ONTOLOGY_OWNED,
                )
            ],
        )
    )
    binding = SourceBinding(
        "erp.assets",
        "mapping-v1",
        SchemaIdentity.from_schema(schema),
        object_existence_ids=("asset",),
        property_ids=("asset.code",),
        link_type_ids=("asset.owned-by",),
    )

    with pytest.raises(ProjectionMaterializationError) as exc_info:
        materialize_projection(
            _empty_selection(),
            schema,
            source_bindings=(binding,),
            source_inputs=(_empty_input("erp.assets", mapping_version="mapping-v1"),),
        )
    assert [item.code for item in exc_info.value.diagnostics] == [
        "source_authority_mismatch",
        "source_authority_mismatch",
        "source_authority_mismatch",
    ]


def test_facts_cannot_impersonate_source_backed_operational_state() -> None:
    facts = MemoryFactStore()
    records = (
        FactRecord(
            fact_id=UUID("10000000-0000-0000-0000-000000000001"),
            subject_id=ASSET_ID,
            schema_identity=SOURCE_SCHEMA_IDENTITY,
            assertion=ObjectAssertion("asset"),
            assertion_kind=AssertionKind.ASSERTED,
            source_ref="erp",
            source_record_ref="asset:A-1",
            valid_from=0,
            recorded_at=1,
        ),
        FactRecord(
            fact_id=UUID("10000000-0000-0000-0000-000000000002"),
            subject_id=ASSET_ID,
            schema_identity=SOURCE_SCHEMA_IDENTITY,
            assertion=PropertyAssertion("asset.code", "A-1"),
            assertion_kind=AssertionKind.ASSERTED,
            source_ref="erp",
            source_record_ref="asset:A-1:code",
            valid_from=0,
            recorded_at=1,
        ),
        FactRecord(
            fact_id=UUID("10000000-0000-0000-0000-000000000003"),
            subject_id=ASSET_ID,
            schema_identity=SOURCE_SCHEMA_IDENTITY,
            assertion=LinkAssertion("asset.owned-by", OWNER_ID),
            assertion_kind=AssertionKind.ASSERTED,
            source_ref="erp",
            source_record_ref="ownership:A-1:O-1",
            valid_from=0,
            recorded_at=1,
        ),
    )
    facts.commit_fact_batch(FactBatch("source-shaped-facts", records))
    binding = SourceBinding(
        "erp.assets",
        "mapping-v1",
        SOURCE_SCHEMA_IDENTITY,
        object_existence_ids=("asset", "owner"),
        property_ids=("asset.code",),
        link_type_ids=("asset.owned-by",),
    )
    source_input = MappedSourceInput(
        binding_id="erp.assets",
        mapping_version="mapping-v1",
        source_revision="revision-1",
        coverage=SourceCoverage.COMPLETE,
        payload=MappedSourceSnapshot(
            objects=(
                MappedSourceObject(
                    object_id=ASSET_ID,
                    object_type_id="asset",
                    source_record_ref="asset:A-1",
                    identity_field_ref="assets.asset_id",
                ),
                MappedSourceObject(
                    object_id=OWNER_ID,
                    object_type_id="owner",
                    source_record_ref="owner:O-1",
                    identity_field_ref="owners.owner_id",
                ),
            )
        ),
    )

    assert _codes(
        lambda: materialize_projection(
            facts.select_facts(valid_at=10, recorded_at=10),
            _source_schema(),
            source_bindings=(binding,),
            source_inputs=(source_input,),
        )
    ) == {
        "link_fact_authority_mismatch",
        "object_fact_authority_mismatch",
        "property_fact_authority_mismatch",
    }


def test_inherited_property_binding_uses_stable_semantic_id() -> None:
    schema = OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id="test.inherited-source-binding",
            namespace="urn:test:inherited-source-binding",
            version="1.0.0",
            object_types=[
                ObjectTypeDefinition(
                    "Base",
                    semantic_id="base",
                    state_authority=StateAuthority.SOURCE_BACKED,
                    abstract=True,
                    properties=[
                        PropertyDefinition(
                            "code",
                            ValueType.STRING,
                            semantic_id="base.code",
                            state_authority=StateAuthority.SOURCE_BACKED,
                            required=True,
                        )
                    ],
                ),
                ObjectTypeDefinition(
                    "Asset",
                    semantic_id="asset",
                    state_authority=StateAuthority.SOURCE_BACKED,
                    parent_types=("Base",),
                ),
            ],
        )
    )
    binding = SourceBinding(
        "erp.assets",
        "mapping-v1",
        SchemaIdentity.from_schema(schema),
        object_existence_ids=("asset",),
        property_ids=("base.code",),
    )
    source_input = MappedSourceInput(
        binding_id="erp.assets",
        mapping_version="mapping-v1",
        source_revision="revision-1",
        coverage=SourceCoverage.COMPLETE,
        payload=MappedSourceSnapshot(
            objects=(
                MappedSourceObject(
                    object_id=ASSET_ID,
                    object_type_id="asset",
                    source_record_ref="asset:A-1",
                    identity_field_ref="assets.asset_id",
                    properties=(
                        MappedSourceProperty(
                            property_id="base.code",
                            value="A-1",
                            field_ref="assets.asset_code",
                            valid_from=1,
                        ),
                    ),
                ),
            )
        ),
    )

    snapshot = materialize_projection(
        _empty_selection(),
        schema,
        source_bindings=(binding,),
        source_inputs=(source_input,),
    )
    asset = snapshot.get(ASSET_ID)
    assert asset is not None
    assert asset.get("code") == "A-1"
    assert isinstance(asset.property("code").origin, SourceOrigin)  # type: ignore[union-attr]


def test_property_authority_composes_independently_from_object_existence() -> None:
    schema = _source_schema()
    existence_binding = SourceBinding(
        "z-master.assets",
        "mapping-v1",
        SOURCE_SCHEMA_IDENTITY,
        object_existence_ids=("asset",),
    )
    property_binding = SourceBinding(
        "a-erp.asset-code",
        "mapping-v2",
        SOURCE_SCHEMA_IDENTITY,
        property_ids=("asset.code",),
    )
    existence_input = MappedSourceInput(
        binding_id="z-master.assets",
        mapping_version="mapping-v1",
        source_revision="master-7",
        coverage=SourceCoverage.COMPLETE,
        payload=MappedSourceSnapshot(
            objects=(
                MappedSourceObject(
                    object_id=ASSET_ID,
                    object_type_id="asset",
                    source_record_ref="asset:A-1",
                    identity_field_ref="assets.asset_id",
                ),
            )
        ),
    )
    property_input = MappedSourceInput(
        binding_id="a-erp.asset-code",
        mapping_version="mapping-v2",
        source_revision="erp-12",
        coverage=SourceCoverage.COMPLETE,
        payload=MappedSourceSnapshot(
            objects=(
                MappedSourceObject(
                    object_id=ASSET_ID,
                    object_type_id="asset",
                    source_record_ref="erp-asset:A-1",
                    identity_field_ref="erp_assets.asset_id",
                    properties=(
                        MappedSourceProperty(
                            property_id="asset.code",
                            value="A-1",
                            field_ref="erp_assets.asset_code",
                            valid_from=1,
                        ),
                    ),
                ),
            )
        ),
    )

    snapshot = materialize_projection(
        _empty_selection(),
        schema,
        source_bindings=(existence_binding, property_binding),
        source_inputs=(existence_input, property_input),
    )

    asset = snapshot.get(ASSET_ID)
    assert asset is not None
    assert asset.get("code") == "A-1"
    assert asset.origin == SourceOrigin(
        "z-master.assets",
        "mapping-v1",
        "master-7",
        "asset:A-1",
        "assets.asset_id",
    )
    assert asset.property("code").origin == SourceOrigin(  # type: ignore[union-attr]
        "a-erp.asset-code",
        "mapping-v2",
        "erp-12",
        "erp-asset:A-1",
        "erp_assets.asset_code",
    )


def test_future_mapped_source_values_are_rejected_for_the_selected_valid_time() -> None:
    binding = SourceBinding(
        "erp.assets",
        "mapping-v1",
        SOURCE_SCHEMA_IDENTITY,
        object_existence_ids=("asset", "owner"),
        property_ids=("asset.code",),
        link_type_ids=("asset.owned-by",),
    )
    source_input = MappedSourceInput(
        binding_id="erp.assets",
        mapping_version="mapping-v1",
        source_revision="revision-1",
        coverage=SourceCoverage.COMPLETE,
        payload=MappedSourceSnapshot(
            objects=(
                MappedSourceObject(
                    object_id=ASSET_ID,
                    object_type_id="asset",
                    source_record_ref="asset:A-1",
                    identity_field_ref="assets.asset_id",
                    properties=(
                        MappedSourceProperty(
                            property_id="asset.code",
                            value="A-1",
                            field_ref="assets.asset_code",
                            valid_from=11,
                        ),
                    ),
                ),
                MappedSourceObject(
                    object_id=OWNER_ID,
                    object_type_id="owner",
                    source_record_ref="owner:O-1",
                    identity_field_ref="owners.owner_id",
                ),
            ),
            links=(
                MappedSourceLink(
                    source_id=ASSET_ID,
                    link_type_id="asset.owned-by",
                    target_id=OWNER_ID,
                    source_record_ref="ownership:A-1:O-1",
                    field_ref="ownership.owner_id",
                    valid_from=12,
                ),
            ),
        ),
    )

    with pytest.raises(ProjectionMaterializationError) as exc_info:
        materialize_projection(
            _empty_selection(),
            _source_schema(),
            source_bindings=(binding,),
            source_inputs=(source_input,),
        )

    future_values = [
        diagnostic
        for diagnostic in exc_info.value.diagnostics
        if diagnostic.code == "source_value_not_yet_valid"
    ]
    assert len(future_values) == 2
    assert all("selected valid_at 10.0" in item.message for item in future_values)


def test_source_backed_property_default_does_not_replace_unknown_source_state() -> None:
    schema = OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id="test.source-default",
            namespace="urn:test:source-default",
            version="1.0.0",
            object_types=[
                ObjectTypeDefinition(
                    "Asset",
                    semantic_id="asset",
                    state_authority=StateAuthority.SOURCE_BACKED,
                    properties=[
                        PropertyDefinition(
                            "status",
                            ValueType.STRING,
                            semantic_id="asset.status",
                            state_authority=StateAuthority.SOURCE_BACKED,
                            default="unknown",
                        )
                    ],
                )
            ],
        )
    )
    binding = SourceBinding(
        "master.assets",
        "mapping-v1",
        SchemaIdentity.from_schema(schema),
        object_existence_ids=("asset",),
    )
    source_input = MappedSourceInput(
        binding_id="master.assets",
        mapping_version="mapping-v1",
        source_revision="master-1",
        coverage=SourceCoverage.COMPLETE,
        payload=MappedSourceSnapshot(
            objects=(
                MappedSourceObject(
                    object_id=ASSET_ID,
                    object_type_id="asset",
                    source_record_ref="asset:A-1",
                    identity_field_ref="assets.asset_id",
                ),
            )
        ),
    )

    asset = materialize_projection(
        _empty_selection(),
        schema,
        source_bindings=(binding,),
        source_inputs=(source_input,),
    ).get(ASSET_ID)

    assert asset is not None
    assert asset.property("status") is None


def test_mapped_link_keeps_endpoint_failures_in_materialization_diagnostics() -> None:
    binding = SourceBinding(
        "erp.assets",
        "mapping-v1",
        SOURCE_SCHEMA_IDENTITY,
        object_existence_ids=("asset", "owner"),
        link_type_ids=("asset.owned-by",),
    )
    source_input = MappedSourceInput(
        binding_id="erp.assets",
        mapping_version="mapping-v1",
        source_revision="revision-1",
        coverage=SourceCoverage.COMPLETE,
        payload=MappedSourceSnapshot(
            objects=(
                MappedSourceObject(
                    object_id=ASSET_ID,
                    object_type_id="asset",
                    source_record_ref="asset:A-1",
                    identity_field_ref="assets.asset_id",
                ),
            ),
            links=(
                MappedSourceLink(
                    source_id=ASSET_ID,
                    link_type_id="asset.owned-by",
                    target_id=OWNER_ID,
                    source_record_ref="ownership:A-1:O-1",
                    field_ref="ownership.owner_id",
                    valid_from=1,
                ),
            ),
        ),
    )

    assert _codes(
        lambda: materialize_projection(
            _empty_selection(),
            _source_schema(),
            source_bindings=(binding,),
            source_inputs=(source_input,),
        )
    ) == {"link_endpoint_missing"}


def test_multi_source_freshness_requires_every_selected_head() -> None:
    schema_identity = SchemaIdentity(
        "test.multi-source-freshness",
        "urn:test:multi-source-freshness",
        "1.0.0",
    )
    selected_heads = (
        SourceInputRevision("erp.assets", "mapping-v1", "erp-10"),
        SourceInputRevision("crm.owners", "mapping-v2", "crm-20"),
    )
    selected_cuts = (
        SourceInputCut(
            "erp.assets",
            "mapping-v1",
            "erp-10",
            "0" * 64,
            SourceCoverage.COMPLETE,
        ),
        SourceInputCut(
            "crm.owners",
            "mapping-v2",
            "crm-20",
            "1" * 64,
            SourceCoverage.COMPLETE,
        ),
    )
    state = ProjectionState(
        schema_identity=schema_identity,
        projection_version=1,
        materialization_cut=MaterializationCut(
            schema_identity=schema_identity,
            source_inputs=selected_cuts,
            fact_watermark=0,
            valid_at=10,
            recorded_at=10,
        ),
        built_at=10,
    )

    missing = evaluate_projection_freshness(
        state,
        observed_fact_watermark=0,
        observed_source_heads=(selected_heads[0],),
        observed_at=11,
    )
    changed = evaluate_projection_freshness(
        state,
        observed_fact_watermark=0,
        observed_source_heads=(
            selected_heads[0],
            SourceInputRevision("crm.owners", "mapping-v2", "crm-21"),
        ),
        observed_at=12,
    )
    current = evaluate_projection_freshness(
        state,
        observed_fact_watermark=0,
        observed_source_heads=tuple(reversed(selected_heads)),
        observed_at=13,
    )

    assert missing.status is ProjectionFreshnessStatus.UNKNOWN
    assert missing.diagnostics == ("source heads were not observed for: crm.owners",)
    assert changed.status is ProjectionFreshnessStatus.STALE
    assert current.status is ProjectionFreshnessStatus.CURRENT
    assert current.observed_source_heads == tuple(reversed(selected_heads))
