from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from types import ModuleType

from loushang.harness.sdk_surface import (
    SdkSurfaceCompatibilityReport,
    SdkSurfaceSnapshot,
)
from loushang.harness.sdk_surface import (
    check_sdk_surface_compatibility as _check_sdk_surface_compatibility,
)
from loushang.harness.sdk_surface import (
    get_sdk_surface_snapshot as _get_sdk_surface_snapshot,
)

DEFAULT_SDK_ENTRY_NAMES: tuple[str, ...] = (
    "create_services",
    "create_agent_session_services",
    "create_agent_session",
    "create_agent_session_result",
    "create_agent_session_from_services",
    "create_agent_session_runtime",
)


def get_sdk_surface_snapshot(
    module: ModuleType | None = None,
    *,
    entry_names: Sequence[str] = DEFAULT_SDK_ENTRY_NAMES,
) -> SdkSurfaceSnapshot:
    target = module or importlib.import_module("loushang.coding")
    return _get_sdk_surface_snapshot(
        target,
        entry_names=entry_names,
    )


def check_sdk_surface_compatibility(
    module: ModuleType | None = None,
    *,
    required_exports: Sequence[str] = (),
    required_entry_signatures: Mapping[str, Sequence[str]] | None = None,
) -> SdkSurfaceCompatibilityReport:
    target = module or importlib.import_module("loushang.coding")
    return _check_sdk_surface_compatibility(
        target,
        entry_names=DEFAULT_SDK_ENTRY_NAMES,
        required_exports=required_exports,
        required_entry_signatures=required_entry_signatures,
    )


__all__ = [
    "DEFAULT_SDK_ENTRY_NAMES",
    "SdkSurfaceCompatibilityReport",
    "SdkSurfaceSnapshot",
    "check_sdk_surface_compatibility",
    "get_sdk_surface_snapshot",
]
