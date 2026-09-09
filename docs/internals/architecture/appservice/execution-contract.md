# Optional Product Execution Contract

[AppService](README.md) · [Tracking #576](https://github.com/zhnt/loushang/issues/576)

## Status And Scope

- Authority: descriptive — source contract and deterministic verification record
- Design status: proposed for integration into the execution lifecycle service
- Implementation status: implemented opt-in values, Product port, invocation
  guard, composite snapshot validator and real Coding adapter; default Product
  composition and submission protocol not activated
- Owner: AppService contract and Product adapter owners

This increment makes one Product invocation independently identifiable and
waitable. It supplies reusable mechanisms and tests before introducing a new
submission service. Existing `HostedSessionPortV1`, `start_turn`, wire codecs,
client scopes and Coding composition retain their current contracts.

`loushang.coding.hosted_execution.CodingHostedExecutionSessionV1` is the optional
real Product implementation. Its constructor takes exclusive ownership of one
`CodingRealHostedSessionV1`; an application selects it explicitly and supplies
the resulting port behind its existing authorization boundary. It must not also
install a second Hosted adapter or direct input driver on that same binding.
No installed CLI, public facade or default resolver selects this capability.

The source lives in `execution_contract.py`, `execution_ports.py`,
`execution_guard.py` and `execution_snapshot.py` under `loushang.appservice`.
These optional modules are absent from the default public facade. They depend
only on standard library code and existing AppServer protocol values.

## Ownership And Port

`HostedExecutionPortV1` is an explicitly injected capability on one owned
Product Session binding. The optional methods are:

| Operation | Contract |
| --- | --- |
| `start_execution(request)` | Retain the invocation synchronously before asynchronous effects; rejection has no admitted work |
| `wait_execution(id)` | Wait for that invocation's immutable Product outcome and completed cleanup; cancelling delivery leaves work owned |
| `interrupt_execution(id, mode)` | Check the exact current ID and apply the requested scope atomically |
| `retry_execution_settlement(id)` | Retry retained cleanup without running user input again |
| `snapshot_execution()` | Capture bounded Product content and its execution observation at one coherent cut |
| `subscribe_execution_content(listener)` | Reserve ordered, nonblocking content delivery before snapshot capture |

AppService will own authorization, identity allocation, admission, submission
deduplication, metadata publication and retained query records. The Product
owns the full call, its result, content cursor, child work and resource cleanup.
An execution ID grants no authority. This increment has no authorization or
deduplication service and must be used behind the owning application's checks.

All helper operations and callbacks use one owning event loop. A Product with
worker-thread events must marshal publication onto that loop. Its owner must
retain the guard and settle it before releasing Session resources; losing a
delivery waiter or closing a connection is not permission to drop ownership.
Effects created before `run` entry remain the adapter's responsibility.

## Full Invocation And Interruption

`ExecutionGuardV1` retains one active or most recent invocation on a binding.
It is not a history store: a waiter already joined to A retains A's result even
if B starts before delivery, but a new lookup of A after B replaces it requires
the future AppService ledger. The caller must allocate unique execution IDs;
the guard does not keep an unbounded set of previously used IDs.

`accepted` precedes Product entry. `running` covers commands, preflight, model
work and settlement, including calls that never create an Agent turn. Product
code returns an explicit `ExecutionOutcomeV1`; normal coroutine return or a
legacy `AckV1` does not establish success. A terminal outcome carries a separate
legacy response so an explicitly failed execution can preserve old Ack behavior.
Unexpected work exceptions map to a bounded failure code without raw details
and preserve a legacy failure response rather than creating an Ack.

`whole_execution` interrupts the entire call. Before its first step it skips
Product work; after entry it requests cancellation once. `legacy_turn_only`
invokes only the currently bound Agent-turn hook. It does not acquire a pending
whole-call interrupt during a command or preflight. A stale ID cannot stop B.

The Product's retryable `settle()` joins retained effects, including effects
that outlive cancellation of the coroutine awaiting them. Until it completes,
the slot stays occupied and source observation stays running. Cleanup failure
returns `CLEANUP_INCOMPLETE` and retains this debt; explicit retry never repeats
`run()`. Repeated interrupts do not cancel settlement. If Product work already
completed successfully before an interrupt arrives during cleanup, the actual
successful outcome remains authoritative.

## Composite Snapshot And Delivery

The immutable application view contains a private binding token, complete
Session identity, a binding-scoped metadata revision, active execution, latest
terminal summary and Q: the last quiescent Product observation. A Product source
snapshot carries the existing content cursor and a coherent observation.

Capture reserves subscriptions to both streams, then reads application E0,
awaits Product snapshot P, and reads application E1. Both application reads
validate current authority. Installation requires the same binding and Session,
an unchanged revision and the following matching rule:

| Application view | Required Product observation |
| --- | --- |
| Active B is running | Running B |
| Active B is accepted | Q, including completed A |
| No active execution | Q |

Latest terminal is a display summary, not a second simultaneous matching
condition. A pre-entry interruption leaves Q unchanged. Reopening a canonical
Session creates a new binding, initially idle Q and new cursor/revision domains;
retained history must not be inserted into this new view's baseline.

No application lock spans Product IO. Capture retries at most three times.
Lost authority or a replaced binding fails immediately. Delivery activates
synchronously after verification, dropping content through P's cursor and
metadata through E1's revision independently. Duplicate positions are ignored;
a gap, malformed stream or full mailbox invalidates the attachment and requires
a new snapshot. The caller unsubscribes a failed/retired buffer. Lifecycle
settlement must have a separate owner and cannot depend on delivery filtering.

The mailbox defaults to 256 entries and permits at most 1,024. Product snapshot
records retain existing V1 bounds; the draft has a 16,384-character bound and
replaces the client draft. The Product sets `truncated` whenever this bounded
projection omits content. The final transcript replaces an active draft. These
are bounded recovery views, not lossless replay or arbitrary transcript export.

## Verification And Integration Gate

Tests use controlled Events and explicit scheduling barriers, without timing
sleeps. Watchdog deadlines detect a stalled scenario rather than selecting the
execution order. Evidence is divided as follows:

| Evidence | Cases |
| --- | --- |
| `tests/appservice/test_execution_guard.py` | Pre-entry/full-call/legacy interruption, no-model success, explicit failure, cleanup ownership and retry, uncancellable child effects, cancelled waiters, A/B result-delivery race, immediate retry failure, task construction rejection |
| `tests/appservice/test_execution_snapshot.py` | A/B matching, source/application completion race, service-only outcome, binding reopen/replacement, authority loss, bounded recovery, independent cursors, duplicates, gaps, overflow and bounded retries |
| `tests/appservice/test_execution_port_conformance.py` | Asynchronous fake Product implementing the optional port, command and model calls through the real guard and snapshot validator, reconnect projection and interruption through cleanup |
| `tests/coding/test_hosted_execution.py` | Real Coding Session and canonical factory, literal input compatibility, extension/model failure, full/legacy interruption, retry identity, cancelled waiters/close, preparation retirement, retained tool-thread effects, final cleanup events, bounded snapshots and persistent Session reopen |
| `tests/harness/runtime/test_retry.py` | Retained continuation cleanup after the legacy retry waiter resets; settlement must not cancel that cleanup a second time |

The fake Product and test application projection remain mechanism fixtures.
Real Coding verification is separately recorded below. Neither establishes an
AppService ledger, durable execution recovery, native-platform acceptance or
GUI delivery.

The next integration increment must build the application admission/ledger
owner over the optional real adapter. Reserve maximum
lifecycle record capacity before acceptance; make duplicate lookup precede new
capacity checks. Then add versioned submission/query/interrupt methods, expected
service-instance fencing and negotiated client support on the stabilized shared
AppHost base. Keep old wait-until-complete and legacy interrupt semantics.
Message/tool entry IDs remain later work.

## Real Coding Adapter

The opt-in adapter inherits the legacy Hosted Session surface and owns one
execution guard. Its `start_turn` submits a private invocation and waits for
its result; the original default adapter continues to use its existing prompt
operation. New and old interruption on the optional binding both check the
same guard; turn-only interruption tests the current Agent without setting a
pending command/preparation interrupt.

Coding reads explicit input disposition through the existing Harness prompt
pipeline. A per-call controller copy observes command dispatch and preflight;
it does not mutate shared callbacks or reimplement input ordering. Extension
command dispatch retains a bounded failure code independently of its legacy
result. Agent outcomes come from the actual last assistant result, including
normal-return failures and interruption. Successful automatic retries replace
the failed attempt's result while retaining one execution ID. Accepted input
handled without an Agent run can succeed independently of model output.

Whole-call interruption is checked again before entering subsequent work
phases, so a preparation owner that consumes coroutine cancellation cannot
accidentally start a model call. Retry continuations and deferred Agent runs
are retained and joined beyond the legacy idle observation. Cancellation already
delivered to a continuation is not repeated during settlement. Final settlement
drains ordered Session projections after the last owner cleanup, including events
scheduled by that cleanup. Product/tool owners remain responsible
for joining their own effects, including threads and processes that outlive a
cancelled await; the adapter never infers such settlement from task cancellation.

Failed preparation retires the binding. Its staged runtime cleanup uses the
existing retryable Product cleanup path; a failed cleanup leaves the execution
running and rejects new input. Retrying settlement performs no prompt replay.
The binding must be closed even after that cleanup eventually succeeds.

Closing the optional adapter rejects new input immediately, interrupts active
work, joins or retries settlement, then closes the real binding. Cancellation of
a close waiter leaves the retained close task owned. An interrupt received after
successful work entered cleanup preserves the actual successful outcome.

Snapshots cache content at the synchronous Product projection boundary and
capture execution observation without yielding. Terminal publication refreshes
the final content after settlement. Drafts are replacements, capped at 16,384
characters, and cleared by final messages. Both truncated deltas and omitted
transcript records propagate an explicit omission flag. Reopening a persisted
Session retains its conversation but starts a fresh execution observation and
cursor domain; execution-history persistence remains an AppService concern.

The two optional Coding modules have a combined 400-line ceiling and a
250-line per-module ceiling. The legacy G11 adapter allowance increases from
400 to 420 lines for bounded omission metadata and one synchronous projection
observation seam. Default import/activation assertions and the unchanged wire
schema constrain that shared addition. The AppHost/AppService test inventories
include the new real Product tests and implementation modules.

## Local Verification Record — 2026-09-08

Source base: `7c41cd57`, isolated branch `appservice/execution-contract-576`.
The optional contract and deterministic verification are complete locally.
Overall AppHost/native integration acceptance remains open.

- Before implementation, the focused existing AppService/Coding adapter/G11
  baseline passed 97 tests.
- Final execution scenarios and the optional-module boundary passed 29 tests.
  Regression-first cases exposed and fixed lost A-result delivery after B
  starts, lost cleanup debt on an immediately failed retry, and an unexpected
  work exception incorrectly returning a legacy Ack.
- Real Product creation plus the updated architecture inventory passed 11
  focused tests. AppHost/AppService Ruff and mypy checks passed; the final four
  execution modules also passed their checks after the exception-response fix.
- `check-hosting` passed: 384 tests, 48 platform skips. Documentation invariants,
  package dependency graph and whitespace checks passed.
- AppHost/AppService regression work was split across the shared inventory and
  its remaining cases. The final remaining-case run passed 132 tests and failed
  the G10 ephemeral canary. G8/G9 evidence passed (19 and 16 tests). Interrupted
  full runs and failed attempts are retained locally and are not full-gate passes.

The remaining failure is
`test_native_canary_leaves_user_session_roots_untouched[G10-EPHEMERAL-NO-SESSION-IO]`,
with `coding_apphost_canary_timeout`. A control run on unmodified main Product
source in the same interpreter/dependency environment passed; restoring this
branch and running the complete G10 evidence selection still failed that case
(14 passed, one failed). Its cause is unresolved. A separate direct child import
diagnostic took 4.35 seconds, close to the existing five-second canary budget,
and loaded no new execution modules. This suggests startup-margin investigation,
not a proven causal explanation or permission to relax the timeout.

Initial validation-environment faults (missing installed entrypoints, duplicate
project installation evidence and an unintended global CLI lookup) were fixed.
The environment now installs this branch separately while reusing dependency
files. Test runs use `not live` and `--skip-host-runtime` outside the managed
sandbox. The change-aware plan still requires host-runtime/platform evidence in
Actions. New Product activation, wire/GUI integration and full native acceptance
must not be inferred from this increment's deterministic results.

Local logs and XML reports are retained under `.artifacts/` with the
`execution-contract-` prefix in the task worktree; they are not packaged runtime
artifacts. The shared AppHost gate must be resolved before integration promotion.

## Real Product Verification — 2026-09-09

Source base: `0c58b02b`, incorporating G17 `9bc69361`. This increment explicitly
constructs the real optional adapter; it does not activate the default Product,
add a submission ledger, or change the wire protocol.

- The existing focused baseline passed 241 tests before implementation.
- The focused Product/command/Host/retry/PromptController selection passed
  78 tests, including 20 real execution scenarios. Regression-first cases exposed
  cancellation swallowed during preparation, terminal publication before cleanup
  events were delivered, and repeated cancellation interrupting retry cleanup.
- A subsequent regression exposed swallowed compaction cancellation entering
  the next extension phase. The phase checkpoint fix passed its regression and
  the literal-input compatibility case; interruption during an old asynchronous
  event subscriber also passed, including the following execution.
- The canonical factory scenario also passed in isolation after an earlier run
  timed out while other tests were running. The watchdog remains unchanged; that
  earlier timeout is not treated as proof of an environmental cause.
- The change-aware plan selected all local scopes because the shared Makefile
  inventories changed. Documentation invariants and the generated dependency
  graph passed. AI checks passed lint, typing, catalog/import checks, 61 offline
  example tests and 849 regression tests (2 skipped, 7 deselected), but failed
  coverage: 89.66% total and 89.35% runtime core against the existing 90% limits.
  AI implementation, its tests, coverage scripts and dependency manifests are
  unchanged from this increment's source base. The two excluded cases carry the
  Host Runtime marker and exercise local OAuth callbacks. This result describes
  the selected offline subset, not the complete gate or proof of a baseline
  coverage defect. The existing coverage limits and safety selectors are kept.
- AppHost, AppService, Hosting and HarnessTUI static checks passed. Harness
  Ruff and mypy passed (682 source files); the final prompt-compaction helper
  also passed its focused type check. The additional optional adapter is an
  explicit AppServer consumer in the A0.4 architecture inventory; the corrected
  inventory passed all six tests.
- The Coding Session/AppHost/legacy Hosted/CLI batch passed 624 tests (two
  deselected). Its G10 ephemeral canary passed in 4.106 seconds under the
  original budget. This is an additional passing execution-branch result,
  not an explanation of the earlier cross-worktree timing discrepancy.
- All 22 real execution scenarios passed together in the broader Coding batch.
  That batch also exposed two test-environment defects: the task's editable
  install predated G17's new console entrypoint, and temporary nested pytest
  probes inherited a custom option without loading its defining conftest.
  The editable install was refreshed offline without changing dependencies.
  The parent retains explicit `--skip-host-runtime` and marker filters; inherited
  `PYTEST_ADDOPTS` now contains only the standard `not live` selector. Original
  failures and targeted rechecks are retained separately. The two affected G17
  files subsequently passed all 14 tests, including real terminal history
  recovery, startup cancellation, forced exit and process reclamation.

- The final selection requested 936 test files in 85 batches, retaining
  `not live`, `not requires_host_runtime`, the terminal/platform marker
  exclusions and explicit `--skip-host-runtime`. It also includes local native
  cases which the repository leaves in that selection; it is not wheel or
  cross-platform acceptance. After the explicit rechecks below, the combined
  unique-case result is **11,051 passed, 147 skipped, zero unresolved failures**.
  The separate CI unittest selection passed all 41 tests.
- A late `/tmp` quota failure prevented C fixture compilation in 18 Hosting
  cases and four Harness native worker cases. The affected Hosting file passed
  all 22 tests, and the four worker cases passed separately, with only compiler
  `TMPDIR` redirected to a task-owned directory on the workspace filesystem.
  No Product implementation, timeout or capability selector was changed for
  these environment failures. The G10 canary and large-journal load budget both
  passed in the final batched selection under their original budgets.

The first combined Harness run was terminated without a complete result after
heavy memory swapping and a transcript-load timing failure. It is not a gate
pass. Its complete offline inventory is included in a fresh run partitioned by
test file, with each architecture file in a separate process. Per-batch XML
retains both successful and failed attempts.

Serial controls used a clean G17 worktree and this execution worktree, each with
its own editable installation and Python 3.11.15 environment backed by the same
dependency versions. G17 failed both the G10 ephemeral canary and the large
transcript-load budget in two runs; this execution branch passed both in the
intervening run. G17's measured load rates were 0.41 and 0.49 seconds/MB against
the unchanged 0.35 budget; its G10 canary hit the unchanged five-second timeout.
The execution branch's G10 case took 3.86 seconds. The loading implementation and
test have no delta from G17. These results do not establish an execution-induced
performance regression or resolve the earlier timing discrepancy. They do not
replace platform acceptance or justify relaxing the existing budgets.

Raw independent scope results are recorded in the task worktree under
`.artifacts/execution-product-scopes/`; focused logs and XML use the
`execution-product-` prefix. The original batches contain 33 failures: one
architecture inventory omission, ten G17 test-environment failures and 22
compiler quota failures. `execution-product-final-results.json` records every
recheck's case identity and original batch; `execution-product-final.xml` contains
the resolved unique-case results. Raw failures are retained rather than rewritten
as successful initial runs.

This completes the optional real Product increment and its selected local
regressions. It does not make the full change-aware gate green: the AI coverage
result above, complete installation/platform acceptance and the unresolved G10
cross-worktree timing discrepancy still require their own evidence before
integration promotion. The temporary clean G17 comparison worktree was removed
after its evidence was retained; the execution delivery branch remains local.
