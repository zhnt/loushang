from __future__ import annotations

import asyncio
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
def test_product_first_frame_runtime_owner_and_output_order(
    monkeypatch, phase, expected
):
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
            queue.put_nowait("/quit\r")
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

        monkeypatch.setattr(module, "run_agent_cli_application", fake_cli)
        monkeypatch.setattr(module, "run_coding_tui", fake_tui)
        binding = Binding(
            builder,
            ProductHostLifecycle.resolve(stdin=stdin, stdout=output, stderr=errors),
        )
        result = await module.run_screen_first_cli(
            (),
            binding=binding,
            host_binding=SimpleNamespace(bind=lambda runners: runners.tui),
            host_runners=Runners(),
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
        if phase != "ui-error":
            assert "bootstrap note" not in before_restore
        assert errors.getvalue().count("cleanup diagnostic") == 1
        if phase == "ui-error":
            assert len(summaries) == 1
            assert "completion preparation failed" in summaries[0]
        if phase.startswith("cleanup-cancel"):
            assert "cleanup cancelled before settlement" in errors.getvalue()
        if phase == "resolve-and-cleanup-error":
            assert "resolve failed" in errors.getvalue()
            assert "second cleanup failure" in errors.getvalue()
        if phase in {"ready", "cleanup-error"}:
            assert output.getvalue().count("resume hint") == 1
            assert output.getvalue().index("<restored>") < output.getvalue().index(
                "resume hint"
            )

    asyncio.run(asyncio.wait_for(scenario(), 10))
