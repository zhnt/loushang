"""Pure, deterministic comparison of compiled ontology schemas."""

from __future__ import annotations

import json as stdlib_json
from dataclasses import dataclass, field
from enum import Enum
from typing import cast

from loushang.foundation.json import JSONValue, dump_json_value
from loushang.ontology.schema.compiler import (
    CompiledActionDefinition,
    CompiledInterfaceTypeDefinition,
    CompiledLinkTypeDefinition,
    CompiledObjectTypeDefinition,
    CompiledOntologySchema,
    CompiledPropertyDefinition,
)
from loushang.ontology.schema.definitions import SchemaVersion

SCHEMA_DIFF_FORMAT = "loushang.ontology.schema-diff/v4"


class ChangeImpact(str, Enum):
    """Compatibility impact of one schema change."""

    NON_BREAKING = "non_breaking"
    BEHAVIORAL = "behavioral"
    BREAKING = "breaking"


class SchemaLineageError(ValueError):
    """Raised when two schemas do not belong to the same package lineage."""

    def __init__(self, old_package_id: str, new_package_id: str) -> None:
        self.old_package_id = old_package_id
        self.new_package_id = new_package_id
        super().__init__(
            f"cannot compare schema packages '{old_package_id}' and '{new_package_id}'"
        )


@dataclass(frozen=True, slots=True, init=False)
class SchemaChange:
    """One stable, immutable schema change record."""

    code: str
    path: str
    impact: ChangeImpact
    message: str
    _before_json: str = field(repr=False)
    _after_json: str = field(repr=False)

    def __init__(
        self,
        *,
        code: str,
        path: str,
        impact: ChangeImpact,
        message: str,
        before: object,
        after: object,
    ) -> None:
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "path", path)
        object.__setattr__(self, "impact", impact)
        object.__setattr__(self, "message", message)
        object.__setattr__(self, "_before_json", _canonical_json(before))
        object.__setattr__(self, "_after_json", _canonical_json(after))

    @property
    def before(self) -> JSONValue:
        return cast(JSONValue, stdlib_json.loads(self._before_json))

    @property
    def after(self) -> JSONValue:
        return cast(JSONValue, stdlib_json.loads(self._after_json))

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "code": self.code,
            "path": self.path,
            "impact": self.impact.value,
            "message": self.message,
            "before": self.before,
            "after": self.after,
        }


@dataclass(frozen=True, slots=True)
class SchemaDiff:
    """Deterministically ordered changes between two schema versions."""

    package_id: str
    from_version: SchemaVersion
    to_version: SchemaVersion
    changes: tuple[SchemaChange, ...]
    format: str = SCHEMA_DIFF_FORMAT

    @property
    def is_empty(self) -> bool:
        return not self.changes

    @property
    def has_breaking_changes(self) -> bool:
        return any(change.impact is ChangeImpact.BREAKING for change in self.changes)

    @property
    def highest_impact(self) -> ChangeImpact | None:
        for impact in (
            ChangeImpact.BREAKING,
            ChangeImpact.BEHAVIORAL,
            ChangeImpact.NON_BREAKING,
        ):
            if any(change.impact is impact for change in self.changes):
                return impact
        return None

    def to_dict(self) -> dict[str, JSONValue]:
        return {
            "format": self.format,
            "package_id": self.package_id,
            "from_version": self.from_version.value,
            "to_version": self.to_version.value,
            "changes": [change.to_dict() for change in self.changes],
        }

    def to_json(self) -> str:
        return dump_json_value(self.to_dict(), name="ontology schema diff", sort_keys=True)


def compare_schemas(
    old: CompiledOntologySchema,
    new: CompiledOntologySchema,
) -> SchemaDiff:
    """Compare two compiled snapshots without I/O or runtime mutation."""

    if old.package_id != new.package_id:
        raise SchemaLineageError(old.package_id, new.package_id)

    changes: list[SchemaChange] = []
    if old.namespace != new.namespace:
        _add_change(
            changes,
            code="namespace_changed",
            path="$.namespace",
            impact=ChangeImpact.BREAKING,
            message="schema namespace changed",
            before=old.namespace,
            after=new.namespace,
        )

    _compare_interface_types(old, new, changes)
    _compare_object_types(old, new, changes)
    _compare_link_types(old, new, changes)
    _compare_actions(old, new, changes)
    ordered = tuple(sorted(changes, key=lambda change: (change.path, change.code)))
    return SchemaDiff(
        package_id=old.package_id,
        from_version=old.version,
        to_version=new.version,
        changes=ordered,
    )


def _compare_object_types(
    old: CompiledOntologySchema,
    new: CompiledOntologySchema,
    changes: list[SchemaChange],
) -> None:
    old_types = {
        object_type.semantic_id: object_type for object_type in old.object_types
    }
    new_types = {
        object_type.semantic_id: object_type for object_type in new.object_types
    }

    for semantic_id in sorted(old_types.keys() - new_types.keys()):
        object_type = old_types[semantic_id]
        path = _object_path(semantic_id)
        _add_change(
            changes,
            code="object_type_removed",
            path=path,
            impact=ChangeImpact.BREAKING,
            message=f"object type '{object_type.name}' was removed",
            before=_object_snapshot(object_type),
            after=None,
        )
    for semantic_id in sorted(new_types.keys() - old_types.keys()):
        object_type = new_types[semantic_id]
        path = _object_path(semantic_id)
        _add_change(
            changes,
            code="object_type_added",
            path=path,
            impact=ChangeImpact.NON_BREAKING,
            message=f"object type '{object_type.name}' was added",
            before=None,
            after=_object_snapshot(object_type),
        )
    for semantic_id in sorted(old_types.keys() & new_types.keys()):
        _compare_object_type(
            old_types[semantic_id],
            new_types[semantic_id],
            changes,
        )


def _compare_object_type(
    old: CompiledObjectTypeDefinition,
    new: CompiledObjectTypeDefinition,
    changes: list[SchemaChange],
) -> None:
    path = _object_path(old.semantic_id)
    if old.name != new.name:
        _field_change(
            changes,
            code="object_type_name_changed",
            path=f"{path}.name",
            impact=ChangeImpact.BREAKING,
            message=f"object type '{old.name}' was renamed to '{new.name}'",
            before=old.name,
            after=new.name,
        )
    if old.state_authority is not new.state_authority:
        _field_change(
            changes,
            code="object_existence_authority_changed",
            path=f"{path}.state_authority",
            impact=ChangeImpact.BREAKING,
            message=f"object type '{old.name}' existence authority changed",
            before=old.state_authority.value,
            after=new.state_authority.value,
        )
    if old.parent_types != new.parent_types:
        _field_change(
            changes,
            code="object_type_parents_changed",
            path=f"{path}.parent_types",
            impact=ChangeImpact.BREAKING,
            message=f"object type '{old.name}' parent types changed",
            before=list(old.parent_types),
            after=list(new.parent_types),
        )
    for name in sorted(set(old.interfaces) - set(new.interfaces)):
        _add_change(
            changes,
            code="object_interface_removed",
            path=f"{path}.interfaces",
            impact=ChangeImpact.BREAKING,
            message=f"object type '{old.name}' stopped implementing interface '{name}'",
            before=name,
            after=None,
        )
    for name in sorted(set(new.interfaces) - set(old.interfaces)):
        _add_change(
            changes,
            code="object_interface_added",
            path=f"{path}.interfaces",
            impact=ChangeImpact.NON_BREAKING,
            message=f"object type '{old.name}' implements interface '{name}'",
            before=None,
            after=name,
        )
    if old.abstract != new.abstract:
        tightened = not old.abstract and new.abstract
        _field_change(
            changes,
            code=(
                "object_type_abstract_tightened"
                if tightened
                else "object_type_abstract_relaxed"
            ),
            path=f"{path}.abstract",
            impact=(ChangeImpact.BREAKING if tightened else ChangeImpact.NON_BREAKING),
            message=f"object type '{old.name}' abstract constraint changed",
            before=old.abstract,
            after=new.abstract,
        )
    _behavioral_field(
        changes,
        code="object_type_icon_changed",
        path=f"{path}.icon",
        message=f"object type '{old.name}' icon changed",
        before=old.icon,
        after=new.icon,
    )
    _behavioral_field(
        changes,
        code="object_type_description_changed",
        path=f"{path}.description",
        message=f"object type '{old.name}' description changed",
        before=old.description,
        after=new.description,
    )
    _behavioral_field(
        changes,
        code="object_type_display_name_changed",
        path=f"{path}.display_name_property",
        message=f"object type '{old.name}' display-name property changed",
        before=old.display_name_property,
        after=new.display_name_property,
    )
    _compare_properties(old, new, changes)


def _compare_properties(
    old_object: CompiledObjectTypeDefinition,
    new_object: CompiledObjectTypeDefinition,
    changes: list[SchemaChange],
) -> None:
    old_properties = {_property_id(prop): prop for prop in old_object.properties}
    new_properties = {_property_id(prop): prop for prop in new_object.properties}

    for semantic_id in sorted(old_properties.keys() - new_properties.keys()):
        prop = old_properties[semantic_id]
        path = _property_path(old_object.semantic_id, semantic_id)
        _add_change(
            changes,
            code="property_removed",
            path=path,
            impact=ChangeImpact.BREAKING,
            message=f"property '{old_object.name}.{prop.name}' was removed",
            before=_property_snapshot(prop),
            after=None,
        )
    for semantic_id in sorted(new_properties.keys() - old_properties.keys()):
        prop = new_properties[semantic_id]
        path = _property_path(new_object.semantic_id, semantic_id)
        required = prop.required
        _add_change(
            changes,
            code="required_property_added" if required else "property_added",
            path=path,
            impact=ChangeImpact.BREAKING if required else ChangeImpact.NON_BREAKING,
            message=f"property '{new_object.name}.{prop.name}' was added",
            before=None,
            after=_property_snapshot(prop),
        )
    for semantic_id in sorted(old_properties.keys() & new_properties.keys()):
        _compare_property(
            old_object,
            old_properties[semantic_id],
            new_properties[semantic_id],
            changes,
        )


def _compare_property(
    object_type: CompiledObjectTypeDefinition,
    old: CompiledPropertyDefinition,
    new: CompiledPropertyDefinition,
    changes: list[SchemaChange],
) -> None:
    object_name = object_type.name
    path = _property_path(object_type.semantic_id, _property_id(old))
    if old.name != new.name:
        _field_change(
            changes,
            code="property_name_changed",
            path=f"{path}.name",
            impact=ChangeImpact.BREAKING,
            message=(
                f"property '{object_name}.{old.name}' was renamed to '{new.name}'"
            ),
            before=old.name,
            after=new.name,
        )
    assert old.state_authority is not None
    assert new.state_authority is not None
    if old.state_authority is not new.state_authority:
        _field_change(
            changes,
            code="property_state_authority_changed",
            path=f"{path}.state_authority",
            impact=ChangeImpact.BREAKING,
            message=f"property '{object_name}.{old.name}' authority changed",
            before=old.state_authority.value,
            after=new.state_authority.value,
        )
    if old.value_type is not new.value_type:
        _field_change(
            changes,
            code="property_value_type_changed",
            path=f"{path}.value_type",
            impact=ChangeImpact.BREAKING,
            message=f"property '{object_name}.{old.name}' value type changed",
            before=old.value_type.value,
            after=new.value_type.value,
        )
    if old.required != new.required:
        tightened = not old.required and new.required
        _field_change(
            changes,
            code=(
                "property_required_tightened"
                if tightened
                else "property_required_relaxed"
            ),
            path=f"{path}.required",
            impact=ChangeImpact.BREAKING if tightened else ChangeImpact.NON_BREAKING,
            message=f"property '{object_name}.{old.name}' required constraint changed",
            before=old.required,
            after=new.required,
        )
    _behavioral_field(
        changes,
        code="property_default_changed",
        path=f"{path}.default",
        message=f"property '{object_name}.{old.name}' default changed",
        before=old.default,
        after=new.default,
    )
    if old.unique != new.unique:
        _field_change(
            changes,
            code="property_unique_changed",
            path=f"{path}.unique",
            impact=(
                ChangeImpact.BREAKING if new.unique else ChangeImpact.NON_BREAKING
            ),
            message=f"property '{object_name}.{old.name}' unique declaration changed",
            before=old.unique,
            after=new.unique,
        )
    _behavioral_field(
        changes,
        code="property_indexed_changed",
        path=f"{path}.indexed",
        message=f"property '{object_name}.{old.name}' index declaration changed",
        before=old.indexed,
        after=new.indexed,
    )
    _behavioral_field(
        changes,
        code="property_description_changed",
        path=f"{path}.description",
        message=f"property '{object_name}.{old.name}' description changed",
        before=old.description,
        after=new.description,
    )


def _compare_link_types(
    old: CompiledOntologySchema,
    new: CompiledOntologySchema,
    changes: list[SchemaChange],
) -> None:
    old_links = {link.semantic_id: link for link in old.link_types}
    new_links = {link.semantic_id: link for link in new.link_types}

    for semantic_id in sorted(old_links.keys() - new_links.keys()):
        link = old_links[semantic_id]
        path = _link_path(semantic_id)
        _add_change(
            changes,
            code="link_type_removed",
            path=path,
            impact=ChangeImpact.BREAKING,
            message=f"link type '{link.name}' was removed",
            before=_link_snapshot(link),
            after=None,
        )
    for semantic_id in sorted(new_links.keys() - old_links.keys()):
        link = new_links[semantic_id]
        path = _link_path(semantic_id)
        required = link.required
        _add_change(
            changes,
            code="required_link_type_added" if required else "link_type_added",
            path=path,
            impact=ChangeImpact.BREAKING if required else ChangeImpact.NON_BREAKING,
            message=f"link type '{link.name}' was added",
            before=None,
            after=_link_snapshot(link),
        )
    for semantic_id in sorted(old_links.keys() & new_links.keys()):
        _compare_link_type(
            old_links[semantic_id],
            new_links[semantic_id],
            changes,
        )


def _compare_actions(
    old: CompiledOntologySchema,
    new: CompiledOntologySchema,
    changes: list[SchemaChange],
) -> None:
    old_actions = {action.semantic_id: action for action in old.actions}
    new_actions = {action.semantic_id: action for action in new.actions}
    for semantic_id in sorted(old_actions.keys() - new_actions.keys()):
        action = old_actions[semantic_id]
        _add_change(
            changes,
            code="action_removed",
            path=_action_path(semantic_id),
            impact=ChangeImpact.BREAKING,
            message=f"action '{action.name}' was removed",
            before=_action_snapshot(action),
            after=None,
        )
    for semantic_id in sorted(new_actions.keys() - old_actions.keys()):
        action = new_actions[semantic_id]
        _add_change(
            changes,
            code="action_added",
            path=_action_path(semantic_id),
            impact=ChangeImpact.NON_BREAKING,
            message=f"action '{action.name}' was added",
            before=None,
            after=_action_snapshot(action),
        )
    for semantic_id in sorted(old_actions.keys() & new_actions.keys()):
        old_action = old_actions[semantic_id]
        new_action = new_actions[semantic_id]
        path = _action_path(semantic_id)
        if old_action.name != new_action.name:
            _field_change(
                changes,
                code="action_name_changed",
                path=f"{path}.name",
                impact=ChangeImpact.BREAKING,
                message=f"action '{old_action.name}' was renamed to '{new_action.name}'",
                before=old_action.name,
                after=new_action.name,
            )
        old_contract = _action_contract_snapshot(old_action)
        new_contract = _action_contract_snapshot(new_action)
        if _canonical_json(old_contract) != _canonical_json(new_contract):
            _add_change(
                changes,
                code="action_contract_changed",
                path=f"{path}.contract",
                impact=ChangeImpact.BREAKING,
                message=f"action '{old_action.name}' contract changed",
                before=old_contract,
                after=new_contract,
            )
        _behavioral_field(
            changes,
            code="action_description_changed",
            path=f"{path}.description",
            message=f"action '{old_action.name}' description changed",
            before=old_action.description,
            after=new_action.description,
        )


def _compare_interface_types(
    old: CompiledOntologySchema,
    new: CompiledOntologySchema,
    changes: list[SchemaChange],
) -> None:
    old_interfaces = {item.name: item for item in old.interface_types}
    new_interfaces = {item.name: item for item in new.interface_types}
    for name in sorted(old_interfaces.keys() - new_interfaces.keys()):
        _add_change(
            changes,
            code="interface_type_removed",
            path=_interface_path(name),
            impact=ChangeImpact.BREAKING,
            message=f"interface type '{name}' was removed",
            before=_interface_snapshot(old_interfaces[name]),
            after=None,
        )
    for name in sorted(new_interfaces.keys() - old_interfaces.keys()):
        _add_change(
            changes,
            code="interface_type_added",
            path=_interface_path(name),
            impact=ChangeImpact.NON_BREAKING,
            message=f"interface type '{name}' was added",
            before=None,
            after=_interface_snapshot(new_interfaces[name]),
        )
    for name in sorted(old_interfaces.keys() & new_interfaces.keys()):
        old_interface = old_interfaces[name]
        new_interface = new_interfaces[name]
        before_properties = [
            _interface_property_snapshot(prop)
            for prop in sorted(old_interface.properties, key=lambda prop: prop.name)
        ]
        after_properties = [
            _interface_property_snapshot(prop)
            for prop in sorted(new_interface.properties, key=lambda prop: prop.name)
        ]
        if _canonical_json(before_properties) != _canonical_json(after_properties):
            _add_change(
                changes,
                code="interface_contract_changed",
                path=_interface_path(name),
                impact=ChangeImpact.BREAKING,
                message=f"interface type '{name}' contract changed",
                before=before_properties,
                after=after_properties,
            )
        _behavioral_field(
            changes,
            code="interface_description_changed",
            path=f"{_interface_path(name)}.description",
            message=f"interface type '{name}' description changed",
            before=old_interface.description,
            after=new_interface.description,
        )


def _compare_link_type(
    old: CompiledLinkTypeDefinition,
    new: CompiledLinkTypeDefinition,
    changes: list[SchemaChange],
) -> None:
    path = _link_path(old.semantic_id)
    if old.name != new.name:
        _field_change(
            changes,
            code="link_type_name_changed",
            path=f"{path}.name",
            impact=ChangeImpact.BREAKING,
            message=f"link type '{old.name}' was renamed to '{new.name}'",
            before=old.name,
            after=new.name,
        )
    if old.state_authority is not new.state_authority:
        _field_change(
            changes,
            code="link_state_authority_changed",
            path=f"{path}.state_authority",
            impact=ChangeImpact.BREAKING,
            message=f"link type '{old.name}' authority changed",
            before=old.state_authority.value,
            after=new.state_authority.value,
        )
    for field_name, code, before, after in (
        ("source_type", "link_source_type_changed", old.source_type, new.source_type),
        ("target_type", "link_target_type_changed", old.target_type, new.target_type),
        (
            "cardinality",
            "link_cardinality_changed",
            old.cardinality.value,
            new.cardinality.value,
        ),
    ):
        if before != after:
            _field_change(
                changes,
                code=code,
                path=f"{path}.{field_name}",
                impact=ChangeImpact.BREAKING,
                message=f"link type '{old.name}' {field_name} changed",
                before=before,
                after=after,
            )
    if old.required != new.required:
        tightened = not old.required and new.required
        _field_change(
            changes,
            code="link_required_tightened" if tightened else "link_required_relaxed",
            path=f"{path}.required",
            impact=ChangeImpact.BREAKING if tightened else ChangeImpact.NON_BREAKING,
            message=f"link type '{old.name}' required declaration changed",
            before=old.required,
            after=new.required,
        )
    _behavioral_field(
        changes,
        code="link_inverse_name_changed",
        path=f"{path}.inverse_name",
        message=f"link type '{old.name}' inverse name changed",
        before=old.inverse_name,
        after=new.inverse_name,
    )
    _behavioral_field(
        changes,
        code="link_temporal_changed",
        path=f"{path}.temporal",
        message=f"link type '{old.name}' temporal declaration changed",
        before=old.temporal,
        after=new.temporal,
    )
    _behavioral_field(
        changes,
        code="link_description_changed",
        path=f"{path}.description",
        message=f"link type '{old.name}' description changed",
        before=old.description,
        after=new.description,
    )


def _behavioral_field(
    changes: list[SchemaChange],
    *,
    code: str,
    path: str,
    message: str,
    before: object,
    after: object,
) -> None:
    if _canonical_json(before) != _canonical_json(after):
        _field_change(
            changes,
            code=code,
            path=path,
            impact=ChangeImpact.BEHAVIORAL,
            message=message,
            before=before,
            after=after,
        )


def _field_change(
    changes: list[SchemaChange],
    *,
    code: str,
    path: str,
    impact: ChangeImpact,
    message: str,
    before: object,
    after: object,
) -> None:
    _add_change(
        changes,
        code=code,
        path=path,
        impact=impact,
        message=message,
        before=before,
        after=after,
    )


def _add_change(
    changes: list[SchemaChange],
    *,
    code: str,
    path: str,
    impact: ChangeImpact,
    message: str,
    before: object,
    after: object,
) -> None:
    changes.append(
        SchemaChange(
            code=code,
            path=path,
            impact=impact,
            message=message,
            before=before,
            after=after,
        )
    )


def _canonical_json(value: object) -> str:
    return dump_json_value(value, name="schema change value", sort_keys=True)


def _object_snapshot(object_type: CompiledObjectTypeDefinition) -> dict[str, JSONValue]:
    return {
        "semantic_id": object_type.semantic_id,
        "name": object_type.name,
        "state_authority": object_type.state_authority.value,
        "properties": [
            _property_snapshot(prop)
            for prop in sorted(object_type.properties, key=_property_id)
        ],
        "parent_types": list(object_type.parent_types),
        "interfaces": list(object_type.interfaces),
        "abstract": object_type.abstract,
        "icon": object_type.icon,
        "description": object_type.description,
        "display_name_property": object_type.display_name_property,
    }


def _property_snapshot(prop: CompiledPropertyDefinition) -> dict[str, JSONValue]:
    return {
        "semantic_id": _property_id(prop),
        "name": prop.name,
        "state_authority": _property_authority_value(prop),
        "value_type": prop.value_type.value,
        "required": prop.required,
        "unique": prop.unique,
        "indexed": prop.indexed,
        "default": prop.default,
        "description": prop.description,
    }


def _link_snapshot(link: CompiledLinkTypeDefinition) -> dict[str, JSONValue]:
    return {
        "semantic_id": link.semantic_id,
        "name": link.name,
        "state_authority": link.state_authority.value,
        "source_type": link.source_type,
        "target_type": link.target_type,
        "cardinality": link.cardinality.value,
        "required": link.required,
        "inverse_name": link.inverse_name,
        "temporal": link.temporal,
        "description": link.description,
    }


def _action_snapshot(action: CompiledActionDefinition) -> dict[str, JSONValue]:
    return {
        "semantic_id": action.semantic_id,
        "name": action.name,
        **_action_contract_snapshot(action),
        "description": action.description,
    }


def _action_contract_snapshot(
    action: CompiledActionDefinition,
) -> dict[str, JSONValue]:
    return {
        "target_object_type_id": action.target_object_type_id,
        "parameters": [
            {
                "name": parameter.name,
                "value_type": parameter.value_type.value,
                "description": parameter.description,
            }
            for parameter in action.parameters
        ],
        "effect": {
            "kind": "set_property",
            "property_id": action.effect.property_id,
            "value_parameter": action.effect.value_parameter,
        },
        "policy_requirement_ref": action.policy_requirement_ref,
    }


def _interface_snapshot(
    interface: CompiledInterfaceTypeDefinition,
) -> dict[str, JSONValue]:
    return {
        "name": interface.name,
        "properties": [
            _interface_property_snapshot(prop)
            for prop in sorted(interface.properties, key=lambda prop: prop.name)
        ],
        "description": interface.description,
    }


def _interface_property_snapshot(
    prop: CompiledPropertyDefinition,
) -> dict[str, JSONValue]:
    return {
        "name": prop.name,
        "value_type": prop.value_type.value,
        "required": prop.required,
    }


def _property_id(prop: CompiledPropertyDefinition) -> str:
    assert prop.semantic_id is not None
    return prop.semantic_id


def _property_authority_value(prop: CompiledPropertyDefinition) -> str:
    assert prop.state_authority is not None
    return prop.state_authority.value


def _object_path(semantic_id: str) -> str:
    return f"$.object_types[{stdlib_json.dumps(semantic_id, ensure_ascii=True)}]"


def _interface_path(name: str) -> str:
    return f"$.interface_types[{stdlib_json.dumps(name, ensure_ascii=True)}]"


def _property_path(object_semantic_id: str, property_semantic_id: str) -> str:
    return (
        f"{_object_path(object_semantic_id)}"
        f".properties[{stdlib_json.dumps(property_semantic_id, ensure_ascii=True)}]"
    )


def _link_path(semantic_id: str) -> str:
    return f"$.link_types[{stdlib_json.dumps(semantic_id, ensure_ascii=True)}]"


def _action_path(semantic_id: str) -> str:
    return f"$.actions[{stdlib_json.dumps(semantic_id, ensure_ascii=True)}]"


__all__ = [
    "SCHEMA_DIFF_FORMAT",
    "ChangeImpact",
    "SchemaChange",
    "SchemaDiff",
    "SchemaLineageError",
    "compare_schemas",
]
