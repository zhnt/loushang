# Linux interactive startup performance — phase one

Status: Linux startup candidate implemented; lifecycle and measurement components
reviewed, required local correctness coverage completed. Source freeze and formal
paired performance acceptance remain pending; this is not a performance claim.
Tracking: G18 #578. Windows second-turn correctness remains separate in #587.
Source baseline: `7f4b27f4832cb88426ce655d19ac230d13f1dad6`.
Task branch: `harness/linux-interactive-startup-v1` in the isolated Harness lane.

## Objective and completion contract

Make real embedded interactive startup measurable, display the screen earlier,
keep input responsive, and avoid transferring the saving to the first turn.
Deliver all four steps: baseline, evidence-led production optimization, loading
interaction regressions, and paired remeasurement plus three-view review and
local commits. No push, PR merge, or Windows acceptance is implied.

The previous screen-first implementation establishes ownership and functional
ordering, not a quantified improvement. Historical import/help measurements and
native A/A classifications remain unchanged. This is a new experiment.

## Boundaries

- Coding owns route selection, optional Product imports, runtime/session
  preparation, and cleanup. Harness remains independent of presentation.
- HarnessTUI owns one screen/composer, attachment, loading input and terminal
  lifetime. Preserve callback ContextVars and joined cancellation/cleanup.
- Optional capability activation must preserve extension flags, policy fences,
  registrations and first-use semantics. Delay only capabilities whose consumer
  is absent; do not invent a second loader or bypass discovery.
- Do not put arbitrary imports or whole Session/bootstrap ownership on threads.
  Any offloaded read must have an explicit side-effect and cancellation contract.
- Non-TTY, help, invalid arguments, custom injected runners, bare resume picker,
  hosted/mux and RPC retain their existing routing unless separately justified
  and covered. This delivery measures embedded new and explicit resume routes.

The present entry imports `coding.cli.application` completely before `run_cli`;
that module imports bootstrap, UI, workflow and method bindings before selecting
screen-first. Preserve default runner identity (`tui_runner is run_coding_tui`),
materialized/replaced entry `run_cli`, canonical argument/launch-plan validation,
and eventual extension discovery. A second simplified parser is not acceptable.
Moving mandatory synchronous imports behind first render still blocks input;
that alone does not satisfy this goal.

## Measurement contract (freeze before candidate timing)

Use real Linux PTY input/rendering and real Product construction/persistence.
Parent-side monotonic timestamps measure external observations. A synthetic
model transport replaces only network/model IO for first-turn measurements;
report its injection boundary and verify ordinary executable startup separately
so test setup cannot silently preload the critical import chain.
Ordinary installed entrypoint samples own the primary frame/readiness claims.
If synthetic injection cannot preserve that entrypoint, its spawn-to-reply is
diagnostic only, never proof of real end-to-end startup gain. Keep model/provider
resolution, persistence and first-turn initialization in the measured path.

Record separately, never as one ambiguous startup number:

| Metric | Start | End witness |
| --- | --- | --- |
| First frame | Immediately before Product process spawn | Completed loading or ready screen frame, not PTY line echo |
| Initial input echo | Write unique draft after first frame | Draft visible in rendered composer |
| Session ready | Product spawn | Attached session idle status, not welcome alone |
| Loading responsiveness | Each scheduled draft edit/paste | Matching rendered composer revision; keep slowest latency |
| First reply | Submit exact synthetic input after ready | Matching assistant reply, not user echo |
| End-to-end first reply | Product spawn | The same assistant reply |
| Turn settlement | Submit | Actual completed invocation/settlement evidence, not reply alone |
| Exit settlement | Quit/EOF | Successful process exit and terminal restoration |

Observe edits during real preparation, not only a deliberately suspended test.
If preparation completes before an edit is sent, classify it as ready input;
do not advertise it as loading responsiveness. Parent detection delay is part of
the external metric; diagnostic instrumented spans are separate observations.

Scenarios: new empty session and explicit resume of a fixed synthetic history.
Prepare seed history outside the measurement, freeze its content and restore it
for each run at the same logical paths. Preserve draft across attachment and
verify history is actually visible after resume. No real user data or credentials.

After pilot validation, freeze collector and seed, then collect two blocks of
three pairs per scenario (six measured samples per side); one excluded declared
warmup per side/scenario/block. Alternate A/B order and reverse scenario order in
block two. Use independent source-pinned environments with identical dependencies,
interpreter, terminal geometry and declared warm bytecode policy. Record provenance,
machine load, raw observations, and all slower samples. Never pool historical runs.
Smoke/source profiles guide development; final claims require paired actual
entrypoint evidence, with synthetic first-turn results labeled separately.

Report arithmetic mean, median, range, paired direction and absolute savings.
Candidate target: approximately 20% lower mean on the demonstrated main startup
boundary; freeze the selected primary metric after baseline diagnosis, before
candidate collection. This is an exploratory estimate, not formal G18 A/A
acceptance or a cross-platform confidence claim. Readiness, input, first reply
and exit remain explicit no-regression checks; do not trade them off silently.
Freeze concrete no-regression tolerances from baseline variability before A/B.

## Bounded collection and isolation

Use task-private HOME/USERPROFILE, platform/runtime/scratch roots outside the
checkout on the main filesystem, not the small /tmp or XDG runtime tmpfs. Do not
inherit provider credentials, developer plugins, source overrides or configuration.
Keep baseline/candidate environments independently identifiable; verify loaded
module origins. No concurrent tests, builds, reviewers or samplers during timed
collection. Stop on failure, preserve partial evidence, diagnose before retrying.

Persist completed sample receipts atomically; restart validates the frozen plan,
source/environment/observer identities and completed receipts, never silently
mixing versions or repeating completed samples. An interrupted active sample is
invalid evidence and must remain recorded. Bound traces/output and scratch use;
keep only task-owned receipts/seeds and failure diagnostics, never delete prior
G18 evidence. Validate actual child settlement before reclaiming its files.
Only a controlled pause after a complete A/B pair and settled owners is resumable;
failure/crash evidence is terminal, not a checkpoint to roll back. Record segment
boundaries; never pair samples across pauses. Any segment warmup policy is frozen
upfront. This pilot work must specify exact input scripts, frame witnesses,
source/wheel/observer/seed hashes, argv, geometry and deadlines before collection.
Reject cumulative stale idle, incomplete frames, kernel echo and history-only
draft matches. Record actual input send times and loading/ready classification.

## Implementation and verification gates

1. Run focused existing startup/terminal baselines before production changes.
   Validate collector witnesses with negative controls and fake-clock tests.
2. Diagnose import and synchronous preparation costs separately; optimize the
   largest one or two demonstrated blockers with narrow ownership-preserving edits.
3. Reuse existing deterministic regressions and fill optimization-specific gaps
   for loading text/paste, blocked submit,
   resize, attach/draft preservation, initialization failure, early quit/EOF/Ctrl-C,
   cleanup cancellation, and exactly-once first submission. Image paste during
   loading must not allocate resources or lose the existing draft.
   Loading `/quit` plus Enter currently remains a blocked draft; early exit uses
   Ctrl-D, EOF or Ctrl-C. Preserve this behavior. Any offloaded read must settle
   before releasing its resources and cannot publish after closing; test its
   late completion explicitly. If completion loading moves, validate first Tab
   and local/extension command semantics, not just a synthetic model reply.
4. Run affected checks and paired measurements. Three independent views cover
   architecture/ownership, measurement validity, and interaction/lifecycle.
   Fix findings, re-review affected results, commit with `Refs #578`, and retain
   an explicit per-requirement delivery audit. Do not mark this goal complete
   on design, instrumentation, or a small passing test subset alone.

## Initial review and regression evidence

Three independent read-only design views completed: architecture and lifecycle
approve baseline work; measurement identified three pre-freeze conditions
(entrypoint/synthetic separation, concrete frame/input witnesses, controlled
pair-boundary resume). Those conditions and compatibility refinements are now
incorporated above; full frozen protocol and implementation remain to be reviewed.

Pre-production-change focused baseline: 38 passed, including existing Coding
screen-first ownership, HarnessTUI startup host, shared CLI terminal contract and
Linux POSIX terminal restoration. Report:
`/var/tmp/loushang-interactive-v1.z5O6F5/startup-baseline.xml`. This is correctness
evidence, not a latency sample. Timed collection starts only after reviewers and
tests have finished.

## Initial source pilot — diagnosis only

One uninstrumented fresh ordinary `python -m loushang.coding.cli --tui`
launch on Linux, private empty project/configuration, 100 columns by 30 rows:

| Observation | Seconds |
| --- | ---: |
| Spawn to first completed visible screen | 4.6833 |
| Loading draft write to visible composer echo | 2.5919 |
| Spawn to ready observed after echo (upper bound) | 8.5816 |
| Quit to successful exit/drained terminal | 1.1189 |

The draft was sent while the completed visible frame still said Loading session,
at spawn +4.8185 seconds; terminal ECHO/ICANON were already disabled. The same
draft survives attachment, can be cleared, and normal quit restores terminal
modes. Report and bounded terminal output:
`/var/tmp/loushang-interactive-v1.z5O6F5/pilot-01/`.

This is one source-tree pilot, not an installed A/B baseline or a performance
gain. Ready is currently observed sequentially after echo, so it is only an
upper bound; the final observer must timestamp independent witnesses. Four
negative controls pass for partial frames/kernel text, stale pre-input idle,
erased history and ready status replaced by loading. The observer reuses existing
completed-frame replay; its own detection overhead is included in these times.

A separate cProfile run completed and preserved
`/var/tmp/loushang-interactive-v1.z5O6F5/profile-01/startup.pstats`. Instrumentation
substantially slows startup and must not be pooled with uninstrumented samples.
It identifies two candidate investigation areas:

- Entry import chain: the application module import accounts for about 6.66
  instrumented cumulative seconds, including resource catalog, Session/runtime
  and presentation dependencies. Nested times overlap and must not be summed.
- After first render: the synchronous `_create_agent_session` invocation takes
  about 5.22 instrumented seconds; installed distribution evidence resolution is
  a major nested contributor. Five evidence resolutions include 6,595 recorded
  path resolutions and repeated package-to-distribution metadata enumeration.
  These are dependency-origin checks, not optional model network calls.

At that pilot, no production optimization had been applied. The next decision was whether the
observed work can be reduced while preserving fresh import-origin and plugin
admission evidence, rather than hiding it behind first render or weakening the
checks. Do not sum asynchronous profiler cumulative times as wall time; use
external paired witnesses for the eventual improvement and non-regression claims.

## Installed harness and first candidate progress

An independent baseline environment is now available at
`/var/tmp/loushang-interactive-v1.z5O6F5/install-a`. The wheel is
`wheels-a/loushang-0.1.0-py3-none-any.whl` under that task root, SHA256
`3dccc0efa64a967a60606e58eff9bf0cc132d5df08f58866cbbb50be1ea3a99b`.
Existing G18 verifiers matched all 1,324 package files against `7f4b27f4`,
installed bytes, generated console wrappers, CPython 3.11.15 and the 40 locked
non-Product dependencies. Default uv cache lacked coverage; installation was
completed offline from the existing G18 cache, without changing dependency pins.

The synthetic child installs a stdlib-only import hook before running the actual
installed console wrapper. It does not preload Product modules or call an
internal alternate CLI. When the real Agent module loads, the hook supplies the
existing explicitly synthetic transport seam; Session.prompt entry/return is
observed separately. Registry/model selection, construction, persistence, input
and rendering remain real. Network connection/DNS calls are rejected. The trace
is exclusive mode 0600, at most 16 records × 2 KiB, and records only synthetic
input digest/length, module origins and local phase order. Such samples remain
instrumented diagnostics until the full protocol is frozen and reviewed.

- `synthetic-smoke-a1` completed a new session, loading draft/attachment, exactly
  one model input, visible reply, prompt return and terminal restoration. It was
  the first launch of this installation and is not a warm performance baseline.
- `seed-03` was created through the baseline SessionManager with 16 synthetic
  user/assistant pairs and a fixed `resume-project` cwd. Journal SHA256:
  `f4262e4f0b9cd72952a91932b1f6a2e8faa01ec8a80b23c80db7229283803989`.
  Two earlier seed attempts closed persistence successfully but failed the helper
  report's Session ID accessor; they remain failed artifacts, not valid seeds.
- `resume-smoke-a1` revealed an unsupported scroll-region sequence in the old
  observer. Added actual DECSTBM/reset replay and rejection tests; did not relax
  the witness to cumulative text. The focused new/old observer regressions pass:
  19 passed, 230 deselected. Historical frozen G18 reports are not reclassified.
- `resume-smoke-a2` then completes actual explicit resume, visible last history
  sentinel and retained loading draft, exactly one new model input, reply,
  prompt return and clean terminal exit. The pilot restores a journal-only copy;
  it does not establish a warm persisted Store-head/cache scenario.

The source candidate optimizes RECORD path processing in
`harness/resources/plugins/distribution_evidence.py`. An initial per-candidate
directory-stat cache was **rejected by architecture review**: a higher ancestor
could become a symlink while a descendant inode stayed unchanged. The new
custom-locator regression first failed against that candidate. The corrected
implementation caches only lexical prefix strings and freshly checks **every**
ancestor and leaf for each record. Complex paths retain Path.resolve semantics,
Windows uses the original path, and later origin/fence reads remain uncached.
Architecture re-review approves this corrected boundary.

Verification: the complete focused Plugin infrastructure plus observer negative
controls passed, 193 tests, JUnit `record-path-regression.xml` under the task root.
A separate RECORD-only microdiagnostic over 1,342 installed RECORD paths retained
six pairs after one declared warmup pair: original mean 0.27057 seconds versus
candidate 0.19170 seconds, approximately 29% less time, with equal resolved sets
and all six candidate pairs faster. This is **not** a startup improvement claim.
The single source candidate smoke still shows a 2.477-second loading echo; its
difference from the original pilot is not reliable evidence of improvement.

Remaining work still includes independent readiness/echo timestamps, frozen
pair/checkpoint protocol and resume seed receipts, earlier real first frame,
additional responsiveness optimization where demonstrated, loading interaction
guards, paired startup/first-turn/no-regression measurements, final three-view
review, affected quality gates and local commits. This goal is not complete.

## CLI import boundary candidate

The architecture-reviewed package-local lazy export facade is implemented in
`harness/cli/__init__.py`. Its 190 public names retain their original order and
owner-module identity, with the original imports exposed to static type checking.
Only successful resolutions are cached. Real dependency import errors propagate;
unknown attributes raise AttributeError so Python's explicit submodule import
fallback continues to work. Directory listing does not load optional modules.
Consumer-side replacement and restoration remain supported; this does not promise
unchanged timing of incidental eager import side effects or owner-side patches.

Cold-process facade checks and existing profile/argument/launch tests passed
24 tests before the additional submodule and restoration controls. This proves a
compatibility/import boundary, not an interactive startup improvement. The actual
Coding application still imports bootstrap and multiple command implementations
before constructing the screen. After the screen starts, the runtime's session
builder still invokes synchronous `_create_agent_session` on the event-loop
thread. Further work must reduce or split those concrete steps; offloading the
whole runtime would require a separate thread-ownership and settlement design.

## Independent observer follow-up

Schema 3 independently observes first frame, ready and initial echo across every
completed frame, including multiple frames received in one snapshot. Such frames
share the snapshot time; no sub-read precision is inferred. The measurement
review accepted the independent timestamp correction for pilot use, but required
stronger stale-draft, loading-classification and observer-overhead boundaries.
The pilot now rejects pre-existing draft tokens and saturated terminal buffers,
labels loading only as the last observed screen state, and replays immutable
snapshots outside the terminal reader lock. Startup replay time/count are reported
separately; timestamps are taken before decoding, and decoding can delay the next
observation/input. These costs must still be bounded before protocol freeze.

The observer negative controls passed 14 tests. Baseline installed synthetic
smoke `witness-v3-smoke-a1` completed a real new session, exactly one model input,
visible reply, prompt return and clean exit. It observed first frame 5.6437 s,
initial echo 2.1905 s, independent ready 9.1553 s and first reply 0.3452 s. This is
another harness smoke, not an A/B result; neither Product candidate is installed
in that baseline environment. The replay-cost counters were added after this
smoke and are not retroactively attributed to its report.

## Declared distribution metadata candidate

The next profile-led optimization avoids repeated whole-environment package
mapping enumeration when every freshly discovered same-name installation has a
valid, nonempty `top_level.txt`. Architecture design review approved this narrow
route instead of copying Python-version-dependent RECORD inference. Only default
readers use it; missing, invalid or exceptional declarations fall back to the
original mapping reader. All same-name versions contribute before version
selection. RECORD paths, editable origins and subsequent fences remain fresh.

The intended exception-scope change is explicit: corruption of an unrelated
distribution no longer fails this declared-only lookup. Exact candidate identity
and origin verification remain authoritative; this is not evidence reuse.
Injected readers retain the previous behavior. The baseline wheel declares
`loushang` in its `top_level.txt`, so this path applies to the actual installation.

The new structural regression first failed (1 failed, 6 passed) because the old
implementation enumerated unrelated distributions. The complete Plugin tests
then passed 196 tests after implementation. A local metadata-only diagnostic
with two same-name installations and six alternating pairs after a warmup found
identical package sets: global mapping mean 0.078858 s, declared lookup including
fresh named discovery 0.000982 s. This isolates metadata cost only; it is not an
installed startup A/B result or proof of responsive input. Focused code review
and a current-source interactive smoke followed.

Code review identified that default metadata readers still delegate to custom
`sys.meta_path` distribution finders, whose named and unfiltered discovery may
differ. The fast path now also requires no nonstandard distribution finder;
otherwise it retains global mapping authority. A real named-only finder regression
checks that its declared package does not gain admission. Separate tests cover
each custom-reader gate independently.

Source smoke `declared-candidate-smoke-01` completed normal startup and exit:
first frame 4.1507 s, echo 2.3387 s, ready 7.7157 s. This is not paired acceptance,
and input remains too slow. Its observer replayed 12 frames in 1.3004 s total
(maximum 0.1239 s per frame); that diagnostic establishes significant remaining
observer overhead. Incremental replay is required before final measurement, not
an arithmetic subtraction of this overhead from Product startup times.

Architecture re-review approved the corrected declared-only implementation;
its focused tests passed 10 cases after the finder fix. The observer now retains
FakeScreen state and replays only newly completed frame segments. Existing
one-shot callers retain the original default behavior. Focused new/old observer
tests passed 26 cases (230 deselected), including incremental/full equivalence
for scroll regions, cursor movement and style. Offline replay of retained new
and resume smoke outputs matched the complete one-shot screen exactly (20 and
42 frames respectively). Those checks establish replay compatibility, not a new
Product latency result. The incrementally replayed observer still needs fresh
PTY validation and the final collection protocol remains unfrozen.

## Installed candidate and remaining bottlenecks

Incremental observer PTY smoke `incremental-candidate-smoke-01` completed with
12 startup frames taking 0.1117 s of replay, versus the earlier 1.3004 s. Source
input echo still took 2.2327 s. A fresh instrumented profile in
`profile-candidate-02/startup.pstats` identifies RECORD processing as the remaining
dominant nested construction work: five resolve_all calls total 3.4209 instrumented
cumulative seconds, including 2.4875 seconds in `_resolve_record_path`. These are
overlapping diagnostic spans, not additive wall-clock metrics. Whole-environment
metadata enumeration is no longer the dominant contributor.

Source discovery sees both the editable venv distribution and a source-directory
distribution, so it is not a substitute for installed evidence. A separate
candidate environment is now installed at `install-candidate-01` under the task
root, using the baseline CPython 3.11.15 and the same 40 hash-pinned dependencies.
Its wheel SHA256 is
`771b9373f3159303462aa4271ec94bb35b45cbc2d31ae8c164d091fdcd396160`;
the existing source/wheel and install/entrypoint verifiers passed, with receipt
`verify-candidate-01/receipt.json`. This is a verified working-tree candidate,
not yet an immutable committed-source acceptance baseline. Installation A is
unchanged.

Installed synthetic new-session smoke `incremental-installed-candidate-01`
completed first frame 7.9064 s, echo 1.5229 s, ready 10.0037 s, first reply
0.2086 s and clean exit. It is this installation's first cold launch, not a
comparison against warm baseline A. Explicit resume smoke
`incremental-installed-resume-01` completed first frame 5.1253 s, echo 1.3033 s,
ready 7.1886 s and first reply 0.2791 s. Both retained the draft, observed exactly
one synthetic model input plus prompt return, and restored the terminal. The
original resume seed SHA256 remains unchanged. These observations are not paired
acceptance, and neither establishes nonblocking input.

Architecture review recommends the next earlier-screen change be a local Coding
entry split: shared lightweight startup-route grammar/launch-plan/eligibility;
early entry only when run_cli is not explicitly materialized/replaced; one screen
adapter that can start before application bindings exist; and application reuse
of that existing screen. Management dispatch priority and custom runner identity
must remain unchanged. Moving imports alone may improve first frame while making
loading input worse, so both metrics must remain acceptance requirements. A broad
facade rewrite or an outer generator around synchronous construction is not the
approved substitute for that boundary.

## Early-entry implementation — responsiveness not accepted

The local Coding entry split is implemented: `startup_route.py` owns the shared
canonical launch plan and eligibility; the ordinary entry preflights the same
parser, while explicit/materialized run_cli bindings retain their path. Command
family tokens remain positional message input during this preflight and cannot
claim a conversation screen. Tests cover all six family spellings with the
supported leading cwd forms. `screen_startup.py` can now create the single screen
before application bindings exist, then hand off through a private callback in
the real application. Runtime ownership and cleanup remain in the same adapter.

Cold-process checks establish that importing/selecting this screen path does not
load `coding.cli.application`, `coding.bootstrap` or `coding.ui.mode`. Lifecycle
review found no duplicate screen or disposal owner and requested two added tests:
application import failure after the first frame with no runtime, and the real
application's single private handoff. These are implemented. Screen lifecycle
tests pass 38 cases; targeted route/CLI help/version/entry tests pass 47 cases
(243 deselected). The review does not establish responsiveness during synchronous
module imports.

Source smoke `early-entry-smoke-01` demonstrates the unresolved tradeoff: first
frame 1.9121 s, input echo 4.1482 s, ready 6.8558 s, clean exit 0.9697 s. The earlier
incremental source smoke observed first frame 4.3354 s and echo 2.2327 s. These
are exploratory observations, not controlled paired acceptance, but they clearly
do not justify calling this a responsive-input success. Moving synchronous work
past first frame is insufficient. This working-tree candidate remains under
development and must not be delivered as the completed performance optimization;
reduce or split the actual post-frame import/construction work before acceptance.
The previously installed candidate wheel predates this entry change.

## Loading-only scheduling boundary — proposed, not activated

Two independent architecture/lifecycle reviews agree that a loading-only worker
is possible on Linux, but reject wrapping the existing screen runner in a thread.
Its normal return restores/drains the terminal and loses local parser state;
attach also occurs after Product code has already mutated the app. This proposal
keeps all Product imports, Session/plugin ownership, ContextVars and cleanup on
the existing main thread. It is not an embedded-to-hosted mode switch.

Required ownership protocol before activation:

1. Main acquires the sole TerminalSession lease and prepares loading rendering
   dependencies. The worker borrows exclusive input/render/protocol-poll access;
   it never owns final restoration or runs Product callbacks.
2. Worker owns only the loading app/composer, native byte-reader state, InputReader
   (including incomplete paste/escape/Kitty state), and TuiRuntime render baseline.
   Main may not read or mutate this app while that ownership is outstanding.
   Submission, clipboard images, completion and Product surface actions stay gated.
3. Product preparation remains on main. Before calling run_coding_tui (therefore
   before any app labels/history/completion/presenter writes), request transfer.
   Worker stops acquiring bytes, routes already-consumed complete events, retains
   incomplete bytes/parser state, removes loop-bound callbacks, and returns the
   entire screen state. This is TRANSFER, not normal EXIT; no flush, drain, finish
   rendering or terminal restore occurs.
4. Main confirms the actual worker termination/join before touching returned
   state, installing fresh main-loop wakeups or attaching Product callbacks. The
   ready runner consumes the same input/parser/render/terminal state without
   repeating welcome or acquiring another lease. UI binding after transfer must
   itself be measured for blocking time.
5. Quit/EOF in worker shows closing and sends a thread-safe cancellation request.
   Main synchronous preparation must return before that cancellation can run;
   immediate visual acknowledgement is distinct from completed shutdown. Worker
   never races main to restore the terminal. Failure/quit paths join the worker,
   settle Product cleanup, then release the one lease and drain buffered output.
6. Worker first-frame, quit/failure and completed-transfer notifications use
   thread-safe futures/messages only, never cross-loop asyncio Task/Future access.
   No runtime/session enters worker. The ready handlers retain the current main
   preparation ContextVars forwarding contract.

The first supporting primitive is an additive, explicitly owned POSIX input
reader. Unlike the legacy scalar read, it tests readiness before each bounded
read (up to 64 available bytes) and
retains an incremental UTF-8 decoder across cancellation and joined handoff to
another loop. A nonblocking ownership lock rejects overlapping reads. It borrows
the fd and owns no terminal lease; malformed input/EOF uses replacement decoding.
The existing stateless/blocking input APIs are unchanged. This reader is not yet
wired into Product startup and does not itself establish responsive input.

Before worker implementation is accepted, tests must prove split UTF-8 and paste
survive transfer; pending input is routed exactly once; quit beats simultaneous
ready; import/worker failures and repeated cancellation settle; terminal enter/
restore happen exactly once; no app access overlaps owners; and no worker import
lock stalls on Product initialization. Windows/macOS retain the existing path
until separately verified. The whole proposed protocol still requires final
design review; no worker is activated by the current reader addition.

### Three-view design follow-up

Architecture and lifecycle reviews permit small-step implementation of the
explicit transfer protocol, not activation of a thread wrapper around the old
runner. Measurement review requires the full worker-to-main blackout in the
response envelope. The additive input primitive passed 12 focused POSIX tests;
that does not prove real thread transfer or performance.

The first implementation must carry an irreversible closing/failure record,
checked again after join and before main touches the app. A completed read task
must have its result collected even when stop wins the scheduling race. One
reader instance owns the fd throughout; neither the legacy reader nor terminal
drain may run concurrently. Partial parser state retains its original idle
deadline instead of restarting ESC timeout at transfer.

Submission admission needs a separate input boundary, not merely ready model
state: worker-consumed bytes/events retain loading classification; a sequence
started before transfer remains loading until resolved. Readable queued input
must also pass the loading router before submission is armed. Continuous input
must not prevent stop/join: hand off the backlog obligation and keep the main
input router in loading mode until that obligation is discharged. Never discard
draft text or reinterpret paste newlines as submissions. The precise arming
linearization and fd-backlog race must be proven by tests before activation;
physical keystroke time cannot be inferred from byte-read time alone.

Proposed responsiveness acceptance is mean short-edit echo <=100 ms and maximum
<=250 ms, including transfer, not simply improvement over multi-second stalls.
The collector must issue edits on a fixed schedule independently of previous
echoes, exercise real synchronous preparation and import work, and send a first
turn shortly after observed ready without a warmup turn. Freeze the exact input
schedule, transfer/join and exit deadlines, and first-turn non-regression limits
before final paired collection. These remain pending protocol parameters, not
fulfilled acceptance claims. No Windows/macOS performance assertion is implied.

### Loading component implementation and lifecycle review

The unactivated `LoadingSurfaceWorker` now borrows the screen on a real thread
while Product preparation remains on main. Its joined transfer retains the
incremental byte decoder, InputReader, render runtime, terminal context and
pending input deadline; it neither restores nor drains the terminal. Input
received by a completed read is collected even when the stop request wins.
Loading input policy lives in `loading_input.py`, shared with the existing
startup host without importing that coordinator from the worker.

Real-thread regressions cover input echo while main executes synchronous Python,
partial UTF-8 and paste across join, submission/clipboard gating and closing
priority. Lifecycle review found an idle-Escape redraw omission: parsing cleared
the draft but did not request another frame. A regression failed before the fix;
normal and idle-flushed events now share the same route/render handling. The
focused worker, startup-host and input-reader suite passed 20 tests after that
fix. These are component correctness results, not startup latency evidence.

CLI activation, queued-input admission during handoff, one-lease settlement and
installed paired responsiveness measurement remain required and incomplete.

The main runner now accepts a single-use `ConversationScreenContinuation` after
the previous owner has joined. This carries the parser, runtime, terminal context,
input reader callback and original idle deadline; the outer caller keeps the
terminal lease through settlement. The continuation path skips terminal entry,
runtime replacement, terminal reconfiguration and welcome replay. It does not
itself authorize submission or start/stop the previous owner.

Real worker-to-main tests preserve split UTF-8 and incomplete bracketed paste,
keep Enter loading-gated, and reject reuse of a consumed continuation. Tests
forbid runtime construction, terminal acquisition and welcome/configuration calls
on this path. The first combined run passed 62 tests (worker, shared runner,
startup host and Coding startup), with the two changed implementation modules
also passing mypy. CLI selection and queued-input arming remain unimplemented;
these results do not establish end-to-end performance or full lease cleanup.

Architecture review identified initialization outside the runner's cleanup
boundary. Size discovery, router construction and surface promotion now execute
inside the same try/finally as the input loop; settlement handles a missing router
and restores prior app bindings. Regressions inject failures before and after
router acquisition, retain the original exception, check exactly-once cleanup,
and reject continuation reuse. An expired transferred parser deadline is also
tested without restarting its timeout. Deadline tracking now applies to ordinary
runner input too, so a protocol wakeup cannot prematurely flush a pending escape
sequence. This is an intentional shared-runner behavior change, not solely a
continuation implementation detail.

### Input admission after transfer

The additive admission path separates Product attachment from enabling submit.
When configured before attachment, startup keeps the loading router and loading
status until the main runner reaches a boundary between complete event batches.
At that point no read task exists: InputReader must have no pending sequence,
the native UTF-8 decoder must have no partial character, and a non-consuming fd
readiness check must find no queued input. Only then does startup arm the ready
router and request the ready frame. Input arriving after this observation belongs
to the next admission interval; this is explicitly not a claim about physical
keystroke timestamps. Continuous queued input keeps the gate closed without
draining or discarding draft content.

The reader rejects boundary inspection during an active read. A real joined
worker/main-runner test queues `draft` plus Enter before attachment, verifies
that no submission occurs and the draft survives, then sends a new Enter after
arming and observes exactly one Product action. Focused tests also cover pending
UTF-8 and parser state blocking admission. Default startup retains its previous
admission behavior; the deferred path is not yet selected by Coding CLI.

Lifecycle review found that attachment during an empty input wait could leave
the gate closed until another keystroke. Continuation admission now opts into
returning from the input helper on a render wakeup, collecting any completed read
first and joining cancellation before the next boundary check. Other callers
retain the helper's existing default. The real transfer test now also covers
delayed attachment with no backlog and no input before admission opens.

### Main-loop startup coordinator

`ThreadedScreenStartup` now coordinates one outer terminal lease. Product prepare
starts on main after the loading first frame. The Product UI hook requests
handoff and waits for the main input owner; the coordinator first stops and
actually joins the loading thread, then resumes the existing preparation task
under the shared runner. No second prepare task is started. Closing and worker
failure wake the main loop through a thread-safe callback.

Join collection is shielded from repeated cancellation and retries only the
specific still-alive join timeout, not a TimeoutError raised by the worker itself.
The outer lease remains held through join and startup settlement. Tests cover
synchronous main preparation with loading echo, main-thread UI binding/submission,
normal completion, preparation failure and loading Ctrl-C cleanup ordering. This
coordinator is not yet selected by Coding CLI; lifecycle review and actual
adapter acceptance remain required before activation.

Coordinator review required preserving combined worker/cleanup diagnostics and
removing an executor-failure ambiguity in join ownership. Collection now polls
nonblocking `Thread.join(0)` on main and yields between still-alive results; no
executor submission participates in the ownership proof. Startup aggregates a
primary failure with settlement failures, and checks known closing state before
starting Product acquisition. Regressions disable executor submission on the
normal path and require both worker and Product-cleanup leaf diagnostics on the
combined failure path.

### Linux CLI activation and first real probes

This milestone supersedes the earlier unactivated-component status above.
Coding's screen-first adapter now selects the coordinator for Linux with native
terminal input. Windows/macOS, redirected input and stream doubles retain the
existing runner. The adapter awaits `before_product_ui()` before importing and
calling the Product UI mode, so no shared-app binding overlaps the loading owner.

Two isolated real source-entry PTY probes completed, with draft echo during
loading, independent ready observation and normal terminal-restoring exit:

| Diagnostic sample | First frame | Initial echo | Ready | Exit |
| --- | ---: | ---: | ---: | ---: |
| `threaded-entry-smoke-01` (new) | 2.2143 s | 0.0078 s | 7.8981 s | 0.9682 s |
| `threaded-resume-smoke-01` | 1.8859 s | 0.0132 s | 7.4526 s | 1.3697 s |

Both reports are under `/var/tmp/loushang-interactive-v1.z5O6F5/`. The resume probe
copies the existing frozen seed. These single, non-paired source samples show
that loading input is no longer blocked for seconds in the observed interval;
they do not prove continuous-typing or handoff latency, installed performance,
first-turn non-regression or the final acceptance envelope. No synthetic model
turn was run in these two probes. Installed paired collection, adapter review,
full lifecycle acceptance and final commits remain required.

Adapter ownership review approved the Linux wiring. Its scope does not turn
the existing stream-double failure tests into threaded-path fault coverage.
The platform-selection and existing adapter/coordinator run passed 50 tests.

An independent installed candidate, `install-candidate-02`, uses CPython 3.11.15
and the same 40 hash-pinned dependencies as A. Source/wheel and installed-byte
verification passed for wheel SHA-256
`259b079d1fea0cd89ce2ef9f167678a04b74b803f493c252c96fd7be075ba4a8`.
The old A and candidate-01 installs remain unchanged. Installed synthetic probes
through the real wrapper completed with exactly one model-input record, visible
reply, prompt return, and normal exit:

| Diagnostic sample | First frame | Initial echo | Ready | First reply |
| --- | ---: | ---: | ---: | ---: |
| `threaded-installed-smoke-01` | 3.6770 s | 0.0129 s | 10.8138 s | 0.1900 s |
| `threaded-installed-resume-01` | 2.2474 s | 0.0026 s | 7.5139 s | 0.2498 s |

The first sample is the first startup of a fresh install. These are still
non-paired diagnostics, not percentages of improvement or a first-turn
non-regression claim. Neither samples continuous edits through the handoff.

### Continuous editing diagnostics and observer review

Exploratory fixed-cadence probes send 100 edits, 100 ms apart, on an observer
thread independent of echo detection. The initial replace-draft workload
(`threaded-edit-train-01`) observed 99/100 markers; the missing marker was near
ready and cannot distinguish overwritten intermediate display from lost input.
It is retained, not accepted as complete latency evidence.

A cumulative two-character append workload (`threaded-append-train-01`) observed
all 100 prefixes, mean 10.9 ms/max 132.7 ms. A later baseline diagnostic
(`baseline-append-train-01`) observed mean 374.5 ms/max 2239.1 ms. These used
different pre-freeze sender anchoring and broad whitespace matching, so they
must not be promoted into a formal pair or improvement percentage.

Measurement review required a main-thread DRAFT-send anchor, retaining actual
sender-start lag, explicit overdue policy (catch up, but invalidate sender
scheduling above 25 ms lag), and composer-only matching. The observer now joins
only full-width 99-column composer rows followed by two-space continuation rows
in the fixed 100-column terminal; it preserves content whitespace and checks the
loading/idle footer. Unified finalization preserves train rows, write failures
and unsent counts even if initial echo fails. Negative controls cover delayed
sender start, injected spaces, history tokens, invalid continuation rows and
write failure. Reports separate observations before ready, pending across ready,
and sends after ready; ready is still an external frame observation.

100 observed prefixes need not mean 100 independently rendered revisions. A
schedule spanning ready does not prove an edit fell inside every short handoff
interval. Formal comparison still uses each startup, not individual keystrokes,
as its independent paired unit. Current observer changes require remeasurement;
the old diagnostics remain unchanged.

The strict observer pilot `strict-append-candidate-01` completed on the verified
candidate-02 installation: 100 attempted/written/observed prefixes, no missing
echoes, valid sender schedule (maximum lag 1.4 ms), mean echo 11.7 ms and maximum
114.1 ms. Its first frame/ready were 2.1395/7.2974 seconds. Fifty edits echoed
before observed ready and fifty were sent after it; none remained pending across
that observation. This validates the current fixed geometry and sender mechanics
but does not prove an edit landed in every short transfer interval.

`measure()` failure-path regressions now inject initial echo timeout, with and
without sender write failure, and require the on-disk report to retain attempt
rows, unsent counts and failure causes after the sender has terminated. Report
`missing_count` explicitly describes attempted edits without observed echo,
including failed writes; it is not synonymous with successfully sent input loss.

Coding's nine adapter lifecycle scenarios now run both on the original loop and
on real loading threads with native pipe input, for both early-entry and prepared
binding routes. Checks retain runtime disposal/output-after-restore ordering and
both diagnostics on combined preparation/cleanup failure. Buffered failure
summaries may be rendered before restore; original output is still drained only
after restore. The combined adapter and observer suite passed 88 tests. Terminal
mode is a test lease in these fault cases, so actual PTY success probes remain
separate evidence rather than being claimed as full real-terminal fault coverage.

### Checkpoint collection implementation status

`scripts/dev/_interactive_campaign.py` now reuses G18's existing locked, durable
safe-pause protocol. It records each attempt before invoking the probe, binds the
finished raw receipt by hash, and refuses to overwrite an existing sample path.
Only a published safe pause resumes; failed/in-flight campaigns remain failed.
Resume consumes the pause before callbacks and checks the immutable plan and
existing evidence. Process completion alone is insufficient: edit observations
also require valid scheduling and complete sent/observed counts. Resumed segments
retain the existing explicit exclusion from automatic performance acceptance.

The measurement re-review found four publication boundaries that are now fixed:
pause requests wait for both sides of a case pair; completion rechecks every raw
receipt, including earlier samples; the sample directory is synced before valid
publication; and a mandatory case-aware observation validator runs before that
publication. Directory-sync failure leaves the campaign failed and the sample
invalid, rather than publishing a resumable successful observation.

Ten collector-core tests cover those boundaries, safe pause/resume without
replay, invalid sample rejection, and changed-plan/changed-receipt refusal.
Together with the input observer tests, 37 tests passed. The measurement reviewer
approved these four fixes with no remaining collector-core blockers; approval
does not extend to installed campaign wiring or performance acceptance. Actions
syntax validation also passed with actionlint (shellcheck disabled).

The observer now records input-phase frame processing separately from pre-input
first-frame replay. This avoids treating pre-input replay cost as measured input
latency; the new metric still requires a real pilot and a frozen validity budget,
and must not be subtracted from observed latency to manufacture a faster result.

The new probe and collector tests have explicit G18 selection, lint and execution
ownership. Actual installed campaign wiring, observer budgets, protocol freeze
and real pause/resume preflight are
still pending; these core tests do not establish those deliverables.

### Workload validator and broad-gate diagnosis

The concrete `validate_workload` now checks four installed cases against the
plan's installation/seed and observer budget, rejects nonfinite timing data,
recomputes the 100-edit fixed-cadence receipts and phase summaries, and verifies
the synthetic input digest plus ordered prompt entry/model input/prompt return.
Review fixes preserve legitimate ready-before-input turn samples while rejecting
ready-before-first-frame, reply-before-draft, and nonmonotonic cumulative-prefix
witnesses. Timing comparisons use fixed absolute tolerance, not uptime-relative
tolerance. Slow but valid observations remain evidence, not automatic failures
of sample validity. Forty collector/validator tests passed. Final validator
re-review approved the logic with no remaining blockers; real installed wiring
is still pending, and the plan's observer budget has not yet been frozen from a
pilot. This approval is not formal performance acceptance.

The broad gate was interrupted in Coding after sustained failures: 250 failed,
1317 passed, 16 skipped, 20 deselected, with the suite incomplete. Its first
failure was an obsolete entrypoint AST allowlist; the precise allowlist now
includes the two explicit early-screen boundaries, without admitting Product
implementation imports. Subsequent representative failures report ENOSPC under
`/run/user/1001/loushang/pytest-runs`, a 164 MB runtime tmpfs, despite 6.3 GB free
on the main disk. Setting TMPDIR alone does not relocate the repository pytest
wrapper's leased runtime. Further managed gates must explicitly set
`LOUSHANG_RUNTIME_DIR=/var/tmp/loushang-interactive-v1.z5O6F5/check-runtime` as well
as TMPDIR. The original process has exited; 39 representative entrypoint,
multi-agent and workspace cases passed on that main-disk runtime. The Coding
offline gate has been restarted there, without repeating already passing AI
checks.
Do not classify all 250 failures as environmental without revalidation.

### Installed campaign binding (under review)

The collector now exposes `--plan`, `--output`, `--resume` and `--pause-after`
through `scripts/dev/_interactive_campaign.py`. `collect_installed` invokes the
existing real installed PTY observer, preserving separate edit and synthetic-turn
workloads and the explicit resume seed/workspace. Entry, every sample and final
completion validate the declared source commits/wheels, installation receipts,
dependency/interpreter contracts, all observer helpers and seed hash. It reuses
the G18 provenance/installation verifiers; it does not introduce an alternative
wheel verifier or import Product into the observer before timing.

The plan must declare warm-installation bytecode policy: pre-sample verification
can warm metadata and filesystem caches, even though its duration is outside
the spawn clock. No cold-start claim follows. A frozen plan must contain `repo`,
`sources`, `wheels`, `installations`, `installation_receipts`, `helpers`, `seed`,
`seed_sha256`, `resume_workspace`, `verification_root`, `bytecode_policy`,
`max_input_observer_seconds` and the existing schedule fields. Source verification
requires clean committed Product files before a real campaign can start.

Forty-eight collector tests passed, including installed-binding case mapping,
pause/resume without replay, source/seed/helper/installation change refusal, and
restoration of the observer's import path. The installed boundary tests use
controlled verifier/probe doubles; they do not replace a real pause/resume pilot.
No frozen campaign plan or formal
performance sample has been published yet; the Coding offline gate is running
on main-disk runtime and timed sampling remains paused until it settles.

The first binding review required additional frozen inputs. The plan now also
contains `observer_identity` (checkout HEAD, interpreter hash/version/prefix,
dependency versions and locations), `bytecode_manifests` for both installations,
and `resume_workspace_manifest`. Loaded observer Product modules must originate
under this checkout's `src`; each sample is checked before and after execution.
Changing a clean observer HEAD, bytecode cache, or workspace is not a permitted
resume. Warmup must finish before freezing bytecode; resume never performs an
ad-hoc rewarm. The measured side is always the last installation verified before
its sample, avoiding an invariant A-then-B verification bias. Fifty-one tests
passed after these changes; binding re-review approved the corrections with no
remaining blockers. The bytecode seal covers installation directories only, not
OS page cache or stdlib caches outside the installations.

Use `--freeze --plan <configuration.json> --output <frozen-plan.json>` after
committing Product changes and completing the declared four-case warmup. The
configuration supplies `revisions` for A/B plus wheels, installations, seed,
resume workspace, verification root, cases, blocks, pairs and an explicit
observer budget. The tool derives all provenance receipts and manifests, then
revalidates them before publishing; it refuses an existing output path. It does
not select a threshold or perform an implicit warmup. Collection then uses
`--plan <frozen-plan.json> --output <new-campaign-directory>`, optionally with
`--pause-after` for a separate resume preflight. Fifty-four collector tests pass,
including plan derivation, invalid-budget refusal and existing-plan preservation.
Review corrections use a synced same-directory temporary file and atomic
create-only link publication, so a target created during verification is never
overwritten. Canonical A/B installation paths must differ, including symlink
aliases. Final freeze-helper re-review approved these corrections with no
remaining blockers; this does not constitute an actual frozen experiment or
performance acceptance.

### Remaining lifecycle findings

A read-only lifecycle audit identified two production fixes required before
performance acceptance: repeated external cancellation during loading join or
Product cleanup must remain cancellation, not become a cleanup-failure group;
resize after attach but before submission arming must reach the already-created
ready router under its Product ContextVars. Add deterministic regressions for
both, plus a real loading-worker resize-to-main handoff case. Existing real
UTF-8/paste/parser-deadline/backlog tests and threaded Coding disposal scenarios
remain useful evidence and need not be recreated.

Both production findings are now fixed: coordinator settlement distinguishes
deferred cancellation from actual cleanup faults, and the startup router delivers
unarmed resize to both loading and ready owners, retaining the captured Product
context. A real blocked worker plus blocked Product cleanup regression issues
repeated cancellation in both phases and requires joined cleanup before the
single terminal restore, with CancelledError rather than a failure group. The
synchronous-preparation regression now changes geometry from 100x30 to 111x33,
witnesses worker rendering before handoff, and checks the main ready router's
dimensions and preserved draft. Together with Coding adapter cases, 79 tests
passed. Lifecycle re-review approved both fixes and the new handoff coverage,
with no remaining must-fix findings in that review scope.

These production changes supersede candidate-02 as the current implementation.
Its diagnostic receipts remain historical evidence, not measurements of the
fixed candidate. Rebuild and verify a fresh installed candidate before any new
protocol freeze or formal A/B collection.

### Final architecture compatibility correction

Architecture review found that a preloaded/replaced `application.run_cli` could
be bypassed by the early TTY route, changing argv identity and adding private
keyword arguments to a historical one-argument runner injection. Early screen
selection now requires that the application module is not already loaded;
otherwise the original application delegation is retained. Normal cold startup
still takes the early route. A cold-process TTY regression replaces only the
application runner and checks original argv identity, returned status and no
screen-module acquisition. Final architecture re-review approved the correction;
the combined route/adapter regression run passed 120 tests. HarnessTUI and Coding UI
static gates passed Ruff and mypy (135 and 22 source files respectively). The
larger Coding run remains active; no passing gate is inferred from progress dots
alone. Architecture approval permits a local commit only after required gates;
it is not a paired performance acceptance result.

### Coding size-budget registration

The HarnessTUI runtime gate was stopped after a concrete architecture-budget
failure (1 failed, 838 passed, 8 deselected; incomplete suite). Coding core was
34,072 lines against the previous 33,985 limit. Relative to `7f4b27f4`, this
delivery adds exactly 101 Coding lines: CLI entry +15, application -29, screen
adapter +17, early route +98. Architecture review approved registering that
explicit delivery allowance: the new limit is 34,086, preserving the original
14-line slack. All files remain counted and every other partition limit is
unchanged. This is a budget increase, not a claim that the old budget passed.
The budget test and the interrupted gate's remaining architecture/Harness files
were rerun together: 179 passed in 496.57 seconds. This closes the known budget
failure and the interrupted suffix; the earlier 838 passes alone were not a
complete gate. Coding UI runtime checks have now started separately (their
static checks already passed). The broad Coding offline run remains active.

Harness and AppService full Ruff targets (`lint-harness`, `lint-appservice`) also
passed. Their remaining type/runtime gates are not implied by these lint results.
Coding UI runtime gate completed: 577 passed, 59 deselected, 211.14 seconds.
Harness/AppService type checks and then TUI offline unit checks are running in
sequence, using main-disk runtime and cache directories. The broad Coding offline
run is still active and must finish independently.

The Coding offline gate subsequently finished with exit code zero: 2,585 passed,
21 skipped, 20 deselected in 2,930.69 seconds. This revalidation used the main-disk
runtime and closes the earlier interrupted ENOSPC run; the original failures are
retained above. Harness and AppService type checks also passed, covering 682 and
86 source files respectively. TUI offline unit checks subsequently passed:
1,258 passed, 118 deselected in 26.28 seconds, exit code zero. The full Harness
runtime target is now running using the same main-disk private runtime.
Lightweight documentation governance passed six checks after the delivery-record
updates. Linux/POSIX native terminal, terminal-platform and render-contract
targets have started in sequence; they remain separate from timing acceptance.
That terminal sequence completed successfully: 12 native contract tests,
110 terminal-platform tests, and 179 render-contract tests (5,106 deselected for
the render-only selector). Hosting/AppHost gates and AppService runtime tests
are next in sequence; AppService's passing lint/type checks are not repeated.
Hosting subsequently passed its full gate: Ruff, mypy for 26 source files, and
385 runtime tests with 48 skips. AppHost Ruff and mypy (99 source files) passed;
its runtime tests remain active ahead of AppService runtime tests.

### Current installed candidate-03

After the lifecycle and runner-injection fixes, an offline wheel was built into
the new `wheels-candidate-03` directory and installed into `install-candidate-03`
under the task's main-disk root. It uses CPython 3.11.15 and the same 40 hash-pinned
dependencies as A (41 installed distributions including Loushang). Current-source
package inventory/bytes, installed bytes and generated entry wrappers verified.
The receipt is `verify-candidate-03/receipt.json`; wheel SHA-256 is
`6f5c34c3f9c46ff6dfa75a4013d1a91f14301aa5c842aca8b79e31f4668857c9`.
This is verified build/install evidence only: Product still needs a local source
commit and the experiment still needs warmup, budget freeze and paired sampling.
Old candidate installations and diagnostic receipts were not overwritten.

Foundation's selected offline gate completed with exit code zero: 106 passed in
96.94 seconds, retaining the standard non-live/skip-host-runtime selectors.
Harness and AppHost runtime gates remain active; AppService runtime follows the
latter. Platform-specific/installation/real-LSP workflow gates are not claimed
as locally completed by these results.

AppHost's main runtime suite completed: 1,373 passed, 12 skipped in 1,411.94
seconds. Its additional G8 (19 tests) and G9 (16 tests) evidence reports passed
both zero-skip pytest verification and manifest verification. The enclosing
`check-apphost` target is still running its G10 evidence step, so the complete
target is not yet marked passed.

G10 subsequently passed all 15 selected tests (12 deselected), zero-skip XML and
manifest verification, and the installed-console canary on
`posix-process-group-v1`. The enclosing AppHost target completed and advanced to
AppService runtime tests. This installed-console canary validates the repository
environment's command path; candidate-03 wheel provenance remains the separate
receipt described above, not an inferred wheel-only G10 result.

## Delivery audit before source freeze

This is an incomplete-delivery checklist, not a performance acceptance report.
The source candidate remains uncommitted at this checkpoint. `make plan-checks`
was refreshed after the final collector and compatibility fixes; its selected
check categories are unchanged. Already passing checks are not rerun merely
because the plan was regenerated.

| Requirement | Current evidence | Still required |
| --- | --- | --- |
| Real installed Linux new/resume startup | Baseline installation and candidate-03 installation have independent byte/entrypoint receipts; the fixed resume seed is retained | Commit candidate source; verify wheel against that commit; warm all four workloads and freeze the actual plan |
| Earlier screen and responsive loading input | Production early route, shared loading surface and input handoff are implemented; lifecycle and architecture reviews passed | Current-observer installed pilot, followed by paired first-frame and continuous-edit evidence |
| No first-turn/ready/exit regression | Synthetic transport isolates network IO; ordinary and synthetic routes have distinct witnesses and validation | Baseline-derived tolerances frozen before formal sampling; new/resume paired results for each boundary |
| Correct interaction and cleanup | Targeted cancellation/resize/runner compatibility tests and the recorded Coding, HarnessTUI, Coding UI and terminal gates passed | Final Harness and AppService runtime results; investigate any failures rather than treating partial output as a pass |
| Resumable collection | Durable pair-boundary checkpoint implementation and 54 collector tests passed; measurement review passed | Real installed safe-pause/resume preflight; keep its segmented evidence separate from uninterrupted acceptance |
| Reproducible delivery | Candidate-03 wheel and installation receipts, fixed dependency set, reviewed helper/source verification | Quiet-machine paired collection, summary with absolute savings and slower samples retained, final three-view evidence review and local commits |

The refreshed local plan explicitly defers platform/installation/real-LSP
Actions jobs (`tui_native`, `harness_native`, `host_runtime`, `windows_shell`,
`install`, `lsp`). The separately recorded local Linux native terminal checks
and installation receipts cover only their stated boundaries, not all of those
jobs. No remote, macOS or Windows acceptance is inferred.

Freeze/collection order is intentional: finish active correctness checks;
commit and verify Product bytes; run excluded installed pilots to establish
baseline variability and the input-observer budget; publish immutable plans;
exercise a separate safe-pause preflight; then run the two-block formal campaign
without tests/builds/review workers running concurrently. Keep all failed or slow
attempts and use new output directories for distinct experiments. Do not change
the observer, thresholds, source, installation or seed midway through a campaign.

### AppService gate failure pending isolated diagnosis

The complete AppService runtime attempt ended with 1 failed, 1,787 passed and
15 skipped in 1,321.15 seconds. The failing case was
`tests/coding/test_hosted_local.py::test_G16_PRODUCT_real_coding_retains_disconnected_work_and_recovers_both_scopes[False]`.
Its first-generation 30-second `asyncio.wait_for` watchdog cancelled the waiter
inside `command.wait_closed()`. Recorded phase offsets were: start 0.097 seconds,
ready-to-construct/interact 0.198, stop requested at 29.137, failure after finally
cleanup at 30.517. This does not isolate a 30-second cleanup failure: construction
and interaction had already consumed nearly all of the generation budget.

Harness was still running concurrently. A contemporaneous read-only resource
check showed 1,637 MiB total RAM, 2,838 MiB swap usage, substantial memory/IO
pressure, and the Harness process waiting in `folio_wait_bit_common`. These
observations justify a serial reproduction, not automatic classification as an
environment-only failure. Keep the original failure and timeout unchanged; wait
for the existing Harness gate to finish, then reproduce the failing case and its
discovery-enabled sibling without another gate running. Product/source changes
and acceptance remain deferred until this failure is explained and resolved.

The original Harness gate subsequently reported 4,522 passed and 66 skipped in
3,904.95 seconds, and its enclosing process finished with exit code zero after
additional exit/cleanup time. Only after that terminal result was the isolated
G16 file rerun started, preserving the original Product and watchdog budgets.

That isolated file rerun passed all three cases in 32.02 seconds with exit code
zero. The two discovery configurations took 15.42 seconds (`False`) and 12.38
seconds (`True`) for their complete test calls, including both generations.
Receipt: `/var/tmp/loushang-interactive-v1.z5O6F5/g16-isolated-01.xml`.
No Product or test timeout was changed. This supports resource-contention
sensitivity but does not alone rule out suite-order effects; the previously
failed AppService runtime target is therefore being rerun serially. Passing
AppService lint/type checks and other package gates are not repeated.

The full serial AppService runtime revalidation then completed with 1,788 passed
and 15 skipped in 667.96 seconds, exit code zero. Together with the isolated
three-case reproduction, this closes the observed gate failure without Product
changes or a larger watchdog. The original contention-era timeout is retained
above; these successful executions do not prove the test can never time out on
an overloaded machine. Subsequent correctness and performance workloads will
remain serial on this 1.6-GiB Linux host.

Required local correctness coverage is now complete as recorded above, including
the explicitly documented HarnessTUI prefix/suffix revalidation. Deferred remote
platform jobs are still not claimed. The next local commit freezes source and
measurement helpers only; installed pilot, immutable experiment plans, real
pause/resume preflight, formal paired measurements and their final review remain
required before this performance goal can be marked complete.
