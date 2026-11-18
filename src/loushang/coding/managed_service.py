"""Coding policy and safe errors for the AppHost managed service control."""

from __future__ import annotations

import os
import sys
from functools import partial
from time import monotonic

from loushang.apphost.managed._files import ManagedStorageError
from loushang.apphost.managed.coordinator import (
    control_managed_service as _control_managed_service,
)
from loushang.apphost.managed.defaults import resolve_managed_defaults
from loushang.apphost.managed.starter import ManagedLaunchRequestFactoryV1
from loushang.appserver.client import AppConnectionClosedError
from loushang.appserver.local_auth import LocalAuthenticationError
from loushang.appserver.local_record import LocalRecordError
from loushang.appserver.protocol import AppServiceError, InvalidAppMessageError
from loushang.hosting.errors import HostingError

from .managed_process import APPLICATION_ID, ENDPOINT, coding_managed_process_request


class ServiceControlError(RuntimeError):
    """A safe lifecycle error for command clients."""


async def control_managed_service(
    operation: str,
    expected: str | None,
    *,
    request_factory: ManagedLaunchRequestFactoryV1 | None = None,
) -> dict[str, object]:
    try:
        return await _control(operation, expected, request_factory)
    except LocalAuthenticationError as error:
        raise ServiceControlError("authentication_failed") from error
    except AppConnectionClosedError as error:
        raise ServiceControlError("connection_failed") from error
    except InvalidAppMessageError as error:
        raise ServiceControlError("protocol_incompatible") from error
    except (AppServiceError, LocalRecordError) as error:
        raise ServiceControlError(error.code.value) from error
    except ManagedStorageError as error:
        raise ServiceControlError(error.code) from error
    except HostingError as error:
        raise ServiceControlError(error.category.value) from error


async def _control(
    operation: str, expected: str | None, request_factory: ManagedLaunchRequestFactoryV1 | None,
) -> dict[str, object]:
    timeout = 30.0
    if operation == "restart":
        timeout += 30.0
    if sys.platform == "win32" and operation in {"start", "restart"}:
        # The manager starts its clock before spawning and admitting the child,
        # which then needs its own bounded window to restore legacy Sessions.
        timeout += 15.0
    deadline = monotonic() + timeout
    defaults = resolve_managed_defaults()
    return await _control_managed_service(
        operation,
        expected,
        defaults=defaults,
        service_alias="coding",
        application_id=APPLICATION_ID,
        endpoint=ENDPOINT,
        deadline=deadline,
        select_request_factory=lambda: request_factory or partial(
            coding_managed_process_request, executable=sys.executable, environment=os.environ,
        ),
        error_factory=lambda code: ServiceControlError(code),
    )
