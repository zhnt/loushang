# G18 Linux Facade Local Delivery

## Status And Scope

Status: in progress; source candidate and paired installations frozen, performance acceptance pending.
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
- [ ] Fixed-slot recovery correctness controls pass.
- [ ] Inert ten-case A/A stability accepted under the existing policy.
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
required fixed-slot recovery correctness work; native A/A can then be calibrated
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
