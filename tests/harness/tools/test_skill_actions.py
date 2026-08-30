from __future__ import annotations

import asyncio
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from loushang.harness.approval import ApprovalDecision
from loushang.harness.resources._catalog_records import ResourceIdentity
from loushang.harness.resources._skill_catalog_consumer import SkillCatalogSummary
from loushang.harness.resources.plugins.manifest import PluginManifestParser
from loushang.harness.resources.plugins.revisions import PluginRevisionStore
from loushang.harness.resources.skill_actions import (
    SkillActionDocument,
    SkillActionDocumentCodec,
)
from loushang.harness.resources.types import RevisionResourceRef
from loushang.harness.tools.process_hosting import (
    ProcessExecutionScope,
    ScopeBoundProcessLauncher,
)
from loushang.harness.tools.skill_actions import (
    ManagedSkillActionBinding,
    ManagedSkillActionError,
    NativeSkillActionSource,
    PackageSkillActionSource,
    SkillActionCatalogSelection,
    SkillRuntimeBinding,
    execute_managed_skill_action,
)
from loushang.harness.workspace.process import ProcessExit
from loushang.harness.workspace.process.local import ProcessContainmentPlan
from loushang.plugin import package, resource, skill_action, skill_action_effect


class _ApprovalResolver:
    actor_id = "root"

    def __init__(self) -> None:
        self.requests = []

    def resolve(self, request):
        self.requests.append(request)
        return ApprovalDecision.allow()


class _Handle:
    def __init__(self) -> None:
        self.stdin = bytearray()
        self.closed = False

    async def read_stdout(self, max_bytes: int = 64 * 1024) -> bytes:
        return b"ok\n"[:max_bytes]

    async def read_stderr(self, max_bytes: int = 64 * 1024) -> bytes:
        return b""[:max_bytes]

    async def write_stdin(self, data: bytes) -> None:
        self.stdin.extend(data)

    async def close_stdin(self) -> None:
        return None

    async def wait(self) -> ProcessExit:
        return ProcessExit(return_code=0)

    async def terminate(self) -> ProcessExit:
        return ProcessExit(return_code=0)

    async def close(self) -> None:
        self.closed = True

    def stderr_tail(self):
        raise AssertionError("not used")


class _Containment:
    requirement = "required"

    def __init__(self) -> None:
        self.plans = []

    async def plan(self, request, *, execution_profile):
        del execution_profile
        plan = ProcessContainmentPlan(request)
        self.plans.append(plan)
        return plan


class _Host:
    def __init__(self) -> None:
        self.requests = []
        self.handle = _Handle()

    async def start(self, request, *, containment_planner):
        await containment_planner(request)
        self.requests.append(request)
        return self.handle


def _declaration(script: bytes):
    return skill_action(
        id="review",
        script="scripts/review.py",
        script_digest=sha256(script).hexdigest(),
        runtime="python",
        argv=("--check",),
        environment=(("LANG", "C.UTF-8"),),
        effects=(skill_action_effect(kind="filesystem.read", target="workspace"),),
    )


def _selection(
    *,
    source_kind: str = "native",
    source_revision: str = "1" * 64,
    skill_content_digest: str = "2" * 64,
) -> SkillActionCatalogSelection:
    return SkillActionCatalogSelection(
        catalog_generation=7,
        catalog_snapshot_fingerprint="3" * 64,
        candidate_fingerprint="4" * 64,
        skill_content_digest=skill_content_digest,
        source_kind=source_kind,  # type: ignore[arg-type]
        source_revision=source_revision,
    )


def _package_catalog_selection(
    *,
    package_digest: str,
    skill_digest: str,
    skill_path: Path,
) -> SkillActionCatalogSelection:
    summary = SkillCatalogSummary(
        catalog_generation=7,
        catalog_snapshot_fingerprint="3" * 64,
        activation_policy_fingerprint="5" * 64,
        candidate_fingerprint="4" * 64,
        identity=ResourceIdentity(
            resource_kind="skill",
            schema_id="loushang.resource.skill",
            schema_version=1,
            public_id="review/SKILL.md",
        ),
        name="review",
        canonical_name="review",
        description="Review",
        enabled=True,
        model_invocable=True,
        media_type="text/markdown",
        expected_content_digest=skill_digest,
        expected_content_length=9,
        source_path=skill_path,
        source_root=skill_path.parent,
        source_kind="external_package",
        source_scope="package",
        source_root_order=0,
        source="plugin",
        diagnostics=(),
        declared_id="review",
        revision_ref=RevisionResourceRef(
            content_digest=package_digest,
            relative_path="skills/review/SKILL.md",
        ),
    )
    return summary.managed_action_selection()


def test_skill_action_document_is_strict_and_canonical() -> None:
    declaration = _declaration(b"print('ok')\n")
    encoded = SkillActionDocumentCodec.encode_bytes(
        SkillActionDocument(actions=(declaration,))
    )

    decoded = SkillActionDocumentCodec.decode_bytes(encoded)

    assert decoded.actions == (declaration,)
    with pytest.raises(ValueError):
        SkillActionDocumentCodec.decode_bytes(encoded + b"\n")


def test_native_skill_action_uses_exact_approval_and_required_containment(
    tmp_path: Path,
) -> None:
    script = b"print('captured')\n"
    skill_root = tmp_path / "skill"
    workspace_root = tmp_path / "workspace"
    skill_root.mkdir()
    workspace_root.mkdir()
    declaration = _declaration(script)
    captured_scripts = {"scripts/review.py": script}
    source = NativeSkillActionSource(
        source_revision="1" * 64,
        skill_content_digest="2" * 64,
        skill_root=skill_root,
        scripts=captured_scripts,
    )
    captured_scripts["scripts/review.py"] = b"raise SystemExit('changed')\n"
    binding = ManagedSkillActionBinding.bind(
        declaration,
        selection=_selection(),
        source=source,
    )
    resolver = _ApprovalResolver()
    host = _Host()
    launcher = ScopeBoundProcessLauncher(
        scope=ProcessExecutionScope(
            approval_resolver=resolver,
            require_approval=True,
        ),
        host=host,  # type: ignore[arg-type]
        containment=_Containment(),
    )
    runtime = SkillRuntimeBinding.capture(
        runtime="python",
        executable=sys.executable,
    )

    result = asyncio.run(
        execute_managed_skill_action(
            binding,
            runtime=runtime,
            launcher=launcher,
            workspace_root=workspace_root,
            correlation_id="skill-action-1",
        )
    )

    assert result.return_code == 0
    assert result.stdout == b"ok\n"
    assert bytes(host.handle.stdin) == script
    assert host.handle.closed
    assert len(resolver.requests) == 1
    request = resolver.requests[0]
    assert request.policy_code == "managed_process_requires_approval"
    metadata = request.arguments["metadata"]
    assert metadata["actionBindingFingerprint"] == binding.binding_fingerprint
    assert metadata["scriptDigest"] == declaration.script_digest
    assert metadata["catalogGeneration"] == 7
    assert metadata["candidateFingerprint"] == "4" * 64
    assert metadata["sourceRevision"] == source.source_revision
    [launch] = host.requests
    assert launch.command[1:] == ("-", "--check")
    assert launch.effective_environment == (("LANG", "C.UTF-8"),)
    assert launch.declared_effects[0].capability == "filesystem.read"


def test_skill_action_rejects_non_required_containment_before_start(
    tmp_path: Path,
) -> None:
    script = b"print('captured')\n"
    skill_root = tmp_path / "skill"
    workspace_root = tmp_path / "workspace"
    skill_root.mkdir()
    workspace_root.mkdir()
    binding = ManagedSkillActionBinding.bind(
        _declaration(script),
        selection=_selection(),
        source=NativeSkillActionSource(
            source_revision="1" * 64,
            skill_content_digest="2" * 64,
            skill_root=skill_root,
            scripts={"scripts/review.py": script},
        ),
    )
    runtime = SkillRuntimeBinding.capture(
        runtime="python",
        executable=sys.executable,
    )

    class _WeakLauncher:
        approval_required = True
        containment_requirement = "best_effort"
        started = False

        async def start(self, request, *, correlation_id, signal=None):
            self.started = True
            raise AssertionError("weak launcher must not start")

    launcher = _WeakLauncher()
    with pytest.raises(ManagedSkillActionError) as captured:
        asyncio.run(
            execute_managed_skill_action(
                binding,
                runtime=runtime,
                launcher=launcher,  # type: ignore[arg-type]
                workspace_root=workspace_root,
                correlation_id="skill-action-2",
            )
        )

    assert captured.value.code == "skill_action_containment_required"
    assert not launcher.started


def test_skill_action_rejects_source_outside_catalog_selection(
    tmp_path: Path,
) -> None:
    script = b"print('captured')\n"
    skill_root = tmp_path / "skill"
    skill_root.mkdir()
    source = NativeSkillActionSource(
        source_revision="1" * 64,
        skill_content_digest="2" * 64,
        skill_root=skill_root,
        scripts={"scripts/review.py": script},
    )

    with pytest.raises(ManagedSkillActionError) as captured:
        ManagedSkillActionBinding.bind(
            _declaration(script),
            selection=_selection(source_revision="9" * 64),
            source=source,
        )

    assert captured.value.code == "skill_action_catalog_selection_mismatch"


def test_package_skill_action_is_pinned_to_published_revision(tmp_path: Path) -> None:
    script = b"print('published')\n"
    declaration = _declaration(script)
    skill = resource.skill(
        contribution_id="review-skill",
        locator="skills/review",
        actions=(declaration,),
    )
    compiled = package(
        id="org.example.review",
        version="1",
        contributions=(skill,),
    )
    source_root = tmp_path / "source"
    for artifact in compiled.artifacts:
        target = source_root / artifact.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(artifact.content)
    skill_root = source_root / "skills" / "review"
    scripts = skill_root / "scripts"
    scripts.mkdir()
    skill_body = b"# Review\n"
    (skill_root / "SKILL.md").write_bytes(skill_body)
    mutable_script = scripts / "review.py"
    mutable_script.write_bytes(script)
    published = PluginRevisionStore(tmp_path / "revisions").publish(
        PluginManifestParser().parse(source_root)
    )
    source = PackageSkillActionSource(
        source_revision="org.example.review@1",
        skill_content_digest=sha256(skill_body).hexdigest(),
        skill_root_locator="skills/review",
        package_content_digest=published.content_digest,
        revision_handle=published.revision_handle,
    )
    binding = ManagedSkillActionBinding.bind(
        declaration,
        selection=_package_catalog_selection(
            package_digest=published.content_digest,
            skill_digest=sha256(skill_body).hexdigest(),
            skill_path=skill_root / "SKILL.md",
        ),
        source=source,
    )

    mutable_script.write_bytes(b"raise SystemExit('changed')\n")

    assert binding.read_verified_script() == script
    assert binding.source_revision == "org.example.review@1"
    assert binding.catalog_source_revision == published.content_digest
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    resolver = _ApprovalResolver()
    host = _Host()
    launcher = ScopeBoundProcessLauncher(
        scope=ProcessExecutionScope(
            approval_resolver=resolver,
            require_approval=True,
        ),
        host=host,  # type: ignore[arg-type]
        containment=_Containment(),
    )
    result = asyncio.run(
        execute_managed_skill_action(
            binding,
            runtime=SkillRuntimeBinding.capture(
                runtime="python",
                executable=sys.executable,
            ),
            launcher=launcher,
            workspace_root=workspace_root,
            correlation_id="package-skill-action",
        )
    )
    assert result.return_code == 0
    assert bytes(host.handle.stdin) == script
    assert len(resolver.requests) == 1
    assert resolver.requests[0].arguments["metadata"]["sourceKind"] == "package"
    with pytest.raises(ValueError, match="digest"):
        PackageSkillActionSource(
            source_revision="org.example.review@1",
            skill_content_digest=sha256(skill_body).hexdigest(),
            skill_root_locator="skills/review",
            package_content_digest="0" * 64,
            revision_handle=published.revision_handle,
        )
    published.revision_handle.close()
