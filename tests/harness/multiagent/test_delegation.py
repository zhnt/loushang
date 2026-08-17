from __future__ import annotations

from pathlib import Path

import pytest

from loushang.harness.authorization import EffectiveExecutionProfile
from loushang.harness.multiagent import (
    AgentPath,
    AgentRef,
    DelegatedExecutionProfile,
)


def test_delegated_execution_profile_freezes_one_child_incarnation(
    tmp_path: Path,
) -> None:
    actor_ref = AgentRef(AgentPath.root().child("reviewer"), 2)
    ceiling = EffectiveExecutionProfile(
        readable_roots=(tmp_path,),
        network="restricted",
    )

    profile = DelegatedExecutionProfile(
        actor_ref=actor_ref,
        allowed_tools=("read", "grep"),
        execution_profile_ceiling=ceiling,
        approval_actor_id=str(actor_ref),
        workspace_ref="workspace:reviewer-2",
    )

    assert profile.allowed_tools == ("read", "grep")
    assert profile.execution_profile_ceiling is ceiling
    assert profile.approval_actor_id == "/root/reviewer@2"


def test_delegated_execution_profile_rejects_widening_identity_or_tools(
    tmp_path: Path,
) -> None:
    actor_ref = AgentRef(AgentPath.root().child("reviewer"), 1)
    ceiling = EffectiveExecutionProfile(readable_roots=(tmp_path,))

    with pytest.raises(ValueError, match="approval_actor_id"):
        DelegatedExecutionProfile(
            actor_ref=actor_ref,
            allowed_tools=("read",),
            execution_profile_ceiling=ceiling,
            approval_actor_id="/root/other@1",
        )
    with pytest.raises(ValueError, match="duplicates"):
        DelegatedExecutionProfile(
            actor_ref=actor_ref,
            allowed_tools=("read", "read"),
            execution_profile_ceiling=ceiling,
            approval_actor_id=str(actor_ref),
        )
