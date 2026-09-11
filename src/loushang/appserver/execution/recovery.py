"""One user submission's recovery state, usable by GUI and other clients.

Transport failure means unknown. Recovery only queries; retry is an explicit
action with the original instance, submission ID and exact input. No fallback
to legacy start_turn and no automatic replay across application restarts.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass, replace
from enum import Enum

from ..protocol import (
    InvalidAppMessageError,
    SessionIdentityV1,
    SessionSnapshotRequestV1,
)
from .client import ExecutionClientV1
from .model import (
    ExecutionErrorCodeV1,
    ExecutionRecordV1,
    ExecutionRequestV1,
    ExecutionServiceErrorV1,
    ExecutionSessionSnapshotV1,
    ExecutionStateV1,
    _identifier,
)


class SubmissionDeliveryV1(str, Enum):
    READY = "ready"
    SENDING = "sending"
    UNKNOWN = "unknown"
    NOT_FOUND = "not_found"
    KNOWN = "known"
    INSTANCE_CHANGED = "instance_changed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class PendingSubmissionV1:
    service_instance_id: str
    identity: SessionIdentityV1
    submission_id: str
    text: str

    def __post_init__(self) -> None:
        _identifier(self.service_instance_id)
        _identifier(self.submission_id)
        if type(self.identity) is not SessionIdentityV1:
            raise TypeError("invalid pending submission identity")
        ExecutionRequestV1("validation", self.text)


class SubmissionRecoveryV1:
    def __init__(self, pending: PendingSubmissionV1) -> None:
        if type(pending) is not PendingSubmissionV1:
            raise TypeError("invalid pending submission")
        self.pending = pending
        self.delivery = SubmissionDeliveryV1.READY
        self.record: ExecutionRecordV1 | None = None
        self._observed: OrderedDict[str, ExecutionStateV1] = OrderedDict()
        self._busy = False

    def _same_instance(self, client: ExecutionClientV1) -> bool:
        if client.service_instance_id == self.pending.service_instance_id:
            return True
        self.delivery = SubmissionDeliveryV1.INSTANCE_CHANGED
        return False

    async def submit(self, client: ExecutionClientV1, control: SessionSnapshotRequestV1) -> None:
        """Explicit initial send/retry; this method never manufactures an ID."""
        if self._busy:
            raise RuntimeError("submission delivery already in progress")
        if not self._same_instance(client):
            return
        self._busy = True
        self.delivery = SubmissionDeliveryV1.SENDING
        try:
            record = await client.submit_execution(
                control, self.pending.service_instance_id,
                self.pending.submission_id, self.pending.text,
            )
            self._merge_record(record)
        except ExecutionServiceErrorV1 as error:
            self.delivery = (SubmissionDeliveryV1.INSTANCE_CHANGED
                             if error.code is ExecutionErrorCodeV1.INSTANCE_CHANGED
                             else SubmissionDeliveryV1.REJECTED)
            raise
        except BaseException:
            self.delivery = SubmissionDeliveryV1.UNKNOWN
            raise
        finally:
            self._busy = False

    async def recover(self, client: ExecutionClientV1, control: SessionSnapshotRequestV1) -> None:
        """Read only: a racing not_found does not cause another submission."""
        if self._busy:
            raise RuntimeError("submission delivery already in progress")
        if not self._same_instance(client):
            return
        self._busy = True
        try:
            record = await client.find_execution_by_submission(
                control, self.pending.service_instance_id, self.pending.submission_id,
            )
            if record is None:
                self.delivery = SubmissionDeliveryV1.NOT_FOUND
            else:
                self._merge_record(record)
        except ExecutionServiceErrorV1 as error:
            self.delivery = (SubmissionDeliveryV1.INSTANCE_CHANGED
                             if error.code is ExecutionErrorCodeV1.INSTANCE_CHANGED
                             else SubmissionDeliveryV1.UNKNOWN)
            raise
        except (Exception, asyncio.CancelledError):
            self.delivery = SubmissionDeliveryV1.UNKNOWN
            raise
        finally:
            self._busy = False

    def observe(self, state: ExecutionStateV1) -> None:
        """Caller supplies metadata from its current authorized attachment only."""
        if type(state) is not ExecutionStateV1:
            raise TypeError("invalid execution state")
        prior = self._observed.get(state.execution_id)
        if (self.record is not None and self.record.state.execution_id == state.execution_id
                and (prior is None or prior.revision < self.record.state.revision)):
            prior = self.record.state
        if prior is not None:
            if state.revision < prior.revision:
                return
            if state.revision == prior.revision and state != prior:
                self.delivery = SubmissionDeliveryV1.UNKNOWN
                raise InvalidAppMessageError()
        self._observed[state.execution_id] = state
        self._observed.move_to_end(state.execution_id)
        while len(self._observed) > 32:
            self._observed.popitem(last=False)
        if (self.record is not None and self.record.state.execution_id == state.execution_id
                and state.revision >= self.record.state.revision):
            self.record = replace(self.record, state=state)

    def replace_snapshot(self, snapshot: ExecutionSessionSnapshotV1) -> None:
        if snapshot.service_instance_id != self.pending.service_instance_id:
            self.delivery = SubmissionDeliveryV1.INSTANCE_CHANGED
            return
        if snapshot.executions.identity != self.pending.identity:
            raise InvalidAppMessageError()
        self._observed.clear()
        for state in (snapshot.executions.active, snapshot.executions.latest_terminal):
            if state is not None:
                self.observe(state)

    def _merge_record(self, record: ExecutionRecordV1) -> None:
        if record.service_instance_id != self.pending.service_instance_id or (
            record.identity != self.pending.identity or record.submission_id != self.pending.submission_id
        ):
            raise InvalidAppMessageError()
        if self.record is not None and self.record.state.execution_id != record.state.execution_id:
            raise InvalidAppMessageError()
        prior = self._observed.get(record.state.execution_id)
        if prior is not None and prior.revision == record.state.revision and prior != record.state:
            raise InvalidAppMessageError()
        if prior is not None and prior.revision > record.state.revision:
            record = replace(record, state=prior)
        if self.record is not None and self.record.state.revision == record.state.revision and self.record != record:
            raise InvalidAppMessageError()
        if self.record is None or self.record.state.revision <= record.state.revision:
            self.record = record
        self.delivery = SubmissionDeliveryV1.KNOWN


__all__ = ["PendingSubmissionV1", "SubmissionDeliveryV1", "SubmissionRecoveryV1"]
