# Local connection-attempt fencing

Status: native probe integration, 2026-09-15. Not a persistent Tauri connection.

`rust/src/connection_epoch.rs` owns a process-local monotonically increasing
attempt epoch. It is neither a server controller generation nor a wire field.
Starting another attempt fences the previous one; exhaustion fails closed.
Each attempt has a cancellation handle and invalidates itself on drop. A stale
handle or old attempt's cleanup cannot invalidate its replacement.

The currency check and a short state-update callback share one mutex critical
section. Checking a token and updating afterwards would leave a cancellation
race; this API avoids that gap. Callbacks cannot await, do IO or reenter the
owner. A callback failure fences the attempt, and poisoned locks fail closed.

The Windows connection probe now acquires an attempt before admission, fences
it before cancellation shuts down the socket, and guards validated attachment,
snapshot staging and event watermark updates. Snapshot/event failure fences
the attempt before best-effort detach. Cleanup retains the original server
attachment and generation; local invalidation does not manufacture authority
or stop the shared application. Final successful completion is also guarded.

## Evidence and limits

- Rust tests exercise replacement, delayed worker cancellation, rejection before
  a stale callback runs, old cleanup isolation, failure fencing and exhaustion.
- Existing loopback cancellation/auth/hello and attachment tests run through the
  integrated guard; real AppHost idle snapshot/event reads remain compatible.
- The current CLI performs one connection per process. Reconnection using the
  same owner is covered by unit tests, not by a persistent desktop client.
- The attachment probe now rechecks mux membership after snapshots and event
  rounds. This module supplies invalidation on mismatch, not continuous detection
  or automatic reacquisition of fresh snapshots.
- No GUI state is published and no authentication data is exposed to React.

Next reuse a long-lived owner in the native adapter, connect disconnect/resync
signals to invalidation, and add membership validation plus atomic GUI snapshot
installation. Do not infer that the bounded probe is a background event reader.
