# Plugin Execution Trust PLC3 Contract

Status: PLC3-1 durable Approval journal implemented; aggregate start permit,
use-state recovery, import realm, Definition evaluation, mixed-source join and
all live owner binding remain closed.

This document is the normative incremental companion to
[Unified Plugin Architecture](unified-plugin-architecture.md),
[Unified Plugin Authoring Primitives Delivery Plan](plugin-authoring-primitives-delivery-plan.md),
and
[Unified Plugin Lifecycle And Coding Pluginization Delivery Plan](plugin-lifecycle-coding-pluginization-plan.md).
It freezes the first executable-trust persistence slice without claiming that
any installed or approved Plugin may execute.

## Ownership And Non-Effect Boundary

`loushang.harness.approval.plugin_execution.PluginExecutionDecisionJournal`
is the sole durable authority added by PLC3-1. One journal belongs to exactly
one `installation` or `workspace` scope and survives Session close. The
existing Session grant store is not reused, and Plugin management, selection,
authoring, Product adapters and UI do not own peer decision state.

The module is internal and is not re-exported by `loushang.harness.approval`.
It records authority and inert use reservations only. It does not:

- issue an aggregate start permit;
- load, import or invoke a Definition/Builder;
- read or reopen a package path or `VerifiedRevisionHandle`;
- enter the Plugin Instance lifecycle or import-realm gate;
- bind, register, publish or dispose a contribution;
- change a Session, Capability Graph, Resource generation or Model Input; or
- add an MCP server, tool or integration path.

The existing Coordinator therefore continues to reject every executable group
as `execution_not_consumed`. A durable approved decision is necessary but not
sufficient execution authority.

## Scope And Approval Subject

Every issue, query and consume operation receives the already-frozen
`PluginExecutionApprovalSubject` v2. The subject is still derived by inert
preflight from the exact package digest, dependency lock, entrypoint, source
trust, Product/scope, configuration, authority closure, reservation closure and
`PluginInstanceRevisionRef`. The journal never parses a manifest or constructs
that subject.

The journal's exact `scopeId` must match the subject. A mismatch fails before
decision lookup or use creation. `scopeKind` is explicit because an identical
string identifier must not silently convert installation authority into
workspace authority or vice versa.

## Durable Records

### `PluginApprovalAuthorizationV1`

The discriminated authorization record contains:

```text
actorId
authorizationKind
authorizationVersion
source
[authorityId]
```

`authorizationVersion` is `1`. `authorizationKind` is `direct`,
`retained_grant`, or `policy_rule`. Only the latter two arms contain the
required `authorityId`. Actor/source are structural provenance, not Product UI
wording. Secret material and raw policy objects are forbidden.

### `PluginApprovalDecisionRecordV1`

The durable Approval-owner record contains exactly:

```text
authorization
consumedExecutionUseId
consumptionState
decisionId
decisionRevision
disposition
expiresAtUnixMs
instanceRevisionRef
issuedAtUnixMs
pluginId
policyRevision
recordVersion
revocationEpoch
scopeId
scopeKind
sourceTrustPolicyRevision
subjectDigest
subjectKind
subjectSchemaVersion
```

`recordVersion` is `1`; `subjectKind` is exact
`plugin_declaration_execution`; `subjectSchemaVersion` is `2`. The tag makes
this record the executable-declaration arm of the Approval-owned Plugin
decision authority. PAP5 may add a separately versioned activation arm only by
extending this same journal owner and event union; it must not create a second
Plugin decision store. Decision and execution
use IDs are fresh 192-bit lowercase hexadecimal values. Times are non-negative
Unix epoch milliseconds and expiry strictly follows issue time. The state is:

```text
approved: AVAILABLE -> CONSUMED | REVOKED
denied:   DENIED
```

Only `CONSUMED` carries `consumedExecutionUseId`. A denied, consumed, revoked or
expired record cannot project positive authority.

The read-only selection projection remains the existing exact
`PluginExecutionDecisionRecord` v2. It contains only decision ID, canonical
subject digest, policy revision, `approved|denied`, decision-record version 2
and subject-schema version 2. This view is not persisted as a second decision.

### `ExecutionUseReservation` v1

PLC3-1 implements the previously frozen exact record:

```text
decisionId
executionUseId
executionUseVersion
hostBootId
importRealmId
instanceRevisionRef
policyRevision
preflightUseId
revocationEpoch
sourceGroupId
sourceTrustPolicyRevision
state
subjectDigest
```

`executionUseVersion` is `1`. PLC3-1 can create only
`CONSUMED_NOT_STARTED`; the record type recognizes the complete frozen state
vocabulary so later journal events can advance it without changing this wire
shape. No PLC3-1 method can produce `STARTING`, `EVALUATED`, a consumption
receipt or import-realm cleanliness evidence.

### Atomic Journal Event

Each JSONL record has exact `eventKind`, `eventVersion`,
`expectedJournalRevision`, `journalRevision` and `payload` fields.
`eventVersion` is `1`, `journalRevision == expectedJournalRevision + 1`,
revisions are contiguous, and the only PLC3-1 events are:

- `decision_issued`, containing the complete initial decision;
- `decision_revoked`, containing expected decision revision, complete
  replacement decision and redacted actor/source/time provenance; and
- `execution_consumed`, containing expected decision revision, the complete
  `CONSUMED` replacement decision and its complete
  `CONSUMED_NOT_STARTED` reservation in one record.

Consumption and reservation creation are therefore one replay transition, not
two append operations. A partial final line is repaired by the shared durable
journal substrate; a complete invalid event, revision gap, orphan transition,
duplicate identity or non-replayable replacement fails the journal closed.

## Linearization And Revalidation

Issue, revoke and consume acquire the same durable journal lock, reload/replay
the complete journal, exact-match `expectedJournalRevision`, validate and append
one event. Consume-versus-revoke therefore has one winner. The loser observes a
revision conflict and must re-read; it cannot infer success.

Immediately before the atomic consume event, the journal checks:

- the exact decision ID and canonical Subject digest;
- durable journal and scope identity;
- `AVAILABLE`/approved and unexpired state;
- current approval-policy and source-trust-policy revisions;
- exact current revocation epoch;
- the exact subject-bound Plugin Instance Revision; and
- liveness of any retained grant or policy rule through the Approval-owner
  validator.

The retained-authority validator is an Approval-owner local check and runs
inside the transaction. It must not call Plugin lifecycle, aggregate,
import-realm or Product code. Exceptions and non-boolean-positive results fail
closed as stale authorization.

Query is idempotent and reconstructs from the journal. It returns the strict v2
selection view only for a matching unexpired `AVAILABLE` or `DENIED` record.
Consumed, revoked, expired, wrong-scope and unknown decisions project `missing`;
the consuming command still reports the exact terminal reason.

## PLC3-1 Exact Error Codes

| Condition | Code |
| --- | --- |
| stale CAS head | `plugin_execution_journal_revision_conflict` |
| absent decision | `plugin_execution_decision_missing` |
| wrong scope / subject | `plugin_execution_decision_scope_mismatch` / `plugin_execution_decision_subject_mismatch` |
| denied / consumed / revoked / expired | `plugin_execution_decision_denied` / `plugin_execution_decision_consumed` / `plugin_execution_decision_revoked` / `plugin_execution_decision_expired` |
| stale policy / trust / epoch / retained authority | `plugin_execution_decision_policy_stale` / `plugin_execution_decision_trust_stale` / `plugin_execution_decision_revocation_stale` / `plugin_execution_authorization_stale` |
| duplicate generated decision/use identity or active Subject | `plugin_execution_decision_identity_conflict` / `plugin_execution_use_identity_conflict` / `plugin_execution_subject_decision_active` |
| unsupported or invalid durable record | `unsupported_plugin_execution_journal_record_version` / `invalid_plugin_execution_journal_record` |
| non-replayable complete journal | `plugin_execution_journal_corrupt` |

## Regression Gate And Next Slice

PLC3-1 is complete only when tests prove strict durable recovery, v2 projection,
denial, expiry, wrong digest/scope, stale policy/trust/epoch, retained-authority
revalidation, atomic one-shot consumption, revocation persistence, CAS failure
without append and consume/revoke lock linearization.

PLC3-2 must add the aggregate-owned opaque start permit before this journal is
wired to a worker, then add durable use-state transitions and external-boot
`CONSUMED_NOT_STARTED -> CANCELLED_BEFORE_START` reconciliation. Only after
`STARTING` is committed may PLC3-3 cross the verified-handle import point.
Public exports and production Host ingress remain forbidden until the complete
PLC3 exit gate passes.
