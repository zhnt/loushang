# Runtime Event Projection And Channel Boundary

## Decision

`loushang.harness.events` owns event facts, the neutral `RuntimeEvent`
envelope, the transport-ready `RuntimeEventView` value contract, generic
selection/projection primitives, and recursive JSON key normalization.
`loushang.harness.session` owns the Agent-session dictionary types, standard
session view serialization, tool-render enrichment, and the complete
RuntimeEvent-to-view path, including delivery hints and correlation IDs.
`harness.events.recording_policy` owns the neutral decision about which runtime
facts become transcript records and the shared cancelled-error classifier.
`loushang.channel` owns the external envelope, JSON codec, and JSONL frame that
can deliver an already created view. Product code owns only the conversion from
a Product/runtime source into a session mapping plus any genuinely
product-specific final presentation policy. The shared runtime event payload
uses one snake_case vocabulary; Pi/camelCase aliases are not accepted or
emitted.

```text
RuntimeEvent (Harness)
  -> Product projection
  -> RuntimeEventView (Harness value contract)
  -> ChannelEnvelope / ChannelEventDelivery (Channel)
  -> client transport
```

The Work path remains independent:

```text
RuntimeEvent -> Work projection -> WorkEvent -> ChannelEnvelope
```

Neither path replaces the other. `RuntimeEvent` is a transient observation,
`RuntimeEventView` is a transient transport representation, `WorkEvent` is a
normalized work/audit semantic event, and `ConversationRecord` remains the
durable transcript fact.

## Runtime Event View Contract

`RuntimeEventView` preserves source identity:

- `event_id`, `kind`, `stream_id`, `sequence`, and timezone-aware
  `occurred_at`;
- optional `session_id`, `run_id`, `source_event_ref`, and `source_record_id`;
- Product-created `event_type`, `view`, optional `correlation_id`, and
  delivery hint;
- a copied strict-JSON object payload.

The view constructor rejects invalid source metadata, unsafe JSON, and unknown
delivery hints. The generic selector accepts only exact matches and a trailing
`*`; aliases such as `assistant.*` are not expanded by any shared runtime
event path.

## Channel Contract

`ChannelEnvelope(kind="event")` accepts either a `WorkEvent` or a
`RuntimeEventView`. Existing Work event JSON is unchanged. Runtime views use:

```json
{
  "event_family": "runtime",
  "event_id": "...",
  "kind": "agent.message_update",
  "stream_id": "session:...",
  "sequence": 7,
  "occurred_at": "2026-07-19T12:00:00+00:00",
  "event_type": "assistant_delta",
  "view": "assistant_stream",
  "delivery_hint": "coalesce",
  "payload": {"type": "assistant_delta", "delta": "..."}
}
```

`event_family` distinguishes the runtime representation only. Unknown
additive fields remain ignored by the existing object decoder. Channel does not
attempt Product event mapping, selector expansion, render enrichment,
subscription, acknowledgement, replay, or delivery scheduling.

## Dependency Direction

```text
harness.events                      -> protocol
harness.session.event_types         -> agent + harness.events
harness.session.event_projection    -> agent + ai + harness.presentation
harness.session.runtime_event_views -> harness.events + harness.session
harness.host                        -> harness.session + harness.events
channel                             -> work
channel.host                        -> harness.host.product_host
channel.adapters.runtime_events     -> harness.events + harness.session
```

Harness has no Channel import. Channel core imports stable Harness Host and
event-view contracts; its optional runtime-event adapter imports the standard
Harness session projection. Channel never imports a Harness event bus,
publisher, store, Product adapter, Coding, Method, or TUI. This one-way
direction lets an OEM Channel implementation carry runtime views without
making its transport part of the Harness runtime.

## Coding Adoption

Coding retains its accepted `AgentSessionEvent` import surface and delegates
standard Agent-session mapping and JSON projection to
`harness.session.event_types`, `harness.session.event_projection`, and
`harness.session.runtime_event_views`. `harness.events.recording_policy` owns
the neutral transcript-write decision. There is no Coding event facade;
Product/work mapping and final presentation remain in their Product owners.
JSON PrintMode and RpcMode subscribe to `subscribe_runtime_events()` when the
session offers it. The old `subscribe()` path remains only for text display and
compatibility session doubles.

## Exclusions

This wave does not add a transport loop, channel registry, capability
negotiation, cross-process replay, acknowledgement/outbox, event persistence,
or a generic Product event language. Those need separate Channel and Host
contracts.
