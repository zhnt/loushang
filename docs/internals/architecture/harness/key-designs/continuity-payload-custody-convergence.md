# Continuity Payload Custody Convergence

- Authority: bounded design and implementation record under COD-RESP-GOAL-002.
- Design status: accepted for reversible implementation on 2026-11-09.
- Implementation status: implemented; bounded technical acceptance on 2026-11-09.
- Owner: existing Harness Continuity; Coding retains Product admission and restore policy.
- Source baseline: `60944e6d4`; local clean archmethod master
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`.

## Complete Scenario And Reuse Decision

The original Continuity bridge has an entire temporary-file custody program:
create/check the path, admit directory-relative operations, open and pin the root,
create one private unique file, write/fsync, retain both descriptors and identities,
delete only that inode through the original root, then close both descriptors.
Its asynchronous write and removal also settle native work before releasing
ownership. These mechanisms carry no Coding source selection or restore policy.

The complete program belongs in the existing Continuity subsystem's internal
`_payload_staging.py`. A stateless frozen binding supplies only the original
diagnostic label. Core takes no Product, Session, approval, source policy, IO
callback or stage handler. Its private DTO is the one five-field/frozen/slots
custody value, with Code retaining a compatibility alias. No second engine,
registry, task scope, lease state machine or permission authority is introduced.

The original short-write loop directly adopts `journal._io_loops.write_all`,
with the same no-progress error and subsequent fsync. Atomic remove continues
to use the original `await_owned_task`. `settled_io` cannot substitute for atomic
write: the original shield loop has distinct cancellation/error precedence.
`CallbackPreparedActivationLease` remains unchanged and does not own native FDs.
Existing `stage_file_import` copies an existing source into a target and has
different path, rollback and Blob contracts. RootedFileIO would narrow the original
POSIX capability contract. Neither is forced onto payload staging.

Native release install/repair was also audited. Its complete programs interleave
Product approval/currentness, receipt/source validation, GC, staging debt rules,
publication and post-publication reader observations. Moving them as one operation
with Code IO callbacks would retain thick cross-layer execution. That candidate
shape is not adopted, and native installation remains explicit residual work.

## Product And Compatibility Boundary

All 32 retained Code class/function declarations are AST-identical to the
baseline. Coding keeps target/source/provider admission, bytes limits, root/cwd
selection, restore invocation, prepared-operation settlement, abort and lease
publication. The original 11 staging declarations exit Code. It binds the shared
program and retains the private write/remove/atomic/support entry aliases used
by current callers. Public constructors, exports and support checks keep their
behavior; no platform or imported media is newly admitted.

The private DTO's definition module and private helpers' bound-method reflection
metadata change. The DTO still has the original fields and Code import alias;
it holds current-process FD custody, not a persisted Product record. This slice
does not claim stable private FQN/new-pickle metadata. No public or persisted
contract requiring the old private definition location was found. Avoiding an
extra DTO factory and two Protocols is part of the accepted cost/shape choice.

The program retains mkdir → ancestor checks → platform capability → root open/
stat/identity → chmod0700 → at most128 exclusive names → chmod0600 → complete
write/fsync → return pins. Writable sticky ancestors are still accepted; ordinary
writable ancestors and symlink/reparse roots are refused. Suffix and random name
rules are unchanged. Cleanup uses retained root/file identity, never deletes a
replacement inode, and closes file FD before root FD even on failure. A renamed
root is cleaned through its retained descriptor; a new visible root is untouched.

Atomic write still returns a settled value if cancellation is withdrawn at its
existing special point, keeps the latest repeated cancellation, and cleans any
successfully produced payload before propagating cancellation. A late write
error escaping the shield loop is preserved directly; the separate already-done
error branch instead annotates cancellation. Cleanup errors/notes and the
Bridge's operation-error versus cleanup-error/abort precedence remain original.

This is an intermediate responsibility migration. [KD003 bytes import](continuity-bytes-import-convergence.md)
remains draft/not-started. The real Path, nonowned FileCopy and temporary_root's
JSONL attachment-source semantics remain. No staging elimination, immutable-input
API, unified owned/legacy/detached rollback or whole P3 completion is claimed.
Only the common short-write loop is algorithm reuse; the rest is responsibility
migration, not algorithm deduplication or a way to hide Coding-specific policy.

## Baseline, Real Verification And Limits

Before production edits, all1,954 source hashes and the original Code/test
modules were preserved outside Product. First original-consumer execution had
14 failures/3 passes/1 skip: the required pytest runtime is below the workspace,
whose mode0775 correctly triggers the original writable-ancestor refusal. The
first two new probe cases failed the same admission. These failures are retained.
Product policy, workspace modes, managed pytest wrapper and the mandated runtime
environment were not changed.

For these path-admission scenarios only, a command-local fixture supplies each
test an independently owned private `/tmp` input directory, below sticky1777.
The managed wrapper still owns its normal run lease and runtime scratch. This
input fixture corrects the test environment; it does not bypass the admission
check, change basetemp or open a platform. Its durable explicit-local probe can
also be loaded as a local plugin when reproducing the original Bridge cases.

43 immutable original observations cover real write/stat/fsync/unlink and both
FDs, mode/identity/inheritance, root/ancestor admission, short/zero writes,
128 collisions, replacement/missing files, renamed roots, compound close faults,
and asynchronous write/remove cancellation. Barrier-controlled schedules distinguish
the two late-write error branches, repeated cancellation and cleanup notes.
The OS capability membership includes the instrumented functions so the probe
does not accidentally observe only unsupported-platform refusal. Expected accepted
cases are asserted before capturing. Source guards prevent replacement code from
being used as old expectations; the durable probe has no capture path.

Original43 observations plus17 original Bridge consumers pass60 with1 original
platform skip before (2.76s) and after (2.61s). Broader durable/local and original
Bridge/Provider/bootstrap/lease/import/architecture selection passes151 with1
original skip (31.43s). These overlapping runs are not independent additive coverage.
Only test effect-hook locations move to the real Core write/remove/write-bytes/
secrets owner. Original assertion ASTs, test names, decorators and selectors are
unchanged. No default test discovery, gate, route, workflow or platform expands.

Real filesystem evidence is local POSIX. These tests do not prove every scheduler
interleaving, supported OS, full Coding SDK/Agent construction or provider/network
activation. Source/Blob import and model execution remain outside this changed
program. Existing ownership boundaries continue to determine their verification.

## Full Cost And Delivery

| Production source | Before | After | Difference |
| --- | ---: | ---: | ---: |
| Coding Continuity | 1,555 | 1,359 | −196 |
| New internal Continuity custody, including DTO/label/imports/formatting | 0 | 219 | +219 |
| Total | 1,555 | 1,578 | +23 |

Coding becomes118177 lines/430files; system644571 lines/1955sources. All1,953
other old production sources are unchanged. Physical formatting/alias/import
costs are included; no physical migration quantity is called system net reduction.
Non-production evidence adds477 probe lines and4528 immutable-fixture lines;
the original Bridge test file changes only effect-hook binding/imports (+2 lines).
The complete P1–P4/≤15K Goal remains active, with103177 Coding lines still over
the bound. KD011/A33 pending user work is not adopted.

Both production sources pass mypy. Changed Python passes Ruff and formatting;
existing dependency freshness, documentation, check-plan generation and diff
validation are checked for the final frame. Earlier AI results are retained
because no relevant AI implementation/input changed. Independent actual-code
reviews by `/root/responsibility_review`, `/root/runtime_review` and
`/root/compatibility_review` accepted this bounded implementation after inspecting
the actual source, original assertions, fixture provenance, costs and terminal
results. They did not rerun pytest; responsibility also independently ran Ruff.
The implementation owner accepts the slice after checking those reports and
the final verification terminals.

Final Code SHA256 is `0119e90b23575600634c750b7aebf4cadc46037052e56c2183a878d46072550f`;
Core is `b62c4b9d31e7da0aa8c166ce930d0808e668fbd0a634928c2e00a08039abeefa`.

Rollback Code's binding and Core custody together, restoring test hook locations
with them. There is no persistent schema migration. Retained in-flight objects
must be settled before changing implementations, as with the original program.
