from __future__ import annotations

import json
from dataclasses import replace
from io import StringIO

from loushang.harness.host.rpc.commands.plugin_desired import (
    RpcPluginDesiredCommands,
)
from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.plugin_management.application import (
    PluginManagementApplicationResultV1,
)
from loushang.harness.plugin_management.desired_command import (
    PluginDesiredCommandRequestV1,
    PluginDesiredRepairResultV1,
)
from loushang.harness.plugin_management.operations import (
    PluginManagementCommandV1,
    PluginManagementOperationEventV1,
)
from loushang.harness.plugin_management.records import (
    PluginDesiredStateMutationV1,
    PluginInstallationKeyV1,
    PluginPackageRevisionRefV1,
)


def _result(
    request: PluginDesiredCommandRequestV1,
) -> PluginManagementApplicationResultV1:
    command = PluginManagementCommandV1(
        action=request.action,
        mutation=PluginDesiredStateMutationV1(
            operation_id=request.operation_id,
            idempotency_key=request.operation_id,
            expected_inventory_revision=request.expected_inventory_revision,
            installation_key=PluginInstallationKeyV1(
                product_id="coding", installation_scope="workspace",
                scope_id="workspace:test", plugin_id=request.plugin_id,
            ),
            desired_state="installed_disabled",
            package_revision=None,
            actor_id="coding:rpc",
            policy_revision="test:rpc",
        ),
    )
    return PluginManagementApplicationResultV1(
        correlation_id=request.correlation_id,
        operation=PluginManagementOperationEventV1.accepted(
            journal_revision=1, command=command
        ),
    )


def test_rpc_desired_command_checks_product_scope_and_preserves_cas() -> None:
    stdout = StringIO()
    submitted: list[dict[str, object]] = []
    stored: list[PluginManagementApplicationResultV1] = []

    class ProductClient:
        product_id = "coding"
        installation_scope = "workspace"
        scope_id = "workspace:test"

        def submit_desired(
            self, request: PluginDesiredCommandRequestV1
        ) -> PluginManagementApplicationResultV1:
            submitted.append({
                "plugin_id": request.plugin_id, "action": request.action,
                "expected_inventory_revision": request.expected_inventory_revision,
                "operation_id": request.operation_id,
                "correlation_id": request.correlation_id,
            })
            result = _result(request)
            stored.append(result)
            return result

        def operation(self, operation_id: str, *, correlation_id: str):
            assert stored[0].operation.command.operation_id == operation_id
            return replace(stored[0], correlation_id=correlation_id)

        def repair(self, _operation_id: str, *, correlation_id: str):
            return PluginDesiredRepairResultV1(
                correlation_id=correlation_id,
                disposition="unknown", status_before=None, result=None,
            )

    commands = RpcPluginDesiredCommands(
        get_cwd=lambda: "/workspace",
        bind_client=lambda _cwd: ProductClient(),
        output=RpcOutput(stdout),
    )
    assert [name for name, _handler in commands.bindings()] == [
        "submit_plugin_desired_v1", "plugin_desired_operation_v1",
        "repair_plugin_desired_v1",
    ]
    payload = {
        "productId": "coding", "scopeId": "workspace:test",
        "pluginId": "coding.base", "action": "disable",
        "expectedInventoryRevision": 7, "operationId": "rpc:desired:1",
    }
    commands.submit_plugin_desired("rpc-1", payload)
    commands.submit_plugin_desired("rpc-2", {
        **payload, "scopeId": "workspace:other",
    })
    commands.submit_plugin_desired("rpc-3", {
        **payload, "expectedInventoryRevision": True,
    })
    commands.plugin_desired_operation("rpc-4", {
        "productId": "coding", "scopeId": "workspace:test",
        "operationId": "rpc:desired:1",
    })
    commands.repair_plugin_desired("rpc-5", {
        "productId": "coding", "scopeId": "workspace:test",
        "operationId": "rpc:desired:missing",
    })
    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert responses[0]["success"] is True
    assert responses[0]["data"]["correlationId"] == "rpc-1"
    assert submitted == [{
        "plugin_id": "coding.base", "action": "disable",
        "expected_inventory_revision": 7, "operation_id": "rpc:desired:1",
        "correlation_id": "rpc-1",
    }]
    assert [item["errorCode"] for item in responses[1:3]] == [
        "plugin_management_scope_mismatch", "invalid_request"
    ]
    assert responses[3]["data"]["operation"]["command"]["mutation"][
        "operationId"
    ] == "rpc:desired:1"
    assert responses[4]["data"]["disposition"] == "unknown"


def test_rpc_desired_command_redacts_product_exception() -> None:
    stdout = StringIO()

    class UnsafeClient:
        product_id = "coding"
        installation_scope = "workspace"
        scope_id = "workspace:test"

        def submit_desired(self, _request: PluginDesiredCommandRequestV1) -> None:
            raise OSError("/private/owner/secret")

        def operation(self, _operation_id: str, *, correlation_id: str) -> None:
            raise OSError("/private/owner/secret")

        def repair(self, _operation_id: str, *, correlation_id: str) -> None:
            raise OSError("/private/owner/secret")

    commands = RpcPluginDesiredCommands(
        get_cwd=lambda: "/workspace",
        bind_client=lambda _cwd: UnsafeClient(),
        output=RpcOutput(stdout),
    )
    commands.submit_plugin_desired("rpc-1", {
        "productId": "coding", "scopeId": "workspace:test",
        "pluginId": "coding.base", "action": "disable",
        "expectedInventoryRevision": 7, "operationId": "rpc:desired:1",
    })
    commands.plugin_desired_operation("rpc-2", {
        "productId": "coding", "scopeId": "workspace:test",
        "operationId": "rpc:desired:1",
    })
    commands.repair_plugin_desired("rpc-3", {
        "productId": "coding", "scopeId": "workspace:test",
        "operationId": "rpc:desired:1",
    })
    assert [json.loads(line)["errorCode"] for line in stdout.getvalue().splitlines()] == [
        "plugin_management_unavailable", "plugin_management_unavailable",
        "plugin_management_unavailable",
    ]
    assert "/private" not in stdout.getvalue()


def test_rpc_operation_lookup_refuses_package_source_evidence() -> None:
    stdout = StringIO()
    package = PluginPackageRevisionRefV1(
        plugin_id="reviewpack", plugin_version="1",
        package_content_digest="a" * 64,
        dependency_lock_digest="b" * 64,
        package_source_identity="/private/owner/secret.whl",
    )
    command = PluginManagementCommandV1(
        action="install",
        mutation=PluginDesiredStateMutationV1(
            operation_id="package:secret", idempotency_key="package:secret",
            expected_inventory_revision=1,
            installation_key=PluginInstallationKeyV1(
                product_id="coding", installation_scope="workspace",
                scope_id="workspace:test", plugin_id="reviewpack",
            ),
            desired_state="installed_disabled", package_revision=package,
            actor_id="coding:cli", policy_revision="test:product",
        ),
    )

    class ProductClient:
        product_id = "coding"
        installation_scope = "workspace"
        scope_id = "workspace:test"

        def operation(self, _operation_id: str, *, correlation_id: str):
            return PluginManagementApplicationResultV1(
                correlation_id=correlation_id,
                operation=PluginManagementOperationEventV1.accepted(
                    journal_revision=1, command=command,
                ),
            )

    commands = RpcPluginDesiredCommands(
        get_cwd=lambda: "/workspace",
        bind_client=lambda _cwd: ProductClient(),  # type: ignore[arg-type]
        output=RpcOutput(stdout),
    )
    commands.plugin_desired_operation("rpc-secret", {
        "productId": "coding", "scopeId": "workspace:test",
        "operationId": "package:secret",
    })
    [response] = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert response["errorCode"] == "plugin_management_unavailable"
    assert "/private" not in stdout.getvalue()
