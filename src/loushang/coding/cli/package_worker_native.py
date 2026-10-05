"""Explicit Linux operator actions for an exact Product Worker native release."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import stat
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
    admit_coding_external_worker_wheel,
    open_coding_fenced_product_application_owner,
)
from loushang.coding.package_product_worker_native_approval import (
    CodingWorkerNativeApprovalJournal,
)
from loushang.coding.package_product_worker_native_install import (
    install_coding_product_worker_native_release,
    repair_coding_product_worker_native_release,
    review_coding_product_worker_native_release,
)
from loushang.coding.package_product_worker_operator_query import (
    query_coding_product_worker,
)
from loushang.coding.package_product_worker_opt_in_owner import (
    CodingWorkerProductOptInOwner,
)
from loushang.coding.package_product_worker_payload import (
    CodingWorkerPayloadDebtPlanV1,
    preview_coding_product_worker_empty_payload_debt,
    preview_coding_product_worker_payload_debt,
    read_coding_product_worker_payload_repair_intent,
    read_coding_product_worker_unmarked_payload_repair_intent,
    reopen_coding_product_worker_empty_payload_repair,
    repair_coding_product_worker_empty_payload_debt,
    repair_coding_product_worker_payload_debt,
    repair_coding_product_worker_unmarked_payload_debt,
    review_coding_product_worker_unmarked_payload_debt,
)
from loushang.coding.package_product_worker_start_gate_journal import (
    CodingWorkerStartGateJournal,
)
from loushang.coding.package_product_worker_start_gate_recovery import (
    CodingWorkerGatedRecoveryError,
    CodingWorkerGatedRecoveryReviewV1,
    repair_coding_product_worker_orphan_runtime,
    review_coding_product_worker_gated_recovery,
    review_coding_product_worker_orphan_runtime,
    settle_coding_product_worker_gated_attempt,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWorkerAdmissionV1,
)

_MAX_WHEEL_BYTES = 4 * 1024 * 1024
_SAFE_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{1,127}\Z")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loushang-worker-native")
    parser.add_argument("--workspace", default=".", help="fenced Coding workspace")
    actions = parser.add_subparsers(dest="action", required=True)
    candidate_capture = actions.add_parser(
        "candidate-capture", help="capture one inert Product Worker Wheel candidate"
    )
    candidate_capture.add_argument("--wheel", required=True)
    candidate_capture.add_argument("--contribution-id", required=True)
    candidate_capture.add_argument("--owner-id", required=True)
    candidate_capture.add_argument(
        "--native-platform", choices=("linux-x86_64",), required=True
    )
    actions.add_parser("status", help="read the current Product approval decision")
    review = actions.add_parser("review", help="verify and review one native Wheel")
    review.add_argument("--wheel", required=True)
    approve = actions.add_parser("approve", help="approve one unchanged review")
    approve.add_argument("--wheel", required=True)
    approve.add_argument("--review-id", required=True)
    approve.add_argument("--operation-id", required=True)
    approve.add_argument("--expected-generation", type=int, required=True)
    revoke = actions.add_parser("revoke", help="revoke the current release approval")
    revoke.add_argument("--operation-id", required=True)
    revoke.add_argument("--expected-generation", type=int, required=True)
    candidate_status = actions.add_parser(
        "candidate-status", help="read one explicit Product Worker opt-in decision"
    )
    candidate_status.add_argument("--plugin-id", required=True)
    candidate_allow = actions.add_parser(
        "candidate-allow",
        help="allow one selected Worker candidate, without routing Sessions",
    )
    candidate_allow.add_argument("--plugin-id", required=True)
    candidate_allow.add_argument("--operation-id", required=True)
    candidate_allow.add_argument("--expected-generation", type=int, required=True)
    candidate_allow.add_argument("--require-worker", action="store_true")
    candidate_revoke = actions.add_parser(
        "candidate-revoke", help="revoke one Product Worker candidate opt-in"
    )
    candidate_revoke.add_argument("--plugin-id", required=True)
    candidate_revoke.add_argument("--operation-id", required=True)
    candidate_revoke.add_argument("--expected-generation", type=int, required=True)
    query = actions.add_parser(
        "query", help="query an installed, selected Worker in an existing Session"
    )
    query.add_argument("--plugin-id", required=True)
    query.add_argument("--session-file", required=True)
    query.add_argument("--symbol", required=True)
    install = actions.add_parser("install", help="install the approved native Wheel")
    install.add_argument("--wheel", required=True)
    actions.add_parser("repair-install", help="finish one complete staged install")
    actions.add_parser(
        "list-gated-attempts", help="list retained Product Worker start-gate attempts"
    )
    orphan_review = actions.add_parser(
        "review-orphan-runtime", help="review one crashed Product Worker runtime"
    )
    orphan_review.add_argument("--attempt-id", required=True)
    orphan_repair = actions.add_parser(
        "repair-orphan-runtime", help="repair an exactly reviewed orphan lease"
    )
    orphan_repair.add_argument("--attempt-id", required=True)
    orphan_repair.add_argument("--review-id", required=True)
    gated_review = actions.add_parser(
        "review-gated-attempt", help="review an offline Worker attempt and payload"
    )
    gated_review.add_argument("--attempt-id", required=True)
    gated_settle = actions.add_parser(
        "settle-gated-attempt", help="record exact abandoned Worker process exit"
    )
    gated_settle.add_argument("--attempt-id", required=True)
    gated_settle.add_argument("--review-id", required=True)
    gated_settle.add_argument("--plan-id", required=True)
    payload_repair = actions.add_parser(
        "repair-payload-debt", help="remove one settled Worker payload stage"
    )
    payload_repair.add_argument("--attempt-id", required=True)
    payload_repair.add_argument("--plan-id", required=True)
    empty_review = actions.add_parser(
        "review-empty-payload-debt", help="review one empty pre-marker Worker stage"
    )
    empty_review.add_argument("--attempt-id", required=True)
    empty_repair = actions.add_parser(
        "repair-empty-payload-debt", help="remove one reviewed empty Worker stage"
    )
    empty_repair.add_argument("--attempt-id", required=True)
    empty_repair.add_argument("--plan-id", required=True)
    unmarked_review = actions.add_parser(
        "review-unmarked-payload-debt",
        help="review one bounded nonempty pre-marker Worker stage",
    )
    unmarked_review.add_argument("--attempt-id", required=True)
    unmarked_repair = actions.add_parser(
        "repair-unmarked-payload-debt",
        help="remove one exactly reviewed nonempty Worker stage",
    )
    unmarked_repair.add_argument("--attempt-id", required=True)
    unmarked_repair.add_argument("--review-id", required=True)
    args = parser.parse_args(argv)

    if os.name != "posix" or not sys.platform.startswith("linux"):
        sys.stderr.write("Coding Worker native command refused: platform_unsupported\n")
        return 1
    try:
        workspace = Path(args.workspace).expanduser().resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError("Coding workspace is not a directory")
        lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
        result: dict[str, object]
        if args.action == "candidate-capture":
            binding = admit_coding_external_worker_wheel(
                lifecycle,
                source=Path(args.wheel).expanduser().absolute(),
                admission=PackageProductLocalWorkerAdmissionV1(
                    contribution_id=args.contribution_id,
                    owner_id=args.owner_id,
                    native_platform=args.native_platform,
                ),
            )
            result = {
                "workerCandidateBinding": binding.to_dict(),
                "candidateCapture": "recorded",
                "productAdmission": "not_checked",
                "productUse": "not_checked",
            }
        else:
            application = open_coding_fenced_product_application_owner(
                lifecycle,
                workspace=workspace,
                runtime_version=version("loushang"),
                runtime_protocol_epoch=CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
                worker_candidates=True,
            )
            try:
                product = application.runtime_owner.product_owner
                if not isinstance(product, PosixLocalWheelProductSessionOwner):
                    raise ValueError("Coding Worker native Product owner is unsupported")
                result = _execute(product, args)
            finally:
                application.close()
    except (OSError, RuntimeError, ValueError, PackageNotFoundError) as error:
        reason = getattr(error, "code", None)
        if not isinstance(reason, str) or _SAFE_ERROR_CODE.fullmatch(reason) is None:
            reason = "coding_worker_native_command_unavailable"
        sys.stderr.write(f"Coding Worker native command refused: {reason}\n")
        return 1
    sys.stdout.write(json.dumps(result, sort_keys=True, separators=(",", ":")) + "\n")
    return 0


def _execute(
    product: PosixLocalWheelProductSessionOwner,
    args: argparse.Namespace,
) -> dict[str, object]:
    if args.action == "list-gated-attempts":
        return {
            "gatedAttempts": [
                {"attemptId": record.attempt_id, "phase": record.phase}
                for record in CodingWorkerStartGateJournal(product).attempts()
            ]
        }
    if args.action == "query":
        answer = asyncio.run(
            query_coding_product_worker(
                product=product,
                workspace=product.workspace,
                plugin_id=args.plugin_id,
                session_file=Path(args.session_file).expanduser(),
                symbol=args.symbol,
            )
        )
        return {"workerQuery": {"text": answer}}
    if args.action in {"candidate-status", "candidate-allow", "candidate-revoke"}:
        opt_in = CodingWorkerProductOptInOwner(product)
        if args.action == "candidate-status":
            current = opt_in.current(args.plugin_id)
            return {
                "candidateOptInDecision": (
                    None if current is None else current.to_dict()
                ),
                "ordinarySessionRouting": "python_sdk_explicit_linux",
                "defaultSessionRouting": "closed",
            }
        if args.action == "candidate-allow":
            candidate_decision = opt_in.allow(
                plugin_id=args.plugin_id,
                operation_id=args.operation_id,
                expected_generation=args.expected_generation,
                require_worker=args.require_worker,
            )
        else:
            candidate_decision = opt_in.revoke(
                plugin_id=args.plugin_id,
                operation_id=args.operation_id,
                expected_generation=args.expected_generation,
            )
        return {
            "candidateOptInDecision": candidate_decision.to_dict(),
            "ordinarySessionRouting": "python_sdk_explicit_linux",
            "defaultSessionRouting": "closed",
        }
    if args.action in {"review-orphan-runtime", "repair-orphan-runtime"}:
        orphan_review = review_coding_product_worker_orphan_runtime(
            product, attempt_id=args.attempt_id
        )
        if args.action == "review-orphan-runtime":
            return {
                "orphanRuntimeReview": {
                    "attemptId": args.attempt_id,
                    "reviewId": orphan_review.review_id,
                    "repairCandidate": orphan_review.repair_candidate,
                    "groupStatus": orphan_review.gated_review.group_status,
                    "supervisorPhase": (
                        None
                        if orphan_review.gated_review.attempt_record is None
                        else orphan_review.gated_review.attempt_record.phase
                    ),
                    "leaseId": (
                        None
                        if orphan_review.orphan_lease is None
                        else orphan_review.orphan_lease.lease_id
                    ),
                }
            }
        if args.review_id != orphan_review.review_id:
            raise CodingWorkerGatedRecoveryError(
                "coding_worker_orphan_runtime_review_stale"
            )
        repaired = repair_coding_product_worker_orphan_runtime(
            product, expected_review=orphan_review
        )
        return {
            "orphanRuntimeRepair": {
                "attemptId": args.attempt_id,
                "leaseId": repaired.lease_id,
                "reviewId": orphan_review.review_id,
            }
        }
    if args.action in {"review-gated-attempt", "settle-gated-attempt"}:
        gated = review_coding_product_worker_gated_recovery(
            product, attempt_id=args.attempt_id
        )
        plan = preview_coding_product_worker_payload_debt(
            product, attempt_id=args.attempt_id
        )
        review_id = _gated_review_id(product, gated, plan)
        if args.action == "review-gated-attempt":
            return {
                "gatedRecoveryReview": {
                    "attemptId": args.attempt_id,
                    "reviewId": review_id,
                    "planId": plan.fingerprint,
                    "settlementCandidate": gated.settlement_candidate,
                    "groupStatus": gated.group_status,
                    "supervisorPhase": (
                        None
                        if gated.attempt_record is None
                        else gated.attempt_record.phase
                    ),
                }
            }
        if args.review_id != review_id or args.plan_id != plan.fingerprint:
            raise CodingWorkerGatedRecoveryError(
                "coding_worker_gated_recovery_review_stale"
            )
        settled = settle_coding_product_worker_gated_attempt(
            product, expected_review=gated, expected_plan=plan
        )
        return {"gatedAttemptSettlement": settled.to_dict()}
    if args.action == "repair-payload-debt":
        prior_payload = read_coding_product_worker_payload_repair_intent(
            product, attempt_id=args.attempt_id
        )
        if prior_payload is not None:
            if args.plan_id != prior_payload.fingerprint:
                raise CodingWorkerGatedRecoveryError(
                    "coding_worker_payload_debt_plan_stale"
                )
            repaired_payload_prior = repair_coding_product_worker_payload_debt(
                product, expected_plan=prior_payload
            )
            return {
                "payloadDebtRepair": {
                    "attemptId": repaired_payload_prior.attempt_id,
                    "planId": repaired_payload_prior.fingerprint,
                }
            }
        plan = preview_coding_product_worker_payload_debt(
            product, attempt_id=args.attempt_id
        )
        if args.plan_id != plan.fingerprint:
            raise CodingWorkerGatedRecoveryError(
                "coding_worker_payload_debt_plan_stale"
            )
        repaired_plan = repair_coding_product_worker_payload_debt(
            product, expected_plan=plan
        )
        return {
            "payloadDebtRepair": {
                "attemptId": repaired_plan.attempt_id,
                "planId": repaired_plan.fingerprint,
            }
        }
    if args.action in {"review-unmarked-payload-debt", "repair-unmarked-payload-debt"}:
        prior_unmarked = (
            read_coding_product_worker_unmarked_payload_repair_intent(
                product, attempt_id=args.attempt_id
            )
            if args.action == "repair-unmarked-payload-debt"
            else None
        )
        unmarked_review = (
            prior_unmarked
            or review_coding_product_worker_unmarked_payload_debt(
                product, attempt_id=args.attempt_id
            )
        )
        if args.action == "review-unmarked-payload-debt":
            return {
                "unmarkedPayloadDebtReview": {
                    "attemptId": unmarked_review.attempt_id,
                    "reviewId": unmarked_review.fingerprint,
                    "members": [member.to_dict() for member in unmarked_review.members],
                }
            }
        if args.review_id != unmarked_review.fingerprint:
            raise CodingWorkerGatedRecoveryError(
                "coding_worker_payload_debt_plan_stale"
            )
        unmarked_repaired = repair_coding_product_worker_unmarked_payload_debt(
            product, expected_review=unmarked_review
        )
        return {
            "unmarkedPayloadDebtRepair": {
                "attemptId": unmarked_repaired.attempt_id,
                "reviewId": unmarked_repaired.fingerprint,
            }
        }
    if args.action in {"review-empty-payload-debt", "repair-empty-payload-debt"}:
        if args.action == "repair-empty-payload-debt":
            prior_empty = reopen_coding_product_worker_empty_payload_repair(
                product, attempt_id=args.attempt_id
            )
            if prior_empty is not None:
                if args.plan_id != prior_empty.fingerprint:
                    raise CodingWorkerGatedRecoveryError(
                        "coding_worker_payload_debt_plan_stale"
                    )
                repaired_empty_prior = repair_coding_product_worker_empty_payload_debt(
                    product, expected_plan=prior_empty
                )
                return {
                    "emptyPayloadDebtRepair": {
                        "attemptId": repaired_empty_prior.attempt_id,
                        "planId": repaired_empty_prior.fingerprint,
                    }
                }
        empty_plan = preview_coding_product_worker_empty_payload_debt(
            product, attempt_id=args.attempt_id
        )
        if args.action == "review-empty-payload-debt":
            return {
                "emptyPayloadDebtReview": {
                    "attemptId": empty_plan.attempt_id,
                    "planId": empty_plan.fingerprint,
                }
            }
        if args.plan_id != empty_plan.fingerprint:
            raise CodingWorkerGatedRecoveryError(
                "coding_worker_payload_debt_plan_stale"
            )
        repaired_empty = repair_coding_product_worker_empty_payload_debt(
            product, expected_plan=empty_plan
        )
        return {
            "emptyPayloadDebtRepair": {
                "attemptId": repaired_empty.attempt_id,
                "planId": repaired_empty.fingerprint,
            }
        }
    owner = CodingWorkerNativeApprovalJournal(product)
    if args.action == "status":
        decision = owner.current()
        return {"approvalDecision": None if decision is None else decision.to_dict()}
    if args.action == "revoke":
        decision = owner.change(
            operation_id=args.operation_id,
            expected_generation=args.expected_generation,
            action="revoke",
            approval=None,
        )
        return {"approvalDecision": decision.to_dict()}
    if args.action == "repair-install":
        decision = owner.current()
        if (
            decision is None
            or decision.action != "approve"
            or decision.approval is None
        ):
            raise ValueError("Coding Worker native release approval is absent")
        reader = repair_coding_product_worker_native_release(
            product, approval_owner=owner, approved=decision.approval
        )
        return {"nativeClosure": reader.current_closure().to_dict()}
    wheel = _read_wheel(Path(args.wheel))
    review = review_coding_product_worker_native_release(product, wheel=wheel)
    if args.action == "review":
        return {"nativeReleaseReview": review.to_dict()}
    if args.action == "approve":
        if args.review_id != review.review_id:
            raise ValueError("Coding Worker native release review changed")
        decision = owner.change(
            operation_id=args.operation_id,
            expected_generation=args.expected_generation,
            action="approve",
            approval=review.approval,
        )
        return {"approvalDecision": decision.to_dict()}
    if args.action == "install":
        decision = owner.current()
        if (
            decision is None
            or decision.action != "approve"
            or decision.approval != review.approval
        ):
            raise ValueError("Coding Worker native release approval is not current")
        reader = install_coding_product_worker_native_release(
            product,
            approval_owner=owner,
            approved=review.approval,
            wheel=wheel,
        )
        return {"nativeClosure": reader.current_closure().to_dict()}
    raise ValueError("Coding Worker native command is unsupported")


def _gated_review_id(
    product: PosixLocalWheelProductSessionOwner,
    gated: CodingWorkerGatedRecoveryReviewV1,
    plan: CodingWorkerPayloadDebtPlanV1,
) -> str:
    fence = product.epoch_runtime.cutover_result.fence
    if fence is None:
        raise ValueError("Coding Worker Product fence is unavailable")
    return sha256(
        canonical_json_bytes(
            {
                "reviewVersion": 1,
                "productScopeId": product.policy.project_scope_id,
                "storeRootIdentity": fence.fenced_root_identity,
                "attemptId": gated.attempt_id,
                "gateRecord": (
                    None if gated.gate_record is None else gated.gate_record.to_dict()
                ),
                "attemptRecord": (
                    None
                    if gated.attempt_record is None
                    else gated.attempt_record.to_dict()
                ),
                "nativeClosureCurrent": gated.native_closure_current,
                "groupStatus": gated.group_status,
                "planId": plan.fingerprint,
            }
        )
    ).hexdigest()


def _read_wheel(path: Path) -> bytes:
    target = path.expanduser().absolute()
    descriptor = os.open(target, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not 0 < metadata.st_size <= _MAX_WHEEL_BYTES
        ):
            raise ValueError("Coding Worker native Wheel source is invalid")
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, _MAX_WHEEL_BYTES + 1 - size))
            if not chunk:
                break
            size += len(chunk)
            if size > _MAX_WHEEL_BYTES:
                raise ValueError("Coding Worker native Wheel exceeds its bound")
            chunks.append(chunk)
        if size != metadata.st_size:
            raise ValueError("Coding Worker native Wheel changed during read")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    raise SystemExit(main())
