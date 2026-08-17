from __future__ import annotations

import pytest

from loushang.harness.events import (
    BranchSummaryCompleted,
    BranchSummaryStarted,
    ContextCompactionCompleted,
    ContextCompactionStarted,
    ConversationMetadataChanged,
    PackageProgressChanged,
    PermissionProfileChanged,
    QueueChanged,
    RetryCompleted,
    RetryStarted,
    ToolPolicyAuditEvent,
    session_runtime_event_kind,
)
from loushang.harness.events.session import QueueSnapshot, RetryAttempt, RetryOutcome


@pytest.mark.parametrize(
    ("payload", "kind"),
    [
        (QueueChanged(QueueSnapshot()), "session.queue_update"),
        (ContextCompactionStarted("manual"), "session.compaction_start"),
        (
            ContextCompactionCompleted("threshold", None, False, False),
            "session.compaction_end",
        ),
        (
            RetryStarted(RetryAttempt(1, 2, 100, "unavailable")),
            "session.auto_retry_start",
        ),
        (RetryCompleted(RetryOutcome(True, 1)), "session.auto_retry_end"),
        (
            BranchSummaryStarted("target", "old", True),
            "session.branch_summary_start",
        ),
        (
            BranchSummaryCompleted("target", "old", "new", "summary", False, False),
            "session.branch_summary_end",
        ),
        (ConversationMetadataChanged("Demo"), "session.session_info_changed"),
        (
            PackageProgressChanged(
                progress_type="progress",
                action="install",
                source="pack",
                target_path="/tmp/pack",
            ),
            "session.package_progress",
        ),
        (
            ToolPolicyAuditEvent(
                "tool_policy_evaluated",
                {"tool_name": "write", "decision": "allow"},
            ),
            "session.tool_policy_evaluated",
        ),
        (
            ToolPolicyAuditEvent(
                "tool_execution_completed",
                {"tool_name": "write", "outcome": "completed"},
            ),
            "session.tool_execution_completed",
        ),
        (
            PermissionProfileChanged(
                previous_profile_id="standard",
                requested_profile_id="cautious",
                effective_profile_id="cautious",
                scope="project",
            ),
            "session.permission_profile_changed",
        ),
    ],
)
def test_session_runtime_payloads_have_stable_kinds(payload: object, kind: str) -> None:
    assert session_runtime_event_kind(payload) == kind  # type: ignore[arg-type]


def test_session_runtime_event_kind_rejects_unregistered_payload() -> None:
    with pytest.raises(TypeError, match="unsupported Session runtime event payload"):
        session_runtime_event_kind(object())  # type: ignore[arg-type]
