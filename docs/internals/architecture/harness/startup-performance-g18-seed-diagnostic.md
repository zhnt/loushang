# G18 First Seed Startup Diagnostic

Status: design and implementation passed three-view review without P1/P2;
final scoped collector regression passed 490 tests with four platform skips.
The one approved diagnostic invocation completed; see its bounded result below.
Authority: [G18 plan](startup-performance-plan.md) and the failed
[checkpoint warm attempt](startup-performance-g18-linux-delivery.md).

## Question And Scope

The first `prepare:recovery-cwd` creator timed out before its first TUI frame.
The retained parent snapshot shows `ep_poll`, but does not describe the Hosted
child that the TUI is awaiting. The failed subject retains only an application
lock file. Neither fact identifies a root cause or establishes a deadlock.

Add one explicit `--seed-preparation-diagnostic` mode to the existing native
coordinator. It requires fixed-slot warm A/A and rejects checkpoint/resume,
explicit case selection and other correctness modes. It uses a fresh slot,
output, scratch and subject, the frozen A/A2/observer/wheel/requirements, and only
the existing `prepare:recovery-cwd` operation once. Successful preparation may
perform its original two seed-creation CLI workflows; there are no subsequent
warmups, restored recovery observations, full sampling or comparison. Preserve
all original installation/helper pins, seed validation and final checks.

The report has a distinct diagnostic scope and `comparison: not-evaluated`.
Do not import its timings or state into formal A/A or A/B. Success answers only
that this diagnostic invocation completed; it does not explain the old failure.
Failure retains the original error and evidence. No automatic retry is allowed.

## Failure-Only Evidence

Pass an observer-only CLI flag, never a new Product argument/environment value.
Only this mode records the observed TUI PID/starttime at terminal acquisition.
Ordinary collection does not perform this new pre-ready read or tree snapshot.

If the original operation fails, before the existing terminal owner cleans up,
best-effort read the pinned root and its currently linked descendants via Linux
`/proc/PID/task/TID/children`. Check PID/starttime and PPID relationships before
and after each process observation; mark raced or disappeared entries unusable.
Never signal, stop, attach to or assume ownership of a discovered process.

Bound the snapshot to eight processes, eight threads per process, 4 KiB per read,
256 KiB total payload and a one-second cooperative read budget. Read only
stat/status/wchan/schedstat/io and accessible kernel stack text; exclude argv,
environment, memory, file contents, Python locals and debugger interfaces.
Record permission failures, races, truncation and budget exhaustion explicitly;
do not wait or retry to complete a tree. `/proc` reads are not an atomic snapshot
or a hard real-time operation. Kernel stacks may be unavailable and do not reveal
Python coroutine chains. Accept this diagnostic limit rather than escalating.

The original 35-second ready predicate, 240-second preparation owner and physical
cleanup remain unchanged. Snapshot failures are secondary diagnostics and must
never replace the original exception or bypass owner cleanup. Unreadable identity
disables tree collection; it does not make a success fail or signal a target.

## Validation And Execution Boundary

Deterministic tests cover identity reuse/disappearance, descendant relationship
changes, per-process/thread/payload/time bounds, permission errors, no private
input reads, default-mode non-interference and original-exception preservation.
Coordinator tests prove one seed preparation, zero observations/comparator calls,
and rejection of incompatible modes or A/B inputs before Product execution.
Run scoped collector regressions and static checks, then three-view code review.

Only after review and an adequate capacity/resource check, execute one diagnostic
at `.artifacts/g18-linux-delivery/seed-startup-diagnostic-01`. No simultaneous
test/build/review workload from this task. Preserve all evidence and stop after
its terminal result. Do not change Product code, deadlines, fixture cleanup,
runtime lifecycle/dispatch or acceptance thresholds.

The implementation stays in the existing collector/probe and its scoped tests;
it adds no Product package, process owner or CI selection rule. Tests also cover
observer receipt publication failure preserving the original operation error.
The initial new fault-injection test failed because it injected at initial report
creation; its corrected test targets the failure-path final publication. The
25-case diagnostic subset then passed, and that test correction plus the explicit
Linux PTY skip condition passed read-only compatibility re-review.
The final unified result is retained as
`.artifacts/g18-linux-delivery/seed-diagnostic-regression-final.xml` (exit 0).
Changed-file Ruff checks and documentation invariants passed. This is scoped
collector verification; it does not claim a new full Coding/AppService gate run
or any installed/performance acceptance.

## Single Invocation Result

Tool commit `eaa082a4`; session **4403**, terminal **exit 0**. The preflight
recorded about 8.43 GiB free, no running task collector/test/scan, and two vmstat
intervals with 79%/89% idle and 16/0 KiB swap-in. These readings are descriptive,
not a proof of isolation or a causal comparison with the previous failure.
Resource receipt:
`.artifacts/g18-linux-delivery/resource-seed-startup-diagnostic-01.json`.

- Report: `.artifacts/g18-linux-delivery/seed-startup-diagnostic-01/report.json`;
  SHA-256 `fc9c7e5b2ea6f3a075c154c4fdb4864b646476d71e38d76f0d3342a183095af8`.
- Raw receipt: `/var/tmp/g18-recovery-pqxk3_a2/control/prepare-0.json`;
  SHA-256 `500b4c7db8f9dd99675983a3f384265ef06d904f3a9567426081aa5c7438939e`.
- Exactly one original seed preparation completed with two settled CLI workflows;
  their whole-workflow durations were 30.351051 and 13.103257 seconds. These are
  not individual ready latencies and must not be compared directly with the
  35-second ready deadline.
- Zero observations; comparator remains `not-evaluated`. The frozen A source is
  used on both sides; all 1,202 helper entries match before/after, final original
  installation checks completed, and the slot is idle/nonfailed. Recorded CLI
  PIDs 3098082 and 3098124 were absent at the post-exit check.
- No operation failed, so the failure-only tree snapshot was not triggered. The
  diagnostic does not provide missing Python/descendant stacks for the old run.

Parent `/var/tmp/lg18-tests-P7V9eO`, scratch
`/var/tmp/loushang-g18-native-tjanzrb3`, slot `g18-slot-abw48a8i` and seed artifacts
are retained. The prior failed report/slot are unchanged. This invocation did
not reproduce the timeout; it does not identify or fix its cause, accept native
stability or authorize automatic full A/A/A/B retries. A separately reviewed
measurement-condition decision is still needed before another formal attempt.
Independent read-only evidence audit verified both hashes, raw/report agreement,
zero seed restores and this non-reproduction classification; no P1/P2 remained.
