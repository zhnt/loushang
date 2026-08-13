from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from loushang.coding.sandbox import bind_coding_sandbox_runtime
from loushang.harness.authorization import EffectiveExecutionProfile
from loushang.harness.config.agent import (
    ControlConfig,
    PermissionSettings,
    SettingsManager,
)
from loushang.harness.environment import LocalHostEnvironmentProbe
from loushang.harness.permissions import PermissionProfileCeiling
from loushang.harness.sandbox import (
    SandboxBackendRegistry,
    SandboxSettings,
    SandboxUnavailableError,
)
from loushang.harness.workspace.exec import ExecService
from tests.coding.tui_support.permission_behavior import (
    PermissionBehaviorHarness,
    run_permission_behavior_matrix,
)


def test_permission_profiles_drive_real_coding_tools_through_the_gateway(
    tmp_path: Path,
) -> None:
    evidence = asyncio.run(run_permission_behavior_matrix(tmp_path / "workspace"))
    cases = {case.name: case for case in evidence.cases}

    for name in (
        "standard-read",
        "standard-write",
        "standard-test",
        "standard-git-status",
        "standard-public-http-read",
        "standard-unknown-harmless",
        "cautious-read",
    ):
        assert cases[name].outcome == "allowed"
        assert cases[name].approval_count == 0
        assert cases[name].event_types[-2:] == (
            "tool_execution_started",
            "tool_execution_completed",
        )

    expected_risks = {
        "delete": "filesystem_deletion",
        "publish": "external_publication",
        "privilege": "privilege_escalation",
        "secret": "secret_access",
        "external-effect": "external_api_mutation",
    }
    for risk, policy_code in expected_risks.items():
        standard = cases[f"standard-{risk}"]
        assert standard.outcome == "asked"
        assert standard.policy_code == policy_code
        assert standard.approval_count == 1
        assert standard.event_types[-2:] == (
            "tool_approval_requested",
            "tool_approval_resolved",
        )

        full_access = cases[f"full-access-{risk}"]
        assert full_access.outcome == "allowed"
        assert full_access.effective_profile == "full_access"
        assert full_access.policy_code == policy_code
        assert full_access.approval_count == 0
        assert full_access.event_types[-2:] == (
            "tool_execution_started",
            "tool_execution_completed",
        )

    cautious = cases["cautious-write"]
    assert cautious.outcome == "asked"
    assert cautious.policy_code == "cautious_workspace_mutation"
    assert cautious.approval_count == 1
    assert cases["managed-deny"].outcome == "denied"
    assert cases["managed-profile-ceiling"].outcome == "asked"
    assert cases["root-full-access-write"].outcome == "allowed"
    assert cases["child-delegated-ceiling"].outcome == "contained"
    assert cases["child-delegated-ceiling"].actor_id == "/root/reviewer@2"
    assert evidence.audit_events


def test_full_access_cannot_override_a_managed_policy_deny(tmp_path: Path) -> None:
    harness = PermissionBehaviorHarness(
        tmp_path / "workspace",
        initial_profile="full_access",
        blocked_tools=("bash",),
    )

    result = asyncio.run(
        harness.run(
            "managed-deny",
            tool_name="bash",
            arguments={"command": "git status --short"},
        )
    )

    assert result.outcome == "denied"
    # The legacy ``bash`` setting migrates to the stable command capability so
    # the same managed deny also covers the Windows ``shell`` tool.
    assert result.policy_code == "capability_blocked"
    assert result.approval_count == 0
    assert result.event_types == (
        "tool_action_frozen",
        "tool_policy_evaluated",
    )
    assert harness.executions == []


def test_managed_profile_ceiling_keeps_a_full_access_request_at_standard(
    tmp_path: Path,
) -> None:
    harness = PermissionBehaviorHarness(
        tmp_path / "workspace",
        initial_profile="full_access",
        ceiling=PermissionProfileCeiling(
            maximum_profile="standard",
            reason="Managed session ceiling",
        ),
    )

    result = asyncio.run(
        harness.run(
            "managed-profile-ceiling",
            tool_name="bash",
            arguments={"command": "git push origin main"},
        )
    )

    assert result.requested_profile == "full_access"
    assert result.effective_profile == "standard"
    assert result.outcome == "asked"
    assert result.policy_code == "external_publication"
    assert harness.executions == []


def test_full_access_cannot_widen_a_child_execution_ceiling(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    root = PermissionBehaviorHarness(
        workspace,
        initial_profile="full_access",
        execution_profile=EffectiveExecutionProfile(
            readable_roots=(workspace,),
            writable_roots=(workspace,),
        ),
    )
    child = PermissionBehaviorHarness(
        workspace,
        initial_profile="full_access",
        actor_id="/root/reviewer@2",
        execution_profile=EffectiveExecutionProfile(
            readable_roots=(workspace,),
            writable_roots=(),
        ),
    )

    root_result = asyncio.run(
        root.run(
            "root-write",
            tool_name="write",
            arguments={"path": "root.txt", "content": "root"},
        )
    )
    child_result = asyncio.run(
        child.run(
            "child-write",
            tool_name="write",
            arguments={"path": "child.txt", "content": "child"},
        )
    )

    assert root_result.outcome == "allowed"
    assert (workspace / "root.txt").read_text(encoding="utf-8") == "root"
    assert child_result.outcome == "contained"
    assert child_result.actor_id == "/root/reviewer@2"
    assert child_result.approval_count == 0
    assert child_result.event_types[-1] == "tool_execution_failed"
    assert not (workspace / "child.txt").exists()


def test_full_access_does_not_downgrade_a_required_sandbox(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    settings = SettingsManager(
        ControlConfig(permissions=PermissionSettings("full_access"))
    )

    assert (
        settings.get_permission_profile_snapshot().effective_profile.profile_id
        == "full_access"
    )
    with pytest.raises(SandboxUnavailableError, match="no sandbox backend"):
        bind_coding_sandbox_runtime(
            workspace_root=workspace,
            writable_workspace=True,
            settings=SandboxSettings(enabled=True, requirement="required"),
            base_exec_service=ExecService(),
            registry=SandboxBackendRegistry(),
            environment_probe=LocalHostEnvironmentProbe(
                platform_name="linux",
                architecture="x86_64",
                environ={},
            ),
        )
