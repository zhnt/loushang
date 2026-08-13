from __future__ import annotations

import asyncio
import os
import shlex
import sys
from pathlib import Path

import pytest

from loushang.agent import AbortController
from loushang.harness.workspace.exec import (
    ExecLaunchError,
    ExecOutputChunk,
    ExecRequest,
    ExecResult,
    ExecService,
    LocalExecBackend,
    materialize_exec_request,
)


def test_exec_records_normalize_sequences_and_validate_rolling_limit() -> None:
    request = ExecRequest(
        command=["git", "status"],
        env=[["A", "1"], ("B", "2")],
    )
    result = ExecResult(
        exit_code=0,
        stdout_chunks=["out\n"],
        output_chunks=[ExecOutputChunk(stream="stdout", text="out\n")],
    )

    assert request.command == ("git", "status")
    assert request.env == (("A", "1"), ("B", "2"))
    assert result.stdout_chunks == ("out\n",)
    assert result.output_chunks == (ExecOutputChunk(stream="stdout", text="out\n"),)
    assert result.stdio_complete is True
    assert result.stdio_drain_reason is None

    with pytest.raises(ValueError, match="rolling_max_bytes must be >= 1"):
        ExecRequest(command=["true"], rolling_max_bytes=0)
    with pytest.raises(ValueError, match="complete stdio cannot have a drain reason"):
        ExecResult(exit_code=0, stdio_drain_reason="idle_timeout")
    with pytest.raises(ValueError, match="incomplete stdio requires a drain reason"):
        ExecResult(exit_code=0, stdio_complete=False)


def test_exec_request_materialization_preserves_abi_and_freezes_process_state(
    tmp_path: Path,
) -> None:
    request = ExecRequest(
        ("printf", "ok"),
        None,
        (("B", "override"),),
        5,
    )
    inherited = {"A": "one", "B": "base"}

    materialized = materialize_exec_request(
        request,
        environ=inherited,
        cwd=str(tmp_path),
    )
    inherited["A"] = "changed"

    assert request.timeout_seconds == 5
    assert request.env == (("B", "override"),)
    assert request.effective_environment is None
    assert materialized.cwd == str(tmp_path)
    assert materialized.env == (("B", "override"),)
    assert dict(materialized.effective_environment or ()) == {
        "A": "one",
        "B": "override",
    }
    assert (
        materialize_exec_request(materialized, environ={"A": "later"}) is materialized
    )


def test_exec_request_materialization_preserves_explicit_empty_cwd() -> None:
    materialized = materialize_exec_request(
        ExecRequest(command=("true",), cwd=""),
        environ={},
    )

    assert materialized.cwd == ""


def test_exec_request_materialization_merges_windows_environment_case_insensitively(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from loushang.harness.workspace.exec import types as exec_types

    monkeypatch.setattr(
        exec_types,
        "_local_environment_is_case_insensitive",
        lambda: True,
    )

    materialized = materialize_exec_request(
        ExecRequest(
            command=("tool",),
            env=(("PATH", "override"), ("MiXeD", "caller")),
        ),
        environ={"Path": "inherited", "MIXED": "base", "KEEP": "value"},
        cwd=".",
    )

    assert dict(materialized.effective_environment or ()) == {
        "PATH": "override",
        "MiXeD": "caller",
        "KEEP": "value",
    }


def test_exec_service_delegates_to_custom_backend_and_streams_updates(
    tmp_path: Path,
) -> None:
    seen: list[tuple[tuple[str, ...], str | None, object | None]] = []
    updates: list[ExecOutputChunk] = []

    async def backend(request, *, signal=None, on_update=None):
        seen.append((request.command, request.cwd, signal))
        chunk = ExecOutputChunk(stream="stdout", text="remote\n")
        if on_update is not None:
            await on_update(chunk)
        return ExecResult(exit_code=0, stdout="remote\n", output_chunks=(chunk,))

    async def scenario() -> None:
        signal = object()
        service = ExecService(backend=backend)

        async def on_update(chunk: ExecOutputChunk) -> None:
            updates.append(chunk)

        result = await service.execute(
            ExecRequest(command=["deploy"], cwd=str(tmp_path)),
            signal=signal,
            on_update=on_update,
        )

        assert result.stdout == "remote\n"
        assert seen == [(("deploy",), str(tmp_path), signal)]

    asyncio.run(scenario())
    assert updates == [ExecOutputChunk(stream="stdout", text="remote\n")]


def test_exec_service_custom_backend_receives_one_frozen_process_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[ExecRequest] = []
    original_cwd = tmp_path / "original"
    changed_cwd = tmp_path / "changed"
    original_cwd.mkdir()
    changed_cwd.mkdir()
    monkeypatch.chdir(original_cwd)
    monkeypatch.setenv("HARNESS_EXEC_SNAPSHOT", "original")

    async def backend(request, **kwargs):
        del kwargs
        captured.append(request)
        monkeypatch.chdir(changed_cwd)
        monkeypatch.setenv("HARNESS_EXEC_SNAPSHOT", "changed")
        await asyncio.sleep(0)
        return ExecResult(exit_code=0)

    asyncio.run(
        ExecService(backend=backend).execute(
            ExecRequest(
                command=["remote"],
                env=(("HARNESS_EXEC_OVERRIDE", "caller"),),
            )
        )
    )

    request = captured[0]
    assert request.cwd == str(original_cwd)
    assert request.env == (("HARNESS_EXEC_OVERRIDE", "caller"),)
    assert (
        dict(request.effective_environment or ())["HARNESS_EXEC_SNAPSHOT"] == "original"
    )
    assert (
        dict(request.effective_environment or ())["HARNESS_EXEC_OVERRIDE"] == "caller"
    )


def test_exec_service_rejects_invalid_backend_result() -> None:
    async def backend(request, *, signal=None, on_update=None):
        del request, signal, on_update
        return object()

    async def scenario() -> None:
        with pytest.raises(TypeError, match="exec backend must return ExecResult"):
            await ExecService(backend=backend).execute(ExecRequest(command=["invalid"]))

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("cwd_factory", "expected_kind"),
    [
        (lambda root: root / "missing", "cwd_not_found"),
        (lambda root: root / "file", "cwd_not_directory"),
    ],
)
def test_exec_service_reports_typed_cwd_launch_errors(
    tmp_path: Path,
    cwd_factory,
    expected_kind: str,
) -> None:
    cwd = cwd_factory(tmp_path)
    if expected_kind == "cwd_not_directory":
        cwd.write_text("not a directory", encoding="utf-8")

    async def scenario() -> None:
        with pytest.raises(ExecLaunchError) as raised:
            await ExecService().execute(
                ExecRequest(command=("missing-tool",), cwd=str(cwd))
            )
        assert raised.value.kind == expected_kind
        assert raised.value.cwd == str(cwd)

    asyncio.run(scenario())


def test_exec_service_reports_typed_executable_launch_error(tmp_path: Path) -> None:
    async def scenario() -> None:
        with pytest.raises(ExecLaunchError) as raised:
            await ExecService().execute(
                ExecRequest(
                    command=("loushang-command-that-does-not-exist",),
                    cwd=str(tmp_path),
                )
            )
        assert raised.value.kind == "executable_not_found"
        assert raised.value.executable == "loushang-command-that-does-not-exist"

    asyncio.run(scenario())


def test_exec_service_runs_subprocess_and_preserves_per_stream_order(
    tmp_path: Path,
) -> None:
    updates: list[tuple[str, str]] = []

    async def scenario() -> None:
        async def on_update(chunk: ExecOutputChunk) -> None:
            updates.append((chunk.stream, chunk.text))

        result = await ExecService().execute(
            ExecRequest(
                command=[
                    "/usr/bin/env",
                    "python3",
                    "-c",
                    (
                        "import sys, time; "
                        "sys.stdout.write('out1\\n'); sys.stdout.flush(); "
                        "time.sleep(0.05); "
                        "sys.stderr.write('err1\\n'); sys.stderr.flush(); "
                        "time.sleep(0.05); "
                        "sys.stdout.write('out2\\n'); sys.stdout.flush()"
                    ),
                ],
                cwd=str(tmp_path),
            ),
            on_update=on_update,
        )

        assert result.exit_code == 0
        assert result.stdout == "out1\nout2\n"
        assert result.stderr == "err1\n"
        observed = tuple((chunk.stream, chunk.text) for chunk in result.output_chunks)
        # stdout and stderr are independent pipes. Preserve the order within each
        # stream, while treating their merged order as the host's observation order.
        assert tuple(text for stream, text in observed if stream == "stdout") == (
            "out1\n",
            "out2\n",
        )
        assert tuple(text for stream, text in observed if stream == "stderr") == (
            "err1\n",
        )
        assert updates == list(observed)

    asyncio.run(scenario())


def test_exec_service_streams_output_larger_than_asyncio_line_limit(
    tmp_path: Path,
) -> None:
    expected = "x" * (128 * 1024)

    async def scenario() -> None:
        result = await asyncio.wait_for(
            ExecService().execute(
                ExecRequest(
                    command=[
                        sys.executable,
                        "-c",
                        "import sys; sys.stdout.write('x' * (128 * 1024))",
                    ],
                    cwd=str(tmp_path),
                )
            ),
            timeout=2,
        )

        assert result.exit_code == 0
        assert result.stdout == expected
        assert result.stdout_total_bytes == len(expected)
        assert result.stdout_total_lines == 1

    asyncio.run(scenario())


def test_exec_service_incrementally_decodes_split_utf8_sequence(tmp_path: Path) -> None:
    async def scenario() -> None:
        result = await ExecService().execute(
            ExecRequest(
                command=[
                    sys.executable,
                    "-c",
                    (
                        "import os, time; "
                        "data='😀'.encode(); "
                        "os.write(1, data[:2]); time.sleep(0.05); "
                        "os.write(1, data[2:])"
                    ),
                ],
                cwd=str(tmp_path),
            )
        )

        assert result.stdout == "😀"
        assert result.stdout_total_bytes == 4
        assert result.stdout_total_lines == 1

    asyncio.run(scenario())


def test_exec_service_waits_for_delayed_stdio_after_root_exit(tmp_path: Path) -> None:
    child_script = (
        "import sys, time; "
        "sys.stdout.write('\\n'); sys.stdout.flush(); "
        "time.sleep(0.2); "
        "sys.stdout.write('formatted\\n'); sys.stdout.flush()"
    )
    root_script = (
        "import subprocess, sys; "
        f"subprocess.Popen([sys.executable, '-c', {child_script!r}])"
    )

    async def scenario() -> None:
        result = await asyncio.wait_for(
            ExecService().execute(
                ExecRequest(
                    command=(sys.executable, "-c", root_script),
                    cwd=str(tmp_path),
                )
            ),
            timeout=2,
        )

        assert result.stdout.splitlines() == ["", "formatted"]
        assert result.stdio_complete is True
        assert result.stdio_drain_reason is None

    asyncio.run(scenario())


def test_exec_service_hard_limits_active_descendant_stdio(tmp_path: Path) -> None:
    child_script = (
        "import sys, time; "
        "[(sys.stdout.write('x'), sys.stdout.flush(), time.sleep(0.02)) "
        "for _ in range(100)]"
    )
    root_script = (
        "import subprocess, sys; sys.stdout.write('r'); sys.stdout.flush(); "
        f"subprocess.Popen([sys.executable, '-c', {child_script!r}])"
    )
    service = ExecService(
        backend=LocalExecBackend(
            post_exit_stdio_grace_seconds=0.25,
            post_exit_stdio_hard_timeout_seconds=0.25,
        )
    )

    async def scenario() -> None:
        started_at = asyncio.get_running_loop().time()
        result = await asyncio.wait_for(
            service.execute(
                ExecRequest(
                    command=(sys.executable, "-c", root_script),
                    cwd=str(tmp_path),
                )
            ),
            timeout=2,
        )

        assert asyncio.get_running_loop().time() - started_at < 1
        assert 0 < len(result.stdout) < 101
        assert result.stdio_complete is False
        assert result.stdio_drain_reason == "hard_timeout"

    asyncio.run(scenario())


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group regression")
def test_exec_service_returns_when_descendant_holds_pipe_after_parent_exit(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "late-descendant-output"

    async def scenario() -> None:
        started_at = asyncio.get_running_loop().time()
        result = await asyncio.wait_for(
            ExecService(
                backend=LocalExecBackend(
                    post_exit_stdio_grace_seconds=0.1,
                    post_exit_stdio_hard_timeout_seconds=0.5,
                )
            ).execute(
                ExecRequest(
                    command=[
                        "/bin/sh",
                        "-c",
                        (
                            "printf done; "
                            f"(sleep 0.8; printf late > {shlex.quote(str(marker))}) &"
                        ),
                    ],
                    cwd=str(tmp_path),
                )
            ),
            timeout=2,
        )

        assert result.exit_code == 0
        assert result.stdout == "done"
        assert result.stdio_complete is False
        assert result.stdio_drain_reason == "idle_timeout"
        assert asyncio.get_running_loop().time() - started_at < 0.5
        await asyncio.sleep(0.9)
        assert marker.read_text(encoding="utf-8") == "late"

    asyncio.run(scenario())


def test_exec_service_accepts_a_process_that_exits_without_reading_stdin(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        result = await ExecService().execute(
            ExecRequest(
                command=[sys.executable, "-c", "raise SystemExit(0)"],
                cwd=str(tmp_path),
                stdin="ignored\n" * 131_072,
            )
        )

        assert result.exit_code == 0

    asyncio.run(scenario())


def test_exec_service_builds_tail_preview_and_full_output_artifact(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        result = await ExecService().execute(
            ExecRequest(
                command=[
                    "/usr/bin/env",
                    "python3",
                    "-c",
                    "print('a'); print('b'); print('c'); print('d')",
                ],
                cwd=str(tmp_path),
                preview_max_lines=2,
                preview_max_bytes=1024,
                artifact_dir=str(tmp_path),
            )
        )

        assert result.stdout_preview == "c\nd\n"
        assert result.stdout_truncated is True
        assert result.stdout_truncated_by == "lines"
        assert result.stdout_artifact_path is not None
        assert (
            Path(result.stdout_artifact_path).read_text(encoding="utf-8")
            == "a\nb\nc\nd\n"
        )

    asyncio.run(scenario())


def test_exec_service_rolls_capture_without_losing_artifact(tmp_path: Path) -> None:
    full_output = "".join(f"line-{index:04d}\n" for index in range(400))

    async def scenario() -> None:
        result = await ExecService().execute(
            ExecRequest(
                command=[
                    "/usr/bin/env",
                    "python3",
                    "-c",
                    "for i in range(400): print(f'line-{i:04d}')",
                ],
                cwd=str(tmp_path),
                preview_max_lines=2,
                preview_max_bytes=1024,
                artifact_dir=str(tmp_path),
                capture_full_output=False,
                rolling_max_bytes=512,
            )
        )

        assert result.stdout != full_output
        assert len(result.stdout.encode("utf-8")) <= 512
        assert result.stdout_preview == "line-0398\nline-0399\n"
        assert result.stdout_artifact_path is not None
        assert (
            Path(result.stdout_artifact_path).read_text(encoding="utf-8") == full_output
        )

    asyncio.run(scenario())


@pytest.mark.parametrize("capture_full_output", [True, False])
def test_exec_service_discards_unretained_output_artifacts(
    tmp_path: Path,
    capture_full_output: bool,
) -> None:
    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    async def scenario() -> None:
        result = await ExecService().execute(
            ExecRequest(
                command=[
                    "/usr/bin/env",
                    "python3",
                    "-c",
                    "for i in range(400): print(f'line-{i:04d}')",
                ],
                cwd=str(tmp_path),
                preview_max_lines=2,
                preview_max_bytes=1024,
                artifact_dir=str(artifact_dir),
                capture_full_output=capture_full_output,
                retain_output_artifacts=False,
                rolling_max_bytes=512,
            )
        )

        assert result.stdout_preview == "line-0398\nline-0399\n"
        assert result.stdout_truncated is True
        assert result.stdout_artifact_path is None
        assert result.stderr_artifact_path is None
        assert list(artifact_dir.iterdir()) == []

    asyncio.run(scenario())


def test_exec_service_marks_timeout_and_cancellation(tmp_path: Path) -> None:
    async def scenario() -> None:
        timed_out = await ExecService().execute(
            ExecRequest(
                command=["/bin/sh", "-c", "printf timeout; sleep 1"],
                cwd=str(tmp_path),
                timeout_seconds=0.05,
            )
        )
        assert timed_out.timed_out is True
        assert timed_out.cancelled is False
        assert timed_out.stdout == "timeout"

        controller = AbortController()

        async def abort_soon() -> None:
            await asyncio.sleep(0.05)
            controller.abort()

        asyncio.create_task(abort_soon())
        cancelled = await ExecService().execute(
            ExecRequest(
                command=["/bin/sh", "-c", "printf cancelled; sleep 1"],
                cwd=str(tmp_path),
            ),
            signal=controller.signal,
        )
        assert cancelled.cancelled is True
        assert cancelled.timed_out is False
        assert cancelled.stdout == "cancelled"

    asyncio.run(scenario())


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group regression")
def test_exec_service_task_cancellation_kills_process_tree(tmp_path: Path) -> None:
    marker = tmp_path / "cancelled-descendant"

    async def scenario() -> None:
        task = asyncio.create_task(
            ExecService().execute(
                ExecRequest(
                    command=(
                        "/bin/sh",
                        "-c",
                        (
                            "printf started; "
                            f"(sleep 0.5; printf late > {shlex.quote(str(marker))}) & "
                            "sleep 2"
                        ),
                    ),
                    cwd=str(tmp_path),
                )
            )
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        await asyncio.sleep(0.6)
        assert not marker.exists()

    asyncio.run(scenario())
