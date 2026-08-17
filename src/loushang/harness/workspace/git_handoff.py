"""Persistent Git workspaces and immutable patch handoff mechanics."""

from __future__ import annotations

import asyncio
import errno
import hashlib
import importlib
import json
import os
import stat
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Literal, TypedDict, Unpack, cast
from uuid import uuid4

from loushang.harness.journal import journal_file_lock

from .exec import ExecRequest, ExecResult, ExecService
from .git import GitPaths, find_git_paths, list_git_worktree_paths

GitWorkspaceStatus = Literal[
    "allocating",
    "active",
    "capturing",
    "retained",
    "applying",
    "applied",
    "discarding",
    "discarded",
    "missing",
    "needs_inspection",
]

_UuidFactory = Callable[[], str]
_WORKSPACE_REF_PREFIX = "git-workspace:"
_ARTIFACT_REF_PREFIX = "git-artifact:"


class GitWorkspaceError(RuntimeError):
    """Expected Git workspace operation failure."""


class GitWorkspaceConflict(GitWorkspaceError):
    """A persisted revision or target fingerprint changed."""


@dataclass(frozen=True, slots=True)
class GitWorkspaceRecord:
    workspace_id: str
    workspace_ref: str
    repository_id: str
    repository_path: str
    common_git_dir: str
    path: str
    base_oid: str
    owner_ref: str
    owner_pid: int
    status: GitWorkspaceStatus
    revision: int = 1
    runtime_owned: bool = True
    artifact_refs: tuple[str, ...] = ()
    last_error: str | None = None
    created_at: float = 0.0
    updated_at: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_refs", tuple(self.artifact_refs))


class _GitWorkspaceRecordChanges(TypedDict, total=False):
    status: GitWorkspaceStatus
    runtime_owned: bool
    artifact_refs: tuple[str, ...]
    last_error: str | None


@dataclass(frozen=True, slots=True)
class GitWorkspaceCapture:
    record: GitWorkspaceRecord
    artifact_refs: tuple[str, ...] = ()
    changed: bool = False
    inspection_required: bool = False


@dataclass(frozen=True, slots=True)
class GitApplyPlan:
    workspace_ref: str
    artifact_ref: str
    repository_id: str
    record_revision: int
    patch_digest: str
    manifest_digest: str
    target_path: str
    target_head: str
    target_fingerprint: str
    touched_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GitApplyResult:
    workspace_ref: str
    artifact_ref: str
    applied: bool
    record: GitWorkspaceRecord


@dataclass(frozen=True, slots=True)
class GitDiscardResult:
    workspace_ref: str
    discarded: bool
    record: GitWorkspaceRecord


@dataclass(frozen=True, slots=True)
class _Artifact:
    artifact_ref: str
    descriptor: Mapping[str, object]
    patch_path: Path
    manifest_path: Path
    patch_bytes: bytes
    manifest_bytes: bytes

    @property
    def touched_paths(self) -> tuple[str, ...]:
        return tuple(
            part.decode("utf-8", errors="surrogateescape")
            for part in self.manifest_bytes.split(b"\0")
            if part
        )


class GitWorkspaceManager:
    """Git-only mechanics with persistent records and no Product dependency."""

    def __init__(
        self,
        *,
        cwd: str | Path,
        state_root: str | Path,
        managed_root: str | Path,
        exec_service: ExecService | None = None,
        uuid_factory: _UuidFactory | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        resolved_cwd = Path(cwd).expanduser().resolve()
        if not resolved_cwd.is_dir():
            raise NotADirectoryError(20, "Not a directory", str(resolved_cwd))
        git_paths = find_git_paths(resolved_cwd)
        if git_paths is None:
            raise GitWorkspaceError(f"Git workspace requires a repository: {cwd}")
        if timeout_seconds <= 0:
            raise ValueError("Git workspace timeout_seconds must be positive")
        self._cwd = resolved_cwd
        self._git_paths = git_paths
        self._state_root = Path(state_root).expanduser().resolve()
        self._managed_root = Path(managed_root).expanduser().resolve()
        self._repository_id = _repository_id(git_paths)
        self._repository_state = (
            self._state_root / "workspaces" / self._repository_id
        )
        self._repository_managed_root = self._managed_root / self._repository_id
        self._exec = exec_service or ExecService()
        self._uuid_factory = uuid_factory or (lambda: uuid4().hex[:12])
        self._timeout_seconds = timeout_seconds
        self._operation_lock = asyncio.Lock()
        self._validate_roots()

    @property
    def repository_id(self) -> str:
        return self._repository_id

    @property
    def state_root(self) -> Path:
        return self._state_root

    @property
    def managed_root(self) -> Path:
        return self._managed_root

    async def acquire(
        self,
        *,
        owner_ref: str,
        name_hint: str = "agent",
    ) -> GitWorkspaceRecord:
        if not owner_ref.strip():
            raise ValueError("owner_ref must be non-empty")
        async with self._operation_lock:
            base_oid = (await self._required(self._cwd, "rev-parse", "HEAD^{commit}")).stdout
            base_oid = base_oid.strip()
            workspace_id = _workspace_id(name_hint, self._uuid_factory())
            workspace_ref = _workspace_ref(self._repository_id, workspace_id)
            path = (self._repository_managed_root / workspace_id).resolve()
            self._require_managed_path(path)
            now = time.time()
            record = GitWorkspaceRecord(
                workspace_id=workspace_id,
                workspace_ref=workspace_ref,
                repository_id=self._repository_id,
                repository_path=str(self._git_paths.repo_dir),
                common_git_dir=str(self._git_paths.common_git_dir),
                path=str(path),
                base_oid=base_oid,
                owner_ref=owner_ref,
                owner_pid=os.getpid(),
                status="allocating",
                created_at=now,
                updated_at=now,
            )
            self._create_record(record)
            self._repository_managed_root.mkdir(parents=True, exist_ok=True)
            try:
                await self._required(
                    self._git_paths.repo_dir,
                    "worktree",
                    "add",
                    "--detach",
                    str(path),
                    base_oid,
                )
            except BaseException as error:
                record = self._update_record(
                    record,
                    status="needs_inspection",
                    runtime_owned=False,
                    last_error=_exception_text(error),
                )
                if isinstance(error, (GitWorkspaceError, OSError)):
                    await self._safe_failed_allocation_cleanup(record)
                raise
            return self._update_record(record, status="active", last_error=None)

    async def capture(self, workspace_ref: str) -> GitWorkspaceCapture:
        async with self._operation_lock:
            return await self._capture(workspace_ref)

    async def release(self, workspace_ref: str) -> GitWorkspaceRecord:
        """Release runtime ownership, retaining every changed workspace."""

        async with self._operation_lock:
            record = self.get(workspace_ref)
            if record.status == "discarded":
                raise GitWorkspaceError(f"workspace is already discarded: {workspace_ref}")
            if record.status in {"allocating", "capturing", "applying", "discarding"}:
                raise GitWorkspaceError(
                    f"workspace cannot be released while {record.status}: {workspace_ref}"
                )
            if record.status in {"needs_inspection", "missing", "retained", "applied"}:
                return self._update_record(record, runtime_owned=False)

            status = await self._required(
                Path(record.path),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            )
            if status.stdout:
                captured = await self._capture(workspace_ref)
                return self._update_record(captured.record, runtime_owned=False)

            record = self._update_record(
                record,
                status="discarding",
                runtime_owned=False,
            )
            try:
                await self._remove_registered_worktree(record)
            except BaseException as error:
                self._update_record(
                    record,
                    status="needs_inspection",
                    runtime_owned=False,
                    last_error=_exception_text(error),
                )
                raise
            return self._update_record(record, status="discarded", last_error=None)

    def get(self, workspace_ref: str) -> GitWorkspaceRecord:
        workspace_id = _workspace_id_from_ref(workspace_ref, self._repository_id)
        path = self._record_path(workspace_id)
        if not path.is_file():
            raise GitWorkspaceError(f"workspace not found: {workspace_ref}")
        record = _record_from_json(path.read_text(encoding="utf-8"))
        self._validate_record(record, expected_ref=workspace_ref)
        return record

    def list_records(self) -> tuple[GitWorkspaceRecord, ...]:
        records_dir = self._repository_state / "records"
        if not records_dir.is_dir():
            return ()
        records = tuple(
            _record_from_json(path.read_text(encoding="utf-8"))
            for path in records_dir.glob("*.json")
        )
        for record in records:
            self._validate_record(record, expected_ref=record.workspace_ref)
        return tuple(
            sorted(records, key=lambda item: (item.created_at, item.workspace_id))
        )

    async def reconcile(self) -> tuple[GitWorkspaceRecord, ...]:
        """Repair crash-visible states without deleting uncertain paths."""

        async with self._operation_lock:
            registered = set(await self._registered_worktree_paths())
            reconciled: list[GitWorkspaceRecord] = []
            for record in self.list_records():
                path = Path(record.path).resolve()
                owner_alive = _pid_is_alive(record.owner_pid)
                if record.status == "allocating":
                    if owner_alive:
                        reconciled.append(record)
                    elif path in registered:
                        reconciled.append(
                            self._update_record(
                                record,
                                status="active",
                                runtime_owned=False,
                            )
                        )
                    elif not path.exists():
                        reconciled.append(
                            self._update_record(
                                record,
                                status="discarded",
                                runtime_owned=False,
                            )
                        )
                    else:
                        reconciled.append(
                            self._update_record(
                                record,
                                status="needs_inspection",
                                runtime_owned=False,
                                last_error="incomplete allocation left an unregistered path",
                            )
                        )
                    continue
                if record.status in {"capturing", "applying", "discarding"}:
                    if owner_alive:
                        reconciled.append(record)
                    else:
                        reconciled.append(
                            self._update_record(
                                record,
                                status="needs_inspection",
                                runtime_owned=False,
                                last_error=f"process exited while {record.status}",
                            )
                        )
                    continue
                if record.status in {"active", "retained", "applied"}:
                    if path not in registered or not path.is_dir():
                        reconciled.append(
                            self._update_record(
                                record,
                                status="missing",
                                runtime_owned=False,
                                last_error="registered workspace path is missing",
                            )
                        )
                    elif record.runtime_owned and not owner_alive:
                        reconciled.append(
                            self._update_record(record, runtime_owned=False)
                        )
                    else:
                        reconciled.append(record)
                    continue
                reconciled.append(record)
            return tuple(reconciled)

    async def plan_apply(
        self,
        artifact_ref: str,
        *,
        target: str | Path,
    ) -> GitApplyPlan:
        artifact = self._load_artifact(artifact_ref)
        workspace_ref = cast(str, artifact.descriptor["workspace_ref"])
        record = self.get(workspace_ref)
        if record.status != "retained" or record.runtime_owned:
            raise GitWorkspaceError(
                "apply requires a retained workspace with released runtime ownership"
            )
        requested_target = Path(target).expanduser().resolve()
        target_git = find_git_paths(requested_target)
        if target_git is None or _repository_id(target_git) != self._repository_id:
            raise GitWorkspaceError("apply target belongs to a different repository")
        target_path = target_git.repo_dir.resolve()
        touched_paths = artifact.touched_paths
        _validate_touched_paths(touched_paths)
        patch_paths = _parse_numstat_paths(
            (
                await self._required(
                    target_path,
                    "apply",
                    "--numstat",
                    "-z",
                    str(artifact.patch_path),
                )
            ).stdout
        )
        if set(patch_paths) != set(touched_paths):
            raise GitWorkspaceError("artifact patch and manifest path sets differ")
        touched_status = await self._required(
            target_path,
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--",
            *touched_paths,
            env=(("GIT_LITERAL_PATHSPECS", "1"),),
        )
        if touched_status.stdout:
            raise GitWorkspaceConflict(
                "apply target has staged, unstaged, or untracked changes "
                "on an artifact path"
            )
        await self._required(
            target_path,
            "apply",
            "--check",
            str(artifact.patch_path),
        )
        head = (
            await self._required(target_path, "rev-parse", "HEAD^{commit}")
        ).stdout.strip()
        fingerprint = await self._target_fingerprint(target_path, head=head)
        return GitApplyPlan(
            workspace_ref=workspace_ref,
            artifact_ref=artifact_ref,
            repository_id=self._repository_id,
            record_revision=record.revision,
            patch_digest=cast(str, artifact.descriptor["patch_digest"]),
            manifest_digest=cast(str, artifact.descriptor["manifest_digest"]),
            target_path=str(target_path),
            target_head=head,
            target_fingerprint=fingerprint,
            touched_paths=touched_paths,
        )

    async def plan_apply_workspace(
        self,
        workspace_ref: str,
        *,
        target: str | Path,
    ) -> GitApplyPlan:
        record = self.get(workspace_ref)
        if not record.artifact_refs:
            raise GitWorkspaceError(f"workspace has no artifact: {workspace_ref}")
        return await self.plan_apply(record.artifact_refs[-1], target=target)

    async def apply(self, plan: GitApplyPlan) -> GitApplyResult:
        lock_path = self._repository_state / "locks" / "apply-discard.lock"
        async with self._operation_lock, _AsyncFileLock(
            lock_path,
            timeout_seconds=self._timeout_seconds,
        ):
            current_plan = await self.plan_apply(
                plan.artifact_ref,
                target=plan.target_path,
            )
            if current_plan != plan:
                raise GitWorkspaceConflict("apply plan is stale")
            record = self.get(plan.workspace_ref)
            record = self._update_record(record, status="applying")
            artifact = self._load_artifact(plan.artifact_ref)
            try:
                await self._required(
                    Path(plan.target_path),
                    "apply",
                    "--check",
                    str(artifact.patch_path),
                )
                await self._required(
                    Path(plan.target_path),
                    "apply",
                    str(artifact.patch_path),
                )
            except BaseException as error:
                self._update_record(
                    record,
                    status="needs_inspection",
                    last_error=_exception_text(error),
                )
                raise
            record = self._update_record(record, status="applied", last_error=None)
            return GitApplyResult(
                workspace_ref=record.workspace_ref,
                artifact_ref=plan.artifact_ref,
                applied=True,
                record=record,
            )

    async def discard(self, workspace_ref: str) -> GitDiscardResult:
        lock_path = self._repository_state / "locks" / "apply-discard.lock"
        async with self._operation_lock, _AsyncFileLock(
            lock_path,
            timeout_seconds=self._timeout_seconds,
        ):
            record = self.get(workspace_ref)
            if record.runtime_owned:
                raise GitWorkspaceError("cannot discard a runtime-owned workspace")
            if record.status == "discarded":
                return GitDiscardResult(workspace_ref, True, record)
            if record.status not in {
                "active",
                "retained",
                "applied",
                "needs_inspection",
                "missing",
            }:
                raise GitWorkspaceError(
                    f"workspace cannot be discarded while {record.status}"
                )
            path = Path(record.path).resolve()
            self._require_managed_path(path)
            registered = set(await self._registered_worktree_paths())
            if path.exists() and path not in registered:
                record = self._update_record(
                    record,
                    status="needs_inspection",
                    last_error="refusing to remove an unregistered workspace path",
                )
                raise GitWorkspaceError(record.last_error or "unsafe workspace path")
            record = self._update_record(record, status="discarding")
            try:
                if path in registered:
                    await self._remove_registered_worktree(record)
                record = self._update_record(
                    record,
                    status="discarded",
                    runtime_owned=False,
                    last_error=None,
                )
            except BaseException as error:
                self._update_record(
                    record,
                    status="needs_inspection",
                    runtime_owned=False,
                    last_error=_exception_text(error),
                )
                raise
            return GitDiscardResult(workspace_ref, True, record)

    def artifact_diff(self, workspace_ref: str) -> str:
        record = self.get(workspace_ref)
        if not record.artifact_refs:
            raise GitWorkspaceError(f"workspace has no artifact: {workspace_ref}")
        return self._load_artifact(record.artifact_refs[-1]).patch_bytes.decode(
            "utf-8"
        )

    async def _capture(self, workspace_ref: str) -> GitWorkspaceCapture:
        record = self.get(workspace_ref)
        if record.status not in {"active", "retained"}:
            raise GitWorkspaceError(
                f"workspace cannot be captured while {record.status}: {workspace_ref}"
            )
        record = self._update_record(record, status="capturing", last_error=None)
        temp_index: Path | None = None
        try:
            status = await self._required(
                Path(record.path),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            )
            if not status.stdout:
                record = self._update_record(record, status="active")
                return GitWorkspaceCapture(record=record)

            temp_dir = self._repository_state / "tmp"
            temp_dir.mkdir(parents=True, exist_ok=True)
            descriptor, temp_index_name = tempfile.mkstemp(
                prefix="index-",
                dir=temp_dir,
            )
            os.close(descriptor)
            temp_index = Path(temp_index_name)
            temp_index.unlink()
            env = (
                ("GIT_INDEX_FILE", str(temp_index)),
                ("GIT_TERMINAL_PROMPT", "0"),
                ("GIT_CONFIG_NOSYSTEM", "1"),
            )
            await self._required(
                Path(record.path),
                "read-tree",
                record.base_oid,
                env=env,
            )
            await self._required(Path(record.path), "add", "-A", "--", ".", env=env)
            patch = (
                await self._required(
                    Path(record.path),
                    "diff",
                    "--cached",
                    "--binary",
                    "--full-index",
                    "--no-ext-diff",
                    "--no-renames",
                    record.base_oid,
                    env=env,
                )
            ).stdout.encode("utf-8", errors="surrogateescape")
            manifest = (
                await self._required(
                    Path(record.path),
                    "diff",
                    "--cached",
                    "--name-only",
                    "-z",
                    "--no-renames",
                    record.base_oid,
                    env=env,
                )
            ).stdout.encode("utf-8", errors="surrogateescape")
            if not patch:
                record = self._update_record(record, status="active")
                return GitWorkspaceCapture(record=record)
            artifact_ref = self._publish_artifact(record, patch, manifest)
            artifact_refs = (
                record.artifact_refs
                if artifact_ref in record.artifact_refs
                else (*record.artifact_refs, artifact_ref)
            )
            record = self._update_record(
                record,
                status="retained",
                artifact_refs=artifact_refs,
            )
            return GitWorkspaceCapture(
                record=record,
                artifact_refs=(artifact_ref,),
                changed=True,
            )
        except asyncio.CancelledError as error:
            self._update_record(
                record,
                status="needs_inspection",
                last_error=_exception_text(error),
            )
            raise
        except (GitWorkspaceError, OSError) as error:
            record = self._update_record(
                record,
                status="needs_inspection",
                last_error=_exception_text(error),
            )
            return GitWorkspaceCapture(
                record=record,
                changed=True,
                inspection_required=True,
            )
        finally:
            if temp_index is not None:
                temp_index.unlink(missing_ok=True)

    async def _target_fingerprint(self, target: Path, *, head: str) -> str:
        """Bind a plan to Git-visible target content, not status labels alone."""

        commands = (
            (
                "diff",
                "--cached",
                "--binary",
                "--full-index",
                "--no-ext-diff",
                "--no-renames",
                head,
            ),
            (
                "diff",
                "--binary",
                "--full-index",
                "--no-ext-diff",
                "--no-renames",
            ),
            ("status", "--porcelain=v1", "-z", "--untracked-files=all"),
            ("ls-files", "--others", "--exclude-standard", "-z"),
        )
        results = [await self._required(target, *command) for command in commands]
        digest = hashlib.sha256()
        digest.update(head.encode("ascii"))
        for result in results[:3]:
            digest.update(b"\0")
            digest.update(_output_bytes(result.stdout))

        untracked_paths = tuple(
            part.decode("utf-8", errors="surrogateescape")
            for part in _output_bytes(results[3].stdout).split(b"\0")
            if part
        )
        if untracked_paths:
            _validate_touched_paths(untracked_paths, label="untracked target paths")
        for relative_path in untracked_paths:
            _update_path_digest(digest, target, relative_path)
        return digest.hexdigest()

    def _publish_artifact(
        self,
        record: GitWorkspaceRecord,
        patch: bytes,
        manifest: bytes,
    ) -> str:
        patch_digest = hashlib.sha256(patch).hexdigest()
        manifest_digest = hashlib.sha256(manifest).hexdigest()
        descriptor = {
            "version": 1,
            "workspace_ref": record.workspace_ref,
            "repository_id": record.repository_id,
            "base_oid": record.base_oid,
            "patch_digest": patch_digest,
            "manifest_digest": manifest_digest,
        }
        descriptor_bytes = _canonical_json_bytes(descriptor)
        artifact_digest = hashlib.sha256(descriptor_bytes).hexdigest()
        artifact_ref = _artifact_ref(record.repository_id, artifact_digest)
        _publish_immutable(
            self._repository_state / "artifacts" / f"{patch_digest}.patch",
            patch,
        )
        _publish_immutable(
            self._repository_state / "manifests" / f"{manifest_digest}.paths",
            manifest,
        )
        _publish_immutable(
            self._repository_state / "descriptors" / f"{artifact_digest}.json",
            descriptor_bytes,
        )
        return artifact_ref

    def _load_artifact(self, artifact_ref: str) -> _Artifact:
        repository_id, artifact_digest = _artifact_parts(artifact_ref)
        if repository_id != self._repository_id:
            raise GitWorkspaceError("artifact belongs to a different repository")
        descriptor_path = (
            self._repository_state / "descriptors" / f"{artifact_digest}.json"
        )
        try:
            descriptor_bytes = descriptor_path.read_bytes()
        except OSError as error:
            raise GitWorkspaceError(f"artifact descriptor is unavailable: {error}") from error
        if hashlib.sha256(descriptor_bytes).hexdigest() != artifact_digest:
            raise GitWorkspaceError("artifact descriptor digest mismatch")
        try:
            descriptor = cast(dict[str, object], json.loads(descriptor_bytes))
            patch_digest = cast(str, descriptor["patch_digest"])
            manifest_digest = cast(str, descriptor["manifest_digest"])
            workspace_ref = cast(str, descriptor["workspace_ref"])
            base_oid = cast(str, descriptor["base_oid"])
            descriptor_repository = cast(str, descriptor["repository_id"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise GitWorkspaceError("artifact descriptor is invalid") from error
        if descriptor_repository != self._repository_id:
            raise GitWorkspaceError("artifact descriptor repository mismatch")
        record = self.get(workspace_ref)
        if base_oid != record.base_oid:
            raise GitWorkspaceError("artifact descriptor base mismatch")
        patch_path = self._repository_state / "artifacts" / f"{patch_digest}.patch"
        manifest_path = (
            self._repository_state / "manifests" / f"{manifest_digest}.paths"
        )
        try:
            patch_bytes = patch_path.read_bytes()
            manifest_bytes = manifest_path.read_bytes()
        except OSError as error:
            raise GitWorkspaceError(f"artifact content is unavailable: {error}") from error
        if hashlib.sha256(patch_bytes).hexdigest() != patch_digest:
            raise GitWorkspaceError("artifact patch digest mismatch")
        if hashlib.sha256(manifest_bytes).hexdigest() != manifest_digest:
            raise GitWorkspaceError("artifact manifest digest mismatch")
        return _Artifact(
            artifact_ref=artifact_ref,
            descriptor=descriptor,
            patch_path=patch_path,
            manifest_path=manifest_path,
            patch_bytes=patch_bytes,
            manifest_bytes=manifest_bytes,
        )

    async def _safe_failed_allocation_cleanup(
        self,
        record: GitWorkspaceRecord,
    ) -> None:
        path = Path(record.path)
        await self._git(
            self._git_paths.repo_dir,
            "worktree",
            "remove",
            "--force",
            str(path),
        )
        if path.is_dir():
            try:
                path.rmdir()
            except OSError:
                return
        registered = set(await self._registered_worktree_paths())
        if not path.exists() and path.resolve() not in registered:
            current = self.get(record.workspace_ref)
            self._update_record(current, status="discarded", last_error=None)

    async def _remove_registered_worktree(self, record: GitWorkspaceRecord) -> None:
        path = Path(record.path).resolve()
        self._require_managed_path(path)
        removed = await self._git(
            self._git_paths.repo_dir,
            "worktree",
            "remove",
            "--force",
            str(path),
        )
        if removed.exit_code != 0:
            raise GitWorkspaceError(
                "failed to remove managed worktree: "
                + _command_error_text(removed)
            )

    async def _registered_worktree_paths(self) -> tuple[Path, ...]:
        result = await self._required(
            self._git_paths.repo_dir,
            "worktree",
            "list",
            "--porcelain",
        )
        return tuple(
            Path(line.removeprefix("worktree ").strip()).resolve()
            for line in result.stdout.splitlines()
            if line.startswith("worktree ")
        )

    async def _required(
        self,
        cwd: Path,
        *args: str,
        env: tuple[tuple[str, str], ...] = (),
    ) -> ExecResult:
        result = await self._git(cwd, *args, env=env)
        if result.exit_code != 0 or result.timed_out or result.cancelled:
            raise GitWorkspaceError(
                f"git {' '.join(args[:2])} failed: {_command_error_text(result)}"
            )
        return result

    async def _git(
        self,
        cwd: Path,
        *args: str,
        env: tuple[tuple[str, str], ...] = (),
    ) -> ExecResult:
        return await self._exec.execute(
            ExecRequest(
                command=(
                    "git",
                    "--no-optional-locks",
                    "-c",
                    f"core.hooksPath={os.devnull}",
                    *args,
                ),
                cwd=str(cwd),
                env=env,
                timeout_seconds=self._timeout_seconds,
            )
        )

    def _validate_roots(self) -> None:
        worktrees = list_git_worktree_paths(self._cwd)
        for root in (self._state_root, self._managed_root):
            for worktree in worktrees:
                if _is_within(root, worktree):
                    raise GitWorkspaceError(
                        f"managed Git workspace root overlaps a registered worktree: {root}"
                    )

    def _require_managed_path(self, path: Path) -> None:
        try:
            relative = path.resolve().relative_to(self._repository_managed_root)
        except ValueError as error:
            raise GitWorkspaceError("workspace path escaped its managed root") from error
        if not relative.parts or len(relative.parts) != 1:
            raise GitWorkspaceError("workspace path must be one managed child")

    def _validate_record(
        self,
        record: GitWorkspaceRecord,
        *,
        expected_ref: str,
    ) -> None:
        if (
            record.workspace_ref != expected_ref
            or record.workspace_ref
            != _workspace_ref(self._repository_id, record.workspace_id)
            or record.repository_id != self._repository_id
            or Path(record.common_git_dir).resolve()
            != self._git_paths.common_git_dir.resolve()
        ):
            raise GitWorkspaceError("workspace record identity mismatch")
        self._require_managed_path(Path(record.path))

    def _create_record(self, record: GitWorkspaceRecord) -> None:
        with _file_lock(self._repository_state / "locks" / "catalog.lock"):
            path = self._record_path(record.workspace_id)
            if path.exists():
                raise GitWorkspaceConflict(
                    f"workspace record already exists: {record.workspace_ref}"
                )
            _atomic_write(path, _canonical_json_bytes(_record_to_json(record)))

    def _update_record(
        self,
        record: GitWorkspaceRecord,
        **changes: Unpack[_GitWorkspaceRecordChanges],
    ) -> GitWorkspaceRecord:
        with _file_lock(self._repository_state / "locks" / "catalog.lock"):
            path = self._record_path(record.workspace_id)
            current = _record_from_json(path.read_text(encoding="utf-8"))
            if current.revision != record.revision:
                raise GitWorkspaceConflict(
                    f"workspace revision changed: {record.workspace_ref}"
                )
            updated = replace(
                current,
                revision=current.revision + 1,
                updated_at=time.time(),
                **changes,
            )
            _atomic_write(path, _canonical_json_bytes(_record_to_json(updated)))
            return updated

    def _record_path(self, workspace_id: str) -> Path:
        return self._repository_state / "records" / f"{workspace_id}.json"


class _AsyncFileLock:
    def __init__(self, path: Path, *, timeout_seconds: float) -> None:
        self._path = path
        self._timeout_seconds = timeout_seconds
        self._handle: BinaryIO | None = None
        self._lock_module: Any | None = None

    async def __aenter__(self) -> _AsyncFileLock:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self._path.open("a+b")
        try:
            _prepare_lock_byte(self._handle)
            self._lock_module = importlib.import_module(
                "msvcrt" if _is_windows() else "fcntl"
            )
            deadline = (
                asyncio.get_running_loop().time() + self._timeout_seconds
            )
            while True:
                try:
                    if _is_windows():
                        self._handle.seek(0)
                        self._lock_module.locking(
                            self._handle.fileno(),
                            self._lock_module.LK_NBLCK,
                            1,
                        )
                    else:
                        self._lock_module.flock(
                            self._handle.fileno(),
                            self._lock_module.LOCK_EX
                            | self._lock_module.LOCK_NB,
                        )
                    break
                except OSError as error:
                    if error.errno not in {errno.EACCES, errno.EAGAIN}:
                        raise
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError(
                            f"timed out waiting for workspace lock: {self._path}"
                        ) from error
                    await asyncio.sleep(0.05)
        except BaseException:
            self._close_handle()
            raise
        return self

    async def __aexit__(self, *_args: object) -> None:
        assert self._handle is not None
        assert self._lock_module is not None
        try:
            if _is_windows():
                self._handle.seek(0)
                self._lock_module.locking(
                    self._handle.fileno(),
                    self._lock_module.LK_UNLCK,
                    1,
                )
            else:
                self._lock_module.flock(
                    self._handle.fileno(),
                    self._lock_module.LOCK_UN,
                )
        finally:
            self._close_handle()

    def _close_handle(self) -> None:
        if self._handle is not None:
            self._handle.close()
            self._handle = None
        self._lock_module = None


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    with journal_file_lock(path, "exclusive", lock_suffix=""):
        yield


def _prepare_lock_byte(handle: Any) -> None:
    handle.seek(0, os.SEEK_END)
    if handle.tell() == 0:
        handle.write(b"\0")
        handle.flush()
    handle.seek(0)


def _record_to_json(record: GitWorkspaceRecord) -> dict[str, object]:
    return {
        "version": 1,
        "workspace_id": record.workspace_id,
        "workspace_ref": record.workspace_ref,
        "repository_id": record.repository_id,
        "repository_path": record.repository_path,
        "common_git_dir": record.common_git_dir,
        "path": record.path,
        "base_oid": record.base_oid,
        "owner_ref": record.owner_ref,
        "owner_pid": record.owner_pid,
        "status": record.status,
        "revision": record.revision,
        "runtime_owned": record.runtime_owned,
        "artifact_refs": list(record.artifact_refs),
        "last_error": record.last_error,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
    }


def _record_from_json(content: str) -> GitWorkspaceRecord:
    try:
        value = json.loads(content)
        if not isinstance(value, dict) or value.get("version") != 1:
            raise ValueError("unsupported record version")
        return GitWorkspaceRecord(
            workspace_id=str(value["workspace_id"]),
            workspace_ref=str(value["workspace_ref"]),
            repository_id=str(value["repository_id"]),
            repository_path=str(value["repository_path"]),
            common_git_dir=str(value["common_git_dir"]),
            path=str(value["path"]),
            base_oid=str(value["base_oid"]),
            owner_ref=str(value["owner_ref"]),
            owner_pid=int(value["owner_pid"]),
            status=cast(GitWorkspaceStatus, value["status"]),
            revision=int(value["revision"]),
            runtime_owned=bool(value["runtime_owned"]),
            artifact_refs=tuple(str(item) for item in value["artifact_refs"]),
            last_error=(
                str(value["last_error"]) if value.get("last_error") is not None else None
            ),
            created_at=float(value["created_at"]),
            updated_at=float(value["updated_at"]),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise GitWorkspaceError("workspace record is invalid") from error


def _repository_id(git_paths: GitPaths) -> str:
    identity = str(git_paths.common_git_dir.resolve()).encode("utf-8")
    return hashlib.sha256(identity).hexdigest()[:24]


def _workspace_id(name_hint: str, nonce: str) -> str:
    normalized_name = "".join(
        character if character.isalnum() else "-"
        for character in name_hint.lower()
    ).strip("-")
    normalized_nonce = "".join(
        character for character in nonce.lower() if character.isalnum()
    )
    if not normalized_nonce:
        raise ValueError("workspace nonce must contain letters or digits")
    return f"{normalized_name or 'agent'}-{normalized_nonce}"[:100]


def _workspace_ref(repository_id: str, workspace_id: str) -> str:
    return f"{_WORKSPACE_REF_PREFIX}{repository_id}:{workspace_id}"


def _workspace_id_from_ref(workspace_ref: str, repository_id: str) -> str:
    prefix = f"{_WORKSPACE_REF_PREFIX}{repository_id}:"
    if not workspace_ref.startswith(prefix):
        raise GitWorkspaceError("workspace reference belongs to another repository")
    workspace_id = workspace_ref.removeprefix(prefix)
    if not workspace_id or "/" in workspace_id or "\\" in workspace_id:
        raise GitWorkspaceError("workspace reference is invalid")
    return workspace_id


def _artifact_ref(repository_id: str, digest: str) -> str:
    return f"{_ARTIFACT_REF_PREFIX}{repository_id}:{digest}"


def _artifact_parts(artifact_ref: str) -> tuple[str, str]:
    if not artifact_ref.startswith(_ARTIFACT_REF_PREFIX):
        raise GitWorkspaceError("artifact reference is invalid")
    parts = artifact_ref.removeprefix(_ARTIFACT_REF_PREFIX).split(":", 1)
    if len(parts) != 2 or not all(parts):
        raise GitWorkspaceError("artifact reference is invalid")
    return parts[0], parts[1]


def _validate_touched_paths(
    paths: tuple[str, ...],
    *,
    label: str = "artifact manifest paths",
) -> None:
    if not paths or len(paths) != len(set(paths)):
        raise GitWorkspaceError(f"{label} are empty or duplicated")
    for value in paths:
        path = PurePosixPath(value)
        if (
            not value
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in value.split("/"))
        ):
            raise GitWorkspaceError(f"{label} escape target: {value!r}")


def _parse_numstat_paths(output: str) -> tuple[str, ...]:
    paths: list[str] = []
    for row in output.split("\0"):
        if not row:
            continue
        fields = row.split("\t", 2)
        if len(fields) != 3 or not fields[2]:
            raise GitWorkspaceError("artifact patch path summary is invalid")
        paths.append(fields[2])
    return tuple(paths)


def _canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _sync_parent_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _publish_immutable(path: Path, content: bytes) -> None:
    if path.exists():
        if path.read_bytes() != content:
            raise GitWorkspaceError(f"immutable artifact collision: {path.name}")
        return
    _atomic_write(path, content)


def _sync_parent_directory(path: Path) -> None:
    if _is_windows():
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory = os.open(path, flags)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _update_path_digest(
    digest: Any,
    root: Path,
    relative_path: str,
) -> None:
    path = root / relative_path
    metadata = path.lstat()
    digest.update(b"\0path\0")
    digest.update(relative_path.encode("utf-8", errors="surrogateescape"))
    digest.update(b"\0mode\0")
    digest.update(str(stat.S_IFMT(metadata.st_mode) | stat.S_IMODE(metadata.st_mode)).encode())
    if stat.S_ISLNK(metadata.st_mode):
        digest.update(b"\0symlink\0")
        digest.update(
            os.readlink(path).encode("utf-8", errors="surrogateescape")
        )
        return
    if stat.S_ISREG(metadata.st_mode):
        digest.update(b"\0file\0")
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
        return
    digest.update(b"\0special\0")


def _output_bytes(value: str) -> bytes:
    return value.encode("utf-8", errors="surrogateescape")


def _exception_text(error: BaseException) -> str:
    return str(error) or type(error).__name__


def _is_windows() -> bool:
    return os.name == "nt"


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _command_error_text(result: ExecResult) -> str:
    if result.timed_out:
        return "timed out"
    if result.cancelled:
        return "cancelled"
    return result.stderr.strip() or result.stdout.strip() or "Git command failed"


__all__ = [
    "GitApplyPlan",
    "GitApplyResult",
    "GitDiscardResult",
    "GitWorkspaceCapture",
    "GitWorkspaceConflict",
    "GitWorkspaceError",
    "GitWorkspaceManager",
    "GitWorkspaceRecord",
    "GitWorkspaceStatus",
]
