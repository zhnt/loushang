from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from loushang.harness.workspace.exec import ExecRequest, ExecResult, ExecService
from loushang.harness.workspace.exec import service as module


class Sink:
    def __init__(self):
        self.stopped = False
        self.chunks = []

    async def append(self, chunk):
        if not self.stopped:
            assert len(chunk.text) <= 16 * 1024
            self.chunks.append(chunk)

    def stop_accepting(self):
        self.stopped = True


@pytest.mark.parametrize("base", [module.LocalExecBackend, module.AuthorizedProcessExecBackend])
def test_backend_call_wrapper_requires_explicit_capture_support(base):
    class Guard(base):
        async def __call__(self, *args, **kwargs):
            pytest.fail("ordinary policy must not be bypassed implicitly")

    class Explicit(Guard):
        async def execute_captured(self, *args, **kwargs):
            return ExecResult(exit_code=9)

    options = {} if base is module.LocalExecBackend else {"launcher": SimpleNamespace(start=lambda: None)}
    assert ExecService(backend=Guard(**options)).capture_executor() is None
    capability = ExecService(backend=Explicit(**options)).capture_executor()
    assert capability is not None
    assert asyncio.run(capability.execute(ExecRequest(("unused",)), capture=Sink())).exit_code == 9


def test_unsupported_backend_and_execute_wrapper_have_no_capture_capability():
    def ordinary(*args, **kwargs):
        pytest.fail("capability lookup executed backend")

    class Wrapper(ExecService):
        async def execute(self, *args, **kwargs):
            pytest.fail("capability lookup executed wrapper")

    assert ExecService(backend=ordinary).capture_executor() is None
    assert Wrapper().capture_executor() is None


def test_capability_remains_bound_to_original_backend():
    asyncio.run(_capability_remains_bound_to_original_backend())


async def _capability_remains_bound_to_original_backend():
    calls = []

    class Backend:
        async def execute_captured(self, request, **kwargs):
            calls.append(self)
            return ExecResult(exit_code=7)

    original = Backend()
    service = ExecService(backend=original)
    capability = service.capture_executor()
    service._backend = Backend()
    assert capability is not None
    assert (await capability.execute(ExecRequest(("unused",)), capture=Sink())).exit_code == 7
    assert calls == [original]


def test_local_capture_clamps_all_buffers_and_never_uses_old_file_path(tmp_path, monkeypatch):
    asyncio.run(_local_capture_clamps_all_buffers_and_never_uses_old_file_path(tmp_path, monkeypatch))


async def _local_capture_clamps_all_buffers_and_never_uses_old_file_path(tmp_path, monkeypatch):
    monkeypatch.setattr(module.tempfile, "mkstemp", lambda *a, **k: pytest.fail("old artifact path"))
    sink = Sink()
    capability = ExecService().capture_executor()
    assert capability is not None
    result = await capability.execute(ExecRequest(
        (sys.executable, "-c", "import os; os.write(1,b'x'*300000); os.write(2,b'y'*300000); raise SystemExit(7)"),
        cwd=str(tmp_path), artifact_dir=str(tmp_path), rolling_max_bytes=10**9,
        preview_max_bytes=10**9,
    ), capture=sink)
    assert result.exit_code == 7 and result.stdio_complete
    assert result.stdout_artifact_path is result.stderr_artifact_path is None
    assert len(result.stdout.encode()) <= 100 * 1024
    assert len(result.stderr.encode()) <= 100 * 1024
    assert sum(len(chunk.text.encode()) for chunk in result.output_chunks) <= 100 * 1024
    assert sum(len(chunk.text.encode()) for chunk in sink.chunks) == 600000
    assert not list(tmp_path.iterdir())


def test_local_sink_failure_terminates_process_while_stdin_is_blocked(tmp_path, monkeypatch):
    asyncio.run(_local_sink_failure_terminates_process_while_stdin_is_blocked(tmp_path, monkeypatch))


async def _local_sink_failure_terminates_process_while_stdin_is_blocked(tmp_path, monkeypatch):
    processes = []
    spawn = module.spawn_local_process

    async def record_spawn(**kwargs):
        process = await spawn(**kwargs)
        processes.append(process)
        return process

    class FailingSink(Sink):
        async def append(self, chunk):
            if not self.stopped:
                raise ValueError("capture contract failure")

    monkeypatch.setattr(module, "spawn_local_process", record_spawn)
    sink = FailingSink()
    capability = ExecService().capture_executor()
    assert capability is not None
    with pytest.raises(ValueError, match="capture contract failure"):
        await asyncio.wait_for(capability.execute(ExecRequest(
            (sys.executable, "-c", "import os\nwhile True: os.write(1,b'x'*16384)"),
            cwd=str(tmp_path), stdin="i" * 1024 * 1024,
        ), capture=sink), 5)
    assert sink.stopped and len(processes) == 1 and processes[0].returncode is not None


def test_second_cancel_cannot_abandon_local_cleanup_or_native_capture(tmp_path, monkeypatch):
    asyncio.run(_second_cancel_cannot_abandon_local_cleanup_or_native_capture(tmp_path, monkeypatch))


async def _second_cancel_cannot_abandon_local_cleanup_or_native_capture(tmp_path, monkeypatch):
    entered, stdin_closing, release_stdin, release_native = [asyncio.Event() for _ in range(4)]
    processes = []
    spawn = module.spawn_local_process

    async def record_spawn(**kwargs):
        process = await spawn(**kwargs)
        processes.append(process)
        return process

    async def blocked_stdin(*args):
        try:
            await asyncio.Event().wait()
        finally:
            stdin_closing.set()
            await release_stdin.wait()

    native = asyncio.create_task(release_native.wait())

    class PendingSink(Sink):
        async def append(self, chunk):
            if self.stopped:
                pytest.fail("write after admission closed")
            self.chunks.append(chunk)
            entered.set()
            await asyncio.shield(native)

    monkeypatch.setattr(module, "spawn_local_process", record_spawn)
    monkeypatch.setattr(module, "_write_process_stdin", blocked_stdin)
    sink = PendingSink()
    capability = ExecService().capture_executor()
    assert capability is not None
    operation = asyncio.create_task(capability.execute(ExecRequest(
        (sys.executable, "-c", "import os\nwhile True: os.write(1,b'x'*16384)"),
        cwd=str(tmp_path), stdin="blocked",
    ), capture=sink))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        operation.cancel()
        await asyncio.wait_for(stdin_closing.wait(), 5)
        operation.cancel()
        await asyncio.sleep(0)
        assert not operation.done()
        assert processes[0].returncode is not None and not native.done()
        release_stdin.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(operation, 5)
        assert sink.stopped and not native.done()
        assert processes[0].stdout._transport.is_closing()
        assert processes[0].stderr._transport.is_closing()
    finally:
        release_stdin.set()
        release_native.set()
        operation.cancel()
        await asyncio.gather(operation, native, return_exceptions=True)


@pytest.mark.parametrize("fault", ["before", "after"])
def test_local_cleanup_bypasses_external_task_factory(tmp_path, monkeypatch, fault):
    asyncio.run(_local_cleanup_bypasses_external_task_factory(tmp_path, monkeypatch, fault))


async def _local_cleanup_bypasses_external_task_factory(tmp_path, monkeypatch, fault):
    loop = asyncio.get_running_loop()
    previous = loop.get_task_factory()
    attempts, hits, processes = [], [], []
    spawn = module.spawn_local_process

    async def record_spawn(**kwargs):
        process = await spawn(**kwargs)
        processes.append(process)
        return process

    def factory(loop, coroutine, context=None):
        name = coroutine.cr_code.co_name
        attempts.append(name)
        if name == "finish_process":
            hits.append(name)
            if fault == "after":
                asyncio.Task(coroutine, loop=loop, context=context)
            raise RuntimeError("external cleanup factory failure")
        return asyncio.Task(coroutine, loop=loop, context=context)

    monkeypatch.setattr(module, "spawn_local_process", record_spawn)
    loop.set_task_factory(factory)
    try:
        capability = ExecService().capture_executor()
        assert capability is not None
        result = await capability.execute(ExecRequest(
            (sys.executable, "-c", "print('complete')"), cwd=str(tmp_path),
        ), capture=Sink())
        assert result.exit_code == 0 and result.stdio_complete
        assert attempts and not hits
        assert processes[0].stdout._transport.is_closing()
        assert processes[0].stderr._transport.is_closing()
    finally:
        loop.set_task_factory(previous)


class _RejectProcessTaskFactory:
    """Fault only after the backend has received its original process owner."""

    def __init__(self, point, fault):
        self.point, self.fault = point, fault
        self.hits = []
        self.published = []

    def __call__(self, loop, coroutine, context=None):
        name = coroutine.cr_code.co_name
        values = coroutine.cr_frame.f_locals
        matches = (
            (self.point in {"stdout", "stderr"}
             and name in {"_read_stream", "drain_stream"}
             and values.get("stream_name") == self.point)
            or name == {
                "root_exit": "_wait_for_root_process_exit",
                "settlement": "wait",
                "abort": "_wait_for_abort",
                "stdin": "_write_process_stdin",
                "local_cleanup": "finish_process",
                "authorized_stdin": "write_input",
                "authorized_cleanup": "_cleanup_authorized_process",
            }.get(self.point)
        )
        if matches:
            self.hits.append(name)
            if self.fault == "after":
                self.published.append(asyncio.Task(coroutine, loop=loop, context=context))
            else:
                coroutine.close()
            raise RuntimeError("external process task publication failed")
        return asyncio.Task(coroutine, loop=loop, context=context)


@pytest.mark.parametrize("point", ["stdout", "stderr", "root_exit", "settlement", "abort", "stdin", "local_cleanup"])
@pytest.mark.parametrize("fault", ["before", "after"])
@pytest.mark.parametrize("reader_failure", [False, True])
def test_local_captured_process_tasks_bypass_factory_and_settle(tmp_path, monkeypatch, point, fault, reader_failure):
    asyncio.run(_local_captured_process_tasks_bypass_factory_and_settle(
        tmp_path, monkeypatch, point, fault, reader_failure,
    ))


async def _local_captured_process_tasks_bypass_factory_and_settle(tmp_path, monkeypatch, point, fault, reader_failure):
    loop = asyncio.get_running_loop()
    previous = loop.get_task_factory()
    factory = _RejectProcessTaskFactory(point, fault)
    processes = []
    spawn = module.spawn_local_process

    async def record_spawn(**kwargs):
        process = await spawn(**kwargs)
        processes.append(process)
        loop.set_task_factory(factory)
        return process

    class Capture(Sink):
        async def append(self, chunk):
            if reader_failure and not self.stopped:
                raise ValueError("original reader failure")
            await super().append(chunk)

    monkeypatch.setattr(module, "spawn_local_process", record_spawn)
    code = ("import os,time; os.write(1,b'output'); time.sleep(30)" if reader_failure
            else "import sys; sys.stdin.read(); print('output'); raise SystemExit(7)")
    capability = ExecService().capture_executor()
    assert capability is not None
    try:
        operation = capability.execute(ExecRequest(
            (sys.executable, "-c", code), cwd=str(tmp_path), stdin="input", timeout_seconds=3,
        ), capture=Capture(), signal=SimpleNamespace(aborted=False))
        if reader_failure:
            with pytest.raises(ValueError, match="original reader failure"):
                await operation
        else:
            result = await operation
            assert result.exit_code == 7 and result.stdio_complete
        assert not factory.hits
        assert len(processes) == 1 and processes[0].returncode is not None
        assert processes[0].stdout._transport.is_closing()
        assert processes[0].stderr._transport.is_closing()
    finally:
        loop.set_task_factory(previous)
        # The fixture, not a later Product destructor, must contain the broken
        # pre-fix path while the assertions still require backend settlement.
        for process in processes:
            if process.returncode is None:
                await module._kill_process(process)
            module._close_reader_transport(process.stdout)
            module._close_reader_transport(process.stderr)
            await process.wait()
        for task in factory.published:
            task.cancel()
        await asyncio.gather(*factory.published, return_exceptions=True)


@pytest.mark.parametrize("point", ["stdout", "stderr", "settlement", "abort", "authorized_stdin", "authorized_cleanup"])
@pytest.mark.parametrize("fault", ["before", "after"])
@pytest.mark.parametrize("reader_failure", [False, True])
def test_authorized_captured_process_tasks_bypass_factory_and_settle(point, fault, reader_failure):
    asyncio.run(_authorized_captured_process_tasks_bypass_factory_and_settle(point, fault, reader_failure))


async def _authorized_captured_process_tasks_bypass_factory_and_settle(point, fault, reader_failure):
    loop = asyncio.get_running_loop()
    previous = loop.get_task_factory()
    factory = _RejectProcessTaskFactory(point, fault)
    exited = asyncio.Event()
    calls = []

    class Handle:
        def __init__(self):
            self.stdout = [b"output", b""]

        async def read_stdout(self, max_bytes):
            return self.stdout.pop(0)

        async def read_stderr(self, max_bytes):
            return b""

        async def write_stdin(self, content):
            assert content == b"input"

        async def close_stdin(self):
            calls.append("stdin-closed")
            if not reader_failure:
                exited.set()

        async def wait(self):
            await exited.wait()
            return module.ProcessExit(return_code=7)

        async def terminate(self):
            calls.append("terminated")
            exited.set()
            return module.ProcessExit(return_code=-1)

        async def close(self):
            assert exited.is_set()
            calls.append("closed")

    handle = Handle()

    class Launcher:
        async def start(self, *args, **kwargs):
            calls.append("started")
            loop.set_task_factory(factory)
            return handle

    class Capture(Sink):
        async def append(self, chunk):
            if reader_failure and not self.stopped:
                raise ValueError("original reader failure")
            await super().append(chunk)

    capability = ExecService(backend=module.AuthorizedProcessExecBackend(Launcher())).capture_executor()
    assert capability is not None
    try:
        operation = capability.execute(ExecRequest(
            ("/bin/unused",), cwd="/workspace", stdin="input", timeout_seconds=3,
        ), capture=Capture(), signal=SimpleNamespace(aborted=False))
        if reader_failure:
            with pytest.raises(ValueError, match="original reader failure"):
                await operation
        else:
            result = await operation
            assert result.exit_code == 7 and result.stdio_complete
        assert not factory.hits
        assert calls.count("started") == calls.count("closed") == 1
        assert calls.count("terminated") == int(reader_failure)
    finally:
        loop.set_task_factory(previous)
        exited.set()
        for task in factory.published:
            task.cancel()
        await asyncio.gather(*factory.published, return_exceptions=True)
