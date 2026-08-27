from __future__ import annotations

from types import MappingProxyType

import pytest

from loushang.foundation.json import JsonValueError
from loushang.harness.diagnostics.runtime_provenance import (
    RuntimeProvenanceComponent,
    RuntimeProvenanceError,
    StaticRuntimeProvenanceContributor,
    compose_runtime_provenance,
)


def test_compose_runtime_provenance_projects_sorted_installation_components() -> None:
    host = {"package_version": "1.2.3"}
    contributors = (
        StaticRuntimeProvenanceContributor(
            component_id="stat",
            kind="plugin",
            installation_details={"availability": "bundled", "schema_version": 2},
        ),
        StaticRuntimeProvenanceContributor(
            component_id="native-screen",
            kind="renderer",
            installation_details={"contract_version": 1},
        ),
    )

    result = compose_runtime_provenance(host, contributors=contributors)

    assert result == {
        "package_version": "1.2.3",
        "provenance_schema_version": 1,
        "provenance_scope": "installation",
        "components": {
            "native-screen": {"kind": "renderer", "contract_version": 1},
            "stat": {
                "kind": "plugin",
                "availability": "bundled",
                "schema_version": 2,
            },
        },
    }
    assert host == {"package_version": "1.2.3"}


def test_runtime_scope_uses_only_effective_runtime_facts() -> None:
    contributor = StaticRuntimeProvenanceContributor(
        component_id="stat",
        kind="plugin",
        installation_details={"availability": "bundled"},
        runtime_details={"state": "active", "schema_version": 2},
    )

    result = compose_runtime_provenance(
        {},
        contributors=(contributor,),
        scope="runtime",
    )

    assert result["components"] == {
        "stat": {"kind": "plugin", "state": "active", "schema_version": 2}
    }


def test_runtime_scope_omits_installation_only_contributors() -> None:
    contributor = StaticRuntimeProvenanceContributor(
        component_id="native-screen",
        kind="renderer",
        installation_details={"availability": "bundled"},
    )

    result = compose_runtime_provenance(
        {},
        contributors=(contributor,),
        scope="runtime",
    )

    assert result["components"] == {}


def test_component_defensively_copies_and_freezes_details() -> None:
    details = {"state": "active"}

    component = RuntimeProvenanceComponent("stat", "plugin", details)
    details["state"] = "disabled"

    assert component.details == {"state": "active"}
    assert isinstance(component.details, MappingProxyType)
    with pytest.raises(TypeError):
        component.details["state"] = "disabled"  # type: ignore[index]


def test_component_rejects_non_json_details_and_reserved_kind() -> None:
    with pytest.raises(JsonValueError):
        RuntimeProvenanceComponent("stat", "plugin", {"value": object()})
    with pytest.raises(RuntimeProvenanceError, match="reserve 'kind'"):
        RuntimeProvenanceComponent("stat", "plugin", {"kind": "replacement"})


def test_compose_runtime_provenance_rejects_duplicate_component_ids() -> None:
    contributors = (
        StaticRuntimeProvenanceContributor("stat", "plugin"),
        StaticRuntimeProvenanceContributor("stat", "plugin"),
    )

    with pytest.raises(RuntimeProvenanceError, match="duplicate provenance"):
        compose_runtime_provenance({}, contributors=contributors)
