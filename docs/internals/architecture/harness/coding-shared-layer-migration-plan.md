# Coding To Shared-Layer Migration Plan

## Status

Status: accepted long-term planning guidance for `lane/harness`.

This document governs the remaining ownership transfer out of
`loushang.coding`. It replaces future-looking execution estimates in the
historical migration inventory. It does not replace accepted subsystem
boundaries or count an already-existing shared implementation as new migrated
code.

The goal is to make Coding a declarative Agent Product: product content,
selection, policy, compatibility, and final presentation stay in Coding while
the reusable runtime mechanisms live with their semantic shared owner.

## Ownership Rule

Code leaves Coding when both conditions hold:

1. It implements a mechanism, public contract, reusable bridge, or reusable
   default capability.
2. Its product differences can be supplied by an explicit port, profile,
   overlay, configuration value, callback, or admitted runtime layer.

Historical location, a `*Adapter` name, or lack of a second shipping Product
does not make code Product-owned. A bridge that depends only on public
contracts at both ends belongs to the appropriate shared owner.

| Code nature | Canonical owner |
| --- | --- |
| Agent/session/runtime/capability mechanics | `loushang.harness` |
| JSONL/RPC framing and external transport | `loushang.channel` |
| Harness-conversation to terminal presentation bridge | `loushang.harnesstui` |
| Terminal controls, input, and layout primitives | `loushang.tui` |
| Model normalization and provider/model contracts | `loushang.ai` |
| Logs, traces, problem records, and reusable observability context | `loushang.foundation.observability` |
| Method preparation and plan mechanics | `loushang.method` |
| Work operations, events, and projections | `loushang.work` |
| Product content, choices, policy, compatibility, and final contracts | `loushang.coding` |

## Dependency Policy

Harness is not globally prohibited from importing Agent or AI. It is the
shared runtime layer above the Agent loop, so selected Harness integration
modules may use public `loushang.agent` and `loushang.ai` APIs directly.

The required split is:

- neutral Harness core packages such as conversation, journal, generic
  resources, generic diagnostics, configuration, and generic event values do
  not depend on Agent or AI;
- Agent integration packages such as `harness.session`,
  `harness.transcript`, extension Agent bridges, and reusable
  AI-assisted maintenance executors may depend on stable public Agent and AI
  APIs when that is part of their declared contract;
- those integrations may invoke a public AI/Agent capability when the Product
  has already supplied the selection, policy, and credentials through a port
  or resolved binding;
- Harness does not own provider registration, credential resolution, default
  model policy, or provider-specific behavior; those remain AI or Product
  responsibilities;
- `loushang.agent` and `loushang.ai` do not reverse-depend on Harness.

Each Agent/AI-dependent Harness subpackage must declare and test its narrow
dependency boundary. This is a per-package contract, not a repository-wide ban
on importing `agent` or `ai`.

Channel remains transport-first. It does not call or import Harness session
runtime. A narrow value-only dependency on a stable `RuntimeEventView` at a
documented codec boundary is permitted; session operation adaptation stays in
the Product host adapter.

## Product Composition

`ProductRuntimePlan`, `RuntimeProfileResolver`, and `RuntimeProfileBinder` are
the only runtime-profile admission and resolution path. Do not introduce a
second product-plan resolver, overlay precedence system, or dependency
injection root.

A Product may expose a compile-time convenience composition object, but it
must compile into the existing runtime plan, typed ports, and factory registry:

```text
Coding declarations and overlays
  -> ProductRuntimePlan + admitted RuntimeProfileLayer values
  -> RuntimeProfileResolver
  -> ProductRuntimeBindings / typed ProductPorts / FactoryRegistry
  -> shared Harness runtime
```

Runtime plans remain data-only and snapshot-safe. Factories, callbacks,
credentials, provider bridges, and presentation endpoints belong in typed
ports or the factory registry, never in the persisted plan. Shared defaults
are opt-in Product selections, not inferred Harness behavior.

## Measurement And Wave R

The current Coding Python LOC figure is an orientation metric, not an approved
delivery forecast. The long-term architecture target is Coding canonical
implementation at or below 10,000--11,000 LOC. A projected 18,000--20,000 LOC
transfer remains a stretch interval until the following rebaseline is complete.

### Wave R: Owner And Duplicate Rebaseline

Wave R is complete at `lane/harness` commit `336adbf2`; its reviewable result is
[Coding Shared-Layer Owner Rebaseline](coding-shared-layer-owner-rebaseline.md).
It does not claim migration LOC. The rebaseline must produce a
machine-readable or reviewable ledger for every planned source region with:

- pre-change Coding canonical LOC;
- existing shared implementation and canonical owner, if any;
- classification: shared implementation already adopted, Coding duplicate,
  Product adapter, or Product kernel;
- exact Product behavior that remains after cutover;
- target wave and contract/failure tests;
- net Coding LOC deleted and shared LOC added when the wave closes.

The ledger prevents counting an existing Harness, Channel, or HarnessTUI
implementation twice, or counting the same Coding coordinator in both session
and bootstrap waves. Tests, documentation, re-exports, and empty files never
count as migrated implementation.

Wave R also corrects architecture documentation that still describes the
implemented `loushang.channel` package as a future-only target.

## Six Delivery Waves

Each range below is a planning range for net Coding canonical LOC, not a
commitment. The Wave R ledger becomes the source of truth before work starts.

### Wave 1: Leaf Foundations

Initial candidates: diagnostics archive export, source descriptor and runtime
identity splits, AI model-selection utilities, session application ports, and
generic observability-context helpers. Expected first net reduction is about
600--900 LOC after Product adapters remain.

- `harness.diagnostics.export` owns archive writing, artifact read/failure
  containment, injected clock, manifest assembly, and text/structured
  redaction hooks. Products supply labels, artifact sources, output policy,
  README/manifest facts, and a diagnostic projector.
- A diagnostics export must redact structured diagnostics and manifest values,
  or explicitly require already-redacted Product input. Redacting only text
  artifacts is insufficient.
- Source descriptor conversion belongs in `harness.resources.source`; package,
  executable, and Git identity collection is a configurable shared utility;
  Product labels, entrypoints, and package identity remain Product-owned.
- Model normalization, label, deduplication, and current-first ordering belong
  in AI. Session application uses a Harness port. Model registry, auth, model
  preference, and Product wording stay outside Harness.
- The observability problem-to-diagnostics bridge is optional under
  `harness.diagnostics.observability_bridge`; diagnostics core remains
  independent of observability. Coding camelCase diagnostic serialization and
  debug CLI wording remain Product contracts.

### Wave 2: Event And Extension Product Adapter Collapse

Use existing `harness.events`, `harness.extensions`,
`harness.extensions.agent`, and HarnessTUI conversation owners. Do not create
parallel `agent_projection`, `agent_runtime`, or `agent_api` modules.
The concrete contract is
[Event And Extension Product Adapter Collapse](event-extension-adapter-collapse-boundary.md).
The Wave has a definite 231-line Coding hook dispatcher and a reviewable
subset of `ExtensionRunner`; it must not claim a standalone event relocation
because the Coding event projection is already a Product contract.

- Extract only fragments whose input and output are already shared contracts.
- `harness.events` keeps generic facts, `RuntimeEventView`, selectors, and
  strict value projection; Agent/AI-dependent routing belongs in the existing
  permitted session or Agent-transcript integration packages.
- Channel transports completed views; it does not create Agent views.
- HarnessTUI consumes neutral display contracts and does not interpret Coding
  aliases or wire fields.
- Coding retains Pi/camelCase compatibility, product event aliases, provider
  callbacks, permission defaults, result reducers, and Coding render wording.

### Wave 3: Standard Session Capabilities And Command Subsets

The detailed scope and contracts are in
[Standard Session Command Pack Boundary](session-command-pack-boundary.md).
Extend the existing Harness session operation and capability runtimes rather
than moving controllers wholesale. The implemented command-handler cutover,
canonical descriptor contract, and resource/extension source adapters are
ownership changes, not yet a net LOC reduction: Product builtin descriptor
reduction must be completed before claiming its 220--350 LOC target. Any
further tool/package/transcript capability reduction must be separately
ledgered rather than counted in advance.

- Define capability descriptors, availability, typed result values, and
  Product-bound handlers before classifying commands as standard.
- Evaluate commands by capability, not name. Session navigation, abort,
  compaction, and selected fork operations may be standard. Clipboard, HTML
  export, transcript import, extension/tool display, naming, and command
  descriptions may remain Product-specific.
- Bash execution shares workspace execution and lifecycle mechanics, while
  Product prompt behavior, approval, output treatment, and extension policy
  remain Product ports.
- Provider/model extension binding uses AI-facing ports; it does not become a
  generic `harness.session` provider registry.

### Wave 4: Session Composition And Bootstrap Transaction

First collapse `AgentSession` and runtime wrappers onto the existing session,
transcript, lifecycle, and facade owners. Only after that cutover proves a
reusable remainder may Harness gain a narrow bootstrap transaction contract.
Expected net reduction is about 2,000--3,500 LOC.

- A possible `BootstrapPlan`/`BootstrapPorts` owns only activation step order,
  rollback, disposal, and diagnostics collection.
- It does not choose prompts, models, resources, tools, policies, or Product
  session-file/cwd acceptance. Those are Product declarations and ports.
- A bootstrap engine must not become a service locator. It is admitted only
  after a fake Product can exercise activation and rollback without Coding
  imports.

### Wave 5: Channel, RPC, Print, And TUI Adapter Collapse

Use existing `channel` and `harnesstui` hosts. Expected net reduction is about
1,000--1,800 LOC after excluding Product protocol contracts.

```text
JsonlCommandHost / ChannelHost
  -> Product channel host port
  -> Product operation adapter
  -> Harness SessionOperationRuntime
```

- Channel owns parsing, framing, correlation, error isolation, background-task
  delivery, and transport-safe delivery policy.
- Harness owns typed session operations.
- HarnessTUI owns neutral conversation/interactions.
- Coding retains RPC method names and schema, camelCase/Pi compatibility,
  Coding-to-Work mapping, product routes, and product response projection.
- RPC, print, event, and transcript compatibility require golden fixtures;
  schema changes are explicit version boundaries, never silent rewrites.

### Wave 6: Config, Shared Defaults, CLI, And Work/Method Cleanup

Split this wave by owner rather than creating one large Harness package. Its
LOC target is determined only after the preceding ledger closes.

- Harness may add demonstrably cross-product config field groups and generic
  activation behavior. Product field semantics, effects, defaults, model/UI
  mapping, and compatibility remain Product-owned.
- A workspace tool pack, risk profile, resource convention, or compaction
  profile is shared only when it does not encode Coding tool names, shell
  policy, ordering, text, or prompts.
- Generic CLI transport/lifecycle belongs in Channel; terminal interactions
  belong in HarnessTUI/TUI; command syntax and product pages remain Coding.
- Method and Work bridge mechanisms move to their respective owners. Coding
  keeps domain=`coding`, artifact semantics, and submit/product projection.

## Delivery Contract

Before a delivery wave starts, add its concrete source regions and final owners
to the [rolling migration ledger](coding-shared-layer-migration-ledger.md). The
ledger is the scope gate; a short capability contract is also required for
persisted, exported, or security-sensitive boundaries.

Every capability batch uses three reviewable commits:

1. contracts, profile/ports, and a fake-Product probe;
2. shared implementation with focused unit tests and failure-injection tests;
3. Product cutover, duplicate/facade deletion, golden behavior tests, import
   gate, and ledger update.

There must not be two formal engines after cutover. A temporary adapter is
single-directional and has an explicit deletion task.

Required closure evidence:

- the shared owner does not import Coding;
- the fake Product imports no Coding types and exercises the public contract;
- persisted and transport contracts use golden fixtures;
- failure paths cover relevant rollback, append, hook, background-task,
  abort/fork, and redaction behavior;
- focused behavior tests, architecture boundaries, Ruff, and `git diff
  --check` pass; owner-sized waves additionally run the non-live suite;
- the ledger records the actual canonical ownership change.

## Product Kernel At Completion

Coding should ultimately consist primarily of product declarations and product
content: prompt and skill content, resource bundle, default tool/command/risk
selection, model and auth policy, Coding-only tools and commands, Coding
artifact semantics, compatibility mappings, CLI syntax, TUI skin/pages/routes,
and Coding Work/Method adapters. Shared runtime behavior must be imported from
its canonical owner rather than reimplemented or re-exported through Coding.
