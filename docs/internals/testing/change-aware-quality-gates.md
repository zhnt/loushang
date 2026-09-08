# Change-aware quality gates

The repository uses one Actions entrypoint, [quality.yml](../../../.github/workflows/quality.yml).
It selects checks once, calls the affected reusable workflows, and verifies
their results through `quality-gate`. Local development uses the same
[selection rules](../../../scripts/ci/check-scopes.json).

## Selection policy

| Change | Required scope |
| --- | --- |
| Ordinary Markdown/RST documentation | Existing documentation invariants and changed Markdown links; no product dependency installation |
| Coding internals | Coding offline and host-runtime regressions plus source dependency facts; no automatic AI, Agent, or Harness full suite |
| AI internals | AI checks; public message, stream, and invocation contracts additionally select consumers |
| Agent runtime | Agent regressions and affected consumer checks; no automatic AI full suite |
| TUI components | TUI units, deterministic playback, HarnessTUI/Coding UI consumers |
| HarnessTUI presentation | HarnessTUI core, Coding UI adapters, deterministic playback |
| Coding UI adapters | Coding UI and deterministic playback, plus Coding checks where applicable |
| Terminal lifecycle/platform code | TUI units, playback, platform units, native PTY/ConPTY, and tmux |
| Shared dependencies, gate infrastructure, or unknown non-document paths | All configured checks |

Rules are additive. Makefile source/test inventories retain explicitly shared
support paths, such as the Coding product worker canary owned by Harness
checks. An unchanged package can still be affected by changed dependencies or
shared test infrastructure. Package dependency direction does not mean every
consumer change must rerun all of its providers' suites.

The host-runtime workflow also limits collection to affected package test
directories. A Coding-only plan collects Coding host-runtime tests, not Harness
tests. Full validation preserves the original repository-wide host-runtime
collection.

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

## Actions and branch protection

PRs and main pushes select affected checks. The daily run at 20:17 UTC and
Actions → **Change-aware Quality** → **Run workflow** select all configured
checks. Main pushes still validate the merged state, but no longer launch every
suite unconditionally. Real LSP and native evidence commands retain their
existing explicit workflows and platform setup.

Every called workflow checks its complete job inventory against the plan:
selected jobs must succeed and unselected jobs must be skipped. The top-level
gate also requires the selector to succeed. A selected job that fails, is
cancelled, goes missing, or is unexpectedly skipped cannot produce a green gate.

The first migration stage retains these existing required context names:

- `Architecture documentation`
- `ai-quality`
- `harness-quality`
- `harnesstui-quality`
- `tui-cross-platform-contracts`

They all depend on `quality-gate`, so branch protection can remain unchanged
while the new workflow is verified. These five compatibility jobs are cheap,
but do still allocate runners. After successful remote validation:

1. Add `quality-gate` to the required checks for `main`.
2. Confirm it is reported by GitHub Actions and protects the expected branch.
3. Remove the old contexts from both the ruleset and classic branch protection.
4. Remove the five compatibility jobs in a subsequent PR.

Do not remove the old requirements before the replacement is reporting. A
whole workflow skipped by a path filter can leave required checks pending;
this design keeps an unconditional entrypoint and validates job-level skips.
See GitHub's [workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
and [reusable workflows](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows).

## Maintaining the rules

Run `python3 -m unittest discover -s tests/ci -v` after changing selection or
aggregation. These tests cover documentation, package consumers, native
terminals, evidence manifests, Git ranges, renames, and rejection of false green
results. Actions also checks workflow syntax with pinned actionlint 1.7.12 when
CI infrastructure changes. Platform evidence manifests and their verifiers
remain in the corresponding reusable workflows.

The first version deliberately keeps existing broad Harness/AppHost/Hosting
suite commands intact once selected. It splits HarnessTUI core from Coding UI
tests and separates TUI units/playback from native terminals. Further reduction
inside an affected suite requires explicit coverage analysis, rather than
silently dropping existing evidence.
