"""Closed wire profiles, independent of authentication and connection IO."""

from enum import Enum

from .errors import AppErrorCodeV1, AppServiceError
from .model import AppOperationV1
from .stdio_profile import STDIO_HELLO_V1

LOCAL_PROFILE_V1 = "local-detachable/v1"
LOCAL_HELLO_V1 = (
    b'{"profile":"local-detachable/v1","protocolVersion":"loushang.app/v1"}'
)


class AppConnectionProfileV1(str, Enum):
    STDIO = "foreground-stdio/v1"
    LOCAL = LOCAL_PROFILE_V1
    STDIO_DISCOVERY = "foreground-stdio-discovery/v1"
    LOCAL_DISCOVERY = "local-detachable-discovery/v1"


_HELLOS = {
    AppConnectionProfileV1.STDIO: STDIO_HELLO_V1,
    AppConnectionProfileV1.LOCAL: LOCAL_HELLO_V1,
    AppConnectionProfileV1.STDIO_DISCOVERY: (
        b'{"profile":"foreground-stdio-discovery/v1","protocolVersion":"loushang.app/v1"}'
    ),
    AppConnectionProfileV1.LOCAL_DISCOVERY: (
        b'{"profile":"local-detachable-discovery/v1","protocolVersion":"loushang.app/v1"}'
    ),
}


def connection_hello(profile: AppConnectionProfileV1) -> bytes:
    if type(profile) is not AppConnectionProfileV1:
        raise ValueError("invalid application connection profile")
    return _HELLOS[profile]


def supports_session_discovery(profile: AppConnectionProfileV1) -> bool:
    if type(profile) is not AppConnectionProfileV1:
        raise ValueError("invalid application connection profile")
    return profile in {
        AppConnectionProfileV1.STDIO_DISCOVERY,
        AppConnectionProfileV1.LOCAL_DISCOVERY,
    }


def require_profile_operation(
    profile: AppConnectionProfileV1, operation: AppOperationV1
) -> None:
    """Codec recognition is not permission to use an optional operation."""
    if type(operation) is not AppOperationV1:
        raise ValueError("invalid application operation")
    discovery = supports_session_discovery(profile)
    if operation is AppOperationV1.SESSIONS_LIST and not discovery:
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)
