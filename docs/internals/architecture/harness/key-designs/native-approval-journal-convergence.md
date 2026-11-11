# Native Approval Journal Convergence

- Authority: bounded design and implementation record under COD-RESP-GOAL-002.
- Design status: accepted for reversible implementation on 2026-11-09.
- Implementation status: implemented; bounded technical acceptance on 2026-11-09.
- Owner: existing Harness Worker history; Coding retains Product approval policy.
- Baseline: `89992a383`; local clean archmethod master
  `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`.

## Complete Program And Existing Reuse

The Linux native approval journal previously retained its value validation,
hash/wire methods, complete history decoder, Rooted binding, load and change
program in Coding. The existing Windows NativeApprovalRecords already owned
the same replay → conflict → CAS → absent → count capacity → decision creation
program under its separate native custody. Both operate on the same Code record
family; their physical append and strict-byte contracts differ.

Three empty-slots value mixins, the complete decoder and the Rooted program now
belong to `worker.history._native_approval`. Both existing platform programs call
one private pure decision selector returning `(record, is_replay)`. It accepts
already loaded records plus pure factory/error/late-limit bindings. It performs
no IO or admission and returns the original replay object. No new public DTO,
store, registry, approval authority or platform dispatcher is introduced.

The original `bind_private_journal`, RootedFile/IO, FunctionalJournalRecordCodec,
decode_jsonl, canonical_json_bytes and append_jsonl_record remain the sole
mechanisms. The original Windows Resource custody, ACL/lock and append engine
remain unchanged. The existing OptIn and Receipt programs are AST-identical.
The native record protocols are reused from the one common module rather than
copied or imported backward from a Windows implementation.

## Code Boundary And Exact Data Contract

Coding keeps all three actual frozen/slots dataclass field declarations, defaults,
own annotations, Code FQNs and persisted/pickle identities. Four public classmethods
have thin wrappers preserving their exact parameter and return annotations.
Explicit `super(CodeClass, cls)` avoids the replaced-class cell of slots dataclasses.
Generic approval binding keeps those original public input types valid under
mypy without narrowing an incompatible base signature or adding ignores.

Error, Journal constructor, Product/path properties and current() remain
AST-identical. Code retains owner admission and the original combined with:
GC enter → private parent/bind → write lock → Product currentness → load/change.
It does not assert authority before the original possible binding failure.
The journal remains one original object; no second manager receives Product IO.
The original Error type is obtained through a pure getter at binding time;
codec, decision factory and event limit are evaluated at their original call sites.

The exact dict shape/order, nested concrete Approval check, SHA/canonical bytes,
isinstance/subclass acceptance, frozen/slots and old pickle bytes are fixed.
Version checks remain `!= 1`: bool versions succeed with matching fingerprints;
float1.0 reaches the original canonical JSON rejection. Journal/generation and
expected-generation still reject bool through exact-int checks. No input
admission is strengthened under the refactor.

One original invalid-input asymmetry is preserved as explicit residual debt:
revoke rejects a real Approval value but does not require every other value to
be None. A duck with to_dict can be appended by the old change program; the next
read rejects it when decoding a concrete Approval under revoke. The fixed
observations include actual append then failed re-read. A future behavior fix
must be separate; this migration does not silently repair that schema hole.

## Platform And Failure Boundaries

- Linux retains SORTED_UNICODE_JSONL_FORMAT, including spaces, and its JSONL
  acceptance of blank lines/reordered mappings. Raw decode over4MiB is capacity
  before UTF8; Rooted oversized-file read is the original OSError. Full decoding
  precedes event capacity, which precedes scope/revision/operation/revoke folding.
- Windows retains nonempty/size/newline and exact canonical re-encoding checks.
  Its read decoder still uses the Linux module's event limit; the Windows event
  getter is a separate change limit. Neither source is merged into the other.
- Replay precedes CAS/absent/count capacity and returns the loaded object without
  creating or appending. Windows still rechecks visible root before replay return.
  Fresh Windows changes retain line-byte capacity, initialized marker, ACL append
  and visible-root recheck in the original order.
- Append failure is not retried or rolled back. A real partial Rooted append leaves
  the same partial bytes. Cleanup and GC-exit exceptions retain original cause/
  context and priority. Pure configured staticmethod lookup is not a contract for
  arbitrary effectful private descriptors or unrelated hotpatch reflection.

Native install/repair, source review and launch approval/currentness consumption
retain their original Code owners. This slice grants no native use, changes no
Worker/Package schema and opens no Windows execution route.

## Baseline And Actual Verification

All1,955 production-source hashes and complete original modules were saved
outside Product before edits. New observations use the original public classes
and functions, guarded by their real source paths/hashes. The durable fixture
contains101 observations, has no capture path and is compared with the saved
original JSON objects by independent reviewers.

The initial probe passed52 before two retry fixtures failed: this machine's
umask created group-writable seed files. Only the fixture now writes mode0600;
the original Product refusal is not changed. A diagnostic launcher initially
omitted a repository node, so project skip-host options were unregistered and
no tests ran. The corrected command restored normal conftest loading. These
results remain recorded. Stable97 observations then passed; six targeted cases
verified real float-version failure, late Error binding, lock/oversized read and
duck revoke re-read. They overlap and are not additive coverage.

One repeated original observation exposed a probe Duck repr with a random address.
Only that input's repr was made deterministic, and its corrected observation was
independently created under the still-original source. Previous observations
were not overwritten. The final fixture uses100 original stable objects plus
that one corrected original input. Valid success and expected error categories,
classified codes and replay object identity are asserted before comparison.
Old metadata/pickle/wire expectations never come from replacement code.

The first replacement run passed102 (101 observations plus one legacy parent-scope
node covering64 fixed scopes). Mypy then identified two narrowed public override
types; Generic binding corrected the types while retaining the public wrappers.
Typed DTO32 plus native parent scope passed33. Three accidentally included older
parent probes failed on stale fake-owner ports; the same failures were reproduced
on clean `89992a383` in a temporary validation worktree. Only fake-owner/type/
v2-hook locations were updated; their original asserts and fixture are unchanged.
All four parent nodes (256 observations) then passed. The clean, ancestor-contained
temporary worktree and branch were safely removed after verification.

Original Windows IO/read scopes passed256 before implementation. Final durable,
parent/Windows IO, native-reference checkpoint, release reader and existing
architecture selection passed490 with2 source-fact failures (32.94s). C54 only
adds the actual native approval consumer mapping; its assertion functions remain
unchanged. C55's three existing cleanup tokens follow the previously migrated
attempt-lifecycle owner; binder, activation/bridge and forbidden Code scans stay
on their original inputs. The same two failed nodes then passed2 (17.54s).
The original492 nodes have final passing evidence across those runs, not a claim
of a single clean492 rerun. No new assertions, gate, discovery route, trigger,
workflow, platform or required check was added.

Product authority is a controlled typed facade in the new Rooted scenarios;
Rooted files, locks, bytes and partial append are real. Windows custody/native
ports are controlled with real DTO/decoder/selection programs. These results do
not prove native Windows ACLs or process launch, full Product admission, every
fault interleaving or the full P1–P4 Goal. Existing safety selectors remain.

## Full Cost, Review And Delivery

| Production source | Before | After | Difference |
| --- | ---: | ---: | ---: |
| Coding native approval | 448 | 242 | −206 |
| Existing Windows record journals | 392 | 344 | −48 |
| Common native approval values/history/Rooted/selection, all bindings/types | 0 | 432 | +432 |
| Total | 840 | 1,018 | +178 |

Coding is117971 lines/430files; system644749 lines/1956sources. Only two old
production sources change; the other1953 old sources are byte-identical. All
wrapper, Generic, Protocol, getter, import and formatting costs are included.
Non-production evidence adds870 explicit-probe lines and3532 immutable-fixture
lines; original private-probe maintenance only follows its actual binding ports.
This is responsibility convergence plus one shared decision algorithm, not
system net reduction. Full P1–P4/≤15K remains active, still102971 lines over the
Coding bound. KD003 and KD011/A33 pending work are not adopted.

Three independent responsibility/reuse, runtime/failure and data/compatibility
design and actual-code reviews accepted the bounded implementation. They checked
real sources, immutable provenance, scopes and terminal evidence; they did not
rerun pytest. Responsibility also independently ran Ruff. The implementation
owner accepts this slice after the final terminals. Three source files pass
mypy; changed Python passes Ruff/format; documentation, dependency freshness,
check-plan generation and diff checks pass. Previous AI results are retained
because relevant AI sources/inputs have not changed.

Reviewed source SHA256:

- Code: `55b39813c7444df484f6401ba54e3adf3270b18584f7bef0ddba5f5b832009c8`.
- Windows: `6fd772117cc5a5d3043022e38e5e7a11777e79c3cd994340a1230c282d662456`.
- Common: `5b39800a107d48462ccf93502dd6ea9406d42f2fc96bfa5b704139fc32034aaf`.

Rollback the Code delegation and both Core substitutions together, with test
owner locations. Existing approval bytes need no migration or reset.
