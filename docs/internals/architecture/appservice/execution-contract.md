# Optional Product Execution Contract

[AppService](README.md) · [Tracking #576](https://github.com/zhnt/loushang/issues/576)

## Status And Scope

- Authority: descriptive — source contract and deterministic verification record
- Design status: proposed for integration into the execution lifecycle service
- Implementation status: implemented opt-in values, Product port, invocation
  guard and composite snapshot validator; production composition not activated
- Owner: AppService contract and Product adapter owners

This increment makes one Product invocation independently identifiable and
waitable. It supplies reusable mechanisms and tests before introducing a new
submission service. Existing `HostedSessionPortV1`, `start_turn`, wire codecs,
client scopes and Coding composition retain their current contracts.

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

The fake Product and test application projection are verification fixtures.
They do not establish real Coding support, AppService ledger implementation,
durable execution recovery, native-platform acceptance or GUI delivery.

The next increment must bind explicit Product outcomes and quiescence into the
real adapter and build the application admission/ledger owner. Reserve maximum
lifecycle record capacity before acceptance; make duplicate lookup precede new
capacity checks. Then add versioned submission/query/interrupt methods, expected
service-instance fencing and negotiated client support on the stabilized shared
AppHost base. Keep old wait-until-complete and legacy interrupt semantics.
Message/tool entry IDs remain later work.

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
