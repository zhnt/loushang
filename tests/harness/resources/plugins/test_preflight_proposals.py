from __future__ import annotations

from dataclasses import fields

from loushang.harness.resources.plugins.selection import (
    PluginDeclarationDataOnlyDisposition,
    PluginDeclarationExecutionSubjectDisposition,
    PluginDeclarationSourceProposal,
    PluginPreflightProposal,
)


def test_preflight_proposal_field_ownership_is_exact() -> None:
    assert tuple(item.name for item in fields(PluginPreflightProposal)) == (
        "plan",
        "source_proposals",
    )
    assert tuple(item.name for item in fields(PluginDeclarationSourceProposal)) == (
        "package",
        "declaration_source",
        "source_descriptor_fingerprint",
        "reservation_closure",
        "effective_configuration_entries",
        "configuration_map_fingerprint",
        "trust_snapshot",
        "requested_authorities",
        "allowed_authority_ceiling",
        "source_disposition",
    )


def test_source_disposition_is_a_strict_union_without_gate_or_decision_peers() -> None:
    assert tuple(
        item.name for item in fields(PluginDeclarationDataOnlyDisposition)
    ) == ("kind",)
    assert tuple(
        item.name for item in fields(PluginDeclarationExecutionSubjectDisposition)
    ) == ("subject", "kind")
    assert "gate" not in {item.name for item in fields(PluginDeclarationSourceProposal)}
    assert "decision" not in {
        item.name for item in fields(PluginDeclarationSourceProposal)
    }
    assert "preflight_use_id" not in {
        item.name for item in fields(PluginDeclarationSourceProposal)
    }
