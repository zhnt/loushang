# Unified Product, Package, And Plugin Architecture

## Status

- Authority: proposed — non-normative cross-system architecture draft
- Design status: proposed, revised after three independent architecture reviews
  and rebased onto an explicit post-CLA8 planning assumption
- Later refinement: source authority, installation scope, release provenance,
  execution shape, contribution selection, and mutable component data were
  clarified after the prior reviews; those refinements still require normal
  architecture acceptance
- Scenario baseline: CLA0 through CLA8 are assumed complete, integrated, and
  green; this is a planning premise, not a claim about the control lane
- Implementation status: proposed ecosystem control plane not implemented;
  the assumed CLA8 runtime-composition closure is an input, not a U-series
  deliverable
- Owners affected: Harness host and CLI, Product, OEM, resources, extensions,
  capabilities, configuration, and a distribution owner still requiring an
  accepted boundary decision
- Scope: manifest, distribution, lifecycle, configuration, explanation,
  publishing, and Python authoring

This document proposes a common product and plugin experience. It does not
replace accepted architecture, current source, or executable lifecycle gates.
A decision becomes authoritative only after adoption by the appropriate
architecture record and owner documents.

Where this document says "post-CLA8 baseline," it evaluates the requested
hypothesis that CLA0 through CLA8 have all completed and integrated. If an
actual integration lacks one of those closure properties, that mismatch is a
blocking prerequisite; implementations must not add a compatibility authority
inside this proposal to compensate for it.

## 1. Executive Decision

Loushang should present one ecosystem experience for Products, OEM Profiles,
Plugins, Capability Providers, Extensions, Resources, and their distribution
artifacts, while preserving their distinct runtime meanings and authorities.

The central rule is:

> Unify the static manifest, distribution transaction, desired-state controls,
> configuration envelope, explanation, and publication experience. Do not
> collapse all runtime authority into one plugin manager, one state machine, or
> one composition planner.

The assumed post-CLA8 Session Capability Graph is therefore the sole Mount
transaction foundation for migrated top-level Capability Bundles. This
proposal adds declarations, distribution, admission, and operations around
that foundation. It does not reopen graph ownership, rebuild the completed CLA
composition sequence, or create a package/plugin-owned peer Binder.

Coding can therefore become plugin-like in distribution and operations: its
Product Descriptor and Factory are discovered from an admitted Product
Package, not hard-coded into the generic process entry. Coding remains a
Product, not an Extension or an ordinary Plugin. One Coding Product Runtime
still owns each Coding Product Session.

The common user journey is a navigation model, not a shared lifecycle:

```text
discover -> inspect -> verify -> install -> configure -> enable/select
         -> run -> explain -> update -> disable/drain -> uninstall/retire
```

Only actions meaningful to a subject are exposed. For example, a distribution
artifact is installed, a Plugin activation identity is enabled, a Product is
selected, a declaration is admitted, a Capability Provider is bound, its
Capability Bundle is mounted, and a Session is active. The status UI correlates
those facts; it does not turn them into one authoritative object state.

The typed runtime relationship remains:

```text
Product Package / OEM Package / Resource Package delivers artifacts
  -> Product or OEM declares domain identity and policy
  -> Plugin provides an independently enabled activation identity
  -> Extension contributes behavior
  -> Capability Provider implements a Capability contract
  -> Resource contributes content
  -> existing owner runtimes admit, bind, publish, and dispose each part
```

## 2. Problem Statement

Loushang contains most of the individual mechanisms needed for a plugin-first
ecosystem, but they do not form one user-facing control plane:

- the generic process entry still resolves directly to Coding;
- Product Package discovery and the neutral Product Registry/Router path are
  not integrated;
- resource package, Plugin, Extension, capability-provider, configuration, and
  Product declarations do not share one static manifest envelope;
- installation, authenticity, execution trust, enablement, admission,
  authorization, selection, and mounting are easy to conflate;
- the post-CLA8 graph explains Mount and Consumer facts, but artifact,
  desired-state, Product/OEM, admission, and publication facts still lack one
  authorized correlation surface;
- Python decorators exist for tools, but there is no consistent source-side
  authoring aid for Product, Plugin, Extension, and Capability Provider
  factories;
- publication lacks one validation, compatibility, signing, provenance, and
  catalog flow.

The desired outcome is not "everything is the same plugin." It is "every
installable artifact participates in the same ecosystem protocol."

## 3. Truth Planes

### 3.1 Actual Current Facts

The Current plane for this document is the control lane's `main` branch unless
an item explicitly names a development lane. Current source and executable
gates remain more authoritative than this summary.

- `harness.resources` owns the standard layout, resource-oriented package
  catalog/materialization, Plugin mechanics, and resource discovery.
- Current resource package session operations perform materialize, register,
  refresh, update, remove, and uninstall flows. They do not implement the
  immutable artifact generations, retirement leases, or rollback semantics
  proposed here.
- `harness.extensions` owns the current Extension categories and reversible
  activation mechanics.
- Layered configuration, schema codecs, and scoped configuration activation
  exist under the current configuration owner.
- Capability Planner, Binder, Runtime, Projector, Provider bindings, and
  Registration Scopes exist. Current source determines how much of the
  composition-lifecycle sequence is integrated at any moment.
- This revision deliberately does not promote an in-flight CLA branch into the
  Current plane. Section 3.2 instead records the explicit hypothetical baseline
  requested for evaluating the unified architecture.
- `@tool()` attaches a `DecoratedToolSpec` and later compiles it through an
  explicit authoring path. Its frozen dataclass may still contain mutable
  members, so this proposal reuses the delayed-compilation pattern, not a claim
  that arbitrary decorator metadata is deeply immutable.
- the published `loushang` entry point currently targets Coding directly;
  logical multi-Product discovery and physical Product distribution are not
  complete.

### 3.2 Assumed Post-CLA8 Baseline

For the remainder of this proposal, CLA0 through CLA8 are treated as completed
and integrated with their closure gates green. The resulting baseline is:

- one Product Session composition root owns one
  `RuntimeCapabilityGraphRuntime`; only `RuntimeCapabilityGraphBinder` mutates
  its Mount generations, and the Projector remains read-only;
- Model Input, Resources, Workspace, and the accepted `harness.session` Bundle
  participate in that Session-owned graph through Definition / Provider /
  Consumer seams and focused facet captures;
- admitted initial Extension declarations enter the final pure graph plan
  through the completed declaration bridge, while content-only
  Extension/Resource refresh retains its separate owner generation and does
  not fabricate a new Mount generation;
- a graph-owned executable Provider change is rejected as
  `restart_required` before Resource, Extension, Registration, or Mount
  publication, unless a later accepted dependent-closure replacement protocol
  explicitly changes that rule;
- migrated slots have no peer `RuntimeProfileBinder`, resource compatibility
  runtime, private graph, or supported Product construction path claiming the
  same live Bundle authority;
- graph construction failure and cancellation roll back staged Provider values
  and Registration Scopes, prior authoritative generations remain visible,
  Consumer leases are invalidated on retirement, and retryable cleanup is
  retained and joined by Session shutdown;
- effective-runtime and Capability explanation projects the committed graph,
  registrations, source generations, and Consumer facts without becoming a
  lifecycle authority.

This baseline closes runtime composition authority only. It does **not** supply
an artifact resolver, immutable distribution store, unified manifest,
Product/OEM package discovery, Plugin desired-state migration, execution trust,
publisher verification, or public marketplace. Those remain the U-series
delta.

### 3.3 Accepted Product And Host Dependencies

This proposal depends on accepted targets that remain owned elsewhere:

- product-neutral host and CLI mechanics belong to Harness host/CLI scope;
- OEM selection precedes Product routing;
- Product Registry contains admitted, data-only Product Descriptors;
- Product Router selects one Product for a Product Session;
- Product Factory owns Product assembly from an admitted, resolved runtime
  profile;
- one Product Session has exactly one active Product;
- the accepted composition flow reuses Runtime Profile resolution, Extension
  admission, the completed Session graph Planner/Binder path, focused Consumer
  facet capture, and Session activation;
- composed diagnosis never becomes a lifecycle authority.

### 3.4 Proposed Target

The proposed delta is a declarative distribution and operations plane that:

1. defines a versioned `loushang.toml` artifact manifest and canonical static
   intermediate representation;
2. resolves artifacts into an immutable store and reproducible lock generation;
3. records desired state separately from owner runtime facts;
4. admits each typed declaration before projecting it to its existing owner;
5. lets the Harness Host discover admitted Product Descriptors without
   importing Coding;
6. joins owner facts into authorized, redacted explanation;
7. validates source-side factory decorators against the published manifest;
8. packages, signs, verifies, and publishes reproducible artifacts;
9. migrates Coding first logically, then physically, without a dual authority.

## 4. Canonical Vocabulary And Ownership

No single "primary authority" column is sufficient because definition,
admission, runtime publication, and presentation are deliberately separate.

| Concept | Meaning | Definition / policy owner | Mechanism / live-state owner |
| --- | --- | --- | --- |
| Harness Host | Product-neutral process composition root | Harness architecture | `harness.host` / `harness.cli` target scope |
| Product | Domain identity and runtime contract, such as Coding | Product | Product Runtime and Product Session owners |
| OEM Profile | Trusted distribution selection, overlay, branding, and ceilings | OEM under Harness Host security policy | Harness Host applies selection; downstream owners apply admitted inputs |
| Product Package | Installable distribution role providing Product Descriptor, Factory, Adapter, plan, and built-ins | Product plus proposed distribution contract | Distribution owner; then Product/Harness owner bridges |
| OEM Package | Installable distribution role providing an OEM Profile and permitted overlays | OEM plus proposed distribution contract | Distribution owner; then Harness Host admission |
| Resource Package | Resource materialization root, with or without a Plugin manifest | Resource/package contract | `harness.resources.packages` |
| Plugin | Manifest-backed optional identity enabled independently from installed bytes | Plugin declaration plus Product/OEM policy | `harness.resources.plugins` mechanics and admitted owner contributions |
| Extension | Executable or declarative contribution, interceptor, or replacement | Extension-surface owner | `harness.extensions` and exact registration scopes |
| Capability | Stable, owner-qualified ability contract | Capability namespace owner; for example Coding owns `coding.lsp` | Harness owns shared graph mechanics; Product owns admission and Mount policy |
| Capability Provider | Versioned implementation of one Capability contract | Contract owner and Provider publisher | Existing capability Planner/Binder/Runtime after admission |
| Resource | Content with identity, provenance, and precedence | Content publisher and Product policy | `harness.resources`; Product owns projection and presentation |
| Registration | Reversible publication into one registry | Registry owner | Exact `RegistrationScope` or owner-specific lease |

Product, OEM, Package, Plugin, Extension, Capability, and Resource are
orthogonal dimensions. The physical carrier must state every role it
implements; one role is not inferred from another. This draft does not create
the non-canonical semantic type "Plugin Package." The canonical description is
usually "a Resource Package carrying a Plugin manifest."

Operational placement is orthogonal to those domain roles. Source authority,
installation scope, release provenance, and execution shape are defined in
Section 7 and must not be compressed into a single `source`, `embedded`,
`trusted`, or `local` enum. In particular, a local path is neither a trust fact
nor proof that the Host owns the filesystem from which it was discovered.

The proposed distribution artifact envelope is also distinct from the current
resource-oriented Package runtime. The final ownership decision must choose one
of these before implementation:

- extend the existing Harness package owner with a product-neutral artifact
  transaction port; or
- add a separately named Harness distribution owner whose admitted outputs
  project one-way into Product, OEM, and Resource Package owners.

It must not create two catalogs that both claim runtime or trust authority.

## 5. Target Architecture

```text
Local path / fixed Git artifact / fixed wheel / registry artifact
                           |
                           v
             Artifact Resolver + Verifier
                           |
                           v
          Immutable Artifact Store + Lock Generation
                           |
                           v
 Installed Artifact Candidate Catalog (untrusted candidates allowed;
                       no Python import)
                           |
                           v
       Trust + compatibility + Product/OEM admission
              |             |              |
              v             v              v
 admitted Product/OEM   admitted Plugin/   admitted Provider/
 static declarations    Extension inputs   Resource inputs
              |             |              |
              v             v              v
 admitted Product       existing Extension, Resource, Capability,
 Descriptor Registry    and Configuration owner adapters
              |
              v
 Harness Product Router -> Product Factory -> one Product Runtime/Session

Session composition reuses the accepted owner flow:

Product / OEM / admitted package declarations
  -> Runtime Profile resolution
  -> bootstrap-only source discovery
  -> Extension discovery and admission
  -> existing RuntimeCapabilityGraphPlanner
  -> existing RuntimeCapabilityGraphBinder
  -> Consumer facet capture
  -> Session activation

Every owner snapshot -----------> authorized Explain projection
```

There is no new universal `Composition Planner`. Static manifest compilation
only creates immutable declaration facts and owner-specific inputs. The exact
synchronous Product Factory construction point relative to asynchronous graph
publication remains a Product/Harness boundary decision; this draft does not
define a competing order.

The architecture has five planes:

1. **Distribution** resolves, verifies, stores, and locks artifact bytes.
2. **Admission** authenticates the artifact, evaluates execution trust,
   compatibility, OEM/Product policy, and per-declaration grants.
3. **Owner projection** converts admitted static declarations into inputs for
   current Product, Resource, Extension, Capability, and Configuration owners.
4. **Runtime** keeps live instances, Mount generations, registrations, owner
   generations, artifact leases, and Session teardown with their current
   authorities.
5. **Observation** joins owner facts without becoming a second source of truth.

## 6. Unified Manifest

### 6.1 Artifact Envelope And Orthogonal Declarations

Every published artifact contains a root `loushang.toml`. Its `[artifact]`
section identifies delivered bytes; it is not a runtime activation kind.
Product, OEM, Plugin, Extension, Capability Provider, Resource, and
configuration declarations remain separately typed.

Manifest v1 may impose a conservative publication matrix, but that is a
validation restriction rather than a statement that the dimensions are the
same:

| Canonical distribution role | Required declaration | Optional declarations in v1 |
| --- | --- | --- |
| Product Package | exactly one Product | Product-owned Resources and Capability Providers |
| OEM Package | exactly one OEM Profile | trusted overlays and Resource/Plugin references permitted by the OEM contract |
| Resource Package | one or more Resources, or an explicit empty resource root | at most one Plugin identity and its Extensions or Capability Providers |

There is no standalone "Provider Package" in v1. A Capability Provider is
carried by a Product Package or by a Plugin-identified Resource Package so its
desired-state and admission identity are explicit. A future provider-only role
requires its own operator lifecycle decision first.

An artifact that implements more than one canonical role must declare each role
and pass a published combination matrix. Nothing is inferred from a Python
entrypoint. A pure prompt, Skill, theme, or asset Resource Package does not need
a Plugin identity.

### 6.2 Illustrative, Non-Normative Product Package

```toml
manifest_version = 1

[artifact]
id = "org.loushang.coding"
version = "1.0.0"
publisher = "org.loushang"
license = "Apache-2.0"

[compatibility]
host_api = ">=1,<2"
python = ">=3.12"

[product]
id = "coding"
display_name = "Loushang Coding"
product_version = "1.0.0"
product_api = ">=1,<2"
factory = "loushang.coding.product:create_product"
adapter = "loushang.coding.product:CodingProductAdapter"
runtime_plan = "resources/runtime-plan.toml"

[config]
schema_version = 1
schema = "resources/config.schema.json"
defaults = "resources/defaults.toml"

[[capability_providers]]
id = "coding.arch.default"
capability = "coding.arch"
contract = ">=1,<2"
implementation_version = 1
facets = ["query", "explain"]
requires = []
requested_authorities = ["workspace.read"]
factory = "loushang.coding.arch:create_provider"

[[resources]]
id = "coding.prompts.system"
kind = "prompt"
path = "resources/prompts/system.md"
```

The Product Descriptor is static manifest data. The `factory` and `adapter`
are executable references imported only after admission. There is no
`descriptor = module:object` shortcut that would make Product discovery depend
on Python import.

The Capability Provider block above is pseudocontract documentation, not a
frozen manifest-v1 schema. Its exact field mapping, phase, refresh behavior,
dependency facts, factory context, and disposal semantics must be frozen by the
capability owner bridge before this example becomes a schema commitment.

### 6.3 Illustrative Resource Package Carrying A Plugin

```toml
manifest_version = 1

[artifact]
id = "com.example.code-review"
version = "2.1.0"
publisher = "com.example"

[compatibility]
host_api = ">=1,<2"
products = { coding = ">=1,<2" }

[plugin]
id = "com.example.code-review"

[[extensions]]
id = "com.example.code-review.commands"
category = "contribution"
target = "coding.commands"
factory = "example_review.commands:create_extension"
requested_authorities = ["workspace.read"]

[[resources]]
id = "com.example.code-review.prompt"
kind = "prompt"
path = "resources/review.md"
```

Removing `[plugin]` and `[[extensions]]` produces a valid declarative-only
Resource Package in v1.

### 6.4 What The Manifest Contains

The manifest may contain:

- stable identities and artifact version;
- static, data-only Product and OEM descriptors;
- compatibility and dependency constraints;
- inert executable-entrypoint strings;
- per-declaration requested authorities;
- Plugin, Extension, Capability Provider, and Resource declarations;
- configuration schema and default-resource references;
- publication metadata and detached-envelope references.

It must not contain:

- credentials or unredacted secrets;
- live Python objects or arbitrary Python expressions;
- runtime state, activation results, local grants, or Session identities;
- trust or admission decisions made by the local installation;
- implicit import-time registration;
- a signature that recursively claims to authenticate itself.

Parsing, cataloging, validation, compatibility evaluation, and explanation must
work without importing artifact Python code.

### 6.5 Canonical Static IR And Owner Bridges

The manifest parser emits one versioned, immutable `ManifestIR` containing
artifact provenance and typed declaration records. U1 does not claim that all
corresponding runtime descriptor classes already exist.

| Declaration | Static compiler result | Owner bridge after admission |
| --- | --- | --- |
| Product | data-only Product declaration IR | accepted Product Descriptor/Factory input |
| OEM | data-only OEM declaration IR | accepted OEM Profile input |
| Plugin | Plugin declaration IR | existing `PluginManifest`-compatible input |
| Resource | typed resource declaration IR | current prompt/Skill/Extension/theme-specific resource descriptors |
| Extension | Extension declaration IR | current `ExtensionDescriptor` and Extension admission path |
| Capability Provider | Provider declaration IR | accepted CLA declaration bridge, then existing capability Provider/binding inputs |
| Configuration | schema/default references | current layered config and owner codec inputs |

Each adapter is owned and versioned by the destination subsystem. The compiler
does not construct Providers, allocate Registration Scopes, publish resource or
Extension generations, choose a Product, or mount a Capability.

## 7. Identity, Versioning, Scope, And Reproducibility

Stable IDs are owner-qualified where globally shared:

- artifacts, Plugins, Capability Providers, and Extensions use
  publisher-qualified IDs;
- Capabilities use stable namespace-owner IDs such as `coding.lsp`;
- Products and OEM Profiles use registry-unique IDs;
- Resources use package-qualified IDs or the current owner canonical key.

The following versions are independent:

- manifest schema version;
- artifact version and digest;
- Host API range;
- Product API range;
- Capability contract range;
- Provider implementation version;
- configuration schema version;
- Explain JSON schema version.

Four operational axes are also independent:

| Axis | Meaning | Examples |
| --- | --- | --- |
| Source authority | The owner through which bytes and metadata must be listed and read | Host; an exact Executor; an Orchestrator; a future owner-qualified provider |
| Installation or selection scope | Where installed bytes, desired state, or an admitted session selection applies | `managed`, `user`, `project`, `local`, `session` |
| Release provenance | Evidence about how exact bytes entered the system | immutable Host release, authenticated publisher, integrity-pinned unattributed source |
| Execution shape | How an admitted declaration executes | data-only, one-shot process, isolated Worker, explicitly host-equivalent in-process |

V1 may implement only Host-owned materialized artifacts, `user` and `project`
installation/desired-state scopes, and `session` selection overrides. The data
model nevertheless retains a source-authority identity and opaque resource
locator. If a later Executor or Orchestrator contributes a root, every read must
go through that authority; a Host path reconstructed from its locator is
invalid. Resolution produces an inert descriptor and never activates a
component.

Desired state and locks are scoped explicitly. V1 supports `user` and
`project`; `session` overrides may select already admitted artifacts but do not
install bytes. `managed` and `local` are reserved until their precedence and
policy owners are accepted. Every command reports its resolved scope and source
authority separately. An optional named environment/profile may group a lock
generation and desired-state set; it does not become a filesystem authority or
trust root.

A lock generation records exact artifact versions and hashes, fixed sources,
dependency artifact hashes, manifest digest, target platform compatibility, and
the preceding generation ID. It records verification evidence but never grants
trust. Trust roots and publisher policy live in a separately protected owner.

A Product Session pins:

- exact lock generation;
- exact artifact graph and execution-environment fingerprint;
- Product and OEM identities;
- effective desired-state revision and policy revision;
- admitted declaration and Mount fingerprints.

The Session never reinterprets its executable code from the mutable current
lock.

## 8. Distribution Transactions And Artifact Store

### 8.1 MVP Source Policy

The first deliverable supports built-in artifacts authenticated by the Host
release and local-path artifacts integrity-pinned to an exact digest. Local
executable entrypoints additionally require the explicit execution-trust grant
defined below. Git, Python indexes, registries, remote executable code, and
source distributions are later gates, not MVP defaults.

For remote support:

- Git resolves to a fixed commit and locks the resulting artifact digest;
- Python indexes resolve fixed wheels per platform with hashes;
- source distributions and build hooks are denied unless an accepted isolated
  builder produces a separately verified artifact;
- inspect/install never invokes PEP 517, setup hooks, package imports, or
  decorators;
- archive traversal, symlink/hardlink/device entries, decompression limits, and
  credential-bearing URLs are validated before store commit.

### 8.2 Transaction

```text
resolve source metadata
  -> fetch inert bytes into bounded staging
  -> validate archive paths and size limits
  -> compute complete artifact digest
  -> parse manifest as untrusted data
  -> verify required source evidence and, when required, detached signature
  -> evaluate compatibility and local source policy
  -> commit immutable artifact
  -> construct complete candidate lock generation
  -> atomically publish one generation pointer with CAS
```

Integrity verification proves which bytes were staged. Publisher authentication
proves identity only when policy validates a signature or equivalent trusted
release envelope. Neither grants execution trust, enables a Plugin, admits a
declaration, authorizes a Capability, selects a Product, binds a Capability
Provider, or mounts its Capability Bundle.

Built-in artifacts may inherit authentication evidence from the signed Host
release containing their exact digest. An unsigned local-path artifact is
`integrity_verified` but `publisher_unattributed`; it can run only after a
protected, explicit execution-trust grant binds its exact digest, entrypoint,
and execution environment. This is the local MVP path and does not pretend that
an unsigned artifact has publisher authentication.

The detached signed envelope covers canonical manifest bytes, complete artifact
digest, artifact ID/version, dependency artifact hashes, resource/entrypoint
inventory, and SBOM/provenance digests. Trust-root, key rotation, revocation,
freshness, and offline policy require an accepted supply-chain decision before
remote executable artifacts are supported.

### 8.3 Store And Current Resource Package Compatibility

The store is content-addressed or version-immutable. Its exact location and
owner are unresolved until the distribution boundary decision. The examples
below are logical, not a commitment to one global home file:

```text
<scope-home>/artifacts/<artifact-id>/<digest>/
<scope-home>/locks/<generation-id>.json
<scope-home>/current-lock
<scope-home>/desired-state/<revision>.json
```

Current `harness.resources.packages` operations cannot be reused as the new
transaction authority: current install refreshes resources, and current
update/remove paths replace or delete materialization without the proposed
artifact leases. They may be reached only through a legacy Resource Package
adapter after the new staged install/commit/retire port and `ArtifactLease`
enforcement are accepted. U2 may define this adapter but does not invoke it to
publish a runtime Resource snapshot.

The artifact catalog and lock generation use one durable transaction or one
atomic generation pointer with crash recovery. Plugin desired state remains a
separate Config-owner transaction because installation must not change it. A
cross-owner operation uses a durable operation ID and explicit compensation; it
does not claim a fabricated global transaction.

### 8.4 Mutable Component Data Is Not Artifact Content

Installed artifact bytes, prepared dependency environments, and generated
adapters are immutable revisions. A Plugin, Resource, Extension, or Provider
must never write runtime data into those revisions. Mutable data has four
different meanings and remains separately owned:

| Data class | Semantics | Lifetime owner |
| --- | --- | --- |
| Rebuildable cache | Safe to discard and recompute | Exact Product/component owner under quota and lease |
| Durable component state | Schema-versioned state that may outlive one artifact revision | Exact domain/state owner |
| Credential reference | Opaque reference to separately protected secret material | Credential/secret owner |
| Business Artifact | User-visible result with explicit publication and retention | Existing Artifact owner |

There is no universal writable `plugin_data_dir` capability. A common
`ComponentDataRequest` may carry subject, Product/Profile, tenant/workspace,
data class, schema version, quota, and retention intent, but the destination
owner decides whether to return a bounded store facet, an attempt-scoped mount,
or no access. A Worker receives only the accepted facet or mount and its lease;
in-process code does not gain an ambient global data path.

Durable state identity is revision-independent but subject-qualified, so an
update cannot silently fork or adopt another Plugin's state. Schema migration,
rollback compatibility, backup/export, deletion, and recovery are explicit
domain operations. Disabling a Plugin does not delete state; uninstalling or
collecting artifact bytes does not imply state deletion; state deletion is a
separate authorized operation. Failed migration preserves the previous usable
revision and retains all state/artifact leases needed for repair or rollback.

Physical storage may be shared as an implementation detail, but it is not a new
lifecycle, configuration, desired-state, or publication authority.

## 9. Layered Lifecycle Model

There is no universal linear state machine. The common status envelope joins
owner-specific sub-states and labels each fact with `subject_kind`, `subject_id`,
`owner`, `revision`, and `fact_reference`.

| Layer | Authoritative states |
| --- | --- |
| Artifact transaction | `resolved -> staged -> integrity_verified -> stored -> retired -> collected`, plus publisher-authentication evidence |
| Activation identity | `disabled | enabled` for Product availability or Plugin desired state |
| Declaration admission | `admitted | denied | incompatible` per declaration and context |
| Runtime | `planned | selected | mounted | active | degraded | draining | restart_required | pending_retirement` as defined by its owner |
| Grant | effective authorities bound to artifact digest, declaration ID, Product/Session, and policy revision |

`artifact status` is only an aggregate projection. One artifact may contain an
admitted Resource, denied Extension, and incompatible Capability Provider at
the same time.

### 9.1 Enable, Admission, And Grant Rules

- `enable` changes desired state only.
- integrity verification and publisher authentication do not grant execution
  trust.
- admission produces immutable decision facts but no live side effect.
- grants are calculated per declaration; one declaration cannot borrow another
  declaration's authorities merely because both share an artifact.
- Binder consumes an admitted Capability Provider and narrow authorized facets;
  Mount publication exposes the resulting Capability Bundle.
- a policy revision, artifact digest change, or context change invalidates the
  corresponding cached admission/grant decision.

Plugin desired state remains Plugin-identity-level. Per-declaration enablement,
selection, approval mode, and Product eligibility are owner-qualified
configuration, not a second Plugin lifecycle store. Every selectable
contribution therefore has a stable declaration ID and an explicit
`required | optional` relation to its Plugin activation identity:

- an unavailable or denied required declaration prevents that Plugin revision
  from becoming effective for the affected Product/Profile;
- an unavailable optional declaration produces a truthful `partial` projection
  without borrowing authority from a sibling declaration; and
- an update becomes selectable for a new Session only after its required
  declarations are admitted and ready under their exact owners.

Current Sessions remain pinned to their accepted lock and owner generations.
This readiness barrier coordinates selection; it is not a global atomic Plugin
registry, a cross-owner transaction, or permission for management code to
publish contributions.

### 9.2 Disable, Drain, Retirement, And Collection

The general ordering is:

```text
close new Session and artifact-lease acquisition
  -> publish desired-disabled or draining intent
  -> compute owner-specific withdrawal plan
  -> reject unsafe sealed-graph mutation before any owner generation publishes
  -> wait for or cancel in-flight turns/tasks/workers according to policy
  -> withdraw Resource, Extension, Provider, and Registration facts in owner order
  -> retain retryable pending-retirement state on partial cleanup failure
  -> release only the leases whose owning cleanup completed
  -> collect bytes only after the last durable lease is gone
```

Plugin disable compiles into separate withdrawal requests for each admitted
Resource, Extension, and Capability Provider. It is not one generic disposer.
Current Sessions retain their sealed Mount generation when a graph-owned
Provider change requires restart. For declaration-only or content-only changes,
new Sessions may use the new admitted plan under accepted owner rules. If the
change selects a new executable lock generation, every Session created in the
old process remains pinned to the old generation; only a new process may use the
new executable generation.

Under the assumed post-CLA8 baseline, those requests enter the existing Product
Session composition root. A Plugin or distribution subsystem may propose an
admitted Provider candidate or owner withdrawal input, but it may not call
Provider factories, mutate the graph, publish registrations, or dispose graph
nodes directly. Content-only Resource/Extension refresh may remain live under
its completed owner transaction; a change to a graph-owned Provider selection
is next-Session or `restart_required` according to the sealed-graph rule.

`ArtifactLease` is distinct from `RegistrationLease` and runtime binding
leases. It is acquired by any Product descriptor/runtime, pinned Session graph,
Resource snapshot, Extension generation, external worker, or executable import
environment that needs artifact bytes. Cross-process collection requires a
durable lease/GC decision or conservatively retains the artifact.

An owner whose cleanup is incomplete retains its `ArtifactLease` or an
equivalent durable GC hold. `pending_retirement` never permits byte collection
while a residual Registration, worker, snapshot, or runtime object can still
reference the artifact.

### 9.3 Plugin Desired-State Authority

The current Config owner persists `disabled_plugins`; a new distribution
subsystem must not dual-write a second Plugin desired-state database. Until an
accepted migration, that Config field remains the sole persistence authority.

U3 may replace it with a scoped, explicit Plugin desired-state map, but the new
map remains owned by the Config subsystem. The one-way migration reads the
legacy field, projects previously discovered non-disabled Plugins as enabled to
preserve behavior, defaults newly installed Plugins to disabled, writes only the
new field, and stops writing `disabled_plugins`. Read-old compatibility has an
observed-use retirement gate; there is no permanent fallback or dual write.

## 10. Admission, Execution Trust, And Isolation

### 10.1 Authority Intersection

```text
effective grant = Harness Host security ceiling
                intersect trusted OEM ceiling
                intersect Product policy
                intersect declaration request
                intersect Session grant
```

The request belongs to a specific Product, Plugin, Extension, Capability
Provider, or Resource declaration, never to a vague package-wide bucket.

### 10.2 Integrity, Authentication, And Execution Trust

Three separate decisions are mandatory:

- `integrity_verified`: the staged bytes match the computed or expected digest;
- `publisher_authenticated`: trusted evidence binds a publisher to that digest,
  or the fact explicitly records `publisher_unattributed`;
- `execution_trusted`: local policy permits the exact digest and entrypoint to
  execute with a named execution environment.

Requested manifest authorities constrain only the APIs and Capability facets
injected by Loushang. They cannot constrain arbitrary `os`, filesystem,
subprocess, network, environment, or native-code access performed by Python
running in the Host interpreter.

Therefore:

- only fully execution-trusted artifacts may be imported in the Host process;
- an untrusted artifact is declarative-only until an accepted isolation model
  exists;
- untrusted executable Extensions or Providers require a worker process,
  container, or sandbox with capability-mediated IPC and an explicit failure
  and teardown contract;
- decorators and registration scopes are authoring/lifecycle mechanisms, not a
  security sandbox;
- this proposal does not claim safe third-party executable plugins until the
  isolation decision and adversarial gates are accepted.

The import decision binds the exact artifact digest, entrypoint, dependency
graph, and `ArtifactExecutionEnvironment`. Import or factory failure must not
leave registrations; full cleanup of arbitrary malicious import-time threads,
signals, or `sys.modules` mutations is impossible in-process and is another
reason to restrict in-process loading to fully trusted code.

### 10.3 Multi-Version Python

Ordinary dotted Python imports reuse `sys.modules` and cannot safely run two
versions of the same package and dependency graph in one interpreter. Until a
worker/process isolation design is accepted:

- executable artifact updates are `restart_required`;
- one process pins one executable lock generation;
- old processes and Sessions continue on the old generation;
- new processes use the newly committed generation;
- rollback selects a complete retained lock generation, not an individual
  package version;
- renaming only the entry module is not treated as dependency isolation.

## 11. Configuration

Configuration reuses the current layered configuration and owner codecs rather
than creating a manifest-specific config runtime.

```text
Harness defaults
  -> Product plan
  -> trusted OEM overlay
  -> admitted Extension or Capability Provider defaults
  -> Session override
```

Each field declares permitted sources, value codec, scope, effect, redaction,
and whether its change is live, next-session, or restart-required. Security
ceilings are intersections and cannot be relaxed by a later layer.

Canonical subject references are typed:

```text
product/coding
oem/enterprise-a
plugin/com.example.code-review
provider/coding.arch.default
```

The common request envelope contains subject reference, key, scope, typed
JSON/TOML value, expected revision, dry-run flag, and caller authority. The
destination owner still validates and applies the value through its schema
codec.

```text
loushang config schema <subject>
loushang config get <subject> [key] --scope user|project
loushang config set <subject> <key> --value-json <json> --scope user|project
loushang config unset <subject> <key> --scope user|project
loushang explain config <subject> [key]
```

There is one canonical explain command. A temporary `config explain` alias, if
needed, must project the same result and have an explicit removal gate.

## 12. Product And OEM Positioning

### 12.1 Coding Migration Has Two Distinct Deltas

The first delta is logical Product registration:

```text
load Installed Artifact Candidate Catalog
  -> authenticate and admit static Product declarations
  -> populate Product Registry with admitted Product Descriptors only
  -> resolve OEM Profile and requested Product
  -> Product Router selects the admitted descriptor
  -> Product Factory creates the Product Runtime under the accepted lifecycle
```

Harness Host/CLI code must not contain `if product_id == "coding"` or import
Coding to discover it. Coding owns its static Product Descriptor facts, Product
Factory, Product Adapter, Product Runtime Plan, built-in resources, Capability
Provider declarations, and domain policy.

The second delta is physical distribution. Splitting Coding into independently
installed Python bytes requires a separate packaging and dependency-isolation
decision. Until that is complete, uninstalling Coding can mean unregistering or
disabling its Product declaration, not deleting Coding code from the current
monolithic Python distribution.

This makes Coding plugin-like operationally while preserving Product semantics.
A Plugin can be absent without removing the Product domain; an admitted Product
Descriptor and Factory define that domain.

Neutral-host cutover requires Coding and a second minimal real Product to use
the same Registry, Router, Factory, resume identity, and Session lifecycle. A
test double is insufficient evidence for a shared abstraction.

### 12.2 OEM Profiles

An OEM Profile is a trusted distribution overlay. It can:

- select available and default Products;
- set branding and presentation metadata;
- constrain or allowlist Capability Provider candidates only at override points
  declared by the Product Runtime Plan, plus select approved Plugin catalogs;
- constrain permissions, sources, and configuration;
- provide trusted defaults and compatibility policy.

An OEM does not fork Product source or become a runtime service locator. Its
data enters Harness Host selection and downstream admission inputs. Its
identity and policy revision appear in Session fingerprints and explanation.

## 13. Capability And Extension Rules

### 13.1 Post-CLA8 Graph Is A Runtime Authority, Not A Package Model

The completed Capability Graph and the proposed ecosystem control plane solve
different problems:

```text
Artifact / Package
  -> declares Product, Plugin, Extension, Provider, and Resource candidates
  -> verification, compatibility, admission, policy, and desired state
  -> existing Product Session composition root
  -> existing Planner -> Binder -> one committed Mount generation
  -> focused Consumer facet leases
```

The graph does not discover marketplaces, install bytes, own Plugin desired
state, select a Product, or authenticate a publisher. Conversely, the artifact,
Product, OEM, and Plugin layers do not construct or publish a Capability
Bundle. Their only graph-facing output is an admitted, authorized, immutable
planning input consumed by the existing composition root.

The following CLA8 closure properties are permanent guardrails for every
U-series slice:

- no second graph Runtime, Binder, Projector, transaction, or graph-wide
  service locator;
- no return of a peer resource/session Profile binding for a migrated Bundle;
- no direct Provider construction or Registration publication during manifest
  parsing, installation, enablement, or admission;
- no live replacement of a sealed graph-owned Provider disguised as a Plugin
  reload;
- no graph node for every helper, file, or resource merely because it arrived
  in a Package.

### 13.2 Coding Capability Admission

`coding.lsp` and `coding.arch` remain the accepted top-level Coding Capability
IDs and are the only initial provider-declaration pilots. More Coding
subsystems may become capabilities only when:

- consumers depend on a stable contract rather than implementation internals;
- an alternate, absent, degraded, or test implementation is useful;
- lifecycle ownership and teardown can be expressed explicitly;
- authorities and configuration can be scoped;
- Product/OEM Provider selection is valuable;
- selection, binding, and Mount provenance can be explained.

Small helpers, domain entities, tight inner-loop functions, and inseparable
state remain ordinary code. "Everything is a Capability" is not a goal.

Extensions keep current categories and reversible owner generations. One Plugin
may identify several Resources, Extensions, and Capability Providers, but every
declaration is admitted and activated independently by its owner.

## 14. Python Decorator Authoring

Decorators are a post-MVP source-authoring aid. The published manifest is the
only installed runtime declaration authority.

Recommended names describe executable roles rather than semantic identities:

```python
from loushang.sdk import (
    capability_provider_factory,
    extension_factory,
    product_factory,
)


@product_factory()
def create_coding_product(context: ProductFactoryContext):
    ...


@capability_provider_factory()
def create_lsp_provider(context: CapabilityProviderContext):
    ...


@extension_factory()
def create_command_extension(context: ExtensionFactoryContext):
    ...
```

Plugin is a declarative activation identity in v1 and therefore has no
`@plugin_entrypoint` object. Its executable behavior is expressed by admitted
Extension or Capability Provider factories with their existing owner
lifecycles.

The decorator either:

- marks a factory kind and lets the trusted build tool generate overlapping
  manifest fields; or
- contains source-only metadata that the build tool compares field-by-field
  with the generated manifest.

An installed runtime never imports code to discover declaration identity,
compatibility, authorities, target, or contract version. After admission and
import, activation validates the decorated callable kind and any repeated
metadata against the manifest; mismatch aborts activation before factory
construction.

Decorator specifications must normalize nested collections into immutable
values. Decorators perform no global registration, construction, I/O, task
creation, secret access, or trust decision by contract. This contract helps
well-behaved authors but does not constrain malicious import-time Python; the
execution-trust rules still apply. Factory contexts are narrow, typed owner
contexts rather than a universal service locator.

## 15. Explain, Events, Audit, And Privacy

Explain is one read-only surface over multiple authorities:

```text
loushang explain artifact <id> [--json]
loushang explain product <id> [--json]
loushang explain oem <id> [--json]
loushang explain plugin <id> [--json]
loushang explain capability <id> [--json]
loushang explain provider <id> [--json]
loushang explain resource <id> [--json]
loushang explain config <subject> [key] [--json]
loushang explain session <id> [--json]
loushang explain runtime [--json]
```

A projection may correlate:

```text
artifact source ID and digest
  -> manifest declaration
  -> stored and desired state
  -> authentication, execution trust, compatibility, and admission facts
  -> Product/OEM selection
  -> resource winner or Extension generation
  -> Provider planning, binding, and Mount
  -> exact Registration and Consumer
  -> committed Model Input or presentation fact reference
```

The boundaries are:

- the Config owner for Plugin desired state may own a durable operation/audit
  record;
- each runtime owner emits observations only after its authoritative commit;
- events carry `operation_id`, `attempt_id`, owner stream sequence,
  before/after revision, and authoritative fact reference;
- no cross-owner exactly-once or global ordering is implied;
- Explain persists no second lifecycle record and can be rebuilt from owner
  facts;
- if durable historical explanation is required, it needs a separate accepted
  observation/retention boundary.

Composed Explain returns every source clock and revision plus
`consistent|partial|stale|unavailable` disposition. It never presents several
independently read clocks as one atomic global snapshot or invents a missing
selection.

Event, audit, and Explain schemas classify fields as
`public|operator|session_private|secret`. Redaction occurs before data enters a
shared event bus or immutable projection, not only at CLI rendering. Rules
cover URL userinfo/query data, absolute paths, environment names, credential
references, workspace/session/tenant IDs, policy denial detail, exception text,
and fingerprints. Paths use scoped opaque source IDs or approved relative
forms. Sensitive fingerprints are policy-scoped and keyed.

Every Explain subject enforces caller and field-level authorization. Session,
runtime, and config additionally enforce tenant, Product, workspace, and
Session scope; artifact, Product, OEM, Plugin, Capability Provider, Capability,
and Resource views still redact or deny operator/private provenance. Human and
JSON projections use the same reason facts; JSON is not a privileged leak
channel.

## 16. Unified CLI And Remediation

All commands accept `--json`; mutating commands resolve `--scope user|project`
and support `--dry-run` and an expected revision where concurrency matters.

```text
loushang artifact inspect|validate|verify|install|update|list|status|lock|uninstall
loushang artifact retire|gc
loushang product list|enable|disable|status|set-default
loushang product disable <id> --drain|--terminate
loushang oem list|use|status
loushang plugin list|enable|disable|status
loushang provider list|status
loushang trust publisher list|add|remove|status
loushang trust execution status|grant|revoke artifact/<id>@<digest> --entrypoint <ref> --environment <id>
loushang policy explain|grant|revoke <subject>
loushang config schema|get|set|unset
loushang explain artifact|product|oem|plugin|capability|provider|resource|config|session|runtime
loushang artifact init|validate|test|pack|sign|publish
```

`artifact` is the unambiguous CLI noun for installed bytes. Compatibility
aliases may retain current package commands, but `remove` must not ambiguously
mean source deregistration, materialization deletion, uninstall, and garbage
collection. Public lifecycle verbs are `install`, `uninstall`, `retire`, and
`gc` with distinct effects.

Every status result uses a common envelope but kind-specific facts and
remediation:

| Subject/fact | Typical reason | Allowed remediation |
| --- | --- | --- |
| Artifact integrity/authentication incomplete | digest/signature/publisher failure or unsigned local source | inspect evidence; change protected publisher policy/source, or explicitly trust the exact local digest for execution |
| Artifact not execution-trusted | exact digest, entrypoint, or environment lacks a protected grant | keep declarative-only or grant/revoke the exact execution subject after review |
| Declaration denied | Product/OEM/policy ceiling | `policy explain`; grant only if every upper ceiling permits it |
| Plugin desired-disabled | explicit scoped setting | `plugin enable` at the intended scope |
| Product draining | disable or upgrade operation | wait, cancel under policy, or inspect blocking Sessions |
| Capability restart-required | sealed graph or executable generation change | restart/fork the affected Session or process |
| Artifact pending-retirement | live artifact lease or cleanup failure | inspect lease holders; retry retirement/GC safely |

`status --why` is a convenience view of the same Explain facts and reason
codes, not a separate diagnostic implementation.

## 17. Publishing And Supply Chain

The eventual pipeline is:

```text
init -> validate -> contract test -> pack -> sign -> publish
```

The MVP stops at deterministic `pack` for built-in artifacts and explicitly
digest-trusted local artifacts.
Signing and remote publishing become available only after the supply-chain and
execution-isolation decisions are accepted.

A publication contains or references:

- artifact bytes and `loushang.toml`;
- immutable artifact and manifest digests;
- complete dependency hashes and compatibility metadata;
- configuration schemas and resource/entrypoint inventory;
- software bill of materials;
- detached signature, publisher identity, and build provenance;
- license and source metadata.

The contract test kit validates:

- manifest schema and canonical IR;
- compatibility and declaration-owner mapping;
- zero Python/build-hook execution during inspect/install;
- admission without pre-admission imports;
- activation rollback, disable, teardown, and artifact-lease behavior;
- configuration codec, effects, and redaction;
- deterministic, authorized Explain projections;
- Product, Capability Provider, and Extension contracts;
- decorator/manifest consistency when decorators are enabled.

Publisher adapters may later target PyPI, fixed Git artifacts, GitHub releases,
local catalogs, or an enterprise registry. A custom marketplace is not required
for the first release.

## 18. Failure, Update, And Rollback Semantics

- fetch, verification, or manifest failure leaves the current lock generation
  and candidate catalog unchanged and executes no package code;
- desired-state mutation is an atomic compare-and-swap operation with a durable
  audit fact;
- failed Product startup produces a failed Session without corrupting the
  admitted Product Descriptor;
- failed Extension refresh keeps the previous valid owner generation active;
- failed Provider binding publishes no partial Mount generation;
- update commits a complete new lock generation before switching its atomic
  pointer;
- a Session and process pinned to an older executable generation remain on it;
- rollback selects the complete retained predecessor lock generation;
- disable and retirement close new lease acquisition before teardown;
- partial cleanup remains retryable and cannot claim collection success;
- artifact bytes are collected only after all durable artifact leases release.

Crash recovery tests inject failure after staging, store commit, lock creation,
pointer publication, desired-state commit, runtime bind, and old-generation
retirement. Recovery must expose either a complete old state or a complete new
state, never an unlabelled mixture.

## 19. Migration Plan

### U0 — Owner Decisions And Baseline

- accept vocabulary, orthogonal declaration axes, and Harness Host ownership;
- decide whether artifact distribution extends the existing Harness package
  owner or receives a separately named Harness owner;
- inventory hard-coded Coding entrypoints and legacy manifest formats;
- verify and freeze the assumed post-CLA8 invariants as executable prerequisite
  gates: one Session graph owner, no peer binding authority for migrated
  Bundles, rollback-safe publication, restart-required Provider replacement,
  focused Consumer facets, and joined cleanup;
- stop U-series implementation if the actual CLA integration fails those gates;
  repair the owning CLA boundary rather than introducing a U-series fallback.

### U1 — Ecosystem Kernel MVP

- support Host-authenticated built-ins and exact-digest local Resource Packages,
  with optional Plugin identity and explicit execution trust where needed;
- define `loushang.toml` v1, JSON schema, canonical `ManifestIR`, and static
  candidate catalog;
- add `inspect`, `validate`, reason codes, versioned JSON, and scope handling;
- read legacy `plugin.json`, `loushang-plugin.json`, and
  `loushang-package.json`, but project only the new format; never dual-write;
- exclude decorators, remote execution, OEM, and Capability Provider
  declarations.

### U2 — Transactional Local Store And Lock

- add staging, immutable local storage, lock generations, atomic pointer/CAS,
  and crash recovery;
- add the new install/commit/retire transaction port;
- define but do not invoke the current Resource Package legacy adapter; runtime
  projection waits for U3 lease and withdrawal semantics;
- implement `install|status|uninstall|retire|gc` and minimal Explain for
  candidates that have never been admitted or projected to a runtime owner;
- keep installation separate from Plugin enablement.

### U3 — Desired State, Admission, And Leases

- migrate scoped Plugin desired state within the Config owner and add
  declaration-level admission facts;
- add per-declaration grants, reason codes, audit facts, and owner withdrawal
  plans;
- introduce `ArtifactLease`, draining, retryable retirement, and GC;
- activate the Resource Package legacy adapter only after lease acquisition and
  owner withdrawal gates protect every projected snapshot;
- map desired-state changes to Resource and Extension owners and to immutable
  next-Session graph planning inputs without a shared runtime state machine or
  direct Binder access.

### U4 — Accepted Product Registration Boundary

- accept Product Descriptor, Factory, Adapter, Runtime Plan, and version
  negotiation interfaces;
- add admitted Product Registry and Router to Harness Host scope;
- migrate logical Coding registration away from the hard-coded process entry;
- validate Coding and a second minimal real Product before neutral-host cutover;
- add Product status and Explain in the same slice.

### U5 — Product Distribution And Execution Environment

- decide Python distribution split, dependency isolation, lock generation
  pinning, and `ArtifactExecutionEnvironment`;
- make executable updates restart-required until stronger isolation exists;
- only then claim physical Coding install/uninstall.

### U6 — OEM Profiles

- accept and package OEM selection, branding, ceilings, defaults, and approved
  catalogs;
- include OEM identity and decisions in fingerprints and explanation.

### U7 — Capability Provider Declaration Bridge

- extend the completed CLA6 declaration bridge and reuse the sole
  Session-owned Planner/Binder path established by the post-CLA8 baseline;
- define the full manifest-to-admitted-provider mapping, including artifact
  provenance, Product/OEM policy, contract/facet compatibility, requested
  authorities, binding-input fingerprint, scope, phase, refresh boundary, and
  `restart_required` behavior;
- pilot only `coding.arch` and `coding.lsp`;
- compile admitted declarations into immutable candidate inputs for the Product
  Session composition root; do not construct a Provider during discovery,
  install, enable, or admission;
- do not add a parallel Provider registry or let a Plugin/distribution owner
  publish graph-owned source, Registration, Bundle, or Mount changes.

The capability-runtime convergence and CLA0-CLA8 composition-authority closure
are prerequisites and are assumed complete. U7 is therefore a distribution-to-
admission bridge, not another graph migration or legacy-authority cleanup phase.

### U8 — Author And Remote Ecosystem

- add factory-kind decorators and activation-time manifest consistency checks;
- accept execution-isolation and supply-chain decisions;
- add signing, provenance, fixed Git/wheel resolvers, publisher adapters, and
  adversarial verification gates;
- keep source distributions disabled until isolated build output is verified.

### U9 — Compatibility Retirement

- remove hard-coded Coding discovery and legacy Plugin/Provider paths;
- remove read-old adapters only after observed-use gates pass;
- prohibit permanent fallback or dual-write authorities;
- do not recreate any graph/profile compatibility authority already removed by
  CLA8; U9 retires ecosystem discovery and manifest compatibility only.

## 20. Hard Adoption Gates And Acceptance Criteria

Before external executable artifacts, physical Product uninstall, or remote
publishing are accepted, separate owner decisions must define:

1. artifact distribution ownership and relationship to Resource Package
   operations;
2. execution trust and same-process versus isolated-worker policy;
3. detached signatures, trust roots, revocation, freshness, offline behavior,
   and lock replay;
4. `ArtifactExecutionEnvironment`, executable generation pinning, and restart
   rules;
5. per-layer state transitions with owner, inputs, output, failure, and rollback;
6. `ArtifactLease`, cross-process collection, and stale-lease recovery;
7. desired-state changes mapped to Session graph and owner generations;
8. Runtime Event, durable audit, Explain, privacy, and retention boundaries;
9. source-authority/opaque-locator routing for every non-Host Resource root; and
10. durable component-state ownership, migration, retention, deletion, and
    tenant/workspace isolation.

The assumed post-CLA8 properties are prerequisite preservation gates, not open
design choices for this proposal. Every U-series integration test must also
prove that it:

- uses the existing Product Session composition root and sole Graph Binder;
- performs no Provider construction or runtime publication before admission;
- preserves the previous authoritative Mount on failure or cancellation;
- returns next-Session or `restart_required` for a changed sealed
  graph-owned Provider rather than hot-swapping it;
- leaves content-only owner refresh and graph Mount generations as distinct
  authorities; and
- introduces no peer Profile Binder, compatibility graph, or Plugin-owned
  registration lifetime for a migrated Bundle.

The complete design succeeds when:

1. Harness Host starts without importing Coding.
2. An admitted Coding Product Descriptor becomes discoverable without a
   Harness source change.
3. Coding and a second real Product use the same Registry, Router, Factory,
   resume identity, and Session lifecycle.
4. Invalid or integrity-unverified artifacts execute no code and commit no
   stored state; publisher-unattributed local artifacts may be stored but cannot
   execute without an exact protected grant.
5. Untrusted executable code never enters the Host interpreter.
6. Install does not imply execution trust, enablement, admission, grant,
   Product selection, or Capability Mount.
7. A lock generation replays the same complete artifact graph without mutable
   network metadata.
8. Sessions resume with their exact executable generation or fail closed.
9. Capability contract mismatch fails before Provider construction.
10. Extension activation failure preserves the previous valid generation.
11. graph-owned Provider change returns restart-required before any conflicting
    Resource, Extension, or Mount generation publishes.
12. disable/drain/retirement closes new lease acquisition and never collects
    live bytes.
13. partial cleanup and process crashes recover to explicit retryable states.
14. Explain traces artifact provenance through owner decisions to Consumer facts
    with source clocks, redaction, authorization, and partial/stale status.
15. model-visible content is reconstructed from canonical committed Model Input
    facts and their referenced owner facts, not from fingerprints alone.
16. manifest/decorator drift aborts activation and publication.
17. no Harness Host code imports Coding to discover or select it.
18. package installation, Plugin enablement, and manifest admission never
    mutate a Session graph except through its existing composition root and
    Binder transaction.
19. the post-CLA8 single-authority and cleanup gates remain green after Coding
    and the second Product adopt the ecosystem control plane.
20. a forged or stale source locator cannot make Executor/Orchestrator bytes
    readable as a Host path or activate a contribution during resolution.
21. required-contribution failure blocks new-Session selection while optional
    failure reports `partial` and preserves the previous usable revision.
22. disable, uninstall, rollback, and artifact GC cannot silently delete,
    cross-adopt, or cross-tenant durable component state.

Required adversarial suites include malicious archive entries, dependency
substitution, moving Git refs, same-version byte replacement, signature
downgrade/revocation/offline freshness, build-hook execution, import-time
side effects, cross-version Python collisions, source-locator forgery,
cross-tenant state adoption, failed state migration, concurrent
disable/update/new Session races, crash recovery, event loss/reordering, clock
skew, and canary secret leakage across logs/events/audit/Explain.

## 21. Non-Goals And Guardrails

This proposal does not introduce:

- one process-global mutable `PluginManager`;
- one universal writable Plugin data directory or state manager;
- a universal service locator or untyped plugin context;
- a new top-level Platform architecture scope;
- a second Composition Plan, transaction, Projector, or Product Registry;
- one global generation or atomic clock across unrelated owners;
- automatic enablement or trust on installation;
- Python import as install-time metadata discovery;
- arbitrary live mutation of sealed Session graphs;
- conversion of every helper or domain object into a Capability;
- conversion of all Resources into registrations;
- Product semantics inside the Harness substrate;
- safe untrusted in-process Python by declaration alone;
- a generic Hook bus whose commands, URLs, or callbacks bypass exact Extension
  and event owners;
- a custom marketplace requirement for the first release.

## 22. Relationship To Reference Plugin Systems

### 22.1 DeepSeek Harness

The local DeepSeek Harness reference uses Cordis so every product component is
a plugin in one boot-time plugin tree. Profiles and bundles layer configuration;
services, typed events, and reversible effects make model adapters, tools,
session log, and agent loop replaceable. Capability seams explicitly include
Service Definition, Service Provider, and Consumer roles.

Loushang should adopt the useful properties:

- static, inspectable composition;
- profile/bundle-style reusable assembly;
- complete capability seams rather than provider-only abstractions;
- reversible registration and unload effects;
- configuration-driven replacement and strong self-explanation.

It should not copy the universal runtime identity literally. Loushang has
first-class Product and OEM semantics, Product Session identity, Product Kernel
ownership, several already accepted typed owner runtimes, and layered admission
policy. Collapsing them into one Cordis-like context would recreate a global
service locator and erase Product Mount/admission authority.

The practical gap is therefore:

| Dimension | DeepSeek Harness reference | Loushang assumed post-CLA8 / proposed response |
| --- | --- | --- |
| Boot composition | one patchable plugin tree from profiles and bundles | current entry is Coding-centric; proposed admitted Product discovery plus existing owner flow |
| Reversible lifecycle | uniform Cordis effects | completed graph, Extension generation, Registration Scope, rollback, and joined cleanup remain authoritative; proposal adds artifact/desired-state coordination without replacing them |
| Capability seams | Definition / Provider / Consumer is a standard package pattern | one Session-owned graph and the CLA declaration bridge are baseline; Product/OEM admission of packaged Provider candidates is the remaining convergence path |
| Distribution declaration | package metadata plus Cordis/profile configuration | proposed `loushang.toml`, `ManifestIR`, immutable artifact lock, and typed owner bridges |
| Product/OEM identity | profiles and bundles compose a harness | Loushang keeps Product and OEM as stronger domain and distribution concepts |
| Install/explain/publish | inspectable boot configuration is mature; full third-party trust is a separate concern | proposed control plane closes install/status/config/explain/publish and supply-chain gaps explicitly |

The target is "everything is distributable and composable through a common
protocol," not "everything is the same Plugin class."

### 22.2 Codex And Claude Code

Current Codex and Claude Code implementations provide complementary evidence,
not normative dependencies. Codex demonstrates authority-bound resource
locators, inert resolution, immutable installed revisions separated from
mutable data, and policy below the Plugin enable bit. Claude Code demonstrates
the product value of convention roots, built-ins, managed/user/project/local/
session placement, typed user configuration, component inventories, and
generation-safe refresh.

Loushang adopts those pressures through its existing owners:

| Proven product pressure | Loushang response |
| --- | --- |
| Put a Skill or prompt in a conventional directory | Native Resource tree; no synthesized Plugin identity |
| Run scripts shipped beside a Skill | Generic Tool compatibility or strict snapshot-bound managed action; no Worker/per-Skill Plugin requirement |
| Bundle several capability kinds | Canonical package and ContributionIndex; every declaration still enters its exact owner |
| Configure one server/tool without disabling the package | Plugin-identity desired state plus owner-qualified contribution selection/policy |
| Read resources discovered outside the Host | Source authority plus opaque locator; resolution is inert |
| Preserve data across immutable upgrades | Owner-mediated cache/state/credential/Artifact classes, never a universal data directory |
| React to lifecycle/tool events | Future typed exact-event Extensions, not raw command/URL Hooks or a global bus |
| Accept another ecosystem's layout | Offline importer to the sole canonical manifest; no second runtime parser |

Loushang deliberately does not copy permissive unknown-field handling, ambient
command/runtime lookup, secret interpolation into instructions or commands,
same-user process isolation presented as a Sandbox, or a cross-owner Plugin
manager. The reference implementations evolve independently; interoperability
must remain an optional adapter with conformance tests, not a foundation of the
runtime architecture.

## 23. Tradeoffs

Benefits:

- one ecosystem experience without erasing domain boundaries;
- logical Coding replaceability at the Harness Host;
- reproducible artifacts and stronger supply-chain provenance;
- consistent admission, configuration, lifecycle, and explanation envelopes;
- concise source authoring after the runtime contracts stabilize;
- clearer separation between distribution identity and runtime ability.

Costs:

- more schemas, compatibility dimensions, signature policy, and migration work;
- separate artifact, declaration, runtime, and grant states;
- process restart or worker isolation for executable upgrades;
- temporary read-old compatibility for legacy manifests;
- strict lease, privacy, and crash-recovery requirements.

Mitigations are a narrow local-only MVP, canonical static IR, no dual-write,
deterministic reason codes, owner-specific bridges, versioned JSON, and explicit
adoption gates before every expansion in trust or runtime authority.

## 24. Open Decisions

The following require accepted owner decisions:

- distribution owner and its relationship to current Resource Package owners;
- exact Product/OEM descriptor and version-negotiation interfaces;
- artifact store, lock generation, desired-state transaction, and scope format;
- execution trust, worker isolation, and dependency environment;
- signature envelope, trust roots, revocation, freshness, and offline behavior;
- full Capability Provider manifest-to-runtime mapping;
- cross-process artifact lease and collection behavior;
- non-Host source-authority provider/locator contracts and precedence;
- durable component-state owner mapping, migration, retention, quota, and
  deletion contracts;
- Product disable defaults for interactive Sessions;
- event/audit/Explain retention and privacy policy;
- legacy command and manifest retirement thresholds.

These decisions block the affected migration slice; they do not block U1's
local, declarative, static-schema work.

## 25. Independent Review Disposition

Three independent agents reviewed the initial draft from architecture,
lifecycle/security, and developer-experience perspectives. All three rejected
the initial version as implementation-ready while agreeing with the central
direction. This revision resolves their blocking findings as follows:

| Initial finding | Revision disposition |
| --- | --- |
| Undefined Platform authority | Host/CLI ownership is explicitly Harness; no new top-level scope |
| Second universal Composition Planner | removed; accepted Resolver/Extension/Planner/Binder flow is reused |
| Installed catalog bypassed Product admission | candidate catalog and admitted Product Registry are now distinct |
| Package/Plugin/Provider axes were collapsed | orthogonal declarations, canonical Product/OEM/Resource Package roles, no Provider Package v1 |
| Capability authority was assigned wholly to Harness | contract namespace, Product policy, Harness mechanics, and live scopes are separated |
| Product logical registration and physical install were mixed | split into U4 logical and U5 physical deltas |
| Current capability status was stale | actual Current remains source-backed; this revision separately assumes the completed CLA0-CLA8 single-graph baseline and makes U-series work preserve it rather than depend on future CLA delivery |
| Existing Resource Package operations were overstated | treated as a legacy adapter, not transaction/rollback authority |
| One common lifecycle became a second state machine | replaced with labeled owner-specific state layers and an aggregate status envelope |
| Untrusted same-process Python was described as safe | authentication/execution trust separated; untrusted executable code requires isolation |
| Multi-version Python and Session pinning were absent | execution environment, lock generation pinning, restart, and full-graph rollback added |
| Disable/retirement/leases were incomplete | owner withdrawal plan and distinct durable artifact lease added |
| Explain record risked a second authority | only desired-state audit is durable; Explain joins owner facts with clocks |
| Privacy covered only secret values | field classification, early redaction, access control, and canary tests added |
| Manifest/decorator was a runtime dual source | manifest is sole installed authority; decorators are deferred factory aids |
| CLI lacked scope and remediation | typed subjects, explicit scope, stable lifecycle verbs, status/reason/remediation matrix added |
| Second real Product arrived too late | moved into the neutral-host cutover gate |

This disposition does not turn the draft into accepted architecture. It makes
the remaining disagreements explicit adoption decisions rather than hidden
implementation assumptions.

After the revisions, the same three reviewers performed scoped rechecks of
their remaining findings. Architecture, lifecycle/security, and
developer-experience reviewers each returned `approve as proposed draft` with
no open blocker in the reviewed scope. That is a review result, not an accepted
architecture decision; the adoption gates and open owner decisions above still
apply.

The later post-CLA8 baseline refresh in this revision was not part of those
three scoped rechecks. It changes sequencing and prerequisite statements, not
their accepted review scope; it still requires review against the eventual
CLA8 integrated source and executable gates before adoption.

## 26. Relationship To Existing Architecture

This proposal composes, and does not supersede, the following current owner
documents:

- [Architecture Method](../../../architecture-method/README.md)
- [Product Glossary](../../../glossary/loushang-product.md)
- [Harness Current Owner Map](../../harness/current-owner-map.md)
- [Platform Resource Layout Boundary](../../harness/platform-resource-layout-boundary.md)
- [Package Session Operations Boundary](../../harness/package-session-operations-boundary.md)
- [Extension Runtime Core Boundary](../../harness/extension-runtime-core-boundary.md)
- [Product Configuration Runtime Boundary](../../harness/product-configuration-runtime-boundary.md)
- [Capability Runtime Convergence Plan](../../harness/capability-runtime-convergence-plan.md)
- [Composition Lifecycle Authority Plan](../../harness/composition-lifecycle-authority-plan.md)
- [Product Runtime Injection Plan](../../harness/product-runtime-injection/README.md)
- [Current / Target Gap Ledger](../../current-target-gap-ledger.md)

If this draft conflicts with those documents, current source, or executable
gates, those authorities win until an explicit architecture decision changes
them.

Under the scenario evaluated by this revision, the Composition Lifecycle
Authority Plan is treated as a completed dependency. It remains linked as the
normative provenance of the single-graph invariants, not as unfinished work in
the U-series migration plan.
