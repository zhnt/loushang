from __future__ import annotations

from pathlib import Path

from loushang.harness.tools.workspace import ToolContext


def _tool_context_provider(*, cwd: str):
    def _provider(*, tool_call_id: str) -> ToolContext:
        return ToolContext(tool_call_id=tool_call_id, cwd=cwd)

    return _provider


def test_decorated_tool_context_receives_abort_signal() -> None:
    import asyncio

    from loushang.harness.tools.core import tool
    from loushang.harness.tools.workspace import direct_tool
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    @tool()
    async def probe(*, ctx: ToolContext) -> dict[str, bool]:
        return {"signal_seen": ctx.signal is signal}

    signal = object()
    runtime_tool = wrap_tool_definition(direct_tool(probe))

    result = asyncio.run(runtime_tool.execute("call-probe", {}, signal=signal))

    assert result.details == {"signal_seen": True}


def test_read_tool_uses_custom_operations(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class VirtualOperations:
        def __init__(self) -> None:
            self.read_paths: list[str] = []

        async def exists(self, path):
            return True

        async def is_file(self, path):
            return True

        async def read_bytes(self, path):
            self.read_paths.append(str(path))
            return b"virtual\ncontent\n"

    operations = VirtualOperations()
    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(operations=operations),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(runtime_tool.execute("call-read", {"path": "remote.txt"}))

    assert result.content[0].text == "virtual\ncontent\n"
    assert operations.read_paths == [str(tmp_path / "remote.txt")]


def test_read_tool_accepts_pi_style_operations(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class PiReadOperations:
        def __init__(self) -> None:
            self.access_paths: list[str] = []
            self.read_paths: list[str] = []

        async def access(self, absolute_path: str) -> None:
            self.access_paths.append(absolute_path)

        async def readFile(self, absolute_path: str) -> bytes:
            self.read_paths.append(absolute_path)
            return b"pi read\n"

    operations = PiReadOperations()
    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(operations=operations),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(runtime_tool.execute("call-pi-read", {"path": "remote.txt"}))

    assert result.content[0].text == "pi read\n"
    assert operations.access_paths == [str(tmp_path / "remote.txt")]
    assert operations.read_paths == [str(tmp_path / "remote.txt")]


def _missing_read_message(runtime_tool, *, call_id: str, path: str) -> str:
    import asyncio

    try:
        result = asyncio.run(runtime_tool.execute(call_id, {"path": path}))
    except FileNotFoundError as exc:
        return str(exc)
    # Some hosts surface tool errors as error results; the hint must be visible
    # to the caller either way.
    return result.content[0].text


def test_read_tool_missing_native_file_includes_path_and_hint(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    message = _missing_read_message(
        runtime_tool, call_id="call-read-missing", path="missing.txt"
    )

    assert str(tmp_path / "missing.txt") in message
    assert "rg --files" in message
    assert str(tmp_path) in message


def test_read_tool_missing_virtual_file_does_not_probe_local_fs(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class VirtualOperations:
        async def exists(self, path):
            return False

        async def is_file(self, path):
            raise AssertionError("is_file must not run when exists is false")

        async def read_bytes(self, path):
            raise AssertionError("read_bytes must not run when exists is false")

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(operations=VirtualOperations()),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    message = _missing_read_message(
        runtime_tool, call_id="call-read-virtual-missing", path="remote.txt"
    )

    assert str(tmp_path / "remote.txt") in message
    assert "rg --files" in message


def test_read_tool_pi_style_missing_file_includes_hint(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class PiReadOperations:
        async def access(self, absolute_path: str) -> None:
            raise FileNotFoundError(absolute_path)

        async def readFile(self, absolute_path: str) -> bytes:
            raise AssertionError("readFile must not run when access fails")

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(operations=PiReadOperations()),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    message = _missing_read_message(
        runtime_tool, call_id="call-pi-read-missing", path="remote.txt"
    )

    assert str(tmp_path / "remote.txt") in message
    assert "rg --files" in message


def test_read_tool_disappearing_file_still_reports_missing_with_hint(
    tmp_path,
) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class VanishingOperations:
        async def exists(self, path):
            return True

        async def is_file(self, path):
            return True

        async def read_bytes(self, path):
            raise FileNotFoundError(str(path))

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(operations=VanishingOperations()),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    message = _missing_read_message(
        runtime_tool, call_id="call-read-vanishing", path="remote.txt"
    )

    assert str(tmp_path / "remote.txt") in message
    assert "rg --files" in message


def test_read_tool_missing_error_when_exists_raises(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class RaisingExistsOperations:
        async def exists(self, path):
            raise FileNotFoundError("gone")

        async def is_file(self, path):
            raise AssertionError("is_file must not run when exists raises")

        async def read_bytes(self, path):
            raise AssertionError("read_bytes must not run when exists raises")

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(operations=RaisingExistsOperations()),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    message = _missing_read_message(
        runtime_tool, call_id="call-read-exists-raises", path="remote.txt"
    )

    assert str(tmp_path / "remote.txt") in message
    assert "rg --files" in message


def test_read_tool_missing_error_when_is_file_raises(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class RaisingIsFileOperations:
        async def exists(self, path):
            return True

        async def is_file(self, path):
            raise FileNotFoundError("gone")

        async def read_bytes(self, path):
            raise AssertionError("read_bytes must not run when is_file raises")

    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(operations=RaisingIsFileOperations()),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    message = _missing_read_message(
        runtime_tool, call_id="call-read-is-file-raises", path="remote.txt"
    )

    assert str(tmp_path / "remote.txt") in message
    assert "rg --files" in message


def test_read_tool_file_vanishing_between_exists_and_is_file(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class VanishingBetweenStages:
        def __init__(self) -> None:
            self.exists_calls = 0

        async def exists(self, path):
            self.exists_calls += 1
            # Present for the first check, gone by the re-check.
            return self.exists_calls == 1

        async def is_file(self, path):
            return False

        async def read_bytes(self, path):
            raise AssertionError("read_bytes must not run once the file vanished")

    operations = VanishingBetweenStages()
    runtime_tool = wrap_tool_definition(
        create_read_tool_definition(operations=operations),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    message = _missing_read_message(
        runtime_tool, call_id="call-read-vanished-mid-check", path="remote.txt"
    )

    assert str(tmp_path / "remote.txt") in message
    assert "rg --files" in message


def test_read_tool_preserves_directory_and_permission_errors(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_read_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    def _error_type_and_message(runtime_tool, *, call_id: str) -> tuple[type | None, str]:
        try:
            result = asyncio.run(runtime_tool.execute(call_id, {"path": "remote.txt"}))
        except (IsADirectoryError, PermissionError) as exc:
            return type(exc), str(exc)
        # Hosts that convert tool errors into error results lose the exception
        # type, so require at least that the failure is not relabeled as a
        # missing file.
        return None, result.content[0].text

    class DirectoryOperations:
        async def exists(self, path):
            return True

        async def is_file(self, path):
            return False

        async def read_bytes(self, path):
            raise AssertionError("read_bytes must not run for a directory")

    directory_tool = wrap_tool_definition(
        create_read_tool_definition(operations=DirectoryOperations()),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    error_type, message = _error_type_and_message(
        directory_tool, call_id="call-read-dir"
    )

    assert error_type in (None, IsADirectoryError)
    assert "rg --files" not in message

    class LockedOperations:
        async def exists(self, path):
            return True

        async def is_file(self, path):
            return True

        async def read_bytes(self, path):
            raise PermissionError(str(path))

    locked_tool = wrap_tool_definition(
        create_read_tool_definition(operations=LockedOperations()),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    error_type, message = _error_type_and_message(
        locked_tool, call_id="call-read-locked"
    )

    assert error_type in (None, PermissionError)
    assert "rg --files" not in message


def test_per_tool_operations_and_options_are_public_api() -> None:
    from loushang.harness.tools.workspace import (
        BashToolOptions,
        EditOperations,
        EditToolOptions,
        FindOperations,
        FindToolOptions,
        GrepOperations,
        GrepToolOptions,
        LsOperations,
        LsToolOptions,
        ReadOperations,
        ReadToolOptions,
        WriteOperations,
        WriteToolOptions,
    )

    assert ReadOperations is not None
    assert WriteOperations is not None
    assert EditOperations is not None
    assert LsOperations is not None
    assert FindOperations is not None
    assert GrepOperations is not None
    assert ReadToolOptions().operations is None
    assert WriteToolOptions().operations is None
    assert EditToolOptions().operations is None
    assert LsToolOptions().operations is None
    assert FindToolOptions().operations is None
    assert GrepToolOptions().operations is None
    assert BashToolOptions().operations is None


def test_factory_forwards_pi_style_per_tool_options(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import (
        ReadToolOptions,
        ToolsOptions,
        create_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class VirtualReadOperations:
        async def exists(self, path):
            return True

        async def is_file(self, path):
            return True

        async def read_bytes(self, path):
            return b"from read options\n"

    runtime_tool = wrap_tool_definition(
        create_tool_definition(
            "read",
            options=ToolsOptions(
                read=ReadToolOptions(operations=VirtualReadOperations())
            ),
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-read-options", {"path": "remote.txt"})
    )

    assert result.content[0].text == "from read options\n"


def test_write_tool_uses_custom_operations_and_creates_parent_directories(
    tmp_path,
) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_write_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class RecordingOperations:
        def __init__(self) -> None:
            self.mkdir_calls: list[tuple[str, bool, bool]] = []
            self.write_calls: list[tuple[str, str]] = []

        async def exists(self, path):
            return False

        async def is_file(self, path):
            return True

        async def is_dir(self, path):
            return False

        async def mkdir(self, path, *, parents: bool, exist_ok: bool):
            self.mkdir_calls.append((str(path), parents, exist_ok))

        async def write_text(self, path, content: str, *, newline=None):
            self.write_calls.append((str(path), content))

    operations = RecordingOperations()
    runtime_tool = wrap_tool_definition(
        create_write_tool_definition(operations=operations),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-write", {"path": "nested/notes.txt", "content": "alpha\n"}
        )
    )

    assert operations.mkdir_calls == [(str(tmp_path / "nested"), True, True)]
    assert operations.write_calls == [
        (str(tmp_path / "nested" / "notes.txt"), "alpha\n")
    ]
    assert result.details["operation"] == "create"


def test_write_tool_accepts_pi_style_operations(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_write_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class PiWriteOperations:
        def __init__(self) -> None:
            self.mkdir_calls: list[str] = []
            self.write_calls: list[tuple[str, str]] = []

        async def mkdir(self, absolute_dir: str) -> None:
            self.mkdir_calls.append(absolute_dir)

        async def writeFile(self, absolute_path: str, content: str) -> None:
            self.write_calls.append((absolute_path, content))

    operations = PiWriteOperations()
    runtime_tool = wrap_tool_definition(
        create_write_tool_definition(operations=operations),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-pi-write", {"path": "nested/notes.txt", "content": "alpha\n"}
        )
    )

    assert operations.mkdir_calls == [str(tmp_path / "nested")]
    assert operations.write_calls == [
        (str(tmp_path / "nested" / "notes.txt"), "alpha\n")
    ]
    assert result.details["operation"] == "create"


def test_edit_tool_uses_custom_operations(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_edit_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class VirtualOperations:
        def __init__(self) -> None:
            self.content = "alpha\nbeta\n"
            self.write_calls: list[tuple[str, str, str | None]] = []

        async def exists(self, path):
            return True

        async def is_file(self, path):
            return True

        async def read_text(self, path, *, newline=None):
            return self.content

        async def write_text(self, path, content: str, *, newline=None):
            self.write_calls.append((str(path), content, newline))
            self.content = content

    operations = VirtualOperations()
    runtime_tool = wrap_tool_definition(
        create_edit_tool_definition(operations=operations),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-edit",
            {"path": "remote.py", "edits": [{"oldText": "beta", "newText": "BETA"}]},
        )
    )

    assert operations.content == "alpha\nBETA\n"
    assert operations.write_calls == [
        (str(tmp_path / "remote.py"), "alpha\nBETA\n", "")
    ]
    assert result.details["first_changed_line"] == 2


def test_edit_tool_accepts_pi_style_operations(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_edit_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class PiEditOperations:
        def __init__(self) -> None:
            self.content = b"alpha\nbeta\n"
            self.access_paths: list[str] = []
            self.write_calls: list[tuple[str, str]] = []

        async def access(self, absolute_path: str) -> None:
            self.access_paths.append(absolute_path)

        async def readFile(self, absolute_path: str) -> bytes:
            return self.content

        async def writeFile(self, absolute_path: str, content: str) -> None:
            self.write_calls.append((absolute_path, content))
            self.content = content.encode("utf-8")

    operations = PiEditOperations()
    runtime_tool = wrap_tool_definition(
        create_edit_tool_definition(operations=operations),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-pi-edit",
            {"path": "remote.py", "edits": [{"oldText": "beta", "newText": "BETA"}]},
        )
    )

    assert operations.access_paths == [str(tmp_path / "remote.py")]
    assert operations.write_calls == [(str(tmp_path / "remote.py"), "alpha\nBETA\n")]
    assert result.details["first_changed_line"] == 2


def test_ls_tool_uses_custom_operations(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_ls_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class VirtualOperations:
        async def exists(self, path):
            return True

        async def is_dir(self, path):
            return str(path).endswith("pkg") or str(path) == str(tmp_path)

        async def iterdir(self, path):
            return [tmp_path / "z.txt", tmp_path / "pkg"]

    runtime_tool = wrap_tool_definition(
        create_ls_tool_definition(operations=VirtualOperations()),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(runtime_tool.execute("call-ls", {"path": "."}))

    assert result.content[0].text.splitlines() == ["pkg/", "z.txt"]


def test_ls_tool_accepts_pi_style_operations(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_ls_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class Stat:
        def __init__(self, directory: bool) -> None:
            self._directory = directory

        def isDirectory(self) -> bool:
            return self._directory

    class PiLsOperations:
        async def exists(self, absolute_path: str) -> bool:
            return True

        async def stat(self, absolute_path: str) -> Stat:
            return Stat(absolute_path.endswith("pkg") or absolute_path == str(tmp_path))

        async def readdir(self, absolute_path: str) -> list[str]:
            return ["z.txt", "pkg"]

    runtime_tool = wrap_tool_definition(
        create_ls_tool_definition(operations=PiLsOperations()),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(runtime_tool.execute("call-pi-ls", {"path": "."}))

    assert result.content[0].text.splitlines() == ["pkg/", "z.txt"]


def test_find_tool_uses_custom_operations(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_find_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class VirtualOperations:
        async def exists(self, path):
            return True

        async def is_dir(self, path):
            return True

        async def walk_files(self, path):
            return [tmp_path / "src" / "app.py", tmp_path / "README.md"]

    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(operations=VirtualOperations()),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-find", {"pattern": "*.py", "path": "."})
    )

    assert result.content[0].text == "src/app.py"
    assert result.details["matches"] == [{"path": "src/app.py"}]


def test_find_tool_accepts_pi_style_operations(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_find_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class PiFindOperations:
        def __init__(self) -> None:
            self.glob_calls: list[tuple[str, str, dict[str, object]]] = []

        async def exists(self, absolute_path: str) -> bool:
            return True

        async def glob(
            self, pattern: str, cwd: str, options: dict[str, object]
        ) -> list[str]:
            self.glob_calls.append((pattern, cwd, options))
            return ["src/app.py"]

    operations = PiFindOperations()
    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(operations=operations),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-pi-find", {"pattern": "*.py", "path": "."})
    )

    assert result.content[0].text == "src/app.py"
    assert result.details["matches"] == [{"path": "src/app.py"}]
    assert operations.glob_calls == [
        (
            "*.py",
            str(tmp_path),
            {"ignore": ["**/node_modules/**", "**/.git/**"], "limit": 1000},
        )
    ]


def test_grep_tool_uses_custom_operations(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_grep_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class VirtualOperations:
        async def exists(self, path):
            return True

        async def is_dir(self, path):
            return True

        async def walk_files(self, path):
            return [tmp_path / "src" / "app.py"]

        async def read_text(self, path, *, newline=None):
            return "before\nneedle\n"

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(operations=VirtualOperations()),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-grep", {"pattern": "needle", "path": ".", "literal": True}
        )
    )

    assert result.content[0].text == "src/app.py:2:needle"
    assert result.details["matches"] == [
        {"path": "src/app.py", "line_number": 2, "line": "needle"}
    ]


def test_grep_tool_accepts_pi_style_operations(tmp_path) -> None:
    import asyncio

    from loushang.harness.tools.workspace import create_grep_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    target = tmp_path / "src" / "app.py"
    target.parent.mkdir()
    target.write_text("before\nneedle\nafter\n", encoding="utf-8")

    class PiGrepOperations:
        def __init__(self) -> None:
            self.read_paths: list[str] = []

        async def isDirectory(self, absolute_path: str) -> bool:
            return absolute_path.endswith("src")

        async def readFile(self, absolute_path: str) -> str:
            self.read_paths.append(absolute_path)
            return Path(absolute_path).read_text(encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(operations=PiGrepOperations()),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-pi-grep",
            {"pattern": "needle", "path": "src/app.py", "literal": True, "context": 1},
        )
    )

    assert result.content[0].text.splitlines() == [
        "app.py-1-before",
        "app.py:2:needle",
        "app.py-3-after",
    ]
    assert result.details["matches"] == [
        {"path": "app.py", "line_number": 2, "line": "needle"}
    ]
