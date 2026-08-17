from __future__ import annotations

from types import SimpleNamespace

from loushang.foundation.observability import get_log
from loushang.foundation.observability._router import reset_observability
from loushang.harness.diagnostics.observability_runtime import (
    session_observability_context,
)


def test_session_observability_context_accepts_product_output_directories(tmp_path) -> None:
    debug_dir = tmp_path / "debug"
    trace_dir = tmp_path / "trace"
    args = SimpleNamespace(debug="", trace="all", debug_file=None, trace_file=None)
    session = SimpleNamespace(session_id="harness-session", diagnostics_service=None)

    reset_observability()
    try:
        with session_observability_context(
            args=args,
            session=session,
            cwd=tmp_path,
            mode="test",
            debug_dir=debug_dir,
            trace_dir=trace_dir,
        ):
            get_log("loushang.tests.harness").debug_event("test", "runtime.bound")
    finally:
        reset_observability()

    assert (debug_dir / "harness-session.log").exists()
    assert (trace_dir / "harness-session.jsonl").exists()
