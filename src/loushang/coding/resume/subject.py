"""Exact current Hosted subject validation for Coding Resume admission."""

from __future__ import annotations

from loushang.appserver.protocol import SessionSnapshotRequestV1
from loushang.appservice.client_scope import ScopedAppServicePortV1

from .activation_attempt import CodingActivationAttemptV1

HostedResumeSubjectScope = ScopedAppServicePortV1
HostedResumeSubjectControl = SessionSnapshotRequestV1


def _require_current_coding_hosted_resume_subject(
    attempt: CodingActivationAttemptV1,
    scope: HostedResumeSubjectScope | None,
    control: HostedResumeSubjectControl | None,
) -> None:
    if type(scope) is not ScopedAppServicePortV1 or type(control) is not SessionSnapshotRequestV1:
        raise TypeError("Coding Resume requires the original Hosted subject owner and control")
    scope.require_current_resume_subject(
        control, attempt.subject_digest, expected_session_id=attempt.session_id,
    )


_require_current_coding_hosted_resume_subject.__module__ = "loushang.coding._hosted_execution_work"
require_current_coding_hosted_resume_subject = _require_current_coding_hosted_resume_subject

__all__ = [
    "HostedResumeSubjectControl",
    "HostedResumeSubjectScope",
    "require_current_coding_hosted_resume_subject",
]
