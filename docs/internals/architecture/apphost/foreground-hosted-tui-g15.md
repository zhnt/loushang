# Foreground Hosted TUI G15

[Architecture](../README.md) · [AppHost](README.md) ·
[G14](../appserver/foreground-stdio-hosted-app-g14.md) ·
[Named Mux proposal](../drafts/harnesstui-named-mux-daemon-attach-design.md)

## Status

- ID: `FOREGROUND-HOSTED-TUI-G15`
- Kind: cross-scope boundary and delivery design
- Scope: AppHost optional launcher / Harnesstui hosted shell / Product composition
- Parent: Loushang application architecture
- Authority: normative accepted boundary design
- Design status: accepted following the three-perspective review below
- Implementation status: not-started for the G15 launcher; the shared shell is
  implemented by G16, which does not implement the foreground child lifetime
- Activation status: existing defaults and G14 foreground semantics unchanged
- Tracking: [Hosted Workspace V1 #566](https://github.com/zhnt/loushang/issues/566)
- Inherits: [architecture principles](../loushang-architecture-principles.md),
  [governance profile](../governance-profile.md),
  [ARD-003](../decisions/ARD-003-apphost-top-level-placement.md)

## Outcome And Scope

A user explicitly selects a foreground Hosted TUI, creates or selects a named
mux, works in independent Session windows, exits, and later recovers canonical
history. The controller process owns its child application. Exiting the client
ends that foreground application; logical mux detach is not a promise that the
process remains alive. G16 requires a separate detachable deployment contract.

This goal accepts G15 design and then implements G16. It does not label the
whole G15 UI/launcher implemented merely because G16 reuses part of this design.
Every reused responsibility must have its own implementation/evidence entry.

Non-goals: daemon/service installation, background discovery, network listeners,
automatic restart/replay, live-runtime transfer from Embedded TUI, multiple
writers to one mux, default activation, new top-level packages, and feature
parity with every Coding Embedded command or attachment type.

## Current Facts And Delta

The [source-backed inventory](foreground-hosted-tui-g15-inventory.json) records
the baseline separately from planned files:

- Hosting provides shell-free Process Host and atomic Child Session Host,
  explicit launch preparation, bounded byte IO and process-tree cleanup.
- G14 provides framed stdio, AppClient, real Coding Sessions and an installed
  `loushang-hosted` executable. G13 owns durable application coordination and
  canonical Session recovery. No launcher is installed for the client.
- `harnesstui.mux` now includes G16's interactive shell and native terminal
  loop alongside the state, reducer, controller and shared conversation view.
  Its installed `loushang-mux attach` borrows an independently connected client;
  this is not a G15 launch owner.
- AppHost A0.5 and the G15 foreground launcher/client entrypoint remain missing.
  Existing `loushang` and `loushang-tui` remain Embedded routes.
- AppClient's legacy required surface has no resumable-Session listing operation.
  G17 adds the separate optional discovery contract, codec and profile checks;
  these are implemented-uncomposed, not an end-to-end Product discovery route.
  The Product catalog exists server-side, but AppService discovery views and
  a client picker remain implementation gaps.

The older named-mux proposal informs UI behavior, not current implementation
status. In particular its detachable lifetime cannot be applied to G14 pipes.

## Requirements

| ID | Observable acceptance condition |
| --- | --- |
| `G15-EXPLICIT` | installed explicit selection starts one child; omission leaves Embedded startup and imports unchanged |
| `G15-ADMISSION` | no shell, wire-supplied executable, ambient path rediscovery, unadmitted environment or factory crosses the launch boundary |
| `G15-LIFETIME` | startup cancel/failure and repeated close retain one process/connection cleanup owner; timeout never reports clean application shutdown |
| `G15-INTERACTION` | input, streamed replies, approval, interrupt, local window selection and independent drafts work through AppClient |
| `G15-MUX` | named mux selection, ordered members and attention markers are visible without creating a process per mux or window |
| `G15-RECOVERY` | cwd/home selection is explicit; relaunch restores stable mux/member/Session identities and new attachments, not active work |
| `G15-CAPABILITIES` | unavailable features are visibly rejected before effects, not dropped or converted into client file paths |
| `G15-EVIDENCE` | fake-terminal playback and installed native Linux/macOS/Windows scenarios prove the complete user path |

## Logical And Physical Context

Logical actors are the user, the trusted Product/OEM composition, the hosted
application, and the existing Session authority. The UI translates user intent
through AppClient; it does not obtain Session or process capabilities. The
Product admits configuration and executable material. Hosting receives only
the admitted process request and preparation capability, not an object graph.

Physical composition (edges mean constructs/binds, not imports):

```text
client Product command
  constructs optional AppHost launcher
    binds Hosting process lease to AppServer byte port/client
  constructs Harnesstui hosted shell with borrowed AppClient
    renders through generic TUI

complete child executable
  constructs G14 Coding composition and G13 application
    binds AppServer connection to AppService semantic port
      resolves canonical Product Sessions
```

No Python factory, Session, AppService or TUI object crosses the process edge.
The target validates its own admitted configuration once. cwd and home are
scope selectors, not two competing registries or permission to scan arbitrary
client paths.

## Candidate Discovery And Refinement

Candidate functions come from startup/exit, cold recovery, protocol failure,
window switching, approvals, scopes and the existing Hosting/G14 contracts.

| Candidate | Decision / primary owner | Collaborators | Explicit non-owners |
| --- | --- | --- | --- |
| executable/settings selection | keep in Product outer composition | admitted configuration and Product catalog | UI, AppServer, Hosting |
| launch and child ownership | keep as optional AppHost launcher | Hosting public process contract | UI, AppServer, AppService |
| process-IO to protocol-IO adaptation | merge into that outer launcher boundary | AppServer byte port and Hosting lease | AppServer must not import Hosting |
| framing, hello and RPC correlation | keep in AppServer | injected byte IO | launcher does not copy the protocol |
| window/input/view lifecycle | keep in Harnesstui hosted shell | existing mux controller and shared view | Session factory, process owner |
| layout, key decoding and terminal restoration | keep in TUI | presentation-ready values | mux identity and Product policy |
| Session recovery and durable assets | keep existing Product/Harness authority | G13 coordination | launcher, UI, transport |
| resumable Session listing | extend App Contract and the injected Product discovery port | AppService coordinates opaque results | UI and AppServer must not scan directories |

The component model therefore adds two responsibility units: the optional
launcher and the hosted shell. Existing Product composition and protocol
components absorb their own extensions; no generic manager or new package is
introduced. Byte bridging is an adapter within a boundary, not a sixth owner.

## Ports And Dependency Contract

The optional launcher consumes an immutable launch descriptor, an injected
Hosting Process Host/preparation port and explicit deadlines. It provides an
owned foreground client handle: borrowed AppClient access, raw child-exit
observation, bounded redacted diagnostics and idempotent close. Names here are
design roles; the exact implementation API is not claimed to exist.

The byte adapter reads/writes the exact owned ProcessLease pipes. Closing
protocol input requests G14 graceful EOF; it does not discard process ownership.
The launch owner retains the lease until wait/terminate/close has settled.
The complete executable request uses piped stdin/stdout and a captured bounded
stderr tail. Hosting's public preparation contract must verify the admitted
request before spawn; G15 does not claim H6 sealed execution or sandboxing for
an ordinary installed Python environment.

The bridge must respect Hosting's admitted per-read and per-write bounds.
One maximum App frame includes the four-byte frame header as well as its
payload. Either admit that complete size before launch or split the serialized
frame into bounded writes without releasing its writer ownership. Reads are
likewise clamped to the Hosting limit. This adaptation does not allocate an
unbounded intermediate buffer or reinterpret protocol messages.

The shell receives only AppClient, selected mux/scope values, supported action
facts and an exit-intent callback. It does not receive the owned client handle,
process lease, raw paths, settings manager or Product Session. Its UI close
releases its logical attachment; outer composition decides deployment exit.

Intended optional imports, not current package dependencies:

```text
Product client composition -> apphost.launcher + harnesstui hosted shell
apphost.launcher -> Hosting public contracts + AppServer client/framing
harnesstui hosted shell -> AppClient/protocol + shared Harnesstui + TUI

AppHost core -/-> optional launcher / Product / UI
AppServer -/-> Hosting / AppService / AppHost / Product / UI
Harnesstui -/-> Hosting / AppHost / Product / AppService
Hosting -/-> AppServer / AppService / AppHost / Product / UI
```

This is the parent-level approval candidate for the exact A0.5 edge only;
implementation must update the exact architecture gate, not allow an entire
package to import arbitrary siblings. Library facades stay lazy/default-dark.

### Bounded Session Discovery Extension

The picker needs an explicit typed `sessions/list` operation, not an indirect
filesystem read or an assumption that `list_muxes` lists resumable Sessions.
The request contains the admitted scope kind/fingerprint, a limit in 1..64,
and an optional opaque continuation. The response contains pathless identity,
bounded title, source scope and compatibility/availability facts, plus an
optional continuation and explicit completeness indication. It grants no
resume permission by itself; the Product revalidates the selected candidate
at open. Missing, stale and unavailable results remain distinct.

AppService consumes an injected narrow Product discovery port; AppServer only
validates/encodes the values. The server retains a bounded discovery snapshot,
not a new durable Session index. Continuations bind to the scope, snapshot
revision and deployment generation; expired snapshots fail explicitly rather
than restarting the scan invisibly. At most two scope snapshots per client
and 256 candidates per scope use the existing Product discovery ceiling.
An over-budget scan is visibly incomplete. This contract extension needs its
own codec, implementation and tests before the picker is advertised.

## Startup, Interaction And Settlement

1. Validate explicit selection and immutable launch material before terminal
   takeover. Publish a launch-attempt owner before starting any process.
2. Reserve/start the process through Hosting, install one reader and one
   bounded diagnostic owner, then wait for G14 ready hello. Process liveness
   does not imply recovery or protocol readiness.
3. Complete hello, select/create the requested mux using existing typed
   operations, attach via the snapshot barrier, then open the terminal shell.
4. UI polls while request tasks execute; it never awaits a long prompt inside
   the input/render loop. Control actions retain the protocol's reserved slots.
5. On exit, fence UI actions and cancel local request waiters without waiting
   for their remote turns to finish. Best-effort logical detach is bounded by
   the same close budget; failure does not skip closing protocol input. EOF
   then requests G14 application settlement. Settle cancelled local waiters
   and the connection reader before handing raw stdout draining to the owner.
   Exactly one reader drains at a time; keep stderr draining while awaiting
   the child so full pipes cannot obstruct shutdown.
6. At the graceful deadline, the launch owner requests termination and reaping
   through Hosting. Forced exit is a raw failure fact, not successful semantic
   close. Unsettled owners remain retryable cleanup debt.
7. Restore terminal state in an outer finally path even when shutdown fails.

The startup deadline includes cold Product imports and G13 recovery, separate
from the ready peer's hello deadline. Defaults are 30 seconds for complete
startup and 20 seconds for complete shutdown, with at most 10 seconds of that
shutdown budget used for graceful settlement. One absolute close deadline
bounds all phases; retry does not restart elapsed budgets. At expiry, report
cleanup debt and retain the exact outstanding task/owner rather than dropping
it or claiming the tree was reaped. Callers may explicitly grant a later retry
budget. A repeated in-flight close joins the same operation. There is no
fire-and-forget process or a second component that also calls terminate.

No failed or cancelled mutation is automatically resubmitted. A lost response
has an unknown outcome; retrieve a fresh authoritative view before offering a
new explicit user action. Refreshing a view must preserve unsubmitted drafts
by stable member identity, never position, and never revive stale authority.

## Presentation, Scope And Resource Contract

The hosted shell reuses the shared conversation view. Window selection is
local and must not wait for an RPC. Membership changes reattach at a fresh
barrier. Each member retains its own bounded draft and scroll state.

The hosted footer uses the existing status row plus one mux row: name,
1-based positions, active marker and one prioritized background marker
(attention, unread output, running). Narrow terminals truncate by display
width, never wrap the row or render untrusted terminal control sequences.
Contextual Tab is used only after modal/completion/composer handling; prefix
navigation remains available. Embedded rendering/key behavior is unchanged.

The selector displays cwd versus user-home and the chosen execution workspace.
A global Session's historic cwd is descriptive, not executable authority.
Legacy transcripts without G14 identity metadata are not silently adopted.
Drafts are limited to 64 KiB UTF-8 per member and 1 MiB per shell; the UI action
queue is limited to 64 entries. Full queues or draft budgets reject further
input visibly rather than discarding it. Server member/mailbox/wire bounds
remain independent limits; client admission cannot enlarge them.

Configuration and machine resources retain their existing owners. Client
drafts are private bounded run-local state. Submitted content belongs to the
canonical Session authority. Logs/traces use the existing observability sink
and retention policy; protocol stdout carries no diagnostics. No new Session
directory, global cache, registry, or service record is introduced by the UI.

G14's text/control contract does not carry image bytes. The G15 profile must
advertise only supported actions and reject unsupported paste/upload before
reading or persisting image content. A later image capability needs pathless
validated transfer and Session Blob promotion; neither AppServer nor the UI
becomes a durable image store. Do not pass a parent-local filename to a child
as an apparent supported attachment.

## Design Review And Acceptance Gate

The following is a three-perspective review by one reviewer, not an
independent-agent claim. Findings were resolved before accepting this design:

1. Architecture / authority (`G15-R1`): the proposed scope picker implied a
   Session-list API absent from AppClient. Resolved with an explicitly missing,
   bounded pathless discovery extension owned by Product/AppService, with
   generation-bound cursors and no UI directory access. G15 cannot claim that
   UI capability from the existing remote controller tests.
2. Lifecycle / concurrency (`G15-R2`): waiting for long requests before EOF can
   prevent shutdown; independently reset phase timeouts can exceed the exit
   budget. Resolved with local waiter cancellation, bounded optional detach,
   EOF regardless of detach failure, single-reader drain transfer and one
   absolute close deadline with retained cleanup debt. Native process tests
   must prove these orderings, not count parent kill as graceful exit.
3. Contract / user evidence (`G15-R3`): a maximum protocol payload plus header
   exceeds the default Hosting write bound, and vaguely bounded UI state is
   not an acceptance contract. Resolved with explicit frame-overhead adaptation,
   per-member/aggregate draft and queue limits, unsupported-image rejection,
   and separate installed/terminal/three-platform requirements. Existing
   Embedded behavior and G14 EOF semantics are retained.

Re-review: ownership is single-valued; no reverse package imports, implicit
daemon, persistence duplication, connection-driven Product discovery, or
unimplemented feature claim remains in the design. Acceptance approves this
Target only; the implementation gaps remain explicit in the inventory.

Design-only verification: the unchanged G11--G14 baseline passed 211 tests,
Ruff and mypy (39 files). The G15/G14 design and G9 closure selection passed
16 tests; `make check-architecture-docs` passed its five cases. These results
verify this design delivery and retained baseline, not future G15 runtime.

The design/inventory test proves only Current/Target separation, declared
ownership, source paths and unchanged script routing. It does not prove a
launcher or terminal shell works. Runtime acceptance additionally requires:

- startup failure before/after child publication, cancellation during recovery,
  repeated close, unresponsive child and terminal restoration;
- concurrent submit/approval/interrupt, attention markers, drafts across
  window switches and membership refresh, contextual keys and narrow widths;
- installed help/start, normal exit and recovery for cwd and home; and
- native Linux/macOS/Windows evidence with no skipped required platform cases.

## Handoff To G16

G16 may reuse the UI and AppClient boundary but cannot reuse the rule that
connection EOF closes the application. Its design must specify authenticated
local admission, a separate connection generation, connection-bound attachment
authority, execution owned independently of a client await, approval loss,
reconnect snapshot barriers and bounded aggregate shutdown. A live detached
turn is not a persisted turn; G13 process recovery still restores durable
state without replaying active execution.

An independently running foreground server or external supervisor can own that
lifetime. G15's attached process lease is not a daemon owner, and G16 must not
introduce `hosting.service` merely by renaming the launcher. The two profiles
remain explicit, distinguishable and independently tested.
