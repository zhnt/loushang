# Hosted Product Runtime G9 Promotion Record

[Architecture](../README.md) ·
[AppHost](README.md) ·
[G9 V1 Closure](hosted-product-v1-closure-g9.md) ·
[G9.3 Current Owner Decision](current-worker-owner-decision-g9.md)

## Status

- ID: `HOSTED-PRODUCT-G9-PROMOTION`
- Scope: `loushang / AppHost / Product / Harness Worker / Hosting`
- Parent: `HOSTED-PRODUCT-G9`
- Authority: descriptive — completed immutable promotion evidence
- Design status: not-applicable
- Implementation status: implemented — promotion complete
- Promotion status: merged to `main`
- Activation status: default-dark; omitted Worker owner remains Current
- Effect: capability availability only
- Owner: Loushang architecture release control

## Promotion Identity

- Promotion PR: [#556](https://github.com/zhnt/loushang/pull/556)
- Immutable `lane/harness` head:
  `07ad9a9984295449d9fc0db45c4a76d3e8bf8c34`
- `main` merge commit: `445c0fb567163ed92b1163456133ff7545362de9`
- G9.3 decision: `RETAIN`
- Merge time: `2026-09-06T14:44:08Z`

GitHub recorded every promotion workflow below with the same
`head_sha=07ad9a9984295449d9fc0db45c4a76d3e8bf8c34`, event `pull_request`, run
attempt 1, terminal status `completed`, and conclusion `success`. The merge
commit has that immutable lane head as its promoted parent; no later rerun or
different source commit substitutes for the evidence.

## Exact-Head Gate Evidence

| Required scope | Workflow/run | Result | Retained proof |
| --- | --- | --- | --- |
| architecture | `Architecture Quality` / `34039700017` | `success` | status, link, dependency, and generated-fact guards |
| install and AI surface | `AI Quality` / `34039700020` | `success` | Ubuntu/macOS install matrix and AI quality |
| Harness and Linux Product | `Harness Quality` / `34039700046` | `success` | Linux harness plus zero-skip PLC9C5 C5.4 report and manifest verification |
| AppHost Linux/Windows | `AppHost Quality` / `34039700011` | `success` | AppHost contract gates plus separate zero-skip G8/G9 Linux and Windows reports |
| Hosting Linux/macOS/Windows | `Hosting Quality` / `34039700010` | `success` | H0--H6 mechanics plus zero-skip Windows C5.5b/c reports and manifest verification |
| host runtime | `Host Runtime Quality` / `34039700038` | `success` | host runtime contracts |
| Harnesstui | `Harnesstui Quality` / `34039700021` | `success` | shared Product-neutral presentation contracts |
| TUI platforms | `TUI Cross-platform Contracts` / `34039700009` | `success` | POSIX/Windows terminal and deterministic render contracts |
| Windows shell | `Windows Shell Compatibility` / `34039700014` | `success` | Windows command and shell compatibility |

The canonical retained case identities remain in the
[G8 evidence manifest](hosted-product-g8-evidence-manifest.json),
[G9 evidence manifest](hosted-product-g9-evidence-manifest.json), and
[PLC9C5 evidence manifest](../harness/plugin/plugin-lifecycle-plc9c5-evidence-manifest.json).
Workflow artifacts are retained by their owning runs rather than copied into
the repository.

## Reconciled Result

Hosted Product Runtime V1 through G9 is available on `main`. Availability has
not changed activation authority:

- no installed Coding CLI, TUI, SDK, AppServer, hosted, or mux entrypoint
  selects the G9 composition;
- omission remains Current and cannot be changed by imports, environment,
  platform detection, cwd/home, Session data, or backend availability;
- a selected Hosting attempt still cannot fall back to Current in that attempt;
- Current remains present under the accepted G9.3 `RETAIN` decision; and
- activation, omitted-owner change, Current deletion, AppServer/AppService
  runtime, launcher, and mux implementation require later independent changes.

## Supersession Rule

This completed record is immutable historical evidence. Later activation or
deletion decisions add their own records and evidence; they do not rewrite the
G9 promotion identity or reinterpret availability as prior activation.
