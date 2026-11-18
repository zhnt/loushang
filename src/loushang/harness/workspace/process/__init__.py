"""Hosted-process contracts for long-lived workspace capabilities."""

from .lifecycle import wait_for_process_exit
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
    "wait_for_process_exit",
]
