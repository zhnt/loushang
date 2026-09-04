# Hosting Support Boundary For Hosted Applications

[Hosting](../README.md) ·
[System Context](../system-context.md) ·
[AppHost Top-Level Placement](../../drafts/apphost-top-level-placement.md) ·
[AppService Hosted Boundary](../../drafts/appservice-embedded-tui-hosted-boundary-plan.md) ·
[Application Service Refactor](../../drafts/application-service-refactor.md)

## Status

- ID: `HOST-KD-HOSTED-APPLICATION`
- Kind: key design
- Scope: `hosting`
- Parent: `loushang`
- Authority: normative proposed design
- Design status: proposed
- Implementation status: not-started
- Owner: Loushang Hosting architecture

## Purpose

This design fixes the boundary between OS hosting mechanisms and the future
hosted application stack. Hosting supplies exact process, inherited-handle,
shutdown, and machine-resource mechanisms. It does not acquire AppService,
AppServer, Product, client, or presentation semantics merely because those
systems can run in another process.

The governing rule is:

```text
Hosting owns how a local process and its OS resources live.
All protocol, application, Product, and presentation meaning stays with the
external consumer graph governed by the parent AppHost decision.
```

## Deployment Profiles

| Profile | State | Hosting participation | Consumer-side fact at the black-box edge |
| --- | --- | --- | --- |
| embedded Coding TUI | Current | bypass Hosting process services | no process/service request reaches Hosting |
| in-process AppClient | Proposed Target | bypass OS Hosting | no process or endpoint request reaches Hosting |
| foreground AppHost server over standard I/O | Proposed Target | an outer launcher may use Process Host to launch the complete AppHost executable | caller supplies only admitted serializable launch material |
| attached one-parent/one-child sidecar | Proposed Hosting Target | Child Session Host and Inherited Peer Endpoint Host own spawn, transfer, closure, and termination | consumer owns framing, handshake, RPC, and semantic recovery |
| local AppServer listener | Proposed Target | Hosting may launch the complete AppHost process but never receives or owns the listener | caller's readiness probe, not process liveness, reports application readiness |
| externally supervised service | Deferred delivery profile | systemd, launchd, Windows SCM, container, or another supervisor owns process continuity | foreground AppHost entrypoint is outside Hosting service control |
| library-managed daemon | Deferred Hosting candidate | AppHost daemon-control profile may use a future Service Instance Controller after separate acceptance | only versioned service-control inputs and readiness observations cross the boundary |
| remote or cloud AppServer | Deferred delivery profile | no Hosting dependency unless this installation launches a local process | no local request reaches Hosting in the bypass case |

An inherited peer endpoint is intentionally not a reconnectable or
multi-client listener. Reusing that primitive as an AppServer listener would
mix one child Session's ownership with independent client admission.

## External Consumer Contract

AppHost placement, sibling dependencies, Product catalog ownership, deployment
profiles, and application responsibility allocation are governed by the
parent-level
[AppHost Top-Level Placement](../../drafts/apphost-top-level-placement.md).
This Hosting child design specifies only Hosting's black-box relationship with
trusted external consumers:

| Consumer | Serializable/provided input | Hosting result | Hosting non-ownership |
| --- | --- | --- | --- |
| Harness composition | exact materialized launch request plus preparation lease | process lease or atomic child-session lease and neutral observations | Policy, Product/Worker protocol, domain publication |
| controller-process AppHost launcher | complete executable identity, argv/environment allowlist, profile and state references | process lease, bounded diagnostics, raw exit facts | target-process object graph, AppServer readiness meaning, Session recovery |
| AppHost daemon-control adapter | versioned serialized service/control specification and injected readiness probe | generic service-instance operation/result when that component is separately accepted | listener, AppService shutdown semantics, Product state |
| external supervisor | foreground executable and platform-native signal/service contract | outside Hosting library scope | all Hosting service-controller behavior |

Hosting never receives an in-memory Product factory, Runtime handle, hosted
adapter, AppService, AppServer, or presentation object. A direct foreground
AppHost executable bypasses Hosting. When a controller launches it, the entire
AppHost target executable crosses the boundary and performs its own in-process
composition.

AppServer, AppService, Product packages, and UI packages are not Hosting
consumers. In particular, every AppServer subpackage is forbidden from
importing any `loushang.hosting` package. Hosting likewise never imports those
application scopes. The parent AppHost decision owns the complete sibling
graph and responsibility table.

## Future Service Instance Controller

`hosting.service` is a candidate namespace, not an accepted package or sixth
baseline component. It becomes eligible only when a named local service must
outlive its launching client and requires independent start, stop, restart, or
reconcile operations.

The candidate Service Instance Controller would own:

- a narrow service-state directory derived once from the admitted
  `PlatformPaths.state`, never an independently resolved home or cwd;
- serialized lifecycle operations, instance epoch, and exact creation identity;
- executable identity and stale process-record fencing;
- idempotent start, stop, restart, inspect, and reconcile mechanics;
- idempotent retire/removal of its mechanism-only record after the matching
  process tree is confirmed reaped, with conservative residue on cleanup
  failure;
- readiness scheduling through an injected probe; and
- a bounded launch-diagnostic handle containing mechanism facts only.

Its bounded stop state machine is mechanism-only and convergent: issue the
injected application stop request, wait the configured grace interval, then
terminate, wait, kill the owned process tree, reap, close process handles, and
publish raw exit/timeout facts. Failure in an earlier step never skips reachable
reclamation. It cannot translate forced termination into successful
AppService/Session closure.

It would not own:

- the App protocol or AppService lifecycle;
- listener choice, connection authentication, framing, or slow-client policy;
- application aggregate identity, membership, attachment/controller state,
  multi-stream ordering, cardinality, or recovery;
- Product Session recovery, transcript truth, durable Work, or reconnect
  cursor semantics;
- installation, upgrade, general system-service management, log retention, or
  remote deployment.

Only a parent-approved AppHost daemon-control profile may consume this
mechanism. From Hosting's black-box perspective, the external consumer supplies
a versioned, serialized application readiness/stop adapter; Hosting schedules
and observes it without interpreting listener, application, Session, or Product
state. External-supervisor profiles bypass this candidate. The parent
[AppHost Top-Level Placement](../../drafts/apphost-top-level-placement.md) owns
the target-process mapping and sibling orchestration. Promotion requires its
own requirements, system context, component discovery, and acceptance gate
under the architecture method.

## Hosting Resource Contract

The parent
[AppHost Top-Level Placement](../../drafts/apphost-top-level-placement.md) and
accepted
[Machine-Local Runtime Storage](../../harness/machine-local-runtime-storage.md)
decision govern cross-scope placement. At Hosting's black-box edge:

- each controller or target process receives one immutable, admitted path
  value from its own composition root; Hosting never rereads cwd, home, or path
  environment variables;
- a child-session lease owns only Hosting-created process, endpoint, bounded
  stream, and rollback-temporary resources for that lease lifetime;
- launch diagnostics are bounded mechanism facts routed to the caller-owned
  observability sink; Hosting owns no log-retention policy;
- a future service record contains only exact process/control facts in an
  injected narrow state directory; and
- Hosting never treats a process lease, run lease, or service record as
  authority over transcripts, Session Blobs, application snapshots, listener
  state, clipboard drafts, or Product artifacts.

## Acceptance Invariants

1. A controller-process AppHost launcher supplies only an admitted complete
   executable and serializable launch material; Hosting never receives an
   application object graph.
2. The returned process/child-session lease and raw observations contain no
   listener, protocol, application, Session-recovery, Product, or UI semantics.
3. Application readiness and stop behavior enter only through a narrow injected
   required port; Hosting does not import the consumer that implements it.
4. A daemon cannot enter the baseline by renaming Child Session Host; it
   requires the Service Instance Controller trigger and architecture review.
5. Every Hosting-created process, endpoint, process record, launch diagnostic,
   and rollback temporary has exactly one lifecycle owner.
6. Running one or many application coordination aggregates does not change the
   Hosting request, lease, readiness, service record, or process lifetime; only
   the opaque AppHost target can interpret that application state.

## Deferred Decisions

- AppHost component/module details governed by the parent-level placement;
- whether the first AppServer transport is standard I/O, a local listener, or
  another accepted connection profile;
- whether `hosting.service` is justified by a real daemon requirement; and
- concrete public API names, which this proposed design does not reserve.
