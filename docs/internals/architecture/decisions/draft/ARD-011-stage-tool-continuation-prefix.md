# ARD-011: Stage The Immutable Prefix Of A Tool Continuation

## Status

- ID: `ARD-011`
- Scope: Loushang (Agent, AI, Harness and Coding)
- Parent: Loushang
- Authority: candidate design; not an accepted execution contract
- Design status: draft
- Implementation status: not-started
- Owner: Loushang architecture
- Method revision: `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`

## Background And Drivers

The [Session model-call boundary](../../harness/session-model-call-closure-boundary.md)
requires a fresh logical input and final provider request for every sampling,
then a durable Model Input snapshot before transport. The Agent can run another
sampling after a tool result. That order is authoritative and remains required.

In a restored long Session, the ordinary post-tool path repeats historical
message conversion, provider preparation and Model Input graph materialization.
The [focused evidence](../../harness/issue-803-tool-exit-worked-evidence-2026-10-21.md)
measures 1.277 seconds p95 for a silent command and 1.36–1.72 seconds for four
other tool cases. Even a no-generation-two-collection shorter-history turn took
about 578ms: roughly 129ms before Session preparation, 72ms in that preparation,
49ms in adapter preparation, 162ms in durable input commit, 94ms in terminal
usage/outcome appends and 45ms in final presentation. These are diagnostic
intervals, not a proposed latency budget. The required target is p95 at most
250ms from actual tool exit to the matching visible Worked, with no early
Worked, missing durable facts or input freeze. The separate terminal-observation
contract question below does not relax this issue's acceptance target.

The two reconstructed ordinary continuations in the evidence have exact
append-only logical and prepared message prefixes. This is evidence of a
candidate fast path, not evidence that object identity proves equality: Agent
messages have mutable nested lists and mappings, and user conversion or
provider normalization can change historical output.

## Options

| Option | Fit | Cost and evidence |
| --- | --- | --- |
| Keep all preparation after the tool | Preserves Current semantics | Measured no-GC work alone exceeds 250ms. |
| Tune collection or copy only the blob projection | Leaves ownership unchanged | A five-pair copy-on-write experiment improved median but worsened Worked p95 from 1.10s to 1.64s; it was reverted. |
| Stage an immutable, provenance-checked prefix while the tool runs | Moves historical work before the measurement start and keeps final publication after the result | Requires a new cross-scope seam, explicit mutation and branch checks, adapter support, bounded memory and a fallback. |

## Candidate Decision

The recommended direction is an optional **Session-owned derivation cache** for
an in-flight tool continuation. It is not a new authority. The existing
transcript, current-Session predicate, Graph/Profile binding and AI prepared
request remain authoritative. A cache miss or failed guard uses the present
full preparation path; neither route may send transport before the final Model
Input snapshot is durable.

1. Once an assistant tool call is final and committed, Agent exposes a narrow
   tool-execution-start notification. Session may stage work from the current
   selected transcript and previous committed Model Input while the tool is
   running. Staging may allocate and compute but may not append a final Model
   Input snapshot, send a provider request or publish Worked.
2. The staged value is bound to the exact prior snapshot and source leaf/revision,
   selected record ancestry, current Session and graph/profile generation,
   model and adapter identity, converter identity, system prompt, tools,
   request options and resource evidence. It owns an immutable representation
   of the historical message prefix and any reusable provider/Model Input
   canonical fragments. Its lifetime ends on cancellation, branch selection,
   compaction, model or option change, Session replacement or failed proof.
3. At tool completion, Agent and Session must prove that the submitted context
   extends that sealed historical prefix without in-place changes. Record IDs
   and Python object identity alone are insufficient. A valid implementation
   needs either a versioned immutable committed-message view or an exact
   content check whose post-tool cost meets the latency budget. This proof is
   an open design finding; the fast path is disabled until it is resolved.
4. AI may offer an optional append-stable adapter capability for processing
   only new messages. AI remains independent of Agent and Harness. A custom
   converter, adapter without that capability, changed normalization result or
   non-append transformation falls back to ordinary preparation. No core
   behavior branches on provider ID or URL.
5. Harness may reuse only previously verified Model Input node references and
   canonical prefix state from the same selected ancestry. It processes the
   actual suffix, checks exact final logical/prepared hashes, and commits new
   nodes and the snapshot through the current unit of work. Current-Session,
   revision/leaf and cancellation checks run again at the final barrier.
6. The current Provider path awaits terminal attempt usage and model outcome
   recording before returning to the Agent, and therefore before Worked. Those
   recorder interfaces are optional and ordinary recording failures are traced
   without failing the model call. The recovery contract already represents a
   prepared attempt with no terminal outcome as `unknown` after a crash. Treat
   "terminal observations durable before Worked" as a separate candidate UI
   guarantee, not as a prerequisite for the next provider request. Issue #803
   still forbids moving these appends behind Worked to report an improved p95.
   A future change to that completion contract would need an owned, ordered
   writer, a flush boundary for the next transcript mutation and Session
   shutdown, and crash/reopen and cancellation evidence. It cannot merely
   detach unowned tasks or allow a later append to overtake the outcome.

The current 29,209-record diagnostic assigns about 106ms to the two terminal
appends and about 599ms to provider preparation plus Model Input commit after
Session preparation. Moving only terminal recording off the UI path would
therefore leave the long-session target far out of reach. Prefix staging and
incremental finalization remain necessary if this option is selected.

## Consequences And Validation

This direction trades memory held during a tool call and more explicit cache
invalidation for a shorter post-tool critical path. The staged value is
ephemeral, bounded to one in-flight continuation, and is never reconstructed
as authority after resume. Failed or late staging cannot block a correct
ordinary continuation. Custom streams retain the prepared-request conformance
barrier.

Before accepting this design, resolve the committed-message mutation proof and
the append-stability contract against Agent, AI and Session owners. A prototype
must compare exact logical/provider payloads and hashes with the ordinary path
under model/options changes, tool pairing, resource evidence, branches,
compaction, cancellation and adapter fallback. End-to-end acceptance uses real
PTY and offline transport on the original Session's isolated read-only copy:
five matched before/after pairs for each of silent, streaming, consecutive,
large ASCII and Unicode results, normal and cancelled turns, at multiple
history scales. Native reopening must verify snapshots, usage, outcome, output
hashes/truncation, drafts, exactly one Worked and zero historical tool replay.

A private feasibility check over restored messages found that comparing a
restricted, never-deserialized byte representation takes about 22ms for 1,474
messages and rejects an injected object with a custom reducer. It detects a
nested modification and a boolean-to-integer change. The representation must
still be tested against the actual in-flight Agent context, and its allowed
type closure must be specified. Per-message proof costs about as much as full
logical message serialization, so it is justified only if one proof allows
reuse of the larger AI and Model Input prefix computations.

## Review And Acceptance

Draft review by the implementation agent on `d3190fcd` found two blockers to
acceptance: a cheap exact mutation/provenance proof is not yet implemented, and
no staged prototype has demonstrated the end-to-end p95 target. The rejected
copy-on-write experiment also shows that lower allocation alone does not bound
GC pauses. The restricted byte check is preliminary evidence, not closure of
the mutation finding. This record remains a candidate until those findings
are closed; the existing Session model-call contract continues to govern
Product behavior.
