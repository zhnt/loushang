# Plugin Lifecycle PLC9B Safe Package Boundary Contract

## Status

- Contract version: PLC9B.0.
- Delivery status: design-only. No runtime acquisition, archive extraction,
  dependency resolution, or publication route is implemented by this change.
- Scope: the future Plugin-bound Package acquisition boundary, its exact
  callers and owners, versioned evidence, failure semantics, and adversarial
  acceptance matrix.
- Public author SDK effect: none.
- Out of scope: PLC9A2 transport activation, `local_worker` or
  `remote_service`, source builds, artifact GC/deletion, private-data deletion,
  and removal of compatibility paths.

This contract refines the PLC9.0 safe Package lifecycle decision. It does not
make the current `PythonPackageInstallerBackend`, Git materializer, direct
materializer calls, or startup auto-materialization safe. Until a later PLC9B
runtime slice satisfies every gate below, a Plugin-bound artifact operation
must remain unavailable or fail closed without mutation.

## First Principles

1. Untrusted bytes are data, never a pathname, command, module, or build plan.
2. Each writable root has one owner. The Package transaction owner owns the
   acquisition/quarantine root and passes an already-verified candidate
   capability to the immutable-store owner; neither side reopens a caller path.
3. Authentication, provenance, content integrity, archive safety, dependency
   closure, and runtime admission are distinct claims with distinct evidence.
4. Validate the complete recursive artifact graph before making any revision
   selectable. A valid leaf does not make an incomplete closure valid.
5. Publication is immutable and digest addressed. Selection changes only from
   a durable receipt over the exact published set; a directory appearing is
   not a commit.
6. Every budget is checked while consuming input. A post-extraction size check
   cannot contain an archive bomb.
7. Recovery proves or repeats an idempotent transition. It never guesses that
   an interrupted operation succeeded and never falls back to an unsafe peer.
8. One ingress/classification authority and one transaction owner gate every
   CLI, RPC, Session, startup, and direct materializer route. Transport shape
   and a caller-supplied “non-Plugin” boolean confer no authority.

## Ownership And Dependency Boundary

The accepted dependency direction is:

```text
CLI / RPC / Session / startup / direct compatibility adapter
  -> one Package lifecycle ingress + classification authority
     -> Plugin-bound or indeterminate: PLC9B Package lifecycle owner
        -> per-artifact Source Authority byte/provenance port
        -> owner-created quarantine + verified-candidate capability
        -> narrow retention-pin port
        -> PluginRevisionStore staging + atomic committed-set manifest
        -> durable Package commit receipt with stable revision refs
     -> non-Plugin: separately accepted non-Plugin authority only

management command -> Package commit-admission port -> exact stable revision ref
                   -> PluginRevisionStore returns short-lived verified handle
PluginPackageLifecycleLedger <- narrow retention evidence port
```

The single PLC9B Package lifecycle owner belongs in
`loushang.harness.resources.packages`, where Package acquisition and storage
composition already live. It does not belong in `foundation`, a transport, a
Product adapter, `plugin_management`, a source backend, or the public
`loushang.plugin` author SDK.

Ownership is deliberately split only at stable evidence boundaries:

| Boundary | Sole authority | Explicit non-authority |
| --- | --- | --- |
| Package lifecycle ingress/classification authority | classify one typed request as `plugin_bound`, `non_plugin`, or `indeterminate`; bind the decision to owner revisions and an input fingerprint | transports cannot classify, submit a boolean, inspect an archive, or choose a fallback |
| Source Authority port | authenticate one root or dependency origin and return versioned provenance, expected content identity when available, and a bounded byte stream | cannot choose a filesystem path, extract, resolve dependencies, publish, bind, enable, or delete |
| PLC9B Package lifecycle owner | own quarantine, enforce every budget, inspect/extract, verify every wheel and recursive node, coordinate pins/staging/commit, journal phases, and issue the final receipt | cannot execute package code, mutate desired enablement, invent Source provenance, or delete live revisions |
| `PluginRevisionStore` evolution | consume a pinned verified-candidate capability, stage/freeze content, publish an atomic committed-set manifest, and reopen a stable committed ref as a short-lived verified handle | current digest/source-only `reopen` and final-namespace `publish` do not satisfy Package commit admission; the store does not authenticate Sources, parse archives, verify closure, or decide desired state |
| closure-v2 evidence owner | bind every recursive node to its source, acquisition, wheel-verification and publication evidence plus the exact resolution environment | v1 replay records are not upgraded or reinterpreted as recursive evidence |
| Package commit-admission port | prove that a stable revision ref is a member of one exact committed publication receipt and closure graph | cannot create refs, accept raw digests, mutate desired state, or return an uncommitted/staged object |
| narrow retention port over `PluginPackageLifecycleLedger` | obtain/transfer/release transaction and dependency pins for the exact root and dependency set | Package owner does not import the concrete ledger; the ledger does not acquire, extract, publish, select, or erase artifacts |
| management application | verify commit admission, reopen an exact stable ref, and consume it in a separately authorized install/update command | does not accept mutable source paths, raw digest/source pairs, live handles in durable records, or infer success from publication alone |

Source-specific adapters may perform network or local-source reads only behind
the Source Authority port. The Package owner supplies the write sink and
budgets; adapters stream bytes into that sink and return provenance. They never
receive the quarantine pathname. The sink distrusts adapter-supplied filenames,
media types, sizes, digests, and dependency claims until it verifies them.

## Single Classification Authority

The future Package lifecycle ingress accepts the original command, source
locator, Product/scope, authenticated caller context, and requested Package or
Plugin identity. It does not accept a classification result from the caller.
Its versioned `PluginBoundPackageClassificationV1` evidence contains:

- exactly one decision: `plugin_bound`, `non_plugin`, or `indeterminate`;
- the canonical request fingerprint and canonical Source identity without
  credentials, URL query, or fragment;
- every basis fact and its owner revision: explicit Plugin command intent,
  existing Plugin binding/history, configured Source kind, accepted independent
  non-Plugin authority, and policy revision; and
- decision revision, expiry/recheck rule, and classifier schema/epoch.

Explicit Plugin intent or existing Plugin binding/history is `plugin_bound`.
Only evidence from a separately accepted non-Plugin authority can yield
`non_plugin`. A filename, URL suffix, caller flag, missing binding, current
manifest, or Source backend cannot do so. Everything else is `indeterminate`.
An indeterminate request may enter the PLC9B owner for bounded inert inspection
when policy explicitly permits; otherwise it returns
`package_target_classification_indeterminate`. It never enters the legacy
installer, and inert inspection never hands bytes to that installer afterward.

Every route uses the same classification vector. The Package owner rechecks the
classification fingerprint before acquisition and before committed-set
publication. Changed or expired owner facts produce
`package_target_classification_changed`; they cannot be patched by a transport.

## Versioned Evidence Model

The names below freeze record responsibilities, not Python API names. Runtime
types are intentionally absent in PLC9B.0.

| Evidence | Required immutable facts |
| --- | --- |
| Plugin-bound classification v1 | request fingerprint, three-way decision, basis facts with owner revisions, policy revision, recheck rule, classifier epoch, and redacted canonical Source identity |
| authenticated source envelope v1 | operation/node identity, canonical credential-free source identity, origin kind, authentication decision and authority identity, requested locator digest, expected artifact digest if declared, redirect policy, policy revision, capture time, and schema version |
| bounded acquisition receipt v1 | node identity, envelope fingerprint, actual byte digest/count, request/redirect/time budgets, termination disposition, owner sink identity, and source-adapter result; no source pathname or secret |
| quarantine receipt v1 | owner root identity, private operation-directory identity, every byte/entry/path/parser/memory/time/closure/solver budget and consumption, platform normalization profile, attempt epoch, and creation phase |
| verified wheel artifact v1 | canonical distribution name/version, wheel filename and compatible tags, artifact digest/size, canonical metadata digests, complete RECORD verification, and extraction-tree digest |
| dependency closure node v2 | canonical project identity, source-envelope fingerprint, acquisition-receipt fingerprint, wheel-evidence fingerprint, artifact/tree digests, normalized requirements, selected edges, and later stable publication ref |
| dependency closure lock v2 | root node, every recursive node, directed edges, marker evaluation, exact resolution-environment fingerprint, canonical order, node/set counts, and graph digest |
| retention-pin receipt v1 | operation/attempt, exact root and dependency candidates, pin kind/owner revision/lease, acquisition/release/transfer state, and recovery identity |
| immutable publication receipt v1 | operation identity, classification and quarantine fingerprints, complete closure graph/set digest, exact stable published revision refs (never live handles), committed-set manifest identity, retention-pin evidence, store/root identity, phase sequence, and commit revision |
| Package lifecycle status/failure v1 | operation/request fingerprint, phase, attempt epoch, terminal disposition, evidence references, stable failure code/stage/retryability/operator action, redacted bounded details, and status revision |

`PluginDependencyClosureLock` v1 remains replay-only and keeps its existing
meaning: final package-tree digest plus installed `name==version` facts. A v1
record never satisfies PLC9B recursive verification, and no reader may decode
v1 bytes as closure v2. An unsupported future evidence version fails closed.

PLC9B v1 identities use lowercase hexadecimal SHA-256 over strict UTF-8 JSON:
sorted object keys, no duplicate keys, no floats, no insignificant whitespace,
and exact non-secret strings. Wheel `RECORD` accepts `sha256`, `sha384`, or
`sha512`; weaker/unknown algorithms fail closed, and an empty hash/size is
allowed only for the RECORD file and its explicitly permitted signature files.
The resolution environment covers every input that can change marker or wheel
compatibility selection. Canonical distribution names are compared after the
same specified normalization, and two artifacts that normalize to one name are
a terminal conflict, never a cycle-tolerant or last-writer-wins choice.

## Owner Transaction And Recovery

The durable phase machine is monotonic:

```text
accepted
  -> classified
  -> acquiring
  -> acquired
  -> inspecting
  -> extracted
  -> resolving_closure
  -> closure_verified
  -> transaction_pinned
  -> staging
  -> set_published
  -> committed
```

`rejected`, `cancelled`, and `committed` are terminal operation dispositions.
`retryable_failure` terminates only one numbered attempt. A retry of the same
operation/request fingerprint obtains a greater attempt epoch and resumes from
the last proved evidence; changed input is
`package_operation_identity_conflict`. The request fingerprint binds command,
Product/scope, canonical credential-free Source identity, requested identity,
classification/policy revisions, quota profile, and resolution environment.
Once acquisition wins its compare-and-swap, all later attempts must reproduce
the same actual artifact digest and evidence chain.

- `accepted` records the fixed request fingerprint before untrusted bytes enter
  the owner sink; `classified` records the single authority decision.
- `acquiring` through `closure_verified` operate only in an owner-created,
  private, identity-pinned quarantine. Every archive entry is normalized and
  authorized before any object is created.
- `transaction_pinned` obtains a versioned transaction pin over the root and
  every dependency before anything enters a store namespace.
- `staging` gives the immutable store only a pinned verified-candidate
  capability, not a pathname. Staged refs are owner-private and cannot be
  reopened by management or the current digest/source API.
- `set_published` is one atomic committed-set manifest over the complete graph.
  A crash before that edge leaves only staged, unselectable content. Recovery
  revalidates staged identity and either advances the same set or transfers it
  to evidence-backed cleanup. Directory existence alone is never admission.
- `committed` durably binds the set manifest and transaction pin. The read-only
  Package commit-admission port is the only route from a stable ref to a
  short-lived `VerifiedRevisionHandle`.
- A later desired install/update first obtains dependency-retention pins under
  one handoff identity, then commits desired state, then presents the durable
  desired receipt to the retention port. That owner atomically records handoff
  completion and releases the transaction pin. There is no cross-owner atomic
  claim: a crash leaves both pins, never a zero-pin gap, and exact replay
  completes the same handoff. Rejection, cancellation, or never-selected
  publication keeps the transaction pin visible to the same recovery state
  machine. PLC9D owns physical artifact deletion; PLC9B owns bounded quarantine
  cleanup and cannot silently drop retention evidence.

Slow Source I/O, parsing, hashing, and extraction never hold the journal lock.
Each attempt instead owns a bounded lease/fencing epoch. Every phase append is
an expected-phase compare-and-swap over `(operation, request fingerprint,
attempt epoch, prior journal revision)`. A stale worker cannot append, renew a
lease, stage, publish a set, or commit after a newer recovery attempt has won.
Store/transaction/pin locks have a fixed order and bounded critical sections.
Concurrent same-input attempts converge; different input rejects; an existing
digest is reusable only after exact candidate, set-membership, and store-identity
revalidation.

## Status, Diagnostics, And Operator Actions

`PackageLifecycleFailureV1` is a closed, versioned application record. It
contains `code`, `stage`, `retryable`, `operator_action`, `operation_id`,
`evidence_ref`, and bounded redacted details. `operator_action` is exactly one
of `none`, `retry`, `repair`, `upgrade_runtime`, `offline_restore`, or
`review_policy`. The initial code set is:

| Code family | Retry/action rule |
| --- | --- |
| `package_target_classification_indeterminate`, `package_target_classification_changed` | terminal for this request; review policy or submit a new request after owner facts change |
| `package_source_unauthorized`, `package_source_provenance_changed` | terminal; review policy/source authority |
| `package_acquisition_limit_exceeded`, `package_operation_timed_out` | retryable only when no acquired digest won; otherwise terminal for the same request |
| `package_acquisition_digest_mismatch`, `package_artifact_identity_changed` | terminal security failure |
| `package_archive_malformed`, `package_archive_path_rejected`, `package_archive_name_collision`, `package_archive_entry_type_rejected` | terminal artifact rejection |
| `package_resource_limit_exceeded`, `package_wheel_metadata_invalid`, `package_wheel_record_invalid`, `package_artifact_type_rejected` | terminal artifact rejection; a new artifact requires a new operation |
| `package_closure_artifact_invalid`, `package_closure_conflict`, `package_closure_evidence_unsupported` | terminal for the graph/evidence version |
| `package_publication_root_untrusted`, `package_publication_collision`, `package_commit_admission_denied` | terminal security failure; repair never overwrites or admits an uncommitted ref |
| `package_operation_interrupted` | retryable with a greater fenced attempt epoch |
| `package_operation_identity_conflict` | terminal; caller must use a new operation identity |
| `package_operation_cancelled` | terminal and operator-requested; a retry is a new operation |
| `package_runtime_epoch_unsupported` | terminal in-process; upgrade runtime or offline restore |
| `package_route_unavailable` | terminal while PLC9B is disabled; never invokes a peer installer |

Every transport projects the same record without changing the code or
retryability. CLI emits the code, operation id and evidence reference and exits
`1`; exit `2` remains parser/usage failure and `130` remains user interruption.
RPC returns the record as its structured command error. Session raises one typed
Package lifecycle application error carrying the record. Startup emits the same
diagnostic and aborts configuration for Plugin-bound or indeterminate input; it
cannot silently continue with a missing Plugin. Query returns
`PackageLifecycleStatusV1`; retry, cancel, and repair are typed owner operations,
not transport-local mutations.

Diagnostics, journals, fingerprints, and digests never contain credentials,
authorization headers, URL user-info/query/fragment, private registry tokens,
or raw unbounded metadata. Canonical Source identity strips those fields before
hashing. Details use an allowlist and length limits; an opaque evidence ref is
used for privileged inspection.

## Safe Acquisition, Inspection, And Extraction

Before runtime implementation is accepted, the owner must prove all of the
following on every supported platform:

- request/redirect/artifact counts, transport/decompressed bytes, entry count,
  directory and closure depth, closure node/edge count, component/total path
  length, per-entry/aggregate expansion, parser and metadata memory, CPU and
  wall-clock time, dependency-solver steps, marker operations, and sparse-file
  allocation are hard limits enforced incrementally while consuming input;
- absolute, root-relative, parent-traversal, empty, dot, drive, UNC, alternate
  data stream, reserved-device, trailing-dot/space, and platform-ambiguous
  names are rejected before filesystem creation;
- duplicate names and names colliding after separator, Unicode, case, or
  platform normalization are rejected globally;
- only regular files and directories are accepted; symlinks, hard links,
  junctions/reparse points, devices, sockets, and FIFOs are rejected in both
  archive metadata and the materialized tree;
- every create/open is root-relative, no-follow, exclusive where required, and
  checked against the pinned owner root; ancestor or entry replacement fails
  closed;
- malformed headers, inconsistent local/central metadata, overlap, truncation,
  unsupported compression/encryption, duplicate records, and trailing payload
  fail closed; and
- rejection closes handles, records evidence, and leaves no selectable
  revision, binding, desired-state change, or attacker-controlled file outside
  quarantine.

Python artifacts are verified wheel-only. The owner verifies filename,
compatible tags, `WHEEL`, `METADATA`, and the complete `RECORD` relation before
canonical-tree publication. Missing, mismatched, duplicate, or unlisted files
are rejected. Metadata is parsed as inert bytes; no module import, entry point,
setup script, build backend, package-manager hook, or adjacent executable is
invoked. Source distributions are unconditionally rejected by PLC9B. A future
contained build service requires a separate contract and may return only a
digest-addressed wheel to this same boundary.

Rejected/cancelled quarantine is owner-local temporary state, not artifact GC.
The versioned quota profile bounds outstanding quarantine count, aggregate
bytes, and maximum age per store. A terminal disposition attempts immediate
rooted cleanup; cleanup failure records `package_operation_interrupted`, keeps a
bounded tombstone/status projection, and blocks new admission before exceeding
the store quota. Repair retries only exact owner-root cleanup. Evidence journals
retain bounded fingerprints/status, not untrusted bytes; TTL never authorizes
deletion of a committed or pinned immutable revision.
The operation's terminal `rejected`/`cancelled` disposition never reopens; a
separate `cleanup_retryable` substatus records cleanup progress and repair.

## Exact Entrypoint Gate

The canonical source occurrence inventory is maintained in
`plugin-lifecycle-plc9-inventory.md` and verified from the Python AST across all
of `src/loushang`. It has two independent machine-checked blocks:

- an ingress/declaration inventory of 95 exact `(path, qualified scope,
  lifecycle symbol)` rows and 151 occurrences; and
- an effect/capability inventory of 117 exact rows and 132 occurrences covering
  materializer/backend/store/source-resolver/operations construction plus
  materialize/update/remove/forget/publish/bind/reopen capabilities.

Together the inventories include:

- Coding and shared CLI queries/commands;
- RPC Package capabilities and bindings;
- Session public ports, facade forwarding, and lifecycle adaptation;
- `SessionPackageController` and `PackageOperationsRuntime` composition;
- startup `PackageSourceResolver` auto-materialization; and
- direct `PackageMaterializer` sync/check and mutable remove/forget seams.

The scanner counts module/class/function definitions, imports and renamed
imports, names, attribute access, and exact dynamic strings at the narrowest
scope. Adding, deleting, renaming, or changing a count requires the same
reviewed inventory update. Computed reflection, string-built method names, and
callable laundering are forbidden, not “unseen means allowed.” Static inventory
does not claim a complete Python call graph: runtime route-conformance and
negative side-effect tests remain an activation gate.

During implementation every entrypoint submits the unclassified typed request
to the one ingress authority before side effects. Only independently proved
`non_plugin` input may reach separately accepted behavior. `plugin_bound` or
`indeterminate` enters the PLC9B owner or returns the stable classified refusal.
It cannot fall through to the current `uv`/`pip`, Git checkout publication,
direct mutable removal, or startup auto-materialization path. Transport modules
may import only the future application port/records; the concrete materializer,
backend, store, classifier, ledger, and quarantine owner remain forbidden.

## Adversarial Acceptance Matrix

The machine-readable manifest below is the mandatory runtime evidence plan.
PLC9B.0 deliberately leaves every row `planned`: no fixture or artifact is
created or executed in this design slice. Runtime activation must change each
row to `required`, provide the exact collected pytest node and workflow job, and
make either a missing node or a skip fail that job.

`platform` is `any`, `posix-native`, or `windows-native`. `disposition` is the
exact journal result. Oracles use a closed vocabulary: `no_outside_write`,
`no_process`, `no_import`, `no_extra_network`, `no_publication`, `no_binding`,
`no_desired`, `no_peer_fallback`, `no_secret`, `bounded_residue`,
`same_receipt`, `pin_visible`, `single_owner`, and `no_skip`.

<!-- plc9b-adversarial-manifest:start -->
```text
case_id | platform | barrier | fixture | code | disposition | oracles | test_node | workflow | status
B-CLASS-PLUGIN | any | classified | explicit_plugin_intent | ok | classified@plugin_bound | single_owner;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLASS-PLUGIN] | harness-quality.yml#plc9b-linux-native | planned
B-CLASS-NONPLUGIN | any | classified | independent_non_plugin_evidence | ok | classified@non_plugin | single_owner;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLASS-NONPLUGIN] | harness-quality.yml#plc9b-linux-native | planned
B-CLASS-INDETERMINATE | any | classified | unknown_source | package_target_classification_indeterminate | rejected@classified | no_publication;no_binding;no_desired;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLASS-INDETERMINATE] | harness-quality.yml#plc9b-linux-native | planned
B-CLASS-CHANGED | any | staging | classification_revision_race | package_target_classification_changed | rejected@staging | no_publication;no_binding;no_desired;no_peer_fallback;pin_visible | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLASS-CHANGED] | harness-quality.yml#plc9b-linux-native | planned
B-CLASS-SPOOF | any | classified | caller_non_plugin_boolean | package_target_classification_indeterminate | rejected@classified | single_owner;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLASS-SPOOF] | harness-quality.yml#plc9b-linux-native | planned
B-ACQ-AUTH | any | acquiring | unauthenticated_origin | package_source_unauthorized | rejected@acquiring | no_extra_network;no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ACQ-AUTH] | harness-quality.yml#plc9b-linux-native | planned
B-ACQ-PROVENANCE | any | acquiring | changed_authority | package_source_provenance_changed | rejected@acquiring | no_publication;no_binding;no_peer_fallback;no_secret | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ACQ-PROVENANCE] | harness-quality.yml#plc9b-linux-native | planned
B-ACQ-BYTES | any | acquiring | byte_limit | package_acquisition_limit_exceeded | retryable_failure@acquiring | bounded_residue;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ACQ-BYTES] | harness-quality.yml#plc9b-linux-native | planned
B-ACQ-REDIRECT | any | acquiring | redirect_limit | package_acquisition_limit_exceeded | retryable_failure@acquiring | bounded_residue;no_extra_network;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ACQ-REDIRECT] | harness-quality.yml#plc9b-linux-native | planned
B-ACQ-TIMEOUT | any | acquiring | wall_clock_limit | package_operation_timed_out | retryable_failure@acquiring | bounded_residue;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ACQ-TIMEOUT] | harness-quality.yml#plc9b-linux-native | planned
B-ACQ-DIGEST | any | acquired | declared_digest_mismatch | package_acquisition_digest_mismatch | rejected@acquired | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ACQ-DIGEST] | harness-quality.yml#plc9b-linux-native | planned
B-ACQ-IDENTITY | any | inspecting | archive_replacement | package_artifact_identity_changed | rejected@inspecting | no_outside_write;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ACQ-IDENTITY] | harness-quality.yml#plc9b-linux-native | planned
B-ARCH-TRUNCATED | any | inspecting | truncated_archive | package_archive_malformed | rejected@inspecting | bounded_residue;no_outside_write;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ARCH-TRUNCATED] | harness-quality.yml#plc9b-linux-native | planned
B-ARCH-HEADERS | any | inspecting | inconsistent_headers | package_archive_malformed | rejected@inspecting | no_outside_write;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ARCH-HEADERS] | harness-quality.yml#plc9b-linux-native | planned
B-ARCH-OVERLAP | any | inspecting | overlapping_entries | package_archive_malformed | rejected@inspecting | no_outside_write;no_publication;bounded_residue | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ARCH-OVERLAP] | harness-quality.yml#plc9b-linux-native | planned
B-ARCH-COMPRESSION | any | inspecting | unsupported_compression_or_encryption | package_archive_malformed | rejected@inspecting | no_process;no_outside_write;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ARCH-COMPRESSION] | harness-quality.yml#plc9b-linux-native | planned
B-ARCH-TRAILING | any | inspecting | trailing_payload | package_archive_malformed | rejected@inspecting | no_outside_write;no_publication;no_binding | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ARCH-TRAILING] | harness-quality.yml#plc9b-linux-native | planned
B-PATH-ABSOLUTE | any | inspecting | absolute_path | package_archive_path_rejected | rejected@inspecting | no_outside_write;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-ABSOLUTE] | harness-quality.yml#plc9b-linux-native | planned
B-PATH-TRAVERSAL | any | inspecting | parent_traversal | package_archive_path_rejected | rejected@inspecting | no_outside_write;no_publication;no_binding | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-TRAVERSAL] | harness-quality.yml#plc9b-linux-native | planned
B-PATH-EMPTY | any | inspecting | empty_or_dot_component | package_archive_path_rejected | rejected@inspecting | no_outside_write;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-EMPTY] | harness-quality.yml#plc9b-linux-native | planned
B-PATH-WIN-ROOT | windows-native | inspecting | drive_or_unc_path | package_archive_path_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-WIN-ROOT] | windows-shell-compatibility.yml#plc9b-windows-native | planned
B-PATH-WIN-ADS | windows-native | inspecting | alternate_data_stream | package_archive_path_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-WIN-ADS] | windows-shell-compatibility.yml#plc9b-windows-native | planned
B-PATH-WIN-RESERVED | windows-native | inspecting | reserved_device_name | package_archive_path_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-WIN-RESERVED] | windows-shell-compatibility.yml#plc9b-windows-native | planned
B-PATH-WIN-TRAILING | windows-native | inspecting | trailing_dot_or_space | package_archive_path_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-WIN-TRAILING] | windows-shell-compatibility.yml#plc9b-windows-native | planned
B-PATH-COLLISION-SEP | any | inspecting | separator_collision | package_archive_name_collision | rejected@inspecting | no_outside_write;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-COLLISION-SEP] | harness-quality.yml#plc9b-linux-native | planned
B-PATH-COLLISION-UNICODE | any | inspecting | unicode_collision | package_archive_name_collision | rejected@inspecting | no_outside_write;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-COLLISION-UNICODE] | harness-quality.yml#plc9b-linux-native | planned
B-PATH-COLLISION-CASE | windows-native | inspecting | casefold_collision | package_archive_name_collision | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-COLLISION-CASE] | windows-shell-compatibility.yml#plc9b-windows-native | planned
B-TYPE-SYMLINK | posix-native | inspecting | symlink_entry | package_archive_entry_type_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-TYPE-SYMLINK] | harness-quality.yml#plc9b-linux-native | planned
B-TYPE-HARDLINK | posix-native | inspecting | hardlink_entry | package_archive_entry_type_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-TYPE-HARDLINK] | harness-quality.yml#plc9b-linux-native | planned
B-TYPE-DEVICE | posix-native | inspecting | device_entry | package_archive_entry_type_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-TYPE-DEVICE] | harness-quality.yml#plc9b-linux-native | planned
B-TYPE-SOCKET | posix-native | inspecting | socket_entry | package_archive_entry_type_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-TYPE-SOCKET] | harness-quality.yml#plc9b-linux-native | planned
B-TYPE-FIFO | posix-native | inspecting | fifo_entry | package_archive_entry_type_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-TYPE-FIFO] | harness-quality.yml#plc9b-linux-native | planned
B-TYPE-REPARSE | windows-native | inspecting | reparse_entry | package_archive_entry_type_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-TYPE-REPARSE] | windows-shell-compatibility.yml#plc9b-windows-native | planned
B-TYPE-JUNCTION | windows-native | inspecting | junction_entry | package_archive_entry_type_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-TYPE-JUNCTION] | windows-shell-compatibility.yml#plc9b-windows-native | planned
B-LIMIT-ENTRY | any | inspecting | entry_or_expansion_budget | package_resource_limit_exceeded | rejected@inspecting | bounded_residue;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-LIMIT-ENTRY] | harness-quality.yml#plc9b-linux-native | planned
B-LIMIT-MEMORY | any | inspecting | parser_or_metadata_memory | package_resource_limit_exceeded | rejected@inspecting | bounded_residue;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-LIMIT-MEMORY] | harness-quality.yml#plc9b-linux-native | planned
B-LIMIT-CPU | any | inspecting | cpu_or_wall_budget | package_resource_limit_exceeded | rejected@inspecting | bounded_residue;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-LIMIT-CPU] | harness-quality.yml#plc9b-linux-native | planned
B-LIMIT-GRAPH | any | resolving_closure | closure_node_edge_depth | package_resource_limit_exceeded | rejected@resolving_closure | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-LIMIT-GRAPH] | harness-quality.yml#plc9b-linux-native | planned
B-LIMIT-SOLVER | any | resolving_closure | solver_or_marker_steps | package_resource_limit_exceeded | rejected@resolving_closure | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-LIMIT-SOLVER] | harness-quality.yml#plc9b-linux-native | planned
B-LIMIT-REQUESTS | any | acquiring | request_redirect_artifact_count | package_resource_limit_exceeded | rejected@acquiring | no_extra_network;no_publication;bounded_residue | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-LIMIT-REQUESTS] | harness-quality.yml#plc9b-linux-native | planned
B-WHEEL-SDIST | any | inspecting | source_distribution | package_artifact_type_rejected | rejected@inspecting | no_process;no_import;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-WHEEL-SDIST] | harness-quality.yml#plc9b-linux-native | planned
B-WHEEL-ZIP | any | inspecting | arbitrary_zip_or_editable | package_artifact_type_rejected | rejected@inspecting | no_process;no_import;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-WHEEL-ZIP] | harness-quality.yml#plc9b-linux-native | planned
B-WHEEL-TAGS | any | inspecting | unsupported_wheel_tags | package_artifact_type_rejected | rejected@inspecting | no_publication;no_binding | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-WHEEL-TAGS] | harness-quality.yml#plc9b-linux-native | planned
B-WHEEL-METADATA | any | extracted | wheel_metadata_mismatch | package_wheel_metadata_invalid | rejected@extracted | no_publication;no_binding;no_desired | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-WHEEL-METADATA] | harness-quality.yml#plc9b-linux-native | planned
B-WHEEL-RECORD-HASH | any | extracted | record_hash_or_size | package_wheel_record_invalid | rejected@extracted | no_publication;no_binding;no_desired | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-WHEEL-RECORD-HASH] | harness-quality.yml#plc9b-linux-native | planned
B-WHEEL-RECORD-SET | any | extracted | record_missing_or_unlisted | package_wheel_record_invalid | rejected@extracted | no_publication;no_binding;no_desired | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-WHEEL-RECORD-SET] | harness-quality.yml#plc9b-linux-native | planned
B-WHEEL-RECORD-ALGO | any | extracted | weak_or_unknown_record_hash | package_wheel_record_invalid | rejected@extracted | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-WHEEL-RECORD-ALGO] | harness-quality.yml#plc9b-linux-native | planned
B-CLOSURE-MISSING | any | resolving_closure | missing_dependency | package_closure_artifact_invalid | rejected@resolving_closure | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLOSURE-MISSING] | harness-quality.yml#plc9b-linux-native | planned
B-CLOSURE-DIGEST | any | resolving_closure | dependency_digest_mismatch | package_closure_artifact_invalid | rejected@resolving_closure | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLOSURE-DIGEST] | harness-quality.yml#plc9b-linux-native | planned
B-CLOSURE-ORIGIN | any | resolving_closure | dependency_unauthorized_origin | package_closure_artifact_invalid | rejected@resolving_closure | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLOSURE-ORIGIN] | harness-quality.yml#plc9b-linux-native | planned
B-CLOSURE-MARKER | any | resolving_closure | marker_or_environment_mismatch | package_closure_conflict | rejected@resolving_closure | no_publication;no_binding;no_desired | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLOSURE-MARKER] | harness-quality.yml#plc9b-linux-native | planned
B-CLOSURE-NAME | any | resolving_closure | duplicate_name_or_version | package_closure_conflict | rejected@resolving_closure | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLOSURE-NAME] | harness-quality.yml#plc9b-linux-native | planned
B-CLOSURE-CYCLE | any | resolving_closure | dependency_cycle | package_closure_conflict | rejected@resolving_closure | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLOSURE-CYCLE] | harness-quality.yml#plc9b-linux-native | planned
B-CLOSURE-V1 | any | resolving_closure | v1_or_future_evidence | package_closure_evidence_unsupported | rejected@resolving_closure | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLOSURE-V1] | harness-quality.yml#plc9b-linux-native | planned
B-PUB-PRECREATE | any | staging | precreated_quarantine | package_publication_root_untrusted | rejected@staging | no_outside_write;no_publication;pin_visible | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PUB-PRECREATE] | harness-quality.yml#plc9b-linux-native | planned
B-PUB-SWAP | any | staging | ancestor_or_entry_swap | package_publication_root_untrusted | rejected@staging | no_outside_write;no_publication;pin_visible | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PUB-SWAP] | harness-quality.yml#plc9b-linux-native | planned
B-PUB-COLLISION | any | set_published | same_digest_different_identity | package_publication_collision | rejected@staging | no_publication;no_binding;pin_visible | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PUB-COLLISION] | harness-quality.yml#plc9b-linux-native | planned
B-PUB-REUSE | any | set_published | exact_committed_set_exists | ok | committed@committed | same_receipt;pin_visible;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PUB-REUSE] | harness-quality.yml#plc9b-linux-native | planned
B-PUB-UNCOMMITTED | any | set_published | stable_ref_without_commit_receipt | package_commit_admission_denied | rejected@staging | no_binding;no_desired;pin_visible;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PUB-UNCOMMITTED] | harness-quality.yml#plc9b-linux-native | planned
B-CRASH-ACCEPTED | any | accepted | crash_edge | package_operation_interrupted | retryable_failure@accepted | same_receipt;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-ACCEPTED] | harness-quality.yml#plc9b-linux-native | planned
B-CRASH-CLASSIFIED | any | classified | crash_edge | package_operation_interrupted | retryable_failure@classified | same_receipt;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-CLASSIFIED] | harness-quality.yml#plc9b-linux-native | planned
B-CRASH-ACQUIRING | any | acquiring | crash_edge | package_operation_interrupted | retryable_failure@acquiring | same_receipt;bounded_residue;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-ACQUIRING] | harness-quality.yml#plc9b-linux-native | planned
B-CRASH-ACQUIRED | any | acquired | crash_edge | package_operation_interrupted | retryable_failure@acquired | same_receipt;bounded_residue;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-ACQUIRED] | harness-quality.yml#plc9b-linux-native | planned
B-CRASH-INSPECTING | any | inspecting | crash_edge | package_operation_interrupted | retryable_failure@inspecting | same_receipt;bounded_residue;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-INSPECTING] | harness-quality.yml#plc9b-linux-native | planned
B-CRASH-EXTRACTED | any | extracted | crash_edge | package_operation_interrupted | retryable_failure@extracted | same_receipt;bounded_residue;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-EXTRACTED] | harness-quality.yml#plc9b-linux-native | planned
B-CRASH-RESOLVING | any | resolving_closure | crash_edge | package_operation_interrupted | retryable_failure@resolving_closure | same_receipt;bounded_residue;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-RESOLVING] | harness-quality.yml#plc9b-linux-native | planned
B-CRASH-CLOSURE | any | closure_verified | crash_edge | package_operation_interrupted | retryable_failure@closure_verified | same_receipt;no_publication;no_binding | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-CLOSURE] | harness-quality.yml#plc9b-linux-native | planned
B-CRASH-PINNED | any | transaction_pinned | crash_edge | package_operation_interrupted | retryable_failure@transaction_pinned | same_receipt;pin_visible;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-PINNED] | harness-quality.yml#plc9b-linux-native | planned
B-CRASH-STAGING | any | staging | crash_edge | package_operation_interrupted | retryable_failure@staging | same_receipt;pin_visible;no_binding | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-STAGING] | harness-quality.yml#plc9b-linux-native | planned
B-CRASH-SET | any | set_published | crash_edge | package_operation_interrupted | retryable_failure@set_published | same_receipt;pin_visible;no_binding;no_desired | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-SET] | harness-quality.yml#plc9b-linux-native | planned
B-CRASH-COMMITTED | any | committed | crash_after_edge | ok | committed@committed | same_receipt;pin_visible;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-COMMITTED] | harness-quality.yml#plc9b-linux-native | planned
B-CONCUR-SAME | any | each_phase | concurrent_same_fingerprint | ok | committed@committed | same_receipt;single_owner;pin_visible | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CONCUR-SAME] | harness-quality.yml#plc9b-linux-native | planned
B-CONCUR-CONFLICT | any | classified | concurrent_different_fingerprint | package_operation_identity_conflict | rejected@classified | single_owner;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CONCUR-CONFLICT] | harness-quality.yml#plc9b-linux-native | planned
B-CONCUR-STALE | any | each_phase | stale_attempt_epoch | package_operation_identity_conflict | rejected@prior_phase | single_owner;no_publication;no_binding;pin_visible | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CONCUR-STALE] | harness-quality.yml#plc9b-linux-native | planned
B-ENTRY-CLI | any | classified | cli_plugin_bound | ok | committed@committed | single_owner;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ENTRY-CLI] | harness-quality.yml#plc9b-linux-native | planned
B-ENTRY-RPC | any | classified | rpc_plugin_bound | ok | committed@committed | single_owner;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ENTRY-RPC] | harness-quality.yml#plc9b-linux-native | planned
B-ENTRY-SESSION | any | classified | session_plugin_bound | ok | committed@committed | single_owner;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ENTRY-SESSION] | harness-quality.yml#plc9b-linux-native | planned
B-ENTRY-STARTUP | any | classified | startup_plugin_bound | ok | committed@committed | single_owner;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ENTRY-STARTUP] | harness-quality.yml#plc9b-linux-native | planned
B-ENTRY-OPERATIONS | any | classified | operations_plugin_bound | ok | committed@committed | single_owner;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ENTRY-OPERATIONS] | harness-quality.yml#plc9b-linux-native | planned
B-ENTRY-MATERIALIZER | any | classified | direct_materializer_plugin_bound | package_route_unavailable | rejected@classified | single_owner;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ENTRY-MATERIALIZER] | harness-quality.yml#plc9b-linux-native | planned
B-ENTRY-PUBLISH | any | staging | direct_publish_or_bind | package_route_unavailable | rejected@staging | single_owner;no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ENTRY-PUBLISH] | harness-quality.yml#plc9b-linux-native | planned
B-ENTRY-DISABLED | any | classified | plc9b_owner_disabled | package_route_unavailable | rejected@classified | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ENTRY-DISABLED] | harness-quality.yml#plc9b-linux-native | planned
B-NOEXEC-IMPORT | any | extracted | import_trap | ok | committed@committed | no_process;no_import;no_extra_network | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-NOEXEC-IMPORT] | harness-quality.yml#plc9b-linux-native | planned
B-NOEXEC-SETUP | any | extracted | setup_or_build_hook | package_artifact_type_rejected | rejected@extracted | no_process;no_import;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-NOEXEC-SETUP] | harness-quality.yml#plc9b-linux-native | planned
B-NOEXEC-ENTRYPOINT | any | extracted | malicious_entrypoint_metadata | ok | committed@committed | no_process;no_import;no_extra_network | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-NOEXEC-ENTRYPOINT] | harness-quality.yml#plc9b-linux-native | planned
B-NOEXEC-ADJACENT | any | extracted | adjacent_executable | ok | committed@committed | no_process;no_import;no_extra_network | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-NOEXEC-ADJACENT] | harness-quality.yml#plc9b-linux-native | planned
B-STATE-CANCEL-EARLY | any | each_phase_before_transaction_pinned | operator_cancel | package_operation_cancelled | cancelled@prior_phase | bounded_residue;no_publication;no_binding;no_desired | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-STATE-CANCEL-EARLY] | harness-quality.yml#plc9b-linux-native | planned
B-STATE-CANCEL-PINNED | any | each_precommit_phase_from_transaction_pinned | operator_cancel | package_operation_cancelled | cancelled@prior_phase | no_binding;no_desired;pin_visible;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-STATE-CANCEL-PINNED] | harness-quality.yml#plc9b-linux-native | planned
B-STATE-REJECT-CLEANUP | any | rejected | quarantine_cleanup_failure | package_operation_interrupted | rejected@cleanup_retryable | bounded_residue;no_binding;no_desired;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-STATE-REJECT-CLEANUP] | harness-quality.yml#plc9b-linux-native | planned
B-STATE-SECRETS | any | each_phase | credentialed_private_locator | ok | committed@committed | no_secret;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-STATE-SECRETS] | harness-quality.yml#plc9b-linux-native | planned
B-STATE-STATUS | any | rejected | transport_status_mapping | package_archive_malformed | rejected@inspecting | same_receipt;no_secret;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-STATE-STATUS] | harness-quality.yml#plc9b-linux-native | planned
B-COMPAT-EPOCH | any | accepted | newer_lifecycle_epoch | package_runtime_epoch_unsupported | rejected@accepted | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-EPOCH] | harness-quality.yml#plc9b-linux-native | planned
B-COMPAT-MIXED | any | accepted | mixed_fence_aware_processes | package_runtime_epoch_unsupported | rejected@accepted | single_owner;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-MIXED] | harness-quality.yml#plc9b-linux-native | planned
B-COMPAT-LEGACY | any | classified | legacy_lock_binding_revision | package_closure_evidence_unsupported | rejected@classified | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-LEGACY] | harness-quality.yml#plc9b-linux-native | planned
B-COMPAT-ROLLFORWARD | any | retryable_failure | upgrade_downgrade_rollforward | ok | committed@committed | same_receipt;pin_visible;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-ROLLFORWARD] | harness-quality.yml#plc9b-linux-native | planned
```
<!-- plc9b-adversarial-manifest:end -->

Native Windows rows run only in the named Windows workflow and native POSIX
rows in the named Harness workflow. The job collects the exact node ids and
rejects skips; unsupported-host emulation is never the only evidence. General
rows also observe filesystem/process/import/network/publication/binding/desired
state and peer-fallback oracles, not merely an exception string.

## Epoch, Upgrade, And Downgrade Fence

The future owner records a Package lifecycle epoch and minimum fence-aware
runtime against the exact Package-store root identity before any v2 transaction
or staged object. Every fence-aware process checks that record before Source,
lockfile, binding, revision, or quarantine access. A newer epoch, an active
different-epoch lease, or unknown evidence yields
`package_runtime_epoch_unsupported`; mixed-epoch writers are never admitted.

A pre-fence binary cannot be made safe by a record it does not understand.
Direct downgrade after any B epoch state exists is unsupported. The only
pre-fence recovery is an offline restore of the complete pre-B Package store,
Source configuration, lock/binding history, desired-state backup, and fence
record, followed by exclusive old-runtime startup. Otherwise operators upgrade
to the minimum fence-aware runtime and roll forward. Crash recovery by an older
fence-aware epoch also refuses before touching paths.

Existing lockfiles, bindings, closure-v1 records, and published revisions remain
replay/retention evidence but are `legacy_unverified`; they never satisfy B
classification, recursive closure, commit admission, or dependency pinning.
Existing desired/Instance state is not silently deleted, rebound, or claimed as
B-verified. Adoption requires authenticated reacquisition and the complete B
transaction under a new operation. If reacquisition is impossible, a future
explicit operator trust-import contract is required; PLC9B.0 does not invent
one. Upgrade -> downgrade refusal -> roll-forward, mixed-process, old-state, and
offline-restore fixtures are mandatory manifest cases.

## Rollout, Rollback, And Deletion Gates

PLC9B runtime work must land dark and fail closed before routes are activated.
Activation requires every manifest row to be `required` and collected without
skip, exact-entry/effect routing tests, crash/replay tests, epoch/adoption
fixtures, and cross-platform root-containment tests. There is no rollback to the
current installer for Plugin-bound input: disabling the new owner disables the
artifact command. Roll forward repairs only from versioned evidence and exact
digests.

The current `PythonPackageInstallerBackend`, Git publication behavior, startup
auto-materialization, direct mutable removal, binding/history forgetting, and
synchronous compatibility calls remain visible migration debt. They may be
narrowed or deleted only after:

1. every inventoried Plugin-bound route reaches the PLC9B owner or refusal;
2. no production caller can publish a Plugin revision through the peer path;
3. closure-v1 replay, epoch/mixed-process/adoption, and downgrade refusal
   fixtures pass;
4. non-Plugin Package behavior has a separately accepted owner and regression
   evidence;
5. rollback disables Plugin artifact operations instead of restoring an unsafe
   implementation; and
6. the canonical ingress/effect inventories and negative architecture guard
   freeze every known capability acquisition site, while runtime conformance
   rejects computed reflection, callable laundering, and dynamic fallback.

PLC9A2 may project non-artifact management operations after PLC9A1, but it may
not expose materialize/install/update/remove/uninstall for Plugin-bound targets
until this runtime gate passes. PLC9C, PLC9D, and PLC9E remain separate slices.
