"""Explicit Windows Worker management and offline recovery."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import secrets
import sys
from collections.abc import Sequence
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from loushang.coding._plugin_lifecycle import (
    CodingPluginLifecycleStateLayout,
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    admit_coding_external_worker_wheel,
    open_coding_fenced_product_application_owner,
)
from loushang.coding.package_product_worker_windows_activation_state_journal import (
    CodingWindowsWorkerActivationStateJournal,
)
from loushang.coding.package_product_worker_windows_backend_release import (
    review_coding_windows_worker_backend_release,
)
from loushang.coding.package_product_worker_windows_crash_recovery import (
    recover_coding_windows_product_worker_crash_attempt,
)
from loushang.coding.package_product_worker_windows_installed_backend import (
    install_coding_windows_worker_backend_release,
)
from loushang.coding.package_product_worker_windows_native_approval_owner import (
    CodingWindowsWorkerNativeApprovalOwner,
)
from loushang.coding.package_product_worker_windows_opt_in_owner import (
    CodingWindowsWorkerProductOptInOwner,
)
from loushang.coding.package_product_worker_windows_orphan_review import (
    review_coding_windows_product_worker_orphan_runtime,
)
from loushang.coding.package_product_worker_windows_recovery_inventory import (
    inspect_coding_windows_product_worker_recovery_inventory,
)
from loushang.coding.package_product_worker_windows_stage_retirement import (
    _read_review as read_coding_windows_worker_stage_retirement_review,
)
from loushang.coding.package_product_worker_windows_stage_retirement import (
    retire_coding_windows_product_worker_complete_stage,
)
from loushang.coding.package_product_worker_windows_stage_review import (
    CodingWindowsWorkerStageReviewError,
    review_coding_windows_product_worker_complete_stage,
)
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.package_product.product_worker_candidate import (
    verify_product_selected_worker_candidate,
)
from loushang.harness.plugin_management.operations import (
    PluginManagementCommandV1,
    PluginManagementOperationEventV1,
)
from loushang.harness.plugin_management.records import PluginDesiredStateMutationV1
from loushang.harness.plugin_management.updates import PluginUpdateOperationEventV2
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleRequestV2,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
)
from loushang.harness.resources.packages.product_contract import (
    PackageProductLifecycleIntentV1,
)
from loushang.harness.resources.packages.product_handoff import (
    package_product_command_identity,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWorkerAdmissionV1,
)

_SAFE_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{1,127}\Z")
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
    capture = actions.add_parser(
        "candidate-capture", help="capture one inert Worker Wheel"
    )
    capture.add_argument("--wheel", required=True)
    capture.add_argument("--contribution-id", required=True)
    capture.add_argument("--owner-id", required=True)
    install_candidate = actions.add_parser(
        "candidate-install", help="install one captured Worker disabled"
    )
    install_candidate.add_argument("--plugin-id", required=True)
    install_candidate.add_argument("--artifact-digest", required=True)
    install_candidate.add_argument("--operation-id", required=True)
    update_candidate = actions.add_parser(
        "candidate-update", help="update one exact installed Worker revision"
    )
    update_candidate.add_argument("--plugin-id", required=True)
    update_candidate.add_argument("--from-artifact-digest", required=True)
    update_candidate.add_argument("--artifact-digest", required=True)
    update_candidate.add_argument("--operation-id", required=True)
    update_candidate.add_argument(
        "--expected-inventory-revision", type=int, required=True
    )
    enable_candidate = actions.add_parser(
        "candidate-enable", help="enable one exact installed Worker"
    )
    enable_candidate.add_argument("--plugin-id", required=True)
    enable_candidate.add_argument("--artifact-digest", required=True)
    enable_candidate.add_argument("--operation-id", required=True)
    enable_candidate.add_argument(
        "--expected-inventory-revision", type=int, required=True
    )
    for action, help_text in (
        ("candidate-disable", "disable one exact installed Worker"),
        ("candidate-remove", "remove one Worker from Desired State"),
    ):
        change = actions.add_parser(action, help=help_text)
        change.add_argument("--plugin-id", required=True)
        change.add_argument("--artifact-digest", required=True)
        change.add_argument("--operation-id", required=True)
        change.add_argument("--expected-inventory-revision", type=int, required=True)
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
    status = actions.add_parser("candidate-status", help="read one Worker opt-in")
    status.add_argument("--plugin-id", required=True)
    allow = actions.add_parser("candidate-allow", help="allow one selected Worker")
    allow.add_argument("--plugin-id", required=True)
    allow.add_argument("--operation-id", required=True)
    allow.add_argument("--expected-generation", type=int, required=True)
    allow.add_argument("--require-worker", action="store_true")
    revoke = actions.add_parser("candidate-revoke", help="revoke one Worker opt-in")
    revoke.add_argument("--plugin-id", required=True)
    revoke.add_argument("--operation-id", required=True)
    revoke.add_argument("--expected-generation", type=int, required=True)
    args = parser.parse_args(argv)
    if os.name != "nt" or platform.machine().lower() not in {"x86_64", "amd64"}:
        sys.stderr.write(
            "Windows Worker candidate refused: windows_worker_candidate_platform_closed\n"
        )
        return 1
    try:
        workspace = Path(args.workspace).expanduser().resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError("Coding workspace must be a directory")
        lifecycle = resolve_coding_plugin_lifecycle_state_layout(workspace)
        document: dict[str, object]
        if args.action == "candidate-capture":
            binding = admit_coding_external_worker_wheel(
                lifecycle,
                source=Path(args.wheel).expanduser().absolute(),
                admission=PackageProductLocalWorkerAdmissionV1(
                    contribution_id=args.contribution_id,
                    owner_id=args.owner_id,
                    native_platform="windows-amd64",
                ),
            )
            document = {
                "workerCandidateBinding": binding.to_dict(),
                "productAdmission": "not_checked",
                "productUse": "not_checked",
            }
        else:
            document = _run_product_action(lifecycle, workspace, args)
    except (OSError, RuntimeError, ValueError, PackageNotFoundError) as error:
        reason = getattr(error, "code", None)
        if not isinstance(reason, str) or _SAFE_ERROR_CODE.fullmatch(reason) is None:
            reason = "windows_worker_candidate_recovery_unavailable"
        sys.stderr.write(f"Windows Worker candidate refused: {reason}\n")
        return 1
    sys.stdout.write(json.dumps(document, sort_keys=True) + "\n")
    return 0


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
    if args.action in {"candidate-update", "candidate-disable", "candidate-remove"}:
        return _change_candidate(product, args)
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
        try:
            stage_review = review_coding_windows_product_worker_complete_stage(
                product, attempt_id=args.attempt_id
            )
        except CodingWindowsWorkerStageReviewError as error:
            if (
                args.action != "retire-normal"
                or error.code != "coding_worker_stage_review_settlement_unverified"
            ):
                raise
            with product.gc_gate.guard():
                product.assert_root_gc_authority_current()
                resumed_review = read_coding_windows_worker_stage_retirement_review(
                    product, args.attempt_id
                )
                product.assert_root_gc_authority_current()
            if resumed_review is None:
                raise
            stage_review = resumed_review
        if args.action == "review-normal":
            return {
                "normalStageReview": {
                    "attemptId": stage_review.attempt_id,
                    "reviewId": stage_review.fingerprint,
                }
            }
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
    if args.action in {"candidate-status", "candidate-allow", "candidate-revoke"}:
        opt_in = CodingWindowsWorkerProductOptInOwner(product)
        if args.action == "candidate-status":
            opt_in_decision = opt_in.current(args.plugin_id)
        elif args.action == "candidate-allow":
            opt_in_decision = opt_in.allow(
                plugin_id=args.plugin_id,
                operation_id=args.operation_id,
                expected_generation=args.expected_generation,
                require_worker=args.require_worker,
            )
        else:
            opt_in_decision = opt_in.revoke(
                plugin_id=args.plugin_id,
                operation_id=args.operation_id,
                expected_generation=args.expected_generation,
            )
        return {
            "candidateOptInDecision": (
                None if opt_in_decision is None else opt_in_decision.to_dict()
            ),
            "defaultSessionRouting": "closed",
        }
    if args.action in {"candidate-install", "candidate-enable"}:
        matching = tuple(
            binding
            for binding in product.policy.bindings
            if binding.source_trust_class == "local-worker-candidate"
            and binding.plugin_id == args.plugin_id
            and binding.artifact_digest == args.artifact_digest
        )
        if len(matching) != 1:
            raise ValueError("Windows Worker candidate is unavailable or ambiguous")
        binding = matching[0]
        snapshot = product.desired_state.snapshot()
        installed = tuple(
            item
            for item in snapshot.installations
            if item.installation_key.plugin_id == args.plugin_id
            and item.installation_key.product_id == "coding"
            and item.installation_key.installation_scope == "workspace"
        )
        if len(installed) > 1:
            raise ValueError("Windows Worker candidate installation is ambiguous")
        if args.action == "candidate-enable":
            if len(installed) != 1 or installed[0].selection.package_revision is None:
                raise ValueError("Windows Worker candidate is not installed")
            revision = installed[0].selection.package_revision
            if (
                revision.package_source_identity != binding.source_identity
                or revision.package_content_digest != binding.artifact_digest
            ):
                raise ValueError("Windows Worker candidate selection changed")
            operation = product.management.submit(
                PluginManagementCommandV1(
                    action="enable",
                    mutation=PluginDesiredStateMutationV1(
                        operation_id=args.operation_id,
                        idempotency_key=args.operation_id,
                        expected_inventory_revision=args.expected_inventory_revision,
                        installation_key=installed[0].installation_key,
                        desired_state="installed_enabled",
                        package_revision=None,
                        actor_id=product.actor_id,
                        policy_revision=product.desired_policy_revision,
                    ),
                )
            )
            if (
                operation.status != "terminal"
                or operation.result is None
                or operation.result.disposition != "succeeded"
            ):
                raise ValueError("Windows Worker candidate enable did not settle")
            return {
                "candidateManagementOperation": operation.to_dict(),
                "inventoryRevision": product.desired_state.snapshot().inventory_revision,
            }
        if installed:
            installed_revision = installed[0].selection.package_revision
            if (
                installed_revision is None
                or installed_revision.package_source_identity != binding.source_identity
                or installed_revision.package_content_digest != binding.artifact_digest
            ):
                raise ValueError("Windows Worker candidate installation changed")
            return {
                "candidateInstall": {
                    "pluginId": args.plugin_id,
                    "artifactDigest": args.artifact_digest,
                    "alreadyInstalled": True,
                    "inventoryRevision": snapshot.inventory_revision,
                }
            }
        session_id = f"worker-candidate-install-{secrets.token_hex(16)}"
        factory = product.factory_for_session(
            session_id=session_id, cwd=product.workspace, runtime_id=session_id
        )
        try:
            runtime = factory.create(
                PackageProductRuntimeRequestV1(
                    product_id="coding",
                    session_id=session_id,
                    cwd=str(product.workspace),
                )
            )
        except BaseException:
            factory.dispose_unbound_runtime()
            raise
        try:
            runtime.activate()
            routed = runtime.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id=args.operation_id,
                    action="install",
                    source=binding.source_identity,
                    scope="project",
                ),
                entrypoint="cli",
            )
            if (
                not routed.handled
                or routed.record is None
                or routed.record.lifecycle != "installed"
            ):
                raise ValueError("Windows Worker candidate install did not settle")
            selected = tuple(
                item
                for item in product.desired_state.snapshot().installations
                if item.installation_key.plugin_id == args.plugin_id
                and item.installation_key.product_id == "coding"
                and item.installation_key.installation_scope == "workspace"
            )
            if (
                len(selected) != 1
                or selected[0].selection.package_revision is None
                or selected[0].selection.package_revision.package_source_identity
                != binding.source_identity
                or selected[0].selection.package_revision.package_content_digest
                != binding.artifact_digest
            ):
                raise ValueError("Windows Worker candidate install selection changed")
            return {
                "candidateInstall": {
                    "pluginId": args.plugin_id,
                    "artifactDigest": args.artifact_digest,
                    "alreadyInstalled": False,
                    "inventoryRevision": product.desired_state.snapshot().inventory_revision,
                }
            }
        finally:
            runtime.dispose_runtime()
    raise ValueError("Windows Worker candidate action is unsupported")


def _read_candidate_selection(
    product: WindowsLocalWheelProductSessionOwner, plugin_id: str
) -> dict[str, object]:
    """Verify selected Product bytes without issuing a Worker-use receipt."""

    installed = tuple(
        item
        for item in product.desired_state.snapshot().installations
        if item.installation_key.product_id == "coding"
        and item.installation_key.installation_scope == "workspace"
        and item.installation_key.plugin_id == plugin_id
        and item.selection.desired_state == "installed_enabled"
        and item.selection.package_revision is not None
    )
    if len(installed) != 1:
        raise ValueError("Windows Worker candidate selection is unavailable")
    revision = installed[0].selection.package_revision
    assert revision is not None
    bindings = tuple(
        binding
        for binding in product.policy.bindings
        if binding.plugin_id == plugin_id
        and binding.source_trust_class == "local-worker-candidate"
        and binding.worker_admission is not None
        and binding.source_identity == revision.package_source_identity
        and binding.artifact_digest == revision.package_content_digest
    )
    if len(bindings) != 1:
        raise ValueError("Windows Worker candidate selection is unavailable")
    binding = bindings[0]
    admission = binding.worker_admission
    assert admission is not None
    session_id = f"worker-candidate-selection-{secrets.token_hex(16)}"
    factory = product.factory_for_session(
        session_id=session_id, cwd=product.workspace, runtime_id=session_id
    )
    try:
        runtime = factory.create(
            PackageProductRuntimeRequestV1(
                product_id="coding", session_id=session_id, cwd=str(product.workspace)
            )
        )
    except BaseException:
        factory.dispose_unbound_runtime()
        raise
    try:
        runtime.activate()
        selected = runtime.capture_selected_plugin_manifest_for(
            plugin_id, max_files=16, max_total_bytes=16 * 1024 * 1024
        )
        revision = selected.snapshot.package_revision
        if (
            revision.package_source_identity != binding.source_identity
            or revision.package_content_digest != binding.artifact_digest
            or selected.snapshot.root_ref.artifact_digest != binding.artifact_digest
        ):
            raise ValueError("Windows Worker candidate selection changed")
        candidate = verify_product_selected_worker_candidate(
            selected,
            contribution_id=admission.contribution_id,
            native_platform="windows-amd64",
        )
        if candidate.owner_id != admission.owner_id:
            raise ValueError("Windows Worker candidate owner changed")
        return {
            "candidateSelection": {
                "stage": "observed_in_read",
                "pluginId": candidate.plugin_id,
                "pluginVersion": candidate.plugin_version,
                "artifactDigest": binding.artifact_digest,
                "executableDigest": candidate.executable_digest,
            },
            "productUse": "not_checked",
        }
    finally:
        runtime.dispose_runtime()


def _change_candidate(
    product: WindowsLocalWheelProductSessionOwner, args: argparse.Namespace
) -> dict[str, object]:
    matching = tuple(
        binding
        for binding in product.policy.bindings
        if binding.source_trust_class == "local-worker-candidate"
        and binding.plugin_id == args.plugin_id
        and binding.artifact_digest == args.artifact_digest
    )
    if len(matching) != 1:
        raise ValueError("Windows Worker candidate is unavailable or ambiguous")
    binding = matching[0]
    snapshot = product.desired_state.snapshot()
    installed = tuple(
        item
        for item in snapshot.installations
        if item.installation_key.plugin_id == args.plugin_id
        and item.installation_key.product_id == "coding"
        and item.installation_key.installation_scope == "workspace"
    )
    if len(installed) != 1:
        raise ValueError("Windows Worker candidate installation changed")
    selected = installed[0]
    revision = selected.selection.package_revision
    if args.action == "candidate-update":
        request = PackageLifecycleJournal(
            product.state_root / "lifecycle.jsonl"
        ).request(args.operation_id)
        prior_update = None
        if (
            isinstance(request, PackageLifecycleRequestV2)
            and request.action == "update"
            and request.requested_plugin_id == args.plugin_id
            and request.canonical_source_identity == binding.source_identity
        ):
            command_id, _ = package_product_command_identity(
                args.operation_id, request.request_fingerprint
            )
            prior_update = product.management.operation(command_id)
        if (
            isinstance(prior_update, PluginUpdateOperationEventV2)
            and revision is not None
            and prior_update.status == "terminal"
            and prior_update.result is not None
            and prior_update.result.disposition in {"succeeded", "restart_required"}
            and prior_update.result.transition is not None
            and prior_update.command.installation_key == selected.installation_key
            and prior_update.command.expected_inventory_revision
            == args.expected_inventory_revision
            and prior_update.command.expected_package_revision.package_content_digest
            == args.from_artifact_digest
            and prior_update.command.staged_package_revision.package_source_identity
            == binding.source_identity
            and prior_update.command.staged_package_revision.package_content_digest
            == args.artifact_digest
            and prior_update.result.transition.committed_state == selected
            and prior_update.result.transition.inventory_revision
            == snapshot.inventory_revision
        ):
            _require_candidate_revoked(product, args.plugin_id)
            return {
                "candidateUpdate": {
                    "pluginId": args.plugin_id,
                    "fromArtifactDigest": args.from_artifact_digest,
                    "artifactDigest": args.artifact_digest,
                    "inventoryRevision": snapshot.inventory_revision,
                    "alreadyUpdated": True,
                }
            }
        if (
            snapshot.inventory_revision != args.expected_inventory_revision
            or revision is None
            or revision.package_content_digest != args.from_artifact_digest
            or args.from_artifact_digest == args.artifact_digest
            or selected.selection.desired_state
            not in {"installed_enabled", "installed_disabled"}
        ):
            raise WindowsWorkerCandidateCommandError(
                "windows_worker_candidate_update_selection_stale",
                "Windows Worker candidate update selection changed",
            )
        _require_candidate_revoked(product, args.plugin_id)
        session_id = f"worker-candidate-update-{secrets.token_hex(16)}"
        factory = product.factory_for_session(
            session_id=session_id, cwd=product.workspace, runtime_id=session_id
        )
        try:
            runtime = factory.create(
                PackageProductRuntimeRequestV1(
                    product_id="coding",
                    session_id=session_id,
                    cwd=str(product.workspace),
                )
            )
        except BaseException:
            factory.dispose_unbound_runtime()
            raise
        try:
            runtime.activate()
            routed = runtime.lifecycle.route(
                PackageProductLifecycleIntentV1(
                    operation_id=args.operation_id,
                    action="update",
                    source=binding.source_identity,
                    scope="project",
                ),
                entrypoint="cli",
            )
            if (
                not routed.handled
                or routed.record is None
                or routed.record.lifecycle != "installed"
            ):
                raise ValueError("Windows Worker candidate update did not settle")
            updated_snapshot = product.desired_state.snapshot()
            updated = tuple(
                item
                for item in updated_snapshot.installations
                if item.installation_key == selected.installation_key
            )
            if (
                len(updated) != 1
                or updated[0].selection.package_revision is None
                or updated[0].selection.package_revision.package_source_identity
                != binding.source_identity
                or updated[0].selection.package_revision.package_content_digest
                != binding.artifact_digest
            ):
                raise ValueError("Windows Worker candidate update selection changed")
            return {
                "candidateUpdate": {
                    "pluginId": args.plugin_id,
                    "fromArtifactDigest": args.from_artifact_digest,
                    "artifactDigest": args.artifact_digest,
                    "inventoryRevision": updated_snapshot.inventory_revision,
                    "alreadyUpdated": False,
                }
            }
        finally:
            runtime.dispose_runtime()

    if args.action == "candidate-remove":
        _require_candidate_revoked(product, args.plugin_id)
    if revision is None:
        prior = product.management.operation(args.operation_id)
        if (
            args.action != "candidate-remove"
            or selected.selection.desired_state != "absent"
            or not isinstance(prior, PluginManagementOperationEventV1)
            or prior.command.action != "remove"
            or prior.command.mutation.installation_key != selected.installation_key
            or prior.command.mutation.expected_inventory_revision
            != args.expected_inventory_revision
            or prior.status != "terminal"
            or prior.result is None
            or prior.result.disposition != "succeeded"
            or prior.result.transition is None
            or (
                previous
                := prior.result.transition.previous_state.selection.package_revision
            )
            is None
            or previous.package_source_identity != binding.source_identity
            or previous.package_content_digest != binding.artifact_digest
        ):
            raise ValueError("Windows Worker candidate removal changed")
        return {
            "candidateManagementOperation": prior.to_dict(),
            "inventoryRevision": snapshot.inventory_revision,
            "packageRetirement": "not_checked",
        }
    if (
        revision.package_source_identity != binding.source_identity
        or revision.package_content_digest != binding.artifact_digest
    ):
        raise ValueError("Windows Worker candidate installation changed")
    action: Literal["disable", "remove"] = (
        "disable" if args.action == "candidate-disable" else "remove"
    )
    desired_state: Literal["installed_disabled", "absent"] = (
        "installed_disabled" if action == "disable" else "absent"
    )
    operation = product.management.submit(
        PluginManagementCommandV1(
            action=action,
            mutation=PluginDesiredStateMutationV1(
                operation_id=args.operation_id,
                idempotency_key=args.operation_id,
                expected_inventory_revision=args.expected_inventory_revision,
                installation_key=selected.installation_key,
                desired_state=desired_state,
                package_revision=None,
                actor_id=product.actor_id,
                policy_revision=product.desired_policy_revision,
            ),
        )
    )
    if (
        operation.status != "terminal"
        or operation.result is None
        or operation.result.disposition != "succeeded"
    ):
        raise ValueError("Windows Worker candidate change did not settle")
    return {
        "candidateManagementOperation": operation.to_dict(),
        "inventoryRevision": product.desired_state.snapshot().inventory_revision,
        **({"packageRetirement": "not_checked"} if action == "remove" else {}),
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
    parent = open_windows_directory(target.parent, writable=False)
    try:
        descriptor = open_windows_regular_file_at(
            parent, target.name, create_new=False, write=False
        )
        try:
            metadata = os.fstat(descriptor)
            if not 0 < metadata.st_size <= _MAX_WHEEL_BYTES:
                raise ValueError("Windows Worker backend Wheel source is invalid")
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = os.read(descriptor, min(64 * 1024, _MAX_WHEEL_BYTES + 1 - size))
                if not chunk:
                    break
                size += len(chunk)
                if size > _MAX_WHEEL_BYTES:
                    raise ValueError("Windows Worker backend Wheel exceeds its bound")
                chunks.append(chunk)
            if size != metadata.st_size:
                raise ValueError("Windows Worker backend Wheel changed during read")
            return b"".join(chunks)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent)


if __name__ == "__main__":
    raise SystemExit(main())
