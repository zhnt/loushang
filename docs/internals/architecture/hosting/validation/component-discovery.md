# Hosting Component Discovery And Refinement

## Status

- Scope: `hosting`
- Parent: `loushang`
- Authority: descriptive — design validation input
- Design status: not-applicable
- Implementation status: not-applicable
- Owner: Loushang Hosting architecture

## Purpose

This record applies the Loushang component-identification method before fixing
the final Hosting component model. It is validation evidence, not a second
normative component inventory.

## Discovery Inputs

### Requirements and scenarios

- one-shot trusted local process hosting;
- long-lived local Worker with a non-stdio native byte channel;
- cancellation during preparation or spawn;
- child exit before publication;
- endpoint-transfer failure after process creation;
- host shutdown with several published and pending children;
- unsupported or partially capable POSIX/Windows host.

### Current facts

- `harness.workspace.process` owns materialized requests, local spawn, process
  reservations, bounded streams, exit convergence, and cleanup.
- `harness.tools.process_hosting` binds Policy/Approval/Authorization and the
  caller-owned preparation path.
- `harness.sandbox.process` owns current containment preparation and cleanup.
- `harness.worker` owns Worker launch identity, framing, supervisor, journal,
  and read-only domain adaptation.

These paths reveal reusable mechanics and existing authority seams. Their
current module boundaries are inputs, not the target component answer.

### Reference systems

- [HashiCorp go-plugin](https://github.com/hashicorp/go-plugin) demonstrates
  the value of one client lifetime owning a child process, connection, and
  cleanup. Hosting adopts that lifetime lesson, not its stdout address
  discovery, TCP-first transport, magic-cookie security posture, or immediate
  reattach surface.
- [Nomad plugin authoring](https://developer.hashicorp.com/nomad/plugins/author)
  demonstrates separation between a generic plugin mechanism and domain plugin
  contracts. Hosting goes further by leaving Plugin and Worker protocol meaning
  entirely outside the OS substrate.

Reference structure is evidence and counterexample material, not a template.

## Candidate Function Inventory

| ID | Candidate function | Important non-owner |
| --- | --- | --- |
| `HF-01` | validate immutable shell-free launch shape | Product command resolver |
| `HF-02` | reserve and release bounded process capacity | Product scheduler |
| `HF-03` | create/attach a child without cancellation leaks | Worker supervisor |
| `HF-04` | expose bounded stdin/stdout/stderr mechanics | application protocol |
| `HF-05` | converge wait, terminate, kill, close, and natural exit | domain retirement owner |
| `HF-06` | reclaim an owned process tree | Sandbox policy |
| `HF-07` | create a native host/child endpoint pair | Worker frame codec |
| `HF-08` | allowlist and transfer only the child endpoint | Plugin declaration |
| `HF-09` | close unused peer sides and detect peer closure | heartbeat policy |
| `HF-10` | atomically publish process plus host endpoint | Capability publisher |
| `HF-11` | roll back preparation, endpoint, and process in reverse order | durable restart journal |
| `HF-12` | absorb POSIX/Windows OS variation | generic fallback selector |
| `HF-13` | emit bounded neutral lifecycle observations | log store/retention owner |
| `HF-14` | provide deterministic fake seams and platform conformance | Product test policy |

## Candidate Components

| Candidate | Classification | Reason to consider |
| --- | --- | --- |
| Hosting Contract Model | logical supporting component | stable requests, leases, errors, observations, and required ports survive implementation changes |
| Process Lifetime Host | logical technical component | stable process resource and lifecycle center already spans several use cases |
| Inherited Peer Endpoint Host | logical technical component | parent/child endpoint ownership and inheritance are independent of application framing and listening endpoints |
| Child Session Host | logical functional component | owns a new atomic invariant that neither process nor endpoint owner can own alone |
| Platform Adapter Set | boundary logical component | isolates POSIX/Windows process and handle variation |
| Diagnostic Store | candidate responsibility cluster | rejected because retention/root policy belongs to consumers |
| Preparation/Sandbox Host | candidate responsibility cluster | remains a required consumer port because security meaning is Harness-owned |
| Reattach Registry | candidate responsibility cluster | deferred; v1 explicitly rejects adoption and durable PID identity |
| Service Instance Controller | candidate responsibility cluster | deferred until an accepted daemon requires detached start/stop/reconcile and durable machine-state ownership |
| Worker Protocol Host | candidate responsibility cluster | rejected from Hosting because bytes are not domain protocol |
| Generic Plugin Client | candidate responsibility cluster | rejected because Plugin topology/handshake/publication are not OS hosting |

## Function-To-Component Mapping

| Function | Primary owner | Collaborators | Explicit non-owners |
| --- | --- | --- | --- |
| `HF-01`, `HF-13` | Contract Model | Process/Session hosts | Product resolver, log store |
| `HF-02`–`HF-06` | Process Lifetime Host | Contract Model, Platform Adapter | Worker supervisor, Sandbox policy, domain retirement |
| `HF-07`–`HF-09` | Inherited Peer Endpoint Host | Contract Model, Platform Adapter | listener/accept loop, frame codec, heartbeat owner |
| `HF-10`, `HF-11` | Child Session Host | Process Host, Endpoint Host, preparation port | Capability publisher, restart journal |
| `HF-12` | Platform Adapter Set | Process and Endpoint hosts | Product/platform policy |
| `HF-14` | each component's conformance tests | fake and real platform fixtures | production diagnostics |

The mapping is mostly one-to-many around Contract Model and Platform Adapter,
and many-to-one around Child Session Host. No many-to-many cluster requires a
generic manager.

## Refinement: Split / Merge / Keep

| Candidate | Decision | Rationale |
| --- | --- | --- |
| Contract Model | keep | one stable vocabulary and port owner; analogous to a fact model, not a type dump |
| Process Lifetime Host | keep | strong resource/lifecycle center; useful without native IPC |
| Inherited Peer Endpoint Host | keep | independent parent/child OS resource with distinct inheritance and closure invariants; its narrower name prevents listener ownership drift |
| Child Session Host | keep | atomic cross-resource transaction is a stable responsibility, not a convenience facade |
| Platform Adapter Set | keep as component group | POSIX and Windows adapters differ physically but implement one boundary responsibility |
| Diagnostics | merge into owning components | records are component facts; storage/retention is external |
| Preparation/Sandbox | keep outside via required port | moving it would transfer security authority into Hosting |
| Reattach/adoption | defer | requires creation identity, durable CAS ownership, containment continuity, and a new threat model |
| Service Instance Controller | defer | daemon lifecycle has a different durable owner and trigger from an attached Child Session |
| Worker protocol/plugin client | exclude | violates mechanism-versus-meaning boundary |

The final peer set contains five objects, within the method's `3-7` review
range, and uses one consistent responsibility view: contract, two resource
owners, their transaction owner, and the OS boundary adapter group.

## Open Validation Questions

1. Which POSIX endpoint primitive provides the smallest portable full-duplex
   contract while preserving exact descriptor inheritance?
2. Which Windows primitive and Python spawn path can prove a strict inherited
   handle allowlist and bidirectional peer closure?
3. Can current sealed executable and cwd identity mechanics move without
   carrying Harness authorization meaning into Hosting?
4. Which cleanup ordering preserves the current Process Host cancellation
   guarantees when endpoint transfer fails after OS creation?

These are narrow runtime-feasibility questions for later spikes. They do not
block defining ownership, and their answers must not widen Hosting into Worker
or Sandbox semantics.
