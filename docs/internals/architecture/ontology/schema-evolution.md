# Ontology Schema Evolution

## Status

Accepted contract for offline comparison of two compiled Semantic Kernel
schemas. It describes compatibility; it does not mutate runtime state or data.

This contract implements the stable semantic identity decision in
[ARD-003](ARD-003-declared-state-authority-and-multi-source-materialization.md).
It covers object types, their properties, link types, and published Actions.
Interface types remain name-keyed until a separate demonstrated need extends
their identity contract; their structural properties therefore accept neither
`semantic_id` nor `state_authority` in schema v4.

## Identity and Lineage

- `package_id` identifies one schema lineage. Schemas with different package
  IDs cannot be compared.
- `namespace` belongs to that lineage; changing it is a breaking change.
- every object type, object property, link type, and Action declares an explicit
  package-local `semantic_id`;
- those IDs share one package-wide namespace and must be unique; the globally
  resolvable identity is schema `namespace` plus `semantic_id`;
- `name` remains versioned API metadata. Keeping the ID while changing the name
  produces an explicit breaking rename change;
- changing the ID means replacing semantic identity and therefore appears as
  removal plus addition. The comparator never guesses renames from shape;
- schema versions are reported in the diff but the comparator does not enforce
  SemVer or require versions to increase.

Semantic IDs use the same compact identifier grammar as other schema keys; they
are not generated UUIDs and are never derived silently from a mutable name.

## State Authority

Every object type, object property, and link type also declares exactly one
`state_authority`:

- `source-backed`: an external system owns the state;
- `ontology-owned`: Ontology owns accepted changes to the state;
- `derived`: published logic owns computation of the state.

For an object type the declaration applies to object existence; for a property
it applies to that value; for a link type it applies to the link instance
family. Reassigning authority is breaking because it changes the accepted write
contract. Schema v4 does not identify a concrete source or logic binding.
Ontology-owned `SetProperty` Actions are planned separately from the compiler;
source write routing and derivation execution remain outside this contract.

## Public Contract

```python
from loushang.ontology.schema import compare_schemas

old = compiler.load_json(old_payload)
new = compiler.load_json(new_payload)
diff = compare_schemas(old, new)
```

The pure comparison returns an immutable `SchemaDiff` containing immutable,
path-addressed `SchemaChange` records. Its JSON format identifier is
`loushang.ontology.schema-diff/v4`. Compiled schema JSON uses
`loushang.ontology.schema/v4`. Change ordering is stable by path and code;
object, property, link, and Action declaration order does not affect the result.
Object/property/link/Action paths are keyed by `semantic_id`, not display or API
name. There is no schema v3 compatibility reader.

## Impact Classes

| Impact | Meaning | Representative changes |
| --- | --- | --- |
| `NON_BREAKING` | existing consumers and instances remain valid | add object type, optional property, optional link, or Action; relax required or abstract |
| `BEHAVIORAL` | compatibility remains but presentation or runtime behavior may differ | default, index, description, icon, display name, inverse name, or temporal declaration |
| `BREAKING` | existing consumers, instances, write ownership, or graph contracts may become invalid | authority reassignment; rename or removal; Action contract change; type change; required/unique tightening; abstract tightening; interface contract, parent, endpoint, cardinality, namespace change |

Adding a required property or required link is breaking. Adding a new object
type is non-breaking even when the new type itself contains required fields,
because it does not invalidate existing object types.

`unique` is enforced during materialization and snapshot validation, so
tightening it is breaking and relaxing it is non-breaking. Required-link
tightening is breaking even though completeness is checked explicitly rather
than as a hidden single-object create gate. Adding an interface implementation
is non-breaking; removing one or changing an interface property contract is
breaking. Adding an Action is non-breaking; removing it, renaming it, or
changing its target, parameter, effect, or policy requirement is breaking.

## Determinism

The comparator:

- consumes only two `CompiledOntologySchema` values;
- performs no I/O and reads no Store or global registry;
- matches object types, object properties, link types, and Actions by stable
  semantic ID rather than name or declaration position;
- continues to compare interface contracts by name;
- compares JSON defaults canonically;
- emits detached strict-JSON `before` and `after` values;
- produces the same canonical JSON for the same two schema snapshots.

## Non-Goals

This contract does not add:

- automatic migration, backfill, or migration planning;
- `Ontology.upgrade_schema` or mutation of a bound `ObjectStore`;
- Schema Registry, filesystem persistence, or remote publishing;
- hot reload of a running ontology;
- SemVer validation or release approval policy;
- source/logic bindings, write routing, connector execution, or derivation;
- source-backed Action execution, Decision, OWL, or domain ontology behavior.
