# Change-aware quality gates

The repository uses one Actions entrypoint, [quality.yml](../../../.github/workflows/quality.yml).
It selects checks once, calls the affected reusable workflows, and verifies
their results through `quality-gate`. Local development uses the same
[selection rules](../../../scripts/ci/check-scopes.json).

## Refactoring proposal

The proposed [重构与优化测试与 PR 门禁](test-and-pr-gate-refactoring-plan.md)
consolidates test classification, minimal capability coverage, duplicate removal,
and replacement of historical phase jobs with module/capability gates. Its
[three-view review](test-and-pr-gate-refactoring-review.md) records findings and
revisions. Its [complete current gate inventory](test-and-pr-gate-inventory.md)
accounts for all workflows and source job definitions. Implementation is in
progress; the current selection rules and pause policy below remain in effect
except for the reviewed test roles described below.

## Temporary long-running gate pause

The following entire reusable workflows are paused by user request while their
necessary scenarios and execution costs are reviewed:

| Workflow | Observed long task |
| --- | --- |
| Windows Shell Compatibility | Session recovery/direct 30–34 minutes; normal GC 27 minutes |
| Hosting Quality | Sustained Worker query 24 minutes |
| AppService Quality | Windows AppService 20 minutes |
| Host Runtime Quality | Runtime group 15 minutes |
| Registered Worker Reboot Drill | QEMU recovery 13 minutes |
| Harness Quality | Linux native/contract composite 11 minutes |

This applies to PRs, main pushes, scheduled and manual full validation. The
root `quality-gate` expects these workflows to skip and continues enforcing all
other selected workflows. Complete affected Harness, Hosting, AppService and
AppServer offline module regressions run through the module workflow instead;
Harness retains its four deterministic shards. Three-platform core persistence
and selected terminal cancellation smoke remain enabled. Windows tests in
other selected workflows remain enabled.

Original native test cases and inventories are retained. `PAUSED_WORKFLOWS` and
`PAUSED_MODULES` in `scripts/ci/select_checks.py` record the pause and offline
coverage replacement. Remove a workflow from both mappings when restoring its
reviewed gate. Runs already in progress keep their original selection plans.

Restore scenarios individually: ordinary module regression; one or two portable
core smoke flows; affected-platform native smoke; path-selected crash/GC/recovery;
and separately scheduled sustained/reboot campaigns. Record each scenario's
unique assertion, owner paths, runtime and duplicate coverage before restoring
it. Long campaigns must not silently return to ordinary PR gates.

## Selection policy

The reviewed [test classification catalog](../../../scripts/ci/test-classification.json)
currently covers the complete Agent, Channel, Resource, Work, HarnessWork, Method,
Foundation and Ontology test directories,
including Agent's owned examples contracts. Changes
limited to these unit/contract files run the owner's complete reviewed set and
Ruff without selecting global integration/E2E. Mixed source changes and shared
fixtures retain their normal impact union. Missing or stale file classifications
fail validation; owned extras must also be classified and run exactly once.
Unreviewed modules retain their existing coverage.

HarnessWork's two registered golden fixtures have one reviewed contract consumer.
Changes limited to these fixtures run the owner's complete module set without
global E2E. Fixture metadata requires an existing owner-local path and a unique,
nonempty list of reviewed consumers. Shared conftest, unknown fixture paths and
mixed source edits retain their broader impact selection. Consumer declarations
must be reviewed when fixture usage changes; this is an explicit ownership
inventory rather than a complete automatic Python dependency analysis.

The module workflow validates actual JUnit testcase counts and identities through
[verify_module_report.py](../../../scripts/ci/verify_module_report.py). Reviewed
necessary sets reject every skipped testcase; an unsharded result must include
every registered test file. Duplicate identities, results outside the reviewed
owner, missing reports, empty runs and failures are rejected. Unreviewed legacy
sets retain their platform skip allowance while requiring a passing testcase.
For sharded sets, individual reports validate their own results; complete union
coverage still requires the planned shard collection and ownership checks.

| Change | Required scope |
| --- | --- |
| Ordinary Markdown/RST documentation | Existing documentation invariants and changed Markdown links; no product dependency installation |
| HarnessGUI source, fixtures, dependencies and `scripts/gui/**` | Rapid-development GUI typecheck and offline unit/playback tests; native/full/layout checks run on demand |
| Ordinary package source on a PR or main push | That package's complete offline regression directory and explicitly owned extras, plus documentation and source dependency facts |
| Test implementation or package-owned test fixture only | Its existing module or targeted owner; no global integration, consumer, native, or E2E expansion |
| Session, conversation, transcript, or hosted application code on a PR or main push | Package units plus a focused create → turn → resume → turn → close E2E smoke |
| Public AI contracts, shared Foundation, plugin SDK, and platform or native code | Existing affected package and consumer gates |
| Terminal lifecycle/platform code | TUI units, playback, native PTY/ConPTY, and tmux; a PR runs one Windows ConPTY startup/exit case unless it changes native backend ownership |
| Hosting provider source | Hosting checks and its AppHost/AppService startup and settlement consumers |
| Hosted native/wheel evidence helpers, supervisors, and PTY/ConPTY fixture drivers | AppService quality plus G16/G17 native and installed matrices; native evidence changes retain full Windows coverage on the PR |
| Edits to the CI routing table, unit inventory, selector, gate verifier, or their existing contract tests | CI routing regressions, pinned Actions syntax check, one Agent module regression, and the three-platform E2E smoke |
| Edits to the module regression reusable workflow | CI routing and Actions syntax checks, every eligible package's complete offline regression, and the three-platform E2E smoke |
| Edits to a known product reusable workflow | CI routing and syntax checks, the complete owned workflow, and three-platform E2E; unrelated native suites are not selected |
| Edits to the E2E reusable workflow or its explicitly owned smoke test file | CI routing and syntax checks and both smoke cases on three platforms |
| Main merge push with matching successful PR evidence | Lightweight documentation and any applicable CI static checks, plus verification of the successful same-tree, same-plan PR run |
| Shared dependencies, main gate infrastructure, or unknown non-document paths | All configured checks |

The fast PR/main-push source route is limited to known package source. A change
contained under an owned `tests/<package>/` tree selects that package's existing
module regression without adding global integration or E2E. Registered targeted
tests and dedicated fixtures keep their exact existing targeted owner; the core
smoke file keeps the E2E workflow. Shared test infrastructure such as root
`tests/conftest.py`, CI runners, and paths without an owner remain conservative.
Each unclassified module job still runs every test in its package directory with
offline selectors; this test-only rule changes routing, not the collected suite.
Coding excludes its separately owned UI suite, and existing AI, Agent, Coding,
and Harness example tests retain their package owner. Coding, Harness,
HarnessTUI, and TUI module jobs use deterministic shards. Coding uses eight
shards, selected from the 4,798-case PR #740 report: the slowest recomputed
hash shard carried 399 seconds of testcase time, leaving setup margin inside
the ten-minute target. A change touching
two packages runs both complete module regressions. Package source that selects
a platform, Worker, installation, LSP, or other high-risk gate also keeps the
existing route. The core E2E smoke creates a real hosted Coding session, executes the product's
read tool on a private UTF-8 fixture, closes its owners, reconstructs the catalog
and factory from the saved transcript, verifies restored messages and tool
results, and sends another message. It runs once on Linux, macOS and Windows
for code PRs. The composition canary with test session ports remains in the
Coding offline regression rather than being advertised as persistence evidence.

Agent, session, tool, approval and terminal control changes additionally select
one terminal cancellation smoke in the same platform job. This drives the real
screen input/render loop and AgentSession with scripted terminal IO: start a
controlled tool, press Escape, observe actual cancellation and task settlement,
then submit and render another reply before exiting. Native PTY/ConPTY checks
remain in their platform gates; this portable smoke does not replace them.
The model transport is synthetic and neither flow calls a live provider.
Reports require exactly one or two passing, non-skipped cases according to the
selection plan; selected smoke cases are excluded from concurrent module shards. Changes to the explicitly listed routing files exercise CI static checks,
the Agent module job, and E2E. Changes to the module regression workflow run
the complete eligible unit inventory instead of unrelated native suites. Known reusable workflows validate their own complete scope. The main orchestrator
and unclassified gate machinery retain full validation. Agent, Coding and
Foundation offline regressions have one execution owner in the module workflow;
risk selection adds platform or integration gates without rerunning those suites.

The existing routing rules are additive outside this fast PR route. Makefile source/test inventories retain explicitly shared
support paths, such as the Coding product worker canary owned by Harness
checks. An unchanged package can still be affected by changed dependencies or
shared test infrastructure. Package dependency direction does not mean every
consumer change must rerun all of its providers' suites.

The narrow routing-file exception applies to pull requests and ordinary main
pushes. Scheduled/manual validation stays full. The main workflow, other
unclassified CI files, test runners, shared test infrastructure, and build
dependencies still select the complete gate. New files inside a known package
test tree use that package's module regression; they do not silently create a
new integration or platform route.

Windows jobs have a second selection within their affected scope. An ordinary
PR or main push selected for Windows Shell runs native shell execution and an
ordinary Session. Worker-native changes add one hosted Worker query with clean
exit evidence. Crash, recovery, GC, fence, and C5 scenarios run in scheduled or
manual full validation; changing several Worker risk paths together does not
expand an ordinary PR to the full native matrix.
The Linux Hosting Worker gate likewise runs one hosted Session on an ordinary
PR; its four direct, hosted, disable-fence, and update-fence cases remain in
scheduled/manual validation and on native boundary or test changes.
AppService runs one authenticated local request and one native console entry
case; TUI runs one ConPTY startup and
exit case. Changes to the native Worker test suite itself and Windows Job/process
ownership retain the full Worker matrix. Private data, ACL, and other native
platform code retain their affected full Windows jobs. Other gate infrastructure and unknown paths retain the complete
Windows matrix. Scheduled/manual validation uses the full Windows suites.
The Windows summary verifies each selected full or smoke job,
including expected skips, against the same change plan.

The host-runtime workflow runs at most two explicit Linux smoke cases on an
ordinary PR: Worker candidate admission for Coding, native launcher containment
for Hosting, or transcript process exit for Harness and other scopes. Its pytest
XML report must contain passing cases with no skips. Changes to the native
host-runtime tests, Windows Worker platform boundaries, or gate infrastructure
retain the affected full collection. Scheduled/manual validation preserves the
original repository-wide host-runtime collection.

Coding backend collection excludes the Coding UI test inventory already owned
by the separate adapter job. This avoids rerunning that UI suite indirectly
through a backend or host-runtime check.

Machine-consumed evidence manifests and Markdown test fixtures are not ordinary
documentation. The generated package dependency document also triggers source
fact verification. The source graph is checked once; the lightweight document
check reuses existing pure document assertions without pytest collection or
product imports. Changed Markdown links are checked for existing repository
targets; remote URL reachability and heading anchors are not checked.

PR selection uses the merge base with the PR head. Main pushes use the complete
before/after range. Renames include both old and new paths; local selection
includes staged, unstaged, and untracked files. An invalid comparison or malformed
plan fails instead of silently selecting nothing.

## Local commands

```bash
# Explain the plan without installing dependencies or running tests.
python3 scripts/ci/check_changed.py --plan-only

# Preview or run the same fast package route used by PRs.
.venv/bin/python scripts/ci/check_changed.py --pr-fast --plan-only
.venv/bin/python scripts/ci/check_changed.py --pr-fast

# Run the local portion with the existing virtual environment.
.venv/bin/python scripts/ci/check_changed.py

# Compare against another integration branch.
.venv/bin/python scripts/ci/check_changed.py --base main

# Request all configured scopes explicitly.
.venv/bin/python scripts/ci/check_changed.py --full

# Existing Make entrypoints.
make plan-checks
make check-changed
make check-docs-light
make check-agent
```

On Windows, use `python` and `.venv\Scripts\python.exe` as appropriate. Selection
and direct Python scopes are portable; the legacy Make-based scopes still need
Make. Local execution reports platform, installation, and real-LSP scopes that
must run in Actions; a local success is not a substitute for that evidence.
Existing offline and host-runtime selectors are preserved. Do not repeat a
passed suite without relevant changes or an unresolved failure.

The GUI scope invokes `pnpm --dir gui run check` directly, without Unix Make
activation recipes. The rapid-development default needs Node and pnpm, not
Rust; see the
[GUI README](../../../gui/README.md). Its reusable
[lightweight workflow](../../../.github/workflows/gui-quality.yml) participates
in the same fail-closed aggregate gate, without TUI/Harness suites or native
packaging. Edits to that GUI-only workflow select GUI and CI routing/syntax
checks. Shared routing/aggregate changes still select all affected checks.
Use `check:full` for Rust/native/toolchain changes and run browser playback or
packaging when needed for acceptance. Building the executable does not establish
native visual acceptance. This temporary B1 policy must be reassessed for B2
real-service integration and release acceptance.

## Actions and branch protection

PRs and main pushes use the fast package route for ordinary changes. The daily run at 20:17 UTC and
Actions → **Change-aware Quality** → **Run workflow** select all configured
checks. Main pushes still validate the merged state, but no longer launch every
suite unconditionally. Real LSP and native evidence commands retain their
existing explicit workflows and platform setup.

Multi-job reusable workflows check their complete job inventory against the
plan: selected jobs must succeed and unselected jobs must be skipped. The
single-owner architecture, module regression, and E2E workflows rely on the
top-level gate to check their workflow result without starting another runner.
Each module shard and E2E platform also verifies a nonempty passing JUnit
report. The top-level gate requires the selector to succeed. A selected job that fails, is
cancelled, goes missing, or is unexpectedly skipped cannot produce a green gate.

The required `main` status is `quality-gate`. Ordinary documentation-only PRs
run the lightweight documentation invariants and changed-link check inside the
existing `changes` job. They select no reusable workflows, so their only
runner jobs are `changes` and `quality-gate`. The generated source dependency
document still selects the architecture source-facts workflow; mixed changes
retain every affected product check. A failure in documentation validation
fails `changes`, which in turn fails `quality-gate`.

The entrypoint always runs: skipping the whole workflow with a path filter can
leave a required check pending. The gate validates job-level skips and selected
results.

Reviewed routing selectors, catalogs, report verifiers, and their CI contract
tests are owned by the existing CI contract check. A PR containing only those
files runs documentation invariants, all CI routing and aggregation contracts,
and Actions syntax validation in the existing `changes` job without starting a
reusable Agent regression or product E2E workflow.
Unclassified CI scripts, the main workflow, shared test execution machinery,
and scoped reusable workflows retain their conservative or explicit owners.
See GitHub's [workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
and [reusable workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows).

## Maintaining the rules

Run `python3 -m unittest discover -s tests/ci -v` after changing selection or
aggregation. These tests cover documentation, package consumers, native
terminals, evidence manifests, Git ranges, renames, and rejection of false green
results. Actions also checks workflow syntax with pinned actionlint 1.7.12 when
CI infrastructure changes. The top-level `quality.yml` aggregator and its routing
scripts use this CI contract path; editing them does not start unrelated product
regressions. Platform evidence manifests and their verifiers
remain in the corresponding reusable workflows.

Broad Harness/AppHost/Hosting suite commands remain available for selected
high-risk changes, unclassified paths, and scheduled/manual full validation. When changing the routing
inventory, confirm that the path is eligible for complete offline package
regression and that live or native tests remain behind their dedicated gates.

## Reusing successful PR validation after merge

A successful PR gate with E2E smoke or package unit regression selected attempts to upload
`pr-quality-evidence` for seven days. Evidence recording is nonblocking: if the record or upload fails,
the merge push runs its selected checks normally. The evidence records the actual checked-out Git tree, complete compact execution plan, PR number,
run ID and run attempt. An ordinary main push can reuse it only for a single merge
commit whose first parent is the push's previous main revision and whose second
parent is the head of the associated merged PR from this repository.

The lookup requires a completed successful run of this same workflow, for that exact PR head with artifact evidence recording the PR number, and an unexpired evidence artifact from the
same run attempt. Its tested tree and all execution-plan fields except changed
filenames must exactly match the main checkout and selected plan. The top-level
gate verifies that change selection succeeded and every reused workflow skipped;
it records the source run in the job summary. Documentation invariants and
applicable CI routing/syntax checks still execute on main.

Missing artifacts, old runs without evidence, API errors, failed/cancelled runs,
changed plans or trees, fork PRs, direct/squash/rebase/multiple-merge pushes, and
forced pushes fall back to normal selected testing. Scheduled/manual runs and
PRs always execute their selected tests. No test-result reuse occurs across
different code contents. This removes post-merge repetition without changing
which tests the PR must pass.
