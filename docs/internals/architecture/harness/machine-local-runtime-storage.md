# Machine-Local Runtime Storage

## Decision

Loushang classifies machine-local resources by lifetime before choosing a
path. A path is an output of that classification, not the storage model.

| Lifetime | Canonical root | Examples | Ownership rule |
| --- | --- | --- | --- |
| durable user data | `$LOUSHANG_HOME/data` | sessions, user indexes | explicit authority; compatibility roots are read-only discovery |
| durable machine state | `$LOUSHANG_HOME/state` | debug logs, traces, diagnostics inputs | append/private-file policy owned by the producing service |
| reproducible cache | `$LOUSHANG_HOME/cache` | downloads, derived metadata | safe to evict and rebuild |
| live process resources | `$LOUSHANG_RUNTIME_DIR/runs/<run_id>` | leases, drafts, artifact snapshots | one `RuntimeScope` and one exclusive `RunLease` per application run |
| disposable scratch | `$LOUSHANG_TMPDIR` | atomic-write intermediates | never used as a durable reference |

`LOUSHANG_HOME` defaults to `~/.loushang`. The runtime root prefers
`LOUSHANG_RUNTIME_DIR`, then `XDG_RUNTIME_DIR/loushang`, then a user-specific
directory below the operating-system temporary root. Path resolution is pure
and performs no filesystem I/O.

## Composition rule

The composition edge resolves `PlatformPaths` and `RuntimeScope` once and
injects the immutable result. Leaf storage consumers do not reread process
environment variables and do not infer cwd or user-home policy. This makes a
scope deterministic in tests and prevents behavior from changing midway
through a run.

`RuntimeScope` exposes only run-local namespaces. `RuntimeResourceOwner` is the
application-level effectful owner: it acquires one `RunLease`, constructs one
ArtifactStore, retains both for the complete run, and closes them as one
transaction. The screen composition root retains that owner and releases it
after the runner exits. Leaf services such as the input router dispose only the
resources they own.

The package boundary follows the same ownership split. Foundation supplies
only the mechanism-level, product-agnostic path and lease primitives:
`loushang.foundation.platform_paths` and
`loushang.foundation.runtime_scope`. Harness owns artifact semantics and the
application composition lifetime in `loushang.harness.artifacts` and
`loushang.harness.runtime.resources`. Foundation must not import Harness, and
the former `loushang.foundation.artifact_store` and
`loushang.foundation.runtime_resources` modules are intentionally removed.

```text
PlatformPaths (pure configuration)
        |
        v
RuntimeResourceOwner (application lifetime)
        |
        +--> RuntimeScope --> immutable run identity
        |
        +--> RunLease -----> liveness + stale sweep
        |
        `--> ArtifactStore -> immutable objects + portable manifest

RuntimeScope
        |
        `--> input-router lifetime --> DraftStore --> bounded clipboard drafts
```

The concrete store does not cross the composition edge. Producers receive an
`ArtifactWriter`; verified consumers receive an `ArtifactReader`; snapshotting
exporters receive an `ArtifactSnapshotStore`. These are separate runtime
proxies, not type-only views of one broad object. Snapshot source roots are
bound when the composition root creates that projection; a leaf cannot widen
them per call. The projections are revocable: closing first rejects new
operations, waits for already admitted operations to finish, and only then
releases the Lease. No leaf receives the Lease, concrete backend, or authority
to delete the run tree.

Construction is transactional. If a run-local service cannot be created after
the Lease is acquired, `RuntimeResourceOwner.acquire` closes the Lease and
removes the incomplete run before returning the failure. Both the interactive
screen host and the diagnostics CLI operation use this same owner instead of
assembling peer lifetimes independently.

## Crash recovery and safety

A startup sweep considers a valid lease active when its lock cannot be
acquired. Active runs are never removed. Inactive, validly leased runs are
atomically renamed to a `.gc-*` quarantine entry while the lease remains
locked, then removed. Interrupted quarantine entries are reclaimed by a later
sweep. This prevents another process from acquiring an unlocked candidate
between liveness validation and deletion. A
directory without a valid lease may belong to an older running version, so it
is never automatically removed; this conservative compatibility residue can be
handled by an explicit maintenance operation later.

The sweeper accepts only 32-character hexadecimal run ids, rejects non-owned
directories, does not follow symbolic links, and verifies the lease file's
device/inode identity before unlinking it. Cleanup failure leaves reclaimable
residue and must not replace the application's real shutdown result.

## Pytest scratch governance

Repository test entry points use `scripts/dev/run_pytest.py` rather than giving
pytest an unmanaged, user-global base directory. Each invocation acquires a
`RunLease` in the dedicated
`$LOUSHANG_RUNTIME_DIR/pytest-runs/<run_id>` namespace and binds pytest's
`--basetemp` below that private run. This keeps test-generated projects outside
the checkout, makes concurrent invocations disjoint, and prevents temporary
project discovery from changing merely because a test is run from a worktree.

The pytest namespace is separate from application runs so its aggressive
startup sweep cannot shorten application crash-evidence retention. A sweep
removes only a valid, unlocked lease; active test processes and unprovable
legacy directories remain untouched. Normal exit removes the run directly;
only a failed removal repairs an owned read-only entry and retries that failed
operation, avoiding a second full-tree scan. A
crash leaves a locked-until-process-exit lease that the next managed run can
safely reclaim.

Before collection, the runner checks filesystem free space and, where the
platform supports it, performs a real allocation reservation to detect
per-user quotas that filesystem-wide free-space reports cannot see. The
default floor is 64 MiB and can be adjusted for a constrained environment via
`LOUSHANG_PYTEST_MIN_FREE_BYTES`. Caller-provided `--basetemp` is rejected so
temporary-tree ownership has exactly one authority. Direct pytest invocations
also retain no completed `tmp_path` trees, but the managed runner is the
canonical Make and TUI-test entry point because it additionally supplies
leases, concurrency isolation, quota preflight, and crash recovery.

## Clipboard images as drafts

Clipboard bytes are transient prompt-draft resources, not workspace files and
not session transcripts. The standard profile stages them below
`<run>/drafts/clipboard`, while markers stay relative to `<run>/drafts` so the
user sees `@clipboard/...` rather than a machine-specific absolute path.

`DraftStore` owns both the in-memory bytes and the private file until submit,
cancel, EOF, exceptional paste, or router disposal. It enforces per-image,
attachment-count, and total-draft byte limits. Oversized images are rejected
before disk persistence. It belongs to the nested input-router/draft lifetime,
not to `RuntimeResourceOwner`; the shared `RuntimeScope` supplies its location
without transferring cleanup authority for the whole run. On submit, bytes
transfer to the model-facing boundary and the path/cleanup identity are
deliberately dropped.

## Session and observability separation

Sessions are durable user data and therefore never live under a cwd-relative
runtime directory. The user-global session authority is
`$LOUSHANG_HOME/data/sessions`; cwd is a query/filter and the current
`.loushang/sessions` path is compatibility discovery only. Logs and traces are
machine state under `$LOUSHANG_HOME/state`, not session content. Diagnostic
exports may snapshot selected observability files but must not silently include
the transcript.

## Run artifacts and explicit export

`ArtifactStore` owns immutable objects below `<run>/artifacts`, plus a portable
manifest containing logical name, kind, media type, disclosure policy, byte
size, digest, timestamp, and semantic source. Physical machine paths are not
written into the manifest or exposed by the public `ArtifactRef`; physical
paths and file identities remain private backend records. The store enforces
per-object, count, and total-byte bounds before publication. It requires an
already-live run directory and never creates, closes, or recursively removes a
shared `RunLease` tree.

Snapshot sources require explicit allowed roots. The composition root binds
those roots into a snapshot capability before injection. The backend resolves
the source, rejects non-regular or non-owned files and reparse points, uses
no-follow opens where available, verifies path/file identity, bounds reads, and
rejects a file that changes during capture. The store never infers authority
from the source path, and a leaf exporter cannot supply or widen roots. Every
artifact declares one of
three disclosure levels:

- `private`: never implicitly share;
- `redact`: eligible only through a mandatory redacting exporter;
- `shareable`: caller has explicitly declared the content safe to publish.

The first production consumer is diagnostics export. The CLI composition root
creates a short-lived `RuntimeScope`, `RunLease`, and `ArtifactStore`; debug and
trace `latest` inputs are copied into `redact` snapshots, and only those stable
snapshots enter the ZIP. Export reads those objects back through the store's
identity and digest check rather than reopening their physical paths. The ZIP
is fsynced and atomically published without
replacing an existing file. Default machine-managed archives remain under
`$LOUSHANG_HOME/state/diagnostics` and are bounded by age, count, and total
bytes. Explicit user output paths are not garbage-collected.

Debug and trace producers remain rotating machine state under
`$LOUSHANG_HOME/state`; moving active sinks under a transient run would lose
the evidence needed after a crash. Sessions likewise remain durable user data.
ArtifactStore therefore unifies capture, provenance, quota, disclosure, and
export without collapsing distinct lifetimes into one directory.

## Durable resource transitions

Runtime artifacts, user exports, and Session blobs are deliberately different
authorities rather than three paths into one store:

```text
RunArtifactRef
    +-- explicit export ------> UserExportRef
    `-- verified promotion ---> SessionBlobRef
```

`RunArtifactRef` is valid only while its `RunLease` is live and must never be
serialized into a durable transcript. `UserExportRef` is a receipt for an
explicit user-selected destination; the receipt itself contains no destination
path because the user owns that file after publication. `SessionBlobRef` is a
portable, digest-bearing reference whose bytes are owned by exactly one durable
session. All three carry logical name, kind, media type, disclosure, size, and
digest; none carries a machine path.

Promotion rereads bytes through the source `ArtifactReader`, verifies size and
digest, applies disclosure policy, writes a private same-directory temporary,
fsyncs it, and publishes without overwrite. `private` user export needs an
additional opt-in, while `redact` export requires an actual redaction transform.
A Session promotion publishes the immutable object and manifest before its
reference may enter the transcript.

The first durable layout is intentionally session-local rather than a global
content-addressed store:

```text
$LOUSHANG_HOME/data/session-assets/<session-id>/
    manifest.json
    objects/<sha256>
```

Objects are content-addressed only inside their owning session. This avoids a
global reference-count database and makes delete, backup, restore, and failure
recovery local transactions. A resumed transcript reports missing or corrupt
blobs but remains readable. A fork copies only references reachable from its
selected branch, verifies the source bytes, and rewrites them to the new
session identity. Transcript deletion commits first; asset cleanup failure
leaves conservative residue instead of resurrecting or partially deleting the
transcript.

Portable backup uses a single `.loushang.zip` bundle containing the linearized
Conversation JSONL branch, a strict portable blob manifest, and verified
objects. Import bounds member count and bytes, rejects undeclared, duplicate,
or traversal-shaped members, verifies every digest before publication, creates
the target blob authority before the transcript, and removes it if transcript
creation fails. Plain JSONL remains a transcript-only interchange format and
never claims to carry external bytes.

The durable transcript encoder accepts the old `fullOutputPath` field for
compatibility reads but never emits it again. New records persist
`fullOutputBlob`; presentation renders its logical name, not its physical
location. Therefore a durable transcript can never reference
`<runtime>/runs/<run-id>`.

## Durable command output and images

Command streams and images share the same Session Blob authority without
sharing their ingestion adapters. The common invariant is that a durable fact
contains a typed, digest-bearing reference and never contains a physical path
or an unbounded binary payload.

The Session composition edge wraps the selected `ExecService` with a private
scratch owner below `$LOUSHANG_TMPDIR`. It forces full-output capture into that
scratch root, performs a stable no-follow read, atomically publishes stdout and
stderr as separate `SessionBlobRef` objects, and clears both temporary paths
before returning. This applies equally to successful, failed, timed-out, and
cancelled commands. Failure remains an exception, but its pathless tool-result
details carry the retained stream references so both Agent tool results and
interactive command records remain recoverable. Failure to retain output never
changes a successful process result or masks the original process failure.

Clipboard, user, screenshot/tool-result, and assistant/generated images enter
through one transcript image boundary. Before a durable message commit, inline
base64 is validated and bounded, published as a private image Blob, and
replaced with the Harness-only `SessionImagePart`. It deliberately does not
subclass the AI `ImagePart`; only successful hydration constructs an AI wire
image, so an unhydrated durable placeholder fails closed at the provider edge.
If transcript commit fails, only that
unchanged publication is rolled back. Model context hydration rereads and
verifies the Blob; a missing or corrupt image becomes a portable text marker so
ordinary resume remains usable.

Model Input snapshots are a second durability boundary and must not re-inline
hydrated images. The Product transcript edge therefore projects exact known
base64 strings and provider data URLs into content-addressed Session markers
before Model Input v2 materialization. Provider adapters project encoded image
locations once into the stable `PreparedRequestBinaryField` contract; Harness
never guesses provider wire keys while traversing arbitrary JSON. The marker contains only Blob ID,
encoding form, and a non-binary prefix. The snapshot records the projection
version; reconstruction requires the owning Session Blob reader, verifies the
object, restores the provider's exact original JSON shape, and validates the
original logical and prepared-request hashes. AI types and provider adapters
remain storage-unaware.

Blob IDs are content digests, so Model Input markers survive fork and bundle
import without reference rewriting. The authoritative `SessionImagePart` is
still traversed and rewritten to the target Session identity, which makes the
same digest available in the new authority. Bundle export includes only
reachable Blob objects, and delete removes the complete per-Session authority.

## Unified machine-resource control plane

`loushang.harness.machine_resources` exposes one operational view over these
different lifetimes without
pretending they share one deletion policy. `loushang storage paths` is pure
path projection; `storage status` performs a bounded, read-only, no-follow
inventory. Both show canonical user-global paths and the cwd/user-home
compatibility session roots, so `cwd` remains a discovery filter rather than a
hidden storage authority. JSON output is versioned with `schemaVersion: 1`.

`storage clean` is a preview unless `--apply` is explicit. Its initial mutation
surface is intentionally narrow:

- runtime runs are removed only through `RunLease` liveness proof;
- diagnostics cleanup targets only the managed `loushang-diag*.zip` family;
- Session Blob authorities are removed only when a valid canonical Conversation
  deletion tombstone positively authorizes reclamation and a complete bounded
  transcript scan finds no live claim. Missing, corrupt, linked, unreadable, or
  truncated authority state refuses cleanup.

The command does not recursively delete sessions, arbitrary logs, cache roots,
or the shared temporary root. Those resources either have a stronger owner or
cannot be proven inactive from a pathname alone.

`storage migrate` is likewise a preview by default. Apply mode accepts strict
Conversation JSONL files from cwd, legacy user-home, and explicitly supplied
compatibility session roots. Apply revalidates that a caller-supplied plan stays
inside those roots and the canonical destination, parses the exact stable-read
bytes, and applies independent transcript and aggregate Blob budgets. It verifies every Blob,
copies Blob authority first, commits the canonical transcript second, and rolls
the copied authority back only when the commit is proven not to have landed.
Cancellation waits for the shielded commit result; an unknown receipt is
reconciled against the canonical transcript before assets can be reclaimed.
Sources are retained. Existing
destinations are never overwritten, and a changed source invalidates its plan.
This gives migration recovery the same copy-first transaction used by bundle
import instead of treating a directory move as an identity change.

The Product-facing discovery, provenance, conflict, Continuity, and selected
asset-health projection built on this control plane is specified in
[Session Discovery and Continuity](session-discovery-continuity.md).
