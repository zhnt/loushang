from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import time
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest

from loushang.ai.model import Capabilities, Model
from loushang.coding._resource_catalog_shadow import (
    CodingResourceCatalogAdmissionError,
    CodingResourceCatalogShadowAdmissionError,
    build_coding_initial_resource_catalog_shadow_adapter,
)
from loushang.coding.bootstrap import _create_agent_session, create_services
from loushang.coding.control import SettingsManager
from loushang.coding.prompt import (
    CODING_KERNEL_SYSTEM_PROMPT,
    CODING_STANDARD_SYSTEM_PROMPT_FRAGMENT,
)
from loushang.coding.session_manager import SessionManager
from loushang.harness.capabilities.consumer_requirements import (
    ProductCompositionAuthorityContext,
    ProductCompositionCompilation,
    ProductCompositionCompiler,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAdmissionRecord,
    OwnerContributionAuthority,
    OwnerContributionCandidateEnvelope,
    OwnerContributionKind,
    OwnerContributionPolicy,
    ResourceContributionSpec,
)
from loushang.harness.capabilities.model_input_contracts import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
)
from loushang.harness.capabilities.prompt_preflight import (
    SkillBodyLoadRequiresAsyncError,
)
from loushang.harness.capabilities.resources_consumers import (
    ResourceSkillStatusCatalogCapabilityConsumer,
)
from loushang.harness.capabilities.workspace_contracts import (
    WORKSPACE_CAPABILITY_DEFINITION,
)
from loushang.harness.cli import PackageLifecycleRequest, run_package_lifecycle
from loushang.harness.host.rpc.commands import RpcPackageCommands
from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.plugin_authoring.host import PluginDeclarationHost
from loushang.harness.resources._catalog_input_receipt import (
    ResourceCatalogInputReceipt,
)
from loushang.harness.resources._catalog_records import ResourceIdentity
from loushang.harness.resources.loader import (
    ResourceLoader,
    ResourceLoaderCompatibilityError,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.packages.mounts import PackageResourceMount
from loushang.harness.resources.plugins.authority import (
    PluginResolutionAuthority,
    PluginRuntimeResolution,
)
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.revisions import PluginRevisionStore
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
from loushang.harness.session.product_composition_assembly import (
    ProductCompositionAssemblyRequest,
    ProductContributionOwnerBinding,
)

_CODING_BASE_SHADOW_ROOT = (
    Path(__file__).parent.parent
    / "harness"
    / "resources"
    / "plugins"
    / "fixtures"
    / "coding_base_shadow"
)


def _copy_resource_only_plugin(target: Path) -> None:
    shutil.copytree(_CODING_BASE_SHADOW_ROOT, target)
    plugin_id = "coding.test.resources"
    manifest_path = target / "plugin.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["name"] = plugin_id
    manifest["contributionIndex"]["items"] = [
        item
        for item in manifest["contributionIndex"]["items"]
        if item["kind"] == "resource_item"
    ]
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    declarations_path = target / "declarations" / "plugin.json"
    declarations = json.loads(declarations_path.read_text(encoding="utf-8"))
    declarations["declarations"] = [
        item for item in declarations["declarations"] if item["kind"] == "resource_item"
    ]
    for declaration in declarations["declarations"]:
        declaration["pluginId"] = plugin_id
        if declaration["contributionId"] == "prompt-standard":
            declaration["payload"]["locator"] = "prompts/package-standard.md"
        if declaration["contributionId"] == "skill-standard":
            declaration["payload"]["locator"] = "skills/package-standard/SKILL.md"
    declarations_path.write_text(
        json.dumps(declarations, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    (target / "prompts" / "standard.md").rename(
        target / "prompts" / "package-standard.md"
    )
    skill_root = target / "skills" / "package-standard"
    (target / "skills" / "standard").rename(skill_root)
    (skill_root / "SKILL.md").write_text(
        "---\nname: package-standard\n"
        "description: Automatically admitted package Skill.\n---\n"
        "Use the admitted package Skill.\n",
        encoding="utf-8",
    )


def _model() -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128_000,
            max_tokens=4096,
        ),
    )


def _write_dynamic_prompt_extension(path: Path, *, text: str) -> None:
    path.write_text(
        "\n".join(
            (
                "from pathlib import Path",
                "",
                "from loushang.harness.extensions.agent import ExtensionResourceContribution",
                "from loushang.harness.resources.types import PromptFragmentDescriptor",
                "",
                "",
                "def register(api):",
                "    def discover(bundle, ctx):",
                "        del bundle, ctx",
                "        return ExtensionResourceContribution(",
                "            prompt_descriptors=[",
                "                PromptFragmentDescriptor(",
                "                    name='dynamic-review',",
                "                    source_path=Path(__file__).resolve(),",
                f"                    text={text!r},",
                "                )",
                "            ]",
                "        )",
                "",
                "    api.on('resources_discover', discover)",
                "",
            )
        ),
        encoding="utf-8",
    )


def _receipt(tmp_path: Path) -> ResourceCatalogInputReceipt:
    user_root = tmp_path / "user"
    project_root = tmp_path / "project"
    user_root.mkdir(exist_ok=True)
    project_root.mkdir(exist_ok=True)
    return ResourceCatalogInputReceipt(
        cwd=project_root,
        project_resource_root=project_root,
        project_context_roots=(tmp_path, project_root),
        package_mounts=(),
        package_resource_candidates=(),
        package_diagnostic_codes=(),
        user_resource_roots=(user_root,),
        explicit_user_resource_roots=frozenset({user_root}),
        additional_extension_paths=(),
        additional_skill_paths=(),
        additional_prompt_template_paths=(),
        additional_theme_paths=(),
        no_extensions=False,
        no_skills=False,
        no_prompt_templates=False,
        no_themes=False,
        no_context_files=False,
        built_in_resource_packages=("loushang.coding.resources",),
        context_file_names=("AGENTS.md", "CLAUDE.md"),
    )


def _coding_package_skill_admission(
    source: Path,
    *,
    revision_root: Path,
    locator: str = "skills/package-review/SKILL.md",
) -> OwnerContributionAdmissionRecord:
    published = PluginRevisionStore(revision_root).publish(
        PluginManifestParser().parse(source)
    )
    handle = published.revision_handle
    candidate = OwnerContributionCandidateEnvelope(
        owner_id="resources.skill",
        plugin_id="review-package",
        contribution_id="review-package.skill",
        contribution=ResourceContributionSpec(
            resource_kind="skill",
            locator=locator,
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
        product_id="coding",
        scope_id="session:test",
        product_policy_revision="coding-resource-catalog-shadow-v2",
        instance_revision_ref=PluginInstanceRevisionRef(
            instance_id="review-package@coding",
            plugin_id="review-package",
            revision=1,
        ),
        package_source_identity="test:review-package",
        source_trust_class="test_trusted",
        source_trust_policy_revision="test-trust-v1",
        source_trusted=True,
    )
    now = int(time.time())
    admission = OwnerContributionAuthority(
        OwnerContributionPolicy(
            owner_id="resources.skill",
            contribution_kind="resource_item",
            product_id="coding",
            policy_revision="resource-skill-owner-v1",
            revocation_epoch=0,
            allowed_source_trust_classes=("test_trusted",),
            allowed_collection_ids=("loushang.resource.skill",),
            allowed_requirement_bindings=("direct",),
            consumer_scope="session",
            consumer_refresh_boundary="sealed",
        )
    ).admit(candidate, issued_at=now - 60, expires_at=now + 3600)
    handle.close()
    return admission


def _coding_product_composition(
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
            product_id="coding",
            scope_id=candidate.scope_id,
            product_policy_revision=candidate.product_policy_revision,
            evaluated_at=int(time.time()),
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


def _coding_base_composition_assembly(
    tmp_path: Path,
    *,
    source_root: Path = _CODING_BASE_SHADOW_ROOT,
) -> tuple[ProductCompositionAssemblyRequest, PluginRuntimeResolution]:
    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=source_root))
    runtime = authority.publish_runtime(
        (inspection,),
        binding_store=PackageMaterializer(
            install_root=tmp_path / "composition-installed",
            plugin_revision_root=tmp_path / "composition-revisions",
        ),
    )
    [package] = runtime.packages
    [binding] = runtime.bindings
    plugin_id = package.manifest.name
    plan = PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id="coding",
            scope_id="workspace:test",
            policy_revision="coding-plugin-policy-1",
            instance_revision_refs=(
                PluginInstanceRevisionRef(
                    instance_id="coding.base@workspace:test",
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
    selection = PluginDeclarationHost().resolve(
        (package,),
        bindings=(binding,),
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    if not isinstance(selection, PluginSelection):
        runtime.close()
        raise AssertionError("coding.base data-only selection must finalize")
    owner_specs: tuple[tuple[str, OwnerContributionKind, str], ...] = (
        ("commands.session", "command_pack", "harness.session.standard"),
        ("resources.prompt", "resource_item", "loushang.resource.prompt"),
        ("resources.skill", "resource_item", "loushang.resource.skill"),
        ("tools.workspace", "tool_pack", "harness.workspace.core"),
    )
    owner_bindings = tuple(
        ProductContributionOwnerBinding(
            authority=OwnerContributionAuthority(
                OwnerContributionPolicy(
                    owner_id=owner_id,
                    contribution_kind=contribution_kind,
                    product_id="coding",
                    policy_revision=f"{owner_id}-v1",
                    revocation_epoch=0,
                    allowed_source_trust_classes=("host-equivalent-local",),
                    allowed_collection_ids=(collection_id,),
                    allowed_requirement_bindings=("direct",),
                    consumer_scope="session",
                    consumer_refresh_boundary="sealed",
                )
            ),
            admission_ttl_seconds=3600,
        )
        for owner_id, contribution_kind, collection_id in owner_specs
    )
    return (
        ProductCompositionAssemblyRequest(
            selection=selection,
            owner_bindings=owner_bindings,
            mandatory_roots=(MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,),
            definitions=(
                MODEL_INPUT_CAPABILITY_DEFINITION,
                WORKSPACE_CAPABILITY_DEFINITION,
            ),
        ),
        runtime,
    )


def test_coding_shadow_maps_one_receipt_without_bundle_inference(
    tmp_path: Path,
) -> None:
    adapter = build_coding_initial_resource_catalog_shadow_adapter(_receipt(tmp_path))

    selection = adapter.selection
    assert selection.product_policy_revision == "coding-resource-catalog-v3"
    assert [item.handle_id for item in selection.native_roots] == [
        "coding-user-0",
        "coding-project-context-0",
        "coding-project-context-1",
        "coding-project-standard",
    ]
    assert [item.root_kind for item in selection.native_roots] == [
        "combined",
        "context",
        "context",
        "standard",
    ]
    assert [item.source_root_order for item in selection.native_roots] == [
        0,
        0,
        1,
        0,
    ]
    assert len(selection.embedded_collections) == 1
    embedded = selection.embedded_collections[0]
    assert embedded.collection_id == "coding-built-in-0"
    assert embedded.embedded_revision.startswith("sha256:")
    assert selection.context_file_names == ("AGENTS.md", "CLAUDE.md")


def test_coding_shadow_preserves_disabled_context_as_standard_roots(
    tmp_path: Path,
) -> None:
    receipt = replace(
        _receipt(tmp_path),
        project_context_roots=(),
        no_context_files=True,
    )

    selection = build_coding_initial_resource_catalog_shadow_adapter(receipt).selection

    assert [item.handle_id for item in selection.native_roots] == [
        "coding-user-0",
        "coding-project-standard",
    ]
    assert [item.root_kind for item in selection.native_roots] == [
        "standard",
        "standard",
    ]


@pytest.mark.parametrize(
    ("change", "reason"),
    (
        (
            {"package_mounts": (PackageResourceMount(root=Path("/package")),)},
            "unverified_package_sources",
        ),
        (
            {"additional_skill_paths": (Path("skill"),)},
            "temporary_sources",
        ),
        ({"no_skills": True}, "resource_kind_switches"),
    ),
)
def test_coding_shadow_rejects_inputs_not_covered_by_the_thin_slice(
    tmp_path: Path,
    change: dict[str, object],
    reason: str,
) -> None:
    receipt = replace(_receipt(tmp_path), **change)

    with pytest.raises(CodingResourceCatalogShadowAdmissionError) as captured:
        build_coding_initial_resource_catalog_shadow_adapter(receipt)

    assert reason in captured.value.reasons


def test_coding_shadow_requires_exact_admission_for_verified_package_candidates(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source"
    skill = source / "skills" / "package-review" / "SKILL.md"
    project = tmp_path / "project"
    skill.parent.mkdir(parents=True)
    project.mkdir()
    (source / "plugin.json").write_text(
        json.dumps({"name": "review-package", "version": "1"}),
        encoding="utf-8",
    )
    skill.write_text(
        "---\nname: package-review\n"
        "description: Package review\n---\nReview from package.\n",
        encoding="utf-8",
    )
    admission = _coding_package_skill_admission(
        source,
        revision_root=tmp_path / "admission-revisions",
    )
    product_composition = _coding_product_composition(admission)
    published = PluginRevisionStore(tmp_path / "receipt-revisions").publish(
        PluginManifestParser().parse(source)
    )
    handle = published.revision_handle
    loader = ResourceLoader(project_resource_mode="legacy")
    loader.set_package_mounts(
        (
            PackageResourceMount(
                root=handle.root,
                content_digest=handle.content_digest,
                revision_handle=handle,
            ),
        )
    )
    try:
        loader.discover_resources(project)
        receipt = loader._take_initial_resource_catalog_input_receipt()

        with pytest.raises(CodingResourceCatalogShadowAdmissionError) as missing:
            build_coding_initial_resource_catalog_shadow_adapter(receipt)
        assert "package_candidate_without_admission" in missing.value.reasons

        adapter = build_coding_initial_resource_catalog_shadow_adapter(
            receipt,
            product_composition=product_composition,
            package_admission_now=int(time.time()),
        )
        assert adapter.selection.product_composition is product_composition
        assert len(adapter.selection.package_resources) == 1
        assert adapter.selection.package_resources[0].revision_handle is handle

        with pytest.raises(CodingResourceCatalogShadowAdmissionError) as foreign:
            build_coding_initial_resource_catalog_shadow_adapter(
                receipt,
                product_composition=replace(
                    product_composition,
                    authority_context=replace(
                        product_composition.authority_context,
                        product_id="foreign",
                    ),
                ),
                package_admission_now=int(time.time()),
            )
        assert "foreign_product_composition" in foreign.value.reasons

        invalid_locator_admission = _coding_package_skill_admission(
            source,
            revision_root=tmp_path / "invalid-locator-revisions",
            locator="/skills/package-review/SKILL.md",
        )
        invalid_locator_composition = _coding_product_composition(
            invalid_locator_admission
        )
        with pytest.raises(CodingResourceCatalogShadowAdmissionError) as invalid:
            build_coding_initial_resource_catalog_shadow_adapter(
                receipt,
                product_composition=invalid_locator_composition,
                package_admission_now=int(time.time()),
            )
        assert "invalid_package_admission" in invalid.value.reasons

        with pytest.raises(CodingResourceCatalogShadowAdmissionError) as diagnostic:
            build_coding_initial_resource_catalog_shadow_adapter(
                replace(
                    receipt,
                    package_diagnostic_codes=("unsupported_skill_entry",),
                ),
                product_composition=product_composition,
                package_admission_now=int(time.time()),
            )
        assert "package_discovery_diagnostics" in diagnostic.value.reasons
    finally:
        loader.close()


def test_coding_initial_catalog_shadow_publishes_project_context_and_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        project_root = tmp_path / "project"
        skill_root = project_root / "skills" / "review"
        skill_root.mkdir(parents=True)
        (project_root / "AGENTS.md").write_text("Project guidance", encoding="utf-8")
        (skill_root / "SKILL.md").write_text(
            "---\nname: review\ndescription: Review code\n---\nReview carefully.\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "missing-home"))
        services = create_services(
            settings_manager=SettingsManager(
                global_settings_path=tmp_path / "global-settings.json",
                project_settings_path=tmp_path / "project-settings.json",
            )
        )
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(project_root),
            persist=False,
        )
        session = _create_agent_session(
            session_manager=manager,
            services=services,
            model=_model(),
        )
        bootstrap = session._initial_resource_catalog_bootstrap
        assert bootstrap is not None
        resource_candidate = session._staged_resource_candidate
        assert resource_candidate is not None
        try:
            with pytest.raises(RuntimeError, match="v4 capture is not available"):
                session.list_skill_statuses()
            assert "Review code" not in session.agent.system_prompt
            assert "skill:review" not in {
                command.name for command in session.list_commands()
            }

            await session.prepare_model_call_runtime()

            assert bootstrap.state == "published"
            assert resource_candidate.ownership_state == "graph_owned"
            assert session._resource_catalog_snapshot is not None
            statuses = session.list_skill_statuses()
            assert [(status.name, status.status) for status in statuses] == [
                ("review", "effective"),
                ("standard", "effective"),
            ]
            assert session.resource_bundle is not None
            assert [skill.name for skill in session.resource_bundle.skills] == [
                "review",
                "standard",
            ]
            assert [
                descriptor.text
                for descriptor in session.resource_bundle.prompt_descriptors
            ] == [
                "Project guidance",
                CODING_STANDARD_SYSTEM_PROMPT_FRAGMENT.rstrip(),
            ]
            assert "Review code" in session.agent.system_prompt
            assert "Review carefully." not in session.agent.system_prompt
            assert "skill:review" in {
                command.name for command in session.list_commands()
            }

            session.resource_bundle.skills[0] = replace(
                session.resource_bundle.skills[0],
                content="Forged compatibility body.",
            )
            preflight = await session._preflight_user_input_async(
                "/skill:review inspect this change"
            )
            assert "Review carefully." in preflight.text
            assert "Forged compatibility body." not in preflight.text
            assert len(preflight.loaded_skills) == 1
            loaded_skill = preflight.loaded_skills[0]
            assert loaded_skill.receipt.content_digest == (
                statuses[0].expected_content_digest
            )
            assert loaded_skill.receipt.content_length == (
                statuses[0].expected_content_length
            )
            alias_preflight = await session._preflight_user_input_async(
                "/skill:review/SKILL.md through canonical id"
            )
            assert "Review carefully." in alias_preflight.text
            assert alias_preflight.loaded_skills[0].summary.name == "review"
            empty_preflight = await session._preflight_user_input_async("/skill:")
            assert empty_preflight.text == "/skill:"
            assert [item.code for item in empty_preflight.diagnostics] == [
                "unresolved_skill_reference"
            ]
            with pytest.raises(
                SkillBodyLoadRequiresAsyncError,
                match="requires asynchronous",
            ):
                session._preflight_user_input("/skill:review")
            with pytest.raises(SkillBodyLoadRequiresAsyncError):
                session.steer("/skill:review queued steer")
            with pytest.raises(SkillBodyLoadRequiresAsyncError):
                session.follow_up("/skill:review queued follow-up")
            assert session.get_steering_messages() == []
            assert session.get_follow_up_messages() == []

            executed = await session.execute_command_async(
                "skill:review",
                "through command dispatch",
            )
            assert executed is not None
            assert executed.result["source"] == "skill"
            assert "Review carefully." in executed.result["text"]
            assert "Forged compatibility body." not in executed.result["text"]

            # Enumeration and exact body loads are pinned to the captured
            # Catalog Consumer, not the eager compatibility Bundle.
            session.resource_bundle.skills.clear()
            session._rebuild_prompt_and_tools_view()
            assert "Review code" in session.agent.system_prompt
            assert "skill:review" in {
                command.name for command in session.list_commands()
            }
            after_clear = await session._preflight_user_input_async(
                "/skill:review after compatibility clear"
            )
            assert "Review carefully." in after_clear.text
        finally:
            await session.dispose()
        assert resource_candidate.ownership_state == "disposed"
        assert session._capability_graph_runtime.is_closed is True
        assert session._capability_graph_runtime.has_pending_retirements is False

    asyncio.run(scenario())


def test_coding_catalog_bootstrap_fails_closed_when_extension_source_drifts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        project_root = tmp_path / "project-extension-drift"
        project_root.mkdir()
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "missing-home"))
        services = create_services(
            settings_manager=SettingsManager(
                global_settings_path=tmp_path / "global-settings.json",
                project_settings_path=tmp_path / "project-settings.json",
            )
        )
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(project_root),
            persist=False,
        )
        session = _create_agent_session(
            session_manager=manager,
            services=services,
            model=_model(),
        )
        extension = project_root / "extensions" / "late.py"
        extension.parent.mkdir()
        extension.write_text("def register(api):\n    del api\n", encoding="utf-8")
        try:
            with pytest.raises(
                RuntimeError,
                match="Extension bootstrap projection changed before Catalog",
            ):
                await session.prepare_model_call_runtime()
            assert session._skill_catalog_consumer is None
            assert session._resource_catalog_snapshot is None
        finally:
            await session.dispose()

    asyncio.run(scenario())


def test_coding_failed_initial_publication_leaves_loader_unpublished(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        project_root = tmp_path / "project-publication-failure"
        project_root.mkdir()
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "missing-home"))
        services = create_services(
            settings_manager=SettingsManager(
                global_settings_path=tmp_path / "global-settings.json",
                project_settings_path=tmp_path / "project-settings.json",
            )
        )
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(project_root),
            persist=False,
        )
        session = _create_agent_session(
            session_manager=manager,
            services=services,
            model=_model(),
        )
        original_commit = session._commit_initial_resource_publication

        def fail_after_commit(
            catalog: object,
            projection: object,
            bundle: object,
        ) -> None:
            original_commit(catalog, projection, bundle)  # type: ignore[arg-type]
            raise RuntimeError("injected initial publication failure")

        session._commit_initial_resource_publication = fail_after_commit  # type: ignore[method-assign]
        try:
            with pytest.raises(RuntimeError, match="injected initial publication"):
                await session.prepare_model_call_runtime()
            with pytest.raises(
                ResourceLoaderCompatibilityError,
                match="catalog_projection_not_published",
            ):
                session.resource_loader.get_resource_bundle()
        finally:
            await session.dispose()

    asyncio.run(scenario())


def test_catalog_compatibility_views_are_isolated_across_shared_services(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "missing-home"))
        services = create_services(
            settings_manager=SettingsManager(
                global_settings_path=tmp_path / "global-settings.json",
                project_settings_path=tmp_path / "project-settings.json",
            )
        )
        sessions = []
        for name in ("a", "b"):
            project = tmp_path / f"project-{name}"
            project.mkdir()
            (project / "AGENTS.md").write_text(
                f"Project {name.upper()} guidance",
                encoding="utf-8",
            )
            manager = await SessionManager.new(
                session_dir=tmp_path / f"sessions-{name}",
                cwd=str(project),
                persist=False,
            )
            session = _create_agent_session(
                session_manager=manager,
                services=services,
                model=_model(),
            )
            await session.prepare_model_call_runtime()
            sessions.append(session)

        first, second = sessions
        assert first.resource_loader is not second.resource_loader
        assert first.resource_loader is not services.resource_loader
        assert first.resource_loader.get_resource_bundle().agents_md == (
            "Project A guidance"
        )
        assert second.resource_loader.get_resource_bundle().agents_md == (
            "Project B guidance"
        )

        failed_project = tmp_path / "project-failed"
        failed_project.mkdir()
        failed_manager = await SessionManager.new(
            session_dir=tmp_path / "sessions-failed",
            cwd=str(failed_project),
            persist=False,
        )
        failed = _create_agent_session(
            session_manager=failed_manager,
            services=services,
            model=_model(),
        )
        original_commit = failed._commit_initial_resource_publication

        def fail_after_commit(
            catalog: object,
            projection: object,
            bundle: object,
        ) -> None:
            original_commit(catalog, projection, bundle)  # type: ignore[arg-type]
            raise RuntimeError("injected interleaved publication failure")

        failed._commit_initial_resource_publication = fail_after_commit  # type: ignore[method-assign]
        try:
            with pytest.raises(RuntimeError, match="interleaved publication"):
                await failed.prepare_model_call_runtime()
            with pytest.raises(
                ResourceLoaderCompatibilityError,
                match="catalog_projection_not_published",
            ):
                failed.resource_loader.get_resource_bundle()
            assert first.resource_loader.get_resource_bundle().agents_md == (
                "Project A guidance"
            )
            assert second.resource_loader.get_resource_bundle().agents_md == (
                "Project B guidance"
            )
        finally:
            await failed.dispose()
            for session in reversed(sessions):
                await session.dispose()

    asyncio.run(scenario())


def test_coding_initial_catalog_applies_disabled_skill_in_owner_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        project_root = tmp_path / "project"
        skill_root = project_root / "skills" / "review"
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text(
            "---\nname: review\ndescription: Review code\n---\nReview carefully.\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "missing-home"))
        settings = SettingsManager(
            global_settings_path=tmp_path / "global-settings.json",
            project_settings_path=tmp_path / "project-settings.json",
        )
        settings.update_settings(scope="project", disabled_skills=("review",))
        services = create_services(settings_manager=settings)
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(project_root),
            persist=False,
        )
        session = _create_agent_session(
            session_manager=manager,
            services=services,
            model=_model(),
        )
        try:
            assert (
                session._composition.resource_refresh_runtime._catalog_refresh_lock
                is services.resource_catalog_refresh_lock
            )
            await session.prepare_model_call_runtime()

            statuses = session.list_skill_statuses()
            assert {item.name for item in statuses} == {"review", "standard"}
            status = next(item for item in statuses if item.name == "review")
            assert (status.name, status.status, status.status_reason) == (
                "review",
                "inactive_activation",
                "activation_disabled",
            )
            assert status.declared_enabled is True
            assert status.effective is False
            standard_status = next(item for item in statuses if item.name == "standard")
            assert standard_status.status == "effective"
            assert "Review code" not in session.agent.system_prompt
            assert "skill:review" not in {
                command.name for command in session.list_commands()
            }
            disabled_preflight = await session._preflight_user_input_async(
                "/skill:review must remain unresolved"
            )
            assert disabled_preflight.text == ("/skill:review must remain unresolved")
            assert [item.code for item in disabled_preflight.diagnostics] == [
                "unresolved_skill_reference"
            ]
            assert disabled_preflight.loaded_skills == ()
        finally:
            await session.dispose()

    asyncio.run(scenario())


def test_coding_catalog_refresh_publishes_one_exact_next_generation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        project_root = tmp_path / "project-refresh"
        skill_file = project_root / "skills" / "review" / "SKILL.md"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text(
            "---\nname: review\ndescription: Review v1\n---\nReview v1 body.\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "missing-home"))
        services = create_services(
            settings_manager=SettingsManager(
                global_settings_path=tmp_path / "global-settings.json",
                project_settings_path=tmp_path / "project-settings.json",
            )
        )
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(project_root),
            persist=False,
        )
        session = _create_agent_session(
            session_manager=manager,
            services=services,
            model=_model(),
        )
        try:
            await session.prepare_model_call_runtime()
            old_consumer = session._skill_catalog_consumer
            mounted = session._mounted_resource_candidate
            assert old_consumer is not None
            assert mounted is not None
            assert old_consumer.catalog_generation == 1
            graph_generation = session._capability_graph_runtime.generation

            skill_file.write_text(
                "---\nname: review\ndescription: Review v2\n---\nReview v2 body.\n",
                encoding="utf-8",
            )
            await session._composition.resource_refresh_runtime.refresh_async(
                reason="test"
            )

            new_consumer = session._skill_catalog_consumer
            assert new_consumer is not None
            assert new_consumer is not old_consumer
            assert new_consumer.catalog_generation == 2
            assert {
                item.name: item.description
                for item in old_consumer.list_effective_skills()
            }["review"] == "Review v1"
            assert {
                item.name: item.description
                for item in new_consumer.list_effective_skills()
            }["review"] == "Review v2"
            assert session._capability_graph_runtime.generation == graph_generation
            assert session._composition.resource_refresh_runtime.resource_revision == 2
            assert mounted.ownership_state == "graph_owned"
            assert await mounted.retire_replaced_owner_generations() == ()
            loaded = await session._preflight_user_input_async(
                "/skill:review refreshed"
            )
            assert "Review v2 body." in loaded.text
            assert "Review v1 body." not in loaded.text
            with pytest.raises(RuntimeError, match="not graph-owned"):
                old_consumer.load_handle(old_consumer.list_effective_skills()[0])
        finally:
            await session.dispose()
            services.resource_loader.close()

    asyncio.run(scenario())


def test_coding_catalog_extension_refresh_pins_real_load_and_serves_g2_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        project_root = tmp_path / "project-extension-refresh"
        extension_file = project_root / "extensions" / "dynamic_review.py"
        extension_file.parent.mkdir(parents=True)
        _write_dynamic_prompt_extension(extension_file, text="extension body v1")
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "missing-home"))
        services = create_services(
            settings_manager=SettingsManager(
                global_settings_path=tmp_path / "global-settings.json",
                project_settings_path=tmp_path / "project-settings.json",
            )
        )
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions-extension-refresh",
            cwd=str(project_root),
            persist=False,
        )
        session = _create_agent_session(
            session_manager=manager,
            services=services,
            model=_model(),
        )
        identity = ResourceIdentity(
            resource_kind="prompt",
            schema_id="loushang.resource.prompt",
            schema_version=1,
            public_id="dynamic-review",
        )
        release_load: asyncio.Event | None = None
        inflight: asyncio.Task[object] | None = None
        refresh: asyncio.Task[None] | None = None
        try:
            await session.prepare_model_call_runtime()
            facets = session._resource_skill_catalog_facets
            assert facets is not None
            generation_one = ResourceSkillStatusCatalogCapabilityConsumer(facets)
            assert generation_one.snapshot.catalog_generation == 1
            handle_one = generation_one.load_handle(identity)

            mounted = session._mounted_resource_candidate
            assert mounted is not None
            old_owner = mounted._require_prepared_owner_generation()
            old_source_lease = old_owner._shadow._extension_source_lease  # type: ignore[attr-defined]
            assert old_source_lease is not None
            old_source_generation = old_source_lease._owner  # type: ignore[attr-defined]
            original_load = old_source_lease.load
            load_started = asyncio.Event()
            release_load = asyncio.Event()

            async def blocked_load(handle):  # type: ignore[no-untyped-def]
                load_started.set()
                await release_load.wait()
                return original_load(handle)

            old_source_lease.load = blocked_load  # type: ignore[method-assign]
            inflight = asyncio.create_task(generation_one.load(handle_one))
            await load_started.wait()

            _write_dynamic_prompt_extension(
                extension_file,
                text="extension body from generation two",
            )
            refresh = asyncio.create_task(
                session._composition.resource_refresh_runtime.refresh_async(
                    reason="extension-g2"
                )
            )

            async def wait_for_publication() -> None:
                while (
                    getattr(
                        session._resource_catalog_snapshot,
                        "catalog_generation",
                        0,
                    )
                    < 2
                ):
                    await asyncio.sleep(0)

            await asyncio.wait_for(wait_for_publication(), timeout=5)
            assert refresh.done() is False
            assert old_source_generation.is_disposed is False

            generation_two = ResourceSkillStatusCatalogCapabilityConsumer(facets)
            assert generation_two.snapshot.catalog_generation == 2
            loaded_two = await generation_two.load(generation_two.load_handle(identity))
            assert loaded_two.body == b"extension body from generation two"

            release_load.set()
            assert (await inflight).body == b"extension body v1"
            await refresh
            assert old_source_generation.is_disposed is True
        finally:
            if release_load is not None:
                release_load.set()
            tasks = tuple(
                task
                for task in (inflight, refresh)
                if task is not None and not task.done()
            )
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            await session.dispose()
            services.resource_loader.close()

    asyncio.run(scenario())


def test_coding_catalog_refresh_cancellation_rolls_back_prepared_successor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        project_root = tmp_path / "project-refresh-cancel"
        skill_file = project_root / "skills" / "review" / "SKILL.md"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text(
            "---\nname: review\ndescription: Review v1\n---\nReview v1.\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "missing-home"))
        services = create_services(
            settings_manager=SettingsManager(
                global_settings_path=tmp_path / "global-settings.json",
                project_settings_path=tmp_path / "project-settings.json",
            )
        )
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions-cancel",
            cwd=str(project_root),
            persist=False,
        )
        session = _create_agent_session(
            session_manager=manager,
            services=services,
            model=_model(),
        )
        try:
            await session.prepare_model_call_runtime()
            initial_catalog = session._resource_catalog_snapshot
            mounted = session._mounted_resource_candidate
            factory = session._resource_catalog_refresh_bootstrap_factory
            assert mounted is not None
            assert factory is not None
            prepared = asyncio.Event()
            successors: list[object] = []
            bootstraps: list[object] = []
            original_stage = mounted.stage_refresh_successor

            def capture_successor():  # type: ignore[no-untyped-def]
                successor = original_stage()
                successors.append(successor)
                return successor

            def blocking_factory(generation: int):  # type: ignore[no-untyped-def]
                bootstrap = factory(generation)
                bootstraps.append(bootstrap)
                original_prepare = bootstrap.prepare

                async def prepare_then_block(**kwargs):  # type: ignore[no-untyped-def]
                    await original_prepare(**kwargs)
                    prepared.set()
                    await asyncio.Event().wait()

                bootstrap.prepare = prepare_then_block  # type: ignore[method-assign]
                return bootstrap

            mounted.stage_refresh_successor = capture_successor  # type: ignore[method-assign]
            session._resource_catalog_refresh_bootstrap_factory = blocking_factory
            task = asyncio.create_task(session.refresh_resources())
            await prepared.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

            assert len(successors) == 1
            assert successors[0].ownership_state == "disposed"  # type: ignore[attr-defined]
            assert len(bootstraps) == 1
            assert bootstraps[0].state == "disposed"  # type: ignore[attr-defined]
            assert session._resource_catalog_snapshot is initial_catalog
            assert session._skill_catalog_consumer is not None
            assert session._skill_catalog_consumer.catalog_generation == 1
            assert session._composition.resource_refresh_runtime.resource_revision == 1
        finally:
            await session.dispose()
            services.resource_loader.close()

    asyncio.run(scenario())


def test_coding_catalog_package_mutations_publish_before_return(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        project_root = tmp_path / "project-package-refresh"
        project_root.mkdir()
        package_root = tmp_path / "review-package"
        _copy_resource_only_plugin(package_root)
        project_settings_path = tmp_path / "project-settings.json"
        project_settings_path.write_text(
            json.dumps({"plugin_sources": [str(package_root)]}),
            encoding="utf-8",
        )
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "missing-home"))
        settings = SettingsManager(
            global_settings_path=tmp_path / "global-settings.json",
            project_settings_path=project_settings_path,
        )
        services = create_services(settings_manager=settings)
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(project_root),
            persist=False,
        )
        session = _create_agent_session(
            session_manager=manager,
            services=services,
            model=_model(),
        )
        try:
            await session.prepare_model_call_runtime()
            initial = session._skill_catalog_consumer
            assert initial is not None
            assert initial.catalog_generation == 1
            assert [item.name for item in initial.list_effective_skills()] == [
                "package-standard",
                "standard",
            ]

            (package_root / "skills" / "package-standard" / "SKILL.md").write_text(
                "---\nname: package-standard\n"
                "description: Updated admitted package Skill.\n---\n"
                "Use the updated admitted package Skill.\n",
                encoding="utf-8",
            )
            updated = await session.update_package(str(package_root))
            after_update = session._skill_catalog_consumer
            assert updated["lifecycle"] == "installed"
            assert after_update is not None
            assert after_update.catalog_generation == 2
            assert [item.name for item in after_update.list_effective_skills()] == [
                "package-standard",
                "standard",
            ]
            loaded = await session._preflight_user_input_async(
                "/skill:package-standard package generation"
            )
            assert "Use the updated admitted package Skill." in loaded.text

            # A package source that is not backed by a verified Plugin
            # admission must fail at the awaited boundary and roll back its
            # settings registration rather than returning false success.
            unsupported_root = tmp_path / "unsupported-package"
            unsupported_root.mkdir()
            with pytest.raises(
                CodingResourceCatalogAdmissionError,
                match="unverified_package_sources",
            ):
                await session.install_package(
                    str(unsupported_root),
                    scope="session",
                )
            assert settings.get_package_sources() == []
            assert session._skill_catalog_consumer is after_update

            # Catalog uninstall awaits its own next publication.
            settings.add_package_source(str(unsupported_root), scope="session")
            lifecycle = await run_package_lifecycle(
                session,
                PackageLifecycleRequest(
                    uninstall=(str(unsupported_root),),
                    scope="session",
                ),
            )
            uninstalled = lifecycle.outputs[0]["record"]
            after_uninstall = session._skill_catalog_consumer
            assert isinstance(uninstalled, dict)
            assert uninstalled["lifecycle"] == "remote_registered"
            assert after_uninstall is not None
            assert after_uninstall.catalog_generation == 3
            assert [item.name for item in after_uninstall.list_effective_skills()] == [
                "package-standard",
                "standard",
            ]
            assert settings.get_package_sources() == []

            # The RPC command keeps its stable wire name while resolving the
            # same async Catalog mutation entrypoint.
            settings.add_package_source(str(unsupported_root), scope="project")
            stdout = StringIO()
            rpc = RpcPackageCommands(
                runtime=session,
                get_session=lambda: session,
                output=RpcOutput(stdout),
            )
            handler = dict(rpc.bindings())["uninstall_package"]
            await handler("catalog-uninstall", {"source": str(unsupported_root)})
            response = json.loads(stdout.getvalue())
            assert response["success"] is True
            assert response["data"]["record"]["lifecycle"] == "remote_registered"
            assert session._skill_catalog_consumer is not None
            assert session._skill_catalog_consumer.catalog_generation == 4
            assert settings.get_package_sources() == []
        finally:
            await session.dispose()
            services.resource_loader.close()

    asyncio.run(scenario())


def test_coding_catalog_refresh_reloads_disabled_skill_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        project_root = tmp_path / "project-disabled-refresh"
        skill_file = project_root / "skills" / "review" / "SKILL.md"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text(
            "---\nname: review\ndescription: Review\n---\nReview body.\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "missing-home"))
        settings = SettingsManager(
            global_settings_path=tmp_path / "global-settings.json",
            project_settings_path=tmp_path / "project-settings.json",
        )
        services = create_services(settings_manager=settings)
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions-disabled",
            cwd=str(project_root),
            persist=False,
        )
        session = _create_agent_session(
            session_manager=manager,
            services=services,
            model=_model(),
        )
        try:
            await session.prepare_model_call_runtime()
            initial = session._skill_catalog_consumer
            assert initial is not None
            assert [item.name for item in initial.list_effective_skills()] == [
                "review",
                "standard",
            ]

            settings.update_settings(
                scope="project",
                disabled_skills=("review",),
            )
            await session.refresh_resources()

            consumer = session._skill_catalog_consumer
            assert consumer is not None
            assert consumer.catalog_generation == 2
            assert [item.name for item in consumer.list_effective_skills()] == [
                "standard"
            ]
            status = next(
                item for item in session.list_skill_statuses() if item.name == "review"
            )
            assert (status.status, status.status_reason) == (
                "inactive_activation",
                "activation_disabled",
            )
        finally:
            await session.dispose()
            services.resource_loader.close()

    asyncio.run(scenario())


def test_coding_catalog_refresh_restores_owner_and_product_view_on_publish_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        project_root = tmp_path / "project-refresh-rollback"
        skill_file = project_root / "skills" / "review" / "SKILL.md"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text(
            "---\nname: review\ndescription: Review v1\n---\nReview v1 body.\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "missing-home"))
        services = create_services(
            settings_manager=SettingsManager(
                global_settings_path=tmp_path / "global-settings.json",
                project_settings_path=tmp_path / "project-settings.json",
            )
        )
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(project_root),
            persist=False,
        )
        session = _create_agent_session(
            session_manager=manager,
            services=services,
            model=_model(),
        )
        try:
            await session.prepare_model_call_runtime()
            previous_catalog = session._resource_catalog_snapshot
            previous_projection = session._resource_catalog_projection
            previous_bundle = session.resource_bundle
            previous_consumer = session._skill_catalog_consumer
            mounted = session._mounted_resource_candidate
            assert mounted is not None

            skill_file.write_text(
                "---\nname: review\ndescription: Review v2\n---\nReview v2 body.\n",
                encoding="utf-8",
            )
            rebuild = session._rebuild_prompt_and_tools_view

            def reject_publication() -> None:
                raise RuntimeError("reject refreshed Product view")

            session._rebuild_prompt_and_tools_view = reject_publication  # type: ignore[method-assign]
            with pytest.raises(RuntimeError, match="reject refreshed Product view"):
                await session._composition.resource_refresh_runtime.refresh_async(
                    reason="test-failure"
                )
            session._rebuild_prompt_and_tools_view = rebuild  # type: ignore[method-assign]

            assert session._resource_catalog_snapshot is previous_catalog
            assert session._resource_catalog_projection is previous_projection
            assert session.resource_bundle is previous_bundle
            assert session._skill_catalog_consumer is previous_consumer
            assert mounted.resource_catalog_snapshot is previous_catalog
            assert mounted.ownership_state == "graph_owned"
            assert await mounted.retire_replaced_owner_generations() == ()
            assert session._composition.resource_refresh_runtime.resource_revision == 1
        finally:
            await session.dispose()
            services.resource_loader.close()

    asyncio.run(scenario())


def test_coding_catalog_refresh_preflight_rejection_releases_candidate_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        project_root = tmp_path / "project-refresh-preflight"
        skill_file = project_root / "skills" / "review" / "SKILL.md"
        skill_file.parent.mkdir(parents=True)
        skill_file.write_text(
            "---\nname: review\ndescription: Review v1\n---\nReview v1 body.\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "missing-home"))
        services = create_services(
            settings_manager=SettingsManager(
                global_settings_path=tmp_path / "global-settings.json",
                project_settings_path=tmp_path / "project-settings.json",
            )
        )
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(project_root),
            persist=False,
        )
        session = _create_agent_session(
            session_manager=manager,
            services=services,
            model=_model(),
        )
        try:
            await session.prepare_model_call_runtime()
            previous_catalog = session._resource_catalog_snapshot
            preflight = session._extension_declaration_preflight

            def reject_declarations(_snapshot: object) -> None:
                raise RuntimeError("Extension graph restart required")

            session._extension_declaration_preflight = reject_declarations  # type: ignore[assignment]
            with pytest.raises(RuntimeError, match="restart required"):
                await session._composition.resource_refresh_runtime.refresh_async(
                    reason="preflight-rejection"
                )
            assert session._resource_catalog_snapshot is previous_catalog

            session._extension_declaration_preflight = preflight
            skill_file.write_text(
                "---\nname: review\ndescription: Review v2\n---\nReview v2 body.\n",
                encoding="utf-8",
            )
            await session._composition.resource_refresh_runtime.refresh_async(
                reason="preflight-retry"
            )
            assert session._skill_catalog_consumer is not None
            assert session._skill_catalog_consumer.catalog_generation == 2
        finally:
            await session.dispose()
            services.resource_loader.close()

    asyncio.run(scenario())


def test_coding_initial_catalog_compiles_configured_plugin_resource_admissions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        project_root = tmp_path / "project"
        plugin_root = tmp_path / "plugin"
        project_root.mkdir()
        _copy_resource_only_plugin(plugin_root)
        project_settings_path = tmp_path / "project-settings.json"
        project_settings_path.write_text(
            json.dumps(
                {
                    "capabilities": {"coding.lsp": "always"},
                    "plugin_sources": [str(plugin_root)],
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "missing-home"))
        services = create_services(
            settings_manager=SettingsManager(
                global_settings_path=tmp_path / "global-settings.json",
                project_settings_path=project_settings_path,
            )
        )
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(project_root),
            persist=False,
        )
        session = _create_agent_session(
            session_manager=manager,
            services=services,
            model=_model(),
        )
        try:
            inputs = session._capability_composition_inputs
            assert inputs is not None
            assert inputs.product_composition.authority_context.product_id == "coding"
            assert session._coding_lsp_plugin_assembly is not None
            assert (
                session._coding_lsp_plugin_assembly.selection.plan.selected_plugin_ids
                == (
                    "coding.base",
                    "coding.lsp.default",
                    "coding.test.resources",
                )
            )
            assert {
                (item.plugin_id, item.contribution_id)
                for item in inputs.product_composition.catalog_admissions
            } == {
                ("coding.base", "coding.builtin"),
                ("coding.base", "coding.standard"),
                ("coding.lsp.default", "coding-lsp-tools"),
            }
            assert {
                (item.plugin_id, item.contribution_id)
                for item in inputs.product_composition.resource_admissions
            } == {
                ("coding.base", "prompt-standard"),
                ("coding.base", "skill-standard"),
                ("coding.test.resources", "prompt-standard"),
                ("coding.test.resources", "skill-standard"),
            }
            await session.prepare_model_call_runtime()

            assert [
                (item.name, item.status) for item in session.list_skill_statuses()
            ] == [
                ("package-standard", "effective"),
                ("standard", "effective"),
            ]
            assert (
                "Automatically admitted package Skill." in session.agent.system_prompt
            )
            assert "skill:package-standard" in {
                command.name for command in session.list_commands()
            }
        finally:
            await session.dispose()
            services.resource_loader.close()

    asyncio.run(scenario())


def test_coding_initial_catalog_admits_materialized_remote_plugin_resources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.coding.resource_runtime import CodingPackageMaterializer
    from loushang.harness.resources.packages.materializer import (
        GitPackageMaterializerBackend,
    )

    async def scenario() -> None:
        project_root = tmp_path / "project"
        source_root = tmp_path / "source"
        project_root.mkdir()
        _copy_resource_only_plugin(source_root)
        for args in (
            ("init",),
            ("config", "user.email", "test@example.invalid"),
            ("config", "user.name", "Test User"),
            ("add", "."),
            ("commit", "-m", "initial"),
        ):
            subprocess.run(
                ("git", *args),
                cwd=source_root,
                check=True,
                capture_output=True,
                text=True,
            )
        remote_root = tmp_path / "resource-plugin.git"
        subprocess.run(
            ("git", "clone", "--bare", str(source_root), str(remote_root)),
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )
        source = remote_root.as_uri()
        materializer = CodingPackageMaterializer(
            install_root=tmp_path / "installed",
            plugin_revision_root=tmp_path / "plugin-revisions",
            backend=GitPackageMaterializerBackend(),
        )
        record = materializer.materialize_remote_source_sync(source)
        assert record.lifecycle == "installed"
        project_settings_path = tmp_path / "project-settings.json"
        project_settings_path.write_text(
            json.dumps({"plugin_sources": [source]}),
            encoding="utf-8",
        )
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "missing-home"))
        services = create_services(
            settings_manager=SettingsManager(
                global_settings_path=tmp_path / "global-settings.json",
                project_settings_path=project_settings_path,
            )
        )
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(project_root),
            persist=False,
        )
        session = _create_agent_session(
            session_manager=manager,
            services=services,
            model=_model(),
            package_materializer=materializer,
        )
        try:
            await session.prepare_model_call_runtime()
            assert [
                (item.name, item.status) for item in session.list_skill_statuses()
            ] == [
                ("package-standard", "effective"),
                ("standard", "effective"),
            ]
        finally:
            await session.dispose()
            services.resource_loader.close()

    asyncio.run(scenario())


def test_default_coding_standard_publishes_base_without_hidden_settings_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        project_root = tmp_path / "project"
        project_root.mkdir()
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "missing-home"))
        services = create_services(
            settings_manager=SettingsManager(
                global_settings_path=tmp_path / "global-settings.json",
                project_settings_path=tmp_path / "project-settings.json",
            )
        )
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(project_root),
            persist=False,
        )

        session = _create_agent_session(
            session_manager=manager,
            services=services,
            model=_model(),
        )
        assembly = session._coding_base_plugin_assembly
        assert assembly is not None
        owner_handle = assembly.package.revision_handle
        [loader_mount] = services.resource_loader._package_mounts
        loader_handle = loader_mount.revision_handle
        assert loader_handle is not None
        assert loader_handle is not owner_handle
        assert services.settings_manager.get_settings().plugin_sources == ()
        assert assembly.scope_id == f"session:{manager.get_header().conversation_id}"
        assert session.agent.system_prompt.startswith(
            CODING_KERNEL_SYSTEM_PROMPT.rstrip()
        )
        assert (
            session.agent.system_prompt.count(
                CODING_STANDARD_SYSTEM_PROMPT_FRAGMENT.rstrip()
            )
            == 1
        )
        assert "You help users by reading files" not in session.agent.system_prompt
        assert owner_handle.closed is False

        try:
            await session.prepare_model_call_runtime()
            assert [
                (item.name, item.status) for item in session.list_skill_statuses()
            ] == [("standard", "effective")]
            assert session.resource_bundle is not None
            [base_skill] = session.resource_bundle.skills
            assert base_skill.name == "standard"
            assert base_skill.source_kind == "external_package"
            assert owner_handle.closed is False
        finally:
            await session.dispose()

        assert owner_handle.closed is True
        assert loader_handle.closed is False
        services.resource_loader.close()
        assert loader_handle.closed is True

    asyncio.run(scenario())


def test_coding_resource_authority_modes_are_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    skill_root = project_root / "skills" / "legacy"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\nname: legacy\n---\nLegacy explicit body.\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "missing-home"))
    services = create_services(
        settings_manager=SettingsManager(
            global_settings_path=tmp_path / "global-settings.json",
            project_settings_path=tmp_path / "project-settings.json",
        )
    )
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(project_root),
            persist=False,
        )
    )

    with pytest.raises(ValueError, match="authority mode is invalid"):
        _create_agent_session(
            session_manager=manager,
            services=services,
            model=_model(),
            resource_authority_mode="auto",  # type: ignore[arg-type]
        )

    session = _create_agent_session(
        session_manager=manager,
        services=services,
        model=_model(),
        resource_authority_mode="legacy_explicit",
    )
    assert session._initial_resource_catalog_bootstrap is None
    assert session._composition.resource_refresh_runtime.refresh_catalog is None
    legacy_preflight = session._preflight_user_input("/skill:legacy")
    assert "Legacy explicit body." in legacy_preflight.text
    assert legacy_preflight.loaded_skills == ()
    session.steer("/skill:legacy steer")
    session.follow_up("/skill:legacy follow-up")
    assert "Legacy explicit body." in session.get_steering_messages()[0]
    assert "Legacy explicit body." in session.get_follow_up_messages()[0]
    asyncio.run(session.dispose())


def test_coding_catalog_required_reports_missing_custom_loader_receipt(
    tmp_path: Path,
) -> None:
    from loushang.harness.resources.types import ResourceBundle

    class _Loader(ResourceLoader):
        def prepare_catalog_input_receipt(self, cwd: str | Path) -> ResourceBundle:
            return ResourceBundle(cwd=Path(cwd))

    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(tmp_path),
            persist=False,
        )
    )

    with pytest.raises(CodingResourceCatalogShadowAdmissionError) as captured:
        _create_agent_session(
            session_manager=manager,
            services=create_services(resource_loader=_Loader()),
            model=_model(),
        )

    assert captured.value.reasons == ("catalog_receipt_unavailable",)


def test_coding_legacy_authority_rejects_catalog_composition_inputs(
    tmp_path: Path,
) -> None:
    assembly, plugin_runtime = _coding_base_composition_assembly(tmp_path)
    manager = asyncio.run(
        SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(tmp_path),
            persist=False,
        )
    )
    try:
        with pytest.raises(ValueError, match="requires catalog_required authority"):
            _create_agent_session(
                session_manager=manager,
                services=create_services(),
                model=_model(),
                resource_authority_mode="legacy_explicit",
                initial_resource_catalog_product_composition_assembly=assembly,
            )
    finally:
        plugin_runtime.close()


def test_coding_initial_catalog_shadow_adopts_exact_admitted_package_skill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        project_root = tmp_path / "project"
        plugin_root = tmp_path / "plugin"
        project_root.mkdir()
        shutil.copytree(_CODING_BASE_SHADOW_ROOT, plugin_root)
        (plugin_root / "skills" / "standard" / "SKILL.md").write_text(
            "---\nname: standard\n"
            "description: Package Skill admitted by Product composition.\n---\n"
            "Review from the compiled package.\n",
            encoding="utf-8",
        )
        composition_assembly, plugin_runtime = _coding_base_composition_assembly(
            tmp_path,
            source_root=plugin_root,
        )
        project_settings_path = tmp_path / "project-settings.json"
        project_settings_path.write_text(
            json.dumps({"plugin_sources": [str(plugin_root)]}),
            encoding="utf-8",
        )
        monkeypatch.setenv("LOUSHANG_HOME", str(tmp_path / "missing-home"))
        services = create_services(
            settings_manager=SettingsManager(
                global_settings_path=tmp_path / "global-settings.json",
                project_settings_path=project_settings_path,
            )
        )
        manager = await SessionManager.new(
            session_dir=tmp_path / "sessions",
            cwd=str(project_root),
            persist=False,
        )
        session = _create_agent_session(
            session_manager=manager,
            services=services,
            model=_model(),
            initial_resource_catalog_product_composition_assembly=(
                composition_assembly
            ),
        )
        resource_candidate = session._staged_resource_candidate
        assert resource_candidate is not None
        assert session.resource_bundle is not None
        bootstrap_package_skill = next(
            skill
            for skill in session.resource_bundle.skills
            if skill.name == "standard"
        )
        try:
            await session.prepare_model_call_runtime()

            assert session.resource_bundle is not None
            package_skill = next(
                skill
                for skill in session.resource_bundle.skills
                if skill.name == "standard"
            )
            assert package_skill.source_kind == "external_package"
            assert bootstrap_package_skill.content is None
            assert package_skill.content is None
            assert (
                package_skill.name,
                package_skill.description,
                package_skill.disable_model_invocation,
                package_skill.canonical_name,
                package_skill.source_scope,
                package_skill.source_root_order,
            ) == (
                bootstrap_package_skill.name,
                bootstrap_package_skill.description,
                bootstrap_package_skill.disable_model_invocation,
                bootstrap_package_skill.canonical_name,
                bootstrap_package_skill.source_scope,
                bootstrap_package_skill.source_root_order,
            )
            session.resource_bundle.skills[:] = [
                replace(skill, content="Forged compatibility body.")
                if skill.name == "standard"
                else skill
                for skill in session.resource_bundle.skills
            ]
            preflight = await session._preflight_user_input_async("/skill:standard")
            assert "Review from the compiled package." in preflight.text
            assert "Forged compatibility body." not in preflight.text
            loaded = preflight.loaded_skills[0]
            assert loaded.summary.source_kind == "external_package"
            assert loaded.receipt.content_digest == (
                loaded.summary.expected_content_digest
            )
            assert resource_candidate.ownership_state == "graph_owned"
        finally:
            await session.dispose()
            services.resource_loader.close()
            plugin_runtime.close()
        assert resource_candidate.ownership_state == "disposed"
        assert session._capability_graph_runtime.has_pending_retirements is False

    asyncio.run(scenario())
