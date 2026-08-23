from __future__ import annotations

import inspect
from dataclasses import fields

import pytest

from loushang.harness.resources.plugins.selection import (
    PendingOnlyPluginExecutionDecisionLookup,
    PluginExecutionApprovalSubject,
    PluginExecutionDecisionCurrent,
    PluginExecutionDecisionMissing,
    PluginExecutionDecisionRecord,
    PluginInstanceRevisionRef,
    PluginSelectionResolver,
)


def test_preflight_accepts_only_the_approval_owner_lookup_port() -> None:
    parameters = inspect.signature(PluginSelectionResolver.preflight).parameters

    assert "decision_lookup" in parameters
    assert "decisions" not in parameters


def test_pending_only_lookup_has_no_decision_storage_or_positive_arm() -> None:
    lookup = PendingOnlyPluginExecutionDecisionLookup()
    result = lookup.lookup_execution_decision(_subject())

    assert isinstance(result, PluginExecutionDecisionMissing)
    assert tuple(item.name for item in fields(result)) == ("disposition",)
    assert vars(lookup) == {}


def test_current_lookup_result_requires_an_exact_v2_decision() -> None:
    decision = PluginExecutionDecisionRecord(
        decision_id="decision-1",
        subject_digest=_subject().digest,
        policy_revision="policy-1",
        disposition="approved",
    )

    current = PluginExecutionDecisionCurrent(decision=decision)

    assert current.disposition == "current"
    assert current.decision is decision
    with pytest.raises(TypeError, match="DecisionRecord"):
        PluginExecutionDecisionCurrent(decision=object())  # type: ignore[arg-type]


def _subject() -> PluginExecutionApprovalSubject:
    return PluginExecutionApprovalSubject(
        plugin_id="coding.lsp",
        package_content_digest="3" * 64,
        dependency_lock_digest="2" * 64,
        entrypoint="definition.py:define",
        package_source_identity="registry:example",
        source_trust_class="registry_signed",
        source_trust_policy_revision="trust-1",
        product_id="coding",
        scope_id="workspace",
        policy_revision="policy-1",
        ambient_host_authority=True,
        configuration_map_fingerprint="1" * 64,
        requested_authorities=("process.launch",),
        allowed_authority_ceiling=("process.launch",),
        reservation_closure_fingerprint="4" * 64,
        source_descriptor_fingerprint=(
            "c24ebbab018030bda115eee4257003ef8ac86423faa480fe158bce31fc0377b7"
        ),
        instance_revision_ref=PluginInstanceRevisionRef(
            instance_id="coding.lsp@product",
            plugin_id="coding.lsp",
            revision=1,
        ),
    )
