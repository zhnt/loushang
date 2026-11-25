"""Complete Windows stage retirement using the original record and deletion owners.

These fixed Product operations add no lifecycle registry or durable state. The
caller retains Product admission; this program holds original quiescence/GC/root
custody through replay, proof, exact member deletion and receipt publication.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import ClassVar, Generic, Protocol, TypeVar, cast

from loushang.harness.resources.packages._private_receipts_windows import (
    WindowsPrivateReceiptIO,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_lease_registry import (
    PackageWindowsRuntimeQuiescenceV1,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    windows_listdir_at,
)
from loushang.harness.worker._windows_provisioning_journal import (
    WindowsWorkerProvisioningAttemptV1,
)
from loushang.harness.worker.history._windows_recovery import (
    WindowsRecoveryAttemptV1,
    _valid_crash_effect_history,
    _WindowsOrphanRuntimeReviewMethods,
    _WindowsStageRetirementReceiptMethods,
)
from loushang.harness.worker.history._windows_recovery import (
    require_windows_worker_repair_record as _require_repair_record,
)
from loushang.harness.worker.history._windows_semantic_contracts import (
    _LaunchIntentFacts,
    launch_matches_intent,
    native_attempt_history_matches,
    native_attempt_identity_matches,
    native_attempts_for,
    native_matches_intent,
    no_effect_history_matches,
)
from loushang.harness.worker.history._windows_sources import (
    WINDOWS_WORKER_RETIREMENT_NAME,
    WINDOWS_WORKER_RETIREMENT_NAME_PREFIXES,
    WINDOWS_WORKER_RETIREMENT_STEMS,
)
from loushang.harness.worker.history._windows_stage_review_wire import (
    _WindowsCompleteStageReviewMethods,
    _WindowsCrashStageReviewMethods,
    _WindowsPartialStageReviewMethods,
    _WindowsReservedStageReviewMethods,
)
from loushang.harness.worker.payload._windows_stage_io import WindowsStageInspection
from loushang.harness.worker.payload._windows_stage_retirement import (
    CompleteStageProof,
    PartialWindowsStageRetirement,
    WindowsStageRetirement,
)

from ._windows_worker_recovery import (
    ReadWindowsRecoveryInventory,
    _CapturePartialReview,
    _CaptureReservedReview,
)
from ._worker_windows_attempt import (
    WindowsWorkerRetirementRecords,
    _IntentRecord,
    _RuntimeReview,
    _StageCaptureIntent,
    inspect_windows_product_worker_retirement_ids,
    list_windows_worker_state_root_names,
    require_windows_worker_retirement_root,
    windows_product_worker_offline_write,
)
from .product_local_wheel_runtime import WindowsLocalWheelProductSessionOwner


def _require_retirement_entry(
    product: WindowsLocalWheelProductSessionOwner,
    review: object,
    *,
    product_id: str | None,
    review_type: type[object],
    message: str,
    required_native_revision: int | None = None,
) -> None:
    if product_id is not None and (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != product_id
        or type(review) is not review_type
        or (
            required_native_revision is not None
            and cast(_WindowsReservedStageReviewMethods, review).native_revision
            != required_native_revision
        )
    ):
        raise OSError(message)


class _RetirementLaunchIntent(_LaunchIntentFacts, _StageCaptureIntent, Protocol):
    pass


_ReviewT = TypeVar("_ReviewT", bound=_WindowsCompleteStageReviewMethods)
_ReviewCo = TypeVar(
    "_ReviewCo", bound=_WindowsCompleteStageReviewMethods, covariant=True
)
_ReceiptT = TypeVar("_ReceiptT", bound=_WindowsStageRetirementReceiptMethods)
_IntentT = TypeVar("_IntentT", bound=_RetirementLaunchIntent)
_ReviewRecordT = TypeVar("_ReviewRecordT", bound=_IntentRecord)


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


@contextmanager
def _bound_retirement_root(
    product: WindowsLocalWheelProductSessionOwner,
    inspection: Callable[[], WindowsStageInspection],
    *,
    error_type: type[Exception],
    active_message: str,
    root_changed: str,
) -> Iterator[tuple[PackageWindowsRuntimeQuiescenceV1, int]]:
    with windows_product_worker_offline_write(
        product, active_error=error_type, active_message=active_message
    ) as quiescence:
        with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
            require_windows_worker_retirement_root(
                product, root, inspection, error_type, root_changed
            )
            yield quiescence, root


def _receipt_for_review(
    receipt_type: type[_ReceiptT],
    review: (
        _WindowsCompleteStageReviewMethods
        | _WindowsPartialStageReviewMethods
        | _WindowsReservedStageReviewMethods
        | _WindowsCrashStageReviewMethods
    ),
) -> _ReceiptT:
    return cast(Callable[..., _ReceiptT], receipt_type)(
        attempt_id=review.attempt_id,
        review_fingerprint=review.fingerprint,
        stage_identity=review.stage_identity[:2],
    )


def _require_empty_stage_delete_intent(
    records: WindowsWorkerRetirementRecords[_ReviewRecordT, _ReceiptT],
    io: WindowsPrivateReceiptIO,
    product: WindowsLocalWheelProductSessionOwner,
    stage: int | None,
    attempt_id: str,
    receipt: _ReceiptT,
    error_prefix: str,
    *,
    intent_path: Path | None = None,
    read_intent: Callable[[], _ReceiptT | None] | None = None,
) -> None:
    # The physical owner removes the directory only after this barrier returns.
    if stage is None:
        return
    if windows_listdir_at(stage):
        raise records.error_type(error_prefix + "_extra_member")
    records.ensure_root_delete_intent(
        receipt,
        path=lambda: intent_path or records.root_intent_path(product, attempt_id),
        read=read_intent or (lambda: records.read_root_intent(product, attempt_id)),
        write=io.write_private_receipt,
        changed_message=error_prefix + "_root_intent_changed",
    )


def _publish_retirement_completion(
    records: WindowsWorkerRetirementRecords[_ReviewRecordT, _ReceiptT],
    io: WindowsPrivateReceiptIO,
    product: WindowsLocalWheelProductSessionOwner,
    root: int,
    start: _ReviewRecordT,
    receipt: _ReceiptT,
    *,
    stage_error: type[Exception],
    stage_retained: str,
    publication_changed: str,
) -> _ReceiptT:
    if windows_worker_stage_exists(root, start.attempt_id):
        raise stage_error(stage_retained)
    records.publish_receipt(
        product,
        start,
        receipt,
        write=io.write_private_receipt,
        read=records.read_receipt,
        changed_message=publication_changed,
    )
    return receipt


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
    error_prefix: str

    entry_product_id: str | None = None
    entry_required_message: str = ""

    def physical(self) -> WindowsStageRetirement:
        return WindowsStageRetirement(
            self.inspection(), self.records.error_type, self.error_prefix
        )

    def retire_with_review_id(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        attempt_id: str,
        *,
        review_current: Callable[[], _ReviewT],
        review_id: str,
        retry_error: type[RuntimeError],
        retry_code: str,
    ) -> _ReceiptT:
        """Retry only a persisted review after a matching live refusal."""
        try:
            review = review_current()
        except retry_error as error:
            if getattr(error, "code", None) != retry_code:
                raise
            with product.gc_gate.guard():
                product.assert_root_gc_authority_current()
                retained = self.records.read_start(product, attempt_id)
                product.assert_root_gc_authority_current()
            if retained is None:
                raise
            review = retained
        if review_id != review.fingerprint:
            raise ValueError("Windows Worker normal stage review changed")
        return self.retire(product, expected_review=review)

    def retire(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        expected_review: _ReviewT,
    ) -> _ReceiptT:
        "Retire only the reviewed stage while Package runtime remains offline."
        _require_retirement_entry(
            product,
            expected_review,
            product_id=self.entry_product_id,
            review_type=self.records.review_type,
            message=self.entry_required_message,
        )
        with _bound_retirement_root(
            product,
            self.inspection,
            error_type=self.records.error_type,
            active_message=self.error_prefix + "_runtime_active",
            root_changed=self.error_prefix + "_root_changed",
        ) as (quiescence, root):
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
                self.records.publish_start(
                    self.records.start_path(product, expected_review.attempt_id),
                    expected_review,
                    write=self.io.write_private_receipt,
                )
                start = self.records.read_start(product, expected_review.attempt_id)
            if start != expected_review:
                raise self.records.error_type(self.error_prefix + "_review_stale")
            self.require_history(product, start)
            receipt = _receipt_for_review(self.records.receipt_type, start)
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
            return _publish_retirement_completion(
                self.records,
                self.io,
                product,
                root,
                start,
                receipt,
                stage_error=self.records.error_type,
                stage_retained=self.error_prefix + "_stage_retained",
                publication_changed=self.error_prefix + "_publication_changed",
            )

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
            _require_empty_stage_delete_intent(
                self.records,
                self.io,
                product,
                stage,
                review.attempt_id,
                receipt,
                self.error_prefix,
                intent_path=root_delete_intent_path,
                read_intent=read_root_delete_intent,
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


_PartialT = TypeVar("_PartialT", bound=_WindowsPartialStageReviewMethods)
_ReservedT = TypeVar("_ReservedT", bound=_WindowsReservedStageReviewMethods)
_CrashT = TypeVar("_CrashT", bound=_WindowsCrashStageReviewMethods)
_CrashCo = TypeVar("_CrashCo", bound=_WindowsCrashStageReviewMethods, covariant=True)
_IntentContra = TypeVar(
    "_IntentContra", bound=_RetirementLaunchIntent, contravariant=True
)
_ReceiptContra = TypeVar(
    "_ReceiptContra", bound=_WindowsStageRetirementReceiptMethods, contravariant=True
)


class _RemoveCompleteStage(Protocol[_IntentContra, _ReceiptContra]):
    def __call__(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        root: int,
        review: CompleteStageProof,
        intent: _IntentContra,
        receipt: _ReceiptContra,
        *,
        root_delete_intent_path: Path | None = None,
        read_root_delete_intent: Callable[[], _ReceiptContra | None] | None = None,
    ) -> None: ...


class _ReviewCrashStage(Protocol[_CrashCo]):
    def __call__(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        attempt_id: str,
        quiescence: PackageWindowsRuntimeQuiescenceV1,
    ) -> _CrashCo: ...


_PARTIAL_RETIRED_DEBTS = (
    "payload_missing",
    "launch_intent_missing",
    "native_history_missing",
    "supervisor_history_missing",
)
_PARTIAL_DEBTS = (
    "payload_retained",
    "launch_intent_missing",
    "native_history_missing",
    "supervisor_history_missing",
)
_UNLAUNCHED_RETIRED_DEBTS = (
    "payload_missing",
    "launch_intent_retained",
    "supervisor_history_missing",
)


_NoEffectT = TypeVar(
    "_NoEffectT",
    bound=_WindowsPartialStageReviewMethods | _WindowsReservedStageReviewMethods,
)


@dataclass(frozen=True, slots=True, kw_only=True)
class _NoEffectStageRetirement(Generic[_NoEffectT, _ReceiptT], ABC):
    """Hold the retirement transaction for stages that never started an effect."""

    records: WindowsWorkerRetirementRecords[_NoEffectT, _ReceiptT]
    io: WindowsPrivateReceiptIO
    inspection: Callable[[], WindowsStageInspection]
    error_prefix: str
    entry_product_id: str | None = None
    entry_required_message: str = ""

    required_native_revision: ClassVar[int | None] = None

    def read_start(
        self, product: WindowsLocalWheelProductSessionOwner, attempt_id: str
    ) -> _NoEffectT | None:
        return self.records.read_start(product, attempt_id)

    def other_artifact(
        self, product: WindowsLocalWheelProductSessionOwner, attempt_id: str
    ) -> bool:
        return has_other_windows_worker_retirement_artifact(
            product, attempt_id, self.records.stem
        )

    @abstractmethod
    def require_history(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        review: _NoEffectT,
        *,
        stage_present: bool,
    ) -> None: ...

    @abstractmethod
    def _capture_current(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        review: _NoEffectT,
        *,
        lease_owner_revision: int,
    ) -> _NoEffectT: ...

    @abstractmethod
    def _prepare_removal(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        root: int,
        review: _NoEffectT,
        receipt: _ReceiptT,
    ) -> Callable[[], None]: ...

    def retire(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        *,
        expected_review: _NoEffectT,
    ) -> _ReceiptT:
        """Replay exact retirement under the offline lease and GC guard."""
        _require_retirement_entry(
            product,
            expected_review,
            product_id=self.entry_product_id,
            review_type=self.records.review_type,
            message=self.entry_required_message,
            required_native_revision=self.required_native_revision,
        )
        with _bound_retirement_root(
            product,
            self.inspection,
            error_type=self.records.error_type,
            active_message=self.error_prefix + "_runtime_active",
            root_changed=self.error_prefix + "_root_changed",
        ) as (quiescence, root):
            attempt_id = expected_review.attempt_id
            start = self.read_start(product, attempt_id)
            completed = self.records.read_receipt(product, attempt_id)
            if start is None:
                if completed is not None or (
                    self.required_native_revision is not None
                    and self.records.read_root_intent(product, attempt_id) is not None
                ):
                    raise self.records.error_type(self.error_prefix + "_start_missing")
                self.require_history(product, expected_review, stage_present=True)
                current = self._capture_current(
                    product,
                    expected_review,
                    lease_owner_revision=quiescence.owner_revision,
                )
                if current != expected_review:
                    raise self.records.error_type(self.error_prefix + "_review_stale")
                self.records.publish_start(
                    self.records.start_path(product, attempt_id),
                    expected_review,
                    write=self.io.write_private_receipt,
                )
                start = self.read_start(product, attempt_id)
            if start != expected_review:
                raise self.records.error_type(self.error_prefix + "_review_stale")
            receipt = _receipt_for_review(self.records.receipt_type, start)
            root_intent = self.records.read_root_intent(product, start.attempt_id)
            if root_intent is not None and root_intent != receipt:
                raise self.records.error_type(
                    self.error_prefix + "_root_intent_changed"
                )
            stage_present = windows_worker_stage_exists(root, start.attempt_id)
            self.require_history(product, start, stage_present=stage_present)
            remove = self._prepare_removal(product, root, start, receipt)
            if completed is not None:
                if completed != receipt or root_intent != receipt or stage_present:
                    raise self.records.error_type(
                        self.error_prefix + "_completed_changed"
                    )
                return completed
            if not stage_present and root_intent is None:
                raise self.records.error_type(self.error_prefix + "_stage_disappeared")
            remove()
            return _publish_retirement_completion(
                self.records,
                self.io,
                product,
                root,
                start,
                receipt,
                stage_error=self.records.error_type,
                stage_retained=self.error_prefix + "_stage_retained",
                publication_changed=self.error_prefix + "_publication_changed",
            )

    def _completed_review(
        self, product: WindowsLocalWheelProductSessionOwner, attempt_id: str
    ) -> tuple[_NoEffectT, _ReceiptT]:
        review = self.read_start(product, attempt_id)
        completed = self.records.read_receipt(product, attempt_id)
        root_intent = self.records.read_root_intent(product, attempt_id)
        if (
            review is None
            or completed is None
            or completed != root_intent
            or completed.review_fingerprint != review.fingerprint
            or completed.stage_identity != review.stage_identity[:2]
        ):
            raise self.records.error_type(self.error_prefix + "_history_unverified")
        return review, completed


@dataclass(frozen=True, slots=True)
class WindowsProductWorkerPartialStageRetirement(
    _NoEffectStageRetirement[_PartialT, _ReceiptT]
):
    inspect_inventory: ReadWindowsRecoveryInventory[WindowsRecoveryAttemptV1]
    capture_partial: _CapturePartialReview[_PartialT]
    physical: Callable[[], WindowsStageRetirement]

    def _capture_current(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        review: _PartialT,
        *,
        lease_owner_revision: int,
    ) -> _PartialT:
        return self.capture_partial(
            product,
            attempt_id=review.attempt_id,
            expected_stage=review.stage_identity[:2],
            lease_owner_revision=lease_owner_revision,
        )

    def _prepare_removal(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        root: int,
        review: _PartialT,
        receipt: _ReceiptT,
    ) -> Callable[[], None]:
        return partial(self.remove_remaining, product, root, review, receipt)

    def require_history(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        review: _PartialT,
        *,
        stage_present: bool,
    ) -> None:
        inventory = self.inspect_inventory(product)
        matches = tuple(
            (item for item in inventory if item.attempt_id == review.attempt_id)
        )
        expected_debts = _PARTIAL_DEBTS if stage_present else _PARTIAL_RETIRED_DEBTS
        if (
            len(matches) != 1
            or matches[0].observed_debts != expected_debts
            or (
                stage_present
                and matches[0].payload_directory_identity != review.stage_identity[:2]
            )
            or self.other_artifact(product, review.attempt_id)
        ):
            raise self.records.error_type(self.error_prefix + "_history_changed")

    def require_completed(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        attempt: WindowsRecoveryAttemptV1,
    ) -> None:
        self._completed_review(product, attempt.attempt_id)
        if (
            attempt.observed_debts != _PARTIAL_RETIRED_DEBTS
            or self.other_artifact(product, attempt.attempt_id)
        ):
            raise self.records.error_type(self.error_prefix + "_history_unverified")

    def remove_remaining(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        root: int,
        review: _PartialT,
        receipt: _ReceiptT,
    ) -> None:
        with PartialWindowsStageRetirement(
            self.physical(), self.records.error_type, self.error_prefix
        ).partial(root, review) as stage:
            _require_empty_stage_delete_intent(
                self.records, self.io, product, stage, review.attempt_id, receipt, self.error_prefix
            )


@dataclass(frozen=True, slots=True)
class WindowsProductWorkerUnlaunchedStageRetirement(
    _NoEffectStageRetirement[_ReservedT, _ReceiptT],
    Generic[_ReservedT, _ReceiptT, _IntentT],
):
    inspect_inventory: ReadWindowsRecoveryInventory[WindowsRecoveryAttemptV1]
    read_intent: Callable[[WindowsLocalWheelProductSessionOwner, str], _IntentT | None]
    capture_reserved: _CaptureReservedReview[_IntentT, _ReservedT]
    physical: Callable[[], WindowsStageRetirement]

    required_native_revision = 2

    def _capture_current(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        review: _ReservedT,
        *,
        lease_owner_revision: int,
    ) -> _ReservedT:
        return self.capture_reserved(
            product,
            intent=self.require_intent(product, review),
            native_revision=2,
            lease_owner_revision=lease_owner_revision,
        )

    def _prepare_removal(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        root: int,
        review: _ReservedT,
        receipt: _ReceiptT,
    ) -> Callable[[], None]:
        intent = self.require_intent(product, review)
        return partial(self.remove_remaining, product, root, review, intent, receipt)

    def require_history(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        review: _ReservedT,
        *,
        stage_present: bool,
    ) -> None:
        inventory = self.inspect_inventory(product)
        matches = tuple(
            (item for item in inventory if item.attempt_id == review.attempt_id)
        )
        intent = self.require_intent(product, review)
        if (
            len(matches) != 1
            or not no_effect_history_matches(matches[0], settled=True)
            or matches[0].observed_debts
            != (
                (
                    "payload_retained",
                    "launch_intent_retained",
                    "supervisor_history_missing",
                )
                if stage_present
                else _UNLAUNCHED_RETIRED_DEBTS
            )
            or (
                stage_present
                and matches[0].payload_directory_identity != review.stage_identity[:2]
            )
            or (not native_matches_intent(matches[0], intent))
            or (not launch_matches_intent(matches[0], intent))
            or (matches[0].launch_stage_identity != intent.stage_identity)
            or self.other_artifact(product, review.attempt_id)
        ):
            raise self.records.error_type(self.error_prefix + "_history_changed")

    def require_completed(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        attempt: WindowsRecoveryAttemptV1,
    ) -> None:
        review, completed = self._completed_review(product, attempt.attempt_id)
        if (
            attempt.observed_debts != _UNLAUNCHED_RETIRED_DEBTS
            or not no_effect_history_matches(attempt, settled=True)
            or self.other_artifact(product, attempt.attempt_id)
        ):
            raise self.records.error_type(self.error_prefix + "_history_unverified")
        intent = self.require_intent(product, review)
        if (
            intent.stage_identity != completed.stage_identity
            or not native_matches_intent(attempt, intent)
            or (not launch_matches_intent(attempt, intent))
            or (attempt.launch_stage_identity != intent.stage_identity)
        ):
            raise self.records.error_type(self.error_prefix + "_history_unverified")

    def require_intent(
        self, product: WindowsLocalWheelProductSessionOwner, review: _ReservedT
    ) -> _IntentT:
        intent = self.read_intent(product, review.attempt_id)
        if intent is None or intent.fingerprint != review.intent_fingerprint:
            raise self.records.error_type(self.error_prefix + "_intent_changed")
        return intent

    def remove_remaining(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        root: int,
        review: _ReservedT,
        intent: _IntentT,
        receipt: _ReceiptT,
    ) -> None:
        with self.physical().complete(root, review, intent) as stage:
            _require_empty_stage_delete_intent(
                self.records, self.io, product, stage, review.attempt_id, receipt, self.error_prefix
            )

    def start_path(
        self, product: WindowsLocalWheelProductSessionOwner, *, start_id: str
    ) -> Path:
        return self.records.start_path(product, start_id)

    def read_start(
        self, product: WindowsLocalWheelProductSessionOwner, attempt_id: str
    ) -> _ReservedT | None:
        review = self.records.read_start(product, attempt_id)
        if review is not None and review.native_revision != 2:
            raise self.records.error_type(self.error_prefix + "_start_invalid")
        return review


@dataclass(frozen=True, slots=True)
class WindowsProductWorkerCrashStageRetirement(Generic[_CrashT, _ReceiptT, _IntentT]):
    records: WindowsWorkerRetirementRecords[_CrashT, _ReceiptT]
    io: WindowsPrivateReceiptIO
    review_stage: _ReviewCrashStage[_CrashT]
    review_runtime: _RuntimeReview[_WindowsOrphanRuntimeReviewMethods]
    inspect_native: Callable[
        [WindowsLocalWheelProductSessionOwner],
        tuple[WindowsWorkerProvisioningAttemptV1, ...],
    ]
    read_intent: Callable[[WindowsLocalWheelProductSessionOwner, str], _IntentT | None]
    remove_complete: _RemoveCompleteStage[_IntentT, _ReceiptT]
    inspection: Callable[[], WindowsStageInspection]

    def retire(
        self, product: WindowsLocalWheelProductSessionOwner, *, expected_review: _CrashT
    ) -> _ReceiptT:
        with _bound_retirement_root(
            product,
            self.inspection,
            error_type=ValueError,
            active_message="Windows Worker crash stage has active leases",
            root_changed="Windows Worker crash stage root changed",
        ) as (quiescence, root):
            self.require_no_other(product, expected_review.attempt_id)
            start = self.records.read_start(product, expected_review.attempt_id)
            completed = self.records.read_receipt(
                product, expected_review.attempt_id
            )
            root_intent = self.records.read_root_intent(
                product, expected_review.attempt_id
            )
            if start is None:
                if completed is not None or root_intent is not None:
                    raise ValueError("Windows Worker crash stage start is missing")
                current = self.review_stage(
                    product,
                    attempt_id=expected_review.attempt_id,
                    quiescence=quiescence,
                )
                if current != expected_review:
                    raise ValueError("Windows Worker crash stage review is stale")
                self.records.publish_start(
                    self.records.start_path(product, expected_review.attempt_id),
                    expected_review,
                    write=self.io.write_private_receipt,
                )
                start = self.records.read_start(product, expected_review.attempt_id)
            if start != expected_review:
                raise ValueError("Windows Worker crash stage review changed")
            assert start is not None
            receipt = _receipt_for_review(self.records.receipt_type, start)
            if root_intent is not None and root_intent != receipt:
                raise ValueError("Windows Worker crash stage root intent changed")
            present = windows_worker_stage_exists(root, start.attempt_id)
            self.require_history(
                product, start, stage_present=present, quiescence=quiescence
            )
            if completed is not None:
                if completed != receipt or root_intent != receipt or present:
                    raise ValueError("Windows Worker crash stage receipt changed")
                return completed
            if not present and root_intent is None:
                raise ValueError("Windows Worker crash stage disappeared")
            intent = self.read_intent(product, start.attempt_id)
            if intent is None:
                raise ValueError(
                    "Windows Worker crash stage launch intent is missing"
                )
            self.remove_complete(
                product,
                root,
                start,
                intent,
                receipt,
                root_delete_intent_path=self.records.root_intent_path(
                    product, start.attempt_id
                ),
                read_root_delete_intent=lambda: self.records.read_root_intent(
                    product, start.attempt_id
                ),
            )
            return _publish_retirement_completion(
                self.records,
                self.io,
                product,
                root,
                start,
                receipt,
                stage_error=ValueError,
                stage_retained="Windows Worker crash stage remains",
                publication_changed="Windows Worker crash stage receipt changed",
            )

    def require_history(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        review: _CrashT,
        *,
        stage_present: bool,
        quiescence: PackageWindowsRuntimeQuiescenceV1 | None = None,
    ) -> None:
        joined = self.review_runtime(product, attempt_id=review.attempt_id, orphans=())
        attempt = joined.attempt
        receipt = joined.receipt_record
        intent = self.read_intent(product, review.attempt_id)
        expected_debts = (
            "payload_retained" if stage_present else "payload_missing",
            "launch_intent_retained",
        ) + (
            ()
            if review.supervisor_revision is not None
            else ("supervisor_history_missing",)
        )
        if (
            joined.missing_proofs != ("orphan_lease_absent",)
            or attempt is None
            or receipt is None
            or (intent is None)
            or (attempt.observed_debts != expected_debts)
            or (not _valid_crash_effect_history(attempt, settled=True))
            or (attempt.native_revision != review.native_revision)
            or (attempt.supervisor_revision != review.supervisor_revision)
            or (
                attempt.supervisor_phase != "process_settled"
                if review.supervisor_revision is not None
                else attempt.supervisor_phase is not None
            )
            or (
                review.supervisor_revision is not None
                and attempt.supervisor_process_settled is not True
            )
            or (intent.fingerprint != review.intent_fingerprint)
            or (not launch_matches_intent(attempt, intent))
            or (not native_matches_intent(attempt, intent))
            or (
                review.supervisor_revision is not None
                and attempt.supervisor_identity_fingerprint
                != intent.identity_fingerprint
            )
            or (
                stage_present
                and attempt.payload_directory_identity != review.stage_identity[:2]
            )
        ):
            raise ValueError("Windows Worker crash stage history changed")
        if quiescence is not None:
            _require_repair_record(
                quiescence,
                runtime_id=receipt.receipt.policy.product_runtime_id,
                expected=(review.repaired_lease_id, review.lease_repair_revision),
            )
        native = native_attempts_for(self.inspect_native(product), review.attempt_id)
        if len(native) != 1:
            raise ValueError("Windows Worker crash stage native history changed")
        [provisioned] = native
        identity = provisioned.identity
        if (
            not native_attempt_history_matches(
                provisioned, attempt, phase="settled", revision=review.native_revision
            )
            or identity["specFingerprint"] != review.native_spec_fingerprint
            or not native_attempt_identity_matches(
                identity, attempt, receipt, request_fingerprint=intent.request_fingerprint
            )
        ):
            raise ValueError("Windows Worker crash stage native identity changed")
        product.assert_root_gc_authority_current()

    def require_completed(
        self,
        product: WindowsLocalWheelProductSessionOwner,
        attempt: WindowsRecoveryAttemptV1,
    ) -> None:
        review = self.records.read_start(product, attempt.attempt_id)
        receipt = self.records.read_receipt(product, attempt.attempt_id)
        root_intent = self.records.read_root_intent(product, attempt.attempt_id)
        if (
            review is None
            or receipt is None
            or root_intent is None
            or (receipt != root_intent)
            or (receipt.review_fingerprint != review.fingerprint)
            or (receipt.stage_identity != review.stage_identity[:2])
            or (attempt.payload_directory_identity is not None)
        ):
            raise ValueError("Windows Worker crash stage retirement is unverified")
        self.require_no_other(product, attempt.attempt_id)
        self.require_history(product, review, stage_present=False)

    def require_no_other(
        self, product: WindowsLocalWheelProductSessionOwner, attempt_id: str
    ) -> None:
        if has_other_windows_worker_retirement_artifact(
            product, attempt_id, "worker-crash-stage"
        ):
            raise ValueError("Windows Worker crash stage retirement conflicts")
