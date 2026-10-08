# PLC9D3j Offline Package GC Command

## Status

- Tracking: PLC9 `#509`. `loushang-package-gc` is an offline operator route
  for an already fenced Coding B workspace on Linux and, with explicit
  `--windows-candidate`, on Windows. It is not a
  Session, RPC, UI, SDK, or scheduled deletion route.
- On Windows the CLI requires `--windows-candidate`; without it the command
  returns `package_gc_platform_unsupported` before opening a Product owner.
  macOS remains unsupported. The Windows route uses the fenced Product owner,
  runtime lease, GC gate, and exact Store target.
- Root deletion requires the exact B-owned immutable Plugin-root handoff
  crosswalk. Dependency deletion additionally requires every committed holder
  root's verified deletion, one exact dependency Store settlement, and its
  committed publisher. Neither route has private-data or backup authority.
- The hidden `--worker-candidates` switch opens the explicitly admitted
  Worker candidate Product for offline GC. It does not select Worker Sessions
  or admit dependency execution.

## Command Sequence

`prepare` invokes normal Product transaction/handoff recovery, refuses active
runtime leases or acquired transaction pins, completes the Package recovery
barrier, and durably seals the three GC reference writers. `list` returns
pathless candidate IDs, Plugin IDs, exact durable statuses, and a read-only
`dependencyRetention` projection. The latter names each dependency ref's
holder roots and keeps it retained until every holder has a verified root-GC
success. For an `orphan_candidate`, the same offline Product read joins the
exact dependency Store settlement and committed publisher, reporting either
`exact_target` with its opaque settlement ID or an evidence-conflict code.
After a deletion starts, `list` reports `started`, `retryable_failure`,
`terminal_failure`, or `succeeded` with its durable start and latest attempt
IDs. `delete`
requires one listed candidate ID and an operator attempt key; it reserves and
starts only that candidate through the D3i Product owner. The reservation
operation identity is deterministic for the Store and candidate. Repeating
the same candidate and attempt key returns the same settled result.

`retry` requires the durable reservation ID returned by `delete` or `list`
and a new attempt key. It refuses a reservation without `deletion_started`.
After an interrupted deletion it uses the recorded settlement rather than
recomputing a potentially stale candidate. The Product Store still verifies
its exact rooted physical identity and both durable tombstones before success
is projected. An attempt key is hashed before it enters the journal; operators
must retain it for exact replay.

`delete-dependency` requires the exact orphan dependency ref ID, settlement
ID, and an attempt key from the same offline Product view. Under the Product
GC gate it rechecks all holder roots and the publisher, persists one exact
dependency deletion start, and only then calls the role-specific dependency
Store. `retry-dependency` requires that durable start ID and a new attempt
key. It can finish after the Store was physically deleted but before the
attempt result was journaled. A changed target, live holder, active Session,
or unattributed Store tombstone refuses deletion. The Product and Store
journals retain the exact result or failure disposition. A Store collision or
untrusted root becomes terminal debt: `retry-dependency` returns the recorded
attempt without another Store effect. A successful result must still have the
Store tombstone on replay.
`inspect-dependency-debt --start-id ID` is a separate offline diagnostic for
one terminal dependency attempt. It rejoins the immutable start, current
orphan target, and terminal attempt under the Product GC fence, then returns
only Store ID, start/attempt/settlement IDs, disposition, and error code. An
unknown or nonterminal start, changed target, or active runtime refuses it.
It does not inspect or repair physical Store bytes, authorize a new attempt,
or clear the terminal disposition. Ordinary retry remains inert.
`review-dependency-debt` requires the exact start, terminal attempt,
settlement, and error code plus an opaque remediation reference. Under the
same offline Product fence it records one immutable review with the local
Coding CLI actor and policy. The review alone grants no Store authority.
If a reviewed repair ends in terminal Store debt, a subsequent review must
name that exact result with `--prior-repair-result-id` and supply a new
remediation reference. The Product verifies that it is the latest terminal
repair for the same unchanged dependency target before recording a version-2
review. An unstarted, successful, foreign, or older result cannot authorize a
new review. Replaying an identical review returns its original ID.
`repair-dependency-debt` requires that review ID and one attempt key. The
Product rechecks the current orphan target and terminal attempt, then asks an
explicitly injected repair policy to authorize the review. Its separate
repair journal records the operation before any Store effect. The Store still
validates native root and tree identity; a remaining collision records a
terminal repair result and leaves the tree intact. A crash after physical
deletion replays the same repair start to `already_absent` success, and later
same-key replay does not call Store. The original terminal attempt is never
rewritten, and ordinary `retry-dependency` stays inert.
The next reviewed repair has a separate start and result. The journal requires
its start to name the prior terminal repair result, so the previous result
remains inspectable and cannot be silently upgraded to success.
`inspect-dependency-repair --review-id ID` and `list.dependencyRepairs`
report the separate reviewed, started, terminal, or succeeded status with
opaque IDs. A successful status requires the Store tombstone and exact result
proof. Review and repair journals reject changed identities and duplicate
JSON keys.
The Product owner now receives dependency deletion through an explicit
role-specific Store port. Its POSIX composition creates the concrete Store only
for an admitted deletion attempt; target resolution, holder accounting, and
durable starts stay in the Product owner. The port alone does not add a Windows
Product owner or runtime lease. A configured two-Plugin Product regression
observes that this Store port is not opened while one holder remains and opens
only after both roots have verified deletion results.

The `list` output captures candidates, root statuses, dependency inspections,
and repair statuses under one offline Product hold so a concurrent GC command
cannot split those fields across different observations.

The persistent-workspace subprocess test proves preparation, candidate
selection, unknown-candidate refusal without deletion, exact root removal,
unrelated-root survival, idempotent replay, reservation retry, and success
projection across separate CLI processes. A second native case interrupts
after exact physical deletion but before result append: the status remains
`deletion_started`, and a new CLI process retries that reservation to persist
`already_absent` Store success without recapturing a candidate.
The configured Linux local-Wheel Product regression also installs a Wheel
with a dependency, removes its only holder, deletes its root, crashes after
dependency Store deletion, and retries from the durable start. Coding's
current public local-data Wheel policy does not admit dependency Wheels, so
this proves the configured Product path and operator binding, not that a
normal Coding user can install and consume a dependency-bearing plugin.
The same Product regression refuses dependency deletion while its holder is
live, with a mismatched settlement ID, or while another runtime lease is
active; each refusal leaves the dependency tree and deletion journal intact.
Another Product case records a role-specific untrusted-root Store failure as
`terminal_failure`, leaves the tree intact, and proves that both same-key replay
and a new retry return that debt without another Store call, even after a
separate review record is persisted. It also proves
exact terminal-debt inspection without a new deletion attempt and refusal for an
unknown start, a nonterminal start, or an active runtime. The separate
post-deletion crash case proves exact-start recovery to `already_absent` success.
An attempted update to a second dependency-bearing Wheel also refuses with
`package_route_unavailable`, leaving one committed set and one dependency
settlement. A Product policy binding alone does not open this update route.
An independently configured Linux Product case installs two different Plugins
that require identical dependency bytes. New dependency refs use a content
revision, so the two operations record distinct exact settlements over one
verified physical tree and one stable ref. The first root deletion leaves the
dependency retained and refuses early deletion; the second releases the final
holder, after which the Product command deletes the one tree. A Store case
also proves either settlement can replay the same ref-wide tombstone without
appending a second tombstone. Store reuse refuses changed physical tree bytes,
and reopening the Product GC owner after the first root deletion still retains
the shared dependency. Existing `tree:<manifestId>` settlements remain readable
and keep their previous non-sharing semantics.

## Remaining Closure

Existing pre-B state adoption, Windows Product execution, default management
and RPC selection, broader terminal debt repair acceptance, explicit
private-data confirmation, and correlated backup-status projection remain
separate work. The narrow POSIX repair candidate has real configured Product
evidence for exact review refusal, default-dark and rejecting policies,
persistent collision followed by a separately reviewed successful repair,
Store-effect crash recovery, independent status, and ordinary retry inertia.
A fresh Python subprocess now reopens the configured
Product from persisted workspace state and completes the same CLI command
handler after the Store-effect crash. Positive execution through the deployed
Coding CLI entry point now passes for one explicitly flagged Linux Worker
candidate Product: a real dependency-bearing Wheel is installed, its root is
removed, one Store failure becomes terminal debt, and fresh CLI processes
inspect, review, repair, replay, and confirm it. The complete
`tests/coding/test_package_gc_cli.py` file passes both the original builtin-root
and the new dependency repair cases with zero skips in the verified
`installed-gc-cli-final-20260930.xml` report outside Git. Wrong-settlement
review and unreviewed repair refuse, and ordinary retry retains the original
terminal attempt after reviewed repair. This is an
explicit operator candidate, not a general Coding data or Worker runtime route.
Configured
Product negatives already refuse a forged review with another settlement and
a missing verified holder-root deletion result before Store effects. Reopening
a new Product GC owner preserves the settled repair status and same-key replay. Coding's
ordinary data-Wheel policy still rejects dependency-bearing Wheels.
The Windows role-specific Store adapter now has the same content-ref, alias,
and exact dependency-delete code path, with native reuse/tombstone and tamper
cases added. Its cutover owner can reconstruct a fenced result from durable
evidence without the old Source and recheck the selected root through native
handles. A narrow Windows Product epoch owner retains that result beside the
native lease registry, prepares pinned state and Source roots, and rechecks
both the control root and selected epoch. Candidate ACL admission checks the
pinned control root and each state/Source directory for an exact protected
current-user/SYSTEM DACL, with explicit security on new directories. An
explicit native preparation step creates only a missing control root and
refuses an insecure existing root. Coding's Product state opener now accepts
the Windows owner. The owner now issues a native runtime lease only after
admission against the current fence and live lease set. A candidate Windows
local-Wheel Session factory now composes the generic Product runtime from this epoch
owner's exact state, dependency, and selected Store roots. It pins the
workspace identity across factory creation, transfers the live lease to the
binding, and uses a Windows root-aware admission and transaction guard.
Coding binds this factory only through an explicit `windows_candidate=True`
Product owner call; default Session selection remains closed. The cutover and
GC CLIs now admit explicit `--windows-candidate` commands after native
acceptance; unflagged Windows commands still refuse before Product effects.
The candidate also has a native Coding first-B bootstrap and selected-manifest
test, plus native local Source and built-in Wheel publication tests. A
candidate Windows Product GC composition now reuses the offline reference
gate and targets the Windows root and dependency Stores. Its native test
installs and removes one Coding builtin, refuses an active lease, then checks
exact root deletion and replay. The strict Windows Shell, Worker admission,
normal/partial retirement-to-GC, and crash retirement-to-GC jobs passed on
the same exact head `f33576a2` (run `37297923719`). The Windows quarantine
path creates and reopens its root, attempt directories, and artifact files
with exact private ACLs. A native transaction guard retains
the same coordination lock through Product admission and effects, with nested
lease reads under the held lock. Current Windows journal locks serialize
Product transactions, so throughput remains an explicit platform gate. A
B-to-B cutover adapter takes quiescence from the same lock and refuses an
active lease. A separate Windows pre-fence owner now registers Coding's old
Session startup, management writer, and Continuity bootstrap before lifecycle
preparation and holds native per-startup liveness
locks; the first-B cutover adapter projects that live set while excluding new
launches. A real Windows first-B Product API captures and authenticates
the snapshot before the fence; the default write CLI remains closed. Ordinary
Windows Session promotion requires a separate Product decision. Broader dependency
cleanup debt repair policy, ordinary Coding dependency-Wheel admission, and
broader platform/recovery evidence remain separate gates. The configured
two-Plugin Product proof does not change Coding's public local-data policy or
open dependency-bearing Wheel updates.
