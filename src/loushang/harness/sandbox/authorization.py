from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from loushang.harness.authorization import (
    EffectiveExecutionProfile,
    ExecutionProfileProvider,
    constrain_execution_profile,
    select_execution_profile,
)
from loushang.harness.authorization.execution_profile import execution_path_is_covered
from loushang.harness.workspace.exec import ExecRequest

from .types import SandboxScopeRequest


class WorkspaceSandboxScopePolicy:
    """Turn a Product's workspace roots into a bounded process scope."""

    __slots__ = ()
    workspace_root: Path
    writable_workspace: bool
    _readable_roots: tuple[Path, ...]
    _writable_roots: tuple[Path, ...]
    execution_profile: EffectiveExecutionProfile | None
    execution_profile_provider: ExecutionProfileProvider | None
    _product_label: ClassVar[str]

    @staticmethod
    def _workspace_roots(
        workspace_root: Path, writable: bool
    ) -> tuple[tuple[Path, ...], tuple[Path, ...]]:
        raise NotImplementedError

    def __post_init__(self) -> None:
        if type(self.writable_workspace) is not bool:
            raise TypeError("writable_workspace must be a bool")
        root = Path(self.workspace_root).expanduser().resolve(strict=False)
        if not root.is_dir():
            raise NotADirectoryError(20, "Not a directory", str(root))
        object.__setattr__(self, "workspace_root", root)
        readable, writable = self._workspace_roots(root, self.writable_workspace)
        object.__setattr__(self, "_readable_roots", readable)
        object.__setattr__(self, "_writable_roots", writable)
        workspace_profile = EffectiveExecutionProfile(
            readable_roots=readable, writable_roots=writable
        )
        ceiling = self.execution_profile or workspace_profile
        if not isinstance(ceiling, EffectiveExecutionProfile):
            raise TypeError("execution profile must be an EffectiveExecutionProfile")
        if self.execution_profile_provider is None:
            ceiling = constrain_execution_profile(workspace_profile, ceiling)
        object.__setattr__(self, "execution_profile", ceiling)

    def __call__(self, request: ExecRequest) -> SandboxScopeRequest:
        return authorize_workspace_sandbox_scope(
            request,
            workspace_root=self.workspace_root,
            execution_profile=self.execution_profile,
            execution_profile_provider=self.execution_profile_provider,
            product_label=self._product_label,
        )


def sandbox_scope_request_from_profile(
    profile: EffectiveExecutionProfile,
    *,
    cwd: str | Path,
) -> SandboxScopeRequest:
    """Project authorized execution authority into an enforcing sandbox scope."""

    return SandboxScopeRequest(
        cwd=Path(cwd),
        readable_roots=profile.readable_roots,
        writable_roots=profile.writable_roots,
        denied_roots=profile.denied_roots,
        network=profile.network,
    )


def authorize_workspace_sandbox_scope(
    request: ExecRequest,
    *,
    workspace_root: Path,
    execution_profile: EffectiveExecutionProfile | None,
    execution_profile_provider: ExecutionProfileProvider | None,
    product_label: str,
) -> SandboxScopeRequest:
    """Select current execution authority and project the requested process scope."""
    if request.cwd is None:
        raise ValueError(f"{product_label} sandbox requires a materialized working directory")
    cwd = Path(request.cwd).expanduser().resolve(strict=False)
    assert execution_profile is not None
    selected = select_execution_profile(execution_profile, execution_profile_provider)
    if (
        not execution_path_is_covered(cwd, selected.readable_roots)
        or execution_path_is_covered(cwd, selected.denied_roots)
        or (execution_profile_provider is None and not cwd.is_relative_to(workspace_root))
    ):
        raise PermissionError(
            f"process cwd is outside the {product_label} sandbox workspace: {cwd}"
        )
    requested_profile = request.execution_profile
    if requested_profile is not None and not isinstance(
        requested_profile, EffectiveExecutionProfile
    ):
        raise TypeError("execution profile must be an EffectiveExecutionProfile")
    return sandbox_scope_request_from_profile(
        constrain_execution_profile(selected, requested_profile or selected), cwd=cwd
    )


__all__ = ["sandbox_scope_request_from_profile"]
