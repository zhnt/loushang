from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from string import ascii_uppercase

from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    ExecutionProfileProvider,
    constrain_execution_profile,
    select_execution_profile,
)
from loushang.harness.diagnostics.service import DiagnosticsService
from loushang.harness.diagnostics.types import DiagnosticDraft
from loushang.harness.environment import HostEnvironmentProbe
from loushang.harness.permissions import PermissionProfileSnapshot
from loushang.harness.sandbox import (
    SandboxBackendRegistry,
    SandboxDiagnostic,
    SandboxExecutionRuntime,
    SandboxScopeRequest,
    SandboxSettings,
    bind_sandbox_execution_runtime,
    sandbox_scope_request_from_profile,
)
from loushang.harness.workspace.exec import ExecRequest, ExecService
from loushang.harness.workspace.git import find_git_paths


@dataclass(frozen=True, slots=True)
class CodingExecutionAuthority:
    """Live user selection within immutable Product and delegated ceilings."""

    workspace_root: Path
    workspace_profile: EffectiveExecutionProfile
    ceiling: EffectiveExecutionProfile
    permission_snapshot: Callable[[], PermissionProfileSnapshot]

    def __call__(self) -> EffectiveExecutionProfile:
        return self._select(self.workspace_profile)

    def for_workspace_operation(self) -> EffectiveExecutionProfile:
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

    roots: tuple[Path, ...]
    if sys.platform == "win32":
        # Enumerate mounted drives once, without probing 26 potentially absent
        # devices or disconnected network paths during every session startup.
        import ctypes

        drive_mask = ctypes.windll.kernel32.GetLogicalDrives()
        if not drive_mask:
            raise OSError("cannot determine host filesystem drives")
        roots = tuple(
            Path(f"{drive}:\\") for index, drive in enumerate(ascii_uppercase)
            if drive_mask & (1 << index)
        )
    else:
        roots = (Path("/"),)
    anchor = Path(workspace_root.expanduser().resolve(strict=False).anchor)
    if anchor not in roots:
        roots = (*roots, anchor)
    return EffectiveExecutionProfile(
        readable_roots=roots,
        writable_roots=roots if writable else (),
        network="allowed",
    )


@dataclass(frozen=True, slots=True)
class CodingSandboxScopePolicy:
    """Derive one usable process scope from a Coding session workspace."""

    workspace_root: Path
    writable_workspace: bool = True
    _readable_roots: tuple[Path, ...] = field(init=False, repr=False)
    _writable_roots: tuple[Path, ...] = field(init=False, repr=False)
    execution_profile: EffectiveExecutionProfile | None = None
    execution_profile_provider: ExecutionProfileProvider | None = None

    def __post_init__(self) -> None:
        if type(self.writable_workspace) is not bool:
            raise TypeError("writable_workspace must be a bool")
        root = Path(self.workspace_root).expanduser().resolve(strict=False)
        if not root.is_dir():
            raise NotADirectoryError(20, "Not a directory", str(root))
        object.__setattr__(self, "workspace_root", root)
        readable_roots, writable_roots = _coding_workspace_roots(
            root,
            writable=self.writable_workspace,
        )
        object.__setattr__(self, "_readable_roots", readable_roots)
        object.__setattr__(self, "_writable_roots", writable_roots)
        ceiling = coding_workspace_execution_profile(
            root,
            writable=self.writable_workspace,
        )
        maximum = self.execution_profile or ceiling
        if not isinstance(maximum, EffectiveExecutionProfile):
            raise TypeError("execution profile must be an EffectiveExecutionProfile")
        if self.execution_profile_provider is None:
            maximum = constrain_execution_profile(ceiling, maximum)
        object.__setattr__(
            self,
            "execution_profile",
            maximum,
        )

    def __call__(self, request: ExecRequest) -> SandboxScopeRequest:
        if request.cwd is None:
            raise ValueError("Coding sandbox requires a materialized working directory")
        cwd = Path(request.cwd).expanduser().resolve(strict=False)
        assert self.execution_profile is not None
        selected = select_execution_profile(self.execution_profile, self.execution_profile_provider)
        if (
            not any(cwd.is_relative_to(root) for root in selected.readable_roots)
            or any(cwd.is_relative_to(root) for root in selected.denied_roots)
            or (self.execution_profile_provider is None and not cwd.is_relative_to(self.workspace_root))
        ):
            raise PermissionError(
                f"process cwd is outside the Coding sandbox workspace: {cwd}"
            )
        requested_profile = request.execution_profile
        if requested_profile is not None and not isinstance(
            requested_profile,
            EffectiveExecutionProfile,
        ):
            raise TypeError("execution profile must be an EffectiveExecutionProfile")
        return sandbox_scope_request_from_profile(
            constrain_execution_profile(
                selected,
                requested_profile or selected,
            ),
            cwd=cwd,
        )


def _coding_workspace_roots(
    workspace_root: Path,
    *,
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

    def record_diagnostic(diagnostic: SandboxDiagnostic) -> None:
        if diagnostics_service is None:
            return
        record = diagnostics_service.normalize_diagnostic(
            DiagnosticDraft(
                code=diagnostic.code,
                message=diagnostic.message,
                details={
                    "backend_id": diagnostic.backend_id,
                    "sandbox_state": "degraded",
                },
            ),
            phase="runtime",
            source="exec",
            session_id=session_id,
            level="warning",
        )
        diagnostics_service.record(record)

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
        diagnostic_sink=record_diagnostic,
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
