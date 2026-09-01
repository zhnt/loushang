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
2. The component that owns the destination root also owns limits, extraction,
   verification, publication, and recovery. A source adapter cannot choose or
   reopen an owner path.
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
8. One policy and one owner gate every CLI, RPC, Session, startup, and direct
   materializer route. Transport shape does not confer authority.

## Ownership And Dependency Boundary

The accepted dependency direction is:

```text
CLI / RPC / Session / startup / direct compatibility adapter
  -> Plugin-bound Package application port or fail-closed classifier
     -> PLC9B Package lifecycle owner in loushang.harness.resources.packages
        -> Source Authority byte/provenance port
        -> owner-created quarantine and verification primitives
        -> PluginRevisionStore immutable-publication primitive
        -> durable Package transaction receipt
  -> management command consumes an exact verified revision

PluginPackageLifecycleLedger <- publication/selection retention evidence
```

The single PLC9B Package lifecycle owner belongs in
`loushang.harness.resources.packages`, where Package acquisition and storage
composition already live. It does not belong in `foundation`, a transport, a
Product adapter, `plugin_management`, a source backend, or the public
`loushang.plugin` author SDK.

Ownership is deliberately split only at stable evidence boundaries:

| Boundary | Sole authority | Explicit non-authority |
| --- | --- | --- |
| Source Authority port | authenticate an origin, return versioned provenance, expected content identity when available, and a bounded byte stream | cannot choose a filesystem path, extract, resolve dependencies, publish, bind, enable, or delete |
| PLC9B Package lifecycle owner | create/pin quarantine, enforce all budgets, inspect/extract, verify wheels and recursive closure, coordinate immutable publication, journal phases, and issue the final receipt | cannot execute package code, mutate desired enablement, invent Source provenance, or delete live revisions |
| `PluginRevisionStore` | revalidate a safe regular tree, freeze content identity, atomically publish an immutable Plugin revision, and return a verified handle | does not authenticate Sources, parse archives, verify wheel metadata/closure, or decide desired state |
| closure-v2 evidence owner | bind every recursive verified wheel artifact and the exact resolution environment into one canonical graph digest | v1 replay records are not upgraded or reinterpreted as recursive evidence |
| `PluginPackageLifecycleLedger` | retain Package/Instance/pin/cleanup evidence used by later GC | does not acquire bytes, extract, publish, select, or erase artifacts |
| management application | consume an exact verified revision in a separately authorized install/update command | does not accept mutable source paths or infer success from publication alone |

Source-specific adapters may perform network or local-source reads only behind
the Source Authority port. The Package owner supplies the write sink and
budgets; adapters stream bytes into that sink and return provenance. They never
receive the quarantine pathname. The sink distrusts adapter-supplied filenames,
media types, sizes, digests, and dependency claims until it verifies them.

## Versioned Evidence Model

The names below freeze record responsibilities, not Python API names. Runtime
types are intentionally absent in PLC9B.0.

| Evidence | Required immutable facts |
| --- | --- |
| authenticated source envelope v1 | operation identity, canonical source identity, origin kind, authentication decision and authority identity, requested locator, expected artifact digest if declared, policy revision, capture time, and schema version |
| bounded acquisition receipt v1 | envelope fingerprint, actual byte digest and count, transfer limit, termination disposition, owner sink identity, and source-adapter result; no source pathname |
| quarantine receipt v1 | owner root identity, private operation-directory identity, applied entry/byte/depth/path/compression budgets, platform normalization profile, and creation phase |
| verified wheel artifact v1 | canonical distribution name/version, wheel filename and compatible tags, artifact digest/size, canonical metadata digests, complete RECORD verification, and extraction-tree digest |
| dependency closure lock v2 | root artifact, every recursive artifact digest and verified identity, directed dependency edges, normalized requirement/marker evaluation, exact resolution-environment fingerprint, canonical order, and graph digest |
| immutable publication receipt v1 | operation identity, source/acquisition/quarantine/closure fingerprints, exact published revision identities and handles, store/root identity, phase sequence, and commit revision |

`PluginDependencyClosureLock` v1 remains replay-only and keeps its existing
meaning: final package-tree digest plus installed `name==version` facts. A v1
record never satisfies PLC9B recursive verification, and no reader may decode
v1 bytes as closure v2. An unsupported future evidence version fails closed.

All digests name the algorithm and canonical encoding. The resolution
environment covers every input that can change marker or wheel compatibility
selection. Canonical distribution names are compared after the same specified
normalization, and two artifacts that normalize to one name are a conflict,
not last-writer-wins.

## Owner Transaction And Recovery

The durable phase machine is monotonic:

```text
accepted
  -> acquiring
  -> acquired
  -> inspecting
  -> extracted
  -> closure_verified
  -> publishing
  -> published
  -> committed
```

Any pre-commit phase may record `rejected` or `retryable_failure` with the last
proved evidence. `committed` is terminal for the same operation identity and
input fingerprint. A retry with the same identity and fingerprint resumes or
returns the same receipt; the same identity with different input fails closed.

- `accepted` records policy/provenance intent before untrusted bytes enter the
  owner sink.
- `acquiring` through `closure_verified` operate only in an owner-created,
  private, identity-pinned quarantine. Every archive entry is normalized and
  authorized before any object is created.
- `publishing` may create digest-addressed immutable objects idempotently. Such
  objects remain unselectable until the complete `published` set is proven and
  the final receipt reaches `committed`.
- A crash after an immutable rename but before `committed` leaves only an inert,
  content-addressed orphan. Recovery reopens it through the store, revalidates
  its exact identity, and either completes the same receipt or retains it for
  evidence-backed later GC. It never trusts directory existence alone.
- Binding or desired-state mutation is a later application command over the
  committed receipt. PLC9B publication cannot implicitly enable a Plugin.

The owner uses one stable lock order over transaction journal, quarantine
identity, digest publication, and final receipt. Concurrent retries of the same
fingerprint converge. A different fingerprint for the same operation is
rejected. Independent digests may proceed concurrently, but a publication
collision succeeds only when the already-published object reopens as the exact
verified identity.

## Safe Acquisition, Inspection, And Extraction

Before runtime implementation is accepted, the owner must prove all of the
following on every supported platform:

- transport and decompressed byte limits, entry count, directory depth,
  component length, total path length, per-entry expansion, and aggregate
  expansion are enforced while reading;
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

## Exact Entrypoint Gate

The canonical source occurrence inventory is maintained in
`plugin-lifecycle-plc9-inventory.md` and verified from the Python AST. PLC9B.0
freezes 70 exact `(path, qualified scope, lifecycle symbol)` rows containing
111 occurrences. The inventory includes:

- Coding and shared CLI queries/commands;
- RPC Package capabilities and bindings;
- Session public ports, facade forwarding, and lifecycle adaptation;
- `SessionPackageController` and `PackageOperationsRuntime` composition;
- startup `PackageSourceResolver` auto-materialization; and
- direct `PackageMaterializer` sync/check and mutable remove/forget seams.

Adding, deleting, renaming, or changing the count of an inventoried site must
update the inventory and architecture guard in the same reviewed change. A
dynamic lookup, alias, generated binding, new UI/SDK transport, or internal
direct call is not exempt.

During implementation every entrypoint must classify the target before side
effects. A non-Plugin Package may retain its separately documented behavior. A
Plugin-bound or indeterminate target either calls the one PLC9B application
port with typed input or returns a stable refusal. It cannot fall through to
the current `uv`/`pip`, Git checkout publication, direct mutable removal, or
startup auto-materialization path.

## Adversarial Acceptance Matrix

The following matrix is mandatory runtime evidence for later PLC9B delivery.
PLC9B.0 freezes the cases but deliberately creates or executes no artifact.

| ID | Stage | Adversarial input or interleaving | Required result and negative evidence |
| --- | --- | --- | --- |
| B-ACQ-01 | source | unauthenticated origin, changed authority, stale policy, or provenance mismatch | reject before acquisition; no bytes accepted, quarantine, publication, binding, or execution |
| B-ACQ-02 | acquire | stream exceeds byte limit, stalls past limit, changes declared length, or digest mismatches | terminate and reject while streaming; bounded residue only, no publish/bind/execute |
| B-ACQ-03 | acquire | malformed/truncated archive, unsupported encryption/compression, overlapping entries, central/local header mismatch, or trailing payload | reject during inert inspection; no extraction outside quarantine and no publish/bind/execute |
| B-PATH-01 | inspect | absolute POSIX path, root-relative path, empty/dot name, or `..` traversal at any depth | reject the whole artifact before creation; no outside write, publish, bind, or execution |
| B-PATH-02 | inspect | backslash/forward-slash ambiguity, Windows drive/UNC path, ADS, reserved device, or trailing dot/space | reject under the frozen platform normalization profile; no create/publish/bind/execute |
| B-PATH-03 | inspect | duplicate or collision after separator, Unicode, case-fold, or canonical distribution-name normalization | reject the complete artifact; never overwrite or choose a winner |
| B-PATH-04 | extract | component/path/depth limit exceeded or ancestor/entry identity changes between validation and create | fail closed through pinned root-relative I/O; no outside write or selectable revision |
| B-TYPE-01 | inspect | symlink, hard link, device, socket, FIFO, junction, reparse point, or disguised special entry | reject in metadata and materialized-tree recheck; no target dereference, publish, bind, or execution |
| B-LIMIT-01 | acquire/extract | entry-count, per-entry, aggregate decompressed-byte, compression-ratio, nesting, or sparse-file budget exceeded | stop at the first exceeded budget; bounded cleanup, no publish/bind/execute |
| B-WHEEL-01 | classify | sdist, source tree, editable input, arbitrary ZIP, or unsupported wheel tags | reject; no build backend, setup script, package manager, import, hook, or adjacent executable runs |
| B-WHEEL-02 | verify artifact | wheel filename disagrees with `METADATA`, `WHEEL` is invalid, identity/version is ambiguous, or required metadata is duplicated/missing | reject before canonicalization; no publish/bind/execute |
| B-WHEEL-03 | verify artifact | `RECORD` missing, hash/size mismatch, duplicate path, unlisted extracted file, listed file absent, or RECORD self-rule invalid | reject the whole wheel; no partial tree or revision becomes selectable |
| B-WHEEL-04 | verify artifact | archive mutates or is replaced between digest, inspection, extraction, and verification | fail closed on identity recheck; no reopen by attacker pathname and no publish/bind/execute |
| B-CLOSURE-01 | resolve closure | dependency artifact missing, digest mismatch, unauthorized origin, incompatible tag/marker, or unresolved requirement | reject the complete recursive graph; no root-only publication receipt or selection |
| B-CLOSURE-02 | resolve closure | cycle, duplicate normalized project name, conflicting versions, graph reorder, or environment-fingerprint mismatch | deterministically reject or reproduce the identical canonical graph; never last-writer-wins |
| B-CLOSURE-03 | replay | v1 closure is presented as v2, v2 field is unknown, or future schema is unsupported | reject as insufficient/unsupported; preserve v1 bytes and never reinterpret them |
| B-PUB-01 | publish | attacker precreates quarantine, swaps an ancestor, inserts a special entry, or races final destination | owner-exclusive create/identity checks reject; no attacker path is trusted or overwritten |
| B-PUB-02 | publish | destination digest already exists with same name but different bytes/identity | reject collision; never replace the existing immutable revision or issue a receipt |
| B-PUB-03 | publish | exact verified digest already exists | reopen and revalidate exact store identity, then idempotently reuse; no mutable overwrite |
| B-CRASH-01 | every phase | crash before/after each journal edge from `accepted` through `committed` | fail closed or replay only the same fingerprint; no false commit, unsafe fallback, implicit bind, or execution |
| B-CRASH-02 | publish/commit | crash after one or more immutable renames but before final committed receipt | published objects remain inert; revalidate and roll forward or retain for evidence-backed GC; no implicit bind/execute |
| B-CONCUR-01 | all | concurrent same operation/fingerprint, same operation/different fingerprint, or different operations/same digest | same input converges; conflicting input rejects; exact digest reuse revalidates; no duplicate receipt or unsafe overwrite, and locks do not deadlock |
| B-ENTRY-01 | entry gate | each inventoried CLI, RPC, Session, startup, operations, and direct materializer route receives Plugin-bound input | every route reaches the one owner or stable fail-closed refusal before mutation; no peer publication path |
| B-ENTRY-02 | entry gate | target classification is missing, ambiguous, spoofed, or changes during dispatch | treat as Plugin-bound/unsafe and reject; no non-Plugin fallback, source removal, or lockfile mutation |
| B-NOEXEC-01 | all | package contains import traps, entry points, setup/build hooks, executable names, or malicious metadata text | treat all as inert bytes; assert zero child process, import, hook, network side effect, or code execution |
| B-STATE-01 | reject/retry | any case above fails after journal or quarantine creation | fail closed with a stable diagnostic plus bounded recoverable evidence; no desired state, binding, mutable source history, or live revision changes |

Each case requires positive owner-port evidence and negative observation of
filesystem escape, process spawn/import, network reuse beyond the authorized
source read, immutable publication, Package binding, desired-state mutation,
and unsafe fallback. Platform-specific name and reparse cases run natively on
their platform; unsupported host emulation cannot count as the only evidence.

## Rollout, Rollback, And Deletion Gates

PLC9B runtime work must land dark and fail closed before routes are activated.
Activation requires all matrix cases, exact-entry routing tests, crash/replay
tests, and cross-platform root-containment tests. There is no rollback to the
current installer for Plugin-bound input: disabling the new owner disables the
artifact command. Roll forward repairs only from versioned evidence and exact
digests.

The current `PythonPackageInstallerBackend`, Git publication behavior, startup
auto-materialization, direct mutable removal, binding/history forgetting, and
synchronous compatibility calls remain visible migration debt. They may be
narrowed or deleted only after:

1. every inventoried Plugin-bound route reaches the PLC9B owner or refusal;
2. no production caller can publish a Plugin revision through the peer path;
3. closure-v1 replay and downgrade refusal fixtures pass;
4. non-Plugin Package behavior has a separately accepted owner and regression
   evidence;
5. rollback disables Plugin artifact operations instead of restoring an unsafe
   implementation; and
6. the canonical inventory and negative architecture guard prove that the
   deleted symbol cannot be reconstructed through dynamic fallback.

PLC9A2 may project non-artifact management operations after PLC9A1, but it may
not expose materialize/install/update/remove/uninstall for Plugin-bound targets
until this runtime gate passes. PLC9C, PLC9D, and PLC9E remain separate slices.
