"""Explicit offline Windows candidate Worker inspection and crash recovery."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    open_coding_fenced_product_application_owner,
)
from loushang.coding.package_product_worker_windows_activation_state_journal import (
    CodingWindowsWorkerActivationStateJournal,
)
from loushang.coding.package_product_worker_windows_crash_recovery import (
    recover_coding_windows_product_worker_crash_attempt,
)
from loushang.coding.package_product_worker_windows_orphan_review import (
    review_coding_windows_product_worker_orphan_runtime,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)

_SAFE_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{1,127}\Z")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loushang-worker-windows-candidate")
    parser.add_argument("--workspace", required=True, help="fenced Coding workspace")
    parser.add_argument(
        "--windows-candidate", action="store_true", help=argparse.SUPPRESS
    )
    actions = parser.add_subparsers(dest="action", required=True)
    for action, help_text in (
        ("inspect", "inspect one retained Worker attempt"),
        ("recover-crash", "resume exact Product crash cleanup and C5 settlement"),
    ):
        command = actions.add_parser(action, help=help_text)
        command.add_argument("--attempt-id", required=True)
    args = parser.parse_args(argv)
    if os.name != "nt" or not args.windows_candidate:
        sys.stderr.write(
            "Windows Worker candidate refused: windows_worker_candidate_platform_closed\n"
        )
        return 1
    try:
        workspace = Path(args.workspace).expanduser().resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError("Coding workspace must be a directory")
        lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
        owner = open_coding_fenced_product_application_owner(
            lifecycle,
            workspace=workspace,
            runtime_version=version("loushang"),
            runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
            windows_candidate=True,
            worker_candidates=True,
        )
        try:
            product = owner.runtime_owner.product_owner
            if type(product) is not WindowsLocalWheelProductSessionOwner:
                raise ValueError("Windows Worker candidate Product is unavailable")
            if args.action == "inspect":
                review = review_coding_windows_product_worker_orphan_runtime(
                    product, attempt_id=args.attempt_id
                )
                attempt = review.attempt
                if attempt is None:
                    raise ValueError("Windows Worker attempt is absent")
                c5 = tuple(
                    item
                    for item in CodingWindowsWorkerActivationStateJournal(
                        product
                    ).retained_attempts_read_only()
                    if item.attempt_id == args.attempt_id
                )
                document = {
                    "attemptId": args.attempt_id,
                    "supervisorPhase": attempt.supervisor_phase,
                    "nativePhase": attempt.native_phase,
                    "nativeJobAbsent": review.native_job_absent,
                    "orphanLeaseCount": len(review.orphan_leases),
                    "payloadRetained": attempt.payload_directory_identity is not None,
                    "c5Phase": c5[0].phase if len(c5) == 1 else None,
                }
            else:
                settled = recover_coding_windows_product_worker_crash_attempt(
                    product, attempt_id=args.attempt_id
                )
                document = {
                    "attemptId": settled.attempt_id,
                    "c5Phase": settled.phase,
                    "c5Revision": settled.last_seen_revision,
                }
        finally:
            owner.close()
    except (OSError, RuntimeError, ValueError, PackageNotFoundError) as error:
        reason = getattr(error, "code", None)
        if not isinstance(reason, str) or _SAFE_ERROR_CODE.fullmatch(reason) is None:
            reason = "windows_worker_candidate_recovery_unavailable"
        sys.stderr.write(f"Windows Worker candidate refused: {reason}\n")
        return 1
    sys.stdout.write(json.dumps(document, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
