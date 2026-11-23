"""CLI arguments and lifecycle commands for explicitly selected Worker Wheels."""

from __future__ import annotations

import os
from argparse import ArgumentParser, Namespace, _SubParsersAction
from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Literal, Protocol, TypeVar, cast

from loushang.harness.package_product.product_local_wheel_runtime import (
    PosixLocalWheelProductSessionOwner,
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.package_product.product_runtime import (
    PackageProductSelectedManifestReadPort,
)
from loushang.harness.package_product.product_worker_candidate import (
    ProductWorkerOptInFacts,
    _capture_worker_candidate_installations,
    _change_worker_candidate_lifecycle,
    _install_worker_candidate,
    _update_worker_candidate,
    _worker_candidate_revision_matches,
)
from loushang.harness.plugin_management.package_product import (
    PackageProductRuntimeReadError,
)
from loushang.harness.resources.packages._file_consumption import (
    closing_descriptor,
    read_exact_bounded_file,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    open_windows_regular_file_at,
)
from loushang.harness.resources.packages.product_local_wheel_policy import (
    PackageProductLocalWorkerAdmissionV1,
)
from loushang.harness.worker.package_candidate import WorkerPackageCandidateV1

from .package_lifecycle import package_operator_error_code, run_package_operator_command

_CHANGE_ACTIONS = (
    "candidate-install",
    "candidate-update",
    "candidate-enable",
    "candidate-disable",
    "candidate-remove",
)
WORKER_CANDIDATE_CHANGE_ACTIONS = frozenset(_CHANGE_ACTIONS)
WORKER_CANDIDATE_OPT_IN_ACTIONS = (
    "candidate-status",
    "candidate-allow",
    "candidate-revoke",
)


def add_worker_candidate_commands(
    actions: _SubParsersAction[ArgumentParser],
    *,
    help_text: Mapping[str, str],
    native_platform_option: str | None = None,
) -> None:
    capture = actions.add_parser(
        "candidate-capture", help=help_text["candidate-capture"]
    )
    capture.add_argument("--wheel", required=True)
    capture.add_argument("--contribution-id", required=True)
    capture.add_argument("--owner-id", required=True)
    if native_platform_option is not None:
        capture.add_argument(
            "--native-platform", choices=(native_platform_option,), required=True
        )
    for action in _CHANGE_ACTIONS:
        command = actions.add_parser(action, help=help_text[action])
        command.add_argument("--plugin-id", required=True)
        if action == "candidate-update":
            command.add_argument("--from-artifact-digest", required=True)
        command.add_argument("--artifact-digest", required=True)
        command.add_argument("--operation-id", required=True)
        if action != "candidate-install":
            command.add_argument(
                "--expected-inventory-revision", type=int, required=True
            )


def add_worker_candidate_opt_in_commands(
    actions: _SubParsersAction[ArgumentParser], *, help_text: Mapping[str, str]
) -> None:
    for action in WORKER_CANDIDATE_OPT_IN_ACTIONS:
        command = actions.add_parser(action, help=help_text[action])
        command.add_argument("--plugin-id", required=True)
        if action != "candidate-status":
            command.add_argument("--operation-id", required=True)
            command.add_argument("--expected-generation", type=int, required=True)
        if action == "candidate-allow":
            command.add_argument("--require-worker", action="store_true")


def add_native_worker_review_commands(
    actions: _SubParsersAction[ArgumentParser],
    *,
    prefix: str = "",
    review_help: str,
    approve_help: str,
) -> None:
    review = actions.add_parser(prefix + "review", help=review_help)
    review.add_argument("--wheel", required=True)
    approve = actions.add_parser(prefix + "approve", help=approve_help)
    approve.add_argument("--wheel", required=True)
    approve.add_argument("--review-id", required=True)
    approve.add_argument("--operation-id", required=True)
    approve.add_argument("--expected-generation", type=int, required=True)


@dataclass(frozen=True, slots=True)
class NativeWorkerReleaseInput:
    """Freeze the bytes presented to the Product's review and approval owners."""

    label: str
    maximum_bytes: int
    native_platform: Literal["linux-x86_64", "windows-amd64"]

    def read(self, value: str) -> bytes:
        path = Path(value).expanduser().absolute()
        windows = self.native_platform == "windows-amd64"
        with ExitStack() as custody:
            if windows:
                parent = open_windows_directory(path.parent, writable=False)
                custody.enter_context(closing_descriptor(parent))
                descriptor = open_windows_regular_file_at(
                    parent, path.name, create_new=False, write=False
                )
            else:
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
            return read_exact_bounded_file(
                custody.enter_context(closing_descriptor(descriptor)),
                self.maximum_bytes,
                label=self.label,
                check_regular=not windows,
            )


class _WorkerCandidateRecord(Protocol):
    def to_dict(self) -> dict[str, object]: ...


class _CaptureWorkerCandidate(Protocol):
    def __call__(
        self, *, source: Path, admission: PackageProductLocalWorkerAdmissionV1
    ) -> _WorkerCandidateRecord: ...


class _OptInAuthority(Protocol):
    def current(self, plugin_id: str) -> _CandidateStatusDecision | None: ...

    def allow(
        self,
        *,
        plugin_id: str,
        operation_id: str,
        expected_generation: int,
        require_worker: bool,
    ) -> _WorkerCandidateRecord: ...

    def revoke(
        self, *, plugin_id: str, operation_id: str, expected_generation: int
    ) -> _WorkerCandidateRecord: ...


_LayoutT = TypeVar("_LayoutT")


@dataclass(frozen=True, slots=True)
class NativeWorkerCandidateOperator:
    """Route native candidate commands through the existing Package CLI owners."""

    product_id: str
    native_platform: Literal["linux-x86_64", "windows-amd64"]
    label: str
    error_type: Callable[[str, str], Exception]
    error_prefix: str
    not_directory: str
    refused: str
    failure_code: str
    ordinary_session_routing: str | None = None
    compact: bool = False

    def run(
        self,
        args: Namespace,
        *,
        resolve_layout: Callable[[Path], _LayoutT],
        admit: Callable[[_LayoutT], _CaptureWorkerCandidate],
        execute: Callable[[_LayoutT, Path, Namespace], dict[str, object]],
    ) -> int:
        """Keep inert capture outside the native Product application lifetime."""

        def dispatch(workspace: Path) -> dict[str, object]:
            layout = resolve_layout(workspace)
            if args.action != "candidate-capture":
                return execute(layout, workspace, args)
            binding = admit(layout)(
                source=Path(args.wheel).expanduser().absolute(),
                admission=PackageProductLocalWorkerAdmissionV1(
                    contribution_id=args.contribution_id,
                    owner_id=args.owner_id,
                    native_platform=self.native_platform,
                ),
            )
            document: dict[str, object] = {"workerCandidateBinding": binding.to_dict()}
            if self.native_platform == "linux-x86_64":
                document["candidateCapture"] = "recorded"
            document.update(productAdmission="not_checked", productUse="not_checked")
            return document

        return run_package_operator_command(
            args.workspace,
            dispatch,
            not_directory=self.not_directory,
            refused=self.refused,
            failure_reason=partial(package_operator_error_code, fallback=self.failure_code),
            compact=self.compact,
        )

    def execute_candidate_action(
        self,
        product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner,
        args: Namespace,
        *,
        opt_in_owner: Callable[[], _OptInAuthority],
    ) -> dict[str, object] | None:
        """Execute the common candidate actions before the native operator's own routes."""
        if args.action in WORKER_CANDIDATE_CHANGE_ACTIONS:
            return self._change_candidate(product, args, opt_in_owner=opt_in_owner)
        if args.action not in WORKER_CANDIDATE_OPT_IN_ACTIONS:
            return None
        owner = opt_in_owner()
        decision: _WorkerCandidateRecord | None
        if args.action == "candidate-status":
            decision = owner.current(args.plugin_id)
        elif args.action == "candidate-allow":
            decision = owner.allow(
                plugin_id=args.plugin_id,
                operation_id=args.operation_id,
                expected_generation=args.expected_generation,
                require_worker=args.require_worker,
            )
        else:
            decision = owner.revoke(
                plugin_id=args.plugin_id,
                operation_id=args.operation_id,
                expected_generation=args.expected_generation,
            )
        return worker_candidate_opt_in_document(
            decision, ordinary_session_routing=self.ordinary_session_routing
        )

    def _change_candidate(
        self,
        product: PosixLocalWheelProductSessionOwner | WindowsLocalWheelProductSessionOwner,
        args: Namespace,
        *,
        opt_in_owner: Callable[[], _OptInAuthority],
    ) -> dict[str, object]:
        label = self.label

        def require_revoked() -> None:
            decision = opt_in_owner().current(args.plugin_id)
            if decision is not None and decision.action == "allow":
                raise self.error_type(
                    f"{self.error_prefix}_candidate_opt_in_revoke_required",
                    f"{label} candidate opt-in must be revoked",
                )

        windows = self.native_platform == "windows-amd64"
        binding, snapshot, installed = _capture_worker_candidate_installations(
            product,
            args.plugin_id,
            args.artifact_digest,
            product_id=self.product_id,
            label=label,
        )
        if (
            windows
            and args.action in {"candidate-update", "candidate-disable", "candidate-remove"}
            and len(installed) != 1
        ):
            raise ValueError(f"{label} candidate installation changed")
        if len(installed) > 1:
            raise ValueError(f"{label} candidate installation is ambiguous")
        selected = installed[0] if installed else None
        revision = None if selected is None else selected.selection.package_revision
        document: dict[str, object] = (
            {}
            if windows
            else {"productSelection": "not_checked", "productUse": "not_checked"}
        )
        if args.action == "candidate-install":
            lifecycle, inventory_revision, already_installed = _install_worker_candidate(
                product,
                binding,
                snapshot,
                selected,
                product_id=self.product_id,
                plugin_id=args.plugin_id,
                operation_id=args.operation_id,
                label=label,
                reinstall_removed=not windows,
                refresh_inventory=windows,
            )
            install_result = {
                "pluginId": args.plugin_id,
                "artifactDigest": args.artifact_digest,
                "inventoryRevision": inventory_revision,
                "alreadyInstalled": already_installed,
            }
            if not windows:
                install_result["lifecycle"] = lifecycle
                document["productAdmission"] = "installed"
            return {"candidateInstall": install_result, **document}
        if args.action == "candidate-update":
            lifecycle, inventory_revision, already_updated = _update_worker_candidate(
                product,
                binding,
                snapshot,
                selected,
                args,
                product_id=self.product_id,
                label=label,
                require_revoked=require_revoked,
                error_type=self.error_type,
                error_code=f"{self.error_prefix}_candidate_update_selection_stale",
                post_selection_error_type=None if windows else self.error_type,
            )
            update_result = {
                "pluginId": args.plugin_id,
                "fromArtifactDigest": args.from_artifact_digest,
                "artifactDigest": args.artifact_digest,
                "inventoryRevision": inventory_revision,
                "alreadyUpdated": already_updated,
            }
            if not windows:
                update_result["lifecycle"] = lifecycle
                document["productAdmission"] = "installed"
            return {"candidateUpdate": update_result, **document}

        action = cast(
            Literal["enable", "disable", "remove"], args.action.removeprefix("candidate-")
        )
        if windows and action == "enable" and revision is None:
            raise ValueError(f"{label} candidate is not installed")
        if windows and action == "remove":
            require_revoked()
        if revision is not None and not _worker_candidate_revision_matches(
            revision, binding
        ):
            changed = "selection" if windows and action == "enable" else "installation"
            raise ValueError(f"{label} candidate {changed} changed")
        if not windows and action == "remove":
            require_revoked()
        if selected is None:
            raise ValueError(f"{label} candidate installation changed")
        operation, inventory_revision = _change_worker_candidate_lifecycle(
            product,
            binding,
            snapshot,
            selected,
            action=action,
            operation_id=args.operation_id,
            expected_inventory_revision=args.expected_inventory_revision,
            label=label,
            unsettled_message=(
                f"{label} candidate change did not settle"
                if windows and action != "enable"
                else f"{label} candidate enable did not settle"
            ),
        )
        if action == "remove":
            document["packageRetirement"] = "not_checked"
        return {
            "candidateManagementOperation": operation,
            "inventoryRevision": inventory_revision,
            **document,
        }


def worker_candidate_opt_in_document(
    decision: _WorkerCandidateRecord | None, *, ordinary_session_routing: str | None
) -> dict[str, object]:
    document: dict[str, object] = {
        "candidateOptInDecision": None if decision is None else decision.to_dict(),
        "defaultSessionRouting": "closed",
    }
    if ordinary_session_routing is not None:
        document["ordinarySessionRouting"] = ordinary_session_routing
    return document


class _CandidateSelectionEvidence(Protocol):
    @property
    def candidate(self) -> WorkerPackageCandidateV1: ...
    @property
    def artifact_digest(self) -> str: ...
    @property
    def native_platform(self) -> str: ...


class _CandidateStatusDecision(_WorkerCandidateRecord, Protocol):
    @property
    def action(self) -> str: ...
    @property
    def opt_in(self) -> ProductWorkerOptInFacts | None: ...


class _CandidateStatusReader(Protocol):
    @property
    def selected_manifests(self) -> PackageProductSelectedManifestReadPort: ...

    def worker_opt_in_decision(self, plugin_id: str) -> _CandidateStatusDecision | None: ...

    def selected_worker_candidate_evidence(self, plugin_id: str) -> _CandidateSelectionEvidence: ...


def worker_candidate_selection_document(
    candidate: WorkerPackageCandidateV1, *, artifact_digest: str | None = None,
) -> dict[str, object]:
    document: dict[str, object] = {"stage": "observed_in_read"}
    if artifact_digest is not None:
        document["pluginId"] = candidate.plugin_id
    document["pluginVersion"] = candidate.plugin_version
    if artifact_digest is not None:
        document["artifactDigest"] = artifact_digest
    document["executableDigest"] = candidate.executable_digest
    return document


def read_worker_candidate_status(
    owner: _CandidateStatusReader,
    plugin_id: str,
    *,
    ordinary_session_routing: str | None,
) -> dict[str, object]:
    """Join read-only selection and opt-in observations as partial evidence."""

    before = owner.selected_manifests.capture_plugin_desired_selection_for(plugin_id)
    decision_before = owner.worker_opt_in_decision(plugin_id)
    selection: dict[str, object] = {"stage": "not_selected"}
    evidence: _CandidateSelectionEvidence | None = None
    if before.desired_state == "installed_enabled":
        try:
            evidence = owner.selected_worker_candidate_evidence(plugin_id)
        except PackageProductRuntimeReadError as error:
            if error.code != "package_product_root_not_selected":
                raise
            selection = {"stage": "blocked", "reasonCode": error.code}
        else:
            selection = worker_candidate_selection_document(evidence.candidate)
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
        **worker_candidate_opt_in_document(
            decision_after, ordinary_session_routing=ordinary_session_routing
        ),
        "candidateStatusVersion": 2,
        "snapshotStatus": "stale_evidence" if stale else "partial_evidence",
        "desiredInventoryRevision": after.inventory_revision,
        "candidateSelection": selection,
        "candidateOptInAlignment": alignment,
        "productUse": "not_checked",
    }
