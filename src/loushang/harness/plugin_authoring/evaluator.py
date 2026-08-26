"""Internal evaluator for one approved in-process Plugin Definition."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from typing import Protocol, cast

from loushang.harness.approval.plugin_execution import (
    PluginApprovalDecisionRecordV1,
    PluginExecutionDecisionJournal,
    PluginExecutionJournalError,
    PluginExecutionUseReservationV1,
    PluginExecutionUseState,
)
from loushang.harness.plugin_authoring.builder import PluginDeclarationBuilder
from loushang.harness.resources.plugins.declarations import PluginDeclaration
from loushang.harness.resources.plugins.dependencies import (
    PluginDependencyClosureLock,
)
from loushang.harness.resources.plugins.distribution_evidence import (
    InstalledPythonDistributionEvidenceError,
    InstalledPythonDistributionEvidenceResolver,
)
from loushang.harness.resources.plugins.import_realm import (
    PluginImportRealm,
    PluginImportRealmError,
)
from loushang.harness.resources.plugins.locators import parse_plugin_entrypoint
from loushang.harness.resources.plugins.python_symbols import (
    load_verified_plugin_python_module,
)
from loushang.harness.resources.plugins.selection import (
    PluginDeclarationBatch,
    PluginDeclarationExecutionPreflightGate,
    PluginDeclarationSourceGroup,
    PluginExecutionStartPermit,
)

_MAX_JOURNAL_CAS_ATTEMPTS = 16
_HOST_API_PREFIXES = (
    "loushang.harness.capabilities",
    "loushang.harness.plugin_authoring",
)


class PluginDefinition(Protocol):
    def __call__(self, builder: PluginDeclarationBuilder) -> object: ...


class PluginDefinitionEvaluationError(RuntimeError):
    """Redacted, stable failure at the executable declaration boundary."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class PluginDefinitionEvaluator:
    """Consume Approval authority and project verified Definition code to IR."""

    def __init__(
        self,
        *,
        decision_journal: PluginExecutionDecisionJournal,
        import_realm: PluginImportRealm,
        clock: Callable[[], int],
        distribution_evidence_resolver: (
            InstalledPythonDistributionEvidenceResolver | None
        ) = None,
    ) -> None:
        if not isinstance(decision_journal, PluginExecutionDecisionJournal):
            raise TypeError("Plugin Definition evaluator requires a decision journal")
        if not isinstance(import_realm, PluginImportRealm):
            raise TypeError("Plugin Definition evaluator requires an import realm")
        if not callable(clock):
            raise TypeError("Plugin Definition evaluator requires a durable clock")
        self._decision_journal = decision_journal
        self._import_realm = import_realm
        self._clock = clock
        self._distribution_evidence_resolver = (
            distribution_evidence_resolver
            if distribution_evidence_resolver is not None
            else InstalledPythonDistributionEvidenceResolver()
        )

    def evaluate(
        self,
        group: PluginDeclarationSourceGroup,
        permit: PluginExecutionStartPermit,
    ) -> PluginDeclarationBatch:
        gate = self._validate_start(group, permit)
        dependency_lock = group.package.dependency_lock
        handle = group.package.revision_handle
        handle.verify()
        self._validate_dependency_lock(group, dependency_lock)
        try:
            self._import_realm.preflight(
                host_boot_id=permit.host_boot_id,
                package_namespace=group.package.manifest.name,
                dependency_lock=dependency_lock,
            )
        except PluginImportRealmError as exc:
            raise _realm_evaluation_error(exc) from exc
        reservation = self._consume_decision(group, gate, permit)
        try:
            realm_lease = self._import_realm.reserve(
                host_boot_id=permit.host_boot_id,
                execution_use_id=reservation.execution_use_id,
                package_namespace=group.package.manifest.name,
                dependency_lock=dependency_lock,
            )
        except BaseException as exc:
            self._persist_cancelled_before_start(reservation, permit=permit)
            if isinstance(exc, PluginImportRealmError):
                raise _realm_evaluation_error(exc) from exc
            raise

        try:
            starting = self._transition_use(
                reservation.execution_use_id,
                expected_state="CONSUMED_NOT_STARTED",
                target_state="STARTING",
                permit=permit,
            )
        except BaseException:
            self._import_realm.cancel(realm_lease)
            self._persist_cancelled_before_start(reservation, permit=permit)
            raise

        try:
            declarations = self._import_realm.execute(
                realm_lease,
                lambda: self._evaluate_verified_definition(
                    group,
                    dependency_lock=dependency_lock,
                ),
            )
        except BaseException as exc:
            self._persist_failed_after_start(starting, permit=permit)
            raise PluginDefinitionEvaluationError(
                "Plugin Definition evaluation failed after execution start.",
                code="plugin_definition_evaluation_failed",
            ) from exc

        try:
            evaluated = self._transition_use(
                starting.execution_use_id,
                expected_state="STARTING",
                target_state="EVALUATED",
                permit=permit,
            )
        except BaseException:
            self._import_realm.pollute(realm_lease)
            self._persist_failed_after_start(starting, permit=permit)
            raise

        try:
            self._import_realm.commit(realm_lease)
        except BaseException:
            with suppress(PluginImportRealmError):
                self._import_realm.pollute(realm_lease)
            raise
        receipt = self._decision_journal.execution_consumption_receipt(
            evaluated.execution_use_id,
            current_host_boot_id=permit.host_boot_id,
            current_import_realm_id=self._import_realm.import_realm_id,
        )
        return PluginDeclarationBatch._from_in_process_evaluated(
            group,
            declarations,
            receipt,
        )

    @staticmethod
    def _validate_start(
        group: PluginDeclarationSourceGroup,
        permit: PluginExecutionStartPermit,
    ) -> PluginDeclarationExecutionPreflightGate:
        if not isinstance(group, PluginDeclarationSourceGroup):
            raise TypeError("Plugin Definition evaluator requires a SourceGroup")
        if not isinstance(permit, PluginExecutionStartPermit):
            raise TypeError("Plugin Definition evaluator requires a start permit")
        if not isinstance(group.gate, PluginDeclarationExecutionPreflightGate):
            raise PluginDefinitionEvaluationError(
                "Document declaration groups cannot be evaluated as code.",
                code="plugin_definition_evaluation_not_applicable",
            )
        if (
            permit.preflight_use_id != group.preflight_use_id
            or permit.source_group_id != group.source_group_id
        ):
            raise PluginDefinitionEvaluationError(
                "Plugin execution start permit does not match its SourceGroup.",
                code="plugin_execution_start_permit_mismatch",
            )
        return group.gate

    def _validate_dependency_lock(
        self,
        group: PluginDeclarationSourceGroup,
        dependency_lock: PluginDependencyClosureLock,
    ) -> None:
        gate = cast(PluginDeclarationExecutionPreflightGate, group.gate)
        if (
            dependency_lock.package_content_digest != group.package.content_digest
            or dependency_lock.digest != gate.subject.dependency_lock_digest
        ):
            raise PluginDefinitionEvaluationError(
                "Plugin dependency closure does not match the approved revision.",
                code="plugin_import_dependency_lock_mismatch",
            )
        try:
            for distribution in dependency_lock.python_distributions:
                self._distribution_evidence_resolver.resolve_all(distribution)
        except InstalledPythonDistributionEvidenceError as exc:
            raise PluginDefinitionEvaluationError(
                "A locked Plugin dependency is unavailable.",
                code="plugin_import_dependency_unavailable",
            ) from exc

    def _consume_decision(
        self,
        group: PluginDeclarationSourceGroup,
        gate: PluginDeclarationExecutionPreflightGate,
        permit: PluginExecutionStartPermit,
    ) -> PluginExecutionUseReservationV1:
        for _attempt in range(_MAX_JOURNAL_CAS_ATTEMPTS):
            snapshot = self._decision_journal.snapshot()
            decision = _decision_for_gate(snapshot.decisions, gate)
            try:
                return self._decision_journal.consume_execution_decision(
                    gate.subject,
                    decision_id=decision.decision_id,
                    preflight_use_id=group.preflight_use_id,
                    source_group_id=group.source_group_id,
                    host_boot_id=permit.host_boot_id,
                    import_realm_id=self._import_realm.import_realm_id,
                    expected_revocation_epoch=decision.revocation_epoch,
                    current_policy_revision=gate.subject.policy_revision,
                    current_source_trust_policy_revision=(
                        gate.subject.source_trust_policy_revision
                    ),
                    expected_journal_revision=snapshot.journal_revision,
                )
            except PluginExecutionJournalError as exc:
                if exc.code != "plugin_execution_journal_revision_conflict":
                    raise
        raise PluginDefinitionEvaluationError(
            "Plugin execution journal remained contended.",
            code="plugin_execution_journal_contention",
        )

    def _transition_use(
        self,
        execution_use_id: str,
        *,
        expected_state: PluginExecutionUseState,
        target_state: PluginExecutionUseState,
        permit: PluginExecutionStartPermit,
    ) -> PluginExecutionUseReservationV1:
        for _attempt in range(_MAX_JOURNAL_CAS_ATTEMPTS):
            snapshot = self._decision_journal.snapshot()
            current = next(
                (
                    item
                    for item in snapshot.execution_uses
                    if item.execution_use_id == execution_use_id
                ),
                None,
            )
            if current is None or current.state != expected_state:
                raise PluginDefinitionEvaluationError(
                    "Plugin execution use changed before its durable transition.",
                    code="plugin_execution_use_state_conflict",
                )
            try:
                return self._decision_journal.transition_execution_use(
                    execution_use_id,
                    expected_state=expected_state,
                    target_state=target_state,
                    host_boot_id=permit.host_boot_id,
                    import_realm_id=self._import_realm.import_realm_id,
                    transitioned_at_unix_ms=self._clock(),
                    expected_journal_revision=snapshot.journal_revision,
                )
            except PluginExecutionJournalError as exc:
                if exc.code != "plugin_execution_journal_revision_conflict":
                    raise
        raise PluginDefinitionEvaluationError(
            "Plugin execution journal remained contended.",
            code="plugin_execution_journal_contention",
        )

    def _persist_failed_after_start(
        self,
        starting: PluginExecutionUseReservationV1,
        *,
        permit: PluginExecutionStartPermit,
    ) -> None:
        # The realm is already quarantined. Preserve the original evaluation
        # failure while durable recovery treats STARTING as possibly executed.
        with suppress(Exception):
            self._transition_use(
                starting.execution_use_id,
                expected_state="STARTING",
                target_state="FAILED_AFTER_START",
                permit=permit,
            )

    def _persist_cancelled_before_start(
        self,
        reservation: PluginExecutionUseReservationV1,
        *,
        permit: PluginExecutionStartPermit,
    ) -> None:
        with suppress(Exception):
            self._transition_use(
                reservation.execution_use_id,
                expected_state="CONSUMED_NOT_STARTED",
                target_state="CANCELLED_BEFORE_START",
                permit=permit,
            )

    def _evaluate_verified_definition(
        self,
        group: PluginDeclarationSourceGroup,
        *,
        dependency_lock: PluginDependencyClosureLock,
    ) -> tuple[PluginDeclaration, ...]:
        entrypoint = group.declaration_source.entrypoint
        if entrypoint is None:
            raise ValueError("Executable declaration source has no entrypoint")
        relative_path, symbol = parse_plugin_entrypoint(entrypoint)
        module = load_verified_plugin_python_module(
            revision_handle=group.package.revision_handle,
            dependency_lock=dependency_lock,
            relative_path=relative_path.as_posix(),
            module_name=(
                "_loushang_plugin_definition_"
                + group.source_group_fingerprint[:16]
            ),
            host_api_prefixes=_HOST_API_PREFIXES,
            distribution_evidence_resolver=(
                self._distribution_evidence_resolver
            ),
        )
        definition = module.resolve(symbol)
        if not callable(definition):
            raise TypeError("Plugin Definition entrypoint must be callable")
        builder = PluginDeclarationBuilder(source_group=group)
        result = cast(PluginDefinition, definition)(builder)
        return builder._validate_definition_result(result)


def _decision_for_gate(
    decisions: tuple[PluginApprovalDecisionRecordV1, ...],
    gate: PluginDeclarationExecutionPreflightGate,
) -> PluginApprovalDecisionRecordV1:
    decision = next(
        (item for item in decisions if item.decision_id == gate.decision.decision_id),
        None,
    )
    if (
        decision is None
        or decision.subject_digest != gate.subject.digest
        or decision.policy_revision != gate.subject.policy_revision
        or decision.source_trust_policy_revision
        != gate.subject.source_trust_policy_revision
        or decision.instance_revision_ref != gate.subject.instance_revision_ref
    ):
        raise PluginDefinitionEvaluationError(
            "Plugin execution decision is no longer current.",
            code="plugin_execution_decision_not_current",
        )
    return decision


def _realm_evaluation_error(
    error: PluginImportRealmError,
) -> PluginDefinitionEvaluationError:
    return PluginDefinitionEvaluationError(str(error), code=error.code)


__all__ = [
    "PluginDefinitionEvaluationError",
    "PluginDefinitionEvaluator",
]
