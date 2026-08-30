# Installed Continuity Mutation Lifecycle (Phase 5E Contract)

## Status and scope

- Document kind: implemented incremental contract.
- Foundation: the exact-plan transaction in
  [Phase 5D](continuity-mutation-phase5d-contract.md).
- Installed owner lifecycle: the sealed Provider generation from
  [Phase 5C](continuity-provider-phase5c-contract.md).
- Product durability: `loushang.harness.plugin_management.continuity_mutation`.
- Product binding: Coding explicitly injects a recovery-capable deletion
  authority when it elects to publish mutation-capable Providers.

Phase 5E exposes only `delete` for an installed Continuity Provider. It does not
create a generic Plugin write grant, filesystem capability, transcript handle,
or arbitrary mutation verb.

## End-to-end authority flow

Deletion begins only after the Product has obtained user confirmation and calls
the ordinary `ContinuityHub.delete(exact_target)` API. The Hub resolves the
admitted Provider but receives no journal or source callback.

```text
Product-confirmed Hub.delete(exact target + revision)
  -> sealed generation synchronously admits prepare
  -> Provider prepares one exact deletion candidate
  -> durable Product authority appends ACCEPTED(plan, source, attempt)
  -> generation registers the authorized mutation lease
  -> generation synchronously admits consume
  -> Provider idempotently commits the exact plan
  -> durable Product authority appends COMPLETED(receipt)
  -> Provider candidate releases its generation resources
  -> generation unregisters the terminal lease
  -> Hub returns applied=True or not_found=False
```

The Provider supplies Domain semantics. Harness supplies bounded orchestration.
Plugin Management supplies durable policy evidence. Coding supplies the Product
choice to enable this path. None of those roles can stand in for another.

## Portable Provider surface

An import Provider may additionally implement `prepare_delete(target)`. It may
declare exactly `("activate", "delete")` in the inert V2 declaration and must
request the `continuity.delete` authority within the Product authority ceiling;
V1 declarations normalize to activation-only. These actions enter candidate,
admission, selection, binding, and stable owner fingerprints. The executable
descriptor must equal—not merely fit within—the admitted action set. The
adapter also requires a Product `ContinuityDeletionAuthority` before it will
admit such a Provider. Activation-only Providers remain valid and do not
receive mutation authority.

`prepare_delete` returns only a `PreparedContinuityDeletion`. The Provider does
not receive the Product journal, local paths, approval records, Instance ledger,
Package ledger, or callbacks capable of deleting anything else. Commit receives
the Host-frozen `ContinuityDeletionPlanV1`, not a mutable service object.

## Durable Product journal

`PluginContinuityDeletionJournal` is an append-only, locked, durable JSONL
journal with exact V1 records. Every event repeats the recovery inputs and is
strictly validated:

- `accepted`: exact plan, exact redacted Plugin source, attempt, authorization;
- `completed`: same identity plus exact typed receipt;
- `cancelled`: same identity and no receipt.

Transitions are `none|cancelled -> accepted -> completed|cancelled`. Accept is
idempotent while an attempt is accepted or completed. A later confirmation may
re-open a cancelled exact plan as a new attempt with a new authorization ID.
Old evidence cannot settle the new attempt. Corrupt fields, versions, revision
gaps, duplicate authorization identities, and illegal transitions fail closed.

An exact operation-scoped filesystem lock is acquired before `accepted` is
read or appended and remains held through Product completion or cancellation.
It serializes duplicate Hub calls and concurrent recovering processes. A caller
that arrives after completion receives the exact durable receipt; Harness aborts
and closes its unused candidate without re-running Domain commit. Thus an
`applied` result cannot conflict with a later legitimate `not_found` replay.
Lock acquisition uses non-blocking OS attempts plus asynchronous bounded
backoff. A process-local single-flight admits at most one OS-lock contender per
exact operation; duplicate callers await its terminal future and replay the
durable receipt, or elect one new contender after cancellation. Waiters never
occupy the shared executor needed by the lock holder to durably settle and
release the operation.

The journal path is Product configuration. The canonical helper appends
`.continuity-deletions.jsonl` to the complete Instance-runtime basename beside
that journal, so suffixed and suffixless runtime paths cannot collide. It never
derives storage from CWD or Plugin input. Durable creation fsyncs the new file
and its parent directory entry; atomic partial-tail repair fsyncs the replacement
and parent directory before recovery continues.

## Crash recovery and generation succession

`publish_continuity_plugin_generation_with_mutations` is asynchronous because
recovery is a publication barrier. Before the Hub is observable it enumerates
every durable accepted operation, finds exactly one compatible Provider, asks
that Provider to recreate the exact candidate, and drives the 5D lease to
completion. Publication fails if any accepted operation remains.

Both synchronous activation-only publication and asynchronous mutation
publication synchronously reserve the sole generation publication slot before
their first possible await. A competing publisher cannot expose a Hub during
recovery. Failed publication permanently retires that generation for disposal;
a retry constructs a fresh sealed generation.

A process restart necessarily creates new generation and one-attempt execution
fingerprints. Recovery therefore requires equality of provider ID, Plugin ID,
contribution ID, Instance ID and revision, trust class and policy revision,
implementation identity and version, plus a stable owner-recovery fingerprint
covering the package/binding specification, declaration authority,
Product/owner policy, trust, authorities, and admitted actions. The exact
attempt owner-binding fingerprint remains in every record for audit, but may
differ when the same semantic selection is reconstructed after a crash. The authority
continues to authorize against the original accepted source record. A different
Plugin revision, trust decision, contribution, implementation, or Provider
cannot inherit the operation.

Journals written before the stable recovery field was introduced remain
readable. Because those records cannot prove semantic identity across process
attempts, recovery preserves their stricter legacy rule and requires the exact
owner-binding fingerprint; no identity is synthesized during migration.

The recreated candidate is compared with the accepted plan before
reauthorization. A mismatch aborts only that unpublished candidate and leaves the durable confirmed intent pending for a future compatible generation.

The Provider must reconcile the same plan fingerprint idempotently. If the
remote deletion happened before the crash, it returns the matching `applied` or
`not_found` receipt and Product completion becomes durable without a second
unrelated effect.

## Shutdown and revocation

Mutation prepare calls, authorized leases, pending preparation cleanup, consume,
abort, and source release all belong to the same `ContinuityPluginGenerationGate`
as activation.

- graceful shutdown poisons admission, closes the Hub, settles every lease and
  cleanup, then releases Instance families;
- security revocation durably accepts the revocation set, poisons admission,
  settles the same mutation inventory, enters `REVOKING`, then hands off Package
  cleanup and releases families;
- an unstarted accepted mutation is durably cancelled before source abort;
- once consume intent linearizes, shutdown can only drive commit, Product
  completion, and source release; it can never record cancellation;
- any retryable failure keeps the generation and its Instance/Package ownership
  pinned. In short: **Instance/Package ownership pinned** until quiesce reaches
  a fixed point. Quiesce failure prevents disposal.

Caller cancellation never cancels an owned durable transition. It propagates
only after the owned task reaches a stable success; a structural retryable
failure takes precedence.

## Coding Product binding

`bind_coding_plugin_continuity(..., deletion_authority=...)` is the explicit
Product switch. Without it, Coding uses the Phase 5C activation-only publication
path and a mutation-declaring Provider fails closed. With it, Coding invokes the
recovery publication barrier before retaining the Hub. The authority remains an
injected Harness port; Coding does not import the concrete journal module.

## Failure and diagnostic contract

Public failures use stable, redacted codes for Provider prepare/consume,
recovery, journal corruption/conflict, generation close, quiesce timeout, and
5D settlement. Plugin exceptions cannot surface credentials, paths, callback
representations, raw remote responses, or journal contents.

## Non-goals

Phase 5E does not implement rename, archive, synchronization, bulk mutation,
automatic deletion, background retry daemons, cross-process Provider execution,
or containment of malicious in-process code. Provider idempotency remains an
admission/trust obligation; the Product journal independently verifies every
authorization and receipt transition.

Phase 5E is complete only after architecture, security/lifecycle, and
product/test review, all findings are fixed, and the same reviewers return PASS
on the post-fix diff.
