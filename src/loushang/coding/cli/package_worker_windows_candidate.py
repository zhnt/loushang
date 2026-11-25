"""Explicit Windows Worker management and offline recovery."""

from __future__ import annotations

import argparse
import os
import platform
import sys
from collections.abc import Sequence
from contextlib import closing
from functools import partial
from pathlib import Path

from loushang.coding.package.product_runtime import (
    _open_installed_product,
    admit_coding_external_worker_wheel,
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
    _HISTORY_INVENTORY,
)
from loushang.coding.package.product_worker_windows_stage_retirement import (
    _operations as _NORMAL_STAGE_RETIREMENT,
)
from loushang.coding.package.product_worker_windows_stage_review import (
    CodingWindowsWorkerStageReviewError,
    review_coding_windows_product_worker_complete_stage,
)
from loushang.coding.plugin_manager.lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.harness.cli.worker_candidate import (
    NativeWorkerCandidateOperator,
    add_native_worker_review_commands,
    add_worker_candidate_commands,
    add_worker_candidate_opt_in_commands,
    worker_candidate_selection_document,
)
from loushang.harness.cli.worker_recovery import (
    add_windows_worker_recovery_commands,
    execute_windows_worker_recovery_action,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_worker_candidate import (
    NativeWorkerReleaseInput,
    _observe_installed_worker_candidate,
)

_RELEASE_INPUT = NativeWorkerReleaseInput(
    "Windows Worker backend Wheel", 64 * 1024 * 1024, "windows-amd64"
)


class WindowsWorkerCandidateCommandError(ValueError):
    """A classified operator refusal; no state transition is implied."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


_CANDIDATE_OPERATOR = NativeWorkerCandidateOperator(
    product_id="coding",
    native_platform="windows-amd64",
    label="Windows Worker",
    error_type=WindowsWorkerCandidateCommandError,
    error_prefix="windows_worker",
    not_directory="Coding workspace must be a directory",
    refused="Windows Worker candidate refused",
    failure_code="windows_worker_candidate_recovery_unavailable",
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="loushang-worker-windows-candidate")
    parser.add_argument("--workspace", required=True, help="fenced Coding workspace")
    parser.add_argument(
        "--windows-candidate", action="store_true", help=argparse.SUPPRESS
    )
    actions = parser.add_subparsers(dest="action", required=True)
    add_windows_worker_recovery_commands(actions)
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
    add_native_worker_review_commands(
        actions,
        prefix="release-",
        review_help="review the installed backend Wheel",
        approve_help="approve one exact review",
    )
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

    return _CANDIDATE_OPERATOR.run(
        args,
        resolve_layout=resolve_coding_plugin_lifecycle_state_layout,
        admit=lambda layout: partial(admit_coding_external_worker_wheel, layout),
        execute=_run_product_action,
    )


def _run_product_action(
    lifecycle: CodingPluginLifecycleStateLayout,
    workspace: Path,
    args: argparse.Namespace,
) -> dict[str, object]:
    owner = _open_installed_product(
        lifecycle,
        workspace=workspace,
        windows_candidate=True,
        worker_candidates=True,
    )
    with closing(owner):
        product = owner.runtime_owner.product_owner
        if type(product) is not WindowsLocalWheelProductSessionOwner:
            raise ValueError("Windows Worker candidate Product is unavailable")
        if args.action in {"inspect", "recover-crash"}:
            result = _RECOVERY_OPERATOR(product, args)
            assert result is not None
            return result
        return _execute(product, args)


_RECOVERY_OPERATOR = partial(
    execute_windows_worker_recovery_action,
    histories=_HISTORY_INVENTORY,
    review_orphan=review_coding_windows_product_worker_orphan_runtime,
    recover_crash=recover_coding_windows_product_worker_crash_attempt,
    retirement=_NORMAL_STAGE_RETIREMENT,
    review_normal=review_coding_windows_product_worker_complete_stage,
    retry_error=CodingWindowsWorkerStageReviewError,
    retry_code="coding_worker_stage_review_settlement_unverified",
)


def _execute(
    product: WindowsLocalWheelProductSessionOwner, args: argparse.Namespace
) -> dict[str, object]:
    if args.action == "candidate-selection":
        return _read_candidate_selection(product, args.plugin_id)
    candidate_result = _CANDIDATE_OPERATOR.execute_candidate_action(
        product,
        args,
        opt_in_owner=lambda: CodingWindowsWorkerProductOptInOwner(product),
    )
    if candidate_result is not None:
        return candidate_result
    if args.action in {"list-attempts", "review-normal", "retire-normal"}:
        recovery_result = _RECOVERY_OPERATOR(product, args)
        assert recovery_result is not None
        return recovery_result
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
        wheel = _RELEASE_INPUT.read(args.wheel)
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
            candidate,
            artifact_digest=artifact_digest,
        ),
        "productUse": "not_checked",
    }


if __name__ == "__main__":
    raise SystemExit(main())
