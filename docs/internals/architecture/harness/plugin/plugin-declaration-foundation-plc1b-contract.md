# Plugin Declaration Foundation PLC1B Contract

## Status And Authority

This document is the normative implementation contract for the PLC1B
declaration foundation. It refines the
[Unified Plugin Architecture](architecture.md) and the two Plugin
delivery plans without changing their owner model. Where an older plan uses the
ambiguous phrase `declaration_source_fingerprint`, the exact identities below
apply.

The final narrow freeze review accepted the PLC1B-1 core contract at `3f53a5af`
with zero P0/P1. The later inert payload slices extend that same source,
reservation, evidence, and Candidate foundation regression-first; they do not
reopen its authority model. PLC1B-1 through PLC1B-4 are implemented on the
current delivery branch; the contract still grants no later lifecycle or live
owner authority.

PLC1B remains internal and inert. It adds no public Plugin SDK, import path,
owner admission, live Resource/Tool/Command publication, Capability binding,
or MCP behavior.

Source implementation is tracked by
[#481](https://github.com/zhnt/loushang/issues/481).

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
surrogates, null unless that exact schema field explicitly permits it, and a
non-supported version or union tag. In particular, nullable alternatives cannot
stand in for a tagged union arm; the Provider payload's required `disposer`
field is the explicit `SymbolReference v2 | null` exception.
`PluginDeclarationDocument` bytes must equal their canonical re-encoding; thus
whitespace, key-order, escape, or trailing-newline variants are not alternate
accepted encodings. `documentBytesDigest` is SHA-256 of those exact verified
bytes. Semantic declaration and candidate fingerprints are separate logical
identities and never substitute for the bytes digest.

The PLC1B engine ceilings are part of this version: one declaration document is
at most 4,194,304 bytes, contains at most 1,024 declarations, and has JSON
nesting depth at most 64, counting the root object as depth 1 and incrementing
once for each entered object or array. The strict manifest boundary applies duplicate-key
detection before extracting `contributions`; typed Index/Source codec errors
retain their exact diagnostic instead of being collapsed into a generic
manifest error. These are hard safety ceilings, not Product configuration.

One private low-level `StrictPluginJsonCodec` in
`loushang.harness.resources.plugins._strict_json` owns UTF-8/BOM/constant/
duplicate-key/depth decoding and canonical re-encoding. `PluginManifestParser`
uses it with canonical-byte equality disabled, then passes the decoded Index to
the strict Index codec. `PluginDeclarationDocumentCodec`, colocated with the
low-level declaration records under `resources.plugins`, uses the same primitive
with canonical-byte equality required. The higher
`PluginDeclarationCoordinator` imports neither `json` nor a raw JSON decoder:
its one document-group read is exactly one receiver-qualified
`VerifiedRevisionHandle.open_file()` call, after which it calls
`PluginDeclarationDocumentCodec.decode_bytes()`. It never calls `Path.open`,
`read_text`, `read_bytes`, or another byte helper.

This boundary is frozen by an exact import/call edge, not by a decoder-name
heuristic. The Coordinator isolates byte ingress in one private
`_read_and_decode_document(handle: VerifiedRevisionHandle, locator)` method.
That method contains exactly one `handle.open_file(locator)`, one read from the
returned stream, and one direct
`PluginDeclarationDocumentCodec.decode_bytes(verified_bytes)` call; it accepts
no reader or decoder callback and makes no other call. `decode_bytes` is the
stateless class/static schema-codec entrypoint. The Coordinator stores no codec
instance or codec-valued attribute, so there is no constructor injection,
instance rebinding, property, or dynamic override seam. The Coordinator
directly and without an alias imports that codec from
`resources.plugins.declarations` and `VerifiedRevisionHandle` from
`resources.plugins.revisions`; neither imported name may be rebound.
The Coordinator module permits no wildcard import, because its exported names
could shadow either exact boundary binding.
Architecture tests verify the handle annotation and receiver, freeze those three call edges,
scan raw-decoder symbol references (including module/import/assignment aliases),
and reject every helper call from this method even when its import lives outside
the three package-boundary directories. A helper therefore cannot create a peer
decode route. A real `VerifiedRevisionHandle` integration fixture separately
proves the static receiver constraint at runtime.

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

The payload v2 has exactly:

| Key | Type/value |
| --- | --- |
| `bindingInputs` | strict JSON object exactly equal to the selected Index item's package-default `configuration` |
| `disposer` | required key; exact SymbolReference v2 object or JSON `null` |
| `factory` | exact SymbolReference v2 object |
| `payloadVersion` | integer `2` |
| `provider` | exact `CapabilityBundleProvider` owner-schema object |

V2 removes the redundant v1 `configurationFingerprint`: the domain-wrapped
`reservationFingerprint` already binds package-default configuration, while
`configurationMapFingerprint` separately binds Product-effective configuration
after publication. Missing `disposer`, a null `factory`, or a null/unknown peer
field fails the exact diagnostics below. Neither the payload nor either symbol
reference contains `packageDigest`. Host
validation binds every reference to the selected package's exact content digest
and the Index item's `contributionExecutionModel` before a resolved-symbol view
can exist. This is structural provenance validation only; symbol resolution,
callable loading and import remain deferred to the Component Host. The
unpublished payload/symbol-reference v1 shapes fail closed; no source-kind-
specific decoder or compatibility alias remains.

### `PluginContributionIndex` v2

The envelope has exactly `items` and `version`, with `version: 2`. `items` is
sorted by contribution `id`, contains no duplicate ID, and each item has exactly:

| Key | Type |
| --- | --- |
| `configuration` | strict JSON object containing no secret material |
| `contributionExecutionModel` | exact `"data_only"` or `"in_process"` contributed-runtime tag; `capability_provider` and the exact-owner `continuity_provider` require `"in_process"`, while `resource_item`, `tool_pack`, and `command_pack` require `"data_only"` |
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

`contributionExecutionModel` is the package security envelope's independent
authority. It is not inferred from `declarationSource.kind` or copied from an
owner payload. Capability Provider factory/disposer references must exact-match
it; thus a document source may safely declare an in-process Provider factory
without making document decoding executable.

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

### `resource_item` payload v1

`resource_item` is one contribution kind with an independent owner-controlled
subtype; no Resource subtype is a Plugin type, numeric type code, capability
bit, executable Definition, Tool, Command, or Graph node. Its payload has
exactly:

| Key | Type/value |
| --- | --- |
| `locator` | canonical contained revision-root-relative path |
| `locatorKind` | exact `"file"` or `"directory"` |
| `mediaType` | non-empty canonical media-type string |
| `ownerNamespace` | canonical Resource owner namespace; exact-matches Declaration `owner` |
| `payloadVersion` | integer `1` |
| `resourceKind` | exact `"skill"`, `"prompt"`, `"method"`, `"theme"`, `"asset"`, or `"source"` |
| `schemaId` | canonical owner-schema identifier |
| `schemaVersion` | positive non-boolean integer |

`skill` accepts either a directory locator or a file named `SKILL.md`;
`prompt` and `method` require Markdown file locators; `theme` requires a JSON
file locator. `asset` and raw `source` accept either exact locator kind and let
their Resource owner interpret the declared media/schema identity. Host
resolution exact-matches `locatorKind` through the accepted package's
`VerifiedRevisionHandle.entry_kind()` without reading or publishing the
Resource.

The payload carries no package digest, Product/scope facts, executable symbol,
live descriptor, registry, nested contribution, authority list, or copied
configuration fingerprint. Its enclosing Candidate already binds the exact
package digest and SourceGroup evidence; that group fingerprint transitively
binds the closure-local effective `configurationMapFingerprint`. A
`resource_item` Index reservation therefore requires
`contributionExecutionModel: "data_only"` and an empty
`requestedAuthorities` list. It may be declared by either document or
preflighted in-process source, but the Resource itself is never executed by
PLC1B-2.

### Catalog Consumer payload v1

`tool_pack` and `command_pack` are sibling contribution kinds sharing one
strict Catalog Consumer primitive. The outer Declaration kind remains the only
Tool-versus-Command tag; the payload does not repeat it as a peer type code.
The `tool_pack` payload has exactly:

| Key | Type/value |
| --- | --- |
| `catalogId` | canonical owner-controlled Tool catalog identifier |
| `catalogRevision` | positive non-boolean pinned catalog revision |
| `ownerNamespace` | canonical Tool owner namespace; exact-matches Declaration `owner` |
| `payloadVersion` | integer `1` |
| `requirements` | Capability-ID-sorted unique list of exact `CapabilityRequirement` records |
| `tools` | non-empty sorted unique list of canonical Tool identities |

The `command_pack` payload substitutes these two exact fields and otherwise
uses the same record:

| Key | Type/value |
| --- | --- |
| `catalogId` | canonical owner-controlled Command catalog identifier |
| `catalogRevision` | positive non-boolean pinned catalog revision |
| `commands` | non-empty sorted unique list of canonical Command identities |
| `ownerNamespace` | canonical Command owner namespace; exact-matches Declaration `owner` |
| `payloadVersion` | integer `1` |
| `requirements` | Capability-ID-sorted unique list of exact `CapabilityRequirement` records |

Each requirement has exactly `binding`, `capability`, `compatibleContract`,
`facets`, and `optional`. `capability` and every facet are canonical
identifiers; `binding` is `"direct"` or `"stable_reference"`;
`compatibleContract` has exact positive non-boolean integer `minimum` and
`maximum` fields with `maximum >= minimum`; `facets` is a non-empty sorted
unique string list; and `optional` is boolean. These requirement facets are the
only Capability-use request in the payload. Duplicate Capability identities
within one pack fail instead of being merged. The inert codec performs no
transitive Graph walk; PLC4 passes owner-normalized requirements to the existing
Graph Planner through the Product Consumer-root compiler.

One internal `plugin_authoring.capability_requirement` codec owns the shared
contract-range and requirement wire mapping. Capability Provider and Catalog
Consumer codecs are sibling clients of it; neither imports the other and no
second Tool-specific or Command-specific requirement parser exists.

Both contribution kinds require `contributionExecutionModel: "data_only"` and
an empty `requestedAuthorities` list. Catalog identity/revision, item IDs, and
requirements are strict data only. The payload contains no activation choice,
Resource locator, Tool schema/handler, Command callback, Provider, admission,
registry, service bag, Graph, Session, executable symbol, package digest, or
configuration fingerprint. Product selection owns activation. PLC1B-3 is
catalog-reference-only; a future owner-approved executable or file-backed
definition requires a separately versioned owner schema and cannot be smuggled
through these fields. A separate `resource_item` may hold source bytes, but it
does not mint the Tool or Command identity.

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
| `ambientHostAuthority` | boolean derived from the accepted execution posture; PLC1B `in_process` Subject is `true` |
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

Candidate construction is private to Resolver finalization and enforces all of
these invariants before hashing: the package ref content digest equals Evidence
`packageContentDigest`; Evidence was created for the same claimed
SourceGroup/attempt/reservation closure and exact verified Batch; the
Declaration fingerprint is a member of that Batch's validated declaration set;
and Candidate `sourceGroupFingerprint` is derived only from that Evidence, not a
peer caller value. Owner admission receives this trusted process-local
projection; no public constructor may combine package A, declaration A, and
evidence B.

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
| `configurationMapFingerprint` | domain `loushang.plugin-group-configuration/v1`; `configurations` = the current SourceProposal/SourceGroup's complete reservation-closure projection, encoded as `(pluginId, contributionId)`-sorted exact Product-owned effective entries `{configuration, contributionId, pluginId}` |
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
The executable Source wrapper used by the Subject sentinel has canonical bytes:

```json
{"domain":"loushang.plugin-declaration-source-descriptor/v1","source":{"entrypoint":"definition.py:define","kind":"in_process","sourceVersion":1}}
```

Their SHA-256 is
`c24ebbab018030bda115eee4257003ef8ac86423faa480fe158bce31fc0377b7`.
The complete, cross-field-valid Subject sentinel canonical bytes are:

```json
{"domain":"loushang.plugin-execution-approval-subject/v2","subject":{"allowedAuthorityCeiling":["process.launch"],"ambientHostAuthority":true,"configurationMapFingerprint":"1111111111111111111111111111111111111111111111111111111111111111","dependencyLockDigest":"2222222222222222222222222222222222222222222222222222222222222222","entrypoint":"definition.py:define","instanceRevisionRef":{"instanceId":"coding.lsp@product","pluginId":"coding.lsp","revision":1},"packageContentDigest":"3333333333333333333333333333333333333333333333333333333333333333","packageSourceIdentity":"registry:example","pluginId":"coding.lsp","policyRevision":"policy-1","productId":"coding","requestedAuthorities":["process.launch"],"reservationClosureFingerprint":"4444444444444444444444444444444444444444444444444444444444444444","schemaVersion":2,"scopeId":"workspace","sourceDescriptorFingerprint":"c24ebbab018030bda115eee4257003ef8ac86423faa480fe158bce31fc0377b7","sourceTrustClass":"registry_signed","sourceTrustPolicyRevision":"trust-1"}}
```

Their SHA-256 is
`cfa8e2bbeb73cc55c4e67149c4d6bc0b452b7d93c9d76bfa2bb610a3ebd330fb`.
The Candidate sentinel canonical bytes are:

```json
{"declarationFingerprint":"2fe5d856380b78228e5d3baeb5227598e19268f403c4765e12e99e2567381217","domain":"loushang.plugin-contribution-candidate/v2","evidenceFingerprint":"5555555555555555555555555555555555555555555555555555555555555555","packageContentDigest":"3333333333333333333333333333333333333333333333333333333333333333","sourceGroupFingerprint":"6666666666666666666666666666666666666666666666666666666666666666"}
```

Their SHA-256 is
`bab38106e94908a0e7385da2c5576aa3ce0898348a0521aec1c83d3d8732fb3c`.

## Contribution Semantic Fingerprint v1

`PluginContributionSemanticFingerprint` is the separate pre-owner/pre-Host
conformance diagnostic defined by UPA. The declaration compiler is its sole
constructor. Callers provide one `PluginDeclaration`; they cannot separately
supply a schema identity, schema version, catalog identity, catalog revision,
or already-normalized payload. The compiler first decodes through the one
strict kind-specific payload codec, exact-matches its owner facts, and then
re-encodes that typed payload before hashing.

Version 1 hashes the strict canonical JSON bytes of exactly this logical
record (shown structurally rather than as golden canonical bytes):

```text
{
  "catalogRevisions": [],
  "domain": "loushang.plugin-contribution-semantic/v1",
  "kind": "resource_item",
  "owner": "resources.prompt",
  "payload": {},
  "payloadSchema": {"id": "loushang.resource.prompt", "version": 1}
}
```

The empty objects are illustrative typed-value positions, not permissive
payloads. The exact projection is:

| Contribution kind | `payloadSchema` | `catalogRevisions` |
| --- | --- | --- |
| `resource_item` | exact payload `schemaId` and `schemaVersion`, under the exact-matched Resource owner namespace | `[]` |
| `tool_pack` | `<Declaration owner>.tool-pack`, version equal to payload `payloadVersion` | one entry derived from exact payload `catalogId`/`catalogRevision` |
| `command_pack` | `<Declaration owner>.command-pack`, version equal to payload `payloadVersion` | one entry derived from exact payload `catalogId`/`catalogRevision` |
| `capability_provider` | `<Declaration owner>.capability-provider`, version equal to payload `payloadVersion` | `[]` |
| `continuity_provider` | `harness.continuity.continuity-provider`, version equal to payload `payloadVersion` | `[]` |

Catalog records have exactly `catalog` and positive-integer `revision`, are
identity-sorted, and reject duplicate identities. Empty catalog use is always
the literal empty list. Schema and catalog facts therefore cannot drift from
the payload through a peer argument. The algorithm uses the existing strict
canonical JSON encoder: sorted keys, compact separators, `allow_nan: false`,
`ensure_ascii: true`, UTF-8 hashing, and no Unicode normalization.

For the fixed CJK Resource payload whose locator is `prompts/编码.md`, canonical
bytes are:

```json
{"catalogRevisions":[],"domain":"loushang.plugin-contribution-semantic/v1","kind":"resource_item","owner":"resources.prompt","payload":{"locator":"prompts/\u7f16\u7801.md","locatorKind":"file","mediaType":"text/markdown","ownerNamespace":"resources.prompt","payloadVersion":1,"resourceKind":"prompt","schemaId":"loushang.resource.prompt","schemaVersion":1},"payloadSchema":{"id":"loushang.resource.prompt","version":1}}
```

Their SHA-256 is
`4f2924b72efe84918324a0b37a3c70921b6584a8c390d343bd702d9791e4e1b1`.
Otherwise identical locators containing precomposed `café` and combining
`cafe\u0301` hash respectively to
`ca6d0cda904d6289148c26acb48996a90dcfea9012b98ab4002bd3c7b5072928` and
`df8f5399b527fa31a2a99fac3e7fb61e04ec057ed92a1fb2e7114f767c8d1023`.
An unpaired surrogate fails the strict declaration-data boundary before any
semantic digest can be produced.

This diagnostic excludes the Declaration's `pluginId`/`contributionId`
envelope fields, package revision, declaration source, reservation, execution
evidence, Product/scope and admission facts. Exact semantic fields already
inside a typed payload remain part of that payload; the compiler does not strip
or reinterpret them. The diagnostic grants no identity, compatibility,
selection, approval, owner admission, catalog resolution, binding, or
execution authority and does not replace any fingerprint in the table above.
Complete Declaration and Candidate fingerprints remain source/reservation/
evidence-bound.

## Preflight Context, Attempts, And Ownership

PLC1B introduces the pure data `PluginPreflightContextV1` with exactly
`contextVersion: 1`, non-empty string `productId`, `scopeId`, and
`policyRevision`, plus `instanceRevisionRefs`: a Plugin-ID-sorted non-empty
tuple of exact `PluginInstanceRevisionRef` values. The Product
composition input supplies exactly one ref for every selected Plugin ID and no
extra ref; duplicate Plugin IDs, instance IDs, or refs fail closed. The exact
sort key is `(pluginId, instanceId, revision)`. PLC1B validates complete
one-to-one coverage and does not invent or persist these values. PLC2 makes the
same identity durable and owns its lifecycle without changing its meaning or
fingerprint.

`PluginSelectionPlanV2` is the sole Product authority passed to `preflight()`.
Its frozen process-local dataclass has exactly `planVersion: 2`, `context`,
`selectedPluginIds`, `selectedContributions`, `sourceTrustSnapshots`,
`effectiveConfigurationSet`, and `allowedAuthorityCeiling`. Plugin IDs and the
authority ceiling are sorted unique non-empty string tuples; contributions are
strictly `(pluginId, contributionId)`-sorted exact refs. It owns exactly one
Context rather than peer `productId`/`scopeId`/policy arguments. A
`PluginSourceTrustSnapshotV1` has exactly `trustSnapshotVersion: 1`, `pluginId`,
`packageSourceIdentity`, `sourceTrustClass`, `sourceTrustPolicyRevision`, and
boolean `trusted`; it must
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
deletes, sensitivity classification, and secret resolution policy before
preflight. PLC1B receives only the already-resolved frozen
`PluginEffectiveConfigurationSetV1` with exactly
`configurationSetVersion: 1` and `entries`. Each entry has exactly
`configuration`, `contributionId`, and `pluginId`; entries are strictly sorted
by `(pluginId, contributionId)` and exactly cover the union of every proposed
source reservation closure in the Plan. For each SourceProposal/SourceGroup,
PLC1B projects exactly the entries in that source's complete reservation
closure and computes `configurationMapFingerprint` from that local sorted
projection. There is no Plan-global configuration fingerprint and a group may
not hash or retain another group's entries. Consequently changing only group B
configuration does not change group A's configuration fingerprint, group
fingerprint, Subject, or approval lookup key unless A and B are the same source
closure. PLC1B validates and hashes these projections; it has no overlay,
delete, merge, or sensitivity-classification algorithm and accepts no peer `overlays`
argument. A secret value never enters this map. At any nesting depth, an object
containing `$secretRef` must contain only that key, whose value is the exact
tagged reference
`{"$secretRef":{"authorityClass":...,"providerId":...,"referenceId":...,
"rotationEpoch":...,"secretReferenceVersion":1}}`, where the first three
values are non-empty strings and `rotationEpoch` is a non-negative non-boolean
integer. PLC1B rejects malformed tagged references but cannot infer whether an
ordinary JSON string is sensitive. The Product configuration owner must reject
raw values at schema-sensitive paths before constructing the Set; the PLC1B
integration fixture proves that owner handoff, while PLC1B fixtures prove only
tag structure and that no resolved secret reaches its input, digest, or
diagnostic.

Preflight has the single logical signature
`preflight(packages, bindings, plan, decision_lookup)`. The
`PluginExecutionDecisionLookupPort` is an Approval-owner read-only lookup by the
exact Subject v2/`subjectDigest`; callers cannot supply a tuple or map of
decisions. Its strict result is `missing` or `current(DecisionRecordV2)`. The
Approval owner projects exactly one latest effective, unexpired, unrevoked,
unconsumed record for that Subject; owner corruption yielding multiple current
records is `rejected`, an effective denial is `denied`, and an already-consumed
approval is `missing` rather than reusable. Before PAP2, the production
`PendingOnlyPluginExecutionDecisionLookup`
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
| `AcceptedPluginPreflight` | `preflightUseId`, `hostBootId` (also typed locally as `hostEpoch`), monotonic deadline, exact Context, identity-sorted SourceGroups, and opaque internal terminal handle |
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

- a cryptographically random `preflightUseId` encoded as 48 lowercase
  hexadecimal characters, collision-checked against active and retained
  tombstone IDs in the current boot;
- one 32-lowercase-hex `hostBootId` (the process-local `hostEpoch` is this same
  value, never a second identity) and monotonic `expiresAt` deadline;
- one internal terminal handle;
- one process-owner expiry task/reaper registered before the accepted value can
  become visible;
- exact attempt-bound SourceGroups; and
- one-use reservations that carry only `sourceGroupId` and
  `sourceGroupFingerprint` references.

The accepted SourceGroup exclusively owns its `data_only` or
`execution_preflight` gate. The stable group fingerprint excludes the attempt
nonce; the group ID, evidence, Batch, and Candidate bind the attempt. Finalize
requires every evidence `preflightUseId` and `sourceGroupId` to match the current
ACTIVE_OPEN token and atomically marks those evidence uses terminal. Mismatch fails
`plugin_declaration_evidence_attempt_mismatch`.

## Aggregate Claim And Terminal Protocol

The private Resolver state and the Coordinator use one linearizable protocol:

```text
aggregate: ACTIVE_OPEN -> CLOSING_ABORT -> ABORTED
                       -> CLOSING_EXPIRE -> EXPIRED
                       -> FINALIZED
group:     PENDING -> CLAIMED -> COMPLETED | FAILED

claim(group, now):
  one lock/CAS checks ACTIVE_OPEN
  if now >= expiresAt, CAS to CLOSING_EXPIRE and join/help close
  otherwise
    marks PENDING -> CLAIMED and increments in_flight atomically
    returns one opaque PluginGroupClaimLease to the execution unit

settle(claim_lease, actual_worker_completion):
  only the execution unit's shielded completion/finally may settle
  one lock/CAS marks CLAIMED -> COMPLETED | FAILED exactly once
  decrements in_flight atomically

finalize(now):
  stage candidates privately
  CAS ACTIVE_OPEN -> FINALIZED only when now < expiresAt,
      every group COMPLETED, and in_flight == 0
  publish/return staged candidates only after the winning CAS

abort or expire:
  CAS ACTIVE_OPEN -> CLOSING_ABORT | CLOSING_EXPIRE
  reject every new group claim and execution-start permit
  request cancellation of every CLAIMED group; closer never settles for worker
  wait for each claim lease's actual completion acknowledgement
  only when in_flight == 0, complete closing state to its terminal
```

PLC1B processes document groups serially but uses this same claim interface.
PLC3 may add concurrent executable groups without adding a second state owner.
Once close begins, a late result is discarded for publication and recorded for
diagnostics, while its execution unit must still acknowledge physical exit and
settle its own claim. Cancellation request is not completion: a cancellation-
resistant worker delays the terminal; an isolated worker may acknowledge only
after confirmed process termination. A closer cannot decrement on its behalf.
`now >= expiresAt` is expired; a finalize at
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
installed. The Coordinator also requests abort/expiry in a shielded `finally`,
but the process-owner reaper is authoritative if cancellation occurs after
acceptance and before Coordinator handoff, or if the internal handle is dropped.
No Approval callback executes while the aggregate lock is held.

The Coordinator is the only caller of terminal operations; the Resolver's
private terminal port owns CAS and retains terminal tombstones through the
current host boot. During `CLOSING_*`, claim returns `preflight_closing`, while
finalize/abort/expire joins the close and then returns the exact terminal result.
Repeated or racing calls deterministically return
`preflight_already_finalized`, `preflight_already_aborted`, or
`preflight_expired`. Monotonic time is authoritative for an in-process deadline;
wall-clock expiry is diagnostic only. Any token from a prior host boot returns
`preflight_expired`; PLC1B does not add a durable aggregate store. PLC2 may
persist management/audit projections but cannot become a peer terminal owner.

The process owner enforces `maxActiveAttempts = 1024`,
`maxTerminalTombstones = 8192` per host boot, and
`maxAttemptLifetimeSeconds = 300`. It compacts only unreferenced terminal
tombstones, never an active/closing attempt; ID collision checks cover both
active state and retained tombstones. After compaction, uniqueness relies on
192-bit random collision resistance rather than an unbounded historical ID set.
Capacity exhaustion rejects before an accepted token is published.

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

The same higher layer exposes exactly one production composition entry,
`PluginDeclarationHost.resolve()`. One Host instance constructs and retains one
Resolver/Coordinator pair. It passes `pending_approval`, `denied`, and
`rejected` through as their existing immutable outcome arms, but it transfers
`accepted` directly to the Coordinator and exposes only `PluginSelection` on
success. It never writes an Approval decision or returns the accepted token to
Product code. Before PLC3, an executable accepted arm therefore still follows
the Coordinator's typed `execution_not_consumed` aggregate abort fence.

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

The executable worker first owns a `PluginGroupClaimLease`, then requests one
opaque `PluginExecutionStartPermit` from the aggregate lock. This permit is the
start linearization point:

- if `ACTIVE_OPEN` wins before close/deadline, the permit is issued and close
  may subsequently enter `CLOSING_*` but must wait for this in-flight worker;
- if close/deadline wins first, no permit is issued, no Approval transaction or
  loader call is legal, and the worker settles its claim as failed; and
- the aggregate lock is released before any Approval call. The logical order is
  aggregate start permit, then Approval transaction, then Plugin-instance
  lifecycle, then import-realm gate. The Approval transaction commits and
  releases before later lifecycle/import locks; those later locks may nest only
  in the stated order.

After a permit wins, one Approval-owner transaction consumes the decision and
creates its exact durable `ExecutionUseReservation` in
`CONSUMED_NOT_STARTED`. A close that begins afterward does not revoke the
already-issued permit or reject this permitted consumption; it waits for actual
worker completion. `ExecutionUseReservation` v1 has exactly:

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

`executionUseVersion` is integer `1`; `executionUseId` is fresh 48-lowercase-
hex; `hostBootId` is the accepted attempt's 32-lowercase-hex boot identity;
`importRealmId` is a fresh 32-lowercase-hex interpreter/import-ledger realm
identity unique within that boot; revisions/IDs/digests exact-match the
Decision, Subject, attempt and group; `revocationEpoch` is a non-negative non-
boolean integer. Its durable state is:

```text
CONSUMED_NOT_STARTED -> CANCELLED_BEFORE_START
                     -> STARTING -> EVALUATED
                                 -> FAILED_AFTER_START
```

`STARTING` commits before invoking the loader. Recovery treats `STARTING` and
`FAILED_AFTER_START` as possibly executed and marks the import realm polluted.
An external `hostBootId` in `CONSUMED_NOT_STARTED` can only transition to
`CANCELLED_BEFORE_START`; it is never resumed. A permit winner that crashes
before creating a use leaves no durable consumption; one that crashes after the
transaction but before `STARTING` is reconciled to that same before-start
terminal. `hostEpoch` is only the process-local typed name for `hostBootId`, and
the two must never diverge; `importRealmId` is subordinate to one boot and is not
an epoch alias.

Only an exact current-realm `EVALUATED` use constructs
`PluginExecutionConsumptionReceipt` v1 with exactly:

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

`receiptVersion` is integer `1` and `state` is exact `"EVALUATED"`; all other
fields exact-match the terminal Reservation. Both Reservation and Receipt
therefore carry `hostBootId` and `importRealmId`; the receipt is embedded in
`in_process_evaluated` Evidence and its fingerprint.

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
unsupported_continuity_provider_declaration_payload_version
unsupported_resource_item_declaration_payload_version
unsupported_tool_pack_declaration_payload_version
unsupported_command_pack_declaration_payload_version
unsupported_plugin_symbol_reference_version
unsupported_plugin_declaration_source_version
unsupported_plugin_declaration_ir_version
unsupported_plugin_declaration_document_version
unsupported_plugin_execution_approval_subject_version
unsupported_plugin_execution_decision_record_version
unsupported_plugin_declaration_evidence_version
```

## Exact Non-Version Diagnostics

The finite non-version codes are:

```text
plugin_declaration_invalid_utf8
plugin_declaration_utf8_bom
plugin_declaration_invalid_json
plugin_declaration_invalid_json_constant
plugin_declaration_duplicate_json_key
plugin_declaration_json_depth_exceeded
plugin_declaration_document_too_large
plugin_declaration_document_too_many_declarations
plugin_declaration_exact_field_mismatch
plugin_declaration_field_type_mismatch
plugin_declaration_field_value_mismatch
unsupported_plugin_declaration_source_kind
unsupported_plugin_contribution_kind
unsupported_plugin_contribution_execution_model
unsupported_resource_item_kind
unsupported_resource_item_locator_kind
unsupported_plugin_declaration_evidence_kind
plugin_contribution_index_unsorted
duplicate_plugin_contribution_identity
plugin_declaration_document_unsorted
duplicate_plugin_declaration_identity
plugin_declaration_cross_field_mismatch
plugin_declaration_closure_mismatch
plugin_declaration_noncanonical_bytes
plugin_declaration_evidence_attempt_mismatch
invalid_plugin_effective_configuration
```

The condition-to-code mapping is normative and exhaustive for PLC1B:

| Validation condition | Exact diagnostic |
| --- | --- |
| bytes are not UTF-8 | `plugin_declaration_invalid_utf8` |
| UTF-8 BOM is present | `plugin_declaration_utf8_bom` |
| JSON syntax or trailing input is invalid | `plugin_declaration_invalid_json` |
| NaN or Infinity constant is present | `plugin_declaration_invalid_json_constant` |
| an object contains a duplicate key | `plugin_declaration_duplicate_json_key` |
| nesting exceeds the frozen limit | `plugin_declaration_json_depth_exceeded` |
| document byte length exceeds the frozen limit | `plugin_declaration_document_too_large` |
| declaration count exceeds the frozen limit | `plugin_declaration_document_too_many_declarations` |
| a supported-version object has a missing or extra key | `plugin_declaration_exact_field_mismatch` |
| a field has the wrong JSON type, a forbidden null, or a boolean in an integer field | `plugin_declaration_field_type_mismatch` |
| an individually validated field violates its value domain, including an empty/invalid identifier, digest width/case, integer range, canonical contained locator/symbol path, or a field-level sorted-unique list such as `requestedAuthorities` | `plugin_declaration_field_value_mismatch` |
| Source union tag is unknown | `unsupported_plugin_declaration_source_kind` |
| contribution kind is unknown | `unsupported_plugin_contribution_kind` |
| contributed execution-model tag is unknown or incompatible with its contribution kind | `unsupported_plugin_contribution_execution_model` |
| Resource subtype tag is unknown | `unsupported_resource_item_kind` |
| Resource locator-kind tag is unknown | `unsupported_resource_item_locator_kind` |
| Evidence union tag is unknown or not enabled in this slice | `unsupported_plugin_declaration_evidence_kind` |
| Index `items` are not contribution-ID sorted | `plugin_contribution_index_unsorted` |
| Index contains duplicate contribution identity | `duplicate_plugin_contribution_identity` |
| Document `declarations` are not `(pluginId, contributionId)` sorted | `plugin_declaration_document_unsorted` |
| Document contains duplicate declaration identity | `duplicate_plugin_declaration_identity` |
| individually valid peer fields disagree, including Source fields, Provider owner metadata versus Declaration owner/source, or factory/disposer model versus Index model | `plugin_declaration_cross_field_mismatch` |
| declaration/reservation/source set does not equal its complete expected closure | `plugin_declaration_closure_mismatch` |
| otherwise valid document bytes differ from canonical re-encoding | `plugin_declaration_noncanonical_bytes` |
| Evidence attempt/group/use identity does not match the active accepted attempt | `plugin_declaration_evidence_attempt_mismatch` |
| effective configuration coverage, entry identity, or exact `$secretRef` form is invalid | `invalid_plugin_effective_configuration` |

An unsupported or missing version discriminator uses the record-specific
`unsupported_*_version` code listed above. A discriminator with the wrong JSON
type uses `plugin_declaration_field_type_mismatch`. The specialized kind,
execution-model, ordering, duplicate, closure, Evidence-attempt, and effective-
configuration rows override the general value/cross-field rows, so no invalid
condition in the table can be assigned two codes.

Decode priority is deterministic: UTF-8/BOM/JSON/duplicate-key failure first;
then a present version discriminator's strict integer type and supported value;
then union tag; then exact field set, field types, and field values; then the
specialized ordering/duplicate checks; then cross-field/closure validation;
and finally canonical-byte equality. For the known unpublished
legacy Index, Declaration, Subject, Decision, Capability Provider payload,
Resource Item payload, Tool/Command pack payload, and symbol-reference shapes,
a missing version discriminator maps to that record's
exact `unsupported_*_version` code rather than exact-field mismatch. A present
supported version with a missing peer field is exact-field mismatch. Thus a
Decision with `decisionRecordVersion: 2` and `subjectSchemaVersion: 1` is
`unsupported_plugin_execution_approval_subject_version`; an unversioned
Decision is `unsupported_plugin_execution_decision_record_version`; and an
Evidence with supported `evidenceVersion` but wrong `documentSchemaVersion` is
`unsupported_plugin_declaration_document_version`.

Nested order is also fixed. Index envelope/version precedes item field/type,
contribution kind/model, then nested Source version/kind/cross-field checks;
order/duplicate/closure checks follow successful item decoding. Generic
Declaration decoding precedes owner payload decoding. Resource Item payload
version precedes its subtype, exact field set, field types, locator-kind and
subtype-specific path constraints, then reservation/package cross-field checks.
Tool/Command pack payload version precedes its exact field set, field types,
catalog/item canonicalization, nested typed requirements, and finally
reservation/owner cross-field checks. Nested requirement contract ranges and
facets decode before pack requirement ordering and duplicate checks.
Capability Provider payload version precedes its field set/types, then Provider
metadata, required factory, and finally required nullable disposer. A missing
disposer is `plugin_declaration_exact_field_mismatch`; `disposer: null` is
valid; a null factory is `plugin_declaration_field_type_mismatch`.

An unknown union tag is not a version error and uses its record-specific
exact finite `unsupported_*_kind` diagnostic above. Known
`in_process_evaluated` evidence in PLC1B
fails `unsupported_plugin_declaration_evidence_kind` before any executable field
can be accepted. Exact-field mismatch, duplicate key, noncanonical bytes,
closure mismatch, and evidence-attempt mismatch remain separate diagnostics.
The manifest parser preserves these typed codec codes and never replaces them
with `invalid_plugin_contribution_index`: `PluginManifestError.code` is the
unchanged nested code and its path adds manifest location only.

## PLC1B-1 Regression Gate

Implementation begins regression-first and must prove:

1. golden full canonical JSON bytes and fixed digest hex for Source, Index v2,
   Declaration v2, Document v1, Subject v2, Decision v2, document evidence, and
   candidate, covering every domain in the fingerprint table;
2. a real document-backed `capability_provider` package with payload/symbol-
   reference v2 can be written, content-addressed, published, decoded and bound
   by the Host to the exact package digest without any package byte containing
   `packageDigest`; its Index independently binds
   `contributionExecutionModel`; absent/present disposer v2 fixtures are exact;
   and both unpublished v1 shapes fail their exact version code;
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
   entries, stable map ordering, two independent SourceGroups proving that a
   group-B-only change leaves group A's configuration/group/Subject digests
   unchanged, secret-reference rotation, malformed tagged
   references, and Product-owner raw-secret rejection before PLC1B handoff,
   without putting secret bytes in PLC1B hashes or diagnostics;
7. each document source is read exactly once only through the Coordinator's
   receiver-qualified `VerifiedRevisionHandle.open_file()`, the sole low-level
   strict JSON primitive serves manifest/document codecs, the private byte-
   ingress method has only the exact three call edges above, assignment/module/
   third-party decoder aliases, mutable codec-instance routes, import shadowing
   and imported helper routes fail the architecture
   gate, a real verified-handle fixture proves the receiver, and manifest/Index
   duplicate keys and unsorted items preserve their exact diagnostics;
8. claim/settle/finalize/abort/expire barriers cover deadline equality,
   close-versus-claim, close-versus-finalize, caller cancellation, CAS-loser
   candidate destruction, cancellation-resistant worker completion, accepted-
   before-handoff cancellation, reaper-driven expiry, dropped handles,
   foreign/fake handle rejection, active/tombstone ID collision, capacity, and
   exact terminal diagnostics;
9. old evidence cannot cross `preflightUseId`, and a document candidate cannot
   carry any execution peer field;
10. a mixed PLC1B package, accepted only by the private routing test double, has
    zero import, zero executable declaration ingress, one abort, and zero
    finalization; and
11. architecture scans cover `resources.plugins`, `resources.packages`, and
    `plugin_authoring`; exact import/call edges freeze exactly one Coordinator
    document `open_file()`, stream read and document-codec call, reject `Path`
    reads, raw decoder symbol aliases, `JSONDecoder.decode`, third-party
    decoders or any helper call from byte ingress, and prove old public subject/
    finalize/rollback exports, a second decoder, Subject builder,
    non-Coordinator terminal caller, or reservation-owned gate is absent; and
12. PAP2/PLC3 barrier fixtures (before executable ingress is enabled) cover
    permit-before-close, close-before-permit, close between permit/Approval/
    `STARTING`, `CANCELLED_BEFORE_START` recovery, transaction atomicity, exact
    boot/realm receipt fields, and no loader call without both permit and
    committed `STARTING`.

## PLC1B-2 Regression Gate

PLC1B-2 additionally proves:

1. all six `resourceKind` arms round-trip through the exact payload-v1 field
   set and strict canonical Declaration/Document bytes;
2. missing/unsupported payload version, unknown Resource/locator kind, extra or
   missing fields, wrong JSON types, invalid owner/schema/media facts, absolute,
   Windows, traversing, or subtype-incompatible paths fail with the exact
   diagnostics above;
3. the Index accepts `resource_item` only as `data_only` and authority-free,
   while declaration source remains an independent document/in-process fact;
4. the reservation-bound Builder consumes one Resource reservation once, and a
   document-backed package reaches an inert Candidate without Definition
   import, Resource generation, RegistrationScope, Tool/Command registration,
   Model Input, or other live effect;
5. the candidate/reservation bridges exact-match Declaration owner and envelope,
   Resource `ownerNamespace`, contribution execution model, empty authority set,
   and the verified package entry kind; and
6. no Resource payload field can encode a nested contribution, callable,
   executable symbol, package digest, copied configuration fingerprint, owner
   admission, registry, Tool, Command, Capability, or Plugin instance.

## PLC1B-3 Regression Gate

PLC1B-3 additionally proves:

1. Tool and Command packs use one shared Catalog Consumer parser/binder with
   distinct exact `tools`/`commands` wire field sets and record-specific payload
   version diagnostics;
2. catalog identity/revision, owner namespace and item identities round-trip
   canonically; missing/extra fields, wrong types, unsorted/duplicate/empty
   items, invalid identifiers and unsupported versions fail with the exact
   diagnostics above;
3. typed requirements preserve contract bounds, requested facets, optionality
   and binding, require Capability-ID order, and reject duplicate identities;
4. the Index accepts `tool_pack` and `command_pack` only as `data_only` and
   authority-free, while declaration source remains independently document or
   in-process;
5. the reservation-bound Builder consumes each sibling contribution exactly
   once, and document-backed packs reach inert Candidates without catalog
   resolution, Tool/Command construction or registration, Provider lookup,
   Graph planning, Session access, Definition import, or MCP behavior;
6. Candidate/reservation bridges exact-match Declaration kind, owner/source/
   reservation envelope and payload `ownerNamespace`; and
7. a Capability Provider payload explicitly requiring its own Capability fails
   before owner admission, while transitive cycle detection remains solely with
   the existing Graph Planner.

## PLC1B-4 Regression Gate

PLC1B-4 additionally proves:

1. one repository fixture is a canonical, document-backed `coding.base`
   package with exactly two optional Resource descriptors, one
   `coding.builtin` Tool pack reference and one standard Session Command pack
   reference; every contribution is `data_only`, authority-free and shares one
   exact document source closure;
2. the Tool and Command declarations pin their owner-controlled catalog
   identities and positive revisions, while prompt and Skill Resources pin
   contained locators plus owner-controlled schema identities and revisions;
3. hand-authored typed IR, Host-decoded document Candidates, and the internal
   reservation-bound Builder produce byte-equal strict payloads and equal
   `PluginContributionSemanticFingerprint` v1 digests for every contribution;
4. document and in-process Builder Declaration fingerprints remain different,
   and separate Host attempts retain distinct evidence-bound Candidate
   fingerprints even when declaration semantics are unchanged;
5. CJK fixed bytes/digest, precomposed-versus-combining distinction, and
   unpaired-surrogate rejection freeze the semantic codec's Unicode behavior;
6. the semantic compiler derives kind schema and catalog-revision projections
   only from strict typed payloads; no caller-supplied peer projection can be
   forged, and the diagnostic never enters selection or owner admission; and
7. resolving or deleting the shadow requires no Tool/Command registration,
   Resource generation/publication, Definition import, Provider lookup, Graph
   planning/binding, Session/Model Input effect, disposer or live-state cleanup.
