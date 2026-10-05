"""Optional Product-scoped Package repair command for the JSONL RPC host."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Protocol, cast

from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.host.rpc.routing import LegacyRpcHandler

_COMMAND = "repair_plugin_package_v1"
_SAFE_CODE = re.compile(r"[a-z][a-z0-9_]{1,127}\Z")
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_ACTIONS = frozenset(
    {
        "repair-handoff",
        "inspect-staging",
        "inspect-published",
        "repair-staging",
        "repair-published",
        "repair-pinned",
        "repair-retryable",
        "repair-unstarted",
        "repair-acquired",
        "repair-resolving",
        "repair-verified",
    }
)


class PackageRepairRpcResultPort(Protocol):
    @property
    def operation_id(self) -> str: ...

    @property
    def phase(self) -> str: ...

    @property
    def disposition(self) -> str | None: ...

    @property
    def decision_id(self) -> str | None: ...

    @property
    def failure_code(self) -> str | None: ...

    @property
    def checkpoint_id(self) -> str | None: ...

    @property
    def missing_node_ids(self) -> tuple[str, ...]: ...

    @property
    def staged_node_count(self) -> int | None: ...


class PackageRepairRpcClientPort(Protocol):
    @property
    def product_id(self) -> str: ...

    @property
    def scope_id(self) -> str: ...

    async def perform(
        self, action: str, operation_id: str
    ) -> PackageRepairRpcResultPort: ...


class RpcPackageRepairCommands:
    """Expose explicit A2 actions only when a Product supplies the client."""

    def __init__(
        self,
        *,
        get_cwd: Callable[[], str],
        bind_client: Callable[[str], PackageRepairRpcClientPort],
        output: RpcOutput,
    ) -> None:
        self._get_cwd = get_cwd
        self._bind_client = bind_client
        self._output = output

    def bindings(self) -> tuple[tuple[str, LegacyRpcHandler], ...]:
        return ((_COMMAND, self.repair_plugin_package),)

    async def repair_plugin_package(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        correlation = _request_string(payload.get("correlationId", command_id))
        product_id = _request_string(payload.get("productId"))
        scope_id = _request_string(payload.get("scopeId"))
        operation_id = _request_string(payload.get("operationId"))
        action = payload.get("action")
        if (
            correlation is None
            or product_id is None
            or scope_id is None
            or operation_id is None
            or not isinstance(action, str)
            or action not in _ACTIONS
        ):
            self._error(command_id, "invalid_request")
            return
        try:
            cwd = self._get_cwd()
            if not isinstance(cwd, str) or not cwd:
                raise ValueError("Package repair has no current workspace")
            client = self._bind_client(cwd)
            if client.product_id != product_id or client.scope_id != scope_id:
                self._error(command_id, "package_repair_scope_mismatch")
                return
            result = await client.perform(cast(str, action), operation_id)
            document = _safe_result(
                result, action=cast(str, action), operation_id=operation_id
            )
        except Exception as exc:
            code = getattr(exc, "code", None)
            if not isinstance(code, str) or _SAFE_CODE.fullmatch(code) is None:
                code = "package_repair_unavailable"
            self._error(command_id, code)
            return
        self._output.success(
            command=_COMMAND,
            request_id=command_id,
            data={"correlationId": correlation, **document},
        )

    def _error(self, command_id: str | None, code: str) -> None:
        self._output.error(
            command=_COMMAND, request_id=command_id, error=code, code=code
        )


def _request_string(value: object) -> str | None:
    return (
        value if isinstance(value, str) and value and value == value.strip() else None
    )


def _safe_result(
    result: PackageRepairRpcResultPort, *, action: str, operation_id: str
) -> dict[str, object]:
    if (
        result.operation_id != operation_id
        or not isinstance(result.phase, str)
        or _SAFE_CODE.fullmatch(result.phase) is None
    ):
        raise ValueError("Package repair result changed identity")
    if action in {"inspect-staging", "inspect-published"}:
        if (
            result.phase
            != (
                "transaction_pinned" if action == "inspect-staging" else "set_published"
            )
            or (action == "inspect-published" and result.missing_node_ids != ())
            or not isinstance(result.checkpoint_id, str)
            or _SAFE_ID.fullmatch(result.checkpoint_id) is None
            or type(result.staged_node_count) is not int
            or result.staged_node_count < 0
            or type(result.missing_node_ids) is not tuple
            or any(
                not isinstance(node, str) or _SAFE_ID.fullmatch(node) is None
                for node in result.missing_node_ids
            )
            or result.disposition is not None
        ):
            raise ValueError("Package repair inspection result is invalid")
        return {
            "operationId": operation_id,
            "phase": result.phase,
            "checkpointId": result.checkpoint_id,
            "missingNodeIds": list(result.missing_node_ids),
            "stagedNodeCount": result.staged_node_count,
        }
    if action == "repair-handoff":
        if (
            result.phase != "committed"
            or result.decision_id is not None
            or result.staged_node_count is not None
            or result.disposition not in {"committed", "aborted"}
            or (result.disposition == "committed" and result.failure_code is not None)
            or (
                result.disposition == "aborted"
                and result.failure_code != "package_handoff_aborted"
            )
        ):
            raise ValueError("Exact Package handoff result is invalid")
        return {
            "operationId": operation_id,
            "phase": result.phase,
            "decisionId": None,
            "disposition": result.disposition,
            "failureCode": result.failure_code,
        }
    if (
        result.staged_node_count is not None
        or not isinstance(result.disposition, str)
        or _SAFE_CODE.fullmatch(result.disposition) is None
        or not isinstance(result.decision_id, str)
        or _SAFE_ID.fullmatch(result.decision_id) is None
        or (
            result.failure_code is not None
            and (
                not isinstance(result.failure_code, str)
                or _SAFE_CODE.fullmatch(result.failure_code) is None
            )
        )
    ):
        raise ValueError("Package repair mutation result is invalid")
    return {
        "operationId": operation_id,
        "phase": result.phase,
        "decisionId": result.decision_id,
        "disposition": result.disposition,
        "failureCode": result.failure_code,
    }


__all__ = [
    "PackageRepairRpcClientPort",
    "PackageRepairRpcResultPort",
    "RpcPackageRepairCommands",
]
