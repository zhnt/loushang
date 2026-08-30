from __future__ import annotations

import asyncio
import sys
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

import loushang.harness.resources._skill_action_authority as action_authority
import loushang.harness.tools.skill_actions as skill_action_runtime
from loushang.harness.approval import ApprovalDecision
from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    ExecutionAuthorizationError,
)
from loushang.harness.capabilities.contribution_admission import (
    OwnerContributionAuthority,
    OwnerContributionPolicy,
    ResourceContributionSpec,
)
from loushang.harness.environment import HostEnvironment, LocalHostEnvironmentProbe
from loushang.harness.plugin_authoring.contribution_admission import (
    prepare_owner_contribution_candidate,
)
from loushang.harness.plugin_authoring.host import PluginDeclarationHost
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
    build_effective_skill_catalog_projection,
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
from loushang.harness.sandbox import (
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


async def _catalog_action(
    script: bytes,
    *,
    root: Path,
    declaration=None,
) -> CatalogManagedSkillAction:
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
    shadow = await run_first_party_resource_catalog_shadow(
        product_id="coding",
        scope_id="workspace:test",
        runtime_id=f"managed-action:{uuid4().hex}",
        product_policy_revision="managed-action-test-v1",
        root_handles=(root_handle,),
        issued_at=10,
        expires_at=100,
        now=20,
        projection_cwd=root,
    )
    assert shadow.catalog_projection is not None
    projection = build_effective_skill_catalog_projection(
        snapshot=shadow.catalog_snapshot,
        projection=shadow.catalog_projection,
    )

    class _ShadowCatalog:
        snapshot = shadow.catalog_snapshot
        skill_projection = projection

        def load_handle(self, identity):
            return shadow.load_handle(identity)

        async def load(self, handle):
            return await shadow.load(handle)

    consumer = SkillCatalogConsumer(_ShadowCatalog())
    [summary] = consumer.list_effective_skills()
    [action] = consumer.capture_managed_actions(summary)
    assert await shadow.dispose() == ()
    return action


async def _catalog_package_action(
    script: bytes,
    *,
    root: Path,
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
        shadow = await run_first_party_resource_catalog_shadow(
            product_id="coding",
            scope_id="workspace:test",
            runtime_id=f"managed-package-action:{uuid4().hex}",
            product_policy_revision="managed-action-test-v1",
            root_handles=(),
            package_resources=(resource_input,),
            issued_at=10,
            expires_at=100,
            now=20,
            projection_cwd=root,
        )
        assert shadow.catalog_projection is not None
        projection = build_effective_skill_catalog_projection(
            snapshot=shadow.catalog_snapshot,
            projection=shadow.catalog_projection,
        )

        class _ShadowCatalog:
            snapshot = shadow.catalog_snapshot
            skill_projection = projection

            def load_handle(self, identity):
                return shadow.load_handle(identity)

            async def load(self, handle):
                return await shadow.load(handle)

        consumer = SkillCatalogConsumer(_ShadowCatalog())
        [summary] = consumer.list_effective_skills()
        [action] = consumer.capture_managed_actions(summary)
        assert await shadow.dispose() == ()
        return action
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
    with pytest.raises(ValueError, match="owner capability"):
        _register_catalog_managed_skill_action(
            forged,
            owner_capability=object(),  # type: ignore[arg-type]
        )


def test_catalog_action_owner_capability_rejects_non_consumer_binding() -> None:
    with pytest.raises(TypeError, match="canonical Resource consumer"):
        action_authority._bind_catalog_action_owner(
            object(),
            owner_identity=object(),
        )


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
            "_owner_identity",
            "_owner_seal",
            "_skill_root_identity",
        ):
            object.__setattr__(clone, name, getattr(action, name))

        with pytest.raises(ValueError, match="owner evidence"):
            ManagedSkillActionBinding.bind(clone)

    asyncio.run(scenario())


def test_catalog_action_rejects_mutated_owner_projection(tmp_path: Path) -> None:
    async def scenario() -> None:
        action = await _catalog_action(b"print('owner')\n", root=tmp_path)
        registration = action_authority._REGISTRATIONS[id(action)]
        consumer = registration.consumer
        consumer._managed_action_sources.clear()

        with pytest.raises(ValueError, match="live Resource-owner evidence"):
            ManagedSkillActionBinding.bind(action)

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


def test_managed_action_rejects_fake_launcher_and_weak_containment(
    tmp_path: Path,
) -> None:
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
