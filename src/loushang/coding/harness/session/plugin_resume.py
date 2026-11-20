"""Prepare and read exact Plugin Resume evidence in its original journals."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TypedDict

from loushang.coding.composition import capability_plugins as _binding
from loushang.coding.resume.activation_attempt import CodingResumeRecoveryRequired
from loushang.coding.resume.activation_attempt_v2 import (
    CodingActivationAttemptV2,
    CodingResumeEffectOwnerV1,
)
from loushang.harness.resources.plugins.selection import PluginInstanceRevisionRef

_DEFINITION_OWNER = "harness.plugin-execution"
_ACTIVATION_OWNER = "harness.plugin-activation"
_UNSUPPORTED_OWNERS = "input.effect_owner_set_unsupported"
_UNKNOWN_SETTLEMENT = "input.effect_settlement_unknown"


class _JournalOptions(TypedDict, total=False):
    clock: Callable[[], int]
    required_writer_capabilities: frozenset[str]


def _journals_for_session(
    session_id: str,
    state_root: Path,
    *,
    definition_options: _JournalOptions,
    activation_options: _JournalOptions,
) -> tuple[
    _binding.PluginExecutionDecisionJournal, _binding.PluginActivationDecisionJournal
]:
    scope_id = f"session:{session_id}"
    return (
        _binding.PluginExecutionDecisionJournal(
            state_root / _binding._DEFINITION_DECISIONS_FILENAME,
            scope_kind="workspace",
            scope_id=scope_id,
            **definition_options,
        ),
        _binding.PluginActivationDecisionJournal(
            state_root / _binding._ACTIVATION_DECISIONS_FILENAME,
            scope_id=scope_id,
            **activation_options,
        ),
    )


def journals_for_parents(
    parents: _binding.CodingResumePluginParents,
    *,
    session_id: str,
    state_root: Path,
    clock: Callable[[], int],
) -> tuple[
    _binding.PluginExecutionDecisionJournal, _binding.PluginActivationDecisionJournal
]:
    if parents.definition.session_id != session_id:
        raise ValueError(
            f"{_binding._RESUME_PLUGIN_LABEL} parents belong to another Session"
        )
    return _journals_for_session(
        session_id,
        state_root,
        definition_options={
            "clock": clock,
            "required_writer_capabilities": frozenset(
                {"harness.plugin-execution.resume-context/v1"}
            ),
        },
        activation_options={
            "clock": clock,
            "required_writer_capabilities": frozenset(
                {"harness.plugin-activation.resume-context/v1"}
            ),
        },
    )


def prepare_effect_owners(
    *, session_id: str, state_root: Path, product_id: str
) -> tuple[CodingResumeEffectOwnerV1, ...]:
    """Freeze the two original Plugin journal lookup obligations without I/O."""

    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError(f"{_binding._RESUME_PLUGIN_LABEL} owner Session id is invalid")
    if not isinstance(state_root, Path) or not state_root.is_absolute():
        raise ValueError(f"{_binding._RESUME_PLUGIN_LABEL} owner state root is invalid")
    definition, activation = _journals_for_session(
        session_id, state_root, definition_options={}, activation_options={}
    )
    return tuple(
        sorted(
            (
                CodingResumeEffectOwnerV1(
                    _DEFINITION_OWNER,
                    definition.resume_parent_scope_digest(product_id=product_id),
                    definition.resume_parent_contract_digest,
                    ("declaration",),
                ),
                CodingResumeEffectOwnerV1(
                    _ACTIVATION_OWNER,
                    activation.resume_parent_scope_digest(product_id=product_id),
                    activation.resume_parent_contract_digest,
                    ("activation",),
                ),
            ),
            key=lambda owner: owner.identity,
        )
    )


def _require_effect_owners(
    attempt: CodingActivationAttemptV2,
    owner_ids: set[str],
    expected_owner_ids: set[str] | frozenset[str],
) -> None:
    if (
        owner_ids != expected_owner_ids
        or attempt.effect_classes
        or any(owner.effect_classes for owner in attempt.effect_owners)
    ):
        raise CodingResumeRecoveryRequired(_UNSUPPORTED_OWNERS)


def require_no_plugin_effects(
    attempt: CodingActivationAttemptV2,
    receipt: Mapping[str, object],
    *,
    expected_set_id: str,
    allowed_owner_ids: frozenset[str],
    capability_plugin_ids: frozenset[str],
) -> None:
    """Prove the expected receipt contains no Capability Plugin effects."""
    _require_effect_owners(
        attempt, {owner.owner_id for owner in attempt.effect_owners}, allowed_owner_ids
    )
    revisions = receipt.get("selectedRevisions")
    if receipt.get("setId") != expected_set_id or not isinstance(revisions, list):
        raise CodingResumeRecoveryRequired(_UNKNOWN_SETTLEMENT)
    for raw in revisions:
        if not isinstance(raw, Mapping) or raw.get("pluginId") in capability_plugin_ids:
            raise CodingResumeRecoveryRequired(_UNKNOWN_SETTLEMENT)


def require_resume_effect_settlement(
    attempt: CodingActivationAttemptV2,
    receipt: Mapping[str, object],
    *,
    state_root: Path,
    clock: Callable[[], int],
    allowed_external_owner_ids: frozenset[str],
    capability_plugin_ids: frozenset[str],
) -> None:
    """Reconcile exact selected Plugin revisions with both original journals."""

    if type(attempt) is not CodingActivationAttemptV2:
        raise TypeError(
            f"{_binding._RESUME_PLUGIN_LABEL} settlement requires an exact v2 intent"
        )
    if not isinstance(receipt, Mapping):
        raise TypeError(
            f"{_binding._RESUME_PLUGIN_LABEL} settlement requires a current receipt"
        )
    owners = {owner.owner_id: owner for owner in attempt.effect_owners}
    _require_effect_owners(
        attempt,
        set(owners),
        {_DEFINITION_OWNER, _ACTIVATION_OWNER} | allowed_external_owner_ids,
    )
    parents = _binding.CodingResumePluginParents(
        definition=attempt.parent_context(owners[_DEFINITION_OWNER]),
        activation=attempt.parent_context(owners[_ACTIVATION_OWNER]),
    )
    try:
        definition, activation = parents._journals(
            session_id=attempt.session_id,
            state_root=state_root,
            clock=clock,
        )
        definition_snapshot = definition.resume_parent_snapshot(parents.definition)
        activation_snapshot = activation.resume_parent_snapshot(parents.activation)
    except (
        _binding.PluginExecutionJournalError,
        _binding.PluginActivationJournalError,
    ) as error:
        raise CodingResumeRecoveryRequired(_UNKNOWN_SETTLEMENT) from error
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
        raise CodingResumeRecoveryRequired(_UNKNOWN_SETTLEMENT)

    raw_revisions = receipt.get("selectedRevisions")
    if not isinstance(raw_revisions, list):
        raise CodingResumeRecoveryRequired(_UNKNOWN_SETTLEMENT)
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
        raise CodingResumeRecoveryRequired(_UNKNOWN_SETTLEMENT) from error

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
        raise CodingResumeRecoveryRequired(_UNKNOWN_SETTLEMENT)
