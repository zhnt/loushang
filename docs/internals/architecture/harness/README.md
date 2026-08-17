# Loushang Harness Architecture

`loushang.harness` is the cross-product substrate that lets product adapters
prepare and run agent work without depending on another product package.

It is intentionally narrower than a product framework and broader than the
initial prepared-run facade. Harness owns product-neutral contracts, helper
engines, registries, and lifecycle shapes that `coding`, `design`, `research`,
`ppt`, `cowork`, and Products supplied or configured by OEMs can share.

Harness may provide explicitly overridable cross-product platform defaults. It
does not own domain content/defaults, product stores, product UI state, method
planning, work event persistence, or AI provider behavior.

## Start Here

- [Current Owner Map](current-owner-map.md) is the short, authoritative map of
  implemented owners, dependency direction, Product-owned exclusions, Session
  assembly phases, and public loading boundaries.
- [Shared Capability Boundaries](shared-capability-boundaries.md) provides the
  detailed owner matrix for cross-Product capabilities.
- [Capability Dependency And Mount Lifecycle](capability-dependency-and-mount-lifecycle.md)
  defines top-level Capability IDs, dependency direction, Mount identity,
  graph lifecycle, and graph diagnostics.
- [Harness Capability Catalog](capability-catalog.md) is the generated,
  source-backed inventory of role-complete Capability Definition / Provider /
  Consumer seams and their lifecycle metadata.
- [Capability Runtime Convergence Plan](capability-runtime-convergence-plan.md)
  records the completed PR0-PR9 delivery for owner-scoped reversible registration,
  Definition/Provider/Consumer separation, composed Profile/Mount/registration
  projection, and reconstruction of model-visible inputs from committed facts.
- [Capability Composition Lifecycle Authority Plan](composition-lifecycle-authority-plan.md)
  defines the accepted next-stage convergence of Profile, Mount, Registration,
  and Extension/Resource construction authority around one publisher per owned
  live object while preserving independent fact clocks.
- [Composition Lifecycle Authority CLA0 Baseline](composition-lifecycle-authority-cla0-baseline.md)
  freezes the current construction/publication owners, supported entrypoint
  counts, Profile-slot handoff classes, Binder ordering, and production
  construction allowlists before lifecycle convergence changes behavior.
- [Capability Runtime Convergence PR0 Baseline](capability-runtime-convergence-pr0-baseline.md)
  freezes the mutable-surface, compatibility, model-call, package-owner, and
  lifecycle-fault evidence that later convergence PRs must preserve or revise.
- [Session And Model-Call Closure Boundary](session-model-call-closure-boundary.md)
  fixes PR8's Session/candidate-graph nesting, per-sampling commit seam, complete
  model-call inventory, compaction lineage compatibility, and failure policy.
- [Model Input Persistence And Capacity Recovery](model-input-persistence-capacity-recovery.md)
  is the proposed corrective boundary for incremental Model Input persistence,
  typed invocation outcomes, capability-safe model selection, Provider request
  budgets, and bounded overflow recovery after PR #451.
- [Effective Runtime Diagnostics Boundary](effective-runtime-diagnostics-boundary.md)
  fixes PR9's four-clock composed view, explicit skew, explain, JSON, and diff
  semantics while retaining the existing graph projector as the only projector.
- [Refactoring Principles](refactoring-principles.md) defines the evidence and
  neutrality gates for moving code into Harness.

The source tree and architecture gates are authoritative. Boundary documents
describe accepted decisions. Files named `plan`, `inventory`, `ledger`,
`status`, or `migration` are delivery and historical records; they do not
override the current owner map merely because they contain a target-state
description.

## Boundary And Migration Document Catalog

- [Product And OEM Glossary](../../glossary/loushang-product.md) defines the
  canonical Product, OEM, Capability, Harness Capability, Package, Plugin,
  Extension, Product Capability Bundle, and multi-Product launch vocabulary
  used by these boundaries.
- [Capability Dependency And Mount Lifecycle](capability-dependency-and-mount-lifecycle.md)
  separates static Capability Plan nodes from live Mounted Capabilities,
  fixes `A -> B` as "A depends on B", and defines graph planning, incremental
  binding, disposal, diagnostics, and multi-Product observation.
- [Harness Capability Catalog](capability-catalog.md) is regenerated from
  source-backed seam metadata and fails verification when an implemented
  Definition, Provider, requirement, or Consumer drifts.
- [Capability Variation And Replacement Boundary](capability-variation-and-replacement-boundary.md)
  defines aggregate contribution, ordered interception and decoration,
  exclusive replacement, protocol injection, composition-root ownership, and
  the invariant enforcement layer that Product and Plugin variation cannot
  bypass.
- [Capability Runtime Convergence Plan](capability-runtime-convergence-plan.md)
  records the completed migration sequence that joined registration ownership
  and disposal, Capability role separation, graph projection, and durable
  model-input reconstruction. It does not override implemented source or
  accepted boundary documents.
- [Capability Composition Lifecycle Authority Plan](composition-lifecycle-authority-plan.md)
  is the accepted follow-on delivery plan for a Session-owned graph, the
  `harness.resources` vertical slice, and contraction of duplicate live
  construction paths; workspace production mounting remains an independent
  follow-up. Its
  [independent review brief](composition-lifecycle-authority-review-brief.md)
  can be given to reviewers without prior conversation context.
- [Composition Lifecycle Authority CLA0 Baseline](composition-lifecycle-authority-cla0-baseline.md)
  is the executable zero-behavior-change inventory for that accepted plan and
  distinguishes current repeated construction from cleanup leakage.
- [Capability Runtime Convergence PR0 Baseline](capability-runtime-convergence-pr0-baseline.md)
  is the executable pre-change inventory for that sequence. It records current
  compatibility and assigns each future contract to one package owner.
- [Session And Model-Call Closure Boundary](session-model-call-closure-boundary.md)
  defines the implemented PR8 Session graph, per-sampling commit, complete
  model-call inventory, and compaction-lineage boundary.
- [Model Input Persistence And Capacity Recovery](model-input-persistence-capacity-recovery.md)
  proposes a v1-compatible Model Input v2 representation and the selection,
  error, capacity, and recovery boundaries required before it is implemented.
- [Effective Runtime Diagnostics Boundary](effective-runtime-diagnostics-boundary.md)
  defines PR9's Product-neutral effective runtime diagnostics and clock-skew
  semantics without introducing another authority.
- [Refactoring Principles](refactoring-principles.md) defines what may move
  into harness and how migration slices should be shaped.
- [Shared Capability Boundaries](shared-capability-boundaries.md) maps tools,
  approval, renderers, workspace, resources, context, memory, session, and
  diagnostics across harness and product adapters, and records the product
  kernel that must remain product-owned.
- [Coding To Harness Migration Inventory](coding-to-harness-migration-inventory.md)
  records how the current `loushang.coding` modules should be classified before
  implementation moves code.
- [Coding To Shared-Layer Migration Plan](coding-shared-layer-migration-plan.md)
  records the accepted long-term owner map, Agent/AI dependency policy,
  mandatory rebaseline ledger, revised six delivery waves, and closure gates
  for turning Coding into a declarative Product adapter.
- [Coding Shared-Layer Migration Ledger](coding-shared-layer-migration-ledger.md)
  is the closed historical record of the concrete source-to-owner cutover
  completed through Wave 7, Slice Z.
- [CLI Product Host Collapse](cli-product-host-collapse.md) defines ordered
  standard CLI operation dispatch and shared session/resource/package host
  operations while Products retain grammar, policy, and mode selection.
- [Product Host Runtime Boundary](product-host-runtime-boundary.md) defines
  Product-neutral input, task, stream, and disposal lifecycle mechanics below
  Channel and Product protocols.
- [JSONL Command Host Boundary](jsonl-command-host-boundary.md) defines strict
  Product-owned JSONL command input and remote UI correlation without making
  either mechanism a Channel protocol.
- [Product CLI Lifecycle Boundary](product-cli-lifecycle-boundary.md) records
  shared turn ordering, stream binding, TTY detection, and failure disposal.
- [Coding Shared-Layer Owner Rebaseline](coding-shared-layer-owner-rebaseline.md)
  records shared owners, actual Coding adapters and kernels, and the source
  boundary required before a further migration wave can claim LOC.
- [Diagnostics Export Boundary](diagnostics-export-boundary.md) defines the
  reusable archive, structural redaction, and product projection contract.
- [Slice 1 Closure Status](slice-1-status.md) records the approval, tools-core,
  contribution, and presentation substrate that has landed on `lane/harness`,
  plus deferred runtime and product-adapter work.
- [Slice 2 Execution Context Design](slice-2-execution-context-design.md)
  records Slice 2A implementation complete for runtime tool contribution
  adapter verification and Slice 2B eligible under the neutrality evidence
  gate but not yet implemented.
- [Resource Frontmatter Boundary](resource-frontmatter-boundary.md) defines the
  shared parser owner, legacy compatibility paths, and product-owned resource
  semantics that remain outside harness.
- [Resource Provenance Boundary](resource-provenance-boundary.md) defines
  shared source metadata and the resource-to-diagnostic-draft factory while
  preserving coding path representations.
- [Platform Resource Layout Boundary](platform-resource-layout-boundary.md)
  records the implemented Harness-owned platform roots, resource/package
  runtime, standard resource scopes, `AGENTS.md` conventions, and built-in
  package mechanisms while preserving product content, activation, trust, and
  runtime projection.
- [Contribution Inventory Boundary](contribution-inventory-boundary.md) defines
  shared descriptor and registry ownership.
- [Extension Runtime Core Boundary](extension-runtime-core-boundary.md) defines
  shared manifest, loading, registration, conflict resolution, observer/input
  dispatch, resource contribution, and tool-wrapper ownership while preserving
  product policy, session/model behavior, and UI integration.
- [Extension Context Runtime Boundary](extension-context-runtime-boundary.md)
  defines the standard extension context, lifecycle records, generation-bound
  capability injection, and snake_case-only extension UI contract.
- [Extension And Resource Generation Lifecycle](extension-generation-lifecycle-boundary.md)
  defines candidate admission, exact owner/generation registrations,
  synchronous runtime/resource publication, rollback, and reverse unload.
- [Control Plane Runtime Boundary](control-plane-runtime-boundary.md) defines
  deterministic extension routing, neutral policy subjects and evaluator
  composition, pending approval lifecycle, and the Product adapters that retain
  risk defaults, result semantics, and presentation.
- [Policy And Approval Redesign](policy-approval-redesign.md) replaces the
  current tool-shaped policy and boolean approval model with an action-based
  authorization runtime, scoped grants, execution-time revalidation, common
  approval coordination, and explicit Coding/TUI/Work/daemon/MCP/multi-agent
  integration boundaries.
- [Tool Execution Binding Boundary](tool-execution-binding-boundary.md) defines
  one hosted dispatch path, a Product-neutral authoring API, explicit direct or
  authorized bindings, typed common effects, a session-owned authorization
  gateway, and the migration that removes raw tool execution bypasses without
  changing permission behavior.
- [One-Shot Agent Invocation Tool Boundary](agent-invocation-tool-boundary.md)
  records the implemented `delegate_agent` P0: a finite authorized subprocess
  tool, Coding-owned CLI semantics, non-widening child tools, bounded output,
  and the evidence gates before jobs or multi-agent semantics are introduced.
- [Harness Tool Authoring](tool-authoring-guide.md) is the short developer guide
  for pure tools, common filesystem actions, and custom action adapters.
- [Sandbox Runtime Boundary](sandbox-runtime-boundary.md) defines the optional,
  disabled-by-default process containment service, its cross-platform
  Protocols, centralized host detection and backend selection, existing
  `ExecService` integration, and session/child lifecycle.
- [Process Hosting Boundary](process-hosting-boundary.md) defines the narrow
  session-owned long-lived child-process substrate, fixed lifecycle limits,
  public contract restraint, execution-scope authorization, private Sandbox
  containment planning, and ordered Session fallback cleanup.
- [Context Budget And Accounting Boundary](context-budget-accounting-boundary.md)
  defines deterministic compaction-budget and usage-estimate record ownership
  while keeping message estimation and compaction policy in product adapters.
- [Context, Compaction, And Journal Foundations](context-compaction-journal-foundations.md)
  records the implemented ownership of context items and packing, selectable
  compaction strategies, profiled append-only JSONL mechanics, branch graphs,
  and focused Coding/Work compatibility adapters.
- [Runtime Data Foundations](runtime-data-foundations.md) records the follow-on
  ownership of transcript repositories, rebuildable projection indexes,
  layered configuration, explainable salience, and summary-profile mechanics
  while preserving Product schemas, prompts, defaults, and artifact semantics.
- [Summary Evaluation Boundary](summary-evaluation-boundary.md) defines
  profile-driven structured-summary evaluation and resource-operation evidence
  while Products retain prompts, profile selection, production decoration, and
  product-specific semantic checks.
- [Product Configuration Runtime Boundary](product-configuration-runtime-boundary.md)
  defines transactional layered configuration, declarative Product schema
  adapters, scoped change records, injected value resolution, and activation
  DAG ownership. Its optional Agent profile composes those existing components
  into standard cross-product settings types, codecs, getters, and setters while
  Products retain paths, overlays, effects, diagnostics, and presentation.
- [Product Runtime Injection Architecture](product-runtime-injection/README.md)
  records proposed requirements and the component directory for Product,
  OEM, and extension selection of runtime capabilities. Detailed component
  binding contracts are written before their corresponding migration waves;
  this directory does not claim that a new injection runtime is implemented.
- [Conversation Runtime Core Boundary](conversation-runtime-core-boundary.md)
  defines shared conversation records and ports, repository/catalog/replay,
  branch delta, command execution records, and turn-aware compaction planning
  while preserving Product prompts, domain payloads, and storage policy.
- [Conversation Persistence Refactor](conversation-persistence-refactor.md)
  records the implemented journal/conversation/Agent persistence consolidation,
  provider-bound catalogs, and revision-aware rebuildable indexes without
  changing the Conversation JSONL format; project-aware picker work remains a
  follow-on.
- [Agent Transcript Profile Boundary](agent-transcript-profile-boundary.md)
  defines the optional common Agent/AI transcript schema and codec profile,
  opaque preservation, Native v3 migration, idempotent application-message
  commit, Product extension points, and its narrow AI/Agent import allowlist.
- [Agent Transcript File Store Boundary](agent-transcript-file-store-boundary.md)
  defines the Conversation JSONL provider, file layout and lock ownership,
  Product store selection, and the separation between native loading and
  external importers.
- [Agent Transcript Catalog Boundary](agent-transcript-catalog-boundary.md)
  defines the common Conversation JSONL transcript discovery, summary/query, projection
  index, and branch-label read model while Products retain roots and
  presentation policy.
- [Agent Transcript Lifecycle Boundary](agent-transcript-lifecycle-boundary.md)
  defines common create, restore, detached-copy, fork, disposal, and active
  Native-file deletion mechanics while Products retain binding and resume
  policy.
- [Agent Transcript Session Factory Boundary](agent-transcript-session-factory-boundary.md)
- [Product Transcript Session Boundary](product-transcript-session-boundary.md)
  defines reusable header, Native-context, create/load/recent-resume, and fork
  assembly while Products retain profile selection and resume compatibility.
- [Agent Transcript Interaction Runtime Boundary](agent-transcript-interaction-runtime-boundary.md)
  defines standard branch navigation, selection persistence, transcript
  inspection, and context replay while Products retain domain actions.
- [Agent Transcript Maintenance Runtime Boundary](agent-transcript-maintenance-boundary.md)
  defines common context accounting, compaction/retry lifecycle, checkpoint
  persistence, and runtime events while Products retain strategy and policy.
- [Agent Transcript Export Boundary](agent-transcript-export-boundary.md)
  defines portable JSONL/HTML transcript exports, standard document rendering,
  and the narrow Product presentation profile while Products retain semantic
  render hooks, themes, output paths, and command/API projection.
- [Session Capabilities Runtime Boundary](session-capabilities-boundary.md)
  defines live tool activation, dynamic command composition and dispatch, and
  selected command-tool execution while Products retain policy, command
  implementations, extension semantics, prompts, and presentation.
- [Standard Session Command Pack Boundary](session-command-pack-boundary.md)
  defines the shared parsing and callback delegation for selected session
  commands while Products retain descriptor order, wording, result projection,
  local commands, and UI/transport behavior.
- [Session RPC Operation Boundary](session-rpc-operation-boundary.md) records
  the current Product command wire, command-group, dynamic-session, and
  Channel-separation ownership.
- [Session Interaction And Command Collapse Boundary](session-interaction-command-collapse-boundary.md)
  records the historical UI/command composition slice that preceded the final
  Harness RPC cutover.
- [Session Facade Boundary](session-facade-boundary.md) defines the common
  Product-facing operation surface over already-bound session runtimes while
  Products retain model/auth, prompts, extension protocols, lifecycle policy,
  and channel projection.
- [Session RPC Operations Boundary](session-rpc-operations-boundary.md) defines
  typed capability-grouped session operations below transport schemas while
  the Harness RPC host owns wire mapping and Products retain runtime and
  selected event/diagnostic projections.
- [Mode Host Boundary](mode-host-boundary.md) defines the shared RPC/plain host
  implementation and the remaining Coding Work/event/diagnostic bindings.
- [Session Product Adapter Collapse](session-product-adapter-collapse.md)
  records the direct Facade/inspector/retry bindings that remove redundant
  Coding session controllers while preserving Coding product ports.
- [Session Product Runtime Composition Boundary](session-product-runtime-composition-boundary.md)
  defines the shared active-session composition adapter and the Product ports
  that keep transcript storage, fork policy, cwd policy, diagnostics, and
  lifecycle effects configurable.
- [Bootstrap Tool Contribution Boundary](bootstrap-tool-contribution-boundary.md)
  defines shared extension-tool contribution projection, pack composition,
  conflict filtering, and registry registration through Product callbacks.
- [Bootstrap Activation Collapse Boundary](bootstrap-activation-collapse-boundary.md)
  defines the standard Agent startup stage graph and its composition over the
  existing activation, resource, diagnostics, session, and catalog owners.
- [Session Inspection Boundary](session-inspection-boundary.md) defines
  Product-neutral Agent/transcript state, context usage, and statistics while
  Products retain display and wire-format projection.
- [Session Diagnostics Runtime Boundary](session-diagnostics-boundary.md)
  defines common session-correlated diagnostic reads and Agent/Tool failure
  projection while Products retain diagnostic selection and presentation.
- [Session Resource Refresh Runtime Boundary](session-resource-refresh-boundary.md)
  defines common session resource reload/discovery/activation/commit ordering
  while Products retain loaders, roots, settings, diagnostics, and extension
  protocol behavior.
- [Package Session Operations Boundary](package-session-operations-boundary.md)
  defines common package lifecycle ordering and typed catalog diagnostic
  recording while Products retain source policy, roots, settings, and wire
  projection.
- [Store And Runtime Event Protocol Migration](store-event-protocol-migration.md)
  records the implemented protocol-based Store cutover, Memory/File reference
  adapters, Agent transcript persistence facade, common runtime-event envelope,
  commit/publication ordering, and the deliberately deferred SQL, Redis,
  outbox, and extension-provider work.
- [Session Runtime Events Boundary](session-runtime-events-boundary.md) defines
  common queue, compaction, retry, branch, metadata, package-progress, and
  transcript-commit facts, the single ordered Session stream, and Product event
  projection ownership.
- [Runtime Event Projection And Channel Boundary](runtime-event-projection-channel-boundary.md)
  defines strict transport-ready RuntimeEvent views, the narrow Channel value
  dependency, Session projection ownership, and the separate Work path.
- [Runtime And Event Dependency Direction](runtime-event-dependency-direction.md)
  defines the acyclic Events/Runtime/AgentTranscript/Session/Host ownership
  order and the executable strongly-connected-component guard.
- [Session Lifecycle Runtime Boundary](session-lifecycle-runtime-boundary.md)
  defines active Product-session replacement, Product-selected store/hooks,
  staged import, configurable fork profiles, and Harness's conservative
  default `at` fork profile.
- [Application Input Runtime Boundary](application-input-runtime-boundary.md)
  defines common direct and queued ApplicationMessage delivery, one durable
  commit owner, direct projection retry semantics, and Product Extension/API
  adapter ownership.
- [Scenario Runtime Boundary](scenario-runtime-boundary.md) defines reusable
  scripted interaction scenarios, parser and runner ownership, injected command
  assertions, RuntimeEvent observation, and Coding's local execution adapter.
- [Product Runtime Core Boundary](product-runtime-core-boundary.md) defines
  shared runtime bindings and contexts, session-transition ownership,
  coalesced scheduling, AI/Agent data-contract placement, and the irreducible
  Product kernel that remains outside Harness.
- [Tool Output Projection Core Boundary](tool-output-projection-core.md) defines
  strict JSON ownership, Agent raw-result projection targets, failure timing,
  Harness journal/presentation adoption, and Product wire-schema ownership.
- [Diagnostics Core Boundary](diagnostics-core-boundary.md) defines shared
  diagnostic drafts, records, queries, summaries, startup checks, and in-memory
  engine ownership while keeping checks and presentation in product adapters.
- [Host Runtime Boundary](host-runtime-boundary.md) defines product-neutral host
  lifecycle, input-queue ledger, and ordered event ownership while preserving
  Agent loop and product session responsibilities.
- [Host Turn And Session Orchestration Core Boundary](host-turn-session-orchestration-core.md)
  defines shared turn, retry, resource/extension lifecycle, session operation,
  import staging, and navigation transaction ownership while preserving Product
  messages, policy, persistence, events, and UI.
- [Product Capability Composition Core Boundary](product-capability-composition-core.md)
  defines shared command catalog and dispatch, standard resource-aware prompt
  assembly/preflight and template expansion, and tool activation coordination
  while preserving only Product-exclusive content, policy, side effects, and
  presentation.
- [Capability, Domain, Presentation, And Continuity Architecture](capability-domain-presentation-continuity-architecture.md)
  records the implemented V1 separation of runtime capabilities, Product
  domains, OEM experiences, and resumable continuity units, including
  federated summary/index and common-versus-Product presentation boundaries
  with `/resume` as the first reference workflow.
- [OEM And Extension Architecture](oem-extension-architecture.md) describes how
  OEM customisation, extension contributions, and harness upgrades interact,
  including override mechanisms, extension categories, surface-type gaps, and
  upgrade-compatibility guarantees.
- [Multi-Agent Architecture](multiagent/system-context.md) (implemented)
  defines the target boundary for `loushang.harness.multiagent`: sub-agent
  spawning, context isolation and forking, agent input facade notification,
  concurrency and residency limits, and approval bubbling, with ownership in
  [ARD-001](multiagent/ARD-001-harness-ownership.md) and async / recovery
  semantics in [ARD-002](multiagent/ARD-002-async-execution-and-recovery.md).
  Component boundaries: [run handle](multiagent/run-handle-boundary.md),
  [agent input facade](multiagent/agent-input-facade-boundary.md),
  [context fork](multiagent/context-fork-boundary.md),
  [control](multiagent/control-boundary.md),
  [registry](multiagent/registry-boundary.md),
  [limits and projection](multiagent/limits-and-projection-boundary.md),
  [tool surface](multiagent/tool-surface-boundary.md). The proposed
  [remote Agent capability boundary](multiagent/remote-agent-capability-boundary.md)
  keeps one-shot invocation, asynchronous jobs, and persistent collaboration
  as separate contracts and defers a common execution port until mixed
  placement or recovery proves it necessary.
- [Workspace Execution Boundary](workspace-execution-boundary.md) defines
  harness-owned truncation, exec records, backend protocols, process execution,
  and coding compatibility ownership.
- [Workspace Operation Boundary](workspace-operation-boundary.md) defines
  filesystem operation protocols, local backend ownership, coding compatibility
  paths, and product adapters that remain outside harness.
- [Workspace Path And Mutation Boundary](workspace-path-mutation-boundary.md)
  defines configurable path resolution, canonical identity, optional input
  variants, mutation coordination, and coding path policy ownership.
- [Workspace And Terminal Platform Capabilities Boundary](workspace-platform-capabilities-boundary.md)
  defines canonical Harness Git and Native TUI clipboard ownership, direct
  Product adoption, and retired Coding platform paths.
- [Workspace Tool Pack Boundary](workspace-tool-pack-boundary.md) defines
  reusable concrete read/search/edit/exec ownership and the product-owned
  activation and policy boundary.
- [Tool Facade Extinction Boundary](tool-facade-extinction-boundary.md) records
  removal of `coding.tools`, direct Harness ownership imports, and Coding's
  narrow default tool-pack adapter.
- [Harness Lane Development Workflow](development-workflow.md) defines how the
  long-lived `lane/harness` branch stays isolated from `main` until the
  migration is bootable and validated.

Accepted decisions that govern this directory:

- [ARD-001: Agent Harness and Product Adapter Boundaries](../agent/ARD-001-agent-harness-and-product-adapters.md)
- [ARD-002: Harness Product Adapter Substrate](../agent/ARD-002-harness-product-adapter-substrate.md)

## Boundary Summary

Harness may depend on stable `loushang.agent` primitives and the existing agent
loop. `loushang.agent` must not depend on harness. The neutral
`loushang.harness.conversation` core imports neither Agent nor AI. The optional
`loushang.harness.transcript` and the optional
`loushang.harness.session` profile have narrow, separately tested Agent/AI data
dependencies. The exact allowlists are recorded in the
[Agent Transcript Profile Boundary](agent-transcript-profile-boundary.md) and
[Session Runtime Core](product-runtime-injection/components/session-runtime-core.md).

Neutral Harness core packages must not import:

- `loushang.coding`
- `loushang.design`
- `loushang.research`
- `loushang.ppt`
- `loushang.cowork`
- `loushang.method`
- `loushang.work`
- `loushang.tui`

Agent/AI integration packages may import stable public `loushang.agent` and
`loushang.ai` capabilities when their documented contract requires it. They do
not own provider registration, credentials, default model policy, or
provider-specific behavior, and Agent/AI packages must not reverse-depend on
Harness. The exact per-package allowance belongs in that package's boundary
document and import test.

If a harness contract needs to refer to method, work, channel, UI, or product
state, it should carry opaque ids, neutral metadata, or protocol-shaped values.
The product adapter interprets those values.

## Parallel Development Rule

Harness refactoring should not block TUI, agent, or AI provider work:

- TUI work stays under `loushang.tui` or product-owned UI adapters.
- Agent loop work stays under `loushang.agent`.
- Provider/model/auth work stays under `loushang.ai`.
- Harness work stays in product-neutral contracts and shared engines used by
  product adapters.

When a migration slice touches a product adapter, it must prove product behavior
is unchanged with focused tests and must keep the architecture import-boundary
tests passing.

## Quality Gate

Run `make check-harness` before integrating Harness changes. The gate runs Ruff
over Harness production and tests, mypy over the complete Harness source tree,
the full Harness test suite, and the architecture import-boundary contracts.
The same command runs in the dedicated Harness CI workflow.
