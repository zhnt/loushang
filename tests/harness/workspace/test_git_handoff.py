from __future__ import annotations

import asyncio
import errno
import json
import os
import sys
from pathlib import Path

import pytest

from loushang.harness.workspace import (
    GitWorkspaceConflict,
    GitWorkspaceError,
    GitWorkspaceManager,
    git_handoff,
)
from loushang.harness.workspace.exec import ExecRequest, ExecResult, ExecService


class _BlockingBackend:
    def __init__(self) -> None:
        self._delegate = ExecService()
        self.enabled = False
        self.skip = 0
        self.started = asyncio.Event()

    async def __call__(self, request: ExecRequest, **_kwargs: object) -> ExecResult:
        if self.enabled:
            if self.skip:
                self.skip -= 1
                return await self._delegate.execute(request)
            self.started.set()
            await asyncio.Event().wait()
        return await self._delegate.execute(request)


async def _git(service: ExecService, cwd: Path, *args: str) -> ExecResult:
    result = await service.execute(
        ExecRequest(command=("git", *args), cwd=str(cwd))
    )
    assert result.exit_code == 0, result.stderr
    return result


async def _repo(tmp_path: Path) -> tuple[Path, ExecService]:
    repo = tmp_path / "repo"
    repo.mkdir()
    service = ExecService()
    await _git(service, repo, "init")
    await _git(service, repo, "config", "user.email", "handoff@example.invalid")
    await _git(service, repo, "config", "user.name", "Git Handoff")
    (repo / ".gitignore").write_text("ignored.log\n", encoding="utf-8")
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    (repo / "delete.txt").write_text("delete me\n", encoding="utf-8")
    (repo / "mode.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (repo / "other.txt").write_text("other\n", encoding="utf-8")
    await _git(service, repo, "add", ".")
    await _git(service, repo, "commit", "-m", "base")
    return repo, service


def _manager(
    tmp_path: Path,
    repo: Path,
    service: ExecService,
    *,
    nonce: str,
) -> GitWorkspaceManager:
    return GitWorkspaceManager(
        cwd=repo,
        state_root=tmp_path / "state",
        managed_root=tmp_path / "checkouts",
        exec_service=service,
        uuid_factory=lambda: nonce,
    )


async def _retained_workspace(
    tmp_path: Path,
    *,
    nonce: str = "retained",
) -> tuple[Path, ExecService, GitWorkspaceManager, str]:
    repo, service = await _repo(tmp_path)
    manager = _manager(tmp_path, repo, service, nonce=nonce)
    record = await manager.acquire(owner_ref="/root/worker#1", name_hint="worker")
    worktree = Path(record.path)
    (worktree / "tracked.txt").write_text("changed\n", encoding="utf-8")
    capture = await manager.capture(record.workspace_ref)
    assert capture.artifact_refs
    await manager.release(record.workspace_ref)
    return repo, service, manager, record.workspace_ref


def test_capture_and_apply_preserve_complete_file_tree_semantics(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repo, service = await _repo(tmp_path)
        manager = _manager(tmp_path, repo, service, nonce="complete")
        record = await manager.acquire(owner_ref="/root/worker#1", name_hint="worker")
        worktree = Path(record.path)

        (worktree / "tracked.txt").write_text("changed\n", encoding="utf-8")
        (worktree / "delete.txt").unlink()
        (worktree / "new.txt").write_text("new\n", encoding="utf-8")
        (worktree / "binary.dat").write_bytes(b"\x00\x01payload\xff")
        (worktree / "ignored.log").write_text("ignore me\n", encoding="utf-8")
        os.chmod(worktree / "mode.sh", 0o755)
        (worktree / "link.txt").symlink_to("tracked.txt")

        capture = await manager.capture(record.workspace_ref)
        patch = manager.artifact_diff(record.workspace_ref)
        assert capture.changed is True
        assert "GIT binary patch" in patch
        assert "ignored.log" not in patch
        assert "old mode 100644" in patch
        assert "new mode 100755" in patch

        released = await manager.release(record.workspace_ref)
        assert released.status == "retained"
        plan = await manager.plan_apply_workspace(record.workspace_ref, target=repo)
        assert set(plan.touched_paths) == {
            "binary.dat",
            "delete.txt",
            "link.txt",
            "mode.sh",
            "new.txt",
            "tracked.txt",
        }
        await manager.apply(plan)

        assert (repo / "tracked.txt").read_text(encoding="utf-8") == "changed\n"
        assert not (repo / "delete.txt").exists()
        assert (repo / "new.txt").read_text(encoding="utf-8") == "new\n"
        assert (repo / "binary.dat").read_bytes() == b"\x00\x01payload\xff"
        assert not (repo / "ignored.log").exists()
        assert os.stat(repo / "mode.sh").st_mode & 0o111
        assert (repo / "link.txt").is_symlink()
        assert os.readlink(repo / "link.txt") == "tracked.txt"

    asyncio.run(scenario())


@pytest.mark.skipif(os.name == "nt", reason="raw-byte filenames are POSIX-only")
@pytest.mark.skipif(
    sys.platform == "darwin",
    reason="APFS rejects invalid UTF-8 byte-sequence filenames (Linux ext4 allows them)",
)
def test_capture_and_apply_preserve_non_utf8_git_filenames(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repo, service = await _repo(tmp_path)
        manager = _manager(tmp_path, repo, service, nonce="raw-name")
        record = await manager.acquire(owner_ref="/root/worker#1", name_hint="worker")
        raw_name = b"non-utf8-\xff.txt"
        source = os.path.join(os.fsencode(record.path), raw_name)
        descriptor = os.open(source, os.O_WRONLY | os.O_CREAT, 0o644)
        try:
            os.write(descriptor, b"raw filename\n")
        finally:
            os.close(descriptor)

        capture = await manager.capture(record.workspace_ref)
        await manager.release(record.workspace_ref)
        plan = await manager.plan_apply_workspace(record.workspace_ref, target=repo)
        await manager.apply(plan)

        assert capture.changed is True
        assert os.fsdecode(raw_name) in plan.touched_paths
        target = os.path.join(os.fsencode(repo), raw_name)
        with open(target, "rb") as handle:
            assert handle.read() == b"raw filename\n"

    asyncio.run(scenario())


def test_apply_revalidates_the_complete_target_fingerprint(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repo, _service, manager, workspace_ref = await _retained_workspace(tmp_path)
        (repo / "other.txt").write_text("first parent edit\n", encoding="utf-8")
        plan = await manager.plan_apply_workspace(workspace_ref, target=repo)
        (repo / "other.txt").write_text("second parent edit\n", encoding="utf-8")

        with pytest.raises(GitWorkspaceConflict, match="stale"):
            await manager.apply(plan)

        assert manager.get(workspace_ref).status == "retained"
        assert (repo / "tracked.txt").read_text(encoding="utf-8") == "base\n"

    asyncio.run(scenario())


def test_apply_normalizes_a_subdirectory_target_to_the_repository_root(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repo, _service, manager, workspace_ref = await _retained_workspace(tmp_path)
        subdirectory = repo / "nested"
        subdirectory.mkdir()

        plan = await manager.plan_apply_workspace(
            workspace_ref,
            target=subdirectory,
        )
        result = await manager.apply(plan)

        assert plan.target_path == str(repo)
        assert result.record.status == "applied"
        assert (repo / "tracked.txt").read_text(encoding="utf-8") == "changed\n"

    asyncio.run(scenario())


def test_manifest_tampering_and_catalog_path_escape_fail_closed(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repo, _service, manager, workspace_ref = await _retained_workspace(tmp_path)
        record = manager.get(workspace_ref)
        artifact_digest = record.artifact_refs[-1].rsplit(":", 1)[-1]
        repository_state = (
            tmp_path / "state" / "workspaces" / manager.repository_id
        )
        descriptor = json.loads(
            (
                repository_state / "descriptors" / f"{artifact_digest}.json"
            ).read_text(encoding="utf-8")
        )
        manifest_path = (
            repository_state
            / "manifests"
            / f"{descriptor['manifest_digest']}.paths"
        )
        manifest_path.write_bytes(b"other.txt\0")
        with pytest.raises(GitWorkspaceError, match="manifest digest mismatch"):
            await manager.plan_apply_workspace(workspace_ref, target=repo)

        record_path = (
            repository_state / "records" / f"{record.workspace_id}.json"
        )
        value = json.loads(record_path.read_text(encoding="utf-8"))
        value["path"] = str(tmp_path / "outside")
        record_path.write_text(json.dumps(value), encoding="utf-8")
        with pytest.raises(GitWorkspaceError, match="escaped"):
            manager.get(workspace_ref)

    asyncio.run(scenario())


def test_restart_reconciliation_marks_abandoned_operation_for_inspection(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repo, service, manager, workspace_ref = await _retained_workspace(tmp_path)
        record = manager.get(workspace_ref)
        record_path = (
            tmp_path
            / "state"
            / "workspaces"
            / manager.repository_id
            / "records"
            / f"{record.workspace_id}.json"
        )
        value = json.loads(record_path.read_text(encoding="utf-8"))
        value["status"] = "capturing"
        value["runtime_owned"] = True
        value["owner_pid"] = 999_999_999
        record_path.write_text(json.dumps(value), encoding="utf-8")

        restarted = _manager(tmp_path, repo, service, nonce="unused")
        reconciled = await restarted.reconcile()
        recovered = next(item for item in reconciled if item.workspace_ref == workspace_ref)

        assert recovered.status == "needs_inspection"
        assert recovered.runtime_owned is False
        assert "process exited while capturing" == recovered.last_error

    asyncio.run(scenario())


def test_apply_and_discard_are_serialized_without_losing_the_artifact(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repo, _service, manager, workspace_ref = await _retained_workspace(tmp_path)
        plan = await manager.plan_apply_workspace(workspace_ref, target=repo)

        apply_task = asyncio.create_task(manager.apply(plan))
        await asyncio.sleep(0)
        discard_task = asyncio.create_task(manager.discard(workspace_ref))
        applied, discarded = await asyncio.gather(apply_task, discard_task)

        assert applied.applied is True
        assert discarded.discarded is True
        assert discarded.record.status == "discarded"
        assert manager.artifact_diff(workspace_ref)
        assert (repo / "tracked.txt").read_text(encoding="utf-8") == "changed\n"

    asyncio.run(scenario())


def test_capture_cancellation_moves_the_workspace_out_of_transient_state(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repo, _setup_service = await _repo(tmp_path)
        backend = _BlockingBackend()
        manager = _manager(
            tmp_path,
            repo,
            ExecService(backend=backend),
            nonce="cancel-capture",
        )
        record = await manager.acquire(owner_ref="/root/worker#1", name_hint="worker")
        (Path(record.path) / "tracked.txt").write_text(
            "changed\n",
            encoding="utf-8",
        )
        backend.enabled = True
        task = asyncio.create_task(manager.capture(record.workspace_ref))
        await backend.started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        recovered = manager.get(record.workspace_ref)
        assert recovered.status == "needs_inspection"
        released = await manager.release(record.workspace_ref)
        assert released.runtime_owned is False

    asyncio.run(scenario())


def test_apply_cancellation_marks_the_handoff_for_inspection(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repo, _setup_service = await _repo(tmp_path)
        backend = _BlockingBackend()
        manager = _manager(
            tmp_path,
            repo,
            ExecService(backend=backend),
            nonce="cancel-apply",
        )
        record = await manager.acquire(owner_ref="/root/worker#1", name_hint="worker")
        (Path(record.path) / "tracked.txt").write_text("changed\n", encoding="utf-8")
        await manager.capture(record.workspace_ref)
        await manager.release(record.workspace_ref)
        plan = await manager.plan_apply_workspace(record.workspace_ref, target=repo)
        backend.skip = 8
        backend.enabled = True
        task = asyncio.create_task(manager.apply(plan))
        await backend.started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        inspected = manager.get(record.workspace_ref)
        assert inspected.status == "needs_inspection"
        assert inspected.runtime_owned is False
        assert (repo / "tracked.txt").read_text(encoding="utf-8") == "base\n"

    asyncio.run(scenario())


def test_discard_cancellation_marks_the_workspace_for_inspection(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        repo, _setup_service = await _repo(tmp_path)
        backend = _BlockingBackend()
        manager = _manager(
            tmp_path,
            repo,
            ExecService(backend=backend),
            nonce="cancel-discard",
        )
        record = await manager.acquire(owner_ref="/root/worker#1", name_hint="worker")
        (Path(record.path) / "tracked.txt").write_text("changed\n", encoding="utf-8")
        await manager.capture(record.workspace_ref)
        await manager.release(record.workspace_ref)
        backend.skip = 1
        backend.enabled = True
        task = asyncio.create_task(manager.discard(record.workspace_ref))
        await backend.started.wait()
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        inspected = manager.get(record.workspace_ref)
        assert inspected.status == "needs_inspection"
        assert inspected.runtime_owned is False
        assert Path(inspected.path).is_dir()

    asyncio.run(scenario())


def test_async_lock_does_not_retry_a_permanent_os_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _BrokenLockModule:
        LOCK_EX = 1
        LOCK_NB = 2
        LOCK_UN = 4

        @staticmethod
        def flock(_descriptor: int, _operation: int) -> None:
            raise OSError(errno.EPERM, "locking is not permitted")

    async def scenario() -> None:
        monkeypatch.setattr(
            git_handoff.importlib,
            "import_module",
            lambda _name: _BrokenLockModule(),
        )
        lock = git_handoff._AsyncFileLock(
            tmp_path / "lock",
            timeout_seconds=1,
        )

        with pytest.raises(OSError, match="not permitted"):
            await lock.__aenter__()

        assert lock._handle is None

    asyncio.run(scenario())


def test_async_lock_closes_its_handle_when_waiting_is_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ContendedLockModule:
        LOCK_EX = 1
        LOCK_NB = 2
        LOCK_UN = 4

        @staticmethod
        def flock(_descriptor: int, _operation: int) -> None:
            raise OSError(errno.EAGAIN, "lock is held")

    async def scenario() -> None:
        monkeypatch.setattr(
            git_handoff.importlib,
            "import_module",
            lambda _name: _ContendedLockModule(),
        )
        lock = git_handoff._AsyncFileLock(
            tmp_path / "lock",
            timeout_seconds=10,
        )
        task = asyncio.create_task(lock.__aenter__())
        await asyncio.sleep(0)
        task.cancel()

        with pytest.raises(asyncio.CancelledError):
            await task

        assert lock._handle is None

    asyncio.run(scenario())


def test_atomic_write_skips_unsupported_directory_fsync_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "record.json"
    monkeypatch.setattr(git_handoff, "_is_windows", lambda: True)

    git_handoff._atomic_write(target, b"durable\n")

    assert target.read_bytes() == b"durable\n"
