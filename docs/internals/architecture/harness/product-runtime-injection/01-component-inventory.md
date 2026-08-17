# Product Runtime Injection Component Inventory

## Status

The runtime-profile and binding-lifecycle foundation is implemented. This
remains a directory of capability-specific future binding components, not a
claim that every contribution surface is implemented.

## Common Detailed-Design Template

Every component document will specify:

1. purpose, owner, and requirement traceability;
2. slot shape, contribution sources, and configuration version;
3. resolution, precedence, and conflict rules;
4. factory ports and runtime binding scope;
5. refresh, sealing, disposal, and rollback behavior;
6. durable snapshot/resume behavior where applicable;
7. trust, permissions, diagnostics, compatibility, and contract tests.

Generic resolution mechanics belong to the common runtime-injection kernel.
Component documents define only the capability-specific invariants and binding
rules.

## Component Directory

| Component | Intended Harness owner | Slot shape | Initial detailed-design status | Current foundation |
| --- | --- | --- | --- | --- |
| Runtime profile resolution | `harness.runtime` | profile root | Implemented; Coding adopted | `ProductRuntimePlan`, deterministic resolver, JSON snapshot, diagnostics |
| Binding lifecycle | `harness.runtime` | lifecycle coordinator | Implemented; Coding adopted | explicit factory registry/binder, sealed/turn refresh, generation leases |
| Conversation store | `harness.storage` | single, session-sealed | Planned | `ConversationStore`, Memory/File adapters |
| Transcript profile | `harness.transcript` | single, session-sealed | Planned | common Agent profile, codec registry, commit service |
| Memory | `harness.context` | ordered-many | Planned | context items, packing, salience foundations |
| Context compaction | `harness.context` + `harness.transcript` | one selected mechanism plus Product executor ports | Implemented | coordinator, strategies, turn-aware transcript planning, checkpoint runtime, bound capability |
| Artifact store | focused Harness artifact contract or Work owner | typed single or per-kind | Deferred | Product/Work artifact semantics remain unresolved |
| Prompt | `harness.capabilities` | single composer; nested ordered-many sections | Standard runtime binding implemented | section composition and templates |
| Skill | `harness.resources` plus Product selection | single activation policy; nested resource overlay | Standard runtime binding implemented | descriptor, discovery, resource overlay |
| Method | Method owner plus Product selection | ordered-many | Deferred | Method registry/contract remains outside this wave |
| Resource roots and packages | `harness.resources` | ordered-many | Planned | discovery, merge, materialization, reload |
| Tool pack | `harness.capabilities` / `harness.tools` | single composer; nested ordered-many packs | Standard runtime binding implemented | activation, contributions, workspace packs |
| Command pack | `harness.capabilities` | single composer; nested ordered-many packs | Standard runtime binding implemented | catalog, conflict resolution, dispatch |
| Model and auth selection | AI/Agent data owner plus Product policy | single or ordered policy chain | Deferred | model/auth remain outside current Harness ownership |
| Policy and approval | `harness.policy` / `harness.approval` | chain and exclusive replacement | Planned | control-plane routing and approval broker |
| Presentation and theme | presentation/channel owner | ordered-many, channel-local | Deferred | neutral presentation records and TUI theme primitives |
| OEM and extension contribution resolution | `harness.extensions` / contribution registry | source and validation layer | Partial; Side Question replacement implemented | manifests, contribution inventory, route planning, and focused Runtime Capability replacement registration |

## Migration Coupling

The table maps the dynamic-injection design to the active Coding-to-Harness
consolidation. The order follows dependency and data-safety constraints rather
than the order in which current Coding files happen to appear.

| Migration wave | Components prepared by this design | Current Coding migration relationship | Required design gate before code |
| --- | --- | --- | --- |
| 0. Runtime profile foundation | requirements, profile resolution, binding lifecycle | `harness.runtime.profile` supplies the common contract; `harness.transcript.AgentTranscriptProfileRuntime` composes the optional standard Agent profile; `coding.product_plan` declares Coding's identities and defaults. | `runtime-profile-resolution.md` and contract tests. |
| 1. Session coordination | binding lifecycle, prompt, tool/command contribution hooks | Reduce `coding.session` event, prompt, and queue coordination to Product adapters over Harness runtime/host mechanisms. | Runtime profile resolution and binding lifecycle designs. |
| 2. Transcript and durable store | conversation store, transcript profile | Extend existing direct Store injection to declared profile selection; preserve sealed session semantics. | Conversation store and transcript profile binding designs. |
| 3. Context runtime | memory and context compaction | Coding selects a Harness compaction mechanism and binds Product execution; memory remains a separate future component. | Context compaction binding design complete; memory binding design before memory cutover. |
| 4. Capability composition | resources, prompts, skills, tools, commands, policy/approval | Convert Product defaults and extension activation from ad hoc controller wiring to declared slot selections. | One detailed design per affected capability. |
| 5. Product-specific artifacts and channels | artifact, presentation/theme, method, model/auth as accepted by their owners | Keep deferred until Work, Channel, Method, and AI boundaries accept their corresponding contracts. | Owner-specific detailed designs. |

## Current-Branch Boundary

The active runtime-profile foundation provides deterministic selection and
binding mechanics, but it does not reinterpret accepted RuntimeEvent, Store,
or Transcript contracts. Coding now binds and persists its Product-only
capability profile for resources, prompts, skills, tools, and commands. A
later external-source adoption must name its Product plan, factory boundary,
admission grant, durable snapshot, and compatibility probe before it makes an
OEM or extension capability selectable at runtime.

## Relationship To Coding Session Reduction

`coding.session` must become a Product facade and composition layer. It may
continue to construct Coding-specific prompts, tools, commands, model/auth
policy, resource defaults, compatibility events, and presentation adapters.
It must not retain a second implementation of the mechanisms listed above once
their capability binding contracts are implemented.

The resource/prompt/skill/tool/command binding owner is now
`harness.capabilities.composition_runtime`; Coding retains only its Product
plan and adapters.

The existing [Coding To Harness Migration Inventory](../coding-to-harness-migration-inventory.md)
remains the source of truth for current module ownership. This directory is the
source of truth for future dynamic composition requirements and component
designs.
