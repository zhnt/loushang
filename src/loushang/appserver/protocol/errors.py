"""Stable failures shared by AppClient and the G11 AppService boundary."""

from __future__ import annotations

from enum import Enum


class AppErrorCodeV1(str, Enum):
    INVALID_REQUEST = "invalid_request"
    NOT_FOUND = "not_found"
    ALREADY_EXISTS = "already_exists"
    PRODUCT_MISMATCH = "product_mismatch"
    REVISION_CONFLICT = "revision_conflict"
    SNAPSHOT_REQUIRED = "snapshot_required"
    STALE_ATTACHMENT = "stale_attachment"
    ATTACHMENT_LAGGED = "attachment_lagged"
    SESSION_UNAVAILABLE = "session_unavailable"
    OPERATION_UNAVAILABLE = "operation_unavailable"
    CLEANUP_INCOMPLETE = "cleanup_incomplete"
    SERVICE_CLOSED = "service_closed"


class AppServiceError(RuntimeError):
    """A closed client-safe failure with no raw Product details."""

    def __init__(self, code: AppErrorCodeV1) -> None:
        if type(code) is not AppErrorCodeV1:
            raise TypeError("invalid app error code")
        self.code = code
        super().__init__(code.value)


class InvalidAppMessageError(AppServiceError):
    def __init__(self) -> None:
        super().__init__(AppErrorCodeV1.INVALID_REQUEST)


__all__ = ["AppErrorCodeV1", "AppServiceError", "InvalidAppMessageError"]
