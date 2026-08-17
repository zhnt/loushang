from __future__ import annotations

from loushang.foundation.observability import get_log
from loushang.foundation.observability._router import (
    configure_observability,
    reset_observability,
)
from loushang.foundation.observability.debug_sink import DebugLogSink
from loushang.foundation.observability.runtime import observability_runtime_context


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
