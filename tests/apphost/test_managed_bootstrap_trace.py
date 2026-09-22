from __future__ import annotations

import asyncio
import json
from pathlib import Path
from time import monotonic

import pytest

from loushang.apphost.managed._files import ManagedStorageError
from loushang.foundation.observability.records import DebugEventRecord
from loushang.foundation.observability.runtime import observability_runtime_context

from . import test_managed_bootstrap as fixtures
from . import test_managed_child as child_fixtures

deployment = fixtures.deployment
pytestmark = fixtures.pytestmark


@pytest.mark.parametrize("trace_first", [False, True])
def test_bootstrap_formats_share_one_native_directory_admission(deployment, tmp_path, monkeypatch, trace_first):
    _, _, journal, state, paths = deployment
    Path(paths.logs).mkdir(mode=0o700)
    owner, parent = fixtures.make_bootstrap(deployment, tmp_path, diagnostics=True)
    try:
        owner.open(deadline=monotonic() + 5)
        deadline = monotonic() + 30
        buffer = owner.prepare_trace(deadline=deadline)
        assert owner.prepare_trace(deadline=deadline) is buffer
        with pytest.raises(ManagedStorageError, match="conflict"):
            owner.prepare_trace(deadline=deadline + 1)
        assert not tuple(Path(paths.logs).iterdir())
        journal.register_native(state.handoff.instance, state.handoff.attempt_id,
                                owner._observer.identity, deadline=monotonic() + 5)
        buffer.write_debug_event(DebugEventRecord("turn.start.performance", "turn", {"total_ms": 1}))
        frame = buffer.take()
        assert frame is not None
        directory = owner._log_directory
        original = directory.open
        opens = []
        def counted(**kwargs):
            opens.append(kwargs)
            original(**kwargs)
        monkeypatch.setattr(directory, "open", counted)
        def write_trace():
            owner._record_trace(frame, deadline)
        def write_lifecycle():
            owner._record_lifecycle("ready", None)
        for write in ((write_trace, write_lifecycle) if trace_first else (write_lifecycle, write_trace)):
            write()
        assert len(opens) == 1
        assert owner._trace_writer._directory is owner._log_writer._directory is directory
        assert json.loads((Path(paths.logs) / "trace-0.jsonl").read_bytes())["record"]["instanceId"] == state.handoff.instance.instance_id
    finally:
        owner.close()
        parent.close()
    buffer.write_debug_event(DebugEventRecord("turn.start.performance", "turn", {"total_ms": 2}))
    assert buffer.take() is None


def test_failed_shared_directory_admission_is_not_replayed_by_other_format(deployment, tmp_path, monkeypatch):
    _, _, journal, state, _ = deployment
    owner, parent = fixtures.make_bootstrap(deployment, tmp_path, diagnostics=True)
    try:
        owner.open(deadline=monotonic() + 5)
        deadline = monotonic() + 30
        buffer = owner.prepare_trace(deadline=deadline)
        journal.register_native(state.handoff.instance, state.handoff.attempt_id,
                                owner._observer.identity, deadline=monotonic() + 5)
        calls = []
        def failed(**kwargs):
            calls.append(kwargs)
            raise ManagedStorageError("unavailable")
        monkeypatch.setattr(owner._log_directory, "open", failed)
        with pytest.raises(ManagedStorageError, match="unavailable"):
            owner._record_lifecycle("ready", None)
        buffer.write_debug_event(DebugEventRecord("turn.start.performance", "turn", {"total_ms": 1}))
        with pytest.raises(ManagedStorageError, match="closed"):
            owner._record_trace(buffer.take(), deadline)
        assert len(calls) == 1
    finally:
        owner.close()
        parent.close()


@pytest.mark.parametrize("installed,diagnostics", [(False, False), (True, False), (True, True)])
def test_trace_only_bootstrap_does_not_enable_or_charge_lifecycle(deployment, tmp_path, installed, diagnostics):
    _, _, journal, state, paths = deployment
    Path(paths.logs).mkdir(mode=0o700)
    owner, parent = fixtures.make_bootstrap(deployment, tmp_path, diagnostics=diagnostics)
    try:
        owner.open(deadline=monotonic() + 5)
        buffer = owner.prepare_trace(deadline=monotonic() + 30)
        journal.register_native(state.handoff.instance, state.handoff.attempt_id,
                                owner._observer.identity, deadline=monotonic() + 5)
        child = owner.bind(child_fixtures.Application())
        assert (child._diagnostic is not None) == diagnostics
        assert journal.read().trace_application is None
        async def run():
            waiter = asyncio.create_task(owner.run())
            try:
                await child_fixtures.until(lambda: child.accepting)
                buffer.write_debug_event(DebugEventRecord("turn.start.performance", "turn", {"total_ms": 2}))
                await child_fixtures.until(lambda: child._diagnostic_task.done()
                    and (child._trace_initialized or child._trace_disabled))
            finally:
                await child.close()
                assert await waiter == 0
        with observability_runtime_context(session_id=None, cwd=tmp_path, mode="managed",
                trace_sink=buffer, trace_scopes=frozenset({"turn.start.performance"})):
            if installed:
                owner.trace_sink_installed(buffer)
            asyncio.run(asyncio.wait_for(run(), 10))
        expected_names = {"trace.lock", "trace-0.jsonl", "trace-1.jsonl"} if installed else set()
        if diagnostics:
            expected_names |= {"lifecycle.lock", "lifecycle-0.jsonl"}
        assert {path.name for path in Path(paths.logs).iterdir()} == expected_names
        receipt = journal.read().trace_application
        assert (receipt is not None) == installed
        if installed:
            assert receipt.instance_id == state.handoff.instance.instance_id
            assert receipt.attempt_id == state.handoff.attempt_id
            assert receipt.deadline_ms == round(buffer.deadline * 1000)
        with journal._database.transaction() as connection:
            expected = ([("log", 1)] if diagnostics else []) + ([("trace", 2)] if installed else [])
            assert connection.execute("SELECT kind, count(*) FROM storage_allocations GROUP BY kind ORDER BY kind").fetchall() == expected
    finally:
        owner.close()
        parent.close()
