"""Optional Product-scoped Plugin management snapshot for the JSONL RPC host."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Protocol

from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.host.rpc.routing import LegacyRpcHandler
from loushang.harness.plugin_management.application import (
    PluginManagementProjectionV1,
    PluginManagementQueryV1,
)

_COMMAND = "plugin_management_snapshot_v1"


class PluginManagementSnapshotRpcQueryPort(Protocol):
    @property
    def product_id(self) -> str: ...

    @property
    def installation_scope(self) -> Literal["process", "tenant", "workspace"]: ...

    @property
    def scope_id(self) -> str: ...

    def snapshot(
        self, query: PluginManagementQueryV1
    ) -> PluginManagementProjectionV1: ...


class _ScopeMismatch(ValueError):
    pass


class RpcPluginManagementSnapshotCommands:
    """Publish only a typed read from the Product owner for the current Session."""

    def __init__(
        self,
        *,
        get_cwd: Callable[[], str],
        bind_query: Callable[[str], PluginManagementSnapshotRpcQueryPort],
        output: RpcOutput,
    ) -> None:
        self._get_cwd = get_cwd
        self._bind_query = bind_query
        self._output = output

    def bindings(self) -> tuple[tuple[str, LegacyRpcHandler], ...]:
        return ((_COMMAND, self.snapshot),)

    def snapshot(self, command_id: str | None, payload: dict[str, Any]) -> None:
        correlation = _request_string(payload.get("correlationId", command_id))
        product_id = _request_string(payload.get("productId"))
        scope_id = _request_string(payload.get("scopeId"))
        plugin_ids = _request_plugin_ids(payload.get("pluginIds", []))
        if (
            correlation is None
            or product_id is None
            or scope_id is None
            or plugin_ids is None
        ):
            self._error(command_id, "invalid_request")
            return
        try:
            cwd = self._get_cwd()
            if not isinstance(cwd, str) or not cwd:
                raise ValueError("Plugin management has no current workspace")
            client = self._bind_query(cwd)
            if client.product_id != product_id or client.scope_id != scope_id:
                raise _ScopeMismatch("Plugin management scope changed")
            query = PluginManagementQueryV1(
                correlation_id=correlation,
                product_id=product_id,
                installation_scope=client.installation_scope,
                scope_id=scope_id,
                plugin_ids=plugin_ids,
            )
            result = client.snapshot(query)
            if (
                not isinstance(result, PluginManagementProjectionV1)
                or result.correlation_id != correlation
                or any(
                    not query.matches(item.installation_key)
                    for item in result.installations
                )
                or any(
                    item.installation_key is not None
                    and not query.matches(item.installation_key)
                    for item in result.skew
                )
            ):
                raise ValueError("Plugin management result changed scope")
        except _ScopeMismatch:
            self._error(command_id, "plugin_management_scope_mismatch")
            return
        except Exception:
            self._error(command_id, "plugin_management_unavailable")
            return
        self._output.success(
            command=_COMMAND, request_id=command_id, data=result.to_dict()
        )

    def _error(self, command_id: str | None, code: str) -> None:
        self._output.error(
            command=_COMMAND, request_id=command_id, error=code, code=code
        )


def _request_string(value: object) -> str | None:
    return (
        value
        if isinstance(value, str)
        and 0 < len(value) <= 256
        and value.isascii()
        and value.isprintable()
        and value == value.strip()
        else None
    )


def _request_plugin_ids(value: object) -> tuple[str, ...] | None:
    if type(value) is not list or len(value) > 64:
        return None
    ids = tuple(value)
    if any(_request_string(item) is None for item in ids):
        return None
    if ids != tuple(sorted(set(ids))):
        return None
    return ids


__all__ = [
    "PluginManagementSnapshotRpcQueryPort",
    "RpcPluginManagementSnapshotCommands",
]
