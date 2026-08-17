# Harness Current Owner Map

Status: current architecture reference.

This document is the short, authoritative map of the implemented
`loushang.harness` boundaries. Detailed boundary records explain individual
decisions; migration ledgers record how the code arrived here and are not a
second description of current ownership.

## Scope

Harness is the cross-Product execution substrate. It owns reusable mechanisms,
contracts, lifecycle shapes, and explicitly overridable platform defaults. A
Product owns domain language, prompts, policy choices, presentation semantics,
and the conversion from user intent or Method output into Product operations.

Harness does not import Product packages. In particular, Harness must not
depend on `loushang.coding`, `loushang.harnesswork`, `loushang.work`, `loushang.method`,
`loushang.channel`, `loushang.harnesstui`, or Product UI packages.

## Implemented Owners

| Owner | Owns | Does not own |
| --- | --- | --- |
| `runtime` | cancellation, retry/scheduling primitives, owner-scoped exact registration lifecycle, runtime-profile declarations, admission, resolution, binding, refresh, disposal | live registry conflict policy, Product capability selection policy, or provider behavior |
| `config` | layered/scoped configuration mechanics and optional Agent settings types, patch commands, schema codec, and manager lifecycle | Product-only fields, paths, activation effects, credentials, or presentation |
| `session` | optional Agent-session profile, Product-neutral assembly, turn/lifecycle coordination, command and maintenance bindings, Session facade and inspection | Product prompt content, domain operations, UI state, Work persistence |
| `conversation` | Product-neutral conversation identity, records, repository/catalog and replay contracts | Agent/AI message schema or Product-specific payload meaning |
| `transcript` | optional Agent/AI transcript profile, codecs, file/session lifecycle, context rebuild, compaction/retry/navigation mechanisms, and hidden reconstructable Model Input facts | Product compaction prompts, semantic summary policy, Product store selection, or provider transport outcomes |
| `context` | context items, packing, deterministic budget/accounting records, summary evaluation foundations | Product salience policy or model-specific estimation decisions |
| `tools` / `approval` / `policy` / `sandbox` | tool authoring and hosted execution mechanics, action policy evaluation, approval lifecycle, effects, execution-scope process-start authorization, and optional containment binding | Product risk defaults, executable/catalog admission, Product approval wording, arbitrary Product commands |
| `resources` / `extensions` / `capabilities` | resource discovery and precedence, package materialization mechanics, staged Extension/resource generations with exact live-registration retirement, capability composition, and coarse Capability graph contracts, planning, transactional Mount binding, live state, and read-only projection | Product-owned built-in content, trust decisions, activation policy, or Product-specific Provider behavior |
| `host` / `cli` / `events` / `presentation` | Product-neutral host lifecycle, RPC/JSON projection, runtime event contracts and reusable presentation | AppService tenancy, Channel protocol, Product grammar or final UI composition |
| `diagnostics` / `continuity` / `workspace` | shared diagnostic records/export, continuity provider composition, one-shot execution, and bounded session-owned process primitives | Product-specific recovery UX, business audit retention, protocol/server selection, Product artifact semantics |

## Accepted Capability Graph Target (Mount Runtime Implemented)

The implemented owner table above remains authoritative for current code. The
accepted [Capability Dependency And Mount Lifecycle](capability-dependency-and-mount-lifecycle.md)
decision adds a coarser architecture. Its immutable Definition, Requirement,
Bundle Provider declaration, pure planner, transactional Binder, live per-graph
Runtime, and read-only Projector now exist. `harness.workspace` is a
Definition / Provider / Consumer slice: Consumers receive only declared
filesystem facets or the authorized process-launch port, never the graph
Runtime, raw process host, approval gateway, or sandbox backend.

`harness.resources` is also source-complete but is not production-mounted. Its
Session/bootstrap/sealed Bundle maps the private resource, prompt, skill, Tool
pack, and Command pack Profile selections through focused Consumers. The
Provider temporarily owns its private Profile Binder and computes one complete
construction fingerprint; resource content remains call data and does not
publish a Mount. `interaction.side_question` is excluded and remains a focused
legacy binding owned and disposed by the Product Session.

The generated [Harness Capability Catalog](capability-catalog.md) is the
source-backed coverage projection. A target Capability is not reported as
implemented there until its Definition, Provider, requirements, and Consumers
all exist and pass the architecture gate.

The initial top-level Harness Capability IDs are `harness.workspace`,
`harness.resources`, and `harness.session`; current Coding-owned examples are
`coding.lsp` and `coding.arch`. Runtime Profile slots remain finer internal
Binding Facets rather than additional top-level graph nodes.

| Accepted target responsibility | Current implementation status |
| --- | --- |
| plan dependencies, closure, order, and validation | `RuntimeCapabilityGraphPlanner` is implemented as a pure planner under `loushang.harness.capabilities` |
| bind final nodes transactionally and reuse unchanged binding signatures | `RuntimeCapabilityGraphBinder` stages Provider values and owner-scoped registrations, atomically publishes successful generations, reuses unchanged signatures, and reverse-retires replaced nodes |
| own live Mounted Capability state, generations, and scope leases | `RuntimeCapabilityGraphRuntime` owns one Product/runtime graph and issues narrow, generation-scoped Consumer facet leases; it is not global mutable state |
| project read-only graph snapshots, explanations, and impact paths | `RuntimeCapabilityGraphProjector` exposes the committed `MountGraphSnapshot`, separate registration inventory, explanations, dependency/dependent paths, and impact without live values |

Mount Graph and registration inventory remain separate authorities and clocks.
The Mount snapshot references the existing Runtime Profile fingerprint rather
than copying its selections or changing the persisted Session-header contract.
No global mutable registry, second graph projector, or effective-runtime
selection authority is introduced.

Extension reload has its own narrower generation clock. One stable
`ExtensionRunner` stages declaration/resource discovery and owner-scoped live
bindings, synchronously publishes the selected Extension composition with the
resource bundle, then reverse-retires the replaced generation. It reuses
`RegistrationLease` and `RegistrationScope`; it is not a second Capability
graph or runtime projector. Historical model-visible Tool schemas remain owned
by committed Model Input facts rather than the current Extension generation.

The initial live Binder supports direct dependency facets. A planned
`stable_reference` edge fails closed before Provider construction until a
separate stable-indirection and refresh transaction is implemented; the Binder
does not satisfy that declaration by leaking a concrete refreshable value.

## Dependency Direction

The intended direction is:

```text
Product composition root
        -> Harness public contracts and optional profiles
        -> Agent / AI public contracts where an optional profile requires them

AppService / Product host
        -> Product narrow ports
        -> Harness Session or Work adapter

Harness -/-> Product, HarnessWork/Work, Method, Channel, Harnesstui, or Product UI
```

`session` is an assembly owner and therefore has high fan-out. High fan-out is
acceptable at that composition boundary; cycles, Product imports, and lower
layers importing the Session public barrel are not.

## Session Assembly Shape

The standard Agent-session composition has three explicit phases:

1. Foundation: diagnostics, tools, resources, navigation, and bash.
2. Maintenance: compaction and retry mechanisms with Product policy inputs.
3. Product bindings: model, identity, command, extension, maintenance, and
   inspection bindings.

`SessionCompositionPorts` stores those phase inputs as cohesive records.
`SessionComposition` stores the corresponding phase results and retains flat,
read-only compatibility properties for existing consumers. No generic bridge
or second coordinator is introduced merely to forward callbacks.

## Public API And Loading

`loushang.harness` is the narrow base entrypoint. Optional, larger profiles such
as `loushang.harness.session` and `loushang.harness.transcript` preserve their
published symbols through lazy facades: importing a profile does not construct
or import all implementation runtimes, while accessing a symbol loads its owner
module and caches the result.

Compatibility facades remain stable while large implementation pipelines are
split internally. The implemented dependency direction is:

```text
resource loader facade -> package policy
resource loader facade -> snapshot pipeline
                            -> context discovery
                            -> built-in discovery -> descriptor parsing
                            -> temporary discovery -> filesystem discovery
                                                       -> descriptor parsing
                            -> other source coordinator
                                 -> filesystem discovery -> descriptor parsing
                                 -> package policy
                            -> resolution -> precedence policy

runtime profile facade -> types + admission + resolution + binding + standard slots
admission / resolution / binding / standard slots -> profile types

Agent settings manager -> typed settings patch + settings schema codec
typed settings patch -> settings schema codec field rules
settings schema codec / typed settings patch -> Agent settings types

workspace read tool + Host prompt input -> workspace image payload owner

tool definition owner -> execution bindings
session execution scope -> tool execution host -> structural definition port
```

Context-file ancestor traversal, configured filename precedence, descriptor
construction, and nearest-context selection belong to
`harness.resources._loader_discovery_context`. Package-root and filter
normalization, descriptor-selection patterns, root diagnostics, and per-root
resource accounting belong to `harness.resources._loader_package_policy`.
Source-neutral prompt/skill frontmatter projection, descriptor construction,
and skill metadata validation belong to
`harness.resources._loader_descriptor_parsing`; it performs no filesystem or
package-resource I/O.
Filesystem directory traversal and reads, recursive skill discovery and ignore
rules, extension entry lookup, and theme JSON validation belong to
`harness.resources._loader_discovery_filesystem`. External-package and
project/user source coordination remain in `_loader_discovery`; the coordinator
consumes filesystem discovery and package policy. Temporary runtime-path
resolution, single-file/directory dispatch, source metadata, and path diagnostics
belong to `harness.resources._loader_discovery_temporary`. Built-in package
traversal, logical package paths, resource reads, and built-in category
diagnostics belong to `harness.resources._loader_discovery_builtin`. The snapshot
pipeline calls the source coordinator, context discovery, built-in discovery,
and temporary discovery directly but does not depend directly on their leaf
policies. Context discovery, built-in discovery, temporary discovery,
filesystem discovery, descriptor parsing, and package policy do not depend on
discovery coordination, resolution, the pipeline, or the public loader facade.
Loader option normalization and system-prompt source resolution remain with the
public loader owner rather than discovery coordination. The loader projects its
normalized state into one immutable pipeline-owned discovery request. The
pipeline owns candidate-source aggregation, including the single expression of
temporary, built-in, external-package, user-global, and project-local candidate
order; discovery diagnostic order remains an explicit, separate contract.
Resolution never imports any discovery owner or package policy, live profile
binding never imports profile resolution, and internal leaf modules never
import their public facade. The tool execution host consumes a private
structural definition port; `harness.tools.execution` does not import the
`ToolDefinition` owner in `harness.tools.core`.
The Agent settings manager depends only on the explicit codec/patch ports
enforced by the architecture tests, not on field-level serializer helpers.
Image MIME validation, header dimensions, base64 encoding, inline limits, and
resize preparation belong to `harness.tools.workspace.image_payload`; neither
prompt input nor the read tool owns a second copy of those rules or the
inspect/resize/recompute sequence. Consumer-specific omission and presentation
policy remains with Host prompt input and the read tool.

## Architecture Gates

`make check-harness` is the integration gate. The architecture tests enforce:

- an acyclic internal Harness dependency graph;
- no Session-module import from the Session public barrel;
- one-way Harness, Work, and Channel dependencies;
- explicit Agent/AI import allowlists for optional profiles;
- one-way resource loader, context/built-in/temporary/filesystem discovery,
  descriptor parsing, package policy, runtime profile, and Agent settings
  internals with an exact manager-to-codec/patch import allowlist;
- one-way tool-definition-to-execution dependencies;
- one shared workspace image-payload owner consumed by Host prompt input and
  the read tool;
- Product-neutral Harnesstui and shared runtime owners;
- canonical coarse Capability IDs and Mount terminology in architecture
  documents, without representing Product, Plugin, Package, or Extension
  identities as graph nodes; and
- the capability-runtime convergence inventory, exact existence of implemented
  graph owners, no-second-runtime rule, and narrow graph API parameters.

New boundaries must update this map when they change current ownership. A
migration ledger alone is not sufficient evidence of the resulting boundary.

## Product-Owned Exclusions

The following remain Product-owned unless a separate accepted boundary record
demonstrates multiple real Product implementations:

- prompts, model defaults, domain vocabulary, and policy defaults;
- user-intent parsing and Product operation resolution;
- Method-to-Work preparation and Product Work execution;
- Product event vocabulary and final UI projection;
- Product storage roots, retention policy, and artifact meaning;
- cloud tenancy, billing policy, credentials, and AppService authorization.

## Document Authority

When documents disagree, use this order:

1. current source and architecture gates;
2. this current owner map;
3. accepted boundary documents linked from the Harness README, including the
   Capability dependency and Mount lifecycle decision;
4. proposed architecture documents;
5. migration plans, ledgers, slice status, and historical inventories.

Completed migration records should be retained for traceability but must not be
read as current ownership specifications.
