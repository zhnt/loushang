"""Native Plugin Resume parent coordination over the original two journals."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypedDict

from loushang.harness.approval.plugin_activation import (
    PluginActivationDecisionJournal,
    PluginActivationJournalError,
)
from loushang.harness.approval.plugin_execution import (
    PluginExecutionDecisionJournal,
    PluginExecutionJournalError,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef
from loushang.harness.resume_effects import ResumeEffectParentContextV1


class _JournalOptions(TypedDict, total=False):
    clock: Callable[[], int]
    required_writer_capabilities: frozenset[str]


def plugin_resume_journals(
    session_id: str,
    definition_path: Path,
    activation_path: Path,
    *,
    clock: Callable[[], int] | None = None,
    require_resume_context: bool = False,
) -> tuple[
    PluginExecutionDecisionJournal, PluginActivationDecisionJournal
]:
    scope_id = f"session:{session_id}"
    definition_options: _JournalOptions = {}
    activation_options: _JournalOptions = {}
    if clock is not None:
        definition_options["clock"] = activation_options["clock"] = clock
    if require_resume_context:
        definition_options["required_writer_capabilities"] = frozenset(
            {"harness.plugin-execution.resume-context/v1"}
        )
        activation_options["required_writer_capabilities"] = frozenset(
            {"harness.plugin-activation.resume-context/v1"}
        )
    return (
        PluginExecutionDecisionJournal(
            definition_path,
            scope_kind="workspace",
            scope_id=scope_id,
            **definition_options,
        ),
        PluginActivationDecisionJournal(
            activation_path,
            scope_id=scope_id,
            **activation_options,
        ),
    )


def require_receipt_without_plugin_effects(
    receipt: Mapping[str, object],
    *,
    expected_set_id: str,
    capability_plugin_ids: frozenset[str],
    unsettled: Callable[[], Exception],
) -> None:
    revisions = receipt.get("selectedRevisions")
    if receipt.get("setId") != expected_set_id or not isinstance(revisions, list):
        raise unsettled()
    for raw in revisions:
        if not isinstance(raw, Mapping) or raw.get("pluginId") in capability_plugin_ids:
            raise unsettled()


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



    def require_settled_revisions(
        self,
        receipt: Mapping[str, object],
        *,
        session_id: str,
        state_root: Path,
        clock: Callable[[], int],
        capability_plugin_ids: frozenset[str],
        unsettled: Callable[[], Exception],
    ) -> None:
        """Match receipt revisions against both sealed native journal memberships."""
        try:
            definition, activation = self._journals(
                session_id=session_id,
                state_root=state_root,
                clock=clock,
            )
            definition_snapshot = definition.resume_parent_snapshot(self.definition)
            activation_snapshot = activation.resume_parent_snapshot(self.activation)
        except (
            PluginExecutionJournalError,
            PluginActivationJournalError,
        ) as error:
            raise unsettled() from error
        if (
            not definition_snapshot.sealed
            or definition_snapshot.membership_digest is None
            or not activation_snapshot.sealed
            or activation_snapshot.membership_digest is None
            or activation_snapshot.unfenced_recovered_use_ids
            or not definition_snapshot.execution_uses
            or not activation_snapshot.activation_uses
            or any(use.state != "EVALUATED" for use in definition_snapshot.execution_uses)
            or any(use.state != "COMMITTED" for use in activation_snapshot.activation_uses)
        ):
            raise unsettled()

        raw_revisions = receipt.get("selectedRevisions")
        if not isinstance(raw_revisions, list):
            raise unsettled()
        selected: dict[str, PluginInstanceRevisionRef] = {}
        try:
            for raw in raw_revisions:
                if not isinstance(raw, Mapping) or set(raw) != {
                    "pluginId",
                    "packageRevisionFingerprint",
                    "instanceRevisionRef",
                }:
                    raise ValueError("invalid current revision receipt")
                plugin_id = raw["pluginId"]
                revision_fingerprint = raw["packageRevisionFingerprint"]
                if not isinstance(plugin_id, str) or not isinstance(
                    revision_fingerprint, str
                ):
                    raise ValueError("invalid current revision identity")
                if plugin_id not in capability_plugin_ids:
                    continue
                revision = PluginInstanceRevisionRef.from_dict(raw["instanceRevisionRef"])
                if revision.plugin_id != plugin_id or plugin_id in selected:
                    raise ValueError("current revision receipt changed")
                selected[plugin_id] = revision
        except (TypeError, ValueError) as error:
            raise unsettled() from error

        def revision_order(ref: PluginInstanceRevisionRef) -> tuple[str, str, int]:
            return ref.plugin_id, ref.instance_id, ref.revision

        definition_refs = sorted(
            (use.instance_revision_ref for use in definition_snapshot.execution_uses),
            key=revision_order,
        )
        activation_refs = sorted(
            (use.instance_revision_ref for use in activation_snapshot.activation_uses),
            key=revision_order,
        )
        selected_refs = sorted(selected.values(), key=revision_order)
        if (
            not selected_refs
            or definition_refs != selected_refs
            or activation_refs != selected_refs
        ):
            raise unsettled()
