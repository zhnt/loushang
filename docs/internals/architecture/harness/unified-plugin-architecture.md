# Unified Plugin Architecture

## Status

Target architecture. The existing Capability Graph, Registration Scope,
Extension generation, Resource Package, and Plugin source-management runtimes
remain authoritative while this migration is incomplete. This document does
not claim that `coding.lsp`, `coding.arch`, or the unified Plugin lifecycle are
already implemented.

Canonical Product, Capability, Mount, Package, Plugin, Extension, and Resource
terms remain defined by the
[Product And OEM Glossary](../../glossary/loushang-product.md). The
[Capability Dependency And Mount Lifecycle](capability-dependency-and-mount-lifecycle.md)
remains authoritative for the Capability Graph, and the
[Extension And Resource Generation Lifecycle](extension-generation-lifecycle-boundary.md)
remains authoritative for current Extension generations. This document joins
their target authoring, packaging, selection, and lifecycle entry paths; it
does not introduce a competing graph or publisher.

## Purpose

Loushang needs one Plugin system in which first-party, OEM, workspace, and user
contributions can be distributed, selected, diagnosed, and retired in the same
way. Coding's standard features, LSP support, and architecture analysis should
be composable without turning Harness into a global service locator or letting
installed code acquire authority automatically.

The target relationship is:

```text
Plugin Source
  -> authority-bound Resolved Plugin Package
  -> immutable Plugin Declaration
  -> deterministic Plugin Plan
  -> typed Component candidates + Capability Graph inputs
  -> one committed Plugin Generation
  -> Product/session projections
```

The governing rule is:

> A Plugin is a selectable lifecycle and contribution unit. A Capability is a
> stable typed runtime contract. A Package is a distribution unit. An
> Extension is one executable contribution kind. None is a synonym for the
> others.

## Design Inputs

The target combines four proven design properties without importing another
framework's object model:

- packages resolve to inert, source-authority-bound descriptors before any
  component is loaded;
- component kinds use focused hosts instead of one unrestricted executable
  Plugin context;
- installation, enablement, scope, policy, dependency, refresh, and repair are
  explicit management states;
- every effect belongs to a reversible generation, while sessions pin the
  model-visible composition they actually used.

Loushang adds two stricter requirements: typed Capability Definition / Provider
/ Consumer seams remain the runtime injection model, and existing owner
publishers remain the only publishers of their live objects.

## Non-Negotiable Invariants

1. Plugin identity is not a Capability Graph node. Plugin provenance is a
   selection fact attached to Capability Providers and other contributions.
2. `RuntimeCapabilityGraphBinder` is the only Capability Graph publisher.
3. Every manifest format has one parser. In particular, `plugin.json` has one
   manifest parser; Package projection consumes its resolved descriptor and
   must not parse it again.
4. A contribution has one declaration owner and one binding owner. Manifest
   declarations and runtime registration are not flattened into the same
   ambiguous record.
5. All live registrations belong to one `RegistrationScope` and one Plugin
   generation. Unload and failed admission reverse every owned effect.
6. A Product or OEM profile selects Plugins and authority ceilings; Plugins do
   not select themselves or widen their own authority.
7. Installed code is inert. The state relation is
   `installed != enabled != planned != mounted`.
8. Built-in Plugins use the same resolution, declaration, planning, binding,
   projection, and retirement contracts as external Plugins. Only their source
   resolver and trust provenance differ.
9. Model-visible tools, prompts, Skills, commands, and capability selections
   are committed as generation facts before a model can use them.
10. No API exposes a global mutable Plugin context, `dict[str, Any]` service
    bag, or unconstrained registry lookup.

## Vocabulary And Identity

| Concept | Meaning | Runtime authority |
| --- | --- | --- |
| Plugin Source | A configured built-in, local, materialized, or registry-backed location. | None |
| Resolved Plugin Package | An inert descriptor containing Plugin identity, version, digest, source authority, root, manifest, and typed resource locators. | None |
| Plugin Definition | Trusted authoring entrypoint that can produce a declaration without publishing effects. | Declaration only |
| Plugin Declaration | Immutable typed contributions, requirements, configuration schema, requested authorities, and factories. | None |
| Plugin Composition Set | Ordered reusable Plugin selections and default configuration. It is not a Capability Bundle. | None |
| Plugin Profile | Product/OEM/session selection of composition sets plus explicit overlays and authority ceilings. | Selection only |
| Plugin Plan | Pure, validated, fingerprinted result of source, profile, dependency, policy, and conflict resolution. | None |
| Plugin Instance | One planned Plugin identity bound to a concrete process, workspace, Session, or turn scope. | Candidate owner |
| Plugin Generation | One committed instance revision and all registrations, mounts, resources, and projections that it owns. | Lifecycle owner |
| Component Host | Focused adapter that prepares and retires one contribution kind. | Its owned component only |
| Capability | Stable owner-qualified contract such as `coding.lsp`. | Capability owner and Graph |

Stable identities are distinct even when their display strings look similar:

```text
Plugin ID:        org.loushang.coding-lsp
Capability ID:    coding.lsp
Provider ID:      org.loushang.coding-lsp/default
Plugin instance:  org.loushang.coding-lsp@workspace:repo-123
Plugin generation: instance + plan generation 7
Capability mount: coding.lsp@workspace:repo-123 generation 4
```

A single Plugin may contribute several Capability Providers and resource
families. Several Plugins may offer candidates for one owner-approved
Capability. One Capability Bundle may aggregate admitted contributions from
several Plugins. Identity equality must never be inferred across these rows.

## Four-Phase Pipeline

### 1. Resolve once

`PluginSourceResolver` converts every configured source into a
`ResolvedPluginPackage`. Resolution performs no Python import, process launch,
registry mutation, or Product activation.

The resolved descriptor contains at least:

- canonical Plugin ID, version, source kind, source identity, and content
  digest or immutable revision when available;
- an authority-qualified package root and typed resource locators;
- the parsed canonical manifest and schema version;
- trust provenance, requested authorities, engine compatibility, and
  dependency declarations;
- structured diagnostics for broken or unsupported packages.

Every locator carries both a logical path and the environment/source authority
under which it was resolved. All manifest paths are relative, normalized after
symbolic-link resolution, and proven to remain within the package root.

The canonical parsing boundary is:

```text
plugin.json           -> PluginManifestParser -> ResolvedPluginPackage
loushang-package.json -> PackageManifestParser -> ResolvedResourcePackage
ResolvedPluginPackage -> Package/Resource views without another file read
```

The current `resources.plugins.resolver` and
`resources.packages.manifest` handling of `plugin.json` must therefore converge
on one manifest parser. Compatibility readers may recognize older field names,
but they must normalize into the canonical descriptor and disappear from all
downstream paths.

Discovery records broken packages rather than silently dropping them. A
profile that requires a broken Plugin fails before any activation effect; an
unselected broken Plugin remains visible in inventory diagnostics.

### 2. Declare once

The declaration phase converts one resolved descriptor into one immutable
`PluginDeclaration`. It may load a trusted in-process Plugin Definition, but it
must not publish effects. Resource-only and external-service Plugins can be
declared entirely from data.

A candidate authoring seam is:

```python
class PluginDefinition(Protocol):
    def declare(
        self,
        context: PluginDeclarationContext,
    ) -> PluginDeclaration: ...
```

`PluginDeclarationContext` exposes only immutable package locators, validated
configuration input, engine metadata, and declaration builders. It does not
expose registries, live Providers, a Session, subprocess launch, filesystem
write access, credentials, or arbitrary services.

One declaration can contain these typed contribution families:

| Contribution | Meaning | Binding owner |
| --- | --- | --- |
| Capability Provider | Candidate Provider and factory for an owner-defined Capability contract. | Capability Graph Binder |
| Resource Pack | Prompts, Skills, commands, themes, assets, or methods with provenance. | Resource generation owner |
| Tool or Command Pack | Typed pack contribution to an owning Capability Bundle. | Owning Bundle host |
| Extension Surface | Observer, interceptor, decorator, replacement, renderer, shortcut, or other admitted surface. | Extension generation owner |
| Integration Service | Declarative MCP, LSP-server, or future external-service specification. | Kind-specific service host |
| Configuration Schema | Namespaced Plugin settings, defaults, sensitivity, and restart/refresh policy. | Product configuration runtime |

Capability Definitions remain owner-controlled. A third-party Plugin may
offer a Provider for `coding.lsp` only when the Coding definition explicitly
allows that variation and Product/OEM policy admits it. A first-party Plugin
may carry a new owner-qualified Definition, but Definition publication still
passes the Product's definition-admission boundary before planning.

The manifest and an executable entrypoint must not declare the same
contribution identity twice. A manifest may either declare a data contribution
or point to the Definition that declares it. The compiler reports duplicate
identity with both provenance paths.

The current Extension `register_*` authoring API becomes a compatibility
adapter: during declaration compilation it captures typed calls into a private
declaration builder and freezes the same `PluginDeclaration` shape. It must not
mutate a live registry. Binding later realizes the declaration under the
candidate's `RegistrationScope`. New Plugin SDK code returns declarations
directly, and the compatibility adapter is removed after existing Extensions
migrate.

Declaration is followed by pure planning. `PluginPlanResolver`:

1. composes the host-supplied ordered configuration layers;
2. applies Product/OEM authority and trust ceilings;
3. resolves installation dependencies without granting runtime handles;
4. resolves runtime dependencies through Capability requirements;
5. applies contribution conflict and variation policy;
6. produces a deterministic plan, resolution trace, and fingerprint.

The generic engine does not prescribe global/user/project/session precedence.
The Product Host supplies named low-to-high layers through the existing layered
configuration contract. The plan records every contributing layer. Managed
policy is an admission ceiling, not merely a high-precedence value that a later
layer can overwrite.

Plugin-to-Plugin runtime service lookup is forbidden. A distribution
dependency guarantees that another package is materialized and selected; a
runtime dependency uses a typed `CapabilityRequirement` or contribution
contract. Dependency resolution rejects cycles, incompatible versions, missing
facets, cross-scope lifetime inversion, and unapproved cross-source trust.

### 3. Bind once

`PluginRuntime.prepare(plan)` creates a `PluginGenerationCandidate` without
changing the published generation. One root `RegistrationScope` owns all child
leases and effects. Focused Component Hosts prepare their candidates, while the
Capability planner and Binder receive only typed graph inputs.

```text
Plugin Plan
  -> open root RegistrationScope
  -> prepare Resource/Extension/Integration candidates
  -> build final Capability Definition/Provider/Consumer inputs
  -> RuntimeCapabilityGraphPlanner validates the DAG
  -> RuntimeCapabilityGraphBinder prepares the graph delta
  -> verify model-visible facts and publication fingerprints
  -> synchronously publish owner transactions
  -> expose the new Plugin generation
  -> join and reverse-retire the superseded generation
```

The Plugin publication coordinator orders already-prepared owner transactions;
it does not publish their live objects itself. In particular,
`RuntimeCapabilityGraphBinder` remains the only Capability Graph publisher,
the Extension runner remains the only Extension-generation publisher, and the
Resource owner remains the only Resource-generation publisher.

Every owner transaction must support prepare, synchronous publish, restoration
of the previous snapshot when a later publish step fails, and idempotent
reverse retirement. No await occurs inside the publication window. Failure or
cancellation before commit leaves the previous generation authoritative and
reverse-disposes the candidate under a cleanup shield. Failure after commit is
a retirement failure: the new generation remains authoritative and the old
generation remains tracked for cleanup retry.

A Component Host is intentionally narrow:

| Host | Accepted input | It must not do |
| --- | --- | --- |
| Resource Component Host | Resolved resource locators and typed pack declarations | Reparse Plugin manifests or bind Capabilities |
| Extension Component Host | Admitted Extension declarations and entrypoint locator | Select Product policy or publish the Graph |
| External Service Host | Declarative process/transport spec and authorized launch facet | Launch through raw subprocess APIs |
| Capability Host | Definition/Provider/Consumer inputs and factories | Bypass the Graph Planner/Binder |
| Model Projection Host | Committed contribution facts | Inspect live registries to reconstruct history |

There is no universal `activate(plugin_context)` callback. Provider factories
receive least-authority typed dependency views and a registration collector,
matching the current Capability Provider context. External integrations obtain
workspace/process/network access only through admitted facets.

### 4. Project once

Projection reads the committed Plugin generation, Capability Graph snapshot,
and component snapshots. It never discovers packages, parses manifests,
selects Providers, or binds live objects.

One `EffectivePluginRuntimeProjector` produces inventory, explain, JSON, diff,
and bounded model-facing views. Product adapters may format those records, but
must not reconstruct a second effective state from settings plus registries.

At minimum, one projected Plugin entry records:

- Plugin ID, version, source authority, digest/revision, trust tier, and scope;
- installed, enabled, planned, candidate, mounted, retiring, disabled, or
  broken state;
- plan and generation fingerprints;
- requested and granted authorities;
- declared, selected, rejected, and effective contributions;
- Capability dependencies, mounts, registration owners, and generation IDs;
- configuration provenance with sensitive values redacted;
- failure, rollback, retirement, and retry diagnostics.

Model-facing projection is a bounded allowlist of tool schemas, prompt/Skill
content fingerprints, and other admitted inputs. The complete Plugin manifest,
filesystem paths, environment, credentials, and diagnostic payloads are not
automatically placed in model context.

## Composition Sets And Profiles

A Plugin Composition Set is a reusable ordered list of Plugin selections and
default configuration. It is distribution/configuration data, not a live
runtime object and not a Capability Bundle. A Plugin Profile selects one or
more sets and applies explicit row overlays by stable selection ID.

```text
Product defaults
  -> Product composition sets
  -> OEM Profile selections and ceilings
  -> admitted user/workspace selections
  -> session or CLI overlay
  -> immutable Resolved Plugin Profile
```

An overlay may insert a selection, disable it, replace its version/source pin,
or replace/patch its namespaced configuration. It cannot mutate an already
resolved source descriptor or persist runtime state back into the Profile.
Unknown selection IDs, duplicate IDs at one layer, and invalid patches fail
planning with provenance.

Profiles contain no live Providers, credentials, open files, process handles,
or Python objects. Secret fields store references to the Product's credential
mechanism; resolution happens only in an admitted component host and is never
part of plan fingerprints or projections.

## Scope, Generations, And Refresh

Plugin declarations state the narrowest supported lifetime: process,
workspace, Session, or turn. A longer-lived Plugin instance may not capture a
shorter-lived concrete dependency. It must use a stable reference/lease or be
rebound with the dependent closure.

Each committed Plugin generation tracks an active join count. A Session pins
the exact resolved Profile, Plugin plan generation, Capability graph
generation, and model-input contribution facts it uses. Profile and package
changes affect new Sessions by default.

An existing Session may recompose only when all of the following hold:

- the Session has not made a model-visible call, or the changed owner defines a
  durable turn-boundary replacement contract;
- the complete dependent closure can be prepared and published transactionally;
- removed model-visible inputs remain reconstructable from committed facts;
- old-generation leases remain valid until all joined work releases them.

Otherwise the runtime reports `restart_required`. Superseded generations are
retired as soon as their join count reaches zero; they must not accumulate for
the process lifetime. Failed disposal remains visible and retryable.

## Trust And Authority Model

Installation proves only that bytes were materialized. Activation admission is
the intersection of:

```text
source trust
  AND package integrity/compatibility
  AND Product/OEM Plugin allowlist
  AND Profile authority ceiling
  AND contribution-specific required authority
  AND runtime approval/policy enforcement
```

The first implementation supports only trusted in-process Python Plugins.
Resource-only Plugins and declarative external-service Plugins may run under
narrower trust. Untrusted arbitrary Python is out of scope until an isolated
worker protocol exists; a Python import is not a sandbox.

Required security contracts include:

- normalized containment for every manifest locator, including symbolic-link
  escape checks;
- immutable revision or digest recording for materialized remote sources;
- source policy checked before dependency materialization and again before
  activation;
- no transitive trust across registries or package sources;
- all process launch, filesystem mutation, network, model, secret, and UI
  authority supplied through typed admitted facets;
- execution-time revalidation for actions covered by policy or approval;
- structural redaction for diagnostics and projections.

## Coding Product Decomposition

The Coding Product Kernel remains deliberately small and non-pluggable. It owns
Product identity, Session/turn correctness, Product-to-Harness composition,
transcript and model-call policy, and mandatory safety enforcement. The Coding
Product Kernel must remain usable when every optional Plugin is disabled.

`coding.base` is a Product-owned Plugin ID selected by the default composition
set, not a new top-level Capability ID. It contributes standard Coding prompts,
Skills, commands, Tool packs, and optional adapters into owner-defined
Harness/Coding Capabilities. Disabling it yields a minimal Coding Product; it
does not remove the Product Kernel.

The initial first-party decomposition is:

| Plugin | Main contribution | Capability effect |
| --- | --- | --- |
| `coding.base` | Standard Coding resources, commands, and Tool packs | Aggregates into `harness.resources` and `harness.session`; no new graph node |
| `coding.lsp.default` | LSP declaration admission, supervisor/document runtime, semantic tools, and diagnostics | Provides `coding.lsp`, requiring narrow `harness.workspace` read/process facets |
| `coding.arch.default` | Repository analyzers, architecture facts, queries, and tools | Provides `coding.arch`, requiring `harness.workspace` and optionally consuming `coding.lsp` |

Suggested built-in Profiles are:

| Profile | Selections |
| --- | --- |
| `coding-minimal` | Product Kernel only |
| `coding-standard` | `coding.base` plus on-demand `coding.lsp.default` |
| `coding-architecture` | `coding-standard` plus on-demand `coding.arch.default` |

The LSP vertical slice replaces the current multi-stage mode/discovery/deferred
runtime/process-launch binding chain with one declaration and one Graph bind:

```text
coding.lsp.default declaration
  -> Capability Provider candidate for coding.lsp
  -> requirement on harness.workspace(read, process.launch)
  -> one Provider factory receives those typed facets
  -> one coding.lsp Bundle exposes semantic runtime + tools + diagnostics
```

Tools are not pre-registered against a deferred LSP object. They are part of
the selected Bundle and become visible in the same committed generation as the
runtime they call.

## Single-Authority Matrix

| Concern | Sole authority | Forbidden peer path |
| --- | --- | --- |
| `plugin.json` parsing | `PluginManifestParser` | Package catalog or component host reparsing |
| Source/path authority | `ResolvedPluginPackage` locators | Raw path joining in component consumers |
| Plugin selection | `PluginPlanResolver` under Product/OEM policy | Self-enable in Plugin code |
| Contribution declaration | `PluginDeclarationCompiler` | Live `register_*` mutation outside candidate capture |
| Capability selection and DAG | `RuntimeCapabilityGraphPlanner` | Plugin dependency graph as a service graph |
| Capability publication | `RuntimeCapabilityGraphBinder` | Plugin runtime publishing mounts |
| Extension publication | Extension generation owner | Plugin runtime mutating Extension registries |
| Resource publication | Resource generation owner | Plugin runtime rebuilding Resource state |
| Model-visible effective input | committed Model Input facts | Reading current registries during replay |
| Plugin generation disposal | root `RegistrationScope` plus owner transactions | ad hoc unload callbacks |
| Effective diagnostics | one projector over committed snapshots | CLI/TUI rebuilding effective state independently |

This matrix is the direct answer to duplicate multi-path parsing, binding, and
declaration: the target permits multiple source adapters and multiple typed
component hosts, but exactly one normalized descriptor, declaration, plan,
binding authority per live object, and effective projection.

## Current Gap To The Target

| Area | Current Loushang position | Target gap |
| --- | --- | --- |
| Typed Capability composition | Strong Planner/Binder/Runtime/Projector and registration ownership | Mount `coding.lsp` and `coding.arch`; feed them from Plugin plans |
| Plugin distribution | Resource-oriented source registry and materialization | Authority-bound descriptor, digest/pin, unified manifest and scope inventory |
| Plugin lifecycle | Enablement resolves resource roots; Extension and Graph lifecycles are separate | One plan/generation coordinating existing owner transactions |
| Declarations | Manifest metadata and executable Extension registrations can converge late | Immutable typed declaration compiler and compatibility capture adapter |
| Profiles and composition sets | Product settings and Runtime Profiles exist | Explicit Plugin selections, stable row overlays, fingerprints, generation pinning |
| Component hosting | Resource and Extension owners exist; MCP/LSP paths remain specialized | Focused common Component Host protocol without generic context |
| Refresh | Extension generation rollback is mature; graph hot replacement is restricted | Plugin-level prepare/publish/retire, join counting, restart-required decisions |
| Operations | Package/plugin commands and diagnostics exist | One installed/enabled/planned/mounted inventory plus explain/diff/repair |
| Ecosystem surfaces | Coding-centric integrations | Stable SDK, external process host, MCP/ACP/JSON-RPC and multi-Product adapters in later waves |

Compared with a fully plugin-first Harness, the largest gap is not the
Capability Graph or rollback mechanics; Loushang is already strong there. The
largest gap is that package resolution, Plugin selection, Extension
declaration, Capability planning, LSP construction, and diagnostics do not yet
flow through one Plugin plan and generation. Closing that vertical path before
adding more contribution kinds is the priority.

## Delivery Sequence

Each slice must preserve the formal Harness gate and add a focused architecture
or runtime regression before implementation.

### UPA0: Baseline And Authority Freeze

- freeze every current manifest parse, declaration, Provider construction,
  registration, projection, and disposal path;
- add executable allowlists for the sole authorities in the matrix above;
- record current Coding LSP and Arch wiring and supported compatibility paths.

### UPA1: Resolve Once

- introduce the canonical Plugin manifest schema/parser and
  `ResolvedPluginPackage`;
- make Package/Resource projection consume the resolved descriptor;
- enforce source-qualified containment and structured broken-package inventory;
- migrate built-in, local, and materialized sources through the same result.

### UPA2: Declare And Plan Once

- add `PluginDefinition`, immutable typed declarations, composition sets,
  Profiles, plan resolution, policy ceilings, and fingerprints;
- distinguish installation dependencies from Capability requirements;
- add the Extension registration-capture adapter without changing behavior.

### UPA3: Bind And Project Once

- add the root Plugin candidate/generation and owner-transaction coordinator;
- retain Graph, Extension, and Resource publishers as sole live authorities;
- add installed/enabled/planned/mounted inventory, explain, JSON, and diff;
- pin Sessions and reclaim retired generations by join count.

### UPA4: LSP Vertical Slice

- package the default LSP implementation as a first-party Plugin;
- mount `coding.lsp` in the Session-owned Capability Graph;
- remove deferred LSP/process/tool pre-binding paths;
- prove alternate Provider selection, rollback, restart reconstruction, and
  complete disposal.

### UPA5: Architecture Vertical Slice

- package the default architecture implementation as a first-party Plugin;
- mount `coding.arch`, initially independent of LSP;
- add the optional typed LSP requirement only when its contract is proven;
- move analyzers, facts, diagnostics, and tools into one Bundle generation.

### UPA6: Base Coding Composition

- define `coding.base` and the minimal/standard/architecture Profiles;
- move standard Coding contributions without moving the Product Kernel;
- delete duplicate CLI registrations and hard-coded capability defaults after
  compatibility telemetry shows no remaining callers.

### UPA7: SDK And External Components

- publish the versioned manifest and declaration SDK;
- add declarative MCP/external-service hosting through authorized process and
  transport facets;
- add compatibility, conformance, trust, and upgrade tests for OEM Plugins.

### UPA8: Management And Ecosystem Closure

- unify install, remove, enable, disable, update, refresh, repair, list,
  explain, and diff across CLI/RPC/UI;
- add lock/pin and integrity policy appropriate to remote sources;
- evaluate an isolated out-of-process host before admitting untrusted code;
- remove superseded Plugin, Package, and Extension compatibility adapters.

## Acceptance Gates

The architecture is complete only when all of these statements are executable:

- `plugin.json` is parsed once and path containment is identical for Package
  and Plugin consumers;
- built-in and external Plugins produce the same resolved descriptor and plan
  shapes;
- two Profiles deterministically select different Plugin sets without Product
  code branches;
- an alternate `coding.lsp` Provider can be selected without changing Session,
  CLI, or Tool implementation code;
- a failing or cancelled candidate leaves the old Plugin and Capability
  generations authoritative and leaks no registration;
- disabling or unloading a Plugin disposes tools, hooks, resources, processes,
  Provider bindings, and projections exactly once in reverse order;
- restart reconstructs Plugin plan, Capability graph, and model-visible inputs
  from committed/configured facts rather than stale in-memory registries;
- a running Session remains pinned while new Sessions observe an updated
  Profile, and superseded generations are reclaimed after their final join;
- CLI, RPC, and UI show the same inventory and resolution trace;
- architecture gates reject a second parser, graph publisher, declaration
  mutation route, or effective-runtime projector.

## Explicit Non-Goals

- making every Tool, hook, Skill, analyzer, or service a top-level Capability;
- making Product identity, Product Kernel, OEM Profile, Package, or Plugin a
  Capability Graph node;
- exposing a universal dependency-injection container or mutable Plugin
  context;
- running untrusted arbitrary Python in process;
- hot-swapping arbitrary Plugins inside a Session after model-visible use;
- allowing Plugins to persist changes into their source manifests or Profiles;
- replacing the existing Capability Graph, Registration Scope, Extension
  generation, Resource generation, configuration, policy, or approval owners;
- blocking initial architecture convergence on a remote marketplace, signing
  service, Web client, or every integration protocol.

## Consequences

The architecture makes optional behavior genuinely pluggable while preserving
Loushang's strongest existing properties: typed least-authority injection,
small explainable Capability graphs, transactional publication, durable
model-input reconstruction, and owner-scoped disposal.

It also imposes discipline. Plugin authors cannot reach arbitrary live
services, Product adapters cannot bind the same Capability through a second
path, and management surfaces cannot infer effective state independently. The
cost is a staged migration of Package, Extension, LSP, Arch, and Coding-default
paths before the Plugin SDK can be declared stable.
