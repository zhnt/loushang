from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

from loushang.ai.model import ModelSelection
from loushang.coding.ui.screen_app import ScreenCodingTuiApp
from loushang.coding.ui.screen_surfaces import ScreenSurfaceManager
from loushang.harness.approval import (
    ApprovalPermission,
    ApprovalPermissionsSnapshot,
)
from loushang.harness.permissions import (
    PermissionProfileId,
    permission_profile_snapshot,
)
from loushang.harness.session import SessionApprovalInteractionPort
from loushang.harnesstui.status.provider import StatusProvider
from loushang.harnesstui.surface.view import ScreenSurfaceView
from loushang.harnesstui.testing.scenarios.surface import surface_scenarios
from loushang.tui import ApprovalChoice, DialogSurface
from loushang.tui.playback_suite import (
    PlaybackScenarioSpec as ScreenPlaybackScenarioSpec,
)
from tests.coding.tui_support.fakes import (
    ModelPlaybackSession,
    SessionCommandPlaybackSession,
)
from tests.coding.tui_support.playback import ScreenTuiLoopPlayback
from tests.coding.tui_support.scenario_binding import (
    CODING_SCENARIO_FACTORY,
    CODING_SCENARIO_FRAME_CONTRACTS,
)


def _run_commands_info_surface() -> object:
    playback = ScreenTuiLoopPlayback(
        width=100, height=18, model_label="moonshot:test-endpoint:kimi-for-coding"
    )
    manager = _surface_manager(playback.app)

    result = playback.run(
        (0.00, "/commands terminal\r"),
        (0.01, "\r"),
        (0.03, ""),
        handle_local=manager.handle_text,
        handle_surface_intent=manager.handle_surface_intent,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    result.assert_text_contains("Commands")
    result.assert_text_contains("/terminal - Show terminal diagnostics (local)")
    result.assert_text_not_contains("/settings - Open settings (local)")
    result.assert_no_clear_screen()
    assert result.app.active_surface is None
    return result


def _run_commands_info_session_command() -> object:
    playback = ScreenTuiLoopPlayback(
        width=100, height=18, model_label="moonshot:test-endpoint:kimi-for-coding"
    )
    session = SessionCommandPlaybackSession()
    manager = _surface_manager(playback.app, session=session)

    result = playback.run(
        (0.00, "/commands name\r"),
        (0.01, "\r"),
        (0.03, ""),
        handle_local=manager.handle_text,
        handle_surface_intent=manager.handle_surface_intent,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    result.assert_text_contains("Commands")
    result.assert_text_contains("/rename <name> - Rename the current session (builtin)")
    result.assert_text_not_contains("/terminal - Show terminal diagnostics (local)")
    result.assert_no_clear_screen()
    assert session.commands == []
    assert session.prompts == []
    assert result.app.active_surface is None
    return result


def _run_command_palette_select() -> object:
    playback = ScreenTuiLoopPlayback(
        width=100, height=18, model_label="moonshot:test-endpoint:kimi-for-coding"
    )
    manager = _surface_manager(playback.app)

    result = playback.run(
        (0.00, "/command\r"),
        (0.01, "term"),
        (0.03, "\r"),
        (0.05, ""),
        handle_local=manager.handle_text,
        handle_surface_intent=manager.handle_surface_intent,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    result.assert_composer_text("/terminal ")
    result.assert_text_contains("Command selected: /terminal")
    result.assert_no_clear_screen()
    assert result.app.active_surface is None
    return result


def _run_command_palette_session_command() -> object:
    playback = ScreenTuiLoopPlayback(
        width=100, height=18, model_label="moonshot:test-endpoint:kimi-for-coding"
    )
    session = SessionCommandPlaybackSession()
    manager = _surface_manager(playback.app, session=session)

    result = playback.run(
        (0.00, "/command\r"),
        (0.01, "nam"),
        (0.03, "\r"),
        (0.05, ""),
        handle_local=manager.handle_text,
        handle_surface_intent=manager.handle_surface_intent,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    result.assert_composer_text("/rename ")
    result.assert_text_contains("Command selected: /rename")
    result.assert_no_clear_screen()
    assert session.commands == []
    assert session.prompts == []
    assert result.app.active_surface is None
    return result


def _run_settings_search() -> object:
    playback = ScreenTuiLoopPlayback(
        width=100, height=18, model_label="moonshot:test-endpoint:kimi-for-coding"
    )
    manager = _surface_manager(playback.app)

    result = playback.run(
        (0.00, "/settings\r"),
        (0.01, "zz"),
        (0.03, ""),
        handle_local=manager.handle_text,
        handle_surface_intent=manager.handle_surface_intent,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    result.assert_text_contains("Settings")
    result.assert_text_contains("Search settings...")
    result.assert_text_contains("│ zz")
    result.assert_text_contains("No matching settings")
    result.assert_text_not_contains("Status line: off")
    result.assert_no_clear_screen()
    return result


def _run_model_select() -> object:
    playback = ScreenTuiLoopPlayback(
        width=100, height=18, model_label="moonshot:test-endpoint:kimi-for-coding"
    )
    session = ModelPlaybackSession()
    manager = _surface_manager(playback.app, session=session)

    result = playback.run(
        (0.00, "/model\r"),
        (0.01, "2"),
        (0.03, ""),
        handle_local=manager.handle_text,
        handle_surface_intent=manager.handle_surface_intent,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    assert session.current_model == ModelSelection(
        endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
    )
    assert playback.app.state.model_label == "openai:test-endpoint:gpt-5.4"
    result.assert_text_contains("Select Model")
    result.assert_text_contains("Model set: openai:test-endpoint:gpt-5.4")
    result.assert_text_contains(
        "openai:test-endpoint:gpt-5.4 | repo | main | abcd | idle"
    )
    result.assert_no_clear_screen()
    assert result.app.active_surface is None
    return result


def _run_model_select_search() -> object:
    playback = ScreenTuiLoopPlayback(
        width=100, height=18, model_label="moonshot:test-endpoint:kimi-for-coding"
    )
    session = ModelPlaybackSession()
    manager = _surface_manager(playback.app, session=session)

    result = playback.run(
        (0.00, "/model\r"),
        (0.01, "gpt"),
        (0.03, "\r"),
        (0.05, ""),
        handle_local=manager.handle_text,
        handle_surface_intent=manager.handle_surface_intent,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    assert session.current_model == ModelSelection(
        endpoint_id="test-endpoint", provider="openai", model_id="gpt-5.4"
    )
    assert playback.app.state.model_label == "openai:test-endpoint:gpt-5.4"
    result.assert_text_contains("Search: gpt")
    result.assert_text_contains("Model set: openai:test-endpoint:gpt-5.4")
    result.assert_no_clear_screen()
    assert result.app.active_surface is None
    return result


def _run_approval_surface() -> object:
    return _run_approval_surface_response(
        input_text="1",
        approved=True,
        scope="once",
        expected_status="Action confirmed: write file",
    )


def _run_approval_session_surface() -> object:
    return _run_approval_surface_response(
        input_text="2",
        approved=True,
        scope="session",
        allow_session=True,
        expected_status="Action confirmed: write file",
    )


def _run_approval_reject_surface() -> object:
    return _run_approval_surface_response(
        input_text="n",
        approved=False,
        scope="once",
        expected_status="Action rejected",
        action="rm -rf -- /tmp/approval-test",
        risk="Filesystem content would be deleted or truncated",
        requester="/root/deletion_test@3",
        cwd="/repo",
        environment="local",
        action_id="delete:approval-test",
    )


def _run_approval_abort_surface() -> object:
    return _run_approval_surface_response(
        input_text="\x1b",
        approved=False,
        scope="once",
        outcome="abort",
        expected_status="Turn stopped",
        action="rm -rf -- /tmp/approval-test",
        risk="Filesystem content would be deleted or truncated",
        action_id="delete:approval-test",
    )


def _run_approval_persistent_surface() -> object:
    playback = ScreenTuiLoopPlayback(
        width=120,
        height=18,
        model_label="moonshot:test-endpoint:kimi-for-coding",
    )
    approvals: list[dict[str, object]] = []

    async def on_approval(payload: dict[str, object]) -> None:
        approvals.append(payload)

    manager = _surface_manager(playback.app, on_approval=on_approval)
    manager.open_approval(
        action="git push origin main",
        risk="Commits or refs would be published",
        action_id="push-main",
        options=(
            ApprovalChoice("allow_once", "Allow this action once", "y"),
            ApprovalChoice(
                "allow_session",
                "Allow non-force pushes for this session",
                "s",
                "session",
            ),
            ApprovalChoice(
                "allow_project",
                "Always allow non-force pushes in this project",
                "p",
                "persistent",
            ),
            ApprovalChoice(
                "deny",
                "Deny and let the agent continue",
                "n",
                "deny",
            ),
        ),
    )
    result = playback.run(
        (0.00, "p"),
        (0.02, ""),
        handle_surface_intent=manager.handle_surface_intent,
    )

    result.assert_exit_code(0)
    assert approvals[0]["outcome"] == "allow_project"
    result.assert_text_contains("Always allow non-force pushes in this project")
    result.assert_text_contains("Action confirmed")
    result.assert_no_clear_screen()
    return result


def _run_permissions_reopen_and_revoke_surface() -> object:
    playback = ScreenTuiLoopPlayback(
        width=100, height=18, model_label="moonshot:test-endpoint:kimi-for-coding"
    )
    permission_actions: list[str] = []
    approvals: list[dict[str, object]] = []
    pending = True
    granted = True
    manager: ScreenSurfaceManager

    class Session:
        def permissions_snapshot(self) -> ApprovalPermissionsSnapshot:
            return ApprovalPermissionsSnapshot(
                pending=(
                    ApprovalPermission(
                        kind="pending",
                        permission_id="delete-build",
                        actor_id="/root/reviewer#2",
                        capability="bash",
                        summary="Filesystem content would be deleted",
                    ),
                )
                if pending
                else (),
                grants=(
                    ApprovalPermission(
                        kind="session",
                        permission_id="grant-push",
                        actor_id="/root/implementer#1",
                        capability="git.publish_refs",
                        summary="Publish non-force refs to origin",
                    ),
                )
                if granted
                else (),
            )

        def permission_profile_snapshot(self):
            return permission_profile_snapshot("standard")

        async def apply_permission_action(self, action: str) -> bool:
            nonlocal granted
            permission_actions.append(action)
            if action == "reopen:delete-build" and pending:
                manager.open_approval(
                    action="delete build",
                    risk="Filesystem content would be deleted",
                    requester="/root/reviewer#2",
                    action_id="delete-build",
                )
                return True
            if action == "revoke:grant-push" and granted:
                granted = False
                return True
            return False

    async def on_approval(payload: dict[str, object]) -> None:
        nonlocal pending
        approvals.append(payload)
        pending = False

    manager = _surface_manager(
        playback.app,
        session=Session(),
        on_approval=on_approval,
    )
    manager.open_approval(
        action="delete build",
        risk="Filesystem content would be deleted",
        requester="/root/reviewer#2",
        action_id="delete-build",
    )
    # A presenter may be withdrawn while the broker still owns a pending
    # request (for example during UI reattachment). User Escape is not that
    # operation: it is an explicit denial.
    manager.dismiss_approval("delete-build")
    result = playback.run(
        (0.00, "/permissions\r"),
        (0.02, "\t"),
        (0.04, "\r"),
        (0.07, "y"),
        (0.10, "/permissions\r"),
        (0.12, "\t"),
        (0.14, "\r"),
        (0.17, ""),
        handle_local=manager.handle_text,
        handle_surface_intent=manager.handle_surface_intent,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    assert permission_actions == [
        "reopen:delete-build",
        "revoke:grant-push",
    ]
    assert approvals == [
        {
            "action_id": "delete-build",
            "action": "delete build",
            "approved": True,
            "outcome": "allow_once",
            "scope": "once",
            "raw_note": "delete-build",
        }
    ]
    result.assert_text_contains("Permissions")
    result.assert_text_contains("Approval")
    result.assert_text_contains("/root/reviewer#2")
    result.assert_text_contains("/root/implementer#1")
    result.assert_text_contains("Publish non-force refs to origin")
    result.assert_no_clear_screen()
    return result


class _PermissionProfilePlaybackSession:
    def __init__(self) -> None:
        self.current: PermissionProfileId = "standard"
        self.actions: list[str] = []

    def permissions_snapshot(self) -> ApprovalPermissionsSnapshot:
        return ApprovalPermissionsSnapshot()

    def permission_profile_snapshot(self):
        return permission_profile_snapshot(self.current)

    async def apply_permission_action(self, action: str) -> bool:
        prefix, scope, profile_id = action.split(":", 2)
        if (
            prefix != "set-profile"
            or scope not in {"session", "project", "user"}
            or profile_id not in {"cautious", "standard", "full_access"}
        ):
            return False
        self.actions.append(action)
        self.current = cast(PermissionProfileId, profile_id)
        return True


def _run_permissions_mode_surface() -> object:
    playback = ScreenTuiLoopPlayback(
        width=120, height=20, model_label="moonshot:test-endpoint:kimi-for-coding"
    )
    session = _PermissionProfilePlaybackSession()
    manager = _surface_manager(playback.app, session=session)

    result = playback.run(
        (0.00, "/permissions\r"),
        (0.02, "p"),
        (0.04, "\x1b[B"),
        (0.06, "\r"),
        (0.09, "\x1b"),
        (0.11, ""),
        handle_local=manager.handle_text,
        handle_surface_intent=manager.handle_surface_intent,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    assert session.actions == ["set-profile:project:cautious"]
    assert result.app.state.permission_profile == "cautious"
    result.assert_text_contains("Standard")
    result.assert_text_contains("Cautious (current)")
    result.assert_text_contains("Permissions updated to Cautious (project).")
    result.assert_no_clear_screen()
    return result


def _run_permissions_full_access_confirmation() -> object:
    playback = ScreenTuiLoopPlayback(
        width=100, height=20, model_label="moonshot:test-endpoint:kimi-for-coding"
    )
    session = _PermissionProfilePlaybackSession()
    manager = _surface_manager(playback.app, session=session)

    result = playback.run(
        (0.00, "/permissions\r"),
        (0.02, "\x1b[B"),
        (0.04, "\x1b[B"),
        (0.06, "\r"),
        (0.08, "\r"),
        (0.11, "\x1b"),
        (0.13, ""),
        handle_local=manager.handle_text,
        handle_surface_intent=manager.handle_surface_intent,
        is_local_command=manager.is_local_command,
    )

    result.assert_exit_code(0)
    assert session.actions == ["set-profile:session:full_access"]
    assert result.app.state.permission_profile == "full_access"
    result.assert_text_contains("Enable Full Access?")
    result.assert_text_contains("Full Access (current)")
    result.assert_no_clear_screen()
    return result


def _run_approval_surface_response(
    *,
    input_text: str,
    approved: bool,
    scope: str,
    outcome: str | None = None,
    expected_status: str,
    allow_session: bool = False,
    action: str = "write file",
    risk: str = "Will modify /repo/app.py",
    requester: str = "",
    cwd: str = "",
    environment: str = "",
    action_id: str = "write:app.py",
) -> object:
    playback = ScreenTuiLoopPlayback(
        width=100, height=18, model_label="moonshot:test-endpoint:kimi-for-coding"
    )
    approvals: list[dict[str, object]] = []

    async def on_approval(payload: dict[str, object]) -> None:
        approvals.append(payload)

    manager = _surface_manager(playback.app, on_approval=on_approval)
    manager.open_approval(
        action=action,
        risk=risk,
        requester=requester,
        cwd=cwd,
        environment=environment,
        action_id=action_id,
        allow_session=allow_session,
    )

    result = playback.run(
        (0.00, input_text),
        (0.02, ""),
        handle_surface_intent=manager.handle_surface_intent,
    )

    result.assert_exit_code(0)
    assert approvals == [
        {
            "action_id": action_id,
            "action": action,
            "approved": approved,
            "outcome": outcome
            or (
                "allow_session"
                if approved and scope == "session"
                else "allow_once"
                if approved
                else "deny"
            ),
            "scope": scope,
            "raw_note": action_id,
        }
    ]
    result.assert_text_contains("Approval")
    result.assert_text_contains(action)
    result.assert_text_contains(risk)
    result.assert_text_contains(expected_status)
    result.assert_no_clear_screen()
    assert result.app.active_surface is None
    return result


def _run_dialog_surface() -> object:
    playback = ScreenTuiLoopPlayback(
        width=100, height=18, model_label="moonshot:test-endpoint:kimi-for-coding"
    )
    manager = _surface_manager(playback.app)
    playback.app.active_surface = ScreenSurfaceView(
        title="Confirm",
        purpose="dialog",
        content=DialogSurface(title="Confirm", message="Proceed?"),
        footer="",
        presentation="bottom-exclusive",
    )

    result = playback.run(
        (0.00, "\r"),
        (0.02, ""),
        handle_surface_intent=manager.handle_surface_intent,
    )

    result.assert_exit_code(0)
    result.assert_text_contains("Confirm")
    result.assert_text_contains("Proceed?")
    result.assert_no_clear_screen()
    assert result.app.active_surface is None
    return result


def _surface_manager(
    app: ScreenCodingTuiApp,
    *,
    session: object | None = None,
    on_approval: Callable[[dict[str, Any]], Awaitable[bool | None]] | None = None,
) -> ScreenSurfaceManager:
    bound_session = object() if session is None else session
    return ScreenSurfaceManager(
        app=app,
        session=bound_session,
        status_provider=_status_provider(app),
        on_approval=on_approval,
        approval_interaction_provider=(
            (lambda: cast(SessionApprovalInteractionPort, bound_session))
            if session is not None
            else None
        ),
    )


def _status_provider(app: object) -> StatusProvider:
    state = getattr(app, "state")
    return StatusProvider(
        model_label=state.model_label,
        cwd=state.cwd,
        branch=state.branch,
        session_label=lambda: state.session_label,
        thinking_level=lambda: None,
        running=lambda: state.running,
        permission_profile=lambda: state.permission_profile,
    )


_NEUTRAL_SURFACE_SCENARIOS = surface_scenarios(
    CODING_SCENARIO_FACTORY,
    CODING_SCENARIO_FRAME_CONTRACTS,
)

SURFACE_SCENARIOS = (
    *_NEUTRAL_SURFACE_SCENARIOS[:1],
    ScreenPlaybackScenarioSpec(
        name="command-palette-select",
        description="Search the screen command palette and insert the selected command.",
        run=_run_command_palette_select,
        tags=("command", "surface"),
    ),
    ScreenPlaybackScenarioSpec(
        name="command-palette-session-command",
        description="Select a session command from the screen command palette without executing it.",
        run=_run_command_palette_session_command,
        tags=("command", "surface", "session"),
    ),
    ScreenPlaybackScenarioSpec(
        name="commands-info-surface",
        description="Open and close the screen commands info surface through the local command path.",
        run=_run_commands_info_surface,
        tags=("command", "surface"),
    ),
    ScreenPlaybackScenarioSpec(
        name="commands-info-session-command",
        description="Show session commands in the screen commands info surface without executing them.",
        run=_run_commands_info_session_command,
        tags=("command", "surface", "session"),
    ),
    ScreenPlaybackScenarioSpec(
        name="settings-search",
        description="Search the settings page opened through the screen command path.",
        run=_run_settings_search,
    ),
    ScreenPlaybackScenarioSpec(
        name="model-select",
        description="Open the screen model selector and switch models without clearing the screen.",
        run=_run_model_select,
    ),
    ScreenPlaybackScenarioSpec(
        name="model-select-search",
        description="Search the screen model selector and select the filtered model.",
        run=_run_model_select_search,
    ),
    ScreenPlaybackScenarioSpec(
        name="approval-surface",
        description="Approve an active screen approval surface and verify its callback payload.",
        run=_run_approval_surface,
    ),
    ScreenPlaybackScenarioSpec(
        name="approval-session-surface",
        description="Retain a Policy-admitted approval for the active session.",
        run=_run_approval_session_surface,
    ),
    ScreenPlaybackScenarioSpec(
        name="approval-reject-surface",
        description="Reject an active screen approval surface and verify its callback payload.",
        run=_run_approval_reject_surface,
    ),
    ScreenPlaybackScenarioSpec(
        name="approval-abort-surface",
        description="Escape an approval and abort the active turn.",
        run=_run_approval_abort_surface,
    ),
    ScreenPlaybackScenarioSpec(
        name="approval-persistent-surface",
        description="Persist a Policy-generated project permission.",
        run=_run_approval_persistent_surface,
    ),
    ScreenPlaybackScenarioSpec(
        name="permissions-reopen-revoke-surface",
        description="Reopen a pending approval and revoke a retained session grant.",
        run=_run_permissions_reopen_and_revoke_surface,
        tags=("approval", "surface"),
    ),
    ScreenPlaybackScenarioSpec(
        name="permissions-mode-surface",
        description="Switch a permission mode at project scope.",
        run=_run_permissions_mode_surface,
        tags=("approval", "permissions", "surface"),
    ),
    ScreenPlaybackScenarioSpec(
        name="permissions-full-access-confirmation",
        description="Require explicit confirmation before enabling Full Access.",
        run=_run_permissions_full_access_confirmation,
        tags=("approval", "permissions", "surface"),
    ),
    ScreenPlaybackScenarioSpec(
        name="dialog-surface",
        description="Confirm an active screen dialog surface without repainting the screen.",
        run=_run_dialog_surface,
    ),
    *_NEUTRAL_SURFACE_SCENARIOS[1:],
)


__all__ = ["SURFACE_SCENARIOS"]
