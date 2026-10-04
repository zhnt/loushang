from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from io import StringIO

import pytest

from loushang.harness.host.rpc.commands.package_repair import (
    RpcPackageRepairCommands,
)
from loushang.harness.host.rpc.output import RpcOutput


@dataclass(frozen=True)
class _Result:
    operation_id: str
    phase: str = "committed"
    disposition: str | None = "committed"
    decision_id: str | None = "decision:one"
    failure_code: str | None = None
    checkpoint_id: str | None = None
    missing_node_ids: tuple[str, ...] = ()
    staged_node_count: int | None = None


def test_rpc_package_repair_requires_product_scope_and_exact_result() -> None:
    stdout = StringIO()
    calls: list[tuple[str, str]] = []

    class Client:
        product_id = "coding"
        scope_id = "workspace:test"

        async def perform(self, action: str, operation_id: str) -> _Result:
            calls.append((action, operation_id))
            return _Result(operation_id=operation_id)

    commands = RpcPackageRepairCommands(
        get_cwd=lambda: "/workspace",
        bind_client=lambda _cwd: Client(),
        output=RpcOutput(stdout),
    )
    assert [name for name, _handler in commands.bindings()] == [
        "repair_plugin_package_v1"
    ]
    payload = {
        "productId": "coding",
        "scopeId": "workspace:test",
        "action": "repair-retryable",
        "operationId": "package:one",
    }
    asyncio.run(
        commands.repair_plugin_package(
            "wrong-scope", {**payload, "scopeId": "workspace:other"}
        )
    )
    asyncio.run(
        commands.repair_plugin_package(
            "bad-action", {**payload, "action": ["repair-retryable"]}
        )
    )
    asyncio.run(commands.repair_plugin_package("accepted", payload))
    responses = {
        item["id"]: item
        for item in (json.loads(line) for line in stdout.getvalue().splitlines())
    }
    assert responses["wrong-scope"]["errorCode"] == "package_repair_scope_mismatch"
    assert responses["bad-action"]["errorCode"] == "invalid_request"
    assert responses["accepted"]["data"] == {
        "correlationId": "accepted",
        "operationId": "package:one",
        "phase": "committed",
        "decisionId": "decision:one",
        "disposition": "committed",
        "failureCode": None,
    }
    assert calls == [("repair-retryable", "package:one")]


def test_rpc_package_repair_redacts_product_error_and_spoofed_result() -> None:
    stdout = StringIO()

    class Client:
        product_id = "coding"
        scope_id = "workspace:test"

        async def perform(self, action: str, operation_id: str) -> _Result:
            if action == "repair-retryable":
                raise RuntimeError("private source path")
            return _Result(operation_id="foreign:operation", staged_node_count=2)

    commands = RpcPackageRepairCommands(
        get_cwd=lambda: "/workspace",
        bind_client=lambda _cwd: Client(),
        output=RpcOutput(stdout),
    )
    base = {
        "productId": "coding",
        "scopeId": "workspace:test",
        "operationId": "package:one",
    }
    asyncio.run(
        commands.repair_plugin_package("error", {**base, "action": "repair-retryable"})
    )
    asyncio.run(
        commands.repair_plugin_package("spoofed", {**base, "action": "inspect-staging"})
    )
    responses = [json.loads(line) for line in stdout.getvalue().splitlines()]
    assert [item["errorCode"] for item in responses] == [
        "package_repair_unavailable",
        "package_repair_unavailable",
    ]
    assert "private source path" not in stdout.getvalue()


@pytest.mark.parametrize(
    ("action", "phase", "missing_node_ids"),
    [
        ("inspect-staging", "transaction_pinned", ("node:two",)),
        ("inspect-published", "set_published", ()),
    ],
)
def test_rpc_package_inspection_projects_only_checkpoint_fields(
    action: str, phase: str, missing_node_ids: tuple[str, ...]
) -> None:
    stdout = StringIO()

    class Client:
        product_id = "coding"
        scope_id = "workspace:test"

        async def perform(self, selected_action: str, operation_id: str) -> _Result:
            assert selected_action == action
            return _Result(
                operation_id=operation_id,
                phase=phase,
                disposition=None,
                decision_id=None,
                checkpoint_id="checkpoint:one",
                missing_node_ids=missing_node_ids,
                staged_node_count=1,
            )

    commands = RpcPackageRepairCommands(
        get_cwd=lambda: "/workspace",
        bind_client=lambda _cwd: Client(),
        output=RpcOutput(stdout),
    )
    asyncio.run(
        commands.repair_plugin_package(
            "inspect",
            {
                "productId": "coding",
                "scopeId": "workspace:test",
                "action": action,
                "operationId": "package:one",
            },
        )
    )
    response = json.loads(stdout.getvalue())
    assert response["data"] == {
        "correlationId": "inspect",
        "operationId": "package:one",
        "phase": phase,
        "checkpointId": "checkpoint:one",
        "missingNodeIds": list(missing_node_ids),
        "stagedNodeCount": 1,
    }


def test_rpc_package_repair_surfaces_only_safe_product_code() -> None:
    stdout = StringIO()

    class ProductRefusal(RuntimeError):
        code = "package_source_digest_mismatch"

    class Client:
        product_id = "coding"
        scope_id = "workspace:test"

        async def perform(self, action: str, operation_id: str) -> _Result:
            raise ProductRefusal("private Source path")

    commands = RpcPackageRepairCommands(
        get_cwd=lambda: "/workspace",
        bind_client=lambda _cwd: Client(),
        output=RpcOutput(stdout),
    )
    asyncio.run(
        commands.repair_plugin_package(
            "repair",
            {
                "productId": "coding",
                "scopeId": "workspace:test",
                "action": "repair-retryable",
                "operationId": "package:one",
            },
        )
    )
    response = json.loads(stdout.getvalue())
    assert response["errorCode"] == "package_source_digest_mismatch"
    assert "private Source path" not in stdout.getvalue()


def test_rpc_package_handoff_rejects_forged_decision() -> None:
    stdout = StringIO()

    class Client:
        product_id = "coding"
        scope_id = "workspace:test"

        async def perform(self, action: str, operation_id: str) -> _Result:
            assert action == "repair-handoff"
            return _Result(operation_id=operation_id, decision_id="decision:forged")

    commands = RpcPackageRepairCommands(
        get_cwd=lambda: "/workspace",
        bind_client=lambda _cwd: Client(),
        output=RpcOutput(stdout),
    )
    asyncio.run(
        commands.repair_plugin_package(
            "handoff",
            {
                "productId": "coding",
                "scopeId": "workspace:test",
                "action": "repair-handoff",
                "operationId": "package:one",
            },
        )
    )
    assert json.loads(stdout.getvalue())["errorCode"] == "package_repair_unavailable"
