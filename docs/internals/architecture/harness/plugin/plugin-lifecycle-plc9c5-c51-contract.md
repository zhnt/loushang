# PLC9C5 C5.1 Product Worker Receipt And Lifecycle Contract

## Status

- ID: `PLC9C5-C5.1`
- Parent: `PLC9C5-C5.0`
- Authority: normative implemented contract
- Design status: accepted
- Implementation status: implemented
- Activation status: closed; no Product or native composition exists
- Production default: Current; receipt omission constructs no Hosting owner
- Owner: `loushang.harness.worker`

## Scope

C5.1 implements the platform-independent evidence join and lifecycle aggregate
accepted by C5.0. It does not select a Product, discover a Session, construct
Hosting, capture native material, start a process, or publish a real Capability
generation. Its executable aggregate is deterministic and consumes injected
Product freshness and durable-state owners.

The implementation is
`src/loushang/harness/worker/product_activation.py`. The package facade adds
exactly three closed contracts:

- `ProductWorkerActivationPolicyV1`
- `ProductWorkerActivationReceiptV1`
- `ProductWorkerActivationAuthorityPort`

Cleanup settlement/debt records, admission leases, status/reason vocabulary,
the deterministic CAS store, cleanup-evidence authority, and
`ProductWorkerActivationCoordinator` are
implementation records and are not re-exported by `loushang.harness.worker`.
The coordinator remains internal until a later slice defines a stable typed
outcome/error and durable-owner seam; it never exposes private stores, leases,
records, exceptions, reasons, or broad mappings as public API. C5.1 adds no
native-profile port and does not create `_native_profile_bridge.py`.

## Authority-Free Policy And Receipt

`ProductWorkerActivationPolicyV1` is an immutable value binding:

| Concern | Exact value |
| --- | --- |
| Product | Product id, runtime id, scope id, and Session id |
| Session route | `new` or `selected`; selected has an opaque locator fingerprint and revision, while new has no locator |
| contribution | Plugin id/revision, contribution id, reservation, declaration, and Worker-configuration fingerprints |
| requiredness | declared and effective booleans; effective policy cannot weaken a declared required contribution |
| allowlist | sorted unique Product, contribution, and native-profile identifiers; enabled activation must occur in all three |
| owner | `current` or `hosting`, owner-selection generation, and `no_fallback`; enabled activation requires Hosting and no fallback |
| native policy | logical profile id, immutable catalog revision, allowed ids, and expected policy-closure fingerprint |
| freshness | Product-policy, selected-locator, owner-selection, and kill-switch generations |

All ids and revisions use bounded ASCII token grammars and all fingerprints are
lowercase SHA-256. No filesystem path, environment, secret, descriptor, handle,
PID, or native capture enters either value.

`ProductWorkerActivationReceiptV1` joins one validated policy to a positive
issue sequence and bounded nonce. Its strict JSON codec rejects missing,
additional, or mistyped fields and verifies the canonical fingerprint on
decode. A receipt can be constructed only for enabled Hosting policy. The
receipt is evidence, not authority: it contains no live owner or callable.

Expected and realized native policy closures share
`loushang.worker.native-policy-closure.v1`. Five length-prefixed UTF-8 fields
are encoded in order: catalog revision, profile id, payload digest,
containment-launcher digest, and containment-profile digest. Empty string is
the absent-field marker. Full H6 execution closure remains a separate C5.2
audit fingerprint and is never compared to this policy fingerprint.

## Product-Owned Freshness Port

`ProductWorkerActivationAuthorityPort` exposes three synchronous operations:

1. `serialized_admission()` returns the Product-owned serialization lease.
2. `current_witness(receipt)` returns exactly `(receipt fingerprint,
   Product-policy revision, locator revision, owner-selection generation,
   kill-switch generation)`.
3. `latch_kill_switch(expected_generation=...)` advances kill-switch
   generation while the same lease is held.

Port methods are bound from static class descriptors; properties, instance
shadowing, and dynamic `__getattr__` ports are rejected before use. Calls use
owner-identity shared callback domains for the authority, store, and evidence
owners. Every coordinator bound to the same external owner therefore observes
the same gate before entering either its lifecycle lock or the owner callback;
same-thread and cross-thread callback reentry fail closed immediately, including
a callback that spawns and joins a thread. Disjoint owners retain independent
domains and may execute concurrently; there is no unjustified process-global
serialization. Private constructor seams accept explicit weak-referenceable
domain tokens so multiple wrappers over one authority, store, or evidence
backend share exactly one reclaimable capability; wrappers over the same backend
must pass the same token. The global identity registry holds only a weak
reference, while live coordinators retain the capability. An unweak-referenceable
token is rejected instead of being leaked. Before any external callback, the
coordinator acquires all of its domains in stable identity order, atomically
marks the complete set active, and rolls back as one unit on conflict. Thus a
store callback also fences another coordinator that shares only its authority,
closing cross-owner dependency cycles without a process-global lock. These operations are
deliberately synchronous. An implementation may fetch
asynchronous evidence before the gate, but the admission value must be
synchronously revalidated against shared current state inside it. The
coordinator contains no `async` function and performs no `await` or user
callback between prepublication witness comparison and publication CAS.

## Serialized Lifecycle Aggregate

The coordinator accepts an injected CAS state owner with `load()` and
`compare_and_swap(expected_revision=..., document=...)`. Its strict document
contains only state revision/version, durable kill-switch state and its prior
and current generations, durable restart budget, exact attempt records, and the
deterministic fake publication map. Every attempt persists the exact policy
fingerprint, restart ordinal, and trusted cleanup-evidence authority id and
fingerprint pinned at coordinator construction. The default store is inert and in-memory. No
production construction root exists. A new coordinator over the same injected
store replays latch, attempt, publication, restart, settlement, and debt facts;
it rejects a constructor restart budget that differs from durable state.

All state writers call the same strict validator before the common CAS. The
closed phase transition table is:

| From | Allowed next phase |
| --- | --- |
| `registered` | `effect_started`, `settled` |
| `effect_started` | `published`, `retired`, `cleanup_debt` |
| `published` | `retired`, `cleanup_debt` |
| `retired` | `cleanup_debt`, `settled` |
| `cleanup_debt` | `settled` |
| `settled` | none; absorbing terminal state |

Repeated terminal, retirement, and exact settlement reports are idempotent.
Late debt cannot reopen settlement. At capacity the registry deterministically
compacts only absorbing settled records; if none exists it rejects a 4097th
durable attempt before its write, so it never persists a state its own validator
cannot read.

### Admission lease

`coordinator.admission(...)` returns a one-use internal context manager. Entry
acquires the Product gate, reloads durable state, rejects a latched kill switch,
validates policy/receipt/current witness, and durably registers exact `(receipt
fingerprint, attempt id, owner generation)` as a sticky Hosting attempt. The
gate stays held until `begin_effect()` or `settle_without_effect()` commits,
then is released exactly once before that method returns; `__exit__` handles
only an unfinished lease. Normal exit, exceptional exit before effect, and
explicit no-effect settlement all join the absorbing no-effect settlement.
Once the effect edge is committed, an exception or commit-before-return fault
cannot erase the conservative active attempt or its cleanup obligation.
The Product gate context has an explicit idempotent-release contract. Its exit
capability remains owned by the lease until `__exit__` succeeds, so both a
pre-release failure and an ambiguous post-release failure can be retried
without double release.

Every serialized context's static exit capability is registered in the shared
authority-domain pending authority-release registry before `__enter__` is called.
The Product port therefore requires idempotent exit after ambiguous enter as well
as pre-release and post-release ambiguity. Publication, retirement, latch, and
admission remove the capability only after exit reports success. This includes
failures after their durable CAS and admission validation/CAS failures before a
lease is returned. An enter that acquires then raises is immediately offered its
registered exit; failed cleanup remains debt. `retry_pending_releases()` checks
all callback domains before touching release or state locks and processes shared
debt. Release uses a condition and single-flight marker and never holds the
release lock while invoking external `__exit__`. A competing drain that observes
`releasing` fails fast rather than waiting, because it cannot distinguish a
normal peer from a thread derived by the active exit callback. A callback that
spawns and joins either same- or cross-Coordinator retry is therefore rejected
before that lock. Every coordinator sharing the
authority sees the same registry, drains it before a new gate, and fails closed
if exit still cannot be confirmed.

Each release entry follows the closed phases `reserved`, `held`, `release_due`,
`releasing`, and `settled`. Registration before enter creates only `reserved`;
successful acquisition atomically makes it `held`. Neither phase is drainable.
Enter ambiguity or an operation's explicit/final release first marks
`release_due`; only that phase may become single-flight `releasing`. Successful
exit reaches `settled` and is removed, while a release fault returns to
`release_due`. Retry snapshots both `release_due` and `releasing`: the former
may be claimed, while the latter immediately returns the closed reentrant/busy
failure and must be retried later. If the releaser faults, its entry returns to
`release_due` and one later explicit caller completes it. Concurrent losers
never wait on or take over a live `releasing` entry.
`reserved` and `held` are never enumerated. A peer can therefore ignore
another live reservation/holder and queue on the underlying Product gate, but
can never invoke its exit. Gate `__enter__` is a callback-free acquisition
primitive that may block; it is not marked callback-active, because doing so
would prevent the current holder from reaching exit.

### Atomic publication, retirement, and rollback

`publish(...)` reacquires the same Product gate; reloads state; rejects the
latch; synchronously verifies the exact witness, catalog/profile identity, and
same-domain expected/realized policy closure; verifies `effect_started`; and
commits the fake publication CAS. There is no await or user callback in this
sequence. An occupied domain slot is fenced.

`retire_exact(...)` removes only a matching receipt/attempt/owner-generation
publication. A stale attempt cannot retire a successor. Retirement never
selects or starts Current.

`latch_kill_switch(...)` holds the same Product gate while it first durably
writes `pending` with prior and next generation, idempotently stales Product
authority, durably writes `completed`, and enumerates the complete active
registry. A failure or crash after the pending CAS stays fail-closed; retry with
the prior expected generation repeats the authority latch and completes rather
than reopening. Admission/publication either
commits before the latch and is enumerated or observes the latch and has no
visibility. Existing attempts remain sticky to Hosting; there is no
same-attempt fallback.

### Cleanup and restart

`WorkerCleanupSettlementV1` is an internal strict durable join over receipt,
attempt, owner generation, host/boot identity, protocol terminal, exact domain
retirement, and complete-tree settlement. All three exit facts must be true.

`WorkerCleanupDebtV1` binds the same identity to closed reasons
`same_boot_unknown_tree` or `settlement_incomplete`. Same-boot debt blocks
restart. Settlement and changed-boot absence require an owner-minted opaque
witness verified by the statically bound construction-time evidence authority
against the exact
receipt, attempt, owner generation, host, prior boot, and (when applicable)
current boot. Record APIs accept only the witness and cannot substitute an
authority per call; an always-true counterfeit with a different trusted
identity or fingerprint is rejected. A string, dataclass, default, or forged
object cannot self-prove.
A trusted changed-boot witness can settle old local-tree absence only after
terminal and retirement are durable. `claim_restart(...)` consumes a bounded
ordinal by CAS only after terminal, retirement, settlement, and absence of debt
join. `claim_restart is budget accounting, not activation authority`: it cannot
select an owner, mint a receipt, or authorize activation. Protocol terminal or
PID absence alone is never settlement.

A registration CAS that commits before reporting an error is settled as
same-boot no-effect while its admission gate remains held. If the store also
faults during that conservative settlement, reconstruction exposes only an
exact `registered` record. `recover_registered_no_effect(...)` can move that
same key only to no-effect settlement after the pinned evidence authority
verifies lease-owner expiry across a changed boot; it is idempotent and can
never start or overwrite an effect. Settled-record compaction then prevents the
orphan from permanently consuming the capacity bound.

## Closed Status And Redaction

Status has the closed reasons `admitted`, `disabled_by_policy`,
`policy_required_unavailable`, `invalid_receipt`, `foreign_receipt`,
`stale_authority`, `kill_switch_latched`, `published`, `publication_fenced`,
`retired`, `cleanup_settled`, `cleanup_debt`, `restart_ready`,
`restart_exhausted`, `capacity_exhausted`, `reentrant_call`, and
`optional_degraded`.

Serialization contains only reason, requiredness, receipt fingerprint, attempt
id, owner generation, and version. Rejections never serialize exception text.
Bounded token grammars exclude path separators, query strings, environment
assignments, and arbitrary text, so path/environment/secret sentinels cannot be
reflected through policy, debt, or status.

## Required Evidence

The authoritative manifest is
`plugin-lifecycle-plc9c5-evidence-manifest.json`. C5.1 marks only
`PLC9C5-C5.1-CONTRACT` implemented; later reports remain planned. Its required
JUnit path is `.artifacts/plc9c5-c51-contract.xml` and its exact case ids are:

`C51-CURRENT-REQUIREDNESS`, `C51-INVALID-RECEIPT`, `C51-STALE-RECEIPT`,
`C51-FOREIGN-RECEIPT`, `C51-POLICY-CLOSURE-CODEC`,
`C51-PREACQUIRE-FRESHNESS`, `C51-PREPUBLISH-ATOMIC-CAS`,
`C51-KILLSWITCH-PUBLISH-BLOCKED`, `C51-RECEIPT-ATTEMPT-CLOSURE`,
`C51-EXACT-RETIRE-CAS`, `C51-KILLSWITCH-ADMISSION-BLOCKED`,
`C51-RESTART-LATCH`, `C51-CLEANUP-SETTLED`, `C51-CLEANUP-DEBT`,
`C51-STICKY-OWNER`, `C51-NO-FALLBACK`, `C51-REQUIRED-SUCCESS`,
`C51-OPTIONAL-DEGRADED`, `C51-PUBLICATION-FENCE`, and
`C51-SENTINEL-REDACTION`; plus the 45 mandatory hardening cases declared in
`PLC9C5_C51_HARDENING_CASES`. They cover the monotonic table, durable policy
and budget, capacity, durable latch retry, gate release, all four
no-effect/effect exit paths, commit-before-return, dual-coordinator CAS, both
true threaded publication/latch races, dynamic/reentrant and faulting ports,
counterfeit evidence, registered recovery, both release-fault positions, and
cross-thread authority/store/evidence callback reentry, serialized-release debt
across completed and failed admissions, single-flight fail-fast drain, shared-owner
callback domains, disjoint-owner parallelism, shared release debt, weak domain
capabilities, enter ambiguity, callback-safe drain, and retirement/latch release
faults, non-drainable reserved/held gate races, releasing fail-fast, and later
fault takeover. The manifest contains the exact 65 case ids; deleting any hardening row fails architecture and
evidence gates.

The hardening ids are `C51-MONOTONIC-SETTLEMENT`,
`C51-DURABLE-POLICY-BUDGET`, `C51-CAPACITY-PREWRITE`,
`C51-KILLSWITCH-DURABLE-RETRY`, `C51-GATE-RELEASE-IMMEDIATE`,
`C51-NOEFFECT-NORMAL`, `C51-NOEFFECT-EXCEPTION`,
`C51-NOEFFECT-EXPLICIT`, `C51-EFFECT-EXCEPTION`,
`C51-COMMIT-BEFORE-RETURN`, `C51-DUAL-COORDINATOR-CAS`,
`C51-PUBLISH-THEN-KILL-RACE`, `C51-KILL-THEN-PUBLISH-RACE`,
`C51-DYNAMIC-PORT-REENTRY`, `C51-PORT-FAULTS`,
`C51-COUNTERFEIT-EVIDENCE`, `C51-REGISTERED-RECOVERY`,
`C51-GATE-RELEASE-PREFAULT`, `C51-GATE-RELEASE-POSTFAULT`,
`C51-CROSS-THREAD-AUTHORITY-REENTRY`,
`C51-CROSS-THREAD-STORE-REENTRY`, and
`C51-CROSS-THREAD-EVIDENCE-REENTRY`, `C51-RELEASE-DEBT-PUBLISH`,
`C51-RELEASE-DEBT-ADMISSION-VALIDATION`,
`C51-RELEASE-DEBT-ADMISSION-CAS`, `C51-RELEASE-DEBT-DRAIN-JOIN`,
`C51-SHARED-AUTHORITY-DOMAIN`, `C51-SHARED-STORE-DOMAIN`,
`C51-SHARED-EVIDENCE-DOMAIN`, `C51-DISJOINT-OWNER-PARALLEL`,
`C51-SHARED-RELEASE-DEBT-DRAIN`, `C51-CROSS-OWNER-CALLBACK-FENCE`,
`C51-SHARED-DOMAIN-WRAPPERS`, `C51-DOMAIN-TOKEN-WEAKREF`,
`C51-ENTER-AMBIGUITY-CLEANUP`, `C51-EXIT-CALLBACK-DRAIN-REENTRY`,
`C51-RETIRE-RELEASE-PREFAULT`, `C51-RETIRE-RELEASE-POSTFAULT`,
`C51-LATCH-RELEASE-PREFAULT`, and `C51-LATCH-RELEASE-POSTFAULT`.
The final live-phase cases are `C51-HELD-GATE-NO-EARLY-RELEASE` and
`C51-RESERVED-GATE-NO-DRAIN`; release completion is fixed by
`C51-RELEASING-RETRY-FAILFAST`, `C51-RELEASE-FAULT-RETRY-TAKEOVER`, and
`C51-SHARED-EXIT-CALLBACK-RETRY-REJECT`.

The generic JUnit verifier rejects empty, skipped, or failing reports. The C5
manifest verifier additionally checks implemented status, exact report path,
minimum count, exact case set, duplicates, and substitutions. It recomputes
suite counts from direct testcase children and rejects child failures, errors,
or skips, lying or negative aggregates, missing counts, and nested suites.
Harness CI uploads the retained required report.

## Retained Fences

C5.1 retains every C5.0 fence except the named receipt/coordinator/cleanup
absences: no native bridge or private Hosting import, no native-profile port,
no Product/Coding/AppHost/presenter/CLI composition, no production allowlist or
issuer/state-store route, no unsupported-platform or same-attempt fallback, no
change to default Current or its retained launch owner, and no author SDK or
`remote_service` runtime owner. Passing C5.1 authorizes only a separately
reviewed C5.2 Linux-native implementation slice.
