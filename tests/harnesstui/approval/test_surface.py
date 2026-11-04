from __future__ import annotations

from loushang.harness.approval import (
    ApprovalPermission,
    ApprovalPermissionsSnapshot,
)
from loushang.harness.permissions import (
    PermissionProfileCeiling,
    permission_profile_snapshot,
)
from loushang.harnesstui.approval import build_permissions_surface_view
from loushang.tui import (
    InputEvent,
    InputIntent,
    RenderConstraints,
    strip_control_sequences,
)


def test_permissions_surface_selects_scoped_modes_and_confirms_full_access() -> None:
    view = build_permissions_surface_view(
        ApprovalPermissionsSnapshot(),
        profile_snapshot=permission_profile_snapshot("standard"),
    )

    rendered = "\n".join(
        line.text
        for line in view.render(RenderConstraints(width=90, max_height=24)).lines
    )
    assert "Standard  ✓ Current" in rendered
    assert "Cautious" in rendered
    assert "Full Access" in rendered

    assert view.handle_input(InputEvent(kind="text", text="p")) == InputIntent(
        kind="consumed",
        note="permission_scope",
    )
    view.handle_input(InputEvent(kind="key", key="down"))
    assert view.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="permission_profile_action",
        text="set-profile:project:cautious",
    )

    view.handle_input(InputEvent(kind="key", key="down"))
    assert view.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="consumed",
        note="permission_confirmation",
    )
    confirmation = "\n".join(
        line.text
        for line in view.render(RenderConstraints(width=90, max_height=24)).lines
    )
    assert "Enable Full Access?" in confirmation
    assert "Managed denies" in confirmation
    assert "this session now and save as the project default" in confirmation
    assert view.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="permission_profile_action",
        text="set-profile:project:full_access",
    )


def test_permissions_colors_mark_navigation_and_reserve_red_for_confirmation() -> None:
    view = build_permissions_surface_view(
        ApprovalPermissionsSnapshot(),
        profile_snapshot=permission_profile_snapshot("standard"),
    )
    constraints = RenderConstraints(width=90, max_height=24)

    view.handle_input(InputEvent(kind="key", key="down"))
    modes = view.content.render(constraints).lines
    plain = tuple(strip_control_sequences(line.text) for line in modes)
    assert plain[0].startswith("[Mode]   Retained")
    assert "[Session]" in plain[3]
    assert "  1. Standard  ✓ Current" in plain
    selected = next(line.text for line in modes if "› 2. Cautious" in line.text)
    assert "\x1b[1;36m" in selected
    assert all("\x1b[31m" not in line.text and "\x1b[32m" not in line.text for line in modes)

    view.handle_input(InputEvent(kind="key", key="down"))
    modes = view.content.render(constraints).lines
    full_access = next(line.text for line in modes if "› 3. Full Access" in line.text)
    assert "\x1b[1;36m" in full_access
    assert "\x1b[31m" not in full_access
    view.handle_input(InputEvent(kind="key", key="enter"))
    confirmation = view.content.render(constraints).lines
    assert any("\x1b[1;31m" in line.text for line in confirmation)


def test_saving_full_as_user_default_confirms_even_when_session_is_already_full():
    view = build_permissions_surface_view(
        ApprovalPermissionsSnapshot(),
        profile_snapshot=permission_profile_snapshot("full_access"),
    )
    view.handle_input(InputEvent(kind="text", text="u"))
    assert view.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="consumed", note="permission_confirmation",
    )
    rendered = "\n".join(
        line.text for line in view.render(RenderConstraints(width=90, max_height=24)).lines
    )
    assert "this session now and save as the user default" in rendered
    assert view.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="permission_profile_action", text="set-profile:user:full_access",
    )


def test_permissions_surface_disables_modes_above_managed_ceiling() -> None:
    view = build_permissions_surface_view(
        ApprovalPermissionsSnapshot(),
        profile_snapshot=permission_profile_snapshot(
            "standard",
            PermissionProfileCeiling(
                maximum_profile="standard",
                reason="Managed by your organization.",
            ),
        ),
    )

    view.handle_input(InputEvent(kind="key", key="end"))
    assert view.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="consumed",
        note="permission_mode_disabled",
    )
    rendered = "\n".join(
        line.text
        for line in view.render(RenderConstraints(width=90, max_height=24)).lines
    )
    assert "Managed by your organization." in rendered


def test_permissions_surface_reopens_pending_and_revokes_grants() -> None:
    view = build_permissions_surface_view(
        ApprovalPermissionsSnapshot(
            pending=(
                ApprovalPermission(
                    kind="pending",
                    permission_id="approval-1",
                    actor_id="root",
                    capability="bash",
                    summary="Filesystem content would be deleted",
                ),
            ),
            grants=(
                ApprovalPermission(
                    kind="session",
                    permission_id="grant-1",
                    actor_id="root",
                    capability="git.publish_refs",
                    summary="Publish non-force refs to origin",
                ),
            ),
            project_rules=(
                ApprovalPermission(
                    kind="project",
                    permission_id="policy-project-1",
                    actor_id="policy",
                    capability="git.publish_refs",
                    summary="Publish non-force refs to origin",
                ),
            ),
            user_rules=(
                ApprovalPermission(
                    kind="user",
                    permission_id="policy-user-1",
                    actor_id="policy",
                    capability="network.connect",
                    summary="Connect to api.example.com",
                ),
            ),
        )
    )

    assert view.purpose == "permissions"
    assert view.title == "Permissions"
    assert view.content.items[0].description == (
        "Root · Filesystem content would be deleted"
    )
    assert view.content.items[1].description == (
        "Root · Publish non-force refs to origin"
    )
    assert view.handle_input(InputEvent(kind="key", key="tab")) == InputIntent(
        kind="consumed",
        note="permissions_tab",
    )
    assert view.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="select",
        text="reopen:approval-1",
    )
    view.handle_input(InputEvent(kind="key", key="down"))
    assert view.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="select",
        text="revoke:grant-1",
    )
    view.handle_input(InputEvent(kind="key", key="down"))
    assert view.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="select",
        text="revoke-policy:policy-project-1",
    )
    view.handle_input(InputEvent(kind="key", key="down"))
    assert view.handle_input(InputEvent(kind="key", key="enter")) == InputIntent(
        kind="select",
        text="revoke-policy:policy-user-1",
    )


def test_permissions_surface_identifies_child_incarnations() -> None:
    view = build_permissions_surface_view(
        ApprovalPermissionsSnapshot(
            pending=(
                ApprovalPermission(
                    kind="pending",
                    permission_id="approval-child",
                    actor_id="/root/reviewer#2",
                    capability="bash",
                    summary="Publish a release",
                ),
            ),
        )
    )

    assert view.content.items[0].description == ("/root/reviewer#2 · Publish a release")
