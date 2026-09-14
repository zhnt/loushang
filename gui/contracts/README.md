# C1 execution submit/failure probe

Status: **partial C1 evidence**, not a production adapter or accepted full codec.

Run from the repository root:

```text
pnpm --dir gui run check:contract
```

Requires the repository Python environment (`uv`), Node 24.19, and Rust 1.98.1.
The probe has a separate locked Rust crate; it does not compile Tauri, add native
permissions, or alter the default GUI `check`/CI. On a fresh machine populate
the Rust dependency cache once with:

```text
cargo +1.98.1 fetch --locked --manifest-path gui/contracts/rust/Cargo.toml
```

The command runs Rust with `--offline --locked`. It starts no application
service, calls no provider and uses no credentials. Input/output goes through
process pipes, not recorded user sessions or files containing live data.

## Source of truth and evidence

1. Python loads the submit example from the existing
   [execution fixture](../../tests/appserver/fixtures/execution_v1.json).
   Its mutations must match explicitly expected acceptance/rejection using the
   existing [execution codec](../../src/loushang/appserver/execution/codec.py).
   Every known execution error code also comes from the Python enum.
2. Rust independently decodes typed, closed submit/failure shapes, rejects
   duplicate/unknown/missing fields and compares its projection to Python's.
   `controllerGeneration` is read as raw JSON integer text; there is no f64/u64
   intermediate. Only its **candidate bridge representation** becomes a decimal
   string. The existing numeric wire contract is not changed.
3. TypeScript validates that bridge projection and compares all fields. It
   rejects number-valued generations even when a number is small, and checks
   canonical decimal strings with BigInt. It never parses the raw wire frame
   with JSON.parse; the wire is carried as opaque text in the test envelope.

Coverage includes the official Unicode submit example, positive generation
boundaries through `2^100+1`, boolean/float/exponent/zero/negative/string/null
counter rejection, text length boundaries, missing/unknown/duplicate fields,
unknown protocol/operation/identifier and closed execution failure codes.
`service_instance_changed` and other known failures are valid typed responses,
not malformed transport frames or a retry instruction.

## Explicit limits

This probe does not implement handshake/profile negotiation, authentication,
framing, requests other than submit, app_failure, snapshots, events, recovery,
Workspace/ChangeSet capabilities, live bridge IPC or GUI/TUI concurrency. It
does not claim exhaustive parity for arbitrary Unicode/JSON inputs. Error
presentation/retry policy and reverse bridge-to-wire encoding remain future
work. The small independent validators intentionally duplicate only this
slice; they must not be promoted as a full client schema. Schema/type generation
and complete codec coverage remain C1 decisions.

Execution revision counters are bounded by the Python model to `2^53-1`, unlike
controller generations. Do not generalize one counter's bounds to every field.
No C1/B2 acceptance or real-service readiness follows from this probe passing.

## Recorded result

2026-09-14, Windows x86_64, Node 24.19.0 / Rust 1.98.1:
`check:contract` passed 33 vectors (13 accepted, 20 rejected), plus TypeScript
bridge-only rejection assertions. Rust fmt/clippy and Python Ruff passed.
This is offline process-pipeline evidence, not native WebView/IPC evidence.
