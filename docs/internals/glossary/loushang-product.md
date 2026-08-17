# Loushang Product And OEM Glossary

This glossary defines the canonical Product, OEM, package, plugin, and
capability-composition terms used by Loushang architecture documents and
implementations. Use these terms consistently in new Product, Harness, OEM,
resource, and launch-surface documents.

The glossary defines vocabulary and boundaries. It does not claim that every
described discovery, registration, or routing mechanism is already implemented.
Current implementation status belongs in the relevant architecture boundary
document and code.

For Chinese discussion terms, see the
[Chinese terminology table](./loushang-product-zh.md).

## Core Mental Model

```text
Platform CLI or OEM CLI
  -> Platform Host
  -> OEM Profile
  -> Product Registry
  -> Product Router
  -> Product Factory
  -> one active Product Runtime per Product Session
       -> Product Kernel
       -> admitted Capability Packs
       -> activated Product Capability Bundles
       -> Product-approved Plugin contributions
```

Harness supplies product-neutral mechanisms. A Product supplies domain
semantics, defaults, and policy. An OEM selects and overlays Products. Plugins
contribute optional resources or behavior only after Product and OEM admission.

## Concept Dimensions

The core terms name different architectural dimensions and must not be used as
substitutes for one another:

| Term | Dimension | Governing question |
| --- | --- | --- |
| Product | domain identity | What coherent domain experience owns this Session? |
| OEM | platform selection and overlay | Which Products, defaults, policy, resources, and branding does this distribution select? |
| Capability | runtime composition | What named ability must the runtime bind? |
| Harness Capability | shared mechanism ownership | Which Product-neutral contract or mechanism does Harness own? |
| Package | distribution and materialization | How are software or resources delivered? |
| Plugin | optional identity and activation | Which manifest-backed contribution source can be admitted and enabled independently? |
| Extension | executable or declarative contribution | What optional behavior enters a defined extension surface? |

The runtime relationship is:

```text
OEM selects and overlays Products
  -> Product declares and binds Capability Slots
     -> Harness supplies Product-neutral Harness Capabilities
     -> admitted Plugins contribute resources or Extensions
```

Distribution is an orthogonal relationship:

```text
Product Package  -> registers a Product
OEM Package      -> provides an OEM Profile and optional overlays or Plugins
Resource Package -> distributes resources and optional Extensions
Plugin           -> gives optional identity and activation to a contribution source
Extension        -> contributes behavior to an admitted runtime surface
```

## Platform And Launch Model

### Platform

The installable and runnable Loushang system that can discover, register, and
host one or more Products. The Platform is not itself a domain Product.

### Platform Host

The process-level composition root that owns Product discovery, OEM selection,
Product routing, shared process or tenant services, and runtime disposal.

A Platform Host may expose a CLI, TUI, RPC, web, embedded, or other channel. It
does not supply Coding, PPT, Research, or other domain semantics.

### Platform CLI

The neutral `loushang` command entry point. It resolves an explicitly selected
or configured default OEM and Product, then delegates startup through registered
descriptors and factories.

A Platform CLI should not derive an import path such as
`loushang.<oem>.cli` from an unvalidated string. Registration and trust precede
loading.

### OEM CLI

An OEM-branded command entry point, such as `acme`, that starts the same Platform
Host with a predetermined or selectable OEM Profile.

An OEM CLI is a launch surface, not a separate runtime architecture. It should
call the shared Platform bootstrap rather than copy Product startup,
registration, session, or disposal mechanisms.

### Default OEM

The OEM Profile selected when a launch request does not specify an OEM.

A default is configuration, not code ownership. Selecting a Default OEM must
not make the neutral Platform import one hard-coded OEM module.

### Default Product

The Product selected by an OEM or Platform launch when the user does not
explicitly choose one.

For example, an OEM may define `coding` as its Default Product while also
making the `ppt` Product and a `ppt-authoring` Product Capability Bundle
available.

## Product Model

### Product

A domain-specific Loushang experience with its own goals, language, completion
criteria, prompts, capability defaults, policy, context behavior, artifact
semantics, session compatibility, commands, configuration, and presentation.

Examples include Coding, PPT, Research, Design, Cowork, and Environmental.

A Product is not merely a collection of Skills or Tools. It owns the domain
decisions required to compose those capabilities into a coherent runtime.

### Product Kernel

The irreducible Product-owned semantics and policy that must not migrate into
Harness merely because another Product could reuse the surrounding mechanism.

The Product Kernel includes domain goals, system-prompt content, capability
selection, context salience, compaction and summary policy, risk and approval
defaults, artifact semantics, session compatibility, and Product presentation.

### Product Adapter

The code that binds one Product Kernel to Harness, Agent, Work, Channel, TUI,
and other shared mechanisms.

A Product Adapter should remain small as shared mechanisms improve, but it must
retain Product-exclusive semantics and policy.

### Product Package

An installable software distribution that provides a Product Descriptor,
Product Factory, Product Adapter, and any built-in Product resources.

A Product Package may be first-party or independently distributed. Installation
does not automatically grant activation or trust. A Product Package is distinct
from the current resource-oriented Package and Plugin abstractions.

### Product Descriptor

The data-only registration record for one Product. It identifies the Product
and its compatibility boundary without constructing a live runtime.

A Product Descriptor should include at least a stable `product_id`, display
name, Product version, supported Product API version, factory reference, and
declared compatibility or host requirements.

### Product Factory

The Product-supplied factory that creates a Product Runtime from an admitted
Platform, OEM, workspace, channel, and session context.

The factory owns Product assembly. Product discovery and Product selection do
not construct live Product services as side effects.

### Product Registry

The deterministic catalog of admitted Product Descriptors available to one
Platform Host.

The Product Registry rejects ambiguous Product identities and does not choose a
default Product. Discovery populates the registry; OEM policy filters it; the
Product Router selects from it.

### Product Router

The Platform or OEM mechanism that selects a registered Product for a launch,
request, workspace, or persisted session.

When restoring a session, the persisted `product_id` is authoritative unless an
explicit migration is performed. Routing must not silently reinterpret one
Product's session as another Product.

### Product Runtime Plan

The Product-owned, data-only declaration of runtime capability slots, baseline
selections, allowed override sources, and configuration.

A Product Runtime Plan does not contain factories, credentials, plugin
discovery, or live objects.

### Resolved Runtime Profile

The deterministic result of applying admitted Product, OEM, extension, and
session layers to a Product Runtime Plan.

Its durable snapshot explains which capability implementations and
configuration were used by a Product Session.

### Product Runtime

One live, bound execution of a Product for a specific lifecycle scope. It is
created by a Product Factory from a Resolved Runtime Profile and admitted
resources and services.

A Product Runtime is not a global singleton. Process- or tenant-scoped services
may be shared, but Product, workspace, session, and channel state follow their
declared scopes.

### Active Product

The Product whose runtime owns the current Product Session and interprets the
current input, context, policy, artifacts, and presentation.

One Product Session has exactly one Active Product. A Platform or OEM may host
many Product Runtimes and Product Sessions concurrently.

### Product Session

A durable or ephemeral interaction scope owned by one Product and identified by
that Product's session schema and compatibility policy.

A Product Session records its `product_id` and the runtime selections required
for resume, fork, replay, diagnostics, and migration. Adding a capability does
not change the owning Product identity.

### Product Handoff

An explicit transfer of a Work item, artifact reference, or user intent from
one Product Session to another Product.

For example, Coding may create a deck artifact and hand it to a PPT Product
Session for canvas-level editing. A Product Handoff is not an in-place mutation
of the source session's `product_id`.

### Code-Enabled Product

A Product that mounts Product-approved, Product-neutral workspace, file,
process, Sandbox, Approval, or automation Capabilities without adopting the
Coding Product's domain identity or complete repository-engineering lifecycle.

Every Product may be code-enabled, but not every Product is the Coding Product.
Mounting Harness-owned read, list, search, write, edit, or process-execution
mechanisms does not create a second Product, change the active `product_id`, or
authorize unrestricted shell, network, package-install, or workspace access.
The owning Product still selects the capability packs, grants, roots, defaults,
prompt wording, artifact meanings, and presentation.

### Coding Product

The Product whose kernel owns the complete repository-engineering experience,
including Coding-specific prompts, tool-pack defaults, repository and Git
workflow, session compatibility, diagnostics, and Product presentation.

The accepted target Coding-specific mountable Capability IDs are `coding.arch`
and `coding.lsp`; matching Coding constants already exist, while the top-level
planner and live Mount graph do not. Workspace read, list, search, write, edit,
and process-execution facets belong to the Product-neutral
`harness.workspace` Capability selected and configured by Coding; they are not
Coding-owned merely because Coding was their first consumer. Other Coding-
exclusive Product Kernel semantics remain Product-owned even when they are not
expressed as mountable Capability IDs.

## OEM Model

### OEM

A branded or policy-specific Platform configuration that selects Products and
overlays their allowed configuration, resources, capabilities, models,
permissions, channels, and presentation.

An OEM is not automatically a Product. It becomes a Product only when it defines
a distinct Product Kernel and registers its own Product identity.

### OEM Package

An installable distribution that provides an OEM Descriptor or OEM Profile,
optional OEM CLI, resource overlays, extension contributions, branding, and
Product availability policy.

One OEM Package may enable and configure multiple Product Packages.

### OEM Profile

The data-only configuration that identifies an OEM's enabled Products, Default
Product, Product-specific overlays, shared extensions, branding, model policy,
and permission policy.

An OEM Profile must not contain live runtime objects or credentials.

### OEM Layer

An admitted set of OEM-owned selections or resources applied to a Product's
declared override points.

An OEM Layer cannot alter a capability slot sealed by the Product and does not
gain authority merely by being discovered.

### Multi-Product OEM

An OEM Profile that admits more than one Product, such as Coding and PPT, into
the same Platform Host.

Multi-Product means co-installed and routable Products. It does not mean that
one Product Session simultaneously has multiple owning Product identities.

### OEM Product

Use this term only when an OEM Package defines and registers a distinct Product
Kernel and Product identity.

Do not use OEM Product as a synonym for OEM Package, OEM Profile, a branded
Coding launch, or a Product with OEM overlays.

## Capability Composition

This section defines vocabulary. The binding, conflict, dependency, authority,
and lifecycle rules are defined by the
[Harness Capability Variation And Replacement Boundary](../architecture/harness/capability-variation-and-replacement-boundary.md).
Top-level dependency direction and Mount lifecycle are defined by the
[Capability Dependency And Mount Lifecycle](../architecture/harness/capability-dependency-and-mount-lifecycle.md)
decision.

### Capability

A named runtime or domain concern, such as a conversation store, memory
provider, compaction planner, tool definition, command descriptor, deck
renderer, or artifact handler.

### Capability ID

A stable owner-qualified identity for a top-level Capability, such as
`harness.workspace`, `harness.resources`, `harness.session`, `coding.lsp`, or
`coding.arch`.

A Capability ID names the definition and dependency target. It is not a live
Mount, implementation key, Python Protocol, permission, tool name, or Plugin
identity. Architecture documents may call it *mountable* when a Product exposes
Mount Policy for that Capability.

### Capability Bundle

The owner-composed runtime boundary that implements exactly one Capability ID.
It may contain tools, resources, typed public facet views, and private Binding
Facets with more detailed scope, refresh, selection, and diagnostic lifecycles.

One top-level Mount generation describes the public Bundle binding. Private
Facet generations remain authoritative for internal refreshes, and a Bundle
may hold explicit leases or stable references to broader-lived Facets. It must
not capture a shorter-lived concrete value across its safe boundary.

A Capability Bundle is not a Product Capability Bundle. The former implements
one Capability ID at runtime; the latter is an assembly or distribution
grouping that may deliver several Capability Bundles, resource families, and
Capability Packs.

### Harness Capability

A Product-neutral Capability whose public contract, reusable mechanism, or
explicitly overridable platform default is owned by Harness. Examples include
authorized process launching, workspace operations, resource discovery,
approval coordination, runtime-profile resolution, and shared lifecycle
mechanics.

`Harness Capability` is the canonical owner-oriented term. `Shared capability`
may describe its cross-Product reuse, but it is not a Plugin manifest kind or a
separate activation object. Shared does not mean global singleton, mandatory
for every Product, or identically configured by every Product. Products still
own domain defaults, admission, activation, policy, and presentation unless a
specific boundary says otherwise.

### Product Capability Requirement

An opaque Product-level request for a named capability, declared by an admitted
Skill, Method, Work plan, Session operation, or Product default. A requirement
does not name executable handlers, select a Harness implementation, grant
authority, or imply activation. The Active Product resolves it through its
admitted capability catalog and policy.

### Capability Dependency

A declared requirement from one Capability ID to another. In architecture
graphs `A -> B` means A depends on B. The depended-on Capability binds first and
disposes last.

A dependency may request a narrow facet view, but that view does not create a
new top-level node or grant authority. Permissions, configuration values, and
injected implementation Protocols are not Capability dependencies.

### Binding Facet

An owner-private selection, provider, contribution family, or lifecycle unit
inside a Capability Bundle. Runtime Profile slots such as `prompt.sections` or
`interaction.side_question` may act as Binding Facets without becoming
top-level Capability IDs.

A Binding Facet can retain focused selection, refresh, snapshot, and diagnostic
semantics. Its owner projects an aggregate Capability state to the top-level
graph.

### Capability Slot

A Product-declared location at which one or more implementations of a
Capability may bind. The slot defines composition shape, lifecycle scope,
refresh boundary, and allowed contribution sources. When the slot exposes
replaceable or composable behavior, `variation_semantic` separately records
Aggregate Contribution, Ordered Interception, or Exclusive Replacement.

A Capability Slot is not automatically a top-level Capability dependency node.
It may be a private Binding Facet of a coarser Capability Bundle.

### Runtime Capability Shape

The profile-resolution cardinality and identity rule declared by a
`RuntimeCapabilitySlot`: `single`, `exclusive`, `ordered`, or `append_only`.
Shape answers how selections are retained and bound; it is separate from the
behavioral variation semantic applied by the resolved provider or extension
surface.

An `ordered` shape can feed either Aggregate Contribution or Ordered
Interception. A `single` or `exclusive` shape can supply one provider without
implying that every source is allowed to replace it. `exclusive` additionally
requires a sealed refresh boundary. `append_only` retains repeated selections
where the owning aggregate contract permits them.

### Capability Provider

A factory, adapter, or live implementation that can satisfy a Capability Slot
after discovery, admission, and resolution. A provider does not acquire
authority merely by being installed or discovered.

### Override

An umbrella term for an allowed variation of a Product or platform default.
`Override` does not define a conflict rule. Architecture documents must name
the applicable Aggregate Contribution, Ordered Interception, Resource Overlay,
or Exclusive Replacement semantic instead of relying on unspecified
last-write-wins behavior.

Runtime Capability Shape and variation semantics are orthogonal. Architecture
documents must record both when a runtime-profile slot binds replaceable or
composable behavior.

### Aggregate Contribution

A composition semantic in which every admitted contribution remains active
and the owning Product or Harness mechanism combines them deterministically.
Tools, commands, hooks, and server-definition catalogs may use this semantic
when their owning boundary permits multiple entries.

### Ordered Interception

A composition semantic in which admitted handlers form an explicit ordered
pipeline. Each handler delegates to, observes, or transforms the next result
under a declared error policy. Ordering is part of the resolved contract and
must not depend on incidental discovery order.

### Decoration

A restricted form of Ordered Interception that wraps an already resolved
capability without taking ownership of its selection. Tracing, metrics, and
caching are typical decorators. A decorator must preserve the underlying
authority and lifecycle contract and cannot weaken an invariant enforcement
layer.

### Exclusive Replacement

A composition semantic in which exactly one admitted provider is active for a
declared variation surface. Selection is explicit and explainable: the owning
surface may define deterministic precedence, require a named provider, or
reject candidates that its policy cannot disambiguate. It must not rely on
incidental last-write or discovery order. When profile-bound, Runtime
Capability Shape independently governs selection retention and refresh. Any
fallback is selected by the owning Product or Platform policy.

### Protocol Injection

Composition-root wiring of an implementation through a stable Protocol or
public capability contract. Runtime invocation of the injected object does not
create a reverse source dependency: Harness must not import or interpret a
Product implementation that was injected through a neutral contract.

### Composition Root

The outer lifecycle owner that discovers, admits, resolves, constructs, binds,
and disposes a runtime object graph. A composition root may know concrete
implementations from multiple layers; the composed layers must continue to
depend only on their public inward-facing contracts.

### Invariant Enforcement Layer

A non-bypassable wrapper that preserves authority, approval, sandbox,
resource-limit, validation, or cleanup guarantees around a replaceable
provider or private mechanism. Product and Plugin variation may tighten these
guarantees but cannot replace or weaken the enforcement layer.

### Trusted Backend Substitution

Replacement of a private mechanism by an explicitly trusted Platform
composition point. This is not an ordinary Plugin right and exists only where
the owning boundary deliberately publishes such a seam.

### Capability Pack

One Product-approved, ordered contribution group for a single capability item
family after runtime-profile admission.

In code, `CapabilityPack[T]` contains a `pack_id`, source, priority, enabled
state, and ordered `T` items. Tool packs and command packs are examples.

A Capability Pack is not an installable archive, Product Package, Plugin, or
multi-family bundle. It does not discover contributions or grant authority.

### Product Capability Bundle

An assembly or distribution-level grouping of several related capability and
resource families that can be admitted into a Product.

For example, a `ppt-authoring` Product Capability Bundle may provide Skills,
prompt fragments, tool and command Capability Packs, deck assets, renderers,
and artifact handlers. Each family still passes through its own Product-owned
admission, trust, composition, and lifecycle rules.

A Product Capability Bundle does not become the Active Product. If PPT-specific
canvas state, session compatibility, compaction, approval, or artifact lifecycle
is required, use the PPT Product and an explicit Product Handoff.

A Product Capability Bundle is not a top-level Capability DAG node. Its
contents enter their owner-defined Capability Bundles, resource overlays, or
Capability Pack admission paths independently.

### Capability Mount

The Product-owned act and resulting binding by which an admitted Capability
Bundle becomes available in a specific runtime scope.

A Capability ID such as `coding.lsp` names the definition; it is not itself a
Mount. A concrete Mount combines that Capability ID with a process, tenant,
workspace, Session, turn, or Channel scope instance and a live generation.

### Mount Policy

Product policy that decides when an admitted Capability is mounted. Common
values are `disabled`, `on_demand`, and `always`. Mount Policy does not select a
provider, grant authority, or identify a live runtime instance.

### Mounted Capability

One admitted Capability Bundle bound to a concrete runtime scope. For example,
`coding.lsp@session:session-42` is a useful diagnostic label for one Mounted
Capability, while `coding.lsp` remains its Capability ID.

Scoped Mounts from Product defaults, manual selection, Skills, and Method/Work
steps are additive and independently owned; releasing one scope must not remove
another scope's request. A Mounted Capability owns or imports the lifecycle
required by its declared dependencies. It is unrelated to an AppService
control lease.

For example, Coding may activate the `ppt-authoring` Product Capability Bundle
while remaining the Active Product. Its admitted contents may contribute
resources and Capability Packs or request owner-defined Capability Mounts. The
Product Session should snapshot continuity-critical Mounted Capability
identities, compatible versions, and separately activated bundle provenance.

## Package, Plugin, Extension, And Resource Model

### Package

An overloaded implementation word that must be qualified in architecture
documents.

Use Product Package for an installable Product, OEM Package for an installable
OEM configuration, and Resource Package for an installable resource
collection. Use Python package only for the Python import/distribution concept;
it does not imply a Loushang Resource Package, Plugin, or Product Package. Do
not use unqualified Package when ownership matters.

### Resource Package

An installable or materialized collection of resources such as Skills, prompts,
themes, extensions, and Product-specific assets.

A Resource Package contributes content to an admitted Product. It does not
register or start a Product unless it also implements the separate Product
Package registration contract.

### Plugin

An optional, independently enabled contribution source resolved into resource
roots and, where supported, extension contributions.

A Plugin runs under Product and OEM activation and trust policy. It does not own
the Product lifecycle, select the Active Product, or acquire execution authority
merely by being installed. A Plugin is the manifest-backed identity and
activation boundary, not the installed bytes or materialized directory itself.

### Extension

Executable or declarative optional behavior contributed through a defined
extension surface, such as a Tool, command, hook, policy interceptor, approval
replacement, renderer, or channel adapter.

An Extension is one possible contribution carried by a Plugin or Resource
Package. Product or OEM policy decides whether it is admitted and active. An
Extension does not become a Product or acquire execution authority merely
because its descriptor was discovered.

The canonical resource relationship is:

```text
plugin source -> plugin manifest -> resource package root -> resource descriptors
                                                        -> extension descriptors
```

Not every Resource Package is a Plugin: a configured package root can be
consumed directly. Not every Plugin carries an Extension: it may provide only
Skills, prompts, themes, or assets. Not every Extension needs a dedicated
Package: built-in Product resources may contribute one through their existing
Product Package.

### Skill

An instruction resource that teaches the model a specialized workflow,
domain convention, or Tool-usage pattern.

A Skill is Product content or an optional contribution. It is not executable
authority, a Product, or a replacement for a Tool or Extension.

### Product Asset

A Product-interpreted file used to create or present domain artifacts, such as
a deck template, slide layout, brand kit, image, document template, or design
asset.

Harness may discover and track the asset as a resource, while the Product owns
its semantic type, validation, preview, activation, and artifact behavior.

### Deck Asset

A PPT-domain Product Asset, such as a presentation template, slide layout,
master, theme, brand kit, or reusable media item.

A Deck Asset may be shipped with the PPT Product, an OEM overlay, or a
Product Capability Bundle. It is not a Skill and should not be modeled as one
merely to reuse relative filesystem paths.

## Canonical Launch Interpretations

### Neutral Platform Launch

```text
loushang
  -> resolve Default OEM
  -> resolve that OEM's Default Product
  -> create the selected Product Runtime
```

### OEM-Branded Launch

```text
acme
  -> start the shared Platform Host with OEM Profile "acme"
  -> select Product "coding"
  -> activate admitted OEM and ppt-authoring bundle contributions
```

In this example, `coding` remains the Active Product. The OEM Profile and
activated Product Capability Bundle provenance and resulting Mounted Capability
identities are recorded separately.

### Full PPT Launch Or Handoff

```text
loushang ppt
  -> select Product "ppt"
  -> create a PPT Product Session
```

Use this path when PPT owns the session, canvas, deck lifecycle, compaction,
policy, or presentation semantics.

## Relationship Rules

- Harness provides mechanisms; Products provide domain defaults and semantics.
- A Product Package registers a Product; a Plugin contributes to a Product.
- An OEM Package may configure multiple Product Packages.
- One Platform Host may run multiple Products concurrently.
- One Product Session has exactly one Active Product.
- A Product may activate many admitted Capability Packs and Product Capability
  Bundles; only owner-defined Capability IDs produce Mounted Capabilities.
- A Product Capability Bundle augments a Product; it does not silently replace
  it.
- Product Handoff crosses Product-session boundaries explicitly.
- Installation, discovery, admission, activation, and execution are separate
  lifecycle decisions.

## Terms To Avoid

### Product Plugin

Avoid this term because it conflates Product registration with optional Plugin
contribution. Use Product Package unless the subject specifically implements
both contracts, and name both roles explicitly.

### PPT Skill Pack

Avoid this term when the package also contains Tools, commands, renderers, or
deck assets. Use `ppt-authoring` Product Capability Bundle. Use Skill pack only
for a collection containing Skills.

### OEM Product

Avoid this term for a branded launcher or Product overlay. Use OEM CLI, OEM
Profile, OEM Package, or Product with OEM Layer as appropriate.

### Multi-Product Session

Avoid this term. Use Multi-Product OEM for deployment availability, Product
Handoff for cross-Product transfer, or Composed Product if a genuinely new
Product Kernel owns the unified session.

### `loushang.<OEM>.cli`

Treat this as a possible Python module path, not an architecture concept or
required packaging convention. The canonical concepts are OEM CLI, OEM
Descriptor/Profile, registered launch entry point, and shared Platform Host.
