"""G17 Product command admission and orchestration, not installed acceptance."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import suppress
from dataclasses import replace
from io import StringIO
from types import SimpleNamespace

import pytest

from loushang.coding.cli.hosted_client import (
    CodingHostedTuiCommandV1,
    _launch_request,
    _LaunchPreparation,
    main,
)
from loushang.coding.hosted_bootstrap import CodingHostedLaunchV1


def _launch(root):
    return CodingHostedLaunchV1(
        root, root / "application", "coding.default", root / "cwd", root / "home"
    )


def _argv(root):
    return [
        "--workspace", str(root), "--application-root", str(root / "application"),
        "--cwd-sessions", str(root / "cwd"), "--home-sessions", str(root / "home"),
    ]


def test_G17_COMMAND_help_describe_and_non_tty_have_no_state_effects(tmp_path, capsys):
    with pytest.raises(SystemExit) as help_exit:
        main(["--help"])
    assert help_exit.value.code == 0
    capsys.readouterr()
    assert main([*_argv(tmp_path), "--describe"]) == 0
    output = capsys.readouterr()
    value = json.loads(output.out)
    assert value["profile"] == "foreground-stdio-discovery/v1"
    assert value["exitEndsApplication"] is True
    assert str(tmp_path) not in output.out and output.err == ""
    with pytest.raises(SystemExit) as no_tty:
        main(_argv(tmp_path))
    assert no_tty.value.code == 2
    assert not tuple(tmp_path.iterdir())


def test_G17_ADMISSION_request_preserves_venv_and_uses_isolated_fixed_child(tmp_path):
    request = _launch_request(_launch(tmp_path))
    assert request.argv[:4] == (
        sys.executable, "-I", "-m", "loushang.coding.cli.hosted"
    )
    assert request.argv[-1] == "--session-discovery"
    assert request.cwd == str(tmp_path)


@pytest.mark.parametrize("field", ["argv", "cwd", "effective_environment", "streams"])
def test_G17_ADMISSION_preparation_rejects_changed_complete_request(tmp_path, field):
    from loushang.hosting.contracts import ProcessStderrMode

    async def scenario():
        request = _launch_request(_launch(tmp_path))
        port = _LaunchPreparation(request)
        changes = {
            "argv": (*request.argv, "--describe"),
            "cwd": str(tmp_path.parent),
            "effective_environment": (),
            "streams": replace(request.streams, stderr=ProcessStderrMode.DISCARD),
        }
        with pytest.raises(ValueError):
            await port.prepare(replace(request, **{field: changes[field]}))
        prepared = await port.prepare(request)
        await prepared.verify_current()
        await prepared.close()
        with pytest.raises(ValueError):
            await prepared.verify_current()
        with pytest.raises(ValueError):
            await port.prepare(request)

    asyncio.run(scenario())


def test_G17_COMMAND_budget_exhausted_before_construction_cannot_start_host(tmp_path):
    import time

    with pytest.raises(TimeoutError):
        CodingHostedTuiCommandV1(_launch(tmp_path), started_at=time.monotonic() - 31)


def _fake_command(tmp_path, monkeypatch, *, read_error=None, create_error=None):
    from loushang.apphost import launcher
    from loushang.appserver.protocol import MuxSpaceV1
    from loushang.harnesstui.mux import shell, terminal
    from loushang.hosting import runtime

    calls = []

    class Client:
        async def read_mux(self, request):
            calls.append("read")
            if read_error:
                raise read_error
            return MuxSpaceV1("selected-id", "main", 1, ())

        async def create_mux(self, request):
            calls.append("create")
            if create_error:
                raise create_error
            return MuxSpaceV1("created-id", "main", 1, ())

    class Owner:
        client = Client()
        discovery_client = object()
        diagnostics = SimpleNamespace(exit_code=0, forced_exit=False)

        def __init__(self, *args, **kwargs):
            pass

        async def start(self):
            calls.append("start")

        async def close(self, *, detach=None):
            calls.append("close")
            if detach:
                await detach()

    class Shell:
        def __init__(self, client, **kwargs):
            calls.append(("shell", kwargs))

        async def close(self):
            calls.append("detach")

    async def run_terminal(shell, **kwargs):
        calls.append("terminal")
        await kwargs["settlement"]()
        return 0

    monkeypatch.setattr(launcher, "HostedForegroundClientV1", Owner)
    monkeypatch.setattr(runtime, "create_process_host", lambda **kwargs: object())
    monkeypatch.setattr(shell, "HostedMuxShellV1", Shell)
    monkeypatch.setattr(terminal, "run_hosted_mux_shell", run_terminal)
    return CodingHostedTuiCommandV1(_launch(tmp_path)), calls


@pytest.mark.parametrize("missing", [False, True])
def test_G17_COMMAND_selects_one_authoritative_mux_id_without_creating_session(
    tmp_path, monkeypatch, missing
):
    from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError

    async def scenario():
        command, calls = _fake_command(
            tmp_path, monkeypatch,
            read_error=AppServiceError(AppErrorCodeV1.NOT_FOUND) if missing else None,
        )
        assert await command.run(stdin=StringIO(), stdout=StringIO()) == 0
        assert calls.count("read") == 1 and calls.count("create") == int(missing)
        options = next(item[1] for item in calls if isinstance(item, tuple))
        assert options["selector"].mux_space_id == ("created-id" if missing else "selected-id")
        assert options["selector"].name is None
        assert options["exit_ends_application"] is True
        assert calls.count("close") == 1 and calls.count("detach") == 1
        assert not command.cleanup_pending

    asyncio.run(scenario())


@pytest.mark.parametrize("failed_create", [False, True])
def test_G17_COMMAND_unknown_mutation_or_read_failure_never_retries(tmp_path, monkeypatch, failed_create):
    from loushang.appserver.protocol import AppErrorCodeV1, AppServiceError

    async def scenario():
        command, calls = _fake_command(
            tmp_path, monkeypatch,
            read_error=AppServiceError(
                AppErrorCodeV1.NOT_FOUND if failed_create else AppErrorCodeV1.OPERATION_UNAVAILABLE
            ),
            create_error=TimeoutError("unknown create outcome") if failed_create else None,
        )
        with pytest.raises((TimeoutError, AppServiceError)):
            await command.run(stdin=StringIO(), stdout=StringIO())
        assert calls.count("read") == 1 and calls.count("create") == int(failed_create)
        assert "terminal" not in calls and command._shell is None
        assert not command.cleanup_pending

    asyncio.run(scenario())


def test_G17_COMMAND_close_fences_cancel_resistant_late_mux_response(tmp_path, monkeypatch):
    async def scenario():
        command, calls = _fake_command(tmp_path, monkeypatch)
        entered, release = asyncio.Event(), asyncio.Event()
        read = command._owner.client.read_mux

        async def late_read(request):
            entered.set()
            try:
                await release.wait()
            except asyncio.CancelledError:
                await release.wait()
            return await read(request)

        command._owner.client.read_mux = late_read
        running = asyncio.create_task(command.run(stdin=StringIO(), stdout=StringIO()))
        await asyncio.wait_for(entered.wait(), 1)
        closing = asyncio.create_task(command.close())
        await asyncio.sleep(0)
        release.set()
        await asyncio.wait_for(closing, 1)
        await asyncio.gather(running, return_exceptions=True)
        assert command._shell is None and "terminal" not in calls
        assert calls.count("close") == 1 and calls.count("create") == 0
        assert not command.cleanup_pending

    asyncio.run(scenario())


@pytest.mark.parametrize("exit_code,forced", [(0, False), (2, False), (None, False), (0, True)])
def test_G17_COMMAND_exit_result_is_computed_after_settlement(tmp_path, monkeypatch, exit_code, forced):
    async def scenario():
        command, _ = _fake_command(tmp_path, monkeypatch)
        close = command._owner.close

        async def settle(**kwargs):
            await close(**kwargs)
            command._owner.diagnostics = SimpleNamespace(exit_code=exit_code, forced_exit=forced)

        command._owner.close = settle
        result = await command.run(stdin=StringIO(), stdout=StringIO())
        assert result == int(forced or exit_code != 0)

    asyncio.run(scenario())


def test_G17_COMMAND_real_child_ignores_workspace_and_pythonpath_shadow(tmp_path, monkeypatch):
    """Actual Hosting/child/Product with fake terminal; not isolated-wheel evidence."""
    from loushang.harnesstui.mux import terminal
    from loushang.tui.terminal import FakeTerminalPort, TerminalSize
    from loushang.tui.terminal_session import TerminalSession

    for root in (tmp_path, tmp_path / "evil-pythonpath"):
        package = root / "loushang"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(
            f"from pathlib import Path; Path({str(tmp_path / 'shadow-executed')!r}).touch(); raise RuntimeError('shadow')"
        )
    for name, value in {
        "PYTHONPATH": str(tmp_path / "evil-pythonpath"),
        "PYTHONHOME": str(tmp_path / "nonexistent-python"),
        "LOUSHANG_HOME": str(tmp_path / "platform"),
        "LOUSHANG_RUNTIME_DIR": str(tmp_path / "runtime"),
        "LOUSHANG_TMPDIR": str(tmp_path / "scratch"),
    }.items():
        monkeypatch.setenv(name, value)
    run_terminal = terminal.run_hosted_mux_shell
    events = []

    class Mode:
        def __enter__(self):
            events.append("enter")

        def __exit__(self, *args):
            events.append("restore")

    async def eof(stream):
        return ""

    async def fake_terminal(shell, **kwargs):
        return await run_terminal(
            shell, **kwargs, input_chunk_reader=eof,
            terminal=FakeTerminalPort(size=TerminalSize(columns=80, rows=24)),
            session=TerminalSession(kwargs["stdin"], kwargs["stdout"], mode_factory=lambda *args: Mode()),
        )

    monkeypatch.setattr(terminal, "run_hosted_mux_shell", fake_terminal)

    async def scenario():
        command = CodingHostedTuiCommandV1(_launch(tmp_path))
        try:
            assert await command.run(stdin=StringIO(), stdout=StringIO()) == 0
        except BaseException as error:
            # Test-owned, bounded lifecycle facts only: no stderr, argv, env
            # or exception messages from the Product enter the diagnostic.
            owner = command._owner
            phases = {}
            for name in ("detach", "client", "eof", "drain", "terminate", "lease", "host"):
                task = owner._phases.get(name)
                phases[name] = (
                    "absent" if task is None else "pending" if not task.done() else
                    "cancelled" if task.cancelled() else
                    type(task.exception()).__name__ if task.exception() is not None else "done"
                )
            error.add_note(f"Hosted settlement phases: {phases}; forced={owner.forced_exit}")
            raise
        assert not command.cleanup_pending and not command._owner.cleanup_pending
        assert events == ["enter", "restore"]
        assert not (tmp_path / "shadow-executed").exists()

    asyncio.run(asyncio.wait_for(scenario(), 55))


def test_G17_COMMAND_mux_phase_uses_remaining_startup_budget(tmp_path, monkeypatch):
    import time

    async def scenario():
        command, calls = _fake_command(tmp_path, monkeypatch)

        async def pending(request):
            calls.append("read")
            await asyncio.Event().wait()

        command._owner.client.read_mux = pending
        command._started_at = time.monotonic() - 29.98
        with pytest.raises(TimeoutError):
            await command.run(stdin=StringIO(), stdout=StringIO())
        assert calls == ["start", "read", "close"]
        assert not command.cleanup_pending

    asyncio.run(scenario())


def test_G17_ADMISSION_changed_executable_identity_is_rejected_at_spawn_check(tmp_path):
    async def scenario():
        executable = tmp_path / "admitted-python"
        executable.write_bytes(b"original")
        request = _launch_request(_launch(tmp_path))
        request = replace(request, argv=(str(executable), *request.argv[1:]))
        port = _LaunchPreparation(request)
        prepared = await port.prepare(request)
        executable.write_bytes(b"changed material")
        try:
            with pytest.raises(ValueError, match="hosted_launch_changed"):
                await prepared.verify_current()
        finally:
            await prepared.close()

    asyncio.run(scenario())


def test_G17_COMMAND_deferred_import_failure_is_pathless(tmp_path, monkeypatch, capsys):
    import builtins

    original = builtins.__import__

    def fail(name, *args, **kwargs):
        if name == "loushang.appserver.protocol":
            raise RuntimeError("/private/install/sensitive-import-sentinel")
        return original(name, *args, **kwargs)

    class Tty(StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", Tty())
    monkeypatch.setattr(sys, "stdout", Tty())
    monkeypatch.setattr(builtins, "__import__", fail)
    assert main(_argv(tmp_path)) == 1
    assert capsys.readouterr().err == "hosted_configuration_unavailable\n"
    assert not tuple(tmp_path.iterdir())


def test_G17_RECLAIM_outer_runner_keeps_existing_cleanup_alive_even_with_stdin_eof(monkeypatch, capsys):
    from loushang.coding.cli import hosted_client

    events = []

    class Command:
        cleanup_pending = process_cleanup_pending = True

        async def run(self, **kwargs):
            async def reclaim():
                await asyncio.sleep(0.02)
                events.append("physical-reclaimed")
                self.process_cleanup_pending = self.cleanup_pending = False

            asyncio.create_task(reclaim())
            raise RuntimeError("/private/failure")

        async def close(self):
            pass

    def forbidden_exit(code):
        raise AssertionError("must not abandon physical owner")

    monkeypatch.setattr(sys, "stdin", StringIO())
    monkeypatch.setattr(hosted_client.os, "_exit", forbidden_exit)
    assert hosted_client._execute(Command(), StringIO()) == 1
    assert events == ["physical-reclaimed"]
    output = capsys.readouterr().err
    assert "controller retained" in output and "private" not in output


@pytest.mark.parametrize("second_signal", ["output", "retry"])
def test_G17_RECLAIM_control_c_is_explicit_retry_not_owner_abandonment(monkeypatch, second_signal):
    import signal

    from loushang.coding.cli import hosted_client

    events = []

    class Command:
        cleanup_pending = process_cleanup_pending = True

        async def run(self, **kwargs):
            raise RuntimeError("initial close failed")

        async def close(self, *, retry_timeout=None):
            if retry_timeout is None:
                return
            events.append(("retry", retry_timeout))
            if len(events) == 1:
                if second_signal == "retry":
                    signal.raise_signal(signal.SIGINT)
                    await asyncio.sleep(0)
                raise RuntimeError("first explicit retry failed")
            self.process_cleanup_pending = self.cleanup_pending = False

    command = Command()

    class InterruptingSink(StringIO):
        signals = 0

        def write(self, text):
            if (
                "controller retained" in text
                or (second_signal == "output" and "hosted_cleanup_incomplete" in text)
            ) and self.signals < (2 if second_signal == "output" else 1):
                self.signals += 1
                signal.raise_signal(signal.SIGINT)  # Real handler during synchronous output.
            return super().write(text)

    sink = InterruptingSink()
    previous = signal.getsignal(signal.SIGINT)
    monkeypatch.setattr(sys, "stderr", sink)
    monkeypatch.setattr(hosted_client.os, "_exit", lambda code: pytest.fail("abandoned owner"))
    assert hosted_client._execute(command, StringIO()) == 1
    assert events == [("retry", 20), ("retry", 20)]
    assert sink.signals == (2 if second_signal == "output" else 1)
    assert "controller retained" in sink.getvalue()
    assert signal.getsignal(signal.SIGINT) == previous


@pytest.mark.parametrize("failure", [BrokenPipeError, ValueError])
def test_G17_RECLAIM_failed_diagnostic_sink_cannot_discard_owner(monkeypatch, failure):
    from loushang.coding.cli import hosted_client

    class Command:
        cleanup_pending = process_cleanup_pending = True

        async def run(self, **kwargs):
            async def reclaim():
                await asyncio.sleep(0.02)
                self.process_cleanup_pending = self.cleanup_pending = False

            asyncio.create_task(reclaim())
            raise RuntimeError("close failed")

        async def close(self):
            pass

    class Sink:
        def write(self, text):
            raise failure("diagnostic unavailable")

    monkeypatch.setattr(sys, "stderr", Sink())
    monkeypatch.setattr(hosted_client.os, "_exit", lambda code: pytest.fail("abandoned owner"))
    command = Command()
    assert hosted_client._execute(command, StringIO()) == 1
    assert not command.process_cleanup_pending


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group orphan regression")
def test_G17_RECLAIM_real_outer_controller_cannot_exit_while_child_is_still_owned(tmp_path):
    from pathlib import Path

    async def scenario():
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(Path(__file__).with_name("_hosted_client_debt.py")), str(tmp_path),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={
                **os.environ, "LOUSHANG_HOME": str(tmp_path / "platform"),
                "LOUSHANG_RUNTIME_DIR": str(tmp_path / "runtime"),
                "LOUSHANG_TMPDIR": str(tmp_path / "scratch"),
            },
        )
        assert process.stderr is not None
        child_pid = None
        try:
            lines = []
            while not any(b"controller retained" in line for line in lines):
                line = await asyncio.wait_for(process.stderr.readline(), 35)
                assert line, b"".join(lines).decode(errors="replace")
                lines.append(line)
            child_pid = int((tmp_path / "child.pid").read_text())
            os.kill(child_pid, 0)  # It is actually alive while termination is held.
            assert (tmp_path / "terminal-restored").exists()
            assert process.returncode is None  # EOF did not discard the controller.
            (tmp_path / "release-reclamation").touch()
            await asyncio.wait_for(process.wait(), 15)
            assert process.returncode == 1
            with pytest.raises(ProcessLookupError):
                os.kill(child_pid, 0)  # Child was reaped before controller fatal exit.
        finally:
            (tmp_path / "release-reclamation").touch()
            if process.returncode is None:
                try:
                    await asyncio.wait_for(process.wait(), 15)
                except TimeoutError:
                    if child_pid is not None:
                        with suppress(ProcessLookupError):
                            os.kill(child_pid, 9)
                    process.kill()
                    await process.wait()

    asyncio.run(asyncio.wait_for(scenario(), 70))
