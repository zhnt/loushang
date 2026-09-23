"""POSIX cutover lock composition over real runtime and pre-fence owners.

The pre-fence owner must retain its launch barrier for the full context. An
empty fence-aware runtime set alone never authorizes the first B epoch.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Protocol

from loushang.harness.resources.packages.plugin_lifecycle.lease_registry import (
    PackageEpochRuntimeLeaseRegistry,
)
from loushang.harness.resources.packages.plugin_lifecycle.posix_epoch_cutover import (
    PackageEpochCutoverQuiescenceReceiptV1,
)

_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


@dataclass(frozen=True, slots=True)
class PackagePreFenceRegistrationSnapshotV1:
    """Complete old-process registration set under a held launch barrier."""

    store_id: str
    owner_revision: int
    active_registration_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.store_id, str) or _SAFE_ID.fullmatch(self.store_id) is None:
            raise ValueError("Pre-fence registration store is invalid")
        if type(self.owner_revision) is not int or self.owner_revision < 1:
            raise ValueError("Pre-fence registration revision is invalid")
        values = self.active_registration_ids
        if (
            type(values) is not tuple
            or values != tuple(sorted(set(values)))
            or any(type(value) is not str or _SHA256.fullmatch(value) is None for value in values)
        ):
            raise ValueError("Pre-fence registration set is invalid")


class PackagePreFenceRegistrationQuiescencePort(Protocol):
    """Product-owned scope that blocks old process launches and proves liveness."""

    def exclusive_quiescence(
        self, *, store_id: str
    ) -> AbstractContextManager[PackagePreFenceRegistrationSnapshotV1]: ...


class PackagePosixEpochCutoverCoordination:
    """Combine both complete process sets while retaining both exclusion scopes."""

    def __init__(
        self,
        *,
        leases: PackageEpochRuntimeLeaseRegistry,
        pre_fence: PackagePreFenceRegistrationQuiescencePort,
    ) -> None:
        if not isinstance(leases, PackageEpochRuntimeLeaseRegistry):
            raise TypeError("Rooted Package runtime lease owner is required")
        if not callable(getattr(pre_fence, "exclusive_quiescence", None)):
            raise TypeError("Pre-fence launch and registration owner is required")
        self._leases = leases
        self._pre_fence = pre_fence

    @contextmanager
    def exclusive_quiescence(
        self, *, store_id: str
    ) -> Iterator[PackageEpochCutoverQuiescenceReceiptV1]:
        if store_id != self._leases.store_id:
            raise ValueError("Package cutover coordination store changed")
        with self._pre_fence.exclusive_quiescence(store_id=store_id) as pre_fence:
            if (
                not isinstance(pre_fence, PackagePreFenceRegistrationSnapshotV1)
                or pre_fence.store_id != store_id
            ):
                raise TypeError("Pre-fence registration evidence changed")
            with self._leases.exclusive_runtime_quiescence(
                store_id=store_id
            ) as runtime:
                if runtime.store_id != store_id:
                    raise ValueError("Package runtime quiescence store changed")
                yield PackageEpochCutoverQuiescenceReceiptV1.create(
                    store_id=store_id,
                    owner_revision=(
                        pre_fence.owner_revision + runtime.owner_revision
                    ),
                    active_runtime_lease_ids=(
                        runtime.active_runtime_lease_ids
                    ),
                    active_pre_fence_registration_ids=(
                        pre_fence.active_registration_ids
                    ),
                )


__all__ = [
    "PackagePosixEpochCutoverCoordination",
    "PackagePreFenceRegistrationQuiescencePort",
    "PackagePreFenceRegistrationSnapshotV1",
]
