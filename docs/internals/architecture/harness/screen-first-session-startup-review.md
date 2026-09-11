# Screen-first startup design review

Date: 2026-09-11. Tracking: G18 #578.
Design: [screen-first session startup](screen-first-session-startup-plan.md).

Three independent read-only reviewers examined the design and relevant source.
No implementation changes were made before their design approval.

| View | Initial findings | Resolution | Re-review |
| --- | --- | --- | --- |
| Architecture / ownership | CLI has no universal runtime cleanup; context managers in another task do not transfer ContextVars | Product unique runtime owner; explicit captured execution context for router and all callbacks | Approve |
| Interaction / compatibility | Capture adapters can lose TTY routing; closing output/resume hints could corrupt screen or disappear | Preserve TTY metadata; capture until terminal restoration and drain once to original channels | Approve |
| Lifecycle / failure / tests | Missing acquisition-to-cleanup guarantee; mutual waiting and cleanup cancellation risks | Ordered close fence/router/continuation/join/terminal handshake; shield settlement and test races | Approve |

Pre-change focused offline baseline: 31 passed (18.98 s), including shared
screen runner/application host, Coding screen mode and terminal contract.
Executed outside the managed sandbox per workspace instructions.

Approval is for the design, not a claim that implementation or platform
acceptance has passed. Bare resume picker, hosted/mux, noninteractive routing
and removal of pre-application import costs remain explicitly outside v1.

## Implementation re-review

All three original reviewers independently inspected the implementation.

| View | Findings addressed | Final result |
| --- | --- | --- |
| Architecture | Keep runtime ownership in Coding; retain callback ContextVars; install labels after completion preparation await | Approve |
| Interaction | Keep loading alt-enter newline; restore loading prompt on blocked submit; show concrete failures from both stdout/stderr, including non-verbose launch-shell errors | Approve |
| Lifecycle | Treat disposer self-cancellation as failure; preserve initial plus cleanup leaf diagnostics instead of opaque exception-group counts | Approve |

Implementation adds an optional neutral screen lifecycle hook, one late-bound
router/handler handshake, and a Product startup owner with bounded output
capture. No Harness-to-UI dependency, new IPC or plugin-policy bypass is added.

## Local verification

- Broader offline regression: **1055 passed, 3 deselected**, with six failures
  caused by `/tmp` quota exhaustion (file writes/clipboard lease allocation).
  Only this turn's completed, regenerable 51 MB mypy cache was removed; existing
  G18 evidence and other tasks' temporary directories were not deleted.
- The six affected tests passed when rerun with a new task-local basetemp on
  the main filesystem. That supplemental batch also covered startup ownership,
  input/context/cancellation regressions, observer readiness and native terminal
  checks: **44 passed, 1 Windows-only skipped**. Its one remaining test assertion
  confused rendered diagnostic summaries with raw post-restore output; the
  assertion was corrected to inspect the restored terminal tail and rerun:
  **1 passed**.
- Linux real terminal tests verify the executable reaches session readiness,
  accepts `/quit`, exits successfully and restores terminal modes. The historical
  welcome-only predicates were corrected for screen-first semantics, including
  the G18 observer and retained embedded evidence helper.
- Focused mypy passes for the seven new/changed startup/UI modules. An additional
  exploratory check including the entire legacy `coding/cli/application.py`
  reports errors in existing runtime/work binding regions; it is not represented
  as a passing whole-CLI type gate.
- Changed-file Ruff, `git diff --check`, generated package dependency freshness
  and lightweight architecture documentation invariants pass.

`make plan-checks` was inspected; because this task branch includes earlier G18
deliveries, the default origin/main comparison also selects unrelated historical
scopes. The plan was additionally computed against HEAD to isolate this turn.
No claim is made that the full `check-changed` / AppHost / remote / cross-platform
release gates ran. No commit, push or merge is included in this delivery.

Performance acceptance here is structural and functional: first render precedes
runtime acquisition, suspended initialization remains editable, and one composer
survives attachment. The pre-application import chain and synchronous bootstrap
segments can still delay first frame/input; matched real-startup latency sampling
and external macOS/Windows runs remain follow-up work.
