# Linux Product Native Release Custody Convergence

- Authority: bounded design and implementation under COD-RESP-GOAL-002.
- Design status: accepted for reversible implementation on 2026-11-09.
- Implementation status: implemented; bounded technical acceptance on 2026-11-09.
- Owner: existing Harness Package Product; Coding retains Product values/profile.
- Baseline: `12f67b71a`; clean local archmethod master
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`.

## Complete Program And Reuse

Earlier candidates moving only installation would have required Coding to supply
whole verify, readback and open-reader programs as callbacks. They were rejected.
This slice moves the entire Linux H6 Product release custody: review, installation,
repair, installed receipt/source verification, opening the Product reader and
current launch-material projection. Those actual programs now reside together in
`harness.package_product._linux_worker_native_release`.

The existing Package Product PosixLocalWheelProductSessionOwner remains the one
Product authority. The implementation uses only its existing public state_root,
policy, gc_gate and assert_root_gc_authority_current. Approval is obtained through
the original concrete approval owner and its public current() port. A69 already
placed that owner's Rooted program in Worker history. No second approval source,
manager, registry, transaction engine or launch authority is introduced.

Reuse precedes extension: A67's complete inert release verifier handles original
catalog/ELF/RECORD/member reads; the existing Wheel inspector, canonical bytes,
SHA, noreplace publication and journal write_all remain the actual mechanisms.
The original complete-write loop is removed in favor of write_all with its exact
no-progress message and original chmod/fsync/finally scope. Product-specific
receipt/source custody belongs to Package Product, outside the Worker byte verifier.

One private frozen stateless binding object has five associated output types to
preserve actual Approval, Review, Closure, Material and Reader identities. Its 13
fields are three Product strings, eight pure type/factory/verifier getters and two
lazy version leaves. They contain no Coding IO program or step handler. Receipt
schema, layout, budgets and publication order are fixed in Core, not a policy DSL.
The binding constructor performs no validation, version query or filesystem IO.

## Public Values And Original Entry Differences

Coding retains the actual frozen/slots LaunchMaterial dataclass, both public
Reader classes, original constructor/property/current_closure programs and exact
public function/method annotations. The material method and public operations are
typed thin delegates; Core returns real Coding DTOs/readers through pure factories.
There is no new proxy type or persistence migration. The unused private installed
root-descriptor forwarding helper exits; repository source/tests have no consumer.
The two private Wheel/stage helpers used by the original recovery test retain thin
forwarding entries. All replaced operational bodies exit Coding.

The two module version aliases remain independent and lazy. Wheel review/member
validation/stage flush uses native_install.version; installed descriptor verification
uses installed_native.version after A67's platform admission. Source/Closure
bindings remain in the original raw-verifier factory at actual verification time.
The installed approval class is resolved at the original constructor/current point.
Arbitrary monkeypatches of former imported private operation aliases are not a
compatibility API; fault hooks follow the actual owner rather than retaining Code IO.

- Review constructs the approval owner before wheel admission, then runs the Wheel
  inspector, six-member validation and inert verifier before GC/currentness/Review.
- Install does not call review or its inspector. Wheel/hash/ZIP/profile prechecks
  precede write-GC, current approval and trust admission. Full installed validation
  occurs from the opened stage descriptor at the original point.
- Repair has its original TypeError admission and no Wheel input. It requires one
  complete prefix stage and absent target, retaining partial or ambiguous debt.
- Reader construction itself does not add admission or IO. Open-reader retains its
  Product/profile admission, GC/currentness and actual current_closure check.
- Material uses its original approval-current exceptions, without installation's
  ApprovalError-to-release-error conversion, and projects the original `:gN` suffix.

## Bytes, Publication And Failure Contract

The installed receipt remains exactly seven canonical keys plus LF on disk, exact
int version1, original scope, four lower-case digests and recordDigest. Reading
validates the digest, pops recordDigest and returns the original six-key dict.
Retained source.whl remains the exact admitted bytes and is checked against receipt.
Installed RECORD, package initializer, metadata and catalog verification are reused
unchanged. Review's acceptance of an inert bad initializer and install's subsequent
rejection remain an explicit original asymmetry.

Stage writes remain sorted, launcher0500/other files0600, parent creation0700,
source and receipt0600, followed by the same three directory fsync calls and flags.
Install refuses stage debt before checking an existing target for idempotence.
Its TemporaryDirectory cleans pre-publication failures; repair retains its existing
stage. Neither operation deletes a published target after rename succeeds.

Both paths retain descriptor validation, approved facts, stage fsync, named/opened
inode comparison, second approval, Product currentness, visible Product root check,
noreplace rename, target identity and parent fsync in order. Install opens its final
reader before the additional root readback; repair performs readback before open.
Root and descriptor verification retain separate nested GC/catch boundaries. Only
the original ApprovalError is wrapped by the install/repair approval guard.

Original close/cleanup priority is preserved. In particular a TemporaryDirectory
cleanup error after a stage-to-symlink swap can cover the earlier staged-root error;
its exception context remains recorded. Injected close failures retain the original
outstanding-FD observations, with probe-only cleanup afterward. This refactor does
not silently repair those failure contracts. After repair rename and parent-fsync
failure, another repair rejects the now-published state as ambiguous; five other
fixed retry paths succeed. Not all retries are described as successful recovery.

## Provenance And Actual Validation

All1,956 production hashes and both complete old modules were saved outside Product
under the local `a70-linux-product-native-release` evidence directory before edits.
The original-source guards compare both actual files with their frozen byte copies.
A fixed inert ELF helper supplies bytes only; nothing executes a native launcher.
The durable fixture records baseline/source/observer hashes and has no capture path.

Initial original capture:117 observations plus one existing Reader node passed118.
The first fixed replay on unchanged production was100 passed/17 trace differences:
the observer normalized absolute stage paths but missed random relative-open names.
Only the observer normalization was corrected; original observations and the initial
fixture remain archived. Six same-disk retries were added, and all123 observations
were recaptured under the unchanged original-source guards,124 passed including
the same existing node. The durable fixed123 then passed on original production
before implementation. Replacement expectations were never captured from new code.

After implementation the same123 plus A67's original112 Reader nodes passed235
in5.31s. The probes compare real ZIP/member bytes, stat/FD/read/write/fsync/close
traces, file hashes/modes, exact receipt bytes, error cause/context graphs, staging
cleanup/debt, approvals, inode/root replacement, noreplace and public result types.
Product fencing and ApprovalJournal.current are controlled; this does not prove
actual GC contention, native execution, platform privilege or async task cancellation.

Stage-name normalization also folds the two fixed multi-stage snapshot keys. The
original rejection/trace remains tested, and an additional literal filesystem-name
assertion checks that both real debt directories survive. The fixture is unchanged.
This extra assertion passed on both the replacement and a separate pristine12f
baseline worktree. The baseline worktree was checked clean after removing only
the two copied probe inputs; its branch was verified contained in task HEAD,
then removed with worktree remove and branch -d. It is not a new scenario.

The original candidate-wheel fault hook now patches Core.verify_descriptor at the
same post-verification point. Only14 lines change; its942 asserts and229 raises
remain AST-identical. The temporary whole-file format change was removed; final
module AST equals the already-running formatted version. Original selectors/nodes
are unchanged. C54 only drops an expired direct Worker import entry; all49 asserts
and all test-function ASTs remain unchanged. No new default test discovery, catalog,
route, workflow, platform, matrix or merge condition is introduced.

The original candidate-wheel/native CLI/C54 consumers plus A69's fixed approval
probe passed148 with16 original live/host-runtime nodes deselected in297.21s.
The preceding235 and this148 are different selected nodes; the follow-up literal
multi-stage assertion reruns one existing node, not an additional scenario. No
full Coding/Harness/Hosting suite or excluded native journey is claimed.

Three production files pass mypy; changed source/probe and the minimal original
hook pass Ruff. Only new/changed small files are formatted; the large original
consumer keeps its existing layout. Documentation invariants, source dependency
freshness, change plan and diff checks are recorded separately. The plan selects
existing broad routes, not new gates; focused local validation is the stated scope.
Prior offline AI evidence remains, with no relevant AI source/input changes.

## Full Cost And Bounded Acceptance

| Production source | Before | After | Change |
|---|---:|---:|---:|
| Coding installed reader |295|151|−144|
| Coding install/review/repair |440|74|−366|
| Package Product custody, all types/bindings |0|688|+688|
| All affected production |735|913|**+178**|

Coding is117461 lines/430files; system644927 lines/1957sources. The other1954 old
sources have identical hashes. The full physical source frame counts Code wrappers,
profile, associated types, formatting and receiver costs. Coding drops510 lines;
this is complete responsibility migration with one existing write-loop reuse, not
system net reduction. Necessary moderate system growth is allowed by the Nov9 Goal
revision. It does not resolve the remaining102461 lines above15K.

Responsibility/reuse, runtime/failure and data/compatibility reviewers independently
read the direction, full external prototype and actual replacement/source evidence.
All three report no blocking defect within this slice; they read XML and did not
personally rerun pytest. The implementation owner accepts only the recorded scope.
The literal multi-stage assertion and minimal hook diff close the review's probe
precision/format follow-ups without changing Product code or old expectations.

KD003 immutable bytes import remains draft/not-started; KD011/A33 remain under their
original user-confirmation boundary. Other P1–P4 responsibilities and the full≤15K
Goal remain active. Native default-dark behavior, execution privileges, replacement
operations and wider cross-platform approval are not expanded by this delivery.

Final production SHA256:

- `src/loushang/coding/package_product_worker_installed_native.py`: `35c65f17e487c11f6ac450054deaf85fb4a88a8904bb979e04a929dee52c77da`.
- `src/loushang/coding/package_product_worker_native_install.py`: `6c1d9e1548fc5cc17f13df136de6353895abf70a846a3c8e98c430dab788b332`.
- `src/loushang/harness/package_product/_linux_worker_native_release.py`: `a511abd1f6d7100f5933af006c435802bc18a60a0d10cc01e7c7f76b98c710c2`.
