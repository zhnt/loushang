"""Durable instance generations under one stable service lifecycle fence.

These records coordinate trusted owners. They neither discover live processes
nor confer permission to kill one. A child-side owner alone proposes commit;
trusted Hosting callers supply native lookup values and settlement facts.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from secrets import token_hex

from loushang.hosting.errors import HostingError
from loushang.hosting.service import LinuxServiceIdentityV1

from ._files import (
    ManagedStorageError,
    PrivateManagedDirectory,
    _check_deadline,
    _check_lock_wait,
)
from .admission_record import (
    ManagedInitializationPhaseV1,
    ManagedServiceAdmissionRecordV1,
)
from .contracts import (
    _HEX32,
    ManagedContractError,
    ManagedHandoffPhaseV1,
    ManagedHandoffV1,
    ManagedInstanceRefV1,
    ManagedNamespaceV1,
    ManagedServiceKeyV1,
    ManagedStopEvidenceV1,
    _match,
)
from .registry import ManagedRegistryV1

_MAX_REVISION = 2**63 - 1


@dataclass(frozen=True, slots=True)
class ManagedTraceApplicationV1:
    """Historical configuration fact, never a promise of continuing writes."""

    instance_id: str
    attempt_id: str
    deadline_ms: int
    configuration: str = "aggregate/v1"

    def __post_init__(self) -> None:
        _match(self.instance_id, _HEX32)
        _match(self.attempt_id, _HEX32)
        if (type(self.deadline_ms) is not int or not 0 < self.deadline_ms <= 10**15
                or type(self.configuration) is not str or self.configuration != "aggregate/v1"):
            raise ManagedContractError()


@dataclass(frozen=True, slots=True)
class ManagedServiceStateV1:
    """Last durable observation; not an assertion that an instance is alive."""

    revision: int
    handoff: ManagedHandoffV1
    evidence: ManagedStopEvidenceV1
    native_identity: LinuxServiceIdentityV1 | None = None
    trace_application: ManagedTraceApplicationV1 | None = None

    def __post_init__(self) -> None:
        if (
            type(self.revision) is not int or not 1 <= self.revision <= _MAX_REVISION
            or type(self.handoff) is not ManagedHandoffV1
            or type(self.evidence) is not ManagedStopEvidenceV1
            or self.handoff.instance != self.evidence.instance
            or (self.native_identity is not None and type(self.native_identity) is not LinuxServiceIdentityV1)
            or (self.handoff.phase is ManagedHandoffPhaseV1.COMMITTED and self.native_identity is None)
        ):
            raise ManagedContractError()
        trace = self.trace_application
        if trace is not None and (
            type(trace) is not ManagedTraceApplicationV1 or self.native_identity is None
            or trace.instance_id != self.handoff.instance.instance_id
            or trace.attempt_id != self.handoff.attempt_id
        ):
            raise ManagedContractError()
        if (
            not self.handoff.stop_requested
            and self.handoff.phase is not ManagedHandoffPhaseV1.ABORTING
            and (self.evidence.process_exited or self.evidence.application_cleanup_completed
                 or self.evidence.process_scope_settled)
        ):
            raise ManagedContractError()

    @property
    def cleanly_stopped(self) -> bool:
        return self.evidence.cleanly_stopped


@dataclass(frozen=True, slots=True)
class ManagedServiceTransitionV1:
    """This generation's immutable predecessor evidence, not recovery authority."""

    instance: ManagedInstanceRefV1
    attempt_id: str
    started_revision: int
    previous: ManagedServiceStateV1 | None

    def __post_init__(self) -> None:
        if (type(self.instance) is not ManagedInstanceRefV1 or type(self.started_revision) is not int
                or not 1 <= self.started_revision <= _MAX_REVISION):
            raise ManagedContractError()
        _match(self.attempt_id, _HEX32)
        previous = self.previous
        if previous is None:
            if self.started_revision != 1:
                raise ManagedContractError()
        elif (type(previous) is not ManagedServiceStateV1 or not previous.cleanly_stopped
                or previous.handoff.instance.namespace_key != self.instance.namespace_key
                or previous.handoff.instance.service_id != self.instance.service_id
                or previous.handoff.instance == self.instance
                or previous.handoff.attempt_id == self.attempt_id
                or previous.revision + 1 != self.started_revision):
            raise ManagedContractError()


class ManagedServiceJournalV1:
    """Borrow a registry; own only the injected per-service fence directory.

    Lock order is service fence, then short registry transaction. No network IO,
    process wait or caller callback is performed while either lock is held.
    This slice permits only clean reuse. Unclean retirement/recovery admission
    still needs a separate native proof; never invent application cleanup facts.
    """

    def __init__(
        self, registry: ManagedRegistryV1, namespace: ManagedNamespaceV1,
        service: ManagedServiceKeyV1, lifecycle_root: Path, *, create: bool = False, defer_open: bool = False,
    ) -> None:
        if (type(registry) is not ManagedRegistryV1 or type(namespace) is not ManagedNamespaceV1
                or type(service) is not ManagedServiceKeyV1):
            raise ManagedContractError()
        self._database = registry._database
        if self._database._namespace != namespace.namespace_key:
            raise ManagedContractError()
        self._namespace, self._service = namespace, service
        if type(defer_open) is not bool:
            raise ManagedContractError()
        self._create = create
        self._opened = False
        self._fence = PrivateManagedDirectory(lifecycle_root, create=create, defer_open=True)
        if defer_open:
            return
        try:
            self.open()
        except BaseException as error:
            try:
                self._fence.close()
            except BaseException:
                error.add_note("managed_lifecycle_cleanup_incomplete")
            raise

    def open(self, *, deadline: float | None = None, wait_for_lock: bool = False) -> None:
        _check_lock_wait(wait_for_lock, deadline)
        if self._database.service_admission_required and self._create:
            # Managed control creation belongs to the durable admission owner,
            # never to an opportunistic journal open or a missing instance.
            raise ManagedStorageError("conflict")
        if self._database.service_admission_required:
            # A fresh lifecycle.lock exists before its creator can flock it.
            # Do not steal that lock while its control fact is missing or
            # initializing. This negative check grants no fence authority.
            with self._database.transaction(deadline=deadline, wait_for_lock=wait_for_lock) as connection:
                self._read_control(connection)
        self._fence.open(deadline=deadline)
        if self._create:
            with self._fence.lock("lifecycle.lock", create=True, deadline=deadline, wait_for_lock=wait_for_lock):
                pass
        if self._database.service_admission_required:
            with self._fence.lock("lifecycle.lock", deadline=deadline, wait_for_lock=wait_for_lock), self._database.transaction(
                deadline=deadline, wait_for_lock=wait_for_lock,
            ) as connection:
                self._read(connection)
        _check_deadline(deadline)
        self._opened = True

    def close(self) -> None:
        self._opened = False
        self._fence.close()

    def read(self, *, deadline: float | None = None, wait_for_lock: bool = False) -> ManagedServiceStateV1 | None:
        self._require_open()
        with self._fence.lock("lifecycle.lock", deadline=deadline, wait_for_lock=wait_for_lock), self._database.transaction(
            deadline=deadline, wait_for_lock=wait_for_lock,
        ) as connection:
            result = self._read(connection)
            self._fence._check()
            return result

    def prepare(
        self, attempt_id: str, *, expected: ManagedServiceStateV1 | None,
        deadline: float | None = None,
    ) -> ManagedServiceStateV1:
        """Reserve a fresh generation, never infer absence from socket/PID loss.

        An uncertain result is resolved by read(), not by repeating process spawn.
        Existing generations require all three matching stop facts before reuse.
        """
        self._require_open()
        _match(attempt_id, _HEX32)
        if expected is not None and type(expected) is not ManagedServiceStateV1:
            raise ManagedContractError()
        with self._fence.lock("lifecycle.lock", deadline=deadline), self._database.transaction(write=True, deadline=deadline) as connection:
            current = self._read(connection)
            if current != expected:
                raise ManagedStorageError("conflict")
            if current is not None:
                if not current.cleanly_stopped:
                    raise ManagedStorageError("busy")
                if attempt_id == current.handoff.attempt_id:
                    raise ManagedStorageError("conflict")
            self._database.admit_growth(connection)
            instance_id = token_hex(16)
            if current is not None and instance_id == current.handoff.instance.instance_id:
                raise ManagedStorageError("conflict")
            instance = ManagedInstanceRefV1(self._namespace.namespace_key,
                                            self._service.service_id, instance_id)
            state = ManagedServiceStateV1(
                _next_revision(current), ManagedHandoffV1(instance, attempt_id),
                ManagedStopEvidenceV1(instance, False, False, False),
            )
            self._save(connection, state, insert=current is None)
            transition = ManagedServiceTransitionV1(instance, attempt_id, state.revision, current)
            connection.execute(
                "INSERT INTO service_transitions VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(service_id) DO UPDATE SET instance_id=excluded.instance_id, "
                "attempt_id=excluded.attempt_id, started_revision=excluded.started_revision, previous=excluded.previous",
                (self._service.service_id, instance_id, attempt_id, transition.started_revision, _encode_previous(current)),
            )
            self._fence._check()
            return state

    def read_transition(self, *, deadline: float | None = None) -> ManagedServiceTransitionV1 | None:
        """Read a paired snapshot under the original fence, without repairing it."""
        self._require_open()
        with self._fence.lock("lifecycle.lock", deadline=deadline), self._database.transaction(deadline=deadline) as connection:
            state = self._read_state(connection)
            result = self._read_transition(connection, state)
            self._fence._check()
            return result

    def register_native(
        self, instance: ManagedInstanceRefV1, attempt_id: str, identity: LinuxServiceIdentityV1,
        *, deadline: float | None = None,
    ) -> ManagedServiceStateV1:
        """Persist the trusted launch owner's capture, once per generation.

        This value is a lookup record, not current liveness or signal authority.
        Same-value retries are idempotent even after commit; identity replacement
        or new registration after stop/abort is never admitted.
        """
        _match(attempt_id, _HEX32)
        self._require_native(identity)

        def update(current: ManagedServiceStateV1) -> ManagedServiceStateV1:
            if current.handoff.attempt_id != attempt_id:
                raise ManagedStorageError("conflict")
            if current.native_identity == identity:
                return current
            if (current.native_identity is not None
                    or current.handoff.phase is not ManagedHandoffPhaseV1.PROVISIONAL
                    or current.handoff.stop_requested):
                raise ManagedStorageError("conflict")
            return replace(current, native_identity=identity)

        return self._update(instance, update, deadline=deadline)

    def _require_native(self, identity: LinuxServiceIdentityV1 | None) -> None:
        if type(identity) is not LinuxServiceIdentityV1 or identity.user_id != self._namespace.user_id:
            raise ManagedContractError()

    def commit(
        self, instance: ManagedInstanceRefV1, attempt_id: str, *,
        native_identity: LinuxServiceIdentityV1 | None = None, deadline: float | None = None,
    ) -> ManagedServiceStateV1:
        """Child proposal requires the durable native binding and no stop/abort."""
        _match(attempt_id, _HEX32)
        self._require_native(native_identity)

        def update(current: ManagedServiceStateV1) -> ManagedServiceStateV1:
            if current.handoff.attempt_id != attempt_id or current.native_identity != native_identity:
                raise ManagedStorageError("conflict")
            return replace(current, handoff=current.handoff.commit())

        return self._update(instance, update, deadline=deadline)

    def record_trace_application(
        self, instance: ManagedInstanceRefV1, attempt_id: str, *,
        native_identity: LinuxServiceIdentityV1, trace_deadline_ms: int,
        deadline: float | None = None,
    ) -> ManagedServiceStateV1:
        """Child publishes after sink/consumer/storage admission, not before.

        This trusted composition seam does not itself install or inspect sinks.
        The same fact is idempotent; stopped/replaced attempts cannot first
        publish it, and unknown transaction results require original reobserve.
        """
        self._require_instance(instance)
        self._require_native(native_identity)
        receipt = ManagedTraceApplicationV1(instance.instance_id, attempt_id, trace_deadline_ms)
        def update(current: ManagedServiceStateV1) -> ManagedServiceStateV1:
            if current.handoff.attempt_id != attempt_id or current.native_identity != native_identity:
                raise ManagedStorageError("conflict")
            if current.trace_application is not None:
                if current.trace_application != receipt:
                    raise ManagedStorageError("conflict")
                return current
            if current.handoff.stop_requested or current.handoff.phase is ManagedHandoffPhaseV1.ABORTING:
                raise ManagedStorageError("conflict")
            _check_deadline(trace_deadline_ms / 1000)
            return replace(current, trace_application=receipt)
        # Historical same-value reads remain valid after expiry. A new write
        # uses the trace window for the entire transaction, including its
        # pre-COMMIT check, and rechecks the instance under the write fence.
        observed = self.read(deadline=deadline, wait_for_lock=deadline is not None)
        if observed is None or observed.handoff.instance != instance:
            raise ManagedStorageError("conflict")
        if observed.trace_application is not None:
            return update(observed)
        publication_deadline = trace_deadline_ms / 1000
        if deadline is not None:
            publication_deadline = min(deadline, publication_deadline)
        return self._update(instance, update, deadline=publication_deadline, normal_growth=True, wait_for_lock=True)

    def abort(
        self, instance: ManagedInstanceRefV1, attempt_id: str, *,
        native_identity: LinuxServiceIdentityV1 | None = None, deadline: float | None = None,
    ) -> ManagedServiceStateV1:
        """Starter may abort by exact attempt; bound children must match birth.

        Before birth registration, EOF still permits provisional child cleanup.
        After registration, a child with a different native identity cannot
        mutate the attempt. The check and transition share one transaction.
        """
        _match(attempt_id, _HEX32)
        if native_identity is not None:
            self._require_native(native_identity)

        def update(current: ManagedServiceStateV1) -> ManagedServiceStateV1:
            if current.handoff.attempt_id != attempt_id:
                raise ManagedStorageError("conflict")
            if (native_identity is not None and current.native_identity is not None
                    and native_identity != current.native_identity):
                raise ManagedStorageError("conflict")
            return replace(current, handoff=current.handoff.abort())

        return self._update(instance, update, deadline=deadline)

    def request_stop(self, instance: ManagedInstanceRefV1, *, deadline: float | None = None) -> ManagedServiceStateV1:
        return self._update(instance, lambda current: replace(
            current, handoff=current.handoff.request_stop(),
        ), deadline=deadline)

    def request_child_stop(
        self, instance: ManagedInstanceRefV1, attempt_id: str, native_identity: LinuxServiceIdentityV1,
        *, deadline: float | None = None,
    ) -> ManagedServiceStateV1:
        """Child's explicit stop, atomically bound to its attempt and birth.

        Provisional stop includes abort, preventing a later handoff commit.
        A committed service is stopped, never rewritten as an aborted startup.
        Pre-registration stop remains possible if its starter died before birth.
        """
        _match(attempt_id, _HEX32)
        self._require_native(native_identity)

        def update(current: ManagedServiceStateV1) -> ManagedServiceStateV1:
            self._match_child(current, attempt_id, native_identity)
            handoff = current.handoff
            if handoff.phase is ManagedHandoffPhaseV1.PROVISIONAL:
                handoff = handoff.abort()
            return replace(current, handoff=handoff.request_stop())

        return self._update(instance, update, deadline=deadline)

    def record_child_cleanup(
        self, instance: ManagedInstanceRefV1, attempt_id: str, native_identity: LinuxServiceIdentityV1,
        *, deadline: float | None = None,
    ) -> ManagedServiceStateV1:
        """Record only successful application cleanup, never child/process exit."""
        _match(attempt_id, _HEX32)
        self._require_native(native_identity)

        def update(current: ManagedServiceStateV1) -> ManagedServiceStateV1:
            self._match_child(current, attempt_id, native_identity)
            if not current.handoff.stop_requested and current.handoff.phase is not ManagedHandoffPhaseV1.ABORTING:
                raise ManagedStorageError("conflict")
            return replace(current, evidence=replace(current.evidence, application_cleanup_completed=True))

        return self._update(instance, update, deadline=deadline)

    @staticmethod
    def _match_child(current: ManagedServiceStateV1, attempt_id: str, native: LinuxServiceIdentityV1) -> None:
        if (current.handoff.attempt_id != attempt_id
                or current.native_identity is not None and current.native_identity != native):
            raise ManagedStorageError("conflict")

    def record_native_stop(
        self, instance: ManagedInstanceRefV1, native_identity: LinuxServiceIdentityV1, *,
        process_exited: bool, process_scope_settled: bool, deadline: float,
    ) -> ManagedServiceStateV1:
        """Native-only monotonic facts; never accept an application-cleanup bit."""
        self._require_native(native_identity)
        if type(deadline) not in (int, float) or not 0 < deadline <= 1e12:
            raise ManagedContractError()
        if (type(process_exited) is not bool or type(process_scope_settled) is not bool
                or process_scope_settled and not process_exited):
            raise ManagedContractError()

        def update(current: ManagedServiceStateV1) -> ManagedServiceStateV1:
            if (current.native_identity != native_identity or not current.handoff.stop_requested
                    and current.handoff.phase is not ManagedHandoffPhaseV1.ABORTING):
                raise ManagedStorageError("conflict")
            prior = current.evidence
            return replace(current, evidence=replace(
                prior, process_exited=prior.process_exited or process_exited,
                process_scope_settled=prior.process_scope_settled or process_scope_settled,
            ))

        return self._update(instance, update, deadline=deadline)

    def record_stop_evidence(self, evidence: ManagedStopEvidenceV1) -> ManagedServiceStateV1:
        """Join monotonic facts from the trusted native/application observers."""
        if type(evidence) is not ManagedStopEvidenceV1:
            raise ManagedContractError()

        def update(current: ManagedServiceStateV1) -> ManagedServiceStateV1:
            if not current.handoff.stop_requested and current.handoff.phase is not ManagedHandoffPhaseV1.ABORTING:
                raise ManagedStorageError("conflict")
            prior = current.evidence
            joined = ManagedStopEvidenceV1(
                evidence.instance, prior.process_exited or evidence.process_exited,
                prior.application_cleanup_completed or evidence.application_cleanup_completed,
                prior.process_scope_settled or evidence.process_scope_settled,
            )
            return replace(current, evidence=joined)

        return self._update(evidence.instance, update)

    def _update(
        self, instance: ManagedInstanceRefV1,
        update: Callable[[ManagedServiceStateV1], ManagedServiceStateV1],
        *, deadline: float | None = None, normal_growth: bool = False, wait_for_lock: bool = False,
    ) -> ManagedServiceStateV1:
        self._require_open()
        self._require_instance(instance)
        with self._fence.lock("lifecycle.lock", deadline=deadline, wait_for_lock=wait_for_lock), self._database.transaction(
            write=True, deadline=deadline, wait_for_lock=wait_for_lock,
        ) as connection:
            current = self._read(connection)
            if current is None or current.handoff.instance != instance:
                raise ManagedStorageError("conflict")
            try:
                proposed = update(current)
            except ManagedContractError:
                raise ManagedStorageError("conflict") from None
            if proposed == current:
                self._fence._check()
                return current
            if normal_growth:
                self._database.admit_growth(connection)
            else:
                self._database.admit_control(connection)
            proposed = replace(proposed, revision=_next_revision(current))
            self._save(connection, proposed, insert=False)
            self._fence._check()
            return proposed

    def _require_open(self) -> None:
        if not self._opened:
            raise ManagedStorageError("closed")

    def _require_instance(self, instance: ManagedInstanceRefV1) -> None:
        if (type(instance) is not ManagedInstanceRefV1
                or instance.namespace_key != self._namespace.namespace_key
                or instance.service_id != self._service.service_id):
            raise ManagedContractError()

    def _read(self, connection: sqlite3.Connection) -> ManagedServiceStateV1 | None:
        state = self._read_state(connection)
        self._read_transition(connection, state)
        return state

    def _read_state(self, connection: sqlite3.Connection) -> ManagedServiceStateV1 | None:
        service = self._service
        key = connection.execute("SELECT product, workspace, profile FROM services WHERE service_id=?",
                                 (service.service_id,)).fetchone()
        if key != (service.product_id, service.workspace, service.profile):
            raise ManagedStorageError("conflict")
        if self._database.service_admission_required:
            control = self._read_control(connection)
            self._fence._check()
            lock_identity = self._fence._locks["lifecycle.lock"][1]
            self._fence._check_named("lifecycle.lock", lock_identity)
            if (control.service_id != service.service_id or control.root_identity != self._fence._identity
                    or control.lock_identity != lock_identity):
                raise ManagedStorageError("conflict")
        row = connection.execute("SELECT revision, instance_id, attempt_id, phase, stop_requested, "
                                 "process_exited, application_cleanup_completed, process_scope_settled, native_identity, trace_application "
                                 "FROM instances WHERE service_id=?", (service.service_id,)).fetchone()
        if row is None:
            return None
        return _decode_state(self._namespace, service, row)

    def _read_transition(
        self, connection: sqlite3.Connection, state: ManagedServiceStateV1 | None,
    ) -> ManagedServiceTransitionV1 | None:
        row = connection.execute(
            "SELECT instance_id, attempt_id, started_revision, previous FROM service_transitions WHERE service_id=?",
            (self._service.service_id,),
        ).fetchone()
        if state is None and row is None:
            return None
        if state is None or row is None:
            raise ManagedStorageError("invalid_record")
        try:
            previous = None
            if row[3] is not None:
                if type(row[3]) is not str or len(row[3]) > 4096:
                    raise ManagedContractError()
                raw = json.loads(row[3])
                if (type(raw) is not list or len(raw) != 12
                        or raw[:2] != [self._namespace.namespace_key, self._service.service_id]):
                    raise ManagedContractError()
                previous = _decode_state(self._namespace, self._service, tuple(raw[2:]))
                if _encode_previous(previous) != row[3]:
                    raise ManagedContractError()
            transition = ManagedServiceTransitionV1(
                ManagedInstanceRefV1(self._namespace.namespace_key, self._service.service_id, row[0]),
                row[1], row[2], previous,
            )
            if (transition.instance != state.handoff.instance or transition.attempt_id != state.handoff.attempt_id
                    or transition.started_revision > state.revision):
                raise ManagedContractError()
            return transition
        except (ManagedContractError, ValueError, TypeError, RecursionError):
            raise ManagedStorageError("invalid_record") from None

    def _read_control(self, connection: sqlite3.Connection) -> ManagedServiceAdmissionRecordV1:
        row = connection.execute("SELECT record FROM service_controls WHERE service_id=?",
                                 (self._service.service_id,)).fetchone()
        if row is None:
            raise ManagedStorageError("unavailable")
        try:
            control = ManagedServiceAdmissionRecordV1.from_json(row[0])
        except ManagedContractError:
            raise ManagedStorageError("invalid_record") from None
        if control.service_id != self._service.service_id:
            raise ManagedStorageError("conflict")
        if control.phase is not ManagedInitializationPhaseV1.INITIALIZED:
            raise ManagedStorageError("unavailable")
        return control

    def _save(self, connection: sqlite3.Connection, state: ManagedServiceStateV1, *, insert: bool) -> None:
        values = (*_state_row(state), self._service.service_id)
        if insert:
            connection.execute("INSERT INTO instances (revision, instance_id, attempt_id, phase, "
                               "stop_requested, process_exited, application_cleanup_completed, "
                               "process_scope_settled, native_identity, trace_application, service_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", values)
        else:
            connection.execute("UPDATE instances SET revision=?, instance_id=?, attempt_id=?, phase=?, "
                               "stop_requested=?, process_exited=?, application_cleanup_completed=?, "
                               "process_scope_settled=?, native_identity=?, trace_application=? WHERE service_id=?", values)


def _state_row(state: ManagedServiceStateV1) -> tuple:
    handoff, evidence = state.handoff, state.evidence
    return (state.revision, handoff.instance.instance_id, handoff.attempt_id, handoff.phase.value,
            int(handoff.stop_requested), int(evidence.process_exited), int(evidence.application_cleanup_completed),
            int(evidence.process_scope_settled), _encode_native(state.native_identity), _encode_trace(state.trace_application))


def _encode_previous(state: ManagedServiceStateV1 | None) -> str | None:
    if state is None:
        return None
    instance = state.handoff.instance
    return json.dumps((instance.namespace_key, instance.service_id, *_state_row(state)), separators=(",", ":"))


def _decode_state(
    namespace: ManagedNamespaceV1, service: ManagedServiceKeyV1, row: tuple,
) -> ManagedServiceStateV1:
    """Same strict durable decoder for fenced owners and read-only discovery.

    Decoding conveys no lifecycle authority and performs no native observation.
    """
    try:
        if len(row) != 10 or any(type(value) is not int or value not in (0, 1) for value in row[4:8]):
            raise ManagedContractError()
        instance = ManagedInstanceRefV1(namespace.namespace_key, service.service_id, row[1])
        handoff = ManagedHandoffV1(instance, row[2], ManagedHandoffPhaseV1(row[3]), bool(row[4]))
        native = _decode_native(row[8])
        if native is not None and native.user_id != namespace.user_id:
            raise ManagedContractError()
        return ManagedServiceStateV1(row[0], handoff, ManagedStopEvidenceV1(
            instance, bool(row[5]), bool(row[6]), bool(row[7]),
        ), native, _decode_trace(row[9]))
    except (ManagedContractError, HostingError, ValueError, TypeError):
        raise ManagedStorageError("invalid_record") from None


def _encode_trace(receipt: ManagedTraceApplicationV1 | None) -> str | None:
    return None if receipt is None else json.dumps({"v": 1, **asdict(receipt)}, sort_keys=True, separators=(",", ":"))


def _decode_trace(value: object) -> ManagedTraceApplicationV1 | None:
    if value is None:
        return None
    if type(value) is not str or len(value) > 512:
        raise ManagedContractError()
    try:
        row = json.loads(value)
        if (type(row) is not dict or row.keys() != {"v", "instance_id", "attempt_id", "deadline_ms", "configuration"}
                or type(row["v"]) is not int or row["v"] != 1):
            raise ManagedContractError()
        receipt = ManagedTraceApplicationV1(row["instance_id"], row["attempt_id"], row["deadline_ms"], row["configuration"])
        if _encode_trace(receipt) != value:
            raise ManagedContractError()
        return receipt
    except (ValueError, TypeError, RecursionError):
        raise ManagedContractError() from None


def _encode_native(identity: LinuxServiceIdentityV1 | None) -> str | None:
    return None if identity is None else json.dumps(asdict(identity), sort_keys=True, separators=(",", ":"))


def _decode_native(value: object) -> LinuxServiceIdentityV1 | None:
    if value is None:
        return None
    if type(value) is not str or len(value) > 1024:
        raise ManagedContractError()
    identity = LinuxServiceIdentityV1(**json.loads(value))
    if _encode_native(identity) != value:
        raise ManagedContractError()
    return identity


def _next_revision(current: ManagedServiceStateV1 | None) -> int:
    revision = 1 if current is None else current.revision + 1
    if revision > _MAX_REVISION:
        raise ManagedStorageError("capacity")
    return revision
