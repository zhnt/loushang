# Detachable Local Hosted Workspace G16

[Architecture](../README.md) · [AppServer](README.md) ·
[AppService](../appservice/README.md) · [AppHost](../apphost/README.md) ·
[G15 design](../apphost/foreground-hosted-tui-g15.md) ·
[G14 foreground](foreground-stdio-hosted-app-g14.md)

## Status

- ID: `DETACHABLE-LOCAL-WORKSPACE-G16`
- Kind: cross-scope deployment, authority and lifecycle decision
- Scope: AppServer local profile / AppService client scope / AppHost local edge
- Parent: Loushang application architecture
- Authority: normative accepted deployment boundary
- Design status: accepted following the three-perspective review below
- Implementation status: implemented — semantic scopes, native connections,
  AppHost/G13, real Coding composition and installed interactive attach are
  implemented; Linux native/clean-wheel evidence and the local whole-delta
  review passed. Three-platform native fault evidence passed at `bda21085`.
  Release acceptance is gated by corrected-head checks and the final review
  recorded on [PR #567](https://github.com/zhnt/loushang/pull/567), followed by
  promotion and synchronization; implementation alone is not release acceptance
- Activation status: explicit new deployment only; G14 and Embedded unchanged
- Tracking: [Hosted Workspace V1 #566](https://github.com/zhnt/loushang/issues/566)
- Prerequisite: G15 design accepted in `18d429bc`; G14 delivered in `815c03d2`
- Inherits: [principles](../loushang-architecture-principles.md),
  [governance](../governance-profile.md),
  [ARD-003](../decisions/ARD-003-apphost-top-level-placement.md)

## Outcome, Requirements And Non-Goals

An explicitly running local application hosts several named muxes and real
Product Sessions. Two terminal clients can control different muxes. Closing
one terminal releases only its control authority; already accepted execution
continues under the application owner. A new connection attaches through a
fresh snapshot barrier. Restarting the application restores G13 desired state
and canonical Session history, not in-flight execution.

| ID | Acceptance condition |
| --- | --- |
| `G16-LOCAL-AUTH` | only the literal local endpoint is usable; wrong/stale credentials, replay, reflection and unauthenticated operations fail before semantic admission |
| `G16-PRIVATE-RECORD` | credentials are private from creation, exact-root, bounded, no-follow and instance-fenced; insecure POSIX modes or Windows DACLs fail closed |
| `G16-PROFILE` | detachable negotiation is distinct from foreground-stdio/v1; neither profile silently changes the other's EOF or Ack contract |
| `G16-MULTI-MUX` | one application owns multiple names and concurrent Sessions; independent clients control different muxes without extra application processes |
| `G16-CONTROLLER` | only one client scope controls a mux; another client gets AlreadyAttached; every mutation is scoped, not just turn operations |
| `G16-ACCEPTED-WORK` | the application's admission point transfers accepted work out of a connection's cancellation lifetime; no connection close cancels that work |
| `G16-APPROVAL` | losing a controller revokes its unanswered interactions; later unattached approvals fail closed; an old token cannot be answered by a new controller |
| `G16-REATTACH` | new connection/attachment generations and fresh membership/snapshot/cursor barriers replace old local views; no future, request, decision or event is replayed implicitly |
| `G16-BOUNDS` | connection, authentication, application-operation, Session, frame, queue and shutdown bounds remain enforceable across repeated disconnects |
| `G16-STOP` | explicit application stop fences admission, settles retained work/Product owners and releases G13 last; failed cleanup is not reported as clean shutdown |
| `G16-RECOVERY` | fresh process recovers cwd/home Sessions and stable mux/member identities with fresh credentials and attachments; stale endpoint state grants no process authority |
| `G16-CLIENT` | installed server and interactive terminal client support create/list/attach/detach/close and safe controls through AppClient |
| `G16-EVIDENCE` | deterministic tests, real processes/terminals, installed wheel and non-skipped Linux/macOS/Windows fault gates prove the complete profile |

Non-goals: public-network/HTTP/WebSocket endpoints, multi-user tenancy,
read-only observers or takeover, several writers to one mux, live execution
replay after process death, automatic mutation retry, service installation,
automatic daemon launch, a new Hosting service controller, live Embedded
Session migration, legacy transcript adoption, image upload or default-route
activation. One endpoint admits one Product ID; it is not a cross-Product mux.

G15's full launcher and resumable-Session picker remain design-only. G16
implements the shared hosted shell and its independently connected Product
entrypoint, not the attached-launcher lifecycle. Existing mux/member selection,
explicit scoped member creation/resume and automatic G13 recovery are included;
a global resumable-Session discovery UI is not claimed without G15's new API.

## Current Facts And Delta

G14's `AppServerConnectionV1` owns request tasks and cancels them at EOF.
`AppServiceV1.start_turn` currently awaits the actual Product turn in that
call. Consequently preserving an AppService object alone cannot preserve a
turn across transport cancellation. G16 needs application-owned admission.

Current AppService attachments are not connection-scoped. A later attach
increments the mux controller generation and fences earlier mutations; it
does not reject the second controller. Current detach does not revoke a
Product approval. The new deployment must close these gaps without silently
changing the explicit G11/G14 client contract.

The existing wire values, framing, G13 store/lease, real Coding factory,
controller and conversation projection are retained. The optional native local
connection layer now composes record admission, authentication and an injected
scope factory. The optional AppHost deployment owner now binds that factory to
the recovered G13 application. Real Coding composition and the installed
interactive terminal client activate this explicit route; the
[inventory](detachable-local-workspace-g16-inventory.json) distinguishes
implemented responsibilities from final delivery/evidence still outstanding.

The first G16.1 primitive, `appservice._operations._OwnedAppOperations`, now
reserves application capacity before effects, retains tasks across delivery
cancellation and performs bounded retryable application-stop settlement.
The optional `appservice.client_scope.ScopedAppServiceV1` now composes it with
exclusive mux controllers, scoped read/control validation and interaction
settlement. It must be installed before exposing an application's clients or
starting execution, and the outer application must not expose a parallel
legacy unscoped client to the same peers. AppHost's optional local owner now
activates this edge after recovery. The installed `loushang-mux` route uses it;
the existing G14 request lifetime is unchanged.

`appserver.local_auth` now authenticates an injected byte port and provides
direction-bound sequenced frames. This is not endpoint admission: its material
must come from the validated private record owner. Authentication keeps
transport cleanup with the caller until successful stream adoption; no semantic
scope or Product is constructed by the authentication layer itself.

## Logical And Physical Context

Logical boundary: an authenticated local client receives an application-scoped
capability and an independently owned logical client scope. Mux controller
authority is granted by AppService inside that scope. Product policy and the
canonical Session owner remain authoritative for actual effects and storage.

Physical composition (edges mean constructs/binds):

```text
explicit foreground server / external supervisor
  Product command constructs G13 application
  optional AppHost local edge binds:
    AppServer local listener + per-connection semantic scope factory
    AppService application admission + Product Session binding

client Product command
  reads one explicitly admitted local connection record
  authenticates AppServer local client
  binds borrowed AppClient into Harnesstui hosted shell

client EOF -> that connection/scope settles
application stop -> all connections/scopes/work/Product owners settle -> G13 lease
```

The server is independently started. It is not spawned as a TUI-owned G15
child whose exit would end the application. No Hosting service dependency is
needed for this profile; an external supervisor may own process continuity.

## Component Discovery And Allocation

| Candidate function | Refine / primary owner | Collaborator | Explicit non-owner |
| --- | --- | --- | --- |
| local listener, credential record and authentication | keep one AppServer local connection component | private native filesystem adapter, existing framing | Hosting, Product Session, AppService |
| connection-bound mux control and accepted-work lifetime | keep one optional AppService client-scope component | existing mux registry and Product ports | socket, transport and UI |
| controller-bound interaction invalidation | extend AppService Session ownership | Product's existing approval decision port | transport, UI persistence |
| aggregate start/stop order | keep optional AppHost local deployment edge | injected listener and G13 application | listener internals, Product implementation |
| trusted executable/configuration and installed CLI | keep Product outer composition | existing real Session factory and scope catalog | generic AppServer and UI |
| hosted terminal experience | reuse/extend G15 Harnesstui shell boundary | AppClient and generic TUI | process owner, filesystem discovery |

Authentication and credential files are a transport trust boundary, not a
generic secret-management subsystem. Retained operations belong to application
coordination, not a detached task pool in the connection. Native private-file
helpers remain inside the local endpoint resource owner; no dependency on
Hosting's private Win32 implementation is allowed.

## Local Endpoint Decision

Choose one explicit loopback-only TCP profile on Linux, macOS and Windows.
Bind IPv4 literal `127.0.0.1` on an OS-assigned port. No hostname resolution,
wildcard, caller-selected remote address, proxy, alternate address fallback,
port sharing or public listener is supported. The endpoint record contains
the actual port and one random application instance identity. A browser HTTP
request cannot be interpreted as the binary authenticated profile.

Alternatives considered: Unix sockets plus Windows named pipes provide native
local addressing but require two distinct connection implementations. TLS
adds certificate provisioning/rotation to the local bootstrap boundary.
Neither is prohibited as a later adapter, but G16 chooses an explicit
authenticated loopback profile with a trusted local kernel, not a network
security or confidentiality claim. Same-account malicious code, administrator
access, kernel compromise and deliberate port forwarding are outside this
trust boundary. Credential confidentiality from other ordinary accounts is
still mandatory; loopback alone is not authentication.

The existing stdlib-only AppServer boundary is retained. Only its exact local
endpoint adapter may open sockets; no general permission for connections,
codecs or semantic adapters to spawn, discover Products or access Hosting.

### Credential Record And Publication

The outer Product composition supplies one immutable canonical runtime root
and endpoint name. Default placement belongs to the existing PlatformPaths
authority; an explicit Product command may instead admit a runtime-root override
once. The current development command requires that override and an existing
parent directory; it introduces no second default-path resolver or discovery.
The AppServer record owner derives only narrow children. It never reads home,
cwd or environment again. No record field selects executable code, a Session
root or a Product factory.

The owner acquires an OS-released lock before changing the named record. The
lock inode is stable and is not unlinked on release. A stale record or PID is
not permission to signal a process. A competing process using another G13
store but the same endpoint still cannot publish over the live reservation.

The strict record is at most 8 KiB and contains schema/profile, application
identity, random instance ID, numeric local port, a 32-byte random key and
bounded public scope/capability facts. PID is optional diagnostic data, never
authority. Records are not logged or printed by inspect/help. Secrets are not
passed through argv, inherited environment, Session metadata or child tools.

POSIX creation requires owner-only directories/files, the current owner and
stable regular no-follow objects; symlinks and multiple hard links are
rejected. Windows creation supplies a protected non-null DACL restricted to
the current user and SYSTEM at creation, and checks owner/DACL/reparse/identity
on the opened handle before reads or replacement. `chmod(0600)` is not a
Windows security proof. Native validation must reject permissive/absent DACLs.

Recover G13 and bind the listener before atomically publishing the complete
record. Start admission only when the complete ready state exists. Failed
startup closes the listener and reservation. Retirement removes only the
exact record owned by that instance; never remove a replacement's record.
Restart rotates the instance and key. Old credentials cannot authenticate a
new process even if the OS reuses its port.

### Authentication And Frames

The distinct profile is `local-detachable/v1`, carrying `loushang.app/v1`
semantic operations. It cannot negotiate down to `foreground-stdio/v1`.
Use fresh 32-byte server/client nonces and HMAC-SHA256 challenge/proof with
different role labels and an unambiguous transcript binding profile,
application/instance identity and both nonces. Verify fixed-size proofs with
constant-time comparison. The key itself never crosses the connection.

No semantic scope or request may be admitted until mutual authentication
finishes. No early data. Reject unknown fields, invalid sizes, role reflection,
reused proofs, wrong key, stale instance and unsupported versions with one
redacted authentication failure. A fresh connection gets fresh derived
direction-specific keys and sequence counters; none is persisted.

The authentication exchange consists of three strict, length-prefixed JSON
objects: server challenge (`profile`, `protocol`, `instance`, `server_nonce`),
client proof (`client_nonce`, `proof`) and server proof (`proof`). Nonces and
proofs are exactly 64 lowercase hex characters. Instance identity is the exact
32-character lowercase hex value in the admitted record. No optional or
unknown fields are accepted. The transcript is the fixed ASCII profile and
protocol labels separated by NUL, the 32-byte SHA-256 digest of the canonical
public record (all fields except the key), then server and client nonce bytes.
Proofs are HMAC(key, role + NUL + transcript) for distinct `client` and `server`
roles. Direction keys use distinct `c2s` and `s2c` role labels instead.

After authentication, the first authenticated frame selects exactly `app` or
`stop`. The app path creates a semantic scope and uses the local profile hello
before any AppClient request. The stop path is a separate bounded management
exchange, never an extra reflected method on AppClient. Neither can downgrade
or switch mode after admission. Credential values are excluded from repr,
exceptions, logs and help output as well as from protocol messages.

Authenticated frames bind direction, sequence and payload with HMAC. The
application payload remains capped at 1 MiB; a separate fixed 40-byte
sequence/tag envelope is the only additional frame allowance. Check outer
length before allocation, MAC and monotonically increasing sequence before
semantic decoding. No encryption is claimed. Existing G14 framing and message
limits remain unchanged; the new envelope cannot weaken its defaults.
The authenticated envelope is an unsigned 8-byte big-endian sequence, a
32-byte tag and the unchanged semantic payload. Sequences start at one in
each direction and cannot wrap. The tag covers the sequence and payload with
the corresponding direction key. The stream uses one writer serialization
owner so sequence allocation and complete frame writes cannot reorder.

## Semantic Client Scope And Acceptance

AppHost asks the ready application for one owned client scope only after
authentication. AppServer receives its AppClient and close port through an
injected factory; it neither imports nor constructs AppService. AppService
owns the logical scope, opaque identity, attached muxes and retained operation
budget. Transport connection IDs never become user-supplied authority.

All selectors resolve canonically inside AppService. Listing/reading mux
metadata is available to the authenticated application client. Mutating
membership or closing a mux requires that scope's controller lease. Attach to
an already controlled mux returns `AlreadyAttached` without changing its
generation. The same scope may explicitly refresh its own attachment barrier;
replacement is atomic and does not expose an intermediate takeover window.
No token from another scope grants read-events, snapshot, mutation or approval
authority, even when it is otherwise a well-formed current-generation token.
Add the closed error value `already_attached` to the shared error vocabulary
and schema; do not overload `already_exists` or silently take over a mux. G14
does not begin emitting the new deployment-specific failure by default.

Admission is the linearization point where the application validates current
authority, reserves bounded capacity and publishes an owned operation before
its first Product effect. Work not yet admitted is rejected on scope loss.
Once admitted, connection cancellation cancels only the delivery waiter; the
application retains and observes the exact operation until completion or
explicit application/member stop. There is no automatic retry or exactly-once
claim after an unknown outcome. G13 create identities retain their existing
limited idempotency guarantee, not a general RPC replay log.

`start_turn` Ack keeps its existing completion meaning; a cancelled waiter
does not receive an invented acceptance/completion Ack. While the call waits,
snapshot/events expose running state. New connections reconcile that state
instead of retrying the lost request. Only one active start per Session is
admitted; other starts return busy rather than accumulating a hidden queue.
Accepted structural mutations also retain commit/cleanup ownership across a
disconnect; an attach that finishes after its scope closes must be reclaimed
without publication to that dead scope.

## Detach, Approval And Reattach

Logical detach and EOF both fence that scope's affected control generations.
They do not interrupt ordinary accepted work. AppService releases the mux
controller reservation only after fencing the old authority and registering
required interaction settlement. Cleanup ownership survives cancellation.

An interaction belongs to the controller generation present when it is
published, not whichever client later happens to be newest. On control loss,
unanswered interactions are denied through the existing Product decision port.
An approval requested with no controller is also denied; it cannot create an
unbounded parked waiter or execute implicitly. No transfer of old questions
or approvals to a new controller. A decision already admitted before loss may
finish; disconnect does not roll back an authorized effect.

Application locks are not held while calling Product decision/cleanup ports.
Pending denial failure becomes bounded application cleanup debt and keeps
unsafe control re-grant fenced; it cannot be suppressed and called success.
The Product owns how a denied tool result affects its still-running turn.
Scope closure separates short attachment-initialization/interaction cleanup
from long accepted turns. Only the former can delay release of controller
authority; waiting for a detached turn to finish before allowing reattach
would defeat this profile. A late attachment result is compensated exactly
once and cannot leave a ghost controller. Generation replacement also denies
old unanswered interactions rather than transferring them to a refreshed UI.

Reattach gets a new logical scope/attachment generation and the existing
membership-revision plus per-member snapshot/cursor barrier. UI applies only
that generation, preserving local unsubmitted drafts by member identity when
the member still exists. Cursor gaps require a new snapshot, not guessed
events. An explicit reconnect action is supported; automatic command replay
is not. Repeated reconnect cannot bypass global capacity or leak attachments.

## Bounds And Whole-Application Stop

Defaults: 8 admitted authenticated connections, of which at most 7 are in app
mode and one slot is reserved for stop; 8 additional negotiating attempts
(authentication and the first authenticated mode frame share that pending
budget); 32 retained ordinary application operations plus 8
reserved control/settlement operations; 32 muxes, 64 live Sessions, 128 total
live/initializing attachments. Each connection retains G14's 16 ordinary plus
4 control slots. Authentication frames are at most 2 KiB and have one 5-second
deadline. Public record size is separately bounded at 8 KiB.

Each stream has bounded asyncio read/write watermarks; application payloads
are limited before buffer allocation. Authentication failures and full
admission close only the offending peer. Ordinary capacity cannot consume
the reserved interrupt/denial/stop path. Detached work continues to occupy
application capacity until actually settled, not merely until its peer exits.
The listener's synchronous accept callback reserves capacity before scheduling
an authentication coroutine; rejected peers are closed without allocating an
unbounded task queue. Authentication-to-ready transfer releases/reserves the
corresponding counters atomically. Cleanup debt continues to consume capacity
until its actual owner settles. No per-disconnect recreation resets limits.
The mode frame has its own deadline of at most five seconds after mutual
authentication; it grants no semantic scope before admission. This allocation
retains the original total of 16 tracked peer owners and keeps the stop path
available when all ordinary client slots are occupied.

Application stop has one 30-second monotonic budget. Fence listener and all
logical scopes, close delivery waiters, revoke interactions, interrupt/join
retained execution, close Sessions/Product owners, then release the G13
application lease. The optional AppHost edge owns this ordering. Failed
dependencies prevent a false lease-last success; retain retryable owners and
exit nonzero if bounded fatal settlement is required. An external supervisor
is the hard process-termination owner. Never kill a PID taken from a record.

One authenticated local control request may request application stop through
an injected AppHost callback, outside AppClient's Session API. Its response
means `stop_requested`, not `cleanup_completed`; attempt that response within
the write deadline before starting connection teardown. Once stop is admitted,
a failed response write does not discard the stop request. Its single-flight
owner is published before the write and cannot await itself through the
connection that requested it. The CLI must print that distinction. Native
tests observe actual process exit separately. A normal client detach never
invokes that stop callback.

## Product And Terminal Integration

Add an explicit installed `loushang-mux` command with `serve`, `list`,
`create`, `attach`, `close` and `stop` actions. The existing installed commands
retain their targets and behavior. `serve` requires admitted workspace,
application and Session roots, constructs real Coding Sessions and remains a
foreground process. Clients receive an explicit endpoint record selector; no
daemon auto-discovery, auto-start or installation is added.
The source entrypoint is `coding/cli/mux.py`. The existing
`coding/cli/workspace.py` and `loushang workspace` govern retained Git
workspaces and must not be repurposed for hosted application control.

The client can create/list named muxes and attach the Harnesstui hosted shell.
The shell supports scoped member creation/resume, local window navigation,
drafts, streamed output, approvals, interrupt and detach. Close is a separately
confirmed destructive intent affecting the selected mux/member, not a synonym
for exit. The application connection key grants local management authority,
so `stop` requires an explicit command and is not a UI disconnect fallback.

Reuse the G15 UI boundary and bounds. The G15 inventory must record which
planned shell/client files G16 actually implements while keeping its unused
attached launcher and discovery extension as explicit gaps. No claim of full
G15 implementation or Embedded feature parity follows from this reuse.

## Dependencies, Decisions And Resource Ownership

Intended optional dependencies (not current implemented imports):

```text
appserver local adapter -> AppServer framing/auth/client ports + stdlib
appservice client scope -> AppService runtime/ports + AppServer values
apphost local edge -> AppHost continuity/application + AppServer local ports
Product server/client command -> admitted Product composition + optional edges
harnesstui hosted shell -> AppClient/values + shared Harnesstui/TUI

AppServer -/-> AppService / AppHost / Hosting / Product / UI
AppService -/-> transport / AppHost / Hosting / Product / UI
AppHost core -/-> local transport adapter / Product / UI
Hosting -/-> application or protocol semantics
```

This parent-level decision accepts a new optional deployment boundary, not a
relaxation of the standard-library-only AppServer or product-neutral Harness.
The local edge may consume an application-owned scope factory through an
explicit port; it must not extract private AppService fields from AppHost.

| Resource | Sole owner | Lifetime / location |
| --- | --- | --- |
| endpoint record/key/reservation | AppServer local resource owner | injected runtime child; exact instance publication/retirement |
| socket, auth nonce, frame queues | AppServer connection owner | one connection |
| logical scope, controller, mailbox | AppService | attachment/control lifetime |
| accepted operation and cleanup debt | AppService application owner | actual settlement, independent of client |
| Session execution/transcript/assets | Product/Harness owner | canonical Session lifetime |
| application record and writer lease | existing G13 owner | application recovery/shutdown, lease last |
| draft and terminal state | Harnesstui/TUI | client run, private and bounded |
| diagnostics | existing producer/sink | bounded observability retention, never protocol secrets |

## Evidence And Delivery Plan

1. Design/inventory, exact optional dependency gates and three-view design
   review. Any feasibility experiment verifies an uncertain platform mechanism,
   not a narrowed acceptance profile.
2. Regression-first semantic scope/admission, exclusive controllers, operation
   retention, approval loss, capacity and shutdown ordering with fake Product
   ports. Keep legacy in-process/G14 tests unchanged unless correcting a bug.
3. Authenticated local transport, native private record, replay/reflection/
   framing tests, bounded unauthenticated/slow peer tests and instance fencing.
4. Real G13/AppHost/Coding server, installed CLI and Harnesstui shell; test two
   independent mux clients, close one during a real synthetic-model turn,
   reattach, reject old authority, then restart and recover canonical state.
5. Native Linux/macOS/Windows fault matrix, isolated wheel and terminal
   playback/PTY/ConPTY evidence; full three-view code review and fixes.
6. PR to lane/harness, reviewed promotion PR to main, then verify remote/local
   main and harness contain the delivery. Preserve unrelated staged changes;
   never force-reset a lane to satisfy synchronization.

No required platform case may skip and count as delivered. Unit fakes prove
semantic ordering, not OS authentication, process survival or terminal cleanup.
Test models and safe tools are explicit trusted seams; no live model or
external network service is required. Native connection tests do use the
profile's real local loopback socket.

### Three-View Design Review

Three perspectives by one reviewer, not an independent-agent claim:

1. Architecture/security (`G16-R1`): loopback is not user authentication, and
   post-creation chmod is not private Windows credential creation. Resolved
   with exact record locking/native ACL validation, creation-time privacy,
   fixed mutual-authentication transcript/role separation and per-direction
   authenticated sequencing. The local-kernel threat boundary and lack of
   encryption are explicit. Native Windows ACL and adverse authentication
   tests remain required runtime evidence, not assumed from POSIX results.
2. Cancellation/lifecycle (`G16-R2`): preserving the service object does not
   preserve a turn; second-attach fencing is not exclusive control; late attach
   completion and stop-response failure can leak ownership. Resolved with an
   application-owned admission point, scoped mutation authority, exclusive
   controllers and compensating initialization cleanup, retained interaction
   denial, pre-task accept capacity and a stop owner independent of its reply.
   New tests must race each effect against disconnect and bounded shutdown.
3. Product/evidence (`G16-R3`): the first inventory incorrectly reserved the
   already existing Git-workspace CLI module; its source-existence test failed.
   Resolved by the separate `loushang-mux`/`coding.cli.mux` vocabulary and route,
   preserving Git workspaces. The G15 shell is explicitly included while its
   attached launcher and discovery API stay unimplemented gaps. Three-platform
   real multi-client/approval/restart and terminal evidence remain mandatory.

Re-review: the design now has a distinct physical profile, single semantic
authority, explicit acceptance/cancellation points, bounded control-loss and
shutdown paths, and a non-conflicting installed route. Accepted for incremental
implementation. Neither this review nor its architecture tests prove runtime
completion; inventory status tracks only the behavior actually evidenced.

Design-only verification: the first G16 inventory test failed on the existing
Git-workspace module collision. After the correction, the G16/G15/G14 design
and G9 closure selection passed 18 tests, Ruff passed, and
`make check-architecture-docs` passed its five cases. No production source or
installed entrypoint changed in this design slice.

### G16.1 Implementation Checkpoint

The private operation owner was added after a failing missing-module
regression. Focused cases cover lost waiters, occupied busy keys, separate
ordinary/control capacity, cancellation during close, retry after cleanup
timeout, lost-result observation and task-construction rollback. No semantic
scope, authentication, native transport or user interaction is proved by this
primitive. Those requirements remain open until their integrations land.

Slice review (three perspectives, one reviewer): authority stays outside this
private lifetime primitive; capacity is reserved before task publication and
Product effects; close waiters cannot cancel the retained cleanup owner. The
review added regressions for tasks cancelled before their first step and for
task-factory failure during both admission and close. The architecture guard
was corrected from substring matching to exact AST imports after it falsely
matched the existing `standard_cli_operations` function. The corrected wider
selection passed 140 cases; final `make check-appservice` passed 233 cases
with Ruff and mypy. This is a reviewed primitive, not the final G16 code review.

### G16.2 Semantic Scope Checkpoint

The optional scope owner implements the same 15 AppClient methods, with eight
bounded scopes and one exclusive controller per mux. Authority validation and
retained task admission have no intervening yield. Start-turn completion Ack
is unchanged; the Session busy key survives delivery and scope cancellation.
Short attachment/membership work retains ownership separately from long turns.
Explicit member/mux close cancels and joins that Session's retained turn;
ordinary detach never does. G16 separately caps muxes at 32 rather than inheriting
the legacy protocol's broader 256-value limit. Pending create/open reservations
consume capacity before their first effect and roll back on task-start failure.
Foreign-scope snapshots/events and stale generations are rejected; refresh
keeps the controller reservation while replacing the snapshot barrier.

Interaction questions are bounded to 16 per live Session (at most 64 Sessions,
including opening reservations and retained cleanup). Questions are bound to
the publishing attachment, not the newest controller. Scope loss and refresh
deny unanswered questions; no-controller denial debt must settle before a new
attachment can publish. An admitted response remains owned until it settles.
Scope close uses one retained waiter per bounded scope rather than occupying
the control-operation slot needed by its own denial. Actual asynchronous
Product decisions still share the eight reserved control slots. Synchronous
steer/follow-up/interrupt calls validate and execute without a suspension or
queued operation; they create no retained asynchronous work.

Slice review (three perspectives, one reviewer):

- Authority: selectors are resolved canonically; all attachment consumers,
  including reads, require the calling scope. Unowned denial debt also fences
  attach, rather than merely rejecting an old approval token after regrant.
- Lifecycle: fixed a close-mux self-wait and control-capacity starvation when
  eight scopes close together. Failed denial preserves the controller;
  application stop still closes Product ports and retains retryable debt.
  Real Coding integration then exposed an ordered-event/approval-cancellation
  cycle when an event listener awaited its own automatic-denial completion.
  The listener now only publishes the retained denial task and returns; attach
  waits for settlement outside event delivery. Failed unowned denial or denied
  admission explicitly interrupts the Session; it does not rely on a Product
  event observer propagating listener exceptions.
- Compatibility/evidence: the new `already_attached` error has an exact schema
  vocabulary and codec round trip. New modules have separate 600/220-line
  review budgets; the G11 core budget and default activation remain unchanged.

These tests exercise fake Product ports, the real AppService owner and the real
Coding adapter/ApprovalBroker with isolated local Session files. The latter
verifies denial on disconnect, automatic denial without a controller, then a
new approval after reattachment; the first run timed out on that last step and
passed after removing the listener/decision wait cycle. They do not prove
local authentication, native record privacy, G13 process restart or an
installed interactive terminal client. Final G16 code review remains open.

Verification: the AppService gate's selected suite passed 253 cases, Ruff and
mypy passed (42 source files), the focused scope/operation/real-Coding selection
passed 36 cases, the exact inventory/boundary selection passed 13 cases, and
the architecture documentation gate passed five cases. The real-Coding test
was verified separately and is now explicitly included in both the AppService
and AppHost Makefile gates. No new CLI or transport is activated by this slice.

### G16.3 Authentication And Integrity Checkpoint

The optional `local_auth` adapter implements the exact three-message proof
transcript and authenticated frame envelope above, using standard-library
HMAC-SHA256 and fixed-length constant-time proof/tag comparison. Private framing
mechanics are shared with G14, but the public `AppFramedStreamV1` signature and
1 MiB limit stay unchanged. Authentication fixes a 2 KiB frame limit and one
deadline of at most five seconds; only the authenticated profile admits the
fixed extra 40 bytes. Oversized lengths fail before reading a body.

Slice review (three perspectives, one reviewer):

- Authentication: distinct proof and direction labels, fresh nonces and the
  canonical public-record digest are bound together. Independent expected-wire
  vectors cover the transcript and envelope, while wrong credentials, changed
  record digest, stale instance, downgrade, duplicate keys, replay and reflection
  fail closed. Secrets are absent from credential repr and captured wire frames.
- Lifetime: cancellation of a partial read or uncertainty after a write fences
  the authenticated channel. No subsequent send, replay or receive can reuse it;
  the outer caller still owns cleanup on handshake failure. Between-frame EOF
  retains its distinct clean-EOF signal for the future connection adapter.
- Compatibility/evidence: all existing G14 connection/framing tests remain in
  the selection. Authentication is a separately bounded optional module with no
  reverse semantic dependency or default entrypoint import. These tests use
  fragmented in-memory byte ports, not native endpoint authentication or ACLs.

Private record creation/validation, native listener/connection admission,
profile-mode and semantic-scope composition, actual CLI/TUI and three-platform
fault evidence remain required. This checkpoint is not final G16 acceptance.

Verification: the unchanged AppServer/G14 baseline passed 63 cases; the expanded
AppServer and exact architecture selection passed 133 cases. Final
`make check-appservice` passed 305 cases, including 50 local-authentication and
integrity cases, with Ruff and mypy clean (43 source files). The documentation
gate passed five cases. No native record, listener or installed client evidence
is claimed by these results.

### G16.4 Private Record Checkpoint

`LocalConnectionDirectoryV1` owns an explicitly supplied canonical local root;
`LocalEndpointReservationV1` owns a stable endpoint lock and at most one published
record. Four private helpers separate closed serialization, retained file IO,
POSIX admission and Windows admission without creating another public package
or importing Hosting internals. This component has an explicit 1,100-line total
budget and separate module budgets, not an increase to the G14 protocol budget.

The v1 JSON schema has exactly `schemaVersion`, `profile`, `protocolVersion`,
`endpoint`, `applicationId`, `productId`, `instance`, `port`, `scopes`,
`capabilities` and `key`. Capabilities are the closed list `named_mux`,
`text_turns`, `approvals`; each of one or two scopes contains only `scope`
(`cwd` or `user_home`) and a 64-character lowercase fingerprint. The endpoint
name is bounded to 64 ASCII identifier characters and is hashed into its file
stem. No path, executable, environment variable or PID is admitted from JSON.
Duplicate fields, extra fields and payloads over 8 KiB fail with redacted codes.
The authentication digest covers canonical sorted compact public JSON excluding
only `key`; the key is exactly 32 random bytes, serialized as lowercase hex.

Publication validates any previous private record under the stable OS lock,
writes and flushes a new private exclusive temporary file, and atomically
replaces the record. The temporary attempt is owned before creation, and its
descriptor is retained before inheritance or identity checks. A Windows handle
that has not transferred to the CRT remains owned until exact-handle deletion
and close settle. Publication identity is recorded before rename, so an error
after replacement does not lose retirement ownership. Retiring an endpoint
never unlinks its stable lock file or an observed replacement record.

An unsuccessful create with no acquired descriptor grants no permission to
delete an unexpected file at that name. Unsettled cleanup keeps the lease and
lock, rejects further admission after directory close, and can be retried.
An uncertain POSIX descriptor close is not retried using a possibly recycled
integer and remains reported as cleanup debt. Filesystem IO requires the
injected trusted local filesystem; these synchronous bounded-byte operations
are not a hard wall-clock guarantee against a stalled kernel/filesystem.

Slice review (three perspectives, one reviewer):

- Architecture/security: the native adapter checks opened objects rather than
  trusting creation flags or POSIX mode emulation on Windows. POSIX owner-only
  objects reject symlinks and extra hard links. Windows checks protected,
  non-null owner/SYSTEM DACLs, current owner, non-reparse type and 128-bit file
  identity. Native ACL widening/null-DACL and junction tests are present, but
  their presence is not Windows execution evidence.
- Lifecycle: regression-first fault tests exposed lost temporary ownership
  after creation and before validation. The owner now precedes those checks.
  Tests cover failed writes/flushes, both sides of rename, retryable cleanup
  debt, preservation of byte-identical foreign replacements, and lock/record
  replacement conflicts. A real spawned child is terminated through its owned
  process handle; the next reservation obtains the released lock and rotates
  credentials without using stale record data as process authority.
- Evidence/compatibility: default imports, CLI routes, G14 framing and EOF
  semantics remain unchanged. Native record tests join the existing AppService
  selection on all three CI platforms. Linux and cross-platform static results
  do not stand in for Windows/macOS native runs; complete endpoint, installed
  client and interactive terminal evidence is still required by this goal.

This is an uncomposed record component, not completed local deployment or G16
acceptance. Native endpoint admission, profile negotiation, scope/stop
composition, real CLI/TUI and complete cross-platform fault validation remain.

Verification: final `make check-appservice` passed 345 cases on Linux, with
10 Windows-only cases skipped because their native APIs are unavailable on
Linux. Ruff and mypy passed (48 source files); AppServer also passed a separate
Windows-platform mypy check. The documentation gate passed five cases. The
native record selection includes 39 portable/POSIX cases, with real child
process crash/lock rotation; the additional Windows cases require native CI.

The first native matrix at `b689d71c` passed the complete AppService gate on
[Linux](https://github.com/zhnt/loushang/actions/runs/34142859440/job/101808480067)
and [macOS](https://github.com/zhnt/loushang/actions/runs/34142859440/job/101808479889).
[Windows](https://github.com/zhnt/loushang/actions/runs/34142859440/job/101808480096)
ran the native DACL/reparse/handle and crash cases, but failed two shared fault
tests because their preparation attempted to overwrite a still-open Windows
destination. The replacement fault now moves the held object aside before
installing a foreign object at the original name. It still requires actual
replacement and a `CONFLICT` result; it does not skip the native case or accept
an OS error as a successful identity-fence test. Its Windows rerun is pending.
The same draft exposed two older AppHost/Hosting exact module lists that had
not incorporated G16. Both lists now name the reviewed optional modules; the
dependency restrictions and default-dark requirements remain enforced.

### G16.5 Native Connection Checkpoint

`LocalAppServerV1` and `LocalAppClientConnectionV1` now own actual literal IPv4
loopback connections. Constructors validate configuration without starting IO;
callers retain each owner through start/close failures. The server reserves an
endpoint, binds port zero, adopts the native listener before publishing its
private record, then admits clients. Windows binds with exclusive-address-use;
there is no hostname, remote address, proxy, port sharing or daemon bootstrap
parameter. Only `appserver/local.py` can construct native connections.

The connection component borrows its directory. Each server owns only its
reservation, peer set and startup/close tasks. Each authenticated app peer gets
one synchronously created `OwnedLocalClientScopeV1` through an injected factory;
the server neither constructs nor imports AppService. A private peer owner
reserves capacity before task scheduling and keeps failed scope/IO settlement
charged to that capacity. Its publication barrier also covers eager task
factories. Startup and close keep the exact outstanding task after a timeout,
and late native listener/writer results are adopted and closed behind the
already-established fence. Graceful close preserves queued stop replies;
deadline expiry aborts native IO while retaining any semantic cleanup debt.

The shared executor now consumes `AppMessageStreamV1` and a closed
`AppConnectionProfileV1`. `RemoteAppClientV1` requires explicit profile selection;
`StdioAppClientV1` fixes G14's original profile and constructor. The server's
omitted profile is still G14. Profile values live in protocol code, not in the
authentication engine, and mismatches cannot silently negotiate. Only an
authenticated local peer can select `app` or `stop` on the native listener;
no AppClient operation or Product callback is admitted before that point.

Stop remains a separate management exchange. Its injected callback must
synchronously publish the application stop owner before returning, and receives
a read-only reply-completion awaitable. That owner waits for the bounded reply
attempt before tearing down connections. The peer completes the barrier even
when the reply fails; it never awaits application shutdown through its own
connection. A received reply means only `stop_requested`, not completed cleanup.
The AppHost implementation of this callback and aggregate G13 lease-last stop
is still required; the connection component does not pretend to own it.

Slice review (three perspectives, one reviewer):

- Architecture/security: one exact native-IO module exemption replaces no
  other G11/G14 restriction. Profile negotiation and message handling remain
  transport-neutral; factories receive no unauthenticated request or peer-
  supplied implementation. Reserving one of eight admitted slots for stop
  prevents ordinary connections from exhausting management admission without
  increasing the total peer budget. Defaults and installed routes remain dark.
- Lifetime: native fault tests cover cancelled startup before listener/writer
  handoff, delayed completion after caller cancellation, retained scope cleanup
  and stop reply loss. A regression exposed an unclosed coroutine when task
  creation failed; unstarted work is now closed before propagating that failure.
  Stop admission precedes its reply and its retained shutdown task cannot await
  itself through the requester. A normal EOF closes scope authority, not the
  application-owned execution admitted before that EOF.
- Product/evidence: real loopback tests now combine this component with the
  actual AppService and synthetic Product ports. Two mux clients retain
  independent turns across a disconnect; a fresh connection/attachment restores
  a snapshot without replay, and old authority/approvals fail. This is stronger
  than in-memory framing evidence but is not a real Coding/AppHost server,
  installed client, interactive TUI, restart-recovery or full platform proof.

Remaining at this checkpoint: AppHost's public ready-scope and ordered local-stop
seam (implemented in the next checkpoint), real Coding server/client composition,
the installed command and interactive Harnesstui, cross-platform native/installed
fault evidence, final reviews and promotion.

Connection-slice verification: `make check-appservice` passed Ruff, mypy for
51 source files and 367 tests (10 Windows-native cases skipped on Linux).
The additional Hosting/G9/V1/G16 architecture selection passed 34 tests, and
Windows-platform static mypy passed 23 AppServer files. Native close also
checks that the admitted socket handle is closed; `connection_lost` alone is
not physical-settlement proof. These results are local Linux evidence, not a
Windows/macOS connection run. The Windows replacement-fault test correction
and the new native connection code still require remote platform verification.

### G16.6 AppHost And G13 Deployment Checkpoint

The optional `apphost.local.HostedLocalRuntimeV1` adopts a recovered G13
application and one private connection-record directory before starting IO.
Its application identity comes from G13's public lease-backed metadata, not a
second caller-supplied string. It binds only public application capabilities:
`enable_client_scopes`, `open_client_scope` and `fence_client_scopes`. Neither
the local edge nor AppServer reaches into private AppService/G13 fields.

Scoped activation is explicit and one-way. Borrowing even an unused legacy
client prevents later activation, because fencing a getter cannot revoke a
capability already returned. Once activated, the legacy getter is unavailable;
repeated activation shares the same application-owned scopes. G13 forwards
these operations only after recovery is complete. A synchronous scope fence
denies both new clients and actions from existing clients without cancelling
already accepted execution. G14 and the core facade remain unchanged.

An admitted stop fences listener and logical scopes and publishes its retained
close task before the peer attempts `stop_requested`. A reply failure cannot
discard this intent. The local owner then joins startup, waits for the bounded
reply attempt, closes connections, settles the private directory, and calls
G13 close (not retire). Desired state survives; Service/AppHost/Product settle
before the application lease. Failed connection or record cleanup prevents
advancing to the application. One 30-second monotonic deadline includes all
stop phases. Cancelled waiters do not cancel owned tasks; an expired deadline
does not renew on another close. Explicit `close(retry_timeout=...)` may grant
another budget only after the previous attempt ends, reusing outstanding phase
tasks rather than duplicating close work. An external supervisor remains the
only hard process-termination owner.

Slice review (three perspectives, one reviewer, not independent agents):

- Architecture/authority: keep the local deployment as one optional AppHost
  module; core modules import no transport and existing G14/Embedded routes do
  not activate it. The public scope seam closes the legacy-capability bypass.
  The G12 application component's old 500-line budget failed after adding this
  public mode/fence seam (525 lines). Its reviewed G16 budget is 550 lines;
  client selection stays cohesive with the existing application boundary,
  while the separate local deployment owner is capped at 300. No core import
  restriction or other component budget is relaxed.
- Lifecycle/faults: retained close tasks and one deadline cover reply loss,
  late startup, waiter cancellation, directory failure and explicit retry.
  Regression-first review found that startup rejection was being mislabeled
  as cleanup debt even after successful settlement. Startup now preserves its
  actual failure; unresolved cleanup still takes precedence when necessary.
- Product/evidence: native loopback tests bind real AppHost/G13/AppService to
  synthetic Product/lease ports. A client disconnect leaves its accepted turn
  running; explicit stop settles that turn before Service/AppHost/Product and
  releases the lease last. These are composition tests, not an installed real
  Coding server, durable-file restart, interactive terminal or Windows/macOS
  acceptance. Those full-goal requirements remain open.

Local verification: `make check-apphost` passed Ruff, mypy for 67 source
files, and 591 tests with 11 platform-related skips. Its G8/G9/G10 evidence
subgates passed 19/16/15 tests without skips, including manifest validation
and the installed G10 POSIX canary. The new G16 runtime/scope and boundary
selection passed 23 tests; the reconciled A0/G12/G16 architecture selection
passed 37. These are local Linux checks and do not close G16's installed
Product/UI or three-platform evidence requirements.
The final `make check-appservice` rerun passed Ruff, mypy for 53 source files
and 393 tests with 10 Windows-native skips on Linux. Architecture documentation
validation passed all five cases. Earlier complete runs exposed the obsolete
A0 optional-module lists and G12 component budget; those guards were explicitly
reconciled above before both complete gates passed.

Supplemental Windows-platform static checking passed the 36-file G16
AppHost application/continuity/local, AppService and AppServer chain. Checking
the entire AppHost package also reported six pre-existing POSIX-only API type
errors in the unchanged `apphost/integrations/harness_session.py` adapter
(`O_DIRECTORY`, `O_CLOEXEC`, `O_NOFOLLOW`, `pread`). That optional adapter has
its own native-support guard; this result is not reported as a whole-package
Windows pass, and no permission or fallback policy was relaxed to hide it.

### G16.7 Real Coding Composition And Development Commands

`coding.hosted_bootstrap` now constructs the real Coding Session factory,
admitted Product/profile and G13 durable-file attempt for both explicit G14 and
G16 deployments. The old G14 launch-value import remains an alias to the same
type, and its default description and foreground EOF semantics are unchanged.
The shared bootstrap chooses neither transport nor process deployment. Model
and tool injection remain trusted library test seams, never command-line code
selection. Default Embedded routes import none of the new composition.

`coding.hosted_local.CodingLocalCommandV1` owns the unopened attempt before
recovery and retains any late recovery result. It adopts the local AppHost
owner before starting it, then relinquishes its own application reference.
After this handoff only AppHost closes the application and private directory;
the Product wrapper must not reset the AppHost deadline or reclaim the
application separately. Closing during startup settles an already-adopted local
owner before joining outer startup, avoiding a startup/close dependency cycle.
Cancelled waiters retain exact tasks. An explicit retry budget may be granted
after a failed attempt, but cannot renew an in-flight close.

Review reproduced a ready-after-stop race at both public startup deliveries:
a finished startup task could return after a concurrent stop had fenced the
deployment. AppHost now exposes read-only `accepting`, which stop revokes
synchronously; AppHost and Product recheck it before returning ready. This is
a point-in-time readiness fact, not a lease guaranteeing future availability.
Deterministic tests force the gap between task completion and waiter delivery,
as well as Product handoff, and prove no ready callback after stop and no
duplicate application close.

The development entry `python -m loushang.coding.cli.mux` supplies explicit
`serve`, `list`, `create`, `close --yes` and `stop` commands. It requires an exact
private connection root and endpoint. That root cannot contain the execution
workspace or overlap application/Session storage. Client commands do not
autostart an application, discover endpoints or signal a PID. The native client
checks the expected Coding Product against its single admitted record before
opening a socket, avoiding a separate preflight read and replacement race.
Descriptions/results exclude credentials, numeric ports and filesystem paths;
JSON output escapes terminal controls. `stop_requested` means admission only,
not completed application cleanup. An unresolved cleanup causes a failure exit,
not an unbounded runner shutdown or a claim of clean resource release.

Slice review (three perspectives, one reviewer, not independent agents):

- Architecture/security: share one trusted real Product bootstrap, keep native
  IO in AppServer, keep startup handoff in Product and application settlement
  in AppHost. Admit explicit runtime-root overrides at the outer boundary,
  and verify the expected Product before opening the native connection.
  Exact consumer lists were reconciled for the three new Product modules;
  their separately reviewed combined budget is 900 lines. The existing Coding
  Wave A and G14 budgets and core dependency prohibitions remain unchanged.
- Lifecycle/faults: fix and regress the ready-after-stop race; retain late
  recovery and shutdown tasks; never transfer ownership back after adoption.
  Repeated close joins the current operation and cannot implicitly renew its
  deadline. Client EOF is not an application-stop signal.
- Product/evidence: tests use real Coding/AppHost/G13 file storage over native
  authenticated loopback. Two muxes use cwd and user-home Sessions; accepted
  work survives disconnection, a fresh attachment sees it running, and a new
  runtime recovers stable identities/history with rotated credentials and no
  in-flight replay. Separate real command processes also prove management,
  controller exclusion, stdin EOF survival and explicit stop followed by actual
  server exit. The model stream/tools alone are synthetic. Same-process runtime
  replacement is not process-crash recovery evidence, and module invocation is
  not installed-wheel or interactive-terminal evidence.

Installed `loushang-mux`, the shared interactive shell, real process-crash
recovery for this profile, PTY/ConPTY and final Linux/macOS/Windows acceptance
remain required. No installed script is advertised by this slice. The G15
attached launcher and global resumable-Session discovery picker remain separate
design-only gaps. Neither library tests nor management commands complete G16.

Local verification: the focused lifecycle/real Product/boundary selection
passed 26 tests. `make check-appservice` passed Ruff, mypy for 56 source files,
and 409 tests with 10 Windows-native skips on Linux. Documentation, G14/G16
inventories and the separate Coding budget selection passed all 10 cases.
`make check-apphost` passed Ruff, mypy for 70 source files and 606 tests with
11 platform skips; its G8/G9/G10 subgates passed 19/16/15 tests without skips,
including manifest checks and the installed G10 POSIX canary. These are Linux
slice/regression results, not final three-platform G16 acceptance.
Supplemental Windows-platform mypy passed the 40-file G16 composition selection
with a separate cache. Its first simultaneous invocation exited 139 without
diagnostics; no Product change was made to obtain the isolated successful rerun.
This is static evidence only, not native Windows runtime acceptance.

### G16.8 Interactive Controller Preparation

Before wiring the interactive terminal, regression-first review reproduced
draft loss in the shared Hosted Mux controller. A long submit response cleared
the currently selected window rather than the submitted window, and a fresh
snapshot discarded all local drafts/navigation. Merely attaching the existing
controller to a terminal would expose these failures to normal typing.

Each local draft now carries an edit revision. A successful submit can clear
only the same mux/member/Session draft at the captured revision, even when a
fresh snapshot has replaced the local window object. Editing away and back to
identical text still changes that revision. The new revision field is
keyword-only, preserving existing positional window construction. No failed or
unknown mutation is automatically resubmitted. Refresh and membership
reattachment copy only local
draft/revision, scroll position, unread state and selected member by stable
identity; new snapshot credentials, cursors, records, running state and
interaction authority are never copied from the stale view. A changed Session
under the same member receives no previous Session draft.

During a failed refresh, the old view remains available for local editing,
but its `snapshot_required` fence rejects turn, approval, interrupt and member
mutations before sending an RPC. A subsequent explicit refresh may acquire a
new barrier without discarding the drafts. It is not automatic reconnect or
an operation replay policy.

Slice review (three perspectives, one reviewer, not independent agents):

- Architecture: editing/navigation remains client-local in the existing
  Harnesstui reducer/controller; no new service, transport or Product dependency.
- Concurrency: captured edit revisions prevent late responses from erasing new
  input, and stable identities prevent reordered/replaced members inheriting
  another Session's draft. Failed refresh retains edits but not usable actions.
- Evidence: deterministic controlled-waiter tests exercise intermediate states,
  same-text editing, window changes, snapshot failure/reordering/replacement
  and late completion across refresh. These are controller tests, not a running
  shell or native terminal proof. The installed attach route, bounded input
  queue/drafts, terminal restore and PTY/ConPTY evidence remain open.

The original 600-line G11 Hosted Mux component budget remains unchanged. G15
still delivers design only; this controller refinement does not implement its
launcher, global Session picker or the planned G16 interactive shell.

Local verification: the complete AppService gate passed Ruff, mypy (56 source
files), and 418 tests with 10 Windows-native skips on Linux. The final targeted
controller selection passed 17 cases, including the supplemental positional-API
compatibility regression added after that full run had collected its tests.
The focused controller/architecture selection passed 21 cases earlier in the
slice; documentation and G15/G16 inventory checks passed nine. Final focused
Ruff and mypy cover all six Hosted Mux modules. No native terminal or full G16
acceptance is inferred from these results.

### G16.9 Installed Interactive Terminal Checkpoint

The installed `loushang-mux attach NAME` now authenticates once, obtains
path-free admitted scope facts from that connection, and lends only AppClient
to the Harnesstui shell. `serve` remains independently started and foreground;
terminal EOF and explicit detach do not stop it. Non-terminal attach is rejected
before connection IO. Existing Embedded and G14 entrypoints are unchanged.

The shell reuses the shared conversation screen, Composer, InputReader,
TerminalSession and native terminal port. One editor has a 16-entry undo bound;
per-window drafts are limited to 64 KiB UTF-8 and aggregate drafts to 1 MiB.
Display history is capped at 256 records/512 KiB per window without deleting
canonical history. Unterminated paste over the input bound fails visibly,
instead of interpreting its truncated tail as commands. Image paste is rejected
before clipboard/file effects. The shell has at most 64 local action waiters,
with eight slots reserved for controls, plus two terminal reader/poll waiters;
these are bounded concurrent waiters, not an implicit mutation retry queue.
One retained shell close task and deadline settle those waiters and attachment.
Overdue tasks remain owned and cleanup is not reported complete.

Turn, approval and interrupt identities are captured synchronously before
asynchronous request execution. Window navigation and typing do not wait for
turn completion. First-member creation rejects otherwise unowned text before
editor effects. Membership refresh preserves existing drafts by stable identity.
The G11 six-file semantic controller budget stays at 600 lines; G16's four exact
shell/screen/waiter/terminal modules have a separate 850-line budget, with an
exact module-set check and no process/socket/storage authority in this UI.

Review-driven fixes in this slice include native terminal rollback after partial
entry and independent restoration despite output/drain failures; shared TUI
fault regressions failed before the fix. The Hosted view does not invent a
Product permission profile, model, filesystem location, or run duration.
The v1 snapshot contains canonical history and running state, not earlier
transient assistant deltas; reattachment says so explicitly. No active output
or request is replayed to disguise that contract limit.

Native tests use the installed client in the existing PTY/ConPTY test driver.
The all-installed no-model scenario creates a user-home member, edits, detaches,
lists the retained member and explicitly stops the server. A real Coding/G13
child with only model/tool responses scripted exercises two clients controlling
different muxes and scopes, a genuine policy approval, streamed output, retained
execution after detach, fresh attach and interrupt. A separate test kills the
exact server process during execution and starts a replacement against the same
roots, checking stable mux/member/Session identity, a new endpoint instance,
recovered history and no execution replay, then sends a fresh terminal turn.
These are installed-editable/source-composition native tests, not isolated-wheel
evidence; the scripted child is not the installed server command.

Linux validation: `make check-appservice` passed Ruff, mypy (63 files) and
475 tests with ten Windows-only skips. The broader shared TerminalInput/runner/
TerminalSession selection passed 69. Isolated Win32-targeted mypy of the changed
UI/terminal/connection slice passed 15 files; this is not native Windows proof.

A separate offline wheel installation also passed all four native terminal
cases, with zero skips: all-installed server/attach, two-mux control/approval/
detach/interrupt, and actual process-death recovery for both cwd and user_home.
The test runner used the isolated environment from an external cwd with `-I`,
pytest `pythonpath` set to the repository root (not `src`), and child
PYTHONPATH/PYTHONHOME removed. An import-origin check verified the command,
shell and TerminalSession came from the installed environment. Wheel SHA-256:
`82a417ef94dde7de38dc4a3a8077fdff452d194cf77447db70cb47a6ee18d7f0`.
The first temporary installation failed due to /tmp quota; an isolated
environment in the ignored cache using same-filesystem hardlinks succeeded.
No fallback to the editable installation counted as wheel evidence.

Required macOS/Windows cases have no skip decorators, but their new runs, the
Windows record rerun, cross-platform isolated-wheel gates, complete fault
manifest and final three-view whole-delta review remain outstanding at this
checkpoint. The next slice addresses long approval/help text; the final review
must still audit shutdown failure/retry behavior. G15's foreground launcher
and Session-discovery picker remain design-only. This checkpoint does not
declare Hosted Workspace V1 complete.

### G16.10 Read-Only Details And Exact Evidence Gates

The shared `tui.ui_parts.text_pager.TextPager` now provides bounded plain-text
paging. It has no command, approval or application authority. It strips terminal
control sequences, expands tabs, wraps by display-cell width and rejects input
over 1 MiB before layout. Too-small terminals request resize without crediting
unshown text. Navigation tracks the contiguous prefix actually included in
renders: jumping to the last page alone does not imply that middle pages were
presented, and reflow resets partial presentation. This is presentation
evidence, not proof that a person has read or understood the text.

Harnesstui owns the semantic binding. F1 or `/help` opens complete command help;
F2 or `/question` opens the current approval text without changing the local
draft. `/approve` opens unpresented details without sending an RPC. Only after
every page has been presented, Esc and a new explicit `/approve` may send the
current response. `/deny` does not require viewing first. The presentation key
includes attachment, controller generation, member, Session and question
identity/text; changing any of them invalidates the previous approval view.
An expired view stays read-only until explicitly dismissed, so late pasted text
cannot fall through into an unrelated draft. Nothing automatically approves,
retries a mutation, or grants new Product policy authority.

The [G16 evidence manifest](detachable-local-workspace-g16-evidence-manifest.json)
defines six separate native/installed-wheel reports across `linux`, `darwin`
and `win32`. Each native report requires 26 exact cases; each wheel report
requires four exact native terminal cases. The selectors reuse authoritative
tests rather than implementing replacement Product behavior. Platform-specific
private-file faults select actual POSIX modes/symlinks or Windows DACL/junctions
and do not convert an OS refusal or a skipped test into successful evidence.

The generic evidence verifier keeps the G8/G9/G10 format compatible and adds
optional required suite properties. G16 requires the actual platform; wheel
reports also require `installation=wheel` and the actual `posix-pty` or `conpty`
backend. Missing, conflicting or incorrect properties fail, as do skipped,
missing, duplicate, failed or errored cases. Manifest `implemented` means the
test exists, not that the platform has passed it.

The installed runner builds no Product substitute. It installs the selected
wheel offline into an isolated environment under ignored `.artifacts`, removes
Python source/environment overrides, and executes the native cases with `-I`
outside the source working directory. Before pytest, it verifies module origins,
the selected wheel digest and every installed package file against the artifact
bytes. This does not rely on an installer retaining a hash in `direct_url.json`.
Ordinary quality gates test the script and verifier; separate three-platform CI
jobs execute the native fault and isolated-wheel rows and retain JUnit artifacts.

Reproduction on Linux, after seeding the locked development cache:

```sh
uv --cache-dir .uv-cache sync --locked --extra dev
uv --cache-dir .uv-cache build --wheel --out-dir .artifacts/g16-wheel
uv --cache-dir .uv-cache run python scripts/dev/run_g16_installed_evidence.py --wheel-dir .artifacts/g16-wheel --platform linux
uv run python scripts/dev/run_pytest.py tests/coding/test_mux_native_evidence.py --junitxml=.artifacts/g16-native-linux.xml -q -m 'not live'
uv run python scripts/dev/verify_evidence_manifest.py docs/internals/architecture/appserver/detachable-local-workspace-g16-evidence-manifest.json G16-NATIVE-LINUX .artifacts/g16-native-linux.xml
```

`--wheel-dir` requires exactly one Loushang wheel; `--platform` must match the
executing OS before installation. On macOS/Windows use `darwin`/`win32` and the
matching manifest row. Local repository rules still govern pytest execution.
The script bounds its subprocess waits; native test owners normally settle
their exact processes/terminals in `finally`. A forced termination of the
outer test runner is not evidence of completed Product shutdown.

Slice review (three perspectives, one reviewer, not independent agents):

- Architecture: generic text layout stays in TUI; attachment/question authority
  stays in Harnesstui/AppService. The four hosted UI modules remain within the
  existing 850-line budget, and no process/socket/storage dependency is added.
- Interaction/lifecycle: approval presentation cannot authorize a replacement
  question or silently move late input to another editor. Help preserves drafts,
  and explicit denial and interrupt remain available. Native interaction tests
  now open the actual details before explicitly approving. A regression also
  caught raw C0/C1 controls surviving title sanitization; titles now remove them
  as well as full terminal escape sequences, like the body.
- Evidence: regressions caught the installer-metadata assumption. The corrected
  probe checks installed bytes rather than weakening artifact verification;
  required platform/backend properties prevent relabeling an ordinary source
  run as an installed-wheel or native Windows run.

Linux verification: final `make check-appservice` passed Ruff, mypy for 64 source
files, and 498 tests with ten Windows-only skips in 327.94 seconds. An earlier
concurrent run had one 30-second timeout in the pre-existing real Coding
two-scope scenario (494 passed, ten skipped). That exact test passed separately
in 12.16 seconds, and the complete serial rerun passed without changing its
timeout or Product lifecycle. The 26-case native fault row passed with zero
skips and its manifest properties verified. The final UI/documentation/boundary
selection passed 29 cases. AppHost's Ruff and 78-file typecheck passed; its final
complete runtime/evidence gate still needs a rerun.

The final isolated Linux wheel row passed all four exact cases in 130.54 seconds
with zero skips, followed by successful manifest verification. Wheel SHA-256:
`d6a8c8d851d213dee4724da96040e6f206b9967e4709fb33d6796c3caea3d5b5`.
This artifact includes the title-control regression fix; a preceding successful
wheel run is not substituted for this final artifact.

Evidence qualification from G16.11: this run verified the installed artifact,
but its probe did not yet prove that the artifact's package file set matched
the source checkout. The stronger source/artifact/install check below supersedes
it for final release acceptance; a successful historical wheel run alone is
not proof against stale build-cache contents.

Supplemental Win32-targeted mypy passed the 13-file UI/pager/evidence-script
selection with an isolated repository cache. Initial attempts crashed or
reported an internal `mypy.metastore` SQLite `disk I/O error`; changing to that
cache resolved the tooling failure without changing Product code or suppressing
type errors. This remains static evidence, not native Windows execution.

The macOS/Windows matrix, Windows replacement rerun, full G16 review and delivery
remain required; adding these gates alone does not complete them. G15's launcher
and global discovery picker stay outside this implementation slice.

### G16.11 Whole-Delta Local Code Review And Readiness Fence

Review scope: the complete G16 source delta from the accepted G14 baseline
`815c03d2` through `cc383e3d`, plus the fixes below. This is a review from three
perspectives by one reviewer, not three independent agents. Source review and
Linux evidence do not stand in for native macOS/Windows acceptance.

1. Architecture and authority (`G16-CODE-R1`): the installed `loushang-mux`
   route was absent from the live G9 entrypoint inventory. Both exhaustive
   inventory tests failed against the actual five installed scripts. Inventory
   v5 now records its exact Product command, packaging binding and explicit
   detachable disposition. It does not import the G9 Worker composition, change
   omitted Worker ownership, or turn the Harnesstui client library into a
   launcher. The G10 canary and default routes retain their exact assertions.
   The G16 Windows record implementation was also still marked uncomposed
   although `LocalConnectionDirectoryV1` selects it on Windows; it now records
   that source fact as implemented, without claiming native validation passed.
2. Lifecycle and concurrency (`G16-CODE-R2`): public local server/client
   `start()` could return after its owned startup task completed but a concurrent
   close or admitted stop had already fenced the owner. Three deterministic
   regressions failed before the fix: listener close, client close and stop
   between task completion and public delivery. Public start now rechecks its
   own closed/readiness facts, and the server also checks admitted stop. Failure
   joins existing cleanup rather than publishing readiness. These three cases
   join the exact native evidence rows, increasing each row from 26 to 29.
3. Interaction and evidence (`G16-CODE-R3`): shell shutdown-failure coverage was
   insufficient to conclude the end-to-end client cleanup review. Additional
   deterministic tests now cover terminal restoration before a pending or
   failed detach, retained cleanup debt, reuse of the exact detach task/deadline,
   no automatic detach retransmission, settlement of that task after a late
   success, and Product connection/directory close even when shell close raises.
   The failed logical result remains an error rather than a clean detach claim.

The third perspective also found a release-evidence defect (`G16-CODE-R4`): a
fresh local wheel build reused `build/lib` and included the deleted
`loushang/coding/lsp/tool_pack.py`. The existing probe proved installation
matched that artifact, not that the artifact matched this checkout. Four
regression cases reproduced admission of an obsolete module, a missing module,
changed Python bytes and changed packaged asset bytes. The runner now checks
the exact Python module set, rejects duplicate package entries, and compares
every packaged source/asset byte with the current checkout before any
environment creation or installation. It also rejects package paths escaping
the source root. The existing isolated import/digest/installed-byte checks remain.
Runner unit fixtures use synthetic environments so their failure output does
not include ambient developer credentials.
The stale generated build tree was moved to an ignored, recoverable cache
directory, not deleted or included in the source commit. A clean rebuilt
artifact passes the new source check; its runtime evidence is recorded below
only after the installed scenarios actually pass.

The reviewed ownership chain remains: Product admits configuration and owns
bootstrap until handoff; AppHost owns ordered application settlement and G13
lease-last; AppService owns semantic client scopes, approvals and accepted work;
AppServer owns native admission/authentication/framing/connection cleanup;
Harnesstui owns borrowed-client interaction; generic TUI owns text layout and
terminal restoration. No socket/process/Session authority was added to the UI,
and G14 EOF/default Embedded semantics remain separate.

The requirement audit uses these concrete test scopes. A listed test is an
evidence location, not by itself a passing or cross-platform completion claim:

| Requirements | Authoritative evidence scope |
| --- | --- |
| `G16-LOCAL-AUTH`, `G16-PRIVATE-RECORD` | `tests/appserver/test_local_auth.py`, `test_local_record*.py`, and actual native platform manifest rows: wrong material/Product, replay/reflection, private creation, no-follow, replacement and crash |
| `G16-PROFILE` | retained `tests/appserver/test_connection.py` and `tests/coding/test_hosted_subprocess.py`, alongside explicit local profile negotiation and native EOF cases |
| `G16-MULTI-MUX`, `G16-CONTROLLER`, `G16-ACCEPTED-WORK` | `tests/appservice/test_owned_operations.py`, `test_client_scope.py`, `test_local_deployment.py`, and installed real Coding two-mux terminal scenario |
| `G16-APPROVAL`, `G16-REATTACH` | native disconnect/old-authority cases, generation-bound details tests, and real terminal approval/detach/reattach/interrupt; committed history is distinct from transient output |
| `G16-BOUNDS`, `G16-STOP` | operation/scope capacity tests, native authentication and stop reserve, `tests/apphost/test_local.py`, Product handoff regressions and terminal cleanup-debt tests |
| `G16-RECOVERY` | real process kill/restart from the installed wheel for both cwd and user-home, checking stable mux/member/Session identities, changed endpoint instance and no active execution replay |
| `G16-CLIENT` | installed management/interactive attach, real Coding response/approval and fake-terminal input, draft, navigation, sanitization and failure-restoration checks |
| `G16-EVIDENCE` | full AppHost/AppService gates plus exact zero-skip native and isolated-wheel manifests on Linux/macOS/Windows; final exact-head CI and delivery remain required |

Local targeted verification: the readiness/AppHost/Product selection passed
41 tests while reproducing the two inventory failures. The corrected
G9/G10/inventory/readiness selection passed 35; the terminal/command cleanup
selection passed ten. The source-wheel runner baseline passed three, the four
new stale-source regressions failed before its fix, and the corrected runner
plus evidence architecture selection passed nine. The 29-case native Linux
row passed with zero skips and manifest verification. Architecture docs passed
their source-generation check and five tests.

The full `make check-apphost` gate passed Ruff, 78-file mypy, 693 tests with
11 platform-only skips, G8/G9/G10 exact reports (19/16/15 tests, zero skips),
and the installed POSIX canary. Its 469.70-second main selection was collected
before the later three terminal/command tests and four source-wheel regressions;
those additions have their separate targeted results above. The final
`make check-appservice` gate then passed Ruff, 64-file mypy and 508 tests with
ten Windows-only skips in 313.51 seconds, including all seven later regressions.
The source-wheel runner also passed Win32-targeted mypy and its final
runner/design selection passed 13 tests; static targeting is not a native
Windows run. Historical G16.10 evidence above is not relabeled as this source
state.

The final clean Linux wheel passed all four installed terminal cases in
120.09 seconds with zero skips and successful manifest verification. This run
verified current source against the wheel before installation, then isolated
module origins, artifact digest and every installed package byte. The artifact
is `.artifacts/g16-clean-review-wheel/loushang-0.1.0-py3-none-any.whl`, SHA-256
`f6b98012788311ef9516643c7b1a2cf262a85d0a1382a04e950486318a3a2444`.

Supplemental retained-substrate and Embedded verification on source head
`1efbb7d7` passed without further implementation changes:

- `make check-hosting`: Ruff, mypy for 26 files, 373 passed and 45 skipped
  in 128.31 seconds. The exact optional-module inventory also passed its
  independent eight-test architecture selection.
- `make check-harnesstui`: Ruff, mypy for 152 files, 1,400 passed and 67
  render-contract cases deselected in 372.00 seconds; the independent render
  gate below covers that separate selection.
- `make test-tui`: 1,359 passed and seven skipped in 26.46 seconds, retaining
  the existing `--skip-host-runtime` selector.
- `make test-tui-render-contract`: 179 passed, 4,716 deselected in 21.90 seconds.
- `make test-tui-terminal-platform` and `make test-tui-native`: respectively
  110 and 12 passed, with no skips, using the actual local POSIX profile.
- `make test-tui-input-playback`: all five named selection, bracketed-paste,
  active-surface mouse selection, terminal-cleanup and Ctrl+C scenarios passed.

Read-only CI reconciliation confirmed that PR #567 still tested `b689d71c`:
the old Hosting/AppHost failures were exact-module inventory omissions already
corrected locally; its Windows AppService failures were the two native held-file
replacement injections corrected in `9f92a931`. This reconciliation does not
turn those old failed jobs into passing jobs. New macOS/Windows G16 runs still
require publication and native verification; the POSIX results above are
retained-path regression evidence, not a substitute for that release matrix.

Local review conclusion: the identified source/contract findings are resolved;
cross-platform release acceptance is still open. In particular the macOS and
Windows native/wheel rows, the Windows replacement rerun, final exact-head
review, PR/promotion and local/remote main+harness synchronization must finish
before this goal can be called complete. G15 remains design-only for its
foreground launcher and global Session discovery picker.

### G16.12 Native CI Installation-Workspace Correction

The first post-review CI run at `bda21085` passed all three exact native fault
rows, including the Windows held-file replacement cases. Its isolated-wheel
rows failed before installation: CI's uv 0.12.10 rejects a working directory
inside its managed cache, unlike the local uv 0.10.12 used for earlier evidence.

The evidence runner now creates its private temporary environment under
ignored `.artifacts`, beside `.uv-cache`, not inside it. It retains offline
installation, digest/source/installed-byte checks, isolated imports, exact
native manifests and cleanup on success or failure. Both directory-boundary
regression cases failed before this correction. This is an evidence-runner
fix, not a Product authority or deployment change; all three wheel rows must
pass on the corrected head before merge.

The Windows full suite also exposed Ctrl+C reaching the console signal handler
instead of the Hosted Mux key handler. The native console mode now clears
`ENABLE_PROCESSED_INPUT` while the terminal session owns input, for both VT
admission and its fallback, and restores the exact original flags on exit.
Four regression cases failed before the fix and now cover both native-selection
policies and VT acceptance/rejection. No Product-specific signal handling or
weakened interrupt assertion is introduced.

The G12 retained-AppHost-task test previously used a 10ms wall-clock budget,
which could expire the preceding service phase on Windows. It now reschedules
the real asyncio timeout only when the blocked AppHost callback has started,
retaining the same timed-out-phase, task-reuse and dependency-order assertions.
The application shutdown implementation and production budgets are unchanged.

The correction's architecture/security, lifecycle and evidence review is a
single reviewer's three perspectives, continuing G16.11. The only Product
source delta is the four-line native console mode correction; other changes
are runner isolation, deterministic test timing and evidence documentation.
The scoped authority, retained execution, G13 lease-last ordering and G15/G14
activation boundaries remain unchanged. All remote required rows must be
successful on the final PR head; a previous-head pass or local Win32 static
check is not substituted for native Windows execution.

### Platform API References

Python's [asyncio streams](https://docs.python.org/3.11/library/asyncio-stream.html)
provide explicit reader limits, write draining and connection closure; these
mechanisms do not replace the application's admission and settlement bounds.
Use [HMAC comparison](https://docs.python.org/3.11/library/hmac.html) for fixed
proof/tag verification. Windows private creation/validation uses native
[security descriptors](https://learn.microsoft.com/en-us/windows/win32/api/sddl/nf-sddl-convertstringsecuritydescriptortosecuritydescriptorw)
and a real [non-null DACL](https://learn.microsoft.com/en-us/windows/win32/api/securitybaseapi/nf-securitybaseapi-setsecuritydescriptordacl),
not POSIX mode-bit emulation. These references establish API behavior, not
G16 native acceptance evidence.

The Windows CRT [file lock and handle bridge](https://docs.python.org/3.11/library/msvcrt.html)
and native [file disposition](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_disposition_info)
are physical ownership mechanisms only. Fault tests use actual
[DACL replacement](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setnamedsecurityinfow)
to verify that permissive and null DACLs are rejected before credential reads.
