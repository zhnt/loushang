from __future__ import annotations

import asyncio
import sys
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

import pytest

from loushang.harness.approval import ApprovalDecision
from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    ExecutionAuthorizationError,
)
from loushang.harness.environment import HostEnvironment, LocalHostEnvironmentProbe
from loushang.harness.resource_catalog.shadow import (
    run_first_party_resource_catalog_shadow,
)
from loushang.harness.resources._catalog_native_source import (
    mint_native_resource_root_handle,
)
from loushang.harness.resources._skill_catalog_consumer import (
    SkillCatalogConsumer,
    build_effective_skill_catalog_projection,
)
from loushang.harness.resources.skill_actions import (
    CatalogManagedSkillAction,
    SkillActionCatalogSelection,
    SkillActionDocument,
    SkillActionDocumentCodec,
)
from loushang.harness.sandbox import (
    SandboxBackendRegistration,
    SandboxBackendRegistry,
    SandboxBackendStatus,
    SandboxExecutionRuntime,
    SandboxScopeRequest,
    SandboxSettings,
    bind_sandbox_execution_runtime,
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
from loushang.harness.workspace.process.host import ProcessHost
from loushang.harness.workspace.process.local import ProcessContainmentPlan
from loushang.plugin import skill_action, skill_action_effect


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


def _launcher(
    *,
    resolver,
    root: Path,
) -> tuple[SandboxExecutionRuntime, ScopeBoundProcessLauncher]:
    backend = _HostedSandboxBackend()
    registry = SandboxBackendRegistry(
        (
            SandboxBackendRegistration(
                backend_id=backend.backend_id,
                os_families=frozenset({"linux"}),
                factory=lambda: backend,
            ),
        )
    )
    profile = EffectiveExecutionProfile(
        readable_roots=(root,),
        writable_roots=(root,),
    )
    runtime = bind_sandbox_execution_runtime(
        base_exec_service=ExecService(execution_profile=profile),
        settings=SandboxSettings(enabled=True, requirement="required"),
        registry=registry,
        environment_probe=LocalHostEnvironmentProbe(
            platform_name="linux",
            architecture="x86_64",
            environ={},
        ),
        scope_request_factory=lambda request: _sandbox_scope(root, request),
        execution_profile=profile,
    )
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
        readable_roots=(root,),
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
    with pytest.raises(TypeError, match="Resource-owner-minted"):
        SkillActionCatalogSelection()
    with pytest.raises(TypeError, match="Resource-owner-minted"):
        CatalogManagedSkillAction()
    with pytest.raises(TypeError, match="Catalog-owner evidence"):
        ManagedSkillActionBinding()
    forged = object.__new__(CatalogManagedSkillAction)
    with pytest.raises(ValueError, match="owner evidence"):
        forged.verify()


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
        ):
            object.__setattr__(clone, name, getattr(action, name))

        with pytest.raises(ValueError, match="owner evidence"):
            ManagedSkillActionBinding.bind(clone)

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
            with pytest.raises(
                TypeError,
                match="exact Sandbox containment planner",
            ):
                _bind_process_owner_launcher(
                    scope=ProcessExecutionScope(
                        approval_resolver=_ApprovalResolver(),
                        require_approval=True,
                    ),
                    host=host,
                    containment=_Containment(),
                )
            with pytest.raises(
                TypeError,
                match="exact Sandbox containment planner",
            ):
                _bind_process_owner_launcher(
                    scope=ProcessExecutionScope(
                        approval_resolver=_ApprovalResolver(),
                        require_approval=True,
                    ),
                    host=host,
                    containment=object(),  # type: ignore[arg-type]
                )
        finally:
            await host.close()

    asyncio.run(weak_scenario())


def test_runtime_is_revalidated_after_approval_and_before_spawn(
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    executable = tmp_path / "python-copy"
    executable.write_bytes(Path(sys.executable).read_bytes())
    runtime = SkillRuntimeBinding.capture(runtime="python", executable=executable)
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
            with pytest.raises(ManagedSkillActionError) as captured:
                await execute_managed_skill_action(
                    binding,
                    runtime=runtime,
                    launcher=launcher,
                    workspace_root=workspace_root,
                    correlation_id="runtime-race",
                )
            assert captured.value.code == "skill_action_runtime_changed"
            assert len(resolver.requests) == 1
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
            "i=0; while [ \"$i\" -lt 2048 ]; do "
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
            b"import sys\n"
            b"sys.stdout.buffer.write(b'x' * 1100000)\n"
            b"sys.stdout.flush()\n"
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
            await asyncio.sleep(0.2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=5)
            assert not sandbox_runtime._process_host._reservations
            assert not sandbox_runtime._process_host._registrations
        finally:
            await sandbox_runtime.close()

    asyncio.run(scenario())
