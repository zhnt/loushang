"""Receipt-backed offline retirement for an unlaunched Windows Worker stage."""

from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path

from loushang.foundation.windows_private_acl import WindowsPrivateDirectoryAcl
from loushang.harness.package_product.product_local_wheel_runtime import (
    WindowsLocalWheelProductSessionOwner,
)
from loushang.harness.resources.packages.plugin_lifecycle.windows_quarantine import (
    open_windows_directory,
    windows_listdir_at,
)

from .package_legacy_windows_receipt import (
    read_windows_private_receipt,
    write_windows_private_receipt,
)
from .package_product_worker_windows_partial_stage_review import (
    _PARTIAL_DEBTS,
    CodingWindowsWorkerPartialStageReviewV1,
    _review_partial_tree,
)
from .package_product_worker_windows_recovery_inventory import (
    CodingWindowsWorkerRecoveryAttemptV1,
    _inspect_windows_worker_recovery_inventory_under_gc_guard,
)
from .package_product_worker_windows_stage_retirement import (
    CodingWindowsWorkerStageRetirementReceiptV1,
    _close_opened,
    _delete_directory_if_empty,
    _delete_file_if_present,
    _stage_exists,
)
from .package_product_worker_windows_stage_review import (
    _read_checked_file,
    _require_direct,
)

_MAX_REVIEW_BYTES = 32768
_MAX_RECEIPT_BYTES = 1024
_RETIRED_DEBTS = (
    "payload_missing",
    "launch_intent_missing",
    "native_history_missing",
    "supervisor_history_missing",
)


class CodingWindowsWorkerPartialStageRetirementError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def retire_coding_windows_product_worker_partial_stage(
    product: WindowsLocalWheelProductSessionOwner,
    *,
    expected_review: CodingWindowsWorkerPartialStageReviewV1,
) -> CodingWindowsWorkerStageRetirementReceiptV1:
    """Delete only saved members after verifying no launch ever committed."""

    if (
        os.name != "nt"
        or type(product) is not WindowsLocalWheelProductSessionOwner
        or product.policy.product_id != "coding"
        or type(expected_review) is not CodingWindowsWorkerPartialStageReviewV1
    ):
        raise OSError("Windows Worker partial retirement requires a Product review")
    registry = product.epoch_runtime.registry
    with registry.exclusive_runtime_quiescence(
        store_id=registry.store_id
    ) as quiescence:
        if quiescence.active_runtime_lease_ids:
            raise CodingWindowsWorkerPartialStageRetirementError(
                "coding_worker_partial_retirement_runtime_active"
            )
        with product.gc_gate.guard():
            product.assert_root_gc_authority_current()
            with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
                with WindowsPrivateDirectoryAcl() as acl:
                    _require_direct(root, acl, directory=True)
                    if not os.path.samestat(os.fstat(root), product.state_root.lstat()):
                        raise CodingWindowsWorkerPartialStageRetirementError(
                            "coding_worker_partial_retirement_root_changed"
                        )
                start = _read_start(product, expected_review.attempt_id)
                completed = _read_receipt(product, expected_review.attempt_id)
                if start is None:
                    if completed is not None:
                        raise CodingWindowsWorkerPartialStageRetirementError(
                            "coding_worker_partial_retirement_start_missing"
                        )
                    _require_partial_history(
                        product, expected_review, stage_present=True
                    )
                    current = _review_partial_tree(
                        product,
                        attempt_id=expected_review.attempt_id,
                        expected_stage=expected_review.stage_identity[:2],
                        lease_owner_revision=quiescence.owner_revision,
                    )
                    if current != expected_review:
                        raise CodingWindowsWorkerPartialStageRetirementError(
                            "coding_worker_partial_retirement_review_stale"
                        )
                    write_windows_private_receipt(
                        _start_path(product, expected_review.attempt_id),
                        expected_review.to_bytes(),
                        maximum_bytes=_MAX_REVIEW_BYTES,
                    )
                    start = _read_start(product, expected_review.attempt_id)
                if start != expected_review:
                    raise CodingWindowsWorkerPartialStageRetirementError(
                        "coding_worker_partial_retirement_review_stale"
                    )
                receipt = CodingWindowsWorkerStageRetirementReceiptV1(
                    attempt_id=start.attempt_id,
                    review_fingerprint=start.fingerprint,
                    stage_identity=start.stage_identity[:2],
                )
                root_intent = _read_root_intent(product, start.attempt_id)
                if root_intent is not None and root_intent != receipt:
                    raise CodingWindowsWorkerPartialStageRetirementError(
                        "coding_worker_partial_retirement_root_intent_changed"
                    )
                stage_present = _stage_exists(root, start.attempt_id)
                _require_partial_history(product, start, stage_present=stage_present)
                if completed is not None:
                    if completed != receipt or root_intent != receipt or stage_present:
                        raise CodingWindowsWorkerPartialStageRetirementError(
                            "coding_worker_partial_retirement_completed_changed"
                        )
                    return completed
                if not stage_present and root_intent is None:
                    raise CodingWindowsWorkerPartialStageRetirementError(
                        "coding_worker_partial_retirement_stage_disappeared"
                    )
                _remove_remaining_stage(product, root, start, receipt)
                if _stage_exists(root, start.attempt_id):
                    raise CodingWindowsWorkerPartialStageRetirementError(
                        "coding_worker_partial_retirement_stage_retained"
                    )
                write_windows_private_receipt(
                    _receipt_path(product, start.attempt_id),
                    receipt.to_bytes(),
                    maximum_bytes=_MAX_RECEIPT_BYTES,
                )
                if _read_receipt(product, start.attempt_id) != receipt:
                    raise CodingWindowsWorkerPartialStageRetirementError(
                        "coding_worker_partial_retirement_publication_changed"
                    )
                product.assert_root_gc_authority_current()
                return receipt


def _require_partial_history(
    product: WindowsLocalWheelProductSessionOwner,
    review: CodingWindowsWorkerPartialStageReviewV1,
    *,
    stage_present: bool,
) -> None:
    inventory = _inspect_windows_worker_recovery_inventory_under_gc_guard(product)
    matches = tuple(item for item in inventory if item.attempt_id == review.attempt_id)
    expected_debts = _PARTIAL_DEBTS if stage_present else _RETIRED_DEBTS
    if (
        len(matches) != 1
        or matches[0].observed_debts != expected_debts
        or (
            stage_present
            and matches[0].payload_directory_identity != review.stage_identity[:2]
        )
        or _full_retirement_artifact_present(product, review.attempt_id)
    ):
        raise CodingWindowsWorkerPartialStageRetirementError(
            "coding_worker_partial_retirement_history_changed"
        )


def _require_completed_partial_retirement_under_gc_guard(
    product: WindowsLocalWheelProductSessionOwner,
    attempt: CodingWindowsWorkerRecoveryAttemptV1,
) -> None:
    review = _read_start(product, attempt.attempt_id)
    completed = _read_receipt(product, attempt.attempt_id)
    root_intent = _read_root_intent(product, attempt.attempt_id)
    if (
        review is None
        or completed is None
        or root_intent is None
        or completed != root_intent
        or completed.review_fingerprint != review.fingerprint
        or completed.stage_identity != review.stage_identity[:2]
        or attempt.observed_debts != _RETIRED_DEBTS
        or _full_retirement_artifact_present(product, attempt.attempt_id)
    ):
        raise CodingWindowsWorkerPartialStageRetirementError(
            "coding_worker_partial_retirement_history_unverified"
        )


def _remove_remaining_stage(
    product: WindowsLocalWheelProductSessionOwner,
    root: int,
    review: CodingWindowsWorkerPartialStageReviewV1,
    receipt: CodingWindowsWorkerStageRetirementReceiptV1,
) -> None:
    stage_name = "worker-payload-" + review.attempt_id
    with WindowsPrivateDirectoryAcl() as acl:
        _require_direct(root, acl, directory=True)
        try:
            stage = open_windows_directory(
                stage_name, dir_fd=root, share_delete=False, read_control=True
            )
        except FileNotFoundError:
            return
        try:
            _require_remaining_subset(stage, review, acl)
            if review.entrypoint is not None:
                assert review.executable_identity is not None
                assert review.executable_digest is not None
                parts = review.entrypoint.split("/")
                parent = _open_existing_parent(stage, parts[:-1], review, acl)
                if parent is not None:
                    descriptor, opened = parent
                    try:
                        _delete_file_if_present(
                            descriptor,
                            parts[-1],
                            review.executable_identity,
                            review.executable_digest,
                            acl,
                        )
                    finally:
                        _close_opened(opened)
            for index in range(len(review.directory_identities) - 1, -1, -1):
                path, identity = review.directory_identities[index]
                parts = path.split("/")
                parent = _open_existing_parent(stage, parts[:-1], review, acl)
                if parent is None:
                    continue
                descriptor, opened = parent
                try:
                    _delete_directory_if_empty(descriptor, parts[-1], identity, acl)
                finally:
                    _close_opened(opened)
            if windows_listdir_at(stage):
                raise CodingWindowsWorkerPartialStageRetirementError(
                    "coding_worker_partial_retirement_extra_member"
                )
            if _read_root_intent(product, review.attempt_id) is None:
                write_windows_private_receipt(
                    _root_intent_path(product, review.attempt_id),
                    receipt.to_bytes(),
                    maximum_bytes=_MAX_RECEIPT_BYTES,
                )
            if _read_root_intent(product, review.attempt_id) != receipt:
                raise CodingWindowsWorkerPartialStageRetirementError(
                    "coding_worker_partial_retirement_root_intent_changed"
                )
        finally:
            os.close(stage)
        _delete_directory_if_empty(root, stage_name, review.stage_identity, acl)


def _require_remaining_subset(
    stage: int,
    review: CodingWindowsWorkerPartialStageReviewV1,
    acl: WindowsPrivateDirectoryAcl,
) -> None:
    if _require_direct(stage, acl, directory=True)[:2] != review.stage_identity[:2]:
        raise CodingWindowsWorkerPartialStageRetirementError(
            "coding_worker_partial_retirement_stage_changed"
        )
    first_name = (
        review.directory_identities[0][0]
        if review.directory_identities
        else review.entrypoint
    )
    names = set(windows_listdir_at(stage))
    if (
        any(name.casefold() == "worker-payload.json" for name in names)
        or (first_name is None and names)
        or (first_name is not None and not names <= {first_name.split("/")[0]})
    ):
        raise CodingWindowsWorkerPartialStageRetirementError(
            "coding_worker_partial_retirement_extra_member"
        )
    current = stage
    opened: list[int] = []
    try:
        for index, (path, identity) in enumerate(review.directory_identities):
            name = path.split("/")[-1]
            if name not in windows_listdir_at(current):
                return
            child = open_windows_directory(
                name, dir_fd=current, share_delete=False, read_control=True
            )
            opened.append(child)
            if _require_direct(child, acl, directory=True)[:2] != identity[:2]:
                raise CodingWindowsWorkerPartialStageRetirementError(
                    "coding_worker_partial_retirement_directory_changed"
                )
            next_name = (
                review.directory_identities[index + 1][0].split("/")[-1]
                if index + 1 < len(review.directory_identities)
                else (
                    review.entrypoint.split("/")[-1]
                    if review.entrypoint is not None
                    else None
                )
            )
            child_names = set(windows_listdir_at(child))
            if (next_name is None and child_names) or (
                next_name is not None and not child_names <= {next_name}
            ):
                raise CodingWindowsWorkerPartialStageRetirementError(
                    "coding_worker_partial_retirement_extra_member"
                )
            current = child
        if review.entrypoint is not None:
            assert review.executable_identity is not None
            assert review.executable_digest is not None
            name = review.entrypoint.split("/")[-1]
            if name in windows_listdir_at(current):
                raw, identity = _read_checked_file(
                    current, name, acl, maximum_bytes=16 * 1024 * 1024
                )
                if (
                    identity != review.executable_identity
                    or sha256(raw).hexdigest() != review.executable_digest
                ):
                    raise CodingWindowsWorkerPartialStageRetirementError(
                        "coding_worker_partial_retirement_file_changed"
                    )
            elif windows_listdir_at(current):
                raise CodingWindowsWorkerPartialStageRetirementError(
                    "coding_worker_partial_retirement_extra_member"
                )
    finally:
        _close_opened(opened)


def _open_existing_parent(
    stage: int,
    parts: list[str],
    review: CodingWindowsWorkerPartialStageReviewV1,
    acl: WindowsPrivateDirectoryAcl,
) -> tuple[int, list[int]] | None:
    current = stage
    opened: list[int] = []
    try:
        for index, name in enumerate(parts):
            if name not in windows_listdir_at(current):
                _close_opened(opened)
                return None
            child = open_windows_directory(
                name, dir_fd=current, share_delete=False, read_control=True
            )
            opened.append(child)
            if (
                _require_direct(child, acl, directory=True)[:2]
                != review.directory_identities[index][1][:2]
            ):
                raise CodingWindowsWorkerPartialStageRetirementError(
                    "coding_worker_partial_retirement_directory_changed"
                )
            current = child
        return current, opened
    except BaseException:
        _close_opened(opened)
        raise


def _full_retirement_artifact_present(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> bool:
    with product.epoch_runtime.borrow_product_state_root_descriptor() as root:
        names = windows_listdir_at(root)
    return any(
        name.casefold().startswith(
            (
                f"worker-stage-retire-{attempt_id}.json",
                f"worker-stage-root-delete-{attempt_id}.json",
                f"worker-stage-retired-{attempt_id}.json",
                f"worker-unlaunched-stage-retire-{attempt_id}.json",
                f"worker-unlaunched-stage-root-delete-{attempt_id}.json",
                f"worker-unlaunched-stage-retired-{attempt_id}.json",
                f"worker-crash-stage-retire-{attempt_id}.json",
                f"worker-crash-stage-root-delete-{attempt_id}.json",
                f"worker-crash-stage-retired-{attempt_id}.json",
            )
        )
        for name in names
    )


def _read_start(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> CodingWindowsWorkerPartialStageReviewV1 | None:
    raw = read_windows_private_receipt(
        _start_path(product, attempt_id),
        maximum_bytes=_MAX_REVIEW_BYTES,
        allow_unpublished_stage=True,
    )
    review = (
        None if raw is None else CodingWindowsWorkerPartialStageReviewV1.from_bytes(raw)
    )
    if review is not None and review.attempt_id != attempt_id:
        raise CodingWindowsWorkerPartialStageRetirementError(
            "coding_worker_partial_retirement_start_invalid"
        )
    return review


def _read_receipt(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> CodingWindowsWorkerStageRetirementReceiptV1 | None:
    return _read_bound_receipt(product, attempt_id, _receipt_path(product, attempt_id))


def _read_root_intent(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> CodingWindowsWorkerStageRetirementReceiptV1 | None:
    return _read_bound_receipt(
        product, attempt_id, _root_intent_path(product, attempt_id)
    )


def _read_bound_receipt(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str, path: Path
) -> CodingWindowsWorkerStageRetirementReceiptV1 | None:
    raw = read_windows_private_receipt(
        path, maximum_bytes=_MAX_RECEIPT_BYTES, allow_unpublished_stage=True
    )
    receipt = (
        None
        if raw is None
        else CodingWindowsWorkerStageRetirementReceiptV1.from_bytes(raw)
    )
    if receipt is not None and receipt.attempt_id != attempt_id:
        raise CodingWindowsWorkerPartialStageRetirementError(
            "coding_worker_partial_retirement_receipt_invalid"
        )
    return receipt


def _start_path(product: WindowsLocalWheelProductSessionOwner, attempt_id: str) -> Path:
    return product.state_root / f"worker-partial-stage-retire-{attempt_id}.json"


def _receipt_path(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> Path:
    return product.state_root / f"worker-partial-stage-retired-{attempt_id}.json"


def _root_intent_path(
    product: WindowsLocalWheelProductSessionOwner, attempt_id: str
) -> Path:
    return product.state_root / f"worker-partial-stage-root-delete-{attempt_id}.json"


__all__ = [
    "CodingWindowsWorkerPartialStageRetirementError",
    "retire_coding_windows_product_worker_partial_stage",
]
