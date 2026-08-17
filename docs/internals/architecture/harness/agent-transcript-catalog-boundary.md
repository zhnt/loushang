# Harness Agent Transcript Catalog Boundary

## Status

Status: implementation complete for integration into `lane/harness` on
`harness/agent-transcript-catalog`.

Discovery/index placement in this historical wave is superseded by
[Conversation Persistence Refactor](conversation-persistence-refactor.md).

## Purpose

`loushang.harness.transcript.session_catalog` owns the reusable read model
for Agent transcripts. It provides `AgentTranscriptSessionCatalog`,
`SessionRecord`, `SessionSummary`, `SessionQuery`, and `SessionTreeNode` for
discovery, summary projection, query, JSON projection indexes, and annotated
branch trees.

This is an optional Agent/AI profile, not a neutral Harness core. The neutral
`loushang.harness.conversation` package remains independent of Agent and AI.
The catalog consumes provider-bound `ConversationStore` registrations through
the neutral `ConversationCatalog`; it must not import Coding or a Product
package.

## Ownership

Harness owns these standard current-format facts:

- Agent-specific projection and query over provider-discovered conversations;
- per-session metadata, message previews, model snapshot, and diagnostic
  summary fields;
- filters by workspace, name, parent session, text, diagnostic presence, and
  limit, including relevance ordering;
- rebuildable JSON projection indexes for those summaries;
- display-label annotations and selected-branch context reconstruction;
- canonical comparison of transcript session paths.

The catalog uses `ConversationCatalog`, `ConversationRepository`, and
`JsonConversationIndex`. It does not create another repository or replay
implementation. It does not scan JSONL itself; the bound Store owns physical
discovery and loading.

`AgentTranscriptDirectoryRuntime` is the optional runtime layer above that
catalog. It owns current-root and all-root queries, direct or coalesced index
refresh, and deterministic drain on disposal/tests. It does not create or
replace an active session, choose a Product root or retention policy, or
classify Product diagnostics.

Products choose their session roots, whether persistence is enabled, the
runtime transcript profile, product-specific projected fields, retention,
display names, and CLI/RPC/TUI presentation. `coding.session_manager.SessionManager`
remains the Product lifecycle adapter; it delegates the
standard read model instead of maintaining a second catalog.

## Extensibility

`SessionSummary` is a common read model, not a closed cross-product schema. A
Product needing domain-specific search or index fields composes its own
projection over the same Native records or supplies another catalog profile.
It must not fork the file discovery, summary, query, or index mechanics merely
to add presentation fields.

Database and remote Store providers can participate through the same provider
binding. Redis is suitable as an optional bounded/rebuildable index, not as the
assumed authoritative full transcript.

## Verification

- Harness tests cover Native discovery, direct and root-level query, projection
  index refresh/load and coalesced scheduling, branch context, and annotation
  labels without importing Coding.
- Coding session tests exercise the same owner through its compatibility
  facade.
- Import-boundary tests require `SessionManager` to delegate to
  `AgentTranscriptSessionCatalog`, require `AgentSessionRuntime` to consume
  `AgentTranscriptDirectoryRuntime`, require the catalog to use
  `ConversationCatalog`, and prohibit catalog imports from Coding.
