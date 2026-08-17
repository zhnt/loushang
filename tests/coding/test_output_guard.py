from __future__ import annotations

import sys
from io import StringIO


def test_stdout_guard_routes_prints_to_stderr_and_raw_writes_to_stdout(
    monkeypatch,
) -> None:
    from loushang.harness.host.stdout_guard import (
        flush_raw_stdout,
        is_stdout_taken_over,
        stdout_guard,
        write_raw_stdout,
    )

    process_stdout = StringIO()
    process_stderr = StringIO()
    raw_stdout = StringIO()
    raw_stderr = StringIO()
    monkeypatch.setattr(sys, "stdout", process_stdout)
    monkeypatch.setattr(sys, "stderr", process_stderr)

    with stdout_guard(stdout=raw_stdout, stderr=raw_stderr):
        assert is_stdout_taken_over()
        print("incidental chatter")
        write_raw_stdout('{"type":"result"}\n')
        flush_raw_stdout()

    assert not is_stdout_taken_over()
    assert sys.stdout is process_stdout
    assert process_stdout.getvalue() == ""
    assert process_stderr.getvalue() == ""
    assert raw_stdout.getvalue() == '{"type":"result"}\n'
    assert raw_stderr.getvalue() == "incidental chatter\n"


def test_stdout_guard_nested_context_restores_only_outer_owner(monkeypatch) -> None:
    from loushang.harness.host.stdout_guard import is_stdout_taken_over, stdout_guard

    process_stdout = StringIO()
    raw_stderr = StringIO()
    monkeypatch.setattr(sys, "stdout", process_stdout)

    with stdout_guard(stderr=raw_stderr):
        outer_stdout = sys.stdout
        with stdout_guard(stderr=StringIO()):
            assert is_stdout_taken_over()
            assert sys.stdout is outer_stdout
        assert is_stdout_taken_over()
        print("still guarded")

    assert not is_stdout_taken_over()
    assert sys.stdout is process_stdout
    assert raw_stderr.getvalue() == "still guarded\n"
