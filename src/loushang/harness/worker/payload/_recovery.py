"""Complete retained Worker payload recovery over original storage and journals.

The caller retains Product offline admission and the borrowed root descriptor.
This module closes only stage descriptors it opens. The Supervisor factory is an
effectful Product admission/owner binding, invoked anew at every original point.
No scan, verification, repair publication or deletion is borrowed from Product.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from hashlib import sha256

from loushang.harness.resources.packages.plugin_lifecycle.records import (
    canonical_json_bytes,
)
from loushang.harness.worker.journal import (
    WorkerAttemptRecordV1,
    WorkerSupervisorJournal,
)

from ._records import _ATTEMPT, EmptyPayloadPlan, PayloadPlan, PayloadReview
from ._storage import _DIR_FLAGS, PayloadStorage


def review_complete(
    storage: PayloadStorage,
    root_fd: int,
    *,
    attempt_id: str,
    supervisor: Callable[[], WorkerSupervisorJournal],
) -> tuple[PayloadPlan, WorkerAttemptRecordV1 | None]:
    """Correlate an exact Product stage with its canonical Supervisor journal.

    An absent or failed/fenced attempt does not establish process settlement.
    This review does not authorize deleting the payload or restarting a Worker.
    """
    plan = storage._verify_debt(root_fd, attempt_id)
    record = supervisor().status(attempt_id)
    if storage._verify_debt(root_fd, attempt_id) != plan:
        raise storage.error_type("coding_worker_payload_debt_plan_stale")
    return (plan, record)


def preview_complete(
    storage: PayloadStorage, root_fd: int, *, attempt_id: str
) -> PayloadPlan:
    """Read a complete abandoned stage only while Product Sessions are absent."""
    return storage._verify_debt(root_fd, attempt_id)


def preview_empty(
    storage: PayloadStorage,
    root_fd: int,
    *,
    attempt_id: str,
    supervisor: Callable[[], WorkerSupervisorJournal],
) -> EmptyPayloadPlan:
    """Review only an empty stage with no durable Supervisor claim."""
    plan = storage._verify_empty_debt(root_fd, attempt_id)
    if supervisor().status(attempt_id) is not None:
        raise storage.error_type("coding_worker_payload_attempt_claimed")
    if storage._verify_empty_debt(root_fd, attempt_id) != plan:
        raise storage.error_type("coding_worker_payload_debt_plan_stale")
    return plan


def review_unmarked(
    storage: PayloadStorage,
    root_fd: int,
    *,
    attempt_id: str,
    supervisor: Callable[[], WorkerSupervisorJournal],
) -> PayloadReview:
    """Inspect a nonempty pre-marker stage without granting cleanup authority."""
    review = storage._scan_unmarked_debt(root_fd, attempt_id)
    if supervisor().status(attempt_id) is not None:
        raise storage.error_type("coding_worker_payload_attempt_claimed")
    if storage._scan_unmarked_debt(root_fd, attempt_id) != review:
        raise storage.error_type("coding_worker_payload_debt_plan_stale")
    return review


def repair_unmarked(
    storage: PayloadStorage,
    root_fd: int,
    *,
    expected_review: PayloadReview,
    supervisor: Callable[[], WorkerSupervisorJournal],
) -> PayloadReview:
    """Remove an exact pre-marker stage under offline, unclaimed authority."""
    prior = storage.unmarked.read(root_fd, expected_review.attempt_id)
    if prior is not None and prior != expected_review:
        raise storage.error_type("coding_worker_payload_debt_plan_stale")
    _require_unclaimed_attempt(storage, supervisor, expected_review.attempt_id)
    if prior is not None and (
        not storage._stage_exists(root_fd, expected_review.attempt_id)
    ):
        storage.unmarked.settle(root_fd, expected_review.attempt_id, expected_review)
        return expected_review
    if (
        prior is None
        and storage._scan_unmarked_debt(root_fd, expected_review.attempt_id)
        != expected_review
    ):
        raise storage.error_type("coding_worker_payload_debt_plan_stale")
    stage_name = f"worker-payload-{expected_review.attempt_id}"
    stage_fd = os.open(stage_name, _DIR_FLAGS, dir_fd=root_fd)
    try:
        storage._verify_unmarked_repair_remainder(
            root_fd,
            stage_fd,
            stage_name,
            expected_review,
            allow_partial=prior is not None,
        )
        storage.unmarked.publish(root_fd, expected_review.attempt_id, expected_review)
        _require_unclaimed_attempt(storage, supervisor, expected_review.attempt_id)
        storage._remove_unmarked_repair_remainder(
            root_fd, stage_fd, stage_name, expected_review, allow_partial=True
        )
    finally:
        os.close(stage_fd)
    return expected_review


def reopen_unmarked(
    storage: PayloadStorage,
    root_fd: int,
    *,
    attempt_id: str,
    supervisor: Callable[[], WorkerSupervisorJournal],
) -> PayloadReview | None:
    """Reopen a published, completed pre-marker cleanup after a process crash."""
    prior = storage.unmarked.read(root_fd, attempt_id)
    if prior is None or storage._stage_exists(root_fd, attempt_id):
        return None
    _require_unclaimed_attempt(storage, supervisor, attempt_id)
    return prior


def read_unmarked_intent(
    storage: PayloadStorage,
    root_fd: int,
    *,
    attempt_id: str,
    supervisor: Callable[[], WorkerSupervisorJournal],
) -> PayloadReview | None:
    """Read a durable cleanup intent even when its exact stage remains."""
    prior = storage.unmarked.read(root_fd, attempt_id)
    if prior is not None:
        _require_unclaimed_attempt(storage, supervisor, attempt_id)
    return prior


def _require_unclaimed_attempt(
    storage: PayloadStorage,
    supervisor: Callable[[], WorkerSupervisorJournal],
    attempt_id: str,
) -> None:
    if supervisor().status(attempt_id) is not None:
        raise storage.error_type("coding_worker_payload_attempt_claimed")


def reopen_empty(
    storage: PayloadStorage,
    root_fd: int,
    *,
    attempt_id: str,
    supervisor: Callable[[], WorkerSupervisorJournal],
) -> EmptyPayloadPlan | None:
    """Read a durable repair result only after its exact stage disappeared."""
    plan = storage.empty.read(root_fd, attempt_id)
    if plan is None:
        return None
    if storage._stage_exists(root_fd, attempt_id):
        return None
    if supervisor().status(attempt_id) is not None:
        raise storage.error_type("coding_worker_payload_attempt_claimed")
    return plan


def list_complete(storage: PayloadStorage, root_fd: int) -> tuple[PayloadPlan, ...]:
    """Enumerate every complete attempt stage under offline Product authority.

    A malformed stage name or body makes the whole inventory unavailable. GC
    and recovery callers must not infer that an unreadable attempt is absent.
    """
    try:
        names = tuple(os.listdir(root_fd))
    except OSError as exc:
        raise storage.error_type("coding_worker_payload_debt_unverified") from exc
    plans: list[PayloadPlan] = []
    for name in sorted(names):
        if not name.startswith("worker-payload-"):
            continue
        attempt_id = name.removeprefix("worker-payload-")
        if _ATTEMPT.fullmatch(attempt_id) is None:
            raise storage.error_type("coding_worker_payload_debt_unverified")
        plans.append(storage._verify_debt(root_fd, attempt_id))
    return tuple(plans)


def repair_complete(
    storage: PayloadStorage,
    root_fd: int,
    *,
    expected_plan: PayloadPlan,
    supervisor: Callable[[], WorkerSupervisorJournal],
) -> PayloadPlan:
    """Delete an exact stage only after its Supervisor recorded process exit."""
    prior = storage.complete.read(root_fd, expected_plan.attempt_id)
    if prior is not None and prior[0] != expected_plan:
        raise storage.error_type("coding_worker_payload_debt_plan_stale")
    if prior is None:
        current = storage._verify_debt(root_fd, expected_plan.attempt_id)
        if current != expected_plan:
            raise storage.error_type("coding_worker_payload_debt_plan_stale")
    supervisor_fingerprint = _settled_supervisor_fingerprint(
        storage, supervisor, expected_plan.attempt_id
    )
    if prior is not None and prior[1] != supervisor_fingerprint:
        raise storage.error_type("coding_worker_payload_debt_plan_stale")
    if prior is not None and (
        not storage._stage_exists(root_fd, expected_plan.attempt_id)
    ):
        storage.complete.settle(
            root_fd, expected_plan.attempt_id, (expected_plan, supervisor_fingerprint)
        )
        return expected_plan
    stage_name = f"worker-payload-{expected_plan.attempt_id}"
    stage_fd = os.open(stage_name, _DIR_FLAGS, dir_fd=root_fd)
    try:
        storage._verify_complete_repair_remainder(
            root_fd, stage_fd, stage_name, expected_plan
        )
        storage.complete.publish(
            root_fd, expected_plan.attempt_id, (expected_plan, supervisor_fingerprint)
        )
        if (
            _settled_supervisor_fingerprint(
                storage, supervisor, expected_plan.attempt_id
            )
            != supervisor_fingerprint
        ):
            raise storage.error_type("coding_worker_payload_debt_plan_stale")
        storage._verify_complete_repair_remainder(
            root_fd, stage_fd, stage_name, expected_plan
        )
        if prior is None:
            storage._remove_verified_stage(root_fd, stage_fd, stage_name, expected_plan)
        else:
            storage._remove_partial_stage(
                root_fd, stage_fd, stage_name, expected_plan.entrypoint
            )
    finally:
        os.close(stage_fd)
    return expected_plan


def reopen_complete(
    storage: PayloadStorage,
    root_fd: int,
    *,
    attempt_id: str,
    supervisor: Callable[[], WorkerSupervisorJournal],
) -> PayloadPlan | None:
    """Read one completed, exact payload repair without accepting stage debt."""
    prior = storage.complete.read(root_fd, attempt_id)
    if prior is None or storage._stage_exists(root_fd, attempt_id):
        return None
    plan, recorded_supervisor = prior
    if (
        _settled_supervisor_fingerprint(storage, supervisor, attempt_id)
        != recorded_supervisor
    ):
        raise storage.error_type("coding_worker_payload_debt_plan_stale")
    return plan


def read_complete_intent(
    storage: PayloadStorage,
    root_fd: int,
    *,
    attempt_id: str,
    supervisor: Callable[[], WorkerSupervisorJournal],
) -> PayloadPlan | None:
    """Read a durable settled cleanup intent while its stage may remain."""
    prior = storage.complete.read(root_fd, attempt_id)
    if prior is None:
        return None
    plan, recorded_supervisor = prior
    if (
        _settled_supervisor_fingerprint(storage, supervisor, attempt_id)
        != recorded_supervisor
    ):
        raise storage.error_type("coding_worker_payload_debt_plan_stale")
    return plan


def _settled_supervisor_fingerprint(
    storage: PayloadStorage,
    supervisor: Callable[[], WorkerSupervisorJournal],
    attempt_id: str,
) -> str:
    record = supervisor().status(attempt_id)
    if record is None or not record.process_settled:
        raise storage.error_type("coding_worker_payload_process_unsettled")
    return sha256(canonical_json_bytes(record.to_dict())).hexdigest()


def repair_empty(
    storage: PayloadStorage,
    root_fd: int,
    *,
    expected_plan: EmptyPayloadPlan,
    supervisor: Callable[[], WorkerSupervisorJournal],
) -> EmptyPayloadPlan:
    """Remove an exact empty stage only when Supervisor never claimed it."""
    prior = storage.empty.read(root_fd, expected_plan.attempt_id)
    if prior is not None and prior != expected_plan:
        raise storage.error_type("coding_worker_payload_debt_plan_stale")
    if prior is not None and (
        not storage._stage_exists(root_fd, expected_plan.attempt_id)
    ):
        if supervisor().status(expected_plan.attempt_id) is not None:
            raise storage.error_type("coding_worker_payload_attempt_claimed")
        storage.empty.settle(root_fd, expected_plan.attempt_id, expected_plan)
        return expected_plan
    current = storage._verify_empty_debt(root_fd, expected_plan.attempt_id)
    if current != expected_plan:
        raise storage.error_type("coding_worker_payload_debt_plan_stale")
    if supervisor().status(current.attempt_id) is not None:
        raise storage.error_type("coding_worker_payload_attempt_claimed")
    stage_name = f"worker-payload-{current.attempt_id}"
    stage_fd = os.open(stage_name, _DIR_FLAGS, dir_fd=root_fd)
    try:
        storage._require_visible_stage(stage_name, root_fd, stage_fd)
        opened = os.fstat(stage_fd)
        if (opened.st_dev, opened.st_ino) != (
            current.stage_device,
            current.stage_inode,
        ) or os.listdir(stage_fd):
            raise storage.error_type("coding_worker_payload_debt_plan_stale")
        storage.empty.publish(root_fd, current.attempt_id, current)
        storage._require_visible_stage(stage_name, root_fd, stage_fd)
        storage._remove_empty_stage(root_fd, stage_name)
    finally:
        os.close(stage_fd)
    return current
