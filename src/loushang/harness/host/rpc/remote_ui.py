"""Remote UI adaptation for headless RPC hosts."""

from __future__ import annotations

from collections.abc import Callable

from loushang.harness.host.remote_ui import RemoteUiContext


class RpcExtensionUIContext(RemoteUiContext):
    """Translate generic remote UI facts into the existing RPC vocabulary."""

    def __init__(self, output: Callable[[object], None]) -> None:
        self._output = output

        def emit(payload: dict[str, object]) -> None:
            if payload.get("type") == "remote_ui_request":
                payload = {**payload, "type": "extension_ui_request"}
            self._output(payload)

        super().__init__(emit)

    def emit_extension_error(self, error: dict[str, object]) -> None:
        self._output(
            {
                "type": "extension_error",
                "extensionPath": str(error.get("extensionPath", "")),
                "event": str(error.get("event", "")),
                "error": str(error.get("error", "")),
            }
        )


__all__ = ["RpcExtensionUIContext"]
