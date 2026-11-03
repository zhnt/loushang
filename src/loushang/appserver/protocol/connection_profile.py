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
    STDIO_EXECUTION = "foreground-stdio-execution/v1"
    STDIO_DISCOVERY_EXECUTION = "foreground-stdio-discovery-execution/v1"
    LOCAL = LOCAL_PROFILE_V1
    STDIO_DISCOVERY = "foreground-stdio-discovery/v1"
    LOCAL_DISCOVERY = "local-detachable-discovery/v1"
    LOCAL_EXECUTION = "local-detachable-execution/v1"
    LOCAL_RESUME_EXECUTION = "local-detachable-resume-execution/v1"
    LOCAL_DISCOVERY_EXECUTION = "local-detachable-discovery-execution/v1"
    LOCAL_MANAGED = "local-detachable-managed/v1"
    LOCAL_DISCOVERY_MANAGED = "local-detachable-discovery-managed/v1"
    LOCAL_EXECUTION_MANAGED = "local-detachable-execution-managed/v1"
    LOCAL_DISCOVERY_EXECUTION_MANAGED = "local-detachable-discovery-execution-managed/v1"
    LOCAL_MANAGED_CLOSE = "local-detachable-managed/v2"
    LOCAL_DISCOVERY_MANAGED_CLOSE = "local-detachable-discovery-managed/v2"
    LOCAL_EXECUTION_MANAGED_CLOSE = "local-detachable-execution-managed/v2"
    LOCAL_DISCOVERY_EXECUTION_MANAGED_CLOSE = "local-detachable-discovery-execution-managed/v2"
    LOCAL_DISCOVERY_RESUME_EXECUTION = "local-detachable-discovery-resume-execution/v1"
    LOCAL_RESUME_EXECUTION_MANAGED = "local-detachable-resume-execution-managed/v1"
    LOCAL_DISCOVERY_RESUME_EXECUTION_MANAGED = "local-detachable-discovery-resume-execution-managed/v1"
    LOCAL_RESUME_EXECUTION_MANAGED_CLOSE = "local-detachable-resume-execution-managed/v2"
    LOCAL_DISCOVERY_RESUME_EXECUTION_MANAGED_CLOSE = "local-detachable-discovery-resume-execution-managed/v2"


_RESUME_PROFILES = {
    AppConnectionProfileV1.LOCAL_EXECUTION: AppConnectionProfileV1.LOCAL_RESUME_EXECUTION,
    AppConnectionProfileV1.LOCAL_DISCOVERY_EXECUTION: AppConnectionProfileV1.LOCAL_DISCOVERY_RESUME_EXECUTION,
    AppConnectionProfileV1.LOCAL_EXECUTION_MANAGED: AppConnectionProfileV1.LOCAL_RESUME_EXECUTION_MANAGED,
    AppConnectionProfileV1.LOCAL_DISCOVERY_EXECUTION_MANAGED: AppConnectionProfileV1.LOCAL_DISCOVERY_RESUME_EXECUTION_MANAGED,
    AppConnectionProfileV1.LOCAL_EXECUTION_MANAGED_CLOSE: AppConnectionProfileV1.LOCAL_RESUME_EXECUTION_MANAGED_CLOSE,
    AppConnectionProfileV1.LOCAL_DISCOVERY_EXECUTION_MANAGED_CLOSE: AppConnectionProfileV1.LOCAL_DISCOVERY_RESUME_EXECUTION_MANAGED_CLOSE,
}
_RESUME_BASES = {value: key for key, value in _RESUME_PROFILES.items()}


def resume_input_lookup_profile(profile: AppConnectionProfileV1) -> AppConnectionProfileV1:
    """Select a closed optional profile without changing its other capabilities."""

    if type(profile) is not AppConnectionProfileV1:
        raise ValueError("invalid application connection profile")
    if profile in _RESUME_BASES:
        return profile
    try:
        return _RESUME_PROFILES[profile]
    except KeyError:
        raise ValueError("Resume input lookup requires an execution profile") from None


_HELLOS = {
    AppConnectionProfileV1.STDIO: STDIO_HELLO_V1,
    AppConnectionProfileV1.LOCAL: LOCAL_HELLO_V1,
    AppConnectionProfileV1.STDIO_DISCOVERY: (
        b'{"profile":"foreground-stdio-discovery/v1","protocolVersion":"loushang.app/v1"}'
    ),
    AppConnectionProfileV1.LOCAL_DISCOVERY: (
        b'{"profile":"local-detachable-discovery/v1","protocolVersion":"loushang.app/v1"}'
    ),
    AppConnectionProfileV1.LOCAL_MANAGED: (
        b'{"profile":"local-detachable-managed/v1","protocolVersion":"loushang.app/v1"}'
    ),
    AppConnectionProfileV1.LOCAL_DISCOVERY_MANAGED: (
        b'{"profile":"local-detachable-discovery-managed/v1","protocolVersion":"loushang.app/v1"}'
    ),
    AppConnectionProfileV1.LOCAL_MANAGED_CLOSE: (
        b'{"profile":"local-detachable-managed/v2","protocolVersion":"loushang.app/v1"}'
    ),
    AppConnectionProfileV1.LOCAL_DISCOVERY_MANAGED_CLOSE: (
        b'{"profile":"local-detachable-discovery-managed/v2","protocolVersion":"loushang.app/v1"}'
    ),
}


def connection_hello(
    profile: AppConnectionProfileV1, *, service_instance_id: str | None = None,
) -> bytes:
    if type(profile) is not AppConnectionProfileV1:
        raise ValueError("invalid application connection profile")
    if supports_execution(profile):
        if service_instance_id is None:
            raise ValueError("execution hello requires a service instance")
        from ..execution.codec import execution_hello

        return execution_hello(profile.value, service_instance_id)
    if service_instance_id is not None:
        raise ValueError("legacy hello cannot carry execution identity")
    return _HELLOS[profile]


def supports_execution(profile: AppConnectionProfileV1) -> bool:
    if type(profile) is not AppConnectionProfileV1:
        raise ValueError("invalid application connection profile")
    profile = _RESUME_BASES.get(profile, profile)
    return profile in {
        AppConnectionProfileV1.STDIO_EXECUTION,
        AppConnectionProfileV1.STDIO_DISCOVERY_EXECUTION,
        AppConnectionProfileV1.LOCAL_EXECUTION,
        AppConnectionProfileV1.LOCAL_DISCOVERY_EXECUTION,
        AppConnectionProfileV1.LOCAL_EXECUTION_MANAGED,
        AppConnectionProfileV1.LOCAL_DISCOVERY_EXECUTION_MANAGED,
        AppConnectionProfileV1.LOCAL_EXECUTION_MANAGED_CLOSE,
        AppConnectionProfileV1.LOCAL_DISCOVERY_EXECUTION_MANAGED_CLOSE,
    }


def supports_resume_input_lookup(profile: AppConnectionProfileV1) -> bool:
    if type(profile) is not AppConnectionProfileV1:
        raise ValueError("invalid application connection profile")
    return profile in _RESUME_BASES


def supports_session_discovery(profile: AppConnectionProfileV1) -> bool:
    if type(profile) is not AppConnectionProfileV1:
        raise ValueError("invalid application connection profile")
    profile = _RESUME_BASES.get(profile, profile)
    return profile in {
        AppConnectionProfileV1.STDIO_DISCOVERY,
        AppConnectionProfileV1.STDIO_DISCOVERY_EXECUTION,
        AppConnectionProfileV1.LOCAL_DISCOVERY,
        AppConnectionProfileV1.LOCAL_DISCOVERY_EXECUTION,
        AppConnectionProfileV1.LOCAL_DISCOVERY_MANAGED,
        AppConnectionProfileV1.LOCAL_DISCOVERY_EXECUTION_MANAGED,
        AppConnectionProfileV1.LOCAL_DISCOVERY_MANAGED_CLOSE,
        AppConnectionProfileV1.LOCAL_DISCOVERY_EXECUTION_MANAGED_CLOSE,
    }


def supports_managed_mux(profile: AppConnectionProfileV1) -> bool:
    if type(profile) is not AppConnectionProfileV1:
        raise ValueError("invalid application connection profile")
    profile = _RESUME_BASES.get(profile, profile)
    return supports_managed_mux_close(profile) or profile in {
        AppConnectionProfileV1.LOCAL_MANAGED,
        AppConnectionProfileV1.LOCAL_DISCOVERY_MANAGED,
        AppConnectionProfileV1.LOCAL_EXECUTION_MANAGED,
        AppConnectionProfileV1.LOCAL_DISCOVERY_EXECUTION_MANAGED,
    }


def supports_managed_mux_close(profile: AppConnectionProfileV1) -> bool:
    if type(profile) is not AppConnectionProfileV1:
        raise ValueError("invalid application connection profile")
    profile = _RESUME_BASES.get(profile, profile)
    return profile in {
        AppConnectionProfileV1.LOCAL_MANAGED_CLOSE,
        AppConnectionProfileV1.LOCAL_DISCOVERY_MANAGED_CLOSE,
        AppConnectionProfileV1.LOCAL_EXECUTION_MANAGED_CLOSE,
        AppConnectionProfileV1.LOCAL_DISCOVERY_EXECUTION_MANAGED_CLOSE,
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
    if supports_managed_mux(profile) and operation in {AppOperationV1.MUX_CREATE, AppOperationV1.MUX_CLOSE}:
        raise AppServiceError(AppErrorCodeV1.OPERATION_UNAVAILABLE)


def _local_connection_profile(
    session_discovery: bool, session_execution: bool, mux_management: bool,
    mux_closure: bool, resume_input_lookup: bool,
) -> AppConnectionProfileV1:
    """Project validated local-record flags through the closed profile algebra."""

    if mux_management:
        if session_execution:
            profile = (AppConnectionProfileV1.LOCAL_DISCOVERY_EXECUTION_MANAGED if session_discovery
                    else AppConnectionProfileV1.LOCAL_EXECUTION_MANAGED)
        else:
            profile = (AppConnectionProfileV1.LOCAL_DISCOVERY_MANAGED if session_discovery
                       else AppConnectionProfileV1.LOCAL_MANAGED)
        if mux_closure:
            profile = AppConnectionProfileV1(profile.value.removesuffix("/v1") + "/v2")
    elif session_execution:
        profile = (AppConnectionProfileV1.LOCAL_DISCOVERY_EXECUTION if session_discovery
                   else AppConnectionProfileV1.LOCAL_EXECUTION)
    else:
        profile = (AppConnectionProfileV1.LOCAL_DISCOVERY if session_discovery
                   else AppConnectionProfileV1.LOCAL)
    return resume_input_lookup_profile(profile) if resume_input_lookup else profile
