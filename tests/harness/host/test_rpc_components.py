from __future__ import annotations

import asyncio
import json
from io import StringIO

import pytest

from loushang.harness.host.jsonl_command_host import JsonlCommand
from loushang.harness.host.product_host import ProductHostTaskTracker
from loushang.harness.host.rpc import RpcHost, run_rpc_host
from loushang.harness.host.rpc.arguments import (
    optional_env_pairs,
    optional_number,
    require_string,
)
from loushang.harness.host.rpc.commands import (
    RpcBashMaintenanceCommands,
    RpcCommandCatalogCommands,
    RpcDiagnosticsCommands,
    RpcModelSettingsCommands,
    RpcPackageCommands,
    RpcSessionLifecycleCommands,
    RpcTranscriptCommands,
)
from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.host.rpc.projections import (
    STANDARD_RPC_DIAGNOSTICS_PROJECTION,
)
from loushang.harness.host.rpc.routing import legacy_rpc_routes
from loushang.harness.session import CommandExecutionResult


def test_rpc_package_keeps_the_stable_host_exports() -> None:
    assert RpcHost.__module__ == "loushang.harness.host.rpc.runtime"
    assert run_rpc_host.__module__ == "loushang.harness.host.rpc.runtime"


def test_rpc_argument_readers_preserve_strict_alias_and_env_rules() -> None:
    assert require_string({"model_id": "model-a"}, "modelId", "model_id") == "model-a"
    assert optional_env_pairs([["A", "1"], ("B", "2")]) == [
        ["A", "1"],
        ["B", "2"],
    ]

    with pytest.raises(ValueError, match="finite number"):
        optional_number({"timeout": float("inf")}, "timeout")
    with pytest.raises(ValueError, match="2-item string pairs"):
        optional_env_pairs([["A"]])


def test_rpc_output_preserves_success_and_safe_fallback_wire_shapes() -> None:
    stdout = StringIO()
    output = RpcOutput(stdout)

    output.success(command="probe", request_id="one", data=None)
    output.write(
        {
            "type": "response",
            "command": "unsafe",
            "id": "two",
            "value": object(),
        }
    )

    lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert lines[0] == {
        "type": "response",
        "command": "probe",
        "success": True,
        "id": "one",
        "data": None,
    }
    assert lines[1] == {
        "type": "response",
        "command": "unsafe",
        "success": False,
        "error": "Failed to serialize RPC output.",
        "id": "two",
    }


def test_legacy_rpc_routes_adapt_sync_and_async_handlers_without_name_lookup() -> None:
    calls: list[tuple[str, str | None, dict[str, object]]] = []

    def sync_handler(command_id: str | None, payload: dict[str, object]) -> None:
        calls.append(("sync", command_id, payload))

    async def async_handler(
        command_id: str | None, payload: dict[str, object]
    ) -> None:
        calls.append(("async", command_id, payload))

    routes = legacy_rpc_routes(
        (("sync", sync_handler), ("async", async_handler))
    )
    asyncio.run(
        routes[0].handler(JsonlCommand("one", "sync", {"value": "a"}))
    )
    asyncio.run(
        routes[1].handler(JsonlCommand("two", "async", {"value": "b"}))
    )

    assert calls == [
        ("sync", "one", {"value": "a"}),
        ("async", "two", {"value": "b"}),
    ]


def test_rpc_command_groups_declare_their_complete_legacy_bindings() -> None:
    output = RpcOutput(StringIO())
    diagnostics = RpcDiagnosticsCommands(
        runtime=object(),
        get_session=object,
        output=output,
        projection=STANDARD_RPC_DIAGNOSTICS_PROJECTION,
    )
    packages = RpcPackageCommands(
        runtime=object(),
        get_session=object,
        output=output,
    )
    lifecycle = RpcSessionLifecycleCommands(
        runtime=object(),
        get_session=object,
        operations=object(),  # type: ignore[arg-type]
        output=output,
    )
    model_settings = RpcModelSettingsCommands(
        get_session=object,
        get_operations=object,  # type: ignore[arg-type]
        output=output,
    )
    transcript = RpcTranscriptCommands(
        get_session=object,
        get_messages=lambda _session: [],
        output=output,
    )
    bash_maintenance = RpcBashMaintenanceCommands(
        get_session=object,
        operations=object(),  # type: ignore[arg-type]
        output=output,
        task_tracker=ProductHostTaskTracker(),
    )
    command_catalog = RpcCommandCatalogCommands(
        get_session=object,
        output=output,
    )

    assert tuple(command for command, _handler in diagnostics.bindings()) == (
        "get_diagnostics",
        "get_session_diagnostics",
        "get_diagnostics_summary",
        "get_session_diagnostics_summary",
        "get_last_error_report",
    )
    assert {command for command, _handler in packages.bindings()} == {
        "get_packages",
        "materialize_package",
        "install_package",
        "update_package",
        "update_packages",
        "check_package_updates",
        "remove_package",
        "uninstall_package",
    }
    assert tuple(command for command, _handler in lifecycle.bindings()) == (
        "list_sessions",
        "new_session",
        "switch_session",
        "fork",
        "clone",
    )
    assert tuple(command for command, _handler in model_settings.bindings()) == (
        "set_model",
        "get_available_models",
        "cycle_model",
        "set_active_tools",
        "set_thinking_level",
        "cycle_thinking_level",
        "set_steering_mode",
        "set_follow_up_mode",
        "get_session_stats",
        "set_session_name",
    )
    assert tuple(command for command, _handler in transcript.bindings()) == (
        "get_messages",
        "get_last_assistant_text",
        "get_fork_messages",
        "export_html",
    )
    assert tuple(command for command, _handler in bash_maintenance.bindings()) == (
        "bash",
        "abort_bash",
        "compact",
        "set_auto_retry",
        "abort_retry",
        "set_auto_compaction",
    )
    assert tuple(command for command, _handler in command_catalog.bindings()) == (
        "get_commands",
        "get_command_completions",
        "execute_command",
    )


def test_rpc_command_execution_returns_the_current_session_result() -> None:
    class _Session:
        def __init__(self, value: str) -> None:
            self.value = value
            self.calls: list[tuple[str, str]] = []

        async def execute_command_async(
            self,
            invocation_name: str,
            args: str,
        ) -> CommandExecutionResult:
            self.calls.append((invocation_name, args))
            return CommandExecutionResult(
                invocation_name=invocation_name,
                result={"value": self.value},
            )

    stdout = StringIO()
    current = [_Session("before")]
    commands = RpcCommandCatalogCommands(
        get_session=lambda: current[0],
        output=RpcOutput(stdout),
    )
    selected = _Session("after")
    current[0] = selected

    asyncio.run(
        commands.execute_command(
            "execute",
            {"command": "/status", "args": "verbose"},
        )
    )

    assert selected.calls == [("status", "verbose")]
    assert json.loads(stdout.getvalue()) == {
        "id": "execute",
        "type": "response",
        "command": "execute_command",
        "success": True,
        "data": {
            "invocationName": "status",
            "args": "verbose",
            "result": {"value": "after"},
        },
    }


@pytest.mark.parametrize(
    ("payload", "error_code"),
    [
        ({"command": ""}, "invalid_request"),
        ({"command": "status", "args": []}, "invalid_request"),
    ],
)
def test_rpc_command_execution_rejects_invalid_input(
    payload: dict[str, object],
    error_code: str,
) -> None:
    stdout = StringIO()
    commands = RpcCommandCatalogCommands(
        get_session=object,
        output=RpcOutput(stdout),
    )

    asyncio.run(commands.execute_command("execute", payload))

    response = json.loads(stdout.getvalue())
    assert response["success"] is False
    assert response["errorCode"] == error_code


def test_rpc_command_execution_reports_unknown_and_unserializable_results() -> None:
    class _Session:
        def __init__(self) -> None:
            self.result: object | None = None

        async def execute_command_async(
            self,
            invocation_name: str,
            args: str,
        ) -> object | None:
            del invocation_name, args
            return self.result

    session = _Session()
    stdout = StringIO()
    commands = RpcCommandCatalogCommands(
        get_session=lambda: session,
        output=RpcOutput(stdout),
    )

    asyncio.run(commands.execute_command("missing", {"command": "missing"}))
    session.result = object()
    asyncio.run(commands.execute_command("unsafe", {"command": "unsafe"}))

    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [response["errorCode"] for response in responses] == [
        "command_not_found",
        "command_result_not_serializable",
    ]


def test_rpc_package_commands_resolve_the_current_rebound_session() -> None:
    class _Session:
        def __init__(self, package_name: str) -> None:
            self._package_name = package_name

        def get_packages(self, *, catalog_path: str | None) -> list[dict[str, object]]:
            assert catalog_path is None
            return [{"name": self._package_name}]

    stdout = StringIO()
    current = [_Session("before")]
    commands = RpcPackageCommands(
        runtime=object(),
        get_session=lambda: current[0],
        output=RpcOutput(stdout),
    )
    current[0] = _Session("after")

    commands.get_packages("packages", {})

    assert json.loads(stdout.getvalue())["data"] == {
        "packages": [{"name": "after"}]
    }
