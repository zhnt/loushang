# ARD-005: Commit Resume Binding With The First User Message

## Status

- ID: `ARD-005`
- Scope: Loushang cross-scope Coding and Harness transcript/session owners
- Parent: Loushang architecture
- Authority: normative — accepted Resume continuation and commit boundary
- Design status: accepted
- Implementation status: partial — the original AgentEventRouter can merge
  optional Product message metadata with resource evidence before one append.
  The existing TranscriptCommitter can commit a prebuilt durable UserMessage
  with a fixed record ID, reject conflicting identity or branch, and reconcile
  a lost acknowledgement after an authoritative MemoryStore reload; a JSONL
  partial tail leaves absence unproven. Coding has a bounded internal
  RuntimeBinding v1 metadata codec and pure single-record builder. Selected
  ancestry projection preserves an epoch through compaction, excludes bindings
  copied from a source Session fork, and treats unknown later schema as
  unavailable. Coding also has an internal bounded activation-attempt v1 record
  builder and selected-path validator. The Transcript owner can commit a
  fixed-ID extension fact and reconcile it after an authoritative reload; a
  Coding test helper uses that path for the candidate intent. Selected-path
  projection now marks an unbound intent pending or an unknown version
  unavailable while keeping history viewable. Ordinary Coding bootstrap,
  Product factory selection, model preparation, and message writes reject an
  unresolved current-Session intent before preparing further runtime effects.
  The original Transcript committer now exposes a read-only exact-record
  lookup through the Product operation fence. It reloads the authority store
  and compares frozen payload, complete metadata, and selected branch, with
  committed, not_committed_verified, unknown, and conflict results. Complete
  evidence and an unchanged target are required to prove absence; this is
  not yet the full Hosted logical-ID/model-outcome flow. SessionManager now has
  an internal initial-intent commit route that validates selected Session/leaf/
  ancestry, detaches the canonical record, and closes the local Runtime gate
  before awaiting the original commit owner. Failure, lost acknowledgement and
  cancellation keep the gate closed. This route requires live owner admission
  and is not yet called by ordinary Product bootstrap. Current activation admission,
  complete recovery, and runtime wiring are not implemented
- Owner: Loushang architecture, Coding continuity, and Harness transcript
- Tracking: [Issue #696](https://github.com/zhnt/loushang/issues/696)

## Decision Question And Drivers

How can a resumed Session record the environment used for its first new user
input without allowing a crash, lost acknowledgement, retry, or old reader to
create an unbound or duplicate input?

The [R2.1 design](../../../plans/2026-10-12-resume-compatibility-and-activation-design.md)
requires the first writable current path to preserve `agent.message` and
`UserMessage`, co-commit RuntimeBinding and resource evidence metadata, and
reconcile an unknown result using durable facts. RES-NFR-03 requires at most
one durable visible record for the same input. RES-FR-04 additionally requires
Embedded and Hosted to share that logical fact. This decision concerns the
durable record and version boundary; it does not grant execution authority.

Current `harness/session/agent_event_router.py` prepares request evidence and
appends the message on `message_end`. `harness/transcript/unit_of_work.py`
uses the record ID as the Store operation ID and can report unknown commit
outcomes. Its batch fallback commits records one by one. These facts establish
useful owners but do not prove atomic visibility of a new multi-record
transaction or durable retry across every backend.

## Options And Comparison

| Option | Fit against drivers | Costs and risks |
| --- | --- | --- |
| Append a Binding record before or after the normal message | Separates schemas | A crash can expose only one fact, and the normal message path can append a second input. |
| Add a new message envelope or rely on batch append | Could package more fields | Old readers may lose message semantics; per-record fallback does not supply group atomicity. |
| Keep the existing message kind and co-commit bounded metadata | Preserves the ordinary message path and one-record visibility | Requires stable identity, metadata merge, partial-tail and old-version tests, plus a separate effect settlement protocol. |

## Decision And Exact Scope

Select the third option for the first user-message-triggered writable current
Resume. The existing message commit owner constructs one `agent.message`
record carrying the original `UserMessage`, its existing resource evidence,
and a versioned, bounded Coding-owned RuntimeBinding metadata key. Metadata
keys are merged before commit; conflicts fail closed. The same fixed canonical
record ID is used by the Store operation and subsequent response path. No
preliminary Binding append and no second normal message append are permitted.

RuntimeBinding records an activation attempt ID, stable logical input ID,
target ancestry, origin evidence, planned and actual environment fingerprints,
payload digest, and redacted differences. It contains no Credential, Grant,
live Plan, Worker lease, or whole resource graph. It is an historical fact,
not proof that a Runtime was published or that present authorization persists.
Unknown metadata schema is inert and cannot enter model text. Hosted and HTML
projections use an explicit safe allowlist.

The logical input ID is bound to actor, Product, Session, branch, original
leaf, and frozen payload plus metadata digest. Admission after an uncertain
commit first resolves the fixed record and operation ID from the authority
store, including selected ancestry outside current model context. `not
retained`, an obsolete service instance, or an incomplete scan remains
`unknown`, never verified absent. A committed input is never appended again.
Changing the payload after admission requires a confirmed pre-commit cancel
and a new logical ID.

The record's atomic scope is one fully validated physical message. A partial
JSONL tail, fsync/ack uncertainty, and file replacement still need explicit
recovery evidence. Blob staging occurs before the message references an image;
unknown commit protects the Blob from orphan collection until resolved.
Compaction, branch, fork, export, and request-evidence projection retain the
binding as a selected-path historical fact. A cross-Session fork retains its
origin evidence, but establishes neither target activation nor target input
deduplication.

Activation attempt, plugin/Worker effect settlement, message commit, Runtime
publication, and model transport are distinct boundaries. `use FAILED` does
not prove an external effect never occurred. Publish failure after commit
shows “message saved, response not started.” A model attempt with uncertain
external outcome is marked unknown and is not automatically replayed. The
first writable slice does not cover automatic Continue, compaction, or other
effectful commands without a UserMessage.

The original Package Product epoch owners expose a read-only observation of
their current native fence. They revalidate the existing pinned control and
child roots and load the journal with partial-tail repair disabled. Observation
does not issue a lease or invoke a Product factory. Coding's original
application selection can hash this observation for an already selected
canonical workspace; an unselected or closing selection is unavailable.
The bounded digest is an epoch input dependency. Subject, Policy, content
closure, activation/effect settlement and default Resume wiring remain
separate requirements; the digest cannot satisfy those checks.

The original Coding Root's Resume admission now also compares that selected
native epoch with the attempt, before Writer acquisition and on the existing
commit, delivery and model admission path. A missing/fenced selection is
unavailable; an unequal digest requires explicit recovery. The Root does not
create a Product owner to satisfy the check. First Resume startup must still
obtain its owner through the production application route. Caller admission
and effect settlement remain independently required.

The original Product selection also exposes a formal `prepare_resume_epoch`
entry. It uses the same locked workspace selection/recovery implementation
as ordinary `factory_for_session`, with caller admission checked before and
after selection. It can initialize/recover durable Product state, so it is
an activation operation and must not be invoked by history/background reads.
It returns the original native epoch dependency without a temporary Session
or runtime lease. A post-selection admission failure leaves any selected
owner in the original selection's close lifecycle. This entry does not prove
actor/Policy authority, effect settlement or default CLI/Hosted activation;
those production inputs and routes still require implementation.

Formal epoch preparation now propagates its current admission check through
the original fresh cutover/builtin bootstrap and existing-epoch reopening
paths. Product state checks it before state creation and backup publication;
the original management service checks it before coordination, after acquiring
the GC gate, before journal replay and before each pending operation. This is
a separate `require_current_admission` input. Existing `before_recovery` and
`before_replay` checks retain their existing-store/lock-creation policy; they
cannot be reused as permission to initialize fresh state. Formal checks must
be synchronous and return None. Refusal preserves already accepted durable
effects for original-owner recovery; it does not turn them into absence or a
retry grant. Native activation/Worker effect settlement remains a separate
requirement.

The original Product selection serializes formal preparation and ordinary
factory selection through one reentrant lock. Admission callbacks may observe
the original selected epoch; an unselected epoch remains unavailable. The
original selection records a private in-progress flag to refuse nested factory
selection, formal preparation and disposal before those operations change any
owner. Callback fencing remains permitted and is checked before preparation
continues. The first admission check, selection and final epoch observation
share that same scope, with the flag released on every exit. This adds no
authority owner, lease or effect settlement fact.

Resume candidate validation now independently checks the original published
Capability components. The original Session retains the exact prepared
components and graph generation used at publication; checks refuse a missing
consumer, retired/changed graph, replaced component references or an unsupported
component check. The in-process Component Host verifies its original committed
activation reservation, current authorities and import realm, and fences this
live-use check before awaiting disposal, including failed disposal. The native
Worker Provider checks its original visible facet/admitted attempt/owner through
the original facet publication validator without dispatching a query. That
formal validator may issue the original owner's ephemeral facet grant; it is
not called by history or background planning. Caller current admission brackets
these formal checks, including revalidation after the settlement callback;
denied admission cannot enter native use coordination/grant validation. The
original journal's formal coordination/recovery policy is retained. The local
retirement fence is not a durable external effect settlement record. These checks run independently
of external admission/settlement callbacks before input commit and along the
publication/model path. They establish current activation ownership only.
Recovered FAILED uses, lost journals and retirement debts are not completion
proof. Durable external effect settlement, cross-attempt recovery correlation
and the default coordinator remain required.

### Candidate v1 attempt contract for owner review

The proposed `coding.activation-attempt/v1` intent uses one `extension.data`
record. Its fixed record ID equals `attemptId`; its parent is the selected
`originalLeafId`. The exact, bounded data object contains `version: 1`,
`attemptId`, `requestId`, `sessionId`, `originalLeafId`, `ancestryDigest`,
`planFingerprint`, `epochFingerprint`, `subjectDigest`, and sorted redacted
`effectClasses`. The proposed byte ceiling is 4096 bytes. An unknown version
is inert for historical reading and unavailable for writable continuation.

`requestId` is the stable logical input ID. Before the first input is staged,
the continuation owner checks the intent against the selected ancestry and
current Session. The Binding on the single user record must then match the
intent's attempt, request, Plan, epoch, subject, original leaf, and ancestry.
Its actual record parent is the intent record ID. The record contains no
approval grant, mutable lease, resource secret, or assertion that effects
settled. The Transcript owner has a fixed-ID extension commit and same-record
reload reconciliation path. Coding still lacks the admitted activation owner
that would call it and correlate it with effect settlement.

The selected-path read projection reports an unbound current-Session intent as
pending. A matching first UserMessage clears that pending input fact only when
its Binding and parent record agree with the intent. Unknown attempt versions
or malformed known facts keep historical viewing available but make the pure
Plan unavailable. Clearing the pending input fact does not settle plugin,
Worker, Tool, or model effects.

The minimum writer protocol capability is `coding.resume-continuation/v1`.
Its first shipping build remains a release deliverable. A build advertising
this capability must implement this schema, unknown-version behavior, record
identity, commit owner, recovery states, and continuation gate together.
Historical reader/export support does not imply this writer capability.

## Version And Rollback Boundary

The first release must identify a concrete minimum writer build or protocol
capability that understands RuntimeBinding and its continuation gate. Existing
`pyproject.toml` uses `0.1.0`, so that package version alone is insufficient
to name the boundary. The protocol capability is fixed above; the concrete
first shipping build and tested N/N+1 artifacts must be recorded before release.

A 2026-10-12 local probe used `main` at `e0878dfa` as the old reader/writer
and an `agent.message` carrying a small unknown `coding.runtimeBindingV1`
metadata object. The old reader decoded the `UserMessage` and an export
preserved the unknown metadata. A copy opened by the old writer accepted a
new `UserMessage` without that metadata. This establishes why old-writer
rollback cannot be treated as safe. It does **not** verify the final Binding
schema, released N/N+1 artifacts, compaction, Blob references, or crash
recovery; those remain release gates.

A second local probe on 2026-10-12 used `main` at `29ff1c45` to read and export
a UserMessage with the current internal RuntimeBinding v1 shape and Resource
evidence metadata. The old reader displayed the message and retained both
metadata keys in the export; the new decoder validated that exported binding.
This is local source-version evidence only, not an N/N+1 released-artifact gate.

N and N+1 reader/export tests must demonstrate that a known `agent.message`
still displays or exports appropriately with the new metadata. An old writer
may ignore it; therefore this proposal does not claim safe downgrade writing.
The product must document unsupported rollback write recovery unless a tested
old-binary-readable fence is separately accepted. A reader/export claim is
not a writer claim.

## Consequences, Validation, And Acceptance

Coding owns the Binding schema and continuation decision. The existing
Harness transcript message owner owns record creation, commit outcome, Blob
reference safety, selected ancestry, and export. Effect owners retain their
own durable effect/settlement journals. AppService consumes only a narrow
stable-ID lookup and admission result; it does not become a transcript writer.

Required evidence includes deterministic failure injection at intent,
effect, Blob, commit, publish, and model-start boundaries; JSONL partial-tail
and fsync/ack loss; fixed-ID restart reconciliation; two Writers; selected
ancestry and compaction; fork origin; old reader/export; and explicit old
writer behavior. The [R2.1 review](../../../plans/2026-10-12-resume-compatibility-and-activation-review.md)
identifies message/Blob/restart proof as open investigation. No implementation
or version compatibility is claimed yet.

On 2026-10-12, the project owner explicitly accepted ARD-004, ARD-005, and
ARD-006 in the #696 implementation session with “接受，继续”. This records
the common-parent acceptance for Coding and Harness transcript of the bounded
v1 schema, original Transcript commit owner, fixed-ID recovery states, and
`coding.resume-continuation/v1` minimum writer capability specified here.
The independent R2.1 review remains supporting evidence.

Implementation may proceed under this contract. Release still requires the
fault, reader/export, old-writer, and N/N+1 evidence listed above and a concrete
first shipping build; acceptance does not assert that those gates have passed.
