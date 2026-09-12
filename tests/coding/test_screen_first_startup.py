from __future__ import annotations

import asyncio
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from loushang.coding.cli.application import _cli_launch_plan
from loushang.coding.cli.args import parse_args
from loushang.coding.cli.screen_startup import StartupOutput, screen_startup_eligible


class TTY(StringIO):
    def isatty(self):
        return True


@pytest.mark.parametrize("platform", ["linux", "darwin", "win32"])
@pytest.mark.parametrize("native_tty", [False, True])
def test_threaded_loading_selection_requires_linux_native_terminal(
    monkeypatch, platform, native_tty
):
    from loushang.coding.cli import screen_startup as module

    monkeypatch.setattr(module.sys, "platform", platform)
    monkeypatch.setattr(module.os, "isatty", lambda fd: native_tty and fd == 123)
    stream = SimpleNamespace(fileno=lambda: 123)
    assert module._threaded_loading_supported(stream) == (
        platform == "linux" and native_tty
    )
    assert not module._threaded_loading_supported(TTY())


@pytest.mark.parametrize(
    "argv,expected",
    [
        ([], True),
        (["--tui"], True),
        (["--continue"], True),
        (["--resume", "session-ref"], True),
        (["--session", "session-ref"], True),
        (["--resume"], False),
        (["--help"], False),
        (["--version"], False),
        (["--list-sessions"], False),
        (["--tui", "--list-plugins"], False),
        (["--no-tui"], False),
        (["--tui", "--no-tui"], False),
        (["--mode", "rpc"], False),
        (["--mode", "channel"], False),
        (["--prompt", "hello"], False),
        (["hello"], False),
        (["--fork", "branch"], False),
    ],
)
def test_route_selection(argv, expected):
    args = parse_args(argv)
    assert (
        screen_startup_eligible(args, _cli_launch_plan(args), stdin=TTY(), stdout=TTY())
        is expected
    )
    assert not screen_startup_eligible(
        args, _cli_launch_plan(args), stdin=StringIO(), stdout=TTY()
    )


def test_output_capture_preserves_tty_is_bounded_and_drains_once():
    target = TTY()
    output = StartupOutput(target, limit=4)
    assert output.isatty() and output.encoding == "utf-8"
    assert output.write("abcdef") == 6
    assert target.getvalue() == ""
    output.drain()
    expected = "abcd\n[Startup output truncated]\n"
    assert target.getvalue() == expected
    output.drain()
    assert target.getvalue() == expected


@pytest.mark.parametrize(
    "phase,expected",
    [
        ("ready", 0),
        ("resolve-error", 1),
        ("configure-error", 2),
        ("cancel-resolve", 130),
        ("cleanup-error", 1),
        ("cleanup-cancel-ready", 1),
        ("cleanup-cancel-eof", 1),
        ("resolve-and-cleanup-error", 1),
        ("ui-error", 1),
    ],
)
@pytest.mark.parametrize("early_entry", [False, True])
@pytest.mark.parametrize("threaded_entry", [False, True])
def test_product_first_frame_runtime_owner_and_output_order(
    monkeypatch, request, phase, expected, early_entry, threaded_entry
):
    if threaded_entry and sys.platform != "linux":
        pytest.skip("Linux loading worker")
    from loushang.coding.cli import screen_startup as module
    from loushang.harness.host.product_host import ProductHostLifecycle
    from loushang.harnesstui.conversation.host import ConversationScreenRunProfile
    from loushang.harnesstui.conversation.startup_host import ScreenConversationStartup
    from loushang.tui.terminal import TerminalSize

    @dataclass
    class Binding:
        runtime_builder: object
        host_lifecycle: object
        run_host: object = None

    @dataclass
    class Runners:
        tui: object = None

    async def scenario():
        output, errors, stdin = TTY(), TTY(), TTY()
        events, queue = [], asyncio.Queue()
        if threaded_entry:
            from loushang.harnesstui.conversation.threaded_startup import (
                ThreadedScreenStartup,
            )

            read_fd, write_fd = os.pipe()
            open_fds = [read_fd, write_fd]

            def close_fds():
                for fd in open_fds:
                    os.close(fd)
                open_fds.clear()

            request.addfinalizer(close_fds)
            stdin.fileno = lambda: read_fd

            class NativeQueue:
                def put_nowait(self, value):
                    if value == "":
                        os.close(write_fd)
                        open_fds.remove(write_fd)
                    else:
                        os.write(write_fd, value.encode())

            queue = NativeQueue()
            monkeypatch.setattr(module, "_threaded_loading_supported", lambda _: True)
            original_threaded_run = ThreadedScreenStartup.run

            async def run_threaded(self, **kwargs):
                return await original_threaded_run(
                    self,
                    **kwargs,
                    terminal_mode_factory=terminal,
                    terminal_size_provider=lambda: TerminalSize(columns=80, rows=24),
                )

            monkeypatch.setattr(ThreadedScreenStartup, "run", run_threaded)
        ready_app = []
        summaries = []
        original_run = ScreenConversationStartup.run

        @contextmanager
        def terminal(_stdin, _stdout):
            events.append("terminal.enter")
            try:
                yield object()
            finally:
                events.append("terminal.exit")
                output.write("<restored>\n")

        async def run_screen(self, **kwargs):
            ready_app.append(self.app)
            if phase == "ui-error":
                original_summary = self.failure_summary

                def capture_summary(code):
                    summary = original_summary(code)
                    summaries.append(summary)
                    queue.put_nowait("\x04")
                    return summary

                self.failure_summary = capture_summary
            if threaded_entry:
                return await original_run(self, **kwargs)
            return await original_run(
                self,
                **kwargs,
                terminal_mode_factory=terminal,
                terminal_size_provider=lambda: TerminalSize(columns=80, rows=24),
                input_chunk_reader=lambda _stdin: queue.get(),
            )

        monkeypatch.setattr(ScreenConversationStartup, "run", run_screen)

        class Runtime:
            captured_errors = None

            async def dispose_session_runtime(self):
                events.append("runtime.dispose")
                self.captured_errors.write("cleanup diagnostic\n")
                if phase == "cleanup-error":
                    raise RuntimeError("cleanup failed")
                if phase in {"cleanup-cancel-ready", "cleanup-cancel-eof"}:
                    raise asyncio.CancelledError
                if phase == "resolve-and-cleanup-error":
                    raise RuntimeError("second cleanup failure")

        runtime = Runtime()

        def builder(**_kwargs):
            assert "Loading session" in output.getvalue()
            assert "perm=" not in output.getvalue()
            events.append("runtime.create")
            return runtime

        async def fake_cli(_argv, *, binding, cwd):
            streams = binding.host_lifecycle.streams
            assert streams.stdout.isatty() and streams.stderr.isatty()
            assert streams.stdin is stdin
            streams.stdout.write("bootstrap note\n")
            created = await binding.runtime_builder(
                args=object(),
                cwd=Path("/repo"),
                session_dir=Path("/sessions"),
                services=object(),
                tool_registry=object(),
                approval_resolver=None,
            )
            runtime.captured_errors = streams.stderr
            if phase in {"resolve-error", "resolve-and-cleanup-error"}:
                queue.put_nowait("\x04")
                raise RuntimeError("resolve failed")
            if phase == "configure-error":
                queue.put_nowait("\x04")
                return 2
            if phase == "cancel-resolve":
                queue.put_nowait("\x03")
                await asyncio.Event().wait()
            if phase == "cleanup-cancel-eof":
                queue.put_nowait("")
                await asyncio.Event().wait()
            return await binding.run_host(
                runtime=created,
                session=object(),
                stdin=streams.stdin,
                stdout=streams.stdout,
                stderr=streams.stderr,
            )

        async def fake_tui(*, startup_app, prepared_screen_runner, **kwargs):
            assert startup_app is ready_app[0]
            if phase == "ui-error":
                from loushang.tui.launch import TuiLaunchProfile, run_tui_launch_shell

                async def fail():
                    raise RuntimeError("completion preparation failed")

                return await run_tui_launch_shell(
                    stdin=kwargs["stdin"],
                    stdout=kwargs["stdout"],
                    stderr=kwargs["stderr"],
                    profile=TuiLaunchProfile(fail, fail, "Error: "),
                    verbose=False,
                )
            host = SimpleNamespace(
                submit=lambda _action: None,
                steer=lambda _action: None,
                follow_up=lambda _action: None,
                abort=lambda: None,
            )
            queue.put_nowait("\x04" if threaded_entry else "/quit\r")
            result = await prepared_screen_runner(
                app=startup_app,
                stdin=kwargs["stdin"],
                stdout=kwargs["stdout"],
                action_host=host,
                profile=ConversationScreenRunProfile(None, "interrupted", "cancelled"),
                should_exit=lambda text: text == "/quit",
            )
            kwargs["stdout"].write("resume hint\n")
            return result

        from loushang.coding.cli import application
        from loushang.coding.ui import mode
        from loushang.harness.cli import application as harness_application

        monkeypatch.setattr(harness_application, "run_agent_cli_application", fake_cli)
        monkeypatch.setattr(mode, "run_coding_tui", fake_tui)
        binding = Binding(
            builder,
            ProductHostLifecycle.resolve(stdin=stdin, stdout=output, stderr=errors),
        )
        host_binding = SimpleNamespace(bind=lambda runners: runners.tui)
        runners = Runners()

        async def bind_after_frame(_argv, *, cwd, _prepared_screen_runner):
            assert "Loading session" in output.getvalue()
            return await _prepared_screen_runner(binding, host_binding, runners)

        if early_entry:
            monkeypatch.setattr(application, "run_cli", bind_after_frame)
            monkeypatch.setattr(sys, "stdin", stdin)
            monkeypatch.setattr(sys, "stdout", output)
            monkeypatch.setattr(sys, "stderr", errors)
        result = await module.run_screen_first_cli(
            (),
            binding=None if early_entry else binding,
            host_binding=host_binding,
            host_runners=runners,
            project_root=Path("/repo"),
            cwd=None,
        )
        assert result == expected
        assert events == [
            "terminal.enter",
            "runtime.create",
            "runtime.dispose",
            "terminal.exit",
        ]
        before_restore, _, after_restore = output.getvalue().partition("<restored>")
        assert after_restore.count("bootstrap note") == 1
        if phase not in {"ui-error", "configure-error"}:
            assert "bootstrap note" not in before_restore
        if phase == "configure-error" and "bootstrap note" in before_restore:
            # The main runner may present buffered diagnostics before consuming
            # queued EOF. That is a rendered failure summary, not an early drain.
            assert "Error: bootstrap note" in before_restore
        assert errors.getvalue().count("cleanup diagnostic") == 1
        if phase == "ui-error":
            assert len(summaries) == 1
            assert "completion preparation failed" in summaries[0]
        if phase.startswith("cleanup-cancel"):
            assert "cleanup cancelled before settlement" in errors.getvalue()
        if phase == "resolve-and-cleanup-error":
            # Depending on queued-exit timing, poll may already have presented
            # both failures in the screen instead of re-emitting them on stderr.
            diagnostics = output.getvalue() + errors.getvalue()
            assert "resolve failed" in diagnostics
            assert "second cleanup failure" in diagnostics
        if phase in {"ready", "cleanup-error"}:
            assert output.getvalue().count("resume hint") == 1
            assert output.getvalue().index("<restored>") < output.getvalue().index(
                "resume hint"
            )

    asyncio.run(asyncio.wait_for(scenario(), 10))


def test_real_application_hands_existing_screen_binding_off_once(monkeypatch, tmp_path):
    from loushang.coding.cli import application, screen_startup

    calls = []

    async def forbidden(*args, **kwargs):
        raise AssertionError("must not open a second screen")

    async def accept(binding, host_binding, runners):
        calls.append((binding, host_binding, runners))
        return 23

    monkeypatch.setattr(screen_startup, "run_screen_first_cli", forbidden)
    result = asyncio.run(
        application.run_cli(
            ("--tui",),
            stdin=TTY(),
            stdout=TTY(),
            stderr=TTY(),
            cwd=tmp_path,
            _prepared_screen_runner=accept,
        )
    )
    assert result == 23 and len(calls) == 1


def test_early_application_import_failure_restores_terminal_without_runtime(
    monkeypatch, tmp_path
):
    import builtins

    from loushang.coding.cli import screen_startup
    from loushang.harnesstui.conversation.startup_host import ScreenConversationStartup
    from loushang.tui.terminal import TerminalSize

    async def scenario():
        output, errors, stdin = TTY(), TTY(), TTY()
        events = []
        original_import = builtins.__import__
        original_run = ScreenConversationStartup.run

        def fail_import(name, *args, **kwargs):
            if name == "loushang.coding.cli.application":
                assert "Loading session" in output.getvalue()
                events.append("application.import")
                raise ImportError("application import unavailable")
            return original_import(name, *args, **kwargs)

        @contextmanager
        def terminal(_stdin, _stdout):
            events.append("terminal.enter")
            try:
                yield object()
            finally:
                events.append("terminal.exit")

        async def exit_after_visible_failure(_stdin):
            while "application import unavailable" not in output.getvalue():
                await asyncio.sleep(0.001)
            return "\x04"

        async def run_screen(self, **kwargs):
            return await original_run(
                self,
                **kwargs,
                terminal_mode_factory=terminal,
                terminal_size_provider=lambda: TerminalSize(columns=100, rows=30),
                input_chunk_reader=exit_after_visible_failure,
            )

        monkeypatch.setattr(sys, "stdin", stdin)
        monkeypatch.setattr(sys, "stdout", output)
        monkeypatch.setattr(sys, "stderr", errors)
        monkeypatch.setattr(ScreenConversationStartup, "run", run_screen)
        monkeypatch.setattr(builtins, "__import__", fail_import)
        result = await screen_startup.run_screen_first_cli(
            (), project_root=tmp_path, cwd=None
        )
        assert result == 1
        assert events == ["terminal.enter", "application.import", "terminal.exit"]

    asyncio.run(asyncio.wait_for(scenario(), 10))
