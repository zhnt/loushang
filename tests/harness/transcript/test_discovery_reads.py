from __future__ import annotations

import os

import pytest

from loushang.harness.transcript.jsonl_file import (
    AgentTranscriptFileError,
    AgentTranscriptFileLayout,
    load_agent_transcript_header,
)


def test_discovery_enumeration_is_streamed_and_closes_at_candidate_bound(tmp_path, monkeypatch):
    (tmp_path / "one.jsonl").write_text("{}\n")
    (tmp_path / "two.jsonl").write_text("{}\n")
    original = os.scandir
    observed = []

    class Scan:
        def __enter__(self):
            self.scan = original(tmp_path)
            return self

        def __exit__(self, *_args):
            self.scan.close()
            observed.append("closed")

        def __iter__(self):
            for entry in self.scan:
                observed.append("entry")
                yield entry

    def forbidden(*_args):
        raise AssertionError("eager directory enumeration")

    monkeypatch.setattr(os, "listdir", forbidden)
    monkeypatch.setattr(os, "scandir", lambda *_args: Scan())
    layout = AgentTranscriptFileLayout(tmp_path)
    snapshot = layout.scan_candidate_path_snapshot(layout.namespace, max_candidates=1)
    assert len(snapshot.paths) == 1 and not snapshot.complete
    assert observed == ["entry", "entry", "closed"]
    observed.clear()
    assert not layout.scan_candidate_path_snapshot(
        layout.namespace, should_stop=lambda: True,
    ).complete
    assert observed == []


def test_discovery_header_read_does_not_create_missing_lock(tmp_path):
    path = tmp_path / "one.jsonl"
    path.write_text("{}\n")
    with pytest.raises(AgentTranscriptFileError):
        load_agent_transcript_header(path, blocking=False, create_lock=False)
    assert not path.with_suffix(".jsonl.lock").exists()


def test_discovery_can_distinguish_directory_io_error(tmp_path, monkeypatch):
    def unavailable(*_args):
        raise PermissionError("private path")
    monkeypatch.setattr(os, "scandir", unavailable)
    layout = AgentTranscriptFileLayout(tmp_path)
    with pytest.raises(PermissionError):
        layout.scan_candidate_path_snapshot(layout.namespace, raise_on_error=True)
    assert not layout.scan_candidate_path_snapshot(layout.namespace).complete
