# Resource Packs Binding

## Status

Implemented by the `harness/resource-packs` wave. Harness owns the reusable
binding of the existing resource, prompt, skill, tool-pack, and command-pack
slots. Coding declares its Product defaults and supplies its content, roots,
trust policy, and executable adapters.

## Purpose

The five capability-composition slots already describe how a Product selects
resource activation and capability-pack mechanics. This binding removes the
remaining Coding-private registry and wrapper around those neutral mechanisms
so Research, PPT, Design, Cowork, and OEM-defined Products can bind the same
runtime without copying factory or validation logic.

This is not a new resource discovery system, extension container, or global
service locator. Resource discovery, package materialization, manifest trust,
and Product content remain separate concerns.

## Standard Capability Runtime

`loushang.harness.capabilities.composition_runtime` owns one standard runtime
over the existing profile slots:

| Slot | Standard implementation | Scope | Product supplies |
| --- | --- | --- | --- |
| `resource.runtime` | `harness.resource_activation/v1` | workspace, sealed | discovered bundle and roots/loader policy |
| `prompt.sections` | `harness.prompt_sections/v1` | session | prompt section values and Product text |
| `skill.activation` | `harness.disabled_skill_activation/v1` | session | disabled-skill selectors and Product defaults |
| `tool.packs` | `harness.ordered_capability_packs/v1` | session | admitted tool packs and conflict resolver |
| `command.packs` | `harness.ordered_capability_packs/v1` | session | admitted command packs and catalog policy |

The runtime validates each implementation's strict JSON configuration and
binds it through the existing `RuntimeProfileBinder`. It exposes only neutral
operations: resource activation, disabled-skill application, prompt-section
composition, ordered tool-pack composition, ordered command-pack composition,
and disposal. It never receives Product handlers, credentials, extension
objects, roots, or UI state.

The standard `resource.runtime`, `skill.activation`, `tool.packs`, and
`command.packs` implementations use an empty configuration because their
behavior is fixed. `prompt.sections` requires exactly `separator` and
`stripSections`. Resource roots, disabled selectors, conflict policy, and the
actual pack values are Product inputs to the bound operations, not hidden
Harness configuration. The standard runtime binds one composition mechanism
per slot; multiple admitted prompt sections or content packs are passed to the
selected mechanism and retain their own provenance.

## Product Policy And Admission

A Product owns its `ProductRuntimePlan`, baseline selections, source grants,
and choice to admit OEM or extension layers. It creates Product content and
passes already admitted prompt sections or capability packs to Harness.

Coding's first adoption remains Product-only. It keeps default roots,
`DefaultResourceLoader`, built-in prompts and skills, Coding tools and
commands, extension API translation, package trust/approval, model/auth
resolution, and TUI/RPC projection. Enabling an OEM or extension selection in
Coding requires a separate Product admission policy and an implementation that
has an explicit resume contract; no settings or manifest silently gains this
authority.

## Durable And Refresh Rules

The Product persists the pure resolved capability-profile snapshot separately
from its conversation/runtime profile. The snapshot contains only the declared
variation semantic, selected implementation IDs, versions, JSON config, and
provenance.

`resource.runtime` stays sealed for the session. Prompt, skill, tool-pack, and
command-pack slots retain their declared turn refresh boundary, but a Product
must use the standard runtime binder to rebind them. Existing live values stay
valid until a successful rebind; failed rebinding leaves the prior generation
active.

## Coding Facade Removal

`coding.capability_profile` previously combined Product-plan declaration with
its own registry, factory, and wrapper mechanics. It is removed.
`coding.capability_plan` is also removed:
`harness.capabilities.standard_capability_composition_plan` owns the reusable
standard declaration, while `coding.product_plan` selects it and Coding
session/header code retains Product snapshot validation. Coding bootstrap and
`AgentSession` bind the Harness composition runtime directly.

This removal is intentionally internal. It does not remove Coding's Product
prompt, tool, command, resource, extension, or policy adapters.

## Required Verification

- a neutral Product plan binds all five standard implementations without a
  Coding import;
- strict configuration rejects unknown or malformed values;
- Product defaults preserve Coding's prompt, skill, tool-pack, and command-pack
  behavior;
- the Coding plan persists and validates a pure snapshot;
- production code no longer imports `loushang.coding.capability_profile`;
- Harness composition runtime has no Coding import.
