from __future__ import annotations

import json
from dataclasses import replace

import pytest

from loushang.ontology.deployment import (
    DEPLOYMENT_PROFILE_FORMAT,
    DeploymentProfile,
    DeploymentProfileValidationError,
    IdentityCrosswalkArtifactLock,
    SchemaArtifactLock,
    SourceAdapterArtifactLock,
    SourceInstanceSelection,
    lock_identity_crosswalk,
    lock_schema_artifact,
    lock_source_adapter_artifact,
    validate_deployment_profile,
)
from loushang.ontology.identity import (
    IdentityCrosswalkSnapshot,
    IdentityResolution,
    IdentityResolutionStatus,
    SourceRecordIdentity,
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
from loushang.ontology.source import (
    ApplicationSchemaIdentity,
    SourceAdapterManifest,
    SourceBinding,
)

_DEFAULT_CROSSWALK = object()


def _schema(*, version: str = "1.0.0", code_name: str = "code"):
    return OntologyCompiler().compile(
        OntologyPackageDraft(
            package_id="test.deployment",
            namespace="urn:test:deployment",
            version=version,
            object_types=(
                ObjectTypeDefinition(
                    "Asset",
                    semantic_id="asset",
                    state_authority=StateAuthority.SOURCE_BACKED,
                    properties=(
                        PropertyDefinition(
                            code_name,
                            ValueType.STRING,
                            semantic_id="asset.code",
                            state_authority=StateAuthority.SOURCE_BACKED,
                        ),
                        PropertyDefinition(
                            "status",
                            ValueType.STRING,
                            semantic_id="asset.status",
                            state_authority=StateAuthority.SOURCE_BACKED,
                        ),
                    ),
                ),
            ),
        )
    )


def _manifest(
    adapter_id: str,
    binding_id: str,
    *,
    target_schema: SchemaIdentity,
    object_existence_ids: tuple[str, ...] = (),
    property_ids: tuple[str, ...] = (),
    adapter_version: str = "1.0.0",
) -> SourceAdapterManifest:
    return SourceAdapterManifest(
        adapter_id=adapter_id,
        adapter_version=adapter_version,
        application_schema=ApplicationSchemaIdentity(
            application_id=f"application.{adapter_id}",
            schema_version="schema/v1",
        ),
        target_schema=target_schema,
        bindings=(
            SourceBinding(
                binding_id=binding_id,
                mapping_version="mapping/v1",
                schema_identity=target_schema,
                object_existence_ids=object_existence_ids,
                property_ids=property_ids,
            ),
        ),
    )


def _artifacts():
    schema = _schema()
    identity = SchemaIdentity.from_schema(schema)
    erp = _manifest(
        "vendor.erp",
        "erp.assets",
        target_schema=identity,
        object_existence_ids=("asset",),
        property_ids=("asset.code",),
    )
    oa = _manifest(
        "vendor.oa",
        "oa.asset-status",
        target_schema=identity,
        property_ids=("asset.status",),
    )
    return schema, erp, oa


def _crosswalk(
    *,
    deployment_id: str = "bureau-alpha",
    identity_namespace: str = "urn:test:identity:bureau-alpha",
    revision: str = "identity/v1",
    entries: tuple[IdentityResolution, ...] = (),
) -> IdentityCrosswalkSnapshot:
    return IdentityCrosswalkSnapshot(
        deployment_id=deployment_id,
        identity_namespace=identity_namespace,
        revision=revision,
        entries=entries,
    )


def _profile():
    schema, erp, oa = _artifacts()
    crosswalk = _crosswalk()
    return DeploymentProfile(
        deployment_id="bureau-alpha",
        schema_lock=lock_schema_artifact(schema),
        adapter_locks=(
            lock_source_adapter_artifact(oa),
            lock_source_adapter_artifact(erp),
        ),
        source_instances=(
            SourceInstanceSelection(
                "oa:alpha",
                "vendor.oa",
                ("oa.asset-status",),
            ),
            SourceInstanceSelection(
                "erp:alpha",
                "vendor.erp",
                ("erp.assets",),
            ),
        ),
        identity_crosswalk_lock=lock_identity_crosswalk(crosswalk),
        fact_store_ref="store:ontology-facts",
        projection_store_ref="store:ontology-projection",
    )


def test_profile_round_trip_locks_artifacts_and_resolves_enabled_bindings() -> None:
    schema, erp, oa = _artifacts()
    profile = _profile()

    restored = DeploymentProfile.from_json(profile.to_json())
    selected = validate_deployment_profile(
        restored,
        schema=schema,
        adapter_manifests=(oa, erp),
        identity_crosswalk=_crosswalk(),
    )

    assert restored == profile
    assert [item.adapter_id for item in restored.adapter_locks] == [
        "vendor.erp",
        "vendor.oa",
    ]
    assert [item.source_instance_id for item in restored.source_instances] == [
        "erp:alpha",
        "oa:alpha",
    ]
    assert restored.identity_crosswalk_lock == lock_identity_crosswalk(_crosswalk())
    assert [item.binding_id for item in selected] == [
        "erp.assets",
        "oa.asset-status",
    ]
    assert len(restored.profile_digest) == 64
    assert DeploymentProfile.from_json(restored.to_json()).profile_digest == (
        restored.profile_digest
    )


def test_profile_json_is_strict_and_contains_only_opaque_store_references() -> None:
    profile = _profile()
    document = json.loads(profile.to_json())
    assert "credentials" not in document
    assert document["fact_store_ref"] == "store:ontology-facts"
    document["credentials"] = {"password": "not-allowed"}

    with pytest.raises(ValueError, match="fields do not match"):
        DeploymentProfile.from_json(json.dumps(document))

    nested_document = json.loads(profile.to_json())
    nested_document["schema_lock"]["schema_identity"]["alias"] = "not-allowed"
    with pytest.raises(ValueError, match="schema identity fields"):
        DeploymentProfile.from_json(json.dumps(nested_document))

    with pytest.raises(ValueError, match="fact_store_ref"):
        replace(profile, fact_store_ref="")


def test_profile_accepts_an_ontology_only_artifact_selection() -> None:
    schema = _schema()
    profile = DeploymentProfile(
        deployment_id="ontology-only",
        schema_lock=lock_schema_artifact(schema),
        adapter_locks=(),
        source_instances=(),
        identity_crosswalk_lock=None,
        fact_store_ref="store:facts",
        projection_store_ref="store:projection",
    )

    assert (
        validate_deployment_profile(
            profile,
            schema=schema,
            adapter_manifests=(),
            identity_crosswalk=None,
        )
        == ()
    )


def test_schema_identity_and_content_are_independent_lock_coordinates() -> None:
    schema, erp, oa = _artifacts()
    profile = _profile()
    changed_identity = _schema(version="2.0.0")
    changed_content = _schema(code_name="asset_code")

    assert (
        _validation_code(
            profile,
            changed_identity,
            (erp, oa),
        )
        == "schema_identity_mismatch"
    )
    assert (
        _validation_code(
            profile,
            changed_content,
            (erp, oa),
        )
        == "schema_digest_mismatch"
    )
    assert lock_schema_artifact(schema) == profile.schema_lock


def test_adapter_set_version_and_content_mismatches_fail_explicitly() -> None:
    schema, erp, oa = _artifacts()
    profile = _profile()
    first_lock = profile.adapter_locks[0]

    assert _validation_code(profile, schema, (erp,)) == "adapter_set_mismatch"
    assert (
        _validation_code(
            profile,
            schema,
            (erp, oa, erp),
        )
        == "duplicate_adapter_manifest"
    )
    assert (
        _validation_code(
            replace(
                profile,
                adapter_locks=(
                    replace(first_lock, adapter_version="2.0.0"),
                    profile.adapter_locks[1],
                ),
            ),
            schema,
            (erp, oa),
        )
        == "adapter_version_mismatch"
    )
    assert (
        _validation_code(
            replace(
                profile,
                adapter_locks=(
                    replace(first_lock, manifest_digest="0" * 64),
                    profile.adapter_locks[1],
                ),
            ),
            schema,
            (erp, oa),
        )
        == "adapter_digest_mismatch"
    )


def test_source_instance_selection_rejects_invalid_bindings_and_adapters() -> None:
    schema, erp, oa = _artifacts()
    profile = _profile()
    erp_instance, oa_instance = profile.source_instances
    assert (
        _validation_code(
            replace(
                profile,
                source_instances=(
                    replace(
                        erp_instance,
                        binding_ids=(*erp_instance.binding_ids, "missing.binding"),
                    ),
                    oa_instance,
                ),
            ),
            schema,
            (erp, oa),
        )
        == "source_instance_binding_missing"
    )
    assert (
        _validation_code(
            replace(profile, source_instances=(erp_instance,)),
            schema,
            (erp, oa),
        )
        == "unused_adapter_lock"
    )
    assert (
        _validation_code(
            replace(
                profile,
                source_instances=(
                    replace(erp_instance, adapter_id="vendor.missing"),
                    oa_instance,
                ),
            ),
            schema,
            (erp, oa),
        )
        == "source_instance_adapter_missing"
    )
    assert (
        _validation_code(
            replace(
                profile,
                source_instances=(
                    replace(erp_instance, adapter_id="vendor.oa"),
                    oa_instance,
                ),
            ),
            schema,
            (erp, oa),
        )
        == "source_instance_binding_adapter_mismatch"
    )

    with pytest.raises(ValueError, match="multiple source instances"):
        replace(
            profile,
            source_instances=(
                erp_instance,
                SourceInstanceSelection(
                    "erp:beta",
                    "vendor.erp",
                    ("erp.assets",),
                ),
            ),
        )

    duplicate = _manifest(
        "vendor.duplicate",
        "erp.assets",
        target_schema=SchemaIdentity.from_schema(schema),
        property_ids=("asset.status",),
    )
    duplicate_profile = replace(
        profile,
        adapter_locks=(
            lock_source_adapter_artifact(erp),
            lock_source_adapter_artifact(duplicate),
        ),
        source_instances=(erp_instance,),
    )
    assert (
        _validation_code(
            duplicate_profile,
            schema,
            (erp, duplicate),
        )
        == "duplicate_binding_id"
    )


def test_adapter_target_schema_cannot_be_hidden_by_a_valid_manifest_lock() -> None:
    schema = _schema()
    foreign_identity = SchemaIdentity(
        "test.foreign",
        "urn:test:foreign",
        "1.0.0",
    )
    foreign = _manifest(
        "vendor.foreign",
        "foreign.assets",
        target_schema=foreign_identity,
        object_existence_ids=("asset",),
    )
    profile = DeploymentProfile(
        deployment_id="foreign",
        schema_lock=lock_schema_artifact(schema),
        adapter_locks=(lock_source_adapter_artifact(foreign),),
        source_instances=(
            SourceInstanceSelection(
                "foreign:source",
                "vendor.foreign",
                ("foreign.assets",),
            ),
        ),
        identity_crosswalk_lock=None,
        fact_store_ref="store:facts",
        projection_store_ref="store:projection",
    )

    assert (
        _validation_code(
            profile,
            schema,
            (foreign,),
            identity_crosswalk=None,
        )
        == "adapter_target_schema_mismatch"
    )


def test_crosswalk_selection_and_coordinates_fail_independently() -> None:
    schema, erp, oa = _artifacts()
    profile = _profile()
    crosswalk = _crosswalk()

    assert (
        _validation_code(
            profile,
            schema,
            (erp, oa),
            identity_crosswalk=None,
        )
        == "identity_crosswalk_selection_mismatch"
    )
    assert (
        _validation_code(
            replace(profile, identity_crosswalk_lock=None),
            schema,
            (erp, oa),
            identity_crosswalk=crosswalk,
        )
        == "identity_crosswalk_selection_mismatch"
    )
    assert (
        _validation_code(
            profile,
            schema,
            (erp, oa),
            identity_crosswalk=_crosswalk(deployment_id="bureau-beta"),
        )
        == "identity_crosswalk_deployment_mismatch"
    )
    assert (
        _validation_code(
            profile,
            schema,
            (erp, oa),
            identity_crosswalk=_crosswalk(identity_namespace="urn:test:other"),
        )
        == "identity_crosswalk_namespace_mismatch"
    )
    assert (
        _validation_code(
            profile,
            schema,
            (erp, oa),
            identity_crosswalk=_crosswalk(revision="identity/v2"),
        )
        == "identity_crosswalk_revision_mismatch"
    )

    changed_content = _crosswalk(
        entries=(
            IdentityResolution(
                source_identity=SourceRecordIdentity(
                    "erp:alpha",
                    "erp.assets",
                    "asset",
                    "A-1",
                ),
                status=IdentityResolutionStatus.UNRESOLVED,
            ),
        )
    )
    assert (
        _validation_code(
            profile,
            schema,
            (erp, oa),
            identity_crosswalk=changed_content,
        )
        == "identity_crosswalk_digest_mismatch"
    )


def test_crosswalk_cannot_contain_an_unselected_source_scope() -> None:
    schema, erp, oa = _artifacts()
    crosswalk = _crosswalk(
        entries=(
            IdentityResolution(
                source_identity=SourceRecordIdentity(
                    "erp:unselected",
                    "erp.assets",
                    "asset",
                    "A-1",
                ),
                status=IdentityResolutionStatus.UNRESOLVED,
            ),
        )
    )
    profile = replace(
        _profile(),
        identity_crosswalk_lock=lock_identity_crosswalk(crosswalk),
    )

    assert (
        _validation_code(
            profile,
            schema,
            (erp, oa),
            identity_crosswalk=crosswalk,
        )
        == "identity_source_scope_unselected"
    )


def test_v1_profile_documents_are_rejected_without_a_compatibility_reader() -> None:
    document = json.loads(_profile().to_json())
    document["format"] = "loushang.ontology.deployment-profile/v1"

    with pytest.raises(ValueError, match="unsupported deployment profile format"):
        DeploymentProfile.from_json(json.dumps(document))

    assert DEPLOYMENT_PROFILE_FORMAT.endswith("/v2")


def test_artifact_locks_require_lowercase_sha256_digests() -> None:
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        SchemaArtifactLock(
            schema_identity=SchemaIdentity(
                "test",
                "urn:test",
                "1.0.0",
            ),
            content_digest="not-a-digest",
        )
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        SourceAdapterArtifactLock("adapter", "1.0.0", "A" * 64)
    with pytest.raises(ValueError, match="lowercase SHA-256"):
        IdentityCrosswalkArtifactLock("urn:test", "v1", "A" * 64)


def _validation_code(
    profile,
    schema,
    manifests,
    *,
    identity_crosswalk: IdentityCrosswalkSnapshot | None | object = (
        _DEFAULT_CROSSWALK
    ),
) -> str:
    selected_crosswalk = (
        _crosswalk() if identity_crosswalk is _DEFAULT_CROSSWALK else identity_crosswalk
    )
    assert selected_crosswalk is None or isinstance(
        selected_crosswalk,
        IdentityCrosswalkSnapshot,
    )
    with pytest.raises(DeploymentProfileValidationError) as exc_info:
        validate_deployment_profile(
            profile,
            schema=schema,
            adapter_manifests=manifests,
            identity_crosswalk=selected_crosswalk,
        )
    return exc_info.value.code
