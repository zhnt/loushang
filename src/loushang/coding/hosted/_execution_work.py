"""Coding's explicit invocation result and retained Session settlement."""

from __future__ import annotations

from loushang.apphost.integrations.session_control import _HostedPromptExecutionWork
from loushang.appserver.protocol import SessionSnapshotRequestV1
from loushang.appservice.client_scope import ScopedAppServicePortV1
from loushang.appservice.execution_contract import (
    ExecutionStatusV1 as ExecutionStatusV1,
)
from loushang.coding.resume import subject as _resume_subject

# Concrete original owner types for the optional Coding confirmation borrow.
HostedResumeSubjectScope = ScopedAppServicePortV1
HostedResumeSubjectControl = SessionSnapshotRequestV1
_require_current_coding_hosted_resume_subject = (
    _resume_subject.require_current_coding_hosted_resume_subject
)


def current_coding_hosted_resume_subject() -> tuple[
    HostedResumeSubjectScope, HostedResumeSubjectControl, str,
]:
    """Borrow the original scope captured by native execution admission.

    This observation neither reserves execution nor confirms permissions. The
    caller still binds exact Approval and rechecks the original owner before
    Resume mutation, publication and transport.
    """

    return ScopedAppServicePortV1.current_resume_subject()


def current_coding_hosted_resume_submission_id() -> str | None:
    """Read the initiating stable ID; legacy Ack submissions have no such ID."""

    return ScopedAppServicePortV1.current_resume_submission_id()


class CodingExecutionWorkV1(_HostedPromptExecutionWork):
    """Retain the Coding work type for ordinary prompts and Method steps."""
