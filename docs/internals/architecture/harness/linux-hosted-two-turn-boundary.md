# Linux Hosted two-turn boundary closure

Status: Linux diagnostic baseline complete; Windows acceptance pending.

Baseline: `b6899914`; task branch `harness/linux-hosted-two-turn-boundary`.
This work does not authorize merging the blocked promotion PR #586.

## Objective and evidence

Explain when a second Hosted submission may enter, prove the boundary with
deterministic tests, and provide bounded diagnostics that can be reused for
Windows validation. A successful rerun is not a root-cause explanation.

The G16 synthetic model emits `waiting` only if its last input message is a
user message whose complete text is exactly `hold`. Windows evidence has shown
both `operation_unavailable` and an ordinary synthetic reply after the second
submission. Waiting for a rendered idle member did not eliminate the latter.
These observations do not yet prove an input, context, or runtime defect.

## Required delivery

| Requirement | Acceptance evidence |
| --- | --- |
| Private test environment | Separate workspace, user/platform/session/scratch roots; no ambient credentials |
| Correlated bounded observations | Request receipt/result, model input shape, reply, run/settlement and projection records; no protocol stdout writes |
| Direct Product path | Legacy and opt-in execution ownership distinguished; two real turns with synthetic model IO |
| AppService/IPC path | Same input crosses real framing and admission; reply/ACK/failure correlated |
| Linux PTY path | Real input/rendering path, cwd and user_home, followed by crash recovery |
| Deterministic interleavings | Event barriers around reply and settlement; no timing sleeps as synchronization |
| Evidence-led repair | Fix only the demonstrated owner; preserve legacy semantics and required gates |
| Repeatability and handoff | Fixed commands, baseline and result counts; reusable Windows procedure and explicit pending status |

Do not equate a text delta, a TURN_COMPLETED event, an idle UI projection, RPC
completion, or execution-slot release without checking their actual owners.
The existing G16 composition uses the legacy path by default; testing only
ExecutionGuardV1 would not establish the failing path's behavior.

## Sequence

1. Freeze input observations and establish direct-Product barrier tests.
2. Add framed IPC and Linux PTY evidence using the same synthetic controls.
3. Reproduce the disagreement, repair the demonstrated boundary and freeze
   Linux verification plus a Windows handoff. Keep main promotion blocked
   until its separate platform acceptance is satisfied.

Run pytest outside the managed sandbox, with scratch on the main filesystem
outside any Git checkout. Do not delete earlier G18 artifacts. Restrict local
checks to changed contracts and their affected paths; do not rerun unrelated
provider or whole-repository suites for ordinary test-only changes.

## Observed boundary, not a Windows root-cause claim

The deterministic direct and scoped-service cases establish the following:

| Observation | What it proves | What it does not prove |
| --- | --- | --- |
| Assistant delta received | The model has produced visible text | Producer termination, cleanup, or admission availability |
| `TURN_COMPLETED` delivered to an observer | The Agent end event was projected | The remaining event listeners, Product invocation and retained operation have settled |
| Legacy `start_turn` successfully returns | That invocation has returned through its service owner | The client has drained the separate event mailbox |
| Opt-in execution successfully returns | Its guarded settlement completed | That the legacy G16 composition uses ExecutionGuard |
| Idle rendered on a terminal | The client consumed an idle projection | That its outstanding start RPC has returned |

`test_completed_projection_does_not_release_service_admission` holds the
completion listener with an Event. While it is held, the first request is still
pending and a second request is rejected with `operation_unavailable` on both
legacy and opt-in paths. Releasing it and awaiting the first call allows the
second exact input through. This is expected admission protection, not evidence
that the guard should be weakened or that a fixed sleep is an adequate fence.

In the private Linux IPC and PTY runs, the second model input is a user message
with exactly four characters, digest matching `hold`. The projected reply is
`waiting`. After interrupt, another input executes; after process death,
identities and history survive but the parked execution does not. The ordinary
reply reported on Windows has **not** been reproduced or explained here.
No production semantic change is justified by that missing evidence.

## Diagnostic contract

`tests/coding/_hosted_boundary_trace.py` is an optional test-child observer, not
a public logging API. `LOUSHANG_TEST_BOUNDARY_TRACE` names a caller-created
private directory. Each child exclusively creates one file, mode 0600 on POSIX,
with at most 256 records of at most 2048 bytes each (512 KiB per child). Default
test execution creates no trace. No observation is sent on protocol stdout.
The private test root supplies HOME, USERPROFILE, platform, runtime and scratch
locations and excludes ambient provider credentials and source overrides.

Records contain local request IDs, process-local sequence numbers, monotonic
timestamps, session IDs, phase names, input/reply length and SHA-256, bounded
message-role tails and exact/stripped-hold flags. Prompts, full contexts and
exception messages are not recorded. Digests remain private test evidence, not
an anonymization promise. Never enable this fixture against real user input.
Acceptance rejects saturated traces and discontinuous per-file sequences;
bounded retention must not make a missing completion record look conclusive.

Correlate `rpc_received -> slot_admitted -> product_entered -> model_input ->
projection -> agent_run_released -> product_returned -> slot_released ->
rpc_returned` within one scoped-service
request. G14 stdio uses the legacy unscoped service and does not have the G16
retained-operation slot. A process killed during `hold` must not claim Product
return or slot release. Graceful interrupted producers record settlement;
graceful Session closure records entry and return. File observation adds IO
overhead, so uninstrumented regressions must also pass. Do not compare clocks
from different processes to infer global ordering.

The `rpc_received` / `rpc_returned` phase names observe the decoded service
handler's entry and return, not receipt of its encoded response by the client.
Actual response delivery is established separately by the IPC test awaiting
`controller.submit()`. Do not use a server-side trace record as a client ACK.

## Linux verification and Windows handoff

Linux x86_64 / CPython 3.11.15 evidence on the task branch:

| Run | Coverage | Result |
| --- | --- | --- |
| `boundary-run-1.xml` | Initial boundary cases plus 23 existing real execution cleanup regressions | 34 passed |
| `boundary-run-2.xml` | Final observer safety, direct Product/scoped-service barriers, framed IPC and PTY cases | 12 passed, no skips |
| `boundary-run-3.xml` | Independent repetition of the same final 12 cases | 12 passed, no skips |

Both final runs cover cwd and user_home. Their four pre-crash child traces also
independently establish that the first slot release (local sequence 19) precedes
the second slot admission (sequence 22); both records belong to the same PID.
Module-origin checks with Python isolated mode resolve Coding and AppService
from this worktree, not the control lane or an ambient source path.

Reports and retained per-test traces are under the private local evidence root
`/var/tmp/loushang-two-turn.IX0Ycx`. The final XML SHA-256 values are:

- Run 2: `6ef6faa119c3e18119b8c69fea9f11ea20c09b384b860c401e218596ecd4bcb6`.
- Run 3: `55a0d7aef6f09cb780738e004e22e46c54d875267df33a391ca4fa479b339022`.

These are behavior/repeatability results, not startup or throughput measurements.
Completed change-aware local gates:

| Gate | Result |
| --- | --- |
| Coding offline gate | 2,519 passed / 21 skipped / 20 deselected |
| AppHost | Ruff and mypy passed (99 source files); 1,373 passed / 12 skipped; G8/G9/G10 evidence and installed G10 canary passed |
| AppService | Ruff and mypy passed (86 source files); 1,707 passed / 15 skipped |

The replacement change-aware run exited successfully (code 0). Separate
`host_runtime` checks remain selected for Actions by the shared gate planner;
they and native Windows acceptance are not claimed by this offline Linux
delivery. The final changed-file Ruff and documentation checks passed as well.

Disposition: close the independent Linux diagnostic scope with deterministic
admission regressions, real framed/terminal evidence and the bounded observer.
No Linux input-corruption defect was demonstrated, so production execution
semantics remain unchanged. The Windows ordinary-reply anomaly remains open;
the frozen probes make its next reproduction attributable to a specific boundary.

The first change-aware run was deliberately interrupted, not failed by an
assertion: 1,396 passed / 11 skipped / 20 deselected before interruption. Its
wrapper had selected the 164 MiB XDG runtime tmpfs, which had only 37 MiB left.
The exact pytest process exited and its lease reclaimed its scratch directory.
That incomplete run is not gate acceptance. The replacement explicitly pins
runtime and temporary roots to the main filesystem; setting only `TMPDIR` is
insufficient when `XDG_RUNTIME_DIR` is present:

```sh
boundary_root=$(mktemp -d /var/tmp/loushang-two-turn-gates.XXXXXX) || exit
TMPDIR="$boundary_root" \
LOUSHANG_RUNTIME_DIR="$boundary_root/gate-runtime" \
LOUSHANG_TMPDIR="$boundary_root/gate-scratch" \
UV_NO_SYNC=1 uv run --no-sync python scripts/ci/check_changed.py --base b6899914
```

This is the shared `check-changed` implementation with the independent branch
baseline supplied explicitly; it does not replay the already delivered G18
changes relative to an older `origin/main`.

Run from this branch's installed editable development environment. Use a newly
created task-owned directory on the main filesystem, outside the checkout:

```sh
boundary_root=$(mktemp -d /var/tmp/loushang-two-turn.XXXXXX) || exit
TMPDIR="$boundary_root" UV_NO_SYNC=1 uv run --no-sync pytest \
  tests/coding/test_hosted_boundary_trace.py \
  tests/coding/test_hosted_two_turn_boundary.py \
  tests/coding/test_hosted_boundary_process.py \
  tests/coding/test_hosted_execution.py \
  -q -o tmp_path_retention_count=3 -o tmp_path_retention_policy=all \
  --junitxml="$boundary_root/boundary.xml"
```

Retaining pytest temp roots is explicit: repository defaults remove them even
after failures. Diagnostics are under each case's `boundary-trace` directory.
Keep only the small task-owned evidence roots needed for the handoff; do not
delete unrelated G18 artifacts. Repeat the focused process file after changes
or as the named repeatability experiment, not as an unbounded stress loop.

On Windows, use the same source baseline and installed environment with the
native terminal dependency, create a private directory outside the checkout,
set `TEMP` and `TMP` to it, and run the same four test files and pytest retention
options. For example, in a fresh PowerShell session after installing the dev
environment for that baseline:

```powershell
$boundaryRoot = Join-Path ([IO.Path]::GetTempPath()) ("loushang-two-turn-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $boundaryRoot | Out-Null
$env:TEMP = $boundaryRoot
$env:TMP = $boundaryRoot
uv run --no-sync pytest `
  tests/coding/test_hosted_boundary_trace.py `
  tests/coding/test_hosted_two_turn_boundary.py `
  tests/coding/test_hosted_boundary_process.py `
  tests/coding/test_hosted_execution.py `
  -q -o tmp_path_retention_count=3 -o tmp_path_retention_policy=all `
  --junitxml="$boundaryRoot/boundary.xml"
```

POSIX mode/no-follow assertions are platform-specific; the IPC and
terminal scenarios themselves are not skipped on Windows. Preserve the XML,
per-child traces and terminal failure output. In particular inspect:

1. Did `rpc_received.input` match the intended second input?
2. Did the matching `model_input.latest_role/latest` retain that input?
3. Did the response projection carry `waiting`, and did the terminal see it?
4. Was an earlier request still awaiting Product/slot/RPC completion?

The result determines whether to investigate terminal input, model-context
construction, reply delivery, or admission. A missing record is not proof of
completion. PR #586 remains outside this Linux delivery's merge authority and
must not be presented as cross-platform accepted on the strength of these runs.
