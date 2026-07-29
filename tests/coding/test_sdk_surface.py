from __future__ import annotations

import asyncio
import inspect

from loushang.ai.model import Capabilities, Model
from loushang.ai.types import TextPart, UserMessage


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
        "AgentSession",
        "AgentSessionRuntime",
        "AgentSessionServices",
        "BootstrapServices",
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
        "register_coding_builtin_tools",
        "create_services",
    }

    assert expected_names.issubset(set(coding.__all__))
    assert {name for name in expected_names if not hasattr(coding, name)} == set()


def test_coding_top_level_exposes_sdk_surface_snapshot() -> None:
    import loushang.coding as coding

    snapshot = coding.get_sdk_surface_snapshot()

    assert isinstance(snapshot, coding.SdkSurfaceSnapshot)
    assert snapshot.missing_exports == ()
    assert "AgentSession" in snapshot.export_names
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
        "services",
        "services_factory",
        "agent_factory",
        "persist",
        "append_system_prompt",
        "approval_resolver",
        "enable_multiagent",
    )
    assert snapshot.to_dict()["missing_exports"] == []


def test_coding_sdk_surface_compatibility_report_flags_contract_drift() -> None:
    import loushang.coding as coding

    report = coding.check_sdk_surface_compatibility(
        required_exports=("AgentSession", "missing_surface"),
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
        "services",
        "agent_factory",
        "session_start_event",
        "package_materializer",
        "append_system_prompt",
        "extension_flag_values",
        "approval_resolver",
        "enable_multiagent",
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
        "agent_factory",
        "session_start_event",
        "package_materializer",
        "append_system_prompt",
        "approval_resolver",
        "enable_multiagent",
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
        "services",
        "services_factory",
        "agent_factory",
        "persist",
        "append_system_prompt",
        "approval_resolver",
        "enable_multiagent",
    )


def test_coding_top_level_sdk_smoke_covers_session_runtime_tools_and_diagnostics(
    tmp_path,
) -> None:
    import loushang.coding as coding
    from loushang.harness.diagnostics import DiagnosticsQuery

    project_root = tmp_path / "project"
    import_dir = tmp_path / "imports"
    project_root.mkdir()
    import_dir.mkdir()

    services = coding.create_services()
    session_manager = asyncio.run(
        coding.SessionManager.new(
            session_dir=tmp_path / "direct-sessions",
            cwd=str(project_root),
            persist=True,
        )
    )
    result = coding.create_agent_session_result(
        session_manager=session_manager,
        model=_model(),
        services=services,
    )

    assert isinstance(result, coding.CreateAgentSessionResult)
    assert isinstance(result.cwd_bound_services_audit, coding.CwdBoundServicesAudit)
    assert result.cwd_bound_services_audit.ok is True
    assert [record for record in result.diagnostics if record.type == "error"] == []

    direct_session = coding.create_agent_session(
        session_manager=session_manager,
        model=_model(),
        services=services,
    )
    assert isinstance(direct_session, coding.AgentSession)
    assert direct_session.session_manager is session_manager

    agent_services = coding.create_agent_session_services(
        cwd=project_root,
        global_settings_path=tmp_path / "global-settings.json",
    )
    from_services = coding.create_agent_session_from_services(
        agent_services=agent_services,
        session_manager=session_manager,
        model=_model(),
    )
    assert from_services.session.settings_manager is agent_services.settings_manager

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
        isinstance(definition, ToolDefinition) for definition in all_defs.values()
    )

    runtime = coding.create_agent_session_runtime(
        session_dir=tmp_path / "runtime-sessions",
        model=_model(),
        services=services,
        persist=True,
    )
    created = asyncio.run(runtime.create_session(cwd=str(project_root)))
    asyncio.run(created.session_manager.append_message(_user_message("runtime root")))
    fork_entry = created.session_manager.get_entries()[0].record_id
    forked = asyncio.run(runtime.fork_session(fork_entry))

    imported_manager = asyncio.run(
        coding.SessionManager.new(
            session_dir=import_dir,
            cwd=str(project_root),
            persist=True,
        )
    )
    asyncio.run(imported_manager.append_message(_user_message("imported")))
    imported_file = imported_manager.session_file
    assert imported_file is not None

    import_result = asyncio.run(runtime.import_from_jsonl(str(imported_file)))
    imported = runtime.get_current_session()

    assert forked.session_manager.get_header().metadata.get("parentSession") == str(
        created.session_manager.session_file
    )
    assert import_result == {"cancelled": False}
    assert imported is not None
    assert [
        message.content[0].text for message in imported.get_session_context().messages
    ] == ["imported"]
    assert runtime.get_packages() == []
    assert (
        runtime.get_diagnostics_summary(DiagnosticsQuery(level="error")).total_count
        == 0
    )
    assert runtime.get_diagnostics(DiagnosticsQuery(source="session")) == []
