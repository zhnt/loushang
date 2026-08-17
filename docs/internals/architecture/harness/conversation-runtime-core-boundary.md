# Harness Conversation Runtime Core Boundary

## Status

Status: implementation complete for integration into `lane/harness`.

This capability owns the product-neutral mechanics behind durable, branching
agent conversations. It lets Coding, Research, Design, PPT, Cowork, and OEM
products share one repository, replay, catalog, and compaction-planning core
without forcing every Product to share a transcript profile, prompt, model, or
artifact vocabulary. Agent-backed Products may select the follow-on common
[Agent Transcript Profile](agent-transcript-profile-boundary.md).

## Ownership

`loushang.harness.conversation` owns:

- neutral conversation headers, parent-linked record envelopes, tree nodes,
  branch deltas, and structured `CommandExecutionRecord` payloads;
- header and record codec ports, projector ports, and state-folder ports;
- the single pure in-memory `ConversationRepository`, composed with the
  conversation-owned `BranchGraph` and independent of JSONL;
- active-path selection, children, tree construction, lowest common ancestor,
  branch delta, fork, and state fold mechanics;
- `ConversationReplayFolder`, including visible-item projection, checkpoint
  replacement, first-kept suffix reconstruction, and independent product-state
  folding;
- provider-bound `ConversationCatalog`, `ProjectionQuery`, and revision-aware
  `JsonConversationIndex` for discovery, projection, cache, filter, and search;
- functional adapters for products that prefer callables over custom classes.

`loushang.harness.context.conversation` owns:

- `ConversationCompactionPlanner` and its product-neutral planning contract;
- opaque-record turn grouping;
- recent-token cut-point selection;
- non-cut roles such as tool results;
- split-turn history, turn-prefix, and kept-record planning;
- previous-summary boundary and token accounting;
- cut-group expansion so invisible metadata can remain attached to the first
  kept visible record;
- separate per-record cut estimation and aggregate context-token estimation.

These neutral conversation packages must not import Coding, Agent, AI messages,
model/provider code, Product stores, Method, Work, TUI, or channel
implementations. The optional `loushang.harness.transcript` package is a
separate profile with a narrow data/codec allowlist; it does not weaken this
core boundary.

## Product Ports

A Product supplies the semantics that cannot be inferred by Harness:

- domain-specific record payloads and codecs not supplied by a selected common
  profile;
- record id, parent id, visibility, role, and token-estimation functions;
- checkpoint recognition and summary-item projection;
- product state initialization and reduction;
- catalog discovery roots, accepted filenames, summary fields, match/scoring
  rules, index location, and fail-fast or per-item projection-error policy;
- exact compaction and branch-summary prompts/profiles, model and credential
  selection, domain artifact decoration, and product error wording;
- command-record projection into its Agent message and UI/event protocols.

The split is deliberately asymmetric: the neutral core owns control mechanics,
the optional Agent profile owns common Agent transcript meanings, and Products
name and interpret only their domain data and policy.

## Coding Adoption Baseline

The following records the baseline delivered by this core. The later Agent
Transcript Profile wave supersedes the Coding ownership of common session-entry
schemas, codecs, and replay projection described here; Product storage-root,
prompt, artifact, and presentation policy remain Coding-owned.

Coding now uses `AgentTranscriptUnitOfWork` as the single open-session commit
owner over an injected `ConversationStore`. The optional Agent transcript
profile owns the Conversation JSONL codec, journal factory, file locking, revision
CAS, and durable append; Coding chooses the storage root and runtime binding.
Successful Agent transcript mutations return the record paired with the
backend's exact `CommitReceipt`; Product event projection does not infer
revision from a later snapshot.

`SessionManager` is an async Product adapter. It delegates active branches,
children, tree, fork, lowest common ancestor, branch delta, replay, transcript
commit, and backend persistence to Harness. Coding retains:

- label, cwd, naming, retention, recovery, and session-file policy;
- `SessionSummary` fields, message text/preview, diagnostics, and relevance
  scoring;
- Product catalog/index/query projection and backend selection.

Coding compaction uses the Agent transcript profile's planner and standard
summary executor. The former local cut-point, latest-checkpoint, turn-start,
tool-result, kept-id, message serialization, model-call, and branch-summary
algorithms have been removed. Coding keeps prompt/profile selection, model and
credential selection, file-operation decoration, extension hook mapping, and
summary presentation.

`BashExecutionMessage` specializes `CommandExecutionRecord`; the historical
`bashExecution` role and JSON fields remain Coding-owned.

## Baseline Compatibility Invariants

- Conversation JSONL Coding JSONL files decode with the same Product codec and
  remain writable without schema migration. Older Loushang and external formats
  require an explicit importer and are never rewritten by Product load or scan.
- Harness replay and compaction planning reject missing or future retained-record
  boundaries by default; Coding explicitly selects summary-only recovery for
  historical malformed records.
- Harness catalogs fail fast by default; Coding explicitly skips a single bad
  Product projection to preserve directory enumeration behavior.
- Branch selection, tree labels, fork contents, and unknown-leaf behavior are
  unchanged.
- Replay uses only the selected active path and the latest checkpoint, delays
  visible projection until that checkpoint is known, and still folds model and
  thinking state across every path record.
- A tool result cannot become a compaction cut point.
- Split-turn plans preserve history, turn-prefix, and kept ids.
- summarized, turn-prefix, and kept record partitions never overlap.
- Aggregate context usage and per-record cut estimates remain distinct.
- Metadata immediately preceding a retained message stays inside the retained
  checkpoint boundary.
- Product prompt/profile selection, artifact details, and summary presentation
  remain behavior-compatible.

## Neutrality Evidence

Harness tests use Research-shaped records to exercise persistence, branching,
fork, tree, LCA/delta, replay checkpoints, catalog/index/query, turn grouping,
split turns, tool-result atomicity, metadata cut groups, and previous-summary
accounting without importing Coding or AI.

Coding tests cover historical JSONL codecs, context replay, session catalogs,
fork/tree/labels, compaction parity, branch summaries, and command-record
projection. Architecture tests enforce dependency direction and prevent these
new symbols from becoming accidental top-level Harness exports.

## Explicit Non-Goals

This capability does not:

- define a universal domain transcript schema or force non-Agent Products to
  use the optional Agent profile;
- serialize `AgentMessage` inside the neutral conversation core; the optional
  Agent transcript profile owns that common capability under its exact import
  allowlist;
- choose a model, resolve credentials, or call a provider;
- define compaction prompt text, salience policy, memory policy, or artifact
  meaning;
- choose Product session roots, filenames, retention, recovery, or index fields;
- replace Product controllers, commands, event protocols, UI, or host lifecycle;
- migrate shell selection, execution lifecycle, hooks, or approval policy.

The Agent Transcript Profile composes this core with common Agent transcript
semantics without moving Product prompts, artifacts, storage policy, commands,
or UI into Harness. See
[Agent Transcript Profile Boundary](agent-transcript-profile-boundary.md).
