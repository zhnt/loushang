"""Stable, Product-neutral Hosting failure categories."""

from __future__ import annotations

from enum import Enum


class HostingFailureCategory(str, Enum):
    """Mechanism-only failure categories exposed across the Hosting boundary."""

    INVALID_REQUEST = "invalid_request"
    HOST_CLOSED = "host_closed"
    CAPACITY_EXHAUSTED = "capacity_exhausted"
    PREPARATION_REJECTED = "preparation_rejected"
    PREPARATION_STALE = "preparation_stale"
    PREPARATION_FAILED = "preparation_failed"
    ENDPOINT_UNAVAILABLE = "endpoint_unavailable"
    ENDPOINT_TRANSFER_FAILED = "endpoint_transfer_failed"
    PLATFORM_UNSUPPORTED = "platform_unsupported"
    SPAWN_FAILED = "spawn_failed"
    CHILD_EXITED_EARLY = "child_exited_early"
    READ_BOUND_EXCEEDED = "read_bound_exceeded"
    WRITE_BOUND_EXCEEDED = "write_bound_exceeded"
    PEER_CLOSED = "peer_closed"
    TERMINATION_FAILED = "termination_failed"
    CLEANUP_FAILED = "cleanup_failed"


class HostingError(RuntimeError):
    """Base error whose category never asserts caller-owned security meaning."""

    def __init__(self, category: HostingFailureCategory, message: str) -> None:
        if not isinstance(category, HostingFailureCategory):
            raise TypeError("category must be a HostingFailureCategory")
        if not isinstance(message, str) or not message:
            raise TypeError("message must be non-empty text")
        self.category = category
        super().__init__(message)


class InvalidHostingRequestError(HostingError, ValueError):
    """Raised when materialized launch data violates the Hosting contract."""

    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        super().__init__(
            HostingFailureCategory.INVALID_REQUEST,
            f"{field} {reason}",
        )


__all__ = [
    "HostingError",
    "HostingFailureCategory",
    "InvalidHostingRequestError",
]
