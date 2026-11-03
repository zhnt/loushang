"""Optional Resume data adapters and borrowed original controller context.

These functions operate on the existing scope/session owners. They introduce
no authority table, grant, execution reservation, or separate operation owner.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from loushang.appserver.protocol import (
    AppErrorCodeV1,
    AppServiceError,
    SessionSnapshotRequestV1,
)
from loushang.appserver.resume_model import (
    ResumeInputLookupQueryV1,
    ResumeInputLookupResultV1,
    ResumeInputLookupStatusV1,
)

from .execution_contract import _identifier

__all__ = [
    "HostedResumeInputLookupPortV1", "ResumeInputLookupQueryV1",
    "ResumeInputLookupResultV1", "ResumeInputLookupStatusV1",
]


@runtime_checkable
class HostedResumeInputLookupPortV1(Protocol):
    async def lookup_resume_input(
        self, query: ResumeInputLookupQueryV1,
    ) -> ResumeInputLookupResultV1: ...


async def _lookup_resume_product_input(
    port: object, query: ResumeInputLookupQueryV1,
) -> ResumeInputLookupResultV1:
    if not isinstance(port, HostedResumeInputLookupPortV1):
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
    try:
        value = await port.lookup_resume_input(query)
    except (asyncio.CancelledError, AppServiceError):
        raise
    except BaseException:
        raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE) from None
    if type(value) is not ResumeInputLookupResultV1 or value.input_id != query.input_id:
        raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
    return value


if TYPE_CHECKING:
    from .client_scope import AppClientScopeV1
    from .runtime import _SessionOwner


_RESUME_SUBJECT: ContextVar[tuple[AppClientScopeV1, SessionSnapshotRequestV1, str, str | None] | None] = ContextVar(
    "appservice_resume_subject", default=None,
)


def _resume_subject_digest(
    scope: AppClientScopeV1, request: SessionSnapshotRequestV1,
    *, expected_session_id: str | None = None,
) -> str:
    from .client_scope import AppClientScopeV1

    if type(scope) is not AppClientScopeV1:
        raise TypeError("Resume subject requires the original native client scope")
    scope._service._require_request(request, SessionSnapshotRequestV1)
    scope._attachment(request.attachment_id, request.controller_generation)
    pair = scope._service._attachments.get(request.attachment_id)
    if pair is None:
        raise AppServiceError(AppErrorCodeV1.STALE_ATTACHMENT)
    mux, _ = pair
    session = next((
        member.session for member in mux.members if member.member_id == request.member_id
    ), None)
    if session is None:
        raise AppServiceError(AppErrorCodeV1.STALE_ATTACHMENT)
    scope._require_current_session(request, session)
    if not session._accepting:
        raise AppServiceError(AppErrorCodeV1.SESSION_UNAVAILABLE)
    registry = scope._service._execution_registry
    if registry is None:
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
    identity = session.identity
    if expected_session_id is not None and (
        type(expected_session_id) is not str or expected_session_id != identity.session_id
    ):
        raise AppServiceError(AppErrorCodeV1.STALE_ATTACHMENT)
    encoded = json.dumps({
        "applicationId": registry.application_id,
        "serviceInstanceId": registry.service_instance_id,
        "attachmentId": request.attachment_id,
        "controllerGeneration": request.controller_generation,
        "memberId": request.member_id,
        "productId": identity.product_id,
        "continuityId": identity.continuity_id,
        "sessionId": identity.session_id,
        "scope": identity.scope.value,
        "scopeFingerprint": identity.scope_fingerprint,
    }, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 4096:
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
    return hashlib.sha256(b"loushang.appservice.resume-subject/v1\0" + encoded).hexdigest()


@contextmanager
def _resume_subject_scope(
    scope: AppClientScopeV1, request: SessionSnapshotRequestV1,
    *, submission_id: str | None = None,
) -> Iterator[None]:
    digest = scope.resume_subject_digest(request)
    if submission_id is not None:
        _identifier(submission_id)
    token = _RESUME_SUBJECT.set((scope, request, digest, submission_id))
    try:
        yield
    finally:
        _RESUME_SUBJECT.reset(token)


def _current_resume_subject() -> tuple[AppClientScopeV1, SessionSnapshotRequestV1, str]:
    from .client_scope import AppClientScopeV1

    borrowed = _RESUME_SUBJECT.get()
    if borrowed is None:
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
    scope, control, digest, _ = borrowed
    if type(scope) is not AppClientScopeV1 or type(control) is not SessionSnapshotRequestV1:
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
    scope.require_current_resume_subject(control, digest)
    return scope, control, digest


def _current_resume_submission_id() -> str | None:
    _current_resume_subject()
    borrowed = _RESUME_SUBJECT.get()
    assert borrowed is not None
    return borrowed[3]


async def _lookup_scoped_resume_input(
    scope: AppClientScopeV1, request: SessionSnapshotRequestV1, query: ResumeInputLookupQueryV1,
) -> ResumeInputLookupResultV1:
    scope._service._require_request(request, SessionSnapshotRequestV1)
    scope._service._require_request(query, ResumeInputLookupQueryV1)
    session = await scope._session(
        request.attachment_id, request.controller_generation, request.member_id,
    )
    scope._require_current_session(request, session)
    value = await session.lookup_resume_input(query)
    scope._require_current_session(request, session)
    return value


def _require_scoped_session(
    scope: AppClientScopeV1, request: SessionSnapshotRequestV1, session: _SessionOwner,
) -> None:
    scope._attachment(request.attachment_id, request.controller_generation)
    pair = scope._service._attachments.get(request.attachment_id)
    if pair is None:
        raise AppServiceError(AppErrorCodeV1.STALE_ATTACHMENT)

    mux, attachment = pair
    if (
        not attachment.active or mux.closed
        or attachment.controller_generation != request.controller_generation
        or mux.next_generation != request.controller_generation
        or scope._service._sessions.get(session.identity.session_id) is not session
        or not any(member.member_id == request.member_id and member.session is session
                   for member in mux.members)
    ):
        raise AppServiceError(AppErrorCodeV1.STALE_ATTACHMENT)


def _require_current_resume_subject(
    scope: AppClientScopeV1, request: SessionSnapshotRequestV1, expected_digest: str,
    *, expected_session_id: str | None = None,
) -> None:
    current = scope.resume_subject_digest(request, expected_session_id=expected_session_id)
    if type(expected_digest) is not str or expected_digest != current:
        raise AppServiceError(AppErrorCodeV1.STALE_ATTACHMENT)
