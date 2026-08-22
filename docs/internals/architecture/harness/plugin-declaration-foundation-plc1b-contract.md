# Plugin Declaration Foundation PLC1B Contract

## Status And Authority

This document is the normative implementation contract for PLC1B-1. It refines
the [Unified Plugin Architecture](unified-plugin-architecture.md) and the two
Plugin delivery plans without changing their owner model. Where an older plan
uses the ambiguous phrase `declaration_source_fingerprint`, the exact identities
below apply.

PLC1B-1 remains internal and inert. It adds no public Plugin SDK, import path,
owner admission, live Resource/Tool/Command publication, Capability binding, or
MCP behavior.

## Identity Layers And The No-Self-Reference Rule

Declaration source identity has three layers:

| Identity | Inputs | May appear in package bytes? | Authority |
| --- | --- | --- | --- |
| `sourceDescriptorFingerprint` | Exact `PluginDeclarationSource` wire record only | Yes | Groups equal package-internal source descriptors |
| `sourceGroupFingerprint` | Published package/dependency digests, descriptor fingerprint, accepted Product/scope/policy/instance/trust context, exact reservation closure, effective configuration map, and authority ceiling | No | Host-computed semantic identity for one accepted source group |
| `sourceGroupId` | `preflightUseId` plus `sourceGroupFingerprint` | No | Attempt-specific group identity used by claim, evidence, and terminal validation |

The descriptor fingerprint never includes package content digest, verified
revision, Product/scope facts, configuration overlays, a group, evidence, or an
accepted-use nonce. Therefore it can safely appear in an Index or Declaration
stored inside the content-addressed package. The Host computes group identity
only after publication. A `PluginDeclarationDocument` contains neither group
identity nor evidence. This rule prevents a declaration document from needing
to contain a hash of the package tree that contains that same document.

`package_source_identity` remains the installation/trust fact currently stored
as `PluginSourceBinding.source_identity` and `PluginSourceTrust.source_identity`.
PLC1B may expose a less ambiguous typed property without rewriting the durable
lockfile field. It must not create a second persisted identity with the same
meaning.

## Strict Canonical JSON Profile

Every PLC1B wire record and fingerprint input uses the existing declaration
canonical JSON profile:

```text
UTF-8
sort_keys=True
separators=(",", ":")
allow_nan=False
ensure_ascii=True
no Unicode normalization
```

Strict decoding rejects a UTF-8 BOM, duplicate object keys, unknown or omitted
fields, boolean values in integer fields, NaN/Infinity, unpaired Unicode
surrogates, nullable peer fields, and a non-supported version or union tag.
`PluginDeclarationDocument` bytes must equal their canonical re-encoding; thus
whitespace, key-order, escape, or trailing-newline variants are not alternate
accepted encodings. `documentBytesDigest` is SHA-256 of those exact verified
bytes. Semantic declaration and candidate fingerprints are separate logical
identities and never substitute for the bytes digest.

## Exact PLC1B Wire Records

All object field sets below are exact. Lists described as sorted must already be
in that order on input; the decoder does not silently reorder wire bytes.

### `PluginDeclarationSource` v1

The `document` arm has exactly:

| Key | Type/value |
| --- | --- |
| `kind` | `"document"` |
| `locator` | canonical revision-root-relative contained locator |
| `mediaType` | `"application/vnd.loushang.plugin-declarations+json"` |
| `schemaId` | `"loushang.plugin-declaration-document"` |
| `schemaVersion` | integer `1` |
| `sourceVersion` | integer `1` |

The `in_process` arm has exactly:

| Key | Type/value |
| --- | --- |
| `entrypoint` | canonical contained `relative/module.py:symbol` entrypoint |
| `kind` | `"in_process"` |
| `sourceVersion` | integer `1` |

The source descriptor does not contain package revision or contributed-runtime
factory/service execution model.

### `PluginContributionIndex` v2

The envelope has exactly `items` and `version`, with `version: 2`. `items` is
sorted by contribution `id`, contains no duplicate ID, and each item has exactly:

| Key | Type |
| --- | --- |
| `configuration` | strict JSON object containing no secret material |
| `declarationSource` | exact `PluginDeclarationSource` v1 object |
| `id` | canonical contribution ID |
| `kind` | supported contribution-kind tag |
| `owner` | canonical exact-owner ID |
| `requestedAuthorities` | sorted unique string list |
| `required` | boolean |

`sourceDescriptorFingerprint` is derived from `declarationSource`; it is not a
second stored peer field. The item fingerprint becomes the v2
`reservationFingerprint` and contains neither package revision nor evidence.

### `PluginDeclaration` v2

Each declaration has exactly:

| Key | Type/value |
| --- | --- |
| `contributionId` | canonical contribution ID |
| `irVersion` | integer `2` |
| `kind` | exact reserved contribution kind |
| `owner` | exact reserved owner ID |
| `payload` | strict owner-schema JSON object |
| `pluginId` | canonical Plugin ID |
| `reservationFingerprint` | lowercase SHA-256 of the exact v2 Index item |
| `sourceDescriptorFingerprint` | lowercase SHA-256 of the source descriptor record |
| `sourceKind` | `"document"` or `"in_process"`, matching the descriptor |

The declaration contains no package/revision, Product, scope, policy, group,
approval, decision, receipt, evidence, or accepted-use field. Host validation
exact-matches its three source/reservation fields to the selected Index item.

### `PluginDeclarationDocument` v1

The envelope has exactly `declarations` and `documentVersion`, with
`documentVersion: 1`. `declarations` is non-empty, contains exact Declaration v2
objects, and is strictly sorted by `(pluginId, contributionId)`. It must equal
the complete indexed closure for that one document source; Product selection
may later emit only its selected candidate subset.

### `PluginExecutionApprovalSubject` v2

The exact subject fields are:

```text
ambientHostAuthority
configurationMapFingerprint
dependencyLockDigest
entrypoint
instanceRevisionRef
packageContentDigest
packageSourceIdentity
pluginId
policyRevision
productId
requestedAuthorities
reservationClosureFingerprint
schemaVersion
scopeId
sourceDescriptorFingerprint
sourceTrustClass
sourceTrustPolicyRevision
```

`schemaVersion` is `2`; `requestedAuthorities` is sorted and unique.
`instanceRevisionRef` is the exact record `{instanceId, pluginId, revision}` with
a positive integer revision. The subject contains no `preflightUseId`: approval
may be recorded before an accepted attempt exists.

### `PluginExecutionDecisionRecord` v2 selection view

The strict PLC1B selection view has exactly:

```text
decisionId
decisionRecordVersion
disposition
policyRevision
subjectDigest
subjectSchemaVersion
```

Both version fields are independently required and equal `2`. This is a typed
view projected from the Approval owner's canonical `PluginApprovalDecisionRecord`
and shares its decision ID and transaction; it is not another approval store or
record authority. PLC1B uses it only for inert preflight. PAP2 must resolve and
consume the durable generic record before declaration import.

### `PluginDeclarationEvidence` v1

The `document_decoded` arm has exactly:

```text
declarationSetFingerprint
documentBytesDigest
documentSchemaVersion
evidenceVersion
kind
packageContentDigest
preflightUseId
reservationClosureFingerprint
sourceDescriptorFingerprint
sourceGroupFingerprint
sourceGroupId
```

`kind` is `"document_decoded"`; both versions are `1`. The Host constructs this
record after reading canonical bytes through `VerifiedRevisionHandle.open_file()`
and validating the complete closure.

The future `in_process_evaluated` arm uses the same common fields except the two
document fields and additionally contains one exact
`PluginExecutionConsumptionReceipt`. Its `kind` is
`"in_process_evaluated"`. PLC1B recognizes the tag for fail-closed routing but
cannot construct or accept this arm; PLC3 freezes and implements its remaining
durable audit fields before adding executable ingress.

### Candidate fingerprint v2

`PluginContributionCandidate` carries the exact Declaration and Evidence values,
not a nullable `decisionId`. Its fingerprint is over this exact logical record:

```text
domain: "loushang.plugin-contribution-candidate/v2"
pluginId
packageContentDigest
dependencyLockDigest
productId
scopeId
sourceGroupFingerprint
declarationFingerprint
evidenceFingerprint
```

Because evidence contains `preflightUseId` and `sourceGroupId`, evidence from an
aborted or expired accepted attempt cannot become a candidate in a later one.
A document candidate serializes no subject, decision, execution-use, or receipt
field.

## Exact Fingerprint Inputs

Every digest below is lowercase SHA-256 of the strict canonical JSON record.

| Name | Domain and exact logical payload |
| --- | --- |
| `sourceDescriptorFingerprint` | domain `loushang.plugin-declaration-source-descriptor/v1`; `source` = exact source wire record |
| `reservationFingerprint` | domain `loushang.plugin-contribution-reservation/v2`; `reservation` = exact v2 Index item |
| `reservationClosureFingerprint` | domain `loushang.plugin-reservation-closure/v1`; `reservations` = contribution-ID-sorted `{contributionId, reservationFingerprint}` list |
| `configurationMapFingerprint` | domain `loushang.plugin-group-configuration/v1`; `configurations` = contribution-ID-sorted `{configuration, contributionId}` list after Product overlay and secret-reference normalization |
| `sourceGroupFingerprint` | domain `loushang.plugin-declaration-source-group/v1`; exact fields `ambientHostAuthority`, `configurationMapFingerprint`, `dependencyLockDigest`, `instanceRevisionRef`, `packageContentDigest`, `packageSourceIdentity`, `pluginId`, `policyRevision`, `productId`, `requestedAuthorities`, `reservationClosureFingerprint`, `scopeId`, `sourceDescriptorFingerprint`, `sourceTrustClass`, `sourceTrustPolicyRevision` |
| `sourceGroupId` | domain `loushang.plugin-declaration-source-group-use/v1`; exact fields `preflightUseId`, `sourceGroupFingerprint` |
| `declarationSetFingerprint` | domain `loushang.plugin-declaration-set/v2`; `declarations` = identity-sorted declaration fingerprints |
| `evidenceFingerprint` | domain `loushang.plugin-declaration-evidence/v1`; `evidence` = exact evidence wire record |

The general `PluginContributionSemanticFingerprint` remains the separate
pre-owner/pre-Host conformance diagnostic defined by UPA. It does not replace
any identity in this table.

## Preflight Context, Attempts, And Ownership

PLC1B introduces the pure data `PluginPreflightContextV1` with exact fields
`contextVersion: 1`, `productId`, `scopeId`, `policyRevision`, and a Plugin-ID-
sorted non-empty tuple of exact `PluginInstanceRevisionRef` values. The Product
composition input supplies these refs; PLC1B validates complete coverage and
does not invent or persist them. PLC2 makes the same identity durable and owns
its lifecycle without changing its meaning or fingerprint.

The remaining PLC1B types are process-local immutable values rather than new
wire schemas. Their exact field ownership is:

| Record | Owned fields |
| --- | --- |
| `PluginPreflightProposal` | exact Context plus identity-sorted SourceProposals; no use ID, terminal handle, group, reservation, or gate |
| `PluginDeclarationSourceProposal` | published package ref, exact Source descriptor/fingerprint, complete proposed Index closure, effective configuration map/fingerprint, trust facts, authority ceiling, and strict `sourceDisposition = data_only | execution_subject(subject)`; it owns no accepted Gate |
| `PluginPreflightOutcome` | `accepted(AcceptedPluginPreflight)`; `pending_approval(subjects, diagnostics)`; `denied(diagnostics)`; or `rejected(diagnostics)`, with no nullable peer fields |
| `AcceptedPluginPreflight` | `preflightUseId`, host epoch, monotonic deadline, exact Context, identity-sorted SourceGroups, and opaque internal terminal handle |
| `PluginDeclarationSourceGroup` | use ID, group ID/fingerprint, package ref, Source descriptor/fingerprint, Context/instance ref, complete closure/fingerprint, effective configuration/fingerprint, trust/authority facts, and one Gate |
| `PluginDeclarationGate` | `data_only` with no subject/decision, or `execution_preflight` with exactly one Subject v2 and Decision v2 view |
| `PluginDeclarationReservation` | package/contribution/reservation identity and only its group ID/fingerprint reference; no copied Gate, subject, decision, or evidence |
| `PluginDeclarationBatch` | use ID, group ID/fingerprint, complete identity-sorted Declarations, and exactly one Host-created matching Evidence value |
| `PluginContributionCandidate` | package ref, exact Declaration, exact Evidence, and candidate fingerprint; no peer execution decision field |

These field sets are implemented by frozen dataclasses/strict unions. They are
not serialized as a second interchange format. Batch, Evidence and Candidate
construction remains Host-only.

Every call to `preflight()` rebuilds proposals. It may return `accepted` on the
first call whenever every proposed source requirement is already satisfied; an
all-document selection is merely the no-decision special case. Only a missing current
positive executable decision returns `pending_approval`. Approval recording is
followed by another full call, never mutation or resume of a proposal.

Only `accepted` creates:

- a random, non-reused `preflightUseId`;
- one process `hostEpoch` and monotonic `expiresAt` deadline;
- one internal terminal handle;
- exact attempt-bound SourceGroups; and
- one-use reservations that carry only `sourceGroupId` and
  `sourceGroupFingerprint` references.

The accepted SourceGroup exclusively owns its `data_only` or
`execution_preflight` gate. The stable group fingerprint excludes the attempt
nonce; the group ID, evidence, Batch, and Candidate bind the attempt. Finalize
requires every evidence `preflightUseId` and `sourceGroupId` to match the current
ACTIVE token and atomically marks those evidence uses terminal. Mismatch fails
`plugin_declaration_evidence_attempt_mismatch`.

## Aggregate Claim And Terminal Protocol

The private Resolver state and the Coordinator use one linearizable protocol:

```text
aggregate: ACTIVE(open_for_claims=true, in_flight=0)
group:     PENDING -> CLAIMED -> COMPLETED | FAILED

finalize:
  every group COMPLETED and in_flight == 0
  CAS ACTIVE -> FINALIZED

abort or expire:
  CAS open_for_claims=false
  reject every new group claim and decision consumption
  cancel/settle every CLAIMED group
  when in_flight == 0, CAS ACTIVE -> ABORTED | EXPIRED
```

PLC1B processes document groups serially but uses this same claim interface.
PLC3 may add concurrent executable groups without adding a second state owner.
Once close begins, a late completion is recorded for diagnostics and cannot
form evidence accepted by finalize.

The Coordinator is the only caller of terminal operations; the Resolver's
private terminal port owns CAS and retains terminal tombstones through the
current host epoch. Repeated or racing calls deterministically return
`preflight_already_finalized`, `preflight_already_aborted`, or
`preflight_expired`. Monotonic time is authoritative for an in-process deadline;
wall-clock expiry is diagnostic only. Any token from a prior host epoch returns
`preflight_expired`; PLC1B does not add a durable aggregate store. PLC2 may
persist management/audit projections but cannot become a peer terminal owner.

## PLC1B Executable Boundary

PLC1B scans the accepted group set before accepting any declaration input. If
any group is `execution_preflight`, the Coordinator claims no group, accepts no
Builder output or external executable declaration, imports no code, closes the
aggregate once as `ABORTED` with `execution_not_consumed`, and calls finalization
zero times. Executable Builder codec tests remain isolated unit tests. Only PLC3
adds the evaluator port and the Host construction of executable Batch/evidence.

The Coordinator and future evaluator live in the higher
`loushang.harness.plugin_authoring` composition layer. Lower
`resources.plugins` declarations/selection code never imports that layer.

PLC1B removes or privatizes the current top-level
`build_execution_approval_subject`, `PluginPreflight`, direct `finalize()`, and
`rollback()` entry points. Callers receive proposed subjects only through
`PluginPreflightOutcome`; only the Coordinator holds the internal terminal
handle. Architecture scans forbid non-Coordinator subject construction or
terminal calls.

## Forward Constraints For PAP2, PAP3, And PAP5

PAP2 adds one installation/workspace-scoped durable Plugin decision journal
inside the existing `harness.approval` owner. It is not the current Session
grant store and not a Plugin-owned second store. Recovery of that journal occurs
before Plugin preflight; Session close does not erase installation/workspace
decisions. The exact execution selection view above is projected from its
generic decision record.

Decision consumption creates a unique `executionUseId` bound to
`preflightUseId` and `sourceGroupId`. The durable use state is:

```text
CONSUMED_NOT_STARTED -> STARTING -> EVALUATED
                                -> FAILED_AFTER_START
```

`STARTING` commits before invoking the loader. Recovery treats `STARTING` and
`FAILED_AFTER_START` as possibly executed and marks the import realm polluted.
An explicit retry requires a fresh preflight, fresh decision, and clean Host
restart unless a separately accepted idempotent re-evaluation contract exists.
Only `EVALUATED` can produce `in_process_evaluated` evidence. A failed preflight
does not auto-consume a second decision; it does leave durable audit/use facts
and may leave a polluted import realm even though no owner generation was
published.

PAP5 applies the same one-use rule to activation. Each factory construction,
owner bind, or process spawn receives a token-bound `ActivationUseReservation`
with `CONSUMED_NOT_STARTED -> STARTING -> STARTED|COMMITTED|FAILED`. A Component
Host returns a one-use activation lease; the exact Binder/owner consumes it at
the real factory or launch start. A new attempt requires a fresh one-shot
decision unless the Approval owner issues a new decision under an explicit
retained rule. External-service restart never replays an old receipt.

## Exact Version Diagnostics

The PLC1B codecs use these distinct codes:

```text
unsupported_plugin_contribution_index_version
unsupported_plugin_declaration_source_version
unsupported_plugin_declaration_ir_version
unsupported_plugin_declaration_document_version
unsupported_plugin_execution_approval_subject_version
unsupported_plugin_execution_decision_record_version
unsupported_plugin_declaration_evidence_version
```

An unknown union tag is not a version error and uses its record-specific
`unsupported_*_kind` diagnostic. Exact-field mismatch, duplicate key,
noncanonical bytes, closure mismatch, and evidence-attempt mismatch also remain
separate diagnostics.

## PLC1B-1 Regression Gate

Implementation begins regression-first and must prove:

1. golden full JSON and digest fixtures for Source, Index v2, Declaration v2,
   Document v1, Subject v2, Decision v2, document evidence, and candidate;
2. a package can be written, content-addressed, published, and decoded without
   any hash fixed point;
3. duplicate keys, BOM, NaN/Infinity, noncanonical bytes, CJK escapes,
   normalization-form distinction, and unpaired surrogates fail or hash exactly
   as specified;
4. pending creates no active fact and fresh preflight revalidates package,
   trust, policy, scope, configuration, and decision;
5. one source with multiple contributions and one package with multiple document
   sources preserve complete declaration closure while candidate selection may
   emit a subset;
6. each document source is read exactly once only through
   `VerifiedRevisionHandle.open_file()`;
7. finalize/abort/expire and group-claim races satisfy the CAS protocol and
   return exact terminal diagnostics;
8. old evidence cannot cross `preflightUseId`, and a document candidate cannot
   carry any execution peer field;
9. a mixed PLC1B package has zero import, zero executable declaration ingress,
   one abort, and zero finalization; and
10. old public subject/finalize/rollback paths and reservation-owned gates are
    absent by architecture scan.
