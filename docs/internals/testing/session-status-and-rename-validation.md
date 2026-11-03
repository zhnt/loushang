# Session Status And Rename Validation

## Scope

Authority: implementation and validation evidence. Owner: HarnessTUI presentation
and Harness transcript discovery. Date: 2026-10-15.

The status line displays remaining context as `64% left`. Context calculation,
rounding, measurement source and accuracy tokens are unchanged. Unknown usage
remains `ctx ?`; stale and structurally changed usage retain their suffixes.
Detailed usage views retain accuracy information.

The status line prefers a session name and otherwise displays the first eight
characters of its ID. Resume rows also show compact IDs; shared prefixes extend
until distinguishable among loaded rows. Full IDs remain in status/statistics
details, the Coding resume preview and selection targets. Presentation never
rewrites stored IDs, names, resume arguments or full identity references.

## Reproduced Rename Failure

A real persistent session has an original name near the beginning, a rename
between large messages, and an accurate index summary. Another transcript changes
and makes the directory index stale. Opening Resume discards every indexed row
and reads only transcript heads and tails. The rename is outside those segments,
so the original name returns despite the correct durable transcript and summary.
An ensuing bounded index refresh can preserve that partial result across restart.

The regression fails with `Original name` instead of `Renamed session` before the
fix. It exercises persistent SessionManager writes, the directory runtime, Coding
continuity and an actual ContinuitySurface, then repeats queries and constructs
a new runtime to model reopening after exit. It also clears the name and checks
the existing first-message fallback.

## Repair And Review

Discovery now passes validated index entries into bounded projection. An entry
is reused only when its provider, namespace, logical identity, direct-child path
and authority fingerprint match the current candidate. A second stat rejects a
changed candidate. Changed files still use bounded previews; a directory-wide
stale flag cannot downgrade unchanged summaries. Background bounded refresh uses
the same rule, retaining names across restart. Reused rows retain their known
locator-to-file binding, so selecting them does not trigger a directory rescan.

Candidate limits, transcript byte budgets, current-session exclusion and cursor
semantics remain in place. Missing or unusable caches retain existing partial
preview behavior; this change does not turn Resume into an unbounded replay.
No transcript schema, migration, authority ownership or PR gate changes.

Implementer review covers UI identity/selection separation, cache invalidation and
bounded work. Tests check changed and cleared names are never taken from a stale
entry, and unchanged entries avoid transcript body reads. The consulted local
architecture method was clean `master` at
`0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`; no method files are vendored.

## Validation

Focused rename, cache invalidation, collision and layout regressions pass on
Linux with Python 3.11. Native macOS and Windows execution is not available in
this workspace. These changes use shared presentation and transcript logic;
this evidence does not claim native validation on those platforms.

| Check | Result |
| --- | --- |
| Coding offline module | 3,761 passed, 20 platform skips, 57 deselected |
| Coding UI regression | 588 passed, 59 deselected |
| Render contracts | 181 passed, 7,524 deselected |
| HarnessTUI offline module | 773 passed, 5 deselected |
| Create/turn/resume/close and terminal-cancel E2E | 2 passed |
| Harness offline inventory, including targeted environment retries | 5,390 passed; 121 platform skips, 3 deselected |
| Changed implementation mypy | 15 files passed; final changed-file follow-ups passed |
| Coding UI mypy | 24 files passed |
| Ruff, dependency facts and documentation invariants | Passed; 9 documentation assertions |

All selected local offline scopes completed successfully, including the
environment retries described below. Live providers and opt-in host-runtime
campaigns were excluded by the existing selectors.

The initial broad regression encountered `ENOSPC` on the environment's 164 MiB
runtime tmpfs. Affected checks use the existing `LOUSHANG_RUNTIME_DIR` setting
with owner-private disk-backed scratch under `/var/tmp`. Compiler `TMPDIR` uses
the same private filesystem. Workspace ancestry is unsuitable for native lease
tests because existing group-writable parents correctly fail admission.
The 64 MiB capacity preflight, native directory checks, offline markers and test
assertions remain enabled. The project virtual environment is reused directly
for render contracts, without a second worktree environment.

Harness coverage combines 5,281 initially passing cases, 98 successful retries,
three successful native pilot cases and the final eight successful retries.
The initial 109 failures involved exhausted scratch storage, unsafe scratch
ancestry or compiler temporary-file quota. No assertions were removed to make
the retries pass. Logs and exact retry node lists remain in the task's ignored
`.artifacts/session-presentation-*` evidence files.
