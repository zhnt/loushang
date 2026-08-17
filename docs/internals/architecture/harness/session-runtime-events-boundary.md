# Session Runtime Events Boundary

## Decision

Cross-product Session and Host runtime facts belong to
`loushang.harness.events`. A Product observes the common `RuntimeEvent` stream
and projects those facts into its JSON, RPC, extension, terminal, or UI
contract. A Product does not own a second runtime event bus.

This boundary keeps four event layers distinct:

```text
AgentEvent                 Agent-loop execution facts, owned by loushang.agent
    |
RuntimeEvent               transient Host/Session facts, owned by Harness
    |\
    | \-> Work projection -> WorkEvent, owned by loushang.work
    |
    \--> Product projection -> RuntimeEventView -> Channel delivery
```

`ConversationRecord` remains the durable transcript fact. A runtime event is
an observation and does not replace transcript persistence.

## Common Envelope

`RuntimeEvent` owns:

- event, stream, session, run, source-event, and source-record identity;
- a timezone-aware occurrence time;
- a monotonic sequence within one publisher stream;
- an opaque typed payload.

One `RuntimeEventPublisher` allocates every envelope for a Session stream. The
ordered bus serializes synchronous and asynchronous listeners in subscription
order. It is an observation mechanism, not a command dispatcher.

## Common Session Payloads

Harness owns immutable payloads for:

- queue snapshot changes;
- context compaction start and completion;
- retry start and completion;
- branch summary start and completion;
- conversation metadata changes;
- package materialization progress;
- tool action, policy, approval, and execution audit observations;
- transcript record commits.

The payloads compose existing Harness values where an owner already exists:
`QueueSnapshot`, `RetryAttempt`, and `RetryOutcome`. Package progress is copied
into stable value fields so importing the event contracts does not load a
materializer backend.

Stable event kinds preserve the current runtime names:

```text
session.queue_update
session.compaction_start
session.compaction_end
session.auto_retry_start
session.auto_retry_end
session.branch_summary_start
session.branch_summary_end
session.session_info_changed
session.package_progress
session.tool_action_frozen
session.tool_policy_evaluated
session.tool_approval_requested
session.tool_approval_resolved
session.tool_execution_started
session.tool_execution_completed
session.tool_execution_failed
transcript.record_committed
```

Raw Agent events keep their Agent-owned payload and use `agent.<type>` kinds.
Harness does not duplicate the `AgentEvent` union.

Workspace tools retain their narrow mapping-based `ToolEventSink` protocol.
The Session Host recognizes only the seven public Gateway audit event types
and normalizes each mapping into `ToolPolicyAuditEvent` before publication.
The retained type name covers the existing compatibility surface; the payload
now spans action freeze through terminal execution. Unknown mappings fail
instead of silently entering the common runtime stream.

These mappings contain structurally redacted action and command summaries.
They do not carry raw commands, cwd/path values, contents, stdin, environment
data, free-form decision reasons, or exception text. A restricted raw-evidence
store, when explicitly enabled by a deployment, is a separate sink rather than
another Session event projection.

## Coding Adapter

Coding controllers now emit Harness payloads rather than constructing Coding
event dictionaries. `AgentSession` publishes Agent and common Session payloads
through one Runtime publisher and one ordered bus.

`AgentSession.subscribe_runtime_events()` exposes the common stream directly.
The accepted `AgentSession.subscribe()` API installs a listener adapter on that
same bus and converts observable Agent/Session payloads into the standard
`harness.session.event_types.AgentSessionEvent` dictionary. Transcript commit
events are intentionally invisible to this projection.

Products continue to own:

- RPC, print, TUI, and extension filtering;
- Product artifact display and genuinely Product-specific event payloads;
- final output policy and Product exports.

Harness additionally owns `RuntimeEventView`: a strict-JSON, source-preserving
transport view and generic exact/trailing-wildcard selector. Products create a
view only after applying the standard Session mapping and any Product policy.
The shared view payload uses snake_case; `harness.session` owns the standard
event names and tool-render enrichment, while Products retain final stream
policy without alias expansion.

`loushang.channel` may carry an already-created `RuntimeEventView`; it depends
only on this value contract, while Harness never imports Channel. This neither
makes RuntimeEvent a durable event log nor replaces WorkEvent's separate work
semantics.

The generic Session coordination mechanisms that produce these facts are
documented separately in [Session Runtime Core](product-runtime-injection/components/session-runtime-core.md).
They remain optional Agent/AI profile code and do not make the neutral event
core depend on Agent or AI.

`AgentSessionEvent` is therefore a Session projection contract, not a runtime
control or storage model. The removed `coding.session.SessionEventBus` must not
be recreated.

## Ordering

Transcript mutation ordering is:

```text
Store append
  -> CommitReceipt
  -> transcript.record_committed
  -> later runtime facts that reference the committed record
```

A failed Store append publishes no commit event. A listener or Product
projection failure after a successful append may propagate to the caller but
must not repeat or roll back the append.

## Product And OEM Extension

A Product or OEM may subscribe to `RuntimeEvent` and provide another projection
without modifying Harness. Product-only facts use Product-owned namespaced
kinds and payloads; they are not added to the common Session payload union
unless their semantics are genuinely cross-product.

This migration does not add:

- an event log, outbox, CDC, or replay protocol;
- cross-process or network event transport;
- Redis pub/sub, database notification, or delivery acknowledgement;
- command dispatch through the observation bus;
- a replacement for AgentEvent or WorkEvent.

Those capabilities require separate persistence and delivery contracts.

## Verification

- Harness event modules import no Agent, AI, Product, Work, Method, or TUI code.
- Coding controllers do not import `loushang.coding.event`.
- `AgentSession` contains one Runtime event bus and no Product event bus.
- common payloads map to stable runtime kinds;
- Gateway audit mappings become typed payloads at the Session boundary;
- Coding projection preserves its accepted dictionaries and wire fields;
- transcript commit and later Session facts share one monotonic sequence;
- Work observes the Runtime stream rather than subscribing to the Product API.
