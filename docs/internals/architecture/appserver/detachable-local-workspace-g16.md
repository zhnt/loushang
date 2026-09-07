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
- Implementation status: partial — semantic scopes and the optional native local
  connection component are implemented; AppHost deployment and Product/UI remain
  missing, with Windows record rerun and new connection-platform evidence pending
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
scope factory. AppHost deployment and the terminal client entrypoint are still
missing. The [inventory](detachable-local-workspace-g16-inventory.json) separates
those missing responsibilities from existing extensions.

The first G16.1 primitive, `appservice._operations._OwnedAppOperations`, now
reserves application capacity before effects, retains tasks across delivery
cancellation and performs bounded retryable application-stop settlement.
The optional `appservice.client_scope.ScopedAppServiceV1` now composes it with
exclusive mux controllers, scoped read/control validation and interaction
settlement. It must be installed before exposing an application's clients or
starting execution, and the outer application must not expose a parallel
legacy unscoped client to the same peers. No AppHost factory, transport or CLI
activates this edge yet; the existing G14 request lifetime is unchanged.

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
and endpoint name, resolved once through the existing PlatformPaths authority.
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

Remaining: AppHost's public ready-scope and ordered local-stop seam, real Coding
server/client composition, the installed command and interactive Harnesstui,
cross-platform native/installed fault evidence, final reviews and promotion.

Connection-slice verification: `make check-appservice` passed Ruff, mypy for
51 source files and 367 tests (10 Windows-native cases skipped on Linux).
The additional Hosting/G9/V1/G16 architecture selection passed 34 tests, and
Windows-platform static mypy passed 23 AppServer files. Native close also
checks that the admitted socket handle is closed; `connection_lost` alone is
not physical-settlement proof. These results are local Linux evidence, not a
Windows/macOS connection run. The Windows replacement-fault test correction
and the new native connection code still require remote platform verification.

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
