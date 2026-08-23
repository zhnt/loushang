# Plugin Execution Trust PLC3 Contract

Status: PLC3-3 verified Definition evaluation and mixed-source join implemented;
production Host ingress, live owner binding, public SDK and MCP expansion remain
closed.

This document is the normative incremental companion to
[Unified Plugin Architecture](unified-plugin-architecture.md),
[Unified Plugin Authoring Primitives Delivery Plan](plugin-authoring-primitives-delivery-plan.md),
and
[Unified Plugin Lifecycle And Coding Pluginization Delivery Plan](plugin-lifecycle-coding-pluginization-plan.md).
It freezes the executable-trust persistence and pre-start linearization slices
without claiming that any installed or approved Plugin may execute.

## Ownership And Non-Effect Boundary

`loushang.harness.approval.plugin_execution.PluginExecutionDecisionJournal`
remains the sole durable authority added by PLC3-1/2 and consumed by PLC3-3.
One journal belongs to
exactly one `installation` or `workspace` scope and survives Session close.
The existing Session grant store is not reused, and Plugin management,
selection, authoring, Product adapters and UI do not own peer decision state.

`PluginSelectionResolver` alone owns the PLC3-2 in-memory aggregate start
permit. It linearizes a claimed executable source group against aggregate
close, but owns no Approval decision, execution-use state or receipt. The
permit type and issuing method are internal and are not package exports.

The module is internal and is not re-exported by `loushang.harness.approval`.
The Approval module records authority, use state and inert receipts only. It
does not:

- issue or validate the aggregate-owned start permit;
- load, import or invoke a Definition/Builder;
- read or reopen a package path or `VerifiedRevisionHandle`;
- create, enter, clean or replace an import realm;
- bind, register, publish or dispose a contribution;
- change a Session, Capability Graph, Resource generation or Model Input; or
- add an MCP server, tool or integration path.

The Coordinator accepts executable groups only when its internal construction
receives the PLC3-3 evaluator. The production `PluginDeclarationHost` injects
no evaluator and therefore continues to reject every executable group as
`execution_not_consumed`. A durable approved decision is necessary but not
sufficient execution authority; the executable path still has no production
caller.

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

## Aggregate Start Permit

After `_claim_group` has made one source group in-flight, the same resolver may
issue one opaque `PluginExecutionStartPermit`. The permit identifies only the
exact `preflightUseId`, `sourceGroupId` and `hostBootId`; its claim/permit
tokens remain private. It carries no decision, package path, Definition,
contribution or runtime object.

Permit issuance and aggregate close contend on the resolver condition lock:

- permit wins: the group stays in-flight and close waits for its settle;
- close or exact deadline wins: permit issuance fails as `preflight_closing`;
- a second issuance for the same claim fails as
  `plugin_execution_start_permit_consumed`; and
- a document group fails as `plugin_execution_start_not_applicable`.

No Approval, Product, loader or owner callback runs while the aggregate lock is
held. A rejected permit does not settle the claim; the worker must still settle
so close can finish. This is an internal race primitive, not permission to
import a Definition.

## Verified Definition Evaluator And Import Realm

PLC3-3 adds one internal `PluginDefinitionEvaluator` and one caller-owned,
process-wide `PluginImportRealm`. Neither is a package export. The production
Host constructs neither. An explicitly injected Coordinator performs the exact
sequence:

```text
claim group
-> issue aggregate start permit
-> verify revision handle and dependency lock
-> preflight clean compatible realm
-> atomically consume durable decision
-> reserve exact realm/use
-> persist STARTING
-> read entrypoint bytes through VerifiedRevisionHandle.open_file()
-> compile/invoke Definition with its source-group-bound Builder
-> persist EVALUATED or FAILED_AFTER_START
-> commit or quarantine realm
-> project exact receipt and in_process_evaluated evidence
-> join every Batch and finalize once
```

There is no await, mutable package-path reopen or Product callback between the
verified handle read and loader invocation. The evaluator does not change
`sys.path`, does not register its transient module in `sys.modules`, and does
not load a local helper by mutable path. Standard-library imports, the narrow
Harness authoring API and exact installed distributions named by the immutable
dependency lock are eligible. Relative and package-local transitive imports are
rejected in this first evaluator arm. The lock is a compatibility contract, not
a security sandbox: an in-process Definition is explicitly host-equivalent
trusted and still requires the complete Approval Subject.

One realm binds one `hostBootId`, serializes one active import, and accumulates
compatible exact distribution versions. A different locked version fails
before import. Any loader exception or uncertainty after start permanently
marks that realm `polluted`; no cache cleanup or in-process retry is attempted.
If realm reservation or the durable `STARTING` transition loses before loader
entry, the evaluator best-effort persists `CANCELLED_BEFORE_START`. Recovery
remains the authority for any ambiguous not-started record.

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

PLC3-1 implemented, and PLC3-2 retains, the exact record:

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

`executionUseVersion` is `1`. Atomic decision consumption creates only
`CONSUMED_NOT_STARTED`. PLC3-2 advances the same replacement record through
the exact state machine:

```text
CONSUMED_NOT_STARTED -> CANCELLED_BEFORE_START | STARTING
STARTING             -> EVALUATED | FAILED_AFTER_START
```

All other transitions fail closed. Each transition exact-matches the expected
journal revision, execution-use ID, current state, `hostBootId` and
`importRealmId`. It cannot change any other reservation field.

### `PluginExecutionConsumptionReceiptV1`

Only an exact current-boot/current-realm `EVALUATED` use projects a receipt.
The derived, non-persisted receipt has exactly:

```text
decisionId
executionUseId
hostBootId
importRealmId
instanceRevisionRef
policyRevision
preflightUseId
receiptVersion
revocationEpoch
sourceGroupId
sourceTrustPolicyRevision
state
subjectDigest
```

`receiptVersion` is `1` and `state` is exactly `EVALUATED`. A not-started,
cancelled, starting or failed use has no receipt. A receipt carries no loaded
module, Definition, contribution or owner binding and is not positive package
or aggregate authority by itself.

### Atomic Journal Event

Each JSONL record has exact `eventKind`, `eventVersion`,
`expectedJournalRevision`, `journalRevision` and `payload` fields.
`eventVersion` is `1`, `journalRevision == expectedJournalRevision + 1`,
revisions are contiguous. PLC3-1 events remain:

- `decision_issued`, containing the complete initial decision;
- `decision_revoked`, containing expected decision revision, complete
  replacement decision and redacted actor/source/time provenance; and
- `execution_consumed`, containing expected decision revision, the complete
  `CONSUMED` replacement decision and its complete
  `CONSUMED_NOT_STARTED` reservation in one record.

PLC3-2 adds:

- `execution_use_transitioned`, containing the exact expected state, complete
  replacement reservation and transition time; and
- `execution_uses_recovered`, containing the current host boot, recovery time
  and a sorted non-empty array of complete `CANCELLED_BEFORE_START`
  replacements.

Consumption and reservation creation are therefore one replay transition, not
two append operations. A partial final line is repaired by the shared durable
journal substrate; a complete invalid event, revision gap, orphan transition,
duplicate identity or non-replayable replacement fails the journal closed.

External-boot recovery cancels every `CONSUMED_NOT_STARTED` use from another
boot in one event. A repeated recovery with no remaining candidate appends
nothing. Current-boot not-started uses remain untouched. `STARTING` and
`FAILED_AFTER_START` uses are never rewritten by recovery and project their
exact `(hostBootId, importRealmId)` as polluted realms. Recovery therefore
reports quarantine evidence but performs no module-cache cleanup.

## Linearization And Revalidation

Issue, revoke and consume acquire the same durable journal lock, reload/replay
the complete journal, exact-match `expectedJournalRevision`, validate and append
one event. Consume-versus-revoke therefore has one winner. The loser observes a
revision conflict and must re-read; it cannot infer success.

Transition and recovery use that same lock and CAS head. Transition replaces
one use in one event. Recovery replaces all eligible external-boot not-started
uses in one event, never one append per use. Receipt projection reloads/replays
under the journal lock but does not append. Aggregate permit issuance uses only
the separate resolver lock; PLC3-2 deliberately introduces no cross-owner lock
or callback cycle.

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

## PLC3 Exact Error Codes

| Condition | Code |
| --- | --- |
| stale CAS head | `plugin_execution_journal_revision_conflict` |
| absent decision | `plugin_execution_decision_missing` |
| wrong scope / subject | `plugin_execution_decision_scope_mismatch` / `plugin_execution_decision_subject_mismatch` |
| denied / consumed / revoked / expired | `plugin_execution_decision_denied` / `plugin_execution_decision_consumed` / `plugin_execution_decision_revoked` / `plugin_execution_decision_expired` |
| stale policy / trust / epoch / retained authority | `plugin_execution_decision_policy_stale` / `plugin_execution_decision_trust_stale` / `plugin_execution_decision_revocation_stale` / `plugin_execution_authorization_stale` |
| duplicate generated decision/use identity or active Subject | `plugin_execution_decision_identity_conflict` / `plugin_execution_use_identity_conflict` / `plugin_execution_subject_decision_active` |
| absent use / stale use state / forbidden transition | `plugin_execution_use_missing` / `plugin_execution_use_state_conflict` / `plugin_execution_use_transition_invalid` |
| wrong boot or import realm / unavailable receipt | `plugin_execution_import_realm_mismatch` / `plugin_execution_receipt_unavailable` |
| transition or recovery time outside durable clock | `invalid_plugin_execution_use_transition` / `invalid_plugin_execution_recovery` |
| unsupported or invalid durable record | `unsupported_plugin_execution_journal_record_version` / `invalid_plugin_execution_journal_record` |
| non-replayable complete journal | `plugin_execution_journal_corrupt` |
| aggregate close wins / repeat / document group | `preflight_closing` / `plugin_execution_start_permit_consumed` / `plugin_execution_start_not_applicable` |
| realm polluted / busy / wrong boot | `plugin_import_realm_polluted` / `plugin_import_realm_busy` / `plugin_import_realm_host_mismatch` |
| locked dependency conflict / unavailable | `plugin_import_dependency_conflict` / `plugin_import_dependency_unavailable` |
| Definition failure after start | `plugin_definition_evaluation_failed` |

## Regression Gate And Next Slice

PLC3-2 is complete only when tests additionally prove permit-before-close and
close-before-permit races, close waiting for the claimed worker, one permit per
executable claim, strict state transitions, exact receipt shape and realm
binding, one-event multi-use recovery, idempotent repeated recovery and
polluted-realm projection without cleanup.

PLC3-3 regression tests now prove verified-byte evaluation despite source-tree
mutation, source-bound Builder output, exact current realm receipt evidence,
undeclared local import rejection, conflicting closure fencing, permanent
failure quarantine, fresh-decision retry rejection on a polluted realm,
mixed document/executable join-before-single-finalization and zero finalization
after a later executable failure.

The next slice is PLC4/PAP4 exact Capability owner admission. It must consume
the immutable candidates produced here without letting Definition evaluation
publish a registry, Resource, Mount, live Provider or Graph generation. Public
exports, general Plugin SDK, production Host ingress and MCP expansion remain
forbidden until their later explicit delivery gates.
