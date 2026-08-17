# Coding Shared-Layer Owner Rebaseline

## Status

Status: current post-Phase-0 baseline for `main`.

This is the mandatory owner rebaseline from
[Coding To Shared-Layer Migration Plan](coding-shared-layer-migration-plan.md).
It is verified against the current source tree by architecture tests. Figures
are informational production Python LOC from `wc -l`; historical migration
figures and completed-wave prose are not an authority over the current tree.

## Classification

| Classification | Meaning |
| --- | --- |
| `shared adopted` | A shared owner already performs the mechanism. The Coding code is a Product binding, projection, or adapter and must not be counted again. |
| `duplicate candidate` | Coding still implements a reusable mechanism, pending a concrete port/profile contract and a fake-Product probe. |
| `product adapter` | Coding binds shared mechanisms to Product policy, content, or compatibility. It may shrink but is not a mechanical move. |
| `product kernel` | Coding owns semantics, compatibility, UI, provider/model policy, or final presentation. It stays in Coding. |

## Current Top-Level Dependency Direction

An arrow means “depends on”:

```text
Coding -----> Harness
Coding -----> HarnessTUI
Coding -----> Work
Coding -----> Channel

HarnessTUI -> Harness
Channel ----> Work
Channel ----> Harness
Work -------> Harness  (projection and journal adapters only)
```

`Harness` imports none of Channel, Work, HarnessTUI, or Coding. Work runtime
and value contracts do not import Harness; only the optional Agent projection
and Harness journal adapter do. Work never imports Channel. Channel owns
`ChannelEnvelope` and its Work/runtime-view JSONL frames. Product command JSONL
input, routing, settlement, and response framing are independently owned by
`harness.host.rpc`; “Channel framing” never means the Product RPC wire.

## Session And Host

| Source region | LOC | Current shared owner or adopted mechanism | Classification | Next action |
| --- | ---: | --- | --- | --- |
| `coding.bootstrap` | 693 | Harness activation/configuration runtimes own sequencing and rollback | `product adapter` | Retain Coding services, defaults, paths, callbacks, and concrete factories |
| `coding.runtime.agent_session_runtime` | 67 | Harness lifecycle, transcript, capability, and Session runtimes | `product adapter` | Retain the Product runtime factory; add no second lifecycle |
| `coding.session.agent_session` | 157 | `AgentProductSession`, `SessionRuntime`, and `SessionFacade` | `product adapter` | Audit only pure forwarding methods; retain Coding content and policy binding |
| `coding.session.builtin_commands` | 547 -> deleted | `harness.session.command_pack` | `shared adopted` | Standard descriptors and result projection now live in Harness |
| removed `coding.session.command_controller` | 0 | `harness.capabilities.commands.SessionCommandRuntime` and command sources | `shared adopted` | Coding retains command definitions and Product handlers |
| removed `coding.mode` | 0 | `harness.host.rpc`, `harness.host.mode`, and `harnesstui.conversation` | `shared adopted` | Coding CLI/UI composition injects Product runtime, projections, Work profile, and presentation |
| `coding.prompt_command` plus removed `coding.work_*` | 144 | `harnesswork.integrations.session.SessionWorkRuntime` over canonical `WorkRuntime` | `product adapter` | Retain Coding renderer, failure wording, Method preparation, domain, and event projection |
| removed `coding.runtime_profile` and `coding.capability_plan`; `coding.product_plan` | 46 | runtime resolver/binder, transcript profile, and capability composition | `shared adopted` | Coding declares stable Product identities and defaults only |

Coding remains responsible in this group for concrete service/session
factories, CWD/session-file acceptance, preferred-model decisions, prompts,
resource defaults, Work/Method binding, RPC event/diagnostic projections, and
final UI presentation. Harness owns the Product RPC wire implementation.
Provider implementations and credentials remain behind injected AI/Product
ports.

## Extensions, Events, And Configuration

| Source region | LOC | Current shared owner or adopted mechanism | Classification | Next action |
| --- | ---: | --- | --- | --- |
| removed `coding.extensions` | 0 | `harness.extensions.agent` over the existing neutral extension loader/runtime | `shared adopted` | Standard Agent API, policy, loader, and runner profile moved without retaining a Product facade |
| removed `coding.event` | 1,045 -> 0 | `harness.session.event_types`, `harness.session.event_projection`, `harness.session.runtime_event_views`, and `harness.events.recording_policy` own shared contracts, standard views, render enrichment, stream shaping, snake_case serialization, runtime-view selection, delivery hints, transcript-write decisions, and cancellation classification | `shared adopted` | Consumers import the canonical event owners directly; Product/Work mapping and final presentation remain in their existing owners without a Coding event facade |
| removed `coding.control.settings_manager` | 0 | `harness.config.agent.SettingsManager` composed over `SettingsRuntime`, `ScopedConfigRuntime`, schema codec, and JSON store | `shared adopted` | Standard Agent field codecs, accessors, and mutations moved without adding a second engine |
| removed `coding.control.types` | 0 | `harness.config.agent.types` | `shared adopted` | Standard Agent settings records are shared; Products retain only true domain additions and overlays |
| removed `coding.policy` | 0 | Harness owns policy evaluation, default permission profiles, approval lifecycle, effects, and workspace enforcement | `shared adopted` | Coding selects profiles/resolvers and retains Product UI wording and package defaults |
| `coding.tool_pack`, `resource_runtime` | 312 | Workspace tool/profile and resource/package runtimes | `product adapter` | Retain Coding membership, descriptions, built-ins, prompt assembly, and default bindings |
| `coding.compaction.adapter`, `profiles` | 320 | Transcript compaction and summary-profile mechanisms | `product adapter` + `product kernel` | Retain Coding executor binding and prompt/profile content |

## Leaf And Interaction Regions

| Source region | LOC | Current shared owner or adopted mechanism | Classification | Next action |
| --- | ---: | --- | --- | --- |
| removed `coding.source_info` | 0 | `harness.resources.source` and profiled `foundation.observability.identity` | `shared adopted` | Runtime identity Product labels live in `coding.diagnostics.profile`; no source-info facade remains |
| `coding.interaction.*` | 68 | HarnessTUI settings/schema primitives | `product adapter` | Retain Coding settings profile declarations |
| `coding.model_selection`, `coding.model_selection_tui` | 105 | `ai.model`, `harness.session.model_selection`, and `harnesstui.selection` | `product adapter` | Retain preferred-model policy, persistence, and warning wording |
| `coding.diagnostics.*`; removed `diag_export` and `observability` | 472 -> 138 | Harness diagnostics/export and observability runtime | `shared adopted` | Retain Coding debug-status presentation and its source/identity profile only |
| `coding.sdk_surface` | 138 -> 61 | `harness.sdk_surface` owns generic export/signature inspection | `product adapter` | Retain the Coding entry-name contract and default-module binding |

## Non-Duplicates

Do not recreate the existing shared implementations for session
runtime/facade/lifecycle, transcript factory and directory, retry/compaction/
queue, resources/packages, configuration layering, command composition, JSONL
parsing, or extension Agent hooks. Replacing a Coding call to one of these with
another wrapper does not count as migration.

## Product Bootstrap And Facade Gate

The Product bootstrap transaction gate is closed.
`harness.bootstrap.BootstrapActivationRuntime` owns activation ordering,
reverse cleanup, and failure reporting, while
`ProductTranscriptSessionLifecycleStore` owns transcript create/restore/fork
and failed-build cleanup. Coding supplies typed Product callbacks and concrete
factories.

Any further shared bootstrap change is admitted only when it:

1. sequences injected activation steps, cleanup, failure capture, and final
   factory invocation without importing Coding;
2. reuses `ConfigActivationRuntime`, `CapabilityCompositionRuntime`,
   `SessionLifecycleRuntime`, and `SessionRuntime`, rather than adding a
   resolver, lifecycle, or service locator;
3. receives prompt, model/auth, resource, tool/command, approval,
   session-file/CWD, and extension behavior from typed Product ports or the
   existing runtime profile binding; and
4. is exercised by a fake Product through success, failed activation with
   reverse cleanup, and final disposal.

`AgentSession` remains a Product adapter. A facade audit may remove methods
that only forward an existing Harness surface, but it must not replace the
current facade with another wrapper.

## Measurement Rule

Future extraction proposals record exact pre-change implementation LOC,
post-cutover Product LOC, shared LOC added, and net deleted duplicate
implementation. The snapshot figures above are orientation only; tests and
documentation do not enter the measurement, and historical estimates are not
a delivery metric.
