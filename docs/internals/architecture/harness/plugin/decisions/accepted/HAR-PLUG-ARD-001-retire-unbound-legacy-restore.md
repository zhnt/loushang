# HAR-PLUG-ARD-001: Retire The Unbound Legacy Restore Execution Stack

## Status

- ID: HAR-PLUG-ARD-001
- Scope: Harness Plugin package lifecycle and Harness sandbox adapters
- Parent: Harness
- Authority: normative
- Design status: accepted
- Implementation status: implemented locally; retained Windows-native execution not rerun
- Owner: Harness implementation agent (Codex), within the user's authorized
  legacy-code reduction task on 2026-11-05
- Method: local clean archmethod `master`,
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`; upstream not checked
- Baseline: main `e0a87a8b0`; harness lane `3885476b4` has identical affected sources

## Problem And Options

The source audit found two different legacy concerns. Ordinary unfenced
workspaces still use the materializer and fence-aware Session owner, including
the three current local development directories checked read-only. They are
covered by [ARD-008](../../../../decisions/accepted/ARD-008-workspace-upgrade-compatibility.md).
The global local-data inventory also contains test namespaces; its directory
count is not a count of real users or active workspaces.

Separately, the internal offline-restore coordinator, POSIX/Windows restore
materializers and Linux/Windows isolated legacy-runtime activation adapters
have no production composition. All construction/import consumers of their
execution APIs are tests; none is a Product, CLI, SDK, example or script route.
Snapshot publication and verification *are* production dependencies of fresh
initialization, migration review, backup inspection and pre-fence registration.

| Option | Compatibility and reduction |
| --- | --- |
| Remove the ordinary old materializer immediately | Breaks existing workspaces and Git/Python source behavior; rejected for this slice |
| Keep all legacy code pending a universal migration | Preserves an unbound execution stack with no current Product consumer |
| Retire only the unbound restore execution stack | Removes one complete inactive capability while preserving current startup and snapshot contracts; selected |

## Accepted Change

Remove `PackageOfflineRestoreOwner`, its request/materialization/activation/
result records and ports, the two restore materializers, and both sandbox
legacy-runtime modules. Remove their exclusive tests and the two corresponding
current adversarial manifest rows. The paused Windows full route loses its
explicit retired test-file and manifest-case arguments; triggers, jobs and
platforms are unchanged.

Retain snapshot records in `snapshot_records.py`, rooted platform helpers in
`posix_snapshot_io.py` and `windows_snapshot_io.py`, and update their consumers.
Retained records keep their existing names, version, field sets, fingerprint
algorithm and canonical bytes. Retained I/O operations keep their existing
native calls, identity checks, budgets and exception behavior. No forwarding
modules preserve the removed internal execution APIs.

Ordinary workspace selection, materialization, settings compatibility,
Plugin choices, transcripts, epoch fencing, pre-fence registration and
existing backup files retain their owners and behavior. No real workspace is
converted, rewritten or deleted by this delivery. General automatic conversion
of arbitrary old workspaces remains outside the accepted implementation.

## Consequences And Historical Contracts

The PLC9B4c3a/b/c and PLC9B4c5 execution portions of the old PLC9B contract are
retired by this decision. Their prior implementation and native results remain
historical evidence in Git; they no longer describe a shipped restore API.
Snapshot evidence/publication obligations from those slices remain effective.
Existing `offline_restore` diagnostic enum values remain wire-compatible and
do not advertise an executable Product command.

Reintroducing isolated old-runtime execution would require an actual Product
use case, ownership and a separate accepted design. A universal old-workspace
migration must first cover existing sources, settings, interrupted operations,
concurrency and recoverability before replacing ARD-008's ordinary old owner.

## Review, Verification And Acceptance

Codex reviewed the production import/construction graph, the existing
workspace compatibility requirement, platform snapshot consumers and the
affected test selection. The accepted scope is retirement of the unbound
capability, not retirement of ordinary old-workspace support. No independent
reviewer or user design acceptance is claimed.

Raw source extraction, retired-definition and removed-test inventories are
kept outside the product repository in the local reduction audit directory.
Implementation review found no unresolved issue in the accepted retirement
scope. The agent accepts the local implementation with the evidence below;
this does not claim a Windows-native run or resolution of unrelated baseline
failures. This change adds no PR gate or broader test route.

| Product source scope | Before | After | Net deletion |
| --- | ---: | ---: | ---: |
| Harness Python | 328,526 | 321,728 | 6,798 |
| Resources, included above | 86,555 | 83,962 | 2,593 |

Counts include comments and blank lines, exclude tests and documentation, and
include the newly extracted modules. This is a source reduction, not a directory
move counted as deletion. Retired tests have a separate 4,503-line net reduction.

Validation on 2026-11-05:

- All 98 retained snapshot/record definitions have identical ASTs to the frozen
  baseline; 57 definitions in seven consumer modules also remain identical.
  Only their imports and module descriptions changed.
- Eleven local, non-gating checks compare old/new snapshot fingerprints,
  canonical bytes, round trips and malformed-record rejection results: passed.
- The final Coding compatibility, pre-B snapshot, 125 migration CLI cases,
  old-installation inventory, materializer, architecture and CI selection run
  passed 665 cases. Its two stale Windows manifest-count assertions were
  corrected from 15 to 14 after removing the retired case, then both passed
  their focused rerun. Passing cases were not rerun merely for one green total.
- An earlier wider Resources run was interrupted after 1,303 passed, 74 skipped
  and six failures. All six reproduce on unchanged main at the same assertion:
  five discover the workspace-level ancestor `AGENTS.md` through the required
  disk-backed test root, and one expects a native `review` Skill absent from
  the existing effective Catalog. They are not changed or hidden by this slice.
- `make check-ai` passed 935 tests with two skips and seven deselections, but
  failed its existing coverage threshold. Unchanged main reproduces the same
  AI core result, 6,749/7,530 = 89.63%, below 90%; the gate is not weakened.
- Ruff, focused mypy on all ten affected source files, generated dependency
  freshness, nine documentation invariants, repository links, workflow YAML
  parsing and Git whitespace checks passed.

All pytest invocations used the managed wrapper outside the sandbox, with the
specified disk-backed runtime root and the actual worktree source on
`PYTHONPATH`. Non-live and host-runtime selectors were retained where applicable.
Native Windows execution is not established by Linux collection, AST comparison
or skips; the retained native function bodies are unchanged.
