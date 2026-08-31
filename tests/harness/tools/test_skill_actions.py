from __future__ import annotations

import asyncio
import copy
import subprocess
import sys
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

import loushang.harness._owner_generation_authority as owner_authority
import loushang.harness.resource_catalog._owner_authority as resource_owner_authority
import loushang.harness.resource_catalog.generation as generation_runtime
import loushang.harness.resources._skill_action_authority as action_authority
import loushang.harness.tools.skill_actions as skill_action_runtime
import loushang.harness.workspace.process._sealed_executable as sealed_executable_runtime
from loushang.harness.approval import ApprovalDecision
from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    ExecutionAuthorizationError,
)
from loushang.harness.capabilities import (
    CapabilityGraphPlanRequest,
    RuntimeCapabilityGraphBinder,
    RuntimeCapabilityGraphPlanner,
    RuntimeCapabilityGraphRuntime,
    StagedResourceCompositionCandidate,
    stage_resource_composition_candidate,
    standard_capability_composition_plan,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAuthority,
    OwnerContributionPolicy,
    ResourceContributionSpec,
)
from loushang.harness.capabilities.resources_consumers import (
    ResourceSkillCatalogCapabilityConsumer,
    ResourceSkillStatusCatalogCapabilityConsumer,
)
from loushang.harness.capabilities.resources_contracts import (
    RESOURCES_CAPABILITY_DEFINITION_V3,
    RESOURCES_CAPABILITY_DEFINITION_V4,
    RESOURCES_SKILL_CATALOG_LOAD_REQUIREMENT,
    RESOURCES_SKILL_STATUS_CATALOG_LOAD_REQUIREMENT,
)
from loushang.harness.capabilities.resources_provider import (
    resources_capability_provider_binding,
)
from loushang.harness.environment import HostEnvironment, LocalHostEnvironmentProbe
from loushang.harness.plugin_authoring.contribution_admission import (
    prepare_owner_contribution_candidate,
)
from loushang.harness.plugin_authoring.host import PluginDeclarationHost
from loushang.harness.resource_catalog.generation import (
    PreparedResourceOwnerGeneration,
    ResourceOwnerGenerationDisposalError,
    prepare_first_party_resource_owner_generation,
)
from loushang.harness.resource_catalog.inputs import (
    acquire_admitted_package_resource,
)
from loushang.harness.resource_catalog.shadow import (
    run_first_party_resource_catalog_shadow,
)
from loushang.harness.resources._catalog_native_source import (
    mint_native_resource_root_handle,
)
from loushang.harness.resources._skill_action_authority import (
    _CatalogActionOwnerCapability,
    _register_catalog_managed_skill_action,
)
from loushang.harness.resources._skill_catalog_consumer import (
    SkillCatalogConsumer,
)
from loushang.harness.resources.packages.materializer import PackageMaterializer
from loushang.harness.resources.plugins.authority import PluginResolutionAuthority
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
from loushang.harness.resources.skill_actions import (
    CatalogManagedSkillAction,
    SkillActionCatalogSelection,
    SkillActionDocument,
    SkillActionDocumentCodec,
    _catalog_action_binding_fingerprint,
    _CatalogActionOwnerSeal,
)
from loushang.harness.runtime import RuntimeProfileResolver
from loushang.harness.sandbox import (
    LinuxBubblewrapBackend,
    SandboxBackendRegistration,
    SandboxBackendRegistry,
    SandboxBackendStatus,
    SandboxExecutionRuntime,
    SandboxScopeRequest,
    SandboxSettings,
    SandboxUnavailableError,
    bind_sandbox_execution_runtime,
    default_sandbox_backend_registry,
)
from loushang.harness.tools.process_hosting import (
    ProcessExecutionScope,
    ScopeBoundProcessLauncher,
    _bind_process_owner_launcher,
)
from loushang.harness.tools.skill_actions import (
    ManagedSkillActionBinding,
    ManagedSkillActionError,
    SkillRuntimeBinding,
    execute_managed_skill_action,
)
from loushang.harness.workspace.exec import ExecRequest, ExecService
from loushang.harness.workspace.process._sealed_executable import (
    SealedProcessExecutableUnavailable,
)
from loushang.harness.workspace.process.host import ProcessHost
from loushang.harness.workspace.process.local import ProcessContainmentPlan
from loushang.plugin import package, resource, skill_action, skill_action_effect


class _ApprovalResolver:
    actor_id = "root"

    def __init__(self, *, on_resolve=None) -> None:
        self.requests = []
        self._on_resolve = on_resolve

    def resolve(self, request):
        self.requests.append(request)
        if self._on_resolve is not None:
            self._on_resolve()
        return ApprovalDecision.allow()


class _Containment:
    requirement = "required"

    def __init__(self) -> None:
        self.plans = []

    async def plan(self, request, *, execution_profile):
        del execution_profile
        plan = ProcessContainmentPlan(request)
        self.plans.append(plan)
        return plan


class _HostedSandboxBackend:
    backend_id = "managed-action-test-sandbox"

    def probe(self, environment: HostEnvironment) -> SandboxBackendStatus:
        assert environment.os_family == "linux"
        return SandboxBackendStatus(
            backend_id=self.backend_id,
            state="available",
            enforced_capabilities=frozenset({"filesystem", "process"}),
        )

    async def open_scope(self, request):  # pragma: no cover - Exec is not used here
        del request
        raise AssertionError("managed action test must use hosted-process planning")

    async def _plan_hosted_process(self, request, scope):
        assert isinstance(scope, SandboxScopeRequest)
        return ProcessContainmentPlan(request)

    async def close(self) -> None:
        return None


def _declaration(script: bytes, *, argv: tuple[str, ...] = ("--check",)):
    return skill_action(
        id="review",
        script="scripts/review.py",
        script_digest=sha256(script).hexdigest(),
        runtime="python",
        argv=argv,
        environment=(("LANG", "C.UTF-8"),),
        effects=(skill_action_effect(kind="filesystem.read", target="workspace"),),
    )


async def _owner_built_skill_consumer(
    *,
    root_handles=(),
    package_resources=(),
    projection_cwd: Path,
    skill_catalog_version: int = 3,
) -> tuple[
    SkillCatalogConsumer,
    RuntimeCapabilityGraphBinder,
    RuntimeCapabilityGraphRuntime,
]:
    """Mount one production graph and return its owner-built Skill consumer."""

    profile = RuntimeProfileResolver().resolve(
        standard_capability_composition_plan(product_id="coding")
    )
    candidate = stage_resource_composition_candidate(profile)
    await prepare_first_party_resource_owner_generation(
        staged_candidate=candidate,
        product_id="coding",
        scope_id="workspace:test",
        runtime_id=f"managed-action:{uuid4().hex}",
        product_policy_revision="managed-action-test-v1",
        root_handles=tuple(root_handles),
        package_resources=tuple(package_resources),
        issued_at=10,
        expires_at=100,
        now=20,
        projection_cwd=projection_cwd,
    )
    if skill_catalog_version not in {3, 4}:
        raise ValueError("test Skill Catalog version must be 3 or 4")
    binding = resources_capability_provider_binding(
        profile=profile,
        scope_instance_id=f"session:{uuid4().hex}",
        staged_candidate=candidate,
        enable_skill_catalog_v3=skill_catalog_version == 3,
        enable_skill_catalog_v4=skill_catalog_version == 4,
    )
    definition = (
        RESOURCES_CAPABILITY_DEFINITION_V3
        if skill_catalog_version == 3
        else RESOURCES_CAPABILITY_DEFINITION_V4
    )
    plan = RuntimeCapabilityGraphPlanner().plan(
        CapabilityGraphPlanRequest(
            product_id="coding",
            roots=(definition.capability_id,),
            definitions=(definition,),
            providers=(binding.provider,),
        )
    )
    runtime = RuntimeCapabilityGraphRuntime(
        product_id="coding",
        runtime_id=f"managed-action-runtime:{uuid4().hex}",
        profile_fingerprint=sha256(b"managed-action-profile").hexdigest(),
    )
    binder = RuntimeCapabilityGraphBinder()
    await binder.bind(runtime, plan, (binding,))
    catalog = (
        ResourceSkillCatalogCapabilityConsumer(
            runtime.capture(RESOURCES_SKILL_CATALOG_LOAD_REQUIREMENT)
        )
        if skill_catalog_version == 3
        else ResourceSkillStatusCatalogCapabilityConsumer(
            runtime.capture(RESOURCES_SKILL_STATUS_CATALOG_LOAD_REQUIREMENT)
        )
    )
    return catalog.skill_consumer, binder, runtime


async def _mounted_catalog_action(
    script: bytes,
    *,
    root: Path,
    declaration=None,
    skill_catalog_version: int = 3,
) -> tuple[
    CatalogManagedSkillAction,
    SkillCatalogConsumer,
    RuntimeCapabilityGraphBinder,
    RuntimeCapabilityGraphRuntime,
]:
    resource_root = root / f"catalog-{uuid4().hex}"
    skill_root = resource_root / "skills" / "review"
    declaration = declaration or _declaration(script)
    script_path = skill_root / declaration.relative_script
    script_path.parent.mkdir(parents=True)
    script_path.write_bytes(script)
    (skill_root / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review changes\n---\nReview carefully.\n",
        encoding="utf-8",
    )
    action_document = SkillActionDocumentCodec.encode_bytes(
        SkillActionDocument(actions=(declaration,))
    )
    (skill_root / "actions.json").write_bytes(action_document)
    root_handle = mint_native_resource_root_handle(
        handle_id=f"managed-action-{uuid4().hex}",
        root=resource_root,
        source_class="project_local",
        root_kind="standard",
    )
    consumer, binder, runtime = await _owner_built_skill_consumer(
        root_handles=(root_handle,),
        projection_cwd=root,
        skill_catalog_version=skill_catalog_version,
    )
    [summary] = consumer.list_effective_skills()
    [action] = consumer.capture_managed_actions(summary)
    return action, consumer, binder, runtime


async def _catalog_action(
    script: bytes,
    *,
    root: Path,
    declaration=None,
    skill_catalog_version: int = 3,
) -> CatalogManagedSkillAction:
    action, _consumer, binder, runtime = await _mounted_catalog_action(
        script,
        root=root,
        declaration=declaration,
        skill_catalog_version=skill_catalog_version,
    )
    try:
        return action
    finally:
        assert await binder.dispose(runtime) == ()


async def _catalog_package_action(
    script: bytes,
    *,
    root: Path,
    skill_catalog_version: int = 3,
) -> CatalogManagedSkillAction:
    plugin_id = f"managed-action-package-{uuid4().hex}"
    contribution_id = f"{plugin_id}.skill"
    source = root / f"source-{plugin_id}"
    locator = "skills/review"
    declaration = _declaration(script)
    compiled = package(
        id=plugin_id,
        version="1",
        contributions=(
            resource.skill(
                contribution_id=contribution_id,
                locator=locator,
                actions=(declaration,),
            ),
        ),
    )
    for artifact in compiled.artifacts:
        target = source / artifact.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(artifact.content)
    skill_root = source / locator
    (skill_root / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review package\n---\nReview carefully.\n",
        encoding="utf-8",
    )
    script_path = skill_root / declaration.relative_script
    script_path.parent.mkdir(parents=True)
    script_path.write_bytes(script)

    authority = PluginResolutionAuthority()
    inspection = authority.inspect(PluginSource(path=source))
    plugin_runtime = authority.publish_runtime(
        (inspection,),
        binding_store=PackageMaterializer(
            install_root=root / f"installed-{plugin_id}",
            plugin_revision_root=root / f"revisions-{plugin_id}",
        ),
    )
    [published_package] = plugin_runtime.packages
    [source_binding] = plugin_runtime.bindings
    [reservation] = published_package.contribution_index.items
    revision = published_package.revision_handle
    assert revision is not None
    plan = PluginSelectionPlanV2(
        context=PluginPreflightContextV1(
            product_id="coding",
            scope_id="workspace:test",
            policy_revision="managed-action-test-v1",
            instance_revision_refs=(
                PluginInstanceRevisionRef(
                    instance_id=f"{plugin_id}@product",
                    plugin_id=plugin_id,
                    revision=1,
                ),
            ),
        ),
        selected_plugin_ids=(plugin_id,),
        selected_contributions=(PluginContributionRef(plugin_id, contribution_id),),
        source_trust_snapshots=(
            PluginSourceTrustSnapshotV1(
                plugin_id=plugin_id,
                package_source_identity=source_binding.source_identity,
                source_trust_class="host-equivalent-local",
                source_trust_policy_revision="test-trust-v1",
                trusted=True,
            ),
        ),
        effective_configuration_set=PluginEffectiveConfigurationSetV1(
            entries=(
                PluginEffectiveConfigurationEntry(
                    plugin_id=plugin_id,
                    contribution_id=contribution_id,
                    configuration={},
                ),
            )
        ),
        allowed_authority_ceiling=reservation.requested_authorities,
    )
    selection = PluginDeclarationHost().resolve(
        (published_package,),
        bindings=(source_binding,),
        plan=plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    assert isinstance(selection, PluginSelection)
    [plugin_candidate] = selection.candidates
    candidate = prepare_owner_contribution_candidate(selection, plugin_candidate)
    assert isinstance(candidate.contribution, ResourceContributionSpec)
    assert candidate.contribution.managed_skill_actions is True
    admission = OwnerContributionAuthority(
        OwnerContributionPolicy(
            owner_id="resources.skill",
            contribution_kind="resource_item",
            product_id="coding",
            policy_revision="resource-skill-owner-v1",
            revocation_epoch=0,
            allowed_source_trust_classes=("host-equivalent-local",),
            allowed_collection_ids=("loushang.resource.skill",),
            allowed_requirement_bindings=("direct",),
            consumer_scope="session",
            consumer_refresh_boundary="sealed",
        )
    ).admit(candidate, issued_at=10, expires_at=100)
    resource_input = acquire_admitted_package_resource(
        admission=admission,
        revision_handle=revision,
    )
    try:
        consumer, binder, runtime = await _owner_built_skill_consumer(
            package_resources=(resource_input,),
            projection_cwd=root,
            skill_catalog_version=skill_catalog_version,
        )
        try:
            [summary] = consumer.list_effective_skills()
            [action] = consumer.capture_managed_actions(summary)
            return action
        finally:
            assert await binder.dispose(runtime) == ()
    finally:
        resource_input.close()
        plugin_runtime.close()


def _launcher(
    *,
    resolver,
    root: Path,
) -> tuple[SandboxExecutionRuntime, ScopeBoundProcessLauncher]:
    profile = EffectiveExecutionProfile(
        readable_roots=(root,),
        writable_roots=(root,),
    )
    try:
        runtime = bind_sandbox_execution_runtime(
            base_exec_service=ExecService(execution_profile=profile),
            settings=SandboxSettings(enabled=True, requirement="required"),
            scope_request_factory=lambda request: _sandbox_scope(root, request),
            execution_profile=profile,
        )
    except SandboxUnavailableError as exc:
        pytest.skip(f"managed action requires an enforcing Sandbox backend: {exc}")
    launcher = runtime.bind_process_launcher(
        ProcessExecutionScope(
            approval_resolver=resolver,
            execution_profile_ceiling=profile,
            require_approval=True,
        )
    )
    assert isinstance(launcher, ScopeBoundProcessLauncher)
    return runtime, launcher


def _sandbox_scope(root: Path, request: ExecRequest) -> SandboxScopeRequest:
    assert request.cwd is not None
    return SandboxScopeRequest(
        cwd=Path(request.cwd),
        readable_roots=(root, Path(sys.executable).resolve().parent.parent),
        writable_roots=(root,),
    )


def test_skill_action_document_is_strict_and_canonical() -> None:
    declaration = _declaration(b"print('ok')\n")
    encoded = SkillActionDocumentCodec.encode_bytes(
        SkillActionDocument(actions=(declaration,))
    )

    decoded = SkillActionDocumentCodec.decode_bytes(encoded)

    assert decoded.actions == (declaration,)
    with pytest.raises(ValueError):
        SkillActionDocumentCodec.decode_bytes(encoded + b"\n")


def test_catalog_action_authority_cannot_be_publicly_forged() -> None:
    assert not hasattr(action_authority, "_mint_catalog_action_owner_credential")
    assert not hasattr(
        action_authority,
        "_new_catalog_action_owner_generation_lifecycle",
    )
    assert not hasattr(
        action_authority,
        "_claim_catalog_action_owner_generation_registrar",
    )
    with pytest.raises(TypeError, match="Resource-owner-minted"):
        SkillActionCatalogSelection()
    with pytest.raises(TypeError, match="Resource-owner-minted"):
        CatalogManagedSkillAction()
    with pytest.raises(TypeError, match="Catalog-owner evidence"):
        ManagedSkillActionBinding()
    forged = object.__new__(CatalogManagedSkillAction)
    with pytest.raises(ValueError, match="owner evidence"):
        forged.verify()
    with pytest.raises(TypeError, match="Resource-owner-minted"):
        _CatalogActionOwnerCapability()
    with pytest.raises(TypeError, match="Resource-owner-built"):
        action_authority._CatalogActionOwnerSnapshot()
    with pytest.raises(TypeError, match="Resource-owner-minted"):
        action_authority._CatalogActionOwnerGenerationLifecycle()
    with pytest.raises(TypeError, match="candidate-minted"):
        owner_authority._OwnerGenerationAttachmentReceipt()
    with pytest.raises(TypeError, match="factory-minted"):
        owner_authority._OwnerCandidateFactoryIdentity()
    with pytest.raises(TypeError, match="factory-minted"):
        owner_authority._OwnerGenerationFactoryIdentity()
    assert not hasattr(action_authority, "_CatalogActionOwnerCandidateIdentity")
    assert not hasattr(
        action_authority,
        "_CatalogActionOwnerGenerationFactoryIdentity",
    )
    assert not hasattr(action_authority, "_prepare_catalog_action_owner_attachment")
    with pytest.raises(TypeError, match="Resource-owner-minted"):
        action_authority._CatalogActionOwnerBinding()
    with pytest.raises(TypeError, match="Resource-owner-minted"):
        action_authority._CatalogActionOwnerLiveness()
    with pytest.raises(ValueError, match="owner capability"):
        _register_catalog_managed_skill_action(
            forged,
            owner_capability=object(),  # type: ignore[arg-type]
        )


def test_fake_owner_cannot_enroll_through_structural_attachment() -> None:
    fake_owner = object.__new__(PreparedResourceOwnerGeneration)

    class StructuralCandidate:
        ownership_state = "root_owned"

        def _require_prepared_owner_generation(self):  # type: ignore[no-untyped-def]
            return fake_owner

    assert not owner_authority._is_owner_candidate_factory_recorded(
        StructuralCandidate()
    )
    assert not owner_authority._is_owner_generation_factory_recorded(fake_owner)
    forged_lifecycle = object.__new__(
        action_authority._CatalogActionOwnerGenerationLifecycle
    )
    with pytest.raises(TypeError, match="not authority-recorded"):
        action_authority._begin_catalog_action_owner_generation(
            forged_lifecycle,
            owner=fake_owner,
        )
    profile = RuntimeProfileResolver().resolve(
        standard_capability_composition_plan(product_id="coding")
    )
    genuine_candidate = stage_resource_composition_candidate(profile)
    with pytest.raises(TypeError, match="requires a prepared owner generation"):
        genuine_candidate._attach_prepared_owner_generation(fake_owner)

    class StructuralGeneration:
        ownership_state = "root_owned"

    with pytest.raises(TypeError, match="requires a prepared owner generation"):
        genuine_candidate._attach_prepared_owner_generation(StructuralGeneration())

    class CompatibleCandidate(type(genuine_candidate)):
        pass

    compatible = CompatibleCandidate(
        binding=genuine_candidate.binding,
        _binder=genuine_candidate._binder,
        _profile=profile,
    )
    assert not owner_authority._is_owner_candidate_factory_recorded(compatible)
    with pytest.raises(TypeError, match="exact staged candidate"):
        compatible._begin_graph_construction()
    with pytest.raises(TypeError, match="staging-factory candidate"):
        compatible.stage_refresh_successor()
    compatible.dispose()
    genuine_candidate.dispose()


def test_direct_constructors_do_not_receive_factory_authority(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        profile = RuntimeProfileResolver().resolve(
            standard_capability_composition_plan(product_id="coding")
        )
        staged = stage_resource_composition_candidate(profile)
        direct_candidate = StagedResourceCompositionCandidate(
            binding=staged.binding,
            _binder=staged._binder,
            _profile=profile,
        )
        factory_shadow = await run_first_party_resource_catalog_shadow(
            product_id="coding",
            scope_id="workspace:factory-owner",
            runtime_id="resource-owner:factory-owner",
            product_policy_revision="managed-action-test-v1",
            root_handles=(),
            issued_at=10,
            expires_at=100,
            now=20,
            projection_cwd=tmp_path,
        )
        direct_shadow = await run_first_party_resource_catalog_shadow(
            product_id="coding",
            scope_id="workspace:direct-owner",
            runtime_id="resource-owner:direct-owner",
            product_policy_revision="managed-action-test-v1",
            root_handles=(),
            issued_at=10,
            expires_at=100,
            now=20,
            projection_cwd=tmp_path,
        )
        factory_owner = PreparedResourceOwnerGeneration._from_shadow(
            factory_shadow,
            runtime_id="resource-owner:factory-owner",
            catalog_generation=1,
        )
        direct_owner = PreparedResourceOwnerGeneration(
            _shadow=direct_shadow,
            runtime_id="resource-owner:direct-owner",
            catalog_generation=1,
            provider_binding_fingerprint="0" * 64,
        )
        assert owner_authority._is_owner_candidate_factory_recorded(staged)
        assert not owner_authority._is_owner_candidate_factory_recorded(
            direct_candidate
        )
        direct_candidate._owner_candidate_factory_identity = (
            staged._owner_candidate_factory_identity
        )
        assert not owner_authority._is_owner_candidate_factory_recorded(
            direct_candidate
        )
        assert owner_authority._is_owner_generation_factory_recorded(factory_owner)
        assert resource_owner_authority._is_resource_owner_factory_recorded(
            factory_owner
        )
        assert not owner_authority._is_owner_generation_factory_recorded(direct_owner)
        copied_owner = copy.copy(factory_owner)
        assert not owner_authority._is_owner_generation_factory_recorded(copied_owner)
        with pytest.raises(TypeError, match="factory-recorded generation"):
            copied_owner.retirement_receipt(contribution_ids=("copied",))

        class CompatibleGeneration(PreparedResourceOwnerGeneration):
            pass

        compatible_owner = CompatibleGeneration._from_shadow(
            direct_shadow,
            runtime_id="resource-owner:compatible-owner",
            catalog_generation=1,
        )
        assert not owner_authority._is_owner_generation_factory_recorded(
            compatible_owner
        )
        with pytest.raises(TypeError, match="factory-recorded generation"):
            compatible_owner.retirement_receipt(contribution_ids=("subclass",))
        with pytest.raises(TypeError, match="factory-recorded generation"):
            direct_owner.retirement_receipt(contribution_ids=("forged",))
        with pytest.raises(TypeError, match="not staging-factory-recorded"):
            direct_candidate._attach_prepared_owner_generation(factory_owner)
        with pytest.raises(TypeError, match="exact staged candidate"):
            direct_candidate._begin_graph_construction()
        with pytest.raises(TypeError, match="staging-factory candidate"):
            direct_candidate.stage_refresh_successor()
        with pytest.raises(TypeError, match="requires a prepared owner generation"):
            staged._attach_prepared_owner_generation(direct_owner)
        original_runtime_id = factory_owner.runtime_id
        factory_owner.runtime_id = "resource-owner:mutated"
        assert owner_authority._is_owner_generation_factory_recorded(factory_owner)
        assert not resource_owner_authority._is_resource_owner_factory_recorded(
            factory_owner
        )
        factory_owner.runtime_id = original_runtime_id
        original_catalog_generation = factory_owner.catalog_generation
        factory_owner.catalog_generation = 2
        assert owner_authority._is_owner_generation_factory_recorded(factory_owner)
        assert not resource_owner_authority._is_resource_owner_factory_recorded(
            factory_owner
        )
        factory_owner.catalog_generation = original_catalog_generation
        factory_owner.provider_binding_fingerprint = "1" * 64
        assert owner_authority._is_owner_generation_factory_recorded(factory_owner)
        assert not resource_owner_authority._is_resource_owner_factory_recorded(
            factory_owner
        )
        with pytest.raises(TypeError, match="unchanged factory-recorded generation"):
            factory_owner.retirement_receipt(contribution_ids=("mutated",))
        await factory_owner.dispose_root_owned()
        await direct_owner.dispose_root_owned()
        direct_candidate.dispose()
        staged.dispose()

    asyncio.run(scenario())


def test_consumed_attachment_receipt_cannot_be_replayed(tmp_path: Path) -> None:
    async def scenario() -> None:
        profile = RuntimeProfileResolver().resolve(
            standard_capability_composition_plan(product_id="coding")
        )
        candidate = stage_resource_composition_candidate(profile)
        shadow = await run_first_party_resource_catalog_shadow(
            product_id="coding",
            scope_id="workspace:receipt-replay",
            runtime_id="resource-owner:receipt-replay",
            product_policy_revision="managed-action-test-v1",
            root_handles=(),
            issued_at=10,
            expires_at=100,
            now=20,
            projection_cwd=tmp_path,
        )
        owner = PreparedResourceOwnerGeneration._from_shadow(
            shadow,
            runtime_id="resource-owner:receipt-replay",
            catalog_generation=1,
        )
        receipt = candidate._attach_prepared_owner_generation(owner)
        owner._accept_candidate_attachment(receipt)
        owner._commit_candidate_attachment(receipt)

        with pytest.raises(TypeError, match="not live exact evidence"):
            candidate._detach_failed_prepared_owner_generation(owner, receipt)

        with pytest.raises(TypeError, match="not live exact evidence"):
            action_authority._consume_catalog_action_owner_attachment(
                receipt,
                owner=owner,
                snapshot=None,
            )

        await candidate.dispose_root_owned()

    asyncio.run(scenario())


def test_repeated_preparation_preserves_the_existing_owner(tmp_path: Path) -> None:
    async def scenario() -> None:
        profile = RuntimeProfileResolver().resolve(
            standard_capability_composition_plan(product_id="coding")
        )
        candidate = stage_resource_composition_candidate(profile)
        await prepare_first_party_resource_owner_generation(
            staged_candidate=candidate,
            product_id="coding",
            scope_id="workspace:first-owner",
            runtime_id="resource-owner:first-owner",
            product_policy_revision="managed-action-test-v1",
            root_handles=(),
            issued_at=10,
            expires_at=100,
            now=20,
            projection_cwd=tmp_path,
        )
        first_owner = candidate._require_prepared_owner_generation()

        with pytest.raises(
            RuntimeError,
            match="already has a prepared owner generation",
        ):
            await prepare_first_party_resource_owner_generation(
                staged_candidate=candidate,
                product_id="coding",
                scope_id="workspace:second-owner",
                runtime_id="resource-owner:second-owner",
                product_policy_revision="managed-action-test-v1",
                root_handles=(),
                issued_at=10,
                expires_at=100,
                now=20,
                projection_cwd=tmp_path,
            )

        assert candidate._require_prepared_owner_generation() is first_owner
        await candidate.dispose_root_owned()

    asyncio.run(scenario())


def test_owner_factory_seal_failure_cleans_unpublished_shadow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        profile = RuntimeProfileResolver().resolve(
            standard_capability_composition_plan(product_id="coding")
        )
        candidate = stage_resource_composition_candidate(profile)
        shadows = []
        original_run = generation_runtime.run_first_party_resource_catalog_shadow

        async def capture_shadow(**kwargs):  # type: ignore[no-untyped-def]
            shadow = await original_run(**kwargs)
            shadows.append(shadow)
            return shadow

        def fail_seal(cls, shadow, **kwargs):  # type: ignore[no-untyped-def]
            raise FileNotFoundError("action root disappeared before owner sealing")

        monkeypatch.setattr(
            generation_runtime,
            "run_first_party_resource_catalog_shadow",
            capture_shadow,
        )
        monkeypatch.setattr(
            PreparedResourceOwnerGeneration,
            "_from_shadow",
            classmethod(fail_seal),
        )

        with pytest.raises(FileNotFoundError, match="disappeared"):
            await prepare_first_party_resource_owner_generation(
                staged_candidate=candidate,
                product_id="coding",
                scope_id="workspace:seal-failure",
                runtime_id="resource-owner:seal-failure",
                product_policy_revision="managed-action-test-v1",
                root_handles=(),
                issued_at=10,
                expires_at=100,
                now=20,
                projection_cwd=tmp_path,
            )

        assert len(shadows) == 1
        assert shadows[0].is_disposed
        assert candidate.prepared_owner_generation_state is None
        candidate.dispose()

    asyncio.run(scenario())


def test_attachment_enrollment_rolls_back_after_receipt_consumption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        profile = RuntimeProfileResolver().resolve(
            standard_capability_composition_plan(product_id="coding")
        )
        candidate = stage_resource_composition_candidate(profile)
        captured_owners = []
        captured_receipts = []
        original_accept = PreparedResourceOwnerGeneration._accept_candidate_attachment

        def consume_then_fail(self, receipt):  # type: ignore[no-untyped-def]
            captured_owners.append(self)
            captured_receipts.append(receipt)
            original_accept(self, receipt)
            raise RuntimeError("injected after receipt consumption")

        monkeypatch.setattr(
            PreparedResourceOwnerGeneration,
            "_accept_candidate_attachment",
            consume_then_fail,
        )
        with pytest.raises(RuntimeError, match="injected after receipt consumption"):
            await prepare_first_party_resource_owner_generation(
                staged_candidate=candidate,
                product_id="coding",
                scope_id="workspace:test",
                runtime_id="managed-action:attachment-rollback",
                product_policy_revision="managed-action-test-v1",
                root_handles=(),
                issued_at=10,
                expires_at=100,
                now=20,
                projection_cwd=tmp_path,
            )
        [owner] = captured_owners
        [receipt] = captured_receipts
        assert not candidate.has_prepared_owner_generation
        assert owner._skill_action_owner_lifecycle is None
        with pytest.raises(TypeError, match="not live exact evidence"):
            action_authority._consume_catalog_action_owner_attachment(
                receipt,
                owner=owner,
                snapshot=None,
            )
        forged_lifecycle = object.__new__(
            action_authority._CatalogActionOwnerGenerationLifecycle
        )
        with pytest.raises(TypeError, match="not authority-recorded"):
            action_authority._begin_catalog_action_owner_generation(
                forged_lifecycle,
                owner=owner,
            )
        candidate.dispose()

    asyncio.run(scenario())


def test_attachment_failure_retains_cleanup_custody_until_retry_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        profile = RuntimeProfileResolver().resolve(
            standard_capability_composition_plan(product_id="coding")
        )
        candidate = stage_resource_composition_candidate(profile)
        captured_owners = []
        disposal_attempts = 0
        original_dispose = PreparedResourceOwnerGeneration.dispose_root_owned

        def reject_attachment(self, receipt):  # type: ignore[no-untyped-def]
            del receipt
            captured_owners.append(self)
            raise RuntimeError("injected attachment rejection")

        async def fail_disposal_once(self):  # type: ignore[no-untyped-def]
            nonlocal disposal_attempts
            disposal_attempts += 1
            if disposal_attempts == 1:
                raise ResourceOwnerGenerationDisposalError(
                    ("synthetic_resource_retirement_pending",)
                )
            await original_dispose(self)

        monkeypatch.setattr(
            PreparedResourceOwnerGeneration,
            "_accept_candidate_attachment",
            reject_attachment,
        )
        monkeypatch.setattr(
            PreparedResourceOwnerGeneration,
            "dispose_root_owned",
            fail_disposal_once,
        )

        with pytest.raises(RuntimeError, match="injected attachment rejection"):
            await prepare_first_party_resource_owner_generation(
                staged_candidate=candidate,
                product_id="coding",
                scope_id="workspace:cleanup-retry",
                runtime_id="resource-owner:cleanup-retry",
                product_policy_revision="managed-action-test-v1",
                root_handles=(),
                issued_at=10,
                expires_at=100,
                now=20,
                projection_cwd=tmp_path,
            )

        [owner] = captured_owners
        assert candidate.has_prepared_owner_generation
        assert candidate._require_prepared_owner_generation() is owner
        assert candidate.ownership_state == "root_owned"
        owner._shadow._disposed = True
        owner._ownership = "disposed"
        candidate._StagedResourceCompositionCandidate__candidate.ownership = (
            "disposed"
        )
        await candidate.dispose_root_owned()
        assert disposal_attempts == 2
        assert candidate.ownership_state == "disposed"

    asyncio.run(scenario())


def test_attachment_cleanup_survives_repeated_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        profile = RuntimeProfileResolver().resolve(
            standard_capability_composition_plan(product_id="coding")
        )
        candidate = stage_resource_composition_candidate(profile)
        cleanup_started = asyncio.Event()
        allow_cleanup = asyncio.Event()
        original_dispose = PreparedResourceOwnerGeneration.dispose_root_owned

        def reject_attachment(self, receipt):  # type: ignore[no-untyped-def]
            del self, receipt
            raise RuntimeError("injected attachment rejection")

        async def delayed_disposal(self):  # type: ignore[no-untyped-def]
            cleanup_started.set()
            await allow_cleanup.wait()
            await original_dispose(self)

        monkeypatch.setattr(
            PreparedResourceOwnerGeneration,
            "_accept_candidate_attachment",
            reject_attachment,
        )
        monkeypatch.setattr(
            PreparedResourceOwnerGeneration,
            "dispose_root_owned",
            delayed_disposal,
        )
        task = asyncio.create_task(
            prepare_first_party_resource_owner_generation(
                staged_candidate=candidate,
                product_id="coding",
                scope_id="workspace:cleanup-cancellation",
                runtime_id="resource-owner:cleanup-cancellation",
                product_policy_revision="managed-action-test-v1",
                root_handles=(),
                issued_at=10,
                expires_at=100,
                now=20,
                projection_cwd=tmp_path,
            )
        )
        await cleanup_started.wait()
        task.cancel("first cleanup cancellation")
        await asyncio.sleep(0)
        task.cancel("second cleanup cancellation")
        allow_cleanup.set()

        with pytest.raises(asyncio.CancelledError):
            await task
        assert not candidate.has_prepared_owner_generation
        assert candidate.ownership_state == "root_owned"
        candidate.dispose()

    asyncio.run(scenario())


def test_authority_first_cold_import_mounts_exact_resource_owner() -> None:
    script = """
import asyncio
import loushang.harness.resources._skill_action_authority
from hashlib import sha256
from pathlib import Path
from loushang.harness.capabilities import (
    CapabilityGraphPlanRequest,
    RuntimeCapabilityGraphBinder,
    RuntimeCapabilityGraphPlanner,
    RuntimeCapabilityGraphRuntime,
    stage_resource_composition_candidate,
    standard_capability_composition_plan,
)
from loushang.harness.capabilities.resources_consumers import (
    ResourceSkillStatusCatalogCapabilityConsumer,
)
from loushang.harness.capabilities.resources_contracts import (
    RESOURCES_CAPABILITY_DEFINITION_V4,
    RESOURCES_SKILL_STATUS_CATALOG_LOAD_REQUIREMENT,
)
from loushang.harness.capabilities.resources_provider import (
    resources_capability_provider_binding,
)
from loushang.harness.resource_catalog.generation import (
    prepare_first_party_resource_owner_generation,
)
from loushang.harness.runtime import RuntimeProfileResolver

async def main():
    profile = RuntimeProfileResolver().resolve(
        standard_capability_composition_plan(product_id="coding")
    )
    candidate = stage_resource_composition_candidate(profile)
    await prepare_first_party_resource_owner_generation(
        staged_candidate=candidate,
        product_id="coding",
        scope_id="workspace:cold-import",
        runtime_id="resource-owner:cold-import",
        product_policy_revision="cold-import-v1",
        root_handles=(),
        issued_at=10,
        expires_at=100,
        now=20,
        projection_cwd=Path.cwd(),
    )
    binding = resources_capability_provider_binding(
        profile=profile,
        scope_instance_id="session:cold-import",
        staged_candidate=candidate,
        enable_skill_catalog_v4=True,
    )
    plan = RuntimeCapabilityGraphPlanner().plan(
        CapabilityGraphPlanRequest(
            product_id="coding",
            roots=(RESOURCES_CAPABILITY_DEFINITION_V4.capability_id,),
            definitions=(RESOURCES_CAPABILITY_DEFINITION_V4,),
            providers=(binding.provider,),
        )
    )
    runtime = RuntimeCapabilityGraphRuntime(
        product_id="coding",
        runtime_id="coding-session:cold-import",
        profile_fingerprint=sha256(b"cold-import-profile").hexdigest(),
    )
    binder = RuntimeCapabilityGraphBinder()
    await binder.bind(runtime, plan, (binding,))
    catalog = ResourceSkillStatusCatalogCapabilityConsumer(
        runtime.capture(RESOURCES_SKILL_STATUS_CATALOG_LOAD_REQUIREMENT)
    )
    assert not catalog.skill_consumer.list_effective_skills()
    assert await binder.dispose(runtime) == ()

asyncio.run(main())
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path.cwd(),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_catalog_action_owner_capability_rejects_unregistered_binding() -> None:
    forged = object.__new__(action_authority._CatalogActionOwnerBinding)
    with pytest.raises(TypeError, match="not live owner evidence"):
        action_authority._consume_catalog_action_owner_binding(
            forged,
            projection=object(),
        )


def test_catalog_action_owner_capability_rejects_complete_lookalike(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        action, genuine, binder, runtime = await _mounted_catalog_action(
            b"print('owner')\n",
            root=tmp_path,
        )
        owner_generation = genuine._catalog._generation

        class CallerCapture:
            snapshot = genuine._catalog_snapshot
            skill_projection = genuine._skill_projection

            def load_handle(self, identity):  # type: ignore[no-untyped-def]
                return genuine._catalog.load_handle(identity)

            async def load(self, handle):  # type: ignore[no-untyped-def]
                return await genuine._catalog.load(handle)

        with pytest.raises(TypeError, match="owner-constructed Skill consumer"):
            SkillCatalogConsumer(CallerCapture())

        fake_owner = object.__new__(type(owner_generation))
        object.__setattr__(
            fake_owner,
            "_skill_action_owner_lifecycle",
            owner_generation._skill_action_owner_lifecycle,
        )
        object.__setattr__(
            fake_owner,
            "_owner_generation_factory_identity",
            owner_generation._owner_generation_factory_identity,
        )
        assert not owner_authority._is_owner_generation_factory_recorded(fake_owner)
        with pytest.raises(TypeError, match="not authority-recorded"):
            action_authority._prepare_catalog_action_owner_binding(
                fake_owner._skill_action_owner_lifecycle,
                owner=fake_owner,
                projection=genuine._skill_projection,
            )
        with pytest.raises(AttributeError):
            object.__setattr__(fake_owner, "_skill_action_owner_registrations", {})

        assert ManagedSkillActionBinding.bind(action).read_verified_script() == (
            b"print('owner')\n"
        )
        assert await binder.dispose(runtime) == ()
        with pytest.raises(RuntimeError, match="not graph-owned"):
            owner_generation._construct_skill_catalog_consumer(include_status=False)
        with pytest.raises(RuntimeError, match="not graph-owned"):
            action_authority._prepare_catalog_action_owner_binding(
                owner_generation._skill_action_owner_lifecycle,
                owner=owner_generation,
                projection=genuine._skill_projection,
            )

    asyncio.run(scenario())


def test_graph_owner_rejects_shadow_retarget_and_retires_original_shadow(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        action, genuine, binder, runtime = await _mounted_catalog_action(
            b"print('owner')\n",
            root=tmp_path,
        )
        owner = genuine._catalog._generation
        original_shadow = owner._shadow
        replacement_shadow = await run_first_party_resource_catalog_shadow(
            product_id="coding",
            scope_id="workspace:replacement-shadow",
            runtime_id="resource-owner:replacement-shadow",
            product_policy_revision="managed-action-test-v1",
            catalog_generation=2,
            root_handles=(),
            issued_at=10,
            expires_at=100,
            now=20,
            projection_cwd=tmp_path,
        )
        owner._shadow = replacement_shadow

        assert owner_authority._is_owner_generation_factory_recorded(owner)
        assert not resource_owner_authority._is_resource_owner_factory_recorded(owner)
        with pytest.raises(TypeError, match="unchanged factory-recorded generation"):
            owner._construct_skill_catalog_consumer(include_status=False)
        assert ManagedSkillActionBinding.bind(action).read_verified_script() == (
            b"print('owner')\n"
        )
        assert await binder.dispose(runtime) == ()
        assert original_shadow.is_disposed
        assert not replacement_shadow.is_disposed
        assert await replacement_shadow.dispose() == ()

    asyncio.run(scenario())


def test_shadow_drift_blocks_graph_commit_but_not_ownership_rollback(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        profile = RuntimeProfileResolver().resolve(
            standard_capability_composition_plan(product_id="coding")
        )
        candidate = stage_resource_composition_candidate(profile)
        await prepare_first_party_resource_owner_generation(
            staged_candidate=candidate,
            product_id="coding",
            scope_id="workspace:graph-drift",
            runtime_id="resource-owner:graph-drift",
            product_policy_revision="managed-action-test-v1",
            root_handles=(),
            issued_at=10,
            expires_at=100,
            now=20,
            projection_cwd=tmp_path,
        )
        owner = candidate._require_prepared_owner_generation()
        original_shadow = owner._shadow
        replacement_shadow = await run_first_party_resource_catalog_shadow(
            product_id="coding",
            scope_id="workspace:graph-drift-replacement",
            runtime_id="resource-owner:graph-drift-replacement",
            product_policy_revision="managed-action-test-v1",
            catalog_generation=2,
            root_handles=(),
            issued_at=10,
            expires_at=100,
            now=20,
            projection_cwd=tmp_path,
        )
        candidate._begin_graph_construction()
        owner._shadow = replacement_shadow

        with pytest.raises(TypeError, match="unchanged factory-recorded generation"):
            candidate._commit_graph_ownership()
        candidate._restore_root_ownership()

        assert candidate.ownership_state == "root_owned"
        assert owner.ownership_state == "root_owned"
        await candidate.dispose_root_owned()
        assert original_shadow.is_disposed
        assert await replacement_shadow.dispose() == ()

    asyncio.run(scenario())


def test_shadow_internal_drift_blocks_authority_but_cleanup_uses_originals(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        profile = RuntimeProfileResolver().resolve(
            standard_capability_composition_plan(product_id="coding")
        )
        candidate = stage_resource_composition_candidate(profile)
        await prepare_first_party_resource_owner_generation(
            staged_candidate=candidate,
            product_id="coding",
            scope_id="workspace:shadow-internal-drift",
            runtime_id="resource-owner:shadow-internal-drift",
            product_policy_revision="managed-action-test-v1",
            root_handles=(),
            issued_at=10,
            expires_at=100,
            now=20,
            projection_cwd=tmp_path,
        )
        owner = candidate._require_prepared_owner_generation()
        original_shadow = owner._shadow
        original_runtime = original_shadow._runtime
        original_binder = original_shadow._binder
        replacement_shadow = await run_first_party_resource_catalog_shadow(
            product_id="coding",
            scope_id="workspace:shadow-internal-drift-replacement",
            runtime_id="resource-owner:shadow-internal-drift-replacement",
            product_policy_revision="managed-action-test-v1",
            catalog_generation=2,
            root_handles=(),
            issued_at=10,
            expires_at=100,
            now=20,
            projection_cwd=tmp_path,
        )

        original_shadow.resolution = replacement_shadow.resolution
        original_shadow.source_snapshots = replacement_shadow.source_snapshots
        original_shadow._runtime = replacement_shadow._runtime
        original_shadow._binder = replacement_shadow._binder
        original_shadow._extension_source_lease = object()  # type: ignore[assignment]
        original_shadow._disposed = True
        original_shadow._retiring = True
        original_shadow._active_loads = 99
        original_shadow._loads_drained.set()
        owner._ownership = "disposed"
        owner._retirement_owner = "graph"
        candidate_state = candidate._StagedResourceCompositionCandidate__candidate
        candidate_state.ownership = "disposed"

        assert not resource_owner_authority._is_resource_owner_factory_recorded(owner)
        with pytest.raises(
            (TypeError, RuntimeError),
            match="factory-recorded generation|requires a live generation",
        ):
            owner.retirement_receipt(contribution_ids=("drift",))

        await candidate.dispose_root_owned()

        assert original_shadow._runtime is original_runtime
        assert original_shadow._binder is original_binder
        assert original_shadow.is_disposed
        assert original_runtime.is_closed
        assert not replacement_shadow.is_disposed
        assert await replacement_shadow.dispose() == ()

    asyncio.run(scenario())


def test_owner_cleanup_retires_recorded_action_lifecycle_after_facade_drift(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        _action, consumer, binder, runtime = await _mounted_catalog_action(
            b"print('cleanup authority')\n",
            root=tmp_path,
        )
        owner = consumer._catalog._generation
        lifecycle = owner._skill_action_owner_lifecycle
        assert lifecycle is not None
        owner._skill_action_owner_lifecycle = None

        assert await binder.dispose(runtime) == ()

        record = action_authority._OWNER_GENERATIONS[id(lifecycle)]
        assert record.owner_ref() is owner
        assert record.state == "retired"

    asyncio.run(scenario())


def test_catalog_action_owner_rejects_construction_while_retiring(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        _action, consumer, binder, runtime = await _mounted_catalog_action(
            b"print('retiring')\n",
            root=tmp_path,
        )
        owner = consumer._catalog._generation
        shadow_type = type(owner._shadow)
        original_dispose = shadow_type.dispose
        entered = asyncio.Event()
        release = asyncio.Event()

        async def blocking_dispose(shadow):  # type: ignore[no-untyped-def]
            entered.set()
            await release.wait()
            return await original_dispose(shadow)

        monkeypatch.setattr(shadow_type, "dispose", blocking_dispose)
        disposal = asyncio.create_task(binder.dispose(runtime))
        await entered.wait()
        try:
            assert owner.ownership_state == "retiring"
            with pytest.raises(RuntimeError, match="not graph-owned"):
                owner._construct_skill_catalog_consumer(include_status=False)
            with pytest.raises(RuntimeError, match="not graph-owned"):
                action_authority._prepare_catalog_action_owner_binding(
                    owner._skill_action_owner_lifecycle,
                    owner=owner,
                    projection=consumer._skill_projection,
                )
        finally:
            release.set()
        assert await disposal == ()

    asyncio.run(scenario())


def test_catalog_action_owner_seal_rejects_object_new_clone(tmp_path: Path) -> None:
    async def scenario() -> None:
        action = await _catalog_action(b"print('sealed')\n", root=tmp_path)
        clone = object.__new__(CatalogManagedSkillAction)
        for name in (
            "selection",
            "declaration",
            "action_document_digest",
            "skill_root",
            "binding_source_fingerprint",
            "_script_body",
            "_source_capture_fingerprint",
            "_owner_identity",
            "_owner_seal",
            "_skill_root_identity",
        ):
            object.__setattr__(clone, name, getattr(action, name))

        with pytest.raises(ValueError, match="owner evidence"):
            ManagedSkillActionBinding.bind(clone)

    asyncio.run(scenario())


def test_catalog_action_uses_frozen_owner_snapshot_after_projection_mutation(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        action, consumer, binder, runtime = await _mounted_catalog_action(
            b"print('owner')\n",
            root=tmp_path,
        )
        try:
            consumer._managed_action_sources.clear()

            binding = ManagedSkillActionBinding.bind(action)
            assert binding.read_verified_script() == b"print('owner')\n"
        finally:
            assert await binder.dispose(runtime) == ()

    asyncio.run(scenario())


def test_catalog_action_rejects_nested_owner_fact_drift(tmp_path: Path) -> None:
    async def scenario() -> None:
        action, consumer, binder, runtime = await _mounted_catalog_action(
            b"print('owner')\n",
            root=tmp_path,
        )
        try:
            [summary] = consumer.list_effective_skills()
            source = consumer._managed_action_sources[summary.candidate_fingerprint]
            [captured] = source.capture.actions
            changed_body = b"print('changed')\n"
            object.__setattr__(captured, "script_body", changed_body)
            object.__setattr__(
                captured.declaration,
                "script_digest",
                sha256(changed_body).hexdigest(),
            )

            owner = consumer._catalog._generation
            with pytest.raises(TypeError, match="unchanged factory-recorded"):
                owner._construct_skill_catalog_consumer(include_status=False)
            with pytest.raises(ValueError, match="does not match its Resource owner"):
                consumer.capture_managed_actions(summary)
            binding = ManagedSkillActionBinding.bind(action)
            assert binding.read_verified_script() == b"print('owner')\n"
        finally:
            assert await binder.dispose(runtime) == ()

    asyncio.run(scenario())


def test_catalog_action_rejects_fresh_self_signed_object_graph(tmp_path: Path) -> None:
    async def scenario() -> None:
        genuine = await _catalog_action(b"print('registered')\n", root=tmp_path)
        owner_identity = object()
        selection = object.__new__(SkillActionCatalogSelection)
        for name in (
            "catalog_generation",
            "catalog_snapshot_fingerprint",
            "candidate_fingerprint",
            "skill_content_digest",
            "source_kind",
            "source_revision",
        ):
            object.__setattr__(selection, name, getattr(genuine.selection, name))
        object.__setattr__(selection, "_owner_identity", owner_identity)
        fingerprint = _catalog_action_binding_fingerprint(
            selection=selection,
            declaration=genuine.declaration,
            action_document_digest=genuine.action_document_digest,
        )
        forged = object.__new__(CatalogManagedSkillAction)
        for name, value in (
            ("selection", selection),
            ("declaration", genuine.declaration),
            ("action_document_digest", genuine.action_document_digest),
            ("skill_root", genuine.skill_root),
            ("binding_source_fingerprint", fingerprint),
            ("_script_body", genuine.read_script()),
            (
                "_source_capture_fingerprint",
                genuine._source_capture_fingerprint,
            ),
            ("_owner_identity", owner_identity),
            ("_skill_root_identity", genuine._skill_root_identity),
        ):
            object.__setattr__(forged, name, value)
        seal = object.__new__(_CatalogActionOwnerSeal)
        for name, value in (
            ("_action", forged),
            ("_owner_identity", owner_identity),
            ("_binding_source_fingerprint", fingerprint),
            ("_script_digest", genuine.declaration.script_digest),
            ("_skill_root", genuine.skill_root),
            ("_skill_root_identity", genuine._skill_root_identity),
        ):
            object.__setattr__(seal, name, value)
        object.__setattr__(forged, "_owner_seal", seal)

        with pytest.raises(ValueError, match="live Resource-owner evidence"):
            ManagedSkillActionBinding.bind(forged)

    asyncio.run(scenario())


def test_catalog_action_rejects_replaced_skill_root(tmp_path: Path) -> None:
    async def scenario() -> None:
        action = await _catalog_action(b"print('root')\n", root=tmp_path)
        binding = ManagedSkillActionBinding.bind(action)
        original = action.skill_root.with_name("review-original")
        action.skill_root.rename(original)
        action.skill_root.mkdir()

        with pytest.raises(ValueError, match="root identity changed"):
            binding.read_verified_script()

    asyncio.run(scenario())


def test_catalog_action_uses_exact_approval_and_captured_script(tmp_path: Path) -> None:
    async def scenario() -> None:
        script = b"print('captured')\n"
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        binding = ManagedSkillActionBinding.bind(
            await _catalog_action(script, root=tmp_path)
        )
        resolver = _ApprovalResolver()
        sandbox_runtime, launcher = _launcher(
            resolver=resolver,
            root=tmp_path,
        )
        try:
            result = await execute_managed_skill_action(
                binding,
                runtime=SkillRuntimeBinding.capture(
                    runtime="python",
                    executable=sys.executable,
                ),
                launcher=launcher,
                workspace_root=workspace_root,
                correlation_id="skill-action-1",
            )
            assert result.return_code == 0
            assert result.stdout == b"captured\n"
            [approval] = resolver.requests
            assert approval.policy_code == "managed_process_requires_approval"
            metadata = approval.arguments["metadata"]
            assert metadata["actionBindingFingerprint"] == binding.binding_fingerprint
            assert metadata["actionDocumentDigest"] == binding.action_document_digest
            assert metadata["candidateFingerprint"] == binding.candidate_fingerprint
            assert approval.arguments["command"][1:] == ("-", "--check")
        finally:
            await sandbox_runtime.close()

    asyncio.run(scenario())


def test_package_catalog_action_executes_through_same_sandbox_process_path(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        workspace_root = tmp_path / "package-workspace"
        workspace_root.mkdir()
        action = await _catalog_package_action(
            b"print('package-captured')\n",
            root=tmp_path,
        )
        binding = ManagedSkillActionBinding.bind(action)
        sandbox_runtime, launcher = _launcher(
            resolver=_ApprovalResolver(),
            root=tmp_path,
        )
        try:
            result = await execute_managed_skill_action(
                binding,
                runtime=SkillRuntimeBinding.capture(
                    runtime="python",
                    executable=sys.executable,
                ),
                launcher=launcher,
                workspace_root=workspace_root,
                correlation_id="package-skill-action",
            )
            assert result.return_code == 0
            assert result.stdout == b"package-captured\n"
            assert binding.source_kind == "package"
        finally:
            await sandbox_runtime.close()

    asyncio.run(scenario())


def test_v4_owner_built_consumer_captures_native_and_package_actions(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        native = await _catalog_action(
            b"print('native-v4')\n",
            root=tmp_path,
            skill_catalog_version=4,
        )
        package_action = await _catalog_package_action(
            b"print('package-v4')\n",
            root=tmp_path,
            skill_catalog_version=4,
        )

        native_binding = ManagedSkillActionBinding.bind(native)
        package_binding = ManagedSkillActionBinding.bind(package_action)
        assert native_binding.read_verified_script() == b"print('native-v4')\n"
        assert native_binding.source_kind == "native"
        assert package_binding.read_verified_script() == b"print('package-v4')\n"
        assert package_binding.source_kind == "package"

    asyncio.run(scenario())


def test_managed_action_rejects_fake_launcher_and_weak_containment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "bwrap"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    original_init = LinuxBubblewrapBackend.__init__

    def available_init(self, *args, **kwargs):
        assert not args

        def probe(argv, timeout_seconds):
            del timeout_seconds
            stdout = "--ro-bind-data FD DEST --ro-bind-fd FD DEST"
            return subprocess.CompletedProcess(argv, 0, stdout, "")

        original_init(
            self,
            bwrap_path=executable,
            probe_runner=probe,
            local_backend=kwargs.get("local_backend"),
        )

    monkeypatch.setattr(LinuxBubblewrapBackend, "__init__", available_init)

    async def weak_scenario() -> None:
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        binding = ManagedSkillActionBinding.bind(
            await _catalog_action(b"print('ok')\n", root=tmp_path)
        )
        runtime = SkillRuntimeBinding.capture(
            runtime="python",
            executable=sys.executable,
        )
        with pytest.raises(TypeError, match="Process owner launcher"):
            await execute_managed_skill_action(
                binding,
                runtime=runtime,
                launcher=object(),  # type: ignore[arg-type]
                workspace_root=workspace_root,
                correlation_id="fake-launcher",
            )
        host = ProcessHost()
        try:
            unowned = ScopeBoundProcessLauncher(
                scope=ProcessExecutionScope(
                    approval_resolver=_ApprovalResolver(),
                    require_approval=True,
                ),
                host=host,
                containment=_Containment(),
            )
            with pytest.raises(
                ExecutionAuthorizationError,
                match="Process-owner-minted launcher",
            ):
                await execute_managed_skill_action(
                    binding,
                    runtime=runtime,
                    launcher=unowned,
                    workspace_root=workspace_root,
                    correlation_id="unowned-launcher",
                )
            structurally_bound = _bind_process_owner_launcher(
                scope=ProcessExecutionScope(
                    approval_resolver=_ApprovalResolver(),
                    require_approval=True,
                ),
                host=host,
                containment=_Containment(),
            )
            assert structurally_bound._managed_owner_authority is None
        finally:
            await host.close()

        backend = _HostedSandboxBackend()
        registration = SandboxBackendRegistration(
            backend_id=backend.backend_id,
            os_families=frozenset({"linux"}),
            factory=lambda: backend,
        )
        profile = EffectiveExecutionProfile(
            readable_roots=(tmp_path,),
            writable_roots=(tmp_path,),
        )
        for label, registry in (
            ("public", SandboxBackendRegistry((registration,))),
            (
                "injected-builtin",
                default_sandbox_backend_registry(
                    local_backend=ExecService(execution_profile=profile),
                ),
            ),
        ):
            custom_runtime = bind_sandbox_execution_runtime(
                base_exec_service=ExecService(execution_profile=profile),
                settings=SandboxSettings(enabled=True, requirement="required"),
                registry=registry,
                environment_probe=LocalHostEnvironmentProbe(
                    platform_name="linux",
                    architecture="x86_64",
                    environ={},
                ),
                scope_request_factory=lambda request: _sandbox_scope(tmp_path, request),
                execution_profile=profile,
            )
            custom_launcher = custom_runtime.bind_process_launcher(
                ProcessExecutionScope(
                    approval_resolver=_ApprovalResolver(),
                    execution_profile_ceiling=profile,
                    require_approval=True,
                )
            )
            try:
                assert custom_launcher._managed_owner_authority is None
                with pytest.raises(
                    ExecutionAuthorizationError,
                    match="Process-owner-minted launcher",
                ):
                    await execute_managed_skill_action(
                        binding,
                        runtime=runtime,
                        launcher=custom_launcher,
                        workspace_root=workspace_root,
                        correlation_id=f"untrusted-custom-backend:{label}",
                    )
            finally:
                await custom_runtime.close()

    asyncio.run(weak_scenario())


def test_managed_action_rejects_post_resolution_backend_shadow(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        workspace_root = tmp_path / "workspace-shadow"
        workspace_root.mkdir()
        action = await _catalog_action(b"print('never')\n", root=tmp_path)
        sandbox_runtime, launcher = _launcher(
            resolver=_ApprovalResolver(),
            root=tmp_path,
        )
        resolution = sandbox_runtime.binding.resolution
        assert resolution is not None
        backend = resolution.backend
        assert backend is not None

        called = False

        async def no_op_plan(request, scope):
            nonlocal called
            called = True
            return ProcessContainmentPlan(request)

        backend._plan_hosted_process = no_op_plan  # type: ignore[attr-defined]
        try:
            with pytest.raises(
                SandboxUnavailableError,
                match="resolution authority changed",
            ):
                await execute_managed_skill_action(
                    ManagedSkillActionBinding.bind(action),
                    runtime=SkillRuntimeBinding.capture(
                        runtime="python",
                        executable=sys.executable,
                    ),
                    launcher=launcher,
                    workspace_root=workspace_root,
                    correlation_id="shadowed-backend",
                )
            assert called is False
            assert not sandbox_runtime._process_host._reservations
            assert not sandbox_runtime._process_host._registrations
        finally:
            await sandbox_runtime.close()

    asyncio.run(scenario())


def test_managed_action_requires_managed_bubblewrap_features_before_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "bwrap-without-fd-bind"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)
    original_init = LinuxBubblewrapBackend.__init__

    def feature_limited_init(self, *args, **kwargs):
        assert not args

        def probe(argv, timeout_seconds):
            del timeout_seconds
            stdout = "--ro-bind-data FD DEST" if argv[-1] == "--help" else ""
            return subprocess.CompletedProcess(argv, 0, stdout, "")

        original_init(
            self,
            bwrap_path=executable,
            probe_runner=probe,
            local_backend=kwargs.get("local_backend"),
        )

    monkeypatch.setattr(LinuxBubblewrapBackend, "__init__", feature_limited_init)

    async def scenario() -> None:
        workspace_root = tmp_path / "workspace-feature-limited"
        workspace_root.mkdir()
        binding = ManagedSkillActionBinding.bind(
            await _catalog_action(b"print('never')\n", root=tmp_path)
        )
        resolver = _ApprovalResolver()
        sandbox_runtime, launcher = _launcher(resolver=resolver, root=tmp_path)
        try:
            assert sandbox_runtime.status().state == "enabled"
            with pytest.raises(
                ExecutionAuthorizationError,
                match="Process-owner-minted launcher",
            ):
                await execute_managed_skill_action(
                    binding,
                    runtime=SkillRuntimeBinding.capture(
                        runtime="python",
                        executable=sys.executable,
                    ),
                    launcher=launcher,
                    workspace_root=workspace_root,
                    correlation_id="missing-managed-bwrap-features",
                )
            assert resolver.requests == []
            assert not sandbox_runtime._process_host._reservations
            assert not sandbox_runtime._process_host._registrations
        finally:
            await sandbox_runtime.close()

    asyncio.run(scenario())


def test_runtime_binding_capture_and_verify_are_streaming(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_read_bytes(path: Path) -> bytes:
        raise AssertionError(f"must not buffer complete runtime: {path}")

    monkeypatch.setattr(Path, "read_bytes", unexpected_read_bytes)

    runtime = SkillRuntimeBinding.capture(
        runtime="python",
        executable=sys.executable,
    )
    runtime.verify()


def test_runtime_binding_rejects_sparse_oversize_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "oversize-runtime"
    executable.touch()
    with executable.open("r+b") as stream:
        stream.truncate(sealed_executable_runtime._MAX_EXECUTABLE_BYTES + 1)

    def unexpected_read(descriptor: int, size: int) -> bytes:
        raise AssertionError(f"must reject fd {descriptor} before reading {size} bytes")

    monkeypatch.setattr(sealed_executable_runtime.os, "read", unexpected_read)

    with pytest.raises(ValueError, match="bounded stable regular file"):
        SkillRuntimeBinding.capture(runtime="python", executable=executable)


def test_runtime_binding_verify_rejects_sparse_oversize_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable = tmp_path / "replaced-runtime"
    executable.write_bytes(b"#!/bin/sh\n")
    runtime = SkillRuntimeBinding.capture(runtime="posix", executable=executable)
    with executable.open("r+b") as stream:
        stream.truncate(sealed_executable_runtime._MAX_EXECUTABLE_BYTES + 1)

    def unexpected_read(descriptor: int, size: int) -> bytes:
        raise AssertionError(f"must reject fd {descriptor} before reading {size} bytes")

    monkeypatch.setattr(sealed_executable_runtime.os, "read", unexpected_read)

    with pytest.raises(ManagedSkillActionError) as caught:
        runtime.verify()
    assert caught.value.code == "skill_action_runtime_changed"


def test_managed_action_fails_closed_when_runtime_cannot_be_sealed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        workspace_root = tmp_path / "unsealable-workspace"
        workspace_root.mkdir()
        binding = ManagedSkillActionBinding.bind(
            await _catalog_action(b"print('never')\n", root=tmp_path)
        )
        resolver = _ApprovalResolver()
        host = ProcessHost()
        launcher = ScopeBoundProcessLauncher(
            scope=ProcessExecutionScope(
                approval_resolver=resolver,
                require_approval=True,
            ),
            host=host,
            containment=_Containment(),
        )
        launcher._managed_owner_authority = object()
        launcher._managed_plan_verifier = lambda plan, authority: None

        def unavailable(*args, **kwargs):
            del args, kwargs
            raise SealedProcessExecutableUnavailable("unsupported host")

        monkeypatch.setattr(
            skill_action_runtime,
            "_capture_sealed_process_executable",
            unavailable,
        )
        try:
            with pytest.raises(ManagedSkillActionError) as caught:
                await execute_managed_skill_action(
                    binding,
                    runtime=SkillRuntimeBinding.capture(
                        runtime="python",
                        executable=sys.executable,
                    ),
                    launcher=launcher,
                    workspace_root=workspace_root,
                    correlation_id="unsealable-runtime",
                )
            assert caught.value.code == "skill_action_runtime_unsealable"
            assert resolver.requests == []
            assert not host._reservations
            assert not host._registrations
        finally:
            await host.close()

    asyncio.run(scenario())


def test_runtime_executes_sealed_bytes_when_source_changes_after_approval(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    executable = tmp_path / "python-copy"
    executable.write_bytes(Path(sys.executable).read_bytes())
    runtime = SkillRuntimeBinding.capture(
        runtime="python",
        executable=executable,
        environment=(("PYTHONHOME", sys.base_prefix),),
    )
    resolver = _ApprovalResolver(on_resolve=lambda: executable.write_bytes(b"changed"))

    async def scenario() -> None:
        binding = ManagedSkillActionBinding.bind(
            await _catalog_action(b"print('ok')\n", root=tmp_path)
        )
        sandbox_runtime, launcher = _launcher(
            resolver=resolver,
            root=tmp_path,
        )
        try:
            result = await execute_managed_skill_action(
                binding,
                runtime=runtime,
                launcher=launcher,
                workspace_root=workspace_root,
                correlation_id="runtime-race",
            )
            assert result.return_code == 0
            assert result.stdout == b"ok\n"
            assert executable.read_bytes() == b"changed"
            assert len(resolver.requests) == 1
        finally:
            await sandbox_runtime.close()

    asyncio.run(scenario())


def test_skill_root_replacement_during_approval_fails_before_spawn(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        workspace_root = tmp_path / "workspace-root-race"
        workspace_root.mkdir()
        action = await _catalog_action(b"print('never')\n", root=tmp_path)
        original_root = action.skill_root.with_name("review-approved")

        def replace_root() -> None:
            action.skill_root.rename(original_root)
            action.skill_root.mkdir()

        resolver = _ApprovalResolver(on_resolve=replace_root)
        sandbox_runtime, launcher = _launcher(resolver=resolver, root=tmp_path)
        try:
            with pytest.raises(ValueError, match="root identity changed"):
                await execute_managed_skill_action(
                    ManagedSkillActionBinding.bind(action),
                    runtime=SkillRuntimeBinding.capture(
                        runtime="python",
                        executable=sys.executable,
                    ),
                    launcher=launcher,
                    workspace_root=workspace_root,
                    correlation_id="skill-root-race",
                )
            assert len(resolver.requests) == 1
            assert not sandbox_runtime._process_host._reservations
            assert not sandbox_runtime._process_host._registrations
        finally:
            await sandbox_runtime.close()

    asyncio.run(scenario())


def test_real_process_host_drains_both_streams_and_preserves_nonzero_exit(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        script = (
            b"import sys\n"
            b"sys.stdout.buffer.write(b'o' * 70000)\n"
            b"sys.stdout.flush()\n"
            b"sys.stderr.buffer.write(b'e' * 90000)\n"
            b"sys.stderr.flush()\n"
            b"raise SystemExit(7)\n"
        )
        action = await _catalog_action(
            script,
            root=tmp_path,
            declaration=_declaration(script, argv=()),
        )
        sandbox_runtime, launcher = _launcher(
            resolver=_ApprovalResolver(),
            root=tmp_path,
        )
        try:
            result = await execute_managed_skill_action(
                ManagedSkillActionBinding.bind(action),
                runtime=SkillRuntimeBinding.capture(
                    runtime="python",
                    executable=sys.executable,
                ),
                launcher=launcher,
                workspace_root=workspace_root,
                correlation_id="real-host",
            )
            assert result.return_code == 7
            assert result.stdout == b"o" * 70000
            assert result.stderr == b"e" * 90000
        finally:
            await sandbox_runtime.close()

    asyncio.run(scenario())


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX runtime requires sh")
def test_real_process_host_executes_posix_runtime_without_script_path(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        script = b"printf 'posix-out'; printf 'posix-err' >&2; exit 3\n"
        declaration = skill_action(
            id="review-posix",
            script="scripts/review.sh",
            script_digest=sha256(script).hexdigest(),
            runtime="posix",
        )
        action = await _catalog_action(
            script,
            root=tmp_path,
            declaration=declaration,
        )
        sandbox_runtime, launcher = _launcher(
            resolver=_ApprovalResolver(),
            root=tmp_path,
        )
        try:
            result = await execute_managed_skill_action(
                ManagedSkillActionBinding.bind(action),
                runtime=SkillRuntimeBinding.capture(
                    runtime="posix",
                    executable="/bin/sh",
                ),
                launcher=launcher,
                workspace_root=workspace_root,
                correlation_id="posix-host",
            )
            assert result.return_code == 3
            assert result.stdout == b"posix-out"
            assert result.stderr == b"posix-err"
        finally:
            await sandbox_runtime.close()

    asyncio.run(scenario())


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX runtime requires sh")
def test_posix_action_drains_output_while_large_stdin_is_still_writing(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        output_block = "x" * 64
        script = (
            'i=0; while [ "$i" -lt 2048 ]; do '
            f"printf '{output_block}'; i=$((i + 1)); done\n"
            + "#"
            + ("p" * 850_000)
            + "\nexit 0\n"
        ).encode()
        declaration = skill_action(
            id="review-posix-streaming",
            script="scripts/review.sh",
            script_digest=sha256(script).hexdigest(),
            runtime="posix",
        )
        action = await _catalog_action(
            script,
            root=tmp_path,
            declaration=declaration,
        )
        sandbox_runtime, launcher = _launcher(
            resolver=_ApprovalResolver(),
            root=tmp_path,
        )
        try:
            result = await asyncio.wait_for(
                execute_managed_skill_action(
                    ManagedSkillActionBinding.bind(action),
                    runtime=SkillRuntimeBinding.capture(
                        runtime="posix",
                        executable="/bin/sh",
                    ),
                    launcher=launcher,
                    workspace_root=workspace_root,
                    correlation_id="posix-bidirectional-pipes",
                ),
                timeout=10,
            )
            assert result.return_code == 0
            assert result.stdout == output_block.encode() * 2048
            assert result.stderr == b""
        finally:
            await sandbox_runtime.close()

    asyncio.run(scenario())


def test_real_process_host_terminates_output_overflow_without_pipe_deadlock(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        script = (
            b"import sys\nsys.stdout.buffer.write(b'x' * 1100000)\nsys.stdout.flush()\n"
        )
        action = await _catalog_action(script, root=tmp_path)
        sandbox_runtime, launcher = _launcher(
            resolver=_ApprovalResolver(),
            root=tmp_path,
        )
        try:
            with pytest.raises(ManagedSkillActionError) as captured:
                await asyncio.wait_for(
                    execute_managed_skill_action(
                        ManagedSkillActionBinding.bind(action),
                        runtime=SkillRuntimeBinding.capture(
                            runtime="python",
                            executable=sys.executable,
                        ),
                        launcher=launcher,
                        workspace_root=workspace_root,
                        correlation_id="output-overflow",
                    ),
                    timeout=10,
                )
            assert captured.value.code == "skill_action_output_limit_exceeded"
        finally:
            await sandbox_runtime.close()

    asyncio.run(scenario())


def test_managed_action_cancellation_reclaims_process_and_pipe_tasks(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        workspace_root = tmp_path / "workspace"
        workspace_root.mkdir()
        script = (
            b"import sys, time\n"
            b"sys.stdout.write('started\\n')\n"
            b"sys.stdout.flush()\n"
            b"time.sleep(60)\n"
        )
        action = await _catalog_action(script, root=tmp_path)
        sandbox_runtime, launcher = _launcher(
            resolver=_ApprovalResolver(),
            root=tmp_path,
        )
        task = asyncio.create_task(
            execute_managed_skill_action(
                ManagedSkillActionBinding.bind(action),
                runtime=SkillRuntimeBinding.capture(
                    runtime="python",
                    executable=sys.executable,
                ),
                launcher=launcher,
                workspace_root=workspace_root,
                correlation_id="managed-action-cancel",
            )
        )
        try:
            required_tasks = {
                "managed-skill-action-stdout",
                "managed-skill-action-stderr",
                "managed-skill-action-wait",
            }
            deadline = asyncio.get_running_loop().time() + 5
            while True:
                live_names = {
                    item.get_name() for item in asyncio.all_tasks() if not item.done()
                }
                if (
                    sandbox_runtime._process_host._registrations
                    and required_tasks.issubset(live_names)
                ):
                    break
                if task.done():
                    await task
                if asyncio.get_running_loop().time() >= deadline:
                    raise AssertionError(
                        "managed action did not reach live pipe ownership"
                    )
                await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)
            assert not sandbox_runtime._process_host._reservations
            assert not sandbox_runtime._process_host._registrations
            assert not {
                item.get_name()
                for item in asyncio.all_tasks()
                if item.get_name().startswith("managed-skill-action-")
            }
        finally:
            await sandbox_runtime.close()

    asyncio.run(scenario())
