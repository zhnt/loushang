from __future__ import annotations


def test_exec_service_runs_command_and_returns_stdout(tmp_path) -> None:
    import asyncio

    from loushang.harness.workspace.exec import ExecRequest, ExecService

    async def scenario() -> None:
        service = ExecService()
        result = await service.execute(
            ExecRequest(command=["/bin/sh", "-c", "printf hello"], cwd=str(tmp_path))
        )
        assert result.exit_code == 0
        assert result.stdout == "hello"
        assert result.stderr == ""

    asyncio.run(scenario())


def test_exec_service_returns_nonzero_exit_status(tmp_path) -> None:
    import asyncio

    from loushang.harness.workspace.exec import ExecRequest, ExecService

    async def scenario() -> None:
        service = ExecService()
        result = await service.execute(
            ExecRequest(command=["/bin/sh", "-c", "printf no >&2; exit 7"], cwd=str(tmp_path))
        )
        assert result.exit_code == 7
        assert result.stderr == "no"

    asyncio.run(scenario())


def test_exec_service_marks_timeout_and_kills_process(tmp_path) -> None:
    import asyncio

    from loushang.harness.workspace.exec import ExecRequest, ExecService

    async def scenario() -> None:
        service = ExecService()
        result = await service.execute(
            ExecRequest(
                command=["/bin/sh", "-c", 'printf out; printf err >&2; sleep 1'],
                cwd=str(tmp_path),
                timeout_seconds=0.05,
            )
        )
        assert result.timed_out is True
        assert result.stdout == "out"
        assert result.stderr == "err"
        assert result.exit_code != 0

    asyncio.run(scenario())


def test_exec_service_timeout_kills_process_tree_and_keeps_output(tmp_path) -> None:
    import asyncio

    from loushang.harness.workspace.exec import ExecRequest, ExecService

    marker = tmp_path / "child-still-running"

    async def scenario() -> None:
        service = ExecService()
        result = await service.execute(
            ExecRequest(
                command=[
                    "/bin/sh",
                    "-c",
                    f"printf before; (sleep 0.4; printf child > {marker}) & sleep 1",
                ],
                cwd=str(tmp_path),
                timeout_seconds=0.05,
            )
        )
        assert result.timed_out is True
        assert result.stdout == "before"

    asyncio.run(scenario())
    import time

    time.sleep(0.6)
    assert not marker.exists()


def test_exec_service_applies_request_env_to_subprocess(tmp_path) -> None:
    import asyncio

    from loushang.harness.workspace.exec import ExecRequest, ExecService

    async def scenario() -> None:
        service = ExecService()
        result = await service.execute(
            ExecRequest(
                command=["/bin/sh", "-c", 'printf %s "$LUS_TEST_VAR"'],
                cwd=str(tmp_path),
                env=[("LUS_TEST_VAR", "applied")],
            )
        )
        assert result.exit_code == 0
        assert result.stdout == "applied"
        assert result.stderr == ""

    asyncio.run(scenario())


def test_exec_service_honors_cwd(tmp_path) -> None:
    import asyncio

    from loushang.harness.workspace.exec import ExecRequest, ExecService

    async def scenario() -> None:
        service = ExecService()
        result = await service.execute(
            ExecRequest(command=["/bin/sh", "-c", "pwd"], cwd=str(tmp_path))
        )
        assert result.exit_code == 0
        assert result.stdout == f"{tmp_path}\n"
        assert result.stderr == ""

    asyncio.run(scenario())


def test_exec_service_streams_output_updates_and_records_chunks(tmp_path) -> None:
    import asyncio

    from loushang.harness.workspace.exec import ExecRequest, ExecService

    updates: list[tuple[str, str]] = []

    async def scenario() -> None:
        service = ExecService()

        async def on_update(update) -> None:
            updates.append((update.stream, update.text))

        result = await service.execute(
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
        assert result.stdout_chunks == ("out1\n", "out2\n")
        assert result.stderr_chunks == ("err1\n",)
        assert tuple((chunk.stream, chunk.text) for chunk in result.output_chunks) == (
            ("stdout", "out1\n"),
            ("stderr", "err1\n"),
            ("stdout", "out2\n"),
        )

    asyncio.run(scenario())

    assert updates == [("stdout", "out1\n"), ("stderr", "err1\n"), ("stdout", "out2\n")]


def test_exec_service_captures_truncated_previews_and_full_output_artifacts(tmp_path) -> None:
    import asyncio

    from loushang.harness.workspace.exec import ExecRequest, ExecService

    async def scenario() -> None:
        service = ExecService()
        result = await service.execute(
            ExecRequest(
                command=["/usr/bin/env", "python3", "-c", "print('a'); print('b'); print('c'); print('d')"],
                cwd=str(tmp_path),
                preview_max_lines=2,
                preview_max_bytes=1024,
                artifact_dir=str(tmp_path),
            )
        )
        assert result.exit_code == 0
        assert result.stdout == "a\nb\nc\nd\n"
        assert result.stdout_preview == "c\nd\n"
        assert result.stdout_truncated is True
        assert result.stdout_truncated_by == "lines"
        assert result.stdout_artifact_path is not None
        assert result.stderr_preview == ""
        assert result.stderr_artifact_path is None
        from pathlib import Path

        assert Path(result.stdout_artifact_path).read_text(encoding="utf-8") == "a\nb\nc\nd\n"

    asyncio.run(scenario())


def test_exec_service_can_roll_output_without_retaining_full_stdout(tmp_path) -> None:
    import asyncio
    from pathlib import Path

    from loushang.harness.workspace.exec import ExecRequest, ExecService

    full_output = "".join(f"line-{index:04d}\n" for index in range(3000))

    async def scenario() -> None:
        service = ExecService()
        result = await service.execute(
            ExecRequest(
                command=[
                    "/usr/bin/env",
                    "python3",
                    "-c",
                    "for i in range(3000): print(f'line-{i:04d}')",
                ],
                cwd=str(tmp_path),
                preview_max_lines=2,
                preview_max_bytes=1024,
                artifact_dir=str(tmp_path),
                capture_full_output=False,
                rolling_max_bytes=2048,
            )
        )

        assert result.exit_code == 0
        assert result.stdout != full_output
        assert len(result.stdout.encode("utf-8")) <= 2048
        assert result.stdout_preview == "line-2998\nline-2999\n"
        assert result.stdout_truncated is True
        assert result.stdout_truncated_by == "lines"
        assert result.stdout_artifact_path is not None
        assert Path(result.stdout_artifact_path).read_text(encoding="utf-8") == full_output

    asyncio.run(scenario())


def test_exec_service_marks_cancelled_and_kills_process(tmp_path) -> None:
    import asyncio

    from loushang.agent import AbortController
    from loushang.harness.workspace.exec import ExecRequest, ExecService

    async def scenario() -> None:
        service = ExecService()
        controller = AbortController()

        async def abort_soon() -> None:
            await asyncio.sleep(0.05)
            controller.abort()

        asyncio.create_task(abort_soon())
        result = await service.execute(
            ExecRequest(
                command=["/bin/sh", "-c", 'printf out; printf err >&2; sleep 1'],
                cwd=str(tmp_path),
            ),
            signal=controller.signal,
        )
        assert result.cancelled is True
        assert result.timed_out is False
        assert result.stdout == "out"
        assert result.stderr == "err"
        assert result.exit_code != 0

    asyncio.run(scenario())


def test_exec_service_delegates_to_custom_backend(tmp_path) -> None:
    import asyncio

    from loushang.harness.workspace.exec import (
        ExecOutputChunk,
        ExecRequest,
        ExecResult,
        ExecService,
    )

    seen: list[tuple[tuple[str, ...], str | None, object | None]] = []
    updates: list[tuple[str, str]] = []

    async def backend(request, *, signal=None, on_update=None):
        seen.append((request.command, request.cwd, signal))
        if on_update is not None:
            await on_update(ExecOutputChunk(stream="stdout", text="remote\n"))
        return ExecResult(
            exit_code=0,
            stdout="remote\n",
            stdout_chunks=("remote\n",),
            output_chunks=(ExecOutputChunk(stream="stdout", text="remote\n"),),
        )

    async def scenario() -> None:
        signal = object()
        service = ExecService(backend=backend)

        async def on_update(update) -> None:
            updates.append((update.stream, update.text))

        result = await service.execute(
            ExecRequest(command=["deploy"], cwd=str(tmp_path)),
            signal=signal,
            on_update=on_update,
        )

        assert result.stdout == "remote\n"
        assert tuple((chunk.stream, chunk.text) for chunk in result.output_chunks) == (("stdout", "remote\n"),)
        assert seen == [(("deploy",), str(tmp_path), signal)]

    asyncio.run(scenario())

    assert updates == [("stdout", "remote\n")]
