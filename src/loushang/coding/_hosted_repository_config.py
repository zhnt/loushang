"""Trusted server configuration, not a client task-upload API."""

from __future__ import annotations

import inspect
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from ._hosted_goal_config import CodingHostedGoalV1
from .adapters._goal_repository import RepositoryProfile
from .adapters._goal_repository_hosted_task import HostedRepositoryTask


@dataclass(frozen=True, slots=True)
class CodingHostedRepositoryGoalV1(CodingHostedGoalV1):
    """Reviewer is trusted bounded async pure assessment: no I/O or owned resources.

    It receives isolated JSON values and returns decision/reason/coverage/findings.
    Normal return, exception and completed cancellation leave no retained effects.
    This is a host code contract, not a sandbox for an untrusted callback.
    """

    manifest: Path = Path()
    expected_sha256: str = ""
    reviewer_id: str = ""
    reviewer: Callable[[Mapping], Awaitable[dict]] | None = None
    max_advances: int = 6

    def __post_init__(self):
        super(CodingHostedRepositoryGoalV1, self).__post_init__()
        if (
            self.max_advances > 6
            or not self.reviewer_id.strip()
            or not inspect.iscoroutinefunction(self.reviewer)
        ):
            raise ValueError("bounded async reviewer and at most six commands required")
        if not isinstance(self.manifest, Path) or not self.manifest.is_absolute():
            raise ValueError("explicit manifest required")

    def prepare(self, launch):
        self.validate_roots(launch)
        task = HostedRepositoryTask(self.manifest, self.expected_sha256)
        config = task.config
        temporary = Path(config["temporary_root"]).resolve()
        roots = (
            self.workspace,
            self.data_root,
            launch.application_root,
            task.path.parent,
            temporary,
            *(s.session_dir for s in launch.scopes),
        )
        if task.root != self.workspace or any(
            a.is_relative_to(b) or b.is_relative_to(a)
            for i, a in enumerate(roots)
            for b in roots[i + 1 :]
        ):
            raise ValueError("repository task and storage roots must not overlap")
        if Path(config["python"]).resolve() != Path(sys.executable).resolve():
            raise ValueError("task interpreter must be the trusted host interpreter")
        if not temporary.is_dir():
            raise ValueError("dedicated check temporary root required")
        # Compile the protected Method using the original domain compiler.
        import json
        from types import SimpleNamespace

        from loushang.method.runtime import (
            MethodDomainProfile,
            MethodDomainRequest,
            MethodDomainRuntime,
            MethodPolicy,
        )
        from loushang.method.types import MethodDescriptor

        descriptor = MethodDescriptor(
            **json.loads((task.path.parent / "method.json").read_bytes())
        )
        turns = MethodDomainRuntime(
            profile=MethodDomainProfile(domain="coding"),
            method_loader=SimpleNamespace(discover_methods=lambda cwd: [descriptor]),
        ).prepare_turns(
            MethodDomainRequest(
                "Validate protected Method",
                task.root,
                method_policy=MethodPolicy.explicit(descriptor.id),
            )
        )
        from loushang.harnesswork.integrations.session import (
            project_prepared_session_work_turns,
        )

        prepared = project_prepared_session_work_turns(
            turns, images=None, follow_up_messages=()
        )
        if (
            len(prepared) != 1
            or prepared[0].step_id != "repair"
            or prepared[0].planned_constraint
            or prepared[0].audit_policy
        ):
            raise ValueError("hosted repository requires the single repair Method")
        return RepositoryProfile(task)
