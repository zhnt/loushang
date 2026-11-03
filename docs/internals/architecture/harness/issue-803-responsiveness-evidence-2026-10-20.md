# Issue 803: long-session responsiveness investigation

## Status

- Authority: informative — measurement and implementation review
- Implementation status: partial; end-to-end response acceptance is pending
- Tracking: [#803](https://github.com/zhnt/loushang/issues/803)
- Baseline: `0adc4199466f67b63abc8ac6a01a72cfdc3c27e0`

### Continued measurements on 21 October

#### Native JSON copy dispatch

A later matched experiment isolates native JSON copying from commit batching
and scheduling experiments. Both sides use the Product writer and unchanged
strict JSON, canonical-byte, hash and receipt checks. Only the two recursive
copy functions switch between the frozen `dd80b3b5` implementation and native
scalar/container dispatch. Custom Mapping/Sequence implementations retain the
original generic path; copied mutable containers remain independent.

The same application/session runs two warmups and five alternating AB/BA pairs.
Its private sample has approximately 25,500 historical records and 9,400
deferred bundles by this stage. Continuing probes have grown the active model
context, so absolute times are not comparable with earlier experiments.

| Warm paired metric | Original dispatch | Native dispatch |
| --- | ---: | ---: |
| Worked median ms | 752.86 | 674.81 |
| Worked p95 ms | 1,012.31 | 701.91 |
| Main-thread completion CPU median ms | 632.51 | 575.66 |
| Completion input p95 ms | 476.57 | 224.03 |
| Completion input p99 ms | 551.71 | 264.70 |
| All-phase input p95 ms | 262.02 | 195.57 |
| All-phase input p99 ms | 523.91 | 226.62 |
| Maximum timer-frame gap ms | 579.07 | 284.65 |

Each of the five native-dispatch turns has a shorter Worked duration than its
paired original-dispatch turn. Two generation-2 collections occurred in the
original-dispatch turns and none in the native-dispatch turns; the entire tail
improvement cannot therefore be attributed to dispatch. No collection policy
was changed. The input p95 and Worked targets remain unmet.

Native reopening verified all 12 reports, 24 snapshots with terminal usage and
12 output/truncation fingerprints, without changing authority bytes/mtime.
Draft preservation, one Worked per turn and disposal without asynchronous
task leaks passed. The dispatch budget regression first failed twice on the
original implementation. The final focused selection passed 132 tests with
18 existing host skips. Full `make check-ai` passed: 867 tests, seven offline
deselections, lint/type/catalog/import checks and coverage targets, including
90.57% runtime-core coverage. Scoped two-source mypy and changed-file Ruff pass.

A new completion-phase Escape probe sends the key at an absolute deadline
200ms after the controlled child returns. One observed turn delivered it while
Working was still visible: Stopping appeared 209.41ms after the deadline and
Worked appeared 1,184.83ms after tool return. Only the first request reached
transport; the completed tool result was retained. This is a single diagnostic,
not five-pair cancellation acceptance. An earlier diagnostic was interrupted
after its observation failed to finish; it is excluded from performance data.
Thus completion-phase cancellation remains a concrete acceptance gap.

#### Input forwarding and an expired Escape prefix

The scheduling checkpoints were subsequently isolated from bundle batching.
Both variants keep the Product writer and native JSON dispatch. Five alternating
pairs switch only the existing preparation checkpoints and the writer's 8ms
budget checkpoint between one and three zero-delay loop turns. No timer sleep,
GC policy, durable barrier or post-yield revision/leaf check changes.

| Warm paired metric | One loop turn | Three loop turns |
| --- | ---: | ---: |
| Worked median ms | 704.08 | 680.50 |
| Worked p95 ms | 999.02 | 773.17 |
| Completion input p95 ms | 322.22 | 156.28 |
| Completion input p99 ms | 383.37 | 193.98 |
| All-phase input p95 ms | 352.01 | 130.73 |
| All-phase input p99 ms | 501.43 | 156.49 |

Three baseline turns had main-thread generation-2 collections; the candidate
turns had none. This limits attribution of tail differences. Native verification
passed all 12 reports, 24 snapshots with terminal usage and 12 results. Three
deterministic regressions fail with one loop turn: already queued cancellation
forwarding loses priority to provider preparation, commit or a complete logical
copy. They pass with the candidate. The focused selection passed 161 tests with
18 existing host skips. Full AI checks passed 869 tests with seven deselections,
90.64% total coverage and all lint/type/catalog/import/coverage-target checks.
An earlier private probe incorrectly limited the entire 12-turn matrix to 20
seconds; that interrupted run is excluded. The complete paired probe uses a
120-second observation budget, without changing Product timeouts.

Continuous completion cancellation exposed a separate input correctness bug.
Four turns stopped, but the fifth accepted a late following character as the
tail of an already expired Escape. Cancellation was missed and that character
did not enter the draft. A deterministic screen-loop regression reproduces this
without wall-clock sleeps: a tail read after the 30ms idle deadline becomes
Alt+key. The runner now records read completion time and flushes an expired
prefix before feeding a late chunk. A timely tail still forms its original key,
including when its consumer resumes late. Four deterministic ordering cases
and the related terminal/screen/loading selection pass: 61 tests.

After both changes, five consecutive completion cancellations in the same
long session retained drafts, emitted one Worked per turn and disposed without
asynchronous task leaks. All five reached Stopping while still Working, with
acknowledgement times 181.85, 389.77, 195.94, 178.44 and 199.00ms. Tool return
to Worked remained 888.28–1,477.43ms. This is cancellation correctness evidence,
not a matched speed comparison or response acceptance. Reopening verified five
transmitted snapshots and terminal usage, five completed output/truncation
fingerprints and five cancellations without changing authority bytes/mtime.
Input p95, Escape and Worked targets remain unmet.

A wider native reopen rebuilt all five new snapshots, including a check for
untransmitted snapshots (none), and checked all ten new call outcomes, five of
which are cancelled with stop reason `aborted`. Full HarnessTUI/Coding UI checks
passed lint and 164-source mypy, then reported 1,660 passed, 153 deselected and
the same two known macOS PTY EXTPROC restoration failures listed below. No new
failure node was added. All 13 native terminal contracts passed. Documentation
governance passed nine checks.

#### Follow-up experiments rejected after `c1aa405d`

The Product implementation remains at `c1aa405d` while these alternatives are
evaluated. None of the following experiments is included in that implementation.

A fused copy/strict-validation walk passed 203 focused checks with 18 host skips
and the complete AI route (879 passed, seven deselected, 90.67% coverage). Its
five alternating live pairs did not establish lower CPU cost: the committer's
validation phase median changed from 38.73ms to 39.24ms, and a no-generation-2
completion CPU pair measured 609.65ms versus 609.75ms. Tail differences coincided
with three collections on baseline turns and none on candidate turns. All 12
reports, 24 snapshots/terminal usage and 12 outputs passed native reopening.
The extra copy implementation was withdrawn.

A second alternative runs only the native immutable envelope's pure validation
in a worker thread. Transcript revision/leaf checks, allocation and writes stay
on the event loop; custom ports retain their original thread. Four regression
cases failed before the change, then five worker/cancellation/source-change and
custom-port cases passed. The related selection passed 159 tests with 18 host
skips. Five quiet-command pairs improved preparation input p99 from 659.29ms to
396.41ms, but completion input p99 worsened from 338.00ms to 452.97ms and Worked
p95 from 1,028.34ms to 1,291.62ms. Five further pairs with three actual commands
per turn changed preparation input p99 from 207.54ms to 422.93ms, completion p99
from 437.52ms to 412.07ms and Worked p95 from 1,232.17ms to 1,022.66ms. These
mixed results do not establish a stable response improvement. Both matrices
passed native reopening: 24 reports, 48 snapshots/terminal usage and 48 tool
outputs in total, with unchanged authority bytes/mtime. The worker alternative
was withdrawn as well.

A third alternative shares stateless read-only empty metadata. A private native
session with 26,710 records and 9,787 deferred bundles was opened, its writer
index prepared and its latest snapshot rebuilt. Sharing removed approximately
26,700 retained wrappers: tracked objects changed from 311,011 to 284,222.
Repeated explicit full collections in this diagnostic changed only slightly,
approximately 117ms to 114ms. These diagnostic collections are neither Product
policy changes nor UI response acceptance measurements.

The initial metadata selection passed 220 tests with 43 existing host skips.
A stronger ownership check then found a correctness regression: batch deepcopy
memoizes the shared empty value's mutable dictionary result, so changing one
copied record/header can also change another copy. Both new ownership cases fail
with sharing and pass with the original implementation. The sharing experiment
was withdrawn and those ownership cases are retained as regression guards.
The process-pair matrix was stopped after three complete pairs and one unpaired
candidate; it is not five-pair acceptance. The next child was interrupted after
loading, before its first prompt. Native reopening verified all 14 completed
reports, 28 snapshots/terminal usage and 14 outputs without changing authority
bytes/mtime. Historical commands were never executed.

The same snapshot-rebuild diagnostic found 11,835 materialized reference objects
but only 1,661 distinct reference values across 719 expanded bundles. This is
cross-bundle duplication; the eight mapping entries in that sample are all
distinct. Source-scoped reference sharing was subsequently tested after all
existing journal, identity and hash checks. It reduced 12,003 reference objects
to 1,759 distinct objects in a later diagnostic. Five alternating process pairs
nevertheless worsened warm Worked median from 1,704.62ms to 2,199.22ms and
completion input p99 from 690.62ms to 964.39ms. The related selection passed
125 checks with one skip. Native reopening verified 20 reports, 40 snapshots
with terminal usage and 20 outputs. Sharing was withdrawn. Different continued
history sizes and process protocols prevent comparing these absolute times
with other experiments as though they were matched runs.

Deferring the context-usage thread launch from inside rendering to the next
event-loop callback passed 143 focused checks, including render ordering and
obsolete-launch cancellation. Five alternating pairs in one application showed
no stable response benefit: Worked median changed from 889.89ms to 874.00ms,
but p95 worsened from 1,170.72ms to 1,449.98ms. All-phase input p99 worsened
from 408.78ms to 642.97ms, and idle input p99 from 57.66ms to 263.64ms. Native
reopening verified 12 reports, 24 snapshots/terminal usage and 12 outputs.
That launch change and its candidate-specific tests were withdrawn.

Two further alternatives retain exact builtin tuples for validated deferred
node metadata; public reads still produce the original DTO type. The second
also creates indexed-node wrappers only when requested, keeping stable public
wrapper identity and the existing ancestry/hash checks. Each alternative used
five alternating process pairs with two actual prompts per application/session
process. Both cold and warm turns were measured, including 1.2 seconds of input
after Worked. The private authority had approximately 27,000–28,000 records.

| Metric ms | Scalar rows baseline | Scalar rows candidate | Rows + lazy wrappers baseline | Rows + lazy wrappers candidate |
| --- | ---: | ---: | ---: | ---: |
| Cold Worked median | 858.30 | 1,159.16 | 877.01 | 1,113.52 |
| Cold Worked p95 | 883.31 | 1,601.09 | 888.97 | 1,323.67 |
| Cold all-phase input p99 | 268.63 | 537.36 | 356.08 | 430.30 |
| Warm Worked median | 881.27 | 876.52 | 860.68 | 864.15 |
| Warm all-phase input p99 | 559.24 | 236.10 | 415.54 | 220.84 |

The second alternative reduced GC-tracked objects from 320,820 to 260,100 in
a separate writer-index/latest-snapshot diagnostic, and eliminated 30,372
unused wrappers. Repeated manual full collections decreased from approximately
122ms to 87ms. These are diagnostic results only. Actual cold turns still
incurred approximately 200–375ms collections, often later in the completion
phase. Neither alternative improved overall cold/warm responsiveness reliably;
both were withdrawn without changing Product GC policy or scheduling delays.

The scalar-row selection passed 39 checks. The lazy-wrapper version passed
375 transcript checks with 370 existing host skips, then 41 focused checks
including two additional reference-identity/ancestry guards. Ruff and the
three-source mypy check passed. The two independent integrity guards also pass
on the restored Product implementation and remain as regressions. Native
reopening verified both complete matrices: 40 reports, 80 snapshots with
terminal usage and 40 outputs in total. Authority bytes/mtime were unchanged;
drafts, one Worked per turn and async-task disposal checks passed.

These last two matrices attribute input phases to each key's intended absolute
deadline, rather than its potentially delayed callback delivery. This corrects
phase attribution across a blocked transition; all-phase latency remains
comparable within each pair. Input still uses the existing single-character
fake reader. Real PTY buffering and physical Escape timing remain a separate
acceptance requirement. The static heap diagnostic does not represent the
complete live-runtime heap at a collection boundary.

A subsequent diagnostic samples the actual runtime at generation-2 collection
entry and at the first controlled tool. It is explicitly excluded from latency
acceptance because inventory collection perturbs execution. The first tool had
504,724 tracked objects, including 60,230 node references, 32,775 mapping entries
and 6,846 mapping-root nodes. The latest-snapshot-only diagnostic therefore
understates live retention. The recorded stacks identify initial context-usage
snapshot reconstruction on its worker thread and Resource-evidence recovery's
historical logical-root lookups on the event loop. The next turn's collection
starts while serializing the logical input. Neither thread placement nor static
retention alone establishes a UI response improvement.

An alternative then validates each complete bundle with the existing decoder,
journal-line hash and index checks, but retains only a requested node. Historical
logical-component inspection can also read a root transiently without publishing
a body cache. Full-bundle callers and legacy sources retain their existing
contracts; failed sibling decoding cannot publish a usable selected-node cache.
The independent retention regression failed on the original implementation.
The deferred-component inspection guard also failed when pytest's `pythonpath`
was explicitly set to the frozen baseline. An earlier environment-variable-only
attempt still selected repository source and is excluded from red evidence.

The alternative passed 399 transcript/Resource-evidence checks with 370 existing
host skips, 46 focused checks and four-source mypy/Ruff. Five alternating process
pairs again included two actual prompts per application/session and post-Worked
input observation. They showed the following mixed result:

| Metric ms | Original cache | Selective/transient bodies |
| --- | ---: | ---: |
| Cold Worked median | 949.55 | 963.65 |
| Cold Worked p95 | 1,003.43 | 1,302.96 |
| Cold tool-start median | 5,341.41 | 6,500.59 |
| Warm Worked median | 1,279.24 | 957.97 |
| Warm preparation input p99 | 498.84 | 820.83 |
| Warm completion input p99 | 636.19 | 281.99 |
| Warm all-phase input p99 | 592.39 | 728.90 |

Collections moved from completion toward preparation rather than disappearing.
The alternative was withdrawn because the overall response objective did not
improve reliably. Native reopening verified all 20 reports, 40 snapshots with
terminal usage and 20 outputs without changing authority bytes/mtime. The
diagnostic's two reports, four snapshots/terminal usage and two outputs were also
verified separately. No historical command was executed. A sibling-validation
regression that passes on the original implementation is retained alongside
the two reference-integrity guards. The runtime source remains `c1aa405d`.

#### Private experiments retained outside Product

Batching Model Input component bundles reduced materialization work but removed
natural I/O scheduling breaks. Its five-pair experiment worsened preparation
input p99 from 1,381.28ms to 1,975.87ms. Three zero-delay loop turns at CPU
boundaries then improved forwarded-input/cancel regression behavior and one
completion input p99 comparison from 441.57ms to 269.93ms, but preparation
remained slow and Worked did not improve consistently. That combined prototype
remains private. The later isolated scheduling change described above retains
the existing Product commit boundaries.

A typed record-membership index was also tested while retaining the original
lineage predicates and reading mutable fact fields live. Its five pairs used
identical batching/checkpoints on both sides, toggling only full-history
scans versus candidate spans. Worked median changed from 628.31ms to 616.53ms,
while p95 worsened from 641.73ms to 892.64ms, with two approximately 295ms
generation-2 collections on indexed turns. This does not establish a stable
responsiveness improvement, so the index remains private. These prototypes
have separate correctness evidence; they are not evidence that the Product
meets response targets or that completion-phase Escape is accepted.

The persistent Product-turn objective is still unmet. A bounded decoded-bundle
cache was tested privately and withdrawn: five alternating cold-process pairs
reduced retained decoded bundles from over 3,100 to 16, but normal Worked p95
worsened from 1,373.80ms to 1,638.11ms. Fewer collections and lower retention
did not establish a responsiveness improvement. Neither that cache nor the
experimental 1ms scheduling delays are included in the implementation.

A separate probe now keeps the same Screen application, SessionManager,
AgentSession and native writer caches across five consecutive prompts. It uses
controlled new subprocesses and durable prepared requests; historical commands
are never executed. Each normal turn has two independently rebuilt snapshots,
terminal usage and output/truncation fingerprints. Both variants passed those
checks, retained drafts, emitted one Worked per turn and disposed without
asynchronous task leaks. The original session remains read-only.

On sample A, the first cold prompt and four warm prompts produced the following
tool-return-to-Worked times. These are one continuous process per variant,
not five independent matched process pairs, and are not acceptance evidence.

| Variant | Cold prompt ms | Warm prompts ms |
| --- | ---: | --- |
| Committed cooperative preparation | 929.90 | 921.27, 922.65, 921.34, 936.28 |
| Reduced request-container allocation | 966.52 | 962.53, 974.66, 907.76, 1,138.89 |

Warm completion input p99 was 312.85ms and 414.08ms respectively. Allocation
reductions have focused correctness coverage and the full AI checks pass, but
they do not yet show a stable end-to-end response improvement. No latency
target has been relaxed. The warm writer reused all unchanged sequence items
and planned only four new items per request; the remaining delay therefore
persists even when prefix reuse is working and no generation-2 collection
occurs during the warm turn.

Completion-only profiles identify repeated ancestry-position reconstruction:
the resolver builds the full approximately 24,000-record dictionary at initial
preparation and after each bundle append. The current candidate reuses its
own writer's position map when extending the exact same record-object prefix,
checks every new identity for duplicates and creates fresh resolution caches
and decode budgets. Shortened paths, replacement prefix objects and duplicate
suffix identities fail before publishing a new resolver. This change does not
cache decoded payloads or relax reference, sibling, hash or durable receipt
validation. Five regression cases failed before the implementation and pass
with it; the related focused selection passed 130 tests with one existing skip.

One continuing native Product session then ran a warmup followed by five
alternating pairs of normal quiet-command turns. The frozen candidate was the
same in both cases; the baseline substituted only the original full resolver
constructor after bundle appends. Thus this comparison isolates position-map
reuse, rather than comparing all preceding allocation changes with main.
Orders alternated AB/BA. Every turn used a new controlled subprocess.

| Warm paired metric | Full reconstruction | Prefix extension |
| --- | ---: | ---: |
| Worked median ms | 1,361.08 | 1,266.45 |
| Worked p95 ms | 1,551.85 | 1,473.24 |
| Completion input p95 ms | 460.88 | 445.82 |
| Completion input p99 ms | 526.84 | 514.28 |
| Tool-running input p99 ms | 55.05 | 49.84 |

Native reopen verification checked all 11 reports, 22 prepared snapshots and
their terminal usage, plus all 11 output/truncation fingerprints. The private
authority file was unchanged by verification. Drafts, one Worked per turn and
task cleanup passed. These data show a small improvement for this component;
both completion response and input targets remain unmet. Different tool cases,
cancellation and other historical scales have not yet been reaccepted for this
candidate. Selected consumer gates are complete with the baseline failures
listed below.

The allocation changes freeze only a tree already detached by request
projection, keep immutable payload views and preserve fresh transport copies.
The transcript edge avoids a frozen intermediate while retaining strict JSON,
canonical-byte and hash checks; malformed cycles take the original rejection
path. Unused zero-replacement binary projections are released before indexing;
actual image replacements stay owned until durable storage and reconstruction.
Caller mutation, transport mutation, malformed payloads, actual image hydration
and retained-allocation regressions cover these ownership boundaries. Full AI
validation passed 867 tests with seven offline deselections, including its lint,
type, import/catalog and coverage gates.

The selected full Coding consumer run passed 3,387 tests, skipped 283 and
deselected 55, with 127 failures and 39 setup errors. All 166 failing node IDs
exactly match the previously recorded macOS baseline: no added or missing node.
Dependency checks and the 153-test Agent consumer selection also passed. The
Harnesstui selection passed 1,054 tests with 85 deselections and the same two
known macOS PTY EXTPROC restoration failures. Its lint and 140-source type check
passed. Coding UI passed 602 tests with 68 deselections; the render-contract
route passed 311 tests with 7,649 deselections. Full Harness passed 5,173 tests
with 724 skips and three deselections. Its 25 failures exactly match all 25
previous baseline node IDs, with none added or missing. Full Harness lint
passed; its 775-source type route still reports the same six errors in the
unchanged `package_legacy_runtime.py` PID-namespace attributes. Source hashes
matched the frozen tested candidate after all routes completed. The redundant
unit-Coding invocation was stopped because the completed Coding run uses the
identical command with a strictly broader marker selection; no CI route or
test selector was changed. Host-runtime platform checks remain pending. This
is not a fully green gate claim.

### Private batch experiment: faster completion, worse input

A subsequent isolated prototype stages new graph identities in a private
planning index and submits the missing bundles to the existing native atomic
batch owner once. The planning index reuses the existing strict reference and
sequence validators; new locations and verification caches reach the shared
index only after actual durable receipts. The snapshot still commits before
transport. No provisional receipt is used as storage authority.

The prototype passed 128 focused tests with 18 existing skips, including write
rejection, wrong receipts, invalid record kinds, cancellation before/after
publication and recovery. File-backed diagnostic runs verified three actual
consecutive tools per prompt, cancellation, shared index reuse and 2.16MB Unicode
output, with snapshot/usage and result hash/truncation checks. Those concurrent
diagnostic runs are correctness evidence only.

After consumer tests finished, one continuing sample-A session ran two warmups
and five AB/BA pairs. The unchanged index/cache implementation was verified
byte-identical and shared between the two writer variants to avoid retaining
two full history indexes. All 12 turns passed native verification of 24
snapshots and terminal usage plus 12 converted outputs. Preparation and tool
continuation were both measured with typing continuing through completion.

| Warm paired metric | Existing writer | Private batch writer |
| --- | ---: | ---: |
| Worked median ms | 2,153.86 | 2,029.07 |
| Worked p95 ms | 2,614.55 | 2,445.52 |
| Preparation input p99 ms | 1,381.28 | 1,975.87 |
| Completion input p99 ms | 979.62 | 982.94 |
| Tool-running input p99 ms | 67.15 | 74.14 |

Continuation materialization median fell from 460.73ms to 305.32ms. This did
not improve input responsiveness: the candidate had a 694.88ms main-thread
generation-2 collection and removes some natural scheduling breaks from the
old multi-write path. No collection policy or threshold was changed. This is
a later, larger continued context than the earlier position-map comparison,
so absolute values across those two experiments are not matched comparisons.
The batch prototype remains outside the Product candidate. Further cooperative
scheduling and allocation work must pass the input criteria as well as improve
completion time before it can be adopted.

## Architecture review scope

The implementation agent reviewed this change using the existing local
archmethod revision `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e` and the workspace
high-risk change workflow. No upstream method was fetched.

- Strict historical identity/parent authority stays with the validated graph;
  only immutable suffix links take the extension path. Existing mutation APIs
  and compatible-mode repair retain their reconstruction behavior.
- The transcript UnitOfWork retains durable receipt validation, cancellation
  ownership, commit serialization and candidate publication order.
- Render segments and the lazy screen-text view retain immutable frame data;
  they do not become owners of session history or introduce history trimming.
- Terminal deadlines retain completed-input priority and waiter cleanup. No
  storage protocol, provider, approval or session-lifecycle contract is changed.

The performance objective remains open; this scope review is not acceptance of
unmet latency criteria or a statement of user approval.

## Workload and source isolation

A read-only local session was copied outside the repository into a private
workspace. The original session was not opened for writing or replayed as
commands. Reports carry only aggregate sizes and timings, with no transcript
content or session identifiers.

Sample A contains 191,719,829 bytes and 24,459 records. Its active path projects
to 4,909 display records: 468 prompts, 1,351 assistant messages, 3,082 tool
records and eight compactions. The normal resumed active window retains 17
records under the existing 320 logical-line budget; the full-window experiment
retains all 4,909. These are distinct scenarios.

The baseline platform is macOS, Python 3.11.15, using the lane's existing virtual
environment. Transcript decoding is excluded from append timing. An in-memory
Conversation store isolates repository preparation from filesystem latency;
this is not a Product tool execution or native terminal measurement.

## Finding: repeated repository reconstruction

Every single-record transcript commit rebuilt the complete validated BranchGraph,
including one child list per historical record. The replacement prepares a
separate graph from shallow copies of the lookup maps and a fresh child list
for each changed parent. Existing strict records have immutable identity/parent
links; they cannot point into the new suffix. Single and batch appends validate
new identities and parent links, including forward references within a batch,
and detect cycles among the new nodes before constructing the candidate.
Invalid IDs, duplicates, self-parent and missing-parent checks remain before
backend publication. Compatible graphs still fully normalize historical repairs,
including forward references supplied by the appended record.

The source repository, selected leaf and child lists remain detached. The
UnitOfWork still publishes its candidate only after a valid backend receipt;
its cancellation owner and commit lock are unchanged. Both single and batch
commits now use detached graph extension; compatible-mode graphs retain full
normalization. Regression coverage checks error parity, forward-parent batches,
empty batches, selected-branch preservation and immutable snapshot children.

Five alternating process pairs loaded the same isolated file with the same
interpreter and dependencies. Each process measured five bursts of three
append operations with a 5ms asynchronous heartbeat. Source snapshots were
fixed before measurement. The table reports per-process burst medians and
worst heartbeat intervals, in milliseconds.

| Pair | Baseline append median | Candidate append median | Baseline worst interval | Candidate worst interval |
| --- | ---: | ---: | ---: | ---: |
| 1 | 257.06 | 18.98 | 428.01 | 10.99 |
| 2 | 252.77 | 17.41 | 424.21 | 10.96 |
| 3 | 258.20 | 16.91 | 440.41 | 10.61 |
| 4 | 264.38 | 16.56 | 450.70 | 10.27 |
| 5 | 384.13 | 20.35 | 499.25 | 11.31 |

Across 25 bursts per version, median append time was 264.38ms versus 17.02ms;
the worst observed heartbeat interval was 499.25ms versus 11.31ms. This proves
an improvement in this isolated commit workload. It does not establish the
input-echo or Working-to-Worked acceptance criteria.

## Finding: rebuilding unchanged RenderLine objects

A full-window tool update reconstructed about 64,800 RenderLine objects even
when almost all record text was reused. The region now retains rendered lines
alongside its existing record-block cache and reuses unchanged line objects.
The cache shares the original block invalidation context (record identity,
expansion, window, width and style); focus labels remain regenerated controls.
The assistant/Worked suffix path also fills the per-record line cache.

A regression first failed on lost line identity, then passed after the change.
It compares all resulting text with a fresh region, checks detail controls and
exercises a tool replacement after the completion suffix path. Related screen
and transcript selections passed 98 tests. In a single exploratory full-window
profile, tool-end rendering fell from 624.28ms to 44.85ms. These profiled timings
include instrumentation overhead and are not the five-round UI acceptance
benchmark; cold initial rendering still took 17.27 seconds.

## Finding: replacing the complete committed render segment

Reusing line objects alone left the complete history in one new segment after
any tool change. The native RenderLoop therefore finalized every historical row
again. The region now retains one immutable segment per record, including its
leading separator and optional detail control. It preserves segment identity
when the record, expansion, layout context and control label are unchanged.
The final assistant/Worked suffix fills the same cache as ordinary updates.

The regression preserves all logical rows and compares text/control coordinates
against fresh full layout across widths, viewport heights, anchors and drafts.
Tool changes in a 2,000-record history now materialize at most five rows while
reusing more than 2,000 segments. A real screen-runner regression holds tool
execution and cancellation cleanup separately: draft editing and the Running /
Stopping timer remain observable before completion, one Worked is emitted,
original history objects remain present and no tasks survive shutdown. Both
normal and interrupted variants fail on the baseline because thousands of old
rows are finalized, and pass with record segments.

## Finding: flattening screen text for every input frame

ScreenConversationApp also copied every logical line into a string tuple on
every render for selection and hit testing. It now keeps an immutable frame's
line sequence behind a lazy text view. Individual lookups and requested slices
preserve original logical coordinates; selection snapshots still explicitly
capture their selected frame. A regression previously read 4,008 texts for a
single draft edit; it now limits frame text reads to 40 while checking both the
first historical row and the new draft remain accessible.

## Finding: grapheme scanning for plain commands

The full-history cold-frame profile spent substantial time segmenting printable
ASCII commands with the Unicode grapheme scanner. `wrap_cells` now slices
printable ASCII directly, preserving spaces, explicit empty lines and terminal
control removal. Tabs, controls and Unicode retain the existing cluster layout.
The structural regression first fails when ASCII invokes the cluster scanner;
Unicode, emoji and combining-character behavior is covered by the existing
cell-width suite. Cold full-history response remains an open acceptance item.

## Finding: render activity postponed terminal input deadlines

`read_input_chunk_or_render_tick` reused the original relative idle duration
inside its render-wakeup loop. Continuous output could restart Esc recognition
before every expiry; immediate animation and scheduled frames could postpone
terminal runtime deadlines in the same way. Each input wait now establishes
absolute monotonic deadlines and recomputes their remaining duration after
render activity. An expired deadline still performs the terminal-read and
render-waiter cleanup handoff before returning, so input completing during that
handoff keeps priority over the timeout.

Six deterministic regressions cover pending-input and terminal-runtime deadlines
under render events, immediate frames and scheduled frames. All six failed
before the fix. Existing zero-deadline input/EOF cleanup regressions remain green.
A private single-case real streaming subprocess check then acknowledged Esc in
33ms, preserved the draft and left no tasks. Multi-case full-history acceptance
is still pending; a shorter post-Esc keyboard gap in an exploratory probe also
exposed raw terminal Alt-prefix ambiguity under latency, so it is not counted
as a successful cancellation. The matched probe isolates Esc with a quiet
interval while retaining the requested 100ms acknowledgement threshold.

## Exploratory actual-screen measurements

The private offline probe uses the real screen runner, local ExecService child
processes, Bash result conversion, and the complete 24,459-record in-memory
transcript. It projects the read-only session and preserves its 4,909 display
records in the full-window scenario. Keyboard arrivals use absolute loop
scheduling deadlines and are observed in the physical viewport, including keys
after tool completion. This remains a harness integration measurement: it does
not run a live model, a complete Product agent turn, or a file-backed transcript.

One quiet-command exploration before record segments observed 1,129ms maximum
input echo and 504ms tool-return-to-Worked. After record segments it observed
123ms and 139ms respectively; input p95 was still about 112ms. A subsequent
exploration including lazy screen rows and ASCII wrapping observed 74ms maximum
input echo and 123ms Worked, with a separate quiet-command cancellation observing
50ms Esc acknowledgement. These single exploratory rounds do not prove the
five-round acceptance thresholds.

An earlier probe scanned the entire logical history in its output observer and
reported multi-second stalls caused by measurement overhead. That measurement
is explicitly invalid and excluded. A component-only viewport experiment also
did not represent the native renderer, which requests a complete logical frame
for terminal scrollback correctness. That optimization was removed; full
history and native scrollback semantics are preserved.

## Five-round candidate screen matrix

The frozen candidate was exercised in one continuing native screen loop, with
five rounds of each scenario in normal and interrupted forms (50 turns total).
It retained the complete display history rather than applying the resumed
window budget. Arrival deadlines and terminal conditions were the same across
rounds. p95/p99 use the nearest-rank definition. Esc has a quiet keyboard
interval to distinguish a standalone Esc from an intentional terminal Alt
prefix; the acknowledgement target remains 100ms.

| Scenario | Input p95 ms | Input p99 ms | Worked p95 ms | Esc p95 ms (cancelled) |
| --- | ---: | ---: | ---: | ---: |
| Quiet command | 67.59 | 88.11 | 125.65 | 61.59 |
| Continuous stdout/stderr | 69.25 | 100.89 | 89.21 | 93.85 |
| Three consecutive tools | 83.49 | 95.51 | 117.31 | 62.32 |
| 1.08MB ASCII result | 79.77 | 91.16 | 117.30 | 63.84 |
| 2.16MB UTF-8 result | **134.65** | 158.88 | 169.26 | 61.13 |

Input and Worked columns describe normal completion. Interrupted turns were
also measured; their highest input p95 was 94.04ms. Every draft was preserved,
all scheduled key echoes appeared, exactly one Worked appeared per turn, every
requested cancellation was observed, and shutdown left zero asynchronous tasks.
The maximum measured timer-frame gap was 180.06ms. Large results retained the
existing 51,200-byte preview and `bytes` truncation metadata; stdout fingerprints
and full captured byte counts were retained privately for baseline comparison.

**The Unicode-result input p95 does not meet the 100ms target.** The initial
unbounded logical frame also still took 15.18 seconds. Persistent/Product-turn acceptance and the complete five-round baseline
comparison remain pending.
A prototype UTF-8 fingerprint collector incorrectly used strict encoding on
byte-preserving surrogate escapes at preview boundaries; that prototype result
was discarded. The matched collector uses the same surrogate-escape encoding
contract as ExecService and explicitly requires successful tool receipts.

## Partial baseline screen comparison

The same frozen baseline was run separately with the same local commands,
read-only history, viewport and keyboard deadlines. It completed 25 measured
turns, including two complete rounds of all scenarios, over 431.61 seconds.
The agent stopped that negative-control run to run correctness gates; it did
not complete the required five baseline rounds. The private report retains all
completed measurements and the interrupted process status rather than treating
it as a passing benchmark.

Across its first two complete rounds, normal tool-return-to-Worked ranged from
1,391.83ms to 2,291.01ms. The corresponding candidate's five-round normal p95
values are shown above, but these are **not a complete five-pair comparison**.
Some baseline key echoes were still unobserved at the probe's post-completion
observation limit, and no requested cancellation in its 25 completed turns was
acknowledged as a cancellation. Missing observations are censored failures, not
zero-latency samples; a baseline Esc p95 cannot be reported from that run.

## Real Product turn investigation (2026-10-21)

A second private probe restores the writable isolated session copy through
`SessionManager.open`, uses the real `AgentSession`, file persistence, context
meter and cooperative screen listener, and runs a synthetic model transport.
Only a new probe tool call is allowed; it executes a known local Python child.
The synthetic transport explicitly skips new durable Model Input commits; this
probe covers recovery/preparation and durable message/tool records, and does not
establish the cost of the provider commit-before-send barrier.
No historical tool call or external model request is executed. Runtime settings,
platform data and scratch files are redirected outside the repository.

This distinguishes the actual Product turn from the earlier memory-store screen
matrix. Single-round exploratory measurements on the normal resumed window were:

| Candidate stage | Input p95 | Tool completion to Worked | Maximum loop delay |
| --- | ---: | ---: | ---: |
| First local commit (`816f162d`) | 470.20ms | 608.69ms | 772.28ms |
| Cooperative evidence recovery | 527.33ms | 673.08ms | 515.59ms |
| Recovery plus context replay cache | 339.22ms | 437.06ms | 395.16ms |

These are diagnostic runs on a continuing isolated copy, not five matched
before/after rounds or acceptance evidence. Profiling timings are excluded from
latency acceptance. A path-cache run overlapped a static typecheck and is also
excluded from performance comparisons. No target has been relaxed.

### Durable evidence recovery occupied the model-call boundary

The first actual-turn profile found 2,976 indexed Model Input bundle reads during
evidence recovery. Recovery ran synchronously while preparing a model call.
The new async preparation drives the same checked recovery steps and yields
between records/snapshots after an eight-millisecond work budget. Staged caches
publish only after complete recovery; cancellation, closure and corruption do
not publish partial results. The final synchronous boundary still checks the
current path, message bindings and Session ownership before binding a committer.
A single opaque snapshot rebuild can still exceed the budget; this is not a
universal eight-millisecond bound on arbitrary histories.

### Context bindings repeatedly folded unchanged history

Model-call preparation also requested context bindings repeatedly, causing full
history folds. The UnitOfWork now retains one verified default-profile projection
and folds eligible suffix records. The cache key includes repository identity,
selected leaf and profile generation. Explicit record selections, custom
semantics, non-prefix branch changes and compaction checkpoints retain full
validation. Histories with mutable nested annotation/metadata state also retain
fresh replay. Background reads capture their selected leaf; a concurrent branch
selection cannot label an old path as the new one. Publication remains after
the durable receipt, including the existing cancellation settlement behavior.

### Repeated path walks and initial activation validation

The graph now retains one immutable path, reuses it for repeat reads, and walks
only new suffix links when a strict extension descends from that path. Compatible
repairs create a fresh graph and path. Record objects, branch membership and
old graph snapshots retain their existing meaning; the cache is bounded to one
path per graph.

A lightweight actual-turn trace also identified an initial 428.70ms synchronous
Coding activation-history check. Its async driver now shares the exact selected
path validator with the synchronous API. Cancellation publishes no guard;
commits/branch changes during a yield restart validation, and pending runtime
publication still rejects admission. The Coding preparation entry awaits this
check before ordinary execution. Later synchronous admission fences remain in
place and reuse only a completed matching revision/leaf check.

Blob reference collection also skips non-blob-bearing payload classes before
extracting references and avoids constructing repeated union-type checks. It
still scans relevant mutable message content/details on every call, preserves
stable deduplication order, accepts supported subclasses, and rejects foreign
Session references. No reference cache hides mutations or ownership checks.

### UTF-8 truncation could turn successful output into a tool error

The actual Product probe exposed a correctness failure hidden by the earlier
screen-only matrix: clipping a valid multibyte character could introduce lone
surrogates, which the transcript JSON boundary rejects. The byte-suffix helper
used `surrogateescape` inside a retry loop, so invalid leading bytes never raised
the exception intended to advance to a character boundary. The old boundary
example happened to cut exactly between characters.

The helper now uses a strict fast decode and, when necessary, finds the bounded
suffix in the original string. Valid UTF-8 stays valid; genuinely escaped source
bytes retain their previous byte meaning. Raw artifacts and original byte/line
counts remain unchanged. Four newly covered split-character cases and the real
ExecService-to-Bash preview check failed before the change and passed after it.
The focused truncation, execution and Bash suite passed 45 tests; the integration
case checks incremental and final JSON projection and exact full artifact bytes.

The first large-output probe failed because its private output directory was
missing. After fixing that setup, strict assertions exposed the Product JSON
failure above. Neither failed probe is latency acceptance evidence.

A later four-case diagnostic on frozen phase-two source (before the UTF-8 fix)
reported the following valid quiet/cancel observations. Input was sampled during
preparation and tool/completion windows, rather than continuously across all work:

| Scenario | Input p95 | Esc visible | Tool/cancel to Worked |
| --- | ---: | ---: | ---: |
| Quiet, normal completion | 107.70ms | — | 318.31ms |
| Cancel during preparation | 748.54ms | 187.09ms | No tool had started |
| Cancel during tool execution | 519.39ms | 35.79ms | 980.21ms |

These single rounds still fail the response targets and show long pauses remain.
The source was frozen separately from the earlier candidate, no static/test run
was concurrent, and no transcript/tool correctness failure was accepted as a
successful normal turn. Full matched rounds and continuous-input observation
remain outstanding.

After the UTF-8 fix, the strict large-Unicode Product probe completed with one
successful output, preserved the input draft and left no asyncio tasks after
disposal. Diagnostic input p95/p99 were 87.15/111.67ms and Worked was 312.23ms.
The latter still exceeds the 250ms target. This probe retained the earlier
windowed key schedule, so the input percentiles cannot establish uninterrupted
responsiveness throughout the turn.

GC observation recorded a 221.14ms generation-two collection on a background
thread at turn offset 1.49s; maximum event-loop delay was 247.06ms. The key
windows did not cover that entire pause. The exact allocation owner still needs
thread profiling; moving a computation to a thread alone does not prove that it
cannot pause input. The next private probe schedules absolute key deadlines
continuously through completion and records timer-frame gaps as well. No GC
threshold, timeout or acceptance target was changed. Original session size/mtime
and the read-only copy's 0400 mode were checked again, and current Product source
hashes match the separately frozen UTF-8 candidate.

Focused validation after these changes: 325 passed, 24 skipped. Changed-source
Ruff passed and mypy passed for nine source files. Deterministic
regressions observe work before completion, cancellation without publication,
branch changes while suspended, compatible repairs, and receipt-confirmed
publication. Full response acceptance remains pending.

The required phase-two `make check-changed` run passed documentation and source
dependency validation, then stopped in Coding: 3,357 passed, 283 skipped,
55 deselected, 128 failed and 39 errors (977.25s). The 167 failing node IDs exactly
match the prior diagnostic list: known platform failures plus the recurring grep
500ms timing check, which observed 604.17ms in this run. This is not a green gate
or proof that all failures are environmental. In the isolated exact-case rerun,
the frozen baseline failed at 521.01ms and the current candidate passed. Both
launchers verified their imported source before pytest configuration, and neither
Product timeouts nor the 500ms assertion were changed.

The complete affected Harness offline route passed 5,133 tests, skipped 724 and
deselected three, with the same 25 previously reproduced Linux-rooted-I/O failures
on macOS (392.14s); no new failing node appeared. The earlier TUI-library routes
remain evidence for unchanged source. Repeated consumer UI validation passed
1,656 tests, with 153 deselected and the same two macOS PTY mode-restoration
failures (282.43s). Its Ruff and 164-source mypy checks passed. Hosting offline
regression passed 257 tests, with 193 skipped and four deselected; the two real
Product persistence/cancellation E2E smoke cases passed as well.

## Phase three: prepared transport and repeated activation checks

The private offline probe now uses the normal prepared-provider adapter path.
It verifies the committed snapshot receipt and prepared-payload hash before
each transport call. One new controlled tool call produces two new durable
Model Inputs. Continuous absolute key deadlines cover preparation, execution
and completion. Historical tools are never invoked, and network connections
are blocked. The earlier synthetic transport explicitly omitted these commits;
its timings cannot establish the cost of the real Model Input barrier.

The isolated-file setup also needed correction. Native writer-head metadata is
bound to filesystem identity. Copying a journal invalidates its head, even when
the deferred-read index remains valid. A cold copy's first write therefore
strictly reconciles the entire prefix. The original sample has a valid head.
Warm-write fixtures now use the backend's idempotent append of the already
existing final record, outside the measurement process, to establish a native
head. Both authority bytes and journal mtime are checked unchanged. Cold
recovery remains a separate required scenario; its approximately 35-second
tool-start observation is not representative of an ordinary valid-head append.

With a valid head, the previous committed source still showed an approximately
1,013ms maximum input delay and 1,206ms Worked delay. Its first Model Input
commit took 1,123ms, including 553ms building the historical node index; the
second commit took 353ms. These are exploratory single rounds.

Stage tracing found another synchronous replay after Model Input metadata
advanced the transcript revision: the next Coding message ran the complete
activation projector again, taking approximately 352ms immediately before
Worked. The new Coding guard can reuse its completed classification only when
the entire checked prefix is activation-neutral, native immutable record
identities remain an exact prefix, and the new suffix has valid unique parent
links and no activation intent or reserved runtime-binding key. A later
sensitive fact still gets full ancestry hashing. Bound histories retain the
existing local input-proof check. This deliberately leaves their repeated full
validation as remaining work.

Ordinary-message guard advancement now inspects the committed record and its
selected prefix, including all `coding.runtimeBinding*` keys. It previously
checked only the v1 key in the caller's mutable metadata. Four regressions
first demonstrated that v2/future keys, caller mutation and a concurrent branch
change could bypass the next fence; all pass after the correction. Pending
publication still blocks before any cache lookup.

Cold/branched Model Input indexes now build cooperatively between the same
node checks. Cancellation, malformed history, a changed revision/leaf or a
changed compatibility token prevents publication of the new cache. A previous
branch cache remains intact. Synchronous consumers retain the same generator
and validation. Warm suffix indexing and the durable commit-before-send
barrier are unchanged. Ten regression cases exercise both cold and existing
branch caches, including observation while preparation is incomplete.

The latest isolated prepared round, with 24,459 initial records and 8,967
deferred bundles, recorded the following. This is not a matched five-round
acceptance result:

| Measurement | Observed |
| --- | ---: |
| Continuous input samples | 315 |
| Input p95 / p99 / maximum | 345.62 / 461.40 / 544.88ms |
| Maximum event-loop delay | 412.60ms |
| Maximum timer-frame gap | 576.60ms |
| Maximum warm render frame | 12.48ms |
| Final activation guard | 19.38ms |
| Tool exit to Worked | 1,267.21ms |

Two main-thread generation-two collections still took 280.98ms and 361.16ms.
The second Model Input commit still took 499.25ms. Input and Worked targets
remain unmet. A separate reopened process rebuilt both new Model Inputs through
the Product API, verified their hashes, the new prompt/tool identity and both
terminal usage facts, and checked authority bytes/mtime unchanged. Draft
preservation, one Worked divider and no remaining asyncio tasks also passed.

A separate continued-session cancellation round used the same private copy
after that normal turn. Escape displayed Stopping in 33.59ms and cancelled the
controlled running tool, preserving the draft and leaving no asyncio tasks.
Cancellation-to-Worked still took 652.40ms, with input p95/p99 of
277.38/341.57ms. This is one continued-session round, not a matched cancellation
acceptance result. A completion-only profiler is now available for diagnosis;
its instrumented latency is excluded from acceptance comparisons.

The prepared consecutive-tool probe now invokes three distinct controlled new
tools through the real sequential Agent executor. The short-session smoke
passed with a 6.95ms maximum input delay and 77.09ms Worked delay. In a separate
continued long-session round all three tools succeeded, the draft remained
exact and disposal left no asyncio tasks; maximum input delay was 385.08ms and
Worked took 908.94ms. This corrects the earlier probe's single-tool coverage;
matched long-session consecutive-tool acceptance is still outstanding.

Two allocation experiments were withdrawn: selective per-node bundle decoding
caused repeated parsing and showed no valid response improvement; replacing
per-node callback wrappers with bundle references also failed to establish an
end-to-end improvement. Neither change is retained. No GC policy, timeout or
response threshold was changed.

Current focused offline validation passed 220 tests covering Model Input,
deferred file indexes, request evidence, activation and bindings. Changed-source
Ruff and three-source mypy passed. The required `make check-changed` run passed
documentation and architecture validation, then stopped in Coding: 3,374 passed,
283 skipped, 55 deselected, 127 failed and 39 errors (867.71s). The 166 failing
node IDs are all in the previously established baseline; the additional grep
timing failure from the earlier run did not recur. This is not a green gate.

The complete Harness offline route passed 5,143 tests, skipped 724 and deselected
three, with exactly the same 25 Linux-rooted-I/O failures on macOS (325.78s).
Harness Ruff passed. Its full 775-source mypy route stopped on six errors for
`_pid_namespace_digest` in the unchanged sandbox legacy-runtime module. An
isolated full 775-source run against the frozen prior source reproduced those
same six errors at identical locations. No unrelated runtime code or type gate
was changed to suppress them. Matched normal/cancelled acceptance rounds remain
pending.

Hosting offline regression passed 257 tests, with 193 skipped and four
deselected. The two real Product persistence/resume/close and terminal
cancellation/new-message/exit E2E smoke cases passed (4.35s). Documentation
validation passed nine tests. Product source hashes still match the separately
frozen phase-three candidate; the proposed continuation-purpose and bound-proof
cache changes are separate private experiments, outside this checked snapshot.

## Phase four: continuation selection and bound-history proofs

The Agent emits `tool_continuation` after executing a tool batch, but the
inspection purpose allowlist omitted that value. Inspection rebuilt the latest
tool request, discarded it, then rebuilt an older main request. A private
experiment using saved snapshots from three real controlled tool executions
reproduced two rebuilds and selection of the older request. Including the
actual continuation purpose selected the newest request with one rebuild and
retained full prepared-payload hash verification. The purpose regression first
failed only for `tool_continuation`; the corrected five-purpose matrix passes.

Activation validation now also supports an unchanged bound prefix. Only a
neutral suffix may extend it. Sensitive intent/input records retain exact
record fingerprints, which are checked again before reuse. Full historical
classification and the live local input proof are separate checks; a completed
classification no longer invokes the entire projector a second time just to
check the same input. Writer presence, pending input, committed intent, exact
input digest, parent correspondence and current selected-path identity remain
checked. New sensitive facts still require complete ancestry validation.

Regressions first reproduced both duplicate full replay and publication of a
classification whose sensitive data changed while asynchronous validation was
suspended. The new code captures sensitive fingerprints before validation and
compares them again before publishing. Changes at the same cached revision and
branch changes during input hashing are rejected as well. These tests cover
historical bindings and local live proofs. Focused combined offline validation
passed 246 tests with 32 skipped; two-source mypy and changed-file Ruff passed.
Full affected-route checks remain pending for this phase.

The next continued-session prepared probe began with 24,519 records and 8,982
deferred bundles. It also observed draft input for 1.2 seconds after the first
Worked frame, so late idle stalls are now visible. The probe protocol change
means these timings are not a matched comparison with earlier runs:

| Input phase | Samples | p95 | p99 | Maximum |
| --- | ---: | ---: | ---: | ---: |
| Preparation | 149 | 459.10ms | 638.25ms | 667.94ms |
| Tool execution | 37 | 10.06ms | 37.23ms | 37.23ms |
| Completion | 25 | 406.42ms | 444.09ms | 444.09ms |
| Idle after Worked | 31 | 41.43ms | 55.30ms | 55.30ms |

The controlled tool began after 6,003.91ms. Tool exit to Worked took 1,043.58ms;
the maximum timer-frame gap was 665.73ms. Both new Model Inputs, terminal usage
facts and the new tool result were independently reopened and hash-verified,
with authority bytes/mtime unchanged. Draft and task-cleanup assertions passed.
Preparation and completion still fail the response targets.

A separate diagnostic-only run captured generation-two allocation stacks.
One 230.80ms collection arose while request-evidence recovery read a single
logical component but decoded and retained its entire deferred node bundle.
Another 305.66ms collection arose while the cold node index created per-node
`ModelInputNodeReference` objects. These observations identify concrete retained
allocation owners for the next experiments; they are not acceptance timings.
Any reduction must preserve source-byte authority, validation of unselected
siblings and full-bundle wire compatibility. Earlier selective-decoding
experiments remain withdrawn until a new valid-head comparison proves a gain.

Three additional closed-session candidates of approximately 3.0MB, 13.3MB and
30.2MB have immutable private copies. Original bytes/mtimes and copy hashes are
verified. Native admission and context projection now pass for 372, 2,170 and
3,355 records respectively, with 132, 807 and 1,246 deferred bundles and no blob
references. Private writable fixtures have valid native writer heads, without
changing authority bytes/mtimes or executing historical tools. Performance
validation remains pending before they establish the multiple-scale requirement.

## Allocation and cooperative preparation experiments

A partial-bundle retention experiment continued validating every sibling, but
promoted to a complete cache on a second distinct ordinal. The exploratory
prepared run avoided generation-two collections, yet tool exit to Worked took
1,317.93ms. This did not prove an overall improvement; the extra parsing path
has been withdrawn from the working candidate.

The retained index experiment stores the already-validated immutable identity
and location once, materializes reference DTOs on use, and replaces per-node
callback wrappers with bundle references. Native header validation and full
body identity/hash checks remain. The custom-loader constructor is preserved.
A regression verifies unused indexes retain neither reference DTOs nor loader
wrappers without traversing the private authority bodies.

One identical-prefix pair used 24,459 records, 8,967 deferred bundles, valid
writer heads, fresh processes and the same complete input-observation protocol.
The phase-four baseline took 936.43ms from tool exit to Worked. A private
reference-index plus slotted-DTO experiment took 1,124.13ms, despite reducing
index construction from 622.97ms to 370.33ms. The slotted DTO experiment has not
been applied to Product. One pair cannot establish a latency improvement.

Cooperative materialization alone also remains insufficient: a further pristine
fixture measured 1,275.02ms to Worked, with completion input p99 497.41ms. It
retained a 299.87ms generation-two collection during preparation. The change
does service cancellation before durable writes and between long planning
iterations, but leaves earlier synchronous preparation to investigate.

The current candidate therefore also separates Agent preparation, provider
payload construction, request validation and durable graph materialization with
event-loop checkpoints. After yielding, transcript revision and selected leaf
are rechecked before further work; interrupted planning cannot publish its
sequence-plan updates. Four validation-boundary cases and eight cold/warm
planning cases cover cancellation, concurrent append, branch change and normal
hash-verified reconstruction. The old implementation failed three validation
cases and all eight planning cases. Combined focused validation then passed
259 tests with 32 skips.

Provider payload projection already creates a detached native JSON tree. The
candidate validates that tree without copying it a second time. Returned
transport objects remain independent of both the source and other transport
objects. Two new provider-boundary cancellation tests failed on the old code;
neither durable commit nor transport may run after those interruptions.

Native Model Input JSON trees now use strict no-copy validation followed by the
standard canonical encoder. Frozen/custom containers and rejected native values
retain the general encoder and its existing error contracts. The parity corpus
also checks native projections of every generated sample and shared subtrees,
Unicode and numeric boundaries. Wire schema, canonical bytes, hashes, sibling
validation, GC policy and acceptance thresholds are unchanged. Latency
acceptance for this combined candidate is still pending.

The initial complete AI check exposed five standalone SDK regressions: the
unconditional yields changed completion before an event loop was closed.
Yields are now restricted to requests carrying a durable committer, which is
the long-session Product path under investigation. All five cases and the
prepared-request suite then passed together (38 tests). The complete AI gate
subsequently passed 866 tests, with seven deselected and 90.64% coverage;
76-source mypy, Ruff, catalog and import-boundary checks passed as well.

One preliminary identical-prefix comparison of the combined path produced:

| Large-session metric | Phase-four baseline | Combined candidate |
| --- | ---: | ---: |
| Tool start after Working | 4,788.43ms | 4,898.17ms |
| Preparation input p95 | 275.70ms | 197.68ms |
| Preparation input p99 | 330.02ms | 270.42ms |
| Completion input p95 | 351.37ms | 287.09ms |
| Completion input p99 | 389.19ms | 317.04ms |
| Tool exit to Worked | 936.43ms | 876.35ms |
| Maximum timer-frame gap | 424.43ms | 310.01ms |

Both fixtures began with the same 24,459-record authority prefix, 8,967 deferred
bundles and valid native writer heads. Processes were separate, no CPU-heavy
test job ran during measurement, and draft input continued for 1.2 seconds
after Worked. The candidate still incurred one 243.74ms generation-two
collection. This is one preliminary pair, not the required five-round acceptance
distribution. Preparation and completion input targets and Worked latency still
fail; tool-start time did not improve.

The smaller 372-record sample measured Worked at 237.60ms before and 233.32ms
after, with preparation input maxima of 260.71ms and 194.22ms respectively.
Its six completion input samples measured maxima of 99.80ms and 86.56ms. A
single small-sample pair does not establish sustained responsiveness either.

A continued large-session run executed three actual controlled tools and
measured 895.12ms to Worked. A subsequent stream-tool cancellation displayed
Stopping after 35.33ms; safe tool cancellation to Worked still took 733.51ms.
The cancellation outcome was the expected user abort. Draft, one-Worked and
async-task cleanup assertions passed. Native reopens independently verified both
normal requests and their terminal usage, and all three tool results, without
changing journal bytes/mtime or executing historical tools.

Final affected offline checks so far: Agent 153 passed; Hosting 257 passed,
193 skipped and four deselected; Product persistence/resume and terminal-cancel
E2E two passed. Harness reports 5,161 passed, 724 skipped, three deselected and
25 failed. Those exact 25 node IDs match the earlier macOS Linux-rooted-IO
baseline, with no new failures. Coding reports 3,387 passed, 283 skipped,
55 deselected, 127 failed and 39 errors; the exact 166 failure/error node IDs
match the prior baseline, with none added or removed. `make check-changed`
stops at that known failing Coding route, so this is not a fully green gate.
The separate Harness, Hosting and Product E2E results above cover those paths.

A later final-source repeat on a pristine large-session fixture measured
1,239.32ms to Worked and completion input p99 353.16ms. The source matched the
tested manifest. This variation further limits conclusions from a single pair.
Its two requests, terminal usage, converted-output hash and persisted truncation
flag passed a native reopen without changing journal bytes/mtime. Original
session size/mtime and the immutable sample hash were independently rechecked.

A separate private scheduling experiment changes the six zero-delay CPU-work
checkpoints to 1ms continuations, allowing the queued input/read/render chain
to run before the next CPU phase. Its 155 focused correctness tests passed.
With an identical initial large-session prefix, completion input p99 measured
168.71ms and Worked 1,113.65ms. Preparation still incurred a 292.21ms collection,
with input p99 345.85ms. This is one exploratory pair; the experiment is not
included in the Product candidate or its complete gate results above.

## Verification so far

- Conversation/UnitOfWork regressions after batch extension: 118 passed, 24 skipped.
- Region/screen/cell-width focused tests after ASCII wrapping: 137 passed.
- Screen, Coding screen and cell-width tests after lazy text rows: 130 passed.
- Terminal-input, screen, Coding screen and cell-width regressions after absolute
  deadlines: 167 passed.
- Region, terminal-input and real screen-runner regressions after block-cache
  identity reuse: 135 passed.
- Existing TUI unit route before the final segment changes: 1,312 passed.
- Existing render-contract route before the final segment changes: 311 passed.
- Changed-source Ruff and mypy checks passed (seven source files); architecture
  dependency validation passed, and HarnessTUI's 164-source mypy route passed.
- Full Harness units: 5,111 passed, 724 skipped, three deselected, 25 failed.
  All 25 failures report `rooted IO requires Linux` on this macOS host and
  reproduce on the frozen clean baseline in the exact failed-node selection.
- Original session size/mtime are unchanged, its isolated copy remains mode
  0400, and measured candidate source hashes match the working source.
- Final TUI units: 1,319 passed, 235 deselected. Final render contracts:
  311 passed, 7,615 deselected.
- Final HarnessTUI/Coding UI route: 1,656 passed, 153 deselected, two failed.
  Both are the known macOS PTY EXTPROC restoration cases in
  `test_loading_terminal_adapter`, with the same `2**29` local-mode flag delta.
- Terminal platform: 126 passed. Native terminal contracts: 13 passed.
  Selected host-runtime coverage: five passed, 25 skipped, 10,726 deselected.
- Offline Product E2E: two passed, covering real tool persistence/resume/close
  and terminal cancellation followed by a new message and exit. These are
  short-session correctness checks, not long-session latency acceptance.
- Documentation governance: nine passed. No CI gate, route or platform was added.

The earlier `make check-changed` run stopped in Coding on 128 failures and 39
errors. Of those node IDs, 166 match the known clean baseline. One additional
grep subprocess timing check observed 508ms against a 500ms bound; the exact
case then passed once on the clean baseline and once on the candidate. No
Product timeout was changed. Those results predate the final UI changes and
are not a final green gate.

## Native PTY input waiter follow-up

An input reader can complete while the screen is waiting for a render wakeup.
The previous helper then waited for `asyncio.wait` to resume before cancelling
and joining its owned render waiter. A controlled three-turn scheduling test
showed a ready key could miss the next synchronous preparation boundary. Three
new cases (ordinary text, Escape and an empty chunk) failed on the previous
helper and passed when the input or active-turn completion starts waiter cleanup
immediately. Cancellation still joins the waiter; existing tests cover input
completion during that cleanup and terminal deadlines. This is a narrow input
delivery fix, not a solution to the long-session CPU stalls.

A private probe used a real POSIX PTY, the native terminal reader and a separate
keyboard process that typed on absolute deadlines. It kept one App, Session,
writer and cache across 12 turns: two warmups followed by five alternating
before/after pairs. Each turn ran the same offline prepared transport and one
silent command. Only the input helper's code object changed between variants;
keyboard deadlines were identical. The recovered authority had more than
28,000 records during the formal pairs. Values below exclude warmups.

| Metric | Previous helper | Early waiter cleanup |
| --- | ---: | ---: |
| Input echo p95 / p99 | 217.11 / 453.81 ms | 222.61 / 507.55 ms |
| Completion-phase echo p95 / p99 | 391.46 / 491.46 ms | 229.12 / 376.03 ms |
| Preparation-phase echo p95 / p99 | 280.99 / 482.59 ms | 467.85 / 688.75 ms |
| Tool exit to Worked median / p95 | 1,294.55 / 1,329.02 ms | 1,027.44 / 1,276.65 ms |
| Maximum echo | 549.48 ms | 744.35 ms |
| Generation-two collections | 3 | 3 |

The longest candidate preparation delay included a 385.22ms generation-two
collection. The between-variant differences cannot be attributed solely to the
input helper, and the aggregate input tail and Worked target remain unmet.
All 12 turns retained drafts and one Worked event, with no remaining asyncio
tasks at disposal. Native reopening rebuilt 24 snapshots with their terminal
usage and checked 12 tool outputs, including their hashes and truncation flags.
It ran no historical tools and left the authority file unchanged. The PTY probe
observed the known macOS `EXTPROC` mode restoration delta (`2**29`); all
control characters restored. The final TUI unit route passed 1,550 cases with
seven skipped; changed-source Ruff and mypy passed.

The same real PTY setup also sent Escape 200ms after the silent command ended,
while the final model-input commit and Working state were still active. One
pilot and 12 more continuous turns completed valid cancellation; the latter
included two warmups and five alternating before/after pairs. Formal-pair
Escape acknowledgement p95 was 686.07ms before and 642.32ms after; the medians
were 369.93ms and 468.17ms. Tool exit to Worked p95 was 1,677.31ms and
1,676.14ms. Input echo p99 was 531.93ms and 469.12ms. The pilot's 663.09ms
Escape delay overlapped a 417.28ms synchronous prepared-request validation,
including a 343.78ms generation-two collection. The formal pairs also saw
generation-two collections of roughly 300–350ms. This establishes a separate
long-session CPU/GC stall that the input waiter change cannot remove.

All 13 cancellations were acknowledged during Working and retained draft input
and one Worked event. Native reopening checked all 13 new snapshots, terminal
usage, successful tool outputs and cancellation outcomes, including snapshots
that did not reach transport (none in this run). No historical tool executed;
the authority file was unchanged during verification. These cancellation
results also miss the 100ms Escape and 250ms Worked targets.

Four further five-turn runs kept the real PTY keyboard, prepared offline
transport, native writer head and same continued long-session authority. The
session grew from about 28,800 to 29,100 records across these runs, so the rows
are workload observations, not matched before/after performance comparisons.
The tool-phase column spans the interval from first tool start to final tool
exit; preparation and completion are classified by intended physical key time.

| Workload | Preparation echo p99 | Tool-phase echo p99 | Completion echo p99 | Worked p95 |
| --- | ---: | ---: | ---: | ---: |
| Streaming command | 482.51ms | 18.32ms | 552.34ms | 1,631.38ms |
| Three consecutive tools | 511.58ms | 37.55ms | 576.69ms | 1,715.39ms |
| 1.08MB ASCII result | 466.66ms | 24.25ms | 494.73ms | 1,720.77ms |
| 2.16MB Unicode result | 402.48ms | 22.24ms | 400.71ms | 1,357.84ms |

The streamed result and both large results were truncated as intended; the
Unicode truncation retained valid byte boundaries. Each run preserved drafts,
emitted one Worked event per turn and disposed its async tasks. Native reopening
verified all 40 snapshots with terminal usage, 30 output hashes and their
truncation flags, without executing historical tools or changing the authority
file. Render frames in these four runs were at most 13.22ms, while event-loop
delays reached 564.16ms and generation-two collections took roughly 242–361ms.
The main observed freezes occur in preparation and completion, including the
Working-to-Worked path; these runs do not establish that all tool workloads
meet the response targets.

## Remaining acceptance work

- Complete five matched actual-screen rounds for quiet commands, sustained
  output, consecutive tools, large ASCII and Unicode results, with normal
  completion and cancellation. Verify output/truncation metadata and drafts.
- Complete matched file-backed Product measurements through the prepared offline
  transport, including separate valid-head and cold-recovery workloads. The
  completed exploratory prepared round does not replace matched acceptance.
- Investigate cold full-window rendering and resize. Its uninstrumented first
  frame still took 15.18 seconds with the first committed candidate. The bounded resume
  window and warm-cache improvement do not prove long-running resize is safe.
- Verify multiple history scales and rerun affected offline/native routes
  against the final source, reporting known environment baseline failures.
- Apply input p95/p99, Escape, timer and Worked thresholds only to valid matched
  measurements. The goal remains active and completion is unproven.
