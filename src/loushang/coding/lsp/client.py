"""Minimal, bounded JSON-RPC/LSP client over an injected process handle."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from contextlib import suppress
from types import MappingProxyType

from loushang.coding.lsp.model import LspProtocolError
from loushang.coding.lsp.ports import ProcessHandle
from loushang.harness.workspace.process.json_rpc import (
    ContentLengthJsonRpcProcessTransport,
)

_MAX_HEADER_BYTES = 16 * 1024
_MAX_MESSAGE_BYTES = 4 * 1024 * 1024
_MAX_PENDING_REQUESTS = 128
_MAX_CONFIGURATION_ITEMS = 64
_CONTENT_MODIFIED_ERROR_CODE = -32801
_MAX_CONTENT_MODIFIED_RETRIES = 2
DiagnosticPublicationHandler = Callable[[Mapping[str, object]], bool]
ConnectionClosedHandler = Callable[[], None]


class _LspResponseError(LspProtocolError):
    def __init__(self, error: object) -> None:
        super().__init__(f"LSP response error: {error!r}")
        self.code = error.get("code") if isinstance(error, Mapping) else None


class LspClient(ContentLengthJsonRpcProcessTransport):
    """Own exactly one reader, one serialized writer, and one LSP connection."""

    _protocol_label = "LSP"
    _process_label = "language server"
    _reader_task_name = "coding-lsp-reader"
    _process_exit_task_name = "coding-lsp-process-exit"
    _max_header_bytes = _MAX_HEADER_BYTES
    _max_message_bytes = _MAX_MESSAGE_BYTES
    _max_pending_requests = _MAX_PENDING_REQUESTS
    _cancel_request_method = "$/cancelRequest"
    _error_type = LspProtocolError
    _response_error_type = _LspResponseError

    @staticmethod
    def _is_transient_response_error(error: BaseException) -> bool:
        return isinstance(error, _LspResponseError) and (
            not error.code != _CONTENT_MODIFIED_ERROR_CODE
        )

    def __init__(
        self,
        handle: ProcessHandle,
        *,
        request_timeout_seconds: float,
        shutdown_timeout_seconds: float,
        settings: Mapping[str, object] | None = None,
        on_publish_diagnostics: DiagnosticPublicationHandler | None = None,
        on_close: ConnectionClosedHandler | None = None,
    ) -> None:
        self._initialize_process_binding(
            handle,
            request_timeout_seconds=request_timeout_seconds,
            shutdown_timeout_seconds=shutdown_timeout_seconds,
        )
        self._settings = dict(settings or {})
        self._on_publish_diagnostics = on_publish_diagnostics
        self._initialize_transport_state(on_close=on_close)
        self._initialized = False
        self._initialize_connection_state()
        self._position_encoding = "utf-16"
        self._server_capabilities: Mapping[str, object] = MappingProxyType({})
        self._accepted_diagnostic_publications = 0
        self._discarded_diagnostic_publications = 0
        self._initialize_request_metrics()

    @property
    def position_encoding(self) -> str:
        return self._position_encoding

    @property
    def server_capabilities(self) -> Mapping[str, object]:
        return self._server_capabilities

    @property
    def discarded_diagnostic_publications(self) -> int:
        return self._discarded_diagnostic_publications

    @property
    def accepted_diagnostic_publications(self) -> int:
        return self._accepted_diagnostic_publications

    async def initialize(
        self,
        *,
        root_uri: str,
        initialization_options: Mapping[str, object],
        timeout_seconds: float,
    ) -> None:
        async with self._lifecycle_lock:
            if self._initialized:
                return
            if self.is_closed:
                raise LspProtocolError("cannot initialize a closed LSP connection")
            self._start_reader()
            result = await self.request(
                "initialize",
                {
                    "processId": None,
                    "clientInfo": {"name": "loushang", "version": "0.1"},
                    "rootUri": root_uri,
                    "workspaceFolders": [{"uri": root_uri, "name": "workspace"}],
                    "capabilities": {
                        "general": {"positionEncodings": ["utf-16"]},
                        "textDocument": {
                            "synchronization": {
                                "dynamicRegistration": False,
                                "didSave": False,
                            },
                            "definition": {"dynamicRegistration": False},
                            "references": {"dynamicRegistration": False},
                            "hover": {
                                "dynamicRegistration": False,
                                "contentFormat": ["markdown", "plaintext"],
                            },
                            "implementation": {"dynamicRegistration": False},
                            "documentSymbol": {
                                "dynamicRegistration": False,
                                "hierarchicalDocumentSymbolSupport": True,
                            },
                            "publishDiagnostics": {
                                "relatedInformation": False,
                                "tagSupport": {"valueSet": [1, 2]},
                                "versionSupport": True,
                            },
                        },
                        "workspace": {"configuration": True, "applyEdit": False},
                    },
                    "initializationOptions": dict(initialization_options),
                },
                timeout_seconds=timeout_seconds,
            )
            if not isinstance(result, Mapping):
                raise LspProtocolError("initialize response must be an object")
            capabilities = result.get("capabilities", {})
            if not isinstance(capabilities, Mapping):
                raise LspProtocolError("initialize capabilities must be an object")
            encoding = capabilities.get("positionEncoding", "utf-16")
            if encoding != "utf-16":
                raise LspProtocolError(
                    f"unsupported LSP position encoding: {encoding!r}"
                )
            self._position_encoding = encoding
            self._server_capabilities = MappingProxyType(dict(capabilities))
            await self.notify("initialized", {})
            self._initialized = True

    async def request(
        self,
        method: str,
        params: Mapping[str, object],
        *,
        timeout_seconds: float | None = None,
    ) -> object:
        for attempt in range(_MAX_CONTENT_MODIFIED_RETRIES + 1):
            try:
                return await self._request(
                    method, params, timeout_seconds=timeout_seconds, allow_closing=False
                )
            except _LspResponseError as exc:
                if (
                    exc.code != _CONTENT_MODIFIED_ERROR_CODE
                    or attempt >= _MAX_CONTENT_MODIFIED_RETRIES
                ):
                    self._last_error = "request_failed"
                    raise
                await asyncio.sleep(0)
        raise AssertionError("bounded LSP response retry loop did not return")

    async def _handle_server_request(
        self, message: Mapping[str, object], method: str
    ) -> None:
        request_id = message.get("id")
        response: dict[str, object] = {"jsonrpc": "2.0", "id": request_id}
        if method == "workspace/configuration":
            params = message.get("params", {})
            items = params.get("items", []) if isinstance(params, Mapping) else []
            count = (
                min(len(items), _MAX_CONFIGURATION_ITEMS)
                if isinstance(items, list)
                else 0
            )
            response["result"] = [dict(self._settings) for _ in range(count)]
        elif method == "workspace/applyEdit":
            response["result"] = {"applied": False, "failureReason": "unsupported"}
        elif method == "window/showMessageRequest":
            response["result"] = None
        else:
            response["error"] = {"code": -32601, "message": "Method not found"}
        await self._write_message(response)

    async def _shutdown_protocol(self) -> None:
        if self._initialized and (not self.is_closed):
            with suppress(LspProtocolError):
                await self._request(
                    "shutdown",
                    {},
                    timeout_seconds=self._shutdown_timeout_seconds,
                    allow_closing=True,
                )
            if not self.is_closed:
                with suppress(LspProtocolError):
                    await self._notify("exit", {}, allow_closing=True)
                with suppress(LspProtocolError):
                    await self._wait_for_exit()

    async def _handle_method(self, message: Mapping[str, object], method: str) -> None:
        if "id" in message:
            await self._handle_server_request(message, method)
        elif method == "textDocument/publishDiagnostics":
            accepted = False
            params = message.get("params")
            if isinstance(params, Mapping) and self._on_publish_diagnostics is not None:
                try:
                    accepted = self._on_publish_diagnostics(params) is True
                except Exception:
                    accepted = False
            if not accepted:
                self._discarded_diagnostic_publications += 1
            else:
                self._accepted_diagnostic_publications += 1
        return


__all__ = ["ConnectionClosedHandler", "DiagnosticPublicationHandler", "LspClient"]
