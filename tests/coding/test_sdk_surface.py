from __future__ import annotations

import asyncio
import inspect
import os
import subprocess
import sys
from pathlib import Path

import pytest

from loushang.ai.model import Capabilities, Model
from loushang.ai.types import TextPart, UserMessage

# Frozen G18.1 compatibility inventory, independent of the future lazy map.
_FACADE_OWNERS = {
    "loushang.ai.model": "ModelSelection",
    "loushang.coding.arch": "CODING_ARCH_TOOL_PACK INSPECT_IMPORT_GRAPH_TOOL_NAME ImportGraphToolRuntime create_inspect_import_graph_tool_definition register_coding_arch_tools",
    "loushang.coding.bootstrap": "AgentSessionServices BootstrapServices CreateAgentSessionResult CwdBoundServicesAudit CwdBoundServicesAuditIssue ExtensionFlagValues create_agent_session create_agent_session_from_services create_agent_session_result create_agent_session_runtime create_agent_session_services create_services",
    "loushang.coding.capabilities": "CODING_ARCH_CAPABILITY CODING_LSP_CAPABILITY",
    "loushang.coding.composition_sets": "CodingCompositionSetId CodingCompositionSetPlan resolve_coding_composition_set",
    "loushang.coding.prompt": "assemble_system_prompt",
    "loushang.coding.resource_runtime": "DefaultResourceLoader:CodingResourceLoader",
    "loushang.coding.runtime": "AgentSessionRuntime",
    "loushang.coding.sdk_surface": "SdkSurfaceCompatibilityReport SdkSurfaceSnapshot check_sdk_surface_compatibility get_sdk_surface_snapshot",
    "loushang.coding.session": "CompactionDecision ContextUsage ContextUsageSnapshot SessionStats TokenUsageTotals TreeNavigationResult",
    "loushang.coding.session_manager": "SessionManager",
    "loushang.coding.tool_pack": "CODING_BUILTIN_TOOL_NAMES CODING_BUILTIN_TOOL_PACK CODING_TOOL_NAMES create_coding_tool_definition create_coding_tool_definitions create_coding_tools",
    "loushang.harness.config.agent": "CapabilityMountMode ControlConfig HeadlessApprovalMode SettingsManager ToolSettings",
}
_FACADE_EXPORT_ORDER = """
AgentSessionServices AgentSessionRuntime BootstrapServices
CODING_BUILTIN_TOOL_NAMES CODING_BUILTIN_TOOL_PACK CODING_ARCH_CAPABILITY
CODING_ARCH_TOOL_PACK CODING_LSP_CAPABILITY CODING_TOOL_NAMES CapabilityMountMode
CodingCompositionSetId CodingCompositionSetPlan CompactionDecision ContextUsage
ContextUsageSnapshot ControlConfig CreateAgentSessionResult CwdBoundServicesAudit
CwdBoundServicesAuditIssue DefaultResourceLoader ExtensionFlagValues
HeadlessApprovalMode INSPECT_IMPORT_GRAPH_TOOL_NAME ImportGraphToolRuntime
ModelSelection ToolSettings TreeNavigationResult SessionManager
SdkSurfaceCompatibilityReport SdkSurfaceSnapshot SettingsManager SessionStats
TokenUsageTotals assemble_system_prompt create_agent_session
create_agent_session_from_services create_agent_session_result
create_agent_session_services create_coding_tool_definition
create_coding_tool_definitions create_coding_tools
create_inspect_import_graph_tool_definition create_agent_session_runtime
create_services check_sdk_surface_compatibility get_sdk_surface_snapshot
register_coding_arch_tools resolve_coding_composition_set
""".split()


@pytest.mark.parametrize(
    "first",
    [
        "loushang.coding",
        "loushang.coding.session_manager",
        "loushang.coding.resource_runtime",
        "loushang.harness",
        "cold-star",
        "cold-named",
        "concurrent-bootstrap",
    ],
)
def test_coding_facade_identity_star_dir_and_pickle_in_fresh_process(tmp_path, first):
    source = Path(__file__).resolve().parents[2] / "src"
    code = f"""
import importlib, pickle, sys, types
sys.path.insert(0, {str(source)!r})
assert 'loushang.coding' not in sys.modules
if {first!r} == 'cold-star':
    from loushang.coding import *
elif {first!r} == 'cold-named':
    from loushang.coding import DefaultResourceLoader, SessionManager
elif {first!r} == 'concurrent-bootstrap':
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    import loushang.coding as coding
    assert 'loushang.coding.bootstrap' not in sys.modules
    names = ('create_services', 'create_agent_session_runtime',
             'AgentSessionServices', 'CwdBoundServicesAudit')
    assert all(name not in vars(coding) for name in names)
    start = Barrier(len(names), timeout=30)
    def resolve(name):
        start.wait()
        value = getattr(coding, name)
        owner = sys.modules['loushang.coding.bootstrap']
        return (name, value, owner, owner._SESSION_MANAGER_PLUGIN_OWNER_LOCK,
                owner._CODING_PLUGIN_HOST_BOOT_ID)
    with ThreadPoolExecutor(max_workers=len(names)) as pool:
        resolved = list(pool.map(resolve, names))
    owner = sys.modules['loushang.coding.bootstrap']
    for name, value, module, lock, boot_id in resolved:
        assert module is owner and value is getattr(owner, name)
        assert lock is owner._SESSION_MANAGER_PLUGIN_OWNER_LOCK
        assert boot_id is owner._CODING_PLUGIN_HOST_BOOT_ID
else:
    importlib.import_module({first!r})
import loushang.coding as coding
assert coding.__file__.startswith({str(source)!r})
owners = {_FACADE_OWNERS!r}
expected = {{}}
for module_name, names in owners.items():
    for entry in names.split():
        public, _, original = entry.partition(':')
        expected[public] = (module_name, original or public)
assert len(expected) == 48
assert len(coding.__all__) == 48 and set(coding.__all__) == set(expected)
assert coding.__all__ == {_FACADE_EXPORT_ORDER!r}
assert set(expected) <= set(dir(coding))
for name, (module_name, original) in expected.items():
    value = getattr(coding, name)
    assert value is getattr(importlib.import_module(module_name), original), name
    assert getattr(coding, name) is value, name
    # Class/function pickle lookup must preserve the original module identity.
    if isinstance(value, (type, types.FunctionType)):
        assert pickle.loads(pickle.dumps(value)) is value, name
scope = {{}}
exec('from loushang.coding import *', scope)
assert set(scope) - {{'__builtins__'}} == set(expected)
assert all(scope[name] is getattr(coding, name) for name in expected)
from loushang.coding import DefaultResourceLoader, SessionManager, TreeNavigationResult
from loushang.coding.resource_runtime import CodingResourceLoader
from loushang.harness.transcript import TranscriptNavigationResult
assert DefaultResourceLoader is CodingResourceLoader
assert TreeNavigationResult is TranscriptNavigationResult
assert SessionManager is coding.SessionManager
for instance in (
    coding.ModelSelection(provider='g18', endpoint_id='synthetic', model_id='model'),
    coding.ContextUsageSnapshot(tokens=7, context_window=100, reserve_tokens=10),
    coding.SdkSurfaceSnapshot(export_names=('SessionManager',), entry_signatures={{}}),
    coding.SdkSurfaceCompatibilityReport(),
):
    restored = pickle.loads(pickle.dumps(instance))
    assert type(restored) is type(instance) and restored == instance
try:
    getattr(coding, 'G18_missing_export')
except AttributeError:
    pass
else:
    raise AssertionError('unknown public symbol did not raise')
"""
    # Import-only compatibility probe, not a timing sample or native acceptance.
    environment = {
        name: value
        for name in ("PATH", "SYSTEMROOT", "WINDIR")
        if (value := os.environ.get(name)) is not None
    }
    for name in (
        "HOME",
        "USERPROFILE",
        "LOUSHANG_HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_CACHE_HOME",
        "LOUSHANG_TMPDIR",
        "TMPDIR",
        "TMP",
        "TEMP",
    ):
        environment[name] = str(tmp_path)
    result = subprocess.run(
        [sys.executable, "-I", "-X", f"pycache_prefix={tmp_path / 'pyc'}", "-c", code],
        cwd=tmp_path,
        env=environment,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert not result.stdout and not result.stderr


@pytest.mark.parametrize("negative", [False, True])
def test_coding_facade_static_types_remain_explicit_not_any(tmp_path, negative):
    source = Path(__file__).resolve().parents[2] / "src"
    code = (
        "from typing import assert_type\n"
        f"from loushang.coding import {', '.join(_FACADE_EXPORT_ORDER)}\n"
        "from loushang.coding.session_manager import SessionManager as OwnerManager\n"
        "from loushang.coding.resource_runtime import CodingResourceLoader\n"
        "manager: SessionManager\n"
        "loader: DefaultResourceLoader\n"
        "assert_type(manager, OwnerManager)\n"
        "assert_type(loader, CodingResourceLoader)\n"
        "selection = ModelSelection(provider='g18', endpoint_id='synthetic', model_id='model')\n"
        "assert_type(selection, ModelSelection)\n"
        "assert_type(selection.model_id, str)\n"
    )
    if negative:
        code += (
            "from loushang.coding import G18_missing_export\n"
            "wrong: int = selection.model_id\n"
            "ModelSelection(provider='g18', endpoint_id='synthetic', model_id=1)\n"
        )
    result = subprocess.run(
        [
            sys.executable, "-m", "mypy", "--config-file=",
            "--python-version=3.11", "--follow-imports=silent",
            "--ignore-missing-imports", "--no-error-summary", "--no-pretty",
            "--show-error-codes", "-c", code,
        ],
        cwd=source.parent,
        env={
            **os.environ,
            "MYPYPATH": str(source),
            "MYPY_CACHE_DIR": str(tmp_path / "mypy"),
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert not result.stderr, result.stderr
    if negative:
        assert result.returncode == 1, result.stdout
        assert result.stdout.count(": error:") == 3, result.stdout
        for kind in ("attr-defined", "assignment", "arg-type"):
            assert f"[{kind}]" in result.stdout, result.stdout
    else:
        assert result.returncode == 0 and not result.stdout, result.stdout


def _model() -> Model:
    return Model(
        id="faux-model",
        name="Faux",
        provider="faux",
        endpoint="anthropic-messages",
        capabilities=Capabilities(
            reasoning=True,
            input=("text",),
            context_window=128000,
            max_tokens=4096,
        ),
    )


def _user_message(text: str) -> UserMessage:
    return UserMessage(
        role="user",
        content=[TextPart(type="text", text=text)],
        timestamp=0.0,
    )


def test_coding_top_level_exports_stable_sdk_surface() -> None:
    import loushang.coding as coding

    expected_names = {
        "AgentSessionRuntime",
        "AgentSessionServices",
        "BootstrapServices",
        "CodingCompositionSetId",
        "CodingCompositionSetPlan",
        "CreateAgentSessionResult",
        "CwdBoundServicesAudit",
        "CwdBoundServicesAuditIssue",
        "ExtensionFlagValues",
        "HeadlessApprovalMode",
        "SdkSurfaceCompatibilityReport",
        "SdkSurfaceSnapshot",
        "SessionManager",
        "check_sdk_surface_compatibility",
        "create_agent_session",
        "create_agent_session_from_services",
        "create_agent_session_result",
        "create_agent_session_runtime",
        "create_agent_session_services",
        "CODING_BUILTIN_TOOL_PACK",
        "CODING_TOOL_NAMES",
        "create_coding_tool_definition",
        "create_coding_tool_definitions",
        "create_coding_tools",
        "resolve_coding_composition_set",
        "create_services",
    }

    assert expected_names.issubset(set(coding.__all__))
    assert {name for name in expected_names if not hasattr(coding, name)} == set()
    assert "AgentSession" not in coding.__all__
    assert "register_coding_builtin_tools" not in coding.__all__
    assert not hasattr(coding, "AgentSession")
    assert not hasattr(coding, "register_coding_builtin_tools")


def test_coding_top_level_exposes_sdk_surface_snapshot() -> None:
    import loushang.coding as coding

    snapshot = coding.get_sdk_surface_snapshot()

    assert isinstance(snapshot, coding.SdkSurfaceSnapshot)
    assert snapshot.missing_exports == ()
    assert "AgentSession" not in snapshot.export_names
    assert snapshot.entry_signatures["create_agent_session_runtime"] == (
        "session_dir",
        "model",
        "stream_fn",
        "system_prompt",
        "thinking_level",
        "tools",
        "tool_registry",
        "allowed_tool_names",
        "active_tool_names",
        "no_tools",
        "composition_set",
        "services",
        "services_factory",
        "agent_factory",
        "persist",
        "append_system_prompt",
        "approval_resolver",
        "tool_policy_evaluator",
        "enable_multiagent",
        "lsp_definitions",
        "lsp_baseline_environment",
        "lsp_read_text",
    )
    assert snapshot.to_dict()["missing_exports"] == []


def test_coding_sdk_surface_compatibility_report_flags_contract_drift() -> None:
    import loushang.coding as coding

    report = coding.check_sdk_surface_compatibility(
        required_exports=("SessionManager", "missing_surface"),
        required_entry_signatures={
            "create_services": (
                "ai_model_registry",
                "resource_loader",
                "settings_manager",
                "exec_service",
                "default_model",
                "thinking_level",
                "system_prompt",
            ),
            "create_agent_session": ("session_manager", "wrong"),
            "missing_entry": (),
        },
    )

    assert report.ok is False
    assert report.missing_exports == ("missing_surface",)
    assert report.missing_entries == ("missing_entry",)
    assert report.signature_mismatches == {
        "create_agent_session": {
            "expected": ("session_manager", "wrong"),
            "actual": tuple(inspect.signature(coding.create_agent_session).parameters),
        }
    }
    assert report.to_dict()["signature_mismatches"]["create_agent_session"][
        "expected"
    ] == [
        "session_manager",
        "wrong",
    ]


def test_coding_top_level_sdk_entry_signatures_are_stable() -> None:
    import loushang.coding as coding

    assert tuple(inspect.signature(coding.create_services).parameters) == (
        "ai_model_registry",
        "resource_loader",
        "settings_manager",
        "exec_service",
        "default_model",
        "thinking_level",
        "system_prompt",
    )
    assert tuple(
        inspect.signature(coding.create_agent_session_services).parameters
    ) == (
        "cwd",
        "services",
        "ai_model_registry",
        "resource_loader",
        "settings_manager",
        "exec_service",
        "default_model",
        "thinking_level",
        "system_prompt",
        "global_settings_path",
        "project_settings_path",
        "resource_loader_options",
        "extension_flag_values",
    )
    assert tuple(inspect.signature(coding.create_agent_session).parameters) == (
        "session_manager",
        "model",
        "stream_fn",
        "system_prompt",
        "thinking_level",
        "tools",
        "tool_registry",
        "allowed_tool_names",
        "active_tool_names",
        "no_tools",
        "composition_set",
        "services",
        "agent_factory",
        "session_start_event",
        "package_materializer",
        "package_product_runtime_factory",
        "append_system_prompt",
        "extension_flag_values",
        "approval_resolver",
        "tool_policy_evaluator",
        "enable_multiagent",
        "lsp_definitions",
        "lsp_baseline_environment",
        "lsp_read_text",
    )
    assert tuple(
        inspect.signature(coding.create_agent_session_result).parameters
    ) == tuple(inspect.signature(coding.create_agent_session).parameters)
    assert tuple(
        inspect.signature(coding.create_agent_session_from_services).parameters
    ) == (
        "agent_services",
        "session_manager",
        "model",
        "stream_fn",
        "system_prompt",
        "thinking_level",
        "tools",
        "tool_registry",
        "allowed_tool_names",
        "active_tool_names",
        "no_tools",
        "composition_set",
        "agent_factory",
        "session_start_event",
        "package_materializer",
        "package_product_runtime_factory",
        "append_system_prompt",
        "approval_resolver",
        "tool_policy_evaluator",
        "enable_multiagent",
        "lsp_definitions",
        "lsp_baseline_environment",
        "lsp_read_text",
    )
    assert tuple(inspect.signature(coding.create_agent_session_runtime).parameters) == (
        "session_dir",
        "model",
        "stream_fn",
        "system_prompt",
        "thinking_level",
        "tools",
        "tool_registry",
        "allowed_tool_names",
        "active_tool_names",
        "no_tools",
        "composition_set",
        "services",
        "services_factory",
        "agent_factory",
        "persist",
        "append_system_prompt",
        "approval_resolver",
        "tool_policy_evaluator",
        "enable_multiagent",
        "lsp_definitions",
        "lsp_baseline_environment",
        "lsp_read_text",
    )


def test_coding_top_level_sdk_smoke_covers_session_runtime_tools_and_diagnostics(
    tmp_path,
) -> None:
    import loushang.coding as coding
    from loushang.coding.session import AgentSession
    from loushang.harness.diagnostics import DiagnosticsQuery

    project_root = tmp_path / "project"
    import_dir = tmp_path / "imports"
    project_root.mkdir()
    import_dir.mkdir()

    async def scenario() -> None:
        services = coding.create_services()
        session_manager = await coding.SessionManager.new(
            session_dir=tmp_path / "direct-sessions",
            cwd=str(project_root),
            persist=True,
        )
        standalone_sessions: list[AgentSession] = []
        runtime = None
        imported_manager = None
        try:
            result = coding.create_agent_session_result(
                session_manager=session_manager,
                model=_model(),
                services=services,
            )
            standalone_sessions.append(result.session)

            assert isinstance(result, coding.CreateAgentSessionResult)
            assert isinstance(
                result.cwd_bound_services_audit,
                coding.CwdBoundServicesAudit,
            )
            assert result.cwd_bound_services_audit.ok is True
            assert [
                record for record in result.diagnostics if record.type == "error"
            ] == []

            direct_session = coding.create_agent_session(
                session_manager=session_manager,
                model=_model(),
                services=services,
            )
            standalone_sessions.append(direct_session)
            assert isinstance(direct_session, AgentSession)
            assert direct_session.session_manager is session_manager
            assert direct_session.get_lsp_status().scope == "session"
            assert direct_session.get_lsp_status().servers == ()
            assert "lsp" in {
                command.name for command in direct_session.list_commands()
            }

            agent_services = coding.create_agent_session_services(
                cwd=project_root,
                global_settings_path=tmp_path / "global-settings.json",
            )
            from_services = coding.create_agent_session_from_services(
                agent_services=agent_services,
                session_manager=session_manager,
                model=_model(),
            )
            standalone_sessions.append(from_services.session)
            assert (
                from_services.session.settings_manager
                is agent_services.settings_manager
            )

            from loushang.harness.tools.workspace import (
                ToolDefinition,
                create_all_tool_definitions,
                create_read_only_tool_definitions,
            )

            read_only_defs = create_read_only_tool_definitions()
            all_defs = create_all_tool_definitions()
            assert {"read", "grep", "ls", "find"}.issubset(
                {definition.name for definition in read_only_defs}
            )
            assert {"read", "bash", "edit", "write"}.issubset(set(all_defs))
            assert all(
                isinstance(definition, ToolDefinition)
                for definition in all_defs.values()
            )

            runtime = coding.create_agent_session_runtime(
                session_dir=tmp_path / "runtime-sessions",
                model=_model(),
                services=services,
                persist=True,
            )
            created = await runtime.create_session(cwd=str(project_root))
            await created.session_manager.append_message(_user_message("runtime root"))
            fork_entry = created.session_manager.get_entries()[0].record_id
            forked = await runtime.fork_session(fork_entry)

            imported_manager = await coding.SessionManager.new(
                session_dir=import_dir,
                cwd=str(project_root),
                persist=True,
            )
            await imported_manager.append_message(_user_message("imported"))
            imported_file = imported_manager.session_file
            assert imported_file is not None

            import_result = await runtime.import_from_jsonl(str(imported_file))
            imported = runtime.get_current_session()

            assert forked.session_manager.get_header().metadata.get(
                "parentSession"
            ) == str(created.session_manager.session_file)
            assert import_result == {"cancelled": False}
            assert imported is not None
            assert [
                message.content[0].text
                for message in imported.get_session_context().messages
            ] == ["imported"]
            assert runtime.get_packages() == []
            assert (
                runtime.get_diagnostics_summary(
                    DiagnosticsQuery(level="error")
                ).total_count
                == 0
            )
            assert runtime.get_diagnostics(DiagnosticsQuery(source="session")) == []
        finally:
            if runtime is not None:
                await runtime.dispose_session_runtime()
            if imported_manager is not None:
                await imported_manager.dispose_runtime_profile()
            for session in reversed(standalone_sessions):
                await session.dispose()

    asyncio.run(scenario())
