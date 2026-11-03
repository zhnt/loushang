# Issue 803: Incremental Model-Call Pipeline

## Status And Scope

- ID: `harness-kd-803`
- Authority: candidate key design
- Design status: proposed; no accepted contract is changed by this document
- Implementation status: incremental candidate path implemented on `perf/tool-exit-worked-803`;
  the 30-turn offline native-screen gate passed at 468.42ms p95 on
  2026-10-22; review remains open
- Owner / scope: Harness Session, Agent sampling, AI normalization and provider preparation, Model Input persistence, and TUI observation
- Method: local `archmethod` revision `0f9bd3f`
- Governing contracts: [Session And Model-Call Closure Boundary](session-model-call-closure-boundary.md) and [Model Input Persistence And Capacity Recovery](model-input-persistence-capacity-recovery.md)
- Measurements: [Issue 803 performance evidence](issue-803-tool-exit-worked-evidence-2026-10-21.md)

## Problem And Required Outcome

At design entry, an offline resumed Session with about 30,000 records and
1,680 model messages took roughly 1.8–2.3 seconds from tool exit to Worked.
During that interval Session certification, AI normalization, provider conversion,
prepared-request sealing, and Model Input publication traverse overlapping
parts of the same history. Moving individual traversals to worker threads
improves input response, but the work remains serial and competes for Python
execution time. A counterfactual probe that reused the provider's exact prior
message values reduced provider serialization to below 1ms, yet Worked still
took 1,918ms. Provider-only caching cannot establish the requested 500ms p95.

The target is a representative long-session tool-exit-to-Worked p95 below
500ms, with responsive keyboard input, exact rendering, and reconstructable
durable facts. Worked must continue to mean that the turn has actually
finished; changing its display point does not satisfy the target.

## Proposed Mechanism And Ownership

One per-sampling immutable logical source should be created after Agent context
transformation and the durable append of every Tool result. Session owns the
source, its transcript leaf/revision, and an exact certificate for the prefix
shared with the preceding sampling. It must never accept identity of a mutable
Agent message as proof by itself. The current bounded shape check is a safe
intermediate path; a later source may replace it only after writable aliases
are removed or every mutation is versioned.

AI should normalize from that owned source and retain a certified normalized
prefix. Pairing repair, normalized Tool IDs, cross-provider coercion, and
diagnostics must remain identical to full normalization. A simple concatenation
of prior output and new messages is insufficient: a trailing unmatched Tool
call, late Tool result, changed model, changed pairing mode, or changed Tool
schema can alter the meaning of the boundary. The cache therefore needs an
explicit transform frontier and carry state, or it must fall back to full
normalization.

Each built-in provider adapter may retain its own model-visible projection
frontier, keyed by the exact normalized source and relevant model/configuration
facts. An adapter defines where a prior output prefix becomes stable. For
example, a trailing Responses function call can acquire a Tool result later,
and a Chat Completions run of Tool results can acquire an aggregated image
message. Adapters with no proven frontier take the existing full conversion
path. AI owns the final `PreparedModelRequest`; Session does not construct
provider payloads.

`PreparedModelRequest` may accept exact prior owned, recursively frozen output
items by identity and build only the new suffix. It must still produce the
same canonical bytes, SHA-256 payload hash, capacity metrics, binary-field
inventory, and transport copy as the full path. Retaining a hash state at a
well-defined canonical append boundary is a separate optimization; a prior
final digest alone cannot prove the new digest. Model Input's v2 writer should
consume the same sealed values and publish only after the exact provider
attempt is available.

The TUI consumes Agent and transcript events while CPU projection runs away
from the input loop. It renders Worked after the terminal facts and Agent end
are settled. Background preparation has no permission to publish a snapshot
or start transport; the existing commit barrier remains the only publication
point.

## Critical Scenarios And Boundaries

1. **Tool continuation.** Persist Tool result and its authority first. Seal
   the post-transform context at that leaf, reuse only proven prefixes,
   prepare the exact provider attempt, durably commit Model Input, recheck
   cancellation, then allow transport. Independent prefix preparation may
   overlap Tool execution, but the final suffix and commit join at this order.
2. **Cancellation or failed worker.** Discard speculative projections. A worker
   that finishes after cancellation cannot publish or start transport. The
   current Session generation and transcript leaf are rechecked at commit.
3. **Mutation, branch, compaction, or configuration change.** A changed source
   item, unreachable ancestor, model/API/options change, changed Tool schema,
   or unknown adapter frontier invalidates the relevant cache. Resume starts
   from verified persisted facts; cache reconstruction may examine the tail
   after the latest compact boundary, but never executes historical Tools.
4. **Retry.** An AI provider retry keeps its invocation ID and gets a distinct
   prepared-attempt snapshot. A Product continuation gets a new committer and
   invocation ID. Prefix reuse cannot substitute one attempt's payload for
   another.
5. **Rendered completion.** Draft and committed lines retain their exact order
   and content. Input and Esc remain usable while the worker or durable writer
   runs. The UI must not report Worked while required facts remain unsettled.

## Trade-Offs And Evolution

This design adds ephemeral source certificates and adapter-specific frontiers
in exchange for removing repeated historical traversal. It keeps the accepted
durable record protocol, source authority, and commit-before-transport order.
It does not require stored cache state or a transcript rewrite. Generic SDK
calls and custom adapters keep their existing path until they explicitly
provide a correct frontier. A narrow OpenAI or synthetic adapter pilot should
establish the contract before extending it across providers.

## Verification And Open Questions

- Establish byte-identical normalized contexts, diagnostics, prepared payloads,
  hashes, metrics, binary fields, Model Input snapshots, and transport copies
  against the full path for append, repair, mutation, branch, compact, resume,
  model/configuration change, retry, and cancellation cases.
- Native reopen must verify snapshot lineage, terminal usage, exact Tool
  output, unchanged authority, and zero historical Tool executions.
- Measure at least 30 offline tool continuations on a fixed long-session
  fixture, including keyboard input; report p50/p95 and event-loop and echo
  delays. The candidate passed this gate in the native-screen runner: 30
  continuations, 434.04ms p50 and 468.42ms p95, with exact native reopening.
  Whole-turn GC pauses before Tool start remain outside this acceptance result.
- Determine whether immutable source creation can avoid the current full
  bounded-shape recheck without exposing writable aliases. Resolve provider
  frontier state and canonical hash reuse before claiming an incremental hot
  path. Cold resume cost, memory growth, and cache invalidation require bounds.

## Review And Acceptance

This is a candidate based on source inspection and issue-803 offline probes.
No owner has accepted a new cross-scope contract yet. Review must cover Agent,
Session, AI adapters, Model Input, and TUI together before changing the
accepted per-sampling and durable publication boundaries.
