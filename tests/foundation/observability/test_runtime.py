from __future__ import annotations

import pytest

from loushang.foundation.observability import get_log, runtime
from loushang.foundation.observability._router import (
    configure_observability,
    reset_observability,
)
from loushang.foundation.observability.debug_sink import DebugLogSink
from loushang.foundation.observability.runtime import observability_runtime_context


class RecordingTrace:
    def __init__(self):
        self.events = []
        self.closed = False

    def write_debug_event(self, record):
        self.events.append(record)

    def write_problem(self, record):
        self.events.append(record)

    def close(self):
        self.closed = True


@pytest.mark.parametrize("fail", [False, True])
def test_injected_trace_is_borrowed_and_previous_sink_restored(tmp_path, monkeypatch, fail):
    previous, injected = RecordingTrace(), RecordingTrace()

    def forbidden(*args, **kwargs):
        pytest.fail("injected trace must not construct a file sink")

    monkeypatch.setattr(runtime, "TraceJSONLSink", forbidden)
    reset_observability()
    try:
        configure_observability(trace_sink=previous, trace_scopes={"host"})
        try:
            with observability_runtime_context(
                session_id=None, cwd=tmp_path, mode="managed",
                trace_sink=injected, trace_scopes=frozenset({"host"}),
            ):
                get_log("example").debug_event("host", "during")
                get_log("example").debug_event("other", "excluded")
                if fail:
                    raise RuntimeError("body failed")
        except RuntimeError:
            assert fail
        get_log("example").debug_event("host", "after")
        assert len(injected.events) == 1
        assert len(previous.events) == 1
        assert not injected.closed and not previous.closed
        assert not tuple(tmp_path.iterdir())
    finally:
        reset_observability()


def test_trace_path_and_injected_sink_conflict_before_reconfiguration(tmp_path):
    previous = RecordingTrace()
    reset_observability()
    try:
        configure_observability(trace_sink=previous, trace_scopes={"host"})
        with pytest.raises(ValueError, match="mutually exclusive"):
            with observability_runtime_context(
                session_id=None, cwd=tmp_path, mode="managed",
                trace_sink=RecordingTrace(), trace_path=tmp_path / "trace.jsonl",
            ):
                pytest.fail("conflicting configuration entered")
        get_log("example").debug_event("host", "after")
        assert len(previous.events) == 1
        assert not tuple(tmp_path.iterdir())
    finally:
        reset_observability()


def test_observability_runtime_context_restores_existing_debug_sink(tmp_path) -> None:
    before = tmp_path / "before.log"
    during = tmp_path / "during.log"
    reset_observability()
    try:
        configure_observability(debug_sink=DebugLogSink(before), debug_scopes={"host"})
        with observability_runtime_context(
            session_id="example-session",
            cwd=tmp_path,
            mode="example",
            debug_path=during,
            debug_scopes=frozenset({"host"}),
        ):
            get_log("example").debug_event("host", "during")
        get_log("example").debug_event("host", "after")
    finally:
        reset_observability()

    assert "during" in during.read_text(encoding="utf-8")
    assert "after" in before.read_text(encoding="utf-8")
