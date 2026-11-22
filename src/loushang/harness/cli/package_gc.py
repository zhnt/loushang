"""CLI commands for the fenced Package Store GC owner."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from hashlib import sha256

from loushang.harness.package_product.product_gc_executor import (
    PackageProductRootGcCommandV1,
)
from loushang.harness.package_product.product_root_gc_runtime import (
    LocalWheelProductRootGcOwner,
)
from loushang.harness.plugin_management.package_gc_dependency_journal import (
    PackageDependencyGcAttemptV1,
)
from loushang.harness.plugin_management.package_gc_dependency_repair import (
    PackageDependencyGcRepairResultV1,
)
from loushang.harness.plugin_management.package_gc_results import (
    PluginPackageGcAttemptV1,
)


def add_package_gc_commands(parser: argparse.ArgumentParser) -> None:
    """Register the offline commands shared by both native GC routes."""
    actions = parser.add_subparsers(dest="action", required=True)

    def add(action: str, help_text: str, *required: str) -> argparse.ArgumentParser:
        command = actions.add_parser(action, help=help_text)
        for option in required:
            command.add_argument(option, required=True)
        return command

    add("prepare", "recover and seal GC writer owners")
    add("list", "show exact candidates and durable statuses")
    add("delete", "delete one exact candidate root", "--candidate-id", "--attempt-key")
    add("retry", "retry a durable deletion start", "--reservation-id", "--attempt-key")
    add(
        "delete-dependency",
        "delete one exact orphan dependency",
        "--dependency-ref-id",
        "--settlement-id",
        "--attempt-key",
    )
    add(
        "retry-dependency",
        "retry a durable dependency deletion start",
        "--start-id",
        "--attempt-key",
    )
    add("inspect-dependency-debt", "inspect one terminal dependency debt", "--start-id")
    add(
        "inspect-dependency-repair",
        "inspect one reviewed repair lineage",
        "--review-id",
    )
    review = add(
        "review-dependency-debt",
        "record an exact terminal-debt review",
        "--start-id",
        "--terminal-attempt-id",
        "--settlement-id",
        "--error-code",
        "--remediation-reference",
    )
    review.add_argument("--prior-repair-result-id")
    add(
        "repair-dependency-debt",
        "retry one reviewed terminal debt",
        "--review-id",
        "--attempt-key",
    )


@dataclass(frozen=True, slots=True)
class PackageGcOperator:
    """Dispatch exact GC commands and preserve the Product's durable identities."""

    repair_actor: str
    repair_policy: str
    operation_domain: bytes
    operation_prefix: str

    def operation_identity(self, kind: str, *parts: str) -> str:
        identity = b"\0".join(
            (
                self.operation_domain,
                kind.encode(),
                b"\0".join(part.encode() for part in parts),
            )
        )
        digest = sha256(identity).hexdigest()
        return f"{self.operation_prefix}:{kind}:{digest}"

    def execute(
        self, gc: LocalWheelProductRootGcOwner, args: argparse.Namespace
    ) -> dict[str, object]:
        store_id = gc.product.epoch_runtime.registry.store_id
        output = self._dispatch(gc, args, store_id)
        output["storeId"] = store_id
        return output

    def _dispatch(
        self, gc: LocalWheelProductRootGcOwner, args: argparse.Namespace, store_id: str
    ) -> dict[str, object]:
        if args.action == "prepare":
            gc.prepare()
            return {"disposition": "prepared"}
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
            }
        if args.action == "inspect-dependency-debt":
            start_id = _sha256_id(args.start_id, name="dependency start id")
            inspection, debt = gc.inspect_terminal_dependency_debt(start_id)
            target = inspection.target
            if target is None:
                raise ValueError("Exact terminal dependency GC target is unavailable")
            return _dependency_attempt_output(debt, settlement_id=target.settlement_id)
        if args.action == "inspect-dependency-repair":
            review_id = _sha256_id(args.review_id, name="dependency repair review id")
            return gc.inspect_dependency_repair(review_id).to_dict()
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
                actor_id=self.repair_actor,
                policy_revision=self.repair_policy,
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
            }
        if args.action == "repair-dependency-debt":
            review_id = _sha256_id(args.review_id, name="dependency repair review id")
            attempt_key = _operator_key(args.attempt_key)
            operation_id = self.operation_identity(
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
                "settlementId": _settlement_id(result),
            }
        attempt_key = _operator_key(args.attempt_key)
        if args.action in ("delete-dependency", "retry-dependency"):
            return self._dependency_attempt(gc, args, store_id, attempt_key)
        if args.action == "delete":
            candidate_id = _sha256_id(args.candidate_id, name="candidate id")
            candidates = tuple(
                item for item in gc.candidates() if item.candidate_id == candidate_id
            )
            if len(candidates) != 1:
                raise ValueError("Exact Package GC candidate is unavailable")
            reservation_id = self.operation_identity(
                "reservation", store_id, candidate_id
            )
            attempt_id = self.operation_identity(
                "attempt", store_id, candidate_id, attempt_key
            )
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
            attempt_id = self.operation_identity(
                "retry", store_id, reservation_id, attempt_key
            )
            attempt = gc.retry_started(
                reservation_id,
                operation_id=attempt_id,
                idempotency_key=attempt_id,
            )
        else:
            raise ValueError("Unsupported Package GC command")
        return _attempt_output(attempt)

    def _dependency_attempt(
        self,
        gc: LocalWheelProductRootGcOwner,
        args: argparse.Namespace,
        store_id: str,
        attempt_key: str,
    ) -> dict[str, object]:
        if args.action == "delete-dependency":
            dependency_ref_id = _sha256_id(
                args.dependency_ref_id, name="dependency ref id"
            )
            settlement_id = _sha256_id(args.settlement_id, name="settlement id")
            operation_id = self.operation_identity(
                "dependency-delete", store_id, dependency_ref_id, attempt_key
            )
            attempt = gc.delete_dependency(
                dependency_ref_id,
                expected_settlement_id=settlement_id,
                operation_id=operation_id,
                idempotency_key=operation_id,
            )
        else:
            start_id = _sha256_id(args.start_id, name="dependency start id")
            operation_id = self.operation_identity(
                "dependency-retry", store_id, start_id, attempt_key
            )
            attempt = gc.retry_dependency(
                start_id,
                operation_id=operation_id,
                idempotency_key=operation_id,
            )
        return _dependency_attempt_output(
            attempt, settlement_id=_settlement_id(attempt)
        )


def _attempt_output(attempt: PluginPackageGcAttemptV1) -> dict[str, object]:
    return {
        "attemptId": attempt.attempt_id,
        "disposition": attempt.disposition,
        "errorCode": attempt.error_code,
        "reservationId": attempt.reservation_id,
        "settlementId": attempt.settlement_id,
    }


def _dependency_attempt_output(
    attempt: PackageDependencyGcAttemptV1, *, settlement_id: str | None
) -> dict[str, object]:
    return {
        "attemptId": attempt.attempt_id,
        "disposition": attempt.disposition,
        "errorCode": attempt.error_code,
        "startId": attempt.start_id,
        "settlementId": settlement_id,
    }


def _settlement_id(
    receipt: PackageDependencyGcAttemptV1 | PackageDependencyGcRepairResultV1,
) -> str | None:
    return None if receipt.store_result is None else receipt.store_result.settlement_id


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
