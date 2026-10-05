"""Explicit local TUI actions over the Coding Product Package repair owner."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import cast

from loushang.harness.host.types import HostActionResult

from .package_product_repair import (
    CODING_PACKAGE_REPAIR_ACTIONS_V1,
    CODING_PACKAGE_REPAIR_INSPECTIONS_V1,
    CodingPackageRepairActionV1,
    CodingPackageRepairClientV1,
    CodingPackageRepairResultV1,
    open_coding_package_repair_client,
)

_SAFE_CODE = re.compile(r"[a-z][a-z0-9_]{1,127}\Z")
_USAGE = "Usage: /plugins repair-package ACTION OPERATION_ID"


def execute_coding_package_repair_ui_command(
    workspace: str | Path,
    text: str,
    *,
    open_client: Callable[[str | Path], CodingPackageRepairClientV1] = (
        open_coding_package_repair_client
    ),
) -> HostActionResult:
    tokens = text.split()
    if (
        len(tokens) != 4
        or tokens[0:2] != ["/plugins", "repair-package"]
        or tokens[2] not in CODING_PACKAGE_REPAIR_ACTIONS_V1
        or not 0 < len(tokens[3]) <= 256
        or not tokens[3].isascii()
        or not tokens[3].isprintable()
    ):
        return HostActionResult(error_message=_USAGE)
    action, operation_id = tokens[2:]
    try:
        client = open_client(workspace)
        result = client.perform(
            cast(CodingPackageRepairActionV1, action),
            operation_id,
        )
        if (
            not isinstance(result, CodingPackageRepairResultV1)
            or result.operation_id != operation_id
        ):
            raise ValueError("Package repair result changed identity")
        if action in CODING_PACKAGE_REPAIR_INSPECTIONS_V1:
            if result.staged_node_count is None:
                raise ValueError("Package checkpoint inspection is invalid")
            label = "staging" if action == "inspect-staging" else "published set"
            return HostActionResult(
                status_message=(
                    f"Package {label} {operation_id}: {result.phase}; "
                    f"{result.staged_node_count} staged, "
                    f"{len(result.missing_node_ids)} missing."
                )
            )
        if result.committed:
            return HostActionResult(
                status_message=(
                    f"Package repair committed: {operation_id}; "
                    "new Session required to observe changes."
                )
            )
        code = result.failure_code
        if not isinstance(code, str) or _SAFE_CODE.fullmatch(code) is None:
            code = "package_repair_not_committed"
        return HostActionResult(
            error_message=f"Package repair refused: {code}; operation {operation_id}"
        )
    except Exception as exc:
        code = getattr(exc, "code", None)
        if not isinstance(code, str) or _SAFE_CODE.fullmatch(code) is None:
            code = "package_repair_unavailable"
        return HostActionResult(error_message=f"Package repair refused: {code}")


__all__ = ["execute_coding_package_repair_ui_command"]
