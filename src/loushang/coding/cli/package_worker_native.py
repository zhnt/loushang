"""Explicit Linux operator actions for Worker candidates and native release."""

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
from typing import Literal

from loushang.coding.package.product_preview import (
    CodingFencedProductReadOnlyPreviewOwner,
    CodingWorkerCandidateReadEvidenceV1,
)
from loushang.coding.package.product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    admit_coding_external_worker_wheel,
    open_coding_fenced_product_application_owner,
)
from loushang.coding.package.product_worker_crash_c5_settlement import (
    settle_coding_product_worker_crash_c5,
)
from loushang.coding.package.product_worker_native_approval import (
    CodingWorkerNativeApprovalJournal,
)
from loushang.coding.package.product_worker_native_install import (
    install_coding_product_worker_native_release,
    repair_coding_product_worker_native_release,
    review_coding_product_worker_native_release,
)
from loushang.coding.package.product_worker_operator_query import (
    query_coding_product_worker,
)
from loushang.coding.package.product_worker_opt_in import CodingWorkerOptInDecisionV1
from loushang.coding.package.product_worker_opt_in_owner import (
    CodingWorkerProductOptInOwner,
)
from loushang.coding.package.product_worker_payload import (
    CodingWorkerPayloadDebtPlanV1,
    preview_coding_product_worker_empty_payload_debt,
    preview_coding_product_worker_payload_debt,
    repair_reviewed_coding_product_worker_payload,
    review_coding_product_worker_unmarked_payload_debt,
)
from loushang.coding.package.product_worker_registered_recovery import (
    recover_coding_product_worker_registered_no_effect,
)
from loushang.coding.package.product_worker_start_gate_journal import (
    CodingWorkerStartGateJournal,
)
from loushang.coding.package.product_worker_start_gate_recovery import (
    CodingWorkerGatedRecoveryError,
    CodingWorkerGatedRecoveryReviewV1,
    repair_coding_product_worker_orphan_runtime,
    review_coding_product_worker_gated_recovery,
    review_coding_product_worker_orphan_runtime,
    settle_coding_product_worker_gated_attempt,
)
from loushang.coding.plugin_manager.lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.harness.cli.worker_candidate import (
    WORKER_CANDIDATE_CHANGE_ACTIONS,
    add_worker_candidate_commands,
    execute_worker_candidate_change,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.resources.packages._file_consumption import read_bounded_prefix
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWorkerAdmissionV1,
)

_MAX_WHEEL_BYTES = 4 * 1024 * 1024
_SAFE_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{1,127}\Z")


class CodingWorkerNativeCandidateCommandError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loushang-worker-native")
    parser.add_argument("--workspace", default=".", help="fenced Coding workspace")
    actions = parser.add_subparsers(dest="action", required=True)
    add_worker_candidate_commands(
        actions,
        help_text={
            "candidate-capture": "capture one inert Product Worker Wheel candidate",
            "candidate-install": "install one captured Worker candidate disabled",
            "candidate-update": "update one installed Worker from an exact revision",
            "candidate-enable": "enable one exact installed Worker candidate",
            "candidate-disable": "disable one exact installed Worker candidate",
            "candidate-remove": "remove one Worker candidate from Desired State",
        },
        native_platform_option="linux-x86_64",
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
    crash_c5 = actions.add_parser(
        "settle-crashed-c5",
        help="settle C5 after exact orphan, process, and payload recovery",
    )
    crash_c5.add_argument("--attempt-id", required=True)
    registered_c5 = actions.add_parser(
        "recover-registered-no-effect",
        help="recover one prior-boot Worker registered before native effect",
    )
    registered_c5.add_argument("--attempt-id", required=True)
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
        elif args.action == "candidate-status":
            with CodingFencedProductReadOnlyPreviewOwner.open(
                lifecycle, worker_candidates=True
            ) as read_owner:
                result = _read_candidate_status_document(read_owner, args.plugin_id)
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
                    raise ValueError(
                        "Coding Worker native Product owner is unsupported"
                    )
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


def _candidate_status_document(
    decision: CodingWorkerOptInDecisionV1 | None,
) -> dict[str, object]:
    return {
        "candidateOptInDecision": None if decision is None else decision.to_dict(),
        "ordinarySessionRouting": "python_sdk_explicit_linux",
        "defaultSessionRouting": "closed",
    }


def _read_candidate_status_document(
    owner: CodingFencedProductReadOnlyPreviewOwner, plugin_id: str
) -> dict[str, object]:
    """Join read-only selection and opt-in observations as partial evidence."""

    before = owner.selected_manifests.capture_plugin_desired_selection_for(plugin_id)
    decision_before = owner.worker_opt_in_decision(plugin_id)
    selection: dict[str, object] = {"stage": "not_selected"}
    evidence: CodingWorkerCandidateReadEvidenceV1 | None = None
    if before.desired_state == "installed_enabled":
        try:
            evidence = owner.selected_worker_candidate_evidence(plugin_id)
        except PackageProductRuntimeReadError as error:
            if error.code != "package_product_root_not_selected":
                raise
            selection = {"stage": "blocked", "reasonCode": error.code}
        else:
            selected = evidence.candidate
            selection = {
                "stage": "observed_in_read",
                "pluginVersion": selected.plugin_version,
                "executableDigest": selected.executable_digest,
            }
    after = owner.selected_manifests.capture_plugin_desired_selection_for(plugin_id)
    decision_after = owner.worker_opt_in_decision(plugin_id)
    stale = (
        before.inventory_revision != after.inventory_revision
        or decision_before != decision_after
    )
    if stale:
        selection = {"stage": "stale_evidence"}
        alignment = "stale_evidence"
    elif selection["stage"] == "blocked":
        alignment = "blocked"
    elif evidence is None:
        alignment = "not_selected"
    elif decision_after is None or decision_after.action != "allow":
        alignment = "not_allowed"
    else:
        opt_in = decision_after.opt_in
        candidate = evidence.candidate
        alignment = (
            "identity_match_in_read"
            if opt_in is not None
            and opt_in.plugin_id == candidate.plugin_id
            and opt_in.contribution_id == candidate.contribution_id
            and opt_in.owner_id == candidate.owner_id
            and opt_in.artifact_digest == evidence.artifact_digest
            and opt_in.native_platform == evidence.native_platform
            else "identity_mismatch"
        )
    return {
        **_candidate_status_document(decision_after),
        "candidateStatusVersion": 2,
        "snapshotStatus": "stale_evidence" if stale else "partial_evidence",
        "desiredInventoryRevision": after.inventory_revision,
        "candidateSelection": selection,
        "candidateOptInAlignment": alignment,
        "productUse": "not_checked",
    }


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


def _require_candidate_revoked(
    product: PosixLocalWheelProductSessionOwner, plugin_id: str
) -> None:
    decision = CodingWorkerProductOptInOwner(product).current(plugin_id)
    if decision is not None and decision.action == "allow":
        raise CodingWorkerNativeCandidateCommandError(
            "coding_worker_candidate_opt_in_revoke_required",
            "Coding Worker candidate opt-in must be revoked",
        )


def _execute(
    product: PosixLocalWheelProductSessionOwner,
    args: argparse.Namespace,
) -> dict[str, object]:
    if args.action in WORKER_CANDIDATE_CHANGE_ACTIONS:
        return execute_worker_candidate_change(
            product,
            args,
            product_id="coding",
            native_platform="linux-x86_64",
            label="Coding Worker",
            require_revoked=lambda: _require_candidate_revoked(product, args.plugin_id),
            error_type=CodingWorkerNativeCandidateCommandError,
            stale_update_code="coding_worker_candidate_update_selection_stale",
        )
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
            return _candidate_status_document(opt_in.current(args.plugin_id))
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
    if args.action in _PAYLOAD_REPAIRS:
        stage, response, identifier = _PAYLOAD_REPAIRS[args.action]
        repaired_payload = repair_reviewed_coding_product_worker_payload(
            product,
            stage=stage,
            attempt_id=args.attempt_id,
            expected_fingerprint=(
                args.review_id if stage == "unmarked" else args.plan_id
            ),
            stale_error=CodingWorkerGatedRecoveryError,
        )
        return {
            response: {
                "attemptId": repaired_payload.attempt_id,
                identifier: repaired_payload.fingerprint,
            }
        }
    if args.action == "settle-crashed-c5":
        c5_settled = settle_coding_product_worker_crash_c5(
            product, attempt_id=args.attempt_id
        )
        return {
            "crashedC5Settlement": {
                "attemptId": c5_settled.attempt_id,
                "ownerGeneration": c5_settled.owner_generation,
                "phase": c5_settled.phase,
            }
        }
    if args.action == "recover-registered-no-effect":
        registered_settled = recover_coding_product_worker_registered_no_effect(
            product, attempt_id=args.attempt_id
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
        unmarked_review = review_coding_product_worker_unmarked_payload_debt(
            product, attempt_id=args.attempt_id
        )
        return {
            "unmarkedPayloadDebtReview": {
                "attemptId": unmarked_review.attempt_id,
                "reviewId": unmarked_review.fingerprint,
                "members": [member.to_dict() for member in unmarked_review.members],
            }
        }
    if args.action == "review-empty-payload-debt":
        empty_plan = preview_coding_product_worker_empty_payload_debt(
            product, attempt_id=args.attempt_id
        )
        return {
            "emptyPayloadDebtReview": {
                "attemptId": empty_plan.attempt_id,
                "planId": empty_plan.fingerprint,
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
        body = read_bounded_prefix(descriptor, _MAX_WHEEL_BYTES, chunk_size=64 * 1024)
        if len(body) > _MAX_WHEEL_BYTES:
            raise ValueError("Coding Worker native Wheel exceeds its bound")
        if len(body) != metadata.st_size:
            raise ValueError("Coding Worker native Wheel changed during read")
        return body
    finally:
        os.close(descriptor)


if __name__ == "__main__":
    raise SystemExit(main())
