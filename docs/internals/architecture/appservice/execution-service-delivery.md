# Execution Service Delivery — #576

## Status and scope

- Design status: accepted for this implementation, by the 2026-09-09 request
  to complete the three execution increments.
- Implementation status: implemented in the task branch. Local offline
  verification is complete with the limits recorded below. Default activation
  and native GUI acceptance are separate.
- Tracking: #576. The existing [Product execution contract](execution-contract.md)
  remains the source of Product settlement and snapshot requirements.
- Baseline: Product implementation `99676cd0`, synchronized with committed
  control-lane `main` at `becd4eb2`. Other lanes' uncommitted work is preserved.

## Increments

1. Product lifecycle notification and AppService registration. Product publishes
   source entry synchronously before commands, preflight or model work. A silent
   command enters running without a content event. The AppService registry owns
   application-instance-local submission digests and bounded execution records.
2. Lifecycle and recovery. Execution capacity is separate from communication
   Tasks. Only Product outcome plus completed settlement releases it. Member
   close and application stop interrupt whole executions and join cleanup;
   disconnect only fences authority and drops delivery. Reopened bindings start
   with a fresh projection; canonical submission history remains queryable under
   renewed authority. Legacy start waits for completion and shares the slot,
   without charging the submission ledger; legacy interrupt remains turn-only.
3. Optional versioned protocol and recovery client. Explicit capability admission,
   stable service-instance identity, strict codecs, lost-response recovery and
   bounded composite snapshot/event delivery. The native GUI handoff retains
   the existing Windows/macOS development arrangement; Linux delivers the
   protocol/client contract and reproducible handoff scenarios first.

## Capacity and lifetime

The first delivery retains submission keys until the registry instance ends;
there is no deduplication TTL or restart replay guarantee. New submissions fail
when the count or byte budget is exhausted. Exact duplicate requests are checked
before capacity and return the current record; changed text conflicts. An
instance mismatch fails before ledger lookup or admission. IDs grant no rights.

Each submitted record reserves 8192 bytes of bounded record/index payload for
its entire lifecycle before acceptance. Terminal publication requests no new
ledger capacity. This is a logical payload reservation, not a claim about exact
Python allocator overhead; object counts are also bounded. Active input is
separately bounded by the Product text limit and active invocation limit.
Legacy terminal summaries use a bounded count/age cache and never consume or
evict permanent submission keys. Cleanup debt retains its active slot.

## Verification

All pytest runs use the task's independently installed Python 3.11.15 virtual
environment outside the managed sandbox, with `not live` and
`--skip-host-runtime`. Existing timeout budgets are unchanged. Counts below
describe separate runs and overlap; they must not be summed as unique tests.

The resolved view contains **3987 passed and 81 skipped unique test identities**,
with no remaining failures after the recorded fixes/rechecks. It uses each
test identity's latest completed report, excluding the comparison baseline and
interrupted supplemental report. This is a reconciled result, not a claim that
every raw gate run passed. The machine-readable mapping is retained as
`.artifacts/execution-service-verification-summary.json`.

- Full AppService suite plus real Coding execution adapter: 161 passed.
- Protocol, authenticated local reconnect, recovery and service integration:
  95 passed (`execution-service-integration.xml`).
- Final settlement, observer cancellation, snapshot and architecture recheck:
  70 passed (`execution-service-settlement-recheck.xml`). The subsequent
  lookup-time instance-change client check passed all 7 recovery tests
  (`execution-service-recovery-final.xml`).
- Member removal and first application stop after prior cleanup failure:
  57 passed (`execution-service-stop-recheck.xml`).
  Final registry/service checks, including a driver cancelled before Product
  entry, passed all 19 tests (`execution-service-registry-final.xml`).
- Full `check-appservice` raw run: 1190 passed, 11 skipped, 3 failed
  (`execution-service-gate.xml`). Two architecture failures were corrected:
  the optional foreground import is now checked for explicit selection, and
  the recovery record merge no longer trips a native IO substring guard.
  Both passed in the 70-test recheck. The remaining G17 terminal case timed
  out twice in startup, then passed under sequential comparison with the
  pre-development `5625a1f1` baseline. Baseline: 1 passed in 118.70 seconds;
  execution branch: 1 passed in 65.24 seconds. Those are whole-test durations,
  not startup measurements. Both used identical interpreter/dependency files,
  independent editable installs and unchanged budgets. The timeout cause is
  unresolved; these rechecks do not turn the original gate into a green run.
- AppHost suite and initial boundaries: 207 passed, 1 skipped, 3 failed from
  stale module/import inventory and an 800-line Product owner budget. The
  inventory was updated, composition helper moved into its existing optional
  owner, and all 48 boundary/Product rechecks passed. No old budget was raised.
- AppService, AppHost and Hosting Ruff/mypy targets pass; the latter typechecks
  cover 99 and 26 source files. Documentation invariants and the generated
  source dependency graph also pass.
- Additional offline scopes found one more exact Hosting module inventory to
  update; its focused recheck passed (`execution-service-inventory-final.xml`).
  The first supplemental G10 native invocation selected a global, older CLI
  through `PATH`. After fixing the supplemental runner to put the task virtual
  environment first, that exact case passed with unchanged budgets
  (`execution-service-g10-path-recheck.xml`, 28.84 seconds for the whole test).
  Completed batches were retained; the interrupted batch was rerun with the
  corrected environment. This installation-path issue is distinct from the
  earlier G10 startup comparison limitation.
- The 11 supplemental batches cover 210 additional test files: their raw
  result is 2666 passed, 69 skipped and the two failures described above;
  both have passing targeted rechecks. G8's additional actual Product normal
  close case also passed (`execution-service-g8-cleanup.xml`).

Local reports and the comparison environment manifest are retained under
`.artifacts/execution-service-*`. The temporary comparison worktree is removed
after its clean state and ancestry are verified.

New scenarios cover silent entry, full-ledger deduplication, exact-text
conflicts, cancelled waiters, cleanup debt/retry, pre-entry interruption,
canonical reopen, task-construction rollback, authority fencing, lost delivery,
shared legacy capacity and explicit member-close settlement. A previously
removed member's cleanup debt is included in the first application stop.

The prior G10 timing discrepancy and broader packaging/platform acceptance
remain separately tracked in the Product contract. The change-aware plan also
retains host-runtime/platform checks as external acceptance; the local offline
results do not resolve those integration gates.

## Composition and protocol

The AppService constructor takes an optional `HostedExecutionServiceBindingV1`.
It contains application identity, a fresh service instance ID, limits and an
explicit Product capability selector. Default construction preserves the
existing client and Product contracts. Reuse that binding only within one
application instance; create a fresh instance ID after application restart.
G13 recovery restores desired Session membership, never the execution ledger.

Coding composition can call `create_coding_execution_service_binding` from
`loushang.coding.hosted_execution`, then pass the result as `execution` in
`CodingForegroundHostedApplicationRequestV1`. This selects the real execution
adapter on the canonical AppHost resolver. The adapter retains the exact
AppHost lease owner, so cleanup completes before profile detach and runtime
binding close. No second adapter is installed on the same Product Session.

The optional `HostedLocalRuntimeV1(session_execution=True)` deployment selects
one of these closed profiles:

| Capabilities | Profile |
| --- | --- |
| Execution | `local-detachable-execution/v1` |
| Discovery and execution | `local-detachable-discovery-execution/v1` |

Authentication binds the exact endpoint record, including its closed capability
list. The authenticated hello announces `serviceInstanceId`,
`executionVersion: loushang.execution/v1`,
`submissionRetention: service_instance_lifetime`, and `restartRecovery: false`.
The endpoint's authentication `instance` and the service's `serviceInstanceId`
are different lifetimes; a listener restart must not manufacture a new ledger.

Existing application operations retain their v1 frames. New execution calls
use an independent strict codec and `protocolVersion: loushang.execution/v1`:

| Operation | Additional request fields | Result |
| --- | --- | --- |
| `execution/submit` | `submissionId`, exact `text` | Current record |
| `execution/get` | `executionId` | Current record or not retained |
| `execution/find_submission` | `submissionId` | Current record or not found |
| `execution/interrupt` | `executionId` | Record and `requested` / `already_terminal` disposition |
| `execution/snapshot` | None | Composite source/execution snapshot |
| `execution/read_events` | None | Bounded content and execution updates |

Every new request includes `requestId`, `control` (attachment ID, controller
generation and member ID), and `expectedInstanceId`. The request ID sequence is
shared by old and new calls on that connection. IDs are correlation values;
current scope, controller, membership and binding checks establish authority.
Get/find/interrupt share the bounded control request class, independently of
ordinary requests. Transport overload can reject a communication request;
AppService duplicate admission itself never consumes a new execution slot.

Execution updates have independent Session execution revisions and per-record
revisions. A `running` update is the explicit execution-start notification;
a terminal update appears only after Product cleanup and final source cursor
publication. Content retains its own cursor and execution ID envelope. The
wire snapshot never serializes private binding objects. Source transcript text
is bounded to 65536 codepoints, draft to 16384; omission is explicit. Event
mailboxes reserve at most 512 KiB of worst-case encoded payload. Overflow/gap
requires a fresh snapshot. Consuming an execution snapshot/event batch also
consumes its covered legacy content copies for that member, keeping the
attachment healthy without duplicating GUI output.

## Client and native GUI handoff

`LocalAppClientConnectionV1.execution_client` exposes the optional typed client
after authenticated negotiation. Its methods match `ScopedExecutionClientV1`.
`SubmissionRecoveryV1` and `PendingSubmissionV1` provide an executable client
reference: preserve exact input and ID, distinguish delivery from execution,
query on reconnect, retry explicitly with the same submission, and retain
unknown state across service-instance changes. They never call legacy start
as a recovery fallback. Execution updates received before the submit response
cannot be overwritten by a later accepted response with an older revision.

The native GUI implementer should map these fixtures through the Rust AppClient
and then the React UI port:

- `tests/appserver/test_execution_protocol.py`: strict message algebra, hello,
  malformed records and serialized snapshot/event shapes;
- `tests/appserver/fixtures/execution_v1.json`: checked-in JSON golden values
  for native Rust/TypeScript decoder conformance;
- `tests/appserver/test_execution_recovery.py`: lost response, racing lookup
  miss, explicit retry, instance replacement and early/late event ordering;
- `tests/appserver/test_execution_local.py`: authenticated real local connection,
  controller replacement and same-instance recovery;
- `tests/coding/test_hosted_execution.py`: actual Product execution and lease
  cleanup order, including commands with no model output.

The Linux task does not establish Windows/macOS native IPC, IME or desktop
playback acceptance. The repository currently has GUI design/handoff documents;
this delivery supplies the backend/client seam for that native implementation.

## Owner and reviewability checks

Public execution values and codecs live under `appserver/execution`; AppService
keeps the registry, Product ports and private composite-snapshot proof. Neither
AppServer nor AppService imports Product/Harness implementation to drive work.
The old `appservice.execution_contract` import path reexports shared value
identities, keeping existing Product adapters source-compatible.

Existing G11 core and Product budgets are retained. The notification owner is
bounded to 60 lines, registry to 400, scoped execution client to 250; the separate
transport package has a 1200-line total and 400-line per-module cap. Architecture
tests register every module and enforce these budgets and dependency directions.

## Managed Coding composition — stage 1A

The stage 1A composition reuses the existing Coding execution adapter and the
single `AppServiceV1` execution registry. Managed bootstrap creates one
`HostedExecutionServiceBindingV1` per application attempt; client scopes borrow
that registry and never construct another one. The local listener publishes
Execution only after the application admits this capability. Managed Mux
creation/closure admission is unchanged.

The managed resolver retains the canonical Product identity and projects only
the admitted selection scope/fingerprint. Before adapter construction it seals
an internal proof of the exact leased owner, Product binding, AppHost runtime,
lease, control, canonical identity and selection identity. The adapter accepts
a differing identity only with that proof and the original control. A copied
proof on another owner, a substituted lease/runtime/control or a changed view
is rejected before acquiring the exclusive execution claim. This is an
internal composition invariant, not a wire capability or protection against
arbitrary Python code modifying private implementation state.

Shutdown follows the existing chain: fence AppService admission, interrupt and
settle the registry binding, close the adapter, detach the AppHost lease, close
the runtime Session, then settle the remaining AppHost/Product/catalog owners.
No AgentSession, execution driver, writer or transcript header is replaced to
accommodate the projected identity. Failed adapter construction releases its
claim and closes its own lease/runtime binding; duplicate-owner rejection
only detaches the rejected lease and preserves the existing execution.

Internal implementation acceptance: Codex implementation agent, responsible
for the authorized stage 1A Coding/AppService composition and AppHost ownership
boundary; reviewed against `main@c3d6f3f18` and the
`feature/managed-execution-1a` working diff. The accepted boundary preserves
AppService registry ownership, AppHost binding lifetime and canonical Session
storage. Evidence is the extended managed application/local tests, existing
non-managed execution tests and managed lifecycle regressions. This is agent
acceptance within the delegated task, not a user acceptance statement.

Follow-up outside stage 1A: client disconnect still revokes interaction
authority and can deny a pending approval. GUI profile negotiation, default
TUI migration, remote connections and restart recovery remain separate work.

Stage 1A validation on Linux (2026-11-08): the focused execution/managed/local,
AppService registry/service, AppHost lifecycle, detached process and production
entry group passed 156 cases. The existing PR-fast Coding inventory passed
4,195 cases with 22 existing platform skips across eight deterministic shards;
`verify_module_report.py` validated each report and their duplicate-free union.
Both selected E2E smoke cases passed. Changed-file Ruff, source dependency
freshness and documentation invariants passed. Counts describe separate groups
and must not be summed as unique coverage.

The initial shared virtual environment's editable metadata selected the GUI
worktree, causing host-distribution provenance failures also reproduced on
main. Final module/E2E checks used a private copy of the existing environment
with only this repository reinstalled offline as editable; no project dependency
or shared environment was changed. The default legacy `make check-changed`
sequential run was superseded by the existing PR-fast plan and its sharded
module runner; it is not recorded as a completed passing legacy gate. The
ignored `.artifacts/stage1a/` directory retains the final logs and JUnit reports.

## Managed independent-process validation — stage 1B

`tests/coding/test_managed_execution_process.py` exercises the production
`coding_managed_process_request` / `loushang.coding.managed_process` launch and
managed stop on Linux. Its child wrapper injects a synthetic model through the
existing command constructor and observes the real registry's submit return.
It does not replace bootstrap, AppHost, AppService, Registry, AgentSession,
managed Mux admission, TCP authentication or Execution hello.

Each case starts a Host and then closes the launch coordinator's handles.
A second coordinator must reuse the same native instance without spawning.
Client A and client B are separate Python processes, also distinct from the
Host and pytest. A creates the Mux through `ManagedMuxCreateOperationV1`, opens
one Session, persists the submission intent before sending, and exits while
the model is gated. Cases cover ordinary connection cleanup, `os._exit(17)`
without cleanup, and lost acceptance response (pause A's socket reading before
submit, observe actual Host execution entry, assert A's response future remains
pending, then exit without receiving the receipt).

Only after A is reaped does the test release the first provider gate. The
original Host must record model progress after A's exit. B lists and attaches
the original Mux with a fresh attachment/controller generation; its recovery
path never opens a Session or submits work. It finds the original submission,
observes the same serviceInstanceId/executionId/Session in `running`, and checks
that an absent submission returns unknown (`None`) without replay. Only then
is the final provider gate released. B reads `succeeded`, the expected assistant
answer, and the same retained terminal submission record. Exactly one registry
submit receipt, one model invocation and one Session transcript are required.

Stop runs after execution completion using `ManagedServiceStopOperationV1`.
Success requires exit code zero plus all three durable evidence fields:
application cleanup, process exit and process-scope settlement. Failure teardown
retains/reopens the original native identity and signals only that test-owned
pidfd. A/B are reaped in all paths. This does not validate stopping an active
Execution or failure-settlement guarantees reserved for stage 1C.

Reproduce from the task worktree's private environment, outside the restricted
sandbox (the test uses only a synthetic provider and local connections):

```sh
mkdir -p .artifacts/stage1b
LOUSHANG_STAGE1B_EVIDENCE_DIR=.artifacts/stage1b \
  uv run --no-sync --offline python -m pytest \
  tests/coding/test_managed_execution_process.py -m 'not live' -q
```

The test itself starts/stops the Host and both clients; no manually running
service is needed. Optional evidence JSON files contain native PID/start-time/
boot identity, A/B PIDs and exit codes, managed instance, all business IDs,
provider progress timestamps, final answer and stop evidence. They contain no
connection tokens. `requires_host_runtime` preserves the existing restricted
runtime selector; no CI gate or platform matrix is added.

The first test attempt failed because its manually created Session directory
had an unsafe parent permission. The final test lets the existing production
store-admission path initialize storage. No stage 1B production source fix or
storage-rule change was needed. This validates same-live-Host recovery only;
it does not establish durable submission recovery across Host restart. Pending
approval denial on client disconnect remains unchanged and out of scope.

Stage 1B validation on Linux (2026-11-08): all 172 cases passed in 91.62s
across the new process test, hosted execution, managed application/local,
managed process entry/detached, AppService execution registry/service and
AppHost local/runtime/managed-stopper tests. The three process cases also
passed alone (14.13s). Changed-test Ruff, `git diff --check` and all nine
lightweight documentation invariants passed. The ignored
`.artifacts/stage1b/regression.xml` and `regression.log` retain the final run;
`normal.json`, `abrupt.json`, and `lost.json` retain matching process evidence.
These groups overlap and are not additive unique coverage. The stage 1A
module-wide gate results above were not rerun for these test-only additions.

Internal verification acceptance: Codex implementation agent, responsible for
the authorized stage 1B Linux process verification, reviewed the real-process
assertions, lost-response injection and exact-owner cleanup against the stage
1A working tree. All nine stage 1B criteria have local evidence; this is not
user acceptance or an extension of the validated platform/scope.

