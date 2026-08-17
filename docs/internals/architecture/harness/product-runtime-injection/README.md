# Product Runtime Injection Architecture

## Status

The core runtime-profile contract, context-compaction binding, and standard
resource-pack binding are implemented. This directory continues to define the
requirements and component map for the remaining dynamic Product composition
capabilities; plugin-provided stores and arbitrary runtime replacement are not
implemented.

## Purpose

Products such as Coding, Design, Research, PPT, Cowork, and OEM variants need
to assemble different runtime behavior from common Harness mechanisms. A
Product supplies domain content, policy, defaults, and selection. Harness
supplies contracts, resolution mechanics, lifecycle mechanics, and diagnostics.

The target is not a service locator or a universal Product framework. It is a
bounded way to resolve declared capability selections into one observable,
session-scoped runtime configuration.

```text
Harness defaults
  -> Product runtime plan
  -> trusted OEM overrides
  -> Product-allowed extension contributions
  -> session-scoped resolved runtime snapshot
```

## Document Index

| Document | Role | Status |
| --- | --- | --- |
| [00 Requirements](00-requirements.md) | Product-facing requirements, constraints, non-goals, and acceptance criteria. | Core accepted |
| [01 Component Inventory](01-component-inventory.md) | Index of runtime-injection components, their owners, dependencies, and migration relationship. | Core implemented |
| [02 Context Compaction Binding](02-context-compaction-binding.md) | Selection, lifecycle, Product executor, and contribution contract for transcript compaction. | Implemented |
| [03 Resource Packs Binding](03-resource-packs-binding.md) | Standard runtime binding for resources, prompts, skills, tools, and commands. | Implemented |
| [Component Design Directory](components/README.md) | One detailed binding contract for each capability component. | Runtime profile implemented |

Detailed component documents are added immediately before their corresponding
implementation wave. The implemented
[runtime-profile design](components/runtime-profile-resolution.md) supplies
generic resolution and lifecycle rules so Store, Memory, Compaction, Tool Pack,
and other components do not repeat them.

## Scope

This design covers dynamic binding of Product runtime capabilities, including
durable conversation storage, transcript profiles, memory, compaction,
artifact handling, resources, prompts, skills, methods, tools, commands,
policy, approval, model selection, and presentation choices.

Multi-client channel transport, attach/replay protocol, and channel control
arbitration are intentionally outside this directory. They will be specified
under `docs/internals/architecture/channel/` after this runtime composition
contract is stable.

## Relationship To Current Migration

The current Coding-to-Harness work has already moved many mechanisms without a
single dynamic composition contract: storage protocols, transcript profiles,
context packing and compaction coordination, capabilities, resources,
extensions, policy/approval, runtime bindings, and ordered runtime events.
Coding now uses the runtime-profile core for store, transcript, compaction, and
standard resource-pack selections; other Products and injectable capability
families remain future adoption waves.

This directory is the design gate for the next ownership waves. It does not
reopen completed boundaries. Instead, it specifies how Products, OEMs, and
extensions select and bind the existing mechanisms consistently as Coding's
remaining session facade is reduced.

Every implementation wave that introduces a new injectable capability must:

1. add or accept that capability's detailed component binding document;
2. add a Product-neutral contract probe and a Coding compatibility probe;
3. update the Coding-to-Harness migration inventory with the resulting owner;
4. record whether the capability is sealed, refreshable at a turn boundary, or
   channel-local.

## Related Boundaries

- [Capability Variation And Replacement Boundary](../capability-variation-and-replacement-boundary.md)
- [Shared Capability Boundaries](../shared-capability-boundaries.md)
- [Product Runtime Core Boundary](../product-runtime-core-boundary.md)
- [Product Configuration Runtime Boundary](../product-configuration-runtime-boundary.md)
- [Context, Compaction, And Journal Foundations](../context-compaction-journal-foundations.md)
- [Store And Runtime Event Protocol Migration](../store-event-protocol-migration.md)
- [OEM And Extension Architecture](../oem-extension-architecture.md)
