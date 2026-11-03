"""Optional read-only Plugin preview command over the shared Product port."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from loushang.harness.host.rpc.output import RpcOutput
from loushang.harness.host.rpc.routing import LegacyRpcHandler
from loushang.harness.plugin_management.current_preview import (
    PluginCurrentPreviewQueryPort,
    PluginCurrentPreviewRequestV1,
    project_plugin_current_preview,
)

_COMMAND = "preview_current_plugins"
_PUBLIC_PRODUCT_CODES = frozenset({
    "plugin_preview_scope_mismatch",
    "plugin_preview_product_not_fenced",
    "plugin_preview_composition_invalid",
    "plugin_preview_owner_unavailable",
    "plugin_preview_settings_unavailable",
    "plugin_preview_platform_unsupported",
})


class RpcPluginPreviewCommands:
    """Bind one optional Product query without borrowing live Session authority."""

    def __init__(
        self,
        *,
        get_cwd: Callable[[], str],
        bind_query: Callable[[str], PluginCurrentPreviewQueryPort],
        output: RpcOutput,
    ) -> None:
        self._get_cwd = get_cwd
        self._bind_query = bind_query
        self._output = output

    def bindings(self) -> tuple[tuple[str, LegacyRpcHandler], ...]:
        return ((_COMMAND, self.preview_current_plugins),)

    def preview_current_plugins(
        self, command_id: str | None, payload: dict[str, Any]
    ) -> None:
        correlation = _request_string(payload.get("correlationId", command_id))
        product_id = _request_string(payload.get("productId"))
        scope_id = _request_string(payload.get("scopeId"))
        composition_set_id = _request_string(payload.get("compositionSetId"))
        if (
            correlation is None
            or product_id is None
            or scope_id is None
            or composition_set_id is None
        ):
            self._output.error(
                command=_COMMAND,
                request_id=command_id,
                error="plugin_preview_invalid_request",
                code="invalid_request",
            )
            return
        try:
            cwd = self._get_cwd()
            if not isinstance(cwd, str) or not cwd:
                raise ValueError("Plugin preview has no current workspace")
            request = PluginCurrentPreviewRequestV1(
                correlation_id=correlation,
                product_id=product_id,
                scope_id=scope_id,
                composition_set_id=composition_set_id,
            )
            document = project_plugin_current_preview(
                self._bind_query(cwd), request
            )
        except Exception as error:
            code = getattr(error, "code", None)
            if code not in _PUBLIC_PRODUCT_CODES:
                code = "plugin_preview_unavailable"
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


__all__ = ["RpcPluginPreviewCommands"]
