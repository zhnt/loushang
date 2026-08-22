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

The rule applies to every package-internal locator, including Capability
Provider factory and disposer references. A package-internal locator is only a
canonical revision-root-relative JSON string plus, where applicable, a symbol
and contributed-runtime execution-model tag. It contains no content digest,
verified-revision identity, source authority, trust fact, Product fact, or
accepted-use identity. The Host combines that relative locator with the
`PublishedPluginPackage`/`VerifiedRevisionHandle` only after publication and
attaches the package digest to Host-owned group, candidate, evidence, and
resolved-symbol views. No package byte may claim the digest of the package tree
that contains it.

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

The PLC1B engine ceilings are part of this version: one declaration document is
at most 4,194,304 bytes, contains at most 1,024 declarations, and has JSON
nesting depth at most 64. The strict manifest boundary applies duplicate-key
detection before extracting `contributions`; typed Index/Source codec errors
retain their exact diagnostic instead of being collapsed into a generic
manifest error. These are hard safety ceilings, not Product configuration.

## Exact PLC1B Wire Records

All object field sets below are exact. Lists described as sorted must already be
in that order on input; the decoder does not silently reorder wire bytes.

### `PluginDeclarationSource` v1

The `document` arm has exactly:

| Key | Type/value |
| --- | --- |
| `kind` | `"document"` |
| `locator` | non-empty canonical revision-root-relative contained JSON string; no digest or source authority |
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

### Package-internal Capability Provider payload v2

PLC1B advances the unpublished `CapabilityProviderDeclarationPayload` to v2.
Its `factory` and optional `disposer` use exact `PluginSymbolReference` v2
objects with these fields:

| Key | Type/value |
| --- | --- |
| `executionModel` | exact contributed-runtime tag `"in_process"` |
| `path` | non-empty canonical contained revision-root-relative Python path string |
| `symbol` | non-empty canonical symbol string |
| `symbolReferenceVersion` | integer `2` |

The payload retains the exact v1 top-level field names `bindingInputs`,
`configurationFingerprint`, `disposer`, `factory`, `payloadVersion`, and
`provider`, but requires `payloadVersion: 2` and v2 symbol references. Neither
the payload nor either symbol reference contains `packageDigest`. Host
validation binds every reference to the selected package's exact content digest
and contributed execution model before a resolved-symbol view can exist. The
unpublished payload/symbol-reference v1 shapes fail closed; no source-kind-
specific decoder or compatibility alias remains.

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
`indexFingerprint` is a Host-derived inspection/conformance identity for the
exact envelope; it is not stored inside the Index, used as a reservation, or
accepted in place of item-level validation.

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
| `reservationFingerprint` | lowercase SHA-256 from the exact domain-wrapped reservation algorithm below |
| `sourceDescriptorFingerprint` | lowercase SHA-256 from the exact domain-wrapped source algorithm below |
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
allowedAuthorityCeiling
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

The strict field constraints are:

| Key | Type/value |
| --- | --- |
| `ambientHostAuthority` | boolean |
| `allowedAuthorityCeiling` | sorted unique list of non-empty authority strings |
| `configurationMapFingerprint` | lowercase SHA-256 |
| `dependencyLockDigest` | lowercase SHA-256 |
| `entrypoint` | exact canonical contained entrypoint from the Source descriptor |
| `instanceRevisionRef` | exact `{instanceId, pluginId, revision}`; non-empty string IDs, matching `pluginId`, positive non-boolean integer revision |
| `packageContentDigest` | lowercase SHA-256 |
| `packageSourceIdentity` | non-empty installation/trust identity string |
| `pluginId`, `productId`, `scopeId`, `policyRevision` | non-empty canonical identity/revision strings |
| `requestedAuthorities` | sorted unique list of non-empty strings; subset of `allowedAuthorityCeiling` |
| `reservationClosureFingerprint` | lowercase SHA-256 |
| `schemaVersion` | integer `2` |
| `sourceDescriptorFingerprint` | lowercase SHA-256 |
| `sourceTrustClass`, `sourceTrustPolicyRevision` | non-empty strings from the accepted trust snapshot |

Every repeated Subject field is derived from and must exact-match its one
`PluginDeclarationSourceProposal`; a caller cannot independently assemble the
record. The subject contains no `preflightUseId`: approval may be recorded
before an accepted attempt exists.

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

`decisionId` and `policyRevision` are non-empty strings, `subjectDigest` is a
lowercase SHA-256, `disposition` is exactly `"approved"` or `"denied"`, and both
version fields are non-boolean integers equal to `2`. Policy revision, subject
schema version, and digest must exact-match the queried Subject. This is a typed
read-only view projected by the Approval owner; it is not another approval
store or record authority. PAP2 makes its backing
`PluginApprovalDecisionRecord` durable and must resolve and consume that generic
record before declaration import.

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

`kind` is `"document_decoded"`; `evidenceVersion` and
`documentSchemaVersion` are non-boolean integers equal to `1`; every `*Digest`
or `*Fingerprint` field is lowercase SHA-256; `preflightUseId` is 48 lowercase
hexadecimal characters; and `sourceGroupId` is lowercase SHA-256. The Host
constructs this record after reading canonical bytes through
`VerifiedRevisionHandle.open_file()` and validating the complete closure. Its
package, source, closure, group, and use fields exact-match the claimed group;
they are not independently supplied by the decoder.

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
packageContentDigest
sourceGroupFingerprint
declarationFingerprint
evidenceFingerprint
```

These inputs are mechanically recoverable from the Candidate's package ref,
exact Declaration, and exact Evidence. Plugin/Product/scope/dependency identity
is already transitively bound by Declaration or `sourceGroupFingerprint` and is
not copied into an unreconstructable peer field. Because evidence contains
`preflightUseId` and `sourceGroupId`, evidence from an aborted or expired
accepted attempt cannot become a candidate in a later one. A document Candidate
dataclass/projection contains no subject, decision, execution-use, or receipt
field; PLC1B adds no Candidate wire codec.

## Exact Fingerprint Inputs

Every digest below is lowercase SHA-256 of the strict canonical bytes for one
JSON object whose first listed member is descriptive only: canonical key sorting
still determines the bytes. There is no raw-record hashing exception.

| Name | Domain and exact logical payload |
| --- | --- |
| `sourceDescriptorFingerprint` | domain `loushang.plugin-declaration-source-descriptor/v1`; `source` = exact source wire record |
| `indexFingerprint` | domain `loushang.plugin-contribution-index/v2`; `index` = exact Index v2 envelope |
| `reservationFingerprint` | domain `loushang.plugin-contribution-reservation/v2`; `reservation` = exact v2 Index item |
| `reservationClosureFingerprint` | domain `loushang.plugin-reservation-closure/v1`; `reservations` = contribution-ID-sorted `{contributionId, reservationFingerprint}` list |
| `configurationMapFingerprint` | domain `loushang.plugin-group-configuration/v1`; `configurations` = `(pluginId, contributionId)`-sorted exact Product-owned effective entries `{configuration, contributionId, pluginId}` |
| `declarationFingerprint` | domain `loushang.plugin-declaration/v2`; `declaration` = exact Declaration v2 wire record |
| `subjectDigest` | domain `loushang.plugin-execution-approval-subject/v2`; `subject` = exact Subject v2 wire record |
| `sourceGroupFingerprint` | domain `loushang.plugin-declaration-source-group/v1`; exact fields `allowedAuthorityCeiling`, `ambientHostAuthority`, `configurationMapFingerprint`, `dependencyLockDigest`, `instanceRevisionRef`, `packageContentDigest`, `packageSourceIdentity`, `pluginId`, `policyRevision`, `productId`, `requestedAuthorities`, `reservationClosureFingerprint`, `scopeId`, `sourceDescriptorFingerprint`, `sourceTrustClass`, `sourceTrustPolicyRevision` |
| `sourceGroupId` | domain `loushang.plugin-declaration-source-group-use/v1`; exact fields `preflightUseId`, `sourceGroupFingerprint` |
| `declarationSetFingerprint` | domain `loushang.plugin-declaration-set/v2`; `declarations` = `(pluginId, contributionId)`-sorted `{contributionId, declarationFingerprint, pluginId}` list |
| `evidenceFingerprint` | domain `loushang.plugin-declaration-evidence/v1`; `evidence` = exact evidence wire record |
| `candidateFingerprint` | domain `loushang.plugin-contribution-candidate/v2`; exact fields `declarationFingerprint`, `evidenceFingerprint`, `packageContentDigest`, `sourceGroupFingerprint` |

Repeated source-group/Subject fields use the Subject table's exact types and
constraints. All `*Digest`/`*Fingerprint` values in this table are exactly 64
lowercase hexadecimal characters; bool is never accepted as an integer; all
identity/revision strings are non-empty; and every sorted list is unique on
wire. `sourceGroupId`, Evidence and Candidate consume the recomputed upstream
digest, never a noncanonical alias.

Each implementation fixture stores the complete canonical JSON bytes next to
its fixed SHA-256 hex. The Candidate verifier recomputes all four logical inputs
from the Candidate's own package/Declaration/Evidence fields. A receiver never
accepts a caller-supplied declaration, subject, evidence, or candidate digest
without recomputing it through this table.

The following normative sentinels distinguish the wrapper algorithm from raw-
record hashing. The Source wrapper canonical bytes are:

```json
{"domain":"loushang.plugin-declaration-source-descriptor/v1","source":{"kind":"document","locator":"declarations/plugin.json","mediaType":"application/vnd.loushang.plugin-declarations+json","schemaId":"loushang.plugin-declaration-document","schemaVersion":1,"sourceVersion":1}}
```

Their SHA-256 is
`aec4eb58e83e5b4ee53392eee1881c358f75ca6c3d202c56c348a657edac6595`.
Using that source digest and an all-zero reservation digest, the canonical
generic Declaration wrapper bytes are shown below. Its opaque empty payload is
only a hash-profile sentinel and does not claim Capability-owner admission:

```json
{"declaration":{"contributionId":"provider","irVersion":2,"kind":"capability_provider","owner":"coding.lsp","payload":{},"pluginId":"coding.lsp","reservationFingerprint":"0000000000000000000000000000000000000000000000000000000000000000","sourceDescriptorFingerprint":"aec4eb58e83e5b4ee53392eee1881c358f75ca6c3d202c56c348a657edac6595","sourceKind":"document"},"domain":"loushang.plugin-declaration/v2"}
```

Their SHA-256 is
`2fe5d856380b78228e5d3baeb5227598e19268f403c4765e12e99e2567381217`.
The complete Subject sentinel canonical bytes are:

```json
{"domain":"loushang.plugin-execution-approval-subject/v2","subject":{"allowedAuthorityCeiling":["process.launch"],"ambientHostAuthority":false,"configurationMapFingerprint":"1111111111111111111111111111111111111111111111111111111111111111","dependencyLockDigest":"2222222222222222222222222222222222222222222222222222222222222222","entrypoint":"definition.py:define","instanceRevisionRef":{"instanceId":"coding.lsp@product","pluginId":"coding.lsp","revision":1},"packageContentDigest":"3333333333333333333333333333333333333333333333333333333333333333","packageSourceIdentity":"registry:example","pluginId":"coding.lsp","policyRevision":"policy-1","productId":"coding","requestedAuthorities":["process.launch"],"reservationClosureFingerprint":"4444444444444444444444444444444444444444444444444444444444444444","schemaVersion":2,"scopeId":"workspace","sourceDescriptorFingerprint":"aec4eb58e83e5b4ee53392eee1881c358f75ca6c3d202c56c348a657edac6595","sourceTrustClass":"registry_signed","sourceTrustPolicyRevision":"trust-1"}}
```

Their SHA-256 is
`abc18ae8cf63b0a828accb4638fa389229c0f352db09c0238d0f815771d731bf`.
The Candidate sentinel canonical bytes are:

```json
{"declarationFingerprint":"2fe5d856380b78228e5d3baeb5227598e19268f403c4765e12e99e2567381217","domain":"loushang.plugin-contribution-candidate/v2","evidenceFingerprint":"5555555555555555555555555555555555555555555555555555555555555555","packageContentDigest":"3333333333333333333333333333333333333333333333333333333333333333","sourceGroupFingerprint":"6666666666666666666666666666666666666666666666666666666666666666"}
```

Their SHA-256 is
`bab38106e94908a0e7385da2c5576aa3ce0898348a0521aec1c83d3d8732fb3c`.

The general `PluginContributionSemanticFingerprint` remains the separate
pre-owner/pre-Host conformance diagnostic defined by UPA. It does not replace
any identity in this table.

## Preflight Context, Attempts, And Ownership

PLC1B introduces the pure data `PluginPreflightContextV1` with exact fields
`contextVersion: 1`, `productId`, `scopeId`, `policyRevision`, and a Plugin-ID-
sorted non-empty tuple of exact `PluginInstanceRevisionRef` values. The Product
composition input supplies exactly one ref for every selected Plugin ID and no
extra ref; duplicate Plugin IDs, instance IDs, or refs fail closed. The exact
sort key is `(pluginId, instanceId, revision)`. PLC1B validates complete
one-to-one coverage and does not invent or persist these values. PLC2 makes the
same identity durable and owns its lifecycle without changing its meaning or
fingerprint.

`PluginSelectionPlanV2` is the sole Product authority passed to `preflight()`.
It owns exactly one Context rather than peer `productId`/`scopeId`/policy
arguments, the selected Plugin/contribution refs, one
`PluginSourceTrustSnapshotV1` per selected Plugin, one
`PluginEffectiveConfigurationSetV1`, and the allowed authority ceiling. A trust
snapshot has exact fields `pluginId`, `packageSourceIdentity`,
`sourceTrustClass`, `sourceTrustPolicyRevision`, and boolean `trusted`; it must
exact-match the published binding and completely cover the selected set. Only
`trusted: true` may reach `pending_approval` or `accepted`; an untrusted source
is `rejected` before decision lookup.
Requested authorities are the sorted union of the complete source closure,
must be a subset of the sorted Product ceiling, and both lists are bound into
the group/Subject fingerprint. A plan with missing, extra, or duplicate refs,
trust snapshots, or effective configuration entries is rejected. Published
packages and bindings also form a unique one-to-one map by Plugin ID and exactly
cover the Plan. SourceProposals are strictly unique and sorted by
`(pluginId, sourceDescriptorFingerprint)`; one package/source key cannot be
split or repeated.

The Product configuration owner performs all defaults, OEM/Product overrides,
deletes, and secret resolution policy before preflight. PLC1B receives only the
already-resolved frozen `PluginEffectiveConfigurationSetV1`: version `1` plus
exact entries `{configuration, contributionId, pluginId}` strictly sorted by
`(pluginId, contributionId)` and exactly covering the proposed reservation
closure. PLC1B validates and hashes this map; it has no overlay or merge
algorithm and accepts no peer `overlays` argument. A secret value never enters
this map. The only secret-bearing marker is the exact tagged reference
`{"$secretRef":{"authorityClass":...,"providerId":...,"referenceId":...,
"rotationEpoch":...,"secretReferenceVersion":1}}`, where the first three
values are non-empty strings and `rotationEpoch` is a non-negative non-boolean
integer. Unknown/extra secret-reference fields, a resolved secret value, or an
untagged value identified as secret by Product metadata fails
`invalid_plugin_effective_configuration`; secret bytes never enter a digest or
diagnostic.

Preflight has the single logical signature
`preflight(packages, bindings, plan, decision_lookup)`. The
`PluginExecutionDecisionLookupPort` is an Approval-owner read-only lookup by the
exact Subject v2/`subjectDigest`; callers cannot supply a tuple or map of
decisions. Before PAP2, the production `PendingOnlyPluginExecutionDecisionLookup`
returns only missing/pending and therefore no executable source can produce an
accepted token. A private test double may return a strict Decision v2 view only
to prove pending/denied routing and the PLC1B mixed-source abort fence; it owns
no store, consumption, import, receipt, or evidence path and is unavailable to
production composition.

The remaining PLC1B types are process-local immutable values rather than new
wire schemas. Their exact field ownership is:

| Record | Owned fields |
| --- | --- |
| `PluginPreflightProposal` | exact authoritative Plan plus `(pluginId, sourceDescriptorFingerprint)`-sorted SourceProposals; no use ID, terminal handle, group, reservation, or gate |
| `PluginDeclarationSourceProposal` | published package ref, exact Source descriptor/fingerprint, complete contribution-ID-sorted Index closure, Product-owned effective configuration entries/fingerprint, exact trust snapshot, requested/allowed authorities, and strict `sourceDisposition = data_only | execution_subject(subject)`; it owns no accepted Gate |
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
all-document selection is the production PLC1B case. Outcome priority is
`rejected > denied > pending_approval > accepted`; diagnostics aggregate all
deterministically sortable findings within the winning arm. A missing current
positive executable decision returns `pending_approval`. Approval recording is
followed by another full call, never mutation or resume of a proposal.

Only `accepted` creates:

- a cryptographically random, non-reused `preflightUseId` encoded as 48
  lowercase hexadecimal characters;
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
aggregate: ACTIVE_OPEN -> CLOSING_ABORT -> ABORTED
                       -> CLOSING_EXPIRE -> EXPIRED
                       -> FINALIZED
group:     PENDING -> CLAIMED -> COMPLETED | FAILED

claim(group, now):
  one lock/CAS checks ACTIVE_OPEN and now < expiresAt
  marks PENDING -> CLAIMED and increments in_flight atomically

settle(group):
  one lock/CAS marks CLAIMED -> COMPLETED | FAILED
  decrements in_flight atomically

finalize(now):
  stage candidates privately
  CAS ACTIVE_OPEN -> FINALIZED only when now < expiresAt,
      every group COMPLETED, and in_flight == 0
  publish/return staged candidates only after the winning CAS

abort or expire:
  CAS ACTIVE_OPEN -> CLOSING_ABORT | CLOSING_EXPIRE
  reject every new group claim and decision consumption
  cancel/settle every CLAIMED group
  when in_flight == 0, complete the selected closing state to its terminal
```

PLC1B processes document groups serially but uses this same claim interface.
PLC3 may add concurrent executable groups without adding a second state owner.
Once close begins, a late completion is recorded for diagnostics and cannot
form evidence accepted by finalize. `now >= expiresAt` is expired; a finalize at
the equality edge cannot win. Closing and finalize never race through a shared
generic `ACTIVE` state: only `ACTIVE_OPEN` is a legal predecessor for either
transition. A finalize CAS loser destroys its private staged candidates and
returns the already-terminal diagnostic; no Candidate escapes before the
winning CAS.

Every terminal operation samples monotonic time before its CAS; at or after the
deadline it must request `CLOSING_EXPIRE`, so a late manual abort cannot mask
expiry. Before the deadline, the first successful closing CAS fixes abort
versus expiry reason. Closing is
help-completable and shielded from caller cancellation: later terminal callers
join/help the same close until all claims settle and the terminal tombstone is
installed. No Approval callback executes while the aggregate lock is held.
PLC3/PAP2 must make decision consumption and
`ExecutionUseReservation(CONSUMED_NOT_STARTED)` one Approval-owner transaction,
then linearize its attempt/group execution-start lease against close using the
documented global lock order. A consumption record additionally carries
`importRealmId` and `hostBootId`; clean-process restart cannot inherit a
possibly-started realm.

The Coordinator is the only caller of terminal operations; the Resolver's
private terminal port owns CAS and retains terminal tombstones through the
current host epoch. Repeated or racing calls deterministically return
`preflight_already_finalized`, `preflight_already_aborted`, or
`preflight_expired`. Monotonic time is authoritative for an in-process deadline;
wall-clock expiry is diagnostic only. Any token from a prior host epoch returns
`preflight_expired`; PLC1B does not add a durable aggregate store. PLC2 may
persist management/audit projections but cannot become a peer terminal owner.

The process owner enforces `maxActiveAttempts = 1024`,
`maxTerminalTombstones = 8192` per host epoch, and
`maxAttemptLifetimeSeconds = 300`. It compacts only unreferenced terminal
tombstones, never an active/closing attempt; ID collision checks cover both
active state and retained tombstones. Capacity exhaustion rejects before an
accepted token is published.

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
unsupported_capability_provider_declaration_payload_version
unsupported_plugin_symbol_reference_version
unsupported_plugin_declaration_source_version
unsupported_plugin_declaration_ir_version
unsupported_plugin_declaration_document_version
unsupported_plugin_execution_approval_subject_version
unsupported_plugin_execution_decision_record_version
unsupported_plugin_declaration_evidence_version
```

Decode priority is deterministic: UTF-8/BOM/JSON/duplicate-key failure first;
then a present version discriminator's strict integer type and supported value;
then union tag; then exact field set and field types; then cross-field/closure
validation; and finally canonical-byte equality. For the known unpublished
legacy Index, Declaration, Subject, Decision, Capability Provider payload, and
symbol-reference shapes, a missing version discriminator maps to that record's
exact `unsupported_*_version` code rather than exact-field mismatch. A present
supported version with a missing peer field is exact-field mismatch. Thus a
Decision with `decisionRecordVersion: 2` and `subjectSchemaVersion: 1` is
`unsupported_plugin_execution_approval_subject_version`; an unversioned
Decision is `unsupported_plugin_execution_decision_record_version`; and an
Evidence with supported `evidenceVersion` but wrong `documentSchemaVersion` is
`unsupported_plugin_declaration_document_version`.

An unknown union tag is not a version error and uses its record-specific
`unsupported_*_kind` diagnostic. Known `in_process_evaluated` evidence in PLC1B
fails `unsupported_plugin_declaration_evidence_kind` before any executable field
can be accepted. Exact-field mismatch, duplicate key, noncanonical bytes,
closure mismatch, and evidence-attempt mismatch remain separate diagnostics.
The manifest parser preserves these typed codec codes and never replaces them
with `invalid_plugin_contribution_index`.

## PLC1B-1 Regression Gate

Implementation begins regression-first and must prove:

1. golden full canonical JSON bytes and fixed digest hex for Source, Index v2,
   Declaration v2, Document v1, Subject v2, Decision v2, document evidence, and
   candidate, covering every domain in the fingerprint table;
2. a real document-backed `capability_provider` package with payload/symbol-
   reference v2 can be written, content-addressed, published, decoded and bound
   by the Host to the exact package digest without any package byte containing
   `packageDigest`; both unpublished v1 shapes fail their exact version code;
3. duplicate keys, BOM, NaN/Infinity, noncanonical bytes, CJK escapes,
   normalization-form distinction, and unpaired surrogates fail or hash exactly
   as specified;
4. pending creates no active fact, the production pre-PAP2 lookup cannot accept
   executable input, and fresh preflight revalidates package, trust policy
   revision, policy, scope, configuration, authority ceiling, and decision;
5. one source with multiple contributions and one package with multiple document
   sources preserve complete declaration closure while candidate selection may
   emit a subset;
6. effective configuration fixtures cover Product override/delete/missing/extra
   entries, stable map ordering, secret-reference rotation, and raw-secret
   rejection without putting secret bytes in hashes or diagnostics;
7. each document source is read exactly once only through
   `VerifiedRevisionHandle.open_file()`, while manifest/Index duplicate keys and
   unsorted items preserve their exact codec diagnostics;
8. claim/settle/finalize/abort/expire barriers cover deadline equality,
   close-versus-claim, close-versus-finalize, caller cancellation, CAS-loser
   candidate destruction, foreign/fake handle rejection, active/tombstone ID
   collision, capacity, and exact terminal diagnostics;
9. old evidence cannot cross `preflightUseId`, and a document candidate cannot
   carry any execution peer field;
10. a mixed PLC1B package, accepted only by the private routing test double, has
    zero import, zero executable declaration ingress, one abort, and zero
    finalization; and
11. architecture scans cover `resources.plugins`, `resources.packages`, and
    `plugin_authoring`; they freeze the one document `open_file()` callpoint and
    prove old public subject/finalize/rollback exports, a second JSON decoder,
    a second Subject builder, non-Coordinator terminal calls, and reservation-
    owned gates are absent.
