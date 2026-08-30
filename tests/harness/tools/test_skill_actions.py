from __future__ import annotations

import asyncio
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.approval import ApprovalDecision
from loushang.harness.authorization import ExecutionAuthorizationError
from loushang.harness.resources.skill_actions import (
    CatalogManagedSkillAction,
    SkillActionCatalogSelection,
    SkillActionDocument,
    SkillActionDocumentCodec,
    _mint_catalog_managed_skill_action,
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


class _WeakContainment(_Containment):
    requirement = "best_effort"


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


def _catalog_action(
    script: bytes,
    *,
    skill_root: Path,
    source_kind: str = "native",
) -> CatalogManagedSkillAction:
    declaration = _declaration(script)
    action_document = SkillActionDocumentCodec.encode_bytes(
        SkillActionDocument(actions=(declaration,))
    )
    return _mint_catalog_managed_skill_action(
        catalog_generation=7,
        catalog_snapshot_fingerprint="3" * 64,
        candidate_fingerprint="4" * 64,
        skill_content_digest="2" * 64,
        source_kind=source_kind,  # type: ignore[arg-type]
        source_revision="1" * 64,
        declaration=declaration,
        action_document_digest=sha256(action_document).hexdigest(),
        script_body=script,
        skill_root=skill_root,
    )


def _launcher(
    *,
    resolver,
    host: ProcessHost,
    containment=None,
) -> ScopeBoundProcessLauncher:
    return _bind_process_owner_launcher(
        scope=ProcessExecutionScope(
            approval_resolver=resolver,
            require_approval=True,
        ),
        host=host,
        containment=containment or _Containment(),
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


def test_catalog_action_uses_exact_approval_and_captured_script(tmp_path: Path) -> None:
    async def scenario() -> None:
        script = b"print('captured')\n"
        skill_root = tmp_path / "skill"
        workspace_root = tmp_path / "workspace"
        skill_root.mkdir()
        workspace_root.mkdir()
        binding = ManagedSkillActionBinding.bind(
            _catalog_action(script, skill_root=skill_root)
        )
        resolver = _ApprovalResolver()
        host = ProcessHost()
        try:
            result = await execute_managed_skill_action(
                binding,
                runtime=SkillRuntimeBinding.capture(
                    runtime="python",
                    executable=sys.executable,
                ),
                launcher=_launcher(resolver=resolver, host=host),
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
            assert metadata["candidateFingerprint"] == "4" * 64
            assert approval.arguments["command"][1:] == ("-", "--check")
        finally:
            await host.close()

    asyncio.run(scenario())


def test_managed_action_rejects_fake_launcher_and_weak_containment(
    tmp_path: Path,
) -> None:
    skill_root = tmp_path / "skill"
    workspace_root = tmp_path / "workspace"
    skill_root.mkdir()
    workspace_root.mkdir()
    binding = ManagedSkillActionBinding.bind(
        _catalog_action(b"print('ok')\n", skill_root=skill_root)
    )
    runtime = SkillRuntimeBinding.capture(runtime="python", executable=sys.executable)

    with pytest.raises(TypeError, match="Process owner launcher"):
        asyncio.run(
            execute_managed_skill_action(
                binding,
                runtime=runtime,
                launcher=object(),  # type: ignore[arg-type]
                workspace_root=workspace_root,
                correlation_id="fake-launcher",
            )
        )

    async def weak_scenario() -> None:
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
            launcher = _launcher(
                resolver=_ApprovalResolver(),
                host=host,
                containment=_WeakContainment(),
            )
            with pytest.raises(
                ExecutionAuthorizationError,
                match="required containment",
            ):
                await execute_managed_skill_action(
                    binding,
                    runtime=runtime,
                    launcher=launcher,
                    workspace_root=workspace_root,
                    correlation_id="weak-containment",
                )
        finally:
            await host.close()

    asyncio.run(weak_scenario())


def test_runtime_is_revalidated_after_approval_and_before_spawn(
    tmp_path: Path,
) -> None:
    skill_root = tmp_path / "skill"
    workspace_root = tmp_path / "workspace"
    skill_root.mkdir()
    workspace_root.mkdir()
    executable = tmp_path / "python-copy"
    executable.write_bytes(Path(sys.executable).read_bytes())
    runtime = SkillRuntimeBinding.capture(runtime="python", executable=executable)
    binding = ManagedSkillActionBinding.bind(
        _catalog_action(b"print('ok')\n", skill_root=skill_root)
    )
    resolver = _ApprovalResolver(on_resolve=lambda: executable.write_bytes(b"changed"))

    async def scenario() -> None:
        host = ProcessHost()
        try:
            with pytest.raises(ManagedSkillActionError) as captured:
                await execute_managed_skill_action(
                    binding,
                    runtime=runtime,
                    launcher=_launcher(resolver=resolver, host=host),
                    workspace_root=workspace_root,
                    correlation_id="runtime-race",
                )
            assert captured.value.code == "skill_action_runtime_changed"
            assert len(resolver.requests) == 1
        finally:
            await host.close()

    asyncio.run(scenario())


def test_real_process_host_drains_both_streams_and_preserves_nonzero_exit(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        skill_root = tmp_path / "skill"
        workspace_root = tmp_path / "workspace"
        skill_root.mkdir()
        workspace_root.mkdir()
        script = (
            b"import sys\n"
            b"sys.stdout.buffer.write(b'o' * 70000)\n"
            b"sys.stdout.flush()\n"
            b"sys.stderr.buffer.write(b'e' * 90000)\n"
            b"sys.stderr.flush()\n"
            b"raise SystemExit(7)\n"
        )
        declaration = _declaration(script, argv=())
        document = SkillActionDocumentCodec.encode_bytes(
            SkillActionDocument(actions=(declaration,))
        )
        action = _mint_catalog_managed_skill_action(
            catalog_generation=7,
            catalog_snapshot_fingerprint="3" * 64,
            candidate_fingerprint="4" * 64,
            skill_content_digest="2" * 64,
            source_kind="native",
            source_revision="1" * 64,
            declaration=declaration,
            action_document_digest=sha256(document).hexdigest(),
            script_body=script,
            skill_root=skill_root,
        )
        host = ProcessHost()
        try:
            result = await execute_managed_skill_action(
                ManagedSkillActionBinding.bind(action),
                runtime=SkillRuntimeBinding.capture(
                    runtime="python",
                    executable=sys.executable,
                ),
                launcher=_launcher(resolver=_ApprovalResolver(), host=host),
                workspace_root=workspace_root,
                correlation_id="real-host",
            )
            assert result.return_code == 7
            assert result.stdout == b"o" * 70000
            assert result.stderr == b"e" * 90000
        finally:
            await host.close()

    asyncio.run(scenario())


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX runtime requires sh")
def test_real_process_host_executes_posix_runtime_without_script_path(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        skill_root = tmp_path / "skill"
        workspace_root = tmp_path / "workspace"
        skill_root.mkdir()
        workspace_root.mkdir()
        script = b"printf 'posix-out'; printf 'posix-err' >&2; exit 3\n"
        declaration = skill_action(
            id="review-posix",
            script="scripts/review.sh",
            script_digest=sha256(script).hexdigest(),
            runtime="posix",
        )
        document = SkillActionDocumentCodec.encode_bytes(
            SkillActionDocument(actions=(declaration,))
        )
        action = _mint_catalog_managed_skill_action(
            catalog_generation=7,
            catalog_snapshot_fingerprint="3" * 64,
            candidate_fingerprint="4" * 64,
            skill_content_digest="2" * 64,
            source_kind="native",
            source_revision="1" * 64,
            declaration=declaration,
            action_document_digest=sha256(document).hexdigest(),
            script_body=script,
            skill_root=skill_root,
        )
        host = ProcessHost()
        try:
            result = await execute_managed_skill_action(
                ManagedSkillActionBinding.bind(action),
                runtime=SkillRuntimeBinding.capture(
                    runtime="posix",
                    executable="/bin/sh",
                ),
                launcher=_launcher(resolver=_ApprovalResolver(), host=host),
                workspace_root=workspace_root,
                correlation_id="posix-host",
            )
            assert result.return_code == 3
            assert result.stdout == b"posix-out"
            assert result.stderr == b"posix-err"
        finally:
            await host.close()

    asyncio.run(scenario())


def test_real_process_host_terminates_output_overflow_without_pipe_deadlock(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        skill_root = tmp_path / "skill"
        workspace_root = tmp_path / "workspace"
        skill_root.mkdir()
        workspace_root.mkdir()
        script = (
            b"import sys\n"
            b"sys.stdout.buffer.write(b'x' * 1100000)\n"
            b"sys.stdout.flush()\n"
        )
        action = _catalog_action(script, skill_root=skill_root)
        host = ProcessHost()
        try:
            with pytest.raises(ManagedSkillActionError) as captured:
                await asyncio.wait_for(
                    execute_managed_skill_action(
                        ManagedSkillActionBinding.bind(action),
                        runtime=SkillRuntimeBinding.capture(
                            runtime="python",
                            executable=sys.executable,
                        ),
                        launcher=_launcher(
                            resolver=_ApprovalResolver(),
                            host=host,
                        ),
                        workspace_root=workspace_root,
                        correlation_id="output-overflow",
                    ),
                    timeout=10,
                )
            assert captured.value.code == "skill_action_output_limit_exceeded"
        finally:
            await host.close()

    asyncio.run(scenario())
