from __future__ import annotations

from loushang.harness.approval import (
    ApprovalGrantProposal,
    ApprovalRequest,
    HeadlessApprovalResolver,
    InteractiveApprovalResolver,
    approval_request_to_dict,
    configure_persistent_approval_policy,
)


def test_approval_projection_exposes_policy_bounded_presentation_fields() -> None:
    payload = approval_request_to_dict(
        ApprovalRequest(
            tool_name="bash",
            arguments={"command": "git push origin main"},
            reason="Commits or refs would be published",
            session_grant=ApprovalGrantProposal(
                capability="git.publish_refs",
                constraints=(("remote", "origin"), ("force", "false")),
                summary="Publish non-force refs to origin from this repository",
            ),
        )
    )

    assert payload["action"] == "git push origin main"
    assert payload["risk"] == "Commits or refs would be published"
    assert payload["environment"] == "local"
    assert (
        payload["grant_summary"]
        == "Publish non-force refs to origin from this repository"
    )
    assert tuple(
        option["outcome"] for option in payload["approval_options"]
    ) == ("allow_once", "allow_session", "deny")


def test_approval_projection_redacts_command_secrets() -> None:
    payload = approval_request_to_dict(
        ApprovalRequest(
            tool_name="bash",
            arguments={
                "command": (
                    "curl -H 'Authorization: Bearer secret-token' "
                    "https://example.com"
                )
            },
            reason="A remote system would be contacted or changed",
        )
    )

    assert payload["action"] == (
        "curl -H 'Authorization: Bearer [REDACTED]' https://example.com"
    )
    assert "secret-token" not in str(payload["action"])


def test_standard_approval_policy_stores_are_harness_owned(tmp_path) -> None:
    class Settings:
        project_base_dir = tmp_path / "project"
        global_base_dir = tmp_path / "user"

    resolver = InteractiveApprovalResolver(
        fallback=HeadlessApprovalResolver(mode="deny")
    )

    configure_persistent_approval_policy(resolver, Settings())

    assert set(resolver.policy_stores) == {"project", "user"}
    assert resolver.policy_stores["project"].path == (
        Settings.project_base_dir / "approval-policy.json"
    )
    assert resolver.policy_stores["user"].path == (
        Settings.global_base_dir / "approval-policy.json"
    )
