from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from pathlib import Path

import pytest

from loushang.coding.lsp import (
    DOCUMENT_OUTLINE_TOOL_NAME,
    MAX_HOVER_CONTENT_CHARACTERS,
    CodingLspBinding,
    LspCatalog,
    LspClient,
    LspInvalidInputError,
    LspProtocolError,
    LspSelector,
    LspServerDefinition,
    ProcessExit,
    ProcessLaunchRequest,
    ProcessStderrTail,
    create_document_outline_tool_definition,
    create_inspect_symbol_tool_definition,
    product_default_lsp_definitions,
)
from loushang.harness.tools import ToolContext
from loushang.harness.tools.workspace.wrapper import wrap_tool_definition


def _frame(message: Mapping[str, object]) -> bytes:
    body = json.dumps(message, separators=(",", ":")).encode()
    return f"Content-Length: {len(body)}\r\n\r\n".encode() + body


async def _wait_for_method(
    server: FakeLspServer,
    method: str,
    *,
    count: int = 1,
) -> None:
    for _ in range(100):
        if server.methods().count(method) >= count:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"fake server did not receive {method!r}")


class _FrameReader:
    def __init__(self, queue: asyncio.Queue[bytes | None]) -> None:
        self._queue = queue
        self._buffer = bytearray()

    async def read(self) -> dict[str, object] | None:
        while b"\r\n\r\n" not in self._buffer:
            if not await self._read_chunk():
                return None
        raw_header, _, remainder = self._buffer.partition(b"\r\n\r\n")
        self._buffer = bytearray(remainder)
        length = None
        for line in raw_header.split(b"\r\n"):
            name, _, value = line.partition(b":")
            if name.lower() == b"content-length":
                length = int(value.strip())
        assert length is not None
        while len(self._buffer) < length:
            if not await self._read_chunk():
                return None
        body = bytes(self._buffer[:length])
        del self._buffer[:length]
        value = json.loads(body)
        assert isinstance(value, dict)
        return value

    async def _read_chunk(self) -> bool:
        chunk = await self._queue.get()
        if chunk is None:
            return False
        self._buffer.extend(chunk)
        return True


class FakeLspServer:
    def __init__(
        self,
        *,
        definition_result: object,
        references_result: object,
        implementation_result: object,
        hover_result: object,
        outline_result: object,
        initialize_gate: asyncio.Event | None,
        definition_gate: asyncio.Event | None,
        shutdown_gate: asyncio.Event | None,
        position_encoding: str,
        server_capabilities: Mapping[str, object],
        crash_on_definition: bool,
        content_modified_references: int,
        ignore_exit: bool,
    ) -> None:
        self.stdin: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.stdout: asyncio.Queue[bytes | None] = asyncio.Queue()
        self.definition_result = definition_result
        self.references_result = references_result
        self.implementation_result = implementation_result
        self.hover_result = hover_result
        self.outline_result = outline_result
        self.initialize_gate = initialize_gate
        self.definition_gate = definition_gate
        self.shutdown_gate = shutdown_gate
        self.position_encoding = position_encoding
        self.server_capabilities = dict(server_capabilities)
        self.crash_on_definition = crash_on_definition
        self.content_modified_references = content_modified_references
        self.ignore_exit = ignore_exit
        self.messages: list[dict[str, object]] = []
        self._response_tasks: set[asyncio.Task[None]] = set()
        self.task = asyncio.create_task(self._serve(), name="fake-lsp-server")

    async def _serve(self) -> None:
        reader = _FrameReader(self.stdin)
        try:
            while (message := await reader.read()) is not None:
                self.messages.append(message)
                method = message.get("method")
                request_id = message.get("id")
                if method == "initialize":
                    if self.initialize_gate is not None:
                        await self.initialize_gate.wait()
                    response = _frame(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "capabilities": {
                                    **self.server_capabilities,
                                    "positionEncoding": self.position_encoding,
                                }
                            },
                        }
                    )
                    diagnostic = _frame(
                        {
                            "jsonrpc": "2.0",
                            "method": "textDocument/publishDiagnostics",
                            "params": {
                                "uri": "file:///discarded.py",
                                "diagnostics": [],
                            },
                        }
                    )
                    configuration_request = _frame(
                        {
                            "jsonrpc": "2.0",
                            "id": "server-config-1",
                            "method": "workspace/configuration",
                            "params": {"items": [{"section": "python"}]},
                        }
                    )
                    # Exercise a response split across chunks and a coalesced next frame.
                    await self.stdout.put(response[:11])
                    await self.stdout.put(
                        response[11:] + diagnostic + configuration_request
                    )
                elif method == "textDocument/definition":
                    if self.crash_on_definition:
                        return
                    self._schedule_response(
                        self.definition_gate,
                        _frame(
                            {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "result": self.definition_result,
                            }
                        ),
                    )
                elif method == "textDocument/references":
                    if self.content_modified_references:
                        self.content_modified_references -= 1
                        self._schedule_response(
                            None,
                            _frame(
                                {
                                    "jsonrpc": "2.0",
                                    "id": request_id,
                                    "error": {
                                        "code": -32801,
                                        "message": "content modified",
                                    },
                                }
                            ),
                        )
                        continue
                    self._schedule_response(
                        None,
                        _frame(
                            {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "result": self.references_result,
                            }
                        ),
                    )
                elif method == "textDocument/implementation":
                    self._schedule_response(
                        None,
                        _frame(
                            {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "result": self.implementation_result,
                            }
                        ),
                    )
                elif method == "textDocument/hover":
                    self._schedule_response(
                        None,
                        _frame(
                            {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "result": self.hover_result,
                            }
                        ),
                    )
                elif method == "textDocument/documentSymbol":
                    self._schedule_response(
                        None,
                        _frame(
                            {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "result": self.outline_result,
                            }
                        ),
                    )
                elif method == "shutdown":
                    self._schedule_response(
                        self.shutdown_gate,
                        _frame({"jsonrpc": "2.0", "id": request_id, "result": None}),
                    )
                elif method == "exit" and not self.ignore_exit:
                    break
        finally:
            response_tasks = tuple(self._response_tasks)
            for task in response_tasks:
                task.cancel()
            if response_tasks:
                await asyncio.gather(*response_tasks, return_exceptions=True)
            await self.stdout.put(None)

    def _schedule_response(
        self,
        gate: asyncio.Event | None,
        response: bytes,
    ) -> None:
        async def send() -> None:
            if gate is not None:
                await gate.wait()
            await self.stdout.put(response)

        task = asyncio.create_task(send(), name="fake-lsp-response")
        self._response_tasks.add(task)
        task.add_done_callback(self._response_tasks.discard)

    async def publish_diagnostics(
        self,
        *,
        uri: str,
        diagnostics: list[object],
        version: int | None = None,
    ) -> None:
        params: dict[str, object] = {
            "uri": uri,
            "diagnostics": diagnostics,
        }
        if version is not None:
            params["version"] = version
        await self.stdout.put(
            _frame(
                {
                    "jsonrpc": "2.0",
                    "method": "textDocument/publishDiagnostics",
                    "params": params,
                }
            )
        )

    def methods(self) -> list[str]:
        return [
            method
            for message in self.messages
            if isinstance((method := message.get("method")), str)
        ]


class FakeProcessHandle:
    def __init__(self, server: FakeLspServer) -> None:
        self.server = server
        self.close_calls = 0
        self.terminate_calls = 0
        self.wait_calls = 0

    async def read_stdout(self, max_bytes: int = 65536) -> bytes:
        del max_bytes
        chunk = await self.server.stdout.get()
        return b"" if chunk is None else chunk

    async def write_stdin(self, data: bytes) -> None:
        await self.server.stdin.put(data)

    async def close_stdin(self) -> None:
        await self.server.stdin.put(None)

    async def wait(self) -> ProcessExit:
        self.wait_calls += 1
        await self.server.task
        return ProcessExit(return_code=0)

    async def terminate(self) -> ProcessExit:
        self.terminate_calls += 1
        if not self.server.task.done():
            await self.server.stdin.put(None)
        await self.server.task
        return ProcessExit(return_code=-15)

    async def close(self) -> None:
        self.close_calls += 1
        if not self.server.task.done():
            await self.server.stdin.put(None)
        await self.server.task

    def stderr_tail(self) -> ProcessStderrTail:
        return ProcessStderrTail()


class FakeLauncher:
    def __init__(
        self,
        *,
        definition_result: object,
        references_result: object = None,
        implementation_result: object = None,
        hover_result: object = None,
        outline_result: object = None,
        initialize_gate: asyncio.Event | None = None,
        definition_gate: asyncio.Event | None = None,
        shutdown_gate: asyncio.Event | None = None,
        position_encoding: str = "utf-16",
        server_capabilities: Mapping[str, object] | None = None,
        crash_first_definition: bool = False,
        content_modified_references: int = 0,
        ignore_exit: bool = False,
    ) -> None:
        self.definition_result = definition_result
        self.references_result = references_result
        self.implementation_result = implementation_result
        self.hover_result = hover_result
        self.outline_result = outline_result
        self.initialize_gate = initialize_gate
        self.definition_gate = definition_gate
        self.shutdown_gate = shutdown_gate
        self.position_encoding = position_encoding
        self.server_capabilities = dict(
            {
                "definitionProvider": True,
                "referencesProvider": True,
                "implementationProvider": True,
                "hoverProvider": True,
                "documentSymbolProvider": True,
            }
            if server_capabilities is None
            else server_capabilities
        )
        self.crash_first_definition = crash_first_definition
        self.content_modified_references = content_modified_references
        self.ignore_exit = ignore_exit
        self.requests: list[ProcessLaunchRequest] = []
        self.correlation_ids: list[str] = []
        self.handles: list[FakeProcessHandle] = []

    async def start(
        self,
        request: ProcessLaunchRequest,
        *,
        correlation_id: str,
        signal: object | None = None,
    ) -> FakeProcessHandle:
        del signal
        self.requests.append(request)
        self.correlation_ids.append(correlation_id)
        server = FakeLspServer(
            definition_result=self.definition_result,
            references_result=self.references_result,
            implementation_result=self.implementation_result,
            hover_result=self.hover_result,
            outline_result=self.outline_result,
            initialize_gate=self.initialize_gate,
            definition_gate=self.definition_gate,
            shutdown_gate=self.shutdown_gate,
            position_encoding=self.position_encoding,
            server_capabilities=self.server_capabilities,
            crash_on_definition=self.crash_first_definition and not self.handles,
            content_modified_references=self.content_modified_references,
            ignore_exit=self.ignore_exit,
        )
        handle = FakeProcessHandle(server)
        self.handles.append(handle)
        return handle


def _definition(
    *,
    language_extensions: Mapping[str, tuple[str, ...]] | None = None,
    request_timeout_seconds: float = 1,
    shutdown_timeout_seconds: float = 1,
) -> LspServerDefinition:
    return LspServerDefinition(
        id="fake-python",
        command=("fake-language-server", "--stdio"),
        language_extensions=language_extensions or {"python": ("py",)},
        root_markers=("pyproject.toml",),
        priority=100,
        environment={"LSP_MODE": "test"},
        settings={"python": {"analysis": "strict"}},
        startup_timeout_seconds=1,
        request_timeout_seconds=request_timeout_seconds,
        shutdown_timeout_seconds=shutdown_timeout_seconds,
    )


def _binding(
    workspace: Path,
    launcher: FakeLauncher,
    files: dict[Path, str],
    definition: LspServerDefinition | None = None,
) -> CodingLspBinding:
    return CodingLspBinding(
        workspace_root=workspace,
        definitions=(definition or _definition(),),
        launcher=launcher,
        read_text=lambda path: files[path],
        baseline_environment={"PATH": "/admitted/bin", "LANG": "C.UTF-8"},
    )


def test_fake_launcher_drives_tool_to_definition_and_ordered_sync(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        project = tmp_path / "project"
        project.mkdir()
        (project / "pyproject.toml").touch()
        source = project / "main.py"
        source.touch()
        files = {source.resolve(): "😀target = 1\nprint(target)\n"}
        launcher = FakeLauncher(
            definition_result={
                "uri": source.resolve().as_uri(),
                "range": {
                    "start": {"line": 0, "character": 2},
                    "end": {"line": 0, "character": 8},
                },
            }
        )
        binding = _binding(tmp_path, launcher, files)
        definition = create_inspect_symbol_tool_definition(binding)
        tool = wrap_tool_definition(
            definition,
            context_provider=lambda *, tool_call_id: ToolContext(
                tool_call_id=tool_call_id,
                cwd=str(tmp_path),
            ),
        )

        first = await tool.execute(
            "lsp-call-1",
            {"path": "project/main.py", "line": 2, "character": 7},
        )
        second = await tool.execute(
            "lsp-call-2",
            {"path": "project/main.py", "line": 2, "character": 7},
        )

        assert first.details["items"] == (
            {
                "path": "project/main.py",
                "uri": source.resolve().as_uri(),
                "range": {
                    "start": {"line": 1, "character": 2},
                    "end": {"line": 1, "character": 8},
                },
                "external": False,
                "readable": True,
            },
        )
        assert first.details["document_version"] == 1
        assert second.details["document_version"] == 1
        assert len(launcher.requests) == 1
        assert launcher.correlation_ids == ["lsp-call-1"]
        request = launcher.requests[0]
        assert request.command == ("fake-language-server", "--stdio")
        assert request.cwd == str(project.resolve())
        assert dict(request.effective_environment) == {
            "PATH": "/admitted/bin",
            "LANG": "C.UTF-8",
            "LSP_MODE": "test",
        }
        assert request.effective_environment == (
            ("LANG", "C.UTF-8"),
            ("LSP_MODE", "test"),
            ("PATH", "/admitted/bin"),
        )

        server = launcher.handles[0].server
        assert server.methods().count("initialize") == 1
        assert server.methods().count("textDocument/didOpen") == 1
        assert "textDocument/didChange" not in server.methods()
        configuration_responses = [
            message
            for message in server.messages
            if message.get("id") == "server-config-1" and "result" in message
        ]
        assert configuration_responses == [
            {
                "jsonrpc": "2.0",
                "id": "server-config-1",
                "result": [{"python": {"analysis": "strict"}}],
            }
        ]
        definition_calls = [
            message
            for message in server.messages
            if message.get("method") == "textDocument/definition"
        ]
        assert definition_calls[0]["params"]["position"] == {
            "line": 1,
            "character": 6,
        }
        assert definition.execution_mode == "parallel"
        assert definition.parameters["properties"]["query"]["enum"] == [
            "definition",
            "references",
            "hover",
            "implementation",
        ]
        assert definition.parameters["properties"]["include_declaration"] == {
            "type": "boolean"
        }

        files[source.resolve()] = "😀target = 2\nprint(target)\n"
        changed = await binding.inspect_symbol(
            path="project/main.py",
            line=2,
            character=7,
            correlation_id="lsp-call-3",
        )
        assert changed.document_version == 2
        assert server.methods().count("textDocument/didChange") == 1

        await binding.dispose()
        assert launcher.handles[0].close_calls == 1
        assert server.methods()[-2:] == ["shutdown", "exit"]

    asyncio.run(scenario())


def test_inspect_symbol_supports_references_implementation_and_hover(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        (tmp_path / "pyproject.toml").touch()
        source = tmp_path / "main.py"
        source.touch()
        content = "class Service:\n    pass\n"
        files = {source.resolve(): content}
        location = {
            "uri": source.resolve().as_uri(),
            "range": {
                "start": {"line": 0, "character": 6},
                "end": {"line": 0, "character": 13},
            },
        }
        launcher = FakeLauncher(
            definition_result=None,
            references_result=[location, location],
            implementation_result={
                "targetUri": source.resolve().as_uri(),
                "targetRange": location["range"],
                "targetSelectionRange": location["range"],
                "originSelectionRange": location["range"],
            },
            hover_result={
                "contents": {
                    "kind": "markdown",
                    "value": "`class Service`\n\n" + "x" * MAX_HOVER_CONTENT_CHARACTERS,
                },
                "range": location["range"],
            },
        )
        binding = _binding(tmp_path, launcher, files)

        references = await binding.inspect_symbol(
            path="main.py",
            line=1,
            character=7,
            query="references",
            include_declaration=False,
            limit=1,
            correlation_id="references",
        )
        implementation = await binding.inspect_symbol(
            path="main.py",
            line=1,
            character=7,
            query="implementation",
            correlation_id="implementation",
        )
        hover = await binding.inspect_symbol(
            path="main.py",
            line=1,
            character=7,
            query="hover",
            correlation_id="hover",
        )

        assert references.count == 2
        assert len(references.items) == 1
        assert references.truncated is True
        assert references.items[0].path == "main.py"
        assert implementation.count == 1
        assert implementation.items[0].range.start.character == 7
        assert hover.count == 1
        assert hover.truncated is True
        assert hover.items[0].kind == "markdown"
        assert len(hover.items[0].contents) == MAX_HOVER_CONTENT_CHARACTERS
        assert hover.items[0].range is not None
        assert hover.items[0].range.start.character == 7

        server = launcher.handles[0].server
        references_call = next(
            message
            for message in server.messages
            if message.get("method") == "textDocument/references"
        )
        assert references_call["params"]["context"] == {"includeDeclaration": False}
        assert "textDocument/implementation" in server.methods()
        assert "textDocument/hover" in server.methods()
        await binding.dispose()

    asyncio.run(scenario())


def test_inspect_symbol_retries_content_modified_responses_with_a_bound(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        (tmp_path / "pyproject.toml").touch()
        source = tmp_path / "main.py"
        source.touch()
        files = {source.resolve(): "target = 1\nprint(target)\n"}
        location = {
            "uri": source.resolve().as_uri(),
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 6},
            },
        }

        recovered_launcher = FakeLauncher(
            definition_result=None,
            references_result=[location],
            content_modified_references=2,
        )
        recovered_binding = _binding(tmp_path, recovered_launcher, files)
        recovered = await recovered_binding.inspect_symbol(
            path="main.py",
            line=2,
            character=7,
            query="references",
            correlation_id="content-modified-recovered",
        )

        assert recovered.count == 1
        assert (
            recovered_launcher.handles[0]
            .server.methods()
            .count("textDocument/references")
            == 3
        )
        assert recovered_binding.status().servers[0].last_error is None
        await recovered_binding.dispose()

        exhausted_launcher = FakeLauncher(
            definition_result=None,
            references_result=[location],
            content_modified_references=3,
        )
        exhausted_binding = _binding(tmp_path, exhausted_launcher, files)
        with pytest.raises(LspProtocolError, match="content modified"):
            await exhausted_binding.inspect_symbol(
                path="main.py",
                line=2,
                character=7,
                query="references",
                correlation_id="content-modified-exhausted",
            )
        assert (
            exhausted_launcher.handles[0]
            .server.methods()
            .count("textDocument/references")
            == 3
        )
        await exhausted_binding.dispose()

    asyncio.run(scenario())


def test_inspect_symbol_normalizes_legacy_hover_and_skips_unsupported_query(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        (tmp_path / "pyproject.toml").touch()
        source = tmp_path / "main.py"
        source.touch()
        files = {source.resolve(): "value = 1\n"}
        launcher = FakeLauncher(
            definition_result=None,
            hover_result={
                "contents": [
                    "legacy markdown",
                    {"language": "python", "value": "value: int"},
                ]
            },
            server_capabilities={
                "definitionProvider": True,
                "hoverProvider": True,
            },
        )
        binding = _binding(tmp_path, launcher, files)

        hover = await binding.inspect_symbol(
            path="main.py",
            line=1,
            character=1,
            query="hover",
            correlation_id="legacy-hover",
        )
        unsupported = await binding.inspect_symbol(
            path="main.py",
            line=1,
            character=1,
            query="references",
            correlation_id="unsupported-references",
        )

        assert hover.items[0].kind == "markdown"
        assert hover.items[0].contents == (
            "legacy markdown\n\n```python\nvalue: int\n```"
        )
        assert hover.items[0].range is None
        assert unsupported.items == ()
        assert unsupported.count == 0
        assert unsupported.readiness == "unsupported"
        assert unsupported.warnings == (
            "language server does not advertise references support",
        )
        assert "textDocument/references" not in launcher.handles[0].server.methods()

        with pytest.raises(LspInvalidInputError, match="query must be one of"):
            await binding.inspect_symbol(
                path="main.py",
                line=1,
                character=1,
                query="callers",
                correlation_id="invalid-query",
            )
        with pytest.raises(LspInvalidInputError, match="include_declaration"):
            await binding.inspect_symbol(
                path="main.py",
                line=1,
                character=1,
                query="references",
                include_declaration=1,  # type: ignore[arg-type]
                correlation_id="invalid-include-declaration",
            )
        await binding.dispose()

    asyncio.run(scenario())


def test_document_outline_preserves_hierarchy_and_enforces_depth(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        project = tmp_path / "project"
        project.mkdir()
        (project / "pyproject.toml").touch()
        source = project / "main.py"
        source.touch()
        content = "class Greeter:\n    def hello(self):\n        pass\n\ndef main():\n    pass\n"
        files = {source.resolve(): content}
        outline = [
            {
                "name": "Greeter",
                "detail": "class Greeter",
                "kind": 5,
                "range": {
                    "start": {"line": 0, "character": 0},
                    "end": {"line": 2, "character": 12},
                },
                "selectionRange": {
                    "start": {"line": 0, "character": 6},
                    "end": {"line": 0, "character": 13},
                },
                "children": [
                    {
                        "name": "hello",
                        "kind": 6,
                        "range": {
                            "start": {"line": 1, "character": 4},
                            "end": {"line": 2, "character": 12},
                        },
                        "selectionRange": {
                            "start": {"line": 1, "character": 8},
                            "end": {"line": 1, "character": 13},
                        },
                    }
                ],
            },
            {
                "name": "main",
                "kind": 12,
                "range": {
                    "start": {"line": 4, "character": 0},
                    "end": {"line": 5, "character": 8},
                },
                "selectionRange": {
                    "start": {"line": 4, "character": 4},
                    "end": {"line": 4, "character": 8},
                },
            },
        ]
        launcher = FakeLauncher(definition_result=None, outline_result=outline)
        binding = _binding(tmp_path, launcher, files)

        result = await binding.document_outline(
            path="project/main.py",
            depth=2,
            correlation_id="outline-1",
        )
        shallow = await binding.document_outline(
            path="project/main.py",
            depth=1,
            correlation_id="outline-2",
        )
        limited = await binding.document_outline(
            path="project/main.py",
            limit=1,
            correlation_id="outline-3",
        )

        assert result.count == 3
        assert result.truncated is False
        assert [item.name for item in result.items] == ["Greeter", "main"]
        assert result.items[0].kind_name == "class"
        assert result.items[0].children[0].name == "hello"
        assert result.items[0].children[0].range.start.line == 2
        assert shallow.count == 3
        assert shallow.truncated is True
        assert shallow.items[0].children == ()
        assert limited.count == 3
        assert limited.truncated is True
        assert [item.name for item in limited.items] == ["Greeter"]
        assert launcher.correlation_ids == ["outline-1"]
        assert (
            launcher.handles[0].server.methods().count("textDocument/documentSymbol")
            == 3
        )

        with pytest.raises(LspInvalidInputError, match="depth"):
            await binding.document_outline(
                path="project/main.py",
                depth=0,
                correlation_id="invalid-outline",
            )

        definition = create_document_outline_tool_definition(binding)
        assert definition.name == DOCUMENT_OUTLINE_TOOL_NAME
        await binding.dispose()

    asyncio.run(scenario())


def test_document_outline_skips_unsupported_server_capability(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        (tmp_path / "pyproject.toml").touch()
        source = tmp_path / "main.py"
        source.touch()
        files = {source.resolve(): "value = 1\n"}
        launcher = FakeLauncher(
            definition_result=None,
            server_capabilities={"definitionProvider": True},
        )
        binding = _binding(tmp_path, launcher, files)

        result = await binding.document_outline(
            path="main.py",
            correlation_id="unsupported-outline",
        )

        assert result.items == ()
        assert result.count == 0
        assert result.readiness == "unsupported"
        assert result.document_version is None
        assert result.warnings == (
            "language server does not advertise document symbol support",
        )
        assert "textDocument/documentSymbol" not in launcher.handles[0].server.methods()
        await binding.dispose()

    asyncio.run(scenario())


def test_concurrent_first_queries_single_flight_launch_and_document_open(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        (tmp_path / "pyproject.toml").touch()
        source = tmp_path / "main.py"
        source.touch()
        files = {source.resolve(): "value = 1\nprint(value)\n"}
        gate = asyncio.Event()
        launcher = FakeLauncher(
            definition_result=None,
            initialize_gate=gate,
        )
        binding = _binding(tmp_path, launcher, files)

        first = asyncio.create_task(
            binding.inspect_symbol(
                path="main.py",
                line=2,
                character=7,
                correlation_id="first",
            )
        )
        second = asyncio.create_task(
            binding.inspect_symbol(
                path="main.py",
                line=2,
                character=7,
                correlation_id="second",
            )
        )
        for _ in range(20):
            if launcher.requests:
                break
            await asyncio.sleep(0)
        assert len(launcher.requests) == 1
        gate.set()
        results = await asyncio.gather(first, second)

        assert [result.count for result in results] == [0, 0]
        assert launcher.handles[0].server.methods().count("textDocument/didOpen") == 1
        await binding.dispose()

    asyncio.run(scenario())


def test_initialize_failure_closes_fake_process_and_publishes_no_runtime(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        (tmp_path / "pyproject.toml").touch()
        source = tmp_path / "main.py"
        source.touch()
        launcher = FakeLauncher(
            definition_result=None,
            position_encoding="utf-8",
        )
        binding = _binding(tmp_path, launcher, {source.resolve(): "value = 1\n"})

        with pytest.raises(LspProtocolError, match="position encoding"):
            await binding.inspect_symbol(
                path="main.py",
                line=1,
                character=1,
                correlation_id="bad-init",
            )

        assert len(launcher.handles) == 1
        assert launcher.handles[0].close_calls == 1
        failed = binding.status().servers[0]
        assert failed.state == "failed"
        assert failed.runtime_id is None
        assert failed.request_count == 1
        assert failed.last_error == "initialization_failed"
        await binding.dispose()

    asyncio.run(scenario())


def test_query_rejects_workspace_escape_and_bounds_definition_results(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        (tmp_path / "pyproject.toml").touch()
        source = tmp_path / "main.py"
        source.touch()
        location = {
            "uri": source.resolve().as_uri(),
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 5},
            },
        }
        launcher = FakeLauncher(definition_result=[location, location, location])
        binding = _binding(tmp_path, launcher, {source.resolve(): "value = 1\n"})

        with pytest.raises(LspInvalidInputError, match="within the Coding workspace"):
            await binding.inspect_symbol(
                path="../outside.py",
                line=1,
                character=1,
                correlation_id="escaped",
            )
        assert launcher.requests == []

        result = await binding.inspect_symbol(
            path="main.py",
            line=1,
            character=1,
            limit=2,
            correlation_id="bounded",
        )
        assert result.count == 3
        assert len(result.items) == 2
        assert result.truncated is True
        await binding.dispose()

    asyncio.run(scenario())


def test_caller_cancellation_sends_protocol_cancel_and_keeps_runtime(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        (tmp_path / "pyproject.toml").touch()
        source = tmp_path / "main.py"
        source.touch()
        gate = asyncio.Event()
        launcher = FakeLauncher(definition_result=None, definition_gate=gate)
        binding = _binding(tmp_path, launcher, {source.resolve(): "value = 1\n"})

        query = asyncio.create_task(
            binding.inspect_symbol(
                path="main.py",
                line=1,
                character=1,
                correlation_id="cancelled-query",
            )
        )
        for _ in range(100):
            if launcher.handles:
                server = launcher.handles[0].server
                if "textDocument/definition" in server.methods():
                    break
            await asyncio.sleep(0)
        else:
            raise AssertionError("definition request was not issued")

        query.cancel()
        with pytest.raises(asyncio.CancelledError):
            await query
        await _wait_for_method(server, "$/cancelRequest")

        gate.set()
        result = await binding.inspect_symbol(
            path="main.py",
            line=1,
            character=1,
            correlation_id="next-query",
        )
        assert result.count == 0
        assert len(launcher.requests) == 1
        await binding.dispose()

    asyncio.run(scenario())


def test_request_timeout_sends_protocol_cancel_and_keeps_runtime(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        (tmp_path / "pyproject.toml").touch()
        source = tmp_path / "main.py"
        source.touch()
        gate = asyncio.Event()
        launcher = FakeLauncher(definition_result=None, definition_gate=gate)
        definition = _definition(request_timeout_seconds=0.01)
        binding = _binding(
            tmp_path,
            launcher,
            {source.resolve(): "value = 1\n"},
            definition,
        )

        with pytest.raises(LspProtocolError, match="timed out"):
            await binding.inspect_symbol(
                path="main.py",
                line=1,
                character=1,
                correlation_id="timed-out-query",
            )
        server = launcher.handles[0].server
        await _wait_for_method(server, "$/cancelRequest")
        timed_out_status = binding.status().servers[0]
        assert timed_out_status.state == "ready"
        assert timed_out_status.timeout_count == 1
        assert timed_out_status.last_error is None

        gate.set()
        result = await binding.inspect_symbol(
            path="main.py",
            line=1,
            character=1,
            correlation_id="after-timeout",
        )
        assert result.count == 0
        assert len(launcher.requests) == 1
        await binding.dispose()

    asyncio.run(scenario())


def test_runtime_status_is_read_only_and_explicit_stop_allows_replacement(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        (tmp_path / "pyproject.toml").touch()
        source = tmp_path / "main.py"
        source.touch()
        launcher = FakeLauncher(definition_result=None)
        binding = _binding(tmp_path, launcher, {source.resolve(): "value = 1\n"})

        initial = binding.status()
        assert initial.scope == "session"
        assert initial.enabled is True
        assert initial.servers == ()
        assert launcher.requests == []

        await binding.inspect_symbol(
            path="main.py",
            line=1,
            character=1,
            correlation_id="status-query",
        )
        ready = binding.status()
        assert ready.ready_count == 1
        assert ready.starting_count == 0
        assert len(launcher.requests) == 1
        ready_server = ready.servers[0]
        assert ready_server.definition_id == "fake-python"
        assert ready_server.workspace_root == str(tmp_path.resolve())
        assert ready_server.state == "ready"
        assert ready_server.runtime_id == 1
        assert ready_server.open_document_count == 1
        assert ready_server.request_count == 2
        assert ready_server.timeout_count == 0
        assert ready_server.replacement_count == 0
        assert ready_server.accepted_diagnostic_publications == 0
        assert ready_server.discarded_diagnostic_publications == 1
        assert ready_server.last_request_duration_ms is not None
        assert ready_server.last_error is None

        with pytest.raises(LspInvalidInputError, match="unknown LSP server"):
            await binding.stop(
                definition_id="unknown",
                workspace_root=tmp_path,
            )
        with pytest.raises(LspInvalidInputError, match="must stay within"):
            await binding.stop(
                definition_id="fake-python",
                workspace_root=tmp_path.parent,
            )

        stopped = await binding.stop(
            definition_id="fake-python",
            workspace_root=tmp_path,
        )
        assert stopped is True
        stopped_server = binding.status().servers[0]
        assert stopped_server.state == "stopped"
        assert stopped_server.runtime_id is None
        assert stopped_server.open_document_count == 0
        assert launcher.handles[0].server.methods()[-2:] == ["shutdown", "exit"]

        await binding.inspect_symbol(
            path="main.py",
            line=1,
            character=1,
            correlation_id="replacement-query",
        )
        replacement = binding.status().servers[0]
        assert replacement.state == "ready"
        assert replacement.runtime_id == 2
        assert replacement.replacement_count == 1
        assert replacement.request_count >= 5
        assert len(launcher.requests) == 2

        await binding.dispose()
        disposed = binding.status()
        assert disposed.disposed is True
        assert disposed.servers[0].state == "stopped"

    asyncio.run(scenario())


def test_passive_diagnostics_are_versioned_replaced_bounded_and_released(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        (tmp_path / "pyproject.toml").touch()
        source = tmp_path / "main.py"
        source.touch()
        files = {source.resolve(): "value = 1\n"}
        launcher = FakeLauncher(definition_result=None)
        binding = _binding(tmp_path, launcher, files)

        await binding.inspect_symbol(
            path="main.py",
            line=1,
            character=1,
            correlation_id="diagnostic-open",
        )
        server = launcher.handles[0].server
        diagnostic = {
            "range": {
                "start": {"line": 0, "character": 0},
                "end": {"line": 0, "character": 5},
            },
            "severity": 1,
            "message": "invalid value",
            "source": "fake",
        }

        await server.publish_diagnostics(
            uri=source.resolve().as_uri(),
            version=1,
            diagnostics=[diagnostic],
        )
        for _ in range(100):
            if binding.status().servers[0].current_diagnostic_count == 1:
                break
            await asyncio.sleep(0)
        ready = binding.status().servers[0]
        assert ready.diagnostic_document_count == 1
        assert ready.current_diagnostic_count == 1
        assert ready.accepted_diagnostic_publications == 1
        assert ready.discarded_diagnostic_publications == 1

        await server.publish_diagnostics(
            uri=source.resolve().as_uri(),
            version=0,
            diagnostics=[],
        )
        for _ in range(100):
            if binding.status().servers[0].discarded_diagnostic_publications == 2:
                break
            await asyncio.sleep(0)
        stale = binding.status().servers[0]
        assert stale.current_diagnostic_count == 1
        assert stale.accepted_diagnostic_publications == 1
        assert stale.discarded_diagnostic_publications == 2

        files[source.resolve()] = "value = 2\n"
        changed = await binding.inspect_symbol(
            path="main.py",
            line=1,
            character=1,
            correlation_id="diagnostic-change",
        )
        assert changed.document_version == 2
        assert binding.status().servers[0].current_diagnostic_count == 0

        await server.publish_diagnostics(
            uri=source.resolve().as_uri(),
            version=2,
            diagnostics=[diagnostic, {**diagnostic, "message": "second"}],
        )
        for _ in range(100):
            if binding.status().servers[0].current_diagnostic_count == 2:
                break
            await asyncio.sleep(0)
        assert binding.status().servers[0].current_diagnostic_count == 2
        assert binding.status().servers[0].accepted_diagnostic_publications == 2

        await server.publish_diagnostics(
            uri=source.resolve().as_uri(),
            version=2,
            diagnostics=[],
        )
        for _ in range(100):
            if binding.status().servers[0].current_diagnostic_count == 0:
                break
            await asyncio.sleep(0)
        assert binding.status().servers[0].diagnostic_document_count == 0
        assert binding.status().servers[0].accepted_diagnostic_publications == 3

        await server.publish_diagnostics(
            uri=source.resolve().as_uri(),
            diagnostics=[diagnostic],
        )
        for _ in range(100):
            if binding.status().servers[0].current_diagnostic_count == 1:
                break
            await asyncio.sleep(0)
        assert await binding.stop(
            definition_id="fake-python",
            workspace_root=tmp_path,
        )
        stopped = binding.status().servers[0]
        assert stopped.diagnostic_document_count == 0
        assert stopped.current_diagnostic_count == 0
        await binding.dispose()

    asyncio.run(scenario())


def test_passive_diagnostics_are_released_when_server_stdout_closes(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        (tmp_path / "pyproject.toml").touch()
        source = tmp_path / "main.py"
        source.touch()
        launcher = FakeLauncher(definition_result=None)
        binding = _binding(tmp_path, launcher, {source.resolve(): "value = 1\n"})
        await binding.inspect_symbol(
            path="main.py",
            line=1,
            character=1,
            correlation_id="diagnostic-before-crash",
        )
        server = launcher.handles[0].server
        await server.publish_diagnostics(
            uri=source.resolve().as_uri(),
            version=1,
            diagnostics=[
                {
                    "range": {
                        "start": {"line": 0, "character": 0},
                        "end": {"line": 0, "character": 1},
                    },
                    "message": "before crash",
                }
            ],
        )
        for _ in range(100):
            if binding.status().servers[0].current_diagnostic_count == 1:
                break
            await asyncio.sleep(0)
        assert binding.status().servers[0].current_diagnostic_count == 1

        await server.stdout.put(None)
        for _ in range(100):
            status = binding.status().servers[0]
            if status.state == "failed":
                break
            await asyncio.sleep(0)
        failed = binding.status().servers[0]
        assert failed.state == "failed"
        assert failed.diagnostic_document_count == 0
        assert failed.current_diagnostic_count == 0
        await binding.dispose()

    asyncio.run(scenario())


def test_runtime_status_observes_pending_start_without_starting_another_server(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        (tmp_path / "pyproject.toml").touch()
        source = tmp_path / "main.py"
        source.touch()
        gate = asyncio.Event()
        launcher = FakeLauncher(definition_result=None, initialize_gate=gate)
        binding = _binding(tmp_path, launcher, {source.resolve(): "value = 1\n"})

        query = asyncio.create_task(
            binding.inspect_symbol(
                path="main.py",
                line=1,
                character=1,
                correlation_id="pending-start",
            )
        )
        for _ in range(100):
            if launcher.handles:
                break
            await asyncio.sleep(0)
        assert launcher.handles

        pending = binding.status()
        assert pending.starting_count == 1
        assert pending.servers[0].state == "starting"
        assert pending.servers[0].open_document_count == 0
        assert len(launcher.requests) == 1

        gate.set()
        await query
        assert binding.status().servers[0].state == "ready"
        await binding.dispose()

    asyncio.run(scenario())


def test_shutdown_rejects_new_requests_and_waits_for_graceful_exit(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        definition_gate = asyncio.Event()
        shutdown_gate = asyncio.Event()
        launcher = FakeLauncher(
            definition_result=None,
            definition_gate=definition_gate,
            shutdown_gate=shutdown_gate,
        )
        handle = await launcher.start(
            ProcessLaunchRequest(
                command=("fake-language-server",),
                cwd=str(tmp_path.resolve()),
                effective_environment=(),
            ),
            correlation_id="client-test",
        )
        client = LspClient(
            handle,
            request_timeout_seconds=1,
            shutdown_timeout_seconds=1,
        )
        await client.initialize(
            root_uri=tmp_path.resolve().as_uri(),
            initialization_options={},
            timeout_seconds=1,
        )

        pending = asyncio.create_task(client.request("textDocument/definition", {}))
        await _wait_for_method(handle.server, "textDocument/definition")
        closing = asyncio.create_task(client.shutdown())
        await _wait_for_method(handle.server, "$/cancelRequest")
        await _wait_for_method(handle.server, "shutdown")
        with pytest.raises(LspProtocolError, match="closing"):
            await pending
        with pytest.raises(LspProtocolError, match="closed"):
            await client.request("textDocument/definition", {})
        shutdown_gate.set()
        await closing

        assert handle.wait_calls == 1
        assert handle.terminate_calls == 0
        assert handle.close_calls == 1
        assert handle.server.methods()[-2:] == ["shutdown", "exit"]

    asyncio.run(scenario())


def test_shutdown_timeout_uses_terminate_fallback(tmp_path: Path) -> None:
    async def scenario() -> None:
        launcher = FakeLauncher(definition_result=None, ignore_exit=True)
        handle = await launcher.start(
            ProcessLaunchRequest(
                command=("fake-language-server",),
                cwd=str(tmp_path.resolve()),
                effective_environment=(),
            ),
            correlation_id="client-test",
        )
        client = LspClient(
            handle,
            request_timeout_seconds=1,
            shutdown_timeout_seconds=0.01,
        )
        await client.initialize(
            root_uri=tmp_path.resolve().as_uri(),
            initialization_options={},
            timeout_seconds=1,
        )

        await client.shutdown()

        assert handle.wait_calls == 1
        assert handle.terminate_calls == 1
        assert handle.close_calls == 1

    asyncio.run(scenario())


def test_cancelled_binding_dispose_keeps_one_shared_close_running(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        (tmp_path / "pyproject.toml").touch()
        source = tmp_path / "main.py"
        source.touch()
        shutdown_gate = asyncio.Event()
        launcher = FakeLauncher(
            definition_result=None,
            shutdown_gate=shutdown_gate,
        )
        binding = _binding(tmp_path, launcher, {source.resolve(): "value = 1\n"})
        await binding.inspect_symbol(
            path="main.py",
            line=1,
            character=1,
            correlation_id="open-runtime",
        )

        first = asyncio.create_task(binding.dispose())
        await _wait_for_method(launcher.handles[0].server, "shutdown")
        second = asyncio.create_task(binding.dispose())
        await asyncio.sleep(0)
        assert not first.done()
        assert not second.done()

        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert not second.done()

        shutdown_gate.set()
        await second
        assert launcher.handles[0].close_calls == 1

    asyncio.run(scenario())


def test_concurrent_stop_and_dispose_share_one_server_shutdown(tmp_path: Path) -> None:
    async def scenario() -> None:
        (tmp_path / "pyproject.toml").touch()
        source = tmp_path / "main.py"
        source.touch()
        shutdown_gate = asyncio.Event()
        launcher = FakeLauncher(
            definition_result=None,
            shutdown_gate=shutdown_gate,
        )
        binding = _binding(tmp_path, launcher, {source.resolve(): "value = 1\n"})
        await binding.inspect_symbol(
            path="main.py",
            line=1,
            character=1,
            correlation_id="open-before-stop",
        )

        first_stop = asyncio.create_task(
            binding.stop(
                definition_id="fake-python",
                workspace_root=tmp_path,
            )
        )
        await _wait_for_method(launcher.handles[0].server, "shutdown")
        second_stop = asyncio.create_task(
            binding.stop(
                definition_id="fake-python",
                workspace_root=tmp_path,
            )
        )
        disposing = asyncio.create_task(binding.dispose())
        await asyncio.sleep(0)
        assert not first_stop.done()
        assert not second_stop.done()
        assert not disposing.done()

        shutdown_gate.set()
        assert await first_stop is True
        assert await second_stop is True
        await disposing

        methods = launcher.handles[0].server.methods()
        assert methods.count("shutdown") == 1
        assert methods.count("exit") == 1
        assert launcher.handles[0].close_calls == 1
        assert binding.status().disposed is True

    asyncio.run(scenario())


def test_server_crash_restarts_on_demand_and_reopens_document(tmp_path: Path) -> None:
    async def scenario() -> None:
        (tmp_path / "pyproject.toml").touch()
        source = tmp_path / "main.py"
        source.touch()
        launcher = FakeLauncher(
            definition_result=None,
            crash_first_definition=True,
        )
        binding = _binding(tmp_path, launcher, {source.resolve(): "value = 1\n"})

        with pytest.raises(LspProtocolError, match="reader failed"):
            await binding.inspect_symbol(
                path="main.py",
                line=1,
                character=1,
                correlation_id="crashed-query",
            )
        crashed = binding.status().servers[0]
        assert crashed.state == "failed"
        assert crashed.last_error == "connection_closed"
        result = await binding.inspect_symbol(
            path="main.py",
            line=1,
            character=1,
            correlation_id="replacement-query",
        )

        assert result.count == 0
        assert len(launcher.requests) == 2
        replacement = binding.status().servers[0]
        assert replacement.state == "ready"
        assert replacement.replacement_count == 1
        assert [
            handle.server.methods().count("textDocument/didOpen")
            for handle in launcher.handles
        ] == [1, 1]
        await binding.dispose()

    asyncio.run(scenario())


def test_language_mapping_catalog_freeze_and_literal_root_markers(
    tmp_path: Path,
) -> None:
    settings = {"nested": {"modes": ["strict"]}}
    definition = LspServerDefinition(
        id="typescript-family",
        command=["typescript-language-server", "--stdio"],
        language_extensions={
            "typescript": [".ts", ".tsx"],
            "javascript": [".js", ".jsx"],
        },
        settings=settings,
    )
    settings["nested"]["modes"].append("loose")
    (tmp_path / "sample.js").touch()
    selector = LspSelector(
        workspace_root=tmp_path,
        catalog=LspCatalog((definition,)),
    )

    assert definition.command == ("typescript-language-server", "--stdio")
    assert definition.settings["nested"]["modes"] == ("strict",)
    assert selector.select("sample.js").language_id == "javascript"

    with pytest.raises(ValueError, match="literal relative"):
        LspServerDefinition(
            id="glob-root",
            command=("server",),
            language_extensions={"python": (".py",)},
            root_markers=("**/pyproject.toml",),
        )
    with pytest.raises(ValueError, match="belongs to both"):
        LspServerDefinition(
            id="ambiguous-extension",
            command=("server",),
            language_extensions={
                "typescript": (".ts",),
                "other": (".ts",),
            },
        )


def test_product_presets_run_independently_in_one_monorepo_session(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        projects = (
            (
                "pyright",
                ("pyright-langserver", "--stdio"),
                "python-service",
                "pyrightconfig.json",
                "main.py",
                "value = 1\n",
            ),
            (
                "typescript-language-server",
                ("typescript-language-server", "--stdio"),
                "web-app",
                "tsconfig.json",
                "main.ts",
                "export const value = 1;\n",
            ),
            (
                "rust-analyzer",
                ("rust-analyzer",),
                "rust-service",
                "Cargo.toml",
                "main.rs",
                "fn main() {}\n",
            ),
            (
                "gopls",
                ("gopls", "serve"),
                "go-service",
                "go.mod",
                "main.go",
                "package main\n",
            ),
            (
                "clangd",
                ("clangd",),
                "native-service",
                "compile_commands.json",
                "main.cpp",
                "int main() { return 0; }\n",
            ),
        )
        files: dict[Path, str] = {}
        sources: list[Path] = []
        for _, _, directory, marker, filename, content in projects:
            project_root = tmp_path / directory
            project_root.mkdir()
            (project_root / marker).touch()
            source = project_root / filename
            source.touch()
            sources.append(source)
            files[source.resolve()] = content
        launcher = FakeLauncher(definition_result=None, outline_result=None)
        binding = CodingLspBinding(
            workspace_root=tmp_path,
            definitions=product_default_lsp_definitions(),
            launcher=launcher,
            read_text=lambda path: files[path],
            baseline_environment={"PATH": "/admitted/bin"},
        )

        for index, source in enumerate(sources):
            await binding.document_outline(
                path=str(source.relative_to(tmp_path)),
                correlation_id=f"preset-query-{index}",
            )

        assert [request.command for request in launcher.requests] == [
            command for _, command, _, _, _, _ in projects
        ]
        assert [request.cwd for request in launcher.requests] == [
            str((tmp_path / directory).resolve())
            for _, _, directory, _, _, _ in projects
        ]
        status_by_id = {
            server.definition_id: server for server in binding.status().servers
        }
        assert set(status_by_id) == {item[0] for item in projects}
        for runtime_id, (definition_id, _, _, _, _, _) in enumerate(
            projects,
            start=1,
        ):
            assert status_by_id[definition_id].runtime_id == runtime_id
            assert status_by_id[definition_id].open_document_count == 1
        await binding.dispose()

    asyncio.run(scenario())
