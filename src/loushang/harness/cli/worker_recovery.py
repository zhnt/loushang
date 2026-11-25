"""Operator previews and exact recovery for retained Worker attempts."""

from __future__ import annotations

from argparse import ArgumentParser, Namespace, _SubParsersAction
from collections.abc import Callable
from typing import Literal

from loushang.harness.package_product._linux_worker_recovery import (
    PosixWorkerGatedRecovery,
    RecoveryBindings,
    recover_registered_no_effect,
    settle_crash_c5,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)


def add_posix_worker_recovery_commands(
    actions: _SubParsersAction[ArgumentParser],
) -> None:
    actions.add_parser(
        "list-gated-attempts", help="list retained Product Worker start-gate attempts"
    )
    for name, help_text, evidence_args in (
        ("review-orphan-runtime", "review one crashed Product Worker runtime", ()),
        (
            "repair-orphan-runtime",
            "repair an exactly reviewed orphan lease",
            ("review-id",),
        ),
        ("review-gated-attempt", "review an offline Worker attempt and payload", ()),
        (
            "settle-gated-attempt",
            "record exact abandoned Worker process exit",
            ("review-id", "plan-id"),
        ),
        (
            "repair-payload-debt",
            "remove one settled Worker payload stage",
            ("plan-id",),
        ),
        (
            "settle-crashed-c5",
            "settle C5 after exact orphan, process, and payload recovery",
            (),
        ),
        (
            "recover-registered-no-effect",
            "recover one prior-boot Worker registered before native effect",
            (),
        ),
        ("review-empty-payload-debt", "review one empty pre-marker Worker stage", ()),
        (
            "repair-empty-payload-debt",
            "remove one reviewed empty Worker stage",
            ("plan-id",),
        ),
        (
            "review-unmarked-payload-debt",
            "review one bounded nonempty pre-marker Worker stage",
            (),
        ),
        (
            "repair-unmarked-payload-debt",
            "remove one exactly reviewed nonempty Worker stage",
            ("review-id",),
        ),
    ):
        command = actions.add_parser(name, help=help_text)
        command.add_argument("--attempt-id", required=True)
        for evidence in evidence_args:
            command.add_argument(f"--{evidence}", required=True)


_PAYLOAD_REPAIRS: dict[
    str, tuple[Literal["complete", "empty", "unmarked"], str, str]
] = {
    "repair-payload-debt": ("complete", "payloadDebtRepair", "planId"),
    "repair-empty-payload-debt": ("empty", "emptyPayloadDebtRepair", "planId"),
    "repair-unmarked-payload-debt": (
        "unmarked",
        "unmarkedPayloadDebtRepair",
        "reviewId",
    ),
}


def execute_posix_worker_recovery_action(
    product: PosixLocalWheelProductSessionOwner,
    args: Namespace,
    *,
    gated_recovery: PosixWorkerGatedRecovery,
    recovery_bindings: Callable[[], RecoveryBindings],
) -> dict[str, object] | None:
    """Keep previews read-only and route mutations through their exact owners."""
    custody = gated_recovery.custody
    if args.action == "list-gated-attempts":
        return {
            "gatedAttempts": [
                {"attemptId": record.attempt_id, "phase": record.phase}
                for record in gated_recovery.history().gates(product).attempts()
            ]
        }
    if args.action in {"review-orphan-runtime", "repair-orphan-runtime"}:
        orphan_review = gated_recovery.review_orphan(
            product, attempt_id=args.attempt_id
        )
        if args.action == "review-orphan-runtime":
            supervisor = orphan_review.gated_review.attempt_record
            return {
                "orphanRuntimeReview": {
                    "attemptId": args.attempt_id,
                    "reviewId": orphan_review.review_id,
                    "repairCandidate": orphan_review.repair_candidate,
                    "groupStatus": orphan_review.gated_review.group_status,
                    "supervisorPhase": None if supervisor is None else supervisor.phase,
                    "leaseId": (
                        None
                        if orphan_review.orphan_lease is None
                        else orphan_review.orphan_lease.lease_id
                    ),
                }
            }
        if args.review_id != orphan_review.review_id:
            raise gated_recovery.failure("orphan_runtime_review_stale")
        repaired = gated_recovery.repair_orphan(product, expected_review=orphan_review)
        return {
            "orphanRuntimeRepair": {
                "attemptId": args.attempt_id,
                "leaseId": repaired.lease_id,
                "reviewId": orphan_review.review_id,
            }
        }
    if args.action in {"review-gated-attempt", "settle-gated-attempt"}:
        gated, plan, review_id = gated_recovery.review_payload(
            product, attempt_id=args.attempt_id
        )
        if args.action == "review-gated-attempt":
            supervisor = gated.attempt_record
            return {
                "gatedRecoveryReview": {
                    "attemptId": args.attempt_id,
                    "reviewId": review_id,
                    "planId": plan.fingerprint,
                    "settlementCandidate": gated.settlement_candidate,
                    "groupStatus": gated.group_status,
                    "supervisorPhase": None if supervisor is None else supervisor.phase,
                }
            }
        if args.review_id != review_id or args.plan_id != plan.fingerprint:
            raise gated_recovery.failure("gated_recovery_review_stale")
        settled = gated_recovery.settle(
            product, expected_review=gated, expected_plan=plan
        )
        return {"gatedAttemptSettlement": settled.to_dict()}
    if args.action in _PAYLOAD_REPAIRS:
        stage, response, identifier = _PAYLOAD_REPAIRS[args.action]
        repaired_payload = custody.repair_reviewed(
            product,
            stage=stage,
            attempt_id=args.attempt_id,
            expected_fingerprint=(
                args.review_id if stage == "unmarked" else args.plan_id
            ),
            stale_error=gated_recovery.error_type,
        )
        return {
            response: {
                "attemptId": repaired_payload.attempt_id,
                identifier: repaired_payload.fingerprint,
            }
        }
    if args.action == "settle-crashed-c5":
        c5_settled = settle_crash_c5(
            recovery_bindings(), product, attempt_id=args.attempt_id
        )
        return {
            "crashedC5Settlement": {
                "attemptId": c5_settled.attempt_id,
                "ownerGeneration": c5_settled.owner_generation,
                "phase": c5_settled.phase,
            }
        }
    if args.action == "recover-registered-no-effect":
        registered_settled = recover_registered_no_effect(
            recovery_bindings(), product, attempt_id=args.attempt_id
        )
        return {
            "registeredNoEffectRecovery": {
                "attemptId": registered_settled.attempt_id,
                "ownerGeneration": registered_settled.owner_generation,
                "phase": registered_settled.phase,
                "noEffect": registered_settled.no_effect,
            }
        }
    if args.action == "review-unmarked-payload-debt":
        unmarked_review = custody.review_unmarked(product, attempt_id=args.attempt_id)
        return {
            "unmarkedPayloadDebtReview": {
                "attemptId": unmarked_review.attempt_id,
                "reviewId": unmarked_review.fingerprint,
                "members": [member.to_dict() for member in unmarked_review.members],
            }
        }
    if args.action == "review-empty-payload-debt":
        empty_plan = custody.preview_empty(product, attempt_id=args.attempt_id)
        return {
            "emptyPayloadDebtReview": {
                "attemptId": empty_plan.attempt_id,
                "planId": empty_plan.fingerprint,
            }
        }
    return None
