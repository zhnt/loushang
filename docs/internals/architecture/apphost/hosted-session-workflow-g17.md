# Explicit Hosted Session Workflow G17

[Architecture](../README.md) · [AppHost](README.md) ·
[G15](foreground-hosted-tui-g15.md) ·
[G16](../appserver/detachable-local-workspace-g16.md)

## Status

- ID: `HOSTED-SESSION-WORKFLOW-G17`
- Kind: incremental cross-scope contract and delivery design
- Authority: normative accepted incremental design; inherits G15/G16 boundaries
- Design status: accepted after independent three-perspective review and re-review
- Implementation status: partial — discovery protocol, Product reads, AppService
  views, explicit installed foreground/local wiring and shared picker;
  foreground launch owner and explicit Product client entry implemented;
  Product-entry re-review passed; isolated-wheel/native acceptance pending
- Activation status: explicit opt-in only; Embedded and legacy G14/G16 retained
- Tracking: [G17 #572](https://github.com/zhnt/loushang/issues/572)
- Baseline: `3c06f5b9a4309e03dc754511eb012f9e2c23cbcb`

## Outcome, Current And Target

The user explicitly starts a foreground Hosted client, or attaches to an
independently owned local application, selects admitted cwd or user-home
history, resumes a canonical Session in a named mux, interacts, then exits
according to the selected deployment lifetime. Required installed user paths
pass on Linux, macOS and Windows. Existing Embedded and G16 behavior does not
regress. This is the complete delivery objective, not a design-only closure.

Source facts at the G17 design baseline:

- `appserver.client.AppClientV1` lists muxes, not resumable Session history.
- `coding.hosted_catalog.CodingHostedSessionCatalogV1` owns real canonical
  headers in exactly admitted directories. Its routing query is fail-closed
  on incomplete enumeration; it is not a UI pagination API.
- `appservice.ports.HostedSessionResolverV1` only opens Sessions. AppService
  has no Product discovery port or per-client discovery snapshots.
- G16's `harnesstui.mux.shell` supplies the shared interactive shell and
  explicit identity-based `/resume`, but no historical Session picker.
- G15 A0.5's `apphost.launcher` and `coding.cli.hosted_client` are absent.
- G14/G16 hello bytes and local-record capability tuples are closed. An
  unsolicited new field or unknown request is not backwards negotiation.

Target adds one optional discovery capability to the semantic boundary, a
bounded shell picker, and the already accepted optional foreground launch
owner. Existing Session stores, AppHost catalog, mux coordination, terminal
engine, process host and protocol framing retain their responsibilities.
No new top-level package, persistent Session index, daemon installer, default
activation, arbitrary executable RPC, automatic replay or image transfer.

### Implementation Progress

The first G17.1 implementation slice supplies `SessionListV1`,
`SessionListResultV1`, bounded candidate/completeness values and the strict
`sessions/list` codec. `SessionDiscoveryClientV1` is separate from the unchanged
required `AppClientV1` surface. Explicit new profiles guard both outbound calls
and inbound dispatch; the connection receives an independently injected
discovery port. Remote clients reject pages for a different requested scope or
over the requested limit. Legacy hello bytes and default profiles are retained.

The next local slice binds the existing Coding catalog to bounded, read-only
discovery and AppService's client-local snapshots. The Harness header reader
has explicit nonblocking/no-lock-creation options; directory enumeration now
streams and closes at its bound rather than first materializing all entries.
Actual worker completion retains the scan slot after caller cancellation;
application fence revokes borrowed discovery, and unresolved scans prevent
Product Session owners from being released. Complete duplicate directories
disable all rows, while partial scans mark every observed row unverified.
The completion signal is resolved only after the synchronous read returns;
cancelling all asyncio Tasks cannot counterfeit thread completion. Canonical
routing now checks every bounded header directly, not a display projection's
possibly omitted rows, before treating a successful empty query as missing.

Installed Product bootstrap now supplies resolver admission independently of
the discovery switch. Both ordinary and recovered application construction
carry the optional discovery binding; enabling it requires exactly the same
admitted scopes. Library callers that omit both remain supported. Tests cover
real cwd/home transcript discovery, appends since listing, resume, a synthetic
model turn, scoped-client detach, and desired-state recovery without replay.
The synthetic model is test-only and does not enter command-line input.

The explicit installed `loushang-hosted --session-discovery` command now
selects the new foreground profile and exposes the admitted discovery port.
Default invocation retains the old profile and does not probe optional
capabilities. `--describe --session-discovery` reports the selected profile
without starting or writing state. The public legacy `parse_launch` library
helper retains its pair return and rejects the new flag; the command's private
parser carries all options without silently discarding capability selection.
Foreground construction rejects an absent opted-in port before sending hello;
the published Product command still owns cleanup if construction fails.

The installed `loushang-mux serve --session-discovery` path now also binds
discovery to the private record's exact optional capability tuple. Its record
schema and authentication domain remain unchanged. Both authenticated peers
derive their APP hello from that same record; there is no client-side profile
override or downgrade. Default scopes need no discovery attribute. The optional
typed scope factory retains the exact scope before borrowing the port, and
missing/failed capability access closes that scope. STOP never creates a scope
or APP hello and retains its reserved connection slot.

Discovery's semantic and installed wire paths and the shared picker are
composed; the launch owner is now composed into the explicit Product client
entry, with implementation re-review passed. A real installed stdio/local command test is not an
isolated-wheel or terminal acceptance test. The complete eight-family selector
is now composed for Linux and Windows and both passed on `c9f205bd`; Darwin
remains planned. Windows comprehensive quality still requires a clean rerun. Manifest
`implemented` means an executable gate, not a passing result; actual run
evidence is recorded separately below. Three-platform acceptance remains open.

### Reviewability Budget Supplement

The architecture reviewer independently approved changing only G11's exact
`appserver/protocol/*.py + appserver/client.py` group from 1,800 to 2,100 lines.
At review this group grew from 1,640 to 1,911 lines (+271) for the accepted
discovery algebra, explicit codec, optional client and closed profile checks;
remaining headroom changed from 160 to 189 lines. The glob still counts every
protocol module. All import gates and other owner budgets are unchanged.
This permits neither moving code outside the counted group to hide it nor
adding Product IO, pagination state or process ownership to the protocol.
Later Product/AppService/UI work receives no automatic budget expansion.

The next independent architecture review approved a separate exact 500-line
group for `appservice/discovery_ports.py + session_discovery.py` (308 lines at
initial review). G11 adds only `coding/hosted_catalog.py` to its external
AppService consumers, with a further assertion that this file imports only
`appservice.discovery_ports`, never the service runtime. Product IO remains in
the Product catalog; the new semantic owner remains Product/process neutral.

The same reviewer approved only `apphost/continuity.py` from 650 to 675 lines:
648 baseline lines become 655 (+7) for the borrowed optional capability getter
and recovery-request passthrough. No new lifecycle algorithm or persisted
field is added. The other G13 groups and all other import/size gates remain
unchanged. These supplements do not substitute for final full-goal code review.

For explicit foreground wiring the architecture reviewer approved only adding
`appserver.protocol.connection_profile` to the exact `apphost/foreground.py`
import set. This is a closed pure-value selection, not Product, filesystem or
process responsibility. No import wildcard or file-size budget changed.

## Requirements And Delivery Slices

| ID | Slice | Acceptance |
| --- | --- | --- |
| `G17-DISCOVERY` | G17.1 | typed, bounded, pathless discovery with explicit completeness and expired-cursor errors |
| `G17-AUTHORITY` | G17.1 | exact Product/scope admission before IO; listing does not grant resume; open revalidates canonical identity |
| `G17-COMPAT` | G17.1 | old clients and services retain legacy operations; unsupported discovery is rejected before sending a request |
| `G17-PICKER` | G17.2 | cwd/global selection, paging, empty/error/unavailable states and explicit selection work through borrowed ports |
| `G17-FOREGROUND` | G17.3 | explicit installed command owns startup, connection, child and bounded retryable settlement |
| `G17-LIFETIMES` | G17.3 | foreground exit settles child; local detach preserves application and accepted work |
| `G17-INSTALLED` | G17.4 | required real installed Linux/macOS/Windows user paths and fault cases pass without required-case skips |
| `G17-REGRESSION` | all | Embedded defaults/imports and legacy G14/G16 behavior remain covered and unchanged |

## System And Subsystem Boundaries

Arrows mean dependencies, not ownership transfer:

```text
Coding client composition -> AppHost optional launcher + Harnesstui shell
AppHost launcher -> Hosting public process/preparation + AppServer byte/client
Harnesstui -> AppClient + optional SessionDiscoveryClient + generic TUI
AppService -> AppServer values + injected Product discovery/resolver ports
Coding server composition -> canonical catalog + resolver + AppHost application

AppServer -/-> Hosting / AppService / AppHost / Product / UI
AppService -/-> transport / AppHost / Hosting / Product / UI
Harnesstui -/-> Hosting / AppHost / Product / AppService / filesystem discovery
AppHost core -/-> optional launcher / Product / UI
```

| Responsibility | Sole owner | Collaborators / non-owners |
| --- | --- | --- |
| execution workspace, Session roots, executable/environment admission | Product outer composition | never chosen by wire input or UI |
| canonical discovery and compatibility classification | existing Product Session catalog | Harness supplies bounded transcript reads; no new index |
| discovery snapshots, pagination and client lifetime | AppService | injected Product read port; no path interpretation |
| request/response codec and negotiated capability enforcement | AppServer | values and borrowed semantic port only |
| picker state, scope label, safe rendering and action intent | Harnesstui | receives pathless scopes and borrowed capabilities |
| foreground launch-attempt and settlement ownership | optional AppHost launcher | Hosting owns process mechanics; AppServer owns protocol reader |
| detachable application lifetime and continuity | existing G16/G13 owners | disconnect is neither application stop nor persisted-turn replay |

No source file gains an entire sibling-package import exemption. The A0.5
launcher gets the exact optional imports accepted by G15; facades stay lazy.

## G17.1 Scope And Discovery Contract

The request identifies Product, `SessionScopeV1` and the exact admitted scope
fingerprint, a page limit in 1..64 and an optional opaque continuation. `cwd`
and `user_home` retain their existing wire values. `global` is a UI alias for
the admitted `user_home` root, not an all-filesystems query or a union with
cwd. Users switch scopes explicitly; the client never silently merges them.
The scope fingerprint and Product must match server-admitted facts before any
directory IO. Missing directories produce an empty complete result; unreadable
or invalid roots produce a redacted unavailable error, not an empty success.

`sessions/list` returns an immutable page of pathless candidate values:
canonical Session identity (including source scope/fingerprint), bounded title,
compatibility and availability enums. It also returns a snapshot ID, optional
continuation and `complete`, whose meaning is **the underlying discovery scan
was exhaustive**, not that this happens to be the last page. A last page can
therefore have no continuation and `complete=false`. The UI must say so.

Only verifiable canonical identities become selectable rows. Unsupported
compatibility stays visible but disabled. Legacy Embedded transcripts without
Hosted identity metadata are not implicitly adopted. Malformed, ambiguous or
unverifiable entries never become guessed resume targets; omitted/unavailable
evidence must remain visible as a bounded count/status, not raw filenames or
exception text. Duplicate canonical identities are unavailable, not deduplicated
into apparently valid authority. Order is deterministic within each snapshot;
fallback titles use a short canonical identity, not a filesystem basename.

When `complete=false`, all observed candidates have availability `unverified`
and are disabled: a duplicate identity may exist beyond the scan budget, and
the retained strict resolver cannot establish authority. Display explicitly
that directory verification is incomplete. No G17 path bypasses that strict
resolver to make a partial row selectable. Omission counts are bounded lower
bounds with a separate exactness flag; an unvisited directory tail is unknown,
not zero omitted entries. Counts must not imply an exhaustive total.

`HostedSessionDiscoveryPortV1` is an optional injected AppService port. It
returns one bounded candidate snapshot (at most 256 candidates), completeness
and omission facts for an admitted scope; it does not construct a Session or
retain a second durable index. Product binds this port to its existing catalog.
The existing strict routing query stays strict: discovery must not accidentally
make an incomplete canonical scan authoritative for routing or creation.

Product discovery shares the existing 256-candidate / 32 MiB read ceilings,
and all header enrichment participates in those budgets. No full-transcript
read is added for a title. Bounded synchronous catalog IO must not run in the
UI or protocol event loop. The Product read operation has explicit retained
task ownership if offloaded: cancelling an await must not release its slot or
allow replacement IO while the original worker still runs. Cold caches,
oversized directories, malformed headers and concurrent transcript changes
are required tests, not assumptions of fast local storage.

The discovery-only read uses nonblocking shared-lock acquisition; contention
is visible unavailable/incomplete evidence. It must not call the current
blocking `load_agent_transcript_header` path from a background thread. Each
scan has a five-second monotonic work deadline and a cooperative stop flag,
checked before enumeration/read/lock attempts and between candidates. Do not
retry a contested lock inside the scan. The worker accepts immutable admitted
paths and returns immutable observations; it never acquires an asyncio catalog
lock or updates the live routing cache. A retained worker-completion handle,
not a cancelled asyncio wrapper, owns the scan slot until actual completion.
Filesystem syscalls cannot be forcibly stopped in-process; at deadline fence
publication, retain any actual worker debt, and report cleanup incomplete if
the worker cannot settle within the application budget. Existing command fatal
nonzero exit / parent reaping semantics remain the final escalation, not a
claim of clean shutdown. No overlapping replacement worker is allowed.

### Snapshot Lifetime And Bounds

- AppService owns a discovery view per semantic client. The legacy in-process
  client has one view; every G16 client scope has its own view. No transport
  connection identity enters AppService.
- At most two scope snapshots per client and 256 candidates per snapshot;
  local deployment's existing eight-client limit bounds the aggregate.
- One in-flight discovery scan per client, with an application-wide bound of
  two Product scans. Reject pressure with `operation_unavailable`; discovery
  uses ordinary slots, never reserved interrupt/approval/stop capacity.
- Snapshot lifetime is 60 seconds on a monotonic clock. Continuations are
  unguessable bounded opaque handles bound server-side to client, deployment
  generation, scope, snapshot and next offset. They are not paths or executable
  authority. Each snapshot stores at most 256 continuation positions.
- Explicit refresh replaces only that scope's snapshot. Reusing a valid cursor
  is read-idempotent; changing page size does not skip candidates. Wrong-client,
  wrong-scope, expired, replaced or prior-deployment cursors fail explicitly
  with `snapshot_required`; they never silently restart enumeration.
- Client close fences new queries, drops completed views and prevents late
  publication. Pending Product work remains owned and joins application
  settlement before Product owners are released; no detached task leak.

### Resume Is A Separate Admission

The picker turns an available row into the existing explicit
`MuxMemberOpenV1` / `SessionOpenSpecV1` intent; it does not pass a path or grant
new authority. Product re-resolves the current candidate through the canonical
owner, verifies Product/continuity/Session/scope/compatibility, and uses the
existing runtime claim/fence. Snapshot freshness is not a promise that the
transcript has not changed. Normal transcript appends need not be rejected
merely because the display snapshot is older.

Missing selected identity is `not_found`; invalid scope or current unreadable,
ambiguous or incompatible candidate is `session_unavailable`; expired browsing
state is `snapshot_required`. Errors remain distinguishable and redacted.
Cached live Session reuse must not bypass request identity/scope validation.
No failed or lost open response is automatically resubmitted. Refreshing mux
membership is safe observation, not retry permission.

Add an exact typed, closed `HostedSessionResolutionErrorV1` at the injected
AppService port with `missing` / `unavailable` classifications. Only a complete,
successful canonical lookup may produce `missing`. AppService maps those exact
port failures to `not_found` / `session_unavailable`; unknown exceptions remain
redacted unavailable, and cancellation is propagated rather than reclassified.
This explicitly replaces the current catch-all resolver-error mapping for
typed failures only. Installed Product composition supplies its exact admitted
scope set independently to the resolver, whether discovery is enabled or not;
optional discovery reuses that same set. The resolver checks Product/scope/
fingerprint before enumeration, including on direct identity `/resume`, not
merely after a binding lease has been constructed. Legacy library construction
without discovery remains supported and is not implicitly given new scope
authority by exposing the optional port.

### Optional Capability And Wire Compatibility

Keep `AppClientV1`'s required structural surface unchanged. Add a separate
`SessionDiscoveryClientV1` contract, explicitly supplied to the shell only
after composition/connection admission establishes availability. New service
clients may implement both. An absent Product discovery port is a supported
legacy configuration and returns `operation_unavailable` without effects.

Preserve byte-exact G14/G16 legacy hellos: `foreground-stdio/v1` and
`local-detachable/v1`. New closed profiles
`foreground-stdio-discovery/v1` and `local-detachable-discovery/v1` advertise
the additional operation while keeping the existing application value version
and ordinary/control budgets. Codec recognition does not grant a profile the
operation: both outbound calls and inbound dispatch enforce the selected
profile. Legacy profiles reject discovery before Product access.

G17 foreground composition explicitly selects the discovery profile for both
the admitted child command and launcher. Existing `loushang-hosted` invocation
without selection retains its legacy profile. G16 `serve --session-discovery`
is an explicit opt-in; omission keeps the old record and hello. Its private
authenticated record carries the exact optional capability tuple; the record
digest binds that capability to the live instance. New clients read both old
and new records and select the corresponding closed hello. Old clients reject
the new opt-in record before connection/mutation; they continue to use old
servers unchanged. No fallback reconnect, downgrade or retry after effects.

Local transport authentication remains `local-detachable/v1`; the discovery
profile is an application hello extension, not new cryptography. The closed
record capability tuple is either the existing tuple or that exact tuple plus
`session_discovery`. Authentication's record digest binds the selected tuple.

| Local configuration | Record profile / authentication domain | Semantic APP hello | STOP |
| --- | --- | --- | --- |
| legacy/default | `local-detachable/v1` / unchanged | `local-detachable/v1` | existing authenticated STOP/ACK, no APP hello |
| discovery opt-in | `local-detachable/v1` / unchanged; new capability in authenticated digest | `local-detachable-discovery/v1` | same STOP/ACK and reserved capacity, no APP hello |

The connection constructor derives its semantic profile from the authenticated
record facts, never ambient client flags. Record schema, challenge/MAC transcript
and legacy serialization stay byte-compatible when discovery is omitted.
Capability/profile tampering and cross-profile APP handshakes fail before
Product dispatch; the new opt-in STOP path is independently covered.

Required matrix: old client/legacy server unchanged; new client/legacy server
retains text/mux and disables picker; new/new opt-in enables picker; old client/
new opt-in fails closed; new client with unsupported capability never sends a
discovery request. Unknown fields, operation/profile mismatches and changed
authenticated capability records remain errors.

## G17.2 Picker And Interaction

### Reviewed Presentation Budget And State Ownership

The architecture review approved one new `harnesstui/mux/session_picker.py`
module with a 450-line cap and a 950-line cap (previously 850) for the exact
existing shell/terminal/tasks/screen group. The G11 semantic controller group's
600-line cap is unchanged. The picker is explicitly inventoried and receives
the same no-filesystem/process/reverse-import checks as the shell.

One serialized query runner belongs to the existing ShellActions owner. Scope
changes and refresh coalesce into one latest pending request; they do not
launch competing scans. Dismissal fences publication without pretending that
the outstanding borrowed query has settled. Shell close fences publication and
joins the runner under the existing absolute cleanup budget.

Editor instances are retained by `(mux_space_id, member_id, session_id)`, only
for current members (at most the protocol's 128). Removed/replaced identities
are pruned and shell close releases the cache. Reattachment/reordering alone
does not clear editor history. Rebinding input uses a new public InputRouter,
not a write to its private target. Each editor retains the existing 16-entry
undo/redo bounds and 20-entry kill ring; the 1 MiB current-draft aggregate is
not a claim that all editing history together occupies at most 1 MiB.

The existing shell receives a borrowed optional discovery client. F3 opens the
picker without touching the composer; `/sessions <cwd|user_home|global>` is an
additional command entry. Arrows/Enter select,
Escape dismisses, scope switching and next-page/refresh are explicit. A picker
request is asynchronous and generation-fenced so dismissal, scope changes,
refresh and shell close cannot publish stale rows or revive authority.

Opening the modal preserves per-member composer drafts, scroll and local
selection. Selection resolves stable row identity, never a stale positional
index. Disabled, incomplete, empty, expired and unavailable states are visible.
Submission requires an explicit user action and the existing membership fence.
Scope/page/refresh actions are handled inside the modal, not by overwriting a
draft with another slash command. The F3 path preserves composer text, cursor,
selection and undo state as well as every member draft/scroll. Slash-command
submission retains existing command-consumption semantics; it is not claimed
to preserve the command itself as a draft.
Concurrent approvals/interrupt and local window navigation remain responsive;
modal handling precedes general Tab/window navigation. Untrusted titles pass
the shared terminal-control sanitizer and display-width truncation.

Existing explicit identity `/resume` remains supported; omitting identity can
open the picker rather than guessing the latest Session. Unsupported image
paste remains rejected before capture/read/persistence. Neither picker nor
launcher adds an attachment store, log directory or global cache.

## G17.3 Foreground Ownership And Entry

Implement the G15 A0.5 design, not a second version of Hosting. The separate
installed `loushang-hosted-tui` Product command admits the complete installed
executable, shell-free argv, environment, execution workspace and exact Session/
application roots. The complete child entry is fixed by Product composition;
there is no CLI factory/module injection or RPC executable selection.
The admitted Python/installed executable is not claimed as sealed execution.

Publish an AppHost launch-attempt owner before preparation/spawn. It retains
Hosting's process lease, pipe adapter, bounded stderr tail, AppServer client,
startup and close tasks until settlement. The shell borrows only the semantic
clients and pathless scopes. Startup's 30-second absolute budget includes
imports and G13 recovery; process-alive is not ready. Take the terminal only
after ready and mux attachment, and always restore it on every exit path.

One absolute 20-second close budget includes at most 10 seconds graceful EOF,
then Hosting termination/reaping. Cancel local action waiters; bounded logical
detach failure never prevents EOF. Settle the protocol reader before handing
stdout drain to the process owner, keep stderr draining, and respect Hosting's
read/write bounds including the four-byte frame header. One writer owns all
chunks of a frame. Graceful-cutoff termination is driven by the same launch
owner independently of detach, EOF, blocked stdin writer, reader or stream
close completion. A stuck graceful step cannot consume the force/reap phase.
If the protocol reader is still outstanding, terminate first and join it in
the remaining absolute budget; never start a concurrent drain reader. Tests
must prove one termination request still occurs at the cutoff under blocked
partial-frame writes and cancellation-resistant readers.
Concurrent close joins the same operation; expiry retains
exact retryable cleanup debt. Forced exit is not clean semantic shutdown.
An explicit later retry can grant a new budget; ordinary repetition cannot.

The outer Product command makes deployment semantics visible: foreground quit
ends its child; local detach leaves the independent application/accepted work
alive. G16 stop stays a separate explicit command. No automatic backgrounding,
supervisor installation, orphan adoption or active-turn replay is introduced.

### G17.3 Implementation Boundary Check

The architecture follow-up accepts an optional async settlement callback in the
terminal runner: Product composition binds it to the launch owner's close,
which adopts one UI-detach callable without importing UI. Default/G16 callers
retain the existing shell-owned cleanup. The same selected settlement strategy
must also cover `shell.start()` failure: its current automatic five-second
close followed by a separate launcher twenty-second close would violate the
single budget. Do not remove automatic cleanup for independent library callers.

Publish the first detach binding, close task, absolute deadline and independent
force watchdog before awaiting any cleanup. Repeated close joins the same
operation; it cannot replace the detach binding or renew the budget. An explicit
cleanup retry must not resend an unknown logical detach or restart an expired
graceful window; retain and reuse outstanding termination/cleanup tasks. A normal
child exit avoids forced termination. Startup/attach failure, cancellation and
terminal-entry failure must reach this same owner, with terminal restoration
before settlement whenever the terminal was acquired.

The launch attempt adopts a dedicated ProcessHostingPort before start, so its
close can reclaim even a reservation whose lease has not returned. With no
published lease, immediately publish and retain host.close rather than waiting
for startup first: Hosting needs that close to cancel/reclaim the outstanding
reservation. Each startup await must retain a returned resource before checking
the closing fence, so a late lease cannot be discarded. It borrows
LaunchPreparationPort, not ownership of a shared preparation service. Transfer
stdout to a raw drain only after RemoteAppClient.close succeeds **and the
retained startup/hello task has actually settled and cannot publish another
reader**. Lifecycle review found a P1 in the weaker close-only condition:
RemoteAppClient.start performs hello IO in the caller task before registering
its response reader, so close can succeed while a cancellation-resistant hello
read still owns stdout. Close must fence late-ready publication synchronously,
retain that startup task and wait for actual settlement before any reader
handoff. On failure retain ownership and terminate at the independent cutoff
before attempting settlement again. No private reader-field
inspection or concurrent drain is an acceptable substitute. These are concrete
implementation constraints, not launcher or native acceptance evidence.

The architecture reviewer approved one optional `apphost/launcher.py` with a
550-line cap for the launch/client owner and its private pipe bridge together.
The exact allowed cross-package imports are Hosting public contracts and
AppServer client, framing, remote client and protocol values. AppHost core and
facade stay default-dark; no private Hosting backend, Product, AppService or UI
dependency is added. Implementing A0.5 must update the old no-launcher assertion,
exact optional-module inventory and G15/G17 inventories, not relax core gates.

## G17.4 Evidence And Completion Gate

Design/inventory tests establish contract traceability, not runtime acceptance.
Each slice has focused regression-first tests before behavior changes. Final
acceptance includes:

1. Codec/type/profile compatibility, malformed input, scope rejection before IO,
   cursor replay/expiry/refresh/cross-client/restart and bounded aggregate work.
2. Real Product cwd/home discover/create/resume, missing and incompatible
   records, changing files, cold/partial catalogs and no legacy adoption.
3. Fake-terminal playback for picker races, approval/interrupt, independent
   drafts, empty/no-capability/error states, narrow widths and malicious titles.
4. Real child startup failure before/after publication, recovery cancellation,
   EOF, repeated close, unresponsive child, retryable debt and terminal restore.
5. Isolated installed wheel help/start/create/history/list/resume/interaction/
   normal foreground exit and local detach/reattach on Linux/macOS/Windows.
   Safe deterministic Product streams/tools are test seams, not installed CLI
   factory flags. Installed CLI startup and terminal scenarios are separately
   exercised so a test-only child cannot stand in for the shipped command.
6. Existing G14/G16/Embedded smoke, architecture imports, Ruff, mypy, focused
   Coding/Harness/TUI suites and affected quality gates; native required cases
   have zero skips. Record exact head, workflow/job IDs and required-case counts.
7. Independent architecture/authority, lifecycle/concurrency and contract/user-
   evidence implementation review; fix findings, commit, PR into lane/harness,
   promote to main only on accepted evidence, refresh local main/lane while
   preserving unrelated work. Close #572 only after this complete objective.

The G17 evidence manifest is separate from G16's four installed cases. The
following required-case families must run natively from an isolated wheel on
each of Linux/macOS/Windows; report properties include platform, wheel origins
and PTY/ConPTY backend. CLI cases use the actual installed entrypoint. Controlled
Product interaction cases bind only library test seams and cannot replace CLI
cases. Every family has its own required ID and no required case may skip:

| Required case ID | Observable evidence |
| --- | --- |
| `G17-INSTALLED-ENTRY` | real CLI help, explicit startup, ready, terminal restore and child reaping |
| `G17-INSTALLED-CWD` | real CLI create, list, picker select, exit, relaunch and cwd canonical history restore |
| `G17-INSTALLED-HOME` | same path for user-home/global with a different admitted execution cwd |
| `G17-INSTALLED-LOCAL` | real local discovery opt-in, picker, detach/reattach and explicit STOP; app survives detach |
| `G17-INSTALLED-LEGACY` | legacy local and G14 protocols, unsupported-picker handling and unchanged Embedded startup |
| `G17-PRODUCT-INTERACTION` | deterministic real Product turn/stream/approval/interrupt through wheel imports and terminal |
| `G17-NATIVE-START-CANCEL` | child publication/recovery cancellation retains ownership and restores terminal |
| `G17-NATIVE-FORCED-EXIT` | unresponsive child is terminated/reaped; no clean semantic-exit claim |

Unit fault cases supplement these IDs: real lock contention, offloaded worker
still running after waiter cancellation, no scan-slot reuse before completion,
cross-profile APP/STOP, record-digest tampering, budget-external duplicates,
F3 draft/cursor/scroll playback, blocked frame write and reader cancellation.

Startup timing may be measured in this series, but the separate proposed
startup-performance plan is not incorporated or silently activated here.

## Independent Design Review

Three independent agents reviewed architecture/authority, lifecycle/concurrency
and protocol/user-evidence against current source. All three independently
approved the revised design on 2026-09-08 with no remaining P1/P2 design blockers.
Their approval does not substitute for implementation review or native evidence.
Initial findings and confirmed design resolutions:

- `G17-R1` (architecture and contract, P2): partial discovery cannot establish
  uniqueness or strict resumability. Resolved with unverified disabled rows,
  explicit incomplete verification, lower-bound omissions and budget-external
  duplicate tests. Strict canonical resolution is not relaxed.
- `G17-R2` (architecture, P2): promised missing errors were erased by AppService's
  catch-all. Resolved with exact closed Product port failures, explicit mapping,
  complete-lookup-only missing, cancellation propagation and pre-IO scope checks.
- `G17-R3` (lifecycle, P1): byte/count budgets do not bound a blocking header
  lock or actual worker lifetime. Resolved with nonblocking discovery reads,
  a work deadline/stop flag, immutable worker observations, actual-worker slot
  ownership and lease-last cleanup debt, including native contention evidence.
- `G17-R4` (lifecycle, P2): force/reap could be blocked behind stream settlement.
  Resolved with an independent cutoff inside the sole launch owner; reader/EOF
  failure cannot prevent terminate, and no second stdout reader is created.
- `G17-R5` (contract, P2): record, authentication and hello profile domains were
  ambiguous. Resolved with the explicit layer table, unchanged auth domain,
  digest-bound optional capability, APP mismatch rejection and STOP coverage.
- `G17-R6` (contract, P2): slash-only entry cannot preserve an existing composer
  draft. Resolved with F3 and modal-local navigation plus real input playback.
- `G17-R7` (evidence strengthening): existing G16 wheel cases cannot prove G17.
  Resolved with eight G17-specific required-case families on every platform,
  distinguishing installed CLI evidence from deterministic Product test seams.

The older single-reviewer G15 review is not evidence for this new contract.
Baseline local checks before implementation: 970 passed / 11 platform skips in
AppServer, AppService, AppHost, Harnesstui and G15/G16 design tests. These are
retained baseline checks, not G17 native/installed acceptance.

## G17.1 Local Implementation Review

Three independent reviewers rechecked the current Product/semantic slice only.
All reported their findings closed after regression-first corrections:

- Architecture (P2): resolver admission was derived from optional discovery.
  Independent admitted scopes now reach both resolver construction paths even
  when discovery is disabled. Enabling discovery requires the same exact set;
  forged scope/fingerprint requests cause no catalog call in either mode.
- Lifecycle (P1): cancellation of an internal `to_thread` Task could release
  the scan slot while its thread still ran. An actual-read completion signal
  now owns settlement, independently of asyncio Task cancellation. A real
  blocked-worker regression cancels all outstanding application Tasks and
  proves retained debt before release and successful cleanup only afterwards.
- Contract/evidence (P2): the old display-summary catalog could omit malformed
  or large-header entries and misclassify them as missing. Strict routing now
  validates the actual bounded candidates and directory revision. Real damaged
  files/invalid roots fail unavailable; valid 35 KiB headers remain resumable.

The focused Product/catalog/AppService set passed 48 tests after these fixes.
The lifecycle reviewer also independently ran both cancellation regressions
with an isolated temporary root: two passed. Static Ruff and the 19-file
changed-source typecheck passed. These local slice reviews are not the final
G17 implementation review and do not replace UI, launcher or native wheel
evidence. The first broad run had temporary-directory/child-start failures.
The isolated-root rerun passed 1,427 tests with 11 platform skips and one G16
disconnect-case failure: its five-second running poll included cold turn
preflight. The recorded held user message appeared 5.666 seconds after the
previous completed reply, then was aborted during test cleanup. This timing
does not prove a production preflight root cause. A reviewer audited 25 ordered
cases after fixture teardown and found no retained changes in key functions,
environment or live threads; an isolated pass alone is not failure closure.

The G16 case now waits for the actual synthetic `hold` model entry (also
observing early turn failure) before its existing running poll. The complete
scenario remains bounded by 30 seconds; both five-second observation windows,
disconnect/reattach, STOP and two-scope recovery assertions are unchanged.
The lifecycle reviewer approved this execution-stage synchronization correction;
the related ordered selection passed 26 tests. The final isolated-root broad
run passed 1,428 tests with 11 platform skips in 285.47 seconds, covering
AppServer, AppService, AppHost, Harnesstui, Harness transcripts, Hosted Coding
and G11–G17 architecture tests. The local JUnit report is
`.artifacts/g17-discovery-local.xml`. The exact AppService static gate also
passed Ruff and mypy on 67 source files. No G17 native wheel case is claimed.

### Explicit Foreground Wiring Review

The next bounded slice adds only explicit stdio command composition. All three
reviewers approved architecture/authority, lifecycle and contract boundaries.
The installed command's discovery profile is opt-in; legacy invocation and
its library parser remain compatible. Regression-first selection tests failed
before wiring (nine failed, two passed), then the new/legacy foreground and
architecture set passed 36 tests. The installed/legacy subprocess selection
passed 48 tests in 168.79 seconds.

Reviewer-requested evidence additions cover both admitted scopes with a real
persisted UserMessage, then compare the installed child's wire snapshot and
controller history projection. A command-level missing-capability case proves
application/transport recovery and repeated-close idempotence after foreground
construction fails. Those additions and G17 traceability passed 22 tests in
22.43 seconds. An initial test incorrectly accessed a presentation window's
nonexistent `identity` attribute; it now checks the actual wire snapshot's
complete identity and no longer masks assertion failures during cleanup.
Both AppService and AppHost static gates passed (Ruff; mypy on 67 and 80
source files respectively). New command tests are included in both gates;
AppHost's existing directory selection also includes the foreground tests.

These checks use the installed console entry in the local development
environment, not an isolated wheel or terminal. They do not close local
discovery wiring, picker, launch ownership or any required G17 native case.

### Explicit Local Wiring Review

The local slice preserves the default serialized record bytes and the
`local-detachable/v1` authentication domain. The exact optional capability is
included in the existing record digest; both peers select the semantic APP
profile from the mutually authenticated record. No client flag, re-read or
automatic downgrade chooses that profile. Legacy scopes keep their original
structural interface; only the optional typed factory borrows discovery.
All three reviewers approved the bounded architecture, lifecycle and contract
changes without remaining P1/P2 findings. No import or size budget expanded.

The pre-change local baseline passed 65 tests. Regression-first wire/record
tests initially failed 14 cases (eight existing-compatible checks passed), and
the Product/CLI opt-in tests initially failed all six before composition.
The resulting native transport/record and legacy set passed 63 tests. The
expanded Product/compatibility/lifetime/architecture set passed 64 tests in
43.10 seconds, including G16 held-work disconnect/recovery with discovery both
off and on. One initial Product assertion assumed a turn reply synchronously
delivered the scoped event relay; the test now waits for actual history records
within a five-second observation bound and the original 30-second scenario.
Production execution behavior and existing G16 timing budgets were not changed.

The frozen baseline decoder fixture is the complete original record module
from `7bf9e35f`, Git blob `b711e677cc9039117eda87995920db4f04d00b55`, verified
by SHA-256 before execution. It accepts the new implementation's legacy bytes
and rejects discovery bytes with its own original corrupt-record error. This
is frozen-decoder compatibility, not an old installed-client binary test.
Separate tests prove capability-tampered records fail authentication before
scope creation, cross-profile APP hello fails without discovery dispatch and
closes its exact scope, and seven APP clients leave the reserved STOP slot.

Actual local installed entry tests restore nonempty cwd/home history, preserve
the application across stdin EOF and client close, and explicitly STOP with a
zero exit status. They remain distinct from isolated-wheel/terminal acceptance.
The strengthened installed logical reattach (including the existing history
view) and documentation set passed ten tests in 93.98 seconds. The complete
AppService gate passed Ruff/mypy but its default leased-scratch test run ended
with 672 passed, ten platform skips and two failures in 538.62 seconds. Both
were the G16 held-work case (discovery off/on), cancelled by its outer 30-second
whole-scenario bound during the second application's recovery. They had already
passed their first application's running/disconnect/STOP checks. This is not
classified as an environment-only failure or fixed by isolated passing tests.

An independent default-scratch diagnostic passed both cases in 29.03 seconds;
four real Product Session constructions accounted for roughly 11 seconds per
case and each second-generation startup took 4.96 seconds. This identifies the
main local work, not the cause of the broad run's additional elapsed time.
Lifecycle and contract reviewers independently confirmed that G16 specifies
per-application startup/STOP budgets, not a combined two-generation 30-second
SLO. The test now uses two consecutive, fixed 30-second generation watchdogs.
Only after the first generation has successfully stopped and closed all its
resources does the second recover the same durable root and identity facts.
All five-second observation windows and production budgets remain unchanged;
no retry or individual close grants a fresh generation budget. Failure notes
record startup, interaction, STOP and recovery phase times.

This explicitly changes the test's nominal watchdog allowance from 30 to
30 + 30 seconds; it is not a performance fix or an environment diagnosis.
Cancellation cleanup may extend wall time beyond that nominal allowance.
The default-wrapper focused lifetime set passed 20 tests in 43.17 seconds.
The revised full AppService test gate completed with 674 passed, ten platform
skips and zero failures/errors in 639.153 seconds. The retained JUnit report is
`.artifacts/g17-local-discovery.xml`. Both discovery modes of the G16 lifetime
case passed within their per-generation watchdogs. This closes the local wiring
regression gate, not the unexplained broad-run slowdown or G17 native acceptance.

## G17.2 Picker Implementation Review

The shared shell borrows discovery explicitly; installed local attach supplies
the capability from its authenticated connection. F3 and `/sessions` open a
bounded modal, `/resume` without identity opens it, and `global` normalizes to
the admitted user-home scope in both picker and explicit identity commands.
Only explicit row selection calls the existing member-open path. Expiry,
incompleteness and unsupported rows do not cause fallback scans or opens.

Architecture, lifecycle and contract reviewers approved this bounded increment
after follow-up fixes. The contract review found a P2: coalesced normal text
events (`rr`/`nr`) lost refresh intent. Real InputReader regression first failed
both combined chunks; the fix processes normal command characters in order
while never executing pasted text. The query owner still retains only one
runner and one latest pending request. Further tests exercise page-two identity,
late scope results, reserved controls during saturation, duplicate selection,
cancel-resistant query cleanup debt and release under the same close deadline.

Stable per-member Composer instances preserve cursor, selection and undo across
selection/reattachment/reordering. The screen's explicit binding updates both
the editor and its retained bottom frame; successful close releases the cache
and replaces screen/frame/router references. Tests populate a nonempty kill
ring and render before close, so this assertion cannot pass merely by clearing
an unused editor. The final exact presentation sizes are 905/950 and 247/450.

The original shell/details/terminal baseline passed 16 tests. Three editor
regressions failed before implementation; twelve initial picker cases failed
before injection. The final picker/editor/terminal/design set passed 37 tests
in 3.91 seconds, and AppService Ruff plus mypy passed (68 source files).
A real Coding/native-local integration set passed 14 tests in 24.47 seconds,
including both admitted scopes: picker discovery, canonical resume, model
interaction, UI detach and reattachment with retained history. The model seam
is test-only; terminal byte playback uses FakeTerminalPort. Neither substitutes
for the required isolated-wheel/native-terminal evidence.

An earlier combination run had 45 passes and one original G16 lost-reply
terminal test hit its unchanged two-second watchdog. Static review found no
new wait on that failure path; its isolated rerun passed all five terminal
cases (the failing case took 0.02 seconds). The expanded run passed 67 runtime/
architecture cases and failed only the then-stale picker inventory, now fixed.
These results do not explain the earlier wall-time excursion. No production or
test timeout was raised for the picker slice. The complete AppService gate
passed with 703 tests, ten platform skips, Ruff and mypy in 461.71 seconds;
the retained JUnit report is `.artifacts/g17-picker.xml`. This closes G17.2's
affected local gate, not the required G17.4 isolated-wheel/native acceptance.

## G17.3 Settlement Hook Review

The first G17.3 increment adds an optional async settlement callback to the
terminal runner and the shell's startup-failure path. Default callers retain
shell-only cleanup; Product composition can select one outer owner without
introducing any UI dependency on AppHost or Hosting. The same callback may be
invoked again by terminal finally after startup failure, so it must join one
retained owner rather than create a fresh close budget.

All three independent perspectives approved this bounded hook. Four initial
regressions failed before implementation. The final selection passed 51 tests
in 8.43 seconds, including default G16 terminal/shell, picker, architecture,
normal exit, attach/terminal-entry failure, startup cancellation and cleanup
failure propagation after terminal restoration. Ruff and mypy passed (11 mux
source files); the exact four-file presentation group is 917/950 lines.

This proves cleanup strategy selection and ordering, not a twenty-second
process deadline, force/reap behavior or installed foreground entry. The actual
launch owner and its fault matrix are tracked separately below.

## G17.3 Launch Owner Implementation Review

The optional `apphost.launcher` now adopts a dedicated Hosting port, retains late
leases and exposes borrowed semantic clients only after the selected hello is
ready. At this owner-slice baseline Product composition was still pending; the
subsequent Product entry is tracked below. The pipe adapter bounds
reads to 64 KiB and writes to 1 MiB, with one lock across every chunk of a frame,
including the four-byte header. Its close requests EOF only; it does not take
process ownership from Hosting.

Independent cutoff reclamation reaches `lease.close` even if terminate or exit
observation fails. Reader handoff still requires actual startup/hello and client
settlement. Unknown exit observation is never invented as a successful exit;
`forced_exit` and the bounded scalar diagnostics remain available to Product,
which must report forced/unknown exit as nonzero. Raw stderr, argv, environment
and implementation exception strings do not cross the diagnostics/cleanup
error boundary.

Review fixes include exact profile enum admission before spawn, keeping adopted
detach tasks observable rather than cancelling them at cutoff, rejecting new
ordinary cleanup stages after deadline expiry, and retaining Hosting's last
resort close independently of exit observation. A further regression-first fix
retains terminate as its own phase and records each retry attempt: successful or
in-flight tasks are reused, and each failed phase can restart at most once per
explicit retry. Both duplicate-successful-terminate and double-close-in-one-retry
cases failed before this fix. Failed UI detach is not replayed.

These deterministic owner faults and exact architecture gates are local evidence,
not Product terminal, native process or isolated-wheel acceptance. G17.4's eight
case families remain planned on all three platforms.

All three independent reviewers approved this owner slice after the fixes above.
The final owner/architecture selection passed 70 tests in 30.90 seconds
(`.artifacts/g17-launcher.xml`). AppHost, AppServer and the shared shell/terminal
settlement regression selection passed 469 tests with 11 native-Windows skips
in 8.27 seconds (`.artifacts/g17-launcher-regression.xml`). The AppService Ruff
gate and mypy on 69 source files passed. The optional owner and private adapter
remain within the accepted 550-line budget; exact dependency and default-dark
core gates remain enforced. These are not the G17.4 required-case reports.

## G17.3 Product Entry And Failure-Reclamation Supplement

The separate `loushang-hosted-tui` entry now composes the owner and shared shell.
Its single optional Product module has a 450-line budget. Project dependencies
are lazy and exactly gated; default Embedded, G14 and G16 routes do not import it.
Example (the application directory's parent and workspace must already exist):

```bash
loushang-hosted-tui --workspace /work/project \
  --application-root /private/applications/coding \
  --cwd-sessions /private/sessions/project \
  --home-sessions /private/sessions/global --mux main
```

`--describe` is read-only, pathless and usable without a terminal. Interactive
mode requires both terminal input and output before any launch effect. The
selected mux is read first; only exact `NOT_FOUND` creates it once. Unknown
mutation outcomes are not retried. The returned stable mux ID, rather than its
name, binds attachment. Empty muxes do not silently create Sessions. The picker
gets the explicitly admitted discovery port, never a legacy fallback.

Product freezes the complete request and effective environment, retaining the
venv interpreter's `sys.executable` path. The fixed child argv uses `-I -m
loushang.coding.cli.hosted` and the explicit discovery profile. Workspace and
`PYTHONPATH`/`PYTHONHOME` cannot substitute a module; there is no weaker fallback.
The selected interpreter must see the installation without user-site packages.
Preparation checks the whole request and rechecks executable/workspace identity
before spawn. This trusts the installed environment; it is not H6 sealed
execution, a sandbox, or a claim that stat checks eliminate filesystem races.

One startup budget starts at Product `main` entry, covering subsequent lazy
imports, preparation, the child's cold imports/recovery/hello and mux selection
and attachment. It does not cover Python's earlier console-script bootstrap or
Coding facade initialization. Synchronous imports cannot be preempted, so every
subsequent admission checks expiry. Elapsed monotonic time is converted to the
event loop's deadline, not treated as the same absolute clock. The terminal
runner applies that deadline only to attachment; ready interaction has no
startup timeout. No late response can publish a shell after the Product close
fence. Terminal restoration precedes outer settlement.

The presentation-only `exit_ends_application` choice changes foreground help
and footer: `/exit`, `/detach`, Ctrl+B d, empty-editor Ctrl+D and terminal EOF
end the foreground application. There is no background management endpoint for
this child. Default local presentation continues to promise detach/accepted-work
survival, with G16's separate management commands.

### Physical Reclamation Debt At The Outermost Controller

The controller is the child's only process owner. Unlike the hosted child, it
cannot call `os._exit` merely because a 20-second settlement attempt expired.
That would discard the POSIX process-group owner and could orphan the child.
The optional launcher's pathless `process_cleanup_pending` is a conservative
proof: startup has actually ended, any published process lease closed
successfully, and the dedicated Hosting port closed successfully. An exit code,
terminate return or forced-exit flag alone never proves physical reclamation.
The existing `cleanup_pending` still includes unresolved UI/protocol work.

The already-authorized physical watchdog closes the lease and dedicated host
independently of UI/protocol settlement, including normal child exit. A failed
physical phase is only retried under an explicit later budget; successful or
in-flight phases remain retained. Physical cleanup is not new Product execution.

After an unsuccessful bounded attempt, terminal mode has been restored and the
controller visibly retains its Runner and existing cleanup tasks. It continues
driving that event loop; it does not block it with synchronous input. The prompt
explains that **Ctrl+C now explicitly retries cleanup**, granting at most another
20 seconds. Ordinary repetition, EOF or missing stdin neither grants a retry nor
abandons the owner. This recovery mode starts no second stdin reader: a previous
UI waiter may still own input. It never restarts a child or replays a business
mutation, changes the detach binding, or resets the graceful cutoff.

A continuous, non-raising SIGINT handler covers the entire controller holding
period, including synchronous diagnostic output and Runner handoffs. Its first
interrupt cancels the active interaction once; subsequent signals record retry
intent, and debt-mode signals only request cleanup. Signals during a retry are
coalesced as later intent, not cancellation of the cleanup owner. Broken or
closed stderr is best-effort diagnostic failure, never permission to abandon
the physical owner. The prior signal handler is restored only after physical
reclamation, before ordinary Runner shutdown.

Only after physical reclamation is proven may the outer process use a nonzero
fatal exit to release remaining client-only debt. It prints
`hosted_cleanup_incomplete`; this exception is not a claim of complete semantic
settlement. Forced, unknown or nonzero child exit also cannot become a zero
Product result. The entry/failure supplement has passed implementation re-review;
the real-child/fake-terminal tests do not replace G17.4's required native cases.

### Product Increment Review And Local Evidence

All three independent perspectives approved the Product increment after the
admission, startup deadline, foreground/local copy, physical-owner abandonment,
continuous SIGINT and broken-diagnostic fixes. No P1/P2 remained in that review.
The complete affected AppService gate passed 785 tests with 10 native-platform
skips in 428.78 seconds (`.artifacts/g17-product-entry.xml`), plus Ruff and mypy
on 70 source files. A subsequent fixture-only correction was rerun separately.

The installed `loushang-hosted-tui --help` command starts successfully. Three
additional real-command/native-terminal cases passed in 65.87 seconds
(`.artifacts/g17-terminal-entry.xml`): ready/foreground exit, cwd picker/history
restore/relaunch, and home picker/history restore/relaunch under a different
admitted execution cwd. Each history case retains its single canonical Session
file, and the second process renders the restored message without recreating a
Session or replaying work. These cases are now included in both local gates.

The subsequent terminal-fixture review found that killing only the PTY
controller's process group could abandon its separately grouped Hosted child
after a failed assertion. The foreground-only test context now first requests
SIGINT settlement on POSIX (terminal exit intent on Windows) and gives the owner
its full close budget. If needed, POSIX cleanup freezes the still-owned parent
before recursively adopting its actual descendants, bounds adoption to 128
descendants and a shared ten-second deadline, then terminates the adopted
descendants before restoring the controller to reap them. Every exceptional
path resumes its stopped processes in descendant-before-parent order. This is
a controlled Python test-tree guard, not hostile-process containment; no Product
process policy or generic terminal driver semantics changed.

Five real native cases passed after the initial cleanup fix in 89.46 seconds
(`.artifacts/g17-terminal-entry-reclamation.xml`), including an intentionally
failed predicate against the real Product and an unresponsive test controller
whose child has a separate process group. Both failure cases check that the
observed child PID is gone after settlement. The history/entry cases themselves
observe command exit and rendered history; they do not independently prove
terminal-mode restoration or child reaping. These remain explicit G17.4 duties.
After tightening the per-node and remaining-time bounds, all four selected
cleanup regressions passed in 15.14 seconds (three unrelated cases deselected;
`.artifacts/g17-terminal-cleanup-guard.xml`). The two added guard cases prove
that over-capacity adoption resumes stopped processes without partial killing,
and that `ps` receives only the remaining time budget. The G15/G16/G17
architecture subset also passed all 11 tests; Ruff and mypy on 70 source files
passed again. Required installed evidence remains unchanged and pending.

The physical-debt regression also uses an actual POSIX child: while termination
is deliberately held past a shortened test close budget, the controller remains
alive after terminal restoration and the child is demonstrably still live.
After releasing the retained cleanup, the child is reaped before the controller
exits nonzero. Separate real-SIGINT tests cover synchronous status output and a
second signal during retry; broken/closed stderr and stdin EOF cannot abandon
the owner. These local tests do not claim hostile external-kill survivability.

Product is 367/450 lines, launcher 444/550, and the exact four-file shared
presentation group 944/950. These results close the local G17.3 implementation
increment, not G17.4. The terminal cases used this editable installation on
Linux; isolated wheel origins/bytes and all eight required case families on
Linux, macOS and Windows remain unverified and are not marked accepted.

## G17.4 Native Workflow And Isolated Preflight Increment

The cwd/home native cases now create their canonical Session through the actual
installed foreground CLI. They explicitly close its member before exiting, so
a later picker does not attempt to take a Session still owned by the creator
mux. Historical content is appended only while the application is stopped.
An empty named `picker` mux must be observed before selection, with the history
sentinel absent; only output after Enter may satisfy the history and member
assertions. A new process then proves automatic durable restoration. Home
selection still uses a different admitted execution cwd.

Additional real local CLI cases exercise discovery opt-in, history selection,
detach, history reattach and explicit STOP; the application must remain alive
between clients. The unchanged local profile instead reports unavailable
discovery and still supports create/list/detach/STOP. Its Esc-to-command
transition waits for newly rendered main-screen content, rather than depending
on terminal input chunking. A separate real Product two-mux case runs the
existing synthetic-model stream/tool/approval/interrupt scenario with discovery
enabled. Its library seam does not substitute for the shipped CLI cases.

The first local run found three fixture failures (legacy Esc coalescing and
two attempts to reopen an already-owned Session). Correcting the input
handshake and explicitly releasing membership produced five passing native
cases in 177.10 seconds (`.artifacts/g17-native-workflow-revised.xml`; five
unrelated cases deselected). Contract/user-evidence re-review approved these
revisions without remaining P1/P2.

`scripts/dev/run_g17_installed_evidence.py --smoke` builds an independent
offline installation from a selected wheel and verifies source/package module
sets, wheel digest, installed package bytes and relevant import origins. It
runs exactly these five partial workflow cases and writes only
`.artifacts/g17-wheel-smoke-<platform>.xml`. Runner tests cover report
separation, exact case names and rejection of missing, duplicate, unexpected,
skipped or failed cases. This mode never invokes the complete evidence manifest.
Without `--smoke`, the runner refuses admission until the complete eight-family
selector exists. The inventory therefore marks the runner partially composed;
all three full evidence rows remain planned. Entry terminal-mode/child-reaping
observation, complete legacy/Embedded coverage, native startup cancellation and
forced-exit families, and the three-platform CI matrix still require completion.

The first Linux isolated-wheel preflight verified source, wheel and installed
bytes (wheel SHA-256 `f74409abd651f5ec5bba967de7c973c75d7eb2da03c3fec45b39469664462e10`)
but failed acceptance: four cases passed and the cwd case exited with
`hosted_client_failed` before terminal readiness on a subsequent launch
(`.artifacts/g17-wheel-smoke-linux.xml`, 254.14 seconds). Its cause remains
unverified; no startup budget was enlarged. This first attempt is not passing
evidence, even though subsequent attempts below passed.
The unchanged default G16 native two-mux scenario passed separately in 108.31
seconds (`.artifacts/g17-g16-native-default-regression.xml`).

Initial increment review approved the architecture boundary but found a runner P1:
`subprocess.run(timeout=...)` can kill pytest before its native fixture cleanup
and then remove the temporary environment while separately grouped descendants
remain. This required repair before committing the runner. A
separate report-validation P2 has been repaired by replacing outer-interpreter
assertions with explicit exceptions, including an optimized-interpreter
regression.

The revised test-only supervisor is composed of three stdlib-only helpers under
`scripts/dev`; Product and Hosting have no dependency on it. Its wrapper starts
with `-I -S` and admits site/test imports only after the parent's start gate
(and Windows Job assignment). Timeout requests cooperative interruption first;
even result-publication failures retain the wrapper until a physical-cleanup
release. Parse, pipe-close, repeated-SIGINT and late-wait failures cannot drop
ownership. Windows cleanup requires the independent non-breakaway Job's active
count to reach zero. POSIX freezes the retained Python tree, reclaims leaves
through their actual parents and hands off a still-frozen empty root.

The subsequent architecture review found that an adopted sibling could be lost
when its intermediate parent exited after reaping another leaf. The supervisor
now retains an adopted-member ledger across scans and cleanup retries. Global
PID disappearance, not absence from the current root tree or zombie status, is
required to clear a member. Changed ancestry is sticky cleanup debt and does
not authorize further signals. Resuming a stopped child additionally requires
its parent to remain frozen, closing the last-snapshot-to-resume race. Root
release requires both the current tree and ledger to be empty. These are
controlled Python-tree guarantees for observed descendants, not universal POSIX
containment of children orphaned before the first scan.

Deterministic regressions first reproduced both the forgotten-sibling and
last-snapshot race. A Linux-only independent subreaper regression then checks
real A/B branching, two rejected cleanup attempts, and acceptance only after
the actual new parent reaps the lost sibling. The fixture itself runs inside a
retained supervisor wrapper. Its timeout regression requires a fixture-finally
completion receipt and absence of all four recorded PIDs. An initial fixture
cleanup fault involved `ps` including its own transient child PID; the retained
owner required explicit recovery in that attempt, which is not accepted as an
automatic-cleanup pass. The Linux fixture now reads its direct-child list from
procfs without creating a transient observer process.

After the fixture repair, all 37 supervisor, runner and G17 architecture checks
passed automatically in 22.24 seconds
(`.artifacts/g17-supervisor-ledger-final.xml`). Ruff and `git diff --check`
passed. The original five-path contract review and the revised architecture and
lifecycle reviews approve only this partial increment, not the full native
acceptance matrix.

A subsequent isolated-wheel run passed all five workflow cases in 176.65
seconds, but its runner exited nonzero while removing read-only snapshot
directories. The bounded cleanup retry now repairs only owned, non-link
directories under that exact private installation; it never changes shared
hardlinked cache-file permissions. Failed installations remain for diagnosis.
After this repair, the same wheel passed all five cases in 169.52 seconds and
the runner exited zero (`.artifacts/g17-wheel-smoke-linux.xml`). This is Linux
partial preflight evidence only. The earlier intermittent cwd restart failure
still has no verified root cause. All eight complete families and the native
macOS/Windows matrix remain required before release acceptance.

The final preflight against that original wheel subsequently reproduced a
before-ready failure on the user-home relaunch: four passed and one failed in
217.24 seconds. The supervisor settled and retained the failed installation at
`.artifacts/g17-installed-a_9qcect`; a snapshot of its synthetic home inputs was
kept before three diagnostic replays, all of which succeeded. The latest report
therefore supersedes the earlier green report at the same smoke path. Neither
the earlier green run nor these diagnostic replays close the intermittent
failure's root cause.

### Startup Budget Correction

Inspection identified an independently reproducible startup-policy issue: the
foreground owner admitted up to 30 seconds, but its connection still used the
default ten-second hello wait. A controlled 10.1-second first-byte delay under
an explicit 15-second owner reproduced the premature timeout before the change.
The revised `RemoteAppClientV1.start(*, timeout=None)` permits an explicit budget
for this hello exchange only; omitted/None preserves `phase_timeout`. Validation
precedes state changes. It never changes ordinary send, close or the framing
deadline after the first byte. No wire/profile or default G14/G16 policy changed.

The launch owner captures one deadline before publishing startup. It checks
closing/expiry before a queued task may spawn, retains a returned lease before
rechecking, gives only the remaining budget to hello, and checks again before
publishing ready. The original retained startup, close and cancellation rules
remain. Review caught a queued-task admission gap; its regression first showed
an expired task still spawning, then verified zero spawn and normal host close.
All 112 focused connection, discovery, launcher and G17 architecture cases
passed in 12.03 seconds (`.artifacts/g17-startup-budget-final.xml`); Ruff and
mypy on both changed source files passed. Three perspectives approved the
revised budget increment. This is a verified policy correction, not a claim
that the original intermittent wheel failure has been conclusively explained.

A new wheel was built independently at `.artifacts/g17-budget-wheel`, SHA-256
`185525883b1b2a0d3c861b1ac969e2a7dce427aef4e580d8207388b9d63a6c34`.
The new isolated-wheel preflight verified current package bytes, imports and
digest, then passed all five selected cases in 218.29 seconds with runner exit
zero (`.artifacts/g17-wheel-smoke-linux.xml`). The original wheel no longer
matches current Product source bytes. This new passing preflight remains
partial evidence, not proof of the intermittent failure's precise cause or
completion of the eight-family, three-platform release matrix.

### Supplemental Linux ENTRY Observation

`tests/coding/test_hosted_entry_evidence.py` observes the actual allocated PTY's
native initial mode, verifies ECHO/ICANON are disabled at ready, and checks exact
restoration after the shipped CLI exits. Independently observed Hosted child
PIDs must disappear, not merely become zombies. Assertions happen before
fixture fallback, with no Product terminal or launcher replacement.

The observer runs inside a private supervised Linux subreaper so that a broken
controller cannot orphan a child before observation or cleanup. The guard
reaps actual direct children; if it finds leftovers after an otherwise
successful operation, it rejects success after cleanup. One fault case retains
the original assertion when a controller exits zero but leaves a separate-group
child; another rejects an operation that silently leaves a child. These tests
are supplementary local evidence, not yet isolated-wheel or cross-platform
ENTRY acceptance. macOS and Windows durable observer guards remain pending;
the tests are not added to the fixed five-case smoke or full eight-family IDs.

The final affected run passed all three guarded ENTRY cases along with the
connection and foreground regressions: 370 passed, ten platform-conditional
cases skipped, and one architecture failure in 76.99 seconds
(`.artifacts/g17-affected-entry-and-connections.xml`). That failure was the old
A0 exact-consumer list omitting the already-approved G17
`coding/cli/hosted_client.py` entry. Adding only this explicit path preserved the
dependency restriction; architecture review approved the correction and all
18 A0/G14/G17 boundary checks then passed in 27.00 seconds
(`.artifacts/g17-consumer-boundary-final.xml`). These local conditional skips
are not exceptions to the required zero-skip native release matrix.

### Legacy Family And Linux Native Fault Supplement

`tests/coding/test_hosted_legacy_evidence.py` composes actual legacy local CLI,
G14 installed stdio help/hello/list/EOF, and the installed `loushang --tui`
Embedded welcome/quit path. Each has a distinct private root. The aggregate
constrains inherited local/G14 environments; G14 also runs from its private
cwd. Embedded receives only OS/terminal prerequisites and explicit private
Loushang roots, not provider credentials, plugin flags or Python source paths.
Its paste/focus mode pairs, zero exit, no driver termination fallback and
stopped reader remain observable requirements. The wheel origin probe now
includes the Embedded console module and its TUI dispatch module. This family
is in local focused gates but is not yet composed into full wheel acceptance;
the existing five-case smoke selection is unchanged.

The Linux observer now additionally exercises two real-process fault paths:

- After the actual installed foreground CLI becomes ready, stop its real
  Hosted child using an identity-bound pidfd. `/exit` must return 1, restore
  actual PTY termios exactly, and reap the child before fixture fallback.
  Product grace/force budgets and the Hosting backend are unchanged.
- A test-only wrapper holds publication of an already-created real Hosting
  lease. Cancellation is deliberately resisted until the real host finishes
  closing; the late lease must still settle. The real Product `main` runs on
  a native PTY, exits 130, never invokes the observed/delegated terminal entry,
  and leaves the PTY baseline unchanged and the child absent. This is a
  library fault seam, not a substitute for the shipped CLI entry case.

The independent Linux subreaper guard continues to reject successful evidence
if it must reclaim leftovers. Review corrected numeric child PID signalling
to typed libc pidfd calls, retained the controller identity by checking its
unreaped live diagnostics once, and added a terminal-entry observer rather
than inferring absence of transient activation from two termios samples.
The local portable Python lacks `os.pidfd_open`/`signal.pidfd_send_signal`;
the system libc exposes both APIs. Missing APIs or failed admission fail the
test; there is no numeric-PID fallback or skip that manufactures acceptance.

Contract review also corrected inherited G14 source-path contamination and
removed an unbound `application` directory assertion that could not prove
Embedded storage behavior. Environment-injection regressions check both the
filter and its actual aggregate call boundaries. Architecture, lifecycle and
contract re-review approved this bounded increment with those findings closed.

Local evidence:

- Revised LEGACY native aggregation and runner regressions: 15 passed in
  49.13 seconds (`.artifacts/g17-legacy-isolation-revised.xml`).
- Final native ENTRY/fault and boundary selection: 25 passed, three unselected
  LEGACY tests, in 71.99 seconds
  (`.artifacts/g17-native-faults-and-boundary-final.xml`).
- Final environment injection, Embedded probe assertions and inventory
  traceability: 21 passed, one unselected native LEGACY test, in 5.05 seconds
  (`.artifacts/g17-legacy-boundary-final.xml`).
- `make lint-apphost` passed. Initial cancellation-fixture and missing Python
  pidfd-binding failures were corrected in the test harness, not Product code.

These are local editable-installation/Linux observations. Recovery-phase
cancellation, macOS/Windows durable observation, isolated-wheel composition
of all eight required families and the three-platform CI matrix remain work
to complete. All full manifest rows remain planned; neither this supplement
nor the prior partial smoke closes G17.4.

### Recovery Cancellation And Complete Linux Selector

The recovery-cancellation fault now starts with a Session created by the actual
installed foreground CLI. After that CLI stops, the test adds one offline
UserMessage sentinel through SessionManager and retains canonical bytes and
the decoded desired-state record. A fixed test child delegates to real service
`main`, waits for the original `_recover_session` to reopen the actual Session,
then holds its owner before recovery/hello publication. The real controller
receives SIGINT and must exit 130 with unchanged native terminal mode, no
terminal-entry invocation and no remaining child. This proves physical
reclamation during recovery, not cooperative AppService settlement inside a
forcibly terminated process.

The recovered owner's complete SessionIdentity must match the decoded durable
member, not a value inferred from its filename. Desired state and canonical
history remain byte-identical after cancellation. A new actual installed CLI
must then display the history sentinel that was never typed into that terminal;
its durable mux identity and complete members remain equal, with no new
canonical file and unchanged history bytes. Review corrected the initial
`hosted-` filename/identity mismatch and strengthened the initially empty
Session to this nonempty-history proof. The final focused native case passed
in 57.87 seconds (`.artifacts/g17-recovery-history-native.xml`).

`tests/coding/test_hosted_installed_evidence.py` now selects exactly eight G17
family IDs. ENTRY combines real installed help/start/exit with the independent
native observer. START-CANCEL runs both publication and recovery cancellation
in separate private roots; either failure fails that family. Other families
reuse the actual cwd/home picker, local lifetime, legacy aggregate and explicit
synthetic-model Product interaction paths. Provenance assertions require wheel
archive metadata and real import locations before recording `installation=wheel`;
the outer runner additionally verifies the selected digest and exact package
module sets and bytes. The full selector is not in editable-source test gates.

Linux's manifest row is implemented because this gate is composed; full mode
still rejects macOS/Windows before installing anything. Their manifest rows
remain planned and the overall inventory remains partial. Five-case smoke
keeps its independent selector, report and verifier. Runner/architecture
boundary checks passed 22 tests in 1.08 seconds
(`.artifacts/g17-full-selector-boundary.xml`); actual pytest collection found
exactly the eight required IDs. `make lint-apphost` also passed.

The first complete Linux isolated-wheel run passed all eight required families
in 336.38 seconds. `.artifacts/g17-wheel-linux.xml` contains exactly the required
IDs, `native_platform=linux`, `terminal_backend=posix-pty`, `installation=wheel`,
and zero skips, failures or errors. The manifest verifier and outer runner both
exited zero, including supervised descendant settlement and private installation
cleanup. The independently built wheel's SHA-256 is
`185525883b1b2a0d3c861b1ac969e2a7dce427aef4e580d8207388b9d63a6c34`;
its Product modules are unchanged from the prior budget-fix wheel.

Architecture re-review then corrected default test activation: ordinary
editable suites must not execute a wheel-only selector. `tests/conftest.py`
now deselects only this exact file unless `--g17-installed-evidence` is supplied;
full runner supplies it, smoke does not. An explicit selector invocation
without activation selects zero tests and exits 5, not a skipped/passing full
report. The first full run had already started before this collection-only
correction; its eight family implementations are unchanged. The activation
boundary has separate collection and runner regression evidence.
The final activation/runner/architecture selection passed 24 tests in 12.19
seconds (`.artifacts/g17-selector-activation-final.xml`). Architecture,
lifecycle and contract re-review approved the increment after the identity,
history-proof and default-activation findings were corrected.

This is local Linux wheel acceptance, not exact-head three-platform CI or
mainline delivery. macOS/Windows guarded native observations and full wheel
jobs remain pending; the active G17 objective is not complete. A passing run
also does not establish the precise cause of the original intermittent
before-ready failure recorded above.

## G17.4 Windows Native Observer Supplement

The test-only Windows observer is now composed separately from full installed
acceptance. A retained witness shares the actual CLI's ConPTY, reads baseline,
ready and post-exit console modes without changing them, and stays attached
until the observer releases it. Its real console control handler does not give
the child an inherited ignore-Ctrl+C attribute. The witness reports its own
native PID; pinned process ancestry plus console membership separates venv
redirectors and console launchers from the detached Hosted service.

The independent evidence supervisor assigns its non-breakaway Job before
pytest starts. Its redirector admission correction is implemented below but
still awaits native CI, so full descendant ownership is not yet accepted. Native
thread handles are registered before suspension; synchronous GetThreadContext
confirmation precedes a bounded thread-snapshot fixed point. Cleanup only
undoes confirmed owned suspend increments, retains ambiguous effects, and
retries failed handle closes without resuming twice. Interruption during the
suspend-state handoff retains uncertain ownership for the outer Job.

The separate Windows AMD64 CI job requires five exact zero-skip cases: normal
entry/exit, publication cancellation, recovery cancellation, forced exit, and
a native heartbeat negative control. The last proves that suspension actually
stops execution while the process remains alive, and that undoing suspension
restores progress before cooperative fixture exit. Recovery cancellation
reuses the existing full identity, canonical history bytes and subsequent
actual CLI recovery assertions; the default Linux observer is unchanged.

The [native supplement manifest](hosted-session-workflow-g17-windows-native-manifest.json)
requires Windows/ConPTY properties but makes no wheel-installation claim.
Its implemented status means the selector and CI are composed, not that native
execution has passed. The main Windows eight-family wheel row remains planned.
Three-perspective re-review approved this implementation/CI slice after
correcting Windows mode assumptions, native process roles, suspend confirmation,
and interrupted suspend/resume bookkeeping. An interrupted Resume retains
unknown effect state so reentrant cleanup cannot decrement a suspend count twice.
Local portable observer, manifest, architecture and supervisor regression
checks passed 44 tests in 26.95 seconds
(`.artifacts/g17-windows-observer-final.xml`); `make lint-apphost` passed.
Actual Windows native execution and full Windows/macOS installed acceptance
remain pending. No Product API, default entry or dependency boundary changes
are introduced by this test infrastructure.

### First Native CI Integration Findings

PR #575's first Windows supplement failed all five cases during nested pytest
collection, before native observation. The repository/config was on D: and
the generated probe on C:; an unquoted Windows `pythonpath` override lost its
backslashes through pytest's POSIX shlex parsing. The probe now sets its own
rootdir/confcutdir and passes a quoted forward-slash repository path. Its
portable regression invokes a real isolated pytest collection, imports the
probe and helpers, and requires exactly one collected test. This does not
replace rerunning the Windows cases.

The same CI exposed stale pre-G17 exact inventories. G9 inventory v6 adds the
explicit Hosted TUI entry while preserving all Current and canary rows. A0,
G9/G10, v1 and PLC consumer fences now enumerate the approved optional launcher
and Product command. Only the exact launcher may import Hosting contracts;
core and reverse-direction prohibitions remain. Wave A retains its 33,800-line
core budget and gives the new Product command the independently reviewed
450-line G17 budget. Generated package facts were refreshed with the existing
renderer, not hand-edited.

Three-perspective re-review approved these scoped corrections. The expanded
local selection first passed 85 tests with one further missing v1 consumer;
that exact entry was repaired and its regression passed separately in 12.94
seconds (`.artifacts/g17-ci-v1-fence-recheck.xml`). The preceding full selection
is retained as `.artifacts/g17-ci-fence-fixes.xml`, not claimed all-green.
The full architecture-documentation gate passed five tests in 48.26 seconds.
On the first CI head, all three G16 native and all three G16 wheel jobs passed;
those results preserve baseline evidence but do not establish G17 acceptance.

### Native Process Topology And Remaining Windows Failures

Windows native job `102033391999` on `2c9d93de` reached actual observation.
Both the Hosted launch and the heartbeat fixture showed a Python redirector
with two children: a console host and the executing Python process. The former
single-chain observer rejected this topology before fault injection.

The observer now retains at most one console sidecar separately from the main
chain. It queries the pinned process handle's full executable path and compares
it with the system API's directory plus `conhost.exe`; environment values and
Toolhelp basenames cannot grant admission. Query failure or truncation,
additional sidecars, descendants of a sidecar and changed ancestry/children
are rejected. Every main-chain image is also checked, so a lone console-host
child cannot become the suspension target. Final exit proof covers main chain
and sidecar handles within the existing deadline, without killing a remaining
sidecar to manufacture success. The heartbeat uses the same observer.

The portable selection passed 28 tests in 11.18 seconds after adding full-path,
API-failure, topology and physical-exit negative controls. An earlier run had
26 passes and one assertion-message mismatch: the new child-set fence detected
changed ancestry before the existing identity diagnostic. All identities are
now checked before child sets; both checks remain required. Lifecycle review
also found and closed the single-child console-host target ambiguity. These
portable results do not establish native or wheel acceptance.

Contract re-review additionally corrected native path-length validation to
count UTF-16 code units, including non-BMP interpreter and system-directory
paths. Architecture, lifecycle and contract re-review approved the final
sidecar slice. Its combined observer, manifest, runner and architecture
selection passed 63 tests in 24.83 seconds
(`.artifacts/g17-sidecar-review.xml`); changed-file Ruff and diff checks passed.

On the same CI head, Windows quality job `102033392342` finished with 852
passes, 25 skips and three failures: legacy member creation/reattachment,
normal supervised multigeneration cleanup, and real-child command settlement.
The line-ending, frozen-fixture and pending-scan test corrections passed.
The supervised normal test itself passed but cleanup recorded two active Job
processes. Their identities remain to be proven; permitting an extra active
process is not an acceptable fix. Direct invocation of the target venv's
controlled base interpreter is the reviewed next approach to eliminating the
redirector-before-Job race while preserving isolated startup and venv imports.
Windows native rerun, full Windows/macOS wheel composition, exact-head matrix
acceptance and mainline delivery remain open.

### Windows Controller Admission Correction

The supervisor now bypasses only the test controller's venv redirector. It
reads the target executable's bounded `pyvenv.cfg`, requires one absolute base
home and an existing matching standard CPython runtime, and rejects nested
redirectors or adjacent `._pth` layouts before spawning. The copied environment
removes both executable overrides case-insensitively, then sets the trusted
venv launcher override to preserve CPython's own executable/prefix handling.
There is no PATH fallback or PYTHONPATH replacement, and Product launch code
is unchanged. This is a controlled test-interpreter layout contract, not binary
signature verification or protection against concurrent executable replacement.

The actual base interpreter runs `-I -S` and publishes an atomic pre-start
receipt. After Job assignment, the parent requires the receipt PID to equal
the Popen PID, `no_site` to be one, and Job active count to be exactly one.
Only then can `start` enable `site.main()` and pytest. Both cancellation and
deadline are rechecked after observation and before release; admission consumes
the existing overall deadline, with its own maximum of ten seconds. If admission
fails after assignment, cleanup terminates and empties the whole Job before
waiting for the root and closing handles. The existing extra-process failure
criterion is not relaxed.

Portable tests cover malformed/ambiguous layouts, inherited overrides, receipt
identity, late cancellation and expired admission, including the complete
no-start/Job-reclamation path. A Windows-only actual test creates a separate
venv in-process with subprocess creation forbidden, proves that its `.pth`
sentinel has not run at admission, then verifies target executable/prefix,
the fixture's declared pytest dependency origin, launcher-variable clearing,
and Job count zero at close. It intentionally shares pytest dependencies and
does not claim isolated Product wheel evidence. The existing deliberate
multigeneration leak regression must still fail and reclaim its descendants.
Three-perspective re-review approved after closing fixture setup ownership,
late cancellation and deadline findings. Native Windows results remain pending.

The final local supervisor/runner/sidecar selection passed 85 tests in 48.42
seconds, with the one Windows-only actual-venv case skipped on Linux
(`.artifacts/g17-controller-admission-final.xml`). This skip is not a required
Windows acceptance result. Changed-file Ruff, `make lint-apphost` and diff
checks passed; the native CI must execute that case as well as the existing
normal and deliberately leaking multigeneration cases.

### Native Windows Pass And Legacy Home Isolation

On `c9332719`, native Windows job `102041078095` passed all five supplemental
cases in 58.30 seconds. The exact manifest verifier confirmed five tests with
zero skips, failures and errors. This establishes the console/fault supplement
and its actual supervised execution, not the eight-family Windows wheel report.
The same head's Windows quality job was still running when this increment was
prepared; the separate-venv and remaining Product-flow results are not inferred
from the supplemental pass.

The legacy failure's first visible notice was `session_unavailable`, followed
by the generic refresh hint. Its private environment had removed all OS home
variables. Real session bootstrap necessarily resolves `Path.home()` while
constructing/configuring the model registry: Windows cannot expand it without
USERPROFILE/HOMEPATH, while POSIX can fall back to the actual user's passwd
home. Each legacy fixture now creates its own `user-home` and explicitly sets
HOME and USERPROFILE after allowlist filtering. Ambient home values, credentials
and source paths stay excluded; platform storage and Session scope roots are
unchanged. A regression first failed on the missing HOME and now verifies both
Path.home and Windows ntpath expansion against the private directory.

The full Linux legacy selection passed three tests in 53.44 seconds
(`.artifacts/g17-legacy-private-home.xml`). Separately, the real-child isolation
test now attaches only fixed lifecycle-phase states, exception class names and
the forced flag on failure; its unchanged successful Linux path passed in 9.69
seconds. These diagnostics add no cleanup, retry or budget behavior and do not
expose stderr, environment, arguments or exception messages. All three reviewers
approved this fixture/diagnostic increment. Actual Windows legacy and real-child
results remain required before their failures can be marked closed.

### Complete Windows Wheel Composition

The exact eight-family selector now dispatches Windows native observations to
the independently verified Windows observer, while preserving Linux's existing
observer and timeout choices. Both startup cancellation phases still run in
separate directories. The Windows full manifest is implemented because its gate
is composed, not because it has passed. Darwin full mode continues to reject
before installation. A dedicated CI matrix builds the current wheel and runs
the full selector/verifier on Linux and Windows, separately from the five-case
Windows native supplement; no smoke selector can satisfy this job.

The runner quotes its forward-slash repository-only pytest path, preserves
isolated wheel/module byte checks, and explicitly checks the target venv prefix
and executable. Its two fixed Python probes (wheel validation and manifest
verification) now use the same retained supervisor as pytest, including Job
admission, deadline, interrupt and physical-cleanup guards. They get independent
receipt directories and preserve script argv/SystemExit semantics. Arbitrary
Python probe calls are rejected by the runner; external uv installation commands
retain their existing separate path.

Native CI also showed that the multigeneration leak fixture could drop its
Windows Popen object, close stdin and thereby let its supposedly leaked child
exit cooperatively. The fixture now explicitly retains that object. Both pytest
and standalone probe leak controls require a successful execution receipt before
claiming rejection for native leftovers; the standalone probe also records its
successfully spawned child and checks physical removal on POSIX. Error-mode
probes require the exact requested exit code. These are test-fixture corrections,
not permission to accept extra active Job processes.

Architecture, lifecycle and contract re-review approved this composition after
strengthening the probe leak negative control. The combined local selection
passed 71 tests with one Windows-only skip in 42.12 seconds
(`.artifacts/g17-windows-wheel-composition-final.xml`); the strengthened probe and
multigeneration selection passed nine tests in 13.61 seconds. Absolute-script
argv and SystemExit preservation additionally passed both cases in 0.68 seconds.
The preceding combined run was not green: an undeclared YAML import was removed, and concurrent
default pytest scratch cleanup had removed another run's temporary root. The
passing rerun used the repository's managed, per-run scratch wrapper. Fixed
Actionlint 1.7.7, verified against its release checksum, accepted the workflow.
Full native wheel results remain required; no three-platform acceptance or
mainline delivery is claimed by this increment.

### Cancelled Poll And Local Connection Closure

Windows quality job `102043052614` on `b81df8d7` completed with 890 passes,
25 skips and two failures. The legacy private-home case passed. One remaining
failure was the leaking-child fixture corrected above; the other real-child
case reported only `detach=AppConnectionClosedError`, with client, EOF, drain,
lease and host phases done, termination absent and `forced=False`.

Cancelling the shell's poll while RemoteAppClient is sending closes that local
connection deliberately: a potentially partial frame cannot be reused. A later
detach is therefore rejected locally. Controller close now accepts that concrete
local connection exception and releases its view only after poll settlement.
This is not a remote detach acknowledgement. Connection, scope, lease and process
owners retain their independent cleanup duties. Ordinary wire SERVICE_CLOSED,
OSError and cancellation still fail and retain the view's cleanup debt.

Architecture re-review found and closed a P2: the semantic controller must not
import framing. AppConnectionClosedError now belongs to the transport-neutral
client contract; framing preserves the same class as a compatibility export,
including EOF inheritance and error code. No wire bytes, timeout, ownership
algorithm or architecture budget changed. Exact controller import and exception
identity regressions first failed twice before that boundary correction.

The real RemoteAppClient state machine with a controlled stream reproduces
cancel-during-send and delayed cancellation; it does not substitute for a native
transport test. Its two regression cases failed before the close fix. The final
expanded connection, local authentication/discovery, shell, Product-client and
G11/G16/G17 architecture selection passed 156 tests in 40.18 seconds
(`.artifacts/g17-detach-client-contract.xml`). Ruff, three-source mypy and diff
checks passed. Architecture, lifecycle and contract re-review approved the
corrected implementation with no remaining P1/P2 findings in this slice.
The fixture also cancels its poll on early assertion failure before gathering
tasks. Fresh Windows quality and full Linux/Windows wheel reports are required
before declaring the observed Windows failures closed or reusing earlier wheel
acceptance; the Product bytes changed in this increment.

### First Complete Linux And Windows CI Acceptance

On `c9f205bdfba8c3c8e399bfb5d1716a5a254bb3c8`, AppService workflow
`34223772723` passed both complete wheel jobs: Linux `102052819178` ran eight
families in 128.50 seconds, and Windows `102052819237` ran eight in 145.78
seconds. Both verified installed module origins/bytes and the exact required
manifest. Wheel SHA-256 values were respectively
`d0767f169d97d4109e0d057dfe1126301fba94bec02dc06c9d81322f030cf9b9` and
`fc115f61ff38fd1147882250164b6bf037aaed3525eaaaad02deda617de6bd46`.
The Windows five-case native supplement and all six G16 native/wheel matrix
jobs also passed on that head. This does not cover G17 Darwin observation.

The same workflow's Windows quality job `102052819320` failed two tests, with
907 passes and 25 skips. The previous detach and leaking-child fixture failures
were absent, but this is not an all-green quality claim. The new failures were
the queued-start deadline regression and G14 failed-construction cleanup retry.

The queued-start fixture previously slept 30 milliseconds to cross a 20
millisecond loop-clock budget. It now advances the exact loop clock before
entering the startup body and still requires no spawn or lease operations.
It does not enlarge or modify any Product budget. For the Session fixture,
private settings alone did not isolate user-resource roots or durable plugin
lifecycle IO: those resolve platform paths independently. HOME, USERPROFILE,
LOUSHANG_HOME, runtime and scratch roots are now private, with a resolver-root
regression. The existing 20-second watchdog remains unchanged; a timeout gains
only fixed phase names and monotonic elapsed times. This distinguishes slow
synchronous construction from later cleanup debt without assuming either is
the proven CI cause. No Product close algorithm or cancellation contract changed.

Both test files passed the preceding Linux baseline (52 tests in 27.19 seconds)
and the revised selection (53 tests in 26.75 seconds;
`.artifacts/g17-windows-clock-home.xml`). The deterministic queued-start case
also passed separately. Architecture, lifecycle and contract re-review approved
the fixture-only corrections; Ruff and diff checks passed. Actual Windows rerun
remains required to close these
two reported failures; the failure stack alone did not establish a Product
resource-refresh deadlock.

The subsequent `d4e7289a80cece8bf8285b9be2a2683e524651bd` AppService workflow
`34226302166` completed successfully across all 12 jobs. Windows quality
`102061158395` passed 911 tests with 50 skips in 568.37 seconds; the two earlier
failures are absent. Required installed reports remain separate from quality
skips: Windows `102061158210` passed eight tests in 173.72 seconds and Linux
`102061158241` passed eight in 136.96 seconds, each with exact-manifest validation
and zero skips/failures/errors. Their wheel SHA-256 values were respectively
`52f7ebab961b59d7c77a5e66209994d1f4381527183e6190f5e09a36621278cc` and
`ab5280cc9fb673d81c284c9ed38d377d1b67e578d8be2176f4abc4a3aacda93e`.
The Windows native supplement, all six G16 native/wheel jobs and Linux/macOS
quality also passed. This head still supplies no G17 native Darwin report.

## G17.4 Darwin Observation Admission Guard

The first Darwin infrastructure slice supplies a POSIX observation registry,
not a Darwin observer or a passing native selector. Every first-party POSIX
evidence supervisor registers a scope before starting its retained controller.
Nested supervisors inherit the actual supervisor's scope, independently of a
caller-supplied child environment, and keep records in the outer private root.
Removing an inner workspace cannot discard an ancestor's view of observation
debt. Windows keeps its existing independent Job containment path.

A native-observation scope starts open before spawning, records a bounded
controller/child identity set when admitted, and can only be completed by the
trusted observer after physical proof. Unknown identity is not completed by a
later empty process-tree scan. The registry itself does not observe processes,
grant numeric-PID signal authority or manufacture physical proof. Before any
tree scan, signal, release or reap, a supervisor seals registration beneath its
scope and checks the entire subtree for unfinished observations. Registration
and sealing share one interprocess flock, so either registration wins and the
ancestor retains debt, or sealing wins and the new registration cannot spawn.

Registry size, scope count, ancestry, receipt size and lock acquisition are
bounded. Duplicate JSON keys, missing/corrupt receipts and wrong identities
fail closed. Atomic publication failure preserves the prior admitted record
for the same observer to retry; a closed receipt is idempotent. Only a known
pre-start abort, including Popen's synchronous OS-error path, can discharge an
observation without native proof. An ambiguous interruption is not such an
abort. Controller-only environment data is stripped at the test Product
environment boundary; no Product package imports or handles this registry.

The initial local-only ticket proposal was rejected during lifecycle review
because an outer supervisor could bypass the inner debt. Review additionally
closed parent-context inheritance, Product-environment leakage, zero-spawn
false debt and duplicate-JSON findings. Cross-process register/seal controls,
ancestor retention after inner-directory removal, depth limits, publication
retry and zero-effect cleanup negatives cover those corrections. These tests
are registered in both affected AppHost and AppService quality selections.
The final registry, supervisor and wheel-runner selection passed 90 tests with
one Windows-only skip in 46.54 seconds (`.artifacts/g17-observation-reviewed.xml`).
The earlier Product-environment/real-child combination passed 76 tests with one
Windows-only skip in 165.39 seconds. Architecture, lifecycle and contract
re-review approved this infrastructure slice after the listed corrections;
24 G11/G16/G17 architecture checks and `make lint-appservice` also passed.
These local results do not establish native Darwin observation.

Darwin's retained CLI witness, public waitid/WNOWAIT and kqueue observation,
whole-scenario physical-proof retention, cancellation/forced-exit cases and
full wheel CI composition remain required. Completing this registry alone
must not change the Darwin manifest from planned or satisfy G17-INSTALLED.

### Darwin Public-API Primitive Supplement

The next test-only slice composes five native cases: unreaped exit observation,
registered exit events, a confirmed stop/resume heartbeat barrier, and sticky
rejection of unexpected fork/exec topology. The dedicated macOS job checks the
exact five-case primitive manifest with zero skips. It does not claim an
installed CLI, restored terminal modes or complete eight-family acceptance;
the full Darwin manifest remains planned.

The bindings use public Darwin `waitid(P_PID, WNOHANG | WEXITED | WNOWAIT)` and
kqueue process filters. The owning parent must retain its child until explicit
reap authorization; a kqueue event alone grants no signal authority. ABI fields
use explicit Darwin 64-bit widths even when portable controls run on Windows.
`EV_RECEIPT` uses its public numeric value because CPython 3.11 does not export
that constant. Exit observation waits for both the exit event and the exact
waitable exit code within one deadline, without assuming those kernel states
become visible simultaneously.

Primitive child fixtures run isolated Python with `-I -S` in an independent
POSIX session. Fork parents retain their actual reaping obligation through
interrupts and marker-publication failure. Portable controls send a real
process-group SIGINT and inject an actual post-fork file-write error, then
verify live ancestry and final child/parent absence after actual waitpid.
Cleanup diagnostics cannot break the continuous interrupt guard.

Architecture, lifecycle and contract re-review approved the corrected slice.
Portable/API/architecture regressions passed 27 tests in 1.47 seconds
(`.artifacts/g17-darwin-primitives-reviewed.xml`); Ruff and diff checks passed.
Native macOS execution is still required. This supplement is preparation for,
not a replacement for, the retained CLI witness and whole-workflow observer.

The first actual macOS primitive job `102068652964` in workflow `34228565864`
on `41ee3b9f` passed four cases and failed STOP-BARRIER after the confirmed stop
and stable heartbeat: waitid returned a state the adapter rejected. Public XNU
sources explain a compatible stopped-state path: kernel compilation disables
UNIX03 in [cdefs.h](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/cdefs.h),
so [wait.h](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/wait.h)
defines WSTOPPED as 0177; that mask overlaps the supplied options in the
[waitid stop branch](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_exit.c).
The original failure did not record raw code/status, so this explanation still
requires a native rerun. The adapter now recognizes only exact-PID/SIGCHLD,
CLD_STOPPED with a valid Darwin stop signal as non-terminal (`None`). It neither
reaps nor relaxes exit proof, and unknown diagnostics include bounded numeric
code/status. Seven controls first produced four failures and three passes;
the corrected portable/API/architecture selection passed 34 tests in 1.35
seconds (`.artifacts/g17-darwin-stopped-reviewed.xml`). Native acceptance remains
pending until the unchanged five-case gate passes on the corrected head.
