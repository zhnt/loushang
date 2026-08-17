"""Minimal stdio LSP server used by the real Process Hosting integration test."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path


def _read_message() -> dict[str, object] | None:
    headers: dict[str, str] = {}
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return None
        if line in {b"\n", b"\r\n"}:
            break
        name, separator, value = line.decode("ascii").partition(":")
        if not separator:
            raise RuntimeError("malformed LSP header")
        headers[name.strip().lower()] = value.strip()
    content_length = int(headers["content-length"])
    payload = sys.stdin.buffer.read(content_length)
    if len(payload) != content_length:
        raise RuntimeError("LSP request ended mid-frame")
    message = json.loads(payload)
    if not isinstance(message, dict):
        raise RuntimeError("LSP message must be an object")
    return message


def _write_message(message: Mapping[str, object]) -> None:
    body = json.dumps(
        dict(message),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii"))
    sys.stdout.buffer.write(body)
    sys.stdout.buffer.flush()


def _record_method(method: str) -> None:
    log_path = os.environ.get("LOUSHANG_FAKE_LSP_LOG")
    if log_path is None:
        return
    with Path(log_path).open("a", encoding="utf-8") as stream:
        stream.write(f"{method}\n")


def _definition_result(message: Mapping[str, object]) -> dict[str, object]:
    params = message.get("params", {})
    text_document = (
        params.get("textDocument", {}) if isinstance(params, Mapping) else {}
    )
    uri = text_document.get("uri") if isinstance(text_document, Mapping) else None
    if not isinstance(uri, str):
        raise RuntimeError("definition request is missing a document URI")
    return {
        "uri": uri,
        "range": {
            "start": {"line": 0, "character": 0},
            "end": {"line": 0, "character": 6},
        },
    }


def _outline_result() -> list[dict[str, object]]:
    return [
        {
            "name": "target",
            "kind": 13,
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 10},
            },
            "selectionRange": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 6},
            },
        }
    ]


def main() -> int:
    while True:
        message = _read_message()
        if message is None:
            return 0
        method = message.get("method")
        if isinstance(method, str):
            _record_method(method)

        request_id = message.get("id")
        if method == "initialize":
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "capabilities": {
                            "positionEncoding": "utf-16",
                            "definitionProvider": True,
                            "referencesProvider": True,
                            "hoverProvider": True,
                            "implementationProvider": True,
                            "documentSymbolProvider": True,
                            "textDocumentSync": 2,
                        }
                    },
                }
            )
        elif method == "textDocument/definition":
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": _definition_result(message),
                }
            )
        elif method == "textDocument/references":
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": [_definition_result(message)],
                }
            )
        elif method == "textDocument/implementation":
            location = _definition_result(message)
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "targetUri": location["uri"],
                        "targetRange": location["range"],
                        "targetSelectionRange": location["range"],
                    },
                }
            )
        elif method == "textDocument/hover":
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "contents": {
                            "kind": "markdown",
                            "value": "`target: int`",
                        }
                    },
                }
            )
        elif method == "textDocument/documentSymbol":
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": _outline_result(),
                }
            )
        elif method == "shutdown":
            _write_message({"jsonrpc": "2.0", "id": request_id, "result": None})
        elif method == "exit":
            return 0
        elif request_id is not None:
            _write_message(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": "Method not found"},
                }
            )


if __name__ == "__main__":
    raise SystemExit(main())
