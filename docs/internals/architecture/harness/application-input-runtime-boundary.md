# Application Input Runtime Boundary

## Decision

`loushang.harness.session.ApplicationInputRuntime` owns common delivery
coordination for an `ApplicationMessage`. It is an optional Agent transcript
profile component. A Product adapts its own extension, SDK, RPC, or UI input
shape into the standard message and supplies the commit, queue, turn, and
projection ports.

Harness owns the following delivery modes:

| Mode | Runtime action | Durable commit owner |
| --- | --- | --- |
| `direct` | commit, then invoke the injected direct projector | `TranscriptCommitter` |
| `trigger_turn` | invoke the injected Agent turn | Agent event router -> `TranscriptCommitter` |
| `next_turn` | append to the next-turn queue | Agent event router -> `TranscriptCommitter` |
| `steering` | enqueue a visible steering item | Agent event router -> `TranscriptCommitter` |
| `follow_up` | enqueue a visible follow-up item | Agent event router -> `TranscriptCommitter` |

No controller, queue, or event router owns a second ApplicationMessage journal
append path. The durable record id remains distinct from the stable
`application_message_id`.

## Direct Commit Contract

For `direct` input the ordering is fixed:

```text
TranscriptCommitter commit
  -> durable commit receipt / transcript.record_committed
  -> Product refreshes Agent transcript context
  -> Product projects message_start and message_end
```

Within one runtime instance, a successfully projected direct application id is
not projected again. If projection raises after a successful commit, the id is
not marked projected; a later delivery of the same id reuses the durable record
and retries only projection. `TranscriptCommitter` rejects the same id with a
different payload and rebuilds its commit index from the opened transcript.

This is idempotent transcript commit, not transactional exactly-once delivery.
Queued and trigger-turn input may still execute more than once if a caller
submits it more than once; their transcript append remains idempotent by
application id. Crash recovery does not persist projection completion or queue
delivery acknowledgement.

## Product Adapter

Coding keeps:

- Pi-compatible `sendMessage` and `sendUserMessage` argument parsing;
- its `deliverAs` and `triggerTurn` mapping into a standard delivery mode;
- UserMessage construction, preflight, command rejection, Extension API error
  wording, and Product event/UI/RPC projections;
- Product construction of the direct projector that refreshes its Agent state
  and publishes its accepted event projection.

Coding's extension message controller no longer imports `SessionManager` or
appends an ApplicationMessage itself.

The optional `harness.extensions.agent.input` profile is a consumer of this
runtime, not a second delivery engine. It accepts already-normalized typed
extension application/user input and invokes injected delivery and prepared
queue ports. It does not import `harness.session`. Coding's extension adapter
performs Pi-compatible argument parsing and chooses the typed delivery mode
before calling the profile. In particular, the profile does not receive raw
extension dictionaries and does not parse `customType`, `deliverAs`, or
`triggerTurn`; those are Product wire-contract concerns.

## Dependency And Verification

The runtime imports only Harness transcript values and injected ports. It does
not import Coding, Store backends, extensions, Agent execution, AI providers,
authentication, Work, Method, or presentation code.

Verification covers direct commit/projection idempotence, projection retry
without a second append, all delayed mode routing, the real Coding
`AgentSession` composition, and an import-boundary guard on the Product
adapter.

## Non-goals

This boundary does not add a queue database, outbox, distributed lease,
cross-process delivery acknowledgement, persistent event transport, or a new
extension wire API.
