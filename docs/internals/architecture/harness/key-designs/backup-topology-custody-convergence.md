# Closed Backup Topology Custody Convergence

- Authority: bounded implementation under COD-RESP-GOAL-002 and existing PD-D.
- Design status: accepted for reversible implementation on 2026-11-09.
- Implementation status: implemented; bounded technical acceptance on 2026-11-09.
- Owner: existing Harness Package Product; Coding retains closed backup policy.
- Baseline: `8e5a5222918b0449d9ef982dd5c51783eec87b19`.
- Method: clean local archmethod master
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`; no upstream revision claim.

## Complete Responsibility And Reuse

A76 transfers the complete durable topology read/create/reopen program from
Coding to the existing Package Product component. The original bootstrap ensure,
Arch backup writer check and Worker no-reference attestation all call this same
program. Root validation, descriptor custody, bounded reads, missing-file history
fence, exclusive publication, reread, epoch recheck and exact bytes verification
exit Code together. The original Code operation body is removed.

The receiver directly uses the original RootedFileIO, fenced epoch owners and
the actual WindowsPrivateReceiptIO object. Those owners already implement the
physical operations and retain their authority; no duplicate storage engine,
manager, state, DTO, phase protocol or Code read/write/scan callback is added.
The existing private-data archive program cannot replace a proof about the
current release's closed writer topology. No existing complete topology program
was found; the minimal new internal function supplies that coordination.

Its eleven keyword inputs are the original root, epoch and receipt owners,
expected bytes/create eligibility and file/budget/history-fence/diagnostic data.
It returns verified bytes. Coding retains dynamic canonical wire generation,
closed supported kinds, filename, budgets, revision hash domain and prefix,
product/attempt admission, original GC scopes and actual four-field observation
DTO. Arch admission and the meaning of no Worker backup writer stay Product
policy, as required by [PD-D](private-data-lifecycle-convergence.md).

The earlier managed-resolution candidate is not reopened. A51 already trialled
its two complete programs and deferred their interface cost without sufficient
common execution or simplification. Removing one half did not supply new evidence.
Unlike that shape, this slice removes one complete custody program used by three
existing entries, with no effectful stage or failure-custody callback interface.

## Ordering, Failure And Compatibility

- Bootstrap retains GC type admission, first current-admission call, write guard
  and before_load, second admission, then expected bytes construction inside the
  guard. Creation remains eligible only when before_load is None.
- Expected wire is recomputed on every read. Existing changes to supported kinds
  still invalidate persisted bytes. Canonical JSON has no trailing LF; filename,
  4096-byte maximum, hash domain and revision prefix remain identical.
- POSIX retains lstat, no-follow directory open, fstat identity/uid/private-mode
  checks and the original durable RootedFileIO scope. A missing file always scans
  sibling names, including when creation is forbidden; the 131072 scan limit,
  incomplete-inventory rejection and case-sensitive history prefix stay intact.
  Publication remains create_new, followed by readback. An existing 0644 regular
  topology was readable before and remains readable; no semantic hardening occurs.
- Windows retains the borrowed epoch-root scope and independent native receipt
  owner scopes. Forbidden creation short-circuits before listdir; eligible missing
  files use the original casefold prefix check. Windows inventory has no new
  bound. Existing receipt-stage retry and native error identity stay with the
  original receipt object; the two platform algorithms are not unified.
- Epoch checks, scope exits and exception replacement keep their original order.
  Final epoch recheck precedes exact-byte comparison; failed IO does not gain an
  extra final check. Arch checks supported kind after leaving its read guard.
  Worker attestation borrows the caller's GC/quiescence and adds no new lock.
- The original four-field frozen/slots class, own annotations, FQN, constructor,
  validation, repr and pickle identity remain in Coding. Six non-target complete
  declarations, including all public function signatures, are AST-identical;
  original hash-return AST is identical. The entire IO-body AST matches after
  only explicit parameter/constant and receipt-method binding substitutions.

Old private module aliases for Windows read/write imports exit. Arbitrary runtime
replacement of those aliases or the imported private receipt object is not a
public compatibility promise; native rename binding and the actual receipt/error
objects remain the originals.

## Source And Verification Evidence

Immutable originals, full before/after production frames, external builder and
reviewed candidates, raw original observations, XML/logs and continuation state
are retained outside Product at
`coding-convergence-continue/a76-backup-topology-custody` in workspace runtime.
The frozen source SHA is also recorded in the committed fixed fixture.

Before Product changes, 78 scenarios plus DTO reflection were captured against
byte-guarded original production. Two captures agree except the deliberately
completed Windows body-plus-exit case: the second now injects both independent
errors. Both raw sets and the first parameter-loading failure are retained.
The initial CLI attempt did not load the repository plugin and rejected an
option before tests; the corrected external capture explicitly loads it.

The immutable explicit probe first passed **79 tests on original production
(3.12s)**. Original backup/Windows-reference consumers and the existing receipt
probe passed **33 tests (18.21s)**. After replacement, the same fixed79 plus
original33 passed **112 tests (19.08s)**. Every scenario observes first call and
retry, full error graph, trace, final bytes/modes and tracked POSIX descriptors;
fixture hashes cover full original observations, with readable error summaries.
No capture mode or new default-discovered test/gate is introduced.

Additional original architecture/Product-reopen/repair-SDK/GC selection completed
**173 passed, 1 failed (113.82s)**. The existing Continuity boundary rejects A68's
already accepted journal._io_loops.write_all reuse. This batch changed neither
that source nor the assertion. Restoring all1959 original production source SHAs
and rerunning that exact unchanged node reproduced **1 failed (1.02s)** with the
same two import facts. The reviewed A76 sources were restored byte-for-byte.
This pre-existing boundary mismatch is retained for a separate, exact-fact repair;
the additional selection is not represented as all green.

Actual mypy for both production sources, Ruff and format for those sources plus
the explicit probe passed. Three independent responsibility/reuse, runtime/failure
and data/compatibility reviewers accepted direction, complete prototype and actual
code within the recorded evidence limits. The implementation owner accepts this
bounded slice under the existing Goal; the whole Goal remains open. The
independent follow-up below closes the observed Continuity fact mismatch.

POSIX storage and FD operations are real; epoch, GC and admission are controlled.
Windows uses the actual receipt object with controlled read/write and epoch
methods. Its stage examples prove coordinator calls, not native stage/ACL
recovery; the existing receipt probe has its own finite lower-level boundary.
CancelledError/KeyboardInterrupt are synchronous injections, not Task.cancel.
Close/cleanup failures occur after actual close and do not prove pre-close leak
handling. DTO reflection covers its constructor; public function signatures are
established by complete static AST comparison rather than driver reflection.

## Complete Cost And Remaining Scope

Physical production lines include imports, annotations, adapters, documentation
strings, whitespace and all receiver costs; there is no unrelated format yield.

| Scope | Before | After | Change |
| --- | ---: | ---: | ---: |
| Coding topology module | 257 | 207 | -50 |
| Package Product receiver | 0 | 103 | +103 |
| Whole Coding, 430 files | 116791 | 116741 | -50 |
| Whole system | 645632 / 1959 files | 645685 / 1960 files | +53 / +1 |

All other 1958 original production sources are byte-identical. The 53-line net
increase is the function boundary, explicit product data and imports needed for
complete ownership transfer. This is responsibility migration, not deduplication
or a whole-system reduction. It fits the user's moderate-growth rule; it does
not prove the 15K target achievable or impossible. The remaining gap is101741.

This closes the complete backup-topology storage dependency of registered history
proof. History-retention joins, strict GC-history revalidation and the registered
recovery driver remain separate unfinished programs. P1–P4 and the whole Goal
remain active/partial; KD003 is unimplemented, KD011/A33 remain user-pending.
Rollback restores both production sources as one change; no data rewrite is
needed because old wire, path and revision contracts are unchanged.

## Separate A68 Dependency Fact Correction

After the A76 migration commit `afcd4dbfb`, the original failing Continuity node
was corrected separately. A68 already accepted direct reuse of write_all, whose
short-write loop has no Journal state, storage or authority. Copying that loop or
creating another owner would undermine the accepted reuse.

The existing node exempts only the exact payload-staging source and the two
exact import facts for journal._io_loops and its write_all symbol. All forbidden
prefixes, scan roots, scanner code and original assertions remain unchanged;
other Journal imports and other sources are still rejected. It does not use an
entire-file allowed_paths exemption, add a check or broaden a PR gate. This is
the permitted narrowing of an existing check, not new gate coverage.

The exact node now passed **1 test (1.92s)**. The earlier full selection remains
**173 passed, 1 failed**; it was not rerun or rewritten as all green. A static
inverse removal of only the new local set and its single exclusion makes the
entire original test module AST identical. Production source hashes, physical
counts and all Product behavior remain unchanged. XML, static proof and reviewer
addenda are retained alongside the original failing evidence.
