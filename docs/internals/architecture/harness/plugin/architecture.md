# Unified Plugin Architecture V2

## Status And Authority

- Authority: canonical target architecture for Loushang Plugin composition,
  authoring, execution, management, and cross-Product use.
- Design status: independently reviewed and ready for owner acceptance under
  issue `#502`; architecture, security, and developer-experience reviews passed
  after their blocking findings were corrected and re-reviewed. This status is
  not self-acceptance.
- Implementation status: partial. The strict manifest and declaration codecs,
  immutable revision evidence, desired-state and Instance ledgers, execution
  Approval consumption, exact Capability-owner admission, Provider selection,
  Resource component foundations, and the first `coding.lsp` production path
  exist. Public SDK, managed Skill scripts, isolated Plugin Workers, Resource
  Catalog cutover, `coding.base`, `coding.arch`, and complete operations
  projection remain delivery work.
- Current-runtime authority: source, tests, and narrower accepted boundary and
  contract documents remain authoritative for implemented behavior. Target
  clauses in this document do not make an unimplemented execution shape or API
  available.
- Delivery authority: the
  [Plugin Lifecycle And Coding Pluginization Plan](plugin-lifecycle-coding-pluginization-plan.md)
  is the only coordinating Plugin delivery sequence. This architecture does
  not maintain a competing milestone list.
- Review record: architecture, security, and developer-experience review passed
  after correction and same-reviewer re-review. The durable process evidence
  belongs to issue `#502`, its delivery PR, and Git history rather than a second
  set of architecture documents.

The canonical Product, Capability, Package, Plugin, Extension, and Resource
terms are grounded in the
[Product And OEM Glossary](../../../glossary/loushang-product.md). Existing
owner boundaries remain authoritative, especially the
[Capability Dependency And Mount Lifecycle](../capability-dependency-and-mount-lifecycle.md),
[Extension And Resource Generation Lifecycle](../extension-generation-lifecycle-boundary.md),
[Process Hosting Boundary](../process-hosting-boundary.md), and
[Sandbox Runtime Boundary](../sandbox-runtime-boundary.md).

## Executive Decision

Loushang should have one Plugin experience, not one universal Plugin object.

A Plugin is an independently selectable activation identity that groups typed
contributions and their management provenance. It is not the Product Kernel, a
Capability, a Skill, a Tool, a process, a package, an Extension, a service
locator, or the owner of everything it carries.

The architecture unifies only what truly has one reason to change:

- one package and source authority model;
- one inert manifest and declaration model;
- one desired-state command authority;
- one resolve, preflight, select, admit, bind, project, and retire spine;
- one small authoring projection over those contracts; and
- one correlated explanation view over otherwise independent owner states.

Runtime behavior stays with cohesive domain owners. Capability owners admit and
bind Providers, the Resource owner admits and projects Resources, Tool owners
publish Tools, Approval owns decisions, Sandbox owns containment, Process Host
owns child-process mechanics, and Product owns composition. The Plugin layer
coordinates; it does not absorb these authorities.

The target spine is:

```text
source authority evidence + bounded byte stream
  -> package lifecycle/store owner
  -> immutable package revision
  -> inert resolved Plugin descriptor
  -> pure preflight and versioned declarations
  -> Product selection and exact-owner admission
  -> execution authorization, when code is required
  -> exact-owner binding and generation publication
  -> read-only effective state and Plugin inventory
  -> drain, owner retirement, cleanup, and eventual GC
```

## First Principles

### 1. Plugin identity exists only when independent activation exists

Content does not become a Plugin merely because it is discoverable, packaged,
or executable. Create a Plugin identity only when at least one of these is
needed:

- independent enable, disable, update, or removal;
- independent version and dependency resolution;
- an explicit trust or execution decision;
- atomic selection of several contributions; or
- separately explainable lifecycle and provenance.

A native `SKILL.md`, prompt, theme, or asset normally remains a Resource. A
Product-embedded static contribution normally remains Product build input. If
the same contribution must be independently enabled, updated, or revoked, it
may be packaged as a Plugin without changing its downstream owner contract.

### 2. Static description precedes executable behavior

Discovery, inspection, dependency solving, configuration validation, and
selection operate on inert, bounded, serializable data. They do not import a
module, run a script, start a Worker, contact an undeclared service, or mutate a
runtime registry.

Execution begins only after an exact immutable revision, declaration source,
configuration, scope, requested authority, policy snapshot, and Approval use
have been joined and revalidated.

### 3. Authority is injected narrowly and cannot be self-declared

A manifest may request authority. It cannot grant authority, mark itself
trusted, choose its own Sandbox exemption, publish into another owner's
generation, or widen Product policy. Source location, signature, publisher,
installation scope, and trust are independent facts evaluated by Host-owned
policy.

### 4. Every mutation and registration has one exact owner

The owner that defines an invariant admits, publishes, drains, repairs, and
retires the state protected by that invariant. Plugin management may hold
references and aggregate status, but it cannot become a second Registration,
Capability, Resource, Tool, external-domain, or cleanup owner.

### 5. Reversibility is explicit, not assumed

Live registrations and owner generations must have idempotent retirement
handles. Process start has termination and cleanup. Package updates stage a new
revision before pointer cutover. Irreversible external effects are never called
"rollbackable" merely because their caller is a Plugin.

Loushang does not impose a universal Terraform-style `plan/apply` protocol.
Ordinary scripts and Tools use the existing effect, Policy, Approval, Sandbox,
and audit path. A domain with durable external mutation may define its own
typed prepare/apply/reconcile contract under its exact owner; that is a domain
capability, not Plugin lifecycle.

### 6. Developer simplicity is a projection, not a second runtime

The SDK may hide fingerprints, leases, Approval receipts, process launch, IPC,
and cleanup from ordinary authors. It does so by compiling small declarations
into the same strict internal IR and exact-owner lifecycle. It must not add an
ambient `PluginContext`, mutable service bag, direct registry access, or a
special built-in bypass.

## Vocabulary And Identity

| Concept | Meaning | May execute code? | Runtime authority |
| --- | --- | --- | --- |
| Resource | Model- or user-facing content such as a Skill, prompt, method, theme, or asset | No; a referenced action is separate | Resource owner |
| Package artifact | Immutable distribution bytes and dependency metadata | No | Package store only |
| Plugin | Independently selectable activation identity plus typed contributions | Not by identity alone | Management provenance only |
| Contribution | One typed declaration offered to an exact owner | Depends on execution shape | Candidate only |
| Capability | Stable typed Definition/Provider/Consumer contract | Provider implementation may | Capability owner and Graph |
| Extension | Product programmability contribution under the Extension owner | May | Extension owner |
| Built-in Plugin | Product-shipped Plugin with an explicit Plugin identity | Under declared shape | Same downstream owners |
| Embedded contribution | Product build input without independent Plugin lifecycle | Only if Product explicitly binds trusted code | Product and downstream owner |
| Worker | Supervised child process implementing one versioned owner protocol | Yes | No authority beyond granted IPC and containment |
| Plugin Instance Revision | One selected Plugin revision, configuration, scope, and execution realm | Coordinates direct hosts | Instance lifetime and provenance only |
| Owner generation | Exact published Capability, Resource, Tool, Extension, or other owner state | Owner-defined | Exact owner |

### Orthogonal declaration axes

The manifest and declaration model keeps these decisions independent. Product
policy may constrain valid combinations, but no axis is inferred from another:

| Axis | Question | Examples |
| --- | --- | --- |
| Artifact | How are immutable bytes distributed? | embedded bytes, verified directory, wheel, pinned registry or Git artifact |
| Plugin identity | What is independently installed, selected, updated, or revoked? | `harness.stats.default` |
| Contribution | What is offered to an owner? | `resource_item`, `tool_pack`, `command_pack`, `capability_provider` |
| Capability | Which stable Product contract is implemented? | `harness.stats`, `coding.lsp` |
| Execution topology | Where does implementation run? | none, in-process, one-shot local process, long-lived local Worker, remote service |
| Trust and authority | What may this exact use do? | host-equivalent, workspace read, restricted network, external mutation |
| Lifetime | How long is the live execution retained? | invocation, Session, Product runtime, deployment |
| Placement and scope | Where is it selected and effective? | Product embedded, project, user, tenant, deployment |

Consequently, `resource`, `capability`, `worker`, and `remote` are not Plugin
types. A single Plugin identity and Capability contract can retain their public
identities while a later revision changes from an in-process implementation to
a contained local Worker. That change still requires a new immutable revision,
fresh admission, and compatibility evidence; it does not require a second
Plugin architecture.

Execution topology, lifetime, and minimum authority normally bind to an exact
contribution and executable use, not to the Plugin as a whole. A package may
carry a data-only Skill and a local Worker without granting the Skill the
Worker's lifetime or authority.

Publisher qualification is a typed identity join, not necessarily a DNS-style
display string. The current built-in ID `coding.lsp.default`, for example, is
qualified by Loushang's built-in source/publisher authority and its immutable
package revision. External publication must provide an equally unambiguous
publisher authority; a display name alone is never identity.

Identity domains must not be collapsed:

```text
artifact identity      = source authority + immutable content digest
Plugin identity        = publisher-qualified Plugin ID
Plugin revision        = Plugin identity + artifact identity + engine contract
installation identity  = Plugin revision + installation scope
Instance identity      = installation + Product + runtime scope + configuration
contribution identity  = Plugin revision + declaration kind + owner-qualified ID
owner generation       = owner ID + runtime scope + monotonic generation
execution use          = exact subject + one decision + one attempt
```

Human-readable names are labels, not joins. Every cross-layer join uses exact
typed identities and fingerprints.

The current `RuntimeCapabilityScope` vocabulary remains `process`, `tenant`,
`workspace`, `session`, `turn`, and `channel`. Plugin lifecycle introduces no
ambient `agent` scope: an Agent holds an explicit membership lease in a
Session/Product composition. One lease belongs to one scope and exact owner
generation; a root Plugin object cannot capture foreign leases.

## Ownership Model

### Fixed control plane

The following are not replaceable merely because a package calls itself a
Plugin:

- Product Kernel and agent-loop semantics;
- Runtime Profile and Product composition;
- Capability Graph planning, binding, and projection;
- Policy, Approval, Authorization, and Sandbox enforcement;
- package revision verification and desired-state journals;
- owner admission, publication, retirement, and repair; and
- canonical audit, Model Input persistence, and effective-state clocks.

The agent loop specifically remains owned by `loushang.agent`. Plugins may
contribute typed Tools, Resources, Capability Providers, and presentation or
protocol adapters around the loop; they do not replace its state machine.

### Typed extension seams

Each pluggable mechanism has three cohesive parts:

1. a stable Definition owned by the domain;
2. one or more Provider candidates admitted by that owner; and
3. narrow Consumer facets captured from an exact mounted generation.

Multi-provider aggregation is owner-defined. The Plugin manager cannot invent
merge, precedence, replacement, or conflict rules. A Resource catalog can
aggregate many source components because the Resource owner defines that
policy; a complete Capability Bundle remains one owner-admitted Provider.

### One writer, many projections

| State | Sole writer | Read projections |
| --- | --- | --- |
| Package revisions and leases | package lifecycle/store owner | Plugin inventory, diagnostics |
| Plugin desired state | `PluginManagementService` | CLI/RPC/UI/SDK |
| Execution decisions and uses | Approval/execution-trust owner | audit, Instance diagnostics |
| Capability admission and mounts | exact Capability owner and Graph Binder | effective runtime |
| Resource/Tool/Extension generations | exact domain owner | Product Consumers, status |
| Child processes | authorized Process Host binding | domain host diagnostics |
| Sandbox scopes | Sandbox runtime | execution status |
| Model-visible inputs | Session/model-call persistence owner | replay and audit |

Inventory is a read-only join over these sources. It never becomes a second
cache that can disagree with the owner ledgers.

The exact implemented authority names remain deliberate: `RuntimeProfileResolver`
resolves Profile choices, `ProductCapabilityProviderResolver` selects among
owner-admitted complete Providers, `RuntimeCapabilityGraphBinder` alone
publishes the Capability Graph, and `RuntimeCapabilityGraphProjector` alone
projects its effective state. `RegistrationScope` and its owner-qualified
leases retain registration custody. There is no new Plugin Profile resolver,
global Plugin transaction, or fifth effective-runtime clock.

## Artifact, Manifest, And Declaration Model

### Secure acquisition and materialization

Source Authority authenticates the origin, fetches bytes, and emits provenance
through a bounded sink/port owned by the Package lifecycle/store owner. It
cannot choose the quarantine path, extract or publish a revision, bind a
runtime, or bypass final verification. The Package lifecycle/store owner alone
orchestrates quarantine, extraction, dependency verification, canonical tree
digesting, leases, and atomic publication of one immutable package tree. No
resolver, manifest parser, source adapter, or runtime owner may consume a
partially downloaded or partially extracted tree.

Materialization is fail-closed and must:

- enforce configured download size, expanded total bytes, file count, per-file
  size, directory depth, and compression-ratio limits before exhaustion;
- reject absolute paths, `..` traversal, duplicate/case-colliding entries,
  device files, FIFOs, sockets, and symlinks or hardlinks that could escape or
  alias outside the candidate tree;
- write only inside a Host-minted quarantine directory using no-follow file
  creation and never extract over an existing published revision;
- execute no package-manager lifecycle hook, source build, setup script,
  import, or adjacent executable while fetching, unpacking, or verifying;
- resolve every dependency to an immutable artifact with an expected digest,
  apply the same materialization rules recursively, and freeze the complete
  dependency closure before activation; and
- compute the canonical tree/release digests and dependency lock, revalidate
  the final tree, then atomically publish an immutable revision or delete the
  quarantine on failure.

Dynamic dependency solving, downloading, building, or installation during
declaration evaluation or activation is forbidden. The current PyPI
materializer can invoke `uv pip install`/`pip install` without wheel-only or a
contained build service; this is an explicit current security gap and cannot be
used for untrusted executable Plugin admission until the PLC9 gate closes it.

### One canonical runtime manifest

An independently selectable Plugin package has one strict `plugin.json`.
The target closed schema rejects unknown keys, duplicate JSON keys, invalid
locators, escaping symlinks, unsupported engine versions, mutable roots, and
incomplete contribution indexes. The current parser already provides strict
JSON, locator/root checks, digest evidence, and inert resolution; completing the
closed manifest schema and engine fields remains a versioned delivery change.
The parser produces an inert `ResolvedPluginPackage`; consumers do not reopen
or reparse the manifest.

The runtime manifest contains only bounded data:

- Plugin identity, version, engine range, and display metadata;
- complete contribution index and declaration-source references;
- configuration schema and defaults;
- dependency and compatibility requirements;
- requested authority/effect classes and execution topology; and
- interface metadata needed for inspection before activation.

An ergonomic YAML, TOML, decorator, or Python builder may exist only as an
offline authoring input. Packaging compiles it deterministically to canonical
JSON and declaration IR. A Python builder is an explicit author-invoked build
step, never code imported by install, validate, inspect, or runtime discovery;
its output is still untrusted and passes the same schema checks. The Host
consumes only the canonical form.

Native Resource roots remain manifest-free. The current resolver's ability to
derive a compatibility descriptor when `plugin.json` is absent must not be used
to synthesize a managed Plugin Instance for a plain Resource root; the Resource
Catalog cutover must make that distinction explicit.

### One versioned tagged declaration IR

Every contribution has one discriminated kind, schema version, exact owner,
execution model, configuration reference, and source evidence. The currently
implemented kinds are `resource_item`, `tool_pack`, `command_pack`, and
`capability_provider`; the currently implemented execution models are
`data_only` and verified `in_process`.

New contribution or execution-topology kinds require versioned codecs, explicit
compatibility diagnostics, owner admission, lifecycle tests, and rollback or
retirement evidence. Unknown versions are rejected; no generic
`dict[str, Any]` fallback reaches runtime owners.

Declarations are immutable proposals. They contain no live object, closure,
service reference, secret, or Registration handle. A trusted authoring
Definition may build declarations, but its evaluation is itself an exact
approved execution use and cannot activate them.

### Authority-bound locators

Package paths become opaque, authority-qualified locators after resolution.
They are resolved only through the verified revision root that minted them.
Downstream owners receive content handles or bounded readers rather than
ambient filesystem paths wherever practical. A locator never implies trust or
permission.

## Lifecycle And Linearization

There is no single Plugin state machine. Four related state families remain
independent and are correlated by exact identity:

```text
artifact/cache: Package lifecycle-owned quarantine, retention, and GC states
desired set:   {absent, installed_disabled, installed_enabled}
Instance:      ACTIVE --graceful--> DRAINING --> RETIRED
               ACTIVE --security--> REVOKING --> RETIRED
               DRAINING --security--> REVOKING
owner state:   exact domain-owner generation lifecycle
```

An update creates a new artifact and Instance revision. It never mutates the
bytes or live objects of the old revision in place. `update_staged` is progress
in the management operation journal while desired selection remains unchanged;
it is not a desired state. Preparation likewise belongs to an activation or
owner operation, not to the Plugin Instance execution-state machine.

### Resolve and inspect

1. A Source Authority authenticates the source and delivers provenance plus a
   bounded byte stream through the Package lifecycle/store owner's sink.
2. The Package lifecycle/store owner quarantines and materializes the bytes,
   then binds content digest, source provenance, dependency closure, and
   immutable root evidence before atomic revision publication. Embedded bytes
   cross the same final verification/publication boundary.
3. The canonical parser returns an inert descriptor and typed locators.
4. Inspection can report every requested contribution and authority without
   loading executable code.

### Preflight and declare

1. Product selection fixes scope, configuration, Plugin revision, and policy
   ceilings.
2. Data-only declaration documents decode under bounded strict schemas.
3. Executable declaration sources revalidate source/publisher provenance,
   dependency closure, revocation, and topology eligibility before consuming a
   fresh exact Approval decision and one-use reservation. Approval can allow an
   action inside a Host policy ceiling; it can never grant host-equivalent trust
   or convert third-party code into an in-process candidate.
4. Evaluation returns only immutable declarations; failure or cancellation
   consumes or aborts the attempt without publishing state.
5. All declaration sources join before the preflight is finalized once.

### Admit and bind

1. Product expands Composition Sets into explicit Plugin selections; a Plugin
   cannot select itself.
2. Each exact owner normalizes, checks compatibility and conflicts, and issues
   an admission record for its complete candidate.
3. Product resolves owner-admitted Provider closure without widening grants.
4. Component Hosts prepare exact owner generations.
5. Publication is atomic only inside an existing owner transaction. There is
   no cross-owner pretend transaction.
6. The Session becomes usable only after required owner generations and
   Consumer captures are committed.

### Disable, revoke, update, and remove

- Disable changes desired selection for new composition, drains live Instance
  leases, then requests exact owner retirement.
- Security revoke blocks new use immediately and invokes the stronger owner
  drain/termination path; it is not reported as complete while code or
  registrations remain active.
- Update stages and validates a new revision before an atomic desired pointer
  cutover. Existing Sessions either retain their pinned revision or receive an
  explicit `restart_required` result.
- Remove concerns desired installation state. Owner retirement, process
  termination, private-data deletion, artifact GC, and backup expiry are
  separate observable operations.
- Cleanup is retryable and journaled. Failure never reports a false terminal
  state.

## Contribution And Skill Model

### Resources and Skills

Skills are typed Resource projections, not universal Plugins. A Skill normally
contains instructions, metadata, references, assets, and optional named
scripts. The Resource Catalog and its source/parser mechanisms may themselves
be owner-defined Plugin components; each discovered Skill remains a
`resource_item` with Resource identity and provenance.

All Skill list, enable/disable, summary, explicit-load, refresh, and
model-visible paths must converge on one Resource Catalog generation. The
catalog loads bodies lazily and binds reads to exact source-generation evidence.
Native workspace or user Skills need no manifest, install record, Plugin
Instance, or Python SDK.

### Skills with scripts

Scripts are supported content, but their existence grants no execution
authority. A Skill body may reference a script for human or model guidance. A
script becomes a managed executable action only through a separate strict
declaration that binds:

- exact Resource or package revision and script digest;
- interpreter/runtime, structured shell-free argv template, cwd policy, and
  bounded environment;
- declared inputs, outputs, timeout, resource limits, and effect classes;
- required containment and network/filesystem ceilings; and
- exact Tool/Policy/Approval/audit ownership.

The catalog and Skill parser never execute scripts. Current scripts may be
invoked through already authorized generic Tools; the target managed
Skill-script facade is not public until PLC8 proves both native and packaged
forms. Untrusted scripts require proven containment; a child process alone is
not a Sandbox.

## Execution Architecture

Execution topology follows lifetime, dependency, protocol, latency, deployment,
and containment needs. Trust and authority remain separate inputs. The choice
does not follow a coarse label such as "destructive Plugin".

| Topology | Appropriate use | Security condition | Owner path | Status |
| --- | --- | --- | --- | --- |
| `none` | Resources and static declarations | no code execution | typed parser and exact owner | Implemented as `data_only` |
| `in_process` | Narrow low-latency first-party/OEM Providers | separately established host-equivalent trust; process containment is impossible | verified Definition evaluator and Component Host | Partially implemented |
| `one_shot` | Bounded scripts, formatters, generators, command helpers | exact action authorization; required containment for untrusted code | authorized Exec/Tool path | Generic substrate exists; managed Skill facade pending |
| `local_worker` | Long-lived, stateful, streaming, native, dependency-conflicting, or third-party Providers | every non-host-equivalent executable requires proven non-downgradable containment plus narrow IPC | exact owner host over authorized Process Host | Target; not yet a Plugin declaration kind |
| `remote_service` | managed connectors or externally hosted Providers | authenticated narrow protocol, egress policy, tenant isolation, and remote trust evidence | exact domain owner over a Host-owned client binding | Target; protocol-specific |

### Supervised Worker model

Loushang should support a Nomad-driver-like local Worker shape without adopting
a universal Plugin runtime protocol. A Worker is started, monitored, health
checked, drained, terminated, and recovered by a non-owning coordinator, while
the domain Component Host retains admission, semantic protocol, state, and
publication ownership.

The common Worker envelope may standardize only mechanics:

- version and feature negotiation;
- immutable Instance and attempt identity;
- bounded framed transport and backpressure;
- readiness, heartbeat, cancellation, drain, and termination;
- audit correlation and secret-handle redaction; and
- crash, restart-budget, and cleanup evidence.

Handshake and every frame bind the exact Plugin revision, Instance, owner
generation, execution attempt, connection nonce, direction, and request ID.
Stale generations, replayed IDs, wrong-direction frames, unknown required
features, and cross-attempt responses fail closed. The launch environment and
inherited file descriptors are deny-by-default and reduced to an explicit
Host-built allowlist.

Domain messages remain versioned owner protocols. A remote service uses the
same ownership rule but has distinct identity, authentication, availability,
revocation, and data-residency evidence; it is never treated as a local Worker
with a URL. No Worker or remote service receives a remote
`PluginContext`, arbitrary service lookup, raw Host registry, reusable Approval
token, or ambient credentials. A Worker crash retires or degrades only the
exact owner generation that depended on it.

Activation authorization permits only the exact spawn and handshake. It is not
a bearer grant for future Worker requests. For every IPC request involving
filesystem, network, credential, process, publishing, or external effects, the
Host/domain adapter reconstructs one canonical exact action and executes it
through current Policy, Approval when required, Authorization, Sandbox, and
audit. The Worker receives only the result or a narrow operation handle; it
cannot directly exercise the Host authority. Pure computation messages may be
covered by the owner protocol, but never smuggle an undeclared effect.

### Process isolation is not security isolation

A same-user child process may read files, inherit environment variables, open
network connections, launch descendants, and inspect sibling processes. The
Worker path therefore requires the existing separation:

```text
Policy:    may this actor attempt the action?
Approval:  may this exact exception be granted once?
Sandbox:   what can the process actually access?
Host:      who owns start, I/O limits, termination, and cleanup?
Domain:    what do messages mean and what may be published?
```

Required containment fails closed before spawn. For non-host-equivalent local
code it is an admission invariant that ordinary Product policy cannot downgrade.
Best-effort degradation is visible and can satisfy only explicitly eligible
host-equivalent or non-executable paths; it never satisfies required
containment.

## Security Model

### Independent security axes

The Host evaluates these independently:

- source authority and acquisition channel;
- immutable artifact identity and release provenance;
- publisher trust and host-equivalent eligibility;
- installation and runtime scope;
- declaration kind and execution topology;
- requested filesystem, network, process, credential, and external effects;
- Product/managed policy ceilings; and
- actual Sandbox backend enforcement.

No single `trusted: true`, source type, signature, built-in flag, or process
boundary substitutes for the others.

### Mandatory invariants

1. Install, inspect, list, validate, and dry compilation do not execute package
   code. Source builds and package-manager lifecycle hooks are excluded from
   runtime installation; admitting them later requires a separate contained
   build service and a verified output artifact.
2. Installed is not enabled; enabled is not admitted; admitted is not mounted;
   mounted is not authorized for every future action.
3. Every executable use revalidates exact revision, subject, actor, scope,
   policy, decision lifetime, revocation epoch, and containment requirement.
4. Approval decisions are immutable, one-use where specified, and never passed
   to Plugin code as bearer capabilities.
5. Secrets are resolved by Host-owned handles at the narrowest call boundary.
   Manifests, logs, status, model input, Worker frames, and approval text do not
   contain reusable secret values.
6. Model-visible Plugin and Skill content is committed with exact provenance,
   source revision, digest, precedence, and selection facts before sampling.
7. Package locators cannot escape verified roots or change after resolution.
8. Unknown schemas, contribution kinds, execution shapes, authorities, and IPC
   messages fail closed.
9. Termination, retirement, cleanup, and data deletion have distinct receipts;
   one cannot be inferred from another.
10. Inventory and diagnostics are projections and cannot activate, authorize,
    or repair state through read paths.

### Threat model

The design assumes Plugins and their dependencies may be malicious, buggy,
stale, compromised after publication, or intentionally misleading. It also
assumes configuration may be concurrently changed and that a Host may crash at
any lifecycle boundary. The system must contain or diagnose:

- import-on-discovery and install-hook execution;
- mutable-package time-of-check/time-of-use attacks;
- path traversal and symlink escape;
- dependency substitution and revision drift;
- authority inflation and Approval replay;
- forged readiness, stale IPC responses, and Worker protocol confusion;
- output floods, fork bombs, hangs, and cancellation races;
- leaked secrets or environment values;
- partial update, retirement, cleanup, and crash recovery; and
- conflicting or stale owner publications.

## Developer Experience And Public SDK

The public experience is deliberately tiered. Authors use the lowest level
that satisfies the requirement.

| Level | Author input | Plugin identity? | Execution | Stable target |
| --- | --- | --- | --- | --- |
| L0 native Resource | conventional `SKILL.md`, prompt, theme, method, assets | No | declarative; optional managed action later | no SDK required |
| L1 data package | `plugin.json` plus declaration documents and Resources | Yes only when independently managed | declarative | schema + validator |
| L2 Product build facade | small typed Python build specification | optional built-in Plugin or embedded contribution | declarative by default; only in-process code requires separately proven host-equivalent trust | private before PLC8 |
| L3 Worker SDK | generated domain protocol interface | usually yes | contained supervised Worker | after Worker contract stabilizes |

### SDK design rules

- The author-facing API expresses intent: Resources, Tool packs, Capability
  Providers, requirements, configuration, and execution requests.
- Builders return immutable serializable specs. They do not receive owner,
  process, Approval, Sandbox, journal, graph, registry, or secret objects.
- `validate` and `inspect` never import author code. An explicitly named
  conformance command may execute a verified sample under the real gates.
- Built-in and external packages compile to the same declaration IR and reach
  the same owner admission/binding paths. Built-ins may skip remote acquisition
  and user installation, but never downstream owner validation.
- Embedded contributions compile directly into Product build input and do not
  acquire a fake Plugin Instance. An embedded Plugin is created only when the
  Product intentionally exposes independent selection or lifecycle.
- Generated files are reproducible, schema-versioned, and diffable. Runtime
  reflection is not the source of truth.
- Advanced APIs are owner-qualified; there is no generic `register(name,
  object)` escape hatch.

Illustrative target authoring, not a current public API:

```python
from loushang.plugin import package, resource

plugin = package(
    id="com.example.review",
    version="1.0.0",
    contributions=[
        resource.skill("skills/review/SKILL.md"),
    ],
)
```

Product build input stays equally small while preserving the identity choice.
The following is Product-owned build-facade pseudocode, not another promised
module or current public API:

```python
product = build_product(
    embedded=[resource.skill("skills/base/SKILL.md")],
    built_ins=[plugin],
)
```

The first entry is owned by the Product/Resource composition with no Plugin
lifecycle. The second is a real built-in Plugin and is independently visible,
selectable, diagnosable, and revocable.

### Tooling contract

The SDK ships with one schema compiler and validator capable of:

- canonical manifest/IR generation;
- engine-version and feature negotiation checks;
- contribution/owner and configuration validation;
- path, size, dependency, and authority linting;
- inert inventory preview and deterministic fingerprint output; and
- explicit, opt-in execution conformance under representative policy and
  containment profiles.

Diagnostics use stable codes, exact JSON paths, actionable remediation, and
the responsible owner. A Plugin author should not need to understand internal
generation or journal classes to fix a declaration.

### Compatibility promise after SDK stabilization

| Surface | Compatibility rule |
| --- | --- |
| SDK and engine range | one stable SDK major emits a declared manifest/IR range; the package states that engine range and the Host never guesses compatibility |
| Manifest and declaration IR | a supported version decodes exactly; a deprecated version produces an inert diagnostic and migration command; a removed or unknown version fails before code execution |
| Deprecation | non-security removal spans at least one stable SDK release and one documented Product upgrade window with fixtures; urgent security rejection may be immediate but requires a stable diagnostic and remediation |
| Generated Worker client/server | major protocol versions must match; minor features negotiate explicitly; unknown required features fail before readiness and generated code carries its protocol version |

Compatibility fixtures cover both the oldest supported and first rejected
versions. A compiler may produce a new canonical artifact; the runtime does not
silently rewrite an installed manifest, IR document, or Worker frame.

## Product Roles

### Terminal products: Work and Coding

Terminal products consume the shared lifecycle but choose their own Product
composition, defaults, prompts, Tools, presentation, and policy profile.

- Work primarily benefits from Skills, methods, connectors, domain Resources,
  and supervised integrations.
- Coding primarily benefits from language services, architecture analyzers,
  Tool/Command packs, repository Skills, and project-scoped Resources.
- Both expose one coherent list/inspect/enable/disable/update/explain journey.
- Product-specific UX projects shared typed state; it does not own another
  Plugin registry or lifecycle writer.

The base Product remains useful with every optional Plugin disabled.
For Coding, the Product Kernel, agent/session orchestration, minimum mandatory
system prompt, and recovery path remain Product-owned. A `coding.base` Plugin
may provide selectable/default Resource and Tool contributions, but it cannot
become the Coding Product Kernel or the only path to a usable Product.

### Server products

Server deployments reuse manifests, declaration IR, admission, exact-owner
binding, Workers, and audit evidence, but normally replace interactive prompts
with managed policy and pre-approved deployment configuration. They additionally
need tenant isolation, quotas, fleet rollout, health aggregation, staged
revision rollout, and centralized revocation.

Tenant, deployment, node, Session, and Agent scopes must be explicit. A package
installed in a server fleet does not become enabled for every tenant, and a
tenant decision cannot widen deployment policy. Worker process isolation alone
does not establish tenant security; OS/container/identity boundaries must match
the deployment threat model.

## Configuration, Credentials, And Mutable State

Plugin configuration is one typed schema with layered, owner-defined
precedence. The Host computes and fingerprints the effective configuration
before preflight; Plugin code receives only the validated subset intended for
its contribution.

Configuration scope, package installation scope, Plugin desired-state scope,
runtime Instance scope, and Resource precedence are separate axes. The UI may
present them together but must not infer one from another.

Credentials are references to Host-owned providers, never manifest literals or
ambient environment promises. Mutable component data belongs to the exact
domain owner under a versioned namespace keyed by Plugin, contribution, and the
owner-defined effective security scope. That scope includes tenant, deployment,
and runtime Instance where applicable. Credential handles, Workers, remote
clients, caches, migrations, and cleanup jobs bind to the same scope.

Cross-tenant Worker, connection-pool, cache, or mutable-state sharing is denied
by default. A specific owner protocol may permit it only with demonstrated data
isolation and explicit deployment policy. Update migration, quota, backup,
deletion, and recovery remain owner-defined. Uninstall does not silently delete
mutable data.

## Diagnostics And Model Visibility

Every management surface reads a single correlated projection with separate
facts for:

- artifact verification and retention;
- desired installation and selection;
- preflight, policy, Approval, and execution use;
- owner admission and mounted generations;
- Worker/process/Sandbox state;
- restart, drain, retirement, cleanup, and data-deletion debt; and
- model-visible Resource and Tool provenance.

The projection reports skew rather than hiding it. For example, an updated
desired revision may coexist with Sessions pinned to the previous revision, or
a disabled Plugin may still be draining an old owner generation.

Only content and capabilities actually supplied to a model call enter Model
Input persistence, including complete Tool definitions and schemas rather than
only their names or Plugin fingerprints. Fingerprints are supplementary
provenance only. Replay uses committed immutable inputs and never reopens the
current Plugin package. A Plugin inventory summary alone is not sufficient
replay evidence, and secrets or private environment values never enter normal
model input.

## Current-To-Target Compatibility Ledger

| Area | Current truth | Target decision | Delivery owner |
| --- | --- | --- | --- |
| Manifest | strict JSON/root/digest parser plus a manifest-free compatibility descriptor; fully closed Plugin schema pending | explicit Plugin identity requires canonical closed-schema `plugin.json`; native Resources stay manifest-free without Plugin identity | PLC8 |
| Declaration | strict v2 IR; `data_only` and verified `in_process` | add execution topologies only through versioned codecs | PLC8/PLC9 |
| Package materialization | directory verification is no-follow, but PyPI materialization may execute an sdist/PEP 517 build through `uv`/`pip` | verified wheel-only artifacts or a separately contained build service; bounded safe extraction and digest-locked dependency closure precede atomic publication | PLC9 package lifecycle |
| Management | durable desired state, update, retirement, Instance and cleanup foundations | one CLI/RPC/UI/SDK projection and repair workflow | PLC9 |
| Enablement compatibility | `manifest.enabled` and `source.enabled` can still veto a Product-selected Plugin during preflight | `manifest.enabled` becomes at most an install-time author default, `source.enabled` becomes Source Authority availability, and `PluginManagementService` desired state is the sole runtime selection writer; remove the peer preflight veto after one-time migration | PLC6/PLC9 |
| Capability Provider | exact admission/selection/binding foundation and first Coding LSP path | reuse unchanged for additional Providers | PLC6/PLC7 |
| Resource Catalog | private shadow and composition foundations | one production Catalog and typed Skill projection; delete peer paths | RCP5/PLC6 |
| Skill scripts | scripts may be referenced and generic authorized Tools can execute | strict native/package managed action facade | PLC8 |
| Public SDK | internal authoring package exports no public SDK | tiered schema/builder/Worker SDK after production evidence | PLC8 |
| Built-ins/embedded | Product-specific paths exist | compile to common IR; preserve identity distinction | PLC6/PLC8 |
| Worker Plugins | Process Host and Sandbox substrates exist | contained supervised Worker declaration and owner protocol | PLC9 |

Compatibility adapters may translate old inputs into the canonical contracts,
but they may not parse manifests again, mutate owner state, bypass admission, or
remain a second effective path. Each adapter needs an owner, deletion gate, and
diagnostic sunset.

## Acceptance And Change Rules

This architecture is accepted only when:

1. architecture review finds no duplicate authority or unowned lifecycle;
2. security review finds no import-on-inspect, authority inflation, Approval
   replay, containment overclaim, secret exposure, or false terminal state;
3. developer-experience review confirms the L0-L3 ladder, built-in/embedded
   distinction, Skill scripts, diagnostics, and migration are usable;
4. all blocking findings are corrected and re-reviewed by the same independent
   reviewer;
5. architecture-document validation passes; and
6. the final review evidence is preserved in the acceptance issue/PR record.

Future changes must be small and owner-scoped. A new contribution kind needs an
owner contract. A new execution topology needs a threat model and lifecycle. A new
wire surface needs version negotiation and compatibility fixtures. A new live
state needs one writer, recovery, diagnostics, and deletion semantics.

Detailed wire records remain in the
[PLC1B Declaration Contract](plugin-declaration-foundation-plc1b-contract.md),
execution decisions in the
[PLC3 Execution Trust Contract](plugin-execution-trust-plc3-contract.md), and
Capability admission in the
[PAP4 Contract](plugin-capability-admission-pap4-contract.md). The
[Resource Catalog Plan](resource-catalog-pluginization-plan.md) owns Resource
and Skill convergence detail. These documents refine this architecture within
their exact scope; they do not create a second Plugin architecture.

## Reference Conclusions

The design incorporates de-risked lessons from contemporary harness and coding
agent systems without copying their object models:

| Reference | Adopted conclusion | Deliberate Loushang boundary |
| --- | --- | --- |
| DeepSeek Harness | reversible Provider registration, explicit dependency seams, composable profiles/bundles, and a pluggable Skill catalog are valuable | not every service or content item becomes a Plugin; exact owners and typed Capability seams remain fixed |
| Codex | Plugin packages should resolve to inert authority-bound descriptors and may bundle Skills plus optional tool/service integration | resolution does not activate components; model-facing summaries are bounded projections of actual availability |
| Claude Code | built-in registries, scoped enablement, versioned installation caches, and simple marketplace UX improve adoption | install, enable, admission, activation, and retirement remain distinct states rather than a reload shortcut |

A Skill remains content with scripts, references, and assets, while its
catalog/parser is the pluggable mechanism. Built-in and one-command package UX
are worth preserving only when they compile to the same strict runtime
contracts.

These conclusions preserve Loushang's deliberate difference: typed
Definition/Provider/Consumer seams and exact owner generations replace a
universal mutable Plugin context.

## Consequences

The architecture is intentionally stricter inside and simpler outside.
Authors can begin with a directory, progress to a declarative package, and use
a generated Worker SDK only when necessary. Product teams can ship built-ins
and embedded content without creating special runtimes. Operators gain exact
desired/effective/retirement explanation and fail-closed execution.

The cost is that new contribution and Worker protocols require owner-specific
contracts, and not every update can hot-swap a live Session. That cost buys
high cohesion, explicit authority, deterministic recovery, and a Plugin system
whose convenience does not depend on invisible privilege.
