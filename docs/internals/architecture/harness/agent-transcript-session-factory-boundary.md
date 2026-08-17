# Harness Agent Transcript Session Factory Boundary

## Status

Status: implementation complete for integration into `lane/harness` on
`harness/agent-transcript-session-factory`.

## Purpose

`loushang.harness.transcript.AgentTranscriptSessionFactory` owns the
reusable assembly of a Conversation JSONL Agent transcript session. It composes an
already configured `AgentTranscriptLifecycle` into Product-facing `new`,
`load`, `open`, `continue_recent`, `in_memory`, `fork_from`, and selected-path
`fork` operations.

This is an orchestration boundary, not another store, repository, transcript
profile, or Product session facade. `AgentTranscriptLifecycle` remains the
owner of store binding, durable create/restore, detached restore, copied-path
forking, and runtime-lease disposal.

## Product Contract

A Product supplies only these decisions:

- a binding-input resolver for each persistence mode;
- header metadata derived from that selected binding;
- validation of a restored header against its Product resume policy; and
- optionally, a Conversation JSONL session-file naming policy.

The factory owns conversation-id validation and generation, UTC header time,
standard `cwd` and `parentSession` metadata, Native source context construction,
recent-session selection, and parent conversation lineage. It creates no
Product records and does not import Coding.

The optional session-file callback is deliberate. A Product selecting a file
store passes its Native filename policy; a Product selecting SQL, Redis, or an
OEM `ConversationStore` omits it and receives a persistent context without a
file path. Native `load`, `continue_recent`, and `fork_from` remain current
Native file operations, not a database discovery API.

## Lifecycle Semantics

`load` validates the Conversation JSONL header before acquiring the Product runtime
binding. A non-persistent load remains a detached copy through
`AgentTranscriptLifecycle`, so later writes never mutate the source file.

`fork_from` loads the source as a detached session, copies its records into a
fresh target binding, records the parent conversation and source file reference,
then releases the detached source lease even if target creation fails. `fork`
copies only the requested active path and uses an explicit Product-selected
binding input, so a caller can preserve a currently selected profile while
creating the new session.

## Product Boundary

Coding retains the current runtime/capability profile resolver, snapshot
metadata, resume compatibility validation, root and persistence choices,
catalog presentation, CLI/TUI behavior, diagnostics, and its `SessionManager`
compatibility facade. Its facade delegates session creation and restoration to
the factory rather than rebuilding headers, Native contexts, or fork plumbing.

Other Products may choose a different profile, metadata, store binding, and
file policy. They must not add domain-specific header construction or runtime
resolution to this factory.

## Verification

- Harness tests cover metadata construction, explicit ID validation before
  runtime binding, Native create/open, selected-path fork, detached `fork_from`,
  and lease disposal.
- Coding session-manager and runtime-profile tests exercise the same factory
  through Coding's existing public facade.
- Import-boundary tests require the Coding facade to adopt
  `AgentTranscriptSessionFactory` while the factory has no Coding imports.
