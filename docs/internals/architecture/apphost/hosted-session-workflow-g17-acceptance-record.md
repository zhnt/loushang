# G17 Hosted Session Workflow Acceptance Record

[AppHost](README.md) · [G17 design](hosted-session-workflow-g17.md) ·
[Inventory](hosted-session-workflow-g17-inventory.json)

## Status

- Authority: descriptive — immutable implementation acceptance evidence
- Implementation status: implemented; all G17.1--G17.4 requirements accepted
- Activation status: explicit opt-in; Embedded and legacy G14/G16 retained
- Task integration: [PR #575](https://github.com/zhnt/loushang/pull/575), merged
  as `f5af4af782ca175365d18abee63af7b82546a6be`
- Mainline promotion: [PR #577](https://github.com/zhnt/loushang/pull/577)
- Local refresh and complete-goal closure: [#572](https://github.com/zhnt/loushang/issues/572)

Acceptance is a code-and-evidence fact, not a claim that an arbitrary checkout
is on main. The linked promotion PR is authoritative for main's merge state;
the tracking issue records local refresh only after it is actually verified.
Before promotion, this record describes the accepted lane candidate.

## Exact-Head Evidence

Accepted implementation head: `1cd08a57600a6ca8ed8a24b24528cfdfb9aa106c`,
integrating main `7c41cd57dd96f9da2964ef6146fc474ff96f674e`.
[Unified run 34247900896](https://github.com/zhnt/loushang/actions/runs/34247900896)
ended successfully with all 66 final job results successful. No source changed
between attempts. Attempt 1's only root failure was Harnesstui report upload:
871 tests, Ruff, mypy and exact zero-skip report verification had passed before
the artifact service returned HTTP 403 during finalization. Failed-job-only
attempt 2 reran that job and its dependent summaries; the upload succeeded.
The failed first attempt remains failed evidence, not retroactively successful.

| Native evidence | Exact required result | Job ID |
| --- | --- | --- |
| Linux isolated wheel | 8 families, zero skips/failures/errors | `102134682471` |
| Darwin isolated wheel | 8 families, zero skips/failures/errors | `102134683052` |
| Windows isolated wheel | 8 families, zero skips/failures/errors | `102134682616` |
| Darwin retained CLI workflows | 4 cases, zero skips/failures/errors | `102134682976` |
| Darwin public-API primitives | 6 cases, zero skips/failures/errors | `102134682489` |
| Windows native supplement | 5 cases, zero skips/failures/errors | `102134682425` |

The wheel runner verified import origins, wheel digest and installed bytes on
each platform before exercising every family in the unchanged
[G17 manifest](hosted-session-workflow-g17-evidence-manifest.json). Required
case identities and PTY/ConPTY/platform/installation properties were checked;
editable imports, platform skips and G16-only evidence cannot satisfy G17.
All six G16 native/wheel jobs and all three AppService quality jobs passed.
Coding's offline package suite reported 2399 passed, 21 skips
and 20 deselections; Windows AppService reported 1023 passed and 76 platform
skips. These broad-suite selections do not weaken dedicated zero-skip gates.

## Requirement Closure

| Requirement | Accepted proof |
| --- | --- |
| G17-DISCOVERY / AUTHORITY | Typed bounded discovery; Product scope rejection before IO, canonical-header reads and no adoption; cursor/client/generation and outstanding-worker controls in AppService/AppServer/Coding quality gates |
| G17-COMPAT / REGRESSION | Exact legacy profiles, unchanged Embedded startup/import boundaries, installed LEGACY family and all G16 native/wheel gates |
| G17-PICKER | Shared borrowed-client picker, cwd/home paging and selection; editor/race/error playback plus real installed CWD/HOME recovery |
| G17-FOREGROUND / LIFETIMES | AppHost launch debt, startup/recovery cancellation and force/reap controls; ENTRY, LOCAL, START-CANCEL and FORCED-EXIT installed families plus native supplements |
| G17-INSTALLED | All eight required families independently executed from a verified isolated wheel on each of Linux, Darwin and Windows, including real Product interaction |

Design and implementation received independent architecture/authority,
lifecycle/concurrency and contract/user-evidence reviews. The incremental
design retains the findings and regression-first corrections. The final CI
integration re-review approved complete seven-job AppService routing,
summary dependencies and failure/cancellation/unexpected-skip rejection.
Local final integration controls passed 51 tests; the preceding affected
launcher/observer/witness/registry/runner/architecture selection passed 232.

## Promotion Rule

PR #577 must pass its own exact-head checks before merge. These implementation
results are not substituted for that promotion run. The promotion delta after
PR #575 is delivery documentation and inventory/test status reconciliation,
not a change to Product behavior or evidence requirements. Local main and the
long-lived harness lane are refreshed only after the actual merge, preserving
unrelated control-lane edits and the separate startup-performance draft.
