# Plugin Lifecycle PLC9C Local Worker Boundary

## Status And Authority

- Slice: PLC9C.0 baseline plus PLC9C1--PLC9C4 internal Worker mechanism.
- Implementation base: `90f6a9de` on `main` / `lane/harness`.
- Delivery branch: `harness/plugin-plc9c-worker-containment`.
- Status: reviewed implementation candidate. Architecture,
  security/lifecycle, and Product/test perspectives accepted C1--C4 after
  closing version coupling, protocol bounds, transport ownership, durable
  failure cleanup, shutdown classification, and authority-revocation findings.
- Local evidence: `make check-harness` passed with Ruff, mypy over 673 source
  files, and 4,268 tests passed with 38 expected platform skips.
- Default runtime effect: none. PLC9C1--PLC9C4 add an inert versioned
  `local_worker` declaration, an owner-only launch capability, a bounded
  protocol/supervisor, and one explicitly enabled read-only Capability query
  adapter. The adapter is disabled by policy unless its composition root passes
  `enabled=True`. No Product activation route, native IPC binding, author-SDK
  runtime owner, generation publisher, or remote-service client is added.

This baseline refines the
[PLC9.0 Local Worker Boundary](plugin-lifecycle-plc9-baseline.md#local-worker-boundary)
against the current source-backed
[PLC9 inventory](plugin-lifecycle-plc9-inventory.md#execution-and-containment-seams).
Current source and executable tests remain authoritative for implemented
behavior. PLC9C5 must revise this document and inventory in the same change
that introduces Product activation or native IPC/platform evidence.

## First-Principles Decisions

1. **Execution topology is not acquisition.** `local_worker` is a versioned
   contribution execution model. It is not a declaration source kind, Package
   source, install mechanism, or remote-service alias.
2. **Declaration is inert intent.** A decoded Worker declaration can name a
   protocol and request policy facts, but cannot mint process, filesystem,
   network, credential, Sandbox, publication, or Product authority.
3. **Admission precedes the OS spawn.** Current Plugin revision, exact
   contribution identity, Policy, mandatory Approval, Authorization, and the
   sealed launch request are established before entering Process Host. Process
   Host may then reserve bounded capacity while its owner-scoped callback
   creates and verifies required containment. The Sandbox-owner plan and all
   final identity checks must succeed before the OS spawner is called. Degraded
   or best-effort containment never admits a Worker.
4. **Mechanism and domain meaning stay separate.** Process Host owns bounded
   reservation, child lifetime, and I/O. Sandbox owns containment. The
   product-neutral Worker transport/supervisor owns framing, session protocol,
   heartbeat, correlation, and process shutdown. The exact domain Worker
   adapter and existing domain owners retain semantic admission, Host-side
   actions, generation publication, and retirement. Plugin management owns none
   of those effects.
5. **A child is not an authority.** A Worker receives a bounded protocol, not a
   registry, owner registrar, Store, management ledger, generic launcher, raw
   Process Host, Sandbox planner, or inherited ambient credential.
6. **Handshake is not publication.** A spawned process publishes nothing until
   the exact protocol/version, Plugin revision, contribution, session nonce,
   and domain owner admission all match. Process exit never implies domain
   retirement or cleanup success.
7. **Remote service is a separate topology.** `remote_service` remains absent
   and requires a separate threat model covering identity, authentication,
   egress, tenancy, residency, revocation, and failure semantics.

## Implemented Facts And Retained Absences

At the PLC9C1--PLC9C4 candidate:

- `PluginDeclarationSourceKind` is exactly `document | in_process`;
- `PluginContributionExecutionModel` is exactly
  `data_only | in_process | local_worker`; legacy contribution index v2,
  declaration IR v2, and document v1 retain their exact prior meaning, while
  index v3, IR v3, and document v2 are reserved for a document-sourced,
  explicitly versioned local Worker topology;
- `loushang.plugin` exports no Process Host, Sandbox, management, Worker, or
  remote-service owner;
- `ScopeBoundProcessLauncher.start()` is the generic authorized launch path and
  rejects private managed requests;
- `ScopeBoundProcessLauncher._start_managed()` is private substrate guarded by
  a Process-owner-minted launcher, mandatory Approval, and `required`
  containment;
- `SandboxExecutionRuntime.bind_process_launcher()` remains the Process/Sandbox
  composition root for the generic launcher, while
  `bind_managed_worker_launch_port()` mints a separate capability over the same
  privately owned Process Host and required-containment planner;
- managed Skill actions prove that the private managed substrate can be
  composed without making it a Worker contract;
- `CapabilityComponentHost` and `CapabilityOwnerComponentHost` prepare
  bindings and explicitly do not publish a generation; Capability owner
  generation publication is owned by `CapabilityOwnerComponentRuntime` and
  `CapabilityOwnerComponentBinder`, alongside exact Resource and Continuity
  owners such as `PreparedResourceOwnerGeneration` and
  `PluginContinuityProvider`; a Worker transport cannot replace them; and
- `WorkerRuntimeBindingV1` seals the contained executable/cwd identity before
  `ManagedWorkerLaunchPort` enters the existing private managed Process path;
- the bounded canonical-JSON frame protocol and `WorkerSupervisor` own exact
  handshake identity, direction/state validation, correlation, heartbeat,
  cancellation tombstones, shutdown, crash fencing, durable attempt epochs,
  and restart budgets; and
- `CapabilityQueryWorkerAdapter` admits only one exact read-only Capability
  allowlist, revalidates authority before and after every result, publishes
  nothing, and is disabled by policy by default.

The existence of Process Host, a Sandbox backend, or the managed Skill path is
not evidence that a Plugin Worker is admitted.

## Threat Model

Treat a local Worker as untrusted code from an already verified immutable
Plugin revision. Verification establishes artifact identity; it does not make
the code safe or grant runtime authority.

PLC9C must defend against:

- declaration spoofing, unknown-version downgrade, and topology/source-axis
  confusion;
- direct use of a generic or raw launcher to bypass Worker admission;
- containment unavailable, degraded, replaced, or changed between planning and
  spawn;
- executable, cwd, Plugin revision, contribution, Product/scope, or policy
  identity changing after admission;
- inherited descriptors, environment secrets, credentials, an unbrokered
  writable cwd, ambient network, or unbounded child creation;
- handshake replay, cross-session/cross-Plugin connection, protocol downgrade,
  oversized or malformed frames, request smuggling, and reply confusion;
- effect requests that bypass current Policy, Approval, Authorization, Sandbox,
  or audit by being labeled as Worker protocol messages;
- stdout/stderr, request queues, response bodies, heartbeats, shutdown, or
  restart loops exhausting host resources;
- stale Worker output publishing into a successor owner generation; and
- crash, cancellation, or host restart being reported as successful domain
  retirement, cleanup, or publication rollback.

PLC9C3 selects a bounded canonical-JSON frame protocol over an injected,
already-owned byte transport. Native IPC activation remains in PLC9C5; C1--C4
therefore make no Linux/Windows handle-inheritance claim. Explicit version
negotiation, host-generated correlation/nonces, ordered shutdown, and the
distinction between transport, protocol, domain, containment, and process
failures are executable contracts now.

## Target Ownership And Dependency Direction

```text
versioned inert Plugin declaration
  -> Product selection and exact domain Worker adapter
     -> owner-only ManagedWorkerLaunchPort
        -> Policy -> Approval -> Authorization
           -> Process Host capacity reservation
              -> required Sandbox containment + final identity verification
                 -> OS spawner

Worker <-> bounded transport/session protocol <-> Worker supervisor
                                                  -> exact domain Worker adapter
                                                     -> domain owners
```

The Process/Sandbox composition root mints `ManagedWorkerLaunchPort` only after
it binds an exact required-containment
planner and Process-owner launch authority. The port accepts an already
domain-bound Worker launch request; it does not accept arbitrary Tool requests
or expose the generic launcher.

The product-neutral Worker transport/supervisor owns only mechanism:

- bounded framing and transport lifetime;
- protocol-version negotiation, one fresh session/attempt nonce, heartbeat,
  request/reply correlation, cancellation tombstones, and ordered process
  shutdown; and
- enforcement of the Product/domain-provided restart budget under one durable
  supervisor lease and epoch.

The exact domain Worker adapter and existing domain owners retain meaning:

- Plugin revision, contribution, Product/scope, and owner-generation binding;
- semantic message admission and reconstruction of every effectful request as
  an exact Host-side action; and
- publication, rollback, revocation, and retirement through the existing
  domain generation owner.

The Worker supervisor may observe Process Host, Sandbox, and domain evidence,
but it does not synthesize their truth or publish a contribution. A domain
adapter consumes the narrow supervisor session port; it does not depend on
Process Host or Sandbox implementations. The management read model may project
those independently revisioned facts, but it does not become a supervisor.

Forbidden reverse edges include Process Host or Sandbox importing Plugin
declarations, a Worker importing owner registrars or management ledgers,
Plugin management launching a process, and the author SDK importing concrete
Harness runtime owners.

## Lifecycle And Failure Separation

PLC9C runtime work keeps at least these facts distinct:

| Fact | Sole owner | Required evidence |
| --- | --- | --- |
| declaration decoded/selected | Plugin declaration and Product selection owners | exact IR/document version and contribution fingerprint |
| launch admitted | domain adapter plus Process/Sandbox composition | current revision/scope, Policy, Approval, Authorization, required containment, sealed launch identity |
| process spawned/running/exited | Process Host | process identity, bounded streams, exit/termination receipt |
| containment active/degraded/failed | Sandbox owner | owner-bound plan and current containment evidence |
| protocol handshaken/healthy/lost | product-neutral Worker transport/supervisor | negotiated version, single-use nonce, peer binding, heartbeat/correlation evidence |
| semantic request admitted/refused | exact domain Worker adapter | Plugin/contribution/scope/generation binding and Host-side action evidence |
| generation published/draining/retired | exact domain generation owner | admission, publication, revocation, drain, and retirement receipts |

Failures must remain independently diagnosable: unsupported declaration,
containment unavailable, approval denied, authorization denied, launch failure,
protocol mismatch, handshake timeout, heartbeat loss, frame/queue/output limit,
unexpected exit, cancellation, shutdown failure, and restart-budget exhaustion
must not collapse into a false generic success.

A restart policy is Product/domain policy enforced by the supervisor over
durable attempt evidence. It is not a loop inside Process Host. Each attempt
has a durable `attempt_id`, supervisor epoch, and exclusive lease. PID alone is
never process identity. The first production route does not adopt a surviving
Worker after supervisor/Host loss: it fences the old protocol/generation,
proves the exact process tree terminated, and only then starts the bounded,
contiguous next attempt. If termination or fencing cannot be proved, restart
fails closed. Live adoption is deferred to a separately reviewed slice that
would additionally require process-creation identity, current containment
ownership, a fresh challenge, and single-owner CAS evidence. Exhaustion remains
terminal until an explicit operator or Product decision.

PLC9C3 must also prove these protocol invariants rather than merely name the
risks:

- validate the frame length against a fixed bound before allocating or
  decoding its body;
- admit only the message kinds legal for the current direction and protocol
  state;
- bind the fresh nonce once to the exact supervisor epoch, `attempt_id`,
  Session, Plugin revision, contribution, and owner generation;
- reject duplicate, unknown, or late replies, including replies that arrive
  after a cancelled request; cancellation leaves a bounded correlation
  tombstone;
- keep stdout/stderr as bounded diagnostics, never as the semantic protocol;
  and
- treat malformed input, state violations, queue/output exhaustion, and peer
  closure as explicit protocol/supervisor failures before any domain action or
  publication.

## Product Failure And Rollback Matrix

Product status keeps `available`, `degraded`, `unavailable`, and
`disabled_by_policy` distinct. A bounded reason category distinguishes at least
unsupported platform, containment unavailable, approval/authorization denial,
launch failure, protocol/handshake failure, runtime loss, resource limit, and
restart exhaustion. Later wire contracts may version the exact enum spelling,
but may not collapse these facts or expose paths, commands, credentials, raw
protocol frames, or native handles.

| Contribution and failure point | Product/session result | Generation and process result |
| --- | --- | --- |
| required; pre-spawn admission fails | candidate activation fails atomically and reports `unavailable`; a currently ready Product/session remains current | no OS spawn and no generation publication |
| optional; pre-spawn admission fails | candidate may activate as `degraded` with the contribution explicitly unavailable | no OS spawn and no publication for that contribution |
| required; spawned but handshake/domain admission fails before publication | candidate activation fails atomically and reports `unavailable` | terminate the owned process tree; current accepted generation is unchanged |
| optional; spawned but prepublication admission fails | candidate may activate as `degraded` | terminate the owned process tree; omit only that contribution |
| required; runtime loss after publication | the active Product/session becomes `unavailable` until explicit recovery or replacement; it cannot continue to report ready | fence the attempt immediately, reject late messages, and revoke/drain the exact domain generation before bounded restart |
| optional; runtime loss after publication | Product/session becomes `degraded` while unrelated contributions remain usable | fence the attempt and publish/retain only an owner-authorized successor without the failed contribution |
| Product kill switch | new sessions/attempts report `disabled_by_policy`; no new Worker starts | existing attempts are fenced, drained, and terminated through their owners; process exit alone does not settle retirement |

A predecessor generation is retained only while its existing owner still
considers it current and healthy; it is never resurrected from cached Worker
state. An in-process or alternate Worker fallback must have a distinct
implementation/contribution identity and an explicit Product selection
receipt, then pass its own admission. Absence of that evidence means no
fallback. `local_worker` is never reinterpreted as `in_process`, and required
does not silently become optional.

## Delivery Slices

| Slice | Scope | Exit gate |
| --- | --- | --- |
| PLC9C.0 | this design baseline, threat model, current-source inventory, and absence guards | three-view design review passes; no runtime behavior changes |
| PLC9C1 | additive versioned `local_worker` IR/codec and compatibility fixtures | old versions retain exact meaning; unknown/partial Worker records fail closed; decoding has no effects |
| PLC9C2 | owner-only `ManagedWorkerLaunchPort` minted by Process/Sandbox composition | Process Host owns the capacity reservation; required containment and final owner/identity evidence pass before the OS spawner; generic/raw bypasses fail |
| PLC9C3 | product-neutral bounded transport/session protocol and supervisor | framing, nonce, heartbeat, correlation, limits, cancellation, shutdown, crash fencing, exclusive supervisor epoch, and restart budget have independent evidence |
| PLC9C4 | one read-only, low-authority domain adapter and vertical slice | semantic actions remain Host-side; no publication before handshake/domain admission; stale/crashed Worker cannot publish or retire a generation |
| PLC9C5 | Product activation, recovery, native platform evidence, and rollback | Linux/Windows required-containment gates and cross-entrypoint conformance pass without fallback |

PLC9C1 must not reinterpret declaration IR v2 or document v1. It introduces an
additive versioned shape with explicit compatibility behavior. PLC9C2 must not
make private underscore-prefixed Process mechanics public; it introduces one
narrow owner port at their existing composition boundary. PLC9C4 starts with a
read-only, capability-poor contribution rather than granting a Worker mutation,
deletion, credential, or arbitrary execution authority.

Guard revisions are intentionally incremental:

| Slice | Guard intentionally revised | Guards retained |
| --- | --- | --- |
| PLC9C1 | only the declaration-local `local_worker` absence and exact current IR-version assertions in this file and `test_plugin_lifecycle_plc9_baseline.py` | `remote_service`, runtime owner exports, launch port, supervisor/protocol, spawn, and publication remain absent |
| PLC9C2 | only `ManagedWorkerLaunchPort` absence and its Process/Sandbox composition inventory | protocol/supervisor, domain adapter/publication, author runtime owners, and `remote_service` remain absent |
| PLC9C3 | only protocol/supervisor absence after bounded state-machine evidence lands | domain publication/retirement, author runtime owners, and `remote_service` remain closed |
| PLC9C4 | only the selected domain-adapter absence after its conformance evidence lands | other domains, mutation/deletion authority, public runtime owners, and `remote_service` remain closed |
| PLC9C5 | Product activation absence for the accepted vertical slice | unsupported platforms, undeclared fallbacks, other domains, and `remote_service` remain fail-closed |

The guard-transition ledger is append-only at the slice boundary:

| Transition | Guard ledger action |
| --- | --- |
| PLC9.0 -> PLC9C.0 | retain `test_plugin_lifecycle_plc9_baseline.py`; add this source-backed owner/import/absence guard without weakening the earlier baseline |
| PLC9C.0 -> PLC9C1 | revise only codec/version assertions in both guards in the same commit as the additive compatibility fixtures |
| PLC9C1 -> PLC9C2 | remove only the launch-port absence token after Process/Sandbox owner-composition tests pass |
| PLC9C2 -> PLC9C3 | remove only named supervisor/protocol absence tokens after bounded state-machine, crash-fence, and restart-budget tests pass |
| PLC9C3 -> PLC9C4 | remove only the selected domain-adapter absence token after exact semantic-admission and generation-owner conformance passes |
| PLC9C4 -> PLC9C5 | remove only the accepted Product-activation/platform absence guard; every unlisted environment and undeclared fallback remains closed |

Computed imports, reflection, aliases, and callable laundering do not bypass a
retained guard. Static tests cover direct and relative imports; review and
runtime conformance cover dynamic construction until a stronger repository
rule replaces them.

## Rollback, Recovery, And Native Evidence

Omitting a `local_worker` declaration is the pre-C1 rollback state and retains
the exact current `data_only/in_process` behavior. Once a Worker declaration is
accepted, rollback disables that contribution or selects a compatible
in-process implementation only through Product policy; it never silently
reinterprets `local_worker` as `in_process`.

Recovery reopens durable owner evidence and observes the exact Process,
Sandbox, protocol, and domain-generation state. The first production route
fences and terminates the prior attempt before a bounded restart; it does not
adopt a surviving Worker. It cannot infer health from a PID, infer containment
from process existence, or publish from cached handshake state.

Platform simulations may test pure codecs and state machines but cannot promote
a native containment, handle inheritance, termination-tree, or crash-recovery
row. Every platform decision occurs before the OS spawner and emits a stable,
bounded unsupported-platform or containment-unavailable reason.

| Environment | PLC9C1--PLC9C4 disposition |
| --- | --- |
| native Linux | eligible only after retained native required-containment, inheritance, process-tree termination, and crash-fencing evidence |
| native Windows | eligible only after the corresponding retained native Job/AppContainer or accepted peer evidence |
| macOS | unsupported/fail-closed until an accepted required-containment backend and native evidence exist |
| WSL | a distinct host profile; it does not inherit native Linux acceptance and requires its own containment/termination evidence |
| container-hosted Harness | classified by the actual host/backend pair; container presence alone is not Worker containment evidence |
| every unlisted OS/environment | unsupported/fail-closed; never downgraded to best effort |

## Frozen Forbidden Routes

Until PLC9C5 intentionally revises these guards:

- `local_worker` and its Worker configuration exist only in the additive
  internal index-v3/IR-v3/document-v2 codec; `remote_service` remains absent,
  and the author SDK exports neither topology nor runtime owner objects;
- `ManagedWorkerLaunchPort` may be minted only by
  `SandboxExecutionRuntime.bind_managed_worker_launch_port()` and is not a
  generic process-launch surface;
- no Worker/domain module may construct or call raw `ProcessHost`,
  `LocalSandboxService`, `HostedProcessContainmentPlanner`, private managed
  request builders, or generic `ScopeBoundProcessLauncher.start()`;
- Plugin management may not import Process Host/Sandbox or launch a Worker;
- a failed/degraded required-containment decision may not reach spawn;
- handshake or PID existence may not publish a contribution by itself;
- Worker messages may not carry a registrar, Store, ledger, native path/handle,
  ambient credential, or generic execution capability; and
- `remote_service` may not be introduced as a union arm or compatibility alias
  of `local_worker`.

## PLC9C1--PLC9C4 Exit Gate

PLC9C1--PLC9C4 are complete only when:

- this document is indexed by the active Plugin architecture catalog;
- the source-backed inventory names the versioned declaration, Process Host,
  generic and private managed launch, Worker launch capability, Sandbox
  composition, protocol/supervisor, read-only domain adapter, retained
  generation owners, and missing Product/native activation seams;
- architecture tests freeze codec compatibility, owner boundaries, default
  dark state, author-SDK exclusion, and retained topology absences;
- architecture, security/lifecycle, and Product/test reviewers independently
  accept the corrected implementation with no unresolved high/medium risks;
- targeted and Harness gates pass without enabling a production route; and
- the change contains no PLC9D cleanup/retention or PLC9E compatibility
  deletion.

Passing PLC9C1--PLC9C4 permits a separately reviewed PLC9C5 Product/native
activation change. It does not pre-approve an IPC platform binding, Sandbox
backend, Product recovery policy, public SDK surface, generation publication,
or remote topology.
