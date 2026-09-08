# Explicit Hosted Session Workflow G17

[Architecture](../README.md) · [AppHost](README.md) ·
[G15](foreground-hosted-tui-g15.md) ·
[G16](../appserver/detachable-local-workspace-g16.md)

## Status

- ID: `HOSTED-SESSION-WORKFLOW-G17`
- Kind: incremental cross-scope contract and delivery design
- Authority: normative accepted incremental design; inherits G15/G16 boundaries
- Design status: accepted after independent three-perspective review and re-review
- Implementation status: partial — discovery values/codec and optional wire profiles;
  Product discovery, AppService views, picker, launcher and installed acceptance pending
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

This slice is implemented-uncomposed: no installed Product command selects the
new profiles or exposes directory discovery yet. Neither a working picker nor
G17 runtime/installed acceptance is claimed by protocol tests. Subsequent
slices must update the source inventory and required-case manifest as actual
Product, semantic, UI and process ownership is delivered.

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
scope set to both resolver and discovery. The resolver checks Product/scope/
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
