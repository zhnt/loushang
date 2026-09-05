# Harnesstui Named Mux And Daemon Attach

[Architecture](../README.md) · [Drafts](README.md) ·
[Future Architecture v3](future-loushang-architecture-v3.md) ·
[Application Service Refactor](application-service-refactor.md) ·
[AppService Hosted Boundary](appservice-embedded-tui-hosted-boundary-plan.md)

## Status

- ID: `TUI-DP-NAMED-MUX-ATTACH`
- Kind: architecture and delivery design
- Scope: TUI / Harnesstui / AppService / AppServer / AppHost / Hosting
- Parent: Loushang application architecture
- Proposed prerequisites: `APPHOST-DP-TOP-LEVEL` and the Hosting hosted-
  application support boundary
- Authority: normative target proposal
- Design status: proposed
- Review status: re-review accepted as an aligned proposal; implementation
  prerequisites remain gated
- Implementation status: not-started
- Owner: Loushang application and presentation architecture
- Current evidence:
  - `src/loushang/tui/ui_parts/widgets/tabs.py`
  - `src/loushang/tui/ui_parts/widgets/tab_group.py`
  - `src/loushang/tui/input.py`
  - `src/loushang/tui/keybindings.py`
  - `src/loushang/harnesstui/conversation/`
  - `src/loushang/harnesstui/testing/`
  - `src/loushang/harness/session/facade.py`
  - `src/loushang/harness/session/operations.py`

This draft defines a small terminal-multiplexer-style hosted profile for
Loushang. It adds multiple named attach targets, multiple concurrently live
Sessions, a long-lived AppHost profile, and a Harnesstui window shell. It
does not authorize implementation by itself.

The design is subordinate to the existing AppService drafts and consumes the
still-proposed AppHost and Hosting baseline as prerequisites, not as Current
implementation. In particular, AppService remains outside Harness Capability
and Plugin composition, AppHost is the only whole-process composition owner,
the default embedded TUI remains available, and attach never migrates a
mutable embedded Session into a daemon.

## Decision Summary

The first hosted mux profile uses:

- one admitted AppHost target process per user/configuration endpoint;
- one local AppServer endpoint and one AppService coordinator in that process;
- one allowed Product ID per endpoint in v1, recorded and validated on every
  Session while each Session retains an independent scoped Product Runtime;
- multiple named `MuxSpace` values inside AppService;
- an ordered set of hosted Session members in each MuxSpace;
- one Harnesstui Hosted Mux Profile window per visible MuxSpace member;
- a persistent two-row footer whose bottom row is the mux window selector;
- generic footer, window-selector, and deck rendering from `loushang.tui`;
- a local IPC connection from AppClient through AppServer to AppService;
- one controller attachment per MuxSpace in v1; and
- explicit detach semantics that introduce no implicit Session or turn
  cancellation.

Conceptually:

```text
one admitted AppHost target process
  -> one AppServer local endpoint
       -> one AppService coordinator
       -> MuxSpace "dev"
            -> member 1 -> hosted Session A
            -> member 2 -> hosted Session B
       -> MuxSpace "research"
            -> member 1 -> hosted Session C

Harnesstui attachment to "dev"
  -> local Window 1 -> member 1
  -> local Window 2 -> member 2

zero or one outer process authority
  -> external supervisor, or
  -> AppHost daemon control
       -> future Hosting Service Instance Controller
```

A name identifies a MuxSpace, not a daemon or AppHost process. Creating ten
named MuxSpaces does not create ten peer daemon processes.

## Goals

The first version provides:

1. several independent hosted Sessions running concurrently;
2. a named attach target such as `dev`, `research`, or `ops`;
3. a small tabbed Harnesstui Hosted Mux Profile over those Sessions;
4. client detach on graceful exit, terminal close, or SSH loss;
5. reattach to a still-running AppHost with a membership revision and a valid
   snapshot/cursor pair for each visible Session;
6. direct next-window navigation when Tab is not owned by another UI context;
7. a persistent tmux-like bottom row showing MuxSpace name, 1-based window
   positions, active window, and compact background attention state;
8. explicit create, list, attach, detach, and close operations; and
9. package boundaries that preserve `loushang.tui` as an independent terminal
   GUI toolkit and preserve Harnesstui Embedded Profile behavior.

## Non-Goals

The first version does not provide:

- panes or split-screen layout;
- simultaneous duplicate top tabs and bottom mux navigation;
- terminal emulation or general shell multiplexing;
- a second Harnesstui Product or a copied presentation implementation;
- mutable Session transfer from the embedded profile;
- daemon crash or machine-reboot recovery;
- automatic merge between embedded and hosted transcripts;
- several simultaneous writers to one MuxSpace;
- controller reassignment for an already-presented approval;
- a multi-user ACL or cloud tenancy model;
- WebSocket, public network, or relay exposure;
- hot upgrade or hot unload of the hosted implementation;
- cross-Product MuxSpaces or more than one admitted Product ID per v1 endpoint;
- one daemon per window, Session, or MuxSpace; or
- an independently invented application package/bootstrap or plugin host;
- conversion of AppService into a Harness Capability or ordinary Harness
  Plugin.

## Boundary Vocabulary

| Name | Meaning | Owner |
| --- | --- | --- |
| Hosted Session | A Product-bound Session created in AppService from the beginning | Product binding and AppService registry |
| MuxSpace | A named attach target containing ordered hosted Session references | AppService |
| MuxSpaceMember | A service-side ordered reference to one hosted Session | AppService |
| Window | A Harnesstui presentation of one member | Harnesstui |
| Tab | Generic visual selector for a window | TUI |
| Attachment | One initialized client subscription to a MuxSpace | AppService |
| Controller | The attachment generation allowed to mutate Sessions | AppService |
| AppServer | Protocol edge: listeners, connections, authentication, framing, and transport backpressure | AppServer |
| AppHost | The unique cross-Product process composition and lifecycle owner | AppHost |
| Service Instance Controller | Candidate start, stop, probe, process-record, and platform service mechanics | Future Hosting subsystem |
| Embedded Profile | Existing in-process Harnesstui startup profile | Harnesstui/Product composition |
| Hosted Mux Profile | Optional Harnesstui profile using AppClient and named MuxSpaces | Harnesstui/AppHost profile composition |

The terms Session, member, and window are deliberately different. A Session is
runtime state, a member is AppHost-target-lifetime application coordination,
and a window is client presentation state. AppServer connection state is also
different from an AppService logical Attachment.

## Current And Target Profiles

### Harnesstui Embedded Profile

```text
Harnesstui
  -> Product conversation binding
  -> embedded Product Session
  -> Harness
```

The foreground process owns the Session. Closing that process ends the mutable
runtime. No AppClient or service process is required.

### Harnesstui Hosted Mux Profile

```text
Harnesstui Hosted Mux Profile
  -> AppClient
  -> local IPC transport
  -> AppServer
  -> AppService
  -> Session-scoped Product Runtime binding
  -> Harness

AppHost target process
  -> constructs AppService
  -> injects AppService into AppServer
  -> resolves the admitted Product factory
  -> retains process resources and owns ordered shutdown
```

AppHost owns the whole-process lifetime; AppService owns the hosted Session and
MuxSpace registries; AppServer owns only the protocol edge. Closing
Harnesstui closes only the logical attachment, subject to authoritative
interaction cleanup.

These are two startup profiles of one Harnesstui presentation product, not two
Harnesstui products:

| Property | Embedded Profile | Hosted Mux Profile |
| --- | --- | --- |
| Session placement | foreground process | AppHost target process |
| client binding | embedded Product conversation adapter | AppClient |
| initial surface | one Session | named MuxSpace with several windows |
| footer | existing single application-status row | application-status row plus persistent mux window row |
| exit meaning | end the local application runtime | detach the client |
| reconnect | not required | attach by MuxSpace name |
| daemon/service owner | none | external supervisor or accepted Hosting service owner |

Both profiles reuse Harnesstui conversation projection, rendering models,
input state, interaction surfaces, and semantic actions. Only their outer
binding and mux shell differ. The first version does not migrate a live
Session between them.

“Native TUI” describes the terminal presentation technology and applies to
both profiles. It must not be used as the opposite of “hosted”; the normative
profile names are **Embedded Profile** and **Hosted Mux Profile**.

## Ownership And Dependency Direction

The required source direction is:

```text
loushang.tui
  <- harnesstui core presentation
       <- harnesstui embedded adapter
       <- harnesstui hosted adapter / mux shell
            -> appserver.client / AppClient contract

AppHost hosted runtime
  -> constructs appserver.service / AppService
  -> injects it into appserver.server / AppServer
  -> resolves one Session-scoped Product Runtime binding per Session
       -> public Product/Harness contracts

AppHost daemon control
  -> future hosting.service Service Instance Controller
       -> launches/probes/stops the complete AppHost target

Harness   -X-> AppHost / AppServer / AppService / Harnesstui / TUI
TUI       -X-> Harnesstui / AppService / AppServer / AppHost / Hosting / Harness
AppService -X-> Harnesstui / TUI / Hosting / concrete Product package
AppServer -X-> Hosting / Harnesstui / TUI / concrete Product package
Hosting   -X-> AppHost / AppServer / AppService / Harnesstui / TUI / Product
```

AppHost is the single deliberate outer composition root and may import the
participating sibling packages to supply admitted factories. It does not move
Product behavior into mux, AppServer, Hosting, or TUI and does not create a
second Plugin or Capability graph.

### Package responsibility

| Package | Owns | Must not own |
| --- | --- | --- |
| `loushang.tui` | terminal runtime, input decoding, generic Tabs/TabGroup, generic window deck, focus and rendering | Session, AppClient, MuxSpace, AppHost/Hosting, Product |
| `loushang.harnesstui` core | shared conversation projection, rendering model, input state, interaction surfaces, semantic UI actions | Session runtime, transport, service process, AppService |
| `loushang.harnesstui` embedded adapter | direct binding of the existing in-process Product conversation port | AppClient, mux, AppHost/Hosting, AppServer |
| `loushang.harnesstui` hosted adapter and mux shell | AppClient binding, window mapping, local drafts/scroll/focus/unread state, mux event reduction | Session runtime, socket, service process, protocol server |
| `loushang.appserver.protocol/client` | typed App Contract values/codecs and AppClient | Product implementation, terminal widgets, process control |
| `loushang.appserver.server` | listener, transport authentication, connections, framing, correlation, and bounded transport queues | Product routing, logical detach, MuxSpace registry, OS daemon mechanics |
| `loushang.appserver.service` / AppService | hosted Session and MuxSpace registries, logical attachments, controller generations, snapshots/cursors, delivery and idempotency | transport connection objects, terminal widgets, Hosting, concrete Product discovery |
| `loushang.apphost` | Product/OEM admission, Product catalog/routing, process composition, Session-scoped Product binding ownership, ordered shutdown, outer launch/profile adapters | App protocol, transport framing, Session semantics, OS process mechanism |
| future `loushang.hosting.service` | service records, process discovery, locks, start/stop/probe/readiness, and platform process mechanics | App Contract, listener, MuxSpace, Product/Session semantics, install/update policy |
| `loushang.harness` | existing Product-neutral Session/runtime mechanisms | mux windows, named attach, IPC, AppHost/Hosting service control |
| `loushang.coding` | only its Product behavior when explicitly selected | mux, AppHost/Hosting service control, generic CLI grammar, named attach |

There is no separately owned daemon package and no second hosted composition
root in this target. The mux feature should require no `loushang.coding`
changes and no Harness changes unless implementation proves a genuinely
missing public Session contract. Such a missing contract is proposed and
landed independently through the Harness lane.

## Keeping TUI An Independent Terminal GUI

`loushang.tui` exposes generic values and behavior only. Existing `Tabs` and
`TabGroup` remain reusable, including as implementation material for a bottom
window selector. Hosted Mux renders one navigation surface in the bottom
footer; it does not also render a duplicate top tab strip. A new deck or footer
abstraction is added only if the mux application cannot compose the current
primitives without duplicating generic layout behavior.

A TUI-facing model may look conceptually like:

```python
@dataclass(frozen=True)
class WindowItem:
    id: str
    label: str
    position: int
    badge: str | None
    disabled: bool = False


class WindowDeck(Protocol):
    active_id: str
    items: Sequence[WindowItem]
```

These values do not contain `Session`, `MuxSpace`, `AppClient`, socket,
AppHost, Hosting, Product, or Harness objects.

`position` is a 1-based presentation value supplied by Harnesstui. `badge` is
an already-projected display token such as `!`, `+`, or `~`; TUI does not know
that those tokens originated from approval, unread, or running Session state.
The stable identity remains `id`, never the displayed position.

The same `loushang.tui` package must remain sufficient to build an unrelated
terminal application such as a file browser, settings UI, or log viewer. Its
tests use generic view models and fake input, not hosted Session fixtures.

## One Harnesstui, Two Profile Adapters

Harnesstui retains one shared presentation core and two thin profile adapters:

```text
harnesstui core presentation
  -> conversation projection and reducers
  -> message/interaction view models
  -> composer/input state
  -> shared semantic UI actions

harnesstui embedded adapter
  -> existing in-process Product conversation binding

harnesstui hosted adapter
  -> AppClient
  -> hosted-only mux shell
       -> named attachment projection
       -> member/window mapping
       -> active window and unread state
```

The shared core must not take an AppClient dependency merely to make the
hosted profile possible. The two adapters normalize their input into the same
presentation actions and view data wherever semantics are identical. Hosted-
only attach, reconnect, member ordering, and controller-generation values stop
at the hosted adapter or mux shell.

The default Harnesstui entrypoint selects Embedded Profile exactly as it does
before this feature. Only an explicit mux/attach command selects Hosted Mux
Profile. This preserves both behavioral compatibility and a clean future path
for another GUI to consume AppClient without depending on Harnesstui.

## Harnesstui Hosted Mux Application

The hosted mux shell owns the application-specific presentation model:

```python
@dataclass
class HarnessWindowState:
    window_id: str
    member_id: str
    session_id: str
    title: str
    unread: bool
    draft: str
    scroll_anchor: object | None
```

Harnesstui maps:

```text
App snapshot/event
  -> mux reducer
  -> HarnessWindowState
  -> generic TUI WindowItem and content renderable

TUI input
  -> semantic UI action
  -> mux controller
  -> local state change or AppClient command
```

Local actions do not cross the App Contract:

- select next or previous window;
- change focus;
- scroll;
- edit an unsent draft;
- open help or another local surface; and
- render the tab strip.

Server-backed actions do cross it:

- create or close a MuxSpace member;
- submit input to a hosted Session;
- interrupt a turn;
- answer an interaction;
- rename or reorder a member when supported; and
- close a hosted Session or the whole MuxSpace.

The Harnesstui hosted adapter receives an AppClient-compatible port at
construction. It does not open a socket in a widget or call AppService from
`render()`. The embedded adapter does not construct AppClient or AppService.

## AppService Mux Model

AppService gains an application-coordination model, not a TUI model:

```python
@dataclass(frozen=True)
class MuxSpace:
    mux_space_id: str
    name: str
    members: tuple[MuxSpaceMember, ...]
    revision: int


@dataclass(frozen=True)
class MuxSpaceMember:
    member_id: str
    session_id: str
    title: str
    position: int
```

Required invariants:

1. `mux_space_id`, `member_id`, and `session_id` are different identity
   domains.
2. A name is unique within one authenticated AppServer endpoint.
3. A name is a selector, never a filesystem or socket path.
4. Member order is AppService state so a new attachment reconstructs the same
   space.
5. Active window, scroll position, focus, and drafts are client presentation
   state and are not AppService state.
6. One member references exactly one hosted Session in v1.
7. One hosted Session belongs to at most one MuxSpace in v1.
8. Removing a member and closing its Session are explicit, separately named
   semantics even if the first UI normally performs them together.
9. A named MuxSpace remains until explicitly closed while its AppHost target
   process is alive; v1 has no implicit idle unload.
10. Closing an attachment never closes its MuxSpace or Sessions.
11. Every Session new/open/resume operation carries the required `product_id`
    from the generic Session Identity Envelope.
12. A v1 AppServer endpoint admits exactly one Product ID, but AppHost creates
    and releases one independent scoped Product Runtime binding per Session;
    the constraint never means one shared mutable Product Runtime singleton.
13. A MuxSpace cannot contain a Session whose Product identity is outside the
    endpoint admission rule. Cross-Product MuxSpaces remain deferred.

The selector name should use a conservative cross-platform grammar such as
`[A-Za-z0-9][A-Za-z0-9._-]{0,63}`. A future independent display title may
accept broader Unicode without changing selector identity.

## App Contract Additions

The mux slice extends, rather than replaces, the Session operations in the
AppService hosted-boundary draft.

Minimum requests:

```text
mux/create
mux/list
mux/read
mux/attach
mux/detach
mux/close
mux/member/open
mux/member/close

session/open(product_id, ...)
session/resume(product_id, session_identity_envelope, ...)
session/snapshot
turn/start
turn/steer
turn/followUp
turn/interrupt
interaction/respond
```

Rename and reorder may be included only if the first UI exposes them:

```text
mux/rename
mux/member/rename
mux/member/move
```

`mux/attach` establishes one client-visible initialization barrier. It does
not claim that independent Session snapshots represent one global instant.
The result contains:

- one serialized MuxSpace identity, name, membership revision, and ordered
  member set;
- one authoritative client-safe snapshot and delivery cursor per visible
  hosted Session;
- an `attachmentId` plus controller mode and generation; and
- ordered buffered events strictly after each corresponding member cursor.

AppService initializes the attachment as follows:

1. serialize the MuxSpace membership revision and visible member set;
2. create the logical attachment generation and begin bounded buffering for
   every member stream before exposing any snapshot;
3. obtain one authoritative snapshot/cursor pair from every visible Session;
4. publish the complete initial attachment only after all pairs are valid for
   the selected membership revision; and
5. replay each member stream strictly after its own cursor.

A membership mutation during initialization either waits behind the selected
revision or causes a typed retry; it cannot produce a partly old and partly new
member list. If a retained member stream has a gap, AppService returns
`SnapshotRequired` and establishes a new snapshot/cursor pair for that member
or restarts the complete initialization barrier according to the typed
contract. Harnesstui never guesses across an event gap.

## Named Attach And CLI

The canonical grammar should remain explicit:

```text
loushang mux new --name dev
loushang mux new --name dev --detached
loushang mux attach --target dev
loushang mux list
loushang mux close --target dev
```

Short Product-level conveniences may be:

```text
loushang -t dev
  ensure the local AppHost service exists, then create-or-attach "dev"

loushang -d --name dev
  ensure the local AppHost service exists and ensure "dev" exists, without attaching
```

The canonical subcommands define behavior. The aliases are accepted only after
the top-level CLI owner confirms they do not conflict with positional prompts
or the existing `--tui` option. They are not added to the shared Harness CLI
profile.

`mux attach --target dev` attaches only to an existing name and returns
`NotFound` otherwise. The `-t dev` convenience has create-or-attach semantics,
similar to an idempotent local workspace entry command.

`mux list` distinguishes at least:

```text
dev        3 members    attached/running
research   2 members    detached/idle
ops        1 member     detached/running
```

## Multiple Attachments

One AppHost target supports:

- several different names;
- several client connections;
- concurrent execution across Sessions; and
- simultaneous attachments to different MuxSpaces.

V1 permits only one controller attachment per MuxSpace. A second ordinary
attach to the same name returns `AlreadyAttached`. Read-only observers and
explicit takeover are independently gated later features.

The controller lease is connection-generation fenced. When its connection is
lost, AppService releases that generation. A new attachment cannot answer an
interaction issued to the old generation.

This keeps input, interrupt, and approval ownership deterministic without
introducing collaborative editing.

AppServer connection objects retain byte buffers, framing, transport
authentication, close state, and transport queue pressure. AppService retains
logical attachments, controller generations, MuxSpace mailboxes, member
cursors, idempotency, and disconnect policy. Reconnection creates both a new
transport connection and a new logical attachment generation; neither layer
revives a transport future from the prior connection.

## Input And Window Switching

The default mux key set is intentionally small:

```text
Tab             next window when the current UI context does not own Tab
Ctrl+B n        next window
Ctrl+B p        previous window
Ctrl+B c        create member/window
Ctrl+B d        detach
Ctrl+B 1..9     select member/window
```

Tab is not globally rebound in `loushang.tui`. It remains owned by the most
specific active UI context in this order:

1. modal, dialog, form, grid, or focused surface;
2. an open completion menu;
3. a composer with text where Tab requests or applies completion;
4. the mux shell, only when the composer is empty and no higher-priority
   context consumed the event.

The prefix bindings remain available even when Tab belongs to a nested
component. Enhanced-terminal Ctrl+Tab detection may be optional but is not a
portable baseline.

## Hosted Mux Two-Row Footer

The Harnesstui Hosted Mux Profile always reserves two bottom rows, including
when the MuxSpace contains only one member:

```text
running · model example · waiting 12s
[dev] 1:plan 2:test* 3:docs! 4:research+
```

The penultimate row is the existing application-status surface for the active
window. The bottommost row is the persistent mux navigation surface. It
answers three different questions without opening another view:

1. `[dev]`: which named MuxSpace is attached;
2. `2:test*`: which ordered window is active; and
3. `3:docs!`: which background window needs attention.

The Embedded Profile preserves its existing single-row footer. It does not
reserve an empty mux row and does not import the hosted footer model.

### Position And Shortcut Rules

Displayed window positions are 1-based and match direct prefix shortcuts:

```text
Ctrl+B 1   select position 1
Ctrl+B 2   select position 2
...
Ctrl+B 9   select position 9
```

Positions describe the current ordered membership projection, not durable
identity. Moving or removing a member may renumber later windows; stable
commands and events continue to use `member_id`. Positions above 9 remain
visible and reachable through next/previous navigation, but v1 does not map
position 10 specially to `Ctrl+B 0`.

### Marker Rules

The ASCII marker vocabulary is deliberately small and does not depend on
color:

| Marker | Meaning |
| --- | --- |
| `*` | active window |
| `!` | inactive window requires user action, such as Approval or Question |
| `+` | inactive window has unread durable output |
| `~` | inactive window is running without higher-priority attention |
| none | inactive window is idle and has no unread output |

For the active window, `*` is the only bottom-row marker; its running,
interaction, or failure detail appears in the application-status row above.
For an inactive window, the single displayed marker follows priority
`!` > `+` > `~` > none. This avoids ambiguous combinations such as `*!` while
retaining textual accessibility. Color or style may reinforce a marker but
must never be its only representation.

Window titles and MuxSpace names are presentation text derived from
authoritative identifiers. Harnesstui removes control characters and newlines
before constructing the generic footer model; TUI applies display-width-aware
truncation and must not interpret embedded terminal escape sequences.

### Narrow-Terminal Degradation

The mux row is always exactly one terminal row and never wraps into a third
footer row. Width allocation follows this order:

1. retain a truncated `[MuxSpace]` selector;
2. retain the complete active position and its truncated title plus `*`;
3. retain the nearest previous and next windows while space permits;
4. truncate inactive titles before removing whole inactive entries; and
5. summarize omitted entries with `… +N`.

These rules apply at or above the Harnesstui shell's admitted minimum terminal
width. Below that width, the whole application uses its existing terminal-too-
small fallback rather than claiming that both required identities fit.

For example:

```text
[dev] … 2:test 3:docs* 4:ops … +5
```

Selection changes update the active marker and content locally without waiting
for an AppService round trip. Membership and background status changes arrive
through the existing AppClient projection. `loushang.tui` owns generic two-row
footer layout, width measurement, truncation, and rendering; Harnesstui owns
MuxSpace/member labels, positions, marker projection, and active-window state.

## AppHost, AppServer, AppService, And Daemon Control

The complete AppHost target is the daemon/service target. AppServer is not a
process composition root:

```text
AppHost target process
  -> constructs AppService
  -> injects AppService into AppServer
  -> binds the admitted Product/OEM profile
  -> owns scoped Product Runtime handles
  -> retains one process-level RuntimeResourceOwner
  -> owns graceful shutdown and ordered release

AppServer protocol edge
  -> owns listener, connections, authentication, framing, and transport queues
  -> forwards admitted typed operations to AppService

AppService coordinator
  -> owns MuxSpace, Session, logical attachment, command, snapshot, and event rules

AppHost daemon control
  -> external supervisor, or
  -> future Hosting Service Instance Controller
       -> starts, probes, stops, and reaps one opaque AppHost target process
```

The future Hosting Service Instance Controller may own:

- serialized service lifecycle operations and an instance epoch;
- exact executable/process identity and stale-record fencing;
- start, stop, restart, inspect, reconcile, readiness, and bounded diagnostic
  mechanics;
- PID/lock or equivalent service records under the admitted platform state
  root; and
- platform-specific detached process termination and reaping.

It does not own listener selection, authentication, App Contract framing,
MuxSpace or Session registries, Product recovery, logs/trace retention, or
application install/update policy. A service record is discovery evidence, not
authority over a live process; endpoint identity plus a readiness handshake
must fence stale records.

`hosting.service` remains a proposed candidate requiring its own requirements,
context, component discovery, acceptance, and implementation slices. An
authoritative external supervisor such as systemd, launchd, Windows SCM, or a
container runtime bypasses it and launches the same foreground AppHost target.
There is no separately owned daemon package.

The first process-survival slice targets Unix, covering Linux and macOS with a
local Unix socket owned by AppServer and an AppHost target detached or
externally supervised independently of the invoking terminal. Windows requires
an independently tested lifecycle and local transport provider, such as named
pipes or an admitted loopback endpoint, and must not be claimed merely because
the TUI itself runs on Windows.

## Disconnect, SSH Loss, And Reattach

The required disconnect sequence is:

```text
SSH or terminal closes
  -> Harnesstui process exits
  -> AppServer connection reaches EOF and closes transport-local state
  -> AppService applies logical disconnect policy
  -> AppService removes Attachment and releases its controller generation
  -> no implicit Session close, turn interrupt, or queue clear is introduced
  -> AppHost target remains alive

new SSH login
  -> Harnesstui opens a new connection
  -> initialize
  -> mux/attach by name
  -> membership revision plus one snapshot/cursor pair per member
  -> publish after the attach barrier completes
  -> ordered member events after their corresponding cursors
```

Transport connection cleanup must not itself call Session close, turn
interrupt, queue clear, or MuxSpace close. Logical attachment cleanup occurs
once in AppService, not independently in AppServer.

Approval cleanup follows the existing AppService interaction contract:

- controller disconnect closes its presentation lease;
- the authoritative Approval owner applies its existing cleanup/fallback
  behavior;
- settling or failing an interaction after lease loss may cause its affected
  turn to finish or fail;
- v1 does not transfer an already-presented approval to a new controller; and
- a reattached client receives current authoritative Session state, not a
  resurrected transport future.

The precise guarantee is therefore: unrelated Sessions and turns continue,
and detach introduces no implicit interrupt. It is not an unconditional
promise that every active turn survives every controller disconnect. This
prevents a blocking interaction from being stranded while preserving the
running Session whenever its authoritative lifecycle permits continuation.

## Persistence And Failure Guarantees

V1 guarantees client-loss continuity only:

| Event | V1 guarantee |
| --- | --- |
| graceful detach | Sessions continue |
| terminal close | Sessions continue |
| SSH/network loss | Sessions continue once the local TUI connection closes |
| new attach while AppHost lives | fresh attach barrier and continued control |
| AppHost graceful stop | hosted Sessions close through ordered Product policy |
| AppHost/daemon crash | no live-runtime recovery guarantee |
| machine reboot | no live-runtime recovery guarantee |

MuxSpace metadata may remain process-local in the first slice. Persisting names
or layout across AppHost restart does not imply that active turns, tools,
approvals, or mutable Session runtimes have been restored. Restart recovery
requires a separate durable-runtime contract.

## Runtime Resource Ownership

Every machine resource has one exact owner and bounded lifetime:

| Resource | Owner | Placement / lifetime |
| --- | --- | --- |
| platform roots and run-lease primitive | Foundation | one immutable admitted `PlatformPaths` at each process composition root |
| application-run artifacts and inventory | Harness `RuntimeResourceOwner` | AppHost retains exactly one owner for the target process and releases it in shutdown order |
| service record and PID/lock metadata | future Hosting Service Instance Controller | platform state root; exact service-instance lifetime |
| listener/socket/pipe and transport scratch | AppServer | `PlatformPaths.runtime` and operation-scoped temporary storage; AppServer lifetime |
| MuxSpace and live Session registry | AppService | process-local in v1; AppHost target lifetime |
| Session transcript | Product-selected canonical Session persistence owner | `$LOUSHANG_HOME/data/sessions` writable default |
| Session Blob | Harness Session Blob owner | `$LOUSHANG_HOME/data/session-assets/<session-id>` |
| clipboard/image capture or upload | active presentation adapter | TUI/GUI/WebUI captures bytes; AppHost, AppServer, and Hosting are not image stores |
| unsubmitted prompt/image draft | Harnesstui input-router draft owner | bounded private client/run-local state; remove on submit, cancel, or disposal |
| submitted image bytes | Harness Session Blob authority | validate and promote before a pathless durable reference enters the transcript |
| logs/traces/diagnostics | producing observability owner | bounded-retention `PlatformPaths.state` subdirectory; not Session content or Hosting policy |
| atomic temporary files | exact creating operation | `PlatformPaths.temporary`; exact operation/process lifetime |

Leaf components receive admitted paths or narrow resource handles. They do not
reread environment variables, infer cwd/home, or treat a stale service record
as proof that a live process owns the endpoint.

## AppHost Graceful Shutdown

AppHost owns one bounded, idempotent shutdown state machine for foreground,
externally supervised, and library-managed profiles:

1. mark the process stopping and reject new bootstrap, Product resolution, and
   profile activation;
2. tell AppServer to stop accepting connections and new request admission;
3. freeze AppServer reads and report connection state without deciding logical
   detach;
4. tell AppService to reject new Sessions, perform the sole logical detach,
   settle admitted work/interactions by explicit Product policy, close logical
   attachments, and release every Session-scoped Product binding through its
   idempotent close port;
5. release all remaining Product Runtime handles and presentation-profile
   leases;
6. drain or abort AppServer writers within the remaining deadline, then close
   transports, listener, and connection records;
7. close the process's one `RuntimeResourceOwner`; and
8. publish stopped readiness and let the foreground target exit.

Repeated stop requests join the same operation. Failures are recorded but do
not skip reachable cleanup phases, and one monotonic deadline bounds the whole
sequence. Only after the deadline may the outer Hosting owner or supervisor
terminate, kill, and reap the exact owned process tree. Forced termination
reports process facts; it cannot claim successful Session closure.

## Optional Profile And Plugin Delivery

### V1 delivery decision

V1 is an in-repository, opt-in, first-party AppHost Hosted Mux Profile. It uses
the canonical Product/OEM admission path and does not introduce a parallel
application-level plugin host, standalone application-package bootstrap, or
daemon package.

The following are not ordinary Harness Plugin contributions:

- AppHost process composition and shutdown;
- AppServer listener, authentication, framing, and admission invariants;
- AppService attachment, controller, idempotency, snapshot, and delivery
  invariants; and
- Hosting service-instance authority.

The current Harness Plugin lifecycle exists inside admitted Product/Harness
runtime scopes and cannot bootstrap or replace their outer host. AppService is
therefore not a Capability provider, graph node, or replaceable Harness Plugin
surface.

### Later optional distribution

A later distribution may be optional or separately installable only through
the canonical Product/OEM Plugin and Package governance path. It may contribute
an admitted immutable Product factory, hosted integration factory,
Host/Presentation Profile, and launch descriptor through the established
manifest, trust, enablement, activation, and retirement pipeline.

That later packaging changes distribution, not runtime authority:

```text
canonical Product/OEM admission
  -> immutable Product and hosted-profile factories
  -> AppHost composition
       -> AppServer + AppService + Harnesstui Hosted Mux Profile

built-in/OEM daemon control
  -> external supervisor, or
  -> separately accepted Hosting Service Instance Controller
```

Daemon control remains built-in/OEM authority and is not supplied as an
ordinary Harness Plugin contribution. Hot replacement remains unsupported;
updates require the owning AppHost process to drain and restart under explicit
service policy. Trust, update, disable, and uninstall rules belong to the
canonical Product/OEM governance design and are not redefined here.

## Suggested Source Shape

The target may use:

```text
src/loushang/appserver/
  protocol/
  ports.py
  client.py
  service.py
  attachment.py
  server.py
  connection.py
  mux.py
  transports/
    local.py

src/loushang/apphost/
  contracts.py
  catalog.py
  router.py
  runtime.py
  hosted/
    binding.py
    profile.py
  launch/
    target.py
    daemon_control.py

src/loushang/harnesstui/
  conversation/            # shared Embedded/Hosted presentation core
  embedded/                # existing in-process binding adapter
  hosted/                  # AppClient adapter
  mux/
    app.py
    state.py
    reducer.py
    controller.py
    projection.py
    footer.py
    keybindings.py

src/loushang/tui/
  ui_parts/widgets/
    window_deck.py         # only if current generic composition is insufficient
    window_footer.py       # generic footer only; no MuxSpace/Session types

src/loushang/hosting/
  service/                 # reserved until separately accepted
```

File names are targets, not reserved public APIs. AppHost is the only hosted
composition root. The AppService/AppServer package shape must continue to
satisfy the import rules in the parent hosted-boundary draft, and
`hosting.service` must not be created before its separate acceptance.

## Concurrency, Ordering, And Backpressure

- Mutations within one hosted Session are serialized by the existing Session
  owner.
- Independent Sessions run concurrently.
- MuxSpace membership mutations are serialized per MuxSpace.
- Selecting a local window never waits for a server round trip.
- Each attachment has a bounded outbound queue.
- A slow attachment cannot block Session execution or another attachment.
- Terminal events, interaction requests, request responses, and controller
  lease changes are never silently dropped.
- Ephemeral deltas may be coalesced before a lagged attachment is disconnected.
- Every externally retried member/session creation uses an idempotency key.
- Closing a MuxSpace prevents new member admission before closing members in a
  deterministic order.

## Delivery Slices

The slices align with the parent AppService plan and consume AppHost/Hosting
only after their separately proposed contracts are accepted.

### Slice 0 — Accept The Named Mux Contract

- review this draft;
- accept the v1 Product identity/cardinality rule, attach barrier, resource
  owner table, and AppHost shutdown semantics;
- identify the first admitted Session-scoped Product Runtime factory;
- decide whether Unix-only first delivery is acceptable;
- confirm the default Harnesstui Embedded Profile remains unchanged and the
  Hosted Mux Profile is an explicit startup choice; and
- create a tracking issue and isolated TUI/AppService workstreams before code.

### Slice 1 — App Contract And Fake Client

- define MuxSpace/member/attachment values and typed errors;
- require `product_id`, membership revisions, per-member cursors, and typed
  barrier retry/`SnapshotRequired` results;
- define create, list, attach, detach, close, and member operations;
- add schema and codec tests; and
- provide a fake AppClient for Harnesstui state tests.

No AppHost, Hosting, socket, Product import, or Harness change is included.

### Slice 2 — AppService Mux Core

- add hosted Session and MuxSpace registries;
- inject a fake scoped Product Session resolver;
- implement one controller per MuxSpace;
- implement serialized membership revisions, per-Session snapshot/cursor
  pairs, the attach initialization barrier, and ordered events;
- keep logical attachment generations separate from transport connections; and
- test multiple spaces and independent Session concurrency.

### Slice 3 — Harnesstui Hosted Mux Profile

- preserve one shared Harnesstui presentation core and the default Embedded
  Profile adapter;
- add a separate hosted AppClient adapter and hosted-only mux shell;
- reuse generic TUI Tabs/TabGroup;
- add the window state, reducer, controller, and projection;
- add the persistent two-row hosted footer, 1-based positions, marker priority,
  and narrow-terminal degradation while leaving Embedded Profile unchanged;
- implement contextual Tab and prefix actions;
- bind only to AppClient-compatible ports; and
- extend deterministic screen-loop playback for both profiles.

### Slice 4 — AppHost Runtime And Unix Local IPC

- land the separately accepted AppHost runtime/launcher baseline;
- add one foreground AppHost target that constructs AppService, injects it into
  AppServer, and resolves one scoped Product binding per Session;
- bind one authenticated Unix local endpoint admitting one Product ID;
- implement the bounded AppHost shutdown sequence;
- run under an external supervisor or an attached test launcher first; and
- verify terminal and SSH-client loss does not stop active Sessions; and
- verify fresh-barrier reattach.

### Slice 5 — Hosting Service Instance Controller And Daemon Profile

This slice is separately gated and may be omitted where an external supervisor
is authoritative:

- accept the Hosting Service Instance Controller requirements, context,
  component discovery, and lifecycle contract;
- implement exact process identity, service records, serialized start/stop/
  probe, readiness, deadline, termination, and reaping mechanics;
- add the AppHost daemon-control adapter over that opaque Hosting contract; and
- prove that Hosting and AppServer do not import one another.

### Slice 6 — Product CLI Composition

- add canonical `mux` commands;
- consider `-t` and `-d` only after grammar review;
- keep mux flags outside the shared Harness CLI profile; and
- add end-to-end create/list/attach/detach/close scenarios.

### Slice 7 — Optional Canonical Profile Distribution

This slice is independent and deferred:

- contribute immutable Product/hosted-integration/Profile factories and a
  launch descriptor through canonical Product/OEM governance;
- add service/client/profile version negotiation;
- reuse canonical trust, enablement, activation, drain, retirement, and
  uninstall policy; and
- keep built-in/OEM process control outside ordinary Harness Plugin activation.

### Slice 8 — Windows Lifecycle

This slice is independently gated:

- choose and implement the Windows local endpoint;
- implement detached process ownership and stale-process detection;
- add native lifecycle and reconnect tests; and
- preserve the same App Contract and Harnesstui behavior.

## Size Estimate

For a mergeable Unix-first Hosted Mux Profile running as a foreground AppHost
target or under an external supervisor, excluding generated schema and
documentation:

| Area | Product lines |
| --- | ---: |
| App protocol and client | 350–550 |
| AppService Session/MuxSpace coordination and attach barrier | 700–1,050 |
| local transport, snapshot, delivery, reconnect | 450–750 |
| AppHost hosted composition and ordered lifecycle | 300–550 |
| Harnesstui hosted adapter and mux shell | 500–800 |
| shared Harnesstui/TUI additions, including the two-row footer | 150–300 |
| Product CLI composition | 120–220 |
| Product total | 2,570–4,220 |

Expected tests add approximately 1,700–2,800 lines, for a total change of about
4,270–7,020 lines.

A separately accepted Hosting Service Instance Controller plus AppHost daemon-
control adapter adds roughly 1,100–1,900 lines including tests. Optional
canonical Product/OEM distribution metadata and lifecycle integration adds
roughly 300–700 lines rather than a parallel application-plugin host. A
production-quality Windows lifecycle and transport slice adds roughly another
1,100–1,900 lines including tests.

These are planning ranges, not implementation targets. Existing reusable TUI
widgets may reduce the generic TUI portion.

## Verification Matrix

| Invariant | Required evidence |
| --- | --- |
| TUI remains independent | import denylist and generic widget/input tests |
| Embedded and Hosted are profiles of one Harnesstui | shared-core tests plus distinct embedded/hosted adapter composition tests |
| default Embedded Profile is unchanged | startup, exit, input, and presentation regression tests |
| Harnesstui has no service/socket dependency | fake-AppClient hosted reducer and playback tests |
| AppService has no TUI/Product imports | package import tests |
| Harness has no mux/AppService dependency | architecture import tests |
| AppHost is the unique process owner | composition and eight-phase shutdown tests |
| AppServer and Hosting remain independent | bidirectional import denylist tests |
| one AppHost hosts several names | multi-MuxSpace service and process tests |
| one endpoint admits one Product ID | new/open/resume identity and rejection tests |
| every Session has a scoped Product binding | concurrent create and deterministic release tests |
| spaces isolate state and execution | concurrent independent-Session scenarios |
| window selection is local | no-RPC input/playback assertion |
| contextual Tab preserves nested UI behavior | completion, modal, form, composer, and empty-input tests |
| Hosted footer is two rows and Embedded is unchanged | single/multi-window, embedded, and minimum-height playback tests |
| positions and shortcuts agree | 1-based `Ctrl+B 1..9`, reorder, close, and more-than-nine-window tests |
| footer remains legible when narrow | active-window retention, title truncation, omission-count, and no-wrap tests |
| attention is not color-only | marker-priority and unstyled rendering tests |
| detach adds no implicit interrupt | active-turn disconnect/reconnect plus Approval-lease cleanup scenarios |
| reattach converges | membership revision, per-member cursor, barrier, and `SnapshotRequired` tests |
| controller is generation-fenced | stale connection and duplicate response tests |
| transport and logical attachment are separate | EOF, reconnect, and stale-connection ownership tests |
| Hosting owns no Session semantics | service lifecycle tests use an opaque AppHost launch target |
| machine resources have one owner | placement, disposal, stale-record, and retention tests |
| no ordinary Plugin can replace the host invariants | contribution and import-boundary tests |

Tests that execute pytest or asynchronous runtime behavior follow the workspace
rule and run outside the managed sandbox. TUI interaction changes use the
existing deterministic playback substrate and assert intermediate frames, not
only final state.

## Acceptance Checklist

Before implementation begins, reviewers should be able to answer yes:

- Is `MuxSpace` clearly different from hosted Session and TUI window?
- Are Embedded and Hosted Mux explicitly profiles of one Harnesstui product?
- Does the default Embedded Profile remain independent of AppClient and mux?
- Does one AppHost target support multiple names without spawning peer daemons?
- Is AppHost the unique process composition and shutdown owner?
- Are AppServer transport state and AppService logical attachments distinct?
- Does AppService own application coordination but no rendering or OS process
  mechanics?
- Does Harnesstui own window state while TUI remains a generic toolkit?
- Does Hosted Mux show one application-status row plus one bottom mux row while
  Embedded preserves its current footer?
- Is the bottom mux row the sole window selector rather than a duplicate of
  top tabs?
- Are displayed positions and `Ctrl+B 1..9` consistently 1-based, with stable
  commands continuing to use `member_id`?
- Does the active window remain visible without footer wrapping on a narrow
  terminal?
- Does every Session carry an explicit admitted `product_id` and receive its
  own scoped Product Runtime binding?
- Is active window selection local to each client?
- Does closing an attachment leave active Sessions running?
- Does reconnect use a membership revision, per-member snapshot/cursor pairs,
  and a client-visible barrier rather than claiming one cross-Session instant?
- Is exactly one controller allowed per MuxSpace in v1?
- Does controller loss follow the existing Approval cleanup contract?
- Are `-t` and `-d` Product-level conveniences rather than Harness grammar?
- Is the default embedded profile preserved without Session migration?
- Does optional delivery use canonical Product/OEM admission rather than a
  parallel application-level plugin host or ordinary Harness Plugin?
- Does every runtime resource have one owner and bounded lifetime?
- Are daemon crash recovery, panes, multi-writer collaboration, and Windows
  lifecycle kept outside the Unix-first v1?
