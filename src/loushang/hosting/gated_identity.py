"""Read-only native identity from one exact gated Hosting child session.

Only the synchronous v2 POSIX launch can supply this fact. It does not prove
Product attempt binding, process-scope settlement, or cleanup authority.
"""

from __future__ import annotations

from dataclasses import dataclass

from ._child_session_host import _HostedChildSession
from ._posix_process import _PosixProcess
from ._process_host import _HostedProcess
from .contracts import ChildSessionLease
from .errors import HostingError, HostingFailureCategory
from .service import LinuxServiceIdentityV1


@dataclass(frozen=True, slots=True)
class LinuxGatedChildWitnessV1:
    native_identity: LinuxServiceIdentityV1
    gate_device: int
    gate_inode: int


def linux_gated_child_session_witness(
    lease: ChildSessionLease,
) -> LinuxGatedChildWitnessV1:
    """Return only native facts captured by this exact gated Hosting lease."""

    if type(lease) is not _HostedChildSession:
        raise _error()
    hosted = lease.process
    if type(hosted) is not _HostedProcess:
        raise _error()
    native = hosted._process
    if (
        type(native) is not _PosixProcess
        or native.native_identity is None
        or native.start_gate_identity is None
    ):
        raise _error()
    device, inode = native.start_gate_identity
    return LinuxGatedChildWitnessV1(native.native_identity, device, inode)


def linux_gated_child_session_identity(
    lease: ChildSessionLease,
) -> LinuxServiceIdentityV1:
    return linux_gated_child_session_witness(lease).native_identity


def _error() -> HostingError:
    return HostingError(
        HostingFailureCategory.INVALID_REQUEST,
        "gated child-session identity is unavailable",
    )


__all__ = [
    "LinuxGatedChildWitnessV1",
    "linux_gated_child_session_identity",
    "linux_gated_child_session_witness",
]
