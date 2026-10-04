"""Optional Product-scoped Desired State commands for the JSONL RPC host."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Protocol, cast

from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.host.rpc.routing import LegacyRpcHandler
from loushang.harness.plugin_management.application import (
    PluginManagementApplicationResultV1,
)
from loushang.harness.plugin_management.desired_command import (
    PluginDesiredActionV1,
    PluginDesiredCommandRequestV1,
    PluginDesiredRepairResultV1,
)
from loushang.harness.plugin_management.operations import (
    PluginManagementOperationEventV1,
)

_SUBMIT = "submit_plugin_desired_v1"
_OPERATION = "plugin_desired_operation_v1"
_REPAIR = "repair_plugin_desired_v1"


class PluginDesiredRpcClientPort(Protocol):
    @property
    def product_id(self) -> str: ...

    @property
    def installation_scope(self) -> Literal["process", "tenant", "workspace"]: ...

    @property
    def scope_id(self) -> str: ...

    def submit_desired(
        self, request: PluginDesiredCommandRequestV1
    ) -> PluginManagementApplicationResultV1: ...

    def operation(
        self, operation_id: str, *, correlation_id: str
    ) -> PluginManagementApplicationResultV1 | None: ...

    def repair(
        self, operation_id: str, *, correlation_id: str
    ) -> PluginDesiredRepairResultV1: ...


class _ScopeMismatch(ValueError):
    pass


class RpcPluginDesiredCommands:
    """Only a Product supplied client can enable these management routes."""

    def __init__(
        self,
        *,
        get_cwd: Callable[[], str],
        bind_client: Callable[[str], PluginDesiredRpcClientPort],
        output: RpcOutput,
    ) -> None:
        self._get_cwd = get_cwd
        self._bind_client = bind_client
        self._output = output

    def bindings(self) -> tuple[tuple[str, LegacyRpcHandler], ...]:
        return (
            (_SUBMIT, self.submit_plugin_desired),
            (_OPERATION, self.plugin_desired_operation),
            (_REPAIR, self.repair_plugin_desired),
        )

    def submit_plugin_desired(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        correlation = _request_string(payload.get("correlationId", command_id))
        product_id = _request_string(payload.get("productId"))
        scope_id = _request_string(payload.get("scopeId"))
        plugin_id = _request_string(payload.get("pluginId"))
        operation_id = _request_string(payload.get("operationId"))
        action = payload.get("action")
        revision = payload.get("expectedInventoryRevision")
        if (
            correlation is None
            or product_id is None
            or scope_id is None
            or plugin_id is None
            or operation_id is None
            or action not in ("enable", "disable", "remove")
            or type(revision) is not int
            or revision < 0
        ):
            self._error(_SUBMIT, command_id, "invalid_request")
            return
        try:
            request = PluginDesiredCommandRequestV1(
                correlation_id=correlation,
                operation_id=operation_id,
                plugin_id=plugin_id,
                action=cast(PluginDesiredActionV1, action),
                expected_inventory_revision=revision,
            )
            client = self._scoped_client(product_id, scope_id)
            result = client.submit_desired(request)
            _validate_result(
                result,
                product_id=product_id,
                installation_scope=client.installation_scope,
                scope_id=scope_id,
                correlation_id=correlation,
                operation_id=operation_id,
                plugin_id=plugin_id,
                action=request.action,
                expected_inventory_revision=revision,
            )
        except _ScopeMismatch:
            self._error(_SUBMIT, command_id, "plugin_management_scope_mismatch")
            return
        except Exception:
            self._error(_SUBMIT, command_id, "plugin_management_unavailable")
            return
        self._output.success(
            command=_SUBMIT, request_id=command_id, data=result.to_dict()
        )

    def plugin_desired_operation(
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
            self._error(_OPERATION, command_id, "invalid_request")
            return
        try:
            client = self._scoped_client(product_id, scope_id)
            result = client.operation(operation_id, correlation_id=correlation)
            if result is not None:
                _validate_result(
                    result,
                    product_id=product_id,
                    installation_scope=client.installation_scope,
                    scope_id=scope_id,
                    correlation_id=correlation,
                    operation_id=operation_id,
                )
                document: dict[str, object] = result.to_dict()
            else:
                document = {"correlationId": correlation, "operation": None}
        except _ScopeMismatch:
            self._error(_OPERATION, command_id, "plugin_management_scope_mismatch")
            return
        except Exception:
            self._error(_OPERATION, command_id, "plugin_management_unavailable")
            return
        self._output.success(
            command=_OPERATION, request_id=command_id, data=document
        )

    def repair_plugin_desired(
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
            self._error(_REPAIR, command_id, "invalid_request")
            return
        try:
            client = self._scoped_client(product_id, scope_id)
            result = client.repair(operation_id, correlation_id=correlation)
            if (
                not isinstance(result, PluginDesiredRepairResultV1)
                or result.correlation_id != correlation
            ):
                raise ValueError("Plugin repair result is incompatible")
            if result.result is not None:
                _validate_result(
                    result.result,
                    product_id=product_id,
                    installation_scope=client.installation_scope,
                    scope_id=scope_id,
                    correlation_id=correlation,
                    operation_id=operation_id,
                )
        except _ScopeMismatch:
            self._error(_REPAIR, command_id, "plugin_management_scope_mismatch")
            return
        except Exception:
            self._error(_REPAIR, command_id, "plugin_management_unavailable")
            return
        self._output.success(
            command=_REPAIR, request_id=command_id, data=result.to_dict()
        )

    def _scoped_client(
        self, product_id: str, scope_id: str
    ) -> PluginDesiredRpcClientPort:
        cwd = self._get_cwd()
        if not isinstance(cwd, str) or not cwd:
            raise ValueError("Plugin management has no current workspace")
        client = self._bind_client(cwd)
        if client.product_id != product_id or client.scope_id != scope_id:
            raise _ScopeMismatch("Plugin management scope changed")
        return client

    def _error(self, command: str, command_id: str | None, code: str) -> None:
        self._output.error(
            command=command,
            request_id=command_id,
            error=code,
            code=code,
        )


def _validate_result(
    result: PluginManagementApplicationResultV1,
    *,
    product_id: str,
    installation_scope: Literal["process", "tenant", "workspace"],
    scope_id: str,
    correlation_id: str,
    operation_id: str,
    plugin_id: str | None = None,
    action: PluginDesiredActionV1 | None = None,
    expected_inventory_revision: int | None = None,
) -> None:
    if (
        not isinstance(result, PluginManagementApplicationResultV1)
        or result.correlation_id != correlation_id
        or not isinstance(result.operation, PluginManagementOperationEventV1)
    ):
        raise ValueError("Plugin management owner result is incompatible")
    command = result.operation.command
    mutation = command.mutation
    key = mutation.installation_key
    if (
        command.action not in {"enable", "disable", "remove"}
        or mutation.package_revision is not None
        or key.product_id != product_id
        or key.installation_scope != installation_scope
        or key.scope_id != scope_id
        or mutation.operation_id != operation_id
        or (plugin_id is not None and key.plugin_id != plugin_id)
        or (action is not None and command.action != action)
        or (
            expected_inventory_revision is not None
            and mutation.expected_inventory_revision != expected_inventory_revision
        )
    ):
        raise ValueError("Plugin management owner result changed identity")


def _request_string(value: object) -> str | None:
    return (
        value
        if isinstance(value, str) and value and value == value.strip()
        else None
    )


__all__ = ["PluginDesiredRpcClientPort", "RpcPluginDesiredCommands"]
