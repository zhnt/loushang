from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from loushang.harness.capabilities.component_runtime import (
    CapabilityOwnerComponentBinder,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAuthority,
    OwnerContributionCandidateEnvelope,
    OwnerContributionPolicy,
    ResourceContributionSpec,
)
from loushang.harness.resource_catalog.components import (
    EMBEDDED_RESOURCE_SOURCE_COMPONENT_ID,
    NATIVE_RESOURCE_SOURCE_COMPONENT_ID,
    PACKAGE_RESOURCE_SOURCE_COMPONENT_ID,
)
from loushang.harness.resource_catalog.inputs import (
    AdmittedPackageResource,
    acquire_admitted_package_resource,
)
from loushang.harness.resource_catalog.shadow import (
    run_first_party_resource_catalog_shadow,
)
from loushang.harness.resources._catalog_embedded_source import (
    EmbeddedResourceDiscoveryBudget,
    EmbeddedResourceSourceError,
    mint_embedded_resource_collection_handle,
)
from loushang.harness.resources._catalog_native_source import (
    mint_native_resource_root_handle,
)
from loushang.harness.resources._catalog_package_source import (
    PackageResourceDiscoveryBudget,
    PackageResourceSourceError,
)
from loushang.harness.resources._catalog_records import (
    EmbeddedOemOrigin,
    NativeHostOrigin,
    VerifiedPluginResourceOrigin,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.revisions import (
    PluginRevisionStore,
    VerifiedRevisionHandle,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef


def _skill_body(name: str, description: str, body: str) -> bytes:
    return (f"---\nname: {name}\ndescription: {description}\n---\n{body}\n").encode()


def _admitted_package_skill(
    tmp_path: Path,
    *,
    plugin_id: str,
    public_name: str,
    description: str,
    source_root_order: int = 0,
) -> tuple[AdmittedPackageResource, bytes, VerifiedRevisionHandle]:
    body = _skill_body(public_name, description, f"{description} body")
    return _admitted_package_file(
        tmp_path,
        plugin_id=plugin_id,
        contribution_id=f"{plugin_id}.skill",
        resource_kind="skill",
        locator=f"skills/{public_name}/SKILL.md",
        body=body,
        media_type="text/markdown",
        schema_id="loushang.resource.skill",
        source_root_order=source_root_order,
    )


def _admitted_package_file(
    tmp_path: Path,
    *,
    plugin_id: str,
    contribution_id: str,
    resource_kind: str,
    locator: str,
    body: bytes,
    media_type: str,
    schema_id: str,
    source_root_order: int = 0,
) -> tuple[AdmittedPackageResource, bytes, VerifiedRevisionHandle]:
    source = tmp_path / f"source-{plugin_id}"
    item = source / locator
    item.parent.mkdir(parents=True)
    item.write_bytes(body)
    (source / "plugin.json").write_text(
        json.dumps({"name": plugin_id, "version": "1"}),
        encoding="utf-8",
    )
    published = PluginRevisionStore(tmp_path / "revisions").publish(
        PluginManifestParser().parse(source)
    )
    handle = published.revision_handle
    assert handle is not None
    instance_ref = PluginInstanceRevisionRef(
        instance_id=f"{plugin_id}@product",
        plugin_id=plugin_id,
        revision=1,
    )
    contribution = ResourceContributionSpec(
        resource_kind=resource_kind,
        locator=locator,
        locator_kind="file",
        media_type=media_type,
        schema_id=schema_id,
        schema_version=1,
    )
    owner_id = f"resources.{resource_kind}"
    candidate = OwnerContributionCandidateEnvelope(
        owner_id=owner_id,
        plugin_id=plugin_id,
        contribution_id=contribution_id,
        contribution=contribution,
        plugin_candidate_fingerprint="1" * 64,
        declaration_fingerprint="2" * 64,
        declaration_evidence_fingerprint="3" * 64,
        package_content_digest=handle.content_digest,
        dependency_lock_digest="4" * 64,
        product_id="coding",
        scope_id="workspace:test",
        product_policy_revision="coding-resource-shadow-v1",
        instance_revision_ref=instance_ref,
        package_source_identity=f"test:{plugin_id}",
        source_trust_class="test_trusted",
        source_trust_policy_revision="test-trust-v1",
        source_trusted=True,
    )
    admission = OwnerContributionAuthority(
        OwnerContributionPolicy(
            owner_id=owner_id,
            contribution_kind="resource_item",
            product_id="coding",
            policy_revision=f"resource-{resource_kind}-owner-v1",
            revocation_epoch=0,
            allowed_source_trust_classes=("test_trusted",),
            allowed_collection_ids=(schema_id,),
            allowed_requirement_bindings=("direct",),
            consumer_scope="session",
            consumer_refresh_boundary="sealed",
        )
    ).admit(candidate, issued_at=10, expires_at=100)
    return (
        acquire_admitted_package_resource(
            admission=admission,
            revision_handle=handle,
            source_root_order=source_root_order,
        ),
        body,
        handle,
    )


async def _three_source_precedence_and_exact_unload(tmp_path: Path) -> None:
    native_root = tmp_path / "native"
    native_skill = native_root / "skills" / "review" / "SKILL.md"
    native_skill.parent.mkdir(parents=True)
    native_body = _skill_body("review", "Native review", "Native body")
    native_skill.write_bytes(native_body)
    native_handle = mint_native_resource_root_handle(
        handle_id="native-test",
        root=native_root,
        source_class="project_local",
        root_kind="standard",
    )
    package_resource, _package_body, package_revision = _admitted_package_skill(
        tmp_path,
        plugin_id="review-package",
        public_name="review",
        description="Package review",
    )
    embedded_files = {
        "skills/review/SKILL.md": _skill_body(
            "review", "Embedded review", "Embedded body"
        ),
        "themes/dark.json": b'{"background": "black"}\n',
    }
    embedded = mint_embedded_resource_collection_handle(
        collection_id="coding.builtin",
        embedded_revision="builtin-1",
        files=embedded_files,
    )
    embedded_files["skills/review/SKILL.md"] = b"mutated caller mapping"

    shadow = await run_first_party_resource_catalog_shadow(
        product_id="coding",
        scope_id="workspace:test",
        runtime_id="resource-shadow:rcp3-precedence",
        product_policy_revision="coding-resource-shadow-v1",
        root_handles=(native_handle,),
        package_resources=(package_resource,),
        embedded_collections=(embedded,),
        issued_at=10,
        expires_at=100,
        now=20,
        projection_cwd=tmp_path,
    )
    assert {
        snapshot.source_generation_ref.source_id for snapshot in shadow.source_snapshots
    } == {
        NATIVE_RESOURCE_SOURCE_COMPONENT_ID,
        PACKAGE_RESOURCE_SOURCE_COMPONENT_ID,
        EMBEDDED_RESOURCE_SOURCE_COMPONENT_ID,
    }
    identity = next(
        entry.identity
        for entry in shadow.catalog_snapshot.effective_entries
        if entry.identity.resource_kind == "skill"
    )
    decision = next(
        item
        for item in shadow.catalog_snapshot.merge_decisions
        if item.identity == identity
    )
    assert len(decision.candidate_fingerprints) == 3
    winner = shadow.catalog_snapshot.candidate_by_fingerprint(
        decision.winner_candidate_fingerprint or ""
    )
    assert isinstance(winner.content_origin, NativeHostOrigin)
    origins = {
        type(candidate.content_origin)
        for candidate in shadow.catalog_snapshot.candidate_summaries
        if candidate.identity == identity
    }
    assert origins == {
        NativeHostOrigin,
        VerifiedPluginResourceOrigin,
        EmbeddedOemOrigin,
    }
    assert (await shadow.load(shadow.load_handle(identity))).body == native_body
    assert shadow.catalog_projection is not None
    compatibility = shadow.catalog_projection.to_compatibility_bundle()
    assert len(compatibility.skills) == 1
    assert compatibility.skills[0].source_kind == "project_local"
    assert compatibility.skills[0].content is None
    assert "body" not in compatibility.skills[0].metadata
    assert [theme.content for theme in compatibility.themes] == [
        '{"background": "black"}\n'
    ]

    assert await shadow.dispose() == ()
    assert package_resource.revision_handle.closed is True
    assert package_revision.closed is False
    assert embedded.closed is True
    with pytest.raises(RuntimeError, match="disposed"):
        await shadow.load(shadow.load_handle(identity))
    package_revision.close()


def test_native_package_and_embedded_sources_share_one_owner_generation(
    tmp_path: Path,
) -> None:
    asyncio.run(_three_source_precedence_and_exact_unload(tmp_path))


async def _embedded_extension_package_marker_is_not_a_resource(tmp_path: Path) -> None:
    collection = mint_embedded_resource_collection_handle(
        collection_id="coding.extensions",
        embedded_revision="builtin-1",
        files={
            "extensions/__init__.py": b"# package marker\n",
            "extensions/tool.py": b"def register(api):\n    del api\n",
        },
    )
    shadow = await run_first_party_resource_catalog_shadow(
        product_id="coding",
        scope_id="workspace:test",
        runtime_id="resource-shadow:embedded-extension-marker",
        product_policy_revision="coding-resource-shadow-v1",
        root_handles=(),
        embedded_collections=(collection,),
        issued_at=10,
        expires_at=100,
        now=20,
        projection_cwd=tmp_path,
    )
    assert shadow.catalog_projection is not None
    assert [
        extension.name
        for extension in shadow.catalog_projection.to_compatibility_bundle().extensions
    ] == ["tool.py"]
    assert await shadow.dispose() == ()
    assert collection.closed is True


def test_embedded_extension_package_marker_is_not_a_resource(tmp_path: Path) -> None:
    asyncio.run(_embedded_extension_package_marker_is_not_a_resource(tmp_path))


async def _same_precedence_package_conflict_is_rejected(tmp_path: Path) -> None:
    first, _, first_revision = _admitted_package_skill(
        tmp_path,
        plugin_id="first-review-package",
        public_name="review",
        description="First package",
        source_root_order=0,
    )
    second, _, second_revision = _admitted_package_skill(
        tmp_path,
        plugin_id="second-review-package",
        public_name="review",
        description="Second package",
        source_root_order=1,
    )
    shadow = await run_first_party_resource_catalog_shadow(
        product_id="coding",
        scope_id="workspace:test",
        runtime_id="resource-shadow:rcp3-conflict",
        product_policy_revision="coding-resource-shadow-v1",
        root_handles=(),
        package_resources=(first, second),
        issued_at=10,
        expires_at=100,
        now=20,
    )
    decision = next(
        item
        for item in shadow.catalog_snapshot.merge_decisions
        if item.identity.resource_kind == "skill"
    )
    assert decision.rejected is True
    assert decision.reason == "same_precedence_conflict"
    assert len(decision.candidate_fingerprints) == 2
    assert not shadow.catalog_snapshot.effective_entries
    assert await shadow.dispose() == ()
    assert first.revision_handle.closed is True
    assert second.revision_handle.closed is True
    assert first_revision.closed is False
    assert second_revision.closed is False
    first_revision.close()
    second_revision.close()


def test_two_admitted_packages_conflict_without_root_order_escape(
    tmp_path: Path,
) -> None:
    asyncio.run(_same_precedence_package_conflict_is_rejected(tmp_path))


async def _package_and_embedded_lazy_reads_pin_exact_sources(tmp_path: Path) -> None:
    package_resource, package_body, package_revision = _admitted_package_skill(
        tmp_path,
        plugin_id="package-lazy-read",
        public_name="package-review",
        description="Package lazy read",
    )
    embedded_body = _skill_body(
        "embedded-review",
        "Embedded lazy read",
        "Embedded exact body",
    )
    embedded = mint_embedded_resource_collection_handle(
        collection_id="coding.lazy",
        embedded_revision="builtin-1",
        files={"skills/embedded-review/SKILL.md": embedded_body},
    )
    shadow = await run_first_party_resource_catalog_shadow(
        product_id="coding",
        scope_id="workspace:test",
        runtime_id="resource-shadow:rcp3-load",
        product_policy_revision="coding-resource-shadow-v1",
        root_handles=(),
        package_resources=(package_resource,),
        embedded_collections=(embedded,),
        issued_at=10,
        expires_at=100,
        now=20,
    )
    identities = {
        item.identity.public_id: item.identity
        for item in shadow.catalog_snapshot.effective_entries
    }
    assert (
        await shadow.load(shadow.load_handle(identities["package-review/SKILL.md"]))
    ).body == package_body
    assert (
        await shadow.load(shadow.load_handle(identities["embedded-review/SKILL.md"]))
    ).body == embedded_body
    assert await shadow.dispose() == ()
    assert package_resource.revision_handle.closed is True
    assert package_revision.closed is False
    assert embedded.closed is True
    package_revision.close()


def test_package_and_embedded_lazy_reads_pin_exact_sources(tmp_path: Path) -> None:
    asyncio.run(_package_and_embedded_lazy_reads_pin_exact_sources(tmp_path))


async def _package_theme_projects_from_verified_body(tmp_path: Path) -> None:
    body = b'{"background": "blue"}\n'
    resource, _, revision = _admitted_package_file(
        tmp_path,
        plugin_id="package-theme",
        contribution_id="package-theme.dark",
        resource_kind="theme",
        locator="themes/dark.json",
        body=body,
        media_type="application/json",
        schema_id="loushang.resource.theme",
    )
    shadow = await run_first_party_resource_catalog_shadow(
        product_id="coding",
        scope_id="workspace:test",
        runtime_id="resource-shadow:rcp4-package-theme",
        product_policy_revision="coding-resource-shadow-v1",
        root_handles=(),
        package_resources=(resource,),
        issued_at=10,
        expires_at=100,
        now=20,
        projection_cwd=tmp_path,
    )

    assert shadow.catalog_projection is not None
    assert [theme.content for theme in shadow.catalog_projection.to_compatibility_bundle().themes] == [
        body.decode("utf-8")
    ]

    assert await shadow.dispose() == ()
    assert resource.revision_handle.closed is True
    assert revision.closed is False
    revision.close()


def test_package_theme_projects_from_verified_body(tmp_path: Path) -> None:
    asyncio.run(_package_theme_projects_from_verified_body(tmp_path))


async def _package_budget_failure_releases_source_leases(tmp_path: Path) -> None:
    first, _, first_revision = _admitted_package_skill(
        tmp_path,
        plugin_id="budget-first",
        public_name="first",
        description="First",
    )
    second, _, second_revision = _admitted_package_skill(
        tmp_path,
        plugin_id="budget-second",
        public_name="second",
        description="Second",
    )
    with pytest.raises(PackageResourceSourceError) as raised:
        await run_first_party_resource_catalog_shadow(
            product_id="coding",
            scope_id="workspace:test",
            runtime_id="resource-shadow:rcp3-package-budget",
            product_policy_revision="coding-resource-shadow-v1",
            root_handles=(),
            package_resources=(first, second),
            issued_at=10,
            expires_at=100,
            now=20,
            package_discovery_budget=PackageResourceDiscoveryBudget(maximum_items=1),
        )
    assert raised.value.code == "resource_source_discovery_budget_exceeded"
    assert raised.value.reason == "item_count_exceeded"
    assert first.revision_handle.closed is True
    assert second.revision_handle.closed is True
    assert first_revision.closed is False
    assert second_revision.closed is False
    first_revision.close()
    second_revision.close()


def test_package_budget_failure_releases_only_source_owned_leases(
    tmp_path: Path,
) -> None:
    asyncio.run(_package_budget_failure_releases_source_leases(tmp_path))


async def _embedded_budget_failure_releases_collection() -> None:
    collection = mint_embedded_resource_collection_handle(
        collection_id="coding.budget",
        embedded_revision="builtin-1",
        files={
            "skills/first/SKILL.md": _skill_body("first", "First", "First body"),
            "skills/second/SKILL.md": _skill_body("second", "Second", "Second body"),
        },
    )
    with pytest.raises(EmbeddedResourceSourceError) as raised:
        await run_first_party_resource_catalog_shadow(
            product_id="coding",
            scope_id="workspace:test",
            runtime_id="resource-shadow:rcp3-embedded-budget",
            product_policy_revision="coding-resource-shadow-v1",
            root_handles=(),
            embedded_collections=(collection,),
            issued_at=10,
            expires_at=100,
            now=20,
            embedded_discovery_budget=EmbeddedResourceDiscoveryBudget(maximum_items=1),
        )
    assert raised.value.code == "resource_source_discovery_budget_exceeded"
    assert raised.value.reason == "item_count_exceeded"
    assert collection.closed is True


def test_embedded_budget_failure_releases_collection() -> None:
    asyncio.run(_embedded_budget_failure_releases_collection())


async def _package_cancellation_releases_source_lease(tmp_path: Path) -> None:
    resource, _, revision = _admitted_package_skill(
        tmp_path,
        plugin_id="cancel-package",
        public_name="cancelled",
        description="Cancelled",
    )
    with pytest.raises(asyncio.CancelledError):
        await run_first_party_resource_catalog_shadow(
            product_id="coding",
            scope_id="workspace:test",
            runtime_id="resource-shadow:rcp3-package-cancel",
            product_policy_revision="coding-resource-shadow-v1",
            root_handles=(),
            package_resources=(resource,),
            issued_at=10,
            expires_at=100,
            now=20,
            discovery_cancellation_probe=lambda: True,
        )
    assert resource.revision_handle.closed is True
    assert revision.closed is False
    revision.close()


def test_package_cancellation_releases_only_source_owned_lease(
    tmp_path: Path,
) -> None:
    asyncio.run(_package_cancellation_releases_source_lease(tmp_path))


async def _source_deadlines_release_package_and_embedded_inputs(
    tmp_path: Path,
) -> None:
    resource, _, revision = _admitted_package_skill(
        tmp_path,
        plugin_id="deadline-package",
        public_name="deadline",
        description="Deadline",
    )
    with pytest.raises(PackageResourceSourceError) as package_raised:
        await run_first_party_resource_catalog_shadow(
            product_id="coding",
            scope_id="workspace:test",
            runtime_id="resource-shadow:rcp3-package-deadline",
            product_policy_revision="coding-resource-shadow-v1",
            root_handles=(),
            package_resources=(resource,),
            issued_at=10,
            expires_at=100,
            now=20,
            discovery_deadline_monotonic_ns=0,
        )
    assert package_raised.value.code == "resource_source_discovery_budget_exceeded"
    assert package_raised.value.reason == "deadline_exceeded"
    assert resource.revision_handle.closed is True
    assert revision.closed is False

    collection = mint_embedded_resource_collection_handle(
        collection_id="coding.deadline",
        embedded_revision="builtin-1",
        files={
            "skills/deadline/SKILL.md": _skill_body(
                "deadline", "Deadline", "Deadline body"
            )
        },
    )
    with pytest.raises(EmbeddedResourceSourceError) as embedded_raised:
        await run_first_party_resource_catalog_shadow(
            product_id="coding",
            scope_id="workspace:test",
            runtime_id="resource-shadow:rcp3-embedded-deadline",
            product_policy_revision="coding-resource-shadow-v1",
            root_handles=(),
            embedded_collections=(collection,),
            issued_at=10,
            expires_at=100,
            now=20,
            discovery_deadline_monotonic_ns=0,
        )
    assert embedded_raised.value.code == "resource_source_discovery_budget_exceeded"
    assert embedded_raised.value.reason == "deadline_exceeded"
    assert collection.closed is True
    revision.close()


def test_source_deadlines_release_package_and_embedded_inputs(tmp_path: Path) -> None:
    asyncio.run(_source_deadlines_release_package_and_embedded_inputs(tmp_path))


async def _bind_failure_releases_unmounted_source_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resource, _, revision = _admitted_package_skill(
        tmp_path,
        plugin_id="bind-failure-package",
        public_name="bind-failure",
        description="Bind failure",
    )
    collection = mint_embedded_resource_collection_handle(
        collection_id="coding.bind-failure",
        embedded_revision="builtin-1",
        files={
            "skills/embedded/SKILL.md": _skill_body(
                "embedded", "Embedded", "Embedded body"
            )
        },
    )

    async def fail_bind(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("injected bind failure")

    monkeypatch.setattr(CapabilityOwnerComponentBinder, "bind", fail_bind)
    with pytest.raises(RuntimeError, match="injected bind failure"):
        await run_first_party_resource_catalog_shadow(
            product_id="coding",
            scope_id="workspace:test",
            runtime_id="resource-shadow:rcp3-bind-failure",
            product_policy_revision="coding-resource-shadow-v1",
            root_handles=(),
            package_resources=(resource,),
            embedded_collections=(collection,),
            issued_at=10,
            expires_at=100,
            now=20,
        )
    assert resource.revision_handle.closed is True
    assert revision.closed is False
    assert collection.closed is True
    revision.close()


def test_bind_failure_releases_unmounted_source_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_bind_failure_releases_unmounted_source_inputs(tmp_path, monkeypatch))
