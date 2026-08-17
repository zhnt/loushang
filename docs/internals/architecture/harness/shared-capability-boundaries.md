# Shared Capability Boundaries

## Purpose

This document describes how common capabilities should be split between
`loushang.harness`, product adapters, OEM layers, and extensions.

The guiding rule is:

```text
harness provides mechanism
product adapter provides defaults and semantics
OEM layer overrides product policy
extensions contribute optional providers or capability items through declared surfaces
```

Canonical Product, OEM, Capability, Package, Plugin, and Extension terms are
defined in the
[Product And OEM Glossary](../../glossary/loushang-product.md).

## Harness Capability Meaning

A **Harness Capability** is a Product-neutral Capability whose public contract,
reusable mechanism, or explicitly overridable platform default is owned by
Harness. `Shared capability` describes cross-Product reuse; it does not define
a Plugin surface, installation unit, global singleton, mandatory activation,
or common Product configuration.

Ownership and binding remain separate:

```text
Harness owns a Product-neutral capability contract or mechanism
  -> Product declares whether and how its runtime consumes it
     -> OEM may vary only Product-declared overlay points
        -> admitted Plugins may contribute only through declared surfaces
```

A Product-owned Capability can consume Harness Capabilities without moving its
domain semantics into Harness. An Extension can contribute a provider or item
to an admitted Capability Slot without owning that Capability, Product, or
lifecycle. The composition rules for those slots are defined by the
[Capability Variation And Replacement Boundary](capability-variation-and-replacement-boundary.md).
Top-level Capability dependency and Mount lifecycle rules are defined by
[Capability Dependency And Mount Lifecycle](capability-dependency-and-mount-lifecycle.md).

## Top-Level Harness Capability IDs

The accepted Harness Capability IDs are deliberately coarse. The pure Planner,
transactional Binder, live per-graph Runtime, and read-only Projector are now
implemented under `loushang.harness.capabilities`. Role completeness and
production mounting still vary by Capability; the
[Harness Capability Catalog](capability-catalog.md) and
[Current Owner Map](current-owner-map.md) are authoritative for that Current
coverage.

| Capability ID | Product-neutral boundary |
| --- | --- |
| `harness.workspace` | workspace access, mutation, search, and authorized execution |
| `harness.resources` | resource discovery, activation, and prompt/skill/tool/command contribution composition |
| `harness.session` | Session, transcript, context, interaction, and continuity mechanics |

These identities are the accepted dependency and observation budget and the
node vocabulary of the implemented Mount runtime. They are not a claim that
every accepted ID is production-mounted, not a general public runtime API, and
not a limit on focused Harness Python modules.
Read, write, edit, process launch, prompt sections, Tool packs, compaction, and
side-question providers remain facets or contributions inside the owning
Capability; they do not become top-level nodes merely because their
implementations have separate modules or lifecycle tests.

Capability IDs name definitions. A live instance combines the ID with a
concrete scope and generation, for example
`harness.workspace@workspace:<workspace-id>`. In dependency diagrams `A -> B`
means A depends on B. The depended-on Capability binds first and disposes last.

Authorization, approval coordination, Sandbox enforcement, limits, audit, and
cleanup remain non-bypassable internals of the applicable Harness Capability.
They are not public replacement nodes. A Product depending on a coarse Harness
Capability receives only its admitted facet view rather than an unrestricted
service bundle.

## Layer Model

The long-term product stack is:

```text
client / UI / SDK
  -> channel
  -> work
  -> method            # optional structured-work layer
  -> product adapter   # coding / design / research / ppt / cowork
  -> harness
  -> agent
  -> ai
```

This is a responsibility stack, not a blanket import rule. The important import
rule is that harness stays below product adapters and above agent primitives.
It must not reach upward into product, work, method, channel, TUI, or AI
provider details.

## Product Kernel Ownership

Prompts, skills, and tools are central product assets, but they are not the
complete product boundary. Every product adapter retains an irreducible kernel
of domain semantics and policy:

- product goals, domain language, and completion criteria;
- system prompt and prompt-section content;
- skill content and default activation policy;
- domain-specific concrete tools;
- selection and activation policy for shared tool packs;
- context salience, compaction, and summarization policy;
- risk classification, approval defaults, and permission policy;
- artifact semantics, such as code changes, research reports, slide decks,
  design assets, or collaborative documents;
- product commands, configuration defaults, and presentation projections;
- product resource content, convention activation, additional/override roots,
  product-only formats, trust policy, and runtime projection.

Harness may own value types, registries, assembly engines, schedulers, and
reusable concrete capabilities. Harness may also provide cross-product platform
defaults such as standard resource roots, layouts, and conventions when they
are explicitly overridable. It must not choose domain content, activation,
trust, or projection policy on a product's behalf.

This product kernel is what differentiates `coding`, `design`, `research`,
`ppt`, `cowork`, and OEM-defined Products. Product bootstrap and wiring should become
small as Harness grows, but these semantics must not migrate merely to reduce
the number of lines in a product package.

## Code-Enabled Products And The Coding Product

The canonical principle is:

> **Every Product may be code-enabled, but not every Product is the Coding Product.**

A PPT, Research, Design, Method, or OEM-defined Product may mount an admitted
facet view of `harness.workspace`, `harness.resources`, or `harness.session`.
That composition remains one Product Runtime and one Product Session. It does
not import or embed the Coding Product, and it does not gain repository-
engineering authority merely by mounting a shared tool pack.

Harness owns the reusable mechanisms for workspace read, list, search, write,
edit, and process execution. A Product owns their activation, allowed roots,
effective grants, approval and Sandbox policy, Product-tuned descriptions,
artifact meanings, and final presentation. Full repository engineering may
add Coding-owned Git workflow, session compatibility, prompts, diagnostics,
and other Product Kernel semantics without pulling the neutral mechanisms back
into Coding.

The accepted target Coding Capability inventory contains only the mountable
IDs `coding.arch` and `coding.lsp`. Architecture import-graph
analysis and language-server selection, synchronization, and tool semantics
remain Coding capabilities while they have a Coding-specific contract. They
may declare dependencies on `harness.workspace` and other accepted target
Harness Capabilities while consuming only admitted facets. The matching Coding
constants already exist, but the top-level planner and live Mount graph do not.
This inventory statement does not imply that Coding has only two Product-
specific semantics; it distinguishes mountable Capability IDs from the rest of
the Coding Product Kernel.

If another Product needs bounded file or script automation, it should select
Harness capabilities. If it needs a durable repository-engineering Session,
Git/LSP lifecycle, and Coding compatibility semantics, it should perform an
explicit Product Handoff or delegation to the Coding Product instead of
copying or importing that Product runtime.

## Tools

Harness may own:

- tool definition value types that are not product-specific;
- schema inference and normalization helpers;
- registry/resolution interfaces;
- contribution records from Resource Packages or Extensions;
- availability metadata and diagnostics;
- wrapper engines that adapt neutral tool call inputs to `loushang.agent`
  tool primitives;
- reusable concrete tool packs, including workspace read, list, search, write,
  edit, and process execution implementations;
- execution-scope adapters that route protected long-lived process starts
  through the same Policy, Approval, effect, audit, and Sandbox ceilings;
- generic process helpers, output limits, ignore matching, and optional
  external binary resolution used by those packs.
- allowed/requested/active tool accounting, ordered resolution, activation
  snapshots and diffs, and refresh/rebind coordination with injected policy.

Product adapters own:

- default tool packs;
- product-specific tool names and descriptions;
- executable catalog admission and language-server selection;
- domain-specific coding/design/research/ppt tools;
- prompt wording around tool use;
- destructive-operation policy;
- product-specific tool discovery.

Extensions may contribute tools through harness-shaped records, but product or
OEM policy decides whether those tools are active.

`loushang.harness.capabilities.tools` owns this neutral activation coordinator.
Products retain default pack membership, allowlists, new-tool activation
policy, Agent materialization, execution context, prompt rebuilding, audit
events, and presentation.

## Approval

Harness may own:

- `ApprovalRequest`;
- `ApprovalDecision`;
- `ApprovalResolver` protocol;
- headless default resolvers such as deny-all or allow-readonly;
- approval broker mechanics that can suspend and resume a pending decision.

Product adapters own:

- interactive approval UI;
- product-specific risk classification;
- persisted allowlists;
- explanations shown to users;
- default approval rules.

The neutral `ApprovalBroker` now owns correlation, pending futures, timeout,
cancellation, fallback, and disposal without importing UI callbacks. Product
interactive resolvers remain payload/presentation facades over that broker and
continue to own all displayed wording and persisted grants.

## Presentation And Renderers

Harness may own neutral presentation records:

- text blocks;
- structured rows or key/value fields;
- file references;
- image/file/artifact references by opaque id;
- renderer protocols and registry mechanics.

Harness should not import `loushang.ai` content-part types directly. It may
adapt to agent tool result primitives or define its own neutral presentation
blocks.

Product adapters and UI packages own:

- terminal widgets;
- web/app rendering;
- transcript layout;
- product-specific labels and grouping;
- incremental rendering behavior.

## Workspace And Exec

`harness.workspace` is the accepted target top-level Capability ID for this
boundary. The concrete protocols and operations below are narrow facets of
that Capability, not separate DAG nodes.

Harness may own neutral workspace mechanics:

- workspace path reference types;
- file operation request/result shapes;
- process execution request/result shapes;
- stream event records;
- bounded session-owned process launch/handle records and lifecycle mechanics;
- workspace tool protocols;
- reusable concrete workspace tool definitions and their neutral renderers.

Product adapters own:

- which workspace roots are allowed;
- whether shell commands can run;
- approval policy around writes and process execution;
- how file edits are described to users;
- default workspace tool activation.

The bounded process Host remains policy-free. Products receive a narrow
authorized launcher assembled above it; they do not receive the concrete Host
or a public Sandbox process backend.

Use `loushang.harness.workspace` or `loushang.harness.tools.workspace`; do not
create a top-level `loushang.workspace` package.

Reusable concrete behavior is mechanism, even when Coding was its first owner.
Products inject policy evaluators, approval resolvers, workspace roots,
product-tuned descriptions, activation, and presentation overrides. Harness
must not silently select those values.

## Resources

`harness.resources` is the accepted target top-level Capability ID for this
boundary. Resource runtime, prompt-section, skill-activation, Tool-pack, and
Command-pack selection may retain private Runtime Profile facets without
expanding the accepted target Capability graph.

Harness may own:

- resource descriptors that are product-neutral;
- source metadata;
- frontmatter parsing;
- resource diagnostics;
- platform home resolution through `LOUSHANG_HOME` or `~/.loushang`;
- the standard `<workspace>/.loushang` root and resource directory layout;
- standard scope vocabulary and an overridable precedence preset;
- reusable `AGENTS.md` discovery and optional compatibility conventions;
- filesystem/package discovery, merge, reload, and materialization engines;
- built-in package registration and enumeration.

Product adapters own:

- prompt/theme/skill/extension content and domain semantics;
- convention selection and default activation;
- additional or overridden roots and product-only compatibility formats;
- product built-in package content and registration;
- trust, permissions, package filters, and remote-source policy;
- product-specific resource validation;
- Product-exclusive resource injection into prompts or tools; standard prompt,
  skill, and context projection remains a Harness capability.

If `loushang.resource.frontmatter` becomes part of the shared substrate, migrate
it intentionally into `loushang.harness.resources.frontmatter` rather than
expanding `loushang.resource` into a broad top-level subsystem.

## Prompt

Harness may own prompt assembly contracts, deterministic mechanisms, and
standard concrete behavior:

- prepared prompt value types;
- prompt section records;
- trace/diagnostic records;
- ordered composition;
- injectable template argument parsing and placeholder expansion;
- a neutral default system prompt;
- standard project-context, prompt-fragment, skill, tool, and runtime-footer
  projection;
- standard prompt/skill resource preflight and diagnostics.

Product adapters own:

- Product-exclusive system prompt text and instructions;
- overrides to standard/compatibility instruction conventions;
- domain-only resource projection, salience, or ordering;
- Product-owned template content and selection;
- domain-specific sections and preflight beyond the standard resource commands.

An overridable default is not Product-owned merely because it makes a choice.
Neutral section composition and template expansion live in
`loushang.harness.capabilities.prompt`; the standard resource-aware assembler
and preflight live beside it in `prompt_assembly` and `prompt_preflight`.
Products inject a domain prompt or override sections only where their behavior
genuinely differs.

## Commands

Harness may own:

- generic command descriptors with opaque source metadata;
- name normalization and slash-command parsing;
- aliases, precedence, conflict reporting, catalog lookup, and completion;
- ordered sync/async dispatch whose results remain opaque to Harness.

Product adapters own:

- builtin and domain command definitions;
- source precedence values and activation choices;
- concrete handlers, resource projection, diagnostics, routing, and UI.

`loushang.harness.commands` provides the neutral mechanism.
Products decide what a command means and what effects its handler may perform.

## Context

Harness may own:

- context item refs;
- context bundles;
- budget accounting;
- truncation and packing contracts;
- neutral context assembly protocol;
- context diagnostics.

Product adapters own:

- what facts enter context;
- ranking and salience policy;
- summarization prompts;
- domain-specific compaction behavior;
- transcript rebuild semantics.

Do not create `loushang.context` now. Use `loushang.harness.context` for shared
mechanics and keep product memory/context policy inside product packages.

`loushang.harness.context.budget` now owns deterministic percentage/reserve
threshold accounting and `loushang.harness.context.usage` owns the neutral
usage-estimate result record. Coding still owns message token estimation,
model adaptation, usage snapshots, compaction decisions, and all transcript
policy. Context item refs, bundles, diagnostics, and general packing contracts
remain deferred.

## Memory

Harness may later own a narrow memory provider protocol:

- `MemoryRef`;
- `MemoryQuery`;
- `MemoryHit`;
- `MemoryProvider`.

Harness should not own memory storage, long-term profile semantics, or product
memory policy. Those belong to products, OEM layers, or deployments.

Do not introduce top-level `loushang.memory` until there is a separate accepted
architecture decision.

## Session And Lifecycle

`harness.session` is the accepted target top-level Capability ID for this
boundary. Store, transcript, compaction, interaction, and continuity owners
retain their focused current contracts and internal Binding Facets; the future
graph projector will expose one aggregate Mounted Capability state.

Harness may own:

- host lifecycle protocols;
- idle/abort/dispose contracts;
- queue snapshot records;
- steering/follow-up request shapes;
- run status and generic session status records;
- opaque product runtime binding records and bound/unbound context delegation;
- a serialized current-session slot with injected prepare, shutdown,
  invalidate, dispose, activate, and rebind callbacks;
- generic delayed/coalesced scheduling and deterministic drain mechanics;
- turn interception/preflight/queue/start ordering and retry/backoff lifecycle;
- resource watch/refresh and extension bind/refresh/invalidate ordering;
- opaque session-operation phases, candidate rollback, import staging,
  replacement callback order, and navigation abort scopes.

Product adapters own:

- Product controller policy and adapters;
- storage-provider selection and Product storage layout;
- JSONL schemas;
- command execution;
- Product event projection adapters;
- resource activation and projection policy;
- UI-facing session models;
- session replacement decisions and events, concrete persistence/index
  contents, cwd recovery, tree/fork/import/clone semantics, and diagnostics.

Do not move `AgentSession`, product controllers, or store code wholesale into
harness.

`loushang.harness.events` owns host/session event facts, queue and retry result
records, the common runtime envelope, scoped publisher, and ordered dispatch.
`loushang.harness.runtime.types` owns host/run snapshots and queue modes;
`runtime.input_queue`, `runtime.turn`, `runtime.retry`, and
`runtime.execution` own reusable behavior. `loushang.harness.host` is the outer
RPC/channel/mode adapter and `host.types` owns only its adapter result.
Resource and extension modules continue to own watch/refresh and
bind/refresh/invalidate state machines.
`loushang.harness.runtime` owns generic bindings/contexts, session transitions,
operation phases, rollback, import staging, replacement callback order,
navigation abort scopes, and coalesced scheduling. Coding retains message
construction and delivery, its Product event schema and projection adapter,
replacement decisions, controller policy/adapters, storage composition, and UI
state. Harness storage owns the persistence protocols and Memory/File reference
backends; the optional Agent transcript profile owns open transcript commits.

## Work, Method, And Channel References

Harness may carry opaque ids or metadata for:

- work runs;
- method descriptors;
- method steps;
- artifacts;
- channel requests.

Harness must not import `loushang.work`, `loushang.method`, or channel core to
interpret those values. Product adapters, work projection, and channel hosts
perform interpretation outside harness.

## Diagnostics

Harness may own:

- neutral diagnostic records;
- severity/source/category vocabulary;
- diagnostics query interfaces;
- health/status report contracts.

Product adapters own:

- actual checks;
- user-facing remediation;
- product-specific grouping;
- CLI/TUI formatting.

`loushang.harness.diagnostics.types` now owns the shared vocabulary, records,
queries, summaries, and startup-check contracts.
`loushang.harness.diagnostics.service` owns bounded retention, fingerprinting,
deduplication, filtering, aggregation, normalization, and caller-supplied check
execution. Coding retains actual checks, observability mapping, serialization,
remediation, session projection, and UI behavior.

## OEM Override Model

The canonical composition rules are defined by the
[Capability Variation And Replacement Boundary](capability-variation-and-replacement-boundary.md).
In particular, `override` is an umbrella term: every surface must declare
Aggregate Contribution, Ordered Interception/Decoration, Resource Overlay, or
Exclusive Replacement semantics. Product and OEM variation cannot bypass a
Harness invariant enforcement layer.

OEMs vary Product behavior through three mechanisms. An OEM Package is the
separate distribution boundary that may carry the corresponding Profile,
overlays, and Plugins:

| Mechanism | How it works | Examples |
| --- | --- | --- |
| Protocol injection | OEM supplies an implementation of a Harness-defined protocol; Harness calls it without knowing the product or OEM identity | `PolicyEvaluator`, `ApprovalResolver`, `ExtensionPolicyResolver` |
| Resource overlay | OEM directories are discovered alongside built-in and product directories; same-key files shadow lower-precedence layers | `skills/*/SKILL.md`, `methods/*/METHOD.md`, `prompts/*.md`, `themes/*.json` |
| Extension registration | OEM ships extensions that declare `ExtensionSurfaceDescriptor` records; product/OEM policy gates activation | tools, commands, model providers, channel adapters, hooks |
| OEM Package with Plugin contributions | The OEM Package distributes OEM Profile/configuration and resource roots; optional `loushang-plugin.json` manifests identify independently activated Plugin contributions | OEM Package → `PluginManager → PluginResolver → ResourceDescriptors` |

### Override Layer Order

```text
harness provides mechanism
  -> product adapter provides defaults and domain semantics
     -> OEM layer overrides product policy and product resources
        -> project/user-local configuration can further override
           -> extensions contribute optional capabilities
```

A mechanism belongs to Harness and cannot be overridden by OEM (e.g. the
agent loop, the channel envelope protocol, the contribution inventory index).
An OEM may override product defaults, product resource content, and product
activation policy. An OEM may contribute optional providers or capability items
through admitted Extensions. An OEM must not replace Harness mechanisms.

### Dimensions OEMs Can Override

OEMs can independently override each of these dimensions without affecting
others — they are orthogonal replaceability points:

| Dimension | Override method | Harness stability contract |
| --- | --- | --- |
| Product (coding / ppt / research / …) | Ship an OEM-defined Product Adapter with a distinct Product identity that reuses Harness | Product adapters depend on Harness protocols, not internals |
| Channel (TUI / WebUI / SDK / bot / …) | Register an OEM channel adapter | `ChannelEnvelope(WorkOperation/WorkEvent/RuntimeEventView)` schema, additive evolution |
| Method (bugfix / tdd / review / …) | Override method resources in OEM directories | `methods/*/METHOD.md` format and loader mechanics |
| Skill (debugging / refactoring / …) | Override skill resources | `skills/*/SKILL.md` format and activation settings |
| Model (opus / sonnet / gpt / custom / …) | Register OEM providers/endpoints/models via `models.json` overlay or runtime registration | Model registry cascade merge, additive model-descriptor fields |
| Agent topology (single / workflow / subagent / team) | Inject OEM execution strategy that selects `AgentLane` layout per method | `WorkRun` status machine; topology selection is product/OEM policy |
| Tool pack activation | Override activation lists and tool descriptions | Tool definition and contribution record shapes |
| Policy (permissions / risk / approval / …) | Inject OEM `PolicyEvaluator` and `ApprovalResolver` implementations | Protocol signatures, additive evolution |
| Storage backend | Supply OEM `EventLogBackend` implementation | Backend interface (append / query / subscribe) |
| Deployment (desktop / daemon / managed / …) | Implement OEM Host with custom lifecycle policies | Host abstraction that accepts `WorkOperation` and emits `WorkEvent` |
| Theme / branding | Override theme resources and TUI rendering configuration | Theme resource format and TUI `ExtensionHost` API |

### What OEMs Cannot Override

- The agent loop inside `loushang.agent`
- `loushang.work` state machines (`WorkRun` / `WorkPlanRun` / `WorkStepRun` transitions)
- `ChannelEnvelope` protocol shape
- `ExtensionInventory` indexing and duplicate-key contracts
- Harness import-discipline rules

## OEM And Extension Contribution Model

The shared contribution flow should be:

```text
Extension or Resource Package contributes neutral records
  -> harness validates and normalizes contribution shape
  -> product adapter decides applicability
  -> OEM layer may override activation/policy
  -> product host materializes runtime behavior
```

Harness should not decide that an extension is trusted or that a product should
enable a contributed tool, renderer, resource, or policy rule by default.

`loushang.harness.contributions` owns the current shared descriptor, inventory,
indexing, and duplicate-key contracts. Product adapters construct those records
from their manifests or runtime objects and decide whether a contribution is
applicable. Middleware invocation, observer dispatch, activation, precedence,
and OEM override policy remain outside Harness until their cross-product shape
is proven.
