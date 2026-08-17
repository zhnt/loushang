# Event And Extension Product Adapter Collapse Boundary

## Status

Status: implementation complete for Wave 2 of the Coding shared-layer
migration.

This boundary removes the remaining duplicate Agent extension hook mechanism
from Coding. It does not replace the existing event architecture and it does
not define a new Product event protocol.

## Decision

The existing owners remain canonical:

| Concern | Canonical owner | Product responsibility |
| --- | --- | --- |
| Runtime facts, envelopes, selectors, and strict-JSON view values | `harness.events` | Create a Product view from a fact. |
| Agent/AI extension hook composition | `harness.extensions.agent` | Supply extension context, Product binding, and Product-specific result policy. |
| Neutral extension loading, routing, resource contribution, and lifecycle coordination | `harness.extensions` | Supply API factory, activation policy, and runtime bindings. |
| Transport framing and delivery | `channel` | Supply a Product handler and response projection. |
| Terminal conversation presentation | `harnesstui` | Supply Product vocabulary, rendering, and screen policy. |

The Wave must extend these existing owners. It must not create parallel
`harness.events.agent_projection`, `harness.extensions.agent_runtime`, or
`harness.extensions.agent_api` modules.

`harness.extensions.agent` is an admitted Agent/AI extension profile. It may
use stable public Agent and AI value contracts, but must not resolve providers,
credentials, models, or Product UI behavior. The neutral modules directly
under `harness.extensions` retain their current dependency boundary.

The profile has two deliberately separate planes:

- **control**: typed context, tool, and before-start hooks may return a
  documented decision that changes Agent execution;
- **observation**: lifecycle facts are delivered to extensions after they
  occur and cannot become a second RuntimeEvent stream, transport protocol, or
  control channel.

This follows the useful separation in established coding agents between
lifecycle hooks and client-facing event streams, while retaining Loushang's
in-process, typed, deterministically ordered router. It does not copy an
external-process or shell-hook protocol into the Harness runtime.

The physical package shape is:

```text
harness.extensions
  routing.py, runtime.py, session_runtime.py  # neutral extension mechanism
  agent/
    hooks.py                                  # Agent context/tool dispatch
    lifecycle.py                              # extension lifecycle callbacks
    input.py                                  # extension-originated input
```

`agent/lifecycle.py` is an extension callback adapter, not an event bus. It
does not define a second envelope, subscription API, or projection format.
Client- and channel-facing observation remains on the `harness.events` path.

`harness.session` consumes this profile when it assembles an Agent session; it
does not own or re-export the Extension integration types after the cutover.
`harness.extensions.agent` must not import `harness.session`: Session passes
the profile its queue and application-input capabilities through ports.

## Source Classification

### Extension runtime

| Current source | Classification | Wave 2 result |
| --- | --- | --- |
| `coding.extensions.hooks.HookDispatcher` | Agent extension hook mechanism over an existing Harness route plan | Move its implementation to `harness.extensions.agent.hooks` as `ExtensionToolHookDispatcher`; delete the Coding module. |
| `coding.extensions.runner.ExtensionRunner` prompt/context/tool/session-hook reducers | Shared Agent-session routing, with Product context and error ports | Extract to narrowly named helpers in `harness.extensions.agent.hooks` and `harness.extensions.session_runtime`; reduce `ExtensionRunner` to a Coding binding adapter. |
| Existing `harness.session.extension_events.ExtensionAgentEventRuntime` | In-process extension lifecycle callback adapter | Move to `harness.extensions.agent.lifecycle`; inject its clock and map stable Agent lifecycle facts only. It must not publish `RuntimeEvent` or Coding event dictionaries. |
| removed `coding.extensions.runner.ExtensionRunner` profile binding | Standard Agent loader/runtime composition | Move to `harness.extensions.agent.runner`; Product error projection remains injected. |
| removed `coding.extensions.api.ExtensionAPI` | Standard Agent session/model/provider callback API | Move to `harness.extensions.agent.api`; provider execution and credentials remain outside Harness. |
| removed `coding.extensions.loader.ExtensionLoader` | Standard Agent loader configuration | Move to `harness.extensions.agent.loader` over the existing neutral loader. |
| removed `coding.extensions.policy` | Standard Agent permission defaults | Move to `harness.extensions.agent.policy`; other profiles may inject a different resolver. |

The extracted runtime must accept explicit ports for extension context creation,
diagnostic collection, and runtime-error reporting. It may not reach into a
Coding `AgentSession`, a provider registry, or a Product UI object.

The existing `ExtensionInputRuntime` is not moved verbatim. Its current raw
dictionary parsing and concrete `QueueController`/`ApplicationInputRuntime`
dependencies are session and Coding coupling. The target `agent/input.py`
contains only:

```text
ApplicationInputDeliveryPort
  -> deliver(ApplicationMessage)
  -> has_pending_messages()

PreparedUserInputQueuePort
  -> queue_prepared_steering(text, images)
  -> queue_prepared_follow_up(text, images)

ExtensionApplicationInput     # normalized ApplicationMessage delivery
ExtensionUserInput            # normalized prompt / steering / follow-up input
```

Coding parses `customType`, `deliverAs`, `triggerTurn`, and other legacy input
forms before constructing these typed requests. It also selects defaults and
retains its error wording. The shared input runtime only executes an already
normalized delivery instruction through injected ports.

### Event projection

`harness.session.event_types.AgentSessionEvent` is the shared typed session
mapping contract. The standard serialized event projection is
Session-owned. The following remain Product-owned:

- RuntimeEvent-to-session mapping, Product view selection/overrides, and
  Coding presentation wording;
- `event_writes_transcript` and cancellation wording;
- the conversion from neutral `RuntimeEvent` payloads to Coding dictionaries.

Harness serializes resulting event payloads with one recursive snake_case
normalizer. It does not accept or emit Pi/camelCase aliases, and selector
matching accepts only exact names and trailing-wildcard prefixes.

Production consumers use common facts from `subscribe_runtime_events()` or
`RuntimeEventView` wherever the shared API already provides them. Coding still
binds Product/work mapping and any final presentation override at its
UI/RPC/print/extension boundary, while Harness owns the canonical view,
rendering, and snake_case serialization. No new Harness event type may encode
Product aliases.

## Shared Hook Contract

`harness.extensions.agent.hooks` gains the common Agent extension dispatch
mechanism. The public shape is intentionally small:

```text
ExtensionToolHookDispatcher
  (route_plan, context_factory, diagnostics, runtime_error_handler)
  -> before_tool_call(context, signal)
  -> after_tool_call(context, signal)

ExtensionPromptHookDispatcher
  (plain_diagnostic_router, context_factory, diagnostics,
   before_agent_start_event_factory, before_agent_start_result_coercer)
  -> before_agent_start(request)
  -> transform_context(messages, signal, cwd)

ExtensionSessionHookDispatcher
  (router, context_factory, diagnostics, decision_coercer)
  -> observe_session(event_name, event, cwd)
  -> reduce_session_decision(event_name, event, cwd, result_type)

ExtensionAgentLifecycleRuntime
  (router, context_factory, diagnostics, runtime_error_handler, clock)
  -> observe_agent_lifecycle(fact, cwd)
```

The final names may be consolidated in `agent/hooks.py`, but the concerns must
not be hidden in a second monolithic Product runner. All dispatchers use the
existing `ExtensionRouter` and `ExtensionRoutePlan`; they do not compile their
own route plan or duplicate failure containment.

The standard behavior is fixed as follows:

- context handlers receive and return Agent message values; invalid
  `ContextResult` values create a diagnostic and leave state unchanged;
- before-tool handlers reduce `ToolCallDecision` in route order and stop on a
  blocking decision;
- after-tool handlers reduce `ToolResultDecision` in route order and preserve
  the Agent tool-output projection contract;
- before-agent-start handlers reduce `BeforeAgentStartResult`, including
  `system_prompt_append`, extra messages, and diagnostics;
- `before_agent_start_event_factory` and `before_agent_start_result_coercer`
  are Product ports. Harness never emits or accepts Pi/camelCase aliases;
- session decision dispatch validates the shared base
  `SessionActionDecision`. A Product-provided `decision_coercer` determines
  whether a base decision may become a fork, compaction, or tree result. The
  Coding port preserves today's base-decision-to-subtype compatibility;
- lifecycle callbacks are observation-only. Their invocation context carries
  available `session_id`, `run_id`, `turn_id`, and `tool_call_id`, the CWD, and
  extension provenance; missing correlation values remain absent rather than
  being guessed. A supplied clock and deterministic turn index make emitted
  callback facts reproducible in tests;
- cancellation retains existing Agent cancellation semantics; ordinary hook
  failures are contained by the existing router error policy and reported
  through the injected diagnostic/error ports.

Coding's remaining adapter binds these dispatchers to its `ExtensionRuntime`
and constructs its product runtime context. Extension event objects expose the
shared snake_case fields directly; no legacy Pi/camelCase aliases are added at
the extension boundary.

## Product Injection

Harness receives only typed or capability-shaped ports:

| Port | Supplied by Coding or another Product |
| --- | --- |
| `context_factory` | Bound/unbound extension context, CWD, flags, and Product callbacks |
| `runtime_error_handler` | Product diagnostic/error projection |
| `ExtensionAPI` factory | Product-only extension methods and deferred provider actions |
| permission/activation resolver | Product security defaults and OEM policy |
| before-agent-start event factory and result coercer | Product event vocabulary and legacy response mapping |
| session decision coercer | Product compatibility decision policy |
| normalized extension input adapter | Product wire parsing, defaults, and error wording |
| lifecycle fact adapter and clock | Stable Agent lifecycle correlation and deterministic timestamps |
| event view projector | Coding view selection, rendering, and product additions; Harness owns the shared snake_case wire schema |

Provider registration, model selection, session file policy, and terminal
rendering are excluded from the shared dispatchers. No event aliases are
generated at this boundary.

## Delivery Sequence

The Wave is three reviewable commits. Each commit stays runnable and contains
no compatibility promise beyond the current branch.

1. **Contracts and probes**
   - Completed: created `harness.extensions.agent` and moved the session-owned
     extension Agent hook/lifecycle modules into `agent/hooks.py` and
     `agent/lifecycle.py` with direct-import consumers; do not retain
     `harness.session` re-export facades.
   - Convert extension input to typed requests and injected queue/application
     delivery ports before moving it into `agent/input.py`.
   - Add hook and lifecycle callback protocols plus fake-Product tests under
     `tests/harness`.
   - Lock route order, invalid-result diagnostics, block/modify behavior,
     failure containment, context invalidation, and no-Coding-import gates.
   - Add Coding golden fixtures for current extension and event output before
     changing the adapter.

2. **Shared hook cutover**
   - Completed: moved `HookDispatcher` to
     `harness.extensions.agent.hooks` as `ExtensionToolHookDispatcher`.
   - Completed: extracted the reusable prompt/context/session decision dispatch from
     `ExtensionRunner`, using existing `ExtensionRuntime.router` and
     `plain_diagnostic_router` rather than a new router.
   - Verify with a fake Product that has no Coding imports.

3. **Coding adapter and event facade reduction**
   - Completed: made `ExtensionRunner` a Coding loader/API/context adapter over
     the shared dispatchers; delete `coding.extensions.hooks`.
   - The shared
     `harness.session.event_types.AgentSessionEvent` contract and
     `harness.session.event_projection` views own serialized event fields,
     snake_case shaping, and standard render enrichment. Lock the canonical
     output with golden tests and add an import gate that prevents a second
     neutral event engine; the existing `AgentSession.subscribe()` and Work
     projection adapters remain in place.
   - Add import gates: `harness.extensions.agent` may depend only on the
     declared stable Agent/AI value APIs and has no Coding import; no Coding
     production code imports the deleted dispatcher; `harness.events` is the
     only owner of shared event wire serialization.
   - Update the migration ledger with measured canonical LOC.

## Verification

Focused tests must cover:

- route ordering and invalid tool/context/session-hook result diagnostics;
- rewritten and blocked tool calls, changed tool results, and preserved tool
  output projector behavior;
- before-agent-start prompt replacement/append, extra messages, and
  diagnostics;
- reload/session replacement invalidates old extension contexts;
- extension message input, Agent event mirroring, and hook composition retain
  their current order;
- `agent/input.py` has no Session import, receives only typed requests, and a
  fake Product can bind delivery and queue ports;
- the Agent event mirror uses an injected clock and deterministic turn index;
- Coding's `before_agent_start` factory/coercer and session decision coercer
  preserve legacy event/result behavior;
- Coding extension API deferred provider actions remain Coding-owned;
- Coding JSON/RPC/print event golden fixtures use the canonical snake_case
  fields;
- a fake Product can run the shared hook runtime without importing Coding.

Run targeted Harness and Coding extension/event tests first, then the relevant
architecture-import suite and the non-live consumer suite.

## Non-Goals

This Wave does not:

- replace `AgentEvent`, `RuntimeEvent`, `WorkEvent`, or `AgentSessionEvent`;
- move Coding-specific event content or Product command schemas into Harness;
- add an event log, outbox, transport acknowledgement, or cross-process bus;
- add an external-process, stdin/JSON, exit-code, or shell-hook adapter. A
  future OEM process-hook integration is a separate adapter at
  `harness.extensions`, not part of `harness.extensions.agent`;
- combine skills, MCP tools, extension manifests, lifecycle callbacks, and
  client event delivery into one plugin or event runtime;
- move provider execution, authentication, credentials, or Product preferred
  model policy out of AI/Product owners;
- redesign extension manifests, permission policy, or OEM activation;
- move final TUI, print, RPC, or tool-render contracts.

## Measurement

The initial cutover removed the 231-line `coding.extensions.hooks`
implementation and the session-owned extension Agent profile facades. The
follow-up owner switch moved the remaining standard Agent API, policy, loader,
and runner profile into `harness.extensions.agent` and deleted the complete
Coding extension package. The event portion has no standalone relocation
target and is not counted as migrated merely because a consumer switches to an
existing Harness event API.
