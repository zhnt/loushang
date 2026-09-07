"""Closed wire profiles, independent of authentication and connection IO."""

from enum import Enum

from .stdio_profile import STDIO_HELLO_V1

LOCAL_PROFILE_V1 = "local-detachable/v1"
LOCAL_HELLO_V1 = (
    b'{"profile":"local-detachable/v1","protocolVersion":"loushang.app/v1"}'
)


class AppConnectionProfileV1(str, Enum):
    STDIO = "foreground-stdio/v1"
    LOCAL = LOCAL_PROFILE_V1


def connection_hello(profile: AppConnectionProfileV1) -> bytes:
    if type(profile) is not AppConnectionProfileV1:
        raise ValueError("invalid application connection profile")
    return STDIO_HELLO_V1 if profile is AppConnectionProfileV1.STDIO else LOCAL_HELLO_V1
