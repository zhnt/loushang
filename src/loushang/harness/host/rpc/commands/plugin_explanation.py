"""Optional scoped Plugin operation explanation RPC command."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.host.rpc.routing import LegacyRpcHandler
from loushang.harness.plugin_management.operation_explanation import (
    PluginOperationExplanationQueryPort,
    PluginOperationExplanationRequestV1,
    project_plugin_operation_explanation,
)

_COMMAND = "explain_plugin_operation"
_PUBLIC_PRODUCT_CODES = frozenset({
    "plugin_explanation_scope_mismatch",
    "plugin_explanation_product_not_fenced",
    "plugin_explanation_platform_unsupported",
})


class RpcPluginExplanationCommands:
    def __init__(
        self,
        *,
        get_cwd: Callable[[], str],
        bind_query: Callable[[str], PluginOperationExplanationQueryPort],
        output: RpcOutput,
    ) -> None:
        self._get_cwd = get_cwd
        self._bind_query = bind_query
        self._output = output

    def bindings(self) -> tuple[tuple[str, LegacyRpcHandler], ...]:
        return ((_COMMAND, self.explain_plugin_operation),)

    def explain_plugin_operation(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        correlation = _request_string(payload.get("correlationId", command_id))
        product_id = _request_string(payload.get("productId"))
        scope_id = _request_string(payload.get("scopeId"))
        operation_id = _request_string(payload.get("operationId"))
        if (
            correlation is None
            or product_id is None
            or scope_id is None
            or operation_id is None
        ):
            self._output.error(
                command=_COMMAND,
                request_id=command_id,
                error="plugin_explanation_invalid_request",
                code="invalid_request",
            )
            return
        try:
            cwd = self._get_cwd()
            if not isinstance(cwd, str) or not cwd:
                raise ValueError("Plugin explanation has no current workspace")
            request = PluginOperationExplanationRequestV1(
                correlation_id=correlation,
                product_id=product_id,
                scope_id=scope_id,
                operation_id=operation_id,
            )
            document = project_plugin_operation_explanation(
                self._bind_query(cwd), request
            )
        except Exception as error:
            code = getattr(error, "code", None)
            if code not in _PUBLIC_PRODUCT_CODES:
                code = "plugin_explanation_unavailable"
            self._output.error(
                command=_COMMAND,
                request_id=command_id,
                error=code,
                code=code,
            )
            return
        self._output.success(command=_COMMAND, request_id=command_id, data=document)


def _request_string(value: object) -> str | None:
    return (
        value
        if isinstance(value, str) and value and value == value.strip()
        else None
    )


__all__ = ["RpcPluginExplanationCommands"]
