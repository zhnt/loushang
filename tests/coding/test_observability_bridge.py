from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

from loushang.coding.diagnostics.profile import coding_diagnostic_source
from loushang.harness.diagnostics.observability_runtime import (
    session_observability_context,
)


@contextmanager
def coding_observability_context(**kwargs):
    with session_observability_context(
        **kwargs,
        source_resolver=coding_diagnostic_source,
    ):
        yield


def test_coding_observability_context_bridges_problems_to_diagnostics(tmp_path) -> None:
    from loushang.foundation.observability import get_log
    from loushang.foundation.observability._router import get_problem_store
    from loushang.harness.diagnostics import DiagnosticsService

    diagnostics = DiagnosticsService()
    session = SimpleNamespace(session_id="session-1", diagnostics_service=diagnostics)
    args = SimpleNamespace(debug=None, trace=None, debug_file=None, trace_file=None)

    with coding_observability_context(args=args, session=session, cwd=tmp_path, mode="tui"):
        get_log("loushang.tests.tool").problem(
            "tool_validation_failed",
            source="tool",
            message="Validation failed for write",
            recoverable=True,
            tool_call_id="tc1",
            tool_name="write",
        )

        assert [record.code for record in get_problem_store().all()] == ["tool_validation_failed"]

    records = diagnostics.get_last_diagnostics()
    assert len(records) == 1
    assert records[0].code == "tool_validation_failed"
    assert records[0].type == "error"
    assert records[0].source == "tool"
    assert records[0].phase == "runtime"
    assert records[0].session_id == "session-1"
    assert records[0].message == "Validation failed for write"
    assert records[0].details == {
        "mode": "tui",
        "problem_source": "tool",
        "recoverable": True,
        "tool_call_id": "tc1",
        "tool_name": "write",
    }


def test_coding_observability_context_maps_config_problem_to_model_diagnostic(tmp_path) -> None:
    from loushang.foundation.observability import get_log
    from loushang.harness.diagnostics import DiagnosticsService

    diagnostics = DiagnosticsService()
    session = SimpleNamespace(session_id="session-1", diagnostics_service=diagnostics)
    args = SimpleNamespace(debug=None, trace=None, debug_file=None, trace_file=None)

    with coding_observability_context(args=args, session=session, cwd=tmp_path, mode="startup"):
        get_log("loushang.tests.model").problem(
            "model_selection_ambiguous",
            source="config",
            message="Ambiguous model selection: faux:alpha",
            recoverable=True,
            provider_id="faux",
            model_id="alpha",
        )

    records = diagnostics.get_last_diagnostics()
    assert len(records) == 1
    assert records[0].source == "model"
    assert records[0].phase == "startup"
    assert records[0].details["problem_source"] == "config"
    assert records[0].details["provider_id"] == "faux"


def test_coding_observability_context_uses_stable_debug_env(monkeypatch, tmp_path) -> None:
    from loushang.foundation.observability import get_log

    debug_path = tmp_path / "env-debug.log"
    monkeypatch.setenv("LOUSHANG_DEBUG_SCOPES", "tui")
    monkeypatch.setenv("LOUSHANG_DEBUG_FILE", str(debug_path))
    args = SimpleNamespace(debug=None, trace=None, debug_file=None, trace_file=None)
    session = SimpleNamespace(session_id="session-1", diagnostics_service=None)

    with coding_observability_context(args=args, session=session, cwd=tmp_path, mode="tui"):
        get_log("loushang.tests.ui").debug_event("tui", "prompt.start")

    assert "DEBUG_EVENT tui prompt.start" in debug_path.read_text(encoding="utf-8")


def test_coding_observability_context_cli_debug_overrides_env(monkeypatch, tmp_path) -> None:
    from loushang.foundation.observability import get_log

    env_debug_path = tmp_path / "env-debug.log"
    cli_debug_path = tmp_path / "cli-debug.log"
    monkeypatch.setenv("LOUSHANG_DEBUG_SCOPES", "provider")
    monkeypatch.setenv("LOUSHANG_DEBUG_FILE", str(env_debug_path))
    args = SimpleNamespace(debug="tui", trace=None, debug_file=str(cli_debug_path), trace_file=None)
    session = SimpleNamespace(session_id="session-1", diagnostics_service=None)

    with coding_observability_context(args=args, session=session, cwd=tmp_path, mode="tui"):
        get_log("loushang.tests.provider").debug_event("provider", "chunk.start")
        get_log("loushang.tests.ui").debug_event("tui", "prompt.start")

    assert not env_debug_path.exists()
    assert "prompt.start" in cli_debug_path.read_text(encoding="utf-8")
    assert "chunk.start" not in cli_debug_path.read_text(encoding="utf-8")


def test_coding_observability_context_bare_debug_enables_all_debug_scopes(tmp_path) -> None:
    from loushang.foundation.observability import get_log

    debug_path = tmp_path / "debug.log"
    args = SimpleNamespace(debug="", trace=None, debug_file=str(debug_path), trace_file=None)
    session = SimpleNamespace(session_id="session-1", diagnostics_service=None)

    with coding_observability_context(args=args, session=session, cwd=tmp_path, mode="tui"):
        get_log("loushang.tests.provider").debug_event("provider", "chunk.start")
        get_log("loushang.tests.ui").debug_event("tui", "prompt.start")

    debug_text = debug_path.read_text(encoding="utf-8")
    assert "DEBUG_EVENT provider chunk.start" in debug_text
    assert "DEBUG_EVENT tui prompt.start" in debug_text


def test_coding_observability_context_uses_stable_trace_env(monkeypatch, tmp_path) -> None:
    import json

    from loushang.foundation.observability import get_log

    trace_path = tmp_path / "env-trace.jsonl"
    monkeypatch.setenv("LOUSHANG_TRACE_SCOPES", "provider")
    monkeypatch.setenv("LOUSHANG_TRACE_FILE", str(trace_path))
    args = SimpleNamespace(debug=None, trace=None, debug_file=None, trace_file=None)
    session = SimpleNamespace(session_id="session-1", diagnostics_service=None)

    with coding_observability_context(args=args, session=session, cwd=tmp_path, mode="tui"):
        get_log("loushang.tests.provider").debug_event("provider", "chunk.start")
        get_log("loushang.tests.ui").debug_event("tui", "prompt.start")

    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert [record["name"] for record in records] == ["chunk.start"]


def test_coding_observability_context_reuses_startup_label_for_default_files(monkeypatch, tmp_path) -> None:
    from loushang.foundation.observability import get_log
    from loushang.harness.diagnostics import observability_runtime

    debug_dir = tmp_path / "debug"
    trace_dir = tmp_path / "traces"
    times = iter([1.0, 2.0])
    monkeypatch.setattr(observability_runtime.time, "time", lambda: next(times))
    args = SimpleNamespace(debug="", trace="tui", debug_file=None, trace_file=None)
    session = SimpleNamespace(session_id=None, diagnostics_service=None)

    with coding_observability_context(
        args=args,
        session=session,
        cwd=tmp_path,
        mode="startup",
        debug_dir=debug_dir,
        trace_dir=trace_dir,
    ):
        get_log("loushang.tests.ui").debug_event("tui", "startup.trace")

    debug_files = list(debug_dir.glob("startup-*.log"))
    trace_files = list(trace_dir.glob("startup-*.jsonl"))
    assert len(debug_files) == 1
    assert len(trace_files) == 1
    assert debug_files[0].with_suffix("").name == trace_files[0].with_suffix("").name


def test_coding_observability_context_preserves_existing_trace_when_bridging_problems(tmp_path) -> None:
    import json

    from loushang.foundation.observability import get_log
    from loushang.foundation.observability._router import (
        configure_observability,
        reset_observability,
    )
    from loushang.foundation.observability.trace_sink import TraceJSONLSink
    from loushang.harness.diagnostics import DiagnosticsService

    trace_path = tmp_path / "trace.jsonl"
    diagnostics = DiagnosticsService()
    args = SimpleNamespace(debug=None, trace=None, debug_file=None, trace_file=None)
    session = SimpleNamespace(session_id="session-1", diagnostics_service=diagnostics)

    reset_observability()
    try:
        configure_observability(trace_sink=TraceJSONLSink(trace_path), trace_scopes={"provider"})
        with coding_observability_context(args=args, session=session, cwd=tmp_path, mode="tui"):
            get_log("loushang.tests.provider").debug_event("provider", "chunk.start")
            get_log("loushang.tests.tool").problem("tool_validation_failed", source="tool")
    finally:
        reset_observability()

    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert [record["name"] for record in records] == ["chunk.start"]
    assert [record.code for record in diagnostics.get_last_diagnostics()] == ["tool_validation_failed"]


def test_coding_observability_context_restores_existing_trace_after_exit(tmp_path) -> None:
    import json

    from loushang.foundation.observability import get_log
    from loushang.foundation.observability._router import (
        configure_observability,
        reset_observability,
    )
    from loushang.foundation.observability.trace_sink import TraceJSONLSink
    from loushang.harness.diagnostics import DiagnosticsService

    trace_path = tmp_path / "trace.jsonl"
    diagnostics = DiagnosticsService()
    args = SimpleNamespace(debug=None, trace=None, debug_file=None, trace_file=None)
    session = SimpleNamespace(session_id="session-1", diagnostics_service=diagnostics)

    reset_observability()
    try:
        configure_observability(trace_sink=TraceJSONLSink(trace_path), trace_scopes={"provider"})
        with coding_observability_context(args=args, session=session, cwd=tmp_path, mode="tui"):
            get_log("loushang.tests.tool").problem("tool_validation_failed", source="tool")
        get_log("loushang.tests.provider").debug_event("provider", "after.exit")
    finally:
        reset_observability()

    records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    assert [record["name"] for record in records] == ["after.exit"]
