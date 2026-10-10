"""Explicit Linux operator actions for Worker candidates and native release."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import secrets
import stat
import sys
from collections.abc import Sequence
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Literal

from loushang.coding._plugin_lifecycle import (
    resolve_coding_plugin_lifecycle_state_layout,
)
from loushang.coding.package_product_preview import (
    CodingFencedProductReadOnlyPreviewOwner,
    CodingWorkerCandidateReadEvidenceV1,
)
from loushang.coding.package_product_runtime import (
    CODING_PACKAGE_PRODUCT_RUNTIME_PROTOCOL_EPOCH,
    admit_coding_external_worker_wheel,
    open_coding_fenced_product_application_owner,
)
from loushang.coding.package_product_worker_crash_c5_settlement import (
    settle_coding_product_worker_crash_c5,
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
from loushang.coding.package_product_worker_opt_in import CodingWorkerOptInDecisionV1
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
from loushang.coding.package_product_worker_registered_recovery import (
    recover_coding_product_worker_registered_no_effect,
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
from loushang.harness.package_product.product_runtime import (
    PackageProductRuntimeRequestV1,
)
from loushang.harness.plugin_management.operations import (
    PluginManagementCommandV1,
    PluginManagementOperationEventV1,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.plugin_management.records import PluginDesiredStateMutationV1
from loushang.harness.plugin_management.updates import PluginUpdateOperationEventV2
from loushang.harness.resources.packages.plugin_lifecycle.journal import (
    PackageLifecycleJournal,
)
from loushang.harness.resources.packages.plugin_lifecycle.records import (
    PackageLifecycleRequestV2,
    canonical_json_bytes,
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
    candidate_install = actions.add_parser(
        "candidate-install", help="install one captured Worker candidate disabled"
    )
    candidate_install.add_argument("--plugin-id", required=True)
    candidate_install.add_argument("--artifact-digest", required=True)
    candidate_install.add_argument("--operation-id", required=True)
    candidate_update = actions.add_parser(
        "candidate-update", help="update one installed Worker from an exact revision"
    )
    candidate_update.add_argument("--plugin-id", required=True)
    candidate_update.add_argument("--from-artifact-digest", required=True)
    candidate_update.add_argument("--artifact-digest", required=True)
    candidate_update.add_argument("--operation-id", required=True)
    candidate_update.add_argument(
        "--expected-inventory-revision", type=int, required=True
    )
    candidate_enable = actions.add_parser(
        "candidate-enable", help="enable one exact installed Worker candidate"
    )
    candidate_enable.add_argument("--plugin-id", required=True)
    candidate_enable.add_argument("--artifact-digest", required=True)
    candidate_enable.add_argument("--operation-id", required=True)
    candidate_enable.add_argument(
        "--expected-inventory-revision", type=int, required=True
    )
    for action, help_text in (
        ("candidate-disable", "disable one exact installed Worker candidate"),
        ("candidate-remove", "remove one Worker candidate from Desired State"),
    ):
        candidate_change = actions.add_parser(action, help=help_text)
        candidate_change.add_argument("--plugin-id", required=True)
        candidate_change.add_argument("--artifact-digest", required=True)
        candidate_change.add_argument("--operation-id", required=True)
        candidate_change.add_argument(
            "--expected-inventory-revision", type=int, required=True
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


def _execute(
    product: PosixLocalWheelProductSessionOwner,
    args: argparse.Namespace,
) -> dict[str, object]:
    if args.action in {
        "candidate-install",
        "candidate-update",
        "candidate-enable",
        "candidate-disable",
        "candidate-remove",
    }:
        matching = tuple(
            binding
            for binding in product.policy.bindings
            if binding.source_trust_class == "local-worker-candidate"
            and binding.plugin_id == args.plugin_id
            and binding.artifact_digest == args.artifact_digest
        )
        if len(matching) != 1:
            raise ValueError("Coding Worker candidate is unavailable or ambiguous")
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
            raise ValueError("Coding Worker candidate installation is ambiguous")
        selected = installed[0] if installed else None
        selected_revision = (
            None if selected is None else selected.selection.package_revision
        )
        if args.action == "candidate-update":
            lifecycle_request = PackageLifecycleJournal(
                product.state_root / "lifecycle.jsonl"
            ).request(args.operation_id)
            prior_update = None
            if (
                isinstance(lifecycle_request, PackageLifecycleRequestV2)
                and lifecycle_request.action == "update"
                and lifecycle_request.requested_plugin_id == args.plugin_id
                and lifecycle_request.canonical_source_identity
                == binding.source_identity
            ):
                command_id, _ = package_product_command_identity(
                    args.operation_id, lifecycle_request.request_fingerprint
                )
                prior_update = product.management.operation(command_id)
            if (
                isinstance(prior_update, PluginUpdateOperationEventV2)
                and selected is not None
                and selected_revision is not None
                and prior_update.status == "terminal"
                and prior_update.result is not None
                and prior_update.result.disposition
                in {"succeeded", "restart_required"}
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
                current_opt_in = CodingWorkerProductOptInOwner(product).current(
                    args.plugin_id
                )
                if current_opt_in is not None and current_opt_in.action == "allow":
                    raise ValueError("Coding Worker candidate opt-in must be revoked")
                return {
                    "candidateUpdate": {
                        "pluginId": args.plugin_id,
                        "fromArtifactDigest": args.from_artifact_digest,
                        "artifactDigest": args.artifact_digest,
                        "lifecycle": "installed",
                        "inventoryRevision": snapshot.inventory_revision,
                        "alreadyUpdated": True,
                    },
                    "productAdmission": "installed",
                    "productSelection": "not_checked",
                    "productUse": "not_checked",
                }
            if (
                snapshot.inventory_revision != args.expected_inventory_revision
                or selected is None
                or selected_revision is None
                or selected_revision.package_content_digest != args.from_artifact_digest
                or args.from_artifact_digest == args.artifact_digest
                or selected.selection.desired_state
                not in {"installed_enabled", "installed_disabled"}
            ):
                raise ValueError("Coding Worker candidate update selection changed")
            current_opt_in = CodingWorkerProductOptInOwner(product).current(
                args.plugin_id
            )
            if current_opt_in is not None and current_opt_in.action == "allow":
                raise ValueError("Coding Worker candidate opt-in must be revoked")
            session_id = f"worker-candidate-update-{secrets.token_hex(16)}"
            factory = product.factory_for_session(
                session_id=session_id,
                cwd=product.workspace,
                runtime_id=session_id,
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
                    raise ValueError("Coding Worker candidate update did not settle")
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
                    raise ValueError("Coding Worker candidate update selection changed")
                return {
                    "candidateUpdate": {
                        "pluginId": args.plugin_id,
                        "fromArtifactDigest": args.from_artifact_digest,
                        "artifactDigest": args.artifact_digest,
                        "lifecycle": routed.record.lifecycle,
                        "inventoryRevision": updated_snapshot.inventory_revision,
                        "alreadyUpdated": False,
                    },
                    "productAdmission": "installed",
                    "productSelection": "not_checked",
                    "productUse": "not_checked",
                }
            finally:
                runtime.dispose_runtime()
        if selected_revision is not None and (
            selected_revision.package_source_identity != binding.source_identity
            or selected_revision.package_content_digest != binding.artifact_digest
        ):
            raise ValueError("Coding Worker candidate installation changed")
        if args.action == "candidate-install":
            if selected_revision is not None:
                return {
                    "candidateInstall": {
                        "pluginId": args.plugin_id,
                        "artifactDigest": args.artifact_digest,
                        "lifecycle": "installed",
                        "inventoryRevision": snapshot.inventory_revision,
                        "alreadyInstalled": True,
                    },
                    "productAdmission": "installed",
                    "productSelection": "not_checked",
                    "productUse": "not_checked",
                }
            session_id = f"worker-candidate-install-{secrets.token_hex(16)}"
            factory = product.factory_for_session(
                session_id=session_id,
                cwd=product.workspace,
                runtime_id=session_id,
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
                    raise ValueError("Coding Worker candidate install did not settle")
                snapshot = product.desired_state.snapshot()
                committed = tuple(
                    item
                    for item in snapshot.installations
                    if item.installation_key.plugin_id == args.plugin_id
                    and item.installation_key.product_id == "coding"
                    and item.installation_key.installation_scope == "workspace"
                )
                if (
                    len(committed) != 1
                    or committed[0].selection.package_revision is None
                    or committed[0].selection.package_revision.package_source_identity
                    != binding.source_identity
                    or committed[0].selection.package_revision.package_content_digest
                    != binding.artifact_digest
                ):
                    raise ValueError(
                        "Coding Worker candidate install selection changed"
                    )
                return {
                    "candidateInstall": {
                        "pluginId": args.plugin_id,
                        "artifactDigest": args.artifact_digest,
                        "lifecycle": routed.record.lifecycle,
                        "inventoryRevision": snapshot.inventory_revision,
                        "alreadyInstalled": False,
                    },
                    "productAdmission": "installed",
                    "productSelection": "not_checked",
                    "productUse": "not_checked",
                }
            finally:
                runtime.dispose_runtime()
        if args.action == "candidate-remove":
            current_opt_in = CodingWorkerProductOptInOwner(product).current(
                args.plugin_id
            )
            if current_opt_in is not None and current_opt_in.action == "allow":
                raise ValueError("Coding Worker candidate opt-in must be revoked")
        if selected is None:
            raise ValueError("Coding Worker candidate installation changed")
        if selected_revision is None:
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
                raise ValueError("Coding Worker candidate removal changed")
            return {
                "candidateManagementOperation": prior.to_dict(),
                "inventoryRevision": snapshot.inventory_revision,
                "productSelection": "not_checked",
                "productUse": "not_checked",
                "packageRetirement": "not_checked",
            }
        desired_action: Literal["enable", "disable", "remove"]
        desired_state: Literal["installed_enabled", "installed_disabled", "absent"]
        if args.action == "candidate-enable":
            desired_action, desired_state = "enable", "installed_enabled"
        elif args.action == "candidate-disable":
            desired_action, desired_state = "disable", "installed_disabled"
        else:
            desired_action, desired_state = "remove", "absent"
        operation = product.management.submit(
            PluginManagementCommandV1(
                action=desired_action,
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
            raise ValueError("Coding Worker candidate enable did not settle")
        return {
            "candidateManagementOperation": operation.to_dict(),
            "inventoryRevision": product.desired_state.snapshot().inventory_revision,
            "productSelection": "not_checked",
            "productUse": "not_checked",
            **(
                {"packageRetirement": "not_checked"}
                if args.action == "candidate-remove"
                else {}
            ),
        }
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
        settled = recover_coding_product_worker_registered_no_effect(
            product, attempt_id=args.attempt_id
        )
        return {
            "registeredNoEffectRecovery": {
                "attemptId": settled.attempt_id,
                "ownerGeneration": settled.owner_generation,
                "phase": settled.phase,
                "noEffect": settled.no_effect,
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
