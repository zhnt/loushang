from __future__ import annotations

from dataclasses import fields

import pytest

from loushang.harness.resources.plugins.selection import (
    PluginExecutionApprovalSubject,
    PluginInstanceRevisionRef,
    PluginPreflightAcceptedOutcome,
    PluginPreflightDeniedOutcome,
    PluginPreflightDiagnostic,
    PluginPreflightPendingApprovalOutcome,
    PluginPreflightRejectedOutcome,
)


def test_nonaccepted_preflight_outcomes_have_strict_mutually_exclusive_fields() -> None:
    diagnostic = PluginPreflightDiagnostic(
        code="plugin_execution_denied",
        message="execution denied",
        plugin_id="coding.lsp",
        source_descriptor_fingerprint="a" * 64,
    )
    pending = PluginPreflightPendingApprovalOutcome(
        subjects=(_subject(),),
        diagnostics=(diagnostic,),
    )
    denied = PluginPreflightDeniedOutcome(diagnostics=(diagnostic,))
    rejected = PluginPreflightRejectedOutcome(diagnostics=(diagnostic,))

    assert tuple(item.name for item in fields(pending)) == (
        "subjects",
        "diagnostics",
        "disposition",
    )
    assert tuple(item.name for item in fields(denied)) == (
        "diagnostics",
        "disposition",
    )
    assert tuple(item.name for item in fields(rejected)) == (
        "diagnostics",
        "disposition",
    )
    assert pending.disposition == "pending_approval"
    assert denied.disposition == "denied"
    assert rejected.disposition == "rejected"
    assert not hasattr(pending, "accepted")
    assert not hasattr(denied, "subjects")
    assert not hasattr(rejected, "subjects")


def test_preflight_outcomes_reject_empty_or_wrong_arm_payloads() -> None:
    with pytest.raises(ValueError, match="subjects"):
        PluginPreflightPendingApprovalOutcome(subjects=(), diagnostics=())
    with pytest.raises(ValueError, match="diagnostics"):
        PluginPreflightDeniedOutcome(diagnostics=())
    with pytest.raises(ValueError, match="diagnostics"):
        PluginPreflightRejectedOutcome(diagnostics=())
    with pytest.raises(TypeError, match="accepted preflight"):
        PluginPreflightAcceptedOutcome(accepted=object())  # type: ignore[arg-type]


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
