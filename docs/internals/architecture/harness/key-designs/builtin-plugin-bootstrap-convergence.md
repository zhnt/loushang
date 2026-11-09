# Builtin Plugin Bootstrap Coordination

- Authority: bounded design and delivery record under COD-RESP-GOAL-002.
- Design status: accepted for reversible implementation by the implementation agent.
- Implementation status: implemented; bounded technical acceptance on 2026-11-09.
- Owner: Harness Package Product; Coding retains its product defaults and policy.
- Source checkpoint: `9a5285723`; method: local clean archmethod master
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`.

## Responsibility And Reuse

The complete builtin install, settled-handoff verification, temporary-runtime
disposal, enable and completion-recognition programs currently live in
`coding/package_product_runtime.py`. The execution and recognition paths repeat
the initial-install/first-enable history proof.

Place the complete coordination in the existing Harness Package Product
subsystem. Reuse its actual POSIX/Windows Product Session owners, factory,
runtime binding, lifecycle route, Desired ledger, Management service and handoff
reader. Add no manager, journal, transaction engine, cleanup task, registry or
phase callbacks. Shared history validation consumes already-read facts; it
does not read another snapshot or scan history again.

Coding retains the three builtin IDs and order, default enable/accepted-disabled
selection, fresh/legacy upgrade admission, ID namespaces and error policy.
Its existing private bootstrap and operation-ID functions remain thin entrypoints.
A frozen four-field policy carries product ID, install/runtime ID prefix,
enable ID prefix and diagnostic prefix. It performs no input admission or IO.
The existing public dataclasses and persistent schemas stay at their original
paths with their original fields and identities.

## Runtime And Compatibility Contract

Keep enabled early-return, removed tombstone refusal, explicit superseded
refusal and accepted-disabled behavior. Completion recognition checks the
first install/enable history even after an operator later disables the plugin;
only explicit disabled retry also requires the current package revision.

Preserve snapshot/transition/handoff read ordering, the single history scan in
completion recognition, random ID generation timing, exact ID bytes and
admission/owner-close boundaries. Factory acquisition stays outside the try;
unbound or bound runtime disposal remains in the original finally and happens
before the second snapshot and enable. Cleanup errors retain their original
exception-context precedence.

The actual registry stores `store_id` as an ordinary stable attribute. The
actual Product owner also stores `actor_id` as an ordinary stable field.
Passing these values into the complete operation/history proof reads them
earlier than the original private expressions. This is an explicit accepted boundary: arbitrary effectful
substitute getters, private helper hotpatching and complete reflection traces
are not promised. Existing bootstrap-entrypoint monkeypatch consumers remain
supported. No new runtime validation changes the accepted input set.

## Independent Design Review

Three separate read-only reviewers inspected the original full programs and
the concrete four-field-policy/real-owner design:

| Reviewer | Scope | Conclusion |
| --- | --- | --- |
| `/root/responsibility_review` | responsibility, existing reuse and complete old-body exit | reversible implementation accepted; share the history proof, avoid stage callbacks |
| `/root/runtime_review` | disposal, failure, retry and read ordering | reversible implementation accepted with original finally and one history scan |
| `/root/compatibility_review` | identities, records, short circuit and operator choices | reversible implementation accepted; preserve completed/retry distinction |

The implementation agent accepts this bounded contract within the existing
Package Product ownership direction. This does not adopt the separate pending
KD011 or Windows publication diagrams, nor accept any code before verification.

## Verification And Rollback

Before source changes, three complete original functions and their source hash
were frozen outside Product. Thirty-one controlled original observations plus
one existing repository case passed (32 total). The fixed observations retain
call traces, return values, exception graphs and real Desired DTO encodings;
Product effects are controlled, so these are not native-process evidence.

Compare the new complete operation against those read-only observations,
then run existing fresh/retry/operator-disable, accepted-disabled and affected
architecture tests. Preserve existing platform and host-runtime selectors.
Record actual costs and test limitations before code acceptance. Roll back the
whole two-program substitution and its internal module together; preserve
original namespaces and durable data, and do not retain a parallel runtime.

## Actual Code Review And Acceptance

The same three independent reviewers inspected both complete changed sources
against `9a5285723`, then separately reviewed the accurate V1/UpdateV2 history
annotation and the seven inherited architecture-fact corrections. All report
no remaining blocker in their reviewed scopes; none claims to have independently
rerun the Product regression. The implementation agent `/root` accepts this
bounded implementation after inspecting the final sources and JUnit results.

Actual Code is 1,996→1,820 lines (−176); the private receiving module is 240
lines, including the union annotation, policy, imports and both full programs.
System cost is +64 lines, not net system reduction. The other 31 top-level
Coding classes/functions have unchanged ASTs. Public dataclass identities,
entrypoints, schemas, admission and outer owner-close remain unchanged.

Validation: fixed before/after runs each passed 31 controlled observations and
one identical existing test; the durable local probe passed the same 31 cases
in 3.06s. The larger original selection passed 240, failed seven stale
architecture facts, skipped 43 under original selectors and deselected seven
(340.57s). All 51 Coding Product/hosted cases passed. Correcting the inherited
implementation locations and fixed consumer inventory made the same seven
failed nodes pass (28.47s); the passed 240 were not rerun or added as new unique
coverage. Original failure logs remain preserved.

Both source files pass mypy; changed Python passes Ruff and the new Core passes
format checking. Existing docs checks, generated-dependency freshness and diff
checks pass. The inherited complete change plan selected the existing offline
AI gate: `make check-ai` passed 937 with seven deselections and its original
coverage thresholds. CI routing/platforms and existing assertions' behavioral
coverage were not expanded. Local probes are explicit, not default PR coverage.

No native Windows, full-repository, exhaustive cancellation, ABI or performance
claim follows. The complete P1–P4 and Coding ≤15K Goal remains active.
