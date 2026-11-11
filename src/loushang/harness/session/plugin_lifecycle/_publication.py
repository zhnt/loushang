"""Ephemeral exact-owner publication at the original Session graph boundary."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Generic, Protocol, TypeVar

from loushang.harness.capabilities import StagedResourceCompositionCandidate
from loushang.harness.runtime.registration import OwnerGenerationRetirementReceipt
from loushang.harness.session.capability_composition_inputs import (
    StagedSessionCapabilityOwnerGeneration,
)

from ._owner_evidence import _receipt_identity

OwnerReceipts = tuple[OwnerGenerationRetirementReceipt, ...]
OwnerReceiptGroups = Mapping[str, OwnerReceipts]
OwnerGenerations = tuple[StagedSessionCapabilityOwnerGeneration, ...]
OwnerContributions = tuple[tuple[str, tuple[str, ...]], ...]
ReceiptT = TypeVar("ReceiptT")
ReceiptContraT = TypeVar("ReceiptContraT", contravariant=True)
OwnerCapture = Callable[
    [OwnerGenerations, StagedResourceCompositionCandidate | None, bool], ReceiptT
]


class _OwnerEvidenceTarget(Protocol[ReceiptContraT]):
    def prepare_owner_generations(self, receipts: ReceiptContraT) -> None: ...

    def publish_owner_generations(self, receipts: ReceiptContraT) -> None: ...

    def retire_owner_generations(self, receipts: ReceiptContraT) -> None: ...


class _OwnerPublicationHooks(Protocol):
    def prepare_from(
        self,
        generations: OwnerGenerations,
        candidate: StagedResourceCompositionCandidate | None,
    ) -> None: ...

    def commit_after_graph(self) -> None: ...


class _OwnerLeaseSet:
    """The original ordered fanout, shared with existing assembly facades."""

    def __init__(
        self, leases: Mapping[str, _OwnerEvidenceTarget[OwnerReceipts]]
    ) -> None:
        self._leases = leases

    def has_targets(self) -> bool:
        return bool(self._leases)

    def prepare_owner_generations(self, receipts: OwnerReceiptGroups) -> None:
        for plugin_id, lease in self._leases.items():
            lease.prepare_owner_generations(receipts.get(plugin_id, ()))

    def publish_owner_generations(self, receipts: OwnerReceiptGroups) -> None:
        for plugin_id, lease in self._leases.items():
            lease.publish_owner_generations(receipts.get(plugin_id, ()))

    def retire_owner_generations(self, receipts: OwnerReceiptGroups) -> None:
        for plugin_id, lease in self._leases.items():
            lease.retire_owner_generations(receipts.get(plugin_id, ()))


class _OwnerPublication(Generic[ReceiptT]):
    """One receipt value, flags and one pending publication error.

    This owns no journal or Graph. The original callers retain stage/commit
    order and the actual graph-retirement qualification for each group.
    """

    def __init__(
        self,
        target: _OwnerEvidenceTarget[ReceiptT],
        capture: OwnerCapture[ReceiptT],
        empty_receipts: ReceiptT,
        has_targets: Callable[[], bool] | None = None,
    ) -> None:
        self._target = target
        self._capture = capture
        self._receipts = empty_receipts
        self._has_targets = has_targets
        self._prepared = False
        self._published = False
        self._retired = False
        self._error: BaseException | None = None

    @property
    def receipts(self) -> ReceiptT:
        return self._receipts

    @property
    def prepared(self) -> bool:
        return self._prepared

    @property
    def published(self) -> bool:
        return self._published

    @property
    def retired(self) -> bool:
        return self._retired

    @property
    def publication_error(self) -> BaseException | None:
        return self._error

    def prepare_from(
        self,
        generations: OwnerGenerations,
        candidate: StagedResourceCompositionCandidate | None,
    ) -> None:
        # A present empty lease set still captures and becomes prepared.
        # Repeated stage does not reset previously successful flags.
        self._receipts = self._capture(generations, candidate, True)
        self._target.prepare_owner_generations(self._receipts)
        self._prepared = True

    def commit_after_graph(self) -> None:
        if self._receipts and not self._published:
            try:
                self._target.publish_owner_generations(self._receipts)
            except BaseException as error:
                self._error = error
            else:
                self._published = True

    def require_published(
        self,
        inputs: Callable[
            [], tuple[OwnerGenerations, StagedResourceCompositionCandidate | None]
        ],
    ) -> None:
        if self._has_targets is not None and not self._has_targets():
            return
        error = self._error
        if error is not None:
            self._error = None
            raise error
        if not self._receipts:
            generations, candidate = inputs()
            self._receipts = self._capture(generations, candidate, False)
        if not self._prepared:
            self._target.prepare_owner_generations(self._receipts)
            self._prepared = True
        if not self._published:
            self._target.publish_owner_generations(self._receipts)
            self._published = True

    def retire_after_graph(self) -> None:
        """Called at the original group's qualified retirement point only."""
        if not self._receipts or self._retired:
            return
        if not self._prepared:
            self._target.prepare_owner_generations(self._receipts)
            self._prepared = True
        self._target.retire_owner_generations(self._receipts)
        self._retired = True


def _capture_generation_receipts(
    generations: OwnerGenerations, plugin_id: str, prepared: bool
) -> list[OwnerGenerationRetirementReceipt]:
    return [
        (
            generation.capture_prepared_retirement_receipt()
            if prepared
            else generation.capture_retirement_receipt()
        )
        for generation in generations
        if generation.binding.plugin_id == plugin_id
    ]


def _single_owner_publication(
    lease: _OwnerEvidenceTarget[OwnerReceipts],
    *,
    plugin_id: str,
    owner_contributions: Callable[[], OwnerContributions | None],
    resource_owner_prefix: str,
    missing_candidate_message: str,
) -> _OwnerPublication[OwnerReceipts]:
    def capture(
        generations: OwnerGenerations,
        candidate: StagedResourceCompositionCandidate | None,
        prepared: bool,
    ) -> OwnerReceipts:
        receipts = _capture_generation_receipts(generations, plugin_id, prepared)
        owners = owner_contributions()
        if owners is None:
            return ()
        resource_ids = tuple(
            sorted(
                {
                    contribution_id
                    for owner_reference, contribution_ids in owners
                    if owner_reference.startswith(resource_owner_prefix)
                    for contribution_id in contribution_ids
                }
            )
        )
        if resource_ids:
            if candidate is None:
                raise RuntimeError(missing_candidate_message)
            receipts.append(
                candidate.resource_owner_generation_retirement_receipt(
                    contribution_ids=resource_ids,
                )
            )
        return tuple(sorted(receipts, key=_receipt_identity))

    return _OwnerPublication(lease, capture, ())


def _owner_set_publication(
    leases: Mapping[str, _OwnerEvidenceTarget[OwnerReceipts]],
    plugin_ids: Callable[[], Iterable[str]],
) -> _OwnerPublication[OwnerReceiptGroups]:
    def capture(
        generations: OwnerGenerations,
        _candidate: StagedResourceCompositionCandidate | None,
        prepared: bool,
    ) -> OwnerReceiptGroups:
        return {
            plugin_id: tuple(
                sorted(
                    _capture_generation_receipts(generations, plugin_id, prepared),
                    key=_receipt_identity,
                )
            )
            for plugin_id in plugin_ids()
        }

    target = _OwnerLeaseSet(leases)
    return _OwnerPublication(target, capture, {}, target.has_targets)
