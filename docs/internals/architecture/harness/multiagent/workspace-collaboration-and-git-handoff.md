# Workspace Collaboration And Git Handoff

## Status

Status: **implemented phase-two first delivery**.

This document refines the workspace part of the multi-agent design. It keeps
the technical runtime Product-neutral while giving Coding a safe path from an
isolated child workspace to a parent-owned change.

## Decision

Workspace sharing and Git checkout identity are separate concerns:

```text
WorkspaceScope = parent | group | agent
GitCheckoutMode = current | detached | branch
```

The design admits named profiles rather than every combination:

| Profile | Scope | Checkout | Meaning | Delivery |
| --- | --- | --- | --- | --- |
| parent shared | `parent` | `current` | children edit the parent's current worktree | edits are directly visible |
| agent isolated artifact | `agent` | `detached` | one child owns a managed detached worktree | immutable patch artifact |
| agent isolated branch | `agent` | `branch` | one durable worker owns a branch-backed worktree | branch plus optional artifact |
| group shared branch | `group` | `branch` | a child group shares one branch-backed worktree isolated from the parent | group-owned branch/artifact |

A branch alone is not workspace isolation. Several agents cannot safely switch
one parent worktree between branches, and Git normally prevents one branch
from being checked out by several worktrees. Both branch-backed profiles
therefore use a separate physical worktree.

The first delivery implements only:

```text
parent shared
agent isolated artifact
```

The branch-backed profiles remain explicit extension points. They do not add
phase-two agent types, group lifecycle, commits, merge, push, or PR behavior.

## Layer Ownership

```text
                         loushang.coding
                    implements /       \ uses
                              v         v
loushang.harness.multiagent       loushang.harness.workspace.git
  WorkspaceLease contract          Git worktree, capture, catalog,
  opaque workspace/artifact refs   preflight, apply, cleanup mechanics

              no import in either direction
```

`harness.workspace.git` must not import `harness.multiagent`. Its requests may
carry an opaque `owner_ref`, but never `AgentRef`, agent-type, approval, CLI, or
TUI types. Coding's `CodingGitWorktreeLeasePort` remains the adapter that
translates an admitted `WorkspaceLeaseRequest` into the lower Git mechanism.

The shared Git layer owns safety invariants and structured results. Coding owns
whether an operation is admitted, where it may target, how approval is
obtained, and how conflicts are presented. `harness.multiagent` never parses a
Git patch or performs apply, merge, commit, push, or branch deletion.

The catalog is Git-specific in this phase. A cross-Product retained-workspace
catalog is deferred until another backend demonstrates the same contract.

## Parent-Shared Profile

The parent-shared profile follows the Codex collaboration discipline:

- every worker receives the same resolved parent `cwd` and sees peer edits;
- the parent assigns disjoint file or responsibility ownership;
- workers preserve unrelated changes and adapt to concurrent edits;
- the parent does not edit a worker-owned file while that worker is running;
- overlapping or tightly coupled writes remain serial;
- commit, reset, checkout, merge, push, and publish stay parent-owned.

This is an orchestration contract, not a filesystem lock or automatic merge
protocol. Coding's existing `shared_implementation_worker` is its first
Product binding.

## Agent-Isolated Artifact Profile

The isolated profile creates a managed detached worktree at an immutable base:

```text
base_oid = rev-parse HEAD^{commit}
git worktree add --detach <managed-path> <base_oid>
```

Detached checkout is the phase-two default because the parent owns commit and
publication. It avoids temporary-branch ownership and deletion hazards. A
later Work-owned branch profile may choose a named branch when long-lived
human continuation, push, or PR identity is required.

The managed root is injected by Coding and must be outside every registered
repository worktree. Harness canonicalizes the path and proves containment
before create or removal. Phase 2B replaces Coding's current
`<repository>/.loushang/worktrees` default with a Product state/session path
outside the repository and all registered worktrees; bootstrap fails closed if
the configured root is nested inside one.

### Persistent Record

The Git backend writes one record per workspace under a Product-supplied state
root:

```text
<state-root>/workspaces/<repository-id>/
  records/<workspace-id>.json
  artifacts/<patch-digest>.patch
  manifests/<manifest-digest>.paths
  descriptors/<artifact-ref>.json
  locks/
```

The repository identity derives from the canonical common Git directory. A
record stores the original identity and paths for later verification; it does
not treat a movable branch name as change identity.

The minimum state machine is:

```text
allocating -> active
active | retained -> capturing
capturing -> retained             # immutable artifact published
capturing -> active               # no changes relative to base_oid
retained -> applying -> applied
active | retained | applied | needs_inspection -> discarding -> discarded
any live state -> missing | needs_inspection
```

Creation first writes an `allocating` record containing the fixed
`workspace_id`, managed path, `base_oid`, repository identity, and opaque
`owner_ref`. Only after Git confirms worktree creation does a revision
compare-and-set move the record to `active` and return the lease. Restart
reconciliation completes a confirmed allocation or safely cleans it up; it
also inspects physical worktrees and artifacts rather than trusting record
state blindly.

Records use independent files, cross-process locking, revision
compare-and-set, operation ids, durable temporary writes, and atomic
replacement. A retained workspace may enter `capturing` again for a later
follow-up round. An empty capture publishes no artifact and returns the
workspace to `active`.

Cancellation after entering `capturing`, `applying`, or `discarding` moves the
record to `needs_inspection` before propagating cancellation. This prevents a
live Product process from stranding a record in a transient state that restart
reconciliation would otherwise leave owned by that same PID.

### Round Artifact

The child round performs bounded capture while materializing its terminal
payload, before the terminal fact is committed. Expected timeout or Git
capture failure leaves the workspace recorded as `needs_inspection`, preserves
the worktree, and returns a `WorkspaceLeaseSnapshot` with its `workspace_ref`
and empty `artifact_refs`; it does not raise into or replace the completed
model result. The session driver passes that snapshot into the
`SubagentRoundResult`, then commits the terminal fact. Programming errors and
broken internal invariants may still fail loudly. Cleanup remains strictly
after the terminal commit.

Each round is independent. A follow-up that changes the workspace produces a
new content-addressed artifact rather than mutating the reference from an
earlier completion notice.

Capture represents the final file tree relative to `base_oid`; staged and
unstaged layers are not preserved separately. A temporary index includes
tracked changes and non-ignored untracked files:

```text
GIT_INDEX_FILE=<temporary-index>
git read-tree <base_oid>
git add -A -- .
git diff --cached --binary --full-index --no-ext-diff --no-renames <base_oid>
```

A separate NUL-delimited manifest records touched paths. Patch and manifest
bytes are written durably and hashed. The immutable artifact descriptor binds
`patch_digest`, `manifest_digest`, `base_oid`, and repository identity; its
canonical digest is the opaque `artifact_ref`. Descriptor, patch, and manifest
are atomically published before that reference enters a
`WorkspaceLeaseSnapshot`. Internal Git commands disable prompting and hooks
and run through the existing bounded execution service. Git path output uses
UTF-8 with `surrogateescape`, preserving POSIX filenames containing arbitrary
non-NUL bytes instead of converting a successful model round into a decoding
failure.

`WorkspaceLeaseSnapshot` gains opaque `artifact_refs`. Coding stops using a
mutable `git-branch:` value as its change identity; the transitional generic
`change_set_ref` field is not populated by the new Coding Git path.

## Review And Apply

The shared Git layer exposes structured read and apply mechanics:

```text
list / show / diff
plan_apply(artifact_ref, target) -> GitApplyPlan
apply(plan) -> GitApplyResult
discard(workspace_ref) -> GitDiscardResult
```

The requested target is first normalized to the containing repository's root;
running the CLI from a nested directory cannot cause Git to silently ignore
root-level patch paths. `GitApplyPlan` binds:

```text
catalog revision
artifact digest
repository identity
target HEAD plus content-level staged/unstaged/untracked fingerprint
touched paths
```

Apply is the final handoff for that workspace. Planning requires released
runtime ownership, and an `applied` workspace cannot accept another child
follow-up or enter `capturing` again. Further work starts a new workspace from
a new admitted base rather than replaying an earlier full-tree patch.

Planning rehashes the descriptor, patch, and manifest, verifies every bound
identity, and rejects path escape, repository mismatch, artifact corruption,
and staged, unstaged, or untracked target changes on a touched path.
Non-overlap dirty target paths may remain.

After Product approval, apply acquires a repository-wide cross-process lock,
revalidates the complete plan, repeats `git apply --check`, and uses strict
`git apply` without `--index`, `--3way`, or `--reject`. Expected conflicts
therefore fail before writing. The contract does not claim filesystem
transactionality across power loss or an external process that ignores the
lock.

The fingerprint hashes Git's binary staged and unstaged diffs, status metadata,
and the path, mode, target, and contents of every non-ignored untracked file.
Changing the contents of an already-dirty file therefore invalidates an
approved plan even when its porcelain status label is unchanged.

Coding initially exposes the operation through explicit CLI commands:

```text
loushang workspace list
loushang workspace show <workspace-ref>
loushang workspace diff <workspace-ref>
loushang workspace apply <workspace-ref> --yes
loushang workspace discard <workspace-ref> --yes
```

Apply and discard require explicit Coding confirmation; non-interactive use
must pass `--yes`. Model-callable mutation tools are deferred until that
approval path has been validated.
Apply does not commit, merge, publish, or automatically discard the source.

Discard removes the live managed worktree and marks a tombstone while retaining
the immutable artifact for audit and stable terminal references. Permanent
artifact purge is a separate, later destructive operation.

`WorkspaceLeasePort.release` only releases runtime ownership. It may
automatically clean an unchanged workspace, but a changed, retained, applied,
or `needs_inspection` workspace remains available for review. Session shutdown
therefore cannot delete retained work. Destructive removal of a live retained
workspace occurs only through an explicit, confirmed `discard`.

## Branch-Backed Profiles

Branch-backed worktrees are deliberately deferred:

- `agent + branch` belongs with durable Work execution and human continuation;
- `group + branch` owns one physical worktree and branch for the whole group;
- group members may edit disjoint files, but only the group coordinator owns
  Git index, commit, reset, checkout, and publication operations;
- individual child notices reference the group workspace, while a group
  checkpoint produces the aggregate artifact.

These rules reserve a coherent extension without requiring a phase-two
`WorkspaceGroup`, ref-counting, branch catalog, or group finalization API.

## First Delivery And Evidence

The first delivery is complete only when it proves:

- detached acquire persists `allocating` before Git creation and reaches
  `active` before returning;
- tracked, staged, unstaged, untracked, deleted, binary, mode, and symlink
  changes are captured; ignored files are excluded;
- descriptor, patch, or manifest tampering, repository mismatch, path escape,
  and stale apply plans fail closed;
- nested-directory targets normalize to the repository root, and a change to
  already-dirty target content invalidates the approved plan;
- overlapping target dirt rejects apply without changing target bytes or
  index; non-overlap dirt survives a successful un-staged apply;
- capture timeout or expected Git failure preserves the model result and
  worktree, records `needs_inspection`, and returns no artifact reference;
- cancellation during capture, apply, discard, or lock acquisition leaves no
  transient record or open lock handle;
- POSIX non-UTF-8 filenames round-trip through capture and apply, while record
  publication keeps a Windows-compatible atomic replacement fallback;
- restart reconciliation recovers retained records and marks missing or
  inconsistent state explicitly;
- concurrent apply/discard operations are serialized by lock plus revision
  compare-and-set;
- removal verifies managed-root containment, repository identity, and Git's
  registered worktree list;
- session release retains changed, applied, and inspection-needed workspaces;
  only explicit confirmed discard removes them;
- one playback covers spawn, terminal artifact reference, diff, approved
  apply, and discard.

Binary, concurrency, crash-window, and path-tampering cases belong in real Git
integration tests rather than being simulated through TUI playback.
