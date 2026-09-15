# Read-only attachment and initial snapshot experiment

Status: partial C1/B2 preparation, updated 2026-09-15. This scripted check is not
shared AppHost integration, an ongoing RPC client or live GUI publication.

The Windows connection probe now has an opt-in `--attach` mode after its existing
record/auth/hello sequence. It selects the explicit `gui-fixture` mux, validates
the returned attachment, reads each member's execution composite snapshot and
one execution-event batch, then detaches and closes. It never creates a
mux/session, takes over a controller, submits work or sends service STOP.

The attachment validator checks closed fields, positive lossless generations
and mux revision, ordered/unique members, member/session identity agreement,
source snapshots and the 128-member bound. Composite snapshots reuse the prior
independent execution validator; request ID, service instance, member identity
and non-regressing source cursor are additionally checked against the attempt.
Snapshot values remain temporary until all members validate; no partial success
or successful completion is printed if snapshot or detach validation fails.

Once attachment ownership is validated, a snapshot rejection still attempts
detach with the same attachment/generation. A conflict or malformed attachment
closes the connection without guessing ownership. Failed transport/deadline can
also prevent detach; socket closure is fallback, not proof of completed cleanup.

## Precision regression found and fixed

Using `json!` / a generic JSON Value as an intermediate for a raw generation
silently changed a counter above integer bounds. Requests now serialize typed
structures containing `RawValue` **directly to bytes**. The test's Python decoder
checks the exact `2^100 + 1` generation for both snapshot requests and detach.
The existing numeric wire contract is unchanged; no float or string is sent.

## Evidence

```text
pnpm --dir gui run check:attachment-contract
```

Twelve Windows loopback scenarios pass: two-member success, already-attached,
malformed attachment, second-snapshot instance change, identity change, cursor
regression, wrong request ID, invalid snapshot, detach failure, event cursor gap,
event identity mismatch and event response ID mismatch. Python uses
the reference request/response codecs, verifies the exact operation sequence and
observes connection closure while its listener stays active. Fixture records and
listener are temporary; no existing service or provider is involved.

The first event batch is validated against each member's snapshot: source cursors
are incremented losslessly as decimal strings, while execution metadata revisions
use a separate bounded counter. Wrong identity, duplicate or non-contiguous
positions reject the attempt; no incomplete state is published. Request IDs are
positive increasing decimal numbers across snapshots, event reads and cleanup.

The reference peer is a scripted contract fixture, not AppService. Therefore
these checks do not demonstrate actual controller arbitration/release or a
shared AppHost's behavior. Existing 176 value vectors and connection-lifecycle
checks are retained; no default CI or TUI/Harness gate is added.

## Remaining integration

This is sequential bounded startup work. It lacks ongoing event reading,
membership-change barriers, epoch isolation and bounded concurrent RPC routing.
Snapshots are discarded after validation, not installed in a GUI reducer. Do
not infer that a consistent live snapshot can be published during concurrent
membership changes from this experiment alone.

The separate [real AppHost integration](apphost-integration-evidence.md) now tests
actual ownership and idle event reads. Next expose the read-only native port with correct
event/barrier and cleanup ownership. Keep fixture UI and live facts separate.
