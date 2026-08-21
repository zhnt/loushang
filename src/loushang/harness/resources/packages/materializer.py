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
from collections.abc import Awaitable, Callable, Sequence
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
from loushang.harness.resources.plugins.manifest import PluginManifestError
from loushang.harness.resources.plugins.revisions import PluginRevisionStore
from loushang.harness.resources.plugins.types import (
    PluginRevisionKind,
    PluginSource,
    PluginSourceBinding,
    ResolvedPluginPackage,
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
        plugin_revision_root: str | Path | None = None,
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
        self._plugin_revision_store = PluginRevisionStore(
            plugin_revision_root
            if plugin_revision_root is not None
            else self.install_root.parent / "plugin-revisions"
        )
        self.update_concurrency = max(1, int(update_concurrency))
        self.check_concurrency = max(1, int(check_concurrency))
        self.update_check_timeout_seconds = update_check_timeout_seconds
        self._records: dict[str, PackageMaterializationRecord] = {}
        self._plugin_bindings: dict[str, PluginSourceBinding] = {}
        self._plugin_binding_lock_error: str | None = None
        self._lockfile_diagnostics: list[dict[str, object]] = []
        self._load_lockfile()

    def set_progress_callback(
        self, callback: Callable[[PackageProgressEvent], None] | None
    ) -> None:
        self._progress_callback = callback

    def bind_plugin_packages(
        self,
        packages: Sequence[ResolvedPluginPackage],
    ) -> tuple[PluginSourceBinding, ...]:
        """Atomically bind resolved descriptors without accepting Plugin renames."""

        return self._bind_plugin_packages(packages, allow_plugin_id_change=False)

    def publish_plugin_packages(
        self,
        packages: Sequence[ResolvedPluginPackage],
    ) -> tuple[ResolvedPluginPackage, ...]:
        """Publish source descriptors as verified content-addressed revisions."""

        return self._plugin_revision_store.publish_all(tuple(packages))

    def rebind_plugin_packages(
        self,
        packages: Sequence[ResolvedPluginPackage],
    ) -> tuple[PluginSourceBinding, ...]:
        """Explicitly replace source identities after management authorization."""

        return self._bind_plugin_packages(packages, allow_plugin_id_change=True)

    def validate_plugin_package(self, package: ResolvedPluginPackage) -> None:
        """Validate one descriptor against an existing binding without writing."""

        self._assert_plugin_binding_lock_valid()
        candidate = self._plugin_binding(package)
        self._assert_plugin_binding(candidate, package)

    def get_plugin_binding(
        self,
        source: str | Path | PluginSource,
    ) -> PluginSourceBinding | None:
        return self._plugin_bindings.get(_plugin_source_identity(source))

    def forget_plugin_binding(self, source: str | Path | PluginSource) -> None:
        key = _plugin_source_identity(source)
        if key not in self._plugin_bindings:
            return
        previous = self._plugin_bindings
        self._plugin_bindings = dict(previous)
        self._plugin_bindings.pop(key, None)
        try:
            self._save_lockfile()
        except Exception:
            self._plugin_bindings = previous
            raise

    def _bind_plugin_packages(
        self,
        packages: Sequence[ResolvedPluginPackage],
        *,
        allow_plugin_id_change: bool,
    ) -> tuple[PluginSourceBinding, ...]:
        candidates = tuple(self._plugin_binding(package) for package in packages)
        if not allow_plugin_id_change:
            self._assert_plugin_binding_lock_valid()
        next_bindings = dict(self._plugin_bindings)
        for package, candidate in zip(packages, candidates, strict=True):
            if not allow_plugin_id_change:
                self._assert_plugin_binding(candidate, package, bindings=next_bindings)
            next_bindings[candidate.source_identity] = candidate
        if next_bindings == self._plugin_bindings and not (
            allow_plugin_id_change and self._plugin_binding_lock_error is not None
        ):
            return candidates
        previous = self._plugin_bindings
        previous_lock_error = self._plugin_binding_lock_error
        self._plugin_bindings = next_bindings
        if allow_plugin_id_change:
            self._plugin_binding_lock_error = None
        try:
            self._save_lockfile()
        except Exception:
            self._plugin_bindings = previous
            self._plugin_binding_lock_error = previous_lock_error
            raise
        return candidates

    def _assert_plugin_binding_lock_valid(self) -> None:
        if self._plugin_binding_lock_error is None:
            return
        raise PluginManifestError(
            self._plugin_binding_lock_error,
            code="plugin_binding_lock_invalid",
            path=self.lockfile_path,
        )

    def _record_plugin_binding_lock_error(self, *, code: str, message: str) -> None:
        self._plugin_binding_lock_error = message
        self._lockfile_diagnostics.append(
            {
                "code": code,
                "message": message,
                "path": str(self.lockfile_path),
            }
        )

    def _assert_plugin_binding(
        self,
        candidate: PluginSourceBinding,
        package: ResolvedPluginPackage,
        *,
        bindings: dict[str, PluginSourceBinding] | None = None,
    ) -> None:
        current = self._plugin_bindings if bindings is None else bindings
        bound = current.get(candidate.source_identity)
        if bound is None or bound.plugin_id == candidate.plugin_id:
            return
        raise PluginManifestError(
            f"Plugin source identity changed from {bound.plugin_id!r} to "
            f"{candidate.plugin_id!r}: {candidate.source}",
            code="plugin_identity_changed",
            path=package.manifest_path or package.root,
        )

    def _plugin_binding(
        self,
        package: ResolvedPluginPackage,
    ) -> PluginSourceBinding:
        source = package.source
        source_value = _plugin_source_value(source)
        revision: str | None = None
        revision_kind: PluginRevisionKind | None = None
        if source.kind == "remote" and source.url is not None:
            record = self.get_record(source.url)
            if record is not None and record.installed_commit:
                revision = record.installed_commit
                revision_kind = "git_commit"
            elif record is not None and record.resolved_version:
                revision = record.resolved_version
                revision_kind = "python_version"
        if revision is None and package.content_digest is not None:
            revision = package.content_digest
            revision_kind = "content_sha256"
        elif revision is None and package.manifest_digest is not None:
            revision = package.manifest_digest
            revision_kind = "manifest_sha256"
        return PluginSourceBinding(
            source=source_value,
            source_identity=_plugin_source_identity(source),
            source_kind=source.kind,
            plugin_id=package.manifest.name,
            manifest_digest=package.manifest_digest,
            content_digest=package.content_digest,
            revision=revision,
            revision_kind=revision_kind,
        )

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
        record_key = _record_key(source)
        binding_key = _plugin_source_identity(source)
        if (
            record_key not in self._records
            and binding_key not in self._plugin_bindings
        ):
            return
        previous_records = self._records
        previous_bindings = self._plugin_bindings
        self._records = dict(previous_records)
        self._plugin_bindings = dict(previous_bindings)
        self._records.pop(record_key, None)
        self._plugin_bindings.pop(binding_key, None)
        try:
            self._save_lockfile()
        except Exception:
            self._records = previous_records
            self._plugin_bindings = previous_bindings
            raise

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
            self._plugin_binding_lock_error = (
                f"Package lockfile cannot establish Plugin source identity: {exc}"
            )
            self._lockfile_diagnostics.append(
                {
                    "code": "package_lockfile_unreadable",
                    "message": f"Package lockfile could not be read: {exc}",
                    "path": str(self.lockfile_path),
                }
            )
            return
        if not isinstance(payload, dict):
            self._record_plugin_binding_lock_error(
                code="package_lockfile_invalid_plugin_bindings",
                message="Package lockfile must be a JSON object.",
            )
            return
        binding_section_present = "pluginBindings" in payload
        lockfile_version = payload.get("version", 1)
        if lockfile_version not in {1, 2}:
            self._record_plugin_binding_lock_error(
                code="package_lockfile_invalid_plugin_bindings",
                message=f"Unsupported package lockfile version: {lockfile_version!r}.",
            )
        elif lockfile_version == 2 and not binding_section_present:
            self._record_plugin_binding_lock_error(
                code="package_lockfile_invalid_plugin_bindings",
                message="Package lockfile v2 is missing pluginBindings.",
            )
        elif binding_section_present and lockfile_version != 2:
            self._record_plugin_binding_lock_error(
                code="package_lockfile_invalid_plugin_bindings",
                message=(
                    "Package lockfile pluginBindings requires lockfile version 2."
                ),
            )
        records = payload.get("packages")
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
        bindings = payload.get("pluginBindings")
        if bindings is None:
            return
        if not isinstance(bindings, list):
            self._record_plugin_binding_lock_error(
                code="package_lockfile_invalid_plugin_bindings",
                message="Package lockfile pluginBindings must be a list.",
            )
            return
        for item in bindings:
            binding = _plugin_binding_from_json(item)
            if binding is None:
                self._record_plugin_binding_lock_error(
                    code="package_lockfile_invalid_plugin_binding",
                    message=(
                        "Package lockfile contains an invalid Plugin source binding."
                    ),
                )
                continue
            if binding.source_identity in self._plugin_bindings:
                self._record_plugin_binding_lock_error(
                    code="package_lockfile_duplicate_plugin_binding",
                    message=(
                        "Package lockfile contains duplicate Plugin source bindings."
                    ),
                )
                continue
            self._plugin_bindings[binding.source_identity] = binding

    def _save_lockfile(self) -> None:
        self.lockfile_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.lockfile_path.with_name(
            f"{self.lockfile_path.name}.{id(self)}.tmp"
        )
        payload = {
            "version": 2,
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
            "pluginBindings": [
                {
                    "source": binding.source,
                    "sourceIdentity": binding.source_identity,
                    "sourceKind": binding.source_kind,
                    "pluginId": binding.plugin_id,
                    "manifestDigest": binding.manifest_digest,
                    "contentDigest": binding.content_digest,
                    "revision": binding.revision,
                    "revisionKind": binding.revision_kind,
                }
                for binding in sorted(
                    self._plugin_bindings.values(),
                    key=lambda value: value.source_identity,
                )
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


def _plugin_source_value(source: PluginSource) -> str:
    if source.kind == "remote":
        if source.url is None:
            raise ValueError("Remote Plugin source requires a URL.")
        return source.url
    if source.path is None:
        raise ValueError("Local Plugin source requires a path.")
    return str(source.path.expanduser().resolve())


def _plugin_source_identity(source: str | Path | PluginSource) -> str:
    if isinstance(source, PluginSource):
        if source.kind == "remote":
            if source.url is None:
                raise ValueError("Remote Plugin source requires a URL.")
            return f"remote:{_record_key(source.url)}"
        if source.path is None:
            raise ValueError("Local Plugin source requires a path.")
        path = source.path
    elif isinstance(source, str) and is_remote_package_source(source):
        return f"remote:{_record_key(source)}"
    else:
        path = Path(source)
    return f"local:{path.expanduser().resolve()}"


def _plugin_binding_from_json(value: object) -> PluginSourceBinding | None:
    if not isinstance(value, dict):
        return None
    source = value.get("source")
    source_identity = value.get("sourceIdentity")
    source_kind = value.get("sourceKind")
    plugin_id = value.get("pluginId")
    if (
        not isinstance(source, str)
        or not source
        or not isinstance(source_identity, str)
        or not source_identity
        or source_kind not in {"local", "remote"}
        or not isinstance(plugin_id, str)
        or not plugin_id
        or plugin_id.strip() != plugin_id
    ):
        return None
    remote_source = is_remote_package_source(source)
    if remote_source != (source_kind == "remote"):
        return None
    if source_kind == "local" and str(Path(source).expanduser().resolve()) != source:
        return None
    source_descriptor = (
        PluginSource(url=source, kind="remote")
        if source_kind == "remote"
        else PluginSource(path=Path(source))
    )
    try:
        canonical_source_identity = _plugin_source_identity(source_descriptor)
    except (TypeError, ValueError):
        return None
    if canonical_source_identity != source_identity:
        return None
    manifest_digest = value.get("manifestDigest")
    content_digest = value.get("contentDigest")
    revision = value.get("revision")
    if (
        manifest_digest is not None
        and not isinstance(manifest_digest, str)
        or content_digest is not None
        and not isinstance(content_digest, str)
        or revision is not None
        and not isinstance(revision, str)
    ):
        return None
    if manifest_digest is not None and not _is_sha256_digest(manifest_digest):
        return None
    if content_digest is not None and not _is_sha256_digest(content_digest):
        return None
    revision_kind = value.get("revisionKind")
    if revision_kind not in {
        None,
        "git_commit",
        "python_version",
        "manifest_sha256",
        "content_sha256",
    }:
        return None
    if (revision is None) != (revision_kind is None):
        return None
    if revision_kind == "manifest_sha256" and revision != manifest_digest:
        return None
    if revision_kind == "content_sha256" and revision != content_digest:
        return None
    return PluginSourceBinding(
        source=source,
        source_identity=source_identity,
        source_kind=source_kind,
        plugin_id=plugin_id,
        manifest_digest=manifest_digest,
        content_digest=content_digest,
        revision=revision,
        revision_kind=cast(PluginRevisionKind | None, revision_kind),
    )


def _is_sha256_digest(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


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
