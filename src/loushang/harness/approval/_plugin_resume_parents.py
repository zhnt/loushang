"""Native Plugin Resume parent coordination over the original two journals."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from loushang.harness.approval.plugin_activation import (
    PluginActivationDecisionJournal,
    PluginActivationJournalError,
)
from loushang.harness.approval.plugin_execution import (
    PluginExecutionDecisionJournal,
    PluginExecutionJournalError,
)
from loushang.harness.resume_effects import ResumeEffectParentContextV1


class _PluginResumeParentMethods:
    """No state: operate on the caller's existing immutable parent pair.

    The Product binds original native journal paths/capabilities and diagnostic
    values. Only the original journals persist membership or grant authority.
    """

    __slots__ = ()

    definition: ResumeEffectParentContextV1
    activation: ResumeEffectParentContextV1

    def _journals(
        self, *, session_id: str, state_root: Path, clock: Callable[[], int]
    ) -> tuple[PluginExecutionDecisionJournal, PluginActivationDecisionJournal]:
        raise NotImplementedError("the Product's original journal binding is required")

    def _sealed_parent_error(self, *, definition: bool) -> Exception:
        raise NotImplementedError("the Product's original diagnostic value is required")

    def require_open(
        self, *, session_id: str, state_root: Path, clock: Callable[[], int]
    ) -> None:
        """Read original enrollment before Definition evaluation; never enroll."""

        definition, activation = self._journals(
            session_id=session_id, state_root=state_root, clock=clock
        )
        # Both obligations must already be enrolled in their original journals.
        # A missing Component enrollment cannot be discovered after Definition
        # code has started. Original owners validate scope and contract digests.
        if definition.resume_parent_snapshot(self.definition).sealed:
            raise self._sealed_parent_error(definition=True)
        if activation.resume_parent_snapshot(self.activation).sealed:
            raise self._sealed_parent_error(definition=False)

    def enroll(
        self, *, session_id: str, state_root: Path, clock: Callable[[], int]
    ) -> None:
        """Idempotently enroll both original owners after intent commit."""

        definition, activation = self._journals(
            session_id=session_id, state_root=state_root, clock=clock
        )
        try:
            existing_definition = definition.resume_parent_snapshot(self.definition)
        except PluginExecutionJournalError as error:
            if error.code != "plugin_execution_resume_parent_unknown":
                raise
            definition.enroll_resume_parent(
                self.definition,
                expected_journal_revision=definition.snapshot().journal_revision,
            )
        else:
            if existing_definition.sealed:
                raise self._sealed_parent_error(definition=True)
        try:
            existing_activation = activation.resume_parent_snapshot(self.activation)
        except PluginActivationJournalError as error:
            if error.code != "plugin_activation_resume_parent_unknown":
                raise
            activation.enroll_resume_parent(
                self.activation,
                expected_journal_revision=activation.snapshot().journal_revision,
            )
        else:
            if existing_activation.sealed:
                raise self._sealed_parent_error(definition=False)

    def seal(
        self, *, session_id: str, state_root: Path, clock: Callable[[], int]
    ) -> tuple[object, object]:
        """Fence exact Definition and Component membership after graph preparation."""

        definition, activation = self._journals(
            session_id=session_id, state_root=state_root, clock=clock
        )
        definition_snapshot = definition.resume_parent_snapshot(self.definition)
        if not definition_snapshot.sealed:
            definition_snapshot = definition.seal_resume_parent(
                self.definition,
                expected_journal_revision=definition_snapshot.journal_revision,
            )
        activation_snapshot = activation.resume_parent_snapshot(self.activation)
        if not activation_snapshot.sealed:
            activation_snapshot = activation.seal_resume_parent(
                self.activation,
                expected_journal_revision=activation_snapshot.journal_revision,
            )
        return definition_snapshot, activation_snapshot
