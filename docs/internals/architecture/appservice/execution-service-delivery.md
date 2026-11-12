# Execution Service Delivery — #576

## GUI integration review (2026-11-12)

Codex, acting as the implementation agent for PR #889, reviewed the managed
startup and Workspace seams at `2ef8ace84`. The AppHost starter may use the
Hosting Windows process owner through `loushang.hosting.service_windows`;
the existing POSIX route continues to use `service_process`. The two
architecture assertions enumerate those exact dependencies.

The Coding terminal attaches to its existing Mux and registers a Workspace
only to obtain its scope. Opening a project through the GUI still provisions
its own Mux. After a busy admission read, AppHost releases the original
read context before yielding and refuses to retry through persistent
cleanup debt. The regression cases exercise both transient and persistent
contention and the terminal's single-Mux selection.

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

## Managed active-execution shutdown — stage 1C

Stage 1C adds Linux process verification without changing production shutdown
code. `test_managed_stop_execution.py` reuses the stage 1B production entry and
separate client, with `_managed_stop_probe.py` installed only by the test child.
The probe calls original methods, records successful release receipts, and
introduces explicit scheduling gates/faults; it does not substitute an
AppService, Execution Registry, Session, native observer or process manager.

The actual shutdown chain is:

1. `ManagedServiceStopOperationV1._run_once` admits the recorded native identity
   and process group, durably requests stop, then observes child cleanup and
   native exit separately. Its deadline does not grant authority to kill.
2. The managed child's adopted command fences `HostedLocalRuntimeV1`.
   `HostedLocalRuntimeV1._fence` fences the server and client scopes before
   asynchronous cleanup. `_close_once` finishes any stop reply, closes server
   connections and the connection directory, then closes the application.
3. `HostedApplicationContinuityRuntimeV1._settle_once` first shuts down the
   hosted application. `HostedApplicationRuntimeV1._shutdown_once` runs service,
   AppHost and Product cleanup in that dependency order, retaining a failed
   phase rather than closing its dependencies prematurely.
4. `AppServiceV1.close` fences the Execution Registry and discovery, closes
   client scopes, moves Session owners into cleanup debt, and joins all Session
   closes with `gather(return_exceptions=True)`. One Session failure does not
   skip other Session cleanup; successful owners leave the debt set.
5. `_SessionOwner._close_port` calls `ExecutionRegistryV1.close_binding` before
   Adapter close. The registry marks the binding closing, requests whole-
   execution interruption, joins/retries the original settlement, then removes
   listeners. `CodingExecutionWorkV1` aborts real Agent operations on cancellation
   and calls `AgentSession.settle_execution`; the registry publishes the
   terminal result and releases the active slot only after Product settlement.
6. `CodingHostedExecutionSessionV1._close_execution` retains its close task.
   Its leased owner closes the AppHost lease before `AppHostRuntimeV1.close_session`.
   `CodingRealHostedSessionV1._close_once` disposes the original AgentSession.
   Successful close bodies run once; retrying a failed owner is allowed and
   does not mean repeating a successful resource release.
7. Once service cleanup succeeds, AppHost shutdown and the foreground Product
   factory close complete, including Catalog cleanup. Only then does the
   Continuity runtime release its store lease. Host stop retains the desired
   continuity record; it is not Session-history deletion or application retire.
8. `ManagedChildApplicationV1._close_once` records application cleanup only
   after the adopted application reports no pending cleanup. The external stop
   operation records native leader/group exit; `cleanly_stopped` requires all
   three facts. `_ChildLifetime._drive` retains failed cleanup and retries with
   the existing budget/backoff policy instead of pretending cleanup succeeded.

Operation meanings remain separate: client detach releases connection and
attachment authority (stage 1B proves work survives); Execution interrupt
settles one execution; Session close settles its owned execution and releases
that Session; Host stop fences the whole service and releases every Session
and application owner. No operation was changed to implicitly replace another.

Four real-process cases cover one active Session; three Sessions (one active,
two idle); one Adapter cleanup failure; and a delayed cancellation settlement.
The client submits through the Execution API and proves `running` before stop.
After the real listener/scope fence, a test gate briefly retains the socket so
an additional real submit receives `service_closed`, rather than merely EOF.
The gate then releases normal cleanup. Exactly one accepted execution and one
model entry are required; cancellation must reach the real synthetic transport,
followed by `interrupted` and an empty active slot. Per-Session observations
require one successful Owner/Adapter/Lease/Product/AgentSession release, and
assert that lease release precedes Agent disposal. AppHost, Product factory,
Catalog and Continuity lease completion are observed explicitly.

The fault case rejects one Adapter's release before performing it. Two other
Session owners must complete while the failed owner remains retained. The
stop-waiter timeout must leave application-cleanup and native-exit evidence
false, with the original Host still alive. After removing the injected fault,
a new stop operation joins the same instance and cleanup succeeds. The Host
returns **1**, as the existing lifetime policy preserves the prior application
failure; final clean-stop evidence describes resource settlement, not an exit
code of zero. Ordinary and delayed-settlement cases return **0**.

The timeout case holds the transport's cancellation cleanup beyond the caller's
three-second stop deadline. It asserts that no execution terminal record or
child-cleanup success is published early. Releasing that exact cleanup permits
the same execution to settle; it does not replay input or replace the Runtime.
This exercises a caller stop timeout, not a new Host timeout/kill policy.
Concurrent/repeated stop callers and a fresh stop after native exit must return
consistent final evidence without additional successful release receipts.

Run from the dedicated task worktree, outside the restricted sandbox:

```sh
mkdir -p .artifacts/stage1c
LOUSHANG_STAGE1C_EVIDENCE_DIR=.artifacts/stage1c \
  uv run --no-sync --offline python -m pytest \
  tests/coding/test_managed_stop_execution.py -m 'not live' -q
```

The ignored evidence files retain original process identities, client receipt,
execution/Session IDs, protocol rejection, cancellation/settlement/release
ordering, evidence observed during failure, and final exit/cleanup facts. They
are test observations of the live Registry, not a persistent Execution ledger.
No GUI/TUI, approval, remote-access, restart-recovery or CI-gate changes are
included. Permanent unrecoverable cleanup remains pending under the existing
lifetime contract; these tests release their controlled failures to finish and
reap every owned process rather than leaving an intentionally stuck Host.

Stage 1C regression on Linux (2026-11-08): **268 passed in 122.84s**, including
all stage 1A/1B focused tests from the prior 172-case group, the four new stop
cases, and existing managed child/bootstrap/lifetime/process plus hosted
application/continuity tests. The retained logs are
`.artifacts/stage1c/regression.log` and `regression.xml`. Stage 1B reconnect
identity evidence from this run is under `.artifacts/stage1c/reconnect/`.
The focused stop group is rerun after adding the explicit assertion that a
fresh connection lease to the already stopped instance returns `unavailable`;
its final report is `focused.xml`. These overlapping runs are not additive
unique coverage. Ruff and documentation invariants are checked separately.

Internal verification acceptance: Codex implementation agent, responsible for
the authorized stage 1C shutdown verification, reviewed production call order,
retained cleanup debt, retry/exit-code semantics, exact-process teardown and
all four acceptance scenarios. No production defect requiring a fix was found.
This records delegated implementation verification, not user acceptance or
cross-platform/provider certification. Stage 1C does not authorize proceeding
to GUI or TUI integration.

## Managed GUI adaptation — stage 1D

The explicit user-requested task worktree remains
`feature/managed-execution-1a`; neither main nor the shared GUI lane is edited.
Reviewed stage checkpoints are `5aecc42d5` (1A composition), `a112fc5b9` (1B
process continuity) and `c9ceb4613` (1C shutdown). They contain the actual source
changes, not just documentation or test summaries.

### Execution entry review

With the Execution capability installed, AppService's legacy `start_turn`
resolves the same binding and calls `ExecutionRegistryV1.start_legacy`, which
submits without a client submission ID and waits for the result. The explicit
Execution API returns an acceptance record immediately, retains the invocation
independently of the connection, and supports same-instance submission lookup.
Both use the same `CodingHostedExecutionSessionV1` and original AgentSession,
with the same per-Session active slot and Product execution path. Direct legacy
adapter calls also use its execution guard; no second Agent loop is introduced.
Legacy calls have no caller-retained deduplication key and only bounded legacy
record retention. Explicit submissions retain their ledger for the live service
instance; this is not Host crash recovery. Whole-Execution interrupt and legacy
turn-only interruption remain distinct, including command execution semantics.
Both entry points retain existing interaction/approval authority: disconnect
can deny a pending approval, which remains outside this stage's changes.

The GUI already uses `execution/submit`, `execution/find_submission`,
`execution/snapshot`, event/content polling and `execution/interrupt` through
Rust `ControlAuthority`. It does not submit tasks with `start_turn`. No semantic
conflict requires Agent Loop, model, tool or Runtime restructuring. Original
legacy APIs and default TUI behavior are preserved.

### Client and platform changes

`app_client/record_value.rs` now implements the Python closed capability algebra:
canonical base capability order followed by discovery, execution, managed Mux,
closure and optional resume-input lookup. Closure requires managed Mux; resume
lookup requires Execution. Duplicate, unknown, unordered and invalid combinations
fail. The transport record profile remains `local-detachable/v1`; its semantic
profile is derived from its capabilities, not fabricated or weakened. Existing
valid profiles remain decodable. GUI requires Execution and validates the exact
semantic profile in the canonical hello, protocol/execution versions, service
identity and service-instance-lifetime retention. Authentication still covers
the unchanged full public record, including all capabilities.

On Linux, `record_linux.rs` opens each directory component without following
symlinks, retains the admitted directory and opens the file relative to it.
Current-user ownership, exact private directory/file modes, regular-file type,
single link, size bound, inode identity and read-version checks precede/guard
secret consumption. Windows native DACL/handle admission is unchanged. `libc`
is made a direct Linux-only dependency for openat/geteuid; it was already locked
transitively, and no package version is changed. macOS live bridging is not
newly enabled. Conditional compilation includes Linux only where the new native
reader and platform-neutral transport/worker code support it.

The connection path is explicit launch arguments -> native record admission ->
record capability/profile selection -> loopback HMAC authentication -> exact
Execution hello -> attach named existing Mux -> fresh attachment/control and
composite snapshots -> existing React live projection. The Mux name is selected
by the native launcher; this stage adds no Host chooser/manager. Managed Mux
creation remains in `ManagedMuxCreateOperationV1`; GUI never uses a legacy create
operation to bypass it. New Session uses the existing source Session template;
prepare a Mux with at least one Session for this GUI entry. Reconnect attaches
existing members, without reopening their active Product bindings.

`live_bridge.rs` routes a receipt timeout into the existing unknown-submission
recovery path as well as transport failure. Recovery now carries the original
serviceInstanceId and refuses a different Host before lookup. It queries the
original Session/submission ID and never resubmits. A lookup miss is unknown.
GUI restart reconstructs current Session/Execution state from the Host snapshot;
it does not introduce a persistent client ledger. No keys or attachment/control
authority are published to the WebView.

### Evidence and remaining graphical acceptance

`test_managed_gui_client.py` uses the production managed entry and existing
synthetic provider, a managed-admitted Mux, one real Session, and distinct Rust
client processes compiled from the exact Tauri AppClient/worker sources.
Normal detach and abnormal client termination happen while the Execution is
running. A new Rust process finds the original submission and snapshots the
same service/Session/execution identity. It reads the expected assistant result
or requests an interrupt and waits for `interrupted`. Host survival, one submit,
one model entry, graceful stop and process-group settlement are asserted.
The probe's end condition now follows Execution terminal state, not legacy turn
events. The initial interrupted-execution test exposed that probe-only issue;
no server or Agent behavior was changed to satisfy it.

The actual Tauri Linux window was launched against an independent managed Host
and visually inspected with a window-specific X11 screenshot. It displayed
connected status and the original Mux, Session and service identity. Evidence:
`.artifacts/stage1d/desktop-a.png` and `desktop-connection.json` (Host PID 237084,
GUI PID 237106). Initial attempts without the debug Vite server displayed a
connection-refused page; those are not acceptance successes. The native input
automation in this Wayland/Xwayland session did not deliver text to the WebView.
The desktop harness therefore did **not** complete the GUI submit/close/reopen/
result-display workflow and was torn down after its bounded wait. Its failure
log is retained. This is a graphical acceptance limitation, not permission to
claim Rust probe evidence as end-to-end GUI acceptance. The stage is not fully
accepted until that operator-visible workflow is completed.

`_managed_gui_desktop.py` is an opt-in bounded manual acceptance helper, not a CI
gate or alternate service manager. Start the debug Vite frontend first, build
the native binary, then use it to submit in GUI A, close A while running,
inspect GUI B, release `workspace/finish-after-b`, inspect the answer, and close
B. The helper checks same-Host execution continuity and then uses managed stop.
Its test-only provider/watchdog budget is extended only when the explicit
`desktop-acceptance` marker exists; default 1B/1C budgets are unchanged.

Reproduction from the task worktree:

```sh
cargo +1.98.1 build --locked --offline --manifest-path gui/contracts/rust/Cargo.toml --bins
uv run --no-sync --offline python -m pytest tests/coding/test_managed_gui_client.py -m 'not live' -q
uv run --no-sync --offline python scripts/gui/check_record_values.py
uv run --no-sync --offline python scripts/gui/check_auth_interop.py
cargo +1.98.1 test --locked --offline --manifest-path gui/src-tauri/Cargo.toml --lib
npm --prefix gui run check:full
# Manual native acceptance, after npm --prefix gui run dev:web in another terminal:
cargo +1.98.1 build --locked --offline --manifest-path gui/src-tauri/Cargo.toml
GDK_BACKEND=x11 PYTHONPATH=.:src uv run --no-sync --offline python tests/coding/_managed_gui_desktop.py
```

Native socket/process tests must run outside the restricted sandbox. Existing
Node dependencies were installed from the offline cache into this worktree;
no shared node_modules or package-lock was changed. The private Python editable
installation points to this task worktree. No live provider, user workspace,
Session history, GUI lane worktree, protocol schema, Host lifecycle, TUI,
tray, SSH or new control-sharing policy is changed.

Validation recorded on 2026-11-08:

- The 13-file critical 1A–1D regression group passed **179 tests in 122.27s**;
  `.artifacts/stage1d/regression-final.xml` records the exact test identities.
- The new Rust process tests passed all three scenarios. Their JSON evidence
  records process identities, service/Session/submission/execution IDs, observed
  snapshots, one acceptance/model entry, and clean managed-stop evidence.
- `npm --prefix gui run check:full` passed: 87 React tests in 14 files,
  TypeScript, frontend build, Rust formatting, Clippy and both native feature
  configurations. Native library tests passed 27 cases. The contract crate
  tests also passed (shared AppClient tests are repeated across probe binaries).
- Record-value cross-language checks passed 85 cases; authentication interop
  passed 11 cases. Changed Python files passed Ruff; documentation and diff
  whitespace checks passed.
- An earlier combined run had two failures: the probe waited for a legacy turn
  event after an interrupt, and an existing detached test reported Session
  unavailable during open. The former was fixed in the probe's terminal-state
  detection. The latter was not reproduced by its unchanged nine-test file
  (9 passed, 31.72s) or the final 179-test run; its initial failure log is kept,
  and its cause remains undetermined rather than claimed fixed.

Review responsibility: the implementing agent reviewed the Stage 1D client
protocol, native record admission, ownership and test scope under this task's
existing authorization. This is acceptance of the bounded implementation and
recorded automated evidence, not user acceptance or complete graphical/platform
acceptance. No server protocol, Runtime ownership or persisted Session format
was revised. Full native GUI submit/exit/reopen/result acceptance remains open.

Critical regression command (run from the task worktree):

```sh
uv run --no-sync --offline python -m pytest \
  tests/coding/test_managed_gui_client.py \
  tests/coding/test_managed_stop_execution.py \
  tests/coding/test_managed_execution_process.py \
  tests/coding/test_hosted_execution.py \
  tests/coding/test_managed_application.py \
  tests/coding/test_managed_local.py \
  tests/coding/test_managed_process_entry.py \
  tests/coding/test_managed_detached.py \
  tests/appservice/test_execution_registry.py \
  tests/appservice/test_execution_service.py \
  tests/apphost/test_local.py tests/apphost/test_runtime.py \
  tests/apphost/test_managed_stopper.py -m 'not live' -q \
  --junitxml=.artifacts/stage1d/regression-final.xml
```

Repository-wide change-selected checks:

- `make plan-checks` selected GUI, docs, architecture, Coding and AppHost based
  on the cumulative branch delta. `make check-changed` passed the GUI/docs/
  dependency checks and Coding (4197 passed, 22 skipped, 72 deselected, 737.08s).
- Its AppHost lint and mypy checks passed (143 source files). AppHost pytest
  reported 3110 passed, 13 skipped and four architecture-test failures (330.07s).
  These identified stale Stage 1A architecture inventories: three omitted
  `hosted_execution.py`'s `SessionBindingKeyV1` dependency, and G11 still required
  managed bootstrap to exclude Execution and only one guarded adapter import.
- The four architecture files now record that exact dependency and enforce one
  Binding factory call passed to the original request, only the binding-key
  AppHost import, and the exact two imports under explicit Execution guards.
  The runtime identity/ownership tests are unchanged. These are a bounded 1A
  architecture-test synchronization, not new protocol/runtime behavior or a
  broader CI route. All four files passed on focused rerun: **37 passed, 5.26s**.
  The full `make check-changed` command was not repeated after this test-only
  correction; its initial nonzero result remains in the retained log.

The four synchronized files are `tests/architecture/test_apphost_a0_contract.py`,
`test_apphost_a02_architecture.py`, `test_hosted_product_runtime_v1_baseline.py`
and `test_hosted_application_g11.py` in the same directory. Review acceptance
covers the exact Stage 1A dependency and bootstrap selection described above,
without weakening the default Product boundary or permitting a second Runtime.

## Stage 1D native graphical acceptance follow-up — 2026-11-08

This follow-up uses the unchanged production implementation at `e8f058f50`
on `feature/managed-execution-1a`. The prior section's incomplete graphical
acceptance is retained as historical evidence; the new run supplies actual
human-operated Tauri GUI evidence rather than substituting Rust probes.

The available computer-use inventory exposed browser tabs but no native Tauri
window control. The user therefore operated the real Linux GUI: entering each
request, clicking stop, and closing GUI A. The coordinator only prepared the
managed-admitted Mux and original Session, launched native GUI processes,
released synthetic model gates, observed production calls and checked identity.
It never submitted or interrupted an execution for the GUI. No new automation
framework or production-code change was needed.

The existing `_managed_gui_desktop.py` now coordinates four bounded manual
steps. `_managed_gui_probe.py` records original AgentSession construction,
original Registry interrupt/terminal calls and actual snapshots read by the
GUI. Its deterministic model streams a visible running message and waits on a
file gate. The third producer is cancelled only by the GUI's actual interrupt.
`_managed_execution_host.py` selects this probe only with the explicit
`desktop-scenario-v2` marker. Existing 1B/1C probe defaults remain unchanged.
All listener, ownership, Registry, AgentSession and shutdown code is production.

Run directory: `.artifacts/stage1d/manual-20261108-190914/`.
Host PID: **265425**; GUI A: **265466**; GUI B: **268466**.
Service instance: `22931fc56bde99988cc7b6c334d3bca7`.
Session: `9d0e9ebc420b70160f1849983eddd1d34f5ced04307b1e23132cd4f2b19eb715`.
All four executions use that same service and Session, and the one original
AgentSession. Execution prefix below is `exec-90d93bdc555b38cc625a295c-`.

| GUI request | submissionId | Execution suffix | Terminal outcome |
| --- | --- | --- | --- |
| `gui-final-1` | `gui-7830ca0d-3ebe-4bba-a416-671dc92a5a8a` | 1 | succeeded |
| `gui-final-2` | `gui-ab8ca3bc-91f1-44da-8960-5e40ffd5e61e` | 2 | succeeded after GUI A exit |
| `gui-final-3` | `gui-76e842dc-764a-402b-a1f8-7a0d892f4230` | 3 | interrupted by GUI stop |
| `gui-final-4` | `gui-85d77cc3-9278-4be4-b817-2e5c0a78866e` | 4 | succeeded after interruption |

The user confirmed first-result display, running-task window close, restored
original conversations/results in GUI B, GUI stop's interrupted display, and
fourth-result display. `operator.jsonl` records those exact confirmations;
Host assertions do not substitute for the operator's visual observations.

Critical monotonic timestamps in seconds:

- Second execution running snapshot: 81451.754243.
- GUI A observed exited normally: 81453.995390.
- Same Host's second model progressed: 81454.024448; succeeded: 81454.031573.
- GUI B launched: 81454.198207; original execution's succeeded snapshot read:
  81455.159165. GUI B restored a completed execution, without a second submit.
- Third execution interrupt request: 81597.378613; model cancellation:
  81597.430665; interrupted settlement: 81597.442736.
- Fourth execution succeeded: 81783.082317, and GUI read its final reply.

The audit contains four distinct submissions, four distinct executions and
exactly four model entries, with one Product AgentSession construction. No
Session reopen, duplicate execution or new Host was used for recovery. Native
GUI stdout/stderr are captured in `desktop.log` (this build normally emits no
client text logs); `snapshot_read` entries are observations of actual AppClient
requests at the Host, not an invented client log. `provenance.json` records the
implementation commit, worktree and native binary/test-probe hashes.

Regression commands and results:

```sh
make check-apphost
uv run --no-sync --offline python -m pytest \
  tests/coding/test_managed_execution_process.py \
  tests/coding/test_managed_gui_client.py \
  tests/coding/test_managed_detached.py -q \
  --junitxml=.artifacts/stage1d/final-process-regression.xml
```

The complete AppHost target exited **0**: Ruff passed, mypy passed on 143 source
files, primary pytest **3114 passed / 13 skipped in 332.58s**, G8 evidence
19 passed, G9 evidence 16 passed, G10 evidence 15 passed / 12 deselected, manifest
verification passed, and the installed POSIX process-group canary passed. Thus
the four previously corrected architecture assertions passed in the full
AppHost target, not just a focused rerun. Full log:
`.artifacts/stage1d/apphost-final-acceptance.log`.

The additional process regression passed **15 tests in 55.83s**. The historical
intermittent detached Session-open failure did not recur; its cause remains
undetermined and the earlier failure record is retained. This follow-up does
not claim to have fixed it. No current test failed, and no assertions were
relaxed to obtain these results.

Reproduction: start `npm --prefix gui run dev:web`, then run
`GDK_BACKEND=x11 PYTHONPATH=.:src uv run --no-sync --offline python tests/coding/_managed_gui_desktop.py`.
Follow the published `desktop.json` step. The operator sends `gui-final-1`,
confirms its displayed result; the coordinator creates `ack-first` in the
published test workspace. The operator sends `gui-final-2` and closes GUI A
while running. GUI B is automatically launched after observed A exit and task
completion. The operator confirms recovered replies; the coordinator creates
`ack-reconnect`. The operator sends `gui-final-3`, clicks stop, then sends
`gui-final-4`. After visual confirmation the coordinator creates `ack-final`;
the operator closes GUI B and the helper invokes managed stop. Preserve
screenshots and the run directory. A timeout/failure is recorded and causes
cleanup, never a successful acceptance result.

Final cleanup succeeded in the manual run: GUI A and B both exited normally;
the helper exited 0 and recorded `completed: true`. The managed stop evidence
has `process_exited`, `application_cleanup_completed`, and
`process_scope_settled` all true. The temporary test workspace was removed
only after copying the execution audit and Host diagnostics to the run
artifact directory. No actual Product change was needed to pass these cases.

Acceptance boundary: all four functional graphical scenarios were performed
by the user and confirmed in real time, with matching Host/process evidence.
The implementing agent accepts this bounded Linux manual run and its automated
assertions within the authorized task. The only retained screenshot is
`01-first-result.png`, supplied by the user and inspected to match Session and
service identity plus the successful first reply. The user reported forgetting
the other screenshots. Recovery, interrupted display and fourth-result display
therefore rely on the recorded human confirmations and Host snapshots, **not**
claimed screenshot inspection. The screenshot archive is incomplete; no images
were reconstructed or substituted. This does not assert Windows/macOS or
packaged-release acceptance, or claim autonomous native UI automation.

Final process inspection found Host 265425 and GUI processes 265466/268466
absent. The task's Vite process was stopped separately. Other application
instances and main/GUI integration worktrees were not modified.


## Post-merge Coding execution budget review — 2026-11-09

The implementation agent reviewed the authorized Stage 1A composition at
`a8f3856a5` against merged main `1665cff34`. The existing Execution Product
slice contains the same two files. `hosted_execution.py` has 338 lines versus
265 on main: a net 73 lines for resolver-sealed identity projection, exact
binding/lease/runtime/control checks, and named adapter-port selection.
`_hosted_execution_work.py` remains 133 lines. This implementation-agent
acceptance covers that bounded Product composition only: add 73 to the existing
400-line combined and 265-line per-file allowances, retaining their existing
headroom. No file is excluded, no core allowance changes, and no execution
ownership or authentication assertion is removed. Splitting security checks
into a new module solely to satisfy the old count would obscure their ownership.

The review checks `_admit_execution_projection`, `_owns_execution_projection`
and `CodingHostedExecutionSessionV1.__init__`: admission retains the original
Product binding, lease, Runtime and control; adapter construction verifies the
sealed objects and preserves exclusive execution claims. Existing managed
identity rejection and execution settlement tests remain the behavioral
acceptance criteria. This bookkeeping correction does not assert that tests
have passed; their actual results are recorded separately.


## G1 local desktop management composition review — 2026-11-09

The implementation agent accepts the following scope under the authorized G1
task, based on checkpoint `73a5e97e4`: the desktop invokes one short-lived Coding
management entrypoint; this entrypoint composes existing managed namespace and
service admission, coordinator, connection lease, Mux creation and stopper.
It does not construct AppHostRuntime, AgentSession, ExecutionRegistry or an
Execution Adapter. AppService/Execution protocols, authentication and canonical
Session storage are unchanged. The exact new reverse consumer is registered in
the architecture inventories; its sole direct Hosting edge is the public
HostingError category, not a process-launch or private platform primitive.

Read-only status does not initialize storage. Readiness requires the recorded
instance, native identity, authenticated record and Execution handshake.
Unconfirmed state cannot authorize a replacement. Mux allocation uses the
original ManagedMuxCreateOperationV1 and reconciles the original reservation
after contention. Stop/restart targets a confirmed instance ID and uses the
existing graceful stopper; restart follows confirmed clean settlement only.
Native lock waits use the existing settled-native receipt and all owners are
retained before IO, then closed in reverse order. Cleanup errors override a
success response. No user acceptance or final graphical acceptance is implied
by this internal composition review.

Rust retains connection record paths outside the WebView and uses the existing
AppClient for Session/Execution operations. Connection configuration may change
only at a resynchronization boundary; the client and React conversation remain
owned across disconnect/reconnect. Host shutdown is a distinct, confirmed native
action. GUI exit still closes client delivery only. Linux managed lifecycle is
supported; other platforms explicitly report unavailable management capability.

### G1 Linux graphical acceptance

On 2026-11-09 the operator exercised the real embedded Tauri/React GUI with the
production managed owners and a deterministic model transport. Native window
interaction was manual; a separate observer collected process identities,
authenticated status, model gates, execution receipts and lifecycle events.
The test-only provider shim calls the production management entrypoint and
changes only the Host's synthetic provider entry; it never submits GUI work.

| Operation | Process evidence | Result |
| --- | --- | --- |
| Cold Start and connect | GUI A 37868, Host 41461 | Mux and Session created through existing admission; task succeeded |
| Close GUI during task 2 | GUI A exited 0 at monotonic 2804.221; Host authenticated at 2806.656 | Same Host; model progressed at 2806.692 and original execution succeeded |
| Open and connect GUI B | GUI B 42885, Host 41461 | Original Session, execution and output restored; no replay |
| Confirm Host stop during task 3 | Host 41461 | Model cancelled, execution interrupted, clean stop |
| Start after stop | Host 48239 | New service identity, original Session/history; new request succeeded |
| Confirm Restart Host | Host 51441 | Clean replacement, original Session/history; new request succeeded |
| Display correction recheck | GUI C 53212, Host 53853 | Operator confirmed historical empty-output and disconnected-state labels; held task interrupted by Host stop |

All six submissions produced exactly six model entries and six distinct
execution IDs. There was one AgentSession construction per Host lifetime;
reconnecting GUI B did not construct another. The common Session ID was
`42ca2238fa7937861edfe69e96e5b54bdc43fa2ccae97d8f7dabe153e7fcbf18`.
The initial Execution serviceInstanceId was `de8ffa4e73e072cb9a132f48288cf3ff`; task 2 retained
submission `gui-d0174128-c7c8-4e6c-821c-2b7d384b0310` and execution
`exec-743af495ccff2e24f13a7894-2` after GUI exit. Each Host instance recorded
starting/ready/stopping/stopped. OS observation confirmed all recorded Host
PIDs and process groups had exited. GUI A/B closed normally; after operator
agreement the remaining GUI C was terminated for cleanup, after its Host had
already stopped cleanly. This last cleanup is not counted as a normal-window
close test.

The operator's screenshots exposed two presentation defects, fixed without
changing execution semantics: a disconnected execution is labelled as its
last known state, and an empty completed history record no longer says it is
waiting for output. No historical execution terminal is invented after Host
replacement. The operator confirmed both fixes in the rebuilt native GUI.

Local evidence is retained under `.artifacts/g1/desktop-evidence/`, with the
two pre-fix screenshots alongside it. The original isolated run directory is
`/tmp/loushang-g1-desktop-lwg27cnp`. No connection keys are copied to the evidence
bundle. The initial attempt to use repository-local managed storage was
correctly rejected because its ancestors were group-writable; the observer now
uses a private temporary directory without weakening admission or changing
workspace permissions.

Validation commands include `npm --prefix gui run check:full`, pinned-toolchain
`cargo test --offline --locked --manifest-path src-tauri/Cargo.toml --lib`
(from `gui/`), and `uv run --no-sync --offline python -m pytest` over
`test_managed_service.py`, `test_managed_execution_process.py`,
`test_managed_stop_execution.py`, and `test_managed_gui_client.py` in
`tests/coding/`. React has 97 passing tests, Rust 31; the process regression
passed 11 tests, followed by 2 passing management tests after adding a real
missing-executable failure case. Internationalization checks pass. Use
`python -m pytest` in copied local environments: an earlier direct pytest
script retained the previous worktree's shebang and could not import the new
module; its failure is retained separately from the corrected run. The copied
virtualenv script shebangs were subsequently repaired in this task environment;
no dependencies or other worktree environments were changed.

The change-aware runner (`python scripts/ci/check_changed.py --base 73a5e97e4`)
completed the selected primary checks: Coding 4199 passed / 22 skipped / 73
deselected, Harness 6357 passed / 108 skipped, Hosting 517 passed / 53 skipped,
AppHost 3115 passed / 13 skipped, and the AppHost Product follow-ups 19, 16 and
15 passed (the last excludes 12 tests). Lint, type checks, dependency inventory
and documentation checks passed. Harness emitted 36 explicit tool-denial
warnings from its existing contract tests.

The aggregate command was then deliberately interrupted (exit 130) during its
automatically appended duplicate `unit_coding` route; it is **not** recorded as
a successful aggregate exit. Command comparison showed that this route only
adds `not e2e_smoke` to the already passing Coding selection, and `unit_hosting`
is a subset of the passing Hosting suite. The two additional example files in
`unit_harness` were run separately with the original safety selectors: 3 passed.
No CI selector or required gate was modified. Raw command output and the
interruption remain in `.artifacts/g1/check-changed-g1.log`.

This establishes Linux development-environment acceptance with a synthetic
provider, not installed-package, Windows/macOS lifecycle or external-model
acceptance. The graphical clicks were not automated. Submission recovery remains
in-process and service-instance scoped. Offline approval behavior, TUI migration,
tray, remote Hosts and crash recovery remain outside G1.

## AppServer over a protected port forward — 2026-11-11

The AppHost delivery implementer reviewed the AppServer, AppHost lifecycle,
and desktop changes on the `feature/gui-apphost-delivery` branch based on
`0c3793ba8`. The accepted deployment uses an optional AppHost loopback listener
with an independently provisioned application credential. OpenSSH supplies
machine authentication and encryption between machines. AppServer uses its
existing authenticated frames, capability handshake and application handlers.
The local management record and stop authority stay on the AppHost machine.
Both listeners share AppHost readiness, peer limits and shutdown.

Linux tests exercised a Rust client through a forwarded port, rejected the
local management credential and remote stop mode, and verified that the same
OpenSSH forward reconnects after AppHost restarts. The desktop route and
configuration are covered by the Tauri tests. On Windows 10 x64, the native
workspace probe and release Tauri GUI built from `bd1c58358` authenticated
through an SSH reverse forward and opened a Linux Workspace. The desktop
displayed the selected Session and a connected status. After a graceful Linux
AppHost stop and restart, the same window recovered the same Session ID under
the new service instance, without refreshing the WebView. The test used an
isolated connection and credentials and made no model calls.

The major-version toolchain configuration at `1b128df31` was verified on the
same Windows machine. Node 24.19.0 and npm 11.17.0 completed `npm ci` from the
existing package cache and passed `npm run doctor`.

Native Windows AppHost acceptance also ran on Windows 10 x64. Independent
`lmux` processes started the Host, reused the running instance, read recorded
status, stopped it gracefully and started a new instance. The Host stayed
available after its launching SSH session ended. An isolated interactive Tauri
window connected through the local AppServer record, registered and opened a
Windows Workspace, and displayed its Session. The same window observed the
Host stop and recovered the same Session under the restarted service's new
AppServer identity. The check used separate frontend and Host directories and
made no model calls.

After retiring the duplicate packaged Workspace entry point, the complete
offline AppService gate passed with 2,587 tests and 16 skips.


### Local service management through loushang-mux

`loushang-mux service` owns user-initiated lifecycle actions. On Windows and in
the portable Linux Host package it composes the existing managed AppHost
admission, coordinator and stopper. The Debian package uses its installed
systemd user unit. The TUI service command delegates to the same CLI. Tauri and
the loopback Web BFF share a Rust command client and use the authenticated
AppServer record for business operations. Stopping or restarting a managed
instance requires the instance identity shown in the UI.

Implementation review for the GUI/AppHost boundary was performed by the
implementing Codex agent on `feature/gui-mux-service`. The reviewed scope is
local lifecycle delegation and authenticated record discovery. Workspace and
Session operations stay on the existing AppServer protocol.
