from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
    OwnerContributionAuthority,
    OwnerContributionCandidateEnvelope,
    OwnerContributionPolicy,
    ResourceContributionSpec,
)
from loushang.harness.resource_catalog import product_inputs as product_inputs_module
from loushang.harness.resource_catalog.product_inputs import (
    InitialResourceCatalogProductAdapter,
    InitialResourceCatalogProductSelection,
    ProductAdmittedPackageResourceSpec,
    ProductEmbeddedResourceCollectionSpec,
    ProductNativeResourceRootSpec,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.revisions import (
    PluginRevisionStore,
    VerifiedRevisionHandle,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef
from loushang.harness.resources.types import ResourceBundle


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
        with pytest.raises(ValueError, match="admissions must not repeat"):
            InitialResourceCatalogProductSelection(
                product_policy_revision="policy-v1",
                package_resources=(package, package),
            )
    finally:
        handle.close()


def test_product_adapter_reuse_acquires_independent_package_revision_leases(
    tmp_path: Path,
) -> None:
    admission, source_handle = _package_skill_admission(tmp_path)
    adapter = InitialResourceCatalogProductAdapter(
        InitialResourceCatalogProductSelection(
            product_policy_revision="policy-v1",
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
