"""Explicit offline Package root GC for a fenced Coding Product workspace."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    open_coding_fenced_product_application_owner,
)
from loushang.harness.package_product.product_gc_executor import (
    PackageProductRootGcCommandV1,
)
from loushang.harness.package_product.product_root_gc_runtime import (
    PosixLocalWheelProductRootGcOwner,
    open_posix_local_wheel_product_root_gc,
)
from loushang.harness.plugin_management.package_gc_results import (
    PluginPackageGcAttemptV1,
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loushang-package-gc")
    parser.add_argument("--workspace", default=".", help="fenced Coding workspace")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("prepare", help="recover and seal GC writer owners")
    actions.add_parser("list", help="show exact candidates and durable statuses")
    delete = actions.add_parser("delete", help="delete one exact candidate root")
    delete.add_argument("--candidate-id", required=True)
    delete.add_argument("--attempt-key", required=True)
    retry = actions.add_parser("retry", help="retry a durable deletion start")
    retry.add_argument("--reservation-id", required=True)
    retry.add_argument("--attempt-key", required=True)
    args = parser.parse_args(argv)

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
        )
        try:
            gc = open_posix_local_wheel_product_root_gc(
                owner.runtime_owner.product_owner
            )
            document = _run(gc, args)
        finally:
            owner.close()
    except (OSError, RuntimeError, ValueError, PackageNotFoundError) as error:
        reason = getattr(error, "code", None) or str(error)
        sys.stderr.write(f"Coding Package root GC refused: {reason}\n")
        return 1
    sys.stdout.write(json.dumps(document, sort_keys=True) + "\n")
    return 0


def _run(
    gc: PosixLocalWheelProductRootGcOwner, args: argparse.Namespace
) -> dict[str, object]:
    store_id = gc.product.epoch_runtime.registry.store_id
    if args.action == "prepare":
        gc.prepare()
        return {"disposition": "prepared", "storeId": store_id}
    if args.action == "list":
        return {
            "candidates": [
                {
                    "candidateId": item.candidate_id,
                    "pluginId": item.package_revision.plugin_id,
                }
                for item in gc.candidates()
            ],
            "statuses": [item.to_dict() for item in gc.statuses()],
            "storeId": store_id,
        }
    attempt_key = _operator_key(args.attempt_key)
    if args.action == "delete":
        candidate_id = _sha256_id(args.candidate_id, name="candidate id")
        candidates = tuple(
            item for item in gc.candidates() if item.candidate_id == candidate_id
        )
        if len(candidates) != 1:
            raise ValueError("Exact Package GC candidate is unavailable")
        reservation_id = _operation_identity("reservation", store_id, candidate_id)
        attempt_id = _operation_identity("attempt", store_id, candidate_id, attempt_key)
        attempt = gc.execute(
            PackageProductRootGcCommandV1(
                candidate=candidates[0],
                reservation_operation_id=reservation_id,
                reservation_idempotency_key=reservation_id,
                attempt_operation_id=attempt_id,
                attempt_idempotency_key=attempt_id,
            )
        )
    elif args.action == "retry":
        reservation_id = _sha256_id(args.reservation_id, name="reservation id")
        attempt_id = _operation_identity("retry", store_id, reservation_id, attempt_key)
        attempt = gc.retry_started(
            reservation_id,
            operation_id=attempt_id,
            idempotency_key=attempt_id,
        )
    else:
        raise ValueError("Unsupported Package GC command")
    return _attempt_output(attempt, store_id=store_id)


def _attempt_output(
    attempt: PluginPackageGcAttemptV1, *, store_id: str
) -> dict[str, object]:
    return {
        "attemptId": attempt.attempt_id,
        "disposition": attempt.disposition,
        "errorCode": attempt.error_code,
        "reservationId": attempt.reservation_id,
        "settlementId": attempt.settlement_id,
        "storeId": store_id,
    }


def _operator_key(value: str) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= 128
        or value.strip() != value
    ):
        raise ValueError("Package GC attempt key must have 1-128 non-edge-space chars")
    return value


def _sha256_id(value: str, *, name: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"Package GC {name} must be a lowercase SHA-256 id")
    return value


def _operation_identity(kind: str, *parts: str) -> str:
    digest = sha256(
        b"loushang.coding-package-root-gc/v1\0"
        + kind.encode()
        + b"\0"
        + b"\0".join(part.encode() for part in parts)
    ).hexdigest()
    return f"coding-package-gc:{kind}:{digest}"


if __name__ == "__main__":
    raise SystemExit(main())
