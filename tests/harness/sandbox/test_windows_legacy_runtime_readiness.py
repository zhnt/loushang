from __future__ import annotations

from pathlib import Path

import pytest

from loushang.harness.sandbox import package_windows_legacy_runtime as runtime


def test_empty_readiness_publication_is_retried_while_process_lives(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ready_path = tmp_path / "ready.txt"
    ready_path.write_bytes(b"")
    token = "a" * 64

    monkeypatch.setattr(
        runtime,
        "_process_exit_code",
        lambda process: runtime._STILL_ACTIVE,
    )

    def publish_ready(_seconds: float) -> None:
        ready_path.write_bytes(token.encode("ascii") + b"\r\n")

    monkeypatch.setattr(runtime.time, "sleep", publish_ready)

    runtime._await_ready(ready_path, token, process=1, timeout=1.0)


def test_nonempty_readiness_mismatch_still_fails_closed(tmp_path: Path) -> None:
    ready_path = tmp_path / "ready.txt"
    ready_path.write_bytes(b"wrong-token\r\n")

    with pytest.raises(OSError, match="readiness changed"):
        runtime._await_ready(ready_path, "a" * 64, process=1, timeout=1.0)


def test_empty_readiness_fails_when_process_has_exited(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ready_path = tmp_path / "ready.txt"
    ready_path.write_bytes(b"")
    monkeypatch.setattr(runtime, "_process_exit_code", lambda process: 1)

    with pytest.raises(OSError, match="exited before readiness"):
        runtime._await_ready(ready_path, "a" * 64, process=1, timeout=1.0)
