from __future__ import annotations

import asyncio
import importlib.metadata
import inspect
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol, TypedDict, cast

from loushang.harness.policy import PolicyDecision
from loushang.harness.resources.packages.source import (
    PackageSourceIdentity,
    clone_source_and_ref,
    is_python_package_source,
    is_remote_package_source,
    python_package_requirement,
    remote_package_name,
)


class PackageSourcePolicy(Protocol):
    def evaluate_package_source(self, source: str | Path) -> PolicyDecision: ...


PackageMaterializationLifecycle = Literal[
    "remote_registered",
    "materialization_pending",
    "installed",
    "failed",
]
PackageProgressEventType = Literal["start", "progress", "complete", "error"]
PackageProgressAction = Literal["install", "update", "remove", "check", "resolve"]
PackageSourceType = Literal["git", "python", "local"]


class _PythonDistributionMetadata(TypedDict):
    name: str | None
    version: str | None
    distributions: tuple[str, ...]


@dataclass(frozen=True)
class PackageProgressEvent:
    type: PackageProgressEventType
    action: PackageProgressAction
    source: str
    message: str | None = None
    target_path: Path | None = None


@dataclass(frozen=True)
class PackageMaterializationRecord:
    source: str
    name: str
    lifecycle: PackageMaterializationLifecycle
    target_path: Path
    error_message: str | None = None
    security: Literal["allowed", "denied"] = "allowed"
    pinned: bool = False
    requested_ref: str | None = None
    resolved_commit: str | None = None
    installed_commit: str | None = None
    dirty: bool = False
    last_updated_at: str | None = None
    source_type: Literal["git", "python", "local"] = "git"
    requirement: str | None = None
    resolved_name: str | None = None
    resolved_version: str | None = None
    installer: Literal["uv", "pip"] | None = None
    installed_distributions: tuple[str, ...] = ()

    def with_lifecycle(
        self,
        lifecycle: PackageMaterializationLifecycle,
        *,
        target_path: Path | None = None,
        error_message: str | None = None,
        security: Literal["allowed", "denied"] | None = None,
    ) -> "PackageMaterializationRecord":
        return replace(
            self,
            lifecycle=lifecycle,
            target_path=target_path or self.target_path,
            error_message=error_message,
            security=security or self.security,
        )

    def with_git_state(
        self,
        *,
        requested_ref: str | None = None,
        resolved_commit: str | None = None,
        installed_commit: str | None = None,
        dirty: bool | None = None,
        pinned: bool | None = None,
    ) -> "PackageMaterializationRecord":
        return replace(
            self,
            pinned=pinned if pinned is not None else self.pinned,
            requested_ref=requested_ref
            if requested_ref is not None
            else self.requested_ref,
            resolved_commit=resolved_commit
            if resolved_commit is not None
            else self.resolved_commit,
            installed_commit=installed_commit
            if installed_commit is not None
            else self.installed_commit,
            dirty=dirty if dirty is not None else self.dirty,
            last_updated_at=datetime.now(UTC).isoformat(),
        )

    def with_python_state(
        self,
        *,
        installer: Literal["uv", "pip"],
        resolved_name: str | None = None,
        resolved_version: str | None = None,
        installed_distributions: tuple[str, ...] = (),
    ) -> "PackageMaterializationRecord":
        return replace(
            self,
            installer=installer,
            resolved_name=resolved_name
            if resolved_name is not None
            else self.resolved_name,
            resolved_version=resolved_version
            if resolved_version is not None
            else self.resolved_version,
            installed_distributions=installed_distributions,
            last_updated_at=datetime.now(UTC).isoformat(),
        )


PackageMaterializerBackend = Callable[
    [PackageMaterializationRecord],
    PackageMaterializationRecord | Awaitable[PackageMaterializationRecord],
]


class GitPackageMaterializerBackend:
    """Materialize git-backed package sources into a local install root."""

    def __init__(self, *, git_command: str = "git") -> None:
        self.git_command = git_command

    def __call__(
        self, record: PackageMaterializationRecord
    ) -> PackageMaterializationRecord:
        target = Path(record.target_path)
        source, ref = _git_clone_source(record.source)
        identity = PackageSourceIdentity.parse(record.source)
        record = (
            record.with_git_state(requested_ref=ref, pinned=identity.pinned)
            if ref
            else record
        )
        try:
            if target.exists():
                if not (target / ".git").is_dir():
                    raise RuntimeError(
                        f"Package target already exists and is not a git checkout: {target}"
                    )
                local_state = _record_with_local_git_state(
                    record.with_lifecycle("installed", target_path=target), self
                )
                if local_state.dirty:
                    return local_state.with_lifecycle(
                        "failed",
                        error_message="Package checkout is dirty; commit or discard local changes before updating.",
                    )
                if identity.pinned:
                    return local_state
                self._update_existing_checkout(target)
                return _record_with_local_git_state(
                    record.with_lifecycle("installed", target_path=target), self
                )

            target.parent.mkdir(parents=True, exist_ok=True)
            self._run_git(["clone", source, str(target)])
            if ref:
                self._run_git(["checkout", ref], cwd=target)
            return _record_with_local_git_state(
                record.with_lifecycle("installed", target_path=target), self
            )
        except Exception as exc:
            if target.exists() and not (target / ".git").is_dir():
                shutil.rmtree(target, ignore_errors=True)
            return record.with_lifecycle(
                "failed", error_message=str(exc), target_path=target
            )

    def _run_git(
        self, args: list[str], *, cwd: Path | None = None, check: bool = True
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [self.git_command, *args],
            cwd=cwd,
            check=check,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    def _update_existing_checkout(self, target: Path) -> None:
        branch = self._resolve_origin_head_branch(target)
        if branch:
            remote_ref = f"origin/{branch}"
            self._run_git(
                [
                    "fetch",
                    "--prune",
                    "--no-tags",
                    "origin",
                    f"+refs/heads/{branch}:refs/remotes/origin/{branch}",
                ],
                cwd=target,
            )
        else:
            remote_ref = "origin/HEAD"
            self._run_git(["fetch", "--all", "--prune", "--no-tags"], cwd=target)
            self._run_git(
                ["remote", "set-head", "origin", "-a"], cwd=target, check=False
            )
        local_commit = self._run_git(["rev-parse", "HEAD"], cwd=target).stdout.strip()
        remote_commit = self._run_git(
            ["rev-parse", remote_ref], cwd=target
        ).stdout.strip()
        if local_commit == remote_commit:
            return
        self._run_git(["reset", "--hard", remote_ref], cwd=target)

    def _resolve_origin_head_branch(self, target: Path) -> str | None:
        self._run_git(["remote", "set-head", "origin", "-a"], cwd=target, check=False)
        result = self._run_git(
            ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"],
            cwd=target,
            check=False,
        )
        branch = (
            _origin_branch_from_ref(result.stdout.strip())
            if result.returncode == 0
            else None
        )
        if branch:
            return branch
        upstream = self._run_git(
            ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
            cwd=target,
            check=False,
        )
        return (
            _origin_branch_from_ref(upstream.stdout.strip())
            if upstream.returncode == 0
            else None
        )


class PythonPackageInstallerBackend:
    """Install pypi: package sources into an isolated target directory."""

    def __init__(
        self,
        *,
        uv_command: str = "uv",
        python_command: str = sys.executable,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.uv_command = uv_command
        self.python_command = python_command
        self._runner = runner or subprocess.run

    def __call__(
        self, record: PackageMaterializationRecord
    ) -> PackageMaterializationRecord:
        requirement = record.requirement or python_package_requirement(record.source)
        if requirement is None:
            return record.with_lifecycle(
                "failed",
                error_message=f"Invalid Python package source: {record.source}",
            )
        target = Path(record.target_path)
        temp_path = target.with_name(f".{target.name}.{id(self)}.tmp")
        shutil.rmtree(temp_path, ignore_errors=True)
        try:
            temp_path.mkdir(parents=True, exist_ok=True)
            installer = self._install_requirement(requirement, temp_path)
            if target.exists():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            temp_path.replace(target)
            metadata = _python_distribution_metadata(target, record.name)
            return record.with_lifecycle(
                "installed", target_path=target, error_message=None
            ).with_python_state(
                installer=installer,
                resolved_name=metadata["name"],
                resolved_version=metadata["version"],
                installed_distributions=tuple(metadata["distributions"]),
            )
        except Exception as exc:
            shutil.rmtree(temp_path, ignore_errors=True)
            return record.with_lifecycle(
                "failed", error_message=str(exc), target_path=target
            )

    def _install_requirement(
        self, requirement: str, target: Path
    ) -> Literal["uv", "pip"]:
        try:
            self._run(
                [
                    self.uv_command,
                    "pip",
                    "install",
                    "--target",
                    str(target),
                    requirement,
                ]
            )
            return "uv"
        except FileNotFoundError:
            self._run(
                [
                    self.python_command,
                    "-m",
                    "pip",
                    "install",
                    "--target",
                    str(target),
                    requirement,
                ]
            )
            return "pip"

    def _run(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        return self._runner(
            args,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )


class PackageMaterializer:
    def __init__(
        self,
        *,
        install_root: str | Path,
        backend: PackageMaterializerBackend | None = None,
        python_backend: PackageMaterializerBackend | None = None,
        security_policy: PackageSourcePolicy | None = None,
        lockfile_path: str | Path | None = None,
        update_concurrency: int = 4,
        check_concurrency: int = 4,
        update_check_timeout_seconds: float = 10.0,
        progress_callback: Callable[[PackageProgressEvent], None] | None = None,
    ) -> None:
        self.install_root = Path(install_root).expanduser().resolve()
        self.lockfile_path = (
            Path(lockfile_path).expanduser().resolve()
            if lockfile_path is not None
            else self.install_root.parent / "package-lock.json"
        )
        self._backend = backend
        self._python_backend = python_backend or PythonPackageInstallerBackend()
        self._security_policy = (
            security_policy or _DenyUnconfiguredPackageSourcePolicy()
        )
        self._progress_callback = progress_callback
        self.update_concurrency = max(1, int(update_concurrency))
        self.check_concurrency = max(1, int(check_concurrency))
        self.update_check_timeout_seconds = update_check_timeout_seconds
        self._records: dict[str, PackageMaterializationRecord] = {}
        self._lockfile_diagnostics: list[dict[str, object]] = []
        self._load_lockfile()

    def set_progress_callback(
        self, callback: Callable[[PackageProgressEvent], None] | None
    ) -> None:
        self._progress_callback = callback

    def prepare_remote_source(self, source: str) -> PackageMaterializationRecord:
        if not is_remote_package_source(source):
            raise ValueError(
                f"Package materialization requires a remote source: {source}"
            )
        record = self._source_record(source)
        self._records[_record_key(source)] = record
        self._save_lockfile()
        return record

    async def materialize_remote_source(
        self, source: str
    ) -> PackageMaterializationRecord:
        record = self.prepare_remote_source(source)
        return await self._run_backend_for_record(record)

    def materialize_remote_source_sync(
        self, source: str
    ) -> PackageMaterializationRecord:
        record = self.prepare_remote_source(source)
        return self._run_backend_for_record_sync(record)

    async def materialize_temporary_remote_source(
        self, source: str
    ) -> PackageMaterializationRecord:
        if not is_remote_package_source(source):
            raise ValueError(
                f"Package materialization requires a remote source: {source}"
            )
        return await self._run_backend_for_record(
            self._source_record(source), persist=False
        )

    def materialize_temporary_remote_source_sync(
        self, source: str
    ) -> PackageMaterializationRecord:
        if not is_remote_package_source(source):
            raise ValueError(
                f"Package materialization requires a remote source: {source}"
            )
        return self._run_backend_for_record_sync(
            self._source_record(source), persist=False
        )

    async def update_remote_source(self, source: str) -> PackageMaterializationRecord:
        record = self.get_record(source)
        if record is None:
            record = self.prepare_remote_source(source)
        return await self._run_backend_for_record(
            record.with_lifecycle("materialization_pending", error_message=None),
            action="update",
        )

    def update_remote_source_sync(self, source: str) -> PackageMaterializationRecord:
        record = self.get_record(source)
        if record is None:
            record = self.prepare_remote_source(source)
        return self._run_backend_for_record_sync(
            record.with_lifecycle("materialization_pending", error_message=None),
            action="update",
        )

    def remove_remote_source(self, source: str) -> PackageMaterializationRecord:
        record = self.get_record(source)
        if record is None:
            record = self._source_record(source).with_lifecycle("remote_registered")
        self._emit_progress(
            "start",
            "remove",
            source,
            message=_progress_message("remove", source),
            target_path=record.target_path,
        )
        try:
            if record.target_path.exists():
                shutil.rmtree(record.target_path)
            removed = record.with_lifecycle(
                "remote_registered", error_message=None
            ).with_git_state(
                installed_commit="",
                resolved_commit="",
                dirty=False,
            )
            progress_type: PackageProgressEventType = "complete"
        except Exception as exc:
            removed = record.with_lifecycle("failed", error_message=str(exc))
            progress_type = "error"
        self._records[_record_key(source)] = removed
        self._save_lockfile()
        self._emit_progress(
            progress_type,
            "remove",
            source,
            message=removed.error_message,
            target_path=removed.target_path,
        )
        return removed

    def forget_remote_source(self, source: str) -> None:
        self._records.pop(_record_key(source), None)
        self._save_lockfile()

    async def update_all_remote_sources(self) -> list[PackageMaterializationRecord]:
        if _package_offline_enabled():
            return []
        records = [record for record in self.list_records() if not record.pinned]
        return await _run_with_concurrency(
            (
                lambda record=record: self.update_remote_source(record.source)
                for record in records
            ),
            limit=self.update_concurrency,
        )

    async def check_package_updates(self) -> list[dict[str, object]]:
        if _package_offline_enabled():
            return []
        git_records = [
            record
            for record in self.list_records()
            if not record.pinned
            and record.lifecycle == "installed"
            and record.installed_commit
            and record.source_type == "git"
        ]
        python_records = [
            record
            for record in self.list_records()
            if not record.pinned
            and record.lifecycle == "installed"
            and record.source_type == "python"
            and record.resolved_version
        ]
        checked = await _run_with_concurrency(
            (
                *[
                    lambda record=record: self._check_remote_update(record)
                    for record in git_records
                ],
                *[
                    lambda record=record: self._check_python_update(record)
                    for record in python_records
                ],
            ),
            limit=self.check_concurrency,
        )
        return [update for update in checked if update is not None]

    async def _check_remote_update(
        self, record: PackageMaterializationRecord
    ) -> dict[str, object] | None:
        self._emit_progress(
            "start",
            "check",
            record.source,
            message=_progress_message("check", record.source),
            target_path=record.target_path,
        )
        latest, failure_reason = await _remote_git_head_result_async(
            record.source, self.update_check_timeout_seconds
        )
        _, ref = _git_clone_source(record.source)
        if failure_reason:
            self._emit_progress(
                "error",
                "check",
                record.source,
                message=failure_reason,
                target_path=record.target_path,
            )
            return {
                "source": record.source,
                "name": record.name,
                "currentCommit": record.installed_commit,
                "availableCommit": "",
                "installedCommit": record.installed_commit,
                "resolvedCommit": record.resolved_commit,
                "requestedRef": record.requested_ref or "",
                "availableRef": ref or "HEAD",
                "dirty": record.dirty,
                "pinned": record.pinned,
                "status": "check_failed",
                "reason": failure_reason,
            }
        if latest and latest != record.installed_commit:
            self._emit_progress(
                "complete",
                "check",
                record.source,
                message="Package update available.",
                target_path=record.target_path,
            )
            return {
                "source": record.source,
                "name": record.name,
                "currentCommit": record.installed_commit,
                "availableCommit": latest,
                "installedCommit": record.installed_commit,
                "resolvedCommit": record.resolved_commit,
                "requestedRef": record.requested_ref or "",
                "availableRef": ref or "HEAD",
                "dirty": record.dirty,
                "pinned": record.pinned,
                "status": "update_available",
                "reason": "",
            }
        self._emit_progress(
            "complete",
            "check",
            record.source,
            message=None,
            target_path=record.target_path,
        )
        return None

    async def _check_python_update(
        self, record: PackageMaterializationRecord
    ) -> dict[str, object] | None:
        self._emit_progress(
            "start",
            "check",
            record.source,
            message=_progress_message("check", record.source),
            target_path=record.target_path,
        )
        latest, failure_reason = await _pypi_latest_version_result_async(
            record, self.update_check_timeout_seconds
        )
        current_version = record.resolved_version or ""
        if failure_reason:
            self._emit_progress(
                "error",
                "check",
                record.source,
                message=failure_reason,
                target_path=record.target_path,
            )
            return _python_update_record(
                record,
                available_version="",
                status="check_failed",
                reason=failure_reason,
            )
        if latest and latest != current_version:
            self._emit_progress(
                "complete",
                "check",
                record.source,
                message="Package update available.",
                target_path=record.target_path,
            )
            return _python_update_record(
                record, available_version=latest, status="update_available", reason=""
            )
        self._emit_progress(
            "complete",
            "check",
            record.source,
            message=None,
            target_path=record.target_path,
        )
        return None

    async def _run_backend_for_record(
        self,
        record: PackageMaterializationRecord,
        *,
        persist: bool = True,
        action: PackageProgressAction = "install",
    ) -> PackageMaterializationRecord:
        source = record.source
        decision = self._security_policy.evaluate_package_source(source)
        if decision.disposition != "allow":
            record = record.with_lifecycle(
                "failed", error_message=decision.reason, security="denied"
            )
            self._emit_progress(
                "error",
                action,
                source,
                message=record.error_message,
                target_path=record.target_path,
            )
            if persist:
                self._records[_record_key(source)] = record
                self._save_lockfile()
            return record
        backend = self._backend_for_record(record)
        if backend is None:
            return record
        self._emit_progress(
            "start",
            action,
            source,
            message=_progress_message(action, source),
            target_path=record.target_path,
        )
        try:
            result = backend(record)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:
            result = record.with_lifecycle("failed", error_message=str(exc))
        self._emit_progress(
            "error" if result.lifecycle == "failed" else "complete",
            action,
            source,
            message=result.error_message,
            target_path=result.target_path,
        )
        if persist:
            self._records[_record_key(source)] = result
            self._save_lockfile()
        return result

    def _run_backend_for_record_sync(
        self,
        record: PackageMaterializationRecord,
        *,
        persist: bool = True,
        action: PackageProgressAction = "install",
    ) -> PackageMaterializationRecord:
        source = record.source
        decision = self._security_policy.evaluate_package_source(source)
        if decision.disposition != "allow":
            record = record.with_lifecycle(
                "failed", error_message=decision.reason, security="denied"
            )
            self._emit_progress(
                "error",
                action,
                source,
                message=record.error_message,
                target_path=record.target_path,
            )
            if persist:
                self._records[_record_key(source)] = record
                self._save_lockfile()
            return record
        backend = self._backend_for_record(record)
        if backend is None:
            return record
        self._emit_progress(
            "start",
            action,
            source,
            message=_progress_message(action, source),
            target_path=record.target_path,
        )
        try:
            result = backend(record)
            if inspect.isawaitable(result):
                raise RuntimeError(
                    "Package materializer backend is async and cannot run during synchronous bootstrap."
                )
        except Exception as exc:
            result = record.with_lifecycle("failed", error_message=str(exc))
        self._emit_progress(
            "error" if result.lifecycle == "failed" else "complete",
            action,
            source,
            message=result.error_message,
            target_path=result.target_path,
        )
        if persist:
            self._records[_record_key(source)] = result
            self._save_lockfile()
        return result

    def _source_record(self, source: str) -> PackageMaterializationRecord:
        identity = PackageSourceIdentity.parse(source)
        source_type: Literal["git", "python"] = (
            "python" if identity.source_type == "python" else "git"
        )
        target_root = (
            self.install_root / "python"
            if source_type == "python"
            else self.install_root
        )
        return PackageMaterializationRecord(
            source=source,
            name=remote_package_name(source),
            lifecycle="materialization_pending",
            target_path=target_root / remote_package_name(source),
            source_type=source_type,
            requirement=python_package_requirement(source),
            pinned=identity.pinned,
            requested_ref=identity.ref,
        )

    def _backend_for_record(
        self, record: PackageMaterializationRecord
    ) -> PackageMaterializerBackend | None:
        if record.source_type == "python" or is_python_package_source(record.source):
            return self._python_backend
        return self._backend

    def _emit_progress(
        self,
        event_type: PackageProgressEventType,
        action: PackageProgressAction,
        source: str,
        *,
        message: str | None = None,
        target_path: Path | None = None,
    ) -> None:
        if self._progress_callback is None:
            return
        self._progress_callback(
            PackageProgressEvent(
                type=event_type,
                action=action,
                source=source,
                message=message,
                target_path=target_path,
            )
        )

    def get_record(self, source: str) -> PackageMaterializationRecord | None:
        return self._records.get(_record_key(source))

    def list_records(self) -> list[PackageMaterializationRecord]:
        return list(self._records.values())

    def get_lockfile_diagnostics(self) -> list[dict[str, object]]:
        return [dict(diagnostic) for diagnostic in self._lockfile_diagnostics]

    @staticmethod
    def load_trusted_sources(lockfile_path: str | Path) -> tuple[str, ...]:
        try:
            payload = json.loads(Path(lockfile_path).read_text(encoding="utf-8"))
        except Exception:
            return ()
        values = payload.get("trustedSources") if isinstance(payload, dict) else None
        if not isinstance(values, list):
            return ()
        return tuple(value for value in values if isinstance(value, str))

    def _load_lockfile(self) -> None:
        try:
            payload = json.loads(self.lockfile_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except Exception as exc:
            self._lockfile_diagnostics.append(
                {
                    "code": "package_lockfile_unreadable",
                    "message": f"Package lockfile could not be read: {exc}",
                    "path": str(self.lockfile_path),
                }
            )
            return
        records = payload.get("packages") if isinstance(payload, dict) else None
        if not isinstance(records, list):
            return
        for item in records:
            if not isinstance(item, dict):
                continue
            source = item.get("source")
            target_path = item.get("targetPath")
            if not isinstance(source, str) or not isinstance(target_path, str):
                continue
            lifecycle = item.get("lifecycle")
            if lifecycle not in {
                "remote_registered",
                "materialization_pending",
                "installed",
                "failed",
            }:
                lifecycle = "remote_registered"
            normalized_lifecycle = cast(PackageMaterializationLifecycle, lifecycle)
            raw_source_type = item.get("sourceType")
            source_type = cast(
                PackageSourceType,
                raw_source_type
                if raw_source_type in {"git", "python", "local"}
                else "git",
            )
            self._records[_record_key(source)] = PackageMaterializationRecord(
                source=source,
                name=str(item.get("name") or remote_package_name(source)),
                lifecycle=normalized_lifecycle,
                target_path=Path(target_path),
                error_message=item.get("errorMessage")
                if isinstance(item.get("errorMessage"), str)
                else None,
                security="denied" if item.get("security") == "denied" else "allowed",
                pinned=bool(item.get("pinned")),
                requested_ref=item.get("requestedRef")
                if isinstance(item.get("requestedRef"), str)
                else None,
                resolved_commit=item.get("resolvedCommit")
                if isinstance(item.get("resolvedCommit"), str)
                else None,
                installed_commit=item.get("installedCommit")
                if isinstance(item.get("installedCommit"), str)
                else None,
                dirty=bool(item.get("dirty")),
                last_updated_at=item.get("lastUpdatedAt")
                if isinstance(item.get("lastUpdatedAt"), str)
                else None,
                source_type=source_type,
                requirement=item.get("requirement")
                if isinstance(item.get("requirement"), str)
                else None,
                resolved_name=item.get("resolvedName")
                if isinstance(item.get("resolvedName"), str)
                else None,
                resolved_version=item.get("resolvedVersion")
                if isinstance(item.get("resolvedVersion"), str)
                else None,
                installer=item.get("installer")
                if item.get("installer") in {"uv", "pip"}
                else None,
                installed_distributions=tuple(
                    value
                    for value in item.get("installedDistributions", ())
                    if isinstance(value, str)
                )
                if isinstance(item.get("installedDistributions"), list | tuple)
                else (),
            )

    def _save_lockfile(self) -> None:
        self.lockfile_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.lockfile_path.with_name(
            f"{self.lockfile_path.name}.{id(self)}.tmp"
        )
        payload = {
            "version": 1,
            "trustedSources": sorted(
                record.source
                for record in self._records.values()
                if record.security == "allowed"
            ),
            "packages": [
                {
                    "source": record.source,
                    "name": record.name,
                    "lifecycle": record.lifecycle,
                    "targetPath": str(record.target_path),
                    "errorMessage": record.error_message,
                    "security": record.security,
                    "pinned": record.pinned,
                    "requestedRef": record.requested_ref,
                    "resolvedCommit": record.resolved_commit,
                    "installedCommit": record.installed_commit,
                    "dirty": record.dirty,
                    "lastUpdatedAt": record.last_updated_at,
                    "sourceType": record.source_type,
                    "requirement": record.requirement,
                    "resolvedName": record.resolved_name,
                    "resolvedVersion": record.resolved_version,
                    "installer": record.installer,
                    "installedDistributions": list(record.installed_distributions),
                }
                for record in self.list_records()
            ],
        }
        try:
            temp_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
            )
            temp_path.replace(self.lockfile_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()


class _DenyUnconfiguredPackageSourcePolicy:
    def evaluate_package_source(self, source: str | Path) -> PolicyDecision:
        return PolicyDecision.deny(
            "Package source policy must be supplied by the product adapter.",
            code="package_source_policy_required",
        )


def _git_clone_source(source: str) -> tuple[str, str | None]:
    return clone_source_and_ref(source)


def _record_key(source: str) -> str:
    return PackageSourceIdentity.parse(source).identity_key


def _origin_branch_from_ref(ref: str) -> str | None:
    if not ref.startswith("origin/"):
        return None
    branch = ref[len("origin/") :].strip()
    return branch or None


def _record_with_local_git_state(
    record: PackageMaterializationRecord,
    backend: GitPackageMaterializerBackend,
) -> PackageMaterializationRecord:
    commit = backend._run_git(
        ["rev-parse", "HEAD"], cwd=record.target_path
    ).stdout.strip()
    status = backend._run_git(
        ["status", "--porcelain"], cwd=record.target_path
    ).stdout.strip()
    return record.with_git_state(
        requested_ref=record.requested_ref,
        resolved_commit=commit,
        installed_commit=commit,
        dirty=bool(status),
    )


def _python_distribution_metadata(
    target: Path, preferred_name: str
) -> _PythonDistributionMetadata:
    distributions: list[str] = []
    resolved_name: str | None = None
    resolved_version: str | None = None
    preferred_key = _normalize_dist_name(preferred_name)
    for distribution in importlib.metadata.distributions(path=[str(target)]):
        name = distribution.metadata["Name"] or distribution.name
        version = distribution.version
        if name and version:
            distributions.append(f"{name}=={version}")
        if name and _normalize_dist_name(name) == preferred_key:
            resolved_name = _normalize_dist_name(name)
            resolved_version = version
    return {
        "name": resolved_name,
        "version": resolved_version,
        "distributions": tuple(sorted(distributions)),
    }


def _normalize_dist_name(name: str) -> str:
    import re

    return re.sub(r"[-_.]+", "-", name).lower()


def _progress_message(action: PackageProgressAction, source: str) -> str:
    verb = {
        "install": "Installing",
        "update": "Updating",
        "remove": "Removing",
        "check": "Checking",
        "resolve": "Resolving",
    }[action]
    return f"{verb} {source}..."


def _remote_git_head(source: str) -> str | None:
    head, _ = _remote_git_head_result(source)
    return head


def _remote_git_head_result(
    source: str, timeout_seconds: float | None = None
) -> tuple[str | None, str]:
    if _package_offline_enabled():
        return None, ""
    args = _remote_git_head_args(source)
    if args is None:
        return None, ""
    try:
        result = subprocess.run(
            ["git", *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_seconds,
        )
    except Exception as exc:
        return None, f"Failed to check remote package update: {exc}"
    line = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    if not line:
        return None, "Failed to check remote package update: remote HEAD was empty."
    return line.split()[0], ""


async def _remote_git_head_result_async(
    source: str, timeout_seconds: float | None = None
) -> tuple[str | None, str]:
    if _package_offline_enabled():
        return None, ""
    args = _remote_git_head_args(source)
    if args is None:
        return None, ""
    process = await asyncio.create_subprocess_exec(
        "git",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout_seconds
        )
    except TimeoutError:
        process.kill()
        await process.communicate()
        return (
            None,
            f"Failed to check remote package update: git ls-remote timed out after {timeout_seconds} seconds.",
        )
    if process.returncode != 0:
        reason = (
            stderr.decode("utf-8", errors="replace").strip()
            or f"git exited with status {process.returncode}"
        )
        return None, f"Failed to check remote package update: {reason}"
    line = (
        stdout.decode("utf-8", errors="replace").strip().splitlines()[0]
        if stdout.strip()
        else ""
    )
    if not line:
        return None, "Failed to check remote package update: remote HEAD was empty."
    return line.split()[0], ""


async def _pypi_latest_version_result_async(
    record: PackageMaterializationRecord,
    timeout_seconds: float | None = None,
) -> tuple[str | None, str]:
    return await asyncio.to_thread(_pypi_latest_version_result, record, timeout_seconds)


def _pypi_latest_version_result(
    record: PackageMaterializationRecord,
    timeout_seconds: float | None = None,
) -> tuple[str | None, str]:
    package_name = record.resolved_name or record.name
    if not package_name:
        return None, "Failed to check Python package update: missing package name."
    url = f"https://pypi.org/pypi/{urllib.parse.quote(package_name, safe='')}/json"
    try:
        with urllib.request.urlopen(url, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return None, f"Failed to check Python package update: {exc}"
    info = payload.get("info") if isinstance(payload, dict) else None
    version = info.get("version") if isinstance(info, dict) else None
    if not isinstance(version, str) or not version.strip():
        return (
            None,
            "Failed to check Python package update: PyPI response did not include info.version.",
        )
    return version.strip(), ""


def _python_update_record(
    record: PackageMaterializationRecord,
    *,
    available_version: str,
    status: Literal["update_available", "check_failed"],
    reason: str,
) -> dict[str, object]:
    current_version = record.resolved_version or ""
    return {
        "source": record.source,
        "name": record.resolved_name or record.name,
        "currentVersion": current_version,
        "availableVersion": available_version,
        "installedVersion": current_version,
        "resolvedVersion": current_version,
        "requirement": record.requirement or "",
        "installedDistributions": list(record.installed_distributions),
        "pinned": record.pinned,
        "status": status,
        "reason": reason,
        "sourceType": "python",
    }


def _remote_git_head_args(source: str) -> list[str] | None:
    clone_source, ref = _git_clone_source(source)
    identity = PackageSourceIdentity.parse(source)
    if identity.pinned:
        return None
    return (
        ["ls-remote", clone_source, f"refs/heads/{ref}"]
        if ref
        else ["ls-remote", clone_source, "HEAD"]
    )


async def _run_with_concurrency(tasks, *, limit: int):
    semaphore = asyncio.Semaphore(max(1, int(limit)))

    async def run(task):
        async with semaphore:
            return await task()

    return await asyncio.gather(*(run(task) for task in tasks))


def _package_offline_enabled() -> bool:
    return package_offline_enabled()


def package_offline_enabled() -> bool:
    """Return whether package materialization must avoid network access."""

    for name in ("LOUSHANG_OFFLINE", "PI_OFFLINE"):
        value = os.environ.get(name)
        if value and value.lower() in {"1", "true", "yes"}:
            return True
    return False


def resolve_session_package_install_root(
    *,
    session_dir: str | Path,
    cwd: str | Path,
    session_container_name: str = "sessions",
    platform_directory: str = ".loushang",
) -> Path:
    """Resolve the package cache associated with a Product session layout."""

    resolved_session_dir = Path(session_dir)
    if resolved_session_dir.name == session_container_name:
        return resolved_session_dir.parent / "packages"
    if str(resolved_session_dir):
        return resolved_session_dir / "packages"
    return Path(cwd) / platform_directory / "packages"
