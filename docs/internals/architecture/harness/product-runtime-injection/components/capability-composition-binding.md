# Capability Composition Binding

## Status

Implemented by the `harness/resource-packs` wave. The standard binding runtime
now lives in `loushang.harness.capabilities.composition_runtime`; Coding's
former private binding facade has been removed.

## Purpose

This component binds Product-selected resource, prompt, skill, tool, and
command capabilities into one Agent Session without making Harness a Product
or extension container. Harness owns selection shape, source admission,
ordering, lifecycle, and diagnostics. Products retain their domain content,
default selections, executable handlers, and policy.

It satisfies PDRI-001, PDRI-004, PDRI-008, PDRI-009, PDRI-010, and PDRI-011.
PDRI-013 through PDRI-015 led to the implemented graph Planner, Binder,
Runtime, and Projector owners under `loushang.harness.capabilities`; those
owners are adjacent to this facet-composition component rather than hidden
inside it.

The standard slots below are internal Binding Facets rather than one public
Capability dependency node per slot. Resource, prompt, skill, Tool-pack, and
Command-pack facets project through the top-level `harness.resources`
Capability. `interaction.side_question` is semantically a `harness.session`
facet and is now physically bound through a focused legacy Session-owned
binding rather than the resource composition runtime. See
[Capability Dependency And Mount Lifecycle](../../capability-dependency-and-mount-lifecycle.md).

## Standard Slots

| Slot | Shape / semantic / lifecycle | Sources | Meaning |
| --- | --- | --- | --- |
| `resource.runtime` | single, Exclusive Replacement, workspace, sealed | Product, OEM | Resource discovery/materialization implementation. Content may refresh; the backend cannot hot-swap inside a Session. |
| `prompt.sections` | single, Exclusive Replacement, session, turn-refreshable | Product, OEM, approved extension, session | One prepared-prompt composer; its admitted section inputs are Aggregate Contributions. |
| `skill.activation` | single, Exclusive Replacement, session, turn-refreshable | Product, OEM, approved extension, session | The policy that decides which discovered skills are active and model-visible. |
| `tool.packs` | single, Exclusive Replacement, session, turn-refreshable | Product, OEM, approved extension | One pack composer; its admitted tool-pack inputs are Aggregate Contributions. |
| `command.packs` | single, Exclusive Replacement, session, turn-refreshable | Product, OEM, approved extension | One pack composer; its admitted command-pack inputs are Aggregate Contributions. |
| `interaction.side_question` | optional single, Exclusive Replacement, session, sealed | Product, OEM, approved extension | One Session-owned side-question Provider factory. |

The selected prompt or pack composer retains its input contribution order and
owns its duplicate-name conflict rules. `tool.packs` and `command.packs`
deliberately exclude session selection because a session setting must not
acquire executable authority.

## Admission

`RuntimeProfileResolver` combines already admitted profile layers. It does not
authenticate an OEM or inspect extension permissions. Product bootstrap must
first call `RuntimeProfileAdmissionPolicy` with explicit
`RuntimeProfileLayerGrant` values. A grant is keyed by `(source, layer_id)` and
can restrict both allowed slots and granted permissions. Slot-specific
permissions are declared by the Product policy.

```text
extension manifest / OEM configuration
  -> Product trust and permission decision
  -> RuntimeProfileLayerGrant
  -> RuntimeProfileAdmissionPolicy
  -> RuntimeProfileResolver
  -> focused RuntimeProfileBinder owner
```

An unknown, untrusted, out-of-scope, or under-permissioned layer produces a
structured diagnostic and never reaches the binder. Admission is an
allow-list: it is not extension discovery, dynamic import, or a global service
locator.

## Pack Composition

After admission, `CapabilityPack` flattens live Product values in descending
priority and stable input order, retaining a provenance trace for each active
pack. It does not resolve duplicate tool or command names; the existing tool
contribution resolver and command catalog retain those capability-specific
conflict rules.

Coding binds its current Product-owned default profile through this mechanism
for the following compatibility-preserving paths:

- disabled-skill activation during bootstrap and resource refresh;
- prompt-section composition during initial assembly and tool-driven rebuilds;
- registered Coding tools before extension tool contributions, so the existing
  registry remains authoritative on duplicate tool names;
- extension command handler, built-in command handler, then resource command
  handler; the command list continues to display built-ins, extensions, then
  resource commands.

`coding.product_plan` selects
`standard_capability_composition_plan(product_id="coding")`; session headers
record its resolved snapshot under the separate `capabilityProfile` key. New
sessions and forks write that snapshot; persistent resume rejects a different
supported-profile snapshot. This is independent from `runtimeProfile`, which
continues to select the store, transcript, and context-compaction runtime.

The current Coding plan keeps Product-only selection for every standard slot
except `interaction.side_question`. An Agent Extension may declare one
side-question Provider-factory replacement through
`register_side_question_provider`; its effective Extension policy must grant
the matching `interaction.side_question` permission. Coding maps each active
Extension to one explicit profile layer and grant, runs
`RuntimeProfileAdmissionPolicy`, then resolves and binds the final Session
profile after Extension discovery. Several admitted Extension layers use the
normal source/layer/selection precedence; only the winner's factory is invoked.
Equal-priority candidates inherit the resolver's stable layer and selection
ordering, so the winner does not depend on Extension discovery order.
An unauthorized declaration fails admission before construction, and a
selected factory failure does not retry the Product baseline.
This Session-start binding path requires synchronous factory creation and
disposal; the bound Provider's question execution remains asynchronous.

Bootstrap still uses the Product baseline mechanisms while resources and
Extensions are discovered. `AgentProductConstructionBinding` then transfers
ownership to the final Session resource runtime, transfers the separately
selected side-question binding to that Session, and disposes the bootstrap
resource binding. Session shutdown joins an active side question before
disposing its selected Provider factory. The late-bound side-question choice is
auxiliary rather than continuity-critical: persisted `capabilityProfile`
metadata omits this slot, while the live selected provenance is exposed by
`session.capability_profile`.

The source-complete `harness.resources` Definition, Provider, requirements, and
focused Consumers now map the five resource facets into one
Session/bootstrap/sealed Bundle. The Provider computes a deterministic
construction fingerprint and may use a private Profile Binder, but CLA3 does
not production-mount it. Existing bootstrap/final resource composition remains
the live compatibility path until the atomic CLA4 cutover; content-only calls
do not change the prospective Mount identity.

## Accepted Incremental Finalization Target

The target Capability Plan binds the bootstrap roots' transitive dependency
closure, admits data-only Extension contributions, resolves the final internal
facets, and then reconciles the live graph by binding signature. A finalizer:

1. reuses every unchanged Mounted Capability and owned facet binding;
2. creates only final-only, new, or changed nodes;
3. rolls back newly created nodes if any dependency or factory fails or the
   transaction is cancelled;
4. publishes the new graph generation only after the delta succeeds; and
5. seals Session nodes after commit, then disposes replaced bootstrap-only
   values in reverse dependency order.

Reuse requires the complete target binding signature, including compatible
contract versions, selected factory identity/version, and an owner-supplied
deterministic fingerprint of every binding input that can alter factory output.
The current Runtime Profile snapshot alone is not that fingerprint. On failure
or cancellation, the previous published generation remains current and abort
cleanup cannot itself be skipped by a later cancellation request.

An unchanged Capability must not bind twice merely because Extension discovery
occurs between bootstrap and Session construction. Bootstrap-critical
Capabilities cannot be replaced by an Extension discovered through those same
Capabilities unless declaration-only discovery occurs before binding or a
separate explicit hot-replacement contract is accepted.

Planning, binding, live state, and projection remain separate owners. The
accepted target graph exposes coarse Capability IDs and requested facet views;
it does not expose factories, arbitrary objects, or each internal slot as a
service locator key. One aggregate Mount may hold explicit leases or stable
references to broader-lived internal facets while turn-refreshable facets keep
their own profile generations; aggregation does not force all facets into one
scope or refresh boundary.

## Durable And Refresh Rules

The resolved profile snapshot records variation semantic, implementation ID,
version, JSON configuration, and layer provenance. It never records live
factories, handler callables, credentials, or arbitrary extension objects.

`resource.runtime` is sealed for the Session. Refreshing resources must keep
the selected backend and atomically retain the last valid materialized bundle
when a later reload fails. Turn-refreshable slots can rebind only through the
runtime binder; a prior lease becomes stale after a successful rebind.

## Product Boundary

Harness provides neutral resource descriptors, prompt section composition,
tool activation, command catalog/dispatch, and this binding contract.

Coding retains:

- Coding prompt text, skill wording, and prompt preflight syntax;
- built-in coding tools and command handlers;
- Coding defaults and settings-to-selection translation;
- extension API compatibility mapping and user-facing diagnostics;
- model/auth policy, TUI/RPC presentation, and code artifact semantics.

Coding's current adoption routes resource and skill activation, prompt section
composition, and tool/command pack ordering through this contract. It must not
move model/auth execution, terminal/UI behavior, or arbitrary extension code
into Harness.

## Verification

- Harness tests cover source boundaries, untrusted layers, slot grants, and
  permission denial.
- Product tests cover the same resource bundle, prompt output, active skills,
  tool conflict result, and command conflict result before and after adoption.
- Resume tests assert the persisted continuity-critical runtime and capability
  profiles can be validated without rehydrating executable objects; the
  auxiliary side-question replacement is resolved again from active Extensions.
- Target graph tests must additionally prove bootstrap dependency closure,
  unchanged-signature reuse, failure/cancellation rollback with shielded
  cleanup, cycle/scope diagnostics, and reverse-topological disposal before
  incremental Mount finalization is marked implemented.
