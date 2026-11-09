"""Host-owned entry for inert Plugin declaration composition."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from loushang.harness.approval.plugin_execution import (
    PluginApprovalDecisionRecordV1,
    PluginExecutionDecisionJournal,
    PluginExecutionJournalScopeKind,
)
from loushang.harness.plugin_authoring.coordinator import (
    PluginDeclarationCoordinator,
)
from loushang.harness.plugin_authoring.evaluator import PluginDefinitionEvaluator
from loushang.harness.resources.plugins.distribution_evidence import (
    InstalledPythonDistributionEvidenceResolver,
)
from loushang.harness.resources.plugins.import_realm import PluginImportRealm
from loushang.harness.resources.plugins.selection import (
    PluginExecutionApprovalSubject,
    PluginExecutionDecisionLookupPort,
    PluginPreflightAcceptedOutcome,
    PluginPreflightDeniedOutcome,
    PluginPreflightPendingApprovalOutcome,
    PluginPreflightRejectedOutcome,
    PluginSelection,
    PluginSelectionPlanV2,
    PluginSelectionResolver,
)
from loushang.harness.resources.plugins.types import (
    PluginSourceBinding,
    PublishedPluginPackage,
)
from loushang.harness.resume_effects import ResumeEffectParentContextV1

PluginDeclarationHostResult = (
    PluginSelection
    | PluginPreflightPendingApprovalOutcome
    | PluginPreflightDeniedOutcome
    | PluginPreflightRejectedOutcome
)


class PluginDefinitionApprovalIssuer(Protocol):
    """An explicit Product issuer; declaration composition grants no approval."""

    def approve_definition(
        self,
        *,
        journal: PluginExecutionDecisionJournal,
        subject: PluginExecutionApprovalSubject,
    ) -> PluginApprovalDecisionRecordV1: ...


class PluginDeclarationHost:
    """Own one Resolver/Coordinator pair for the current Host boot.

    resolve() returns proposed approval subjects without recording decisions.
    An accepted preflight goes directly to the sole declaration Coordinator;
    its active token never becomes a Product-facing continuation handle.
    resolve_for_product() coordinates an explicit Product issuer and resolve();
    the issuer retains decision authority and the journal retains storage.
    """

    __slots__ = ("_coordinator", "_resolver")

    def __init__(
        self,
        *,
        execution_evaluator: PluginDefinitionEvaluator | None = None,
    ) -> None:
        self._resolver = PluginSelectionResolver()
        self._coordinator = PluginDeclarationCoordinator(
            self._resolver,
            execution_evaluator=execution_evaluator,
        )

    def resolve(
        self,
        packages: tuple[PublishedPluginPackage, ...],
        *,
        bindings: tuple[PluginSourceBinding, ...],
        plan: PluginSelectionPlanV2,
        decision_lookup: PluginExecutionDecisionLookupPort,
    ) -> PluginDeclarationHostResult:
        """Revalidate one authoritative Plan and compose accepted declarations."""

        outcome = self._resolver.preflight(
            packages,
            bindings=bindings,
            plan=plan,
            decision_lookup=decision_lookup,
        )
        if isinstance(outcome, PluginPreflightAcceptedOutcome):
            return self._coordinator.finalize(outcome.accepted)
        return outcome

    @classmethod
    def resolve_for_product(
        cls,
        packages: tuple[PublishedPluginPackage, ...],
        *,
        bindings: tuple[PluginSourceBinding, ...],
        plan: PluginSelectionPlanV2,
        journal_path: Path,
        scope_kind: PluginExecutionJournalScopeKind,
        scope_id: str,
        clock: Callable[[], int],
        required_writer_capabilities: frozenset[str],
        approval_owner: Callable[[], PluginDefinitionApprovalIssuer],
        distribution_evidence_resolver: Callable[
            [], InstalledPythonDistributionEvidenceResolver
        ],
        resume_parent_context: Callable[[], ResumeEffectParentContextV1 | None],
        approval_label: str,
        error_code_prefix: str,
        error_factory: Callable[[str, str], RuntimeError],
    ) -> PluginSelection:
        """Drive one explicit issuer round without granting or consuming authority.

        The existing resolve() path retains its original no-issuance contract.
        This operation owns the original journal/host/resolve handoff only.
        """
        journal = PluginExecutionDecisionJournal(
            journal_path,
            scope_kind=scope_kind,
            scope_id=scope_id,
            clock=clock,
            required_writer_capabilities=required_writer_capabilities,
        )
        host = cls(
            execution_evaluator=PluginDefinitionEvaluator(
                decision_journal=journal,
                import_realm=PluginImportRealm(),
                clock=clock,
                distribution_evidence_resolver=distribution_evidence_resolver(),
                resume_parent_context=resume_parent_context(),
            )
        )
        outcome = host.resolve(
            packages, bindings=bindings, plan=plan, decision_lookup=journal
        )
        if isinstance(outcome, PluginPreflightPendingApprovalOutcome):
            for subject in outcome.subjects:
                decision = approval_owner().approve_definition(
                    journal=journal, subject=subject
                )
                if not isinstance(decision, PluginApprovalDecisionRecordV1):
                    raise TypeError(
                        f"{approval_label} Definition Approval owner returned invalid evidence"
                    )
                if decision.subject_digest != subject.digest:
                    raise error_factory(
                        f"{approval_label} Definition approval does not match its Subject.",
                        f"{error_code_prefix}_definition_approval_mismatch",
                    )
            outcome = host.resolve(
                packages, bindings=bindings, plan=plan, decision_lookup=journal
            )
        if not isinstance(outcome, PluginSelection):
            disposition = outcome.disposition
            error = error_factory(
                f"{approval_label} Plugin Definition was not approved.",
                f"{error_code_prefix}_definition_denied"
                if isinstance(outcome, PluginPreflightDeniedOutcome)
                else f"{error_code_prefix}_definition_{disposition}",
            )
            for diagnostic in outcome.diagnostics:
                error.add_note(
                    f"Plugin preflight {diagnostic.plugin_id or '<plan>'}: {diagnostic.code}"
                )
            raise error
        return outcome


__all__ = ["PluginDeclarationHost", "PluginDeclarationHostResult"]
