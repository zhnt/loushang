from __future__ import annotations

from pathlib import Path

from loushang.harness.authorization import EffectiveExecutionProfile

from .types import SandboxScopeRequest


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


__all__ = ["sandbox_scope_request_from_profile"]
