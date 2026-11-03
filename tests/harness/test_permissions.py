from __future__ import annotations

import asyncio
from dataclasses import dataclass

import pytest

from loushang.harness.config.agent import SettingsManager
from loushang.harness.permissions import (
    PermissionProfileCeiling,
    PermissionProfilePolicyEvaluator,
    permission_profile_snapshot,
)
from loushang.harness.policy import (
    PolicyDecision,
    ToolPolicySubject,
)
from loushang.harness.policy.engine import PolicyEngine
from loushang.harness.tools.workspace.factory import workspace_tool_runtime_settings


def test_native_policy_fingerprint_reads_current_settings_inputs(tmp_path):
    settings = SettingsManager(
        global_settings_path=tmp_path / "user.json", project_settings_path=tmp_path / "project.json",
    )
    policy = workspace_tool_runtime_settings(settings).policy_engine
    assert isinstance(policy, PermissionProfilePolicyEvaluator)
    initial = policy.configuration_fingerprint()
    assert len(initial) == 64
    assert workspace_tool_runtime_settings(settings).policy_engine.configuration_fingerprint() == initial
    settings.set_permission_profile("full_access", scope="session")
    assert policy.configuration_fingerprint() != initial
    settings.set_permission_profile("standard", scope="session")
    assert policy.configuration_fingerprint() == initial
    settings.update_settings(scope="session", tools={"blocked_tools": ["bash"]})
    fresh = workspace_tool_runtime_settings(settings).policy_engine
    assert fresh.configuration_fingerprint() != initial
    assert policy.configuration_fingerprint() == fresh.configuration_fingerprint()
    assert asyncio.run(policy.evaluate(ToolPolicySubject(tool_name="bash", arguments={}))).disposition == "deny"


def test_policy_fingerprint_preserves_managed_rule_inputs():
    first = PolicyEngine(blocked_tools=("bash",))
    assert first.configuration_fingerprint() == PolicyEngine(blocked_tools=("bash",)).configuration_fingerprint()
    assert first.configuration_fingerprint() != PolicyEngine(ask_tools=("bash",)).configuration_fingerprint()


@pytest.mark.parametrize("scope", ["session", "project", "user"])
def test_interactive_profile_selection_applies_now_and_saves_only_its_default(tmp_path, scope):
    import json

    from loushang.harness.events import PermissionProfileChanged
    from loushang.harness.policy import (
        build_tool_policy_subject,
        normalize_command_subject,
    )
    from loushang.harness.session.approval_interaction import (
        AgentSessionApprovalRuntime,
    )

    user_path = tmp_path / "user.json"
    project_path = tmp_path / "project.json"
    settings = SettingsManager(global_settings_path=user_path, project_settings_path=project_path)
    settings.set_permission_profile("cautious", scope="project")
    settings.set_permission_profile("standard", scope="session")
    live_policy = workspace_tool_runtime_settings(settings).policy_engine
    subject = build_tool_policy_subject(
        tool_name="bash", arguments={"command": "git push origin main"},
        command=normalize_command_subject(("git", "push", "origin", "main")),
    )
    events = []

    async def dispatch(event):
        events.append(event)

    runtime = AgentSessionApprovalRuntime(
        resolver=None,
        get_permission_profile_snapshot=settings.get_permission_profile_snapshot,
        set_permission_profile=settings.set_permission_profile,
        dispatch_event=dispatch,
        abort=lambda: None,
    )

    async def run():
        assert (await live_policy.evaluate(subject)).disposition == "ask"
        assert await runtime.apply_permission_action(f"set-profile:{scope}:full_access")
        # The already-built Policy and Tool registry observe this change.
        assert (await live_policy.evaluate(subject)).disposition == "allow"

    asyncio.run(run())
    assert settings.get_permission_profile_id() == "full_access"
    assert events == [PermissionProfileChanged(
        previous_profile_id="standard", requested_profile_id="full_access",
        effective_profile_id="full_access", scope=scope,
    )]
    assert project_path.exists()
    assert json.loads(project_path.read_text())["permissions"]["profile"] == (
        "full_access" if scope == "project" else "cautious"
    )
    if scope == "user":
        assert json.loads(user_path.read_text())["permissions"]["profile"] == "full_access"
        # A new project inherits the user default; an existing project keeps
        # its explicit preference. Neither setting is silently erased.
        assert SettingsManager(global_settings_path=user_path).get_permission_profile_id() == "full_access"
    else:
        assert not user_path.exists()
    reloaded = SettingsManager(global_settings_path=user_path, project_settings_path=project_path)
    assert reloaded.get_permission_profile_id() == (
        "full_access" if scope == "project" else "cautious"
    )


def test_failed_default_save_does_not_enable_full_for_the_session(tmp_path, monkeypatch):
    from loushang.harness.config.store import JsonConfigStore
    from loushang.harness.session.approval_interaction import (
        AgentSessionApprovalRuntime,
    )

    settings = SettingsManager(global_settings_path=tmp_path / "user.json")
    events = []

    async def dispatch(event):
        events.append(event)

    def fail_save(*_args, **_kwargs):
        raise OSError("Cannot persist settings")

    monkeypatch.setattr(JsonConfigStore, "save", fail_save)
    runtime = AgentSessionApprovalRuntime(
        resolver=None,
        get_permission_profile_snapshot=settings.get_permission_profile_snapshot,
        set_permission_profile=settings.set_permission_profile,
        dispatch_event=dispatch, abort=lambda: None,
    )
    with pytest.raises(OSError, match="Cannot persist"):
        asyncio.run(runtime.apply_permission_action("set-profile:user:full_access"))
    assert settings.get_permission_profile_id() == "standard"
    assert events == []


def test_saving_a_lower_default_also_removes_the_current_full_override(tmp_path):
    from loushang.harness.session.approval_interaction import (
        AgentSessionApprovalRuntime,
    )

    settings = SettingsManager(global_settings_path=tmp_path / "user.json")
    settings.set_permission_profile("full_access", scope="session")
    live_policy = workspace_tool_runtime_settings(settings).policy_engine
    subject = ToolPolicySubject(tool_name="write", arguments={"path": "notes.txt"})

    async def dispatch(_event):
        pass

    interaction = AgentSessionApprovalRuntime(
        resolver=None, get_permission_profile_snapshot=settings.get_permission_profile_snapshot,
        set_permission_profile=settings.set_permission_profile,
        dispatch_event=dispatch, abort=lambda: None,
    )

    async def run():
        assert (await live_policy.evaluate(subject)).disposition == "allow"
        assert await interaction.apply_permission_action("set-profile:user:cautious")
        assert (await live_policy.evaluate(subject)).disposition == "ask"

    asyncio.run(run())


@dataclass(frozen=True)
class _Policy:
    decision: PolicyDecision

    def evaluate(self, subject: object) -> PolicyDecision:
        del subject
        return self.decision


def _evaluate(
    *,
    profile: str,
    decision: PolicyDecision,
    tool_name: str = "bash",
    ceiling: PermissionProfileCeiling | None = None,
) -> PolicyDecision:
    evaluator = PermissionProfilePolicyEvaluator(
        _Policy(decision),
        profile_provider=lambda: profile,  # type: ignore[arg-type]
        ceiling_provider=lambda: ceiling or PermissionProfileCeiling(),
    )
    return asyncio.run(
        evaluator.evaluate(
            ToolPolicySubject(tool_name=tool_name, arguments={})
        )
    )


def test_permission_profile_snapshot_applies_the_managed_ceiling() -> None:
    snapshot = permission_profile_snapshot(
        "full_access",
        PermissionProfileCeiling(
            maximum_profile="standard",
            reason="Managed environment limits this session.",
        ),
    )

    assert snapshot.requested_profile_id == "full_access"
    assert snapshot.effective_profile.profile_id == "standard"
    full_access = next(
        option
        for option in snapshot.options
        if option.profile.profile_id == "full_access"
    )
    assert full_access.enabled is False
    assert full_access.disabled_reason == "Managed environment limits this session."


def test_standard_profile_preserves_policy_decisions() -> None:
    ask = PolicyDecision.ask("Publish refs", code="git_publish")

    assert _evaluate(profile="standard", decision=ask) == ask


def test_full_access_skips_optional_approval_but_never_managed_deny() -> None:
    assert _evaluate(
        profile="full_access",
        decision=PolicyDecision.ask("Delete files", code="delete"),
    ) == PolicyDecision(disposition="allow", code="delete")

    deny = PolicyDecision.deny("Managed deny", code="managed_deny")
    assert _evaluate(profile="full_access", decision=deny) == deny


def test_managed_ceiling_makes_a_full_access_request_effectively_standard() -> None:
    ask = PolicyDecision.ask("Publish refs", code="git_publish")

    assert _evaluate(
        profile="full_access",
        decision=ask,
        ceiling=PermissionProfileCeiling(maximum_profile="standard"),
    ) == ask


@pytest.mark.parametrize("tool_name", ["write", "edit"])
def test_cautious_profile_asks_before_direct_workspace_mutations(
    tool_name: str,
) -> None:
    decision = _evaluate(
        profile="cautious",
        decision=PolicyDecision.allow(),
        tool_name=tool_name,
    )

    assert decision.disposition == "ask"
    assert decision.code == "cautious_workspace_mutation"


def test_cautious_profile_does_not_add_prompts_to_read_only_tools() -> None:
    assert _evaluate(
        profile="cautious",
        decision=PolicyDecision.allow(),
        tool_name="read",
    ) == PolicyDecision.allow()
