"""Shared durable activation-use mechanics for distinct in-process Hosts."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from loushang.harness.approval.plugin_activation import (
    ActivationUseReservationV1,
    PluginActivationApprovalSubject,
    PluginActivationDecisionJournal,
    PluginActivationJournalError,
    PluginActivationUseState,
)

_MAX_JOURNAL_CAS_ATTEMPTS = 16

ActivationHostErrorFactory = Callable[[str, str], RuntimeError]


@dataclass(frozen=True, slots=True)
class DurableActivationHostLifecycle:
    """One shared adapter over the durable decision/use journal state machine."""

    journal: PluginActivationDecisionJournal
    host_boot_id: str
    import_realm_id: str
    clock: Callable[[], int]
    error_factory: ActivationHostErrorFactory

    def now(self) -> int:
        value = self.clock()
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError("Activation Host clock must be non-negative integer")
        return value

    def recover_incomplete_uses(self) -> None:
        for _ in range(_MAX_JOURNAL_CAS_ATTEMPTS):
            snapshot = self.journal.snapshot()
            try:
                self.journal.recover_activation_uses(
                    current_host_boot_id=self.host_boot_id,
                    recovered_at_unix_ms=self.now(),
                    expected_journal_revision=snapshot.journal_revision,
                )
                return
            except PluginActivationJournalError as exc:
                if exc.code != "plugin_activation_journal_revision_conflict":
                    raise self.error_factory(
                        "Activation Host recovery failed.",
                        exc.code,
                    ) from exc
        raise self.error_factory(
            "Activation journal remained contended during recovery.",
            "plugin_activation_journal_contention",
        )

    def consume(
        self,
        subject: PluginActivationApprovalSubject,
        *,
        decision_id: str,
    ) -> ActivationUseReservationV1:
        for _ in range(_MAX_JOURNAL_CAS_ATTEMPTS):
            snapshot = self.journal.snapshot()
            try:
                return self.journal.consume_activation_decision(
                    subject,
                    decision_id=decision_id,
                    host_boot_id=self.host_boot_id,
                    import_realm_id=self.import_realm_id,
                    expected_journal_revision=snapshot.journal_revision,
                )
            except PluginActivationJournalError as exc:
                if exc.code != "plugin_activation_journal_revision_conflict":
                    raise self.error_factory(
                        "Activation authority was rejected.",
                        exc.code,
                    ) from exc
        raise self.error_factory(
            "Activation journal remained contended during consumption.",
            "plugin_activation_journal_contention",
        )

    def validate_current(
        self,
        reservation: ActivationUseReservationV1,
        *,
        expected_state: PluginActivationUseState,
    ) -> None:
        try:
            self.journal.validate_activation_use_current(
                reservation,
                expected_state=expected_state,
            )
        except PluginActivationJournalError as exc:
            raise self.error_factory(
                "Activation authority expired before execution.",
                exc.code,
            ) from exc

    def transition(
        self,
        reservation: ActivationUseReservationV1,
        *,
        expected_state: PluginActivationUseState,
        target_state: PluginActivationUseState,
    ) -> ActivationUseReservationV1:
        for _ in range(_MAX_JOURNAL_CAS_ATTEMPTS):
            revision = self.journal.snapshot().journal_revision
            try:
                return self.journal.transition_activation_use(
                    reservation.activation_use_id,
                    expected_state=expected_state,
                    target_state=target_state,
                    host_boot_id=self.host_boot_id,
                    import_realm_id=self.import_realm_id,
                    transitioned_at_unix_ms=self.now(),
                    expected_journal_revision=revision,
                )
            except PluginActivationJournalError as exc:
                if exc.code != "plugin_activation_journal_revision_conflict":
                    raise self.error_factory(
                        "Activation state transition was rejected.",
                        exc.code,
                    ) from exc
        raise self.error_factory(
            "Activation journal remained contended during transition.",
            "plugin_activation_journal_contention",
        )

    def try_transition(
        self,
        reservation: ActivationUseReservationV1,
        *,
        expected_state: PluginActivationUseState,
        target_state: PluginActivationUseState,
    ) -> ActivationUseReservationV1:
        try:
            return self.transition(
                reservation,
                expected_state=expected_state,
                target_state=target_state,
            )
        except Exception:
            return reservation


__all__: list[str] = []
