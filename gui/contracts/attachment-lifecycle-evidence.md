# Read-only attachment and initial snapshot experiment

Status: partial C1/B2 preparation, updated 2026-09-15. This scripted check is not
shared AppHost integration, an ongoing RPC client or live GUI publication.

The Windows connection probe now has an opt-in `--attach` mode after its existing
record/auth/hello sequence. It selects the explicit `gui-fixture` mux, validates
the returned attachment, reads each member's execution composite snapshot and
two rounds of execution-event batches, then detaches and closes. It never creates a
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

Nineteen Windows loopback scenarios pass: two-member success, already-attached,
malformed attachment, second-snapshot instance change, identity change, cursor
regression, wrong request ID, invalid snapshot, detach failure, event cursor gap,
event identity mismatch, event response ID mismatch, second-batch replay,
mux revision change, member order change, a change after the first event round,
cumulative request duration exceeding startup budget, stalled event response and
slow response-frame bytes. Python uses
the reference request/response codecs, verifies the exact operation sequence and
observes connection closure while its listener stays active. Fixture records and
listener are temporary; no existing service or provider is involved.

Event reading starts from each member's snapshot: source cursors
are incremented losslessly as decimal strings, while execution metadata revisions
use a separate bounded counter. Wrong identity, duplicate or non-contiguous
positions reject the attempt; no incomplete state is published. Watermarks persist
across batches. Each batch advances a temporary copy and commits only after full
validation; failure leaves the previous watermarks unchanged and permanently
invalidates that reader. Rebuilding requires a new validated snapshot. Rust unit
tests cover partial advancement failure, refusal of later/empty batches after
failure, and rejection of a later batch by a fresh snapshot baseline.
Request IDs are
positive increasing decimal numbers across snapshots, event reads and cleanup.
The reusable read session additionally stages the entire round's member
watermarks: no member commits until all members and the mux recheck succeed.
Failure clears the session's readable state while retaining exact authority for
one detach attempt. Reading before initialization or after detach is rejected.
The signed-63-bit request number limit is checked without wraparound.
Successful initialization switches the socket deadline to a fixed per-request
budget. The cumulative-duration case uses four 400 ms delays with a 1000 ms
request budget: it succeeds despite exceeding the old total connection budget.
The stalled and slow-byte cases close the connection without a successful
detach claim. Startup deadlines remain absolute. Unit tests separately verify
that reads cannot renew a deadline and expired startup cannot activate session mode.

After all snapshots and after each event round, the probe reads the selected mux
by its exact ID. It requires the same revision (lossless raw decimal), name,
ordered members, complete member identities, positions and titles. A mismatch
fences the attempt and enters best-effort detach without reporting success.
This is an optimistic membership recheck, not a server transaction or proof of
ongoing controller ownership: mux/read is not an authorization renewal. Changes
after a successful recheck still require detection by the next authorized read
or a future continuous reader. No GUI publication is enabled by this check.

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
