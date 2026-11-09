# Windows Installation Root Lineage Convergence

- Authority: bounded design and implementation under COD-RESP-GOAL-002.
- Design status: accepted for reversible implementation on 2026-11-09.
- Implementation status: implemented; bounded technical acceptance on 2026-11-09.
- Owner: existing Harness Plugin Management private-data lifecycle.
- Baseline: `d86482c26`; clean local archmethod master
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`.

## Complete Responsibility And Existing Reuse

This slice completes the Windows Installation root-lineage custody previously in
Coding: bind, inspect, restore intent, restored receipt publication, deletion-chain
replay, generation-name fencing, canonical intent/receipt codecs and write-or-match.
All16 original programs now belong together to Plugin Management's private
`_installation_root_windows` module. Coding retains exact Installation key/plugin,
root/session path hashing, epoch/current-runtime admission and thin consumer entries.

The actual reused mechanisms are WindowsPrivateReceiptIO, private_windows_directory,
Windows directory-chain/identity primitives, and the original concrete
WindowsPrivateDeletionTransaction. Core resolves the concrete transaction type at
the old local-import point, opens the original private directory, constructs the
transaction, calls its original events() and finally _close(). That events method
already owns scan, decode, canonical bytes and sequence validation in Core. It does
not perform deletion, domain confirmation or Product admission. No Coding history-
loading, receipt-writing or root-binding IO callback is passed into Core.

Existing receipt IO owns single-file custody and staged publication, but does not
own the cross-file root lineage/deletion-predecessor contract. This bounded
extension belongs beside the original private-data deletion/restore components;
it adds no registry, generation authority, transaction engine or Product owner.
The original restore transaction keeps both Product hook positions and every
operational statement; those hooks now reach Code admission then Core lineage.
Its only source edit is a docstring clarifying the retained Installation path policy.

One private stateless frozen object holds eight pure bindings: diagnostic label,
persisted filename prefix, separate read/write bounds, original receipt IO getter,
receipt Error type getter, lazy deletion type getter and actual Generation type.
The original seven-field frozen/slots Generation remains declared in Coding with
its FQN, own annotations and constructor. Nine real consumer/test helper signatures
remain thin delegates. Unconsumed old private operation bodies exit Coding.

The narrow RootDeletionTarget protocol extends the existing deletion target with
the readonly root_path_digest actually used by the old algorithm. The first mypy
run found that the broader target protocol did not expose this field. This type
constraint fixes that gap without Any, ignores, admission or runtime checks. It
cannot be substituted by the nominal generic snapshot type without restricting
the existing structural consumer contract.

The larger lmux command candidate was explicitly rejected before this choice.
Its actual managed effects already reuse coordinator/create/probe/stop owners;
transferring its whole command would mix CLI/TUI/confirmation with Core or add
thick stage callbacks. The separately identified complete close operation remains
a possible later slice; no command framework is adopted to manufacture line savings.

## Exact Admission, Data And Recovery Contract

The three original Code path/session/runtime programs and Generation declaration
are AST-identical. Bind does not gain inspect/restore's epoch-state equality check.
Inspect and restore retain their original root mapping then state admission before
native identity IO. Runtime preparation keeps bind → Session directory preparation
→ rebind → selected-manifest recheck; it neither caches authority nor grants a new
Installation selection.

- Initial intent uses bindingVersion1 and receipt uses2, without generation or
  predecessor fields. Successors use3, generation and predecessorReceiptId.
  Canonical bytes have no appended LF. Actual key and root name remain exact.
- Generation1 takes the original `number == 1` branch, including True/1.0; successor
  bounds remain2..4097. This migration does not introduce exact-int validation.
- Root identity remains a JSON list of two nonnegative exact ints, rejecting bool.
  Receipt validation still compares complete original canonical bytes.
- Current generation first reads the whole original deletion journal. Staged
  events are rejected globally by its owner. Pending rejection occurs only when
  the final global event is unfinished and has the selected key; allow_pending
  keeps its original purpose. It does not scan for the last event of that key.
- Completed same-key events with non-None root identity are replayed in order.
  Each retained root receipt, path digest, deleted disposition and predecessor is
  verified before the future-name fence and current-generation read.
- Historical generations never recover stages. Bind/restore can use recover_stage;
  inspect remains read-only. The underlying allow_unpublished_stage=True returns
  published bytes or None, not staged bytes; recovery remains with original write IO.
- Reads remain4096 bytes; write-or-match explicitly supplies the old receipt
  wrapper's4MiB default. The two budgets are not merged or tightened.
- Write-or-match catches only original ReceiptError/FileExistsError, reads for exact
  match after that error, and still performs the separate final read. It does not
  deduplicate the two reads or broaden errors swallowed after publication.

Lazy type resolution occurs before directory enter. Constructor failure exits the
directory without transaction close; after construction, events failure always
enters close. Close and directory-exit errors retain original context and priority.
The restore intent/publication hooks remain at their original copy/flush/publication
positions in the existing restore transaction, with no new stage graph.

Original recovery differences are explicit: exact staged rename/flush retries can
complete, while an empty interrupted write remains conflicting debt on retry.
ReceiptError raised after matching publication can be swallowed by the old exact
match logic, followed by the original final read. Those behaviors are preserved,
not silently repaired during responsibility migration.

## Immutable Source And Execution Evidence

Before edits, all1957 production source hashes and the complete old module were
saved outside Product under `a71-windows-installation-root-lineage`. Capture guards
compare the actual source bytes with that old copy. The durable fixture records the
full baseline commit, source/observer hashes and each raw observation's canonical
JSON content hash. These content hashes are not pretty-file byte hashes.

The new explicit local probe has86 fixed original observations. For compactness its
fixture retains complete result/error/tree data plus the count and SHA256 of every
ordered trace entry. Raw immutable full traces remain in the external original
capture. The current probe has no capture path. Reviewers independently recomputed
all86 trace and content hashes from the original objects and matched the fixture.

Receipt reads, stage files, FD operations, byte encoding and the original deletion
transaction's scan/decode/sequence program are real. Windows ACL, native directory
identity and admitted logical-path bindings are emulated; physical storage is per-
test local disk. This does not demonstrate native Windows handles/ACL, actual
Product quiescence contention, async cancellation or complete native recovery.

Actual commands retain the managed wrapper, mandated disk runtime, worktree src
PYTHONPATH, escalation from the first pytest attempt and original non-live/host
selectors. Terminal evidence:

1. Original receipt/lineage/deletion/restore consumers:30 passed in2.95s.
2. Original guarded86 capture plus four original lineage nodes:90 passed in3.04s.
3. Durable fixed86 on unchanged old production:86 passed in2.87s.
4. Replacement fixed86 plus same four original lineage nodes:90 passed in3.03s.
5. Broader original deletion/restore/Installation/expiry/native snapshot consumers
   and relevant immutable probes:117 passed,42 original Windows skips and7 original
   selector deselections in45.55s. These overlapping selections are not accumulated
   into a unique scenario total.

The original portable lineage test moves read/write/history/name-fence/identity
hooks to the actual Core effects; its24 assert/raises ASTs remain identical. The
native pre-B receipt interruption hook now patches WindowsPrivateReceiptIO's real
write method with its mandatory maximum_bytes argument; all959 original
assert/raises ASTs and all nodes/parameters/selectors remain. Its native scenario
is among the platform skips here, not claimed executed. Existing large test files
retain their layout; only changed hook lines are reformatted.

The first type run failed only on the missing root_path_digest declaration; the
readonly protocol correction passed both production files. No Product behavior
was changed to hide a test failure. Ruff, three small-file format checks, nine static documentation invariants,
dependency freshness, the existing change plan and diff checks all pass. No CI catalog,
route, default discovery, workflow, platform or merge-blocking condition is added.
Prior AI verification remains; relevant AI source/inputs did not change.

## Full Cost And Bounded Acceptance

| Production source | Before | After | Change |
|---|---:|---:|---:|
| Coding Installation private-data adapter |674|328|−346|
| Plugin Management complete lineage and protocols |0|592|+592|
| Existing Windows restore, description only |857|857|0|
| All affected production |1531|1777|**+246**|

Current Coding is117115 lines/430files; system645173 lines/1958sources. The other
1955 old sources have identical hashes. All eight bindings, three narrow protocols,
actual DTO, nine thin compatibility entries and formatting are counted. Coding
reduces346 lines; the system adds246. This is complete responsibility migration,
not system net reduction or a claim that all491 original lines were duplicate.
Necessary moderate growth is allowed by the Nov9 Goal revision and is paid here
for the proper owner, explicit type boundary and public compatibility.

Responsibility/reuse, runtime/failure and data/compatibility reviewers independently
read the direction, complete prototype, actual Code/Core and immutable evidence.
All report no remaining slice blocker; they read XML rather than personally running
pytest. The implementation owner accepts this bounded scope, with native and
full-Goal limitations above. Private Generation identity and persisted data remain
unchanged, so no storage migration or fresh workspace is required.

Coding still exceeds15K by102115 lines. P1–P4, all remaining responsibility clusters
and final compatibility/recovery acceptance remain incomplete. KD003 bytes import
and the explicitly pending KD011/A33 work are not adopted by this slice. The next
selection should recheck the full remaining responsibility/retained-domain costs,
not infer deletion budgets from a large file or keep pursuing isolated helpers.

Final production SHA256:

- `src/loushang/coding/package_installation_private_data.py`: `aaa4b44f76a33733f2d23f746af9a975256390b0faf3f043f448dfc8f7470d1f`.
- `src/loushang/harness/plugin_management/_installation_root_windows.py`: `ead75303e13aeca6b80b0724ffc0461ea700fde03f4e41adf819a5334891bd84`.
- `src/loushang/harness/plugin_management/_private_data_restore_windows.py`: `0fe19c152ba16ac7f8a95061770e576395c575d3b569577e448d9600eda62570`.
