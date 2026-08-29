# Continuity Mutation Foundation (Phase 5D Contract)

## Status and authority

- Document kind: implemented incremental contract.
- Scope: portable deletion proposal records and Product-authorized transaction
  mechanics in `loushang.harness.continuity.mutation`.
- Continuity Provider: owns discovery and an idempotent mutation candidate for
  its own opaque Domain target.
- Product: owns policy authorization, durable acceptance/completion/cancel
  evidence, transaction orchestration, and user-facing confirmation.
- Harness: owns exact record validation, ownership transfer, cancellation-safe
  settlement, and retry mechanics. It does not approve or execute a Domain
  deletion by itself.

This phase builds on the
[Phase 5B portable import foundation](continuity-provider-phase5b-contract.md)
and the
[Phase 5C installed Provider lifecycle](continuity-provider-phase5c-contract.md).
It does not amend the existing Product/OEM `ContinuityDeletionProvider` path.

## Decision

A non-Product Continuity Provider cannot receive a transcript store, filesystem
root, deletion callback, or generic write capability. It may prepare one typed
proposal for one exact Provider-owned target revision. The proposal becomes
executable only after a Product authority accepts the exact plan and source
provenance and returns opaque same-authority evidence.

The control flow is:

```text
Provider prepares exact, unpublished deletion candidate
  -> Harness validates candidate target == plan target
  -> Harness validates source provider_id owns that target
  -> Product authority durably accepts exact plan + source fingerprints
  -> Harness exposes one authorized deletion lease
  -> consume linearizes before its first await
  -> Provider idempotently commits its own Domain deletion
  -> Harness validates the exact typed receipt
  -> Product authority durably records completion
  -> lease reports success
```

The Product is the transaction coordinator. The Provider remains the only code
that understands how its own remote or private Domain object is mutated. These
roles do not imply that Harness can truthfully verify a remote Provider's claim;
the Product's trust/admission policy remains responsible for allowing that
Provider in the first place.

## Portable records

`ContinuityDeletionPlanV1` contains only:

- `mutationKind = "delete"`;
- `planVersion = 1`; and
- one `ContinuityTarget` whose `revision` is mandatory.

Provider ID, opaque ID, and revision are each bounded. The plan fingerprint is
Host-derived from canonical JSON bytes; a Provider cannot inject a callback,
path, secret, policy decision, or free-form operation identity into the plan.
Deleting the same provider/opaque-id/revision therefore has the same mutation
identity and must be idempotent. Direct typed construction and wire decoding
share the same exact-target, integer-version, length, and valid-UTF-8 checks, so
every constructible record round-trips through its V1 codec.

`ContinuityDeletionReceiptV1` binds the exact target and plan fingerprint and
has only `applied` or `not_found` disposition. `not_found` is successful
idempotent convergence, not proof that an unrelated target was removed.
Unknown versions and malformed fingerprints fail closed.
Both records expose strict exact-field `to_dict`/`from_dict` codecs so the next
phase can persist and recover the same portable schema without an adapter-only
shadow representation.

## Authorization boundary

`ContinuityDeletionAuthority` is a Product-owned port with three operations:

1. `authorize_delete(plan, source)` returns an opaque
   `ContinuityDeletionAuthorization` only after the Product's durable policy
   decision accepts the exact plan and `ContinuityProviderSourceDescriptor`;
2. `complete_delete(authorization, receipt)` durably settles the exact result;
3. `cancel_delete(authorization)` durably prevents an accepted-but-unstarted
   proposal from later committing.

Authorization values have no public constructor. They bind authorization ID,
plan fingerprint, source fingerprint, and the issuing authority object. A
value from another authority, plan, source, generation, or process is rejected.
The Phase 5D module defines this port and validates its evidence; it does not
pretend an in-memory implementation is durable. Phase 5E must bind the installed
Plugin path to a concrete Product journal and recovery adapter.

## Candidate and lease lifecycle

`PreparedContinuityDeletion` is source-owned and unpublished. Its
`commit(exact_plan)` is required to be idempotent for that plan; `abort()`
discards an uncommitted proposal, while `close()` releases its generation and
resource ownership after either completion or abort. All three operations are
idempotent. Successful Product settlement and candidate release are separate
retry checkpoints, so a release failure cannot repeat either Domain commit or
Product completion. The Product never receives an unrestricted Provider object
through the authority port.

`prepare_authorized_continuity_deletion` transfers a valid candidate into one
owner transaction. Authorization failure, cancellation, mismatched evidence,
or mismatched source/target triggers reverse cleanup. If cleanup fails, an
opaque `ContinuityMutationPendingCleanup` remains retryable; the caller cannot
prepare a peer transaction by pretending the candidate was released.

Both `AuthorizedContinuityDeletionLease` and pending-cleanup handles are
owner-constructed: callers can observe their narrow methods but cannot assemble
or replace the candidate, authority, authorization, plan, or source bindings.
The lease snapshots the exact plan and target before authorization, validates
that the candidate did not change during authorization, and passes only that
snapshot back to source commit.

`AuthorizedContinuityDeletionLease` records consume or abort intent before its
first await:

- abort first: Product cancellation is recorded before source cleanup, and a
  later consume is rejected;
- consume first: abort joins the exact commit/completion transaction and never
  races a cancellation against it;
- consume intent linearizes, then source commit fails or returns malformed
  evidence: the transaction remains accepted-but-unsettled and retries the
  idempotent exact-plan commit; `abort()` and `close()` can no longer record
  cancellation or call source abort;
- source commit succeeds but Product completion fails: the exact validated
  receipt is retained, so retry repeats completion without repeating source
  commit;
- Product completion succeeds but candidate release fails: retry repeats only
  `close()`, leaving commit and completion unchanged;
- caller cancellation during commit: the owned task finishes before
  cancellation propagates, and a later consume returns the same settled
  receipt;
- successful consume is idempotent, because mutation callers must tolerate a
  lost response without inventing a second Domain effect.

The in-process receipt cache is not crash recovery. A concrete authority must
retain accepted-but-unsettled operations, while a concrete Provider must make
the plan fingerprint a stable idempotency key or supply equivalent reconciliation.
That production binding is a Phase 5E exit requirement.

## Existing Product behavior

The current Product/OEM `ContinuityDeletionProvider.delete()` contract remains
unchanged. Coding's canonical Session deletion stays Product-owned and continues
to publish its Conversation tombstone before unlinking transcript data. Phase
5D does not route that trusted local operation through a Plugin proposal merely
to make all deletes look identical.

The common Hub does not yet expose installed Plugin deletion through this
foundation. Until Phase 5E binds an admitted Provider, Product authority, and
generation gate, Plugin Provider descriptors remain activation-only.

## Failure contract

The foundation distinguishes at least:

- invalid or revisionless plan;
- candidate target/plan mismatch;
- source/target ownership mismatch;
- foreign or mismatched authorization evidence;
- foreign or malformed receipt;
- closed or aborted lease;
- retryable source commit or Product completion failure; and
- retryable preparation/cancellation cleanup.

Diagnostics contain structural codes and fingerprints, never target payloads,
credentials, raw remote responses, callbacks, approval records, or local paths.
Provider and authority exception text is not propagated through the public
boundary. When caller cancellation races an owned task failure, the structural
settlement failure takes precedence because it carries required retry state;
cancellation propagates only after the owned operation settles successfully.

## Explicit non-goals

Phase 5D does not add:

- installed Plugin mutation registration or execution;
- a Plugin Runtime Profile grant;
- direct transcript/blob/filesystem mutation;
- rename, archive, bulk deletion, synchronization, or arbitrary verbs;
- mutation UI, automatic confirmation, or background retry daemons;
- a generic write-capability/service-locator API;
- cross-process Provider execution or containment claims; or
- hot replacement of the sealed Continuity generation.

## Phase 5E handoff

Phase 5E may expose `delete` for an installed Continuity Provider only when it:

1. starts from the finalized 5C selection and exact generation provenance;
2. uses a concrete durable Product deletion authority;
3. wraps the source candidate in this Phase 5D transaction without exposing a
   raw callback;
4. generation-gates prepare, consume, abort, and pending cleanup;
5. prevents security revocation or shutdown from releasing Instance/package
   leases while a mutation remains unsettled;
6. recovers accepted-but-unsettled operations with the same plan identity; and
7. proves end-to-end Product confirmation, success, cancellation, crash retry,
   graceful shutdown, and security revocation behavior.

The complete Phase 5D requires architecture, security/lifecycle, and
product/test review followed by the same reviewers' post-fix re-review.
