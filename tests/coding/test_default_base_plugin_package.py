from __future__ import annotations

import asyncio
from dataclasses import dataclass, field, replace
from pathlib import Path

import pytest

from loushang.ai.types import ToolCall
from loushang.coding._base_plugin import (
    CodingBasePluginAssemblyError,
    build_coding_base_plugin_owners,
    coding_base_plugin_root,
    prepare_coding_base_plugin_assembly,
    prepare_coding_base_plugin_session,
)
from loushang.coding.composition_sets import resolve_coding_composition_set
from loushang.coding.prompt import CODING_STANDARD_SYSTEM_PROMPT_FRAGMENT
from loushang.coding.resource_runtime import CodingPackageMaterializer
from loushang.harness.capabilities import (
    MODEL_INPUT_CAPABILITY_DEFINITION,
    WORKSPACE_CAPABILITY_DEFINITION,
    CapabilityBundleValue,
    CapabilityFacetBinding,
)
from loushang.harness.capabilities.graph_runtime import CapabilityFacetSet
from loushang.harness.capabilities.workspace_contracts import (
    WORKSPACE_EDIT_FACET,
    WORKSPACE_LIST_FACET,
    WORKSPACE_PROCESS_LAUNCH_FACET,
    WORKSPACE_READ_FACET,
    WORKSPACE_SEARCH_FACET,
    WORKSPACE_WRITE_FACET,
)
from loushang.harness.capabilities.workspace_provider import (
    workspace_capability_provider_binding,
)
from loushang.harness.environment import HostEnvironment
from loushang.harness.plugin_authoring.consumer_pack import (
    CommandPackDeclarationPayload,
    ToolPackDeclarationPayload,
)
from loushang.harness.plugin_authoring.host import PluginDeclarationHost
from loushang.harness.plugin_authoring.resource_item import (
    ResourceItemDeclarationPayload,
)
from loushang.harness.resources.plugins.selection import (
    PendingOnlyPluginExecutionDecisionLookup,
    PluginSelection,
)
from loushang.harness.runtime.bindings import RuntimeBindingState
from loushang.harness.runtime.registration import (
    RegistrationDisposalResult,
    RegistrationIdentity,
    RegistrationLease,
    RegistrationOwner,
)
from loushang.harness.session.capability_composition_inputs import (
    SessionCapabilityConsumerCapture,
    commit_session_capability_owner_generations,
    dispose_session_capability_owner_generations,
    stage_session_capability_owner_generations,
)
from loushang.harness.session.product_composition_assembly import (
    ProductCompositionAssemblyRequest,
    ProductPluginSelectionSeed,
    assemble_product_composition,
)
from loushang.harness.tools.core import ToolDefinition
from loushang.harness.tools.execution import (
    AuthorizedExecution,
    AuthorizedToolAction,
    ToolCallContext,
)
from loushang.harness.tools.workspace.factory import ToolsOptions
from loushang.harness.tools.workspace.shell import ShellToolOptions
from loushang.harness.workspace.operations import LocalToolOperations
from loushang.harness.workspace.process import (
    ProcessExit,
    ProcessLaunchRequest,
    ProcessStderrTail,
)
from loushang.harness.workspace.shell import ResolvedShell


def _materializer(tmp_path: Path) -> CodingPackageMaterializer:
    return CodingPackageMaterializer(
        install_root=tmp_path / "installed",
        plugin_revision_root=tmp_path / "revisions",
    )


def _finalize_base(assembly) -> PluginSelection:
    selection = PluginDeclarationHost().resolve(
        assembly.plan_seed.packages,
        bindings=assembly.plan_seed.bindings,
        plan=assembly.plan_seed.plan,
        decision_lookup=PendingOnlyPluginExecutionDecisionLookup(),
    )
    assert isinstance(selection, PluginSelection)
    return selection


def _compile_base(assembly, *, evaluated_at: int):
    return assemble_product_composition(
        ProductCompositionAssemblyRequest(
            selection=_finalize_base(assembly),
            owner_bindings=assembly.plan_seed.owner_bindings,
            mandatory_roots=(MODEL_INPUT_CAPABILITY_DEFINITION.capability_id,),
            definitions=(
                MODEL_INPUT_CAPABILITY_DEFINITION,
                WORKSPACE_CAPABILITY_DEFINITION,
            ),
        ),
        evaluated_at=evaluated_at,
    )


@dataclass(slots=True)
class _CommittedToolPort:
    staged: dict[str, ToolDefinition] = field(default_factory=dict)
    visible: dict[str, ToolDefinition] = field(default_factory=dict)

    def stage_runtime_tool(
        self,
        tool: object,
        *,
        owner: RegistrationOwner,
        enabled: bool = True,
        source_info: object | None = None,
    ) -> RegistrationLease:
        del source_info
        assert enabled is True
        assert isinstance(tool, ToolDefinition)
        name = tool.name
        self.staged[name] = tool

        def activate() -> None:
            self.visible[name] = self.staged[name]

        def deactivate() -> None:
            self.visible.pop(name, None)

        def rollback() -> RegistrationDisposalResult:
            self.staged.pop(name, None)
            return RegistrationDisposalResult(state="removed")

        def dispose() -> RegistrationDisposalResult:
            self.visible.pop(name, None)
            self.staged.pop(name, None)
            return RegistrationDisposalResult(state="removed")

        return RegistrationLease(
            owner=owner,
            identity=RegistrationIdentity.create(surface="tool", public_key=name),
            activate=activate,
            deactivate=deactivate,
            rollback=rollback,
            dispose=dispose,
        )


@dataclass(slots=True)
class _CapturedProcessHandle:
    stdout: list[bytes] = field(default_factory=lambda: [b"captured shell\n", b""])
    stderr: list[bytes] = field(default_factory=lambda: [b""])
    closed: bool = False

    async def read_stdout(self, max_bytes: int = 64 * 1024) -> bytes:
        del max_bytes
        return self.stdout.pop(0)

    async def read_stderr(self, max_bytes: int = 64 * 1024) -> bytes:
        del max_bytes
        return self.stderr.pop(0)

    async def write_stdin(self, data: bytes) -> None:
        del data

    async def close_stdin(self) -> None:
        return None

    async def wait(self) -> ProcessExit:
        return ProcessExit(return_code=0)

    async def terminate(self) -> ProcessExit:
        return ProcessExit(return_code=-1)

    async def close(self) -> None:
        self.closed = True

    def stderr_tail(self) -> ProcessStderrTail:
        return ProcessStderrTail()


@dataclass(slots=True)
class _CapturedLauncher:
    handle: _CapturedProcessHandle = field(default_factory=_CapturedProcessHandle)
    requests: list[ProcessLaunchRequest] = field(default_factory=list)
    correlation_ids: list[str] = field(default_factory=list)

    async def start(
        self,
        request: ProcessLaunchRequest,
        *,
        correlation_id: str,
        signal: object | None = None,
    ) -> _CapturedProcessHandle:
        del signal
        self.requests.append(request)
        self.correlation_ids.append(correlation_id)
        return self.handle


class _WindowsShellResolver:
    def resolve(self, selection=None) -> ResolvedShell:
        del selection
        return ResolvedShell(
            kind="powershell",
            executable=r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
            flavor="windows-powershell",
            target_id="windows-test",
            target_os_family="windows",
            source="system",
            version="5.1",
            edition="Desktop",
        )


def test_checked_in_base_package_is_data_only_and_matches_product_catalogs(
    tmp_path: Path,
) -> None:
    assembly = prepare_coding_base_plugin_assembly(
        resolve_coding_composition_set("coding-standard"),
        session_id="package-shape",
        package_materializer=_materializer(tmp_path),
    )
    try:
        assert assembly.package.manifest.name == "coding.base"
        assert assembly.package.dependency_lock.python_distributions == ()
        assert not (coding_base_plugin_root() / "definition.py").exists()
        assert (coding_base_plugin_root() / "prompts" / "standard.md").read_text(
            encoding="utf-8"
        ) == CODING_STANDARD_SYSTEM_PROMPT_FRAGMENT

        candidates = {
            item.declaration.contribution_id: item
            for item in _finalize_base(assembly).candidates
        }
        assert tuple(candidates) == (
            "coding.builtin",
            "coding.standard",
            "prompt-standard",
            "skill-standard",
        )
        tools = ToolPackDeclarationPayload.from_candidate(candidates["coding.builtin"])
        commands = CommandPackDeclarationPayload.from_candidate(
            candidates["coding.standard"]
        )
        prompt = ResourceItemDeclarationPayload.from_candidate(
            candidates["prompt-standard"]
        )
        skill = ResourceItemDeclarationPayload.from_candidate(
            candidates["skill-standard"]
        )
        assert tools.item_ids == (
            "bash",
            "edit",
            "find",
            "grep",
            "ls",
            "read",
            "write",
        )
        assert tuple(
            item.contribution_id
            for item in assembly.plan_seed.plan.selected_contributions
        ) == (
            "coding.builtin",
            "coding.standard",
            "prompt-standard",
            "skill-standard",
        )
        normalized_seed = replace(
            assembly.plan_seed,
            packages=list(assembly.plan_seed.packages),  # type: ignore[arg-type]
            bindings=list(assembly.plan_seed.bindings),  # type: ignore[arg-type]
            owner_bindings=list(assembly.plan_seed.owner_bindings),  # type: ignore[arg-type]
        )
        assert isinstance(normalized_seed.packages, tuple)
        assert isinstance(normalized_seed.bindings, tuple)
        assert isinstance(normalized_seed.owner_bindings, tuple)
        assert commands.item_ids == (
            "branch",
            "changelog",
            "clone",
            "compact",
            "copy",
            "delete",
            "export",
            "extensions",
            "fork",
            "import",
            "new",
            "reload",
            "rename",
            "resume",
            "session",
            "tools",
            "tree",
        )
        assert (prompt.resource_kind, prompt.locator) == (
            "prompt",
            "prompts/standard.md",
        )
        assert (skill.resource_kind, skill.locator) == (
            "skill",
            "skills/standard/SKILL.md",
        )
        assert (
            (coding_base_plugin_root() / skill.locator)
            .read_text(encoding="utf-8")
            .startswith("---\nname: standard\n")
        )
    finally:
        assembly.close()


def test_base_assembly_compiles_all_four_exact_owner_admissions(
    tmp_path: Path,
) -> None:
    composition_set = resolve_coding_composition_set("coding-standard")
    assembly = prepare_coding_base_plugin_assembly(
        composition_set,
        session_id="owner-admission",
        package_materializer=_materializer(tmp_path),
    )
    try:
        compilation = _compile_base(assembly, evaluated_at=10)

        assert assembly.scope_id == "session:owner-admission"
        assert assembly.composition_set_fingerprint == composition_set.fingerprint
        assert {
            (item.owner_id, item.contribution_kind)
            for item in compilation.resource_admissions
        } == {
            ("resources.prompt", "resource_item"),
            ("resources.skill", "resource_item"),
        }
        assert {
            (item.owner_id, item.contribution_kind)
            for item in compilation.catalog_admissions
        } == {
            ("commands.session", "command_pack"),
            ("tools.workspace", "tool_pack"),
        }
        assert compilation.consumer_requirements.mandatory_roots == (
            "harness.model_input",
        )
        assert compilation.consumer_requirements.roots == (
            "harness.model_input",
            "harness.workspace",
        )
        [requirement] = compilation.consumer_requirements.entries
        assert requirement.plugin_id == "coding.base"
        assert requirement.contribution_id == "coding.builtin"
        assert requirement.requirement.capability == "harness.workspace"
    finally:
        handle = assembly.package.revision_handle
        assert handle.closed is False
        assembly.close()
        assert handle.closed is True
        assembly.close()


def test_base_plan_selects_one_exact_windows_tool_pack_from_captured_environment(
    tmp_path: Path,
) -> None:
    environment = HostEnvironment("windows", "win32", "amd64")
    assembly = prepare_coding_base_plugin_assembly(
        resolve_coding_composition_set("coding-standard"),
        session_id="windows-selection",
        package_materializer=_materializer(tmp_path),
        host_environment=environment,
    )
    try:
        assert assembly.host_environment is environment
        assert assembly.tool_contribution_id == "coding.builtin.windows"
        assert assembly.tool_names == (
            "edit",
            "find",
            "grep",
            "ls",
            "read",
            "shell",
            "write",
        )
        assert tuple(
            item.contribution_id
            for item in assembly.plan_seed.plan.selected_contributions
            if item.contribution_id.startswith("coding.builtin")
        ) == ("coding.builtin.windows",)
        candidates = {
            item.declaration.contribution_id: item
            for item in _finalize_base(assembly).candidates
        }
        assert (
            ToolPackDeclarationPayload.from_candidate(
                candidates["coding.builtin.windows"]
            ).item_ids
            == assembly.tool_names
        )

        compilation = _compile_base(assembly, evaluated_at=10)
        [admission] = [
            item
            for item in compilation.catalog_admissions
            if item.contribution_kind == "tool_pack"
        ]
        assert admission.contribution_id == "coding.builtin.windows"
        assert admission.admitted_identities == assembly.tool_names
    finally:
        assembly.close()


def test_windows_tool_owner_stages_commits_and_executes_only_captured_shell(
    tmp_path: Path,
) -> None:
    asyncio.run(
        _windows_tool_owner_stages_commits_and_executes_only_captured_shell(tmp_path)
    )


async def _windows_tool_owner_stages_commits_and_executes_only_captured_shell(
    tmp_path: Path,
) -> None:
    environment = HostEnvironment("windows", "win32", "amd64")
    launcher = _CapturedLauncher()
    assembly = prepare_coding_base_plugin_assembly(
        resolve_coding_composition_set("coding-standard"),
        session_id="windows-owner",
        package_materializer=_materializer(tmp_path),
        host_environment=environment,
    )
    generations = None
    try:
        selection_seed = ProductPluginSelectionSeed(
            selection=_finalize_base(assembly),
            packages=assembly.plan_seed.packages,
            bindings=assembly.plan_seed.bindings,
            owner_bindings=assembly.plan_seed.owner_bindings,
        )
        preparation = prepare_coding_base_plugin_session(
            assembly,
            evaluated_at=10,
            selection_seed=selection_seed,
        )
        workspace_binding = workspace_capability_provider_binding(
            operations=LocalToolOperations(),
            process_launcher=launcher,
            scope_instance_id="workspace:windows-owner",
            binding_input_fingerprint="f" * 64,
            source_id="windows-owner-test",
        )
        session_assembly = preparation.bind_workspace(workspace_binding)
        owners = build_coding_base_plugin_owners(
            assembly,
            session_assembly.plugin_assembly,
            clock=lambda: 10,
            tool_options=ToolsOptions(
                host_environment=environment,
                shell=ShellToolOptions(
                    resolver_factory=(
                        lambda _environment, _environ, _cwd: _WindowsShellResolver()
                    )
                ),
            ),
        )
        assert owners.tool is not None
        registration = _CommittedToolPort()
        tool_binding = owners.tool.bind(registration)
        [entry] = (
            session_assembly.session_inputs.product_composition.consumer_requirements.satisfied_entries
        )
        operations = LocalToolOperations()
        runtime_state = RuntimeBindingState(
            CapabilityBundleValue(
                (
                    CapabilityFacetBinding(WORKSPACE_READ_FACET, operations),
                    CapabilityFacetBinding(WORKSPACE_LIST_FACET, operations),
                    CapabilityFacetBinding(WORKSPACE_SEARCH_FACET, operations),
                    CapabilityFacetBinding(WORKSPACE_WRITE_FACET, operations),
                    CapabilityFacetBinding(WORKSPACE_EDIT_FACET, operations),
                    CapabilityFacetBinding(
                        WORKSPACE_PROCESS_LAUNCH_FACET,
                        launcher,
                    ),
                )
            )
        )
        capture = SessionCapabilityConsumerCapture(
            entry=entry,
            facets=CapabilityFacetSet(
                requirement=entry.requirement,
                _lease=runtime_state.capture(),
            ),
        )
        [tool_admission] = [
            item
            for item in session_assembly.plugin_assembly.product_composition.catalog_admissions
            if item.contribution_kind == "tool_pack"
        ]

        generations = await stage_session_capability_owner_generations(
            admissions=(tool_admission,),
            bindings=(tool_binding,),
            captures=(capture,),
        )
        assert "shell" in registration.staged
        assert "bash" not in registration.staged
        assert registration.visible == {}

        commit_session_capability_owner_generations(generations)
        assert "shell" in registration.visible
        assert "bash" not in registration.visible

        shell = registration.visible["shell"]
        assert isinstance(shell.execution, AuthorizedExecution)
        call = ToolCall(
            type="toolCall",
            id="shell-call",
            name="shell",
            arguments={"command": "Write-Output captured"},
        )
        context = ToolCallContext(tool_call_id=call.id, cwd=str(tmp_path))
        prepared = shell.execution.action_adapter.prepare(call, context)
        result = await shell.execution.handler(
            AuthorizedToolAction(
                tool_name=prepared.tool_name,
                authorization_arguments=prepared.authorization_arguments,
                execution_arguments=prepared.execution_arguments,
                cwd=prepared.cwd,
                fingerprint="a" * 64,
                effects=prepared.effects,
            ),
            context.authorized(),
        )

        assert result.content[0].text == "captured shell\n"
        assert len(launcher.requests) == 1
        assert launcher.correlation_ids[0].startswith("workspace-exec:")
        assert launcher.requests[0].command[0].lower().endswith("powershell.exe")
        assert launcher.handle.closed is True
    finally:
        if generations is not None:
            await dispose_session_capability_owner_generations(generations)
        assembly.close()


def test_base_plan_can_omit_tools_and_the_tool_claim_prompt(tmp_path: Path) -> None:
    assembly = prepare_coding_base_plugin_assembly(
        resolve_coding_composition_set("coding-standard"),
        session_id="no-tools",
        package_materializer=_materializer(tmp_path),
        include_tool_contribution=False,
        include_tool_claim_prompt=False,
    )
    try:
        assert assembly.tool_contribution_id is None
        assert assembly.tool_names == ()
        assert tuple(
            item.contribution_id
            for item in assembly.plan_seed.plan.selected_contributions
        ) == ("coding.standard", "skill-standard")
        assert {item.owner_key for item in assembly.plan_seed.owner_bindings} == {
            ("commands.session", "command_pack", "coding"),
            ("resources.skill", "resource_item", "coding"),
        }

        compilation = _compile_base(assembly, evaluated_at=10)
        assert not [
            item
            for item in compilation.catalog_admissions
            if item.contribution_kind == "tool_pack"
        ]
        assert not [
            item
            for item in compilation.resource_admissions
            if item.owner_id == "resources.prompt"
        ]
        assert compilation.consumer_requirements.roots == ("harness.model_input",)
    finally:
        assembly.close()


def test_minimal_set_cannot_prepare_a_hidden_base_package(tmp_path: Path) -> None:
    with pytest.raises(CodingBasePluginAssemblyError) as captured:
        prepare_coding_base_plugin_assembly(
            resolve_coding_composition_set("coding-minimal"),
            session_id="minimal",
            package_materializer=_materializer(tmp_path),
        )

    assert captured.value.code == "coding_base_not_requested"
