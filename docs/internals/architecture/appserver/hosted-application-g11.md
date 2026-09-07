# Hosted Application G11 In-Process Vertical Slice

[Architecture](../README.md) · [AppServer](README.md) ·
[AppHost](../apphost/README.md) ·
[Embedded And Hosted Boundary](../drafts/appservice-embedded-tui-hosted-boundary-plan.md) ·
[Named Mux Design](../drafts/harnesstui-named-mux-daemon-attach-design.md)

## Status

- ID: `HOSTED-APPLICATION-G11-IN-PROCESS`
- Kind: accepted delivery design
- Scope: AppServer protocol / AppService / Product hosted adapter / Harnesstui
- Parent: Loushang application architecture
- Authority: normative accepted design
- Design status: accepted
- Implementation status: implemented — G11.0--G11.4 complete
- Activation status: explicit in-process Hosted Mux Profile only
- Owner: Loushang application architecture with sibling-scope review

## Outcome And Boundary

G11 introduces the first useful hosted application semantics without adding an
external listener or changing the default Product path.  An explicitly
constructed Harnesstui Hosted Mux Profile talks through an `AppClient` contract
to an in-process AppService.  AppService coordinates named MuxSpaces and
Product-owned hosted Sessions.  One Coding adapter demonstrates the Product
edge over public Harness Session controls.

```text
explicit Harnesstui Hosted Mux Profile
  -> AppClient
  -> InProcessAppClient
  -> AppService
  -> Product-owned hosted Session adapter
  -> public Harness Session controls

default Coding TUI / Harnesstui Embedded Profile -> unchanged Current path
```

G11 is not an AppServer runtime.  `loushang.appserver.protocol` owns immutable
client-safe values and a strict codec, but no socket, connection, listener,
authentication, framing, byte buffer, or process lifecycle.  The
`InProcessAppClient` is a semantic adapter and does not serialize its calls.

G11 does not activate the G10 Hosting canary for normal Sessions and does not
supersede the G9.3 `RETAIN` decision.  It establishes application semantics
that a separately reviewed G12 foreground AppHost and local IPC adapter may
transport later.

## Current, Target, And Delta

| Plane | Statement |
| --- | --- |
| Facts | G11 implements the AppServer protocol/client contract, AppService, one Coding hosted adapter and one explicit Harnesstui Hosted Mux Profile. Normal CLI/TUI/SDK paths remain Current. |
| Current | The explicit process-local Hosted Mux Profile consumes a typed AppClient; AppService owns MuxSpace and logical attachment semantics over injected Product Session ports. Harnesstui's installed path still binds an embedded Product conversation directly. |
| Target | A separately accepted successor may compose these semantics into a foreground AppHost and then add a local transport without moving Product, process or presentation authority. |
| Delta | Foreground AppHost composition, authentication, IPC framing/listener, durable daemon continuity and installed activation remain absent and separately gated. |

## Requirements

| ID | Requirement |
| --- | --- |
| `G11-R1-EXPLICIT-PROFILE` | Hosted Mux construction is an explicit library choice. Omitted CLI/TUI/SDK use and the Embedded Profile never import, construct, or discover AppService. |
| `G11-R2-TYPED-CONTRACT` | Every admitted operation, result, event, identity, cursor, revision, and error is represented by a closed immutable type. The codec rejects unknown versions, methods, fields, duplicate keys, invalid identifiers, and non-finite or unbounded input. |
| `G11-R3-IDENTITY-DOMAINS` | Product, continuity, Session, MuxSpace, member, attachment, request, event, interaction, cursor, revision, and controller generation remain distinct validated domains. A mux name is a selector and never a path. |
| `G11-R4-PRODUCT-NEUTRAL-SERVICE` | AppService depends only on AppServer protocol/structural ports and injected hosted Session ports. It imports no Product, Harness, AppHost, Hosting, Harnesstui, or TUI implementation. |
| `G11-R5-AGGREGATE-ISOLATION` | Membership mutations serialize per MuxSpace. No process-global lock is held across Product Session I/O or a turn. Independent MuxSpaces and Sessions remain concurrent. |
| `G11-R6-ATTACH-BARRIER` | Attach returns one stable membership revision plus one authoritative snapshot/cursor pair per member, then delivers only events after the corresponding cursor. Concurrent membership change yields a typed retry, never a mixed revision. |
| `G11-R7-BOUNDED-DELIVERY` | Each attachment owns one bounded logical mailbox. Critical overflow marks that attachment lagged and requires a fresh snapshot; it cannot block the Product event source or another attachment. |
| `G11-R8-LIFECYCLE` | Detach closes only attachment delivery and presenter authority. Member removal and Session close are separate operations. Mux close settles attachments before owned Sessions. Close is bounded, idempotent, and cancellation-safe. |
| `G11-R9-PRODUCT-EDGE` | The Coding adapter uses public Harness Session controls plus the immutable public AppHost Session envelope and explicit Product identity. It projects client-safe snapshots/events and exposes no model/provider, locator, tool implementation, path, credential, or raw exception. |
| `G11-R10-PRESENTATION-ISOLATION` | Harnesstui owns only window selection, drafts, focus, scroll state, reducer/controller behavior, and rendering projection. AppService owns no TUI state; widgets perform no service or socket I/O. |
| `G11-R11-COMPATIBILITY` | The Session identity envelope and scope facts are preserved by the Product resolver. G11 tests create/resume selection for cwd and user-home candidates, but make no cross-process restart or downgrade claim. |
| `G11-R12-NO-AUTHORITY-EXPANSION` | Passing G11 grants no AppServer listener, IPC, daemon, Hosting Service Controller, A0.5 launcher, default owner change, Current deletion, multi-client takeover, or live-turn recovery after AppHost crash. |

## Component Ownership

| Component | Owns | Must not own |
| --- | --- | --- |
| `loushang.appserver.protocol` | client-safe values, version, typed errors, strict JSON codec and schema fixture | service dispatch, Product objects, listener/framing, lifecycle |
| `loushang.appserver.client` | transport-neutral AppClient protocol only | sockets, retries, AppService implementation, Product resolution, presentation |
| `loushang.appservice` | MuxSpace registry, per-aggregate coordination, Session owners, logical attachments/mailboxes, attach barrier | transport connections, Product policy, AppHost or OS process lifecycle, UI state |
| `loushang.appservice.client` | in-process AppClient semantic adapter over one injected AppService | serialization, listener/framing, Product resolution, presentation |
| Product hosted adapter | public Product/Harness ports, Product-specific projection, identity-envelope preservation | mux policy, transport, AppHost core changes, presentation |
| `loushang.harnesstui.mux` | hosted window state, reducer, controller, explicit profile factory | Session implementation, AppService construction, sockets, daemon control |
| AppHost | future outer composition of admitted Product Session ports and AppService | App protocol behavior, mux semantics, Product internals |

## Dependency Direction

```text
appserver.protocol -> Python standard library
appserver.client -> appserver.protocol
appservice -> appserver.protocol
appservice.client -> appservice + appserver.client
coding hosted adapter -> appserver.protocol + appservice.ports + public Harness + public AppHost contracts
harnesstui.mux -> appserver.client + appserver.protocol + Harnesstui/TUI presentation
future outer composition -> AppHost + AppService + Product adapter

appserver -/-> AppHost / Hosting / Product / Harness / Harnesstui / TUI
appservice -/-> AppHost / Hosting / Product / Harness / Harnesstui / TUI
Harness -/-> AppServer / AppService / AppHost / Harnesstui
Hosting -/-> AppServer / AppService / AppHost / Product / Harnesstui
```

The exact hosted Session port is owned by AppService because it expresses the
semantic service's Product requirement.  A0.4's generic `appserver.ports`
bundle remains AppHost composition structure and is not repurposed as a
runtime Session API.  The Coding adapter is the deliberate outer edge allowed
to depend on both the Product/Harness surface and AppService ports. AppHost
core remains unchanged.

## Mux And Session Model

One AppService instance admits exactly one `product_id`.  It owns many named
MuxSpaces.  A name is unique inside that service instance.  One member points
to exactly one hosted Session, and one hosted Session belongs to at most one
MuxSpace in G11.  Member positions are contiguous and service-owned.  Active
window, draft, focus, scroll, and unread presentation flags are client-owned.

G11 supports explicit `create`, `list`, `read`, `attach`, `detach`, `close`,
`member/open`, `member/close`, `session/snapshot`, `turn/start`, `turn/steer`,
`turn/follow_up`, `turn/interrupt`, and `interaction/respond` operations.
Rename, reorder, observers, controller takeover, durable event replay, network
retry idempotency, and cross-Product spaces are deferred.

### Attachment initialization

1. Lock only the selected MuxSpace aggregate and capture its revision/members.
2. Reserve the attachment and its bounded mailbox before exposing snapshots.
3. For each member, obtain the Session owner's current snapshot/cursor.
4. Verify the membership revision is unchanged and publish the complete
   initialization value atomically to the caller.
5. Deliver retained events whose cursor is strictly greater than the member's
   returned cursor.

If history is unavailable, the service raises `SnapshotRequired`.  If the
membership revision changes, it raises `RevisionConflict`.  Neither condition
is hidden by a best-effort partial attachment.

## Lifecycle And Failure Rules

- Session resolvers return independently owned handles; AppService adopts the
  handle before inspecting snapshot or identity state.
- Failed member-open compensates the unpublished handle before returning.
- Registry, MuxSpace and logical attachment admission/settlement change in one
  atomic commit; Product callbacks and owned handles settle outside locks.
- Product callbacks and client callbacks are never invoked while a registry or
  aggregate lock is held.
- Cancellation after ownership adoption completes compensation before it is
  re-raised; incomplete cleanup is a stable typed service error.
- Raw Product exceptions are mapped to stable error codes. Paths, payloads,
  environment, credentials, prompts, model output, and exception strings are
  absent from service error values.

## Threat Model

| Threat | Control |
| --- | --- |
| implicit hosted activation | closed explicit profile factory; Current entrypoint inventory and import guards |
| identity/path confusion | separate validated ID types and selector grammar; no path field in protocol values |
| mixed attach snapshot | per-aggregate revision fence and reserve-before-snapshot barrier |
| slow or abandoned client blocks a Session | bounded nonblocking mailbox; lagged attachment isolation |
| stale attachment mutates a Session | attachment ID and generation are checked on every mutation |
| duplicate or stale event corrupts state | monotonic per-Session cursor and reducer duplicate rejection |
| Product failure leaks secrets | stable closed errors and client-safe projection callbacks |
| cancellation leaks Session/presenter authority | adopted owner, shielded compensation, dependency-ordered close |
| transport or daemon authority appears accidentally | import/AST guards reject socket, subprocess, Hosting and listener owners |
| hosted work changes local TUI | installed-entrypoint and Embedded Profile omission tests |

## Delivery Slices

| Slice | Deliverable | Exit evidence |
| --- | --- | --- |
| G11.0 | accepted boundary, requirements, inventory contract, threat model, parent adoption, architecture guards | three-view design review has no unresolved high/medium finding; no production source change |
| G11.1 | protocol values/errors/codec/schema and AppClient contract | strict round trips and rejection matrix; no runtime/listener imports |
| G11.2 | AppService registry, per-mux coordination, Session owner, attach barrier, bounded mailbox, and AppService-owned InProcessAppClient | multi-space/session concurrency, overflow, detach, cancellation, cleanup and ordering tests |
| G11.3 | Coding hosted Session adapter and identity/scope compatibility fixtures | public Harness/AppHost-contract-only adapter, create/resume/cwd/user-home evidence, bounded projection |
| G11.4 | explicit Harnesstui Hosted Mux Profile, reducer/controller/playback, inventory v4 and promotion evidence | Embedded omission, hosted behavior, dependency graph, cross-platform-safe tests and three-view implementation review |

## Evidence Contract

| ID | Proof |
| --- | --- |
| `G11-CONTRACT-STRICT` | protocol types and codec reject unknown or unbounded input |
| `G11-MUX-IDENTITY` | names, IDs, member cardinality and Product admission are enforced |
| `G11-ATTACH-BARRIER` | snapshots and later events cannot mix membership revisions or cursor order |
| `G11-MAILBOX-BOUND` | a lagged attachment cannot block another attachment or Session source |
| `G11-AGGREGATE-CONCURRENCY` | one blocked MuxSpace does not serialize an independent MuxSpace |
| `G11-CLOSE-ORDER` | detach, member close, mux close, cancellation and failure settle exact owners |
| `G11-PRODUCT-ADAPTER` | Coding uses public Harness Session controls and redacted projection only |
| `G11-SCOPE-COMPAT` | cwd and user-home candidate identity/envelope facts survive create/resume |
| `G11-HOSTED-PROFILE` | explicit Harnesstui mux reducer/controller consumes only AppClient values |
| `G11-EMBEDDED-OMISSION` | normal Coding CLI/TUI/SDK and Embedded Profile remain Current and AppService-free |
| `G11-INVENTORY-V4` | source-backed inventory records every new library surface and no installed hosted entrypoint |
| `G11-DEPENDENCY-GRAPH` | AST graph contains only accepted one-way dependencies and no process/transport owner |

## Three-View Review Contract

The G11.0 design and G11.4 implementation are each reviewed from three
independent views:

1. **Architecture and authority:** scope placement, dependency direction,
   Product neutrality, explicit activation, and unchanged Current ownership.
2. **Lifecycle, concurrency, and safety:** attach barrier, mailbox bounds,
   aggregate isolation, stale-generation fencing, cancellation, compensation,
   and close order.
3. **Contract, presentation, and evidence:** strict codec, identity/envelope
   compatibility, AppClient parity, reducer behavior, inventory, and affected
   quality gates.

High or medium findings block the next slice or final completion.  Fixes are
re-run against the same review view and recorded in this document.

## G11.0 Design Review

The three views accepted this baseline with these binding clarifications:

- architecture: `AppService` is a separate top-level semantic package; only
  the protocol and client abstractions remain in AppServer;
- lifecycle: product callbacks never run under service locks, and attachment
  overflow isolates exactly one attachment; and
- contract/presentation: G11 ends at an explicit in-process profile and cannot
  acquire an installed command by implication.

No unresolved high or medium finding remains.  Production implementation may
start only within the dependency and non-goal boundaries above.

## G11.4 Implementation Review

The final three-view review found and closed the following issues:

- **Architecture and authority:** the in-process client implementation was
  moved to AppService, while AppServer retains only the protocol and client
  interface. The exact hosted Session input port remains AppService-owned;
  A0.4 `appserver.ports` is not overloaded with runtime semantics. Generated
  dependencies and inventory v4 record the resulting one-way edges.
- **Lifecycle, concurrency, and safety:** registry, MuxSpace membership and
  attachment settlement now share one atomic commit and one lock order.
  Adopted Session cleanup survives caller cancellation, close has a bounded
  retryable debt path, lagged attachments remain detachable, and only the
  latest controller generation can mutate a Session.
- **Contract, presentation, and evidence:** failure responses and attachment
  events gained strict codecs; the schema freezes the version and operation
  vocabulary; Coding identity derives from the canonical path-free AppHost
  envelope; and the Hosted profile retains interaction identity plus detach
  authority when close fails.

The same views were re-run after these changes. No unresolved high or medium
finding remains. The profile remains an explicit library construction and no
installed entrypoint, AppHost composition, listener, IPC or daemon authority
was added.

## Exit Gate

G11 is complete only when G11.0--G11.4 are implemented, all twelve evidence
cases pass, inventory v4 matches the source tree and installed entrypoints,
the three-view implementation review has no unresolved high/medium finding,
and the same immutable head passes:

- the focused AppServer/AppService contract and architecture suite;
- `make check-apphost`;
- `make check-harnesstui`;
- `make check-harness`;
- `make check-architecture-docs`; and
- the repository's affected Linux/Windows-safe static and behavioral tests.

Passing G11 grants only an explicit in-process Hosted Mux Profile.  The exact
deferred set is: AppServer listeners; local IPC; daemon continuity; Hosting
service control; default profile/owner changes; and Current deletion.  Each
requires a separate successor goal.
