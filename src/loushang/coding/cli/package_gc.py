"""Explicit offline Package Store GC for a fenced Coding Product workspace."""

from __future__ import annotations

import argparse
import json
import os
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
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_root_gc_runtime import (
    LocalWheelProductRootGcOwner,
    open_posix_local_wheel_product_root_gc,
    open_windows_local_wheel_product_root_gc,
)
from loushang.harness.plugin_management.package_gc_dependencies import (
    PackageDependencyGcTargetV1,
)
from loushang.harness.plugin_management.package_gc_dependency_journal import (
    PackageDependencyGcAttemptV1,
)
from loushang.harness.plugin_management.package_gc_dependency_review import (
    PackageDependencyGcRepairReviewV1,
)
from loushang.harness.plugin_management.package_gc_results import (
    PluginPackageGcAttemptV1,
)

_GC_REPAIR_ACTOR = "coding:package-gc-cli"
_GC_REPAIR_POLICY = "coding:package-gc-repair-v1"
_WINDOWS_CANDIDATE_ROUTE_ADMITTED = False


class _CodingPackageGcRepairAuthority:
    def authorizes(
        self,
        review: PackageDependencyGcRepairReviewV1,
        target: PackageDependencyGcTargetV1,
    ) -> bool:
        return (
            review.actor_id == _GC_REPAIR_ACTOR
            and review.policy_revision == _GC_REPAIR_POLICY
            and review.settlement_id == target.settlement_id
        )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loushang-package-gc")
    parser.add_argument("--workspace", default=".", help="fenced Coding workspace")
    parser.add_argument(
        "--windows-candidate",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--worker-candidates",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("prepare", help="recover and seal GC writer owners")
    actions.add_parser("list", help="show exact candidates and durable statuses")
    delete = actions.add_parser("delete", help="delete one exact candidate root")
    delete.add_argument("--candidate-id", required=True)
    delete.add_argument("--attempt-key", required=True)
    retry = actions.add_parser("retry", help="retry a durable deletion start")
    retry.add_argument("--reservation-id", required=True)
    retry.add_argument("--attempt-key", required=True)
    dependency_delete = actions.add_parser(
        "delete-dependency", help="delete one exact orphan dependency"
    )
    dependency_delete.add_argument("--dependency-ref-id", required=True)
    dependency_delete.add_argument("--settlement-id", required=True)
    dependency_delete.add_argument("--attempt-key", required=True)
    dependency_retry = actions.add_parser(
        "retry-dependency", help="retry a durable dependency deletion start"
    )
    dependency_retry.add_argument("--start-id", required=True)
    dependency_retry.add_argument("--attempt-key", required=True)
    dependency_debt = actions.add_parser(
        "inspect-dependency-debt", help="inspect one terminal dependency debt"
    )
    dependency_debt.add_argument("--start-id", required=True)
    dependency_repair_status = actions.add_parser(
        "inspect-dependency-repair", help="inspect one reviewed repair lineage"
    )
    dependency_repair_status.add_argument("--review-id", required=True)
    dependency_review = actions.add_parser(
        "review-dependency-debt", help="record an exact terminal-debt review"
    )
    dependency_review.add_argument("--start-id", required=True)
    dependency_review.add_argument("--terminal-attempt-id", required=True)
    dependency_review.add_argument("--settlement-id", required=True)
    dependency_review.add_argument("--error-code", required=True)
    dependency_review.add_argument("--remediation-reference", required=True)
    dependency_review.add_argument("--prior-repair-result-id")
    dependency_repair = actions.add_parser(
        "repair-dependency-debt", help="retry one reviewed terminal debt"
    )
    dependency_repair.add_argument("--review-id", required=True)
    dependency_repair.add_argument("--attempt-key", required=True)
    args = parser.parse_args(argv)

    if (
        os.name == "nt"
        and (not args.windows_candidate or not _WINDOWS_CANDIDATE_ROUTE_ADMITTED)
    ) or (
        os.name != "nt" and (not sys.platform.startswith("linux") or args.windows_candidate)
    ):
        sys.stderr.write("Coding Package GC refused: package_gc_platform_unsupported\n")
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
            windows_candidate=args.windows_candidate,
            worker_candidates=args.worker_candidates,
        )
        try:
            product = owner.runtime_owner.product_owner
            gc = (
                open_windows_local_wheel_product_root_gc(
                    product,
                    repair_authority=_CodingPackageGcRepairAuthority(),
                )
                if isinstance(product, WindowsLocalWheelProductSessionOwner)
                else open_posix_local_wheel_product_root_gc(
                    product,
                    repair_authority=_CodingPackageGcRepairAuthority(),
                )
            )
            document = _run(gc, args)
        finally:
            owner.close()
    except (OSError, RuntimeError, ValueError, PackageNotFoundError) as error:
        reason = getattr(error, "code", None) or str(error)
        sys.stderr.write(f"Coding Package GC refused: {reason}\n")
        return 1
    sys.stdout.write(json.dumps(document, sort_keys=True) + "\n")
    return 0


def _run(
    gc: LocalWheelProductRootGcOwner, args: argparse.Namespace
) -> dict[str, object]:
    store_id = gc.product.epoch_runtime.registry.store_id
    if args.action == "prepare":
        gc.prepare()
        return {"disposition": "prepared", "storeId": store_id}
    if args.action == "list":
        snapshot = gc.operator_snapshot()
        return {
            "candidates": [
                {
                    "candidateId": item.candidate_id,
                    "pluginId": item.package_revision.plugin_id,
                }
                for item in snapshot.candidates
            ],
            "statuses": [item.to_dict() for item in snapshot.statuses],
            "dependencyRetention": [
                item.to_dict() for item in snapshot.dependency_inspections
            ],
            "dependencyRepairs": [
                item.to_dict() for item in snapshot.dependency_repairs
            ],
            "storeId": store_id,
        }
    if args.action == "inspect-dependency-debt":
        start_id = _sha256_id(args.start_id, name="dependency start id")
        inspection, debt = gc.inspect_terminal_dependency_debt(start_id)
        target = inspection.target
        if target is None:
            raise ValueError("Exact terminal dependency GC target is unavailable")
        return {
            "attemptId": debt.attempt_id,
            "disposition": debt.disposition,
            "errorCode": debt.error_code,
            "settlementId": target.settlement_id,
            "startId": debt.start_id,
            "storeId": store_id,
        }
    if args.action == "inspect-dependency-repair":
        review_id = _sha256_id(args.review_id, name="dependency repair review id")
        return {
            **gc.inspect_dependency_repair(review_id).to_dict(),
            "storeId": store_id,
        }
    if args.action == "review-dependency-debt":
        start_id = _sha256_id(args.start_id, name="dependency start id")
        terminal_attempt_id = _sha256_id(
            args.terminal_attempt_id, name="terminal dependency attempt id"
        )
        settlement_id = _sha256_id(args.settlement_id, name="settlement id")
        review = gc.record_terminal_dependency_review(
            start_id,
            expected_terminal_attempt_id=terminal_attempt_id,
            expected_settlement_id=settlement_id,
            expected_error_code=_operator_key(args.error_code),
            actor_id=_GC_REPAIR_ACTOR,
            policy_revision=_GC_REPAIR_POLICY,
            remediation_reference=_operator_key(args.remediation_reference),
            prior_repair_result_id=(
                None
                if getattr(args, "prior_repair_result_id", None) is None
                else _sha256_id(
                    args.prior_repair_result_id, name="prior repair result id"
                )
            ),
        )
        return {
            "reviewId": review.review_id,
            "startId": review.start_id,
            "terminalAttemptId": review.terminal_attempt_id,
            "settlementId": review.settlement_id,
            "storeId": store_id,
        }
    if args.action == "repair-dependency-debt":
        review_id = _sha256_id(args.review_id, name="dependency repair review id")
        attempt_key = _operator_key(args.attempt_key)
        operation_id = _operation_identity(
            "dependency-repair", store_id, review_id, attempt_key
        )
        result = gc.repair_terminal_dependency_debt(
            review_id,
            operation_id=operation_id,
            idempotency_key=operation_id,
        )
        return {
            "repairResultId": result.repair_result_id,
            "repairStartId": result.repair_start_id,
            "disposition": result.disposition,
            "errorCode": result.error_code,
            "settlementId": None
            if result.store_result is None
            else result.store_result.settlement_id,
            "storeId": store_id,
        }
    attempt_key = _operator_key(args.attempt_key)
    if args.action == "delete-dependency":
        dependency_ref_id = _sha256_id(args.dependency_ref_id, name="dependency ref id")
        settlement_id = _sha256_id(args.settlement_id, name="settlement id")
        operation_id = _operation_identity(
            "dependency-delete", store_id, dependency_ref_id, attempt_key
        )
        return _dependency_attempt_output(
            gc.delete_dependency(
                dependency_ref_id,
                expected_settlement_id=settlement_id,
                operation_id=operation_id,
                idempotency_key=operation_id,
            ),
            store_id=store_id,
        )
    if args.action == "retry-dependency":
        start_id = _sha256_id(args.start_id, name="dependency start id")
        operation_id = _operation_identity(
            "dependency-retry", store_id, start_id, attempt_key
        )
        return _dependency_attempt_output(
            gc.retry_dependency(
                start_id,
                operation_id=operation_id,
                idempotency_key=operation_id,
            ),
            store_id=store_id,
        )
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


def _dependency_attempt_output(
    attempt: PackageDependencyGcAttemptV1, *, store_id: str
) -> dict[str, object]:
    return {
        "attemptId": attempt.attempt_id,
        "disposition": attempt.disposition,
        "errorCode": attempt.error_code,
        "startId": attempt.start_id,
        "settlementId": None
        if attempt.store_result is None
        else attempt.store_result.settlement_id,
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
