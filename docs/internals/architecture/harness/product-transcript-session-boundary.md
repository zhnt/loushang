# Product Transcript Session Boundary

## Status

Implemented on `harness/session-adapter-collapse`.

## Purpose

`loushang.harness.transcript.ProductTranscriptSession` is the reusable
Product-facing wrapper around a bound `AgentTranscriptLifecycleSession`. It
owns the repetitive session surface shared by Coding, Research, Design, PPT,
and OEM-defined Products:

- create, open, load, recent-resume, in-memory, and selected-path fork;
- current transcript metadata, records, context, tree, labels, diagnostics,
  catalog queries, index refresh, rename, and delete; and
- disposal of the Product runtime binding after the transcript operation ends.

It delegates Native file assembly to `AgentTranscriptSessionFactory` and does
not introduce another repository, store, replay, or transcript schema.

## Product Binding

A Product subclass supplies exactly two decisions:

1. its bound `AgentTranscriptSessionFactory`; and
2. the immutable binding input used when a selected transcript path is forked.

The Harness class has no model registry, auth, prompts, tool policy, extension
policy, UI, or Coding import. Products retain those choices in their runtime
profile and session assembly.

Coding's `SessionManager` is therefore a small binding adapter: it selects the
Coding runtime/capability profile, validates restored headers, exposes Coding
runtime capabilities, and delegates all generic transcript-session mechanics
to `ProductTranscriptSession`.

## Standard Session Contract

The active Coding session and runtime use snake_case APIs. The core no longer
provides Pi SDK aliases such as `getAllTools`, `newSession`, `switchSession`,
or `sendMessage`. Equivalent capabilities remain available through
`get_all_tool_infos`, `new_session`, `restore_session`, `send_message`, and
the explicit `*_operation` methods that return a Harness
`SessionOperationResult` when replacement callbacks are required.

This is an intentional source compatibility break. Coding RPC remains a
Product transport projection and may keep its existing wire fields. TUI UI
namespace naming is a separate presentation-contract migration and is not
changed by this boundary.

## Verification

- Harness tests exercise a Product subclass through create, append, context,
  catalog/index, fork, rename, and runtime-binding disposal.
- Coding `SessionManager` and session/runtime tests exercise the same path
  through the Coding profile binding.
- Architecture tests require `ProductTranscriptSession` to have no Coding
  import and require `SessionManager` to adopt it.
