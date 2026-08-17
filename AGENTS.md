# Repository Guidelines

## Project Structure & Module Organization
This repository uses a `src/` layout. Core package code lives in `src/loushang/`, with AI-facing modules under `src/loushang/ai/`, agent code under `src/loushang/agent/`, and coding/session infrastructure under `src/loushang/coding/`. Tests live in `tests/`. Runnable examples live in `examples/ai/`, with supporting scripts in `scripts/` and exploratory work in `spikes/`. Architecture and design notes belong in `docs/`.

## Worktree Lane Conventions
Use long-lived worktree lanes for major module work:

- `/home/dev/workspace/loushang` is the control/integration lane. It normally stays on `main` and is used for progress management, direction coordination, final verification, merge/push, and small integration-only edits.
- `.worktrees/tui` is the long-lived Native TUI lane. For TUI-dominant work, create or switch task branches inside this lane.
- `.worktrees/code` is the long-lived V1 code hardening lane. For coding/runtime/session/tool/policy/diagnostics-dominant work, create or switch task branches inside this lane.
- `.worktrees/harness` is the long-lived cross-product harness lane. For `loushang.harness`, product-neutral shared substrate, coding-to-harness migration, tool/approval/presentation/resource/context boundary work, and harness architecture docs, create or switch task branches inside this lane. Use `lane/harness` as an integration branch and keep unfinished harness migration out of `main`; see `docs/internals/architecture/harness/development-workflow.md`.
- `.worktrees/method` is the long-lived method/work-runtime lane when method-layer work is active. For `loushang.method`, method execution semantics, MethodPlan/WorkEvent projection, and work/method integration work, create or switch task branches inside this lane.
- `.worktrees/ai` is the long-lived AI/provider lane when AI-layer work is active. For AI/provider/model/usage/auth work, create or switch task branches inside this lane.
- `.worktrees/agent` is the long-lived agent-runtime lane when agent-layer work is active. For agent loop/session orchestration/queue/tool-call semantics work, create or switch task branches inside this lane.
- `.worktrees/ontology` is the long-lived ontology lane. For `loushang.ontology`, operational ontology infrastructure, semantic schema/runtime, ontology actions/functions, standards interoperability, data fusion, and ontology architecture docs, create or switch task branches inside this lane. Use `lane/ontology` as its integration branch and keep it synchronized with the control lane's latest `main`.

Only the control lane should normally check out `main`. Other lanes should use task branches based on `main` or `origin/main` and should regularly rebase or merge the latest `main`. Before switching branches in any lane, check dirty state and preserve user changes.

## Build, Test, and Development Commands
Prefer `uv` for all Python workflows in this repository.

- `make bootstrap` — create `.venv` and install the package with dev dependencies.
- `uv run pytest tests -q` — run the full test suite.
- `make test-ai` — run AI-focused tests.
- `make check-ai` — run AI lint, typecheck, and focused tests; run before committing or pushing AI changes, and fix/report any failures.
- `make lint-ai` — run `ruff check` on AI modules and tests.
- `make fmt-ai` — format AI modules and tests with Ruff.
- `make typecheck-ai` — run `mypy` on `src/loushang/ai`.
- `make example-ai-complete` — run a representative example.

Use `uv run python ...` instead of bare `python ...`, and `uv pip ...` instead of `pip ...`.

## Coding Style & Naming Conventions
Target Python 3.11+ and use 4-space indentation. Follow existing naming patterns: modules and files in `snake_case`, classes in `PascalCase`, functions and variables in `snake_case`, constants in `UPPER_SNAKE_CASE`. Keep examples readable and user-facing: prefer the public `loushang.ai` API over internal provider wiring unless a file is explicitly labeled advanced.

## Testing Guidelines
Tests use `pytest` with `--import-mode=importlib` and `src` on `PYTHONPATH`. Name files `test_*.py` and keep test scope narrow and behavior-focused. Add or update tests when changing provider behavior, model resolution, auth handling, or public examples. Run targeted tests first, then broader suites if the change crosses subsystem boundaries.

Run `pytest` in the normal sandbox with `--skip-host-runtime`; `make
test-sandbox` provides the full sandbox-safe suite. The
`requires_host_runtime` marker is reserved for tests with a demonstrated host
dependency. It currently excludes only the revision-aware
`JsonConversationIndex` test whose `asyncio.to_thread` work does not progress
in the restricted sandbox. Outside the sandbox, normal `pytest` runs it by
default, and `make test-host-runtime` selects the marked test explicitly. Do
not disable sandboxing for the full suite.

## Commit & Pull Request Guidelines
Recent history uses short summaries and occasional conventional prefixes such as `test(integration): ...`. Prefer concise, imperative commit messages; use `type(scope): summary` when helpful. PRs should explain the user-visible change, list validation performed, and call out config or API contract changes. Link related issues or design docs when relevant.

Before committing or pushing AI-related changes, run `make check-ai`. If it fails, fix the issue before committing; when reporting work, include the failed check and the fix applied.

## Configuration & Contributor Notes
Model metadata is defined in `src/loushang/ai/model/models.json`; keep examples and docs aligned with it. Treat `examples/ai/` as public guidance: main examples should show the shortest supported path, while protocol-heavy or custom-registry flows should be marked advanced.
