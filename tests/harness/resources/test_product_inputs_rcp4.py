from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path

import pytest

from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionAuthorityContext,
    ProductCompositionCompilation,
    ProductCompositionCompiler,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
    OwnerContributionAuthority,
    OwnerContributionCandidateEnvelope,
    OwnerContributionPolicy,
    ResourceContributionSpec,
)
from loushang.harness.capabilities.model_input_contracts import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
)
from loushang.harness.capabilities.workspace_contracts import (
    WORKSPACE_CAPABILITY_DEFINITION,
)
from loushang.harness.plugin_authoring.contribution_admission import (
    prepare_owner_contribution_candidate,
)
from loushang.harness.plugin_authoring.host import PluginDeclarationHost
from loushang.harness.resource_catalog import product_inputs as product_inputs_module
from loushang.harness.resource_catalog.product_inputs import (
    InitialResourceCatalogProductAdapter,
    InitialResourceCatalogProductSelection,
    ProductAdmittedPackageResourceSpec,
    ProductEmbeddedResourceCollectionSpec,
    ProductNativeResourceRootSpec,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.plugins.authority import PluginResolutionAuthority
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.revisions import (
    PluginRevisionStore,
    VerifiedRevisionHandle,
)
from loushang.harness.resources.plugins.selection import (
    PendingOnlyPluginExecutionDecisionLookup,
    PluginContributionRef,
    PluginEffectiveConfigurationEntry,
    PluginEffectiveConfigurationSetV1,
    PluginInstanceRevisionRef,
    PluginPreflightContextV1,
    PluginSelection,
    PluginSelectionPlanV2,
    PluginSourceTrustSnapshotV1,
)
from loushang.harness.resources.plugins.types import PluginSource
from loushang.harness.resources.types import ResourceBundle
from loushang.harness.session.product_composition_assembly import (
    ProductCompositionAssemblyError,
    ProductCompositionAssemblyRequest,
    ProductContributionOwnerBinding,
    assemble_product_composition,
)

_CODING_BASE_SHADOW_ROOT = (
    Path(__file__).parent / "plugins" / "fixtures" / "coding_base_shadow"
)


def _package_skill_admission(
    tmp_path: Path,
    *,
    product_id: str = "product",
    expires_at: int = 100,
) -> tuple[OwnerContributionAdmissionRecord, VerifiedRevisionHandle]:
    source = tmp_path / f"source-{product_id}"
    skill = source / "skills" / "review" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: review\ndescription: Package review\n---\nReview.\n",
        encoding="utf-8",
    )
    (source / "plugin.json").write_text(
        json.dumps({"name": "review-package", "version": "1"}),
        encoding="utf-8",
    )
    published = PluginRevisionStore(tmp_path / f"revisions-{product_id}").publish(
        PluginManifestParser().parse(source)
    )
    handle = published.revision_handle
    candidate = OwnerContributionCandidateEnvelope(
        owner_id="resources.skill",
        plugin_id="review-package",
        contribution_id="review-package.skill",
        contribution=ResourceContributionSpec(
            resource_kind="skill",
            locator="skills/review/SKILL.md",
            locator_kind="file",
            media_type="text/markdown",
            schema_id="loushang.resource.skill",
            schema_version=1,
        ),
        plugin_candidate_fingerprint="1" * 64,
        declaration_fingerprint="2" * 64,
        declaration_evidence_fingerprint="3" * 64,
        package_content_digest=handle.content_digest,
        dependency_lock_digest="4" * 64,
        product_id=product_id,
        scope_id="session:test",
        product_policy_revision="policy-v1",
        instance_revision_ref=PluginInstanceRevisionRef(
            instance_id="review-package@product",
            plugin_id="review-package",
            revision=1,
        ),
        package_source_identity="test:review-package",
        source_trust_class="test_trusted",
        source_trust_policy_revision="test-trust-v1",
        source_trusted=True,
    )
    admission = OwnerContributionAuthority(
        OwnerContributionPolicy(
            owner_id="resources.skill",
            contribution_kind="resource_item",
            product_id=product_id,
            policy_revision="resource-skill-owner-v1",
            revocation_epoch=0,
            allowed_source_trust_classes=("test_trusted",),
            allowed_collection_ids=("loushang.resource.skill",),
            allowed_requirement_bindings=("direct",),
            consumer_scope="session",
            consumer_refresh_boundary="sealed",
        )
    ).admit(candidate, issued_at=1, expires_at=expires_at)
    return admission, handle


def _product_composition(
    admission: OwnerContributionAdmissionRecord,
) -> ProductCompositionCompilation:
    candidate = admission.candidate
    owner_snapshot = OwnerContributionAuthority(
        OwnerContributionPolicy(
            owner_id=admission.owner_id,
            contribution_kind=admission.contribution_kind,
            product_id=admission.product_id,
            policy_revision=admission.owner_policy_revision,
            revocation_epoch=admission.revocation_epoch,
            allowed_source_trust_classes=(candidate.source_trust_class,),
            allowed_collection_ids=(candidate.contribution.collection_id,),
            allowed_requirement_bindings=("direct",),
            consumer_scope=admission.consumer_scope,
            consumer_refresh_boundary=admission.consumer_refresh_boundary,
        )
    ).snapshot()
    return ProductCompositionCompiler().compile(
        authority_context=ProductCompositionAuthorityContext(
            product_id=admission.product_id,
            scope_id=candidate.scope_id,
            product_policy_revision=candidate.product_policy_revision,
            evaluated_at=2,
            owner_snapshots=(owner_snapshot,),
            trust_snapshots=(
                PluginSourceTrustSnapshotV1(
                    plugin_id=admission.plugin_id,
                    package_source_identity=candidate.package_source_identity,
                    source_trust_class=candidate.source_trust_class,
                    source_trust_policy_revision=(
                        candidate.source_trust_policy_revision
                    ),
                    trusted=True,
                ),
            ),
        ),
        mandatory_roots=(MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,),
        admissions=(admission,),
        definitions=(MODEL_INPUT_CAPABILITY_DEFINITION,),
        optional_choices=(),
    )


def test_embedded_product_spec_defensively_copies_the_selected_bytes() -> None:
    files = {"skills/builtin/SKILL.md": b"original"}

    spec = ProductEmbeddedResourceCollectionSpec(
        collection_id="builtin-resources",
        embedded_revision="v1",
        files=files,
    )
    files["skills/builtin/SKILL.md"] = b"changed"

    assert spec.files == {"skills/builtin/SKILL.md": b"original"}
    with pytest.raises(TypeError):
        spec.files["skills/other/SKILL.md"] = b"forbidden"  # type: ignore[index]


def test_product_selection_rejects_duplicate_native_and_embedded_identities(
    tmp_path: Path,
) -> None:
    root = ProductNativeResourceRootSpec(
        handle_id="project-resources",
        root=tmp_path,
        source_class="project_local",
        root_kind="standard",
    )
    embedded = ProductEmbeddedResourceCollectionSpec(
        collection_id="builtin-resources",
        embedded_revision="v1",
        files={},
    )

    with pytest.raises(ValueError, match="native root ids must not repeat"):
        InitialResourceCatalogProductSelection(
            product_policy_revision="policy-v1",
            native_roots=(root, root),
        )
    with pytest.raises(ValueError, match="embedded collection ids must not repeat"):
        InitialResourceCatalogProductSelection(
            product_policy_revision="policy-v1",
            embedded_collections=(embedded, embedded),
        )


def test_product_selection_rejects_duplicate_package_admissions(
    tmp_path: Path,
) -> None:
    admission, handle = _package_skill_admission(tmp_path)
    package = ProductAdmittedPackageResourceSpec(
        admission=admission,
        revision_handle=handle,
    )
    try:
        with pytest.raises(ValueError, match="exact-match Product composition"):
            InitialResourceCatalogProductSelection(
                product_policy_revision="policy-v1",
                package_resources=(package,),
            )
        with pytest.raises(ValueError, match="composition policy is stale"):
            InitialResourceCatalogProductSelection(
                product_policy_revision="policy-v2",
                product_composition=_product_composition(admission),
                package_resources=(package,),
            )
        with pytest.raises(ValueError, match="admissions must not repeat"):
            InitialResourceCatalogProductSelection(
                product_policy_revision="policy-v1",
                product_composition=_product_composition(admission),
                package_resources=(package, package),
            )
    finally:
        handle.close()


def test_product_adapter_consumes_compiled_resource_admissions_from_plugin_selection(
    tmp_path: Path,
) -> None:
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=_CODING_BASE_SHADOW_ROOT))
    runtime = authority.publish_runtime(
        (inspection,),
        binding_store=PackageMaterializer(
            install_root=tmp_path / "installed",
            plugin_revision_root=tmp_path / "revisions",
        ),
    )
    [package] = runtime.packages
    [binding] = runtime.bindings
    plugin_id = package.manifest.name
    plan = PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id="coding",
            scope_id="workspace:test",
            policy_revision="policy-1",
            instance_revision_refs=(
                PluginInstanceRevisionRef(
                    instance_id="coding.base@product",
                    plugin_id=plugin_id,
                    revision=1,
                ),
            ),
        ),
        selected_plugin_ids=(plugin_id,),
        selected_contributions=tuple(
            PluginContributionRef(plugin_id, item.contribution_id)
            for item in package.contribution_index.items
        ),
        source_trust_snapshots=(
            PluginSourceTrustSnapshotV1(
                plugin_id=plugin_id,
                package_source_identity=binding.source_identity,
                source_trust_class="host-equivalent-local",
                source_trust_policy_revision="trust-1",
                trusted=True,
            ),
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=tuple(
                PluginEffectiveConfigurationEntry(
                    plugin_id=plugin_id,
                    contribution_id=item.contribution_id,
                    configuration={},
                )
                for item in package.contribution_index.items
            )
        ),
        allowed_authority_ceiling=(),
    )
    try:
        selection = PluginDeclarationHost().resolve(
            (package,),
            bindings=(binding,),
            plan=plan,
            decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
        )
        assert isinstance(selection, PluginSelection)
        contribution_candidates = tuple(
            item
            for item in selection.candidates
            if item.declaration.kind in {"resource_item", "tool_pack", "command_pack"}
        )
        owner_bindings = []
        for contribution_candidate in contribution_candidates:
            candidate = prepare_owner_contribution_candidate(
                selection,
                contribution_candidate,
            )
            owner_authority = OwnerContributionAuthority(
                OwnerContributionPolicy(
                    owner_id=candidate.owner_id,
                    contribution_kind=candidate.contribution_kind,
                    product_id="coding",
                    policy_revision=f"{candidate.owner_id}-v1",
                    revocation_epoch=0,
                    allowed_source_trust_classes=("host-equivalent-local",),
                    allowed_collection_ids=(candidate.contribution.collection_id,),
                    allowed_requirement_bindings=("direct",),
                    consumer_scope="session",
                    consumer_refresh_boundary="sealed",
                )
            )
            owner_bindings.append(
                ProductContributionOwnerBinding(
                    authority=owner_authority,
                    admission_ttl_seconds=100,
                )
            )
        assembly_request = ProductCompositionAssemblyRequest(
            selection=selection,
            owner_bindings=tuple(owner_bindings),
            mandatory_roots=(MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,),
            definitions=(
                MODEL_INPUT_CAPABILITY_DEFINITION,
                WORKSPACE_CAPABILITY_DEFINITION,
            ),
        )
        with pytest.raises(ProductCompositionAssemblyError) as missing:
            assemble_product_composition(
                replace(
                    assembly_request,
                    owner_bindings=assembly_request.owner_bindings[:-1],
                ),
                evaluated_at=150,
            )
        assert missing.value.code == "product_contribution_owner_missing"
        assert missing.value.owner_keys == (
            assembly_request.owner_bindings[-1].owner_key,
        )

        extra_binding = ProductContributionOwnerBinding(
            authority=OwnerContributionAuthority(
                OwnerContributionPolicy(
                    owner_id="resources.theme",
                    contribution_kind="resource_item",
                    product_id="coding",
                    policy_revision="resources.theme-v1",
                    revocation_epoch=0,
                    allowed_source_trust_classes=("host-equivalent-local",),
                    allowed_collection_ids=("loushang.resource.theme",),
                    allowed_requirement_bindings=("direct",),
                    consumer_scope="session",
                    consumer_refresh_boundary="sealed",
                )
            )
        )
        with pytest.raises(ProductCompositionAssemblyError) as extra:
            assemble_product_composition(
                replace(
                    assembly_request,
                    owner_bindings=(*assembly_request.owner_bindings, extra_binding),
                ),
                evaluated_at=150,
            )
        assert extra.value.code == "product_contribution_owner_extra"
        assert extra.value.owner_keys == (extra_binding.owner_key,)

        composition = assemble_product_composition(
            assembly_request,
            evaluated_at=150,
        )
        assert len(composition.resource_admissions) == 2
        assert len(composition.catalog_admissions) == 2
        assert all(
            item.issued_at == 150 and item.expires_at == 100_150
            for item in (
                *composition.resource_admissions,
                *composition.catalog_admissions,
            )
        )
        adapter = InitialResourceCatalogProductAdapter(
            InitialResourceCatalogProductSelection(
                product_policy_revision="policy-1",
                product_composition=composition,
                package_resources=tuple(
                    ProductAdmittedPackageResourceSpec(
                        admission=admission,
                        revision_handle=package.revision_handle,
                    )
                    for admission in composition.resource_admissions
                ),
            ),
            clock=lambda: 150,
        )
        bootstrap = adapter.construct_session(
            product_id="coding",
            session_id="compiled-plugin-selection",
            base_resource_bundle=ResourceBundle(cwd=tmp_path),
            construct=lambda value: value,
        )
        acquired = tuple(
            item.revision_handle for item in bootstrap._inputs.package_resources
        )
        try:
            assert adapter.selection.product_composition is composition
            assert len(acquired) == 2
            assert all(item is not package.revision_handle for item in acquired)
        finally:
            bootstrap.close_unprepared()
        assert all(item.closed for item in acquired)
        assert package.revision_handle.closed is False
    finally:
        runtime.close()


def test_product_adapter_reuse_acquires_independent_package_revision_leases(
    tmp_path: Path,
) -> None:
    admission, source_handle = _package_skill_admission(tmp_path)
    adapter = InitialResourceCatalogProductAdapter(
        InitialResourceCatalogProductSelection(
            product_policy_revision="policy-v1",
            product_composition=_product_composition(admission),
            package_resources=(
                ProductAdmittedPackageResourceSpec(
                    admission=admission,
                    revision_handle=source_handle,
                ),
            ),
        ),
        clock=lambda: 10,
    )
    bundle = ResourceBundle(cwd=tmp_path)

    first = adapter.construct_session(
        product_id="product",
        session_id="first-package",
        base_resource_bundle=bundle,
        construct=lambda bootstrap: bootstrap,
    )
    second = adapter.construct_session(
        product_id="product",
        session_id="second-package",
        base_resource_bundle=bundle,
        construct=lambda bootstrap: bootstrap,
    )
    first_handle = first._inputs.package_resources[0].revision_handle
    second_handle = second._inputs.package_resources[0].revision_handle

    assert first_handle is not second_handle
    assert first_handle is not source_handle
    assert second_handle is not source_handle
    first.close_unprepared()
    assert first_handle.closed is True
    assert second_handle.closed is False
    assert source_handle.closed is False
    second.close_unprepared()
    assert second_handle.closed is True
    assert source_handle.closed is False
    source_handle.close()


@pytest.mark.parametrize(
    ("admission_product_id", "expires_at", "message"),
    (
        ("foreign", 100, "belongs elsewhere"),
        ("product", 5, "is not active"),
        ("product", 10, "is not active"),
    ),
)
def test_product_adapter_rejects_foreign_or_expired_package_admission_before_acquire(
    tmp_path: Path,
    admission_product_id: str,
    expires_at: int,
    message: str,
) -> None:
    admission, source_handle = _package_skill_admission(
        tmp_path,
        product_id=admission_product_id,
        expires_at=expires_at,
    )
    adapter = InitialResourceCatalogProductAdapter(
        InitialResourceCatalogProductSelection(
            product_policy_revision="policy-v1",
            product_composition=_product_composition(admission),
            package_resources=(
                ProductAdmittedPackageResourceSpec(
                    admission=admission,
                    revision_handle=source_handle,
                ),
            ),
        ),
        clock=lambda: 10,
    )

    with pytest.raises(ValueError, match=message):
        adapter.construct_session(
            product_id="product",
            session_id="rejected-package",
            base_resource_bundle=ResourceBundle(cwd=tmp_path),
            construct=lambda bootstrap: bootstrap,
        )

    assert source_handle.closed is False
    source_handle.close()


def test_product_adapter_reuse_mints_independent_session_bootstraps(
    tmp_path: Path,
) -> None:
    adapter = InitialResourceCatalogProductAdapter(
        InitialResourceCatalogProductSelection(
            product_policy_revision="policy-v1",
            embedded_collections=(
                ProductEmbeddedResourceCollectionSpec(
                    collection_id="builtin-resources",
                    embedded_revision="v1",
                    files={
                        "skills/builtin/SKILL.md": (
                            b"---\nname: builtin\ndescription: Built in\n---\nUse it.\n"
                        )
                    },
                ),
            ),
        ),
        clock=lambda: 10,
    )
    bundle = ResourceBundle(cwd=tmp_path)

    first = adapter.construct_session(
        product_id="product",
        session_id="first",
        base_resource_bundle=bundle,
        construct=lambda bootstrap: bootstrap,
    )
    second = adapter.construct_session(
        product_id="product",
        session_id="second",
        base_resource_bundle=bundle,
        construct=lambda bootstrap: bootstrap,
    )

    assert first is not second
    assert first.scope_id == "session:first"
    assert second.scope_id == "session:second"
    first.close_unprepared()
    second.close_unprepared()
    assert first.state == second.state == "disposed"


def test_product_adapter_closes_untransferred_inputs_when_construction_fails(
    tmp_path: Path,
) -> None:
    captured = []
    adapter = InitialResourceCatalogProductAdapter(
        InitialResourceCatalogProductSelection(
            product_policy_revision="policy-v1",
            embedded_collections=(
                ProductEmbeddedResourceCollectionSpec(
                    collection_id="builtin-resources",
                    embedded_revision="v1",
                    files={},
                ),
            ),
        ),
        clock=lambda: 10,
    )

    def fail(bootstrap):  # type: ignore[no-untyped-def]
        captured.append(bootstrap)
        raise RuntimeError("Session construction failed")

    with pytest.raises(RuntimeError, match="Session construction failed"):
        adapter.construct_session(
            product_id="product",
            session_id="failed",
            base_resource_bundle=ResourceBundle(cwd=tmp_path),
            construct=fail,
        )

    assert len(captured) == 1
    assert captured[0].state == "disposed"


def test_product_adapter_releases_partial_embedded_mint_on_later_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    minted = []
    real_mint = product_inputs_module.mint_embedded_resource_collection_handle

    def fail_second_mint(**kwargs):  # type: ignore[no-untyped-def]
        if minted:
            raise RuntimeError("second embedded collection failed")
        handle = real_mint(**kwargs)
        minted.append(handle)
        return handle

    monkeypatch.setattr(
        product_inputs_module,
        "mint_embedded_resource_collection_handle",
        fail_second_mint,
    )
    adapter = InitialResourceCatalogProductAdapter(
        InitialResourceCatalogProductSelection(
            product_policy_revision="policy-v1",
            embedded_collections=(
                ProductEmbeddedResourceCollectionSpec(
                    collection_id="builtin-a",
                    embedded_revision="v1",
                    files={},
                ),
                ProductEmbeddedResourceCollectionSpec(
                    collection_id="builtin-b",
                    embedded_revision="v1",
                    files={},
                ),
            ),
        ),
        clock=lambda: 10,
    )

    with pytest.raises(RuntimeError, match="second embedded collection failed"):
        adapter.construct_session(
            product_id="product",
            session_id="failed",
            base_resource_bundle=ResourceBundle(cwd=tmp_path),
            construct=lambda bootstrap: bootstrap,
        )

    assert len(minted) == 1
    assert minted[0].closed is True


def test_product_adapter_rejects_async_construction_and_closes_its_coroutine(
    tmp_path: Path,
) -> None:
    captured = []
    adapter = InitialResourceCatalogProductAdapter(
        InitialResourceCatalogProductSelection(
            product_policy_revision="policy-v1",
            native_roots=(
                ProductNativeResourceRootSpec(
                    handle_id="project-resources",
                    root=tmp_path,
                    source_class="project_local",
                    root_kind="standard",
                ),
            ),
        ),
        clock=lambda: 10,
    )

    async def pending_session() -> object:
        await asyncio.sleep(0)
        return object()

    def construct(bootstrap):  # type: ignore[no-untyped-def]
        captured.append(bootstrap)
        return pending_session()

    with pytest.raises(TypeError, match="must be synchronous"):
        adapter.construct_session(
            product_id="product",
            session_id="async",
            base_resource_bundle=ResourceBundle(cwd=tmp_path),
            construct=construct,
        )

    assert len(captured) == 1
    assert captured[0].state == "disposed"
