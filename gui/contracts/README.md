# C1 execution contract probes

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

## Hello compatibility slice

The probe additionally checks `local-detachable-execution/v1` and
`local-detachable-discovery-execution/v1` hello values against the profile the
client explicitly expects. It preserves the reference codec's exact-byte
comparison to `execution_hello`: whitespace, reordered keys, duplicate keys,
and alternative JSON string escapes are rejected even when decoded values look
equivalent. Rust checks the canonical wire representation; TypeScript receives
and checks only the decoded bridge values, not the original wire bytes.

The supported declarations are `loushang.app/v1`, `loushang.execution/v1`,
`restartRecovery=false` and `submissionRetention=service_instance_lifetime`.
Unknown versions, mismatched profiles, invalid instance IDs and unsupported
recovery/retention claims fail closed. These declarations do not demonstrate
runtime capabilities, authentication, actual recovery, or a profile registry.

## Idle snapshot and content-event slice

Model-generated samples use the identity in the existing accepted-response
fixture, Python execution/source snapshot constructors, and all ten
`SessionEventKindV1` values. The Python reference codec validates each sample
before the independent Rust and TypeScript probes process it.

Coverage is deliberately restricted to idle composite snapshots (null
observation/active/latestTerminal and empty draft) and content-event batches.
The source cursor/revision and content event cursor become lossless decimal
strings in the candidate bridge. Execution-view revision remains a JS-safe
number. Zero is allowed for source counters, but not for event cursors.

Checks cover identity agreement, explicit nullable fields, interaction event
IDs, absent execution IDs, unknown fields/kinds, 256-entry array limits, and
the 65,536-character snapshot transcript budget. The execution codec limits
all tuple decoding to 256 entries even though the base SessionSnapshot model
allows more records. This probe follows that actual wire decoder limit.

The process pipeline now explicitly sets Python stdout to UTF-8 on Windows.
Literal assertions for Chinese titles/text and emoji prevent equally damaged
expected/actual strings from masquerading as encoding fidelity. Earlier
equality-only Unicode evidence is superseded by these explicit assertions.

## Explicit limits

This probe checks hello value compatibility, not live handshake/profile selection,
authentication,
framing, requests other than submit, app_failure, running/terminal snapshots,
execution metadata updates, stream ordering/gap recovery,
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

The hello increment adds 30 vectors across the two profiles. Combined result:
63 vectors (15 accepted, 48 rejected), including TypeScript bridge mutation
checks. All other acceptance limits above remain unchanged.

The idle snapshot/content-event increment adds 47 vectors. Current total:
110 vectors (37 accepted, 73 rejected), plus bridge-only mutations and literal
Unicode assertions. No real snapshot acquisition or event subscription occurs.
