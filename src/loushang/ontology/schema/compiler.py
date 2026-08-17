"""Pure compiler for versioned ontology schema drafts."""

from __future__ import annotations

import json as stdlib_json
import re
from dataclasses import dataclass, field
from typing import cast

from loushang.foundation.json import (
    JSONValue,
    JsonValueError,
    dump_json_value,
    require_json_mapping,
    require_json_value,
)
from loushang.ontology.schema.definitions import (
    ActionDefinition,
    ActionParameterDefinition,
    InterfaceTypeDefinition,
    LinkCardinality,
    LinkTypeDefinition,
    ObjectTypeDefinition,
    OntologyPackageDraft,
    PropertyDefinition,
    SchemaVersion,
    SetPropertyEffectDefinition,
    StateAuthority,
    ValueType,
)
from loushang.ontology.schema.diagnostics import (
    SchemaCompilationError,
    SchemaDiagnostic,
)

SCHEMA_FORMAT = "loushang.ontology.schema/v4"

_IDENTIFIER = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]*$")
_VERSION = re.compile(r"^[0-9]+(?:\.[0-9]+){0,2}(?:[-+][A-Za-z0-9.-]+)?$")


@dataclass(frozen=True, slots=True)
class CompiledPropertyDefinition:
    """Validated property definition with an isolated JSON default value.

    ``semantic_id`` and ``state_authority`` are required for object properties.
    They remain ``None`` only for structural interface members, whose identity
    and operational ownership are outside the implemented ARD-003 slices.
    """

    name: str
    semantic_id: str | None
    state_authority: StateAuthority | None
    value_type: ValueType
    required: bool
    unique: bool
    indexed: bool
    description: str
    _default_json: str = field(repr=False)

    @property
    def default(self) -> JSONValue:
        # Return a fresh JSON tree so callers cannot mutate the snapshot.
        return cast(JSONValue, stdlib_json.loads(self._default_json))


@dataclass(frozen=True, slots=True)
class CompiledObjectTypeDefinition:
    """Validated, immutable object-type definition."""

    name: str
    semantic_id: str
    state_authority: StateAuthority
    properties: tuple[CompiledPropertyDefinition, ...]
    parent_types: tuple[str, ...]
    interfaces: tuple[str, ...]
    abstract: bool
    icon: str | None
    description: str
    display_name_property: str | None

    def property(self, name: str) -> CompiledPropertyDefinition | None:
        return next((item for item in self.properties if item.name == name), None)

    def property_by_id(self, semantic_id: str) -> CompiledPropertyDefinition | None:
        return next(
            (item for item in self.properties if item.semantic_id == semantic_id),
            None,
        )


@dataclass(frozen=True, slots=True)
class CompiledLinkTypeDefinition:
    """Validated, immutable link-type definition."""

    name: str
    semantic_id: str
    state_authority: StateAuthority
    source_type: str
    target_type: str
    cardinality: LinkCardinality
    required: bool
    inverse_name: str | None
    temporal: bool
    description: str


@dataclass(frozen=True, slots=True)
class CompiledInterfaceTypeDefinition:
    """Validated immutable structural property contract."""

    name: str
    properties: tuple[CompiledPropertyDefinition, ...]
    description: str

    def property(self, name: str) -> CompiledPropertyDefinition | None:
        return next((item for item in self.properties if item.name == name), None)


@dataclass(frozen=True, slots=True)
class CompiledActionParameterDefinition:
    """Validated immutable Action input."""

    name: str
    value_type: ValueType
    description: str


@dataclass(frozen=True, slots=True)
class CompiledSetPropertyEffectDefinition:
    """Validated first-slice property mutation intent."""

    property_id: str
    value_parameter: str


@dataclass(frozen=True, slots=True)
class CompiledActionDefinition:
    """Validated published Action owned by one compiled Schema."""

    name: str
    semantic_id: str
    target_object_type_id: str
    parameters: tuple[CompiledActionParameterDefinition, ...]
    effect: CompiledSetPropertyEffectDefinition
    policy_requirement_ref: str
    description: str

    def parameter(self, name: str) -> CompiledActionParameterDefinition | None:
        return next((item for item in self.parameters if item.name == name), None)


@dataclass(frozen=True, slots=True)
class CompiledOntologySchema:
    """Validated immutable schema snapshot consumed by runtimes."""

    package_id: str
    namespace: str
    version: SchemaVersion
    object_types: tuple[CompiledObjectTypeDefinition, ...]
    link_types: tuple[CompiledLinkTypeDefinition, ...]
    interface_types: tuple[CompiledInterfaceTypeDefinition, ...] = ()
    actions: tuple[CompiledActionDefinition, ...] = ()
    format: str = SCHEMA_FORMAT

    def object_type(self, name: str) -> CompiledObjectTypeDefinition | None:
        return next((item for item in self.object_types if item.name == name), None)

    def object_type_by_id(
        self,
        semantic_id: str,
    ) -> CompiledObjectTypeDefinition | None:
        return next(
            (item for item in self.object_types if item.semantic_id == semantic_id),
            None,
        )

    def interface_type(self, name: str) -> CompiledInterfaceTypeDefinition | None:
        return next((item for item in self.interface_types if item.name == name), None)

    def link_type(self, name: str) -> CompiledLinkTypeDefinition | None:
        return next((item for item in self.link_types if item.name == name), None)

    def link_type_by_id(self, semantic_id: str) -> CompiledLinkTypeDefinition | None:
        return next(
            (item for item in self.link_types if item.semantic_id == semantic_id),
            None,
        )

    def action(self, name: str) -> CompiledActionDefinition | None:
        return next((item for item in self.actions if item.name == name), None)

    def action_by_id(self, semantic_id: str) -> CompiledActionDefinition | None:
        return next(
            (item for item in self.actions if item.semantic_id == semantic_id),
            None,
        )

    def to_dict(self) -> dict[str, JSONValue]:
        """Project the snapshot to its stable strict-JSON representation."""

        return {
            "format": self.format,
            "package_id": self.package_id,
            "namespace": self.namespace,
            "version": self.version.value,
            "interface_types": [
                {
                    "name": interface.name,
                    "properties": [
                        _property_document(prop, include_semantic_id=False)
                        for prop in interface.properties
                    ],
                    "description": interface.description,
                }
                for interface in self.interface_types
            ],
            "object_types": [
                {
                    "semantic_id": object_type.semantic_id,
                    "name": object_type.name,
                    "state_authority": object_type.state_authority.value,
                    "properties": [
                        _property_document(prop, include_semantic_id=True)
                        for prop in object_type.properties
                    ],
                    "parent_types": list(object_type.parent_types),
                    "interfaces": list(object_type.interfaces),
                    "abstract": object_type.abstract,
                    "icon": object_type.icon,
                    "description": object_type.description,
                    "display_name_property": object_type.display_name_property,
                }
                for object_type in self.object_types
            ],
            "link_types": [
                {
                    "semantic_id": link_type.semantic_id,
                    "name": link_type.name,
                    "state_authority": link_type.state_authority.value,
                    "source_type": link_type.source_type,
                    "target_type": link_type.target_type,
                    "cardinality": link_type.cardinality.value,
                    "required": link_type.required,
                    "inverse_name": link_type.inverse_name,
                    "temporal": link_type.temporal,
                    "description": link_type.description,
                }
                for link_type in self.link_types
            ],
            "actions": [
                {
                    "semantic_id": action.semantic_id,
                    "name": action.name,
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
                    "description": action.description,
                }
                for action in self.actions
            ],
        }

    def to_json(self) -> str:
        """Serialize to canonical compact JSON."""

        return dump_json_value(self.to_dict(), name="compiled ontology schema", sort_keys=True)


class OntologyCompiler:
    """Validate a draft and return a detached schema snapshot.

    The compiler has no registry, store, filesystem, network, or process side
    effects. A single instance is safe to reuse because it owns no state.
    """

    def validate(self, draft: OntologyPackageDraft) -> tuple[SchemaDiagnostic, ...]:
        """Return deterministic diagnostics without producing a snapshot."""

        _, diagnostics = self._compile(draft)
        return diagnostics

    def compile(self, draft: OntologyPackageDraft) -> CompiledOntologySchema:
        """Compile ``draft`` or raise all discovered structural diagnostics."""

        compiled, diagnostics = self._compile(draft)
        if diagnostics:
            raise SchemaCompilationError(diagnostics)
        assert compiled is not None
        return compiled

    def load_json(self, payload: str) -> CompiledOntologySchema:
        """Load canonical schema JSON through the same validation boundary."""

        try:
            raw = stdlib_json.loads(payload)
            document = require_json_mapping(raw, name="ontology schema")
            draft = _draft_from_document(document)
        except (JsonValueError, KeyError, TypeError, ValueError, stdlib_json.JSONDecodeError) as exc:
            raise SchemaCompilationError(
                (
                    SchemaDiagnostic(
                        code="invalid_schema_document",
                        path="$",
                        message=str(exc),
                    ),
                )
            ) from exc
        return self.compile(draft)

    def _compile(
        self,
        draft: OntologyPackageDraft,
    ) -> tuple[CompiledOntologySchema | None, tuple[SchemaDiagnostic, ...]]:
        diagnostics: list[SchemaDiagnostic] = []
        semantic_ids: dict[str, str] = {}

        _validate_identifier(draft.package_id, "$.package_id", diagnostics)
        if not isinstance(draft.namespace, str) or not draft.namespace.strip():
            diagnostics.append(
                SchemaDiagnostic("invalid_namespace", "$.namespace", "namespace must be a non-empty string")
            )

        version = draft.version
        if not isinstance(version, SchemaVersion) or not _VERSION.fullmatch(version.value):
            diagnostics.append(
                SchemaDiagnostic(
                    "invalid_schema_version",
                    "$.version",
                    "version must contain one to three numeric components",
                )
            )

        compiled_interfaces: list[CompiledInterfaceTypeDefinition] = []
        interface_names: set[str] = set()
        for interface_index, interface in enumerate(draft.interface_types):
            interface_path = f"$.interface_types[{interface_index}]"
            _validate_identifier(interface.name, f"{interface_path}.name", diagnostics)
            if interface.name in interface_names:
                diagnostics.append(
                    SchemaDiagnostic(
                        "duplicate_interface_type",
                        f"{interface_path}.name",
                        f"interface type '{interface.name}' is declared more than once",
                    )
                )
            interface_names.add(interface.name)
            compiled_interfaces.append(
                CompiledInterfaceTypeDefinition(
                    name=interface.name,
                    properties=_compile_property_definitions(
                        interface.properties,
                        path=interface_path,
                        diagnostics=diagnostics,
                        semantic_ids=None,
                    ),
                    description=interface.description,
                )
            )

        compiled_objects: list[CompiledObjectTypeDefinition] = []
        object_names: set[str] = set()
        for object_index, object_type in enumerate(draft.object_types):
            object_path = f"$.object_types[{object_index}]"
            _validate_identifier(object_type.name, f"{object_path}.name", diagnostics)
            object_semantic_id = _register_semantic_id(
                object_type.semantic_id,
                path=f"{object_path}.semantic_id",
                semantic_ids=semantic_ids,
                diagnostics=diagnostics,
            )
            object_state_authority = _compile_state_authority(
                object_type.state_authority,
                path=f"{object_path}.state_authority",
                diagnostics=diagnostics,
            )
            if object_type.name in object_names:
                diagnostics.append(
                    SchemaDiagnostic(
                        "duplicate_object_type",
                        f"{object_path}.name",
                        f"object type '{object_type.name}' is declared more than once",
                    )
                )
            object_names.add(object_type.name)

            compiled_objects.append(
                CompiledObjectTypeDefinition(
                    name=object_type.name,
                    semantic_id=object_semantic_id,
                    state_authority=object_state_authority,
                    properties=_compile_property_definitions(
                        object_type.properties,
                        path=object_path,
                        diagnostics=diagnostics,
                        semantic_ids=semantic_ids,
                    ),
                    parent_types=tuple(object_type.parent_types),
                    interfaces=tuple(sorted(object_type.interfaces)),
                    abstract=object_type.abstract,
                    icon=object_type.icon,
                    description=object_type.description,
                    display_name_property=object_type.display_name_property,
                )
            )

        for object_index, object_type in enumerate(draft.object_types):
            for parent_index, parent_name in enumerate(object_type.parent_types):
                if parent_name not in object_names:
                    diagnostics.append(
                        SchemaDiagnostic(
                            "unknown_parent_type",
                            f"$.object_types[{object_index}].parent_types[{parent_index}]",
                            f"parent object type '{parent_name}' is not declared",
                        )
                    )

        _validate_parent_cycles(draft.object_types, diagnostics)
        _validate_interface_implementations(
            draft.object_types,
            compiled_objects,
            compiled_interfaces,
            diagnostics,
        )

        compiled_links: list[CompiledLinkTypeDefinition] = []
        link_names: set[str] = set()
        for link_index, link_type in enumerate(draft.link_types):
            link_path = f"$.link_types[{link_index}]"
            _validate_identifier(link_type.name, f"{link_path}.name", diagnostics)
            link_semantic_id = _register_semantic_id(
                link_type.semantic_id,
                path=f"{link_path}.semantic_id",
                semantic_ids=semantic_ids,
                diagnostics=diagnostics,
            )
            link_state_authority = _compile_state_authority(
                link_type.state_authority,
                path=f"{link_path}.state_authority",
                diagnostics=diagnostics,
            )
            if link_type.name in link_names:
                diagnostics.append(
                    SchemaDiagnostic(
                        "duplicate_link_type",
                        f"{link_path}.name",
                        f"link type '{link_type.name}' is declared more than once",
                    )
                )
            link_names.add(link_type.name)

            for endpoint, endpoint_name in (
                ("source_type", link_type.source_type),
                ("target_type", link_type.target_type),
            ):
                if endpoint_name not in object_names:
                    diagnostics.append(
                        SchemaDiagnostic(
                            "unknown_link_endpoint",
                            f"{link_path}.{endpoint}",
                            f"object type '{endpoint_name}' is not declared",
                        )
                    )

            cardinality = _normalize_cardinality(link_type.cardinality)
            if cardinality is None:
                diagnostics.append(
                    SchemaDiagnostic(
                        "invalid_cardinality",
                        f"{link_path}.cardinality",
                        f"unsupported cardinality '{_value_label(link_type.cardinality)}'",
                    )
                )
            else:
                compiled_links.append(
                    CompiledLinkTypeDefinition(
                        name=link_type.name,
                        semantic_id=link_semantic_id,
                        state_authority=link_state_authority,
                        source_type=link_type.source_type,
                        target_type=link_type.target_type,
                        cardinality=cardinality,
                        required=link_type.required,
                        inverse_name=link_type.inverse_name,
                        temporal=link_type.temporal,
                        description=link_type.description,
                    )
                )

        compiled_actions = _compile_action_definitions(
            draft.actions,
            compiled_objects=compiled_objects,
            semantic_ids=semantic_ids,
            diagnostics=diagnostics,
        )

        if diagnostics:
            return None, tuple(diagnostics)

        assert isinstance(version, SchemaVersion)
        return (
            CompiledOntologySchema(
                package_id=draft.package_id,
                namespace=draft.namespace,
                version=version,
                interface_types=tuple(
                    sorted(compiled_interfaces, key=lambda item: item.name)
                ),
                object_types=tuple(
                    sorted(compiled_objects, key=lambda item: item.semantic_id)
                ),
                link_types=tuple(
                    sorted(compiled_links, key=lambda item: item.semantic_id)
                ),
                actions=tuple(
                    sorted(compiled_actions, key=lambda item: item.semantic_id)
                ),
            ),
            (),
        )


def _validate_identifier(
    value: object,
    path: str,
    diagnostics: list[SchemaDiagnostic],
) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        diagnostics.append(
            SchemaDiagnostic(
                "invalid_identifier",
                path,
                "identifier must start with a letter and contain only letters, digits, '.', '_' or '-'",
            )
        )


def _register_semantic_id(
    value: object,
    *,
    path: str,
    semantic_ids: dict[str, str],
    diagnostics: list[SchemaDiagnostic],
) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        diagnostics.append(
            SchemaDiagnostic(
                "invalid_semantic_id",
                path,
                "semantic_id must be an explicit package-local identifier",
            )
        )
        return ""
    previous_path = semantic_ids.get(value)
    if previous_path is not None:
        diagnostics.append(
            SchemaDiagnostic(
                "duplicate_semantic_id",
                path,
                f"semantic_id '{value}' is already declared at {previous_path}",
            )
        )
    else:
        semantic_ids[value] = path
    return value


def _validate_parent_cycles(
    object_types: tuple[ObjectTypeDefinition, ...] | list[ObjectTypeDefinition],
    diagnostics: list[SchemaDiagnostic],
) -> None:
    by_name = {object_type.name: object_type for object_type in object_types}
    object_indexes = {object_type.name: index for index, object_type in enumerate(object_types)}
    state: dict[str, int] = {}
    stack: list[str] = []
    reported_cycles: set[frozenset[str]] = set()

    def visit(name: str) -> None:
        state[name] = 1
        stack.append(name)
        object_type = by_name[name]
        for parent_index, parent_name in enumerate(object_type.parent_types):
            if parent_name not in by_name:
                continue
            if state.get(parent_name, 0) == 0:
                visit(parent_name)
                continue
            if state.get(parent_name) != 1:
                continue

            cycle_start = stack.index(parent_name)
            cycle = stack[cycle_start:] + [parent_name]
            cycle_key = frozenset(cycle)
            if cycle_key in reported_cycles:
                continue
            reported_cycles.add(cycle_key)
            diagnostics.append(
                SchemaDiagnostic(
                    "parent_type_cycle",
                    (
                        f"$.object_types[{object_indexes[name]}]"
                        f".parent_types[{parent_index}]"
                    ),
                    f"parent type cycle detected: {' -> '.join(cycle)}",
                )
            )
        stack.pop()
        state[name] = 2

    for object_type in object_types:
        if state.get(object_type.name, 0) == 0:
            visit(object_type.name)


def _normalize_value_type(value: object) -> ValueType | None:
    if isinstance(value, ValueType):
        return value
    if isinstance(value, str):
        try:
            return ValueType(value)
        except ValueError:
            return None
    return None


def _normalize_state_authority(value: object) -> StateAuthority | None:
    if isinstance(value, StateAuthority):
        return value
    if isinstance(value, str):
        try:
            return StateAuthority(value)
        except ValueError:
            return None
    return None


def _compile_state_authority(
    value: object,
    *,
    path: str,
    diagnostics: list[SchemaDiagnostic],
) -> StateAuthority:
    authority = _normalize_state_authority(value)
    if authority is None:
        diagnostics.append(
            SchemaDiagnostic(
                "invalid_state_authority",
                path,
                "state_authority must be 'source-backed', 'ontology-owned', or 'derived'",
            )
        )
        # The compiled value is discarded whenever diagnostics exist.
        return StateAuthority.ONTOLOGY_OWNED
    return authority


def _compile_property_definitions(
    properties: tuple[PropertyDefinition, ...] | list[PropertyDefinition],
    *,
    path: str,
    diagnostics: list[SchemaDiagnostic],
    semantic_ids: dict[str, str] | None,
) -> tuple[CompiledPropertyDefinition, ...]:
    compiled: list[CompiledPropertyDefinition] = []
    names: set[str] = set()
    for property_index, prop in enumerate(properties):
        property_path = f"{path}.properties[{property_index}]"
        _validate_identifier(prop.name, f"{property_path}.name", diagnostics)
        semantic_id = None
        state_authority = None
        if semantic_ids is None:
            if prop.semantic_id is not None:
                diagnostics.append(
                    SchemaDiagnostic(
                        "interface_property_semantic_id_unsupported",
                        f"{property_path}.semantic_id",
                        "interface property identity is not part of schema v4",
                    )
                )
            if prop.state_authority is not None:
                diagnostics.append(
                    SchemaDiagnostic(
                        "interface_property_state_authority_unsupported",
                        f"{property_path}.state_authority",
                        "interface property authority is not part of schema v4",
                    )
                )
        else:
            semantic_id = _register_semantic_id(
                prop.semantic_id,
                path=f"{property_path}.semantic_id",
                semantic_ids=semantic_ids,
                diagnostics=diagnostics,
            )
            state_authority = _compile_state_authority(
                prop.state_authority,
                path=f"{property_path}.state_authority",
                diagnostics=diagnostics,
            )
        if prop.name in names:
            diagnostics.append(
                SchemaDiagnostic(
                    "duplicate_property",
                    f"{property_path}.name",
                    f"property '{prop.name}' is declared more than once",
                )
            )
        names.add(prop.name)
        value_type = _normalize_value_type(prop.value_type)
        if value_type is None:
            diagnostics.append(
                SchemaDiagnostic(
                    "unsupported_value_type",
                    f"{property_path}.value_type",
                    f"unsupported value type '{_value_label(prop.value_type)}'",
                )
            )
        default_json: str | None = None
        try:
            default_value = require_json_value(prop.default, name=f"{property_path}.default")
            default_json = dump_json_value(default_value, sort_keys=True)
        except JsonValueError as exc:
            diagnostics.append(
                SchemaDiagnostic("invalid_default", f"{property_path}.default", str(exc))
            )
        if value_type is not None and default_json is not None:
            compiled.append(
                CompiledPropertyDefinition(
                    name=prop.name,
                    semantic_id=semantic_id,
                    state_authority=state_authority,
                    value_type=value_type,
                    required=prop.required,
                    unique=prop.unique,
                    indexed=prop.indexed,
                    description=prop.description,
                    _default_json=default_json,
                )
            )
    return tuple(
        sorted(
            compiled,
            key=lambda item: item.name if item.semantic_id is None else item.semantic_id,
        )
    )


def _validate_interface_implementations(
    drafts: tuple[ObjectTypeDefinition, ...] | list[ObjectTypeDefinition],
    compiled_objects: list[CompiledObjectTypeDefinition],
    compiled_interfaces: list[CompiledInterfaceTypeDefinition],
    diagnostics: list[SchemaDiagnostic],
) -> None:
    objects = {item.name: item for item in compiled_objects}
    interfaces = {item.name: item for item in compiled_interfaces}

    def resolved_properties(name: str, visiting: set[str]) -> dict[str, CompiledPropertyDefinition]:
        if name in visiting or name not in objects:
            return {}
        visiting.add(name)
        object_type = objects[name]
        resolved: dict[str, CompiledPropertyDefinition] = {}
        for parent_name in object_type.parent_types:
            resolved.update(resolved_properties(parent_name, visiting))
        visiting.remove(name)
        resolved.update({prop.name: prop for prop in object_type.properties})
        return resolved

    for object_index, draft in enumerate(drafts):
        properties = resolved_properties(draft.name, set())
        seen: set[str] = set()
        for interface_index, interface_name in enumerate(draft.interfaces):
            path = f"$.object_types[{object_index}].interfaces[{interface_index}]"
            if interface_name in seen:
                diagnostics.append(
                    SchemaDiagnostic(
                        "duplicate_interface_implementation",
                        path,
                        f"interface '{interface_name}' is implemented more than once",
                    )
                )
                continue
            seen.add(interface_name)
            interface = interfaces.get(interface_name)
            if interface is None:
                diagnostics.append(
                    SchemaDiagnostic(
                        "unknown_interface",
                        path,
                        f"interface '{interface_name}' is not declared",
                    )
                )
                continue
            for interface_property in interface.properties:
                implementation = properties.get(interface_property.name)
                property_path = f"{path}.properties.{interface_property.name}"
                if implementation is None:
                    diagnostics.append(
                        SchemaDiagnostic(
                            "interface_property_missing",
                            property_path,
                            f"object type '{draft.name}' does not implement property "
                            f"'{interface_property.name}'",
                        )
                    )
                elif implementation.value_type is not interface_property.value_type:
                    diagnostics.append(
                        SchemaDiagnostic(
                            "interface_property_type_mismatch",
                            property_path,
                            f"property '{draft.name}.{interface_property.name}' has an "
                            "incompatible value type",
                        )
                    )
                elif interface_property.required and not implementation.required:
                    diagnostics.append(
                        SchemaDiagnostic(
                            "interface_property_requiredness_mismatch",
                            property_path,
                            f"property '{draft.name}.{interface_property.name}' must be required",
                        )
                    )


def _compile_action_definitions(
    actions: tuple[ActionDefinition, ...] | list[ActionDefinition],
    *,
    compiled_objects: list[CompiledObjectTypeDefinition],
    semantic_ids: dict[str, str],
    diagnostics: list[SchemaDiagnostic],
) -> tuple[CompiledActionDefinition, ...]:
    compiled: list[CompiledActionDefinition] = []
    action_names: set[str] = set()
    objects_by_id = {item.semantic_id: item for item in compiled_objects}
    objects_by_name = {item.name: item for item in compiled_objects}

    for action_index, action in enumerate(actions):
        action_path = f"$.actions[{action_index}]"
        _validate_identifier(action.name, f"{action_path}.name", diagnostics)
        semantic_id = _register_semantic_id(
            action.semantic_id,
            path=f"{action_path}.semantic_id",
            semantic_ids=semantic_ids,
            diagnostics=diagnostics,
        )
        if action.name in action_names:
            diagnostics.append(
                SchemaDiagnostic(
                    "duplicate_action",
                    f"{action_path}.name",
                    f"action '{action.name}' is declared more than once",
                )
            )
        action_names.add(action.name)

        parameters: list[CompiledActionParameterDefinition] = []
        parameter_names: set[str] = set()
        for parameter_index, parameter in enumerate(action.parameters):
            parameter_path = f"{action_path}.parameters[{parameter_index}]"
            if not isinstance(parameter, ActionParameterDefinition):
                diagnostics.append(
                    SchemaDiagnostic(
                        "invalid_action_parameter",
                        parameter_path,
                        "action parameters must be ActionParameterDefinition values",
                    )
                )
                continue
            _validate_identifier(
                parameter.name,
                f"{parameter_path}.name",
                diagnostics,
            )
            if parameter.name in parameter_names:
                diagnostics.append(
                    SchemaDiagnostic(
                        "duplicate_action_parameter",
                        f"{parameter_path}.name",
                        f"action parameter '{parameter.name}' is declared more than once",
                    )
                )
            parameter_names.add(parameter.name)
            value_type = _normalize_value_type(parameter.value_type)
            if value_type is None:
                diagnostics.append(
                    SchemaDiagnostic(
                        "unsupported_action_parameter_type",
                        f"{parameter_path}.value_type",
                        f"unsupported value type '{_value_label(parameter.value_type)}'",
                    )
                )
                continue
            parameters.append(
                CompiledActionParameterDefinition(
                    name=parameter.name,
                    value_type=value_type,
                    description=parameter.description,
                )
            )
        if len(action.parameters) != 1:
            diagnostics.append(
                SchemaDiagnostic(
                    "unsupported_action_parameter_shape",
                    f"{action_path}.parameters",
                    "the first Action format requires exactly one value parameter",
                )
            )

        target = (
            objects_by_id.get(action.target_object_type_id)
            if isinstance(action.target_object_type_id, str)
            else None
        )
        if target is None:
            diagnostics.append(
                SchemaDiagnostic(
                    "unknown_action_target_type",
                    f"{action_path}.target_object_type_id",
                    "action target_object_type_id is not declared",
                )
            )
        elif target.abstract:
            diagnostics.append(
                SchemaDiagnostic(
                    "abstract_action_target_type",
                    f"{action_path}.target_object_type_id",
                    "the first Action format cannot target an abstract object type",
                )
            )

        effect = action.effect
        if not isinstance(effect, SetPropertyEffectDefinition):
            diagnostics.append(
                SchemaDiagnostic(
                    "unsupported_action_effect",
                    f"{action_path}.effect",
                    "the first Action format supports only SetProperty",
                )
            )
            compiled_effect = CompiledSetPropertyEffectDefinition("", "")
        else:
            compiled_effect = CompiledSetPropertyEffectDefinition(
                property_id=effect.property_id,
                value_parameter=effect.value_parameter,
            )
            target_property = (
                None
                if target is None
                else _resolved_property_by_id(
                    target,
                    effect.property_id,
                    objects_by_name,
                )
            )
            if target is not None and target_property is None:
                diagnostics.append(
                    SchemaDiagnostic(
                        "unknown_action_property",
                        f"{action_path}.effect.property_id",
                        "SetProperty target is not declared on the Action object type",
                    )
                )
            value_parameter = next(
                (item for item in parameters if item.name == effect.value_parameter),
                None,
            )
            if value_parameter is None:
                diagnostics.append(
                    SchemaDiagnostic(
                        "unknown_action_value_parameter",
                        f"{action_path}.effect.value_parameter",
                        "SetProperty value_parameter is not declared",
                    )
                )
            elif (
                target_property is not None
                and value_parameter.value_type is not target_property.value_type
            ):
                diagnostics.append(
                    SchemaDiagnostic(
                        "action_parameter_type_mismatch",
                        f"{action_path}.effect.value_parameter",
                        "Action parameter type does not match the target property",
                    )
                )

        if (
            not isinstance(action.policy_requirement_ref, str)
            or not action.policy_requirement_ref.strip()
        ):
            diagnostics.append(
                SchemaDiagnostic(
                    "invalid_action_policy_requirement",
                    f"{action_path}.policy_requirement_ref",
                    "policy_requirement_ref must be a non-empty opaque reference",
                )
            )

        compiled.append(
            CompiledActionDefinition(
                name=action.name,
                semantic_id=semantic_id,
                target_object_type_id=(
                    action.target_object_type_id
                    if isinstance(action.target_object_type_id, str)
                    else ""
                ),
                parameters=tuple(sorted(parameters, key=lambda item: item.name)),
                effect=compiled_effect,
                policy_requirement_ref=(
                    action.policy_requirement_ref
                    if isinstance(action.policy_requirement_ref, str)
                    else ""
                ),
                description=action.description,
            )
        )

    return tuple(compiled)


def _resolved_property_by_id(
    object_type: CompiledObjectTypeDefinition,
    property_id: object,
    objects_by_name: dict[str, CompiledObjectTypeDefinition],
) -> CompiledPropertyDefinition | None:
    if not isinstance(property_id, str):
        return None
    direct = object_type.property_by_id(property_id)
    if direct is not None:
        return direct
    for parent_name in object_type.parent_types:
        parent = objects_by_name.get(parent_name)
        if parent is None:
            continue
        inherited = _resolved_property_by_id(parent, property_id, objects_by_name)
        if inherited is not None:
            return inherited
    return None


def _normalize_cardinality(value: object) -> LinkCardinality | None:
    if isinstance(value, LinkCardinality):
        return value
    if isinstance(value, str):
        try:
            return LinkCardinality(value)
        except ValueError:
            return None
    return None


def _value_label(value: object) -> str:
    if isinstance(value, type):
        return value.__name__
    return str(value)


def _draft_from_document(document: dict[str, JSONValue]) -> OntologyPackageDraft:
    if document.get("format") != SCHEMA_FORMAT:
        raise ValueError(f"format must be '{SCHEMA_FORMAT}'")

    interface_values = _optional_list(document, "interface_types")
    object_values = _require_list(document, "object_types")
    link_values = _require_list(document, "link_types")
    action_values = _require_list(document, "actions")
    interface_types = [_interface_from_value(value) for value in interface_values]
    object_types = [_object_from_value(value) for value in object_values]
    link_types = [_link_from_value(value) for value in link_values]
    actions = [_action_from_value(value) for value in action_values]

    return OntologyPackageDraft(
        package_id=_require_string(document, "package_id"),
        namespace=_require_string(document, "namespace"),
        version=_require_string(document, "version"),
        interface_types=interface_types,
        object_types=object_types,
        link_types=link_types,
        actions=actions,
    )


def _object_from_value(value: JSONValue) -> ObjectTypeDefinition:
    document = require_json_mapping(value, name="object type")
    properties = [
        _property_from_value(item, require_semantic_id=True)
        for item in _require_list(document, "properties")
    ]
    parents = _require_list(document, "parent_types")
    interfaces = _optional_list(document, "interfaces")
    if not all(isinstance(item, str) for item in parents):
        raise TypeError("parent_types must contain only strings")
    if not all(isinstance(item, str) for item in interfaces):
        raise TypeError("interfaces must contain only strings")
    return ObjectTypeDefinition(
        name=_require_string(document, "name"),
        semantic_id=_require_string(document, "semantic_id"),
        state_authority=_require_string(document, "state_authority"),
        properties=properties,
        parent_types=cast(list[str], parents),
        interfaces=cast(list[str], interfaces),
        abstract=_require_bool(document, "abstract"),
        icon=_require_optional_string(document, "icon"),
        description=_require_string(document, "description"),
        display_name_property=_require_optional_string(document, "display_name_property"),
    )


def _interface_from_value(value: JSONValue) -> InterfaceTypeDefinition:
    document = require_json_mapping(value, name="interface type")
    return InterfaceTypeDefinition(
        name=_require_string(document, "name"),
        properties=[
            _property_from_value(item) for item in _require_list(document, "properties")
        ],
        description=_require_string(document, "description"),
    )


def _property_from_value(
    value: JSONValue,
    *,
    require_semantic_id: bool = False,
) -> PropertyDefinition:
    document = require_json_mapping(value, name="property")
    return PropertyDefinition(
        name=_require_string(document, "name"),
        value_type=_require_string(document, "value_type"),
        semantic_id=(
            _require_string(document, "semantic_id")
            if require_semantic_id
            else None
        ),
        state_authority=(
            _require_string(document, "state_authority")
            if require_semantic_id
            else None
        ),
        required=_require_bool(document, "required"),
        unique=_require_bool(document, "unique"),
        indexed=_require_bool(document, "indexed"),
        default=document["default"],
        description=_require_string(document, "description"),
    )


def _link_from_value(value: JSONValue) -> LinkTypeDefinition:
    document = require_json_mapping(value, name="link type")
    return LinkTypeDefinition(
        name=_require_string(document, "name"),
        source_type=_require_string(document, "source_type"),
        target_type=_require_string(document, "target_type"),
        semantic_id=_require_string(document, "semantic_id"),
        state_authority=_require_string(document, "state_authority"),
        cardinality=_require_string(document, "cardinality"),
        required=_require_bool(document, "required"),
        inverse_name=_require_optional_string(document, "inverse_name"),
        temporal=_require_bool(document, "temporal"),
        description=_require_string(document, "description"),
    )


def _action_from_value(value: JSONValue) -> ActionDefinition:
    document = require_json_mapping(value, name="action")
    raw_parameters = _require_list(document, "parameters")
    effect_document = require_json_mapping(document["effect"], name="action effect")
    if _require_string(effect_document, "kind") != "set_property":
        raise ValueError("action effect kind must be 'set_property'")
    return ActionDefinition(
        name=_require_string(document, "name"),
        semantic_id=_require_string(document, "semantic_id"),
        target_object_type_id=_require_string(
            document,
            "target_object_type_id",
        ),
        parameters=[_action_parameter_from_value(item) for item in raw_parameters],
        effect=SetPropertyEffectDefinition(
            property_id=_require_string(effect_document, "property_id"),
            value_parameter=_require_string(effect_document, "value_parameter"),
        ),
        policy_requirement_ref=_require_string(
            document,
            "policy_requirement_ref",
        ),
        description=_require_string(document, "description"),
    )


def _action_parameter_from_value(value: JSONValue) -> ActionParameterDefinition:
    document = require_json_mapping(value, name="action parameter")
    return ActionParameterDefinition(
        name=_require_string(document, "name"),
        value_type=_require_string(document, "value_type"),
        description=_require_string(document, "description"),
    )


def _require_list(document: dict[str, JSONValue], key: str) -> list[JSONValue]:
    value = document[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be an array")
    return value


def _optional_list(document: dict[str, JSONValue], key: str) -> list[JSONValue]:
    value = document.get(key, [])
    if not isinstance(value, list):
        raise TypeError(f"{key} must be an array")
    return value


def _property_document(
    prop: CompiledPropertyDefinition,
    *,
    include_semantic_id: bool,
) -> dict[str, JSONValue]:
    document: dict[str, JSONValue] = {
        "name": prop.name,
        "value_type": prop.value_type.value,
        "required": prop.required,
        "unique": prop.unique,
        "indexed": prop.indexed,
        "default": prop.default,
        "description": prop.description,
    }
    if include_semantic_id:
        assert prop.semantic_id is not None
        assert prop.state_authority is not None
        document["semantic_id"] = prop.semantic_id
        document["state_authority"] = prop.state_authority.value
    return document


def _require_string(document: dict[str, JSONValue], key: str) -> str:
    value = document[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value


def _require_optional_string(document: dict[str, JSONValue], key: str) -> str | None:
    value = document[key]
    if value is not None and not isinstance(value, str):
        raise TypeError(f"{key} must be a string or null")
    return value


def _require_bool(document: dict[str, JSONValue], key: str) -> bool:
    value = document[key]
    if type(value) is not bool:
        raise TypeError(f"{key} must be a boolean")
    return cast(bool, value)


__all__ = [
    "CompiledActionDefinition",
    "CompiledActionParameterDefinition",
    "CompiledInterfaceTypeDefinition",
    "CompiledLinkTypeDefinition",
    "CompiledObjectTypeDefinition",
    "CompiledOntologySchema",
    "CompiledPropertyDefinition",
    "CompiledSetPropertyEffectDefinition",
    "OntologyCompiler",
    "SCHEMA_FORMAT",
]
