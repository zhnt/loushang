from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

import pytest

from loushang.harness.runtime.session_operations import (
    CancelledSessionOperation,
    SessionOperationCandidate,
    SessionOperationCoordinator,
    SessionOperationPhase,
    copy_file_exclusive,
    file_status_fingerprint,
    stage_file_import,
)
from loushang.harness.runtime.transition import SessionTransitionHost


def test_copy_file_exclusive_atomically_publishes_private_content(tmp_path) -> None:
    source = tmp_path / "source.jsonl"
    destination = tmp_path / "destination.jsonl"
    source.write_bytes(b"complete transcript\n")

    copy_file_exclusive(source, destination)

    assert destination.read_bytes() == b"complete transcript\n"
    if os.name == "posix":
        assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert list(tmp_path.glob(f".{destination.name}.*.tmp")) == []


def test_copy_file_exclusive_never_publishes_a_partial_copy(
    tmp_path,
    monkeypatch,
) -> None:
    from loushang.harness.runtime import session_operations

    source = tmp_path / "source.jsonl"
    destination = tmp_path / "destination.jsonl"
    source.write_bytes(b"complete transcript\n")

    def fail_after_partial_copy(_input, output) -> None:
        output.write(b"partial")
        raise OSError("copy interrupted")

    monkeypatch.setattr(session_operations, "copyfileobj", fail_after_partial_copy)

    with pytest.raises(OSError, match="copy interrupted"):
        copy_file_exclusive(source, destination)

    assert destination.exists() is False
    assert list(tmp_path.glob(f".{destination.name}.*.tmp")) == []


def test_copy_file_exclusive_does_not_replace_an_existing_destination(
    tmp_path,
) -> None:
    source = tmp_path / "source.jsonl"
    destination = tmp_path / "destination.jsonl"
    source.write_bytes(b"new transcript\n")
    destination.write_bytes(b"existing transcript\n")

    with pytest.raises(FileExistsError):
        copy_file_exclusive(source, destination)

    assert destination.read_bytes() == b"existing transcript\n"
    assert list(tmp_path.glob(f".{destination.name}.*.tmp")) == []


def test_copy_file_exclusive_rejects_a_linked_source(tmp_path) -> None:
    outside = tmp_path / "outside.jsonl"
    linked = tmp_path / "linked.jsonl"
    destination = tmp_path / "destination.jsonl"
    outside.write_bytes(b"outside transcript\n")
    try:
        linked.symlink_to(outside)
    except (NotImplementedError, OSError):
        pytest.skip("file symlinks are unavailable")

    with pytest.raises(OSError, match="regular file"):
        copy_file_exclusive(linked, destination)

    assert destination.exists() is False
    assert outside.read_bytes() == b"outside transcript\n"


def test_copy_file_exclusive_binds_the_discovered_source_identity(tmp_path) -> None:
    source = tmp_path / "source.jsonl"
    replacement = tmp_path / "replacement.jsonl"
    destination = tmp_path / "destination.jsonl"
    source.write_bytes(b"selected transcript\n")
    expected = file_status_fingerprint(source.lstat())
    replacement.write_bytes(b"replacement transcript\n")
    replacement.replace(source)

    with pytest.raises(OSError, match="no longer matches discovery"):
        copy_file_exclusive(
            source,
            destination,
            expected_source_fingerprint=expected,
        )

    assert destination.exists() is False


def test_stage_file_import_preserves_legacy_two_argument_copy_port(tmp_path) -> None:
    source = tmp_path / "source.jsonl"
    destination_dir = tmp_path / "authority"
    source.write_bytes(b"selected transcript\n")
    expected = file_status_fingerprint(source.lstat())
    calls: list[tuple[Path, Path]] = []

    def legacy_copy(selected: Path, destination: Path) -> None:
        calls.append((selected, destination))
        destination.write_bytes(selected.read_bytes())

    staged = stage_file_import(
        source,
        destination_dir,
        copy_file=legacy_copy,
        expected_source_fingerprint=expected,
    )

    assert calls == [(source, staged.destination)]
    assert staged.destination.read_bytes() == b"selected transcript\n"


def test_copy_file_exclusive_rejects_a_source_append_without_reading_to_eof(
    tmp_path,
    monkeypatch,
) -> None:
    from loushang.harness.runtime import session_operations

    source = tmp_path / "source.jsonl"
    destination = tmp_path / "destination.jsonl"
    source.write_bytes(b"fixed snapshot\n")
    copy = session_operations.copyfileobj

    def append_during_copy(input_handle, output_handle) -> None:
        with source.open("ab") as source_handle:
            source_handle.write(b"racing append\n")
        copy(input_handle, output_handle)

    monkeypatch.setattr(session_operations, "copyfileobj", append_during_copy)

    with pytest.raises(OSError, match="changed while copying"):
        copy_file_exclusive(source, destination)

    assert destination.exists() is False
    assert list(tmp_path.glob(f".{destination.name}.*.tmp")) == []


def test_session_operation_orders_prepare_replace_and_commit() -> None:
    events: list[str] = []
    host = SessionTransitionHost(
        "first",
        dispose=lambda session: events.append(f"dispose:{session}"),
    )
    coordinator = SessionOperationCoordinator(host)

    async def scenario() -> object:
        return await coordinator.run(
            lambda current: (
                events.append(f"prepare:{current}"),
                SessionOperationCandidate("second", "payload"),
            )[1],
            prepare_session=lambda candidate, _previous: events.append(
                f"bind:{candidate.session}:{candidate.payload}"
            ),
            before_release=lambda previous, candidate: events.append(
                f"release:{previous}:{candidate.session}"
            ),
            activate=lambda candidate, _previous: events.append(
                f"activate:{candidate.session}"
            ),
            after_commit=lambda result: events.append(
                f"commit:{result.previous}:{result.current}:{result.payload}"
            ),
        )

    result = asyncio.run(scenario())

    assert result.cancelled is False
    assert result.changed is True
    assert events == [
        "prepare:first",
        "bind:second:payload",
        "release:first:second",
        "dispose:first",
        "activate:second",
        "commit:first:second:payload",
    ]


def test_session_operation_cancellation_keeps_current_and_cleans_up() -> None:
    events: list[str] = []
    host = SessionTransitionHost(
        "first", dispose=lambda session: events.append(session)
    )
    coordinator = SessionOperationCoordinator(host)

    result = asyncio.run(
        coordinator.run(
            lambda _current: CancelledSessionOperation(
                "not-selected",
                cleanup=lambda: events.append("cleanup"),
            )
        )
    )

    assert result.cancelled is True
    assert result.changed is False
    assert result.current == "first"
    assert result.payload == "not-selected"
    assert events == ["cleanup"]


def test_session_operation_rolls_back_uncommitted_candidate_and_reports_phase() -> None:
    events: list[str] = []
    host = SessionTransitionHost(
        "first", dispose=lambda session: events.append(f"dispose:{session}")
    )
    coordinator = SessionOperationCoordinator(host)

    def fail_bind(candidate: object, previous: object) -> None:
        del candidate, previous
        raise RuntimeError("bind failed")

    with pytest.raises(RuntimeError, match="bind failed"):
        asyncio.run(
            coordinator.run(
                lambda _current: SessionOperationCandidate(
                    "second",
                    None,
                    rollback=lambda: events.append("rollback"),
                ),
                prepare_session=fail_bind,
                on_failure=lambda failure: events.append(f"failure:{failure.phase}"),
            )
        )

    assert host.current == "first"
    assert events == [
        "rollback",
        f"failure:{SessionOperationPhase.REPLACE}",
    ]


def test_session_operation_reports_after_commit_without_rolling_back() -> None:
    events: list[str] = []
    host = SessionTransitionHost(
        "first", dispose=lambda session: events.append(f"dispose:{session}")
    )
    coordinator = SessionOperationCoordinator(host)

    def fail_callback(_result: object) -> None:
        raise RuntimeError("callback failed")

    with pytest.raises(RuntimeError, match="callback failed"):
        asyncio.run(
            coordinator.run(
                lambda _current: SessionOperationCandidate(
                    "second",
                    None,
                    rollback=lambda: events.append("rollback"),
                ),
                after_commit=fail_callback,
                on_failure=lambda failure: events.append(f"failure:{failure.phase}"),
            )
        )

    assert host.current == "second"
    assert events == [
        "dispose:first",
        f"failure:{SessionOperationPhase.AFTER_COMMIT}",
    ]


def test_session_operation_invalidation_failure_has_no_false_current() -> None:
    events: list[str] = []

    def fail_dispose(session: str) -> None:
        events.append(f"dispose:{session}")
        raise RuntimeError("dispose failed")

    host = SessionTransitionHost("first", dispose=fail_dispose)
    coordinator = SessionOperationCoordinator(host)

    with pytest.raises(RuntimeError, match="dispose failed"):
        asyncio.run(
            coordinator.run(
                lambda _current: SessionOperationCandidate(
                    "second",
                    None,
                    rollback=lambda: events.append("rollback"),
                ),
                on_failure=lambda failure: events.append(
                    f"failure:{failure.phase}:{failure.current}"
                ),
            )
        )

    assert host.current is None
    assert events == [
        "dispose:first",
        "rollback",
        f"failure:{SessionOperationPhase.REPLACE}:None",
    ]


def test_session_operation_rebind_failure_reports_published_candidate() -> None:
    events: list[str] = []

    def fail_rebind(session: str) -> None:
        events.append(f"rebind:{session}")
        raise RuntimeError("rebind failed")

    host = SessionTransitionHost(
        "first",
        dispose=lambda session: events.append(f"dispose:{session}"),
        rebind=fail_rebind,
    )
    coordinator = SessionOperationCoordinator(host)

    with pytest.raises(RuntimeError, match="rebind failed"):
        asyncio.run(
            coordinator.run(
                lambda _current: SessionOperationCandidate(
                    "second",
                    None,
                    rollback=lambda: events.append("rollback"),
                ),
                on_failure=lambda failure: events.append(
                    f"failure:{failure.phase}:{failure.current}"
                ),
            )
        )

    assert host.current == "second"
    assert events == [
        "dispose:first",
        "rebind:second",
        f"failure:{SessionOperationPhase.AFTER_COMMIT}:second",
    ]


def test_session_operation_cancellation_rolls_back_staged_candidate(tmp_path) -> None:
    staged_file = tmp_path / "staged.jsonl"
    staged_file.write_text("candidate", encoding="utf-8")
    prepare_started = asyncio.Event()
    host = SessionTransitionHost("first", dispose=lambda _session: None)
    coordinator = SessionOperationCoordinator(host)

    async def prepare_session(_candidate: object, _previous: object) -> None:
        prepare_started.set()
        await asyncio.Future()

    async def scenario() -> None:
        task = asyncio.create_task(
            coordinator.run(
                lambda _current: SessionOperationCandidate(
                    "second",
                    None,
                    rollback=staged_file.unlink,
                ),
                prepare_session=prepare_session,
            )
        )
        await prepare_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())

    assert host.current == "first"
    assert staged_file.exists() is False
