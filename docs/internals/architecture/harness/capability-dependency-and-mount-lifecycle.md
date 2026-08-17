# Capability Dependency And Mount Lifecycle

## Status

Implemented Mount-runtime boundary with staged rollout. The Definition,
Requirement, Bundle Provider, pure Planner, transactional Binder, live Runtime,
and read-only Projector described here are implemented. The generated
[Harness Capability Catalog](capability-catalog.md) is the source-backed record
of complete Definition / Provider / Consumer seams. `harness.workspace` is the
first accepted top-level Bundle in that catalog; `harness.resources`,
`harness.session`, `coding.lsp`, and `coding.arch` remain rollout targets rather
than claimed runtime nodes. Runtime Profile slots remain the implemented finer
binding layer inside those future Bundles.

Canonical Product, Capability, Mount, Package, Plugin, and Extension terms are
defined in the
[Product And OEM Glossary](../../glossary/loushang-product.md). Executable
provider composition semantics remain defined by the
[Capability Variation And Replacement Boundary](capability-variation-and-replacement-boundary.md).
This document is the authority for top-level Capability dependency direction,
Mount identity and lifecycle, graph diagnostics, and management ownership.

## Decision

Loushang separates four concepts that must not be collapsed into one registry
or graph node:

| Concept | Meaning |
| --- | --- |
| Capability ID | Stable owner-qualified identity such as `harness.workspace` or `coding.lsp`. |
| Capability Bundle | The owner-composed runtime, tools, resources, and private binding facets that implement one Capability. |
| Mount Policy | Product policy such as `disabled`, `on_demand`, or `always` that decides when a Capability is requested. |
| Mounted Capability | One admitted Capability Bundle bound to a concrete process, tenant, workspace, Session, turn, or Channel scope. |

`coding.lsp` is therefore a Capability ID, not a Mount instance. A live node may
be identified as `coding.lsp@workspace:<workspace-id>`. Architecture documents
may call a Capability ID *mountable* when a Product exposes Mount Policy for it,
but must not call the ID itself a "Mount identity".

## Two Graph Views

The static plan and the live runtime have related but different nodes:

```text
Capability Plan DAG                 Live Mount Graph

coding.lsp                          coding.lsp@session:session-42
  -> harness.workspace                -> harness.workspace@workspace:repo-123
```

- A **Capability Plan DAG** node is a Capability ID plus its owner, declared
  scope, versioned dependency requirements, activation policy, and allowed
  variation.
- A **Live Mount Graph** node is a Mounted Capability plus its selected Bundle,
  scope instance, generation, lifecycle state, and binding signature.
- `A -> B` always means **A depends on B**. Binding proceeds against the arrow;
  disposal proceeds with the arrow.

Product, OEM, Plugin, Package, and Extension identities are not graph nodes.
They remain graph ownership, selection-source, provenance, delivery, and
admission facts. Losing or rejected provider candidates belong in a resolution
trace, not in the final dependency graph.

## Node Granularity

The top-level graph records owner-level runtime capabilities, not every method,
tool, provider, or internal service. A Capability is suitable for a top-level
node when it has a stable contract, an independent activation or binding
lifecycle, an owner that can explain its state, and meaningful dependency or
variation semantics.

The accepted target top-level Harness Capability IDs are:

| Capability ID | Bundle boundary | Representative internal facets |
| --- | --- | --- |
| `harness.workspace` | Product-neutral workspace access and authorized execution | read, list, search, write, edit, authorized process launch |
| `harness.resources` | Resource discovery, activation, and capability-item composition | resource runtime, prompt sections, skill activation, tool packs, command packs |
| `harness.session` | Product-neutral Session, transcript, context, interaction, and continuity mechanics | conversation store, transcript profile, compaction, side question, continuity providers |

This is the accepted top-level Capability budget, not a claim that every row is
already source-backed and not a prohibition on focused Harness modules. The
generated Capability catalog records current role-complete seams. A fourth
top-level Harness Capability requires an independently owned lifecycle and a
demonstrated need that cannot be expressed as a facet or contribution of an
existing Capability.

The accepted target Coding-specific mountable Capability IDs, already
represented by current Coding constants, are:

| Capability ID | Bundle boundary |
| --- | --- |
| `coding.lsp` | Language-server declaration admission, selection, document synchronization, lifecycle, semantic queries, diagnostics, and tools |
| `coding.arch` | Repository architecture analyzers, import-graph facts, architecture queries, diagnostics, and tools |

LSP supervisors, documents, diagnostic inboxes, individual analyzers, Tool
definitions, `interaction.side_question`, and `prompt.sections` do not become
top-level nodes merely because they have focused implementation owners. They
remain Bundle internals or Runtime Profile binding facets unless a later
decision proves an independent public lifecycle.

## Dependencies And Facet Views

Dependencies use stable Capability IDs. Terms such as `port`, `adapter`,
`provider`, and `factory` describe implementation wiring and must not appear as
public dependency identities.

```text
                                     # accepted target Harness composition
harness.session -> harness.resources
harness.session -> harness.workspace

coding.lsp  -> harness.workspace
coding.arch -> harness.workspace
coding.arch -. optional .-> coding.lsp
```

`harness.session` consumes the admitted resource composition and workspace
facets used by the Session runtime, so both Harness edges are required in the
accepted target plan. Current Session assembly wires the not-yet-migrated
Bundle dependencies directly until their complete seams enter the implemented
Planner and Binder.

The optional `coding.arch -> coding.lsp` edge is a permitted future shape, not
part of the initial target. `coding.arch` must remain independently usable
unless a later accepted Product decision changes that contract.

Coarse graph identity does not grant coarse authority. A consumer declares a
narrow facet view separately:

```text
CapabilityRequirement(
    capability="harness.workspace",
    facets=("read", "process.launch"),
    compatible_contract="1.x",
)
```

Every Capability and exported facet view has an owner-versioned contract. A
dependency requirement declares a compatible contract version or range; the
planner rejects an incompatible requirement before construction. An
implementation version identifies a selected provider and does not substitute
for the dependency contract version.

Facets constrain admission and typed injection but do not create more DAG
nodes. The same distinction applies to requirements:

| Requirement kind | DAG edge? | Example |
| --- | --- | --- |
| Managed Capability dependency | Yes | `coding.lsp -> harness.workspace` |
| Narrow injected interface | No | workspace reader or authorized launcher Protocol |
| Permission or authority | No | `filesystem`, `model`, `network` |
| Configuration or scope value | No | cwd, Session id, model selection |
| Aggregate contribution | No | Tool, Command, analyzer, Server definition |

Harness authorization, approval coordination, Sandbox enforcement, limits,
audit, and cleanup remain non-bypassable internals of the applicable Harness
Capability. They are not externally replaceable graph nodes merely to make the
graph visually complete.

## Internal Binding Facets

A Capability Bundle may own private binding facets with more detailed shape,
scope, and refresh semantics. The current `RuntimeCapabilitySlot` inventory is
such a binding mechanism. For example:

```text
harness.resources
  resource.runtime
  prompt.sections
  skill.activation
  tool.packs
  command.packs

harness.session
  conversation.store
  agent.transcript_profile
  context.compaction
  interaction.side_question
  continuity.provider_packs
```

These facets may retain Runtime Profile snapshots and focused diagnostics. They
do not expand the accepted target Capability DAG, and an Extension that
contributes a side-question provider does not become a node. The owning Bundle
admits and resolves that candidate, then projects one aggregate node state
upward.

The top-level Mount scope and generation describe the owner-visible Bundle
binding, not a forced common lifecycle for every private facet. A Session-
scoped `harness.resources` Bundle may hold a lease to its workspace-scoped,
sealed `resource.runtime` facet while its prompt, skill, Tool-pack, and
Command-pack facets remain Session-scoped and turn-refreshable. Likewise,
`harness.session` may consume process-scoped continuity packs through stable
references or leases. The Bundle must not capture a shorter-lived concrete
facet value across its safe boundary.

Facet snapshots and generations remain authoritative for their focused
selection and refresh state. The aggregate Mount generation changes only when
the public Bundle binding signature changes; an internal turn refresh is
projected as facet state and does not invent another top-level node or silently
replace the Mounted Capability.

## Planning And Binding Lifecycle

The target composition lifecycle is:

```text
declare Capability Plan
  -> validate dependencies and authority ceilings
  -> bind bootstrap dependency closure
  -> discover data-only Extension contributions
  -> admit and resolve the final plan and internal facets
  -> reconcile by binding signature
  -> bind only new or changed final nodes
  -> commit and seal the live Mount Graph
```

Bootstrap roots bind their transitive dependency closure rather than a
hand-maintained list. Finalization reuses an existing node only when Capability
ID, scope instance, selected implementation/configuration, dependency
requirements, compatible contract versions, selected factory identity/version,
relevant provenance, and an owner-supplied binding-input fingerprint form the
same binding signature.

The binding-input fingerprint is strict deterministic data covering every
factory input that can alter the live value, such as persistence mode, Session
directory identity, workspace identity, or a stable referenced-runtime
generation. It excludes credentials and arbitrary live objects. A Capability
whose owner cannot provide a complete stable fingerprint is not eligible for
signature reuse.

An unchanged Capability must not be constructed twice merely because Extension
discovery occurs between bootstrap and Session creation. A final-only
Capability is not constructed until final resolution. If an Extension attempts
to replace a Capability already required to discover that Extension, the owner
must either use declaration-only discovery before binding, classify that
Capability as non-Extension-replaceable bootstrap infrastructure, or define a
separate explicit hot-replacement contract. Incidental double construction is
not a valid resolution policy.

Finalization is a construction transaction, not a turn-boundary rebind. It
creates the delta before publishing the new graph, rolls back newly created
nodes on failure or cancellation, and seals Session-scoped nodes only after
commit. Cancellation before commit is a transactional abort: the previously
published generation remains authoritative and the newly created delta is
reverse-disposed. Once rollback begins, cleanup runs to completion under a
cleanup shield; another cancellation request is recorded but cannot skip owned
cleanup. Cancellation after atomic publication follows the normal scope-owner
cancellation and disposal contract rather than retroactively rolling back the
committed generation. Runtime hot replacement remains unsupported unless the
owning Capability explicitly declares a stable reference or dependent-closure
rebind contract.

## Dependency And Lifecycle Validation

If `A -> B`, B must be available before A and must outlive or share A's managed
lifetime. A process-scoped node cannot capture a Session-scoped dependency. A
sealed node cannot capture a turn-refreshable concrete object unless it uses an
explicit stable reference or participates in the same dependent-closure
refresh transaction.

Planning must reject at least:

- unknown Capability IDs or facets;
- dependency cycles, with the complete cycle path;
- scope, refresh-boundary, or bootstrap/final phase inversions;
- missing required dependencies;
- implementation requirements outside the owner-declared facet ceiling;
- undeclared cross-Product runtime dependencies.

Cross-Product Work or Artifact transfer remains a Product Handoff. A
higher-level application composition root may coordinate multiple Product
graphs through Harness contracts, but one Product graph does not turn another
Product identity into an internal node.

The initial target does not share a live Mounted Capability object between
Product graphs merely because their scope labels match. Each graph owns its
bindings and releases independently. Cross-graph pooling would require a
separate accepted scope-owned pool, lease, reference-counting, and final-
disposal contract; the read-only graph catalog is not that lifecycle owner.

## Management Ownership

There is no global mutable DAG manager or service locator. Responsibilities are
split as follows:

| Owner | Responsibility |
| --- | --- |
| `RuntimeCapabilityGraphPlanner` | Pure plan construction, dependency closure, topological order, and validation diagnostics |
| `RuntimeCapabilityGraphBinder` | Transactional bind, signature reuse, failure/cancellation rollback, reverse disposal, and generation invalidation |
| `RuntimeCapabilityGraphRuntime` | Live Mounted Capability state and scope-owned leases |
| `RuntimeCapabilityGraphProjector` | Read-only snapshots, explanations, impact paths, and redacted lifecycle facts |
| optional graph catalog | Read-only aggregation of graph snapshots from multiple Product/runtime instances |

Products own their Capability IDs, Mount Policy, Product-specific dependency
edges, admission, and presentation. Harness owns only Product-neutral graph
mechanics and Harness Capability Bundles. Harness must not import a Product
package or interpret a Product-only facet to plan the graph.

## Diagnostics And Observation

Selection diagnostics and graph diagnostics remain separate:

- a **resolution trace** explains admitted, rejected, losing, and selected
  candidates by source, permission, compatibility, and deterministic policy;
- a **graph plan diagnostic** explains unknown dependencies, cycles, scope or
  phase inversions, and missing facets;
- a **binding fact** reports `planned`, `waiting`, `creating`, `bound`,
  `blocked`, `failed`, `disposing`, or `disposed`, together with its dependency
  path and rollback result.

At minimum, a projected live node records Product id, Capability ID, scope and
scope-instance identity, generation, selected implementation/version and
provenance, requested facet view, lifecycle state, and redacted failure code.
Raw credentials, commands, environment values, provider objects, and arbitrary
configuration are not observation payloads.

Useful read-only operations are:

```text
snapshot(graph_id)
explain(capability_id)
dependencies(capability_id)
dependents(capability_id)
impact(capability_id)
```

Multiple Products publish separate graph snapshots. Aggregation keys by
Product id, runtime/scope instance, generation, and Capability ID; it does not
merge multiple Product profiles into one authoritative profile.

## Consequences

- Product graphs remain small enough to explain while focused owners retain
  internal lifecycle precision.
- Capability IDs remain stable when a provider, adapter, or private module is
  replaced.
- Narrow facet injection preserves least authority without exploding the DAG.
- Extension discovery and final provider selection no longer require rebinding
  every unchanged Capability.
- The finer Runtime Profile slot inventory remains useful as an internal
  selection and snapshot mechanism rather than becoming the public Product
  architecture graph.
