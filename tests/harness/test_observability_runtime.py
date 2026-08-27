from __future__ import annotations

import os
import stat
from types import SimpleNamespace

from loushang.foundation.observability import get_log
from loushang.foundation.observability._router import reset_observability
from loushang.harness.diagnostics.observability_runtime import (
    session_observability_context,
)


def test_session_observability_context_accepts_product_output_directories(
    tmp_path,
) -> None:
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


def test_session_observability_context_uses_platform_state_roots(
    tmp_path,
    monkeypatch,
) -> None:
    platform_home = tmp_path / "user-home"
    monkeypatch.setenv("LOUSHANG_HOME", str(platform_home))
    args = SimpleNamespace(
        debug="all",
        trace="all",
        debug_file=None,
        trace_file=None,
    )
    session = SimpleNamespace(session_id="shared-session", diagnostics_service=None)

    reset_observability()
    try:
        with session_observability_context(
            args=args,
            session=session,
            cwd=tmp_path,
            mode="test",
        ):
            get_log("loushang.tests.harness").debug_event("test", "runtime.bound")
    finally:
        reset_observability()

    assert (platform_home / "state" / "debug" / "shared-session.log").exists()
    assert (platform_home / "state" / "traces" / "shared-session.jsonl").exists()
    if os.name == "posix":
        assert (
            stat.S_IMODE(
                (platform_home / "state" / "debug" / "shared-session.log")
                .stat()
                .st_mode
            )
            == 0o600
        )
        assert (
            stat.S_IMODE(
                (platform_home / "state" / "traces" / "shared-session.jsonl")
                .stat()
                .st_mode
            )
            == 0o600
        )
