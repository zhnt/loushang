from __future__ import annotations

from dataclasses import fields

from loushang.harness.resources.plugins.selection import (
    AcceptedPluginPreflight,
    PluginDeclarationDataOnlyGate,
    PluginDeclarationExecutionPreflightGate,
    PluginDeclarationReservation,
    PluginDeclarationSourceGroup,
)


def test_accepted_preflight_and_source_group_field_ownership_is_exact() -> None:
    assert tuple(item.name for item in fields(AcceptedPluginPreflight)) == (
        "preflight_use_id",
        "host_boot_id",
        "expires_at",
        "context",
        "source_groups",
        "_terminal_handle",
    )
    assert tuple(item.name for item in fields(PluginDeclarationSourceGroup)) == (
        "preflight_use_id",
        "source_group_id",
        "source_group_fingerprint",
        "package",
        "declaration_source",
        "source_descriptor_fingerprint",
        "context",
        "instance_revision_ref",
        "reservation_closure",
        "reservation_closure_fingerprint",
        "effective_configuration_entries",
        "configuration_map_fingerprint",
        "trust_snapshot",
        "requested_authorities",
        "allowed_authority_ceiling",
        "gate",
    )


def test_group_gate_and_reservation_have_no_copied_approval_peers() -> None:
    assert tuple(item.name for item in fields(PluginDeclarationDataOnlyGate)) == (
        "kind",
    )
    assert tuple(
        item.name for item in fields(PluginDeclarationExecutionPreflightGate)
    ) == ("subject", "decision", "kind")
    assert tuple(item.name for item in fields(PluginDeclarationReservation)) == (
        "package",
        "contribution",
        "source_group_id",
        "source_group_fingerprint",
    )
    reservation_fields = {
        item.name for item in fields(PluginDeclarationReservation)
    }
    assert not {
        "gate",
        "approval_subject",
        "decision",
        "decision_id",
        "context",
    }.intersection(reservation_fields)
