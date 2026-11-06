# Harness Lane Development Workflow

## Purpose

`lane/harness` is a long-lived integration branch for the cross-product harness
refactor.

It may contain many commits and remote pushes before it is ready for `main`.
That is intentional. The branch is allowed to accumulate coordinated harness
migration work without blocking parallel `code`, `tui`, `agent`, `ai`, or
`method` lanes.

## Branch Model

Normal product and subsystem work continues to merge through `main`:

```text
code / tui / agent / ai / method task branches
  -> main
```

Harness migration work integrates through `lane/harness` first:

```text
harness/<slice>
  -> lane/harness
  -> main   # only after the harness migration is bootable and validated
```

`lane/harness` may be pushed to `origin/lane/harness` for backup, review, and
coordination. Pushing it does not affect `main`; only an explicit merge or PR
into `main` does.

## Daily Rules

- Keep `lane/harness` as the shared integration branch for harness refactoring.
- Create semantic capability branches from `lane/harness`, such as
  `harness/resource-package-runtime` or `harness/extension-runtime-core`.
  Keep dependency-ordered foundation, engine, adapter, and closure commits on
  that branch instead of creating one branch per leaf type or compatibility
  shim.
- Give each task branch a separate, dedicated worktree whose directory name
  matches or clearly corresponds to the branch, for example
  `harness/resource-package-runtime` in
  `.worktrees/harness-resource-package-runtime`. Keep `.worktrees/harness`
  on `lane/harness` for integration and verification; never switch task
  branches in that shared worktree.
- Open PRs for those task branches against `lane/harness`, not `main`.
- Do not merge `lane/harness` into `code`, `tui`, `agent`, `ai`, or `method`
  lanes.
- If a small fix is needed by both `main` and `lane/harness`, land it on
  `main` first or cherry-pick it intentionally.
- Keep `lane/harness` synchronized with `origin/main` regularly.

For the shared long-lived branch, prefer merge over rebase:

```bash
git fetch origin
git merge origin/main
```

Do not force-push `lane/harness` unless the team has explicitly agreed to
rewrite that integration branch.

## Mainline Isolation

Other lanes should continue to use `origin/main` as their base unless a task is
explicitly part of the harness migration.

This keeps unfinished harness work from affecting:

- coding hardening associated with the `code` lane;
- terminal UI work associated with the `tui` lane;
- low-level agent loop work associated with the `agent` lane;
- provider/model/auth work associated with the `ai` lane;
- method/work-runtime work associated with the `method` lane.

Each task uses its own branch and worktree; these lane names identify module
ownership and integration, not shared task working directories.

`lane/harness` may temporarily contain intermediate states that are acceptable
inside the harness integration branch but not acceptable on `main`.

## Final Main Merge Gate

Do not merge `lane/harness` into `main` until the branch is ready as an
integrated product state.

Minimum readiness criteria:

- `loushang` can start through the supported coding entrypoint or agreed smoke
  command.
- Focused coding behavior tests pass for changed surfaces.
- Architecture import-boundary tests pass.
- Ruff passes for changed source files when source files are touched.
- `git diff --check` passes.
- No `loushang.harness -> product`, `harness -> tui`, `harness -> work`,
  `harness -> method`, or `harness -> ai` imports are introduced.
- No unfinished compatibility shims remain unless explicitly documented and
  accepted.
- Migration inventory and subsystem docs match the final code state.

Only after this gate should a final PR from `lane/harness` to `main` be opened
or marked ready.

## Review Posture

Harness task PRs should be reviewed for:

- boundary correctness;
- product behavior preservation;
- import direction;
- migration reversibility;
- test focus;
- compatibility strategy.

The review question is not only whether a slice works. It is whether the slice
keeps `harness` product-neutral while making future `design`, `research`,
`ppt`, `cowork`, and OEM-defined Products easier to build.
