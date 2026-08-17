# Agent Transcript Interaction Runtime Boundary

## Decision

`loushang.harness.transcript` owns the standard interaction mechanics
over an already-open Agent transcript:

- selected-branch navigation and editor-text recovery for standard user and
  application input records;
- one cancellable branch-summary transaction, standard summary events, durable
  summary/label ordering, and transcript context replay;
- persisted model and thinking-selection mechanics, scoped-selection parsing,
  and deterministic cycling;
- transcript inspection: message counts, fork candidates, entry text, recent
  assistant text, compaction presence, and tree leaf count.

This is an optional Agent/AI profile. `harness.conversation` remains neutral;
it does not import Agent or AI types.

## Ownership

Harness provides:

```text
AgentTranscriptNavigationRuntime
AgentTranscriptSelectionRuntime
AgentTranscriptInspector
CancellationController / CancellationSignal
```

The navigation runtime operates on `AgentTranscriptSession`. It resolves the
selected record, performs leaf changes or appends a standard branch summary,
then invokes the injected context applier. A label remains an append-only
annotation record, so the active leaf may advance past the returned summary
record ID. Summary start/completion use the existing common runtime events.

The selection runtime stores only stable model selection snapshots and thinking
levels. It accepts a Product-supplied `ModelSelectionCatalog`; Harness neither
discovers providers nor resolves credentials.

The inspector is a read model. It has no TUI, RPC, JSON casing, storage-root,
or Product stats policy.

## Product Binding

A Product supplies:

- model catalog and model object construction;
- model/auth side effects and model-selection defaults;
- branch-summary prompt/profile, model selection, domain detail decoration, and
  error wording;
- extension before-hooks, cancellation policy, diagnostics, and Product events;
- context application to its Agent/runtime state;
- TUI, RPC, HTML, CLI, and Work projections.

Coding binds these ports directly in `AgentSession`; no Coding interaction
controller sits between the Product callback and the Harness runtime. Its
`before_session_tree` hook remains Coding-owned; hook results are normalized to
the standard `BranchSummaryOutput` before persistence.

Coding keeps model/auth resolution, summary prompt/profile selection, code
artifact decoration, extension semantics, diagnostics, and Product
presentation. The standard branch-summary model invocation, message
serialization, cancellation, and normalized output are Harness behavior.

## Dependency Rule

`harness.transcript` may import stable Agent message type aliases,
`loushang.ai.types`, and pure value objects in `loushang.ai.model`. Its
dedicated `summarization` module may additionally call the public
`loushang.ai` completion surface. It must not import Coding, model/provider
registries, authentication resolution, provider implementations, or Product
UI. `CancellationController` lives in neutral `harness.runtime` so branch
navigation does not acquire a dependency on the Agent loop.

## Verification

- Harness tests cover selection persistence, inspection, leaf navigation,
  summary commit ordering, and common events without importing Coding.
- Coding session tests preserve model selection, extension refresh, editor
  recovery, summary, and Pi-compatible read projections.
- Architecture tests forbid a Coding import from the interaction runtime and
  require `AgentSession` to bind the Harness owners directly.
