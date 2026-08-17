# Harness Agent Transcript Profile Boundary

## Status

Status: implementation complete for integration into `lane/harness`.

This wave replaces the Coding-owned common transcript model with one optional,
cross-product Agent transcript profile. It is not a directory-only move of
`coding.message`: the wave establishes the final durable record schema, codec,
runtime commit, replay projection, and Product-extension boundary once, then
removes the old Coding implementation.

## Layering And Ownership

`loushang.harness.conversation` remains the neutral core. It owns the generic
`ConversationHeader`, `ConversationRecord[T]`, repository, tree, fork, replay,
catalog, checkpoint mechanics, and compaction planning. It must not import AI,
Agent, Coding, or another Product package.

`loushang.harness.transcript` is an optional profile over that core. It
owns the common durable meanings required by Agent-backed Products:

- Agent messages and their stable wire codec;
- model and thinking selection snapshots;
- command execution, context-compaction checkpoint, and branch-summary records;
- application messages, extension data, annotations, and conversation metadata;
- record codec registration, opaque preservation, state reduction, model-context
  projection, checkpoint resolution, and the standard writer/committer;
- compilation of profile handlers into the existing conversation replay and
  compaction ports.

It does not introduce a second repository, branch graph, replay folder, or
compaction engine. Importing `loushang.harness` must not eagerly import this
optional profile.

A Product selects this profile and registers only its irreducible domain
payloads and projections. Product kinds use a namespace such as
`coding.patch`, `research.citation`, `design.frame`, or `ppt.slide`.

## Native Wire Contract

The native file uses an explicit conversation header discriminator and a
versioned record envelope. The stable logical shape is:

```python
ConversationRecord(
    record_id: str,
    parent_id: str | None,
    kind: str,
    payload_version: int,
    created_at: str,
    payload: PayloadT,
    metadata: Mapping[str, JSONValue],
)
```

Representative JSONL records are:

```json
{"type":"conversation","version":1,"conversationId":"...","createdAt":"..."}
{"type":"record","kind":"agent.message","payloadVersion":1,"recordId":"...","parentId":null,"createdAt":"...","payload":{}}
```

`ConversationHeader.version` versions the file/envelope schema.
`ConversationRecord.payload_version` versions one record kind's payload. The
latter must be an integer greater than or equal to one, and `bool` is not an
integer for this contract. Mixed payload versions may occur in one
conversation. An ordinary load, rewrite, or fork never upgrades payload
versions implicitly; migration is an explicit operation.

Envelope metadata and JSON-backed payloads use the strict
`loushang.foundation.json.JSONValue` algebra.

## Standard Record Kinds

The initial profile owns these stable kind strings:

| Current Coding value | Native record kind |
| --- | --- |
| `SessionMessageEntry` | `agent.message` |
| `ThinkingLevelChangeEntry` | `agent.thinking_selection` |
| `ModelChangeEntry` | `agent.model_selection` |
| `BashExecutionMessage` | `command.execution` |
| `CompactionEntry` | `context.compaction_checkpoint` |
| `BranchSummaryEntry` | `context.branch_summary` |
| `CustomMessageEntry` | `application.message` |
| `CustomEntry` | `extension.data` |
| `LabelEntry` | `record.annotation_patch` |
| `SessionInfoEntry` | `conversation.metadata_patch` |

These names are transcript record kinds, not Python modules, Agent message
roles, or event names. `agent.message` directly carries a supported existing
Agent message. Model and thinking records carry stable value snapshots; they
must not persist model-registry objects, Provider configuration, or credentials.

`command.execution` wraps the existing Harness `CommandExecutionRecord`.
Harness supplies a reusable default model-context projection, while a Product
may override wording, visibility, or presentation.

`context.compaction_checkpoint` and `context.branch_summary` have deliberately
different semantics. Only the checkpoint kind may resolve to a
`ConversationCheckpoint`; a branch summary is an ordinary visible context
record and never truncates history.

Annotations use explicit set/remove operations rather than overloading `None`.
Conversation metadata is an append-only patch with disjoint values and removed
keys. Both reduce deterministically along the selected conversation path and
are invisible to model context by default.

## Hidden Model-Call Facts

The profile also owns three hidden record kinds for the durable
prepare-before-send closure:

- `model.input.component` retains one canonical strict-JSON value with its
  SHA-256 content fingerprint;
- `model.input.prepared` retains ordered component references, logical and
  final prepared-payload fingerprints, invocation identity, source and commit
  clocks, and the committed Profile/Mount/registration references;
- `model.call.outcome` closes one logical invocation after internal Provider
  retries, linking its complete ordered prepared-snapshot sequence to a safe
  completed, failed, or cancelled terminal result.

These records have codecs but no model-context or rendered transcript-body
projection. Portable export data retains the authoritative facts, and an entry
tree may retain their kind and record identity without rendering their payload.
Repeated content is referenced by ancestor record ID and content hash instead
of being copied into every snapshot. A selected-path fork preserves historical
facts unchanged: their `conversation_id` remains creation provenance, while
their source and commit revisions remain clocks from that creation
conversation. The parent-linked record ancestry proves reachability in the
fork; fork-local record positions do not rebase those origin clocks. New facts
in the fork use the fork conversation identity and may reuse reachable
components.

The v1 writer applies an exact 1 MiB ceiling to each encoded default JSONL
record, including its envelope and newline. Oversized content fails before
that record is appended and before provider transport; it is never truncated.
The ceiling applies at the common unit-of-work commit boundary for both
reserved Model Input kinds. A composition may select a lower limit but cannot
raise the v1 ceiling.
Payload version 2 replaces monolithic values with bounded typed node bundles,
large-value chunks, sequence tails, and root-only prepared snapshots. Version 1
facts remain readable and are never rewritten. Because the Store is append-only,
components committed before a later component or snapshot failure may remain
as harmless reusable facts. Only a committed `model.input.prepared` record is
a Model Input snapshot.

`prepared` proves only that AI's final model-visible request passed its frozen
request barrier and that Harness committed its reconstructable facts. It does
not claim that transport was attempted, accepted, or failed. AI owns the
prepared-request value and pre-transport commit port; Harness implements that
port without an `AI -> Harness` dependency. A separate `model.call.outcome`
fact may later close the invocation; a missing fact remains unknown rather than
mutating the prepared snapshot. This wave proves one explicit
main-turn composition whose logical projection contains system prompt,
messages, Tool schemas, and relevant request options, plus
restart/source-deletion reconstruction. Wiring all managed Session call and
retry paths remains a later closure.

The v1 snapshot schema requires references named `system_prompt`, `messages`,
`tools`, and `request_options`, plus a `model_visible_headers` reference.
Reconstruction additionally requires messages and tools to be arrays and
request options to be an object. Provider-specific prepared-payload fields
remain unconstrained.

## Codec And Opaque Contract

The conversation codec always validates and decodes the envelope. The profile
then selects a payload codec by `(kind, payload_version)`:

- an unregistered pair produces the same `ConversationRecord` with an
  `OpaquePayload` containing a defensive strict-JSON snapshot, unless the
  active profile marks that kind as core and required for reconstruction;
- an unknown payload version for a required core kind fails closed instead of
  becoming opaque; the standard Agent profile applies this rule to both Model
  Input kinds;
- a registered codec that rejects its payload reports a corrupted known
  record and must not fall back to opaque;
- opaque records remain part of parent graphs and survive load, selected-path
  fork, and rewrite with JSON-semantic equivalence;
- opaque payloads are state-reducer no-ops, invisible to model context, and do
  not resolve checkpoints by default.

The preservation promise is semantic JSON equality, not byte equality, field
order, whitespace, or escape spelling.

## Profile Composition

`AgentTranscriptProfile` is one composition root with orthogonal registration
axes:

```text
record codecs by (kind, payload_version)
stable state reducers
model-context projectors
checkpoint resolvers
compaction dispositions
Product presentation dispositions and overrides
```

Wire versions and runtime semantics do not share one lifecycle. The profile
validates its capability matrix and compiles handlers into the existing
`ConversationReplayPorts`, record ports, and compaction ports. Missing reducers
default to no-op, missing context projectors to invisible, and missing
checkpoint resolvers to no checkpoint. A missing codec means opaque data, not a
second replay path.

Durable-record projection remains split by audience: profile code projects
state and Agent/model context; Product, Work, RPC, HTML, and TUI adapters own
their display or transport projections. A UI must not reconstruct durable
record meaning from a projected pseudo-Agent message.

## Application Message Commit

An application message carries a stable `application_message_id`, distinct from
the durable `record_id`. A single `TranscriptCommitter` owns persistence for
direct application messages and messages that pass through trigger-turn,
next-turn, steering, or follow-up paths.
`harness.session.ApplicationInputRuntime` owns the delivery split; controllers,
queues, and the Agent event router do not append those records independently.

Within one process and session lifecycle:

- the same application id and payload returns the already committed record id;
- the same application id with a different payload raises an identity conflict;
- append failure neither advances the active leaf nor records the id as
  committed;
- event-dispatch retry may repeat projection but must not append again.

This is in-process idempotent transcript commit. It is not crash-safe
exactly-once delivery. Ordinary user, assistant, and tool messages do not gain
an exactly-once claim from this contract.

## Conversation JSONL And External Data

The Conversation JSONL envelope starts at version 1. Before 1.0, earlier
development-only formats do not create a compatibility promise. In particular,
Session v3 is not part of normal discovery or Resume.

The existing Session v3 importer is an explicit migration utility only:

```text
current Loushang Session format (version 3)
  -> Conversation JSONL format
```

It does not participate in the Conversation JSONL reader. After 1.0, every
released Conversation JSONL version remains readable by the single current
decoder; payload evolution continues to use each record's `payloadVersion`.

Unknown future Conversation JSONL versions are rejected explicitly and must not
enter empty-session recovery. A partial tail may use the documented journal
recovery policy, but unknown profile payloads are valid opaque records and may
not be handled by `invalid_record="skip"`.

Pi, Claude Code, Codex, and other ecosystem formats are External data. Their
future importers will be read-only source adapters that emit the Conversation JSONL
schema through the canonical writer and record source provenance plus import
diagnostics. External importers are deferred from this wave and do not belong
in the Conversation JSONL reader.

## Dependency Boundary

The neutral conversation core may depend on `loushang.foundation.json`, but not
AI or Agent. The optional Agent transcript profile may depend only on these
AI/Agent data, wire-codec, and prepared-request contract modules:

- `loushang.ai.types`
- `loushang.ai.json_codec`
- `loushang.ai.prepared_request` (the pure prepared-request value and commit
  protocol)
- `loushang.agent.types`
- `loushang.agent.json_codec`

It may also depend on `loushang.foundation.json` and neutral Harness packages.
It must not import AI API, auth, provider/providers, model registry or selection
package, event stream, model invocation, or any Product. A local pure-value
`ModelSelectionSnapshot` avoids importing `loushang.ai.model`, whose package
initialization loads broader model infrastructure.

AI and Agent must not depend back on Harness.

## Product Kernel

After cutover, a Product retains:

- goals, domain language, completion criteria, system prompts, prompt sections,
  skills, and their default activation;
- domain-exclusive tools, selection of common tool packs, and activation policy;
- context salience, exact compaction/summary prompts, artifact semantics, and
  domain-specific transcript payloads;
- risk classification, approval defaults, permission policy, Product commands,
  settings defaults, resource roots/conventions, UI, and display/transport
  projections;
- storage-root, naming, retention, import-acceptance, and Product index/search
  policy.

It does not retain duplicate common message records, codecs, repository,
replay, compaction mechanics, or application-message commit routing.

## Delivery Sequence

The semantic branch remains reviewable through four green commits:

1. **Schema Foundation**: this decision, import gates, strict envelope,
   payload version, codec registry, opaque preservation, and Native v3 format
   recognition without changing Coding session behavior.
2. **Agent Transcript Profile**: standard payloads, writer, profile
   composition, state/context/compaction ports, and default projections without
   a parallel repository or replay engine.
3. **Runtime Cutover**: Native v3 migration, store/session/compaction/queue and
   Agent-router adoption, one committer, clear unsupported-format diagnostics,
   and no destructive recovery.
4. **Projection Cutover**: TUI, HTML, RPC, event, and Work adapters, followed by
   deletion of `loushang.coding.message`, its old codec, and compatibility
   exports.

A temporary re-export may keep an intermediate branch commit green, but it is
not a public compatibility promise and must not survive the fourth commit.

## Explicit Non-Goals

This wave does not implement:

- a second conversation repository, replay folder, branch graph, or compaction
  engine;
- v1/v2 Native migration or a generic historical migration registry;
- Pi, Claude Code, Codex, or other External importers;
- byte-preserving JSONL rewrite;
- crash-safe exactly-once, a persistent delivery queue, transaction log, or
  event outbox;
- provider calls, model discovery, authentication, credentials, or Product
  policy;
- old Coding message APIs or old wire-format compatibility after cutover.

## Completion Criteria

The wave is complete only when:

- production code has no `loushang.coding.message` import and the implementation
  package is deleted;
- current Loushang v3 sessions migrate safely, migration failure leaves source
  data unchanged, and repeated open does not migrate again;
- known, unknown-kind, unknown-version, and corrupted-known payload behavior is
  covered, including opaque ancestors, leaves, selected paths, fork, and
  rewrite;
- tool-call/tool-result turns remain atomic during compaction and branch
  summaries never resolve checkpoints;
- application-message duplicate and identity-conflict paths are covered across
  trigger-turn, next-turn, steering, follow-up, retry, and continue flows;
- every standard kind has an explicit state, context, checkpoint, and
  presentation disposition;
- conversation-core neutrality and the profile's exact dependency allowlist
  pass architecture tests;
- focused migration, session, replay, compaction, TUI/HTML/RPC/Work, full
  non-live, and Ruff checks pass.
