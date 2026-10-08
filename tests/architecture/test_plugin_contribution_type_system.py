from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path
from typing import get_args

import pytest

from loushang.harness.capabilities import contribution_admission
from loushang.harness.capabilities.contracts import CapabilityContractRange
from loushang.harness.resources.plugins import declarations
from loushang.harness.resources.plugins.contribution_types import (
    PLUGIN_CONTRIBUTION_KINDS,
    PLUGIN_OWNER_CONTRIBUTION_KINDS,
    PluginContributionKind,
    PluginOwnerContributionKind,
)
from loushang.harness.resources.plugins.declarations import (
    PluginContributionReservation,
    PluginDeclaration,
    PluginDeclarationCodecError,
    PluginDeclarationSource,
)
from loushang.plugin import CapabilityProviderSpec, ResourceItemSpec

CONTRIBUTION_TYPES = Path(
    "src/loushang/harness/resources/plugins/contribution_types.py"
)


def _assigned_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def test_contribution_kinds_have_one_canonical_closed_definition() -> None:
    assert declarations.PluginContributionKind is PluginContributionKind
    assert contribution_admission.OwnerContributionKind is PluginOwnerContributionKind
    assert set(get_args(PluginContributionKind)) == PLUGIN_CONTRIBUTION_KINDS
    assert set(get_args(PluginOwnerContributionKind)) == PLUGIN_OWNER_CONTRIBUTION_KINDS

    definitions = tuple(
        path
        for path in Path("src/loushang").rglob("*.py")
        if "PluginContributionKind" in _assigned_names(path)
    )
    assert definitions == (CONTRIBUTION_TYPES,)

    for path in (
        Path("src/loushang/harness/session/product_composition_assembly.py"),
        Path("src/loushang/coding/_resource_catalog_shadow.py"),
    ):
        source = path.read_text(encoding="utf-8")
        assert "_EXTERNAL_CONTRIBUTION_KINDS" not in source
        assert "PLUGIN_OWNER_CONTRIBUTION_KINDS" in source


def test_wire_owner_is_only_an_inert_exact_id_and_records_reject_locator_fields() -> None:
    class LiveString(str):
        pass

    source = PluginDeclarationSource.in_process("definition.py:declare")
    with pytest.raises(ValueError, match="Invalid contribution owner"):
        PluginContributionReservation(
            contribution_id="provider",
            kind="capability_provider",
            owner=object(),  # type: ignore[arg-type]
            declaration_source=source,
            contribution_execution_model="in_process",
            requested_authorities=(),
        )

    owner = LiveString("example.echo")
    owner.registry = object()
    with pytest.raises(ValueError, match="Invalid contribution owner"):
        PluginContributionReservation(
            contribution_id="provider",
            kind="capability_provider",
            owner=owner,
            declaration_source=source,
            contribution_execution_model="in_process",
            requested_authorities=(),
        )

    label = LiveString("safe-text")
    label.service_locator = object()
    with pytest.raises(ValueError, match="only JSON values"):
        PluginContributionReservation(
            contribution_id="provider",
            kind="capability_provider",
            owner="example.echo",
            declaration_source=source,
            contribution_execution_model="in_process",
            requested_authorities=(),
            configuration={"label": label},
        )

    document: dict[str, object] = {
        "configuration": {},
        "contributionExecutionModel": "in_process",
        "declarationSource": source.to_dict(),
        "id": "provider",
        "kind": "capability_provider",
        "owner": {"registry": "ambient"},
        "requestedAuthorities": [],
        "required": True,
    }
    with pytest.raises(PluginDeclarationCodecError) as owner_error:
        PluginContributionReservation.from_dict(document)
    assert owner_error.value.code == "plugin_declaration_field_type_mismatch"

    document["owner"] = "example.echo"
    document["serviceLocator"] = "ambient"
    with pytest.raises(PluginDeclarationCodecError) as locator_error:
        PluginContributionReservation.from_dict(document)
    assert locator_error.value.code == "plugin_declaration_exact_field_mismatch"


def test_public_authoring_specs_carry_data_references_without_live_owner_access() -> None:
    class LiveString(str):
        pass

    forbidden_fields = {"owner", "registry", "service_locator", "services", "context"}
    for spec in (CapabilityProviderSpec, ResourceItemSpec):
        assert forbidden_fields.isdisjoint(field.name for field in fields(spec))

    for record in (PluginContributionReservation, PluginDeclaration):
        owner_field = next(field for field in fields(record) if field.name == "owner")
        assert owner_field.type == "str"

    with pytest.raises(TypeError, match="owner reference must be a string"):
        CapabilityProviderSpec(
            contribution_id="provider",
            capability=object(),  # type: ignore[arg-type]
            provider_id="example",
            implementation_version=1,
            compatible_contract=CapabilityContractRange(minimum=1, maximum=1),
            facets=(),
            requirements=(),
            authorities=frozenset(),
            factory="definition.py:create",
            disposer=None,
        )
    with pytest.raises(TypeError, match="owner reference must be a string"):
        ResourceItemSpec(
            contribution_id="resource",
            locator="SKILL.md",
            locator_kind="file",
            media_type="text/markdown",
            owner_namespace=object(),  # type: ignore[arg-type]
            resource_kind="skill",
            schema_id="loushang.resource.skill",
            schema_version=1,
        )
    with pytest.raises(TypeError, match="owner reference must be a string"):
        ResourceItemSpec(
            contribution_id="resource",
            locator="SKILL.md",
            locator_kind="file",
            media_type="text/markdown",
            owner_namespace=LiveString("resources.skill"),
            resource_kind="skill",
            schema_id="loushang.resource.skill",
            schema_version=1,
        )
