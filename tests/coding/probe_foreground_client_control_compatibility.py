"""Six explicit old Code foreground-control observations over controlled leaves.

Original Code source SHAffa77827a4600cb85eaa992b40b93e66064c8e40e59e635a90be29fe79be27fa
was source/code pinned before capture. Import events are calls in preloaded
modules, not real cold-load duration; async retry/debt uses actual Tasks.
Controlled launch namespace/identity/UI leaves do not prove Product admission,
native processes, SIGINT or installed-wheel behavior. Sourceguard/capture history
remain external. Fixed /controlled absolute strings are model launch inputs,
required by the original POSIX request contract, not host/worktree file paths.
"""

import asyncio
import builtins
import gzip
import json
import os
import sys
from io import StringIO
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

import loushang.apphost.launcher as launcher
import loushang.coding.cli.hosted_client as code
import loushang.harnesstui.conversation.theme as theme
import loushang.harnesstui.mux.shell as shell
import loushang.harnesstui.mux.terminal as terminal
import loushang.hosting.runtime as hosting
from loushang.appserver.protocol import MuxSpaceV1
from loushang.hosting.contracts import ProcessLaunchRequest

pytestmark = pytest.mark.skipif(
    sys.platform != "linux", reason="Original POSIX model captured on Linux"
)

CASES = (
    "constructor-default-clock",
    "constructor-shell-import-failure",
    "prepare-ui-import-failure",
    "terminal-import-before-guard",
    "close-failure-retained-retry",
    "public-late-close-failure",
)
FIXTURE = Path(__file__).with_name("fixtures") / "foreground_client_control_v1.json.gz"
WATCHED = frozenset(
    (
        "loushang.apphost.launcher",
        "loushang.appserver.protocol",
        "loushang.appserver.protocol.connection_profile",
        "loushang.hosting.runtime",
        "loushang.hosting.contracts",
        "loushang.harnesstui.conversation.theme",
        "loushang.harnesstui.mux.shell",
        "loushang.harnesstui.mux.terminal",
        "loushang.coding.hosted_bootstrap",
    )
)


def error_data(error, known, seen=None):
    if error is None:
        return None
    seen = set() if seen is None else seen
    if id(error) in seen:
        return {"cycle": True}
    seen.add(id(error))
    return {
        "type": type(error).__module__ + "." + type(error).__qualname__,
        "args": list(error.args),
        "message": str(error),
        "identity": next(
            (name for name, value in known.items() if error is value), None
        ),
        "notes": list(getattr(error, "__notes__", ())),
        "suppress_context": error.__suppress_context__,
        "cause": error_data(error.__cause__, known, seen),
        "context": error_data(error.__context__, known, seen),
    }


def actual_control(command):
    return getattr(command, "_control", command)


def observe(case, monkeypatch):
    trace, known, results = [], {}, []
    phase = "setup"
    import_fault_hit = False
    close_calls = 0
    command = None
    original_import = builtins.__import__
    host = object()
    discovery, execution = object(), object()
    ctor_case = case.startswith("constructor-")
    launch = NS(
        workspace=Path("/controlled/workspace"),
        application_root=Path("/controlled/application"),
        application_id="coding.default",
        cwd_sessions=Path("/controlled/cwd"),
        home_sessions=Path("/controlled/home"),
        scopes=(),
    )

    def failure(name, kind):
        value = kind(name)
        value.add_note("original-controlled")
        known[name] = value
        return value

    import_error = failure("import-port", ImportError)
    close_error = failure("close-port", OSError)
    terminal_error = failure("terminal-port", RuntimeError)
    late_error = failure("public-close-port", ValueError)

    def imports(name, globals=None, locals=None, fromlist=(), level=0):
        nonlocal import_fault_hit
        if name in WATCHED and phase != "setup":
            trace.append(["import.call", phase, name])
        failing = (
            (
                case == "constructor-shell-import-failure"
                and phase == "constructor"
                and name == "loushang.harnesstui.mux.shell"
            )
            or (
                case == "prepare-ui-import-failure"
                and phase == "run"
                and name == "loushang.harnesstui.mux.shell"
            )
            or (
                case == "terminal-import-before-guard"
                and phase == "reuse-run"
                and name == "loushang.harnesstui.mux.terminal"
            )
        )
        if failing:
            import_fault_hit = True
            raise import_error
        return original_import(name, globals, locals, fromlist, level)

    class Client:
        async def read_mux(self, request):
            trace.append(["mux.read", request.selector.name])
            return MuxSpaceV1("selected-id", "main", 1, ())

        async def create_mux(self, request):
            raise AssertionError("No create belongs to these six timing observations")

    class Owner:
        client = Client()
        discovery_client = discovery
        execution_client = execution
        process_cleanup_pending = False
        diagnostics = NS(exit_code=0, forced_exit=False)

        def __init__(self, request, **kwargs):
            trace.append(
                [
                    "owner.construct",
                    type(request) is ProcessLaunchRequest,
                    request.argv[0] == sys.executable,
                    request.effective_environment == tuple(sorted(os.environ.items())),
                    kwargs["host"] is host,
                    kwargs["profile"].value,
                    kwargs["startup_timeout"]
                    if ctor_case
                    else 0 < kwargs["startup_timeout"] <= 30,
                ]
            )

        async def start(self):
            trace.append(["owner.start"])

        async def close(self, *, detach=None, **kwargs):
            nonlocal close_calls
            close_calls += 1
            trace.append(
                [
                    "owner.close",
                    detach is not None,
                    list(kwargs),
                    kwargs.get("retry_timeout"),
                ]
            )
            if case == "close-failure-retained-retry" and close_calls == 1:
                raise close_error
            if detach is not None:
                await detach()

    class Shell:
        def __init__(self, client, **kwargs):
            trace.append(
                [
                    "shell.construct",
                    kwargs["selector"].mux_space_id,
                    list(kwargs),
                    kwargs["discovery_client"] is discovery,
                    kwargs["execution_client"] is execution,
                ]
            )

        async def close(self):
            trace.append(["shell.close"])

    async def run_terminal(value, **kwargs):
        trace.append(["terminal.run", kwargs["settlement"].__self__ is command])
        if case == "public-late-close-failure":

            async def late_close(*, retry_timeout=None):
                trace.append(["public.late.close", retry_timeout])
                raise late_error

            monkeypatch.setattr(command, "close", late_close)
            raise terminal_error
        raise AssertionError("Terminal execution only belongs to the late-close case")

    def create_host(**kwargs):
        trace.append(["host.create", kwargs])
        return host

    def identity(request):
        trace.append(["admit.identity"])
        return (1, 2, 3, 4, 5, 6, 7, 8)

    monkeypatch.setattr(launcher, "HostedForegroundClientV1", Owner)
    monkeypatch.setattr(hosting, "create_process_host", create_host)
    monkeypatch.setattr(shell, "HostedMuxShellV1", Shell)
    monkeypatch.setattr(terminal, "run_hosted_mux_shell", run_terminal)
    monkeypatch.setattr(theme, "terminal_transcript_theme", lambda: "theme")
    monkeypatch.setattr(code, "_launch_identity", identity)
    monkeypatch.setattr(builtins, "__import__", imports)

    def construct():
        nonlocal phase, command
        phase = "constructor"
        if ctor_case:
            values = iter(
                (1000.0, 1000.25, 1000.5)
                if case == "constructor-default-clock"
                else (1000.25, 1000.5)
            )

            def clock():
                value = next(values)
                trace.append(["clock.read", value])
                return value

        options = (
            {} if case != "constructor-shell-import-failure" else {"started_at": 1000.0}
        )
        if ctor_case:
            with monkeypatch.context() as clock_patch:
                clock_patch.setattr(code.time, "monotonic", clock)
                command = code.CodingHostedTuiCommandV1(launch, **options)
        else:
            command = code.CodingHostedTuiCommandV1(launch, **options)
        return command

    if ctor_case:
        try:
            construct()
        except BaseException as error:
            results.append(["construct", error_data(error, known)])
        else:
            results.append(["construct", {"cleanup_pending": command.cleanup_pending}])
        if case == "constructor-default-clock":
            assert command is not None and not import_fault_hit
            assert trace[:2] == [["clock.read", 1000.0], ["clock.read", 1000.25]]
        else:
            assert import_fault_hit and command is None
            assert any(row[0] == "owner.construct" for row in trace)
        assert close_calls == 0
        return {"trace": trace, "results": results}

    construct()

    # No fake clock in asynchronous cases: only stable relationships are frozen.
    async def scenario():
        nonlocal phase

        async def call(label, operation):
            try:
                await operation
            except BaseException as error:
                results.append([label, error_data(error, known)])
                return error
            results.append([label, None])
            return None

        state = actual_control(command)
        if case == "prepare-ui-import-failure":
            phase = "run"
            error = await call("run", command.run(stdin=StringIO(), stdout=StringIO()))
            assert error is import_error and import_fault_hit
            assert not any(row[0] == "owner.start" for row in trace)
            assert close_calls == 1 and not command.cleanup_pending
        elif case == "terminal-import-before-guard":
            phase = "reuse-run"
            state._startup = object()
            error = await call("run", command.run(stdin=StringIO(), stdout=StringIO()))
            assert error is import_error and import_fault_hit
            assert close_calls == 0
        elif case == "close-failure-retained-retry":
            phase = "close"
            first = await call("first.close", command.close())
            task, deadline = state._close_task, state._close_deadline
            second = await call("ordinary.close", command.close())
            trace.append(
                [
                    "ordinary.relationships",
                    state._close_task is task,
                    state._close_deadline == deadline,
                    second is first,
                    command.cleanup_pending,
                ]
            )
            assert first is close_error and second is first and close_calls == 1
            await call("explicit.retry", command.close(retry_timeout=20))
            trace.append(
                [
                    "retry.relationships",
                    state._close_task is not task,
                    not command.cleanup_pending,
                    close_calls,
                ]
            )
            assert close_calls == 2 and not command.cleanup_pending
        elif case == "public-late-close-failure":
            phase = "run"
            original_close = command.close
            error = await call("run", command.run(stdin=StringIO(), stdout=StringIO()))
            assert error is late_error and error.__context__ is terminal_error
            trace.append(["pending.after.public.failure", command.cleanup_pending])
            assert command.cleanup_pending
            monkeypatch.setattr(command, "close", original_close)
            await call("manual.cleanup", original_close())
            assert not command.cleanup_pending
        else:
            raise AssertionError(case)

    asyncio.run(scenario())
    return {"trace": trace, "results": results}


@pytest.mark.parametrize("case", CASES)
def test_original_timing(case, monkeypatch):
    observed = json.loads(json.dumps(observe(case, monkeypatch)))
    expected = json.loads(gzip.decompress(FIXTURE.read_bytes()))
    assert observed == expected[case]
