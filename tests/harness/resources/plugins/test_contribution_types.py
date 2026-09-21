from __future__ import annotations

from types import MappingProxyType
from typing import get_args

import pytest

from loushang.harness.resources.plugins import declarations
from loushang.harness.resources.plugins.contribution_types import (
    PLUGIN_CONTRIBUTION_KINDS,
    PLUGIN_CONTRIBUTION_SCHEMA_V2,
    PLUGIN_CONTRIBUTION_SCHEMA_V3,
    PLUGIN_CONTRIBUTION_SCHEMAS,
    PLUGIN_CONTRIBUTION_TYPE_SYSTEM_VERSION,
    PLUGIN_OWNER_CONTRIBUTION_KINDS,
    PluginContributionKind,
    plugin_contribution_schema_for_index,
    plugin_contribution_schema_for_ir,
)


def test_closed_type_system_is_the_declaration_codec_authority() -> None:
    assert PLUGIN_CONTRIBUTION_TYPE_SYSTEM_VERSION == 1
    assert PLUGIN_CONTRIBUTION_KINDS == frozenset(get_args(PluginContributionKind))
    assert declarations.PluginContributionKind is PluginContributionKind
    assert isinstance(PLUGIN_CONTRIBUTION_SCHEMAS, MappingProxyType)
    assert plugin_contribution_schema_for_index(2) is PLUGIN_CONTRIBUTION_SCHEMA_V2
    assert plugin_contribution_schema_for_index(3) is PLUGIN_CONTRIBUTION_SCHEMA_V3
    assert plugin_contribution_schema_for_ir(2) is PLUGIN_CONTRIBUTION_SCHEMA_V2
    assert plugin_contribution_schema_for_ir(3) is PLUGIN_CONTRIBUTION_SCHEMA_V3
    assert plugin_contribution_schema_for_index(True) is None
    assert plugin_contribution_schema_for_index(4) is None
    with pytest.raises(TypeError):
        PLUGIN_CONTRIBUTION_SCHEMAS[4] = PLUGIN_CONTRIBUTION_SCHEMA_V3  # type: ignore[index]


def test_each_schema_closes_kind_execution_and_authority_combinations() -> None:
    expected_v2 = {
        "capability_provider": frozenset({"in_process"}),
        "command_pack": frozenset({"data_only"}),
        "continuity_provider": frozenset({"in_process"}),
        "resource_item": frozenset({"data_only"}),
        "tool_pack": frozenset({"data_only"}),
    }
    expected_v3 = {
        **expected_v2,
        "capability_provider": frozenset({"in_process", "local_worker"}),
    }
    assert {
        kind: rule.execution_models
        for kind, rule in PLUGIN_CONTRIBUTION_SCHEMA_V2.rules.items()
    } == expected_v2
    assert {
        kind: rule.execution_models
        for kind, rule in PLUGIN_CONTRIBUTION_SCHEMA_V3.rules.items()
    } == expected_v3
    assert {
        kind
        for kind, rule in PLUGIN_CONTRIBUTION_SCHEMA_V3.rules.items()
        if not rule.permits_requested_authorities
    } == PLUGIN_OWNER_CONTRIBUTION_KINDS
