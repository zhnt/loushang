from __future__ import annotations

import asyncio


def _tool_context_provider(*, cwd: str):
    from loushang.harness.tools.workspace import ToolContext

    def _provider(*, tool_call_id: str) -> ToolContext:
        return ToolContext(tool_call_id=tool_call_id, cwd=cwd)

    return _provider


def test_bash_provider_schema_is_pi_style_while_internal_schema_stays_enhanced() -> (
    None
):
    from loushang.harness.tools.workspace import create_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    definition = create_tool_definition("bash")
    internal_properties = definition.parameters["properties"]

    assert "cwd" in internal_properties
    assert "env" in internal_properties
    assert "artifact_dir" in internal_properties
    assert "capture_full_output" in internal_properties
    assert "rolling_max_bytes" in internal_properties

    provider_parameters = wrap_tool_definition(definition).parameters

    assert provider_parameters == {
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "number"},
        },
        "required": ["command"],
        "additionalProperties": False,
    }


def test_bash_provider_schema_does_not_block_internal_enhanced_arguments(
    tmp_path,
) -> None:
    from loushang.harness.tools.workspace import ToolsOptions, create_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecResult

    class RecordingOperations:
        def __init__(self) -> None:
            self.requests: list[object] = []

        def execute(self, request, *, signal=None, on_update=None):
            del signal, on_update
            self.requests.append(request)
            return ExecResult(exit_code=0, stdout="ok\n")

    operations = RecordingOperations()
    runtime_tool = wrap_tool_definition(
        create_tool_definition("bash", options=ToolsOptions(bash_operations=operations))
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-bash-enhanced-args",
            {
                "command": "printf ok",
                "cwd": str(tmp_path),
                "env": [["LOUSHANG_TEST", "1"]],
                "stdin": "input",
                "artifact_dir": str(tmp_path / "artifacts"),
                "capture_full_output": True,
                "rolling_max_bytes": 4096,
                "timeout_seconds": 2,
            },
        )
    )

    request = operations.requests[0]
    assert result.content[0].text == "ok\n"
    assert request.cwd == str(tmp_path)
    assert request.env == (("LOUSHANG_TEST", "1"),)
    assert request.stdin == "input"
    assert request.artifact_dir == str(tmp_path / "artifacts")
    assert request.capture_full_output is True
    assert request.rolling_max_bytes == 4096
    assert request.timeout_seconds == 2


def test_bash_defaults_to_session_cwd_from_tool_context(tmp_path) -> None:
    from loushang.harness.tools.workspace import ToolsOptions, create_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecResult

    class RecordingOperations:
        def __init__(self) -> None:
            self.requests: list[object] = []

        def execute(self, request, *, signal=None, on_update=None):
            del signal, on_update
            self.requests.append(request)
            return ExecResult(exit_code=0, stdout="ok\n")

    operations = RecordingOperations()
    runtime_tool = wrap_tool_definition(
        create_tool_definition(
            "bash", options=ToolsOptions(bash_operations=operations)
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-bash-context-cwd", {"command": "pwd"})
    )

    assert result.content[0].text == "ok\n"
    assert operations.requests[0].cwd == str(tmp_path)


def test_bash_golden_result_keeps_stderr_model_visible_and_preserves_artifacts(
    tmp_path,
) -> None:
    from loushang.harness.tools.workspace import ToolsOptions, create_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecResult

    stdout_path = str(tmp_path / "stdout.log")
    stderr_path = str(tmp_path / "stderr.log")

    class ArtifactOperations:
        def execute(self, request, *, signal=None, on_update=None):
            del request, signal, on_update
            return ExecResult(
                exit_code=0,
                stdout="out\n",
                stderr="err\n",
                stdout_artifact_path=stdout_path,
                stderr_artifact_path=stderr_path,
                stdio_complete=False,
                stdio_drain_reason="idle_timeout",
            )

    runtime_tool = wrap_tool_definition(
        create_tool_definition(
            "bash", options=ToolsOptions(bash_operations=ArtifactOperations())
        )
    )

    result = asyncio.run(
        runtime_tool.execute("call-bash-artifact-details", {"command": "printf out"})
    )

    assert result.content[0].text == "out\nerr\n"
    assert result.details["stderr"] == "err\n"
    assert result.details["full_output_path"] == stdout_path
    assert result.details["stdout_artifact_path"] == stdout_path
    assert result.details["stderr_artifact_path"] == stderr_path
    assert result.details["stdio_complete"] is False
    assert result.details["stdio_drain_reason"] == "idle_timeout"


def test_find_fd_output_preserves_directory_suffix(tmp_path) -> None:
    from loushang.harness.tools.workspace import ToolsOptions, create_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    fake_fd = tmp_path / "fd"
    fake_fd.write_text("#!/bin/sh\nprintf 'src/\\nsrc/main.py\\n'\n", encoding="utf-8")
    fake_fd.chmod(0o755)

    class Resolver:
        def resolve_tool(self, name: str) -> str | None:
            return str(fake_fd) if name == "fd" else None

    runtime_tool = wrap_tool_definition(
        create_tool_definition(
            "find", options=ToolsOptions(external_tool_resolver=Resolver())
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute("call-find-directories", {"pattern": "src", "path": "."})
    )

    assert result.content[0].text == "src/\nsrc/main.py"
    assert result.details["matches"] == [{"path": "src/"}, {"path": "src/main.py"}]


def test_find_fd_output_normalizes_absolute_paths_and_exact_limit(tmp_path) -> None:
    from loushang.harness.tools.workspace import ToolsOptions, create_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.py").write_text("pass", encoding="utf-8")
    fake_fd = tmp_path / "fd"
    fake_fd.write_text(
        '#!/bin/sh\nprintf \'%s\\r\\n%s\\r\\n\' "$PWD/src/" "$PWD/src/main.py"\n',
        encoding="utf-8",
    )
    fake_fd.chmod(0o755)

    class Resolver:
        def resolve_tool(self, name: str) -> str | None:
            return str(fake_fd) if name == "fd" else None

    runtime_tool = wrap_tool_definition(
        create_tool_definition(
            "find", options=ToolsOptions(external_tool_resolver=Resolver())
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-find-absolute", {"pattern": "src", "path": ".", "limit": 2}
        )
    )

    assert result.content[0].text == (
        "src/\nsrc/main.py\n\n[2 results limit reached. Use limit=4 for more, or refine pattern]"
    )
    assert result.details["matches"] == [{"path": "src/"}, {"path": "src/main.py"}]
    assert result.details["result_limit_reached"] is True
    assert result.details["result_limit"] == 2


def test_find_required_external_tool_uses_pi_unavailable_error(tmp_path) -> None:
    import pytest

    from loushang.harness.tools.workspace import (
        FindToolOptions,
        create_find_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class MissingResolver:
        def resolve_tool(self, name: str) -> None:
            del name
            return None

    runtime_tool = wrap_tool_definition(
        create_find_tool_definition(
            options=FindToolOptions(
                external_tool_resolver=MissingResolver(), require_external_tool=True
            )
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(
        RuntimeError, match="fd is not available and could not be downloaded"
    ):
        asyncio.run(
            runtime_tool.execute(
                "call-find-unavailable", {"pattern": "*.py", "path": "."}
            )
        )


def test_grep_rg_output_normalizes_absolute_paths_and_exact_limit(tmp_path) -> None:
    from loushang.harness.tools.workspace import (
        GrepToolOptions,
        create_grep_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "main.py").write_text("needle 1\nneedle 2\n", encoding="utf-8")
    fake_rg = tmp_path / "rg"
    fake_rg.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' "
        '\'{"type":"match","data":{"path":{"text":"\'$PWD\'/src/main.py"},'
        '"line_number":1,"lines":{"text":"needle 1\\n"}}}\' '
        '\'{"type":"match","data":{"path":{"text":"\'$PWD\'/src/main.py"},'
        '"line_number":2,"lines":{"text":"needle 2\\n"}}}\'\n',
        encoding="utf-8",
    )
    fake_rg.chmod(0o755)

    class Resolver:
        def resolve_tool(self, name: str) -> str | None:
            return str(fake_rg) if name == "rg" else None

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(
            options=GrepToolOptions(external_tool_resolver=Resolver())
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(
        runtime_tool.execute(
            "call-grep-absolute",
            {"pattern": "needle", "path": ".", "literal": True, "limit": 2},
        )
    )

    assert result.content[0].text == (
        "src/main.py:1:needle 1\n"
        "src/main.py:2:needle 2\n\n"
        "[2 matches limit reached. Use limit=4 for more, or refine pattern]"
    )
    assert result.details["matches"] == [
        {"path": "src/main.py", "line_number": 1, "line": "needle 1"},
        {"path": "src/main.py", "line_number": 2, "line": "needle 2"},
    ]
    assert result.details["match_limit_reached"] is True
    assert result.details["match_limit"] == 2


def test_grep_required_external_tool_uses_pi_unavailable_error(tmp_path) -> None:
    import pytest

    from loushang.harness.tools.workspace import (
        GrepToolOptions,
        create_grep_tool_definition,
    )
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    class MissingResolver:
        def resolve_tool(self, name: str) -> None:
            del name
            return None

    runtime_tool = wrap_tool_definition(
        create_grep_tool_definition(
            options=GrepToolOptions(
                external_tool_resolver=MissingResolver(), require_external_tool=True
            )
        ),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(
        RuntimeError,
        match=r"ripgrep \(rg\) is not available and could not be downloaded",
    ):
        asyncio.run(
            runtime_tool.execute(
                "call-grep-unavailable", {"pattern": "needle", "path": "."}
            )
        )


def test_read_offset_beyond_eof_uses_pi_error_boundary(tmp_path) -> None:
    import pytest

    from loushang.harness.tools.workspace import create_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "notes.txt").write_text("alpha\nbeta\n", encoding="utf-8")
    runtime_tool = wrap_tool_definition(
        create_tool_definition("read"),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    with pytest.raises(
        ValueError, match=r"Offset 5 is beyond end of file \(2 lines total\)"
    ):
        asyncio.run(
            runtime_tool.execute(
                "call-read-offset-eof", {"path": "notes.txt", "offset": 5}
            )
        )


def test_bash_timeout_and_cancelled_results_use_pi_error_boundaries(tmp_path) -> None:
    import pytest

    from loushang.harness.tools.workspace import ToolsOptions, create_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition
    from loushang.harness.workspace.exec import ExecResult

    class TimeoutOperations:
        def execute(self, request, *, signal=None, on_update=None):
            del request, signal, on_update
            return ExecResult(
                exit_code=-1,
                stdout="partial stdout\n",
                stderr="partial stderr\n",
                timed_out=True,
            )

    timeout_tool = wrap_tool_definition(
        create_tool_definition(
            "bash", options=ToolsOptions(bash_operations=TimeoutOperations())
        )
    )

    with pytest.raises(TimeoutError) as timeout_exc:
        asyncio.run(
            timeout_tool.execute(
                "call-bash-timeout", {"command": "sleep 10", "timeout": 3}
            )
        )

    timeout_message = str(timeout_exc.value)
    assert "partial stdout" in timeout_message
    assert "partial stderr" in timeout_message
    assert "Command timed out after 3 seconds" in timeout_message

    class CancelledOperations:
        def execute(self, request, *, signal=None, on_update=None):
            del request, signal, on_update
            return ExecResult(exit_code=-1, stdout="partial\n", cancelled=True)

    cancelled_tool = wrap_tool_definition(
        create_tool_definition(
            "bash", options=ToolsOptions(bash_operations=CancelledOperations())
        )
    )

    with pytest.raises(RuntimeError) as cancelled_exc:
        asyncio.run(
            cancelled_tool.execute("call-bash-cancelled", {"command": "sleep 10"})
        )

    cancelled_message = str(cancelled_exc.value)
    assert "partial" in cancelled_message
    assert "Command aborted" in cancelled_message


def test_ls_output_uses_case_insensitive_pi_ordering(tmp_path) -> None:
    from loushang.harness.tools.workspace import create_tool_definition
    from loushang.harness.tools.workspace.wrapper import wrap_tool_definition

    (tmp_path / "z.txt").write_text("z", encoding="utf-8")
    (tmp_path / "B.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")

    runtime_tool = wrap_tool_definition(
        create_tool_definition("ls"),
        context_provider=_tool_context_provider(cwd=str(tmp_path)),
    )

    result = asyncio.run(runtime_tool.execute("call-ls-ordering", {"path": "."}))

    assert result.content[0].text == "a.txt\nB.txt\nz.txt"
