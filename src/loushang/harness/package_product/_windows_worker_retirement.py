"""Complete Windows stage retirement using the original record and deletion owners.

These fixed Product operations add no lifecycle registry or durable state. The
caller retains Product admission; this program holds original quiescence/GC/root
custody through replay, proof, exact member deletion and receipt publication.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, Protocol, TypeVar, cast

from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    windows_listdir_at,
)
from loushang.harness.worker.history._windows_recovery import (
    WindowsRecoveryAttemptV1,
    _WindowsStageRetirementReceiptMethods,
)
from loushang.harness.worker.history._windows_semantic_contracts import (
    _LaunchIntentFacts,
    launch_matches_intent,
    native_matches_intent,
)
from loushang.harness.worker.history._windows_sources import (
    WINDOWS_WORKER_RETIREMENT_NAME,
    WINDOWS_WORKER_RETIREMENT_NAME_PREFIXES,
    WINDOWS_WORKER_RETIREMENT_STEMS,
)
from loushang.harness.worker.history._windows_stage_review_wire import (
    _WindowsCompleteStageReviewMethods,
)
from loushang.harness.worker.payload._windows_stage_io import WindowsStageInspection
from loushang.harness.worker.payload._windows_stage_retirement import (
    CompleteStageProof,
    WindowsStageRetirement,
)

from ._windows_worker_recovery import ReadWindowsRecoveryInventory
from ._worker_windows_attempt import (
    WindowsWorkerRetirementRecords,
    _StageCaptureIntent,
    inspect_windows_product_worker_retirement_ids,
    list_windows_worker_state_root_names,
    require_windows_worker_retirement_root,
    windows_product_worker_offline_write,
)
from .product_local_wheel_runtime import WindowsLocalWheelProductSessionOwner


class _RetirementLaunchIntent(_LaunchIntentFacts, _StageCaptureIntent, Protocol):
    pass


_ReviewT = TypeVar("_ReviewT", bound=_WindowsCompleteStageReviewMethods)
_ReviewCo = TypeVar(
    "_ReviewCo", bound=_WindowsCompleteStageReviewMethods, covariant=True
)
_ReceiptT = TypeVar("_ReceiptT", bound=_WindowsStageRetirementReceiptMethods)
_IntentT = TypeVar("_IntentT", bound=_RetirementLaunchIntent)


class _ReviewCompleteStage(Protocol[_ReviewCo]):
    def __call__(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        attempt_id: str,
        lease_owner_revision: int,
    ) -> _ReviewCo: ...


def windows_worker_stage_exists(root: int, attempt_id: str) -> bool:
    return "worker-payload-" + attempt_id in windows_listdir_at(root)


def has_other_windows_worker_retirement_artifact(
    product: WindowsLocalWheelProductSessionOwner,
    attempt_id: str,
    excluded_stem: str,
) -> bool:
    names = list_windows_worker_state_root_names(product)
    return any(
        name.casefold().startswith(
            tuple(
                f"{stem}-{phase}-{attempt_id}.json"
                for stem in WINDOWS_WORKER_RETIREMENT_STEMS
                if stem != excluded_stem
                for phase in ("retire", "root-delete", "retired")
            )
        )
        for name in names
    )


@dataclass(frozen=True, slots=True)
class WindowsProductWorkerCompleteStageRetirement(
    Generic[_ReviewT, _ReceiptT, _IntentT]
):
    """One fixed command over actual existing owners; no stage callbacks."""

    records: WindowsWorkerRetirementRecords[_ReviewT, _ReceiptT]
    io: WindowsPrivateReceiptIO
    inspect_inventory: ReadWindowsRecoveryInventory[WindowsRecoveryAttemptV1]
    read_intent: Callable[[WindowsLocalWheelProductSessionOwner, str], _IntentT | None]
    review_stage: _ReviewCompleteStage[_ReviewT]
    inspection: Callable[[], WindowsStageInspection]
    review_maximum: Callable[[], int]
    error_prefix: str

    def physical(self) -> WindowsStageRetirement:
        return WindowsStageRetirement(
            self.inspection(), self.records.error_type, self.error_prefix
        )

    def retire(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        expected_review: _ReviewT,
    ) -> _ReceiptT:
        with windows_product_worker_offline_write(
            product,
            active_error=self.records.error_type,
            active_message=self.error_prefix + "_runtime_active",
        ) as quiescence:
            with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
                require_windows_worker_retirement_root(
                    product,
                    root,
                    self.inspection,
                    self.records.error_type,
                    self.error_prefix + "_root_changed",
                )
                start = self.records.read_start(product, expected_review.attempt_id)
                completed = self.records.read_receipt(
                    product, expected_review.attempt_id
                )
                if start is None:
                    if completed is not None:
                        raise self.records.error_type(
                            self.error_prefix + "_start_missing"
                        )
                    current = self.review_stage(
                        product,
                        attempt_id=expected_review.attempt_id,
                        lease_owner_revision=quiescence.owner_revision,
                    )
                    if current != expected_review:
                        raise self.records.error_type(
                            self.error_prefix + "_review_stale"
                        )
                    self.io.write_private_receipt(
                        self.records.start_path(product, expected_review.attempt_id),
                        expected_review.to_bytes(),
                        maximum_bytes=self.review_maximum(),
                    )
                    start = self.records.read_start(product, expected_review.attempt_id)
                if start != expected_review:
                    raise self.records.error_type(self.error_prefix + "_review_stale")
                self.require_history(product, start)
                receipt = cast(Callable[..., _ReceiptT], self.records.receipt_type)(
                    attempt_id=start.attempt_id,
                    review_fingerprint=start.fingerprint,
                    stage_identity=start.stage_identity[:2],
                )
                root_delete_intent = self.records.read_root_intent(
                    product, start.attempt_id
                )
                if root_delete_intent is not None and root_delete_intent != receipt:
                    raise self.records.error_type(
                        self.error_prefix + "_root_intent_changed"
                    )
                if completed is not None:
                    if (
                        completed != receipt
                        or root_delete_intent != receipt
                        or windows_worker_stage_exists(root, start.attempt_id)
                    ):
                        raise self.records.error_type(
                            self.error_prefix + "_completed_changed"
                        )
                    return completed
                if (
                    not windows_worker_stage_exists(root, start.attempt_id)
                    and root_delete_intent is None
                ):
                    raise self.records.error_type(
                        self.error_prefix + "_stage_disappeared"
                    )
                intent = self.read_intent(product, start.attempt_id)
                if intent is None:
                    raise self.records.error_type(self.error_prefix + "_intent_missing")
                self.remove_remaining(product, root, start, intent, receipt)
                if windows_worker_stage_exists(root, start.attempt_id):
                    raise self.records.error_type(self.error_prefix + "_stage_retained")
                self.records.publish_receipt(
                    product,
                    start,
                    receipt,
                    write=self.io.write_private_receipt,
                    read=self.records.read_receipt,
                    changed_message=self.error_prefix + "_publication_changed",
                )
                return receipt

    def require_history(
        self, product: WindowsLocalWheelProductSessionOwner, review: _ReviewT
    ) -> None:
        attempts = self.inspect_inventory(product)
        matches = tuple(
            item for item in attempts if item.attempt_id == review.attempt_id
        )
        intent = self.read_intent(product, review.attempt_id)
        if (
            len(matches) != 1
            or intent is None
            or intent.fingerprint != review.intent_fingerprint
            or matches[0].native_phase != "settled"
            or matches[0].supervisor_phase != "stopped"
            or matches[0].supervisor_process_settled is not True
            or matches[0].observed_debts
            not in (
                ("payload_retained", "launch_intent_retained"),
                ("payload_missing", "launch_intent_retained"),
            )
            or matches[0].native_revision != review.native_revision
            or matches[0].supervisor_revision != review.supervisor_revision
            or not launch_matches_intent(matches[0], intent)
            or not native_matches_intent(matches[0], intent)
            or matches[0].supervisor_identity_fingerprint != intent.identity_fingerprint
            or has_other_windows_worker_retirement_artifact(
                product, review.attempt_id, "worker-stage"
            )
            or (
                matches[0].payload_directory_identity is not None
                and matches[0].payload_directory_identity != review.stage_identity[:2]
            )
        ):
            raise self.records.error_type(self.error_prefix + "_history_changed")

    def require_completed(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        attempt: WindowsRecoveryAttemptV1,
    ) -> None:
        review = self.records.read_start(product, attempt.attempt_id)
        completed = self.records.read_receipt(product, attempt.attempt_id)
        root_delete_intent = self.records.read_root_intent(product, attempt.attempt_id)
        intent = self.read_intent(product, attempt.attempt_id)
        if (
            review is None
            or completed is None
            or root_delete_intent is None
            or intent is None
            or completed != root_delete_intent
            or completed.review_fingerprint != review.fingerprint
            or completed.stage_identity != review.stage_identity[:2]
            or intent.stage_identity != completed.stage_identity
            or intent.fingerprint != review.intent_fingerprint
            or attempt.observed_debts != ("payload_missing", "launch_intent_retained")
            or attempt.native_phase != "settled"
            or attempt.supervisor_phase != "stopped"
            or attempt.supervisor_process_settled is not True
            or attempt.native_revision != review.native_revision
            or attempt.supervisor_revision != review.supervisor_revision
            or not native_matches_intent(attempt, intent)
            or attempt.supervisor_identity_fingerprint != intent.identity_fingerprint
            or not launch_matches_intent(attempt, intent)
            or attempt.launch_stage_identity != intent.stage_identity
            or has_other_windows_worker_retirement_artifact(
                product, attempt.attempt_id, "worker-stage"
            )
        ):
            raise self.records.error_type(self.error_prefix + "_history_unverified")

    def remove_remaining(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        root: int,
        review: CompleteStageProof,
        intent: _IntentT,
        receipt: _ReceiptT,
        *,
        root_delete_intent_path: Path | None = None,
        read_root_delete_intent: Callable[[], _ReceiptT | None] | None = None,
    ) -> None:
        with self.physical().complete(root, review, intent) as stage:
            if stage is None:
                return
            if windows_listdir_at(stage):
                raise self.records.error_type(self.error_prefix + "_extra_member")
            read_intent = read_root_delete_intent or (
                lambda: self.records.read_root_intent(product, review.attempt_id)
            )
            self.records.ensure_root_delete_intent(
                receipt,
                path=lambda: (
                    root_delete_intent_path
                    or self.records.root_intent_path(product, review.attempt_id)
                ),
                read=read_intent,
                write=self.io.write_private_receipt,
                changed_message=self.error_prefix + "_root_intent_changed",
            )

    def attempt_ids_from_names(self, names: tuple[str, ...]) -> frozenset[str]:
        attempts: set[str] = set()
        for name in names:
            if not name.casefold().startswith(WINDOWS_WORKER_RETIREMENT_NAME_PREFIXES):
                continue
            match = WINDOWS_WORKER_RETIREMENT_NAME.fullmatch(name)
            if match is None:
                raise self.records.error_type(self.error_prefix + "_artifact_invalid")
            attempts.add(match.group(1))
            if len(attempts) > 1024:
                raise self.records.error_type(self.error_prefix + "_capacity")
        return frozenset(attempts)

    def inspect_attempt_ids(
        self, product: WindowsLocalWheelProductSessionOwner
    ) -> frozenset[str]:
        return inspect_windows_product_worker_retirement_ids(
            product,
            inspect_names=self.attempt_ids_from_names,
            inspection=self.inspection,
            error_type=cast(type[RuntimeError], self.records.error_type),
            error_prefix=self.error_prefix,
        )
