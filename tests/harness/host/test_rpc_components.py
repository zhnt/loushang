from __future__ import annotations

import asyncio
import json
from hashlib import sha256
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


def _product_record(
    operation_id: str,
    *,
    action: str = "install",
    source_digit: str = "1",
    failed: bool = False,
) -> dict[str, object]:
    source = f"sha256:{source_digit * 64}"
    return {
        "action": action,
        "errorCode": "package_operation_interrupted" if failed else "",
        "errorMessage": "package_operation_interrupted" if failed else "",
        "kind": "plugin_package",
        "lifecycle": "failed" if failed else "installed",
        "name": f"plugin-{source_digit * 12}",
        "operationId": operation_id,
        "packageLifecycleDisposition": (
            "retryable_failure" if failed else "committed"
        ),
        "packageLifecyclePhase": "acquired" if failed else "committed",
        "path": "",
        "recordVersion": 1,
        "source": source,
    }


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

    async def async_handler(command_id: str | None, payload: dict[str, object]) -> None:
        calls.append(("async", command_id, payload))

    routes = legacy_rpc_routes((("sync", sync_handler), ("async", async_handler)))
    asyncio.run(routes[0].handler(JsonlCommand("one", "sync", {"value": "a"})))
    asyncio.run(routes[1].handler(JsonlCommand("two", "async", {"value": "b"})))

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

    assert json.loads(stdout.getvalue())["data"] == {"packages": [{"name": "after"}]}


def test_rpc_package_uninstall_prefers_runtime_owner_before_session_async_name() -> (
    None
):
    class _Runtime:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def uninstall_package(self, source: str) -> dict[str, object]:
            self.calls.append(source)
            return {"lifecycle": "uninstalled", "source": source}

    class _Session:
        async def uninstall_package_async(self, source: str) -> object:
            raise AssertionError(f"session authority used for {source}")

    runtime = _Runtime()
    stdout = StringIO()
    commands = RpcPackageCommands(
        runtime=runtime,
        get_session=_Session,
        output=RpcOutput(stdout),
    )
    handlers = dict(commands.bindings())

    asyncio.run(handlers["uninstall_package"]("uninstall", {"source": "pack"}))

    assert runtime.calls == ["pack"]
    assert json.loads(stdout.getvalue())["data"] == {
        "record": {"lifecycle": "uninstalled", "source": "pack"}
    }


def test_rpc_package_lifecycle_uses_correlated_typed_product_route() -> None:
    class _Runtime:
        async def install_package(self, source: str) -> object:
            raise AssertionError(f"runtime fallback used for {source}")

    class _Session:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str, str, str]] = []

        async def execute_package_lifecycle(
            self,
            action: str,
            source: str,
            *,
            entrypoint: str,
            operation_id: str,
            scope: str,
        ) -> dict[str, object]:
            self.calls.append((action, source, entrypoint, operation_id, scope))
            return {"lifecycle": "installed", "operationId": operation_id}

    runtime = _Runtime()
    session = _Session()
    stdout = StringIO()
    commands = RpcPackageCommands(
        runtime=runtime,
        get_session=lambda: session,
        output=RpcOutput(stdout),
    )

    asyncio.run(
        dict(commands.bindings())["install_package"](
            "request-1",
            {"source": "acme", "scope": "user"},
        )
    )

    assert len(session.calls) == 1
    action, source, entrypoint, operation_id, scope = session.calls[0]
    assert (action, source, entrypoint, scope) == (
        "install",
        "acme",
        "rpc",
        "user",
    )
    assert len(operation_id) == 64
    assert "request-1" not in operation_id
    assert json.loads(stdout.getvalue())["data"]["record"]["operationId"] == (
        operation_id
    )


def test_rpc_refuses_mismatched_runtime_and_session_product_owners() -> None:
    class Owner:
        def __init__(self, binding_id: str) -> None:
            self.package_product_binding_id = binding_id
            self.calls = 0

        async def execute_package_lifecycle(self, *args: object, **kwargs: object):
            del args, kwargs
            self.calls += 1
            return {"lifecycle": "installed"}

    runtime = Owner("runtime-owner")
    session = Owner("session-owner")
    stdout = StringIO()
    commands = RpcPackageCommands(
        runtime=runtime,
        get_session=lambda: session,
        output=RpcOutput(stdout),
    )

    asyncio.run(
        dict(commands.bindings())["install_package"](
            "request-1",
            {"source": "acme"},
        )
    )

    response = json.loads(stdout.getvalue())
    assert response["success"] is False
    assert runtime.calls == session.calls == 0


def test_rpc_enforced_product_mode_never_uses_hidden_legacy_helper() -> None:
    class Runtime:
        package_product_lifecycle_mode = "enforced"

        def __init__(self) -> None:
            self.calls = 0

        async def install_package(self, source: str) -> dict[str, object]:
            del source
            self.calls += 1
            return {"lifecycle": "installed"}

    class Session:
        package_product_lifecycle_mode = "enforced"
        package_product_binding_id = "owner:test"

        def __init__(self) -> None:
            self.calls = 0

        async def install_package(self, source: str) -> dict[str, object]:
            del source
            self.calls += 1
            return {"lifecycle": "installed"}

    runtime = Runtime()
    session = Session()
    stdout = StringIO()
    commands = RpcPackageCommands(
        runtime=runtime,
        get_session=lambda: session,
        output=RpcOutput(stdout),
    )

    asyncio.run(
        dict(commands.bindings())["install_package"](
            "request-1",
            {"source": "acme"},
        )
    )

    assert json.loads(stdout.getvalue())["success"] is False
    assert runtime.calls == session.calls == 0


def test_rpc_runtime_typed_route_requires_same_session_owner() -> None:
    class Runtime:
        package_product_binding_id = "owner:test"

        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []

        async def execute_package_lifecycle(
            self,
            action: str,
            source: str,
            *,
            entrypoint: str,
            operation_id: str,
            scope: str,
        ) -> dict[str, object]:
            self.calls.append((action, entrypoint, scope))
            del source
            return _product_record(operation_id)

    class Session:
        package_product_binding_id = "owner:test"
        package_product_lifecycle_mode = "enforced"

    runtime = Runtime()
    stdout = StringIO()
    commands = RpcPackageCommands(
        runtime=runtime,
        get_session=Session,
        output=RpcOutput(stdout),
    )

    asyncio.run(
        dict(commands.bindings())["install_package"](
            "request-1",
            {"source": "acme", "scope": "global"},
        )
    )

    assert runtime.calls == [("install", "rpc", "global")]
    assert json.loads(stdout.getvalue())["success"] is True


def test_rpc_update_check_uses_correlated_product_collection() -> None:
    class Session:
        package_product_binding_id = "owner:test"
        package_product_lifecycle_mode = "enforced"

        def __init__(self) -> None:
            self.calls: list[tuple[str, str, str]] = []

        async def execute_package_lifecycle_collection(
            self,
            action: str,
            *,
            entrypoint: str,
            operation_id: str,
            scope: str,
        ) -> list[dict[str, object]]:
            self.calls.append((action, entrypoint, scope))
            return [
                {
                    "checkVersion": 1,
                    "errorCode": "",
                    "name": "plugin-111111111111",
                    "scope": scope,
                    "source": f"sha256:{'1' * 64}",
                    "updateAvailable": False,
                }
            ]

    session = Session()
    stdout = StringIO()
    commands = RpcPackageCommands(
        runtime=object(),
        get_session=lambda: session,
        output=RpcOutput(stdout),
    )

    asyncio.run(
        dict(commands.bindings())["check_package_updates"](
            "request-1",
            {"scope": "session"},
        )
    )

    assert session.calls == [("check", "rpc", "session")]
    assert json.loads(stdout.getvalue())["success"] is True


@pytest.mark.parametrize("action", ["install_package", "check_package_updates"])
def test_rpc_refuses_runtime_product_owner_without_session_attestation(
    action: str,
) -> None:
    class Runtime:
        package_product_binding_id = "owner:test"
        package_product_lifecycle_mode = "enforced"

        def __init__(self) -> None:
            self.calls = 0

        async def execute_package_lifecycle(self, *args: object, **kwargs: object):
            del args, kwargs
            self.calls += 1
            return {"lifecycle": "installed"}

        async def execute_package_lifecycle_collection(
            self, *args: object, **kwargs: object
        ):
            del args, kwargs
            self.calls += 1
            return []

    class Session:
        package_product_lifecycle_mode = "legacy"

    runtime = Runtime()
    stdout = StringIO()
    commands = RpcPackageCommands(
        runtime=runtime,
        get_session=Session,
        output=RpcOutput(stdout),
    )

    payload = {"source": "acme"} if action == "install_package" else {}
    asyncio.run(dict(commands.bindings())[action]("request-1", payload))

    assert json.loads(stdout.getvalue())["success"] is False
    assert runtime.calls == 0


@pytest.mark.parametrize("failure_kind", ["exception", "invalid_projection"])
def test_rpc_product_update_check_never_leaks_runtime_details(
    failure_kind: str,
) -> None:
    secret = "file:///home/alice/private/acme.whl?token=secret"

    class Runtime:
        package_product_binding_id = "owner:test"

        async def execute_package_lifecycle_collection(
            self, *args: object, **kwargs: object
        ) -> list[dict[str, object]]:
            del args, kwargs
            if failure_kind == "exception":
                raise RuntimeError(secret)
            return [{"source": secret}]

    class Session:
        package_product_binding_id = "owner:test"
        package_product_lifecycle_mode = "enforced"

    stdout = StringIO()
    commands = RpcPackageCommands(
        runtime=Runtime(),
        get_session=Session,
        output=RpcOutput(stdout),
    )

    asyncio.run(
        dict(commands.bindings())["check_package_updates"]("request-1", {})
    )

    response = stdout.getvalue()
    assert secret not in response
    assert json.loads(response)["success"] is False


@pytest.mark.parametrize("failure_kind", ["exception", "invalid_projection"])
def test_rpc_product_lifecycle_never_leaks_runtime_details(
    failure_kind: str,
) -> None:
    secret = "file:///home/alice/private/acme.whl?token=secret"

    class Runtime:
        package_product_binding_id = "owner:test"

        async def execute_package_lifecycle(
            self, *args: object, **kwargs: object
        ) -> dict[str, object]:
            del args, kwargs
            if failure_kind == "exception":
                raise RuntimeError(secret)
            return {"lifecycle": "installed", "path": secret}

    class Session:
        package_product_binding_id = "owner:test"
        package_product_lifecycle_mode = "enforced"

    stdout = StringIO()
    commands = RpcPackageCommands(
        runtime=Runtime(),
        get_session=Session,
        output=RpcOutput(stdout),
    )

    asyncio.run(
        dict(commands.bindings())["install_package"](
            "request-1",
            {"source": "acme"},
        )
    )

    response = stdout.getvalue()
    assert secret not in response
    assert json.loads(response)["success"] is False


@pytest.mark.parametrize("collection", [False, True])
@pytest.mark.parametrize("field", ["name", "errorCode"])
def test_rpc_product_lifecycle_rejects_unclassified_detail_channels(
    collection: bool,
    field: str,
) -> None:
    secret = "file:///home/alice/private/acme.whl?token=secret"

    class Session:
        package_product_binding_id = "owner:test"
        package_product_lifecycle_mode = "enforced"

        async def execute_package_lifecycle(
            self, *args: object, operation_id: str, **kwargs: object
        ) -> dict[str, object]:
            del args, kwargs
            record = _product_record(operation_id, failed=field == "errorCode")
            record[field] = secret
            if field == "errorCode":
                record["errorMessage"] = secret
            return record

        async def execute_package_lifecycle_collection(
            self, *args: object, operation_id: str, **kwargs: object
        ) -> list[dict[str, object]]:
            del args, kwargs
            source = f"sha256:{'1' * 64}"
            child_id = sha256(f"{operation_id}\0{source}".encode()).hexdigest()
            record = _product_record(
                child_id,
                action="update",
                failed=field == "errorCode",
            )
            record[field] = secret
            if field == "errorCode":
                record["errorMessage"] = secret
            return [record]

    stdout = StringIO()
    commands = RpcPackageCommands(
        runtime=object(),
        get_session=Session,
        output=RpcOutput(stdout),
    )
    command = "update_packages" if collection else "install_package"
    payload = {} if collection else {"source": "acme"}
    asyncio.run(dict(commands.bindings())[command]("request-1", payload))

    response = stdout.getvalue()
    assert secret not in response
    assert json.loads(response)["success"] is False


def test_rpc_product_bulk_success_projection_cannot_add_secret_fields() -> None:
    secret = "file:///home/alice/private/acme.whl?token=secret"

    class Session:
        package_product_binding_id = "owner:test"
        package_product_lifecycle_mode = "enforced"

        async def execute_package_lifecycle_collection(
            self, *args: object, **kwargs: object
        ) -> list[dict[str, object]]:
            del args, kwargs
            return [{"lifecycle": "installed", "path": secret}]

    stdout = StringIO()
    commands = RpcPackageCommands(
        runtime=object(),
        get_session=Session,
        output=RpcOutput(stdout),
    )

    asyncio.run(dict(commands.bindings())["update_packages"]("request-1", {}))

    response = stdout.getvalue()
    assert secret not in response
    assert json.loads(response)["success"] is False


@pytest.mark.parametrize("failed_rows", [(True,), (False, True)])
def test_rpc_product_bulk_failure_never_returns_success(
    failed_rows: tuple[bool, ...],
) -> None:
    class Session:
        package_product_binding_id = "owner:test"
        package_product_lifecycle_mode = "enforced"

        async def execute_package_lifecycle_collection(
            self,
            _action: str,
            *,
            entrypoint: str,
            operation_id: str,
            scope: str,
        ) -> list[dict[str, object]]:
            del entrypoint, scope
            result = []
            for index, failed in enumerate(failed_rows, start=1):
                source = f"sha256:{str(index) * 64}"
                child_id = sha256(
                    f"{operation_id}\0{source}".encode()
                ).hexdigest()
                result.append(
                    _product_record(
                        child_id,
                        action="update",
                        source_digit=str(index),
                        failed=failed,
                    )
                )
            return result

    stdout = StringIO()
    commands = RpcPackageCommands(
        runtime=object(),
        get_session=Session,
        output=RpcOutput(stdout),
    )

    asyncio.run(dict(commands.bindings())["update_packages"]("request-1", {}))

    response = json.loads(stdout.getvalue())
    assert response["success"] is False
    assert response["errorCode"] == "package_update_failed"
    assert "data" not in response
    assert "private detail" not in stdout.getvalue()


def test_rpc_update_collection_replays_same_command_correlation() -> None:
    class Session:
        package_product_binding_id = "owner:test"
        package_product_lifecycle_mode = "enforced"

        def __init__(self) -> None:
            self.operation_ids: list[str] = []

        async def execute_package_lifecycle_collection(
            self,
            action: str,
            *,
            entrypoint: str,
            operation_id: str,
            scope: str,
        ) -> list[dict[str, object]]:
            assert (action, entrypoint, scope) == ("update", "rpc", "global")
            self.operation_ids.append(operation_id)
            source = f"sha256:{'1' * 64}"
            child_id = sha256(f"{operation_id}\0{source}".encode()).hexdigest()
            return [_product_record(child_id, action="update")]

    session = Session()
    stdout = StringIO()
    commands = RpcPackageCommands(
        runtime=object(),
        get_session=lambda: session,
        output=RpcOutput(stdout),
    )
    handler = dict(commands.bindings())["update_packages"]

    asyncio.run(handler("request-1", {"scope": "global"}))
    asyncio.run(handler("request-1", {"scope": "global"}))

    assert len(session.operation_ids) == 2
    assert session.operation_ids[0] == session.operation_ids[1]
    assert len(session.operation_ids[0]) == 64
