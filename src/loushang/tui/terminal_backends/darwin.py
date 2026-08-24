from __future__ import annotations

import ctypes
import importlib
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

_APPLICATION_SERVICES_PATH = (
    "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
)
_EVENT_SOURCE_STATE_COMBINED_SESSION = 0
_EVENT_FLAG_MASK_SHIFT = 1 << 17

ApplicationServicesLoader = Callable[[], Any | None]
NativeModifiersLoader = Callable[[], Any | None]


def _load_application_services() -> Any | None:
    try:
        return ctypes.CDLL(_APPLICATION_SERVICES_PATH)
    except (OSError, AttributeError):
        return None


def _load_native_modifiers() -> Any | None:
    try:
        return importlib.import_module("loushang.tui.native_modifiers")
    except Exception:
        return None


@dataclass(frozen=True, slots=True)
class DarwinModifierKeys:
    """Own Darwin-specific modifier probing without importing it elsewhere."""

    application_services_loader: ApplicationServicesLoader = (
        _load_application_services
    )
    native_modifiers_loader: NativeModifiersLoader = _load_native_modifiers

    def shift_pressed(self) -> bool:
        try:
            application_services = self.application_services_loader()
        except Exception:
            application_services = None
        if application_services is not None and _quartz_shift_pressed(
            application_services
        ):
            return True
        try:
            native_modifiers = self.native_modifiers_loader()
        except Exception:
            return False
        if native_modifiers is None:
            return False
        try:
            return bool(native_modifiers.is_shift_pressed())
        except Exception:
            return False


def _quartz_shift_pressed(application_services: Any) -> bool:
    try:
        flags_state = application_services.CGEventSourceFlagsState
        flags_state.argtypes = [ctypes.c_uint32]
        flags_state.restype = ctypes.c_uint64
        flags = int(flags_state(_EVENT_SOURCE_STATE_COMBINED_SESSION))
    except Exception:
        return False
    return bool(flags & _EVENT_FLAG_MASK_SHIFT)


__all__ = ["DarwinModifierKeys"]
