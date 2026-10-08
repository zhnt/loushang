"""Explicit POSIX operator CLI over the local Coding Product repair SDK."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version

from loushang.coding.package_product_repair import (
    CODING_PACKAGE_REPAIR_ACTIONS_V1,
    CODING_PACKAGE_REPAIR_INSPECTIONS_V1,
    _perform_coding_package_repair,
    open_coding_package_repair_client,
)
from loushang.coding.package_product_runtime import (
    open_coding_fenced_product_application_owner,
)

_SAFE_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{1,127}\Z")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loushang-package-repair")
    parser.add_argument("--workspace", default=".", help="fenced Coding workspace")
    actions = parser.add_subparsers(dest="action", required=True)
    help_text = {
        "repair-handoff": "recover one committed Package handoff without general activation",
        "inspect-staging": "activate Product and inspect staging without selecting repair",
        "inspect-published": "inspect a complete published set without selecting repair",
        "repair-staging": "select and execute one staged recovery in this runtime",
        "repair-published": "select and commit one complete published set in this runtime",
        "repair-pinned": "select and execute a pinned attempt before staging",
        "repair-retryable": "select and execute one failed retryable attempt",
        "repair-unstarted": "recover an abandoned claim before Package effects",
        "repair-acquired": "recover an abandoned acquisition or inspection",
        "repair-resolving": "recover an abandoned closure resolution",
        "repair-verified": "recover an abandoned verified closure",
    }
    for name in CODING_PACKAGE_REPAIR_ACTIONS_V1:
        action = actions.add_parser(name, help=help_text[name])
        action.add_argument("operation_id", help="exact Package operation ID")
    args = parser.parse_args(argv)

    try:
        client = open_coding_package_repair_client(
            args.workspace, runtime_version=version("loushang")
        )
        result = _perform_coding_package_repair(
            client,
            args.action,
            args.operation_id,
            owner_factory=open_coding_fenced_product_application_owner,
        )
    except (OSError, RuntimeError, ValueError, PackageNotFoundError) as error:
        reason = getattr(error, "code", None)
        if not isinstance(reason, str) or _SAFE_ERROR_CODE.fullmatch(reason) is None:
            reason = "package_repair_unavailable"
        sys.stderr.write(f"Coding Package repair refused: {reason}\n")
        return 1
    sys.stdout.write(json.dumps(result.to_dict(), sort_keys=True) + "\n")
    return (
        0
        if args.action in CODING_PACKAGE_REPAIR_INSPECTIONS_V1 or result.committed
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
