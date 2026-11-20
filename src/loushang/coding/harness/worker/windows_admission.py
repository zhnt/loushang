"""Admission checks shared by Windows Worker history and recovery entries."""

from __future__ import annotations

import re

from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

_ATTEMPT_ID = re.compile(r"[0-9a-f]{32}\Z")


def is_windows_product(
    product: WindowsLocalWheelProductSessionOwner,
    product_id: str,
    platform: str,
    owner_type: type[WindowsLocalWheelProductSessionOwner] = (
        WindowsLocalWheelProductSessionOwner
    ),
) -> bool:
    return not (
        platform != "nt"
        or type(product) is not owner_type
        or product.policy.product_id != product_id
    )


def is_attempt_id(attempt_id: object) -> bool:
    return type(attempt_id) is str and _ATTEMPT_ID.fullmatch(attempt_id) is not None
