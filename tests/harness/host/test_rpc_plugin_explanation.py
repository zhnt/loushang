from __future__ import annotations

import json
from io import StringIO

from loushang.harness.host.rpc.commands.plugin_explanation import (
    RpcPluginExplanationCommands,
)
from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.plugin_management.operation_explanation import (
    PluginOperationExplanationProjector,
    PluginOperationExplanationRequestV1,
)


def _unknown_result(request: PluginOperationExplanationRequestV1):
    class PackageOperations:
        def read_operation(self, _operation_id: str):
            return None

    class ManagementCommands:
        def operation(self, _operation_id: str, *, correlation_id: str):
            return None

    return PluginOperationExplanationProjector(
        package_operations=PackageOperations(),
        management_commands=ManagementCommands(),
        clock_ns=lambda: 7,
    ).explain_operation(
        request.operation_id, correlation_id=request.correlation_id
    )


def test_rpc_plugin_explanation_projects_typed_partial_result() -> None:
    stdout = StringIO()
    observed: list[tuple[str, PluginOperationExplanationRequestV1]] = []

    class Query:
        def explain_plugin_operation(
            self, request: PluginOperationExplanationRequestV1
        ):
            observed.append(("/workspace", request))
            return _unknown_result(request)

    commands = RpcPluginExplanationCommands(
        get_cwd=lambda: "/workspace",
        bind_query=lambda _cwd: Query(),
        output=RpcOutput(stdout),
    )
    assert [name for name, _handler in commands.bindings()] == [
        "explain_plugin_operation"
    ]
    commands.explain_plugin_operation("rpc-1", {
        "productId": "coding", "scopeId": "workspace:test",
        "operationId": "package:absent",
    })
    [response] = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert response["success"] is True
    assert response["data"]["correlationId"] == "rpc-1"
    assert response["data"]["joinStatus"] == "unknown"
    assert response["data"]["snapshotStatus"] == "partial_evidence"
    assert observed[0][1].operation_id == "package:absent"


def test_rpc_plugin_explanation_rejects_invalid_and_redacts_owner_error() -> None:
    stdout = StringIO()

    class UnsafeQuery:
        def explain_plugin_operation(
            self, _request: PluginOperationExplanationRequestV1
        ) -> None:
            raise OSError("/private/owner/secret")

    commands = RpcPluginExplanationCommands(
        get_cwd=lambda: "/workspace",
        bind_query=lambda _cwd: UnsafeQuery(),  # type: ignore[arg-type]
        output=RpcOutput(stdout),
    )
    commands.explain_plugin_operation("rpc-1", {"productId": "coding"})
    commands.explain_plugin_operation("rpc-2", {
        "productId": "coding", "scopeId": "workspace:test",
        "operationId": "package:absent",
    })
    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [item["errorCode"] for item in responses] == [
        "invalid_request", "plugin_explanation_unavailable"
    ]
    assert "/private" not in stdout.getvalue()
