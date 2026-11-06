# Repository Guidelines

## Project Structure & Module Organization
This repository uses a `src/` layout. Core package code lives in `src/loushang/`, with AI-facing modules under `src/loushang/ai/`, agent code under `src/loushang/agent/`, and coding/session infrastructure under `src/loushang/coding/`. Tests live in `tests/`. Runnable examples live in `examples/ai/`, with supporting scripts in `scripts/` and exploratory work in `spikes/`. Architecture and design notes belong in `docs/`.

## Worktree Lane Conventions
Every task must have its own task branch and a separate, dedicated worktree.
Create both before editing; do not switch between task branches in a shared
worktree or reuse another task's worktree. Continuing the same task may reuse
its existing branch/worktree pair. Name the worktree directory to match or
clearly correspond to the branch, for example `feature/gui-i18n` with
`.worktrees/gui-i18n`, or `feature/task-worktree-isolation` with
`.worktrees/task-worktree-isolation`.

Long-lived lanes are reserved for module integration, coordination, and
verification; task implementation happens in dedicated task worktrees:

- The repository root is the control/integration lane. It normally stays on `main` and is used for progress management, direction coordination, final verification, merge/push, and integration of completed task changes.
- `.worktrees/tui` is the long-lived Native TUI lane. For TUI-dominant work, use a dedicated task branch and worktree associated with this lane.
- `.worktrees/gui` is the long-lived HarnessGUI lane. For the Tauri/Rust host, React/TypeScript frontend, desktop developer tooling, and GUI-only integration work, use a dedicated task branch and worktree associated with this lane. Use `lane/gui` as its integration branch and keep unfinished GUI work out of `main`.
- `.worktrees/code` is the long-lived V1 code hardening lane. For coding/runtime/session/tool/policy/diagnostics-dominant work, use a dedicated task branch and worktree associated with this lane.
- `.worktrees/harness` is the long-lived cross-product harness lane. For `loushang.harness`, product-neutral shared substrate, coding-to-harness migration, tool/approval/presentation/resource/context boundary work, and harness architecture docs, use a dedicated task branch and worktree associated with this lane. Use `lane/harness` as an integration branch and keep unfinished harness migration out of `main`; see `docs/internals/architecture/harness/development-workflow.md`.
- `.worktrees/method` is the long-lived method/work-runtime lane when method-layer work is active. For `loushang.method`, method execution semantics, MethodPlan/WorkEvent projection, and work/method integration work, use a dedicated task branch and worktree associated with this lane.
- `.worktrees/ai` is the long-lived AI/provider lane when AI-layer work is active. For AI/provider/model/usage/auth work, use a dedicated task branch and worktree associated with this lane.
- `.worktrees/agent` is the long-lived agent-runtime lane when agent-layer work is active. For agent loop/session orchestration/queue/tool-call semantics work, use a dedicated task branch and worktree associated with this lane.
- `.worktrees/ontology` is the long-lived ontology lane. For `loushang.ontology`, operational ontology infrastructure, semantic schema/runtime, ontology actions/functions, standards interoperability, data fusion, and ontology architecture docs, use a dedicated task branch and worktree associated with this lane. Use `lane/ontology` as its integration branch and keep it synchronized with the control lane's latest `main`.

Only the control lane should normally check out `main`. Long-lived module
lanes keep their integration branches (for example `lane/gui` or
`lane/harness`); do not check out task branches in those worktrees. Create task
branches from `main` or `origin/main`, or from the module's integration branch
when its workflow requires it, and regularly incorporate updates from that
base. GUI feature branches start from the latest `lane/gui` as described in
`gui/AGENTS.md`. Shared integration branches merge updates rather than
rewriting published history. Before creating or resuming a task worktree,
inspect `git worktree list`
and the relevant worktrees' dirty state; preserve existing user changes and
branch/worktree assignments. Existing tasks in shared lanes must be moved to
dedicated worktrees with their changes preserved before further implementation.

Task worktrees are short-lived and must be associated with an issue, PR, or named delivery objective. After delivery closes, verify that the worktree is clean and its branch has no commits outside the accepted target branch, then remove it with `git worktree remove` and delete the local branch with `git branch -d`. Do not use force deletion to bypass failed safety checks. After moving the workspace root, repair existing registrations with `git worktree repair --relative-paths <path>` and do not prune registrations before confirming that the physical worktree directories are obsolete.

## Build, Test, and Development Commands
Prefer `uv` for all Python workflows in this repository.

- `make bootstrap` — create `.venv` and install the package with dev dependencies.
- `uv run pytest tests -q` — run the full test suite.
- `make test-ai` — run AI-focused tests.
- `make check-ai` — run AI lint, typecheck, and focused tests when AI implementation, contracts, tests, or affected dependencies change; ordinary documentation does not require this suite.
- `make lint-ai` — run `ruff check` on AI modules and tests.
- `make fmt-ai` — format AI modules and tests with Ruff.
- `make typecheck-ai` — run `mypy` on `src/loushang/ai`.
- `make example-ai-complete` — run a representative example.

Use `uv run python ...` instead of bare `python ...`, and `uv pip ...` instead of `pip ...`.

## Coding Style & Naming Conventions
Target Python 3.11+ and use 4-space indentation. Follow existing naming patterns: modules and files in `snake_case`, classes in `PascalCase`, functions and variables in `snake_case`, constants in `UPPER_SNAKE_CASE`. Keep examples readable and user-facing: prefer the public `loushang.ai` API over internal provider wiring unless a file is explicitly labeled advanced.

## Testing Guidelines
Tests use `pytest` with `--import-mode=importlib` and `src` on `PYTHONPATH`. Name files `test_*.py` and keep test scope narrow and behavior-focused. Add or update tests when changing provider behavior, model resolution, auth handling, or public examples. Run targeted tests first, then broader suites if the change crosses subsystem boundaries.

Run `pytest` commands and any `make check-*` target that invokes pytest outside
the managed Codex sandbox from the first attempt. Keep existing `not live`,
`--skip-host-runtime`, and similar safety selectors; this rule does not
authorize live or network tests. Purely static Ruff, mypy, source-inspection,
and documentation checks may run in the sandbox. The workspace-level
`AGENTS.md` records the verified asyncio selector restriction and is the source
of truth for this local execution rule.

## Commit & Pull Request Guidelines
Recent history uses short summaries and occasional conventional prefixes such as `test(integration): ...`. Prefer concise, imperative commit messages; use `type(scope): summary` when helpful. PRs should explain the user-visible change, list validation performed, and call out config or API contract changes. Link related issues or design docs when relevant.

Use `make plan-checks` to inspect the change scope and `make check-changed` to run
the applicable local checks. When the plan selects AI, run `make check-ai` (also
included by `check-changed`) and fix/report failures before committing or pushing.
Do not run AI, Agent, Harness, or TUI suites solely because Coding depends on them.
Ordinary documentation uses `make check-docs-light`; changes to source contracts,
shared fixtures, dependencies, or machine-consumed documents can select broader
checks. Do not repeat passing suites without relevant changes or unresolved
failures. For changes to CI selection itself, run the focused `tests/ci` suite
and Actions syntax validation locally; the PR provides full remote validation.
See `docs/internals/testing/change-aware-quality-gates.md` for the shared rules.

Do not add or expand a PR gate without explicit approval from the authorized
approver. This includes adding a required check, workflow, job, test route,
runner platform or matrix entry; broadening path triggers; restoring a paused
workflow; moving scheduled/nonblocking coverage into the blocking PR path; or
making an existing PR result fail under a new condition. A general request to
improve or refactor CI does not by itself approve a gate increase. Before
requesting approval, record the proposed trigger, unique assertion, platforms,
expected wall-clock cost, overlap with existing coverage, and rollback. Static
analysis and proposal writing may continue while approval is pending.

## Configuration & Contributor Notes

Product upgrades must preserve startup and continued use of existing workspaces,
settings, Plugin choices and Session history. Storage changes must retain a
compatible route or supply recoverable migration; do not require users to create
a fresh workspace, clear state, or reset configuration because of an internal
format change. See [ARD-008](docs/internals/architecture/decisions/accepted/ARD-008-workspace-upgrade-compatibility.md).
Model metadata is defined in `src/loushang/ai/model/models.json`; keep examples and docs aligned with it. Treat `examples/ai/` as public guidance: main examples should show the shortest supported path, while protocol-heavy or custom-registry flows should be marked advanced.

## Architecture Decision Responsibilities

For an already authorized task, agents complete internal architecture review
and record acceptance within their delegated project responsibilities. Follow
`docs/internals/architecture/governance-profile.md`, especially
`Acceptance Responsibilities And User Confirmation`. A proposed ARD,
cross-scope change, protocol/schema revision or missing acceptance record does
not by itself require the user to approve it. Ask only when a specific policy
or task instruction reserves the decision for the user, or the decision needs
authorization beyond the existing task. Cite that requirement when asking.
Resolve material technical findings and record the actual accepting role and
reviewed scope; never manufacture a user acceptance statement.
