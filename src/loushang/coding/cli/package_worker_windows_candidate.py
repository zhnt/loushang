"""Explicit Windows Worker management and offline recovery."""

from __future__ import annotations

import argparse
import os
import platform
import sys
from collections.abc import Sequence
from functools import partial
from importlib.metadata import version
from pathlib import Path

from loushang.coding.package.product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    admit_coding_external_worker_wheel,
    open_coding_fenced_product_application_owner,
)
from loushang.coding.package.product_worker_windows_activation_state_journal import (
    CodingWindowsWorkerActivationStateJournal,
)
from loushang.coding.package.product_worker_windows_backend_release import (
    review_coding_windows_worker_backend_release,
)
from loushang.coding.package.product_worker_windows_crash_recovery import (
    recover_coding_windows_product_worker_crash_attempt,
)
from loushang.coding.package.product_worker_windows_installed_backend import (
    install_coding_windows_worker_backend_release,
)
from loushang.coding.package.product_worker_windows_native_approval_owner import (
    CodingWindowsWorkerNativeApprovalOwner,
)
from loushang.coding.package.product_worker_windows_opt_in_owner import (
    CodingWindowsWorkerProductOptInOwner,
)
from loushang.coding.package.product_worker_windows_orphan_review import (
    review_coding_windows_product_worker_orphan_runtime,
)
from loushang.coding.package.product_worker_windows_recovery_inventory import (
    inspect_coding_windows_product_worker_recovery_inventory,
)
from loushang.coding.package.product_worker_windows_stage_retirement import (
    _review_for_retry,
    retire_coding_windows_product_worker_complete_stage,
)
from loushang.coding.package.product_worker_windows_stage_review import (
    CodingWindowsWorkerStageReviewError,
    review_coding_windows_product_worker_complete_stage,
)
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.harness.cli.package_lifecycle import (
    package_operator_error_code,
    run_package_operator_command,
)
from loushang.harness.cli.worker_candidate import (
    WORKER_CANDIDATE_CHANGE_ACTIONS,
    WORKER_CANDIDATE_OPT_IN_ACTIONS,
    add_worker_candidate_commands,
    add_worker_candidate_opt_in_commands,
    execute_worker_candidate_capture,
    execute_worker_candidate_change,
    execute_worker_candidate_opt_in,
    worker_candidate_selection_document,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_worker_candidate import (
    _observe_installed_worker_candidate,
)
from loushang.harness.resources.packages._file_consumption import (
    closing_descriptor,
    read_exact_bounded_file,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
)

_MAX_WHEEL_BYTES = 64 * 1024 * 1024


class WindowsWorkerCandidateCommandError(ValueError):
    """A classified operator refusal; no state transition is implied."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


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
        ("review-normal", "review one settled normal Worker stage offline"),
    ):
        command = actions.add_parser(action, help=help_text)
        command.add_argument("--attempt-id", required=True)
    retire_normal = actions.add_parser(
        "retire-normal", help="retire one exactly reviewed normal Worker stage"
    )
    retire_normal.add_argument("--attempt-id", required=True)
    retire_normal.add_argument("--review-id", required=True)
    actions.add_parser("list-attempts", help="list retained Worker recovery attempts")
    selection = actions.add_parser(
        "candidate-selection", help="read one exact selected Worker candidate"
    )
    selection.add_argument("--plugin-id", required=True)
    add_worker_candidate_commands(
        actions,
        help_text={
            "candidate-capture": "capture one inert Worker Wheel",
            "candidate-install": "install one captured Worker disabled",
            "candidate-update": "update one exact installed Worker revision",
            "candidate-enable": "enable one exact installed Worker",
            "candidate-disable": "disable one exact installed Worker",
            "candidate-remove": "remove one Worker from Desired State",
        },
    )
    actions.add_parser("release-status", help="read the exact native approval")
    review = actions.add_parser(
        "release-review", help="review the installed backend Wheel"
    )
    review.add_argument("--wheel", required=True)
    approve = actions.add_parser("release-approve", help="approve one exact review")
    approve.add_argument("--wheel", required=True)
    approve.add_argument("--review-id", required=True)
    approve.add_argument("--operation-id", required=True)
    approve.add_argument("--expected-generation", type=int, required=True)
    install_release = actions.add_parser(
        "release-install", help="install the approved backend"
    )
    install_release.add_argument("--wheel", required=True)
    install_release.add_argument("--review-id", required=True)
    revoke_release = actions.add_parser("release-revoke", help="revoke native approval")
    revoke_release.add_argument("--operation-id", required=True)
    revoke_release.add_argument("--expected-generation", type=int, required=True)
    add_worker_candidate_opt_in_commands(
        actions,
        help_text={
            "candidate-status": "read one Worker opt-in",
            "candidate-allow": "allow one selected Worker",
            "candidate-revoke": "revoke one Worker opt-in",
        },
    )
    args = parser.parse_args(argv)
    if os.name != "nt" or platform.machine().lower() not in {"x86_64", "amd64"}:
        sys.stderr.write(
            "Windows Worker candidate refused: windows_worker_candidate_platform_closed\n"
        )
        return 1

    def execute(workspace: Path) -> dict[str, object]:
        lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
        if args.action == "candidate-capture":
            return execute_worker_candidate_capture(
                partial(admit_coding_external_worker_wheel, lifecycle),
                args,
                native_platform="windows-amd64",
            )
        return _run_product_action(lifecycle, workspace, args)

    return run_package_operator_command(
        args.workspace,
        execute,
        not_directory="Coding workspace must be a directory",
        refused="Windows Worker candidate refused",
        failure_reason=partial(
            package_operator_error_code, fallback="windows_worker_candidate_recovery_unavailable"
        ),
    )


def _run_product_action(
    lifecycle: CodingPluginLifecycleStateLayout,
    workspace: Path,
    args: argparse.Namespace,
) -> dict[str, object]:
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
        elif args.action == "recover-crash":
            settled = recover_coding_windows_product_worker_crash_attempt(
                product, attempt_id=args.attempt_id
            )
            document = {
                "attemptId": settled.attempt_id,
                "c5Phase": settled.phase,
                "c5Revision": settled.last_seen_revision,
            }
        else:
            document = _execute(product, args)
    finally:
        owner.close()
    return document


def _execute(
    product: WindowsLocalWheelProductSessionOwner, args: argparse.Namespace
) -> dict[str, object]:
    if args.action == "candidate-selection":
        return _read_candidate_selection(product, args.plugin_id)
    if args.action in WORKER_CANDIDATE_CHANGE_ACTIONS:
        return execute_worker_candidate_change(
            product,
            args,
            product_id="coding",
            native_platform="windows-amd64",
            label="Windows Worker",
            require_revoked=lambda: _require_candidate_revoked(product, args.plugin_id),
            error_type=WindowsWorkerCandidateCommandError,
            stale_update_code="windows_worker_candidate_update_selection_stale",
        )
    if args.action == "list-attempts":
        return {
            "attempts": [
                {
                    "attemptId": item.attempt_id,
                    "nativePhase": item.native_phase,
                    "supervisorPhase": item.supervisor_phase,
                    "debts": list(item.observed_debts),
                }
                for item in inspect_coding_windows_product_worker_recovery_inventory(
                    product
                )
            ]
        }
    if args.action in {"review-normal", "retire-normal"}:
        review_current = partial(
            review_coding_windows_product_worker_complete_stage,
            product, attempt_id=args.attempt_id,
        )
        if args.action == "review-normal":
            stage_review = review_current()
            return {
                "normalStageReview": {
                    "attemptId": stage_review.attempt_id,
                    "reviewId": stage_review.fingerprint,
                }
            }
        stage_review = _review_for_retry(
            product, args.attempt_id,
            review_current=review_current,
            retry_error=CodingWindowsWorkerStageReviewError,
            retry_code="coding_worker_stage_review_settlement_unverified",
        )
        if args.review_id != stage_review.fingerprint:
            raise ValueError("Windows Worker normal stage review changed")
        receipt = retire_coding_windows_product_worker_complete_stage(
            product, expected_review=stage_review
        )
        return {
            "normalStageRetirement": {
                "attemptId": receipt.attempt_id,
                "reviewId": receipt.review_fingerprint,
                "stageIdentity": list(receipt.stage_identity),
            }
        }
    if args.action == "release-status":
        decision = CodingWindowsWorkerNativeApprovalOwner(product).current()
        return {"approvalDecision": None if decision is None else decision.to_dict()}
    if args.action == "release-revoke":
        decision = CodingWindowsWorkerNativeApprovalOwner(product).revoke(
            operation_id=args.operation_id,
            expected_generation=args.expected_generation,
        )
        return {"approvalDecision": decision.to_dict()}
    if args.action in {"release-review", "release-approve", "release-install"}:
        wheel = _read_wheel(Path(args.wheel))
        release_review = review_coding_windows_worker_backend_release(
            product, loushang_wheel=wheel
        )
        if args.action == "release-review":
            return {"nativeReleaseReview": release_review.to_dict()}
        if args.review_id != release_review.review_id:
            raise ValueError("Windows Worker backend review changed")
        if args.action == "release-approve":
            decision = CodingWindowsWorkerNativeApprovalOwner(product).approve(
                loushang_wheel=wheel,
                review_id=args.review_id,
                operation_id=args.operation_id,
                expected_generation=args.expected_generation,
            )
            return {"approvalDecision": decision.to_dict()}
        native_installed = install_coding_windows_worker_backend_release(
            product, loushang_wheel=wheel, review_id=args.review_id
        )
        return {
            "nativeClosure": native_installed.native_closure().to_dict(),
            "approvalGeneration": native_installed.approval_generation,
        }
    if args.action in WORKER_CANDIDATE_OPT_IN_ACTIONS:
        return execute_worker_candidate_opt_in(
            CodingWindowsWorkerProductOptInOwner(product),
            args,
            ordinary_session_routing=None,
        )
    raise ValueError("Windows Worker candidate action is unsupported")


def _read_candidate_selection(
    product: WindowsLocalWheelProductSessionOwner, plugin_id: str
) -> dict[str, object]:
    """Verify selected Product bytes without issuing a Worker-use receipt."""

    candidate, artifact_digest = _observe_installed_worker_candidate(
        product,
        plugin_id,
        product_id="coding",
        native_platform="windows-amd64",
        label="Windows Worker",
    )
    return {
        "candidateSelection": worker_candidate_selection_document(
            candidate, artifact_digest=artifact_digest,
        ),
        "productUse": "not_checked",
    }


def _require_candidate_revoked(
    product: WindowsLocalWheelProductSessionOwner, plugin_id: str
) -> None:
    decision = CodingWindowsWorkerProductOptInOwner(product).current(plugin_id)
    if decision is not None and decision.action == "allow":
        raise WindowsWorkerCandidateCommandError(
            "windows_worker_candidate_opt_in_revoke_required",
            "Windows Worker candidate opt-in must be revoked",
        )


def _read_wheel(path: Path) -> bytes:
    target = path.expanduser().absolute()
    with closing_descriptor(
        open_windows_directory(target.parent, writable=False)
    ) as parent:
        with closing_descriptor(
            open_windows_regular_file_at(
                parent, target.name, create_new=False, write=False
            )
        ) as descriptor:
            return read_exact_bounded_file(
                descriptor,
                _MAX_WHEEL_BYTES,
                label="Windows Worker backend Wheel",
                check_regular=False,
            )


if __name__ == "__main__":
    raise SystemExit(main())
