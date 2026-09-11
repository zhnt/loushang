# G18 Linux Facade Local Delivery

## Status And Scope

Status: in progress; source candidate and paired installations frozen; exclusive-window
inert A/A accepted, native stability and all A/B performance acceptance pending.
Tracking: [G18 #578](https://github.com/zhnt/loushang/issues/578).
Authority: [accepted G18 plan](startup-performance-plan.md), including its measurement,
scheduling and facade-budget addenda. This record does not replace the thresholds.

The current goal is the independently committed Linux facade candidate, frozen paired
installations, stability and performance acceptance, followed by three-view review,
corrections and local delivery. No push, merge, dispatch or lifecycle expansion.
macOS/Windows remain separate pending validation, not implicitly passed.

## Immutable Source Pair

| Role | Commit | Contents |
| --- | --- | --- |
| A | `5f7346bb93c0b58203f60450a50cbf54c5713cec` | Shared cleanup identity repair, original eager facade |
| B | `537cc91099a1a48bf16ec15f9d20772a6204737a` | A plus explicit lazy Coding facade and its compatibility/budget tests |

`git diff A B -- src pyproject.toml uv.lock` contains only
`src/loushang/coding/__init__.py`. B is a four-file atomic local commit marked
performance-pending. The checkout was clean after the commit. The cleanup fix
is common to both sides and cannot be attributed to facade performance gains.

Historical `9bc69361494293595ae424be225c61e3226a9996` is not the new A.
The original [freeze record](startup-performance-g18-linux-freeze.md), existing wheel,
installations and failed/inconclusive reports are retained, not relabeled or pooled.
In particular, historical native warm 30/41 stability and absent ready timeout do
not constitute acceptance of this pair.

## Build And Installation Preparation

New task prefix: `.artifacts/g18-linux-delivery/`.
Each source snapshot was exported from its own Git commit, including `src`,
project/lock and license inputs. Builds used the explicit CPython 3.11.15,
task-private HOME/TMP and existing isolated uv cache, offline. No ordinary lane
environment or old baseline installation was overwritten.

Build exec 67754 completed with exit 0, private root `/var/tmp/lg18-tests-VWvLkS`.
Installation exec 27486 completed with exit 0, private root
`/var/tmp/lg18-tests-bddjdY`: 40 hash-locked non-Product dependencies plus the
appropriate non-editable wheel in each of `install-a`, `install-a2`, `observer-a`,
and `install-b`. A was built once; both A/A references and the observer use those
same wheel bytes. The observer is never a measured installation.

| Input | SHA256 |
| --- | --- |
| `wheels-a/loushang-0.1.0-py3-none-any.whl` | `9c1d1439f7b6deb7ac7cf8108fe12179674582e92fdd0e8272bedaa62a14061b` |
| `wheels-b/loushang-0.1.0-py3-none-any.whl` | `a6ee9d627d8237f26edd2a909181cace538a8299a028c98682d96786b678a6e4` |
| Original hashed dependency export | `2414aec09776d1f87ee015c75643b3b38e5bf246dcb5e9deaffdd739ca19d7dd` |
| `uv.lock` | `556547755c39ef7063c8cb1c3624b322d13216fc8abe621daa6fe095d5b1146d` |
| `pyproject.toml` | `41a1e51a74cc407cada03c89f90195a8600e07c3cb527a3602bef4bd3049593e` |

Source/wheel, package inventory, installed bytes, direct URL, wrapper, Python and
dependency matching are separate required checks; successful installation alone
does not prove those checks or startup/performance acceptance.

Identity verification exec 95668 completed with exit 0, private root
`/var/tmp/lg18-tests-eRfhoy`. Both wheels match their immutable commits across
1,304 package files. Their only differing contents are
`loushang/coding/__init__.py` and the corresponding wheel `RECORD`.
The common package-path inventory SHA256 is
`944c0973765959dee88d7cc4b3b06e2df9dbb8854e6eaf9d82855f083bbc37bb`.
All four references pass original `verify_pinned_install`, including each
installation's own uv-generated wrapper/RECORD and wheel direct URL; their
41-distribution inventories, six entry targets and exact interpreter build
`3.11.15 (main, Mar 10 2026, 18:16:52) [Clang 21.1.4 ]` match.
This verifies the pair, not installed readiness or a performance improvement.

## Acceptance Checklist

- [x] Independent facade commit; only approved Product file differs from A.
- [x] Three-view submission/freeze pre-review; no blocking P1/P2.
- [x] New offline wheels and four independent reference installations prepared.
- [x] Immutable source/wheel and four installation identities verified and recorded.
- [x] Installed HOME isolation correctness controls pass on both A and B.
- [x] Fixed-slot recovery correctness controls pass.
- [x] Inert ten-case A/A stability accepted under the existing policy (exclusive-03 only).
- [ ] Native warm and absent A/A: each complete seven-case, 41-metric comparison accepted.
- [ ] Inert A/B: priority help targets and other-entry no-regression accepted.
- [ ] Native warm and absent A/B: ready, first use and settlement no-regression accepted.
- [ ] Final three-view evidence/code review, findings corrected and rechecked.
- [ ] Delivery records and local commits complete; no push/merge.

The first new inert A/A collection is terminal: exec 97286 exit 0, parent private
root `/var/tmp/lg18-tests-whyUw4`, retained scratch
`/var/tmp/loushang-g18-baseline-2eqnxr3c`, output
`.artifacts/g18-linux-delivery/inert-aa-01/report.json` (SHA256
`4437a31995dbf79ae4a493346ba0bea816a54ca99526f1dc5c193c974c06fb43`).
It used `install-a` and `install-a2`, the single A wheel, explicit A source on both
sides, `/var/tmp`, two blocks and ten pairs per block, with all ten cases.
All 400 formal samples and 40 declared warmups are valid, with identical before/
after helper inventories. Collection ran 02:10:16–02:46:48 UTC on 2026-09-10.

The comparison is **inconclusive: nine cases pass, hosted-help does not pass**.
Its four block/install medians are 3.986117, 4.385583, 3.801666 and 4.146801 seconds;
the 0.583917-second span exceeds the original 0.380167-second stability boundary.
Each side is internally stable, but that does not satisfy the required four-group
A/A calibration. No threshold, sample or original report was changed, and no A/B
performance collection has begun. This is not an accepted baseline.

Existing-data decomposition shows that side b's hosted-help CPU medians exceed
side a's in both blocks (3.802862 vs 3.561810 seconds; 3.691341 vs 3.451675 seconds).
The difference is therefore not explained solely by wall-clock scheduling wait.
The import-coding and hosted-tui-help controls do not show the same consistent
side pattern. This is a diagnostic observation, not a root-cause conclusion or
permission to subtract CPU/wait time from the original measurement. The recorded
machine has one CPU and affinity `[0]`; further CPU-affinity narrowing is not an
available isolation remedy. Investigate before scheduling another timing run;
independent HOME/recovery correctness controls may still proceed serially.

## Installed HOME Isolation

The original HOME-only native command completed as exec 85342, exit 0, parent
private root `/var/tmp/lg18-tests-gOvvxy`. Its report is
`.artifacts/g18-linux-delivery/home-isolation-01/report.json`, SHA256
`bb33ad052e34f1ca32bca3b7525ef1bb71153b39f7a700c86e33337084bea0e8`;
scratch `/var/tmp/loushang-g18-native-kbvh649d` is retained. Each installed side
has the four original controls: leaked embedded rejects poison JSON, isolated
embedded reaches ready and exits, leaked foreground exposes session-unavailable,
and isolated foreground opens a member. All eight controls settle, both ambient
before/after inventories match, and both parent-environment witnesses are unchanged.
This proves the scoped isolation controls and actual installed startup paths;
their diagnostic timestamps do not constitute A/B performance acceptance.

## Fixed-Slot Recovery Correctness

Exec 30453 completed with exit 0, private parent root
`/var/tmp/lg18-tests-2StBrR`, retained scratch
`/var/tmp/loushang-g18-native-xcy_o1wg`. Report:
`.artifacts/g18-linux-delivery/slot-recovery-01/report.json`, SHA256
`6843461c2caa745d4dbc0745977b219504bd7a4a04c4fa4c81173486ae84d631`.

Both cwd and user-home/global complete preparation followed by restored A/B/A
at the same fixed prefix: eight valid stages in the exact declared order.
Both slot builds complete; all eight pre/post installation receipts match their
respective slot build. The two references use the same baseline A wheel, not
the facade candidate. The retained owner returns only after physical cleanup;
each preparation records two settled real launches, and each restored launch
records ready, visible history, first command and settlement milestones.

Post-run audit matched all eight raw observer receipts, all 1,200 current helper
hashes/modes and their before/after inventories. Each retained seed archive still
matches its full manifest; the unchanged manifest digests across restores 0–3 are:

- cwd: `72be729a1080ca48dab8606bb4448e7338c0985bc949868b8592ab5dc9fb0d6b`.
- user-home/global: `bbe930d983abcd2971d3f7039902f64cebe13fea10f053b83298c1be1e94cced`.

The coordinator verifies restored bytes/modes/mtime before each operation and
checks the immutable seed afterward. Inode/ctime are not preserved, and this
does not establish a warm Store-head condition. The final slot is idle, not
failed, and active on A. `complete-record-only` with comparison `not-evaluated`
is the expected correctness-only result, not native A/A performance acceptance.

## Native Warm A/A — Complete, Inconclusive

Exec 35360 completed with exit 0, private parent root
`/var/tmp/lg18-tests-K9Tm8U`; retained scratch
`/var/tmp/loushang-g18-native-17l_6az5`. Report:
`.artifacts/g18-linux-delivery/native-aa-warm-01/report.json`, SHA256
`eec2d6772a88e88b7193907a4b4e9c4d95b9680db048d5c7e65fbd936bd20780`.
This is the new shared-cleanup baseline against itself, not A/B and not the
historical 9bc6936 warm run. Both fixed-slot builds use the same frozen A wheel.

All 308 observations are complete and valid: exactly 280 formal samples and 28
declared warmups, with all seven cases, two blocks, ten pairs per block, reversed
case order in block two and the original alternating side order. The post-run
audit matched that exact sequence, all raw observer receipts, all sample pre/post
installation identities against their slot builds, 616 hashed cache receipts,
both opaque seed archives, and all 1,200 helper hashes/modes before/after/current.
Each recovery scope records 44 resets against one unchanged snapshot. Warm cache
preparation preserves its before/ready inventory. The final slot is idle and not
failed; the original collector also completes its final reference/observer pins.

Independent read-only contract review reproduced all 41 comparator results:

| Case | Stable metrics | Inconclusive metrics |
| --- | ---: | ---: |
| embedded | 4 | 1 |
| foreground | 1 | 3 |
| local-mux | 1 | 5 |
| g14-stdio | 2 | 1 |
| recovery-cwd | 1 | 4 |
| recovery-global | 1 | 4 |
| product-first-use | 6 | 7 |
| Total | 16 | 25 |

The overall verdict remains **inconclusive**, not accepted. Failures of stability
include cross-block/four-group median spread and within-group MAD; there is no
sample failure or comparator mismatch. For example, foreground ready's A-block
spread is 0.748791 seconds against a 0.744206-second boundary; proximity is not
permission to round to pass. Recovery-cwd ready's B-block spread is 1.880351
seconds against 1.004704, so this is not merely a numerical boundary issue.

Existing-data diagnosis also finds two interrupt-duration clusters around 0.17
and 0.215 seconds. Different group proportions place medians in different
clusters; original AB/BA paired median(B-A) differences are only +0.002342 and
-0.000967 seconds. Do not interpret the roughly 40 ms aggregate side-median
difference as a stable side overhead or a Product regression, and do not use
paired differences to replace the frozen four-group calibration rule. Correlated
recovery ready/history/spawn boundaries are not three independent root causes.

Read-only source inspection and independent contract review support a possible
poll/render phase effect, not a demonstrated cause of the interrupt clusters.
The [Product terminal loop](../../../../src/loushang/harnesstui/mux/terminal.py)
sleeps 50 ms after each event poll; its render loop normally wakes on input or
a 50 ms timeout while the long-lived poll task remains pending. These are not
strict 50 ms periods: operation time and scheduling also contribute. In contrast,
the [terminal observer](../../../../tests/tui/terminal_process_support/base.py)
notifies waiting readers when output arrives, so its 50 ms condition-wait bound
does not establish a fixed detection delay. The original interrupt metric spans
Ctrl-C write through the visible idle witness, not cancellation processing alone.

Following absent collection and its evidence audit, a possible bounded,
diagnostic-only follow-up is observer segmentation: timestamp Ctrl-C write,
PTY read return/output notification, and the original predicate's first success,
preserving its checkpoint and witness. Use fixed-capacity in-memory records and
write them only after settlement. Such evidence could locate delay after reader
receipt, but cannot distinguish Product polling/rendering from scheduling before
the reader receives output. This is not an approved execution schedule, a reason
to alter the frozen wheels or timings, or permission to retry calibration; any
run still requires predeclared counts, stop conditions and review.

This review is not final delivery review. Preserve the full result; do not retry
warm until green or start A/B acceptance. The separately required absent A/A was authorized to
proceed once, serially, with a fresh slot/output and original conditions after
capacity and retained-owner completion checks. It cannot supersede warm's
inconclusive result. Further warm calibration requires an actionable diagnosis
and a predeclared condition change, without reducing scenarios or thresholds.

## Native Absent A/A — Complete, Inconclusive

Exec 68239 completed with exit 0, private parent root
`/var/tmp/lg18-tests-BafgVo`; retained scratch
`/var/tmp/loushang-g18-native-0yv1kw4j`. Report:
`.artifacts/g18-linux-delivery/native-aa-absent-01/report.json`, SHA256
`b5714d264c46858a1dda5d3c52371a78669c004265de34ff624f6739ab407495`.
Both references and fixed-slot builds use the same frozen shared-cleanup A wheel.
This is the separately required absent condition, not a warm rerun or A/B.

All 308 observations are complete and valid: 280 formal samples and 28 declared
warmups, with the exact seven-case/two-block/ten-pair ordering and iterations
1–308. Main audit and independent contract review reproduced all 41 original
comparator results. Main audit also matched all 308 raw observer receipts,
all sample and preparation pre/post installation receipts against their slot
builds, 616 hashed cache receipts, and 1,200 helper hashes/modes before/after/current.
Every pre-launch cache receipt has empty installed and external ready inventories;
normal writes during observation remain allowed. This is not an OS page-cache flush.
Both frozen A/B wheel hashes are unchanged. The final slot is idle, active on B,
and not failed; the original collector completed final reference/observer pins.

Both seed preparations and retained archives match their manifests, with 44
resets per recovery scope and unchanged seed digests/timestamps across restores:

- cwd: `9c0ef2cbb3474f47045c283502c22cc66525d0d76e077930ee7967ac911804b2`.
- user-home/global: `c6c4b58e9ad8c9ae91952f3226672f4c335a8bcb584f87d014d37437235e3a37`.

The overall verdict is **inconclusive: 28 stable metrics, 13 inconclusive**.
Collection success does not establish calibration or performance acceptance.

| Case | Stable | Inconclusive | Inconclusive metrics |
| --- | ---: | ---: | --- |
| embedded | 4 | 1 | settlement |
| foreground | 3 | 1 | settlement |
| local-mux | 4 | 2 | attach frame; detach settlement |
| g14-stdio | 2 | 1 | settlement |
| recovery-cwd | 4 | 1 | settlement |
| recovery-global | 4 | 1 | settlement |
| product-first-use | 7 | 6 | dev attach frame; first tool; interrupt; review/dev/reattach detach settlement |
| Total | 28 | 13 | |

For example, foreground settlement's four-group median spread is 0.205987 seconds
against a 0.169132-second boundary. Local-mux attach spread is 0.596088 against
0.444714. Product first-tool A0 MAD is 0.022184 against 0.016012. These displayed
values are rounded only for reading; the comparator uses the original exact values.

Across the warm and absent conditions, 15 metrics pass in both, 12 are inconclusive
in both, 13 pass only absent, and dev attach frame passes only warm. This compares
stability verdicts, not speed; do not pool conditions or assemble a passing set
from different runs. Interrupt again has roughly 0.17/0.215-second clusters, but
the side direction reverses: absent A block medians are 0.215294/0.214118, B
0.174073/0.175745, whereas warm has A lower and B higher. This contradicts a fixed
B-install overhead explanation; it does not prove poll/render or observer causality.

Preserve inert, warm and absent inconclusive results. No A/B acceptance run has
started. Remaining diagnosis should distinguish available exit/output/reader
boundaries, especially for settlement/detach, without calling every failure machine
noise. Any additional observer segmentation remains diagnostic-only and requires
predeclared counts, stop conditions and review. No automatic reruns, changed
thresholds, selective samples, dispatch/lifecycle expansion, push or merge.
This scoped evidence review is not final three-view delivery approval.

## Observer Segmentation Follow-Up — Reviewed Design and Completed Diagnostic

The current formal receipts retain aggregate milestones and spawn identities,
not per-call wait/idle/reader intervals. Those intervals cannot be reconstructed
from the existing formal data. The historical eight-observation settlement
diagnostic used the old 9bc6936 baseline; it localized its foreground cost before
the original wait returned, not in idle/close, but cannot establish the cause of
the new baseline's spread. Its bounded call-wrapping approach can be reused without
rerunning or relabeling the historical evidence.

Reviewed next step: one diagnostic-only series of exactly eight complete original
fixture invocations using the two existing A references (`install-a`, `install-a2`)
and the unchanged A observer. Neither side is the facade candidate. New ignored
diagnostic files/output, task-private HOME/TMP under `/var/tmp`, fresh Product
state for every invocation, and new per-reference external bytecode roots are
required. External caches persist within this series; installed caches are recorded
as found, not cleared. Preparation invocations do not establish the formal warm
or absent condition. All eight observations remain ineligible for acceptance.

| Order | Case | Reference | Role |
| --- | --- | --- | --- |
| 1 | foreground | A1 | preparation |
| 2 | product-first-use | A1 | preparation |
| 3 | product-first-use | A2 | preparation |
| 4 | foreground | A2 | preparation |
| 5 | foreground | A2 | diagnostic |
| 6 | product-first-use | A2 | diagnostic |
| 7 | product-first-use | A1 | diagnostic |
| 8 | foreground | A1 | diagnostic |

Each invocation retains the original fixture, commands, synthetic model transport,
ready/interrupt/exit witnesses, inner deadlines, 150-second outer retained owner
and physical settlement assertions. Eight fixture invocations are not eight
processes: Product first use includes server, terminal and command children.
Before/after installation, source/wheel, helper and diagnostic-file pins must match.
Record original measured/observer identities, exact fixture order, cache condition,
per-invocation load, raw observation and diagnostic receipts. Any failure, dropped
event, incomplete boundary or pin mismatch stops the series and invalidates the
diagnostic; retain partial evidence and do not replace or append observations.

Observer-only hooks may wrap original calls to terminal/Popen wait, original
`_try_wait`, idle-output drain, close and the admitted terminal reader's existing
join; reuse the prior transparent call-wrapping logic. Also record Ctrl-C write,
output-buffer publication, reader-done notification and each original `read_until`
predicate call/return. Do not add process polling/reaping, threads, signal handlers,
Product hooks, waits, witness calls or a global profiler. Original arguments,
return objects, exceptions and cancellation must pass through exactly once even
when recording fails; recording failure is sticky and never bypasses cleanup.
Do not coerce or format original return objects to record them. If the original
probe fails and diagnostic publication also fails, preserve the original failure
as primary and retain the publication failure only as additional information.

Use at most 8,192 events and 4 MiB total diagnostic content per invocation,
including decoded raw chunks, predicate evidence and metadata, with identical
limits for preparation and diagnostic roles. Enforce the UTF-8 serialized-byte
budget while buffering, not only at final publication. Capacity exhaustion marks
the trace sticky-invalid; it must not interrupt original work/cleanup or permit
silent clipping followed by acceptance. Publish bounded evidence only after the
original probe returns or raises; do not retain unbounded output snapshots.

Output mapping uses original decoded Unicode strings, per-driver chunk ordinals
and cumulative character ranges, and the original character checkpoint
(`len(raw_output)`), not PTY byte offsets. UTF-8 bytes measure capacity separately.
Record the original predicate input's character length and bounded fingerprint
to correlate it with the retained chunk prefixes without storing each growing
snapshot. Offline replay alone evaluates the original interrupt witness on those
prefixes. Buffer truncation or incomplete mapping invalidates the diagnostic,
not permission to use a later witness or repeat the run. No terminal content is
sent to an external service.

Wrap the original `_record_output` with entry/return timestamps; do not insert a
new Product/condition notification hook. These timestamps bracket the call, not
the exact publication point: its return also follows responder work. Predicate
input-prefix evidence supplies the publication/check relationship; if intervals
overlap, retain that uncertainty instead of claiming a precise positive delay.
Do not reread `raw_output` as a substitute for the actual predicate argument,
reinvoke the live predicate, or add synchronization/notifications to obtain a more
precise timestamp. Offline replay uses the frozen witness semantics and must
agree with the original recorded predicate outcome.

Admission and validation use invocation identity plus spawn/driver ordinals and
original PID/argv, not PID alone. Correlate each admitted driver object with its
own original reader object; only that reader's existing join may be recorded,
never arbitrary thread joins. Non-admitted calls pass through untouched. Cover
early reader output during driver construction or reject the trace as incomplete.
Distinguish server, each terminal attachment and command subprocesses, and use
unique call IDs/thread identities for nested or repeated calls. The validator
must pair call entry/return events, verify original milestone anchors and relevant
per-driver wait/close boundaries, and reject missing or unmatched records.
Nested intervals must not be summed as independent costs. Reader notification is
not proof of reader termination; a negative-to-positive `_try_wait` window is not
an exact exit time or deductible overhead. Readiness notification can wake both
the observer's condition wait and POSIX select early; neither 50 ms timeout is a
fixed detection delay. Output already received versus predicate success can
localize the observer tail, but cannot identify Product poll/render/RPC or
pre-reader scheduling as the cause of the remaining interval.

Architecture, evidence-contract and compatibility design review/re-review found
no remaining P1/P2. Initial P2 findings on character/byte mapping, raw-content
capacity and publication timing were corrected above; the original failure and
per-reader ownership requirements were also made explicit. This is design
approval only, not evidence of a working diagnostic or a performance result.

Before any real invocation: implement only the ignored diagnostic, exercise
mock-only transparency/bounds/identity/partial-failure controls, and review the
implementation. This design does not authorize a new
formal A/A run, A/B acceptance, threshold change, Product change or final delivery.

### Implementation and execution receipt

The ignored implementation lives in
`.artifacts/g18-linux-delivery/observer_segmentation/`. Its wrapper, offline
validator and fixed-order coordinator passed 67 mock-only controls and Ruff.
Three-view implementation review/re-review closed two P2 findings before any
real invocation:

- Foreground directly assigns `first_command_seconds` and
  `spawn_through_first_command_seconds`; they do not generate `probe.mark` calls.
  The validator now preserves all four original foreground metrics and checks
  the direct values against original spawn/write/read/ready/settlement anchors.
  A control invokes the original foreground orchestration with process and
  terminal operations fully mocked, rather than relying only on synthetic rows.
- The last chunk in an actual predicate input is not necessarily the earliest
  chunk containing the witness. Offline replay now separately retains the
  earliest complete prefix satisfying the frozen checkpoint/witness and the
  actual predicate input's publication bracket. Controls cover Unicode,
  cross-chunk witnesses, multiple chunks before a predicate, and overlapping
  publication/check intervals. No live witness calls were added.

The sole predefined series completed all eight invocations in the table above;
the retained coordinator session exited 0. No invocation was retried or replaced.
The report is
`.artifacts/g18-linux-delivery/observer-segmentation-01/report.json`, SHA-256
`2cb7f47baf8f21108a9096502021d6deff1e033918bc23edeb6d959c7bbc6aea`.
Private scratch and original receipts remain at
`/var/tmp/lg18-segments-8rdsp5cp`; parent environment is
`/var/tmp/lg18-tests-tQnHAh`.

Both A references and the observer retain the shared cleanup baseline wheel.
Before/after installation receipts match; the 1,200 helper pins, seven diagnostic
file pins and wheel hash match before/after and the post-run read-only audit.
All eight original observations remain `observed`, `valid=false`, not accepted
performance samples. The audit revalidated each original observation and raw
trace, receipt hash/size, exact order and offline segmentation result. There were
618–1,637 events and 417,479–850,237 trace bytes per invocation, no dropped events
or sticky recording failure. Even the compact per-sample coordinator metadata
plus both raw receipts remained below 4 MiB (maximum 2,948,538 bytes). Installed
caches were inventoried as found and never cleared; external caches persisted
per reference as designed. Preparation and diagnostic observations are not pooled
as a formal warm/absent condition.

### Bounded findings and next boundary

Foreground settlement in the two diagnostic-role invocations was 1,392.491 ms
(#5, A2) and 1,803.476 ms (#8, A1). Their original `Popen.wait()` intervals were
1,376.573 and 1,782.697 ms respectively. Idle-drain calls were 0.027–0.033 ms,
close calls 0.242/0.306 ms and admitted reader joins 0.028/0.040 ms. Thus this
instrumented pair localizes most settlement time and its spread before the
original process wait returns, not in those observer tail operations. Nested
intervals are not summed or deducted from original milestones.

For the four first-use invocations, all figures below are milliseconds. The
middle column brackets the original output call relative to the original
interrupt start; it is not a precise publication timestamp. The final column
bounds the interval from that publication bracket to entry of the successful
original predicate call; predicate execution itself is separate.

| Invocation / role | Original interrupt | Earliest witness publication bracket | Publication-to-predicate-entry bracket |
| --- | ---: | ---: | ---: |
| #2 A1 preparation | 216.504 | 215.665–215.888 | 0.116–0.339 |
| #3 A2 preparation | 167.556 | 166.838–167.045 | 0.050–0.258 |
| #6 A2 diagnostic | 166.159 | 165.458–165.655 | 0.068–0.265 |
| #7 A1 diagnostic | 170.661 | 169.587–169.803 | 0.383–0.598 |

The successful predicate calls took 0.364–0.390 ms. In these observations, the
large interval precedes the witness's output-publication bracket; the sub-ms
observer tail cannot explain a 40–50 ms separation. This is localization within
the instrumented series, not proof of the cause of the older formal A/A results.
It does not distinguish Product emission/poll/render/RPC work from scheduling
or other pre-reader delay. The raw output never leaves the local environment.

Across all four foreground observations (including preparation), the last
negative-to-positive original `_try_wait` observation windows were
50.290–50.359 ms, and reader-done-return to process-wait-return was
3.498–26.400 ms. Neither is an exact process exit timestamp or deductible fixed
tax; reader notification remains distinct from reader termination.

This closes the bounded observer diagnostic, not G18. It does not justify
changing observer deadlines/polling, modifying Product dispatch/lifecycle,
relaxing stability thresholds, starting formal A/B, or repeating A/A until green.
Further measurement needs an actionable, reviewed condition change or a scoped
diagnostic of the remaining pre-output/pre-wait-return interval. The facade
candidate remains implemented but its performance benefit is unaccepted;
inert/warm/absent A/A retain their original inconclusive verdicts.

### Resource preflight after the observer diagnostic

A read-only resource preflight on 2026-09-10 (recorded by 10:11 UTC) found
material current memory/paging pressure. It ran no Product or new timing series.
The checks were repeated outside the managed sandbox, matching the execution
context used for G18 tests, because sandbox process listings are namespace-limited
and one separate read-only command failed before execution while preparing a
`/tmp/.agents` mount with `Quota exceeded`.

Observed outside the sandbox:

- One online CPU; affinity remains `[0]`. The current scope and visible user-slice
  ancestors expose `cpu.max = max 100000` and zero throttled periods/time. There
  is no evidence here of an adjustable task CPU-quota bottleneck or another CPU
  to isolate onto.
- `/proc/meminfo`: `MemTotal=1676332 kB`, and one snapshot had
  `MemAvailable=271796 kB` (approximately 1.60 GiB total / 0.26 GiB available).
- The current Codex control process (PID 2046146) had 847,672 KiB RSS in the
  process listing, then 570,132 KiB RSS and 721,280 KiB swapped in a later status
  snapshot. These are separate snapshots, not simultaneous totals or a leak
  diagnosis. Paused peer agents do not eliminate the controller's memory cost.
- The two interval rows of outside-sandbox `vmstat 1 3` reported swap-in/out
  `620/0` and `7860/98128` in its default KiB/s units; the latter interval had
  `wa=31` (approximately 95.8 MiB/s swap-out and 31% I/O wait). The first,
  since-boot row is not used as an interval measurement.
- A later PSI snapshot reported memory `some/full avg10=8.18/6.61` and I/O
  `some/full avg10=12.24/10.39`. This is contemporaneous environment evidence,
  not a reconstruction of pressure during any earlier performance sample.

The existing inert A/A rows were also decomposed without new execution:
hosted-help user-CPU medians for a/b were 3.362980/3.535183 seconds in block 0
and 3.267134/3.481105 in block 1; system-CPU medians were
0.216680/0.223555 and 0.196495/0.214890. Thus a pure wall-wait explanation remains
insufficient. Current paging pressure must not be presented as the proven cause
of historical A/A spread or all pre-output/pre-wait-return time.

The next timing step needs a user-coordinated resource change: either stabilize
capacity on this Linux machine or provide a task-isolated Linux runner. Do not
kill peer/control processes, change system swap/cache policy, modify Product
dispatch/lifecycle or relax statistical gates to work around the environment.
No new hard memory SLO or substitute acceptance condition is introduced here.
After a resource/environment change, record that condition and re-establish the
full original A/A checks before the required A/B acceptance; old and new timings
must not be pooled or their difference attributed to the facade. The G18 goal
and all remaining acceptance requirements stay open pending that coordination.

### Resource-condition resumption — reviewed pre-execution plan

At the resumed session on 2026-09-10 (preflight recorded by 12:19 UTC), there is
an observable condition change, not merely another request to retry: the prior
controller PID 2046146 no longer exists; the new controller PID 3023451 has
222,300 KiB RSS and zero swapped memory. Two outside-sandbox snapshots show
924,864/941,352 KiB available memory, with no swap-out in their four one-second
interval rows. The second snapshot has zero memory/I/O PSI avg10. CPU count and
physical RAM have not increased; this is a lower-controller-footprint condition,
not a claim of a dedicated runner or a memory expansion. These idle observations
neither prove stability under Product load nor explain previous A/A outcomes.
The bounded preflight receipt is retained at
`.artifacts/g18-linux-delivery/resource-resume-01.json`.

Three-view pre-execution review passed with no P1/P2. The single next collection:

- Invoke the unchanged `scripts/dev/measure_g18_startup.py` against existing
  `install-a` and `install-a2`, both using source
  `5f7346bb93c0b58203f60450a50cbf54c5713cec` and the same already frozen A wheel.
  Candidate B is not measured. Use the original isolated CPython 3.11.15 runner,
  offline uv, private HOME/TMP and `/var/tmp` scratch parent.
- Fresh, exclusive output directory:
  `.artifacts/g18-linux-delivery/inert-aa-resource-02`.
  Two blocks, ten pairs per block, all ten unchanged cases, alternating side
  order and reversed case order in block 1. Exactly 400 formal samples plus
  40 declared warmups, plus four installation-verification probes outside those
  timing samples; no selective case, retry, replacement or append.
- Preserve the original warm-bytecode/fresh-process conditions, argv, output
  assertions, 60-second measured-sample deadline, the original 75-second outer
  retained owner and physical settlement contract,
  source/wheel/install/helper before/after verification and exact comparator.
  New external cache paths belong to this report. No profiler or polling hook
  is inserted; no existing cache, report, installation or Product state is
  manually cleared or modified.
- Reviewers and task tests/builds must finish before timing. Record a final
  resource snapshot after review and a post-collection snapshot; preflight
  readings are descriptive, not newly invented acceptance gates. Retain the
  original per-sample load values. If collection fails, keep partial evidence;
  if the full comparison is inconclusive, do not automatically repeat it.

This authorizes neither A/B nor an automatic second A/A attempt. Native warm and
absent A/A, both native A/B conditions, inert A/B and final delivery review remain
required. Revisit their scheduling after auditing this complete inert result;
passing inert alone does not close G18. Prior formal and diagnostic reports stay
immutable and separate: no pooling, no replacement, and no attribution of old/new
timing differences to the unchanged Product or the unmeasured facade candidate.

### Completed resource-condition resumption — audited, still inconclusive

The one authorized collection is terminal: session 6683 exited 0, from
2026-09-10 12:24:21 to 12:57:17 UTC. Its immutable record is
`.artifacts/g18-linux-delivery/inert-aa-resource-02/report.json`, SHA-256
`c8ceca479de42269ae03e06767f421821a12ee1d0654a5186005bd3264a44c80`.
Report status is `complete-record-only`, comparison phase `aa`, and the overall
verdict remains **inconclusive**. Normal collector exit is not acceptance.

All 440 observations are complete and valid: 400 formal samples and 40 explicit
warmups, with the original exact identities, side/case order, argv, cwd, output
predicates and deadlines. All exit codes are zero and stderr is empty. The four
installation-verification probes are outside those timings. Both sides use the
same frozen A source/wheel, not the facade candidate. Audit verified the shared
source receipt, both installation inventories (41 distributions and six console
entries), 1,200 helper inputs before/after/current, and unchanged A/B wheel and
prior report hashes. Normal runner completion includes its original final
installation verification. No Product execution was added during this audit.

The original exact-decimal comparator was independently reproduced for every
case. Nine cases pass; only `plugin-help` is inconclusive. Its four groups are
shown in milliseconds below; displayed rounding is not used for decisions.

| Block / side | Median | MAD | MAD upper limit |
| --- | ---: | ---: | ---: |
| 0 / a | 684.937233 | 27.280958 | 68.493723 |
| 0 / b | 735.079371 | 73.710717 | 73.507937 |
| 1 / a | 652.240386 | 11.877317 | 65.224039 |
| 1 / b | 679.619586 | 14.970601 | 67.961959 |

The four-group median span is 82.838986 ms, above its 65.224039 ms limit by
17.614947 ms. Block 0 / b also exceeds its MAD limit by approximately 0.202780 ms.
Thus this is not merely a sub-millisecond MAD miss: the independent span gate
also fails. All 44 plugin-help outputs are identical. The previously unstable
`hosted-help` passes in this collection, but old plugin-help passes and new
hosted-help passes must not be combined into an accepted ten-case baseline.

Existing plugin-help rows were decomposed without another collection. Paired
b-minus-a median wall / total-CPU deltas, in milliseconds, are:

| Block | Execution order | Pairs | Wall delta | Total CPU delta |
| --- | --- | ---: | ---: | ---: |
| 0 | AB | 5 | +16.770 | +1.373 |
| 0 | BA | 5 | +99.201 | +35.286 |
| 1 | AB | 5 | +47.740 | +34.846 |
| 1 | BA | 5 | -37.275 | -9.811 |

Total CPU is user plus system CPU per observation before paired subtraction
and median calculation. These small descriptive groups do not establish a
consistent fixed-side penalty, a simple repeatable order effect or a root cause.
Static entry inspection identifies `loushang.plugin.__main__:main`; argparse
help exits before validation/conformance operations. The inspected entry and
supporting source show no direct Coding facade dependency; this is not a full
dynamic import trace, a waiver of the plugin guard, or authority to change Plugin
or Harness runtime code.

The post-collection resource receipt, recorded by 12:58:33 UTC in
`resource-resume-01.json`, has 1,029,620 KiB available memory, controller RSS
120,488 KiB and swapped memory 104,876 KiB. Memory PSI avg10 is zero; I/O
some/full avg10 is 0.95/0.78. The two vmstat interval swap-in/out readings are
0/0 and 168/0 KiB/s. Before/after snapshots do not reconstruct pressure during
the measurement window or establish that it was paging-free.

Architecture, evidence-contract and compatibility reviewers independently
completed the result review with no P1/P2. This approves evidence integrity and
the stated inconclusive conclusion, not stability or performance acceptance.
Keep the original inert, native warm and native absent reports separate and
unchanged. No automatic retry, selective recollection, threshold relaxation or
A/B follows this result. Further sampling needs a bounded reviewed diagnostic
or an actionable reviewed condition change; G18 acceptance remains open.

### Next-measurement decision — close diagnosis, require an actionable condition

Three-view follow-up review does not recommend another plugin importtime run:
there is no specific, falsifiable hypothesis whose result currently identifies
an authorized change to the frozen Coding facade pair. Finding unrelated
Plugin/Harness import costs would not authorize their optimization. A profile
pass, identical import sequence or another quiet idle snapshot would not itself
justify fresh formal sampling. No new Product/runtime finding was raised.

A final existing-data check covered all 400 formal observations in their twenty
original pair windows, retaining the forty warmups as two separate windows.
Each case's wall and total child CPU values were divided by that case's median
over all forty formal observations, for descriptive cross-case comparison only.
Plugin's two-side median normalized wall values range from 0.9375 to 1.1499;
the other nine cases' eighteen-observation medians range from 0.9777 to 1.0399.
The plugin-high block-0/pair-3 window is 1.1499 versus 0.9811 for the other cases;
block-1/pair-7 reverses that relationship (0.9800 versus 1.0399). These sequential,
coarse windows do not establish or exclude shared short-lived contention.
No observations were removed and no acceptance comparison was replaced.

The report records per-observation child CPU and post-observation load averages,
but not absolute sample timestamps, PSI, page faults or context switches.
Wall minus child CPU includes observer/scheduling and other time, not a pure
I/O-wait measure. Existing data therefore do not identify a further actionable
condition correction. Stop mining these reports and stop new sampling under
unchanged conditions; retain all inconclusive verdicts.

The next prerequisite is user-coordinated, sustainable measurement isolation:
a task-isolated Linux runner or an equivalent documented local resource change.
An external machine is a proposed route, not a proven root-cause fix or a new
acceptance requirement. No remote access, system tuning, process termination or
resource purchase is authorized by this handoff. Once a target is available:

- Carry the exact A/B commits, frozen wheel bytes/hashes, project/lock and hashed
  dependency export, plus the reviewed scripts/tests and their helper manifest.
  Keep the original CPython 3.11.15 build and compatible Linux dependency
  artifacts; any necessary interpreter/build/dependency change requires explicit
  registration and review as an additional environment change before timing.
- Recreate A, A2, observer-A and B installations on that target. Do not copy old
  virtualenvs. Reverify source/wheel, installed bytes, direct URLs, wrappers and
  RECORD, Python/dependency inventories and all six entries. Target-specific
  absolute paths and wrapper hashes require new receipts, not old identity claims.
- Reuse the unchanged startup/native collectors and provenance/comparison,
  slot/bytecode/recovery and retained-owner support. Prepare the native
  provisioner's `.artifacts/g18-design/uv-cache` offline before collection.
  Create new private HOME/TMP/XDG roots, caches and seed/slot receipts; build
  both native slot environments at their shared canonical execution prefix,
  retaining same-filesystem switching and independent observer ownership.
- Complete target-local installation, HOME-isolation and slot/recovery/owner
  controls before timing. Record CPU/affinity/quota, RAM/swap/PSI, kernel,
  interpreter, filesystem/scratch/cache locations and the practical isolation
  arrangement. Finish concurrent review/tests/builds before sampling. Resource
  snapshots remain descriptive, not replacements for original stability gates.
- Review the concrete target and execution plan before launching one full inert
  A/A. On acceptance and audit, schedule native warm and absent A/A separately;
  all original A/A conditions must be accepted before the full required A/B work.
  Preserve original case/metric counts, order, warmups, cache policies, argv,
  PTY, deadlines, cleanup and thresholds. Any failed collection/identity/owner
  check or inconclusive comparison stops automatic progression: preserve its
  evidence, do not fill gaps or retry until green. Never pool old/new reports.

This is a reviewed handoff, not an executed migration or an accepted baseline.
The facade implementation remains frozen and the full G18 goal remains open.

### User-confirmed exclusive-window resumption — reviewed execution plan

After the isolation handoff, the user explicitly confirmed that other workloads
can remain paused and this Linux machine can be reserved throughout the complete
measurement window. This is a user-coordinated concurrency condition, not a
claim of additional CPU/RAM, OS-enforced isolation or a proven noise root cause.
The new idle preflight shows one CPU, 1,676,332 KiB total RAM, 953,216 KiB
available RAM, zero memory/I/O PSI avg10 and 2,213,540 KiB available filesystem
space. Idle snapshots alone are not the basis for resumption; the explicit
exclusive-window commitment is. The controller and OS still consume resources.

Architecture, evidence-contract and compatibility pre-execution review passed
with no P1/P2. Execute exactly one unchanged complete inert A/A collection,
under a new exclusive output directory
`.artifacts/g18-linux-delivery/inert-aa-exclusive-03`. Reuse the frozen local A
and A2 installations, A source/wheel, original CPython/offline private parent
environment and `/var/tmp` scratch parent. Recheck source/wheel/helper inputs;
the collector must retain its before/after installed identity checks. No
relocation or installation rebuild is implied by this same-machine window.

Preserve all ten cases, two blocks and ten pairs per block: 400 formal samples,
40 explicit warmups and four identity probes outside timing. Keep original
alternating side order, reversed case order in block 1, warm external bytecode,
fresh process/app state, argv/output predicates, 60-second sample deadline,
75-second retained owner and physical cleanup, plus exact comparison thresholds.
No profiler, extra monitoring hook, cache deletion or Product edit is introduced.
Finish reviews and checks before launch; record one final resource snapshot and
one post-collection snapshot outside the sample window. During collection, only
observe the existing process handle and provide brief progress updates.

Any collection/identity/owner failure or inconclusive full comparison ends this
attempt with its original evidence retained. No retry, selective case replay,
old/new pooling or automatic A/B is authorized. An accepted and audited inert
result allows planning the separately required native warm and absent A/A under
the confirmed window; it does not accept those conditions or close G18.

### Exclusive-window result — complete inert A/A accepted

The reviewed attempt completed from 2026-09-10 14:22:31.769973 to
14:56:23.905064 UTC. Session 36031 is terminal with exit 0. Its immutable report
is `.artifacts/g18-linux-delivery/inert-aa-exclusive-03/report.json`, SHA-256
`fa824481dbb75df8bf5961a0dabf663d3b50909c4fd29bee37be0eb1228b9760`.
Task-owned scratch is `/var/tmp/loushang-g18-baseline-6e2uu17_`; private parent
state is `/var/tmp/lg18-tests-hMhGT5`. Neither was cleared or reused mid-run.

All 440 observations are complete and valid: 400 formal samples and 40 explicit
warmups. Audit reproduced every original identity and execution order, argv/cwd,
output predicate, status and finite nonnegative wall/CPU value. All exit codes
are zero, failure fields null and stderr empty. Four installation identity
probes remain outside these timings. Source/wheel receipts match the frozen A
pair, not candidate B; both sides have matching interpreter, 41 distributions
and six console entries. All 1,200 helper inputs and runner/provenance hashes
match before/after/current, and both frozen wheel hashes and earlier reports
remain unchanged. Normal completion follows the collector's final source,
installation and helper verification; the audit launched no further Product.

The original comparator and all summary values were independently reproduced
from this report alone. All ten cases and the overall A/A comparison pass.
Independent exact-Fraction checks also confirm all four-group median spans and
all group MADs satisfy the unchanged thresholds. In particular, plugin-help's
median span is 39.093243 ms against a 69.830960 ms upper limit; its smallest group
MAD margin is 27.673620 ms. These rounded values describe, not decide, the result.
The maximum measured sample is 10.531465 seconds; original 60-second sample and
75-second retained-owner deadlines were not changed.

Architecture, evidence-contract and compatibility result reviews passed with
no P1/P2. This accepts the complete inert A/A under the user-confirmed exclusive
window. Previous inconclusive reports remain intact and unaccepted; none of
their passing cases contribute to this result. The change in outcome does not
prove the cause of earlier variation, pressure-free operation or facade gains.

The post-collection snapshot at 14:56:49 UTC records 1,015,836 KiB available RAM,
memory PSI some/full avg10 0.07/0.07 and I/O PSI 1.41/1.14. Its two vmstat interval
swap-in/out readings are 0/0 and 4/0 KiB/s. The descriptive receipt is
`.artifacts/g18-linux-delivery/resource-exclusive-03.json`; these readings do
not reconstruct the full measurement interval.

Next is a separately reviewed native **warm A/A** plan: retain the exclusive
window, verify actual runner/scratch capacity before launch, use new output and
a fresh original fixed slot, the frozen A/A2 references and independent A
observer, and preserve all seed/recovery/cache/owner contracts. Keep seven cases,
two blocks and ten pairs: 280 formal observations plus 28 warmups, with all
41 metrics required. Setup and identity work stays outside those timings.
Native absent A/A and all inert/native A/B remain pending. No automatic retry or
A/B is authorized by this acceptance, and G18 is not complete.

### Native warm exclusive-window A/A — reviewed execution plan

Following accepted exclusive-03 inert A/A, continue the user-confirmed Linux
exclusive-window arrangement with one full native **warm A/A**, not candidate
A/B. Preflight on 2026-09-11 at 01:08 UTC still shows one CPU and 1,676,332 KiB
RAM, with 952,468 KiB available. Both one-second vmstat interval rows show no
swap-in/out; memory PSI some/full avg10 is 0.97/0.60 and I/O is 3.45/2.72.
These snapshots are descriptive, not a promise of pressure-free measurements.
Finish review/checks and record a final prelaunch snapshot before timing.

Architecture, evidence-contract and compatibility pre-execution review passed
with no P1/P2, conditional on the final capacity check below. The plan preserves
the unchanged native collector and original fixed-slot warm/cache/recovery/
observer contracts:

- New exclusive output:
  `.artifacts/g18-linux-delivery/native-aa-warm-exclusive-02`.
  Use `measure_g18_native.py --fixed-slot --cache-mode warm`, original A/A2
  reference installations, independent `observer-a`, the same frozen A wheel
  and A source on both sides, original offline CPython/private parent environment
  and `/var/tmp` scratch parent. Use the original hashed dependency export at
  `.artifacts/g18-baseline/requirements.txt` (SHA-256 recorded above).
- Provision a fresh slot under `.artifacts/g18-slots` at the collector's one
  canonical active prefix; neither copy nor resume an earlier slot. Preserve
  same-filesystem switching, all pre/post installation and wheel/helper pins,
  immutable per-scope recovery seeds, resets and independent observer ownership.
  Do not rebuild the frozen reference installations or modify Product code.
- Collect all original seven cases, two blocks and ten pairs per block: 280
  formal observations and 28 declared warmups. Preserve original side alternation
  and reverse case order in block 1. Setup, seed preparation, cache preparation
  and identity verification are separate from the 308 timed observations.
  Retain every raw observer/cache/seed/slot receipt and all 41 original metrics.
- Keep original cache policy, argv, PTY/witness, deadlines, physical settlement
  and exact comparator thresholds. No profiler, new sampling hook or unrelated
  test/build/review runs alongside collection. Only observe the existing process
  handle; do not restart after an observation timeout.
- Retain all evidence and stop if collection, identity, cache, seed or owner
  validation fails, or the complete 41-metric comparison is inconclusive. No
  automatic retry, case selection, outlier removal, old/new pooling or A/B.
  A passing warm result must be audited before separately planning absent A/A;
  it cannot accept absent-cache behavior or any candidate performance benefit.

Before launching, compare available space against the retained previous warm
output, fixed slot and scratch footprint, including cache evidence. The initial
filesystem reading is 2,108,660 KiB available; previous warm output alone uses
887,276 KiB. Its slot and main scratch use 210,048 and 96,476 KiB, and the two
recovery subjects/controls add 7,344 KiB: 1,201,144 KiB total, leaving an estimated
907,516 KiB before transient overhead and new-path metadata growth. Account for
atomic report replacement, seed restore copies and offline installation staging,
not only the terminal footprint. Preserve old evidence and recheck actual usable
runner/scratch capacity; do not delete old reports or change measurement behavior
to save space. This estimate is not a storage upper bound or an acceptance gate.

The outside-sandbox capacity check at 01:11:52 UTC records 2,101,424 KiB free,
12,956,916 free inodes, a writable ext4 filesystem and no shell file-size limit.
The prior report is 4,664,467 bytes and both seed directories together occupy
1,212 KiB; temporary duplicates of these are small relative to the approximately
879 MiB margin over the complete prior footprint. A full reference installation
occupies approximately 183 MiB, leaving additional room for installation staging
and pathname-related evidence growth. This supports one bounded warm collection,
not a promise that subsequent absent/A/B runs also fit. The known sandbox
`/tmp/.agents` mount failures occurred before those read commands executed and
are not Product failures; actual collection uses the verified outside-sandbox
runner with private `/var/tmp` state. Frozen wheels, requirements, all 1,200
helpers and collector/probe/support hashes match their prior receipts.

The user subsequently requested resumable collection. This native attempt was
stopped through the original SIGINT/owner path (session 61168 exit 130), retaining
24 valid observations and one interrupted attempt; it is not accepted or resumed.
See the [checkpoint protocol](startup-performance-g18-checkpoints.md) for the new
opt-in native tooling, legacy evidence hash and separate statistical qualification.

### Checkpoint-enabled warm A/A continuation — pre-execution plan

Status: three-view pre-execution review passed with no P1/P2; capacity clearance
is required before launch. Architecture/lifecycle, evidence-contract and
compatibility/resource reviewers independently confirmed the unchanged full
acceptance scope and the prohibition on launching at current free capacity.
The preceding goal turn made concrete progress: checkpoint tooling was committed
as `d7545673`, the complete scoped collector regression passed 466 tests with four
platform skips, and the installed warm smoke safely resumed from 3 to 8 valid
observations without replacing its prefix, seeds or slot identities. These are
functional receipts, not native stability or candidate performance acceptance.

The next performance attempt retains the reviewed exclusive-window warm A/A
plan above, with only the new opt-in collector protocol and a fresh output:
`.artifacts/g18-linux-delivery/native-aa-warm-checkpoint-03`. Use the unchanged
frozen A/A2 and observer installations, A wheel/source pair, requirements, private
parent environment, `/var/tmp` scratch, fresh fixed slot, all seven cases, two
blocks and ten pairs per block (308 observations, 41 metrics). Freeze current
helper bytes before launch. Do not reuse either interrupted v2 slot or either
checkpoint smoke slot. No Product, dispatch, lifecycle, timeout, cache-policy,
sample-order or comparison-limit changes are authorized by this continuation.

Add `--checkpoint`, but **no planned pause and no `--pause-after`**. The intended
calibration remains one uninterrupted segment; enabling safe pause support does
not itself add setup, warmups or a state reopen between observations. Ordinary
safe-pause requests remain available. If a pause is actually needed, retain its
generation and records, but do not automatically resume it for formal acceptance:
declare and review a matching segmented A/A and A/B schedule first. Every resumed
report's automatic-acceptance flag remains false. An uninterrupted result still
requires the original full stability gates and independent evidence review.
Any failure or inconclusive full comparison ends the attempt; no retry-until-green,
case selection, sample pooling or automatic progression to A/B is permitted.

Capacity preflight after checkpoint delivery found 1,518,804 KiB available on
the shared ext4 filesystem (1.45 GiB). The previous complete warm output, slot,
scratch and recovery controls occupy 1,201,144 KiB (1.15 GiB), leaving only
317,660 KiB before installation staging, atomic report/checkpoint replacement,
pathname growth and other machine writes. The real paused smoke checkpoint alone
is 16,414,487 bytes; the previous reference install is approximately 183 MiB.
These are observed sizes, not certified upper bounds. The previous launch had
about 879 MiB headroom over retained terminal data; this continuation does not
silently adopt a substantially tighter operating margin.

Do not launch until actual free capacity is restored to at least 2.1 GiB for
this one warm attempt, followed by an updated outside-sandbox capacity and
resource receipt. Subsequent absent/A/B campaigns each require their own capacity
clearance; roughly 6 GiB free is a planning allowance for the remaining campaign,
not a proven storage bound or a replacement for per-attempt checks. Do not delete,
rewrite, relocate or compress old measurement evidence/installation/slot state
to meet this condition without a separately authorized retention plan. Disposable
actionlint compiler caches observed here are only about 75 MiB and cannot by
themselves restore the required headroom. Additional capacity or approved cleanup
outside retained G18 evidence requires user coordination.

The final read-only path check found the checkout and `/var/tmp` on the same
filesystem with 1,517,760 KiB free; `/tmp` is a separate tmpfs with only
167,648 KiB free. Changing to one of these existing scratch paths cannot supply
the missing capacity. No new performance process was launched and no historical
data was removed.

Current read-only process inspection found no live G18 collector or task-owned
new gate/compiler workload. Two historical blocked Harness gate process trees
remain outside this continuation's cleanup scope. Resource readings still show
some paging and I/O pressure; they are descriptive, not proof of a pressure-free
exclusive window. Complete review/checks before timing, retain the original
user-coordinated exclusive-window condition, and do not run new tests/builds or
reviews alongside the eventual collector. Until capacity is cleared, do not
start a new performance attempt or claim a verified wait on one.

### Checkpoint warm A/A attempt — seed preparation failed

The user released capacity and requested continuation. At 2026-09-11 02:58 UTC,
the launch receipt recorded 9,139,265,536 bytes available (8.51 GiB), satisfying
the reviewed capacity condition. Known directory scans had exited; the old
Harness pytest processes were no longer present. Frozen A wheel/requirements and
the reviewed scripts/tests were unchanged. Resource snapshots still showed CPU,
paging and I/O pressure; neither free disk nor scan exit proves a noise-free
window. Preflight evidence is retained separately in
`.artifacts/g18-linux-delivery/resource-native-warm-checkpoint-03-launch.json`.

The single full-plan invocation, session **20062**, terminated with **exit 1**.
Report: `.artifacts/g18-linux-delivery/native-aa-warm-checkpoint-03/report.json`,
SHA-256 `ead6cb5f47aa8e6dd6e43506b636abfcc77a18845c8e4cc8c04f27389181bdf6`.
It failed in the first `prepare:recovery-cwd` seed creator: the original 35-second
ready predicate timed out with no PTY output, before any warmup or formal
observation. `samples` is empty; comparison remains `not-evaluated`; report and
checkpoint are `failed`. Slot `g18-slot-estjpxu2` is idle but poisoned. There is
no paused generation to resume; do not clear its failed flag or reuse this slot.
Parent `/var/tmp/lg18-tests-DcbnwX`, scratch
`/var/tmp/loushang-g18-native-9cgdkxm3` and recovery state are retained.

Raw preparation receipt: `/var/tmp/g18-recovery-toasum3t/control/prepare-0.json`,
SHA-256 `b96266422c4d90fff34ad97f9df1f5ada5bc9a29372eddc8907a99ee18f65e9a`.
Its failure-only snapshot records main-thread runtime 10.522051245 seconds,
runqueue wait 12.637826324 seconds, `ep_poll` at capture, two process threads,
and host CPU PSI `some avg10=94.38`. These cumulative/non-atomic readings do not
identify a deadlock or establish the timeout's cause. The original controller
completed its failure cleanup before raising; post-exit inspection found target
PID 3091690 and the task-specific process paths absent. This is physical failure
cleanup, not normal Product settlement or proof that no descendant needed cleanup.

Three independent read-only audits found no evidence-classification P1/P2.
Full versus successful short warm smoke uses identical source/installation/helper
inputs and first seed-preparation path. Short-plan `foreground` observations
occur after seed preparation, not as an extra warmup; the full plan's second
recovery scope had not executed. Pause/seal/reopen had not been reached. Thus the
failure is not specific to full-plan case order or demonstrated to be a checkpoint
regression. The retained failed subject contains only an application lock file,
not session/journal records; this is a limited filesystem observation, not proof
of exactly where the process stopped.

Stop automatic full collection/resume/A/B. The next bounded diagnostic should
target first seed-creator startup before its first frame, including the owned
Hosted descendant rather than assuming the TUI's event-loop wait is the cause.
Any new execution/instrumentation requires a separate reviewed diagnostic plan:
new state, original argv/PTY/35-second ready and retained-owner deadlines,
failure-only bounded evidence before cleanup, no Product edits, debugger attach,
threshold changes or acceptance claims. At that point no diagnostic rerun had
been performed.
The separately reviewed [single-seed diagnostic](startup-performance-g18-seed-diagnostic.md)
defines that next execution and its explicit non-acceptance boundary.
That one invocation subsequently exited 0: the original two seed CLI workflows
settled, final pins passed, and no failure snapshot was triggered. It retained
zero formal observations and did not evaluate a comparator. This is a
non-reproduction result, not a root-cause finding or accepted native stability;
the diagnostic document binds its reports and next-decision boundary.

### Post-cleanup exclusive warm A/A — reviewed execution decision

Status: three-view pre-execution review passed with no P1/P2; final preflight is
required before one full attempt only. The user requested
continuation of the complete Linux acceptance plan after the bounded diagnosis.
The basis for a new attempt is an explicit restored measurement window, not the
single-seed success: the previously observed active peer `loushang` PID 3081809
is now absent, as are the historical pytest jobs and directory scans. No new
collector/test/compiler workload was found. This task will run no reviews,
tests, builds or diagnostic samplers alongside formal collection. Continue the
user-coordinated exclusive-window arrangement; other services and the controller
still exist, so this is not OS-enforced isolation or a causal explanation of the
old timeout.

Current free space is 8,756,980 KiB (8.35 GiB), above the reviewed 2.1 GiB
per-attempt capacity requirement. The two vmstat interval rows show 76%/87%
idle, 12/8 KiB swap-in and no swap-out, unlike the busy launch snapshot of the
failed checkpoint-03. These are descriptive observations, not newly invented
performance gates or a guarantee of stability. Record another final capacity,
process and resource snapshot after all reviews/checks finish and before launch;
do not poll until a preferred snapshot appears or launch if competing work has
resumed. Capture a post-collection snapshot outside the measurement window.

Use fresh output `.artifacts/g18-linux-delivery/native-aa-warm-exclusive-04`,
new private parent environment, `/var/tmp` scratch and newly provisioned slot.
Retain the same frozen A source/wheel on both sides, A/A2 reference installations,
fixed independent observer and hashed requirements. Tools remain the reviewed
`eaa082a4` implementation (only documentation changed afterward). Run original
`--fixed-slot --cache-mode warm --checkpoint`, all seven cases, two blocks and
ten pairs per block: 308 observations, including 28 warmups, and all 41 metrics.
Keep original seeds/resets/cache semantics, side alternation and reversed second
block, PTY predicates, deadlines, ownership and pre/post provenance checks.

Do not pass `--seed-preparation-diagnostic`, `--resume` or `--pause-after`. The
new failure-tree instrumentation remains off in formal mode. No historical
failed/diagnostic state is resumed, copied, relabeled, or mixed into the report.
If a controlled pause is actually requested, preserve the safe checkpoint but
do not automatically resume for acceptance; the separate segmented-calibration
restriction still applies. The intended full attempt is uninterrupted.

Failure or a complete `inconclusive` comparison ends this attempt and preserves
all evidence. No repeated seed probe, full retry, selective replay, threshold
change or automatic A/B is authorized. A complete pass still requires independent
three-view evidence audit before acceptance. Only afterward may absent A/A be
separately planned; all original A/A conditions must be accepted before required
inert/native A/B. The full goal, no-push/no-merge boundary and pending native/A/B
checklist are unchanged.

## Bounded Order/Import Diagnosis — Pre-Execution Review

Independent raw-data review reproduced all ten comparator results and verified
440 unique complete sample identities, common source/install contracts and
unchanged helpers. Hosted-help shows order interaction: ten A-then-B pairs have
median(B-A) wall/CPU differences of +0.039485/+0.058560 seconds (B slower 5/10),
whereas ten B-then-A pairs have +0.523255/+0.210492 seconds (B slower 10/10).
Import-coding and hosted-tui-help controls do not show the same split. These are
associations, not a causal conclusion or new performance acceptance.

Three-view design and implementation review accepted a single artifact-only
diagnostic, `.artifacts/g18-linux-delivery/profile_hosted_help.py`, with no P1/P2:

- Baseline `install-a` and `install-a2` only, no facade candidate; hosted-help and
  hosted-tui-help only. Each case has two declared warmups and eight profile targets,
  in blocks ABBA/BAAB. Total: 20 profile targets, plus four before/after installation
  verification targets; supervision processes are not included in that count.
- Real console wrappers, original retained `capture` owner, 60-second timeout,
  output cap, exit/failure/settlement checks and private environment. Only the
  target gets effective `PYTHONPROFILEIMPORTTIME=1`; isolated observers ignore it.
- New diagnostic bytecode roots per installation, fresh per-sample app state and
  `/var/tmp` scratch; old A/A caches/reports are untouched. Preserve raw stdout,
  stderr, wall/CPU and before/after load, and source/install/helper/script hashes.
- Strict nonempty profile header plus numeric rows; any other stderr is rejected.
  Only a copy passed to original help validation has stderr cleared. Write running
  identity before launch, retain failures, stop immediately, no automatic retries.
- Diagnostic reports always remain ineligible for acceptance. Do not combine
  cumulative import times, subtract profiling overhead or mix these samples with
  formal timings. This standalone two-case order is not a complete replay of the
  original ten-case context, so it cannot confirm or exclude prior-case effects.

Six mock-only deterministic controls passed before real profiling; they launch no
Product processes. Ruff initially reported E402/B023 in the artifact helper/tests;
explicit file-based loading and bound test closure corrected them. The final
review also requested `load_before` alongside `load_after`; both are recorded.
The real diagnostic runs only after HOME and mock controls are terminal, with no
concurrent tests/builds/native workload from this task. No formal rerun is approved
merely because this small diagnostic looks stable.

### Bounded Profile Result

Exec 71760 completed with exit 0 after the six final deterministic controls passed
(0.018 seconds), then all 20 profile targets and four verification targets completed.
Private parent root: `/var/tmp/lg18-tests-bzyatd`; retained profile scratch:
`/var/tmp/lg18-profile-ydkqjeex`. The profile ran 03:00:07–03:02:18 UTC on 2026-09-10.

| Diagnostic artifact | SHA256 |
| --- | --- |
| `profile_hosted_help.py` | `278339eca20e4959133a6d4660ea982a8d8c970e040ddc960624ea91b204ba9a` |
| `test_profile_hosted_help.py` | `b6f3419ba15a9ea2f631046510b35e4aa872044d202c113bc4e405056fef2638` |
| `profile-hosted-order-01/report.json` | `c2745b725e34f5504f5d8d3f48ed4562f24a0f9c9b0a84a949f8b27300701e81` |

All are under the new delivery artifact prefix. Both installation receipts and
helper inventories match before/after; the runner hash matches the recorded file.
Every hosted-help target records 1,075 import rows and every hosted-tui-help target
1,036 rows. The result is `complete-profile-only`, ineligible for acceptance.
Independent result review also found each case's complete ordered `(module, indent)`
sequence identical across its eight formal profiles; no differing import branch
or module order was observed. The original A/A report SHA is still unchanged.

For hosted-help, the four profiled pairs in declared order show wall(B-A)
differences of -0.686142, +0.207743, +0.776399 and +0.376777 seconds; CPU differences
are -0.098184, +0.232983, +0.668088 and +0.375177 seconds. The control also shows
positive wall(B-A) in all four pairs. Thus this small standalone profiled sequence
does not establish the cause of the original case-specific order association.
The largest positive per-module median self-time differences for hosted-help are
about 9.2 ms in component_runtime and protocol.model; no single large self-time
hotspot accounts for the aggregate CPU difference. Import self time is not itself
CPU accounting, and nested cumulative times are not summed.

Root cause remains unresolved. Do not turn this result into an accepted baseline,
change thresholds or automatically repeat full inert A/A. Continue the separately
required fixed-slot recovery correctness work (now completed above); native A/A can be calibrated
under its original conditions without claiming to resolve the inert-path issue.

Formal runs retain two blocks of ten pairs, all original cases and warmups,
existing runtime deadlines and failure policy. Native runs use a fresh fixed slot
and explicit `/var/tmp` scratch parent; slot/cache/evidence locations retain the
accepted independent layout. Before collection, local capacity was checked:
4.6 GiB disk free; `/tmp` had 164 MiB globally free but recurring sandbox quota
failures, so it is not the native scratch parent.

No tests/builds run concurrently with a measurement window. Preserve every
failed, invalid or inconclusive report; a new run requires an evidenced reason,
not retry-until-green. `exit 0` and `complete-record-only` are not comparison
acceptance. The two-cache full native requirement cannot be replaced by help-only
speedups or source-mode tests. Existing thresholds, including the help target,
are unchanged; shortcomings remain open rather than redefining the goal.

## Three-View Submission And Freeze Pre-Review — 2026-09-10

- Architecture/ownership: 48 exports keep their owners and the single alias;
  the exact facade/core budget partition is the approved one. No new owner,
  background thread, public protocol or dispatch behavior. No P1/P2.
- Measurement/contract: existing immutable-commit verifier supports the new A/B;
  no collector edit is needed. Same-wheel A/A, new A observer, explicit source
  SHAs, independent installation validation and complete report audit are required.
  No P1/P2; record-only collection must not be mistaken for acceptance.
- Compatibility/lifecycle: explicit typing, cold imports, bootstrap identity,
  success-only caching and retained cleanup handles preserve existing boundaries.
  Source tests inject `src`, so they cannot stand in for installed-origin and
  ready/first-use/settlement evidence. No P1/P2.

All three reviews were independent and read-only, with no tests or builds run by
reviewers. They authorize the pending-performance source/freeze step, not final
performance acceptance. A stale plan paragraph about broad source gates is also
corrected when linking this delivery record.
