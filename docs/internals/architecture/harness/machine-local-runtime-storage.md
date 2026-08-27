# Machine-Local Runtime Storage

## Decision

Loushang classifies machine-local resources by lifetime before choosing a
path. A path is an output of that classification, not the storage model.

| Lifetime | Canonical root | Examples | Ownership rule |
| --- | --- | --- | --- |
| durable user data | `$LOUSHANG_HOME/data` | sessions, user indexes | explicit authority; compatibility roots are read-only discovery |
| durable machine state | `$LOUSHANG_HOME/state` | debug logs, traces, diagnostics inputs | append/private-file policy owned by the producing service |
| reproducible cache | `$LOUSHANG_HOME/cache` | downloads, derived metadata | safe to evict and rebuild |
| live process resources | `$LOUSHANG_RUNTIME_DIR/runs/<run_id>` | leases, drafts, future run artifacts | one `RuntimeScope` and one exclusive `RunLease` per application run |
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

`RuntimeScope` exposes only run-local namespaces. `RunLease` is the effectful
owner that creates the private tree and holds an exclusive lock in `.lease`.
The screen composition root retains that lease across every run-local service
and releases it after the runner exits. Leaf services such as the input router
dispose only the resources they own.

```text
PlatformPaths (pure configuration)
        |
        v
RuntimeScope (immutable run identity)
        |
        +--> RunLease ----> liveness + stale sweep
        |
        +--> DraftStore --> bounded clipboard-image drafts
        |
        `--> ArtifactStore (later phase; exported run artifacts)
```

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

## Clipboard images as drafts

Clipboard bytes are transient prompt-draft resources, not workspace files and
not session transcripts. The standard profile stages them below
`<run>/drafts/clipboard`, while markers stay relative to `<run>/drafts` so the
user sees `@clipboard/...` rather than a machine-specific absolute path.

`DraftStore` owns both the in-memory bytes and the private file until submit,
cancel, EOF, exceptional paste, or router disposal. It enforces per-image,
attachment-count, and total-draft byte limits. Oversized images are rejected
before disk persistence. On submit, bytes transfer to the model-facing
boundary and the path/cleanup identity are deliberately dropped.

## Session and observability separation

Sessions are durable user data and therefore never live under a cwd-relative
runtime directory. The user-global session authority is
`$LOUSHANG_HOME/data/sessions`; cwd is a query/filter and the current
`.loushang/sessions` path is compatibility discovery only. Logs and traces are
machine state under `$LOUSHANG_HOME/state`, not session content. Diagnostic
exports may snapshot selected observability files but must not silently include
the transcript.

## Deferred boundary

This phase intentionally does not introduce a general `ArtifactStore`.
Artifacts need retention, export, and provenance contracts distinct from
draft cleanup. The next phase may add that service over the already injected
`RuntimeScope` without changing session authority, clipboard semantics, or the
path resolver.
