"""Explicit frozen pre-A181 Supervisor lifetime observations.

Actual public Supervisor methods/Handle and real cancellation Tasks over controlled
launcher, client and diagnostic leaves; selected retained-debt maps are seeded.
Fixed /controlled paths are model values, not host IO or native process evidence.
No capture or default CI route. Public layout is recorded once within six cases.
"""

import asyncio
import dataclasses
import gzip
import inspect
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import loushang.coding.lsp.supervisor as code
from loushang.coding.lsp.catalog import LspCatalog
from loushang.coding.lsp.model import (
    LspServerDefinition,
    LspServerKey,
    LspServerSelection,
)

pytestmark = pytest.mark.skipif(
    sys.platform != "linux",
    reason="Frozen controlled POSIX model paths, not native processes",
)

EXPECTED = Path(__file__).with_name("fixtures") / "supervisor_custody_v1.json.gz"
CASES = (
    "cancel-start-waiter-peer",
    "launch-failure-no-client",
    "initialize-abort-release-errors",
    "dispose-error-order-retention",
    "soft-status-budget",
    "stop-pending-start",
)


def error_data(error, labels, seen=None):
    if error is None:
        return None
    seen = set() if seen is None else set(seen)
    if id(error) in seen:
        return {"cycle": True}
    seen.add(id(error))
    return {
        "type": type(error).__module__ + "." + type(error).__qualname__,
        "args": list(error.args),
        "message": str(error),
        "identity": next(
            (name for name, value in labels.items() if value is error), None
        ),
        "notes": getattr(error, "__notes__", []),
        "cause": error_data(error.__cause__, labels, seen),
        "context": error_data(error.__context__, labels, seen),
        "suppress": error.__suppress_context__,
    }


def public_metadata(runtime):
    return {
        "handle_class": type(runtime).__module__ + "." + type(runtime).__qualname__,
        "handle_fields": [[f.name, f.type] for f in dataclasses.fields(type(runtime))],
        "handle_slots": list(type(runtime).__slots__),
        "handle_signature": str(inspect.signature(type(runtime))),
        "frozen": type(runtime).__dataclass_params__.frozen,
        "no_dict": not hasattr(runtime, "__dict__"),
        "supervisor_signatures": {
            name: str(inspect.signature(getattr(code.LspServerSupervisor, name)))
            for name in ("__init__", "ensure_runtime", "stop", "status", "dispose")
        },
    }


async def observe(case, monkeypatch):
    trace = []
    labels = {}
    start_entered = asyncio.Event()
    launch_gate = asyncio.Event()
    init_entered = asyncio.Event()
    init_gate = asyncio.Event()
    signal = object()
    clients = []
    definition = LspServerDefinition(
        id="sample",
        command=("controlled-lsp",),
        language_extensions={"python": (".py",)},
        environment={"BASE": "override", "EXTRA": "safe"},
    )
    key = LspServerKey("sample", Path("/controlled/workspace"))
    selection = LspServerSelection(
        "sample",
        "python",
        key.workspace_root,
        key.workspace_root / "x.py",
        "controlled",
    )

    class Handle:
        async def close(self):
            trace.append(["handle.close"])

    class Client:
        def __init__(self, handle, **kwargs):
            trace.append(["client.new"])
            self.handle = handle
            self.is_closed = False
            self.request_count = 2
            self.timeout_count = 1
            self.accepted_diagnostic_publications = 3
            self.discarded_diagnostic_publications = 4
            self.last_request_duration_ms = 5.0
            self.last_error = None
            self.failure = None
            clients.append(self)

        async def initialize(self, **kwargs):
            trace.append(["initialize", kwargs["root_uri"]])
            init_entered.set()
            if case == "initialize-abort-release-errors":
                raise labels["initialize"]
            if case == "stop-pending-start":
                try:
                    await init_gate.wait()
                finally:
                    trace.append(["initialize.finally"])

        async def abort(self):
            trace.append(["abort"])
            self.is_closed = True
            if case == "initialize-abort-release-errors":
                raise labels["abort"]

        async def shutdown(self):
            trace.append(["shutdown", self.failure is not None])
            self.is_closed = True
            if self.failure is not None:
                raise self.failure

    class Launcher:
        async def start(self, request, *, correlation_id, signal=None):
            trace.append(
                [
                    "launch",
                    correlation_id,
                    signal is globals_signal,
                    list(request.command),
                    request.cwd,
                    list(request.effective_environment),
                ]
            )
            start_entered.set()
            if case == "cancel-start-waiter-peer":
                await launch_gate.wait()
            if case == "launch-failure-no-client":
                raise labels["launch"]
            return Handle()

    def release(runtime_id):
        trace.append(["release.documents", runtime_id])
        if case == "initialize-abort-release-errors":
            raise labels["release"]

    class Diagnostics:
        def release_runtime(self, runtime_id):
            trace.append(["release.diagnostics", runtime_id])

        def counts(self, runtime_id):
            return 0, 0

    globals_signal = signal
    monkeypatch.setattr(code, "LspClient", Client)
    supervisor = code.LspServerSupervisor(
        catalog=LspCatalog([definition]),
        launcher=Launcher(),
        baseline_environment={"BASE": "original"},
        release_runtime_documents=release,
        diagnostics=Diagnostics(),
    )
    caught = None
    result = {}
    if case == "cancel-start-waiter-peer":
        first = asyncio.create_task(
            supervisor.ensure_runtime(selection, correlation_id="first", signal=signal)
        )
        await start_entered.wait()
        peer = asyncio.create_task(
            supervisor.ensure_runtime(selection, correlation_id="peer", signal=object())
        )
        await asyncio.sleep(0)
        shared = supervisor._starts[key]
        first.cancel()
        try:
            await first
        except asyncio.CancelledError as exc:
            caught = exc
        assert not shared.cancelled() and not shared.done()
        assert not peer.done()
        launch_gate.set()
        runtime = await peer
        again = await supervisor.ensure_runtime(selection, correlation_id="reused")
        assert runtime is again and runtime.client is clients[0]
        assert type(runtime) is code.LspRuntimeHandle
        assert len(clients) == 1 and runtime.runtime_id == 1
        result = {
            "same_runtime": runtime is again,
            "first_cancelled": first.cancelled(),
            "start_entry_removed": key not in supervisor._starts,
            "metadata": public_metadata(runtime),
        }
        await supervisor.dispose()
    elif case in {"launch-failure-no-client", "initialize-abort-release-errors"}:
        if case == "launch-failure-no-client":
            labels["launch"] = OSError("launch failed")
            labels["launch"].add_note("original launch note")
        else:
            labels.update(
                initialize=OSError("initialize failed"),
                abort=ValueError("abort suppressed"),
                release=LookupError("release replaces initialize"),
            )
            labels["initialize"].add_note("original initialize note")
        try:
            await supervisor.ensure_runtime(
                selection, correlation_id="failure", signal=signal
            )
        except BaseException as exc:
            caught = exc
        expected_error = (
            labels["launch"]
            if case == "launch-failure-no-client"
            else labels["release"]
        )
        assert caught is expected_error
        assert key not in supervisor._starts and key not in supervisor._runtimes
        if case == "launch-failure-no-client":
            assert not clients and supervisor._states[key] == "failed"
            assert supervisor._last_errors[key] == "initialization_failed"
        else:
            assert len(clients) == 1 and clients[0].is_closed
            assert caught.__context__ is labels["initialize"]
            assert (
                supervisor._states[key] == "starting"
                and key not in supervisor._last_errors
            )
            assert not any(item[0] == "release.diagnostics" for item in trace)
        result = {
            "status": dataclasses.asdict(supervisor.status()),
            "client_count": len(clients),
        }
        await supervisor.dispose()
    elif case == "dispose-error-order-retention":
        labels.update(
            stop=BaseException("stop failure first"),
            runtime_a=OSError("runtime a failure"),
            runtime_b=ValueError("runtime b failure"),
        )
        stop_key = LspServerKey("sample", Path("/controlled/stop"))

        async def failed_stop():
            trace.append(["retained.stop"])
            raise labels["stop"]

        stop_task = asyncio.create_task(failed_stop())
        supervisor._stops[stop_key] = stop_task
        for index, name in enumerate(("runtime_a", "runtime_b"), 1):
            runtime_key = LspServerKey("sample", Path(f"/controlled/runtime{index}"))
            client = Client(Handle())
            client.failure = labels[name]
            supervisor._runtimes[runtime_key] = code.LspRuntimeHandle(
                runtime_key, index, client
            )
            supervisor._remember_state(runtime_key, "ready")
        errors = []
        owned = None
        for _ in range(2):
            try:
                await supervisor.dispose()
            except BaseException as exc:
                errors.append(exc)
            if owned is None:
                owned = supervisor._dispose_task
            assert supervisor._dispose_task is owned
        assert len(errors) == 2 and errors[0] is errors[1] is labels["stop"]
        assert stop_task.done() and all(client.is_closed for client in clients)
        assert (
            trace.count(["retained.stop"]) == 1
            and sum(item[0] == "shutdown" for item in trace) == 2
        )
        assert (
            not supervisor._runtimes and not supervisor._stops and supervisor._disposed
        )
        caught = errors[0]
        result = {
            "same_retained_task": supervisor._dispose_task is owned,
            "same_error": errors[0] is errors[1],
            "owned_done": owned.done(),
            "all_clients_closed": all(client.is_closed for client in clients),
            "status": dataclasses.asdict(supervisor.status()),
        }
    elif case == "soft-status-budget":
        metrics = (
            "_last_errors",
            "_start_counts",
            "_request_counts",
            "_timeout_counts",
            "_accepted_diagnostic_counts",
            "_diagnostic_counts",
            "_last_request_durations",
        )
        keys = [LspServerKey("sample", Path(f"/controlled/key{i}")) for i in range(129)]
        client = SimpleNamespace(is_closed=False)
        for i, runtime_key in enumerate(keys):
            supervisor._runtimes[runtime_key] = code.LspRuntimeHandle(
                runtime_key, i, client
            )
            supervisor._remember_state(runtime_key, "ready")
        assert len(supervisor._states) == 129 and keys[0] in supervisor._states
        for name in metrics:
            getattr(supervisor, name)[keys[0]] = 7
        before = len(supervisor._states)
        supervisor._runtimes.pop(keys[0])
        supervisor._remember_state(keys[-1], "ready")
        assert len(supervisor._states) == 128 and keys[0] not in supervisor._states
        assert list(supervisor._states)[-1] == keys[-1]
        assert all(keys[0] not in getattr(supervisor, name) for name in metrics)
        result = {
            "protected_count": before,
            "after_inactive_count": len(supervisor._states),
            "oldest_inactive_removed": keys[0] not in supervisor._states,
            "newest_retained_last": list(supervisor._states)[-1] == keys[-1],
            "cleared_metric_maps": list(metrics),
        }
        supervisor._runtimes.clear()
    elif case == "stop-pending-start":
        waiter = asyncio.create_task(
            supervisor.ensure_runtime(
                selection, correlation_id="pending", signal=signal
            )
        )
        await init_entered.wait()
        stopped = await supervisor.stop(key)
        try:
            await waiter
        except asyncio.CancelledError as exc:
            caught = exc
        assert stopped and caught is not None and clients[0].is_closed
        assert (
            not supervisor._starts
            and not supervisor._stops
            and not supervisor._runtimes
        )
        assert (
            supervisor._states[key] == "stopped" and key not in supervisor._last_errors
        )
        result = {
            "stopped": stopped,
            "no_publication": key not in supervisor._runtimes,
            "status": dataclasses.asdict(supervisor.status()),
        }
        await supervisor.dispose()
    else:
        raise AssertionError(case)
    return json.loads(
        json.dumps(
            {"trace": trace, "result": result, "error": error_data(caught, labels)},
            ensure_ascii=False,
        )
    )


@pytest.mark.parametrize("case", CASES)
def test_original_supervisor(case, monkeypatch):
    observed = asyncio.run(observe(case, monkeypatch))
    assert observed == json.loads(gzip.decompress(EXPECTED.read_bytes()))[case]
