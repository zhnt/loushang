"""Safety budgets for the optional test-child observer."""

from __future__ import annotations

import json
import os

import pytest

from ._hosted_boundary_trace import (
    MAX_RECORD_BYTES,
    MAX_RECORDS,
    BoundaryTrace,
    text_shape,
)


def test_observer_is_inert_without_explicit_private_root(monkeypatch, tmp_path, capsys):
    from . import _hosted_boundary_trace as observer

    monkeypatch.delenv(observer.TRACE_ENV, raising=False)
    monkeypatch.setattr(observer, "_writer", None)
    monkeypatch.chdir(tmp_path)
    observer.install()
    observer.emit("ignored")
    assert observer._writer is None
    assert tuple(tmp_path.iterdir()) == ()
    assert capsys.readouterr().out == ""


def test_trace_bounds_records_bytes_permissions_and_omits_text(tmp_path):
    trace = BoundaryTrace(tmp_path)
    secret = "private input sentinel"
    for _ in range(MAX_RECORDS + 10):
        trace.emit("input", input=text_shape(secret))
    payload = trace.path.read_bytes()
    rows = [json.loads(line) for line in payload.splitlines()]
    assert len(rows) == MAX_RECORDS
    assert [row["sequence"] for row in rows] == list(range(MAX_RECORDS))
    assert len(payload) <= MAX_RECORD_BYTES * MAX_RECORDS
    assert secret.encode() not in payload
    if os.name != "nt":
        assert trace.path.stat().st_mode & 0o777 == 0o600
    assert text_shape("hold")["exact_hold"]
    assert not text_shape("hold\n")["exact_hold"]
    assert text_shape("hold\n")["stripped_hold"]


def test_trace_rejects_oversized_record_before_write(tmp_path):
    trace = BoundaryTrace(tmp_path)
    with pytest.raises(ValueError, match="budget"):
        trace.emit("oversized", field="x" * MAX_RECORD_BYTES)
    assert trace.path.read_bytes() == b""


@pytest.mark.skipif(not hasattr(os, "O_NOFOLLOW"), reason="requires POSIX no-follow")
def test_trace_does_not_follow_replaced_file(tmp_path):
    trace = BoundaryTrace(tmp_path)
    target = tmp_path / "untouched"
    target.write_text("sentinel")
    trace.path.unlink()
    trace.path.symlink_to(target)
    with pytest.raises(OSError):
        trace.emit("input")
    assert target.read_text() == "sentinel"
