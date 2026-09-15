# Native connection slice: contract and implementation boundary

Status: proposed GUI implementation plan, 2026-09-14. This is not acceptance of a
new AppServer protocol or evidence of a working native connection.

## Contract source and generated artifacts

Use the existing Python models **and codecs**, not `protocol/schema.py` alone:
that module currently describes operation vocabulary, not complete payloads.
The reference files and normalized SHA-256 digests are recorded in
[generated/manifest.json](generated/manifest.json).

`scripts/gui/generate_contract_types.py` extracts execution nested wire fields
from the codec's explicit `_FIELDS` and their annotations from the model. The
attachment additions use dataclass shapes: their parity with the manually
implemented app codec still needs separate evidence. This is deliberate
test-tool coupling to private reference metadata, not a new public API.

The generated Rust and TypeScript files are **candidate bridge DTOs**, not wire
decoders, JSON Schema, request envelopes or runtime validators. Rust derives
Serialize only: deriving Deserialize would silently weaken required-nullable
fields and would not enforce model invariants. A decimal counter is represented
as a string only after validated, lossless decoding; execution counters remain
bounded numeric values. Unknown integer fields stop generation for an explicit
policy decision. No blanket `int -> number` conversion is allowed.

Generation is opt-in:

```text
pnpm --dir gui run contract:generate
pnpm --dir gui run contract:check-generated
uv run python scripts/gui/test_generate_contract_types.py
pnpm --dir gui run check:contract
```

Keep generated shapes checked in and compiled by the contract probe. Do not
replace its independent value validators with generated structural types.
Generation does not replace negative vectors, canonical-byte checks, reverse
encoding or schema/codec acceptance by the protocol owner. A complete public
versioned contract source remains pending; this extractor is the GUI-side
preparation, without changing server ownership or its wire representation.

## Connection sequence and ownership

Rust owns every phase below. React receives redacted state and validated values,
never a record key, authentication transcript, socket or caller-supplied raw RPC.
Use the existing shared AppHost application; do not start a second GUI service.

| Phase | Required action and reference | Success does not imply |
| --- | --- | --- |
| Record admission | Explicit endpoint selection; validate native file handles, identity and private access using the behavior in `local_record.py` and `_windows_local_record.py` | Readable JSON is not trusted connection material |
| Connect | Loopback endpoint from that admitted record; bounded startup and cancellation; see `local.py` | TCP connection is not authentication |
| Authenticate | Existing `local_auth.py` mutual proof exchange, fresh nonces and directional integrity keys; verify every frame sequence/tag | Authentication is not execution-profile negotiation |
| Negotiate | Send authenticated APP mode, verify expected execution profile/instance and exact hello, then echo hello; see `remote_client.py` | Hello is not controller ownership or UI readiness |
| Attach | Explicit mux selector, `mux/attach`, retain attachment ID and lossless controller generation | Do not silently take over an already-controlled mux |
| Initial snapshot | Validate attachment membership/identity and obtain each member's execution composite snapshot using the negotiated instance | Do not mix fixture values or partial member snapshots into live state |
| Publish | Atomically install validated member snapshots and cursor barriers; expose an explicit read-only connected state | Send/approval/retry remain unavailable in this first slice |
| Detach | Use current attachment/generation to detach, stop readers and close the borrowed connection | Never send STOP mode or shut down the shared application |

Authentication uses the existing G16 transport profile even when the semantic
profile is execution/v1. Do not substitute the execution profile into the HMAC
transcript. Authentication provides integrity, not encryption. Exact bytes,
limits, sequence exhaustion and role labels must follow the reference, not a
fresh GUI protocol.

Initially select an existing mux explicitly. Creating/opening new sessions is a
separate capability; no automatic create-on-not-found. Shared GUI/Hosted Mux
acceptance uses separate muxes under the same application, not two controllers
silently sharing one mux.

## Failure and cleanup requirements

- Cancellation or failure in any phase fences that connection attempt; a late
  completion cannot publish data. A new attempt gets a new local epoch.
- Authentication/profile/instance mismatch closes the transport and returns a
  redacted failure. Never downgrade to legacy `start_turn`.
- `already_attached` is a normal conflict, not a takeover/retry trigger.
- After attachment, snapshot failure releases owned attachment resources where
  possible and closes the connection; report uncertain cleanup honestly.
- Snapshot membership changes, cursor gaps or stale generations require a new
  barrier before publication. Do not synthesize missing events from UI history.
- Keep a single writer and ongoing response reader with bounded pending work;
  control/cleanup requests must not wait behind a long-running request lock.
- Disconnect cannot automatically replay submit, approval or mutation. This
  slice does not implement any of those operations.

## Delivery checkpoints, not new default gates

1. **Implemented preparation:** generated candidate DTOs and drift check,
   independent existing value probes. No native socket or credentials involved.
2. **Partial transport evidence:** [Rust/Python authentication over pipes](authentication-evidence.md)
   is implemented, as is [Windows private-file admission](windows-record-evidence.md)
   with native fixtures. [Closed service-record decoding](record-values-evidence.md)
   is now composed into the file and authentication probes separately.
   Production transport and cancellation/timeout cleanup remain pending; the
   isolated probes are not the native adapter.
   [Loopback lifecycle evidence](connection-lifecycle-evidence.md) additionally
   composes them through hello and close with socket deadlines/cancellation;
   production GUI ownership and ongoing RPC remain pending.
3. **Partial attachment evidence:** [scripted loopback attachment/snapshot/detach](attachment-lifecycle-evidence.md)
   is implemented, including two bounded execution-event rounds per member with
   persistent watermarks and atomic batch validation.
   [Real AppHost integration](apphost-integration-evidence.md) verifies ownership
   arbitration, idle event reads and cleanup with an independent mux client.
   [Local attempt fencing](connection-epoch-evidence.md) now guards probe state
   updates and cancellation. Bounded mux membership rechecks reject a changed
   revision or member set after snapshots and event rounds. Continuous detection
   and integration of a reusable owner into the desktop connection remain pending.
   The attachment reader is now a reusable `ReadSession` with separate attach,
   initialize, poll and detach operations. The evidence driver alone chooses
   two rounds; the session does not own a loop or socket. Each poll commits all
   member watermarks only after its membership recheck. Request IDs fail closed
   at the existing signed-63-bit connection limit instead of wrapping.
4. **Pending acceptance:** persistent read-only native GUI connection and
   presentation. The probe's idle connection evidence is not GUI acceptance.

Transport and attachment must pass their own evidence before enabling the GUI
connection control. No live connection readiness is claimed by checkpoint 1.
Keep these checks opt-in and scoped to the changed GUI adapter; do not add TUI or
Harness suites solely because the GUI consumes their application contracts.

The probe now separates initial connection and per-request deadlines. Admission,
authentication, hello, attachment, snapshots and the first membership recheck
share one absolute startup deadline. Only successful initialization enables a
fresh deadline at each subsequent request send, covering the complete write and
response frame. Byte reads never renew it. Expired or invalid frames fence the
channel; a fresh budget cannot reopen it. This policy assumes sequential RPC,
not concurrent outstanding calls. A long-lived desktop scheduler, cancellation/
join ownership and GUI state publication are still pending.
