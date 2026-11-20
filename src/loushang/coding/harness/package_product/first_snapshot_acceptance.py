"""Accept and reopen a frozen first-snapshot review through its receipt journal."""

from collections.abc import Callable
from typing import TypeVar

from loushang.harness.package_product._legacy_local_migration import (
    _FirstAcceptanceJournal,
)
from loushang.harness.resources.packages.product_epoch_guard import (
    PackageProductPosixFencedRuntimeOwner,
)
from loushang.harness.resources.packages.product_windows_epoch_guard import (
    PackageProductWindowsFencedRuntimeOwner,
)

_Runtime = PackageProductPosixFencedRuntimeOwner | PackageProductWindowsFencedRuntimeOwner
_RecordT = TypeVar("_RecordT")
_ReviewT = TypeVar("_ReviewT")


def accept_review(
    runtime: _Runtime,
    journal: _FirstAcceptanceJournal[_RecordT],
    *,
    accepted_review_id: str,
    current_review_id: str,
    create: Callable[[], _RecordT],
    expected_store_id: Callable[[], str],
    changed_review: str,
    conflict_message: str,
) -> _RecordT:
    if accepted_review_id != current_review_id:
        raise journal.error_type(changed_review)
    proposed = create()
    _require_store(runtime, expected_store_id(), journal.error_type)
    return journal.accept(runtime, proposed, conflict_message=conflict_message)


def read_acceptance(
    runtime: _Runtime,
    journal: _FirstAcceptanceJournal[_RecordT],
    *,
    expected_store_id: str,
    review: Callable[[], _ReviewT],
    create: Callable[[_ReviewT], _RecordT],
    conflict_message: str,
    check_epoch_before_read: bool = False,
    empty_is_missing: bool = True,
) -> _RecordT | None:
    _require_store(runtime, expected_store_id, journal.error_type)
    if check_epoch_before_read:
        runtime.assert_current()
    path = runtime.control_root / "product-state" / journal.filename
    if check_epoch_before_read:
        records = journal.records(
            path, windows=isinstance(runtime, PackageProductWindowsFencedRuntimeOwner)
        )
    else:
        records = journal.records(path)
    if records is None or (empty_is_missing and not records):
        if check_epoch_before_read:
            runtime.assert_current()
        return None
    current_review = review()
    if len(records) != 1 or records[0] != create(current_review):
        raise journal.error_type(conflict_message)
    runtime.assert_current()
    return records[0]


def _require_store(
    runtime: _Runtime, expected_store_id: str, error_type: type[Exception]
) -> None:
    if runtime.registry.store_id != expected_store_id:
        raise error_type("Product Store changed")
