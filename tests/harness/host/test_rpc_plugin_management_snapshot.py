from __future__ import annotations

import json
from io import StringIO

from loushang.harness.host.rpc.commands.plugin_management_snapshot import (
    RpcPluginManagementSnapshotCommands,
)
from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.plugin_management.application import (
    PluginManagementOwnerRevisionsV1,
    PluginManagementProjectionV1,
    PluginManagementQueryV1,
)


def _projection(query: PluginManagementQueryV1) -> PluginManagementProjectionV1:
    return PluginManagementProjectionV1(
        correlation_id=query.correlation_id,
        owner_revisions=PluginManagementOwnerRevisionsV1(
            desired_state=7,
            operations=3,
            enablement_migration=None,
            source=None,
            instances=None,
            packages=None,
            retirement=None,
            unsupported_dimensions=(),
        ),
        installations=(),
        skew=(),
    )


def test_rpc_management_snapshot_uses_current_product_scope_and_typed_result() -> None:
    stdout = StringIO()
    observed: list[tuple[str, PluginManagementQueryV1]] = []

    class Query:
        product_id = "coding"
        installation_scope = "workspace"
        scope_id = "workspace:test"

        def snapshot(
            self, query: PluginManagementQueryV1
        ) -> PluginManagementProjectionV1:
            observed.append(("/workspace", query))
            return _projection(query)

    commands = RpcPluginManagementSnapshotCommands(
        get_cwd=lambda: "/workspace",
        bind_query=lambda _cwd: Query(),
        output=RpcOutput(stdout),
    )
    assert [name for name, _ in commands.bindings()] == [
        "plugin_management_snapshot_v1"
    ]
    commands.snapshot(
        "rpc-1",
        {
            "productId": "coding",
            "scopeId": "workspace:test",
            "pluginIds": ["coding.arch.default", "coding.base"],
        },
    )

    [response] = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert response["success"] is True
    assert response["data"]["correlationId"] == "rpc-1"
    assert response["data"]["ownerRevisions"]["desiredState"] == 7
    assert observed[0][0] == "/workspace"
    assert observed[0][1].plugin_ids == ("coding.arch.default", "coding.base")


def test_rpc_management_snapshot_refuses_scope_and_redacts_owner_failure() -> None:
    stdout = StringIO()

    class Query:
        product_id = "coding"
        installation_scope = "workspace"
        scope_id = "workspace:test"

        def snapshot(self, _query: PluginManagementQueryV1) -> None:
            raise OSError("/private/secret-state")

    commands = RpcPluginManagementSnapshotCommands(
        get_cwd=lambda: "/workspace",
        bind_query=lambda _cwd: Query(),
        output=RpcOutput(stdout),
    )
    commands.snapshot("rpc-1", {"productId": "coding"})
    commands.snapshot(
        "rpc-2",
        {
            "productId": "coding",
            "scopeId": "workspace:foreign",
        },
    )
    commands.snapshot(
        "rpc-3",
        {
            "productId": "coding",
            "scopeId": "workspace:test",
        },
    )
    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [item["errorCode"] for item in responses] == [
        "invalid_request",
        "plugin_management_scope_mismatch",
        "plugin_management_unavailable",
    ]
    assert "/private" not in stdout.getvalue()
