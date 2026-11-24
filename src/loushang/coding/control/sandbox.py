from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    ExecutionProfileProvider,
    constrain_execution_profile,
)
from loushang.harness.authorization.execution_profile import WorkspaceExecutionSelection
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.environment import HostEnvironmentProbe
from loushang.harness.permissions import PermissionProfileSnapshot
from loushang.harness.sandbox import (
    SandboxBackendRegistry,
    SandboxExecutionRuntime,
    SandboxSettings,
    bind_sandbox_execution_runtime,
)
from loushang.harness.sandbox.authorization import WorkspaceSandboxScopePolicy
from loushang.harness.workspace.exec import ExecService
from loushang.harness.workspace.git import find_git_paths
from loushang.hosting.filesystem import host_filesystem_roots


@dataclass(frozen=True, slots=True)
class CodingExecutionAuthority(WorkspaceExecutionSelection):
    """Live user selection within immutable Product and delegated ceilings."""

    workspace_root: Path
    workspace_profile: EffectiveExecutionProfile
    ceiling: EffectiveExecutionProfile
    permission_snapshot: Callable[[], PermissionProfileSnapshot]
    current_workspace_roots: Callable[[], tuple[Path, ...]] | None = None

    def __call__(self) -> EffectiveExecutionProfile:
        return self._select(self.workspace_profile)

    def for_workspace_operation(self) -> EffectiveExecutionProfile:
        if self.current_workspace_roots is not None:
            return self._select(self.workspace_profile)
        # Git processes need linked-worktree metadata outside the workspace.
        # Ordinary Standard/Cautious file tools retain their original boundary.
        workspace_only = constrain_execution_profile(
            self.workspace_profile,
            EffectiveExecutionProfile(
                readable_roots=(self.workspace_root,),
                writable_roots=(self.workspace_root,),
            ),
        )
        return self._select(workspace_only)

    def _select(self, workspace_profile: EffectiveExecutionProfile) -> EffectiveExecutionProfile:
        profile = self.permission_snapshot().effective_profile
        selected = (
            self.ceiling
            if profile.workspace_access == "managed_ceiling"
            else workspace_profile
        )
        if self.current_workspace_roots is not None:
            roots = self.current_workspace_roots()
            selected = constrain_execution_profile(
                selected, EffectiveExecutionProfile(readable_roots=roots, writable_roots=roots),
            )
        return constrain_execution_profile(self.ceiling, selected)


def coding_host_execution_profile(
    workspace_root: Path,
    *,
    writable: bool,
) -> EffectiveExecutionProfile:
    """Full selects host access; OS account permissions still apply.

    Windows uses drive roots plus the workspace's UNC share when applicable.
    A required workspace sandbox or an injected/delegated ceiling is intersected
    by the Product before this maximum is used for any action.
    """

    roots = host_filesystem_roots(workspace_root)
    return EffectiveExecutionProfile(
        readable_roots=roots,
        writable_roots=roots if writable else (),
        network="allowed",
    )


def _coding_workspace_roots(
    workspace_root: Path,
    writable: bool,
) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
    """Include only the repository metadata needed by ordinary Git commands."""

    readable = [workspace_root]
    writable_roots = [workspace_root] if writable else []
    git_paths = find_git_paths(workspace_root)
    if git_paths is None:
        return tuple(readable), tuple(writable_roots)

    _append_uncovered_root(readable, git_paths.repo_dir)
    for metadata_root in (git_paths.common_git_dir, git_paths.head_path.parent):
        _append_uncovered_root(readable, metadata_root)
        if writable:
            _append_uncovered_root(writable_roots, metadata_root)
    return tuple(readable), tuple(writable_roots)


def coding_workspace_execution_profile(
    workspace_root: str | Path,
    *,
    writable: bool,
) -> EffectiveExecutionProfile:
    """Freeze Coding's filesystem/network ceiling for one materialized workspace."""

    root = Path(workspace_root).expanduser().resolve(strict=False)
    if not root.is_dir():
        raise NotADirectoryError(20, "Not a directory", str(root))
    readable_roots, writable_roots = _coding_workspace_roots(
        root,
        writable=writable,
    )
    return EffectiveExecutionProfile(
        readable_roots=readable_roots,
        writable_roots=writable_roots,
        network="allowed",
    )


def _append_uncovered_root(roots: list[Path], candidate: Path) -> None:
    candidate = candidate.resolve(strict=False)
    if any(
        candidate == existing or candidate.is_relative_to(existing)
        for existing in roots
    ):
        return
    roots[:] = [
        existing
        for existing in roots
        if not existing.is_relative_to(candidate)
    ]
    roots.append(candidate)


@dataclass(frozen=True, slots=True)
class CodingSandboxScopePolicy(WorkspaceSandboxScopePolicy):
    """Derive one usable process scope from a Coding session workspace."""

    workspace_root: Path
    writable_workspace: bool = True
    _readable_roots: tuple[Path, ...] = field(init=False, repr=False)
    _writable_roots: tuple[Path, ...] = field(init=False, repr=False)
    execution_profile: EffectiveExecutionProfile | None = None
    execution_profile_provider: ExecutionProfileProvider | None = None

    _workspace_roots = staticmethod(_coding_workspace_roots)
    _product_label = "Coding"


def bind_coding_sandbox_runtime(
    *,
    workspace_root: str | Path,
    writable_workspace: bool,
    settings: SandboxSettings,
    base_exec_service: ExecService,
    diagnostics_service: DiagnosticsService | None = None,
    session_id: str | None = None,
    registry: SandboxBackendRegistry | None = None,
    environment_probe: HostEnvironmentProbe | None = None,
    execution_profile: EffectiveExecutionProfile | None = None,
    execution_profile_provider: ExecutionProfileProvider | None = None,
) -> SandboxExecutionRuntime:
    """Bind Coding's workspace policy to the Product-neutral sandbox runtime."""

    scope_policy = (
        CodingSandboxScopePolicy(
            workspace_root=Path(workspace_root),
            writable_workspace=writable_workspace,
            execution_profile=execution_profile,
            execution_profile_provider=execution_profile_provider,
        )
        if settings.enabled
        else None
    )
    return bind_sandbox_execution_runtime(
        base_exec_service=base_exec_service,
        settings=settings,
        scope_request_factory=scope_policy,
        registry=registry,
        environment_probe=environment_probe,
        diagnostics_service=diagnostics_service,
        session_id=session_id,
        execution_profile=(
            scope_policy.execution_profile if scope_policy is not None else execution_profile
        ),
        execution_profile_provider=execution_profile_provider,
    )


__all__ = [
    "CodingSandboxScopePolicy",
    "CodingExecutionAuthority",
    "bind_coding_sandbox_runtime",
    "coding_workspace_execution_profile",
    "coding_host_execution_profile",
]
