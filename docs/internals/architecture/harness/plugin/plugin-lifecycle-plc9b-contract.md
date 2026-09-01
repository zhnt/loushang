# Plugin Lifecycle PLC9B Safe Package Boundary Contract

## Status

- Contract version: PLC9B.2k.
- Delivery status: PLC9B1 dark Owner Kernel and the unbound
  PLC9B2a/B2b/B2c/B2d/B2e safe
  acquisition and wheel-inspection components are implemented. Versioned inert
  request/classification/status/failure evidence, the owner-revisioned
  three-way classifier, operation/attempt phase-CAS journal, and typed
  retry/cancel/status behavior exist without a production binding. B2a adds
  authenticated Source envelopes, an owner-created bounded byte sink, and a
  private identity-checked quarantine capability. B2b adds raw ZIP-layout
  preflight, portable path/type rejection, bounded inert wheel/RECORD
  verification, and extraction through a rooted owner-only writer after all
  claims pass. B2c binds those dark components to operation phase-CAS plus a
  typed evidence journal, but no production route. Dependency resolution,
  publication, and every production acquisition route remain absent. B2d adds
  durable cleanup-domain tombstones and exact repair. B2e adds evidence-driven acquired/verified
  crash adoption without Source reauthorization. B2f adds the accepted native
  Windows rooted-handle backend and mandatory CI fixture. Its non-skippable
  native gate passed against commit `fb263301` in Windows Shell Compatibility
  run `33486925218`: all five fixtures executed with zero skips, failures, or
  errors, and the XML reports were persisted as an Actions artifact. B2g adds
  the first six implemented acquisition-level end-to-end manifest fixtures;
  their non-skippable Linux CI gate and persisted XML evidence passed. B2h adds
  24 implemented archive/path/type/limit/wheel manifest fixtures; their
  Linux-native CI report executed without skips and persisted its XML evidence.
  B2i implements seven Windows path, collision, reparse, and junction rows;
  their dedicated non-skippable Windows report passed and retained its XML.
  B2j implements artifact-identity replacement, four early crash edges, and
  rejected quarantine cleanup debt after their Linux-native report passed.
  B2k corrects the hardlink threat model and implements one POSIX-native source
  normalization row after its Linux-native report passed.
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

## PLC9B1 Dark Owner Kernel

The first runtime slice lives only under
`loushang.harness.resources.packages.plugin_lifecycle`. It implements:

- strict versioned request, owner-fact, classification, status, failure,
  retry/cancel, and journal records;
- credential-free canonical Source identity and deterministic SHA-256 request
  and evidence fingerprints over canonical integer-only JSON;
- a three-way classifier that consumes all four owner-revisioned basis facts,
  gives Plugin intent/binding/history precedence, and accepts `non_plugin` only
  from the independent non-Plugin authority fact;
- append-only operation and attempt CAS domains, contiguous attempt epochs,
  idempotent exact replay, conflict/stale refusal without journal mutation,
  and crash/retry recovery from the last proved phase; and
- an owner-disabled response that returns the stable
  `package_route_unavailable` failure without creating a lock or journal.

The owner defaults disabled and has no production composition. Its package is
not re-exported from `loushang.harness.resources.packages`, and no transport,
Session, startup, author SDK, management owner, materializer, Source adapter,
revision store, subprocess, network client, extractor, or desired-state port
is imported or called. The only filesystem authority in PLC9B1 is the injected
private journal path. Tests may explicitly enable the owner to exercise inert
state transitions; this does not activate an artifact route.

The executable B1 manifest subset is exactly
`B-CLASS-PLUGIN`, `B-CLASS-NONPLUGIN`, `B-CLASS-INDETERMINATE`,
`B-CLASS-SPOOF`, `B-CRASH-ACCEPTED`, `B-CRASH-CLASSIFIED`,
`B-CONCUR-CONFLICT`, and `B-ENTRY-DISABLED`. Rows whose barrier spans later
acquisition, extraction, closure, publication, handoff, epoch, or every-phase
behavior remain `planned`; partial record-level coverage does not promote
their status.

## PLC9B2a Bounded Acquisition Component

`loushang.harness.resources.packages.plugin_lifecycle.acquisition` introduces
the first independently testable B2 component without activating it:

- a Source Authority returns one versioned authenticated envelope plus a
  transfer capability; raw credentials stay behind that authority;
- the Package owner validates operation/node, credential-free canonical Source
  identity, locator digest, and policy revision before creating quarantine;
- the owner alone creates a private attempt directory and an exclusive regular
  artifact file relative to an identity-pinned root on descriptor-capable
  POSIX hosts and the accepted B2f Windows backend;
- the Source adapter receives only `begin_request`, `record_redirect`, and
  `write`; it receives no pathname, file handle, root, store, publication, or
  desired-state authority;
- byte, request, redirect, and wall-clock budgets are checked before each
  corresponding consumption edge; declared digest mismatch is terminal;
- the acquired candidate revalidates root/attempt/file identity and hashes the
  artifact by bounded streaming before yielding a verifier handle; and
- rejection closes the sink and removes only the exact owner-created attempt.

The portable fallback rejects link/reparse roots and every currently visible
link/reparse ancestor. B2f replaces that fallback on Windows with the accepted
native rooted-handle backend; the native swap/ABA gate is recorded below.
Consequently these B2 components promote no global adversarial manifest row:
the `B-ACQ-*`, `B-LIMIT-*`, `B-STATE-*`, and later-phase crash rows retain
`planned` until the complete caller response, journal effect, and native oracle
specified by each row are executable.

## PLC9B2b Safe Wheel Inspection Component

`loushang.harness.resources.packages.plugin_lifecycle.wheel` consumes only the
opaque acquired-candidate capability from B2a. It remains dark and provides no
Product or transport composition. Before materializing any archive entry it:

- parses the EOCD, central directory, and every local header directly; rejects
  comments, Zip64/multi-disk/data-descriptor/encrypted or unsupported forms,
  prefixes, gaps, overlap, truncation, trailing payload, and inconsistent raw
  metadata;
- applies entry, aggregate expansion, per-entry expansion, metadata,
  component/depth, component/total path, and wall-clock limits at declaration
  and byte-consumption edges;
- rejects absolute/root-relative/traversal/drive/UNC/ADS/reserved-device,
  trailing-dot/space and separator-ambiguous names, then detects global
  Unicode-NFC and case-fold collisions plus file/ancestor conflicts;
- accepts only regular files/directories and ignores no link, device, reparse,
  socket, FIFO, encryption, or executable archive semantics;
- accepts only a compatible `.whl`, binds its filename to the sole matching
  `.dist-info`, verifies `WHEEL` tags and `METADATA` Name/Version, streams all
  file hashes, and proves the exact `RECORD` set with only SHA-256/384/512;
- revalidates the acquired artifact digest immediately before extraction, then
  creates directories/files exclusively beneath the pinned attempt using
  descriptor-relative no-follow operations on supported POSIX hosts and the
  accepted B2f Windows backend; and
- returns versioned `VerifiedWheelArtifactV1` evidence plus an opaque candidate
  whose only current operation is exact cleanup. It exposes no pathname or
  file handle to B3, transports, Products, or Source adapters.

The verifier deliberately rejects source distributions, arbitrary ZIP files,
editable/build inputs, archive extras, and weak/unknown RECORD algorithms. Its
portable fallback is defense-in-depth only. B2f supplies the accepted native
Windows rooted-writer backend, but B2b promotes no global manifest row: those
rows require the complete journaled failure/status response and phase oracle
on Linux and Windows, not merely a passing component test.

## PLC9B2c Dark Artifact Phase Composition

`loushang.harness.resources.packages.plugin_lifecycle.runtime` composes the B1
kernel, B2a acquisition owner, B2b verifier, and a separate typed phase-evidence
journal without activating a Product route. The operation journal now permits
only adjacent success transitions and current-or-adjacent terminal failure
stages. A retryable operation failure preserves the proved operation revision
and appends once in the attempt domain; a terminal artifact rejection appends
once in the operation domain. Stale attempts return a local refusal and append
nothing.

Before Source authority is called, the dark artifact owner rechecks the full
classification evidence. It journals `BoundedAcquisitionReceiptV1` before the
`acquired` transition and `VerifiedWheelArtifactV1` before the `extracted`
transition. Evidence is append-once per operation/attempt/node/kind, binds the
same request fingerprint, and requires the wheel digest/size to match its exact
acquisition parent. The evidence journal is strict JSONL with duplicate-key,
schema, ordering, contiguous revision, and CAS-predecessor validation.

This sub-slice alone does not claim complete B2 recovery. B2d closes the
durable cleanup-domain tombstone/repair obligation and B2e closes the local
acquired/verified evidence adoption window. B2f supplies the accepted native
Windows root-relative create/open/swap fixtures. No additional global
adversarial manifest row changes from `planned` in B2c because this slice does
not execute each row's complete response, journal, and recovery oracle.

## PLC9B2d Durable Quarantine Cleanup Domain

An acquisition or wheel rejection first preserves its original operation or
attempt-domain failure. If immediate cleanup cannot remove the exact
owner-created attempt, the artifact owner additionally appends one versioned
cleanup tombstone. The two facts are deliberately not collapsed:

- operation/attempt status retains the original code, stage, retryability, and
  request fingerprint;
- cleanup status uses `package_quarantine_cleanup_retryable`, subject kind
  `cleanup`, retry domain `cleanup`, and operator action `repair`;
- the tombstone contains only operation/node/attempt identity, store and
  attempt filesystem identities, a deterministic owner attempt name, and a
  SHA-256 cleanup id. It contains no absolute path, Source locator, credential,
  archive entry name, or unbounded error text; and
- deferring cleanup closes the live owner descriptors before transferring the
  inert tombstone to the durable cleanup journal.

Repair holds cleanup-domain CAS, reopens only the configured quarantine store,
proves its identity and the exact attempt identity, and recursively deletes
children with no-follow root-relative operations on descriptor-capable POSIX.
Links are unlinked as entries and never traversed. A changed/moved attempt
fails without a journal append or outside deletion. If deletion completed but
the process crashed before `cleanup_complete`, replay scans the fixed store for
the original attempt identity; only proven absence permits the completion
append. Repair never advances, retries, or reopens the terminal/retryable
Package operation.

The portable path implementation remains defense-in-depth. The accepted B2f
backend supplies rooted native cleanup primitives, but its five-fixture gate
does not execute the cleanup-journal tombstone/repair/swap oracle. Therefore
`B-STATE-REJECT-CLEANUP` remains `planned` until that complete oracle runs on
native Windows CI; B2d's component and Linux tests alone do not promote the
global row.

## PLC9B2e Evidence-Driven Crash Adoption

The artifact owner can now resume the two write-ahead windows where durable
evidence exists but the adjacent operation phase was not appended:

- `acquiring` plus an exact `BoundedAcquisitionReceiptV1` reopens the
  deterministic owner attempt, proves the configured store identity, attempt
  identity, sink identity, regular artifact size, and full byte digest, then
  advances through `acquired` without calling Source Authority again;
- `inspecting` plus exact `VerifiedWheelArtifactV1` evidence reopens the same
  acquired artifact, removes only the rooted owner-created extraction tree,
  reruns inert wheel verification locally, and requires byte-for-byte equal
  verified evidence before advancing to `extracted`; and
- an already active `extracted` operation uses the same local reopen/reverify
  path to reconstruct its opaque process-local candidate. It does not append a
  second evidence record or acquire bytes again.

Process-local candidates expose an explicit suspension edge that closes their
descriptors without deleting durable quarantine state. Recovery never accepts
phase alone as proof, never reconstructs a caller pathname, and never uses
Source reauthorization as a fallback. Missing, mismatched, replaced, or
malformed durable evidence fails closed; exact identity-pinned cleanup remains
separate from operation rejection through the B2d cleanup domain.

B2e is still an unbound component slice. The global `B-CRASH-*`
rows cover every phase, the complete committed-set transaction, and native
platform oracles, so they remain `planned` until those obligations are
executable on Linux and Windows CI.

## PLC9B2f Accepted Native Windows Quarantine

`plugin_lifecycle.windows_quarantine` is a Package-owner-local backend; it does
not import Coding, Foundation, a Product adapter, or a public author SDK. On
Windows it pins the configured quarantine root with `CreateFileW`,
`FILE_FLAG_OPEN_REPARSE_POINT`, and `FILE_FLAG_BACKUP_SEMANTICS`, then performs
every attempt, artifact, extraction-tree, and nested-entry create/open through
`NtCreateFile` with the pinned parent in `OBJECT_ATTRIBUTES.RootDirectory`.
Direct directories and regular files are reparse-checked after handle open.

Cleanup enumerates only through the final path of an already pinned directory;
each discovered child is independently reopened relative to that handle, and
mutation uses `SetFileInformationByHandle`. A reparse child is deleted as an
entry and never traversed. Root/attempt handles omit delete sharing while live,
so rename/replace cannot race a successful operation; recovery after handles
close still requires the durable B2e sink identity and full artifact digest.

The Windows workflow contains a dedicated report that exercises successful
acquire/read/cleanup, live root pinning, pre-attempt root replacement,
partial-tree recovery without a second Source call, attempt reparse rejection,
and full-root ABA rejection. The report is rejected if empty, skipped, or
failing and is retained as an artifact from the hidden report directory.

B2f was accepted on 2026-09-01 by
[Windows Shell Compatibility run `33486925218`](https://github.com/zhnt/loushang/actions/runs/33486925218),
job `99789069453`, against head `fb263301`. The dedicated report recorded
`5 passed`, `0 skipped`, `0 failures`, and `0 errors`; artifact
`windows-shell-pytest-reports` (ID `9792151355`) persisted all three shell XML
reports with upload digest
`0b0fdd5a809e401ea40472d4b299eaea3f75f33cdef46fdaae66916f138f9258`.
This acceptance is scoped to the rooted Windows quarantine backend and the five
named fixtures. It does not promote broader manifest rows whose complete
caller response, phase journal, cleanup repair, closure, or publication oracle
is still absent.

## PLC9B2g Accepted Acquisition Manifest Slice

The first B2 manifest acceptance slice executes `B-ACQ-AUTH`,
`B-ACQ-PROVENANCE`, `B-ACQ-BYTES`, `B-ACQ-REDIRECT`, `B-ACQ-TIMEOUT`, and
`B-ACQ-DIGEST` through the composed dark artifact owner rather than testing an
isolated exception. Each fixture begins with the single ingress/classification
authority and observes the typed caller status plus the operation or attempt
journal selected by the frozen journal-effect policy.

The fixtures additionally prove exact replay without a second Source Authority
call, empty evidence and cleanup journals, zero quarantine residue, an unchanged
outside sentinel, and absence of the injected credential from result repr and
every persisted file. Byte and time consumption are checked before the failing
edge; authorization and provenance refusal occur before a quarantine attempt;
declared digest mismatch terminates at the adjacent `acquired` stage.

The slice was accepted on 2026-09-01 by
[Harness Quality run `33487861156`](https://github.com/zhnt/loushang/actions/runs/33487861156),
Linux harness job `99792062800`, against head `12c7f844`. The report executed
all 14 then-implemented manifest nodes (the eight B1 nodes plus these six B2
nodes) with `0 skipped`, `0 failures`, and `0 errors`. Artifact
`plc9b-linux-native-pytest-report` (ID `9792500305`) persisted the XML with
upload digest
`4cd7756396e0ee2ce19143c35c5dd5020e21b27c663ce6716a0f49e28d121fed`.
The six `B-ACQ-*` rows named above are therefore `implemented`. The slice does
not activate a production route, inspect an archive, publish an artifact, or
alter desired state; every broader row remains `planned` until its own complete
oracle executes.

## PLC9B2h Accepted Archive And Wheel Manifest Slice

B2h drives 24 additional rows through the composed dark artifact owner: all
five `B-ARCH-*` rows; portable absolute, traversal, empty-component,
separator-ambiguous, and Unicode-collision path rows; POSIX symlink, device,
socket, and FIFO entry types; entry, metadata-memory, and wall-clock limits;
and the seven source-distribution/arbitrary-ZIP/tag/METADATA/RECORD wheel rows.
Each fixture proves the caller-visible status and operation journal append,
one bounded acquisition evidence record, exact replay without a second Source
call, empty cleanup debt, zero quarantine residue, an unchanged outside
sentinel, no imported wheel module, and no persisted credential.

Executable evidence corrected two planned-row labels without weakening a
barrier. A backslash-containing ZIP name is rejected as an ambiguous path
before separator normalization, so `B-PATH-COLLISION-SEP` returns
`package_archive_path_rejected`; treating it as a normalized candidate would
create an avoidable alias surface. WHEEL and METADATA identity are validated
before materialization, so `B-WHEEL-METADATA` is rejected at `inspecting`, not
at `extracted`. RECORD relation failures remain at the adjacent `extracted`
proof barrier and still occur before a tree becomes selectable.

`B-TYPE-HARDLINK` was deliberately not included in B2h. Wheel 1.x carries no
portable hardlink inode/relation field, and substituting a symlink or merely
labelling duplicate bytes as a hardlink would be false rejection evidence.

B2h was accepted on 2026-09-01 by
[Harness Quality run `33489524268`](https://github.com/zhnt/loushang/actions/runs/33489524268),
Linux harness job `99797440636`, against head `85896c68`. The report executed
all 38 then-implemented manifest nodes with `0 skipped`, `0 failures`, and
`0 errors`. Artifact `plc9b-linux-native-pytest-report` (ID `9793161479`)
persisted the XML with upload digest
`a858b55a60665b69b1a83dbfe29ef00d3b0ef48107b1d7c112a297f0a125e50f`.
The 24 rows named above are therefore `implemented`; this does not promote the
hardlink-source normalization, Windows-native, cleanup/recovery, closure,
publication, or route rows.

## PLC9B2i Accepted Windows Archive Manifest Slice

B2i adds exact fixtures for `B-PATH-WIN-ROOT`, `B-PATH-WIN-ADS`,
`B-PATH-WIN-RESERVED`, `B-PATH-WIN-TRAILING`, `B-PATH-COLLISION-CASE`,
`B-TYPE-REPARSE`, and `B-TYPE-JUNCTION`. The path fixtures encode drive-root,
alternate-data-stream, reserved-device, trailing-dot/space, and case-fold
aliases directly in the central directory. Reparse uses a Windows-made file
entry with `FILE_ATTRIBUTE_REPARSE_POINT`; junction uses a Windows-made
directory entry carrying both directory and reparse attributes. Neither type
is simulated with a POSIX symlink.

The Windows workflow names all seven pytest nodes explicitly, writes a separate
`windows-shell-plc9b-manifest.xml`, rejects an empty, skipped, failing, or
errored report, and includes it in the persisted shell artifact. Portable local
execution remains defense-in-depth only and cannot accept a Windows-native row.

B2i was accepted on 2026-09-01 by
[Windows Shell Compatibility run `33490630717`](https://github.com/zhnt/loushang/actions/runs/33490630717),
Windows shell job `99801011799`, against head `84722fa7`. The dedicated report
executed all seven named nodes with `0 skipped`, `0 failures`, and `0 errors`.
Artifact `windows-shell-pytest-reports` (ID `9793609340`) retained that XML with
upload digest
`dc2ecd99cb325da76a7c3fcb341f25c7c60da2b872544e0dbbfce8aa87ac9f6c`.
The seven rows are therefore `implemented`. This slice remains dark and
performs no publication, binding, desired-state mutation, process execution,
import, or peer fallback.

## PLC9B2j Accepted Recovery And Cleanup Manifest Slice

B2j names exactly six fixtures: `B-ACQ-IDENTITY`, `B-CRASH-ACQUIRING`,
`B-CRASH-ACQUIRED`, `B-CRASH-INSPECTING`, `B-CRASH-EXTRACTED`, and
`B-STATE-REJECT-CLEANUP`.

The identity fixture lands a durable bounded-acquisition receipt, advances to
`inspecting`, closes process-local handles, replaces the quarantined artifact,
and proves replay rejects the changed inode and bytes without Source
reauthorization or outside deletion. Each crash fixture interrupts at the
named last-proved phase and proves an append-once `package_operation_interrupted`
attempt response, unchanged request fingerprint and artifact evidence, bounded
owner-root residue, and no Source or publication replay. The cleanup fixture
separates the terminal `package_archive_malformed` operation result from its
append-once `package_quarantine_cleanup_retryable` cleanup substatus, then
repairs only the exact owner-root tombstone without reopening the operation.

The existing `plc9b-linux-native` workflow executes the complete adversarial
file, writes a dedicated verified XML report, rejects empty, skipped, failing,
or errored reports, and persists the XML artifact. Portable local execution is
defense-in-depth only.

B2j was accepted on 2026-09-01 by
[Harness Quality run `33492402119`](https://github.com/zhnt/loushang/actions/runs/33492402119),
Linux harness job `99806683722`, against head `0a06172e`. The report executed
all 51 manifest nodes with `0 skipped`, `0 failures`, and `0 errors`, including
all six B2j nodes. Artifact `plc9b-linux-native-pytest-report` (ID `9794291799`)
retained the XML with upload digest
`64b7f93eb4e42555e33fcd67892d18daa28bdd8464b570a74924bab50d8891c6`.
The six rows are therefore `implemented`. Closure, pins, publication, commit
admission, desired state, binding, and production routes remain absent.

## PLC9B2k Accepted POSIX Hardlink Normalization Slice

The current
[Wheel binary distribution specification](https://packaging.python.org/en/latest/specifications/binary-distribution-format/)
defines Wheel 1.x as a ZIP archive whose installed files are authenticated by
`RECORD`; it defines no inode or hardlink relation. The deferred
[PEP 778](https://peps.python.org/pep-0778/) likewise requires a future Wheel
major version even for symlinks and explicitly leaves hardlinks to a future
PEP. PLC9B therefore must not invent a hardlink entry type or reject two regular
members merely because their bytes match.

B2k changes `B-TYPE-HARDLINK` from the unrealizable `hardlink_entry` rejection
to `hardlinked_source_normalized`. The native fixture creates two POSIX names
for one source inode, archives both through Wheel 1.x, and proves the central
directory exposes only independent regular-file members with no link-bearing
extra field. The rooted verifier then creates each destination independently,
and the test proves distinct extracted inode identities with link count one.
No archive-controlled link operation exists anywhere in the verifier port.

B2k was accepted on 2026-09-01 by
[Harness Quality run `33493714647`](https://github.com/zhnt/loushang/actions/runs/33493714647),
Linux harness job `99810931103`, against head `3a89b7d2`. The report executed
all 52 manifest nodes with `0 skipped`, `0 failures`, and `0 errors`, including
`B-TYPE-HARDLINK`. Artifact `plc9b-linux-native-pytest-report` (ID
`9794816942`) retained the XML with upload digest
`254b4be987ea80b8f29a4f6b3034006965ad5a12257d879210fae83a7e21312f`.
The row is therefore `implemented`.

A future Wheel version that standardizes link semantics is unsupported input
until a separate reviewed contract and verifier are implemented; it cannot
inherit B2k's normalization proof.

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
        -> neutral artifact staging + designated Plugin-root publication
        -> atomic committed-set manifest + durable Package commit receipt
     -> non-Plugin: separately accepted non-Plugin authority only

management command -> Package commit-admission port -> exact designated root ref
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
| neutral artifact store evolution | consume pinned verified-candidate capabilities and issue `VerifiedArtifactRefV1` values only for inert dependency trees | cannot store or designate the Plugin root, commit a graph, authenticate Sources, verify closure, decide desired state, or return a selectable live handle |
| `PluginRevisionStore` evolution | consume the designated root candidate and issue one `PluginRevisionRefV1` bound to Installation/Plugin identity | current digest/source-only `reopen` and final-namespace `publish` do not satisfy Package commit admission; the store does not own dependencies, committed sets, Source authentication, closure, or desired state |
| closure-v2 evidence owner | bind every recursive node to its source, acquisition, wheel-verification and publication evidence plus the exact resolution environment | v1 replay records are not upgraded or reinterpreted as recursive evidence |
| Package commit-admission port | prove that a designated `PluginRevisionRefV1` is the root of one exact `CommittedPackageSetRefV1` for the request/operation, Product/scope, Installation/Plugin, and closure digest | cannot admit a dependency as root, mix refs from another set/operation/scope/Plugin, accept raw digests, mutate desired state, or return an uncommitted/staged object |
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
| verified closure plan v2 | designated root identity and role, every recursive node's canonical project identity, source-envelope fingerprint, acquisition-receipt fingerprint, wheel-evidence fingerprint, artifact/tree digests, normalized requirements, selected edges, markers, environment fingerprint, canonical order, counts, and prepublication graph digest; no stable refs yet |
| dependency closure node v2 | one immutable node constructed after staging from the corresponding verified-plan node plus exactly one typed stable publication ref and its store identity |
| dependency closure lock v2 | designated root node, every recursive immutable node, directed edges, marker evaluation, exact resolution-environment fingerprint, canonical order, node/set counts, and final graph/set digest |
| typed stable refs v1 | `VerifiedArtifactRefV1` is a neutral dependency-only artifact ref, `PluginRevisionRefV1` is the designated Installation/Plugin root's only physical stable ref, and `CommittedPackageSetRefV1` binds exactly one root plus dependency refs to the request/operation, Product/scope, identities, closure digest, and commit revision |
| retention-pin receipt v1 | operation/attempt, exact root and dependency candidates, pin kind/owner revision/lease, acquisition/release/transfer state, and recovery identity |
| retention handoff receipt v1 | handoff identity/receipt fingerprint, committed Package operation/receipt, exact transaction/dependency pin sets, desired command identity and expected revision, attempt epoch, state/revision, durable desired receipt when committed, and replay identity |
| immutable publication receipt v1 | operation/request identity, Product/scope and Installation/Plugin identities, classification and quarantine fingerprints, designated-root role/ref, complete closure graph/set digest, exact typed stable refs (never live handles), committed-set ref, retention-pin evidence, store/root identities, phase sequence, and commit revision |
| Package lifecycle status/failure v1 | subject kind/id, operation/request fingerprint, phase, attempt epoch, terminal disposition, evidence references, stable failure code/stage/retryability/retry domain/operator action, redacted bounded details, and status revision |

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

Closure evidence has two construction edges. `closure_verified` freezes the
complete `VerifiedClosurePlanV2` before publication and proves all Source,
artifact, resolution, and graph facts without pretending stable refs exist.
After every candidate is staged, the owner constructs every immutable closure
node and `DependencyClosureLockV2` once from the plan plus typed refs. Digested
evidence is never patched in place. The Package owner then writes the sole
`CommittedPackageSetRefV1`; neutral and Plugin-root stores retain authority only
over their respective typed refs.

There is no second physical root publication: the root closure node contains
exactly one `PluginRevisionRefV1` and its `PluginRevisionStore` identity, while
every dependency node contains exactly one `VerifiedArtifactRefV1` and neutral
store identity. The Package owner coordinates transaction retention across the
set and cleans only its quarantine; each store owns ref integrity/reopen, and
PLC9D later owns pin-authorized physical deletion through those store owners.

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
  Package commit-admission port is the only route from a designated root ref to
  a short-lived `VerifiedRevisionHandle`. Admission checks the request and
  operation fingerprints, Product/scope, Installation/Plugin identities,
  designated-root role/ref, exact committed-set identity, and closure/set
  digest. A dependency, a ref from another set, or a wrong operation, scope, or
  Plugin fails without reopening any store object.
- A later desired install/update uses one durable `RetentionHandoffReceiptV1`
  state machine: `opened -> dependency_pinned -> desired_committed -> settled`
  (or `aborted` before desired commit). It first obtains the exact dependency
  pin set under the handoff identity, then commits desired state with an
  expected-revision CAS, then presents that durable desired receipt to the
  retention port. Only after the retention owner atomically records `settled`
  may it release the transaction pin. There is no cross-owner atomic claim: a
  crash before desired commit leaves the transaction pin plus any acquired
  dependency pins; a crash after desired commit leaves both complete pin sets;
  replay from any edge converges to the exact set and never creates a zero-pin
  gap. A rejected desired CAS aborts/releases only dependency pins and retains
  the transaction pin. Stale receipts and concurrent replay cannot release or
  widen either set. Rejection, cancellation, or never-selected
  publication keeps the transaction pin visible to the same recovery state
  machine. PLC9D owns physical artifact deletion; PLC9B owns bounded quarantine
  cleanup and cannot silently drop retention evidence.

Slow Source I/O, parsing, hashing, and extraction never hold the journal lock.
Before creating a quarantine, each attempt reserves bytes/count against the
global quota and obtains a unique, owner-created, isolated directory plus a
bounded lease/fencing epoch. A stale attempt can write only inside that exact
directory until its lease/deadline and cannot write a newer attempt's directory
or any staged/publication namespace; its bounded residue remains charged until
rooted cleanup succeeds. Every phase append is
an expected-phase compare-and-swap over `(operation, request fingerprint,
attempt epoch, prior journal revision)`. A stale worker cannot append, renew a
lease, stage, publish a set, or commit after a newer recovery attempt has won.
No owner holds its lock while calling another owner, performing I/O, or waiting
on a lease. Publication and later selection are two distinct lock-free sagas:

1. The Package owner performs and releases its operation-phase CAS; calls the
   retention port to acquire the transaction pin and waits for that owner to
   release; calls stores in canonical `(store identity, typed ref)` order, each
   store holding and releasing only its own lock; performs/releases the
   committed-set CAS; then performs/releases the operation `committed` CAS and
   returns the receipt. It never calls the desired application.
2. A later management command first passes commit admission, calls the retention
   owner to acquire exact dependency pins and record `dependency_pinned`, calls
   the desired owner for its expected-revision CAS after the retention call has
   returned, then calls the retention owner again to record `desired_committed`
   and `settled` and release the transaction pin. Rejection calls that same
   retention owner to record `aborted` and release only dependency pins.

No cross-owner locks are nested, and every critical section is bounded.
Concurrent same-input attempts converge; different input rejects; an existing
digest is reusable only after exact candidate, set-membership, and store-identity
revalidation.

## Status, Diagnostics, And Operator Actions

`PackageLifecycleFailureV1` is a closed, versioned application record. It
contains `code`, `stage`, `retryable`, `retry_domain`, `operator_action`,
`subject_kind`, `subject_id`, `operation_id`, `evidence_ref`, and bounded
redacted details. Subject kind is versioned and routes a typed command to the
exact operation, handoff receipt, or cleanup tombstone; a handoff subject id is
its handoff identity plus receipt fingerprint. `retry_domain` is exactly one of
`none`, `operation`, `handoff`, or `cleanup`; cleanup retryability never
reopens or retries a terminal operation. `operator_action` is exactly one
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
| `package_attempt_stale` | terminal local refusal for the stale attempt; retry/recovery continues under the already-winning operation identity |
| `package_quarantine_cleanup_retryable` | terminal operation plus retryable owner-root cleanup substatus; retry domain `cleanup`, operator action `repair` |
| `package_operation_identity_conflict` | terminal; caller must use a new operation identity |
| `package_operation_cancelled` | terminal and operator-requested; a retry is a new operation |
| `package_retention_handoff_interrupted` | retryable fenced replay of the same handoff receipt; exact pins remain visible |
| `package_desired_revision_conflict` | terminal handoff abort; desired state and transaction pin remain unchanged |
| `package_retention_handoff_stale` | terminal caller refusal with no journal or pin mutation |
| `package_runtime_epoch_unsupported` | terminal in-process; upgrade runtime or offline restore |
| `package_route_unavailable` | terminal while PLC9B is disabled; never invokes a peer installer |

The retry policy is independently machine checked. `conditional` becomes true
only when the named condition is proved by the failure evidence; transports do
not reinterpret it. A typed retry requires the matching subject kind/id and
never falls through to another domain.

<!-- plc9b-retry-policy:start -->
```text
selector | retryability | retry_domain | retry_action
package_acquisition_limit_exceeded | conditional:no_acquired_digest | operation | retry
package_operation_timed_out | conditional:no_acquired_digest | operation | retry
package_operation_interrupted | true | operation | retry
package_retention_handoff_interrupted | true | handoff | retry
package_quarantine_cleanup_retryable | true | cleanup | repair
package_attempt_stale | false | none | none
package_retention_handoff_stale | false | none | none
default | false | none | none
```
<!-- plc9b-retry-policy:end -->

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
- only regular files and directories are accepted; recognized symlinks,
  junctions/reparse points, devices, sockets, and FIFOs are rejected. No ZIP
  extra field has link-creation authority, so Wheel 1.x source hardlinks that
  arrive as regular byte members remain unrelated in the materialized tree;
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
rooted cleanup; cleanup failure records
`package_quarantine_cleanup_retryable` in retry domain `cleanup`, keeps a
bounded tombstone/status projection, and blocks new admission before exceeding
the store quota. Repair retries only exact owner-root cleanup and never resumes
the terminal Package operation. Evidence journals
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
- an effect/capability inventory of 141 exact rows and 156 occurrences covering
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
row to `implemented`, provide the exact collected pytest node and workflow job,
and make either a missing node or a skip fail that job.

An `ok` code can describe an explicitly named nonterminal proved phase such as
`extracted`; it never implies `committed`, selection, publication, or binding.

`platform` is `any`, `posix-native`, or `windows-native`. `disposition` is the
caller-visible response outcome, not permission to append a terminal journal
row. The separate journal-effect policy below resolves each response to an
owned append or to `no_append:unchanged`; a refusal can never terminate or
alter an already-valid winner. Oracles use a closed vocabulary: `no_outside_write`,
`no_process`, `no_import`, `no_extra_network`, `no_publication`, `no_binding`,
`no_desired`, `no_peer_fallback`, `no_secret`, `bounded_residue`,
`same_receipt`, `pin_visible`, `single_owner`, `b_namespace_unreachable`,
`exact_pin_set`, `no_zero_pin`,
`transaction_pin_released`, `desired_unchanged`, `handle_released`,
`no_reopen`, `no_handle_issued`, `dependency_pins_released`,
`instance_unchanged`, `binding_unchanged`, `enablement_unchanged`,
`legacy_snapshot_exact`, and `no_skip`. `handle_released` is proved after both
success and refusal by native rename/delete/open probes against every opened
root/ancestor/entry handle; garbage collection or process exit is not proof.
Each `*_unchanged` oracle compares the named canonical projection's exact
before/after revision and bytes, not merely absence of a new row.
For restore, `legacy_snapshot_exact` compares the restored result to the
authenticated pre-B backup. For adoption, it compares the legacy namespace
before/after. Both cover the legacy root pointer, fence, Source configuration,
lock/binding history, desired/Instance/enablement state, and store bytes as one
snapshot; a newly isolated B publication is outside that comparison.

<!-- plc9b-adversarial-manifest:start -->
```text
case_id | platform | barrier | fixture | code | disposition | oracles | test_node | workflow | status
B-CLASS-PLUGIN | any | classified | explicit_plugin_intent | ok | classified@plugin_bound | single_owner;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLASS-PLUGIN] | harness-quality.yml#plc9b-linux-native | implemented
B-CLASS-NONPLUGIN | any | classified | independent_non_plugin_evidence | ok | classified@non_plugin | single_owner;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLASS-NONPLUGIN] | harness-quality.yml#plc9b-linux-native | implemented
B-CLASS-INDETERMINATE | any | classified | unknown_source | package_target_classification_indeterminate | rejected@classified | no_publication;no_binding;no_desired;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLASS-INDETERMINATE] | harness-quality.yml#plc9b-linux-native | implemented
B-CLASS-CHANGED | any | staging | classification_revision_race | package_target_classification_changed | rejected@staging | no_publication;no_binding;no_desired;no_peer_fallback;pin_visible | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLASS-CHANGED] | harness-quality.yml#plc9b-linux-native | planned
B-CLASS-SPOOF | any | classified | caller_non_plugin_boolean | package_target_classification_indeterminate | rejected@classified | single_owner;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLASS-SPOOF] | harness-quality.yml#plc9b-linux-native | implemented
B-ACQ-AUTH | any | acquiring | unauthenticated_origin | package_source_unauthorized | rejected@acquiring | no_extra_network;no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ACQ-AUTH] | harness-quality.yml#plc9b-linux-native | implemented
B-ACQ-PROVENANCE | any | acquiring | changed_authority | package_source_provenance_changed | rejected@acquiring | no_publication;no_binding;no_peer_fallback;no_secret | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ACQ-PROVENANCE] | harness-quality.yml#plc9b-linux-native | implemented
B-ACQ-BYTES | any | acquiring | byte_limit | package_acquisition_limit_exceeded | retryable_failure@acquiring | bounded_residue;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ACQ-BYTES] | harness-quality.yml#plc9b-linux-native | implemented
B-ACQ-REDIRECT | any | acquiring | redirect_limit | package_acquisition_limit_exceeded | retryable_failure@acquiring | bounded_residue;no_extra_network;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ACQ-REDIRECT] | harness-quality.yml#plc9b-linux-native | implemented
B-ACQ-TIMEOUT | any | acquiring | wall_clock_limit | package_operation_timed_out | retryable_failure@acquiring | bounded_residue;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ACQ-TIMEOUT] | harness-quality.yml#plc9b-linux-native | implemented
B-ACQ-DIGEST | any | acquired | declared_digest_mismatch | package_acquisition_digest_mismatch | rejected@acquired | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ACQ-DIGEST] | harness-quality.yml#plc9b-linux-native | implemented
B-ACQ-IDENTITY | any | inspecting | archive_replacement | package_artifact_identity_changed | rejected@inspecting | no_outside_write;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ACQ-IDENTITY] | harness-quality.yml#plc9b-linux-native | implemented
B-ARCH-TRUNCATED | any | inspecting | truncated_archive | package_archive_malformed | rejected@inspecting | bounded_residue;no_outside_write;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ARCH-TRUNCATED] | harness-quality.yml#plc9b-linux-native | implemented
B-ARCH-HEADERS | any | inspecting | inconsistent_headers | package_archive_malformed | rejected@inspecting | no_outside_write;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ARCH-HEADERS] | harness-quality.yml#plc9b-linux-native | implemented
B-ARCH-OVERLAP | any | inspecting | overlapping_entries | package_archive_malformed | rejected@inspecting | no_outside_write;no_publication;bounded_residue | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ARCH-OVERLAP] | harness-quality.yml#plc9b-linux-native | implemented
B-ARCH-COMPRESSION | any | inspecting | unsupported_compression_or_encryption | package_archive_malformed | rejected@inspecting | no_process;no_outside_write;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ARCH-COMPRESSION] | harness-quality.yml#plc9b-linux-native | implemented
B-ARCH-TRAILING | any | inspecting | trailing_payload | package_archive_malformed | rejected@inspecting | no_outside_write;no_publication;no_binding | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ARCH-TRAILING] | harness-quality.yml#plc9b-linux-native | implemented
B-PATH-ABSOLUTE | any | inspecting | absolute_path | package_archive_path_rejected | rejected@inspecting | no_outside_write;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-ABSOLUTE] | harness-quality.yml#plc9b-linux-native | implemented
B-PATH-TRAVERSAL | any | inspecting | parent_traversal | package_archive_path_rejected | rejected@inspecting | no_outside_write;no_publication;no_binding | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-TRAVERSAL] | harness-quality.yml#plc9b-linux-native | implemented
B-PATH-EMPTY | any | inspecting | empty_or_dot_component | package_archive_path_rejected | rejected@inspecting | no_outside_write;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-EMPTY] | harness-quality.yml#plc9b-linux-native | implemented
B-PATH-WIN-ROOT | windows-native | inspecting | drive_or_unc_path | package_archive_path_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-WIN-ROOT] | windows-shell-compatibility.yml#plc9b-windows-native | implemented
B-PATH-WIN-ADS | windows-native | inspecting | alternate_data_stream | package_archive_path_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-WIN-ADS] | windows-shell-compatibility.yml#plc9b-windows-native | implemented
B-PATH-WIN-RESERVED | windows-native | inspecting | reserved_device_name | package_archive_path_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-WIN-RESERVED] | windows-shell-compatibility.yml#plc9b-windows-native | implemented
B-PATH-WIN-TRAILING | windows-native | inspecting | trailing_dot_or_space | package_archive_path_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-WIN-TRAILING] | windows-shell-compatibility.yml#plc9b-windows-native | implemented
B-PATH-COLLISION-SEP | any | inspecting | separator_ambiguous_path | package_archive_path_rejected | rejected@inspecting | no_outside_write;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-COLLISION-SEP] | harness-quality.yml#plc9b-linux-native | implemented
B-PATH-COLLISION-UNICODE | any | inspecting | unicode_collision | package_archive_name_collision | rejected@inspecting | no_outside_write;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-COLLISION-UNICODE] | harness-quality.yml#plc9b-linux-native | implemented
B-PATH-COLLISION-CASE | windows-native | inspecting | casefold_collision | package_archive_name_collision | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PATH-COLLISION-CASE] | windows-shell-compatibility.yml#plc9b-windows-native | implemented
B-TYPE-SYMLINK | posix-native | inspecting | symlink_entry | package_archive_entry_type_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-TYPE-SYMLINK] | harness-quality.yml#plc9b-linux-native | implemented
B-TYPE-HARDLINK | posix-native | extracted | hardlinked_source_normalized | ok | extracted@independent_regular_files | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-TYPE-HARDLINK] | harness-quality.yml#plc9b-linux-native | implemented
B-TYPE-DEVICE | posix-native | inspecting | device_entry | package_archive_entry_type_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-TYPE-DEVICE] | harness-quality.yml#plc9b-linux-native | implemented
B-TYPE-SOCKET | posix-native | inspecting | socket_entry | package_archive_entry_type_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-TYPE-SOCKET] | harness-quality.yml#plc9b-linux-native | implemented
B-TYPE-FIFO | posix-native | inspecting | fifo_entry | package_archive_entry_type_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-TYPE-FIFO] | harness-quality.yml#plc9b-linux-native | implemented
B-TYPE-REPARSE | windows-native | inspecting | reparse_entry | package_archive_entry_type_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-TYPE-REPARSE] | windows-shell-compatibility.yml#plc9b-windows-native | implemented
B-TYPE-JUNCTION | windows-native | inspecting | junction_entry | package_archive_entry_type_rejected | rejected@inspecting | no_outside_write;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-TYPE-JUNCTION] | windows-shell-compatibility.yml#plc9b-windows-native | implemented
B-LIMIT-ENTRY | any | inspecting | entry_or_expansion_budget | package_resource_limit_exceeded | rejected@inspecting | bounded_residue;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-LIMIT-ENTRY] | harness-quality.yml#plc9b-linux-native | implemented
B-LIMIT-MEMORY | any | inspecting | parser_or_metadata_memory | package_resource_limit_exceeded | rejected@inspecting | bounded_residue;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-LIMIT-MEMORY] | harness-quality.yml#plc9b-linux-native | implemented
B-LIMIT-CPU | any | inspecting | cpu_or_wall_budget | package_resource_limit_exceeded | rejected@inspecting | bounded_residue;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-LIMIT-CPU] | harness-quality.yml#plc9b-linux-native | implemented
B-LIMIT-GRAPH | any | resolving_closure | closure_node_edge_depth | package_resource_limit_exceeded | rejected@resolving_closure | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-LIMIT-GRAPH] | harness-quality.yml#plc9b-linux-native | planned
B-LIMIT-SOLVER | any | resolving_closure | solver_or_marker_steps | package_resource_limit_exceeded | rejected@resolving_closure | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-LIMIT-SOLVER] | harness-quality.yml#plc9b-linux-native | planned
B-LIMIT-REQUESTS | any | acquiring | request_redirect_artifact_count | package_resource_limit_exceeded | rejected@acquiring | no_extra_network;no_publication;bounded_residue | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-LIMIT-REQUESTS] | harness-quality.yml#plc9b-linux-native | planned
B-WHEEL-SDIST | any | inspecting | source_distribution | package_artifact_type_rejected | rejected@inspecting | no_process;no_import;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-WHEEL-SDIST] | harness-quality.yml#plc9b-linux-native | implemented
B-WHEEL-ZIP | any | inspecting | arbitrary_zip_or_editable | package_artifact_type_rejected | rejected@inspecting | no_process;no_import;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-WHEEL-ZIP] | harness-quality.yml#plc9b-linux-native | implemented
B-WHEEL-TAGS | any | inspecting | unsupported_wheel_tags | package_artifact_type_rejected | rejected@inspecting | no_publication;no_binding | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-WHEEL-TAGS] | harness-quality.yml#plc9b-linux-native | implemented
B-WHEEL-METADATA | any | inspecting | wheel_metadata_mismatch | package_wheel_metadata_invalid | rejected@inspecting | no_publication;no_binding;no_desired | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-WHEEL-METADATA] | harness-quality.yml#plc9b-linux-native | implemented
B-WHEEL-RECORD-HASH | any | extracted | record_hash_or_size | package_wheel_record_invalid | rejected@extracted | no_publication;no_binding;no_desired | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-WHEEL-RECORD-HASH] | harness-quality.yml#plc9b-linux-native | implemented
B-WHEEL-RECORD-SET | any | extracted | record_missing_or_unlisted | package_wheel_record_invalid | rejected@extracted | no_publication;no_binding;no_desired | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-WHEEL-RECORD-SET] | harness-quality.yml#plc9b-linux-native | implemented
B-WHEEL-RECORD-ALGO | any | extracted | weak_or_unknown_record_hash | package_wheel_record_invalid | rejected@extracted | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-WHEEL-RECORD-ALGO] | harness-quality.yml#plc9b-linux-native | implemented
B-CLOSURE-MISSING | any | resolving_closure | missing_dependency | package_closure_artifact_invalid | rejected@resolving_closure | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLOSURE-MISSING] | harness-quality.yml#plc9b-linux-native | planned
B-CLOSURE-DIGEST | any | resolving_closure | dependency_digest_mismatch | package_closure_artifact_invalid | rejected@resolving_closure | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLOSURE-DIGEST] | harness-quality.yml#plc9b-linux-native | planned
B-CLOSURE-ORIGIN | any | resolving_closure | dependency_unauthorized_origin | package_closure_artifact_invalid | rejected@resolving_closure | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLOSURE-ORIGIN] | harness-quality.yml#plc9b-linux-native | planned
B-CLOSURE-MARKER | any | resolving_closure | marker_or_environment_mismatch | package_closure_conflict | rejected@resolving_closure | no_publication;no_binding;no_desired | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLOSURE-MARKER] | harness-quality.yml#plc9b-linux-native | planned
B-CLOSURE-NAME | any | resolving_closure | duplicate_name_or_version | package_closure_conflict | rejected@resolving_closure | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLOSURE-NAME] | harness-quality.yml#plc9b-linux-native | planned
B-CLOSURE-CYCLE | any | resolving_closure | dependency_cycle | package_closure_conflict | rejected@resolving_closure | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLOSURE-CYCLE] | harness-quality.yml#plc9b-linux-native | planned
B-CLOSURE-V1 | any | resolving_closure | v1_or_future_evidence | package_closure_evidence_unsupported | rejected@resolving_closure | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CLOSURE-V1] | harness-quality.yml#plc9b-linux-native | planned
B-PUB-PRECREATE | any | staging | precreated_quarantine | package_publication_root_untrusted | rejected@staging | no_outside_write;no_publication;pin_visible | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PUB-PRECREATE] | harness-quality.yml#plc9b-linux-native | planned
B-PUB-POSIX-ROOT-SWAP | posix-native | staging | root_rename_replace_swap | package_publication_root_untrusted | rejected@staging | no_outside_write;no_publication;pin_visible;handle_released;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PUB-POSIX-ROOT-SWAP] | harness-quality.yml#plc9b-linux-native | planned
B-PUB-POSIX-ANCESTOR-SWAP | posix-native | staging | ancestor_rename_replace_swap | package_publication_root_untrusted | rejected@staging | no_outside_write;no_publication;pin_visible;handle_released;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PUB-POSIX-ANCESTOR-SWAP] | harness-quality.yml#plc9b-linux-native | planned
B-PUB-POSIX-HANDLE-SUCCESS | posix-native | committed | successful_native_handle_lifecycle | ok | committed@committed | same_receipt;pin_visible;handle_released;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PUB-POSIX-HANDLE-SUCCESS] | harness-quality.yml#plc9b-linux-native | planned
B-PUB-POSIX-HANDLE-REJECT | posix-native | rejected | rejected_native_handle_lifecycle | package_publication_root_untrusted | rejected@staging | no_outside_write;no_publication;pin_visible;handle_released;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PUB-POSIX-HANDLE-REJECT] | harness-quality.yml#plc9b-linux-native | planned
B-PUB-SWAP-WINDOWS | windows-native | staging | ancestor_or_entry_reparse_swap | package_publication_root_untrusted | rejected@staging | no_outside_write;no_publication;pin_visible;handle_released;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PUB-SWAP-WINDOWS] | windows-shell-compatibility.yml#plc9b-windows-native | planned
B-PUB-WIN-ROOT-ABA | windows-native | staging | root_rename_replace_aba | package_publication_root_untrusted | rejected@staging | no_outside_write;no_publication;pin_visible;handle_released;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PUB-WIN-ROOT-ABA] | windows-shell-compatibility.yml#plc9b-windows-native | planned
B-PUB-WIN-ANCESTOR-ABA | windows-native | staging | ancestor_junction_reparse_aba | package_publication_root_untrusted | rejected@staging | no_outside_write;no_publication;pin_visible;handle_released;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PUB-WIN-ANCESTOR-ABA] | windows-shell-compatibility.yml#plc9b-windows-native | planned
B-PUB-WIN-HANDLE-SUCCESS | windows-native | committed | successful_native_handle_lifecycle | ok | committed@committed | same_receipt;pin_visible;handle_released;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PUB-WIN-HANDLE-SUCCESS] | windows-shell-compatibility.yml#plc9b-windows-native | planned
B-PUB-WIN-HANDLE-REJECT | windows-native | rejected | rejected_native_handle_lifecycle | package_publication_root_untrusted | rejected@staging | no_outside_write;no_publication;pin_visible;handle_released;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PUB-WIN-HANDLE-REJECT] | windows-shell-compatibility.yml#plc9b-windows-native | planned
B-PUB-COLLISION | any | set_published | same_digest_different_identity | package_publication_collision | rejected@staging | no_publication;no_binding;pin_visible | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PUB-COLLISION] | harness-quality.yml#plc9b-linux-native | planned
B-PUB-REUSE | any | set_published | exact_committed_set_exists | ok | committed@committed | same_receipt;pin_visible;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PUB-REUSE] | harness-quality.yml#plc9b-linux-native | planned
B-PUB-UNCOMMITTED | any | set_published | stable_ref_without_commit_receipt | package_commit_admission_denied | rejected@staging | no_binding;no_desired;pin_visible;no_reopen;no_handle_issued;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-PUB-UNCOMMITTED] | harness-quality.yml#plc9b-linux-native | planned
B-ADMISSION-DEPENDENCY | any | committed | dependency_ref_claimed_as_root | package_commit_admission_denied | rejected@committed | no_binding;no_desired;pin_visible;no_reopen;no_handle_issued;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ADMISSION-DEPENDENCY] | harness-quality.yml#plc9b-linux-native | planned
B-ADMISSION-WRONG-SET | any | committed | ref_from_other_committed_set | package_commit_admission_denied | rejected@committed | no_binding;no_desired;pin_visible;no_reopen;no_handle_issued;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ADMISSION-WRONG-SET] | harness-quality.yml#plc9b-linux-native | planned
B-ADMISSION-WRONG-REQUEST | any | committed | request_fingerprint_mismatch | package_commit_admission_denied | rejected@committed | no_binding;no_desired;pin_visible;no_reopen;no_handle_issued;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ADMISSION-WRONG-REQUEST] | harness-quality.yml#plc9b-linux-native | planned
B-ADMISSION-WRONG-OPERATION | any | committed | operation_fingerprint_mismatch | package_commit_admission_denied | rejected@committed | no_binding;no_desired;pin_visible;no_reopen;no_handle_issued;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ADMISSION-WRONG-OPERATION] | harness-quality.yml#plc9b-linux-native | planned
B-ADMISSION-WRONG-SCOPE | any | committed | product_or_scope_mismatch | package_commit_admission_denied | rejected@committed | no_binding;no_desired;pin_visible;no_reopen;no_handle_issued;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ADMISSION-WRONG-SCOPE] | harness-quality.yml#plc9b-linux-native | planned
B-ADMISSION-WRONG-PLUGIN | any | committed | installation_or_plugin_mismatch | package_commit_admission_denied | rejected@committed | no_binding;no_desired;pin_visible;no_reopen;no_handle_issued;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ADMISSION-WRONG-PLUGIN] | harness-quality.yml#plc9b-linux-native | planned
B-ADMISSION-DIGEST-TAMPER | any | committed | closure_or_set_digest_tamper | package_commit_admission_denied | rejected@committed | no_binding;no_desired;pin_visible;no_reopen;no_handle_issued;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ADMISSION-DIGEST-TAMPER] | harness-quality.yml#plc9b-linux-native | planned
B-CRASH-ACCEPTED | any | accepted | crash_edge | package_operation_interrupted | retryable_failure@accepted | same_receipt;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-ACCEPTED] | harness-quality.yml#plc9b-linux-native | implemented
B-CRASH-CLASSIFIED | any | classified | crash_edge | package_operation_interrupted | retryable_failure@classified | same_receipt;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-CLASSIFIED] | harness-quality.yml#plc9b-linux-native | implemented
B-CRASH-ACQUIRING | any | acquiring | crash_edge | package_operation_interrupted | retryable_failure@acquiring | same_receipt;bounded_residue;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-ACQUIRING] | harness-quality.yml#plc9b-linux-native | implemented
B-CRASH-ACQUIRED | any | acquired | crash_edge | package_operation_interrupted | retryable_failure@acquired | same_receipt;bounded_residue;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-ACQUIRED] | harness-quality.yml#plc9b-linux-native | implemented
B-CRASH-INSPECTING | any | inspecting | crash_edge | package_operation_interrupted | retryable_failure@inspecting | same_receipt;bounded_residue;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-INSPECTING] | harness-quality.yml#plc9b-linux-native | implemented
B-CRASH-EXTRACTED | any | extracted | crash_edge | package_operation_interrupted | retryable_failure@extracted | same_receipt;bounded_residue;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-EXTRACTED] | harness-quality.yml#plc9b-linux-native | implemented
B-CRASH-RESOLVING | any | resolving_closure | crash_edge | package_operation_interrupted | retryable_failure@resolving_closure | same_receipt;bounded_residue;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-RESOLVING] | harness-quality.yml#plc9b-linux-native | planned
B-CRASH-CLOSURE | any | closure_verified | crash_edge | package_operation_interrupted | retryable_failure@closure_verified | same_receipt;no_publication;no_binding | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-CLOSURE] | harness-quality.yml#plc9b-linux-native | planned
B-CRASH-PINNED | any | transaction_pinned | crash_edge | package_operation_interrupted | retryable_failure@transaction_pinned | same_receipt;pin_visible;no_publication | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-PINNED] | harness-quality.yml#plc9b-linux-native | planned
B-CRASH-STAGING | any | staging | crash_edge | package_operation_interrupted | retryable_failure@staging | same_receipt;pin_visible;no_binding | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-STAGING] | harness-quality.yml#plc9b-linux-native | planned
B-CRASH-SET | any | set_published | crash_edge | package_operation_interrupted | retryable_failure@set_published | same_receipt;pin_visible;no_binding;no_desired | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-SET] | harness-quality.yml#plc9b-linux-native | planned
B-CRASH-COMMITTED | any | committed | crash_after_edge | ok | committed@committed | same_receipt;pin_visible;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CRASH-COMMITTED] | harness-quality.yml#plc9b-linux-native | planned
B-CONCUR-SAME | any | each_phase | concurrent_same_fingerprint | ok | committed@committed | same_receipt;single_owner;pin_visible | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CONCUR-SAME] | harness-quality.yml#plc9b-linux-native | planned
B-CONCUR-CONFLICT | any | classified | concurrent_different_fingerprint | package_operation_identity_conflict | rejected@classified | single_owner;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CONCUR-CONFLICT] | harness-quality.yml#plc9b-linux-native | implemented
B-CONCUR-STALE | any | each_phase | stale_attempt_epoch | package_attempt_stale | rejected@prior_phase | single_owner;no_publication;no_binding;pin_visible | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-CONCUR-STALE] | harness-quality.yml#plc9b-linux-native | planned
B-HANDOFF-BEFORE-DESIRED | any | dependency_pinned | crash_after_dependency_pins | package_retention_handoff_interrupted | retryable_failure@dependency_pinned | exact_pin_set;no_zero_pin;desired_unchanged;pin_visible | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-HANDOFF-BEFORE-DESIRED] | harness-quality.yml#plc9b-linux-native | planned
B-HANDOFF-AFTER-DESIRED | any | desired_committed | crash_before_handoff_settlement | package_retention_handoff_interrupted | retryable_failure@desired_committed | exact_pin_set;no_zero_pin;pin_visible;same_receipt | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-HANDOFF-AFTER-DESIRED] | harness-quality.yml#plc9b-linux-native | planned
B-HANDOFF-AFTER-SETTLEMENT | any | settled | replay_after_transaction_pin_release | ok | settled@settled | exact_pin_set;no_zero_pin;transaction_pin_released;same_receipt | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-HANDOFF-AFTER-SETTLEMENT] | harness-quality.yml#plc9b-linux-native | planned
B-HANDOFF-DESIRED-REJECT | any | dependency_pinned | desired_expected_revision_rejected | package_desired_revision_conflict | rejected@dependency_pinned | exact_pin_set;no_zero_pin;dependency_pins_released;desired_unchanged;pin_visible | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-HANDOFF-DESIRED-REJECT] | harness-quality.yml#plc9b-linux-native | planned
B-HANDOFF-STALE-RECEIPT | any | each_handoff_phase | stale_handoff_receipt | package_retention_handoff_stale | rejected@prior_handoff | exact_pin_set;no_zero_pin;desired_unchanged;same_receipt | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-HANDOFF-STALE-RECEIPT] | harness-quality.yml#plc9b-linux-native | planned
B-HANDOFF-CONCURRENT-REPLAY | any | each_handoff_phase | concurrent_exact_handoff_replay | ok | settled@settled | exact_pin_set;no_zero_pin;transaction_pin_released;same_receipt;single_owner | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-HANDOFF-CONCURRENT-REPLAY] | harness-quality.yml#plc9b-linux-native | planned
B-ENTRY-CLI | any | classified | cli_plugin_bound | ok | committed@committed | single_owner;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ENTRY-CLI] | harness-quality.yml#plc9b-linux-native | planned
B-ENTRY-RPC | any | classified | rpc_plugin_bound | ok | committed@committed | single_owner;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ENTRY-RPC] | harness-quality.yml#plc9b-linux-native | planned
B-ENTRY-SESSION | any | classified | session_plugin_bound | ok | committed@committed | single_owner;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ENTRY-SESSION] | harness-quality.yml#plc9b-linux-native | planned
B-ENTRY-STARTUP | any | classified | startup_plugin_bound | ok | committed@committed | single_owner;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ENTRY-STARTUP] | harness-quality.yml#plc9b-linux-native | planned
B-ENTRY-OPERATIONS | any | classified | operations_plugin_bound | ok | committed@committed | single_owner;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ENTRY-OPERATIONS] | harness-quality.yml#plc9b-linux-native | planned
B-ENTRY-MATERIALIZER | any | classified | direct_materializer_plugin_bound | package_route_unavailable | rejected@classified | single_owner;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ENTRY-MATERIALIZER] | harness-quality.yml#plc9b-linux-native | planned
B-ENTRY-PUBLISH | any | staging | direct_publish_or_bind | package_route_unavailable | rejected@staging | single_owner;no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ENTRY-PUBLISH] | harness-quality.yml#plc9b-linux-native | planned
B-ENTRY-DISABLED | any | classified | plc9b_owner_disabled | package_route_unavailable | rejected@classified | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-ENTRY-DISABLED] | harness-quality.yml#plc9b-linux-native | implemented
B-NOEXEC-IMPORT | any | extracted | import_trap | ok | committed@committed | no_process;no_import;no_extra_network | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-NOEXEC-IMPORT] | harness-quality.yml#plc9b-linux-native | planned
B-NOEXEC-SETUP | any | extracted | setup_or_build_hook | package_artifact_type_rejected | rejected@extracted | no_process;no_import;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-NOEXEC-SETUP] | harness-quality.yml#plc9b-linux-native | planned
B-NOEXEC-ENTRYPOINT | any | extracted | malicious_entrypoint_metadata | ok | committed@committed | no_process;no_import;no_extra_network | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-NOEXEC-ENTRYPOINT] | harness-quality.yml#plc9b-linux-native | planned
B-NOEXEC-ADJACENT | any | extracted | adjacent_executable | ok | committed@committed | no_process;no_import;no_extra_network | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-NOEXEC-ADJACENT] | harness-quality.yml#plc9b-linux-native | planned
B-STATE-CANCEL-EARLY | any | each_phase_before_transaction_pinned | operator_cancel | package_operation_cancelled | cancelled@prior_phase | bounded_residue;no_publication;no_binding;no_desired | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-STATE-CANCEL-EARLY] | harness-quality.yml#plc9b-linux-native | planned
B-STATE-CANCEL-PINNED | any | each_precommit_phase_from_transaction_pinned | operator_cancel | package_operation_cancelled | cancelled@prior_phase | no_binding;no_desired;pin_visible;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-STATE-CANCEL-PINNED] | harness-quality.yml#plc9b-linux-native | planned
B-STATE-REJECT-CLEANUP | any | rejected | quarantine_cleanup_failure | package_quarantine_cleanup_retryable | rejected@cleanup_retryable | bounded_residue;no_binding;no_desired;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-STATE-REJECT-CLEANUP] | harness-quality.yml#plc9b-linux-native | implemented
B-STATE-SECRETS | any | each_phase | credentialed_private_locator | ok | committed@committed | no_secret;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-STATE-SECRETS] | harness-quality.yml#plc9b-linux-native | planned
B-STATE-STATUS | any | rejected | transport_status_mapping | package_archive_malformed | rejected@inspecting | same_receipt;no_secret;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-STATE-STATUS] | harness-quality.yml#plc9b-linux-native | planned
B-COMPAT-EPOCH | any | accepted | newer_lifecycle_epoch | package_runtime_epoch_unsupported | rejected@accepted | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-EPOCH] | harness-quality.yml#plc9b-linux-native | planned
B-COMPAT-MIXED | any | accepted | mixed_fence_aware_processes | package_runtime_epoch_unsupported | rejected@accepted | single_owner;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-MIXED] | harness-quality.yml#plc9b-linux-native | planned
B-COMPAT-LEGACY | any | classified | legacy_binding_history_hint | ok | classified@plugin_bound | no_publication;no_binding;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-LEGACY] | harness-quality.yml#plc9b-linux-native | planned
B-COMPAT-ROLLFORWARD | any | retryable_failure | upgrade_downgrade_rollforward | ok | committed@committed | same_receipt;pin_visible;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-ROLLFORWARD] | harness-quality.yml#plc9b-linux-native | planned
B-COMPAT-CUTOVER-POSIX | posix-native | accepted | offline_quiescent_namespaced_cutover | ok | accepted@epoch_fenced | single_owner;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-CUTOVER-POSIX] | harness-quality.yml#plc9b-linux-native | planned
B-COMPAT-CUTOVER-WINDOWS | windows-native | accepted | offline_quiescent_namespaced_cutover | ok | accepted@epoch_fenced | single_owner;no_publication;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-CUTOVER-WINDOWS] | windows-shell-compatibility.yml#plc9b-windows-native | planned
B-COMPAT-PREFENCE-LIVE-POSIX | posix-native | accepted | pre_fence_writer_blocks_cutover | package_runtime_epoch_unsupported | rejected@pre_fence | single_owner;no_publication;no_binding;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-PREFENCE-LIVE-POSIX] | harness-quality.yml#plc9b-linux-native | planned
B-COMPAT-PREFENCE-LIVE-WINDOWS | windows-native | accepted | pre_fence_writer_blocks_cutover | package_runtime_epoch_unsupported | rejected@pre_fence | single_owner;no_publication;no_binding;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-PREFENCE-LIVE-WINDOWS] | windows-shell-compatibility.yml#plc9b-windows-native | planned
B-COMPAT-OFFLINE-RESTORE-POSIX | posix-native | accepted | complete_pre_b_restore_exclusive_old_runtime | ok | accepted@offline_restore | single_owner;legacy_snapshot_exact;b_namespace_unreachable;no_peer_fallback;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-OFFLINE-RESTORE-POSIX] | harness-quality.yml#plc9b-linux-native | planned
B-COMPAT-OFFLINE-RESTORE-WINDOWS | windows-native | accepted | complete_pre_b_restore_exclusive_old_runtime | ok | accepted@offline_restore | single_owner;legacy_snapshot_exact;b_namespace_unreachable;no_peer_fallback;no_skip | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-OFFLINE-RESTORE-WINDOWS] | windows-shell-compatibility.yml#plc9b-windows-native | planned
B-COMPAT-ADOPT | any | committed | authenticated_legacy_reacquisition | ok | committed@committed | same_receipt;pin_visible;legacy_snapshot_exact;desired_unchanged;instance_unchanged;binding_unchanged;enablement_unchanged | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-ADOPT] | harness-quality.yml#plc9b-linux-native | planned
B-COMPAT-ADOPT-UNAUTHORIZED | any | acquiring | legacy_reacquisition_unauthorized | package_source_unauthorized | rejected@acquiring | legacy_snapshot_exact;desired_unchanged;instance_unchanged;binding_unchanged;enablement_unchanged;no_publication;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-ADOPT-UNAUTHORIZED] | harness-quality.yml#plc9b-linux-native | planned
B-COMPAT-ADOPT-UNAVAILABLE | any | acquiring | registry_network_temporarily_unavailable | package_operation_timed_out | retryable_failure@acquiring | bounded_residue;legacy_snapshot_exact;desired_unchanged;instance_unchanged;binding_unchanged;enablement_unchanged;no_publication;no_extra_network;no_peer_fallback | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-ADOPT-UNAVAILABLE] | harness-quality.yml#plc9b-linux-native | planned
B-COMPAT-ADOPT-CRASH | any | each_precommit_phase | adoption_crash_and_retry | package_operation_interrupted | retryable_failure@prior_phase | same_receipt;bounded_residue;legacy_snapshot_exact;desired_unchanged;instance_unchanged;binding_unchanged;enablement_unchanged | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-ADOPT-CRASH] | harness-quality.yml#plc9b-linux-native | planned
B-COMPAT-ADOPT-CRASH-AFTER-COMMITTED | any | committed | adoption_crash_after_committed_edge | ok | committed@committed | same_receipt;pin_visible;legacy_snapshot_exact;desired_unchanged;instance_unchanged;binding_unchanged;enablement_unchanged | tests/harness/resources/packages/test_plc9b_adversarial.py::test_manifest_case[B-COMPAT-ADOPT-CRASH-AFTER-COMMITTED] | harness-quality.yml#plc9b-linux-native | planned
```
<!-- plc9b-adversarial-manifest:end -->

The first matching selector below determines both the sole journal owner and
its transition; caller response never selects a journal. Every `append_once`
uses a stable event identity plus expected journal revision, permits one winning
CAS, and requires exact replay to return the original receipt with byte-for-byte
unchanged revision/state. `response_state` means the response state to the left
of `@`, not its diagnostic code. `no_append:unchanged` performs no append in any
domain. In particular, a handoff never mutates the already-committed Package
operation journal.

The closed domains and legal appended states are: `operation` = every monotonic
phase from `accepted` through `committed`, plus terminal `rejected` or
`cancelled`; `attempt` = `retryable_failure`;
`handoff_attempt` = `retryable_failure`; `handoff` = `aborted` or `settled`;
`cleanup` = `cleanup_retryable`; and `epoch` = `epoch_fenced`. Domain `none`
has only `no_append:unchanged`. All terminal states and retryable attempt
outcomes are append-once; exact replay never adds another status revision.

Each domain maps to one concrete authority and stable subject journal key.
Fingerprints, epochs, and revisions are genesis-bound or expected-CAS values,
never key components that could fork a conflicting request into an empty peer
journal. Caller ports request a transition; they never write the target journal
directly.

<!-- plc9b-journal-domain-authority:start -->
```text
journal_domain | sole_authority | stable_journal_key | bound_or_expected_cas_value | allowed_writer_port
operation | PLC9B Package lifecycle owner | operation_id | request_fingerprint+prior_journal_revision | PackageOperationJournalCAS
attempt | PLC9B Package lifecycle owner | operation_id+attempt_epoch | parent_request_fingerprint+parent_journal_revision | PackageAttemptJournalCAS
handoff_attempt | retention-handoff owner over PluginPackageLifecycleLedger | handoff_id+attempt_epoch | parent_receipt_fingerprint+parent_handoff_revision | RetentionHandoffJournalCAS
handoff | retention-handoff owner over PluginPackageLifecycleLedger | handoff_id | receipt_fingerprint+prior_handoff_revision | RetentionHandoffJournalCAS
cleanup | PLC9B Package lifecycle owner | quarantine_tombstone_id | cleanup_revision | PackageCleanupJournalCAS
epoch | Package epoch cutover coordinator in Package lifecycle composition | store_root_identity | current_epoch+prior_fence_revision | PackageEpochJournalCAS
none | no authority | no journal | no value | no writer
```
<!-- plc9b-journal-domain-authority:end -->

<!-- plc9b-journal-effect-policy:start -->
```text
selector | journal_domain | journal_transition
B-PUB-REUSE | none | no_append:unchanged
B-PUB-UNCOMMITTED | none | no_append:unchanged
B-ADMISSION-* | none | no_append:unchanged
B-CRASH-COMMITTED | operation | append_once:committed_then_no_append
B-CRASH-* | attempt | append_once:retryable_failure_then_no_append
B-ACQ-BYTES | attempt | append_once:retryable_failure_then_no_append
B-ACQ-REDIRECT | attempt | append_once:retryable_failure_then_no_append
B-ACQ-TIMEOUT | attempt | append_once:retryable_failure_then_no_append
B-CONCUR-SAME | operation | append_once:committed_then_no_append
B-CONCUR-CONFLICT | none | no_append:unchanged
B-CONCUR-STALE | none | no_append:unchanged
B-HANDOFF-BEFORE-DESIRED | handoff_attempt | append_once:retryable_failure_then_no_append
B-HANDOFF-AFTER-DESIRED | handoff_attempt | append_once:retryable_failure_then_no_append
B-HANDOFF-AFTER-SETTLEMENT | none | no_append:unchanged
B-HANDOFF-DESIRED-REJECT | handoff | append_once:aborted_then_no_append
B-HANDOFF-STALE-RECEIPT | none | no_append:unchanged
B-HANDOFF-CONCURRENT-REPLAY | handoff | append_once:settled_then_no_append
B-ENTRY-PUBLISH | none | no_append:unchanged
B-ENTRY-DISABLED | none | no_append:unchanged
B-STATE-REJECT-CLEANUP | cleanup | append_once:cleanup_retryable_then_no_append
B-COMPAT-EPOCH | none | no_append:unchanged
B-COMPAT-MIXED | none | no_append:unchanged
B-COMPAT-CUTOVER-* | epoch | append_once:epoch_fenced_then_no_append
B-COMPAT-PREFENCE-LIVE-* | none | no_append:unchanged
B-COMPAT-OFFLINE-RESTORE-* | none | no_append:unchanged
B-COMPAT-ADOPT-UNAVAILABLE | attempt | append_once:retryable_failure_then_no_append
B-COMPAT-ADOPT-CRASH | attempt | append_once:retryable_failure_then_no_append
B-COMPAT-ADOPT-CRASH-AFTER-COMMITTED | none | no_append:unchanged
default | operation | append_once:response_state_then_no_append
```
<!-- plc9b-journal-effect-policy:end -->

Native Windows rows run only in the named Windows workflow and native POSIX
rows in the named Harness workflow. The job collects the exact node ids and
rejects skips; unsupported-host emulation is never the only evidence. General
rows also observe filesystem/process/import/network/publication/binding/desired
state and peer-fallback oracles, not merely an exception string.

## Epoch, Upgrade, And Downgrade Fence

The first B epoch is an offline, fail-closed cutover rather than a record that
an already-running pre-fence writer could ignore. The coordinator exclusively
holds the existing common coordination lock, proves all legacy leases and
process registrations quiescent, snapshots the complete pre-B state, creates a
fresh identity-pinned B-epoch namespace unreachable through old writable root
names, writes the minimum-runtime fence, and atomically switches the Product
root pointer. Only then may the first B transaction start. The legacy namespace
becomes read-only replay/restore input. If quiescence, exclusive ownership,
snapshot durability, or atomic pointer replacement cannot be proved, cutover
aborts without changing either root. Supervisors also refuse to start a
pre-fence binary against the new root.

This establishes the Package lifecycle epoch and minimum fence-aware runtime
against the exact new root identity before any B transaction or staged object.

Every fence-aware process checks the epoch record and exact Package-store root
identity before Source, lockfile, binding, revision, or quarantine access. A
newer epoch, an active different-epoch lease, or unknown evidence yields
`package_runtime_epoch_unsupported`; mixed-epoch writers are never admitted.

A pre-fence binary cannot be made safe by a record it does not understand.
Direct downgrade after any B epoch state exists is unsupported. The only
pre-fence recovery is an offline restore of the complete pre-B Package store,
Source configuration, lock/binding history, desired-state backup, and fence
record, including the exact legacy root pointer, followed by exclusive
old-runtime startup. Restore writes no B-epoch Package, handoff, cleanup, or
epoch journal; optional operator audit lives outside both restored and B store
namespaces. Native fixtures prove the restored snapshot byte-for-byte, that the
B namespace/fence are unreachable from the restored root and old runtime, and
successful exclusive old-runtime startup. Otherwise operators
upgrade to the minimum fence-aware runtime and roll forward. Crash recovery by an older
fence-aware epoch also refuses before touching paths.

Existing lockfiles, bindings, closure-v1 records, and published revisions remain
replay/retention evidence but are `legacy_unverified`. Existing binding/history
is a one-way input that may classify a request as `plugin_bound`; it cannot
prove `non_plugin` and cannot satisfy B recursive closure, commit admission, or
dependency pinning. Existing desired/Instance/binding state is never silently
deleted, rebound, enabled, disabled, or claimed as B-verified.

Adoption requires authenticated reacquisition and the complete B transaction
under a new operation. Successful adoption publishes evidence but does not
implicitly change desired, Instance, binding, or enablement state. Crash/retry
uses the same operation fingerprint and receipt. If reacquisition is
unavailable, all legacy state remains byte-for-byte authoritative and visible;
the attempt refuses without implicit rebind/enable. A future explicit operator
trust-import contract would require separate review; PLC9B.0 does not invent
one. Upgrade -> downgrade refusal -> roll-forward, native initial cutover with
live pre-fence-writer refusal, authenticated adoption, unavailable
reacquisition, adoption crash/retry, old-state, and exclusive offline-restore
fixtures are mandatory manifest cases.

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
