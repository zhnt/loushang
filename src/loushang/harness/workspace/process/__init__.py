"""Hosted-process contracts for long-lived workspace capabilities."""

from .types import (
    AuthorizedProcessLauncher,
    ProcessExit,
    ProcessHandle,
    ProcessLaunchRequest,
    ProcessStderrTail,
)

__all__ = [
    "AuthorizedProcessLauncher",
    "ProcessExit",
    "ProcessHandle",
    "ProcessLaunchRequest",
    "ProcessStderrTail",
]
