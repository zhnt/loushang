# Session And Model-Call Closure Boundary

## Status

Status: implemented PR8 boundary with the CLA2 Session-owned Graph authority
refinement. The acceptance matrix is enforced by the Session Model Input,
Agent-loop, transcript lineage, lifecycle, and architecture tests referenced
below.

The implementation uses the Session-scoped `harness.model_input` Definition,
Provider, and Consumer; Agent's per-sampling `prepare_model_call` seam; and AI's
existing prepared-request committer. Compaction and branch-summary v2 payloads
carry ordered `modelInputSnapshotIds`, while v1 payloads remain readable and
report `derivation_verifiable == False`. Durable custom streams must use
`prepared_request_conformant`; tests and simulations may make a visible
`synthetic_model_transport` opt-out.

This boundary defines how one current Product Session, its committed Capability
graph, its authoritative transcript, and every Harness-managed model call fit
together. It refines PR8 of the
[Capability Runtime Convergence Plan](capability-runtime-convergence-plan.md)
without introducing another Agent loop, provider runtime, transcript store, or
generic transaction framework.

## Authorities

The following authorities remain separate:

- `SessionTransitionHost` owns the single current-Session pointer and the
  irreversible release/publication order;
- the Session-owned `RuntimeCapabilityGraphRuntime` owns its committed Mount
  generation and registration inventory;
- the existing Agent transcript unit of work owns durable conversation facts;
- AI owns `PreparedModelRequest`, provider attempt identity, and the final
  pre-transport barrier; and
- `ModelInputTranscriptCommitter` projects one logical sampling input and the
  final provider payload into the authoritative transcript.

No combined mutable authority is added. In particular, a Model Input snapshot
references Profile, Mount, and registration clocks; it does not publish or
repair those clocks.

The Session composition root is the sole live graph owner. It creates one
`RuntimeCapabilityGraphRuntime`, one existing Binder, and one read-only
Projector for the Session runtime ID. It also owns the bind lock, captured
model-input Consumer, and final graph disposal. `SessionModelCallRuntime` is a
non-owning adapter: it receives one typed, idempotent Consumer-acquisition port
and the read-only Projector. It cannot plan, bind, dispose, or obtain the graph
runtime itself.

Both lifecycle `prepare_session` and the direct first-sampling path converge on
that same Consumer-acquisition port. Successful preparation installs one
captured facet lease; repeated preparation reuses it. Binding failure publishes
no Mount, and candidate Session disposal removes only the preparer installed by
that Session and closes its private graph.

## Session And Candidate-Graph Nesting

The current Session publication point remains the assignment performed by
`SessionTransitionHost.replace`. A candidate Capability graph is a private,
rollback-capable child of its candidate Session until that assignment.

The required order is:

```text
serialize Session operation
  -> construct candidate Session and candidate-private stores/registries
  -> plan and commit the candidate Capability graph privately
  -> run all veto-capable old-Session release callbacks
  -> clear the current-Session slot
  -> dispose the old Session and its graph
  -> publish the candidate Session pointer
  -> activate/rebind Product adapters
  -> run after-commit observers
```

The graph commit before Session publication is not a second public publication.
Candidate registrations must either target candidate-private registries or
remain staged; they must not change the current Session's effective surface.

Failure semantics are fixed as follows:

- candidate construction or graph binding failure disposes the complete
  candidate and leaves the old Session current and usable;
- a veto-capable before-release failure does the same;
- old-Session disposal failure leaves the current slot empty and rolls back the
  unpublished candidate, because the old Session may already be partly
  disposed and must not be republished;
- after the candidate pointer is published, activation, rebind, or after-commit
  failure is reported as post-publication degradation and never resurrects the
  old Session; and
- candidate rollback and Session shutdown join their owned graph,
  registration, retry, compaction, side-question, and watcher cleanup before
  reporting completion.

These rules preserve the existing transition evidence in
`tests/harness/runtime/test_transition.py::test_transition_host_does_not_publish_session_after_dispose_failure`
and
`tests/harness/runtime/test_session_operations.py::test_session_operation_reports_after_commit_without_rolling_back`.
They do not require a cross-Store transaction or rollback of an object after
its irreversible disposal has started.

Only the current Session may create a Model Input committer. The committer must
capture that Session's exact transcript leaf/revision and exact committed graph
and registration snapshots. A candidate graph cannot authorize model transport
before its Session is current.

## Per-Sampling Committer

One static committer cannot close an Agent run. A main turn may sample more
than once after Tool results, queued input, or retry, and each committed Model
Input advances the transcript revision. The Session composition therefore
provides a per-sampling factory or equivalent narrow adapter that:

1. runs after Agent context transformation and Tool projection;
2. captures the current transcript leaf and revision;
3. captures the current Profile fingerprint and committed Mount/registration
   references as separate facts;
4. assigns an explicit invocation purpose;
5. creates a fresh `ModelInputTranscriptCommitter` for the logical input; and
6. injects that committer into AI's existing `CallOptions` before calling the
   normal AI entrypoint.

AI still prepares the final provider payload, invokes the committer, checks
cancellation, and begins transport. Harness never reconstructs provider
payloads and AI never imports Harness.

The current Profile fingerprint is supplied explicitly by the Session
composition root at each sampling boundary. It is not inferred from
`MountGraphSnapshot.profile_fingerprint`: that Mount field records the Profile
fact used to assemble the committed Mount and may legitimately lag a later
turn-boundary Profile refresh. Mount and Registration must still reference the
same graph ID, runtime ID, and Mount generation or Model Input creation fails
before transcript write and transport. Diagnostics report Profile/Mount skew;
the writer never fabricates a replacement Mount generation to hide it.

One AI provider retry retains its `invocation_id` and increments
`PreparedModelRequest.attempt`; the same per-sampling committer records each
prepared attempt. After the AI retry loop terminates, the committer records one
separate hidden logical outcome linked to the complete ordered attempt sequence;
it never writes a terminal state back into a prepared snapshot. A Product-level
retry or a later Tool/queue continuation is a new logical sampling invocation
with a new committer and invocation ID.

## Model-Call Inventory

Every Harness-managed path must resolve to one of the following rows. The
table describes semantic invocations; several rows intentionally share the one
Agent-loop sampling site.

| ID | Path and evidence | Purpose | Required durable boundary |
| --- | --- | --- | --- |
| MC-01 | Main prompt through `src/loushang/agent/agent.py::_run_prompt_messages` and `src/loushang/agent/agent_loop.py::_collect_assistant_response` | `main` | The user/application prompt is committed before a fresh Model Input committer is created. |
| MC-02 | Tool continuation through `src/loushang/agent/agent_loop.py::_run_loop` and `src/loushang/harness/session/agent_event_router.py::AgentEventRouter.handle` | `tool_continuation` | Every Tool result `message_end` append completes before the next sampling factory reads the transcript. |
| MC-03 | Agent continuation, queued input, and Product retry through `src/loushang/agent/agent.py::_run_continuation` and `src/loushang/harness/transcript/retry_runtime.py::AgentTranscriptRetryRuntime.continue_retry` | `continuation` or `retry` | Committed queued input and retry state precede a new logical invocation; it is not an AI provider attempt of the previous invocation. |
| MC-04 | Manual, automatic, overflow, and split-turn compaction through `src/loushang/harness/transcript/summarization.py::execute_transcript_compaction` | `compaction_history` or `compaction_turn_prefix` | Each actual summary request gets its own committed Model Input before transport; a split turn may create two invocations. |
| MC-05 | Branch summary through `src/loushang/harness/transcript/summarization.py::execute_branch_summary` | `branch_summary` | The selected branch-delta facts and prompt are committed before transport and remain reachable after navigation. |
| MC-06 | Side question through `src/loushang/harness/session/side_question.py::AgentSideQuestionProvider.ask` | `side_question` | The child remains Tool-disabled and output-transient, but its inherited context, boundary prompt, and question are committed as hidden Model Input facts in the parent transcript before transport. |
| MC-07 | Injected `stream_fn` through `src/loushang/agent/agent_loop.py::_collect_assistant_response` | caller-declared | A durable Harness profile accepts only the standard AI entrypoint or a conformance-declared adapter that honors the injected prepared-request committer. Otherwise it fails before transport. Standalone Agent use may still inject an unconstrained stream without claiming durable closure. |

The only direct AI stream/complete imports below the Product layer remain the
standalone Agent defaults and the shared transcript summarizer. The architecture
gate inventories those source modules so a new direct entrypoint cannot bypass
this table silently.

## Commit-Before-Sample Invariants

For every durable Harness-managed invocation:

```text
logical facts committed
  -> logical context frozen
  -> provider payload prepared and frozen
  -> Model Input facts committed
  -> cancellation/deadline rechecked
  -> provider transport may begin
```

The following are invalid and fail closed:

- sampling a Tool result whose transcript append has not completed;
- using a Model Input committer after another writer changed its captured leaf
  or revision;
- capturing graph/registration snapshots from a non-current Session;
- sending through an adapter that cannot run AI's prepared-request barrier; or
- continuing transport after required durable commit failure, cancellation, or
  an unknown commit outcome that cannot be reconciled.

The current awaited event path is retained as the Tool-result ordering seam:
`tests/coding/test_agent_session_retry.py::test_agent_session_retry_preserves_queued_messages_until_retry_continues`
characterizes continuation ordering, while PR8 adds an explicit
Tool-result-commit failure regression before changing production wiring.

## Compaction Lineage

PR8 adds a new compaction lineage payload version rather than rewriting old
records. The new payload references the Model Input snapshot IDs for every
summary request used to produce the checkpoint or branch summary. Split-turn
compaction retains both ordered snapshot IDs.

Writers validate every non-empty v2 reference before committing the summary:
the snapshot must be uniquely reconstructable in the current transcript and
its purpose must match the compaction or branch-summary operation. A record
must not claim verifiable derivation merely because it contains a string ID.

Existing v1 compaction and branch-summary records remain readable and
resumable. They are reported as `derivation-unverifiable`; the reader must not
invent request lineage, rewrite them during load, or reject an otherwise valid
legacy Session.

## Concurrency And Failure Policy

- A per-transcript Model Input commit uses the existing revision/leaf
  precondition. A concurrent writer causes a conflict and zero transport for
  that attempt.
- Side questions and summary calls that race a main-turn transcript mutation
  fail closed and may be retried from a new source revision.
- An unknown Store outcome is reconciled only through the existing operation
  identity and authoritative reload behavior. PR8 does not add a second WAL.
- Provider retries may append more than one prepared snapshot for one logical
  invocation. Product retries always start a new logical invocation.
- Shutdown cancels new sampling, waits for owned commit/transport tasks to
  quiesce—including manual compaction, branch summary, and side question—and
  only then disposes graph/registration state needed by those tasks. Cleanup
  remains cancellation-atomic and continues after an owned Provider's cancel
  callback fails.

## Compatibility

- standalone AI and Agent calls without a committer remain supported and keep
  importing no Harness modules;
- direct callers of `ModelInputRuntimeReferences.from_snapshots` that omit the
  additive Profile argument retain the legacy Mount-profile default; every
  Harness-managed Product call supplies the current Profile explicitly;
- the lazy public model-call symbols remain importable, but their constructors
  no longer offer an owning-graph mode: Product composition must inject the
  typed Consumer-acquisition and read-only projection ports, because preserving
  the old ownership path would recreate the peer Graph authority CLA2 removes;
- synthetic Product tests may opt out of durable closure explicitly, but a
  durable Product profile may not silently downgrade because a custom stream
  was supplied; Agent checks the actual transport at every sampling boundary,
  and Session removes only its own preparation hook during disposal;
- legacy summary executors remain callable in non-durable Sessions, while a
  durable Session rejects an executor without the preparation seam during
  construction rather than failing halfway through a summary;
- current transcript and compaction wire versions remain readable;
- Product prompts, retry classification, model selection, compaction policy,
  and presentation remain Product-owned; and
- credentials, raw adapters, callbacks, and environment values never enter
  Model Input facts.

## Acceptance Matrix

PR8 is complete only when deterministic tests prove:

- all MC-01 through MC-07 paths either commit and reconstruct their Model Input
  or fail before transport;
- Tool-result append failure prevents the next model sample;
- provider retry attempts share invocation identity and each commit before its
  corresponding transport;
- Product retry, Tool continuation, and queued continuation use fresh logical
  invocation identities and source revisions;
- compaction-v2 lineage survives kill/restart, resume, fork, branch navigation,
  source deletion, and Extension unload;
- v1 compaction remains readable as derivation-unverifiable;
- concurrent revision conflict and unreconciled durable failure produce zero
  transport calls; and
- Session replacement/shutdown cannot expose a candidate graph early or leave
  an owned model-call task using disposed registrations.

CLA2 ownership evidence remains
`tests/harness/session/test_agent_product_contract.py::test_agent_product_sessions_keep_compaction_strategy_and_state_isolated`,
failure cleanup evidence remains
`tests/harness/session/test_agent_product_contract.py::test_failed_graph_preparation_is_disposed_without_leaving_agent_boundary`,
explicit current-Profile evidence remains
`tests/harness/session/test_agent_product_contract.py::test_product_model_input_reads_profile_after_turn_boundary_refresh`,
and the non-owning adapter gate remains
`tests/architecture/test_session_model_call_closure_contract.py::test_cla2_model_call_runtime_cannot_plan_bind_or_own_the_graph`.

Existing one-turn evidence remains
`tests/harness/transcript/test_model_input.py::test_main_agent_turn_rebuilds_after_restart_and_source_deletion`
and AI barrier evidence remains
`tests/ai/test_prepared_request.py::test_committer_failure_makes_zero_transport_calls`.

## Non-Goals

- no second Agent loop, provider retry runtime, transcript Store, or graph
  Projector;
- no generic distributed transaction or cross-Store rollback;
- no persistence of provider credentials or arbitrary runtime objects;
- no forced migration of v1 compaction records; and
- no PR9 explain/diff/DOT or multi-Product aggregation work.
