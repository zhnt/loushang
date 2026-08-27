# Plugin Management And Isolated Execution Architecture Review

## Status

- Authority: descriptive — independent architecture validation evidence
- Artifact type: validation
- Reviewed design status: proposed
- Implementation status: not-applicable
- Owner: Loushang architecture review

This is an independent architecture review of
[`plugin-management-and-isolated-execution-improvement-plan.md`](../plugin-management-and-isolated-execution-improvement-plan.md).

This review evaluates consistency with the current owner, Capability Graph,
Plugin-management, execution, and process-hosting boundaries. It is not an
acceptance decision and does not modify the reviewed proposal.

The review checked the current source and the following authoritative or
coordinating documents:

- [`Unified Plugin Architecture`](../../../harness/plugin/architecture.md),
  especially its execution approval, exact-owner, projection, management,
  instance, package-cache, restart, and isolated-worker rules;
- [`Unified Plugin Lifecycle And Coding Pluginization Delivery Plan`](../../../harness/plugin/plugin-lifecycle-coding-pluginization-plan.md),
  including the implemented PLC2 through PLC5.1a status and the unimplemented
  PLC6 through PLC9 scope;
- [`Harness Process Hosting Boundary`](../../../harness/process-hosting-boundary.md)
  and [`Harness Workspace Execution Boundary`](../../../harness/workspace-execution-boundary.md);
- `src/loushang/harness/plugin_management/service.py`,
  `instance_runtime.py`, `package_lifecycle.py`, and their record families;
- `src/loushang/harness/workspace/process`,
  `src/loushang/harness/tools/process_hosting.py`,
  `src/loushang/harness/sandbox/runtime.py`, and
  `src/loushang/harness/workspace/exec`; and
- the management, instance-runtime, package-lifecycle, Process Host, Sandbox,
  and Exec regression suites.

No implementation or test execution was performed for this review.

## Verdict

**Revise before architecture acceptance.**

The proposal's central decisions are sound:

- Skill scripts must be executable without becoming ambient in-process Plugin
  code;
- untrusted executable providers need isolated processes;
- process isolation must not be misreported as a Sandbox;
- one-shot scripts and long-lived Workers need different lifecycle mechanics;
- Worker messages must be typed, bounded, and incapable of direct owner
  publication; and
- plan/apply is appropriate only for durable external mutations.

The proposal is not yet safe to schedule as written. It currently introduces
three architecture-level ambiguities that can become a second authority or
state machine:

1. a single new `effect class` taxonomy competes with the existing composable
   `ToolEffect`, requested-authority, Policy, and
   `EffectiveExecutionProfile` contracts;
2. `PluginWorkerSupervisor` appears to own drain, quarantine, repair, update,
   rollback, readiness publication, and a durable Worker generation despite
   existing Plugin Instance, exact contribution owner, Session, Process Host,
   and package-cache owners; and
3. the generic Effect Broker/plan state appears capable of owning durable
   external mutation instead of leaving that state machine with its exact
   Product/domain owner.

The PM0 gate correctly says these questions must be resolved, but the later
normative text already assigns the conflicting ownership. PM0 therefore needs
concrete required resolutions, not only an open-decision list.

## Evidence Baseline

### Existing lifecycle and management are narrower and more complete than the
proposal states

`PluginManagementService` is currently the sole command authority over inert
desired state. Its implemented command families perform install-disabled,
enable, disable, remove, and staged update/CAS operations; they journal exact
idempotency and hand retirement intent into the existing retirement-set
ledger. The current V1 command state is only
`accepted -> running -> terminal`; it does not yet own package acquisition,
owner execution, process restart, Approval waiting, or general repair.

`PluginInstanceRuntimeLedger` already owns durable direct-host Instance state
and lease families:

```text
ACTIVE -> DRAINING -> RETIRED
ACTIVE -> REVOKING -> RETIRED
DRAINING -> REVOKING
```

`PluginPackageLifecycleLedger` already implements package pins, cleanup tasks,
recovery barriers, GC-candidate derivation, and recheck. The remaining delivery
work must extend and connect these records; it must not introduce a parallel
retention or Worker-retirement ledger.

### Existing process hosting is Session-owned and deliberately private

The accepted Process Hosting boundary provides a Product-neutral,
**Session-owned** `ProcessHost` and exposes only
`AuthorizedProcessLauncher` as the consumer port. `ProcessHost`, its transport,
reservations, spawner, and signaling stay internal. The launcher protects each
spawn through Policy, Approval, audit, an execution-profile ceiling, Sandbox
containment planning, and fixed Host limits.

The current `SandboxExecutionRuntime` constructs and closes that Process Host
for one Session runtime. Consequently, the existing substrate can directly
support a Session-owned Worker. It does not yet prove a workspace- or
process-scoped daemon that survives the Session which supplied its launcher.

### Existing one-shot Exec is mechanics, not a complete authorized script port

`ExecService` materializes cwd and environment and owns bounded one-shot
request/result execution, cancellation, process-tree termination, streaming,
and artifacts. Its accepted boundary explicitly says that it does not freeze
executable lookup, executable bytes, or arbitrary files opened by a child.

Policy and Approval are presently layered through Tool/Product adapters, while
Sandbox can wrap an `ExecService`. There is no public equivalent of
`AuthorizedProcessLauncher` that by itself accepts a verified Skill script,
binds an exact package handle, authorizes its full effect set, and proves that
the same admitted script identity reached the interpreter. PM2 therefore
requires a new narrow adapter above Exec; it cannot claim that the complete
authorized script boundary already exists.

### Existing effective state has exact projectors and independent clocks

The Unified Plugin Architecture permits a Plugin inventory projector to retain
package and selection facts plus opaque references to already-published owner
facts. It forbids that inventory from inferring Graph, Resource, Tool, or Model
Input effectiveness. CLI/RPC/UI may combine Plugin inventory with the existing
Effective Runtime view, preserving visible cross-owner skew; the management
service must not create a synthetic fifth effective generation.

## Findings

### Critical

#### C1. The mandatory single `effect class` is a competing authority model

The proposal requires every declaration and invocation to have **one** of
`compute_only`, `workspace_read`, `workspace_write`, `process_exec`,
`network_client`, `external_mutation`, or `host_control`. Real script and Worker
operations are not mutually exclusive: a generator can read and write the
workspace, invoke a compiler, and contact a package endpoint in one admitted
operation.

Current source already models this as a tuple of concrete `ToolEffect` values
(`FilesystemEffect`, `ProcessEffect`, `NetworkEffect`, and
`PublicationEffect`) plus an independently constrained
`EffectiveExecutionProfile`. Plugin declarations separately carry sorted
requested authorities and an allowed authority ceiling. Replacing this with,
or layering policy selection on, one ordinal-looking class would either lose
authority detail or produce two policy interpretations.

Required correction:

- make effect requirements an additive, owner-qualified set using the existing
  effect/authority vocabulary;
- keep the effective Sandbox profile as the non-widening enforcement value;
- allow a derived risk/UX label such as `external_mutation`, but state that it
  is diagnostics only and grants no authority; and
- add new effect record kinds only through the existing `ToolEffect`/Policy
  subject versioning path, not through a Plugin-only classifier.

The four proposed execution shapes also need to be mapped to existing semantic
axes. `trusted_in_process` is partly a trust classification,
`oneshot_process` is a call lifecycle, and `isolated_worker` is a launch
topology. They must not silently replace the implemented
`PluginContributionExecutionModel = data_only | in_process` field. The ARD
must say exactly which existing codecs advance, which new declaration-source
arm evaluates declarations out of process, and which script metadata remains
inside the Resource owner's schema.

#### C2. `PluginWorkerSupervisor` is assigned ownership already held elsewhere

The proposed Supervisor owns:

```text
reserved -> starting -> handshaking -> ready -> draining -> stopped
                                  -> failed -> quarantined/repairable
```

It also receives update/drain/rollback responsibility, crash-loop quarantine,
Worker generation, readiness publication, and management stop/restart. This
collides with at least four existing authorities:

- `PluginInstanceRuntimeLedger` owns direct-host ACTIVE/DRAINING/REVOKING/
  RETIRED state and lease release;
- the exact Capability/Resource/Extension/external-service owner owns
  contribution publication, routing, drain, and retirement;
- `ProcessHost` owns process reservation, handle, exit, termination, and close;
- the package lifecycle owner owns package quarantine, repair, and GC facts.

`quarantined` is especially unsafe as a Worker state because it is already a
materialized-package security state. `repairable` is a diagnostic/operation
disposition, not a stable runtime state.

Required correction:

- define the Supervisor as an internal protocol/attempt coordinator, never a
  Registration owner, management writer, package-state owner, or effective
  projector;
- bind each attempt to an existing `PluginInstanceRevisionRef`, exact owner
  generation reference, activation-use reservation, Session/runtime scope,
  and `ProcessHandle`;
- call its identity `workerAttemptId` (or another explicitly non-owner term),
  not an independent effective `Worker generation` clock;
- let handshake/health produce a prepared service candidate; only the exact
  owner may make that candidate visible;
- let the exact owner stop routing and request drain, while Process Host owns
  physical termination and Plugin Instance retirement waits on its direct-host
  lease; and
- report crash-loop suppression as an owner/policy diagnostic. Only verified
  compromise evidence may quarantine package bytes through the package owner.

The architecture diagram must show the exact Component Host/owner between
selection/admission and the Supervisor. A direct
`PluginManagementService -> PluginWorkerSupervisor` control arrow is too broad.
Management may commit desired state and durable operational intent, but it
cannot directly publish, replace, or dispose a Worker-backed contribution.

#### C3. Generic plan/apply ownership would create a second domain state machine

The proposal says the Host owns operation journals, checkpoints, effect
receipts, a canonical ChangeSet, partial/unknown results, and reconcile. It
also includes durable mutation planning/application as an Effect Broker facet.
Without an exact owner, this becomes a generic infrastructure controller inside
Plugin execution.

The accepted Unified Plugin Architecture requires irreversible external
effects to be admitted, recorded, and compensated by their **domain owner**.
Plugin management, a Worker supervisor, and a generic broker do not know the
domain's read consistency, target identity, drift semantics, safe retry,
compensation, or repair rules.

Required correction:

- make `ChangeSet`, refresh, apply receipt, partial/unknown outcome, reconcile,
  and migration schema owner-qualified domain contracts;
- let Harness provide only shared strict envelopes, approval-subject binding,
  idempotency fields, transport, redaction, and fault-injection fixtures;
- let the exact Product/domain owner persist and recover the operation journal;
- let the Effect Broker mediate concrete admitted effects after the domain
  owner has selected them; and
- do not make PM4 a prerequisite for ordinary Skill scripts or Worker SDK
  delivery. Start it only when a real domain owner and mutation semantics exist.

### High

#### H1. Worker scope is unresolved, but the plan assumes the current launcher
supports all Plugin scopes

The decision matrix says a stateful Skill uses a Session-owned Worker lease,
while the handshake and management UX are general over Product/Plugin Instance
identity and restart. The existing `AuthorizedProcessLauncher` is bound to a
Session-owned `SandboxExecutionRuntime`; it cannot be assumed to host a
workspace-scoped shared indexer or process-scoped Provider after that Session
closes.

Worker V1 must choose one of these explicit scopes:

1. constrain V1 to Session-owned Workers and prove Session close, Plugin
   Instance lease release, and exact owner retirement; or
2. accept a separate workspace/process-owned execution runtime, containment
   lifecycle, quota owner, shutdown/recovery barrier, and authorization scope
   before implementing shared Workers.

Option 1 is the smaller safe first delivery. Cross-Session pooling should not
be smuggled into a Worker SDK as an implementation detail.

#### H2. Management commands, author tooling, queries, and composite projections
are conflated

The proposal sends `validate`, `pack`, `list`, `inspect`, `status`, `explain`,
and `diff` as typed durable commands to `PluginManagementService`. Those are not
all management mutations:

- `validate` and `pack` are authoring/build operations;
- `list`, `inspect`, `status`, `explain`, and `diff` are queries/projections;
- install/enable/disable/update/remove and explicit repair/data deletion are
  durable mutations; and
- Worker restart is an owner-coordinated runtime operation, not a direct
  desired-state write.

The existing service currently owns only inert desired-state command families
and retirement-intent handoff. Expanding it to read and synthesize all owner
state would violate the accepted Plugin inventory/Effective Runtime projector
split.

Required correction:

- keep versioned durable mutation commands on `PluginManagementService`;
- put validate/pack behind a side-effect-free authoring service using the
  canonical parser and package authority;
- expose Plugin inventory/status through the accepted read model/projector;
- compose `explain` at an adapter/presentation boundary from immutable
  management inventory and existing Effective Runtime snapshots, showing their
  independent revisions and missing evidence; and
- define Worker stop/restart as a typed operational intent whose exact owner
  performs and records the resulting retirement/activation evidence.

#### H3. PM2 overstates the current one-shot execution seam

The phrase "existing authorized one-shot execution boundary" and the PM2
`ExecService` row imply that Exec already binds immutable script identity and
Policy/Approval/Sandbox in one consumer port. It does not. `ExecService`
freezes cwd/environment and owns process mechanics; current Tool/Product layers
provide authorization, and executable lookup/bytes are explicitly outside the
Exec materialization guarantee.

PM2 should deliver an internal `AuthorizedSkillScriptExecutor` (name
illustrative) above `ExecService`. It must:

- accept only an owner-admitted Skill script descriptor and a leased
  `VerifiedRevisionHandle`;
- construct shell-free argv and a frozen environment without exposing raw
  Exec configuration to the Skill;
- bind current Product/Profile/Session/actor, complete effect set, exact
  package/entrypoint/runtime/dependency identities, Approval, and audit;
- revalidate abort, Profile, verified identity, and Sandbox containment
  immediately before execution;
- hold package, artifact, secret, and execution leases through physical process
  settlement; and
- delegate only the final materialized request to the existing Exec mechanics.

Skill script metadata must remain an owner-specific part of the Skill
`resource_item` schema. It must not create a per-Skill Plugin Instance, second
Skill catalog, new declaration kind, or direct Plugin-management invocation
path.

#### H4. The PM sequence duplicates and reorders the live PLC6-PLC9 plan without
an explicit mapping

The current delivery plan records PLC2 through PLC5.1a as implemented and PLC6
through PLC9 as unimplemented. PLC6 (`coding.base`) and PLC7 (`coding.arch`)
are the required production adopters before PLC8 public SDK stabilization;
PLC8 already owns Skill convergence and script routing; PLC9 already owns
management projections, isolated workers, compatibility cleanup, and GC.

The proposed PM0-PM6 graph starts a parallel sequence, moves Skill execution
and Worker work before its “multiple adopters” phase, and repeats management,
SDK, isolation, and GC milestones. It does not say whether PLC6/PLC7 continue,
are prerequisites, or are superseded. That makes completion claims ambiguous
and risks two implementations landing against different schema versions.

Required correction: publish a crosswalk and treat the improvement plan as a
revision/split of PLC8/PLC9, not a second master lifecycle. Any changed order
must be accepted as a sequencing revision in the existing coordinating plan.

#### H5. PM6 risks a second package store, lock, and GC implementation

The proposal lists a new immutable package store, lock, retained-version GC,
and private-data GC as PM6 deliverables. Current source already has
`PluginResolutionAuthority`, published verified revisions, dependency locks,
package lifecycle pins, cleanup tasks, startup recovery barriers, GC candidate
derivation, and candidate recheck. PLC5.1a also records canonical lock
integration as implemented.

PM6 must be restated as extending and productizing these existing authorities:

- publisher authentication and signed publication metadata feed the existing
  source/resolution authority;
- remote acquisition materializes into the same verified revision store;
- no second lockfile, parser, cache key, retained-version counter, or GC
  eligibility calculation is introduced; and
- remaining gaps are inventoried as adapters, byte reclamation, policy,
  diagnostics, and operator workflow against existing records.

### Medium

#### M1. Readiness and update wording promises more live behavior than the owner
model permits

“Readiness is published atomically” should mean only that the Supervisor
returns a ready prepared handle. It must not mean that a Worker independently
publishes a Capability, Tool, Resource, or effective generation. Likewise,
“Workers can update, drain, and roll back” should be rewritten as “exact owners
can stage a new contribution backed by a new Worker attempt, publish under
their existing boundary, drain the previous owner generation, and retain the
old package according to management policy.”

Multi-owner, authority, dependency, executable digest, and process-topology
changes still produce a new Session or `restart_required`. Worker IPC does not
grant universal hot reload.

#### M2. Worker declaration evaluation and contributed runtime hosting are not
separated

The accepted architecture explicitly says a future isolated declaration
evaluator needs a new declaration-source arm and containment protocol; it
cannot implicitly reuse contributed-runtime launch. The proposal mostly
describes a runtime service Worker and says untrusted executable Providers have
no in-process import path, but does not identify how an untrusted package's
declarations become inert candidates before owner admission.

The ARD must define two separately approved uses, even if they later share a
transport library:

- isolated declaration evaluation, producing only frozen declaration batches
  and consumption evidence; and
- post-admission contributed service activation, consuming a distinct
  `ContributionActivationApprovalSubject` and activation-use reservation.

One process must not silently reuse declaration-evaluation approval as runtime
activation authority.

#### M3. Protocol details should bind existing identities rather than add a new
global clock

Protocol version, request ID, bounded frames, nonce, cancellation, and
backpressure are appropriate. The handshake should additionally bind the
existing preflight/activation use ID, exact owner reference, owner generation
candidate reference, Session runtime identity, and current revocation epoch.
Conversely, a standalone Worker generation must not appear in Effective Runtime
or substitute for owner generation provenance.

#### M4. The verification matrix needs explicit no-bypass architecture gates

The behavioral fault list is strong but does not directly prevent future code
from importing `ProcessHost`, writing owner registries, projecting effective
state from management inventory, or launching a script around the authorized
adapter. Static scans alone are insufficient, but qualified architecture tests
plus behavioral negative fixtures are valuable defense in depth.

## Required Dependency And Phase Revision

The following sequence preserves the current PLC authority and removes the
parallel master plan:

```text
PM0 / accepted execution-and-worker ARD
  |
  +-- extend PLC6 and PLC7 only with truthful trusted_in_process diagnostics
  |   (do not block the existing Base/Arch adopter sequence on Worker V1)
  |
  v
PLC8A: Skill owner schema and catalog convergence
  -> inert owner-admitted script descriptors
  -> no execution during discover/list/load
  |
  v
PLC8B: authorized one-shot Skill-script adapter
  -> existing Policy/Approval/Sandbox/Exec mechanics
  -> Python/Bash/Node production fixture
  |
  v
PLC8C: public data-only and one-shot author surface
  -> only after LSP/Base/Arch plus Skill-script conformance
  |
  v
PLC9A: isolated declaration-evaluator source arm
  -> frozen declaration output only
  -> separate execution-use evidence
  |
  v
PLC9B: Session-owned Worker V1 behind one exact Component Host
  -> activation-use evidence
  -> no direct publication
  -> real long-lived adopter
  |
  v
PLC9C: management query/adaptor convergence and operator UX
  -> existing inventory/effective projectors
  -> owner-coordinated operational intents
  |
  v
PLC9D: existing package lifecycle/GC completion and compatibility deletion
  |
  v
optional domain milestone: owner-qualified plan/apply/reconcile
  -> only after a real durable-mutation owner and requirements exist
```

Management adapter convergence for already implemented V1/V2 commands can
proceed earlier, but it must not claim refresh/repair/process/GC completion
before those command families and owner handoffs exist. Read-only inventory
projection can also proceed independently if it preserves source revision
clocks and never infers effective state.

If workspace- or process-scoped Workers are required, insert a separate
accepted Process Hosting scope milestone before PLC9B for those scopes. Do not
expand a Session-owned `ProcessHost` by convention.

## Concrete Amendments To The Improvement Plan

Before acceptance, the plan should make these textual and contract changes:

1. Replace “one effective effect class” with “one exact additive effect set and
   one non-widening effective execution profile”; retain risk class as a
   derived display fact only.
2. Add a mapping table from proposed terminology to current types and owners,
   including `PluginContributionExecutionModel`, declaration-source kind,
   `PluginExecutionApprovalSubject`, `ContributionActivationApprovalSubject`,
   `PluginInstanceRuntimeLedger`, owner generation, `ProcessHandle`, and
   package lifecycle records.
3. Redraw the runtime architecture as
   `PluginManagementService -> desired/operational intent -> exact Component
   Host/owner -> Worker attempt coordinator -> AuthorizedProcessLauncher`.
4. Replace the Supervisor lifecycle with a non-authoritative process-attempt
   state. Remove `quarantined/repairable` from it and identify the owners of
   crash suppression, package quarantine, repair, and retirement.
5. State that V1 Workers are Session-owned, or specify a separately accepted
   longer-lived hosting authority.
6. Split isolated declaration evaluation from admitted runtime service
   activation and retain separate Approval consumption records.
7. Introduce an authorized Skill-script adapter above Exec; do not call raw
   `ExecService` the complete authorization boundary.
8. Keep script metadata in the Resource owner's Skill schema and preserve one
   Resource catalog and no per-Skill Plugin identity.
9. Split management mutation commands, authoring tools, management inventory
   queries, and cross-projector presentation into distinct APIs.
10. Make plan/apply records owner-qualified and move their durable journal and
    reconcile state to the exact Product/domain owner.
11. Replace PM0-PM6 as a parallel delivery spine with an explicit PLC8/PLC9
    crosswalk and architecture-approved sequencing revision.
12. Reword PM6 as integration/productization of the existing resolution,
    canonical lock, package lifecycle, recovery barrier, and GC-candidate
    authorities.

## Executable Delivery Gates

The revised plan should require the following gates in addition to its current
fault matrix.

### Authority and architecture gates

- Only Harness Sandbox runtime construction may instantiate `ProcessHost`;
  Worker code receives `AuthorizedProcessLauncher` through an exact Product
  binding.
- `PluginManagementService` and its adapters cannot import owner registrars,
  Graph Binder publication APIs, `ProcessHost`, raw Sandbox backends, or raw
  subprocess APIs.
- Worker/Skill public SDK modules cannot import Plugin-management journals,
  Approval issuance, owner mutation APIs, Session internals, or Harness private
  process modules.
- A Worker handshake cannot publish a Graph Mount, Tool, Resource, Extension,
  or owner generation; a behavioral fixture proves publication occurs only
  through the exact owner commit.
- Plugin inventory code cannot label an owner contribution effective without
  an exact owner snapshot reference, and a skew fixture preserves independent
  revisions rather than synthesizing one generation.
- No script path reaches `ExecService` from Skill invocation except through the
  authorized Skill-script adapter.

### Lifecycle and ownership gates

- One Worker attempt is traceable to exactly one Plugin Instance revision,
  owner candidate/generation reference, activation-use reservation, Session
  execution runtime, Process handle, and package lease.
- Failed handshake, early exit, owner-publication failure, Session close,
  graceful drain, security revoke, and Host shutdown each release the same
  attempt exactly once without completing Plugin Instance retirement early.
- Worker readiness followed by owner admission/publication failure produces no
  effective contribution.
- Stop/restart submitted through management records intent, but only the exact
  owner stops routing and retires its contribution; the management service
  never closes the Process handle directly.
- Crash-loop suppression does not mutate package quarantine. A separate,
  evidence-backed security operation is required to quarantine a revision.
- A Session-owned Worker cannot survive its `SandboxExecutionRuntime.close()`;
  any future shared Worker has a separate scope-owner conformance suite.

### Script execution gates

- Install, inspect, list, Skill discovery, Skill content loading, and Model
  Input reconstruction never execute or import an adjacent script.
- The executed interpreter and script bytes match the approved revision,
  dependency/runtime identity, and entrypoint digest at the final launch seam;
  symlink, replacement, traversal, PATH, shebang, and wrapper substitution
  fixtures fail closed.
- Combined filesystem/process/network effects remain combined through Policy,
  Approval, effective profile resolution, Sandbox planning, and audit; no
  single label drops an effect.
- Required containment unavailable fails before process creation. Best-effort
  fallback is possible only under an explicit trusted policy and remains
  visible in status.
- Cancellation and timeout settle the process tree, output streams, artifact
  files, package lease, and temporary secret material before returning.

### Declaration and approval gates

- An isolated declaration evaluator can produce only strict frozen
  declarations; it cannot call runtime services or owner publishers.
- Declaration evaluation and runtime activation consume different exact
  subjects and use reservations. Reusing either decision, receipt, nonce, or
  process identity for the other phase fails.
- Stale desired state, package revision, dependency lock, Profile, trust,
  policy revision, revocation epoch, owner admission, or Session runtime
  identity prevents launch or callback authorization.
- A retired/superseded attempt's response and Effect Broker callback fail even
  when request IDs collide with the active attempt.

### Durable mutation gates

- Every ChangeSet codec and operation journal names one exact domain owner and
  schema; no generic Plugin/Worker journal infers domain state.
- Lost response, duplicate apply, stale plan, changed precondition, partial
  result, unknown outcome, Worker crash, Host crash, and reconcile are tested
  through that domain owner.
- Activation Approval, plan Approval, and each required action Approval remain
  distinct and cannot authorize one another.

### Regression commands

Each implementation slice should add focused suites beside the existing
owners, then run the affected broader architecture and Harness/Coding suites.
At minimum, the delivery plan should name commands equivalent to:

```text
.venv/bin/python -m pytest tests/harness/plugin_management -q
.venv/bin/python -m pytest tests/harness/tools/test_process_hosting.py -q
.venv/bin/python -m pytest tests/harness/workspace/test_exec.py -q
.venv/bin/python -m pytest tests/harness/sandbox -q
.venv/bin/python -m pytest tests/harness/resources/plugins -q --skip-host-runtime
.venv/bin/python -m pytest tests/harness/capabilities -q --skip-host-runtime
.venv/bin/python -m pytest tests/harness/session -q --skip-host-runtime
.venv/bin/python -m pytest tests/coding -q --skip-host-runtime
.venv/bin/python -m pytest tests/architecture/test_unified_plugin_architecture.py -q --skip-host-runtime
.venv/bin/ruff check <changed Python files>
git diff --check
```

Real process, asyncio, persistence, and pytest-backed gates must follow the
workspace rule and run outside the managed sandbox from the first attempt.
Static architecture/import checks may run inside it.

## Acceptance Recommendation

Accept the proposal's direction only after C1-C3 are resolved in an ARD and the
plan is rebased onto the existing PLC8/PLC9 sequence. With those corrections,
the smallest coherent first release is:

1. one Resource-owner Skill script descriptor;
2. one authorized one-shot execution adapter over existing Exec/Sandbox;
3. one isolated declaration-evaluator arm;
4. one Session-owned Worker attempt behind an exact Component Host; and
5. management/read-model adapters that expose existing desired, owner,
   process, and cleanup evidence without taking ownership of it.

That release would prove executable Skills and untrusted Providers while
preserving the current single-owner, single-Graph, conservative hot-update, and
reconstructible-lifecycle architecture.

## Re-review Addendum

### Scope And Disposition

This addendum independently re-reviews the revised improvement plan after the
initial architecture, security, and authoring findings were incorporated. It
does not alter the initial review, whose findings remain the record of the
initial draft.

The revised plan substantially resolves the original architecture findings:

| Original finding | Re-review disposition |
| --- | --- |
| C1: competing single effect class | Resolved. Effects are additive existing `ToolEffect`/authority facts, `EffectiveExecutionProfile` remains the non-widening enforcement value, and risk tier is diagnostics only. |
| C2: Worker Supervisor as second owner/state machine | Resolved. `WorkerAttemptCoordinator` is explicitly non-owning; exact owners publish/drain, Process Host owns physical process lifecycle, Plugin Instance owns direct-host state, and package lifecycle owns quarantine/GC. Worker attempt is not an effective clock. |
| C3: generic plan/apply domain owner | Resolved. ChangeSet, journal, result interpretation, reconcile, compensation, and safe-abandon belong to an exact Product/domain owner; the generic layer supplies only neutral mechanics. |
| H1: unresolved Worker scope | Resolved for V1. Worker V1 is explicitly Session-owned; longer-lived pooling requires a separate accepted hosting scope. |
| H2: mutation/query/authoring conflation | Resolved in principle. Authoring, durable mutation, exact read projectors, cross-projection explain, and owner operational intent are separate ports. |
| H3: raw Exec treated as authorized script boundary | Resolved. `AuthorizedSkillScriptExecutor` is a new Product-owned port above neutral `ExecService` and binds verified identity, authority, containment, and leases. |
| H4: parallel PM0-PM6 delivery spine | Resolved. The plan is now an explicit PLC8/PLC9 decomposition, preserves PLC6/PLC7, and gates stable executable authoring on real adopter/conformance evidence. |
| H5: second package store/lock/GC | Resolved for Plugin packages. PLC9D explicitly extends the existing resolution authority, verified store, canonical lock, lifecycle ledger, recovery barrier, and GC candidate/recheck. |
| M1-M4 | Resolved or reduced to the P1 clarifications below. Readiness is preparation only, declaration evaluation and runtime activation are separate, attempts bind existing owner identities, and no-bypass verification is explicit. |

The revised plan also correctly preserves legacy instruction-driven Skill
scripts as visibly generic Tool execution while adding an optional managed
script identity. This closes the practical compatibility gap without claiming
that Markdown prose is an authority declaration.

### New P0 Findings

#### P0-1. Install materialization and desired-state commit still have no one
defined coordinating transaction

The revised port split says:

- `PluginAuthoringService` produces a canonical package;
- `PluginManagementService` owns `install-disabled` desired state;
- adapters must not materialize package roots; and
- PLC9D remote acquisition materializes into the existing verified revision
  store.

The author journey nevertheless exposes `plugin install DIST --disabled`
before PLC9D. Current `PluginManagementCommandV1.install` accepts an already
formed `PluginPackageRevisionRefV1`; current `PluginManagementService` only
journals and commits desired state. `PluginResolutionAuthority.publish_runtime`
is the existing transition that publishes verified package revisions and
durable package bindings. The revised plan does not specify who invokes that
authority, how its result enters the install command, or how a crash between
publication and desired-state CAS is recovered.

Without this contract, an adapter must either materialize directly, creating
the forbidden peer mutation path, or the management service must silently
absorb package-byte authority, creating a second package owner.

Required correction before acceptance:

- define one staged install operation in which `PluginManagementService`
  coordinates, but does not replace, the existing source/resolution and
  package-binding authorities;
- bind the command to the exact source/snapshot/package inspection and expected
  inventory revision;
- durably distinguish inspected, published/bound, desired-state-committed,
  terminal, and orphan-repair outcomes without collapsing package state into
  Installation state;
- specify idempotency and recovery when publication succeeds but desired-state
  commit does not; and
- use this same operation for local DIST and later remote acquisition. Remote
  transport may differ, but the verified publication/install transaction must
  not.

This is required by PLC8C's canonical install-disabled author journey and
cannot be deferred entirely to PLC9D operator productization.

#### P0-2. Prepared dependency environments introduce a new durable cache
without an exact owner

PLC8B-2 introduces immutable prepared Python environments keyed by runtime,
platform, architecture, and dependency-lock digest, with preparation,
retention, update, rollback, rebuild, and GC leases. PLC9D later includes
prepared-environment byte reclamation. The plan says these use existing
package/runtime authorities, but the current package lifecycle is keyed by
`PluginPackageRevisionRefV1` and does not thereby own a potentially shared
runtime environment.

A prepared environment can outlive one invocation, be shared by several
package revisions, fail during construction, become corrupt or incompatible,
hold native code, and race rollback/reclamation. Treating it as package bytes
by assertion would either corrupt package identity or create an unrecorded
second cache lifecycle.

Required correction before PLC8B-2 or stable dependent-script claims:

- decide whether an environment is an immutable child artifact owned by one
  exact Package Revision or a separately shared Host cache;
- if package-owned, include its complete derived identity, preparation receipt,
  package pin, cleanup task, and byte reclamation in the existing package
  lifecycle without changing the package content digest after publication;
- if shared, accept one explicit environment-cache owner with a canonical key,
  build journal, quarantine/repair semantics, reference leases, recovery
  barrier, and GC recheck, while making clear that it is not a Plugin Instance,
  owner generation, or second dependency lock; and
- bind the selected environment identity and lease to script/Worker Approval,
  launch, update, rollback, explain, and cleanup evidence.

The zero-dependency PLC8B-1 slice does not require this owner and may remain the
first executable proof. PLC8B-2 and any PLC8C compatibility claim covering
third-party dependencies do.

### Residual P1 Findings

#### P1-1. Worker-start versus contribution-activation Approval terminology is
not yet exact

The ARD gate lists separate `Worker-start` and `activation` subjects, while the
Approval section describes one “admitted Worker-backed contribution
activation/start” subject. The accepted Unified Plugin Architecture already
assigns external-service factory/owner-bind/process launch to
`ContributionActivationApprovalSubject` and its activation-use reservation.

The revised plan should state whether Worker process spawn is the process arm
of that versioned activation subject, or whether a truly separate start subject
is required. If separate, it must define the distinct protected action, lock
order, two use records, crash reconciliation, and why one approval cannot
safely cover the exact activation attempt. It must not accidentally consume two
independent decisions for one physical start or let either authorize the other.

#### P1-2. `PluginAuthoringService` is lifecycle-pure, not filesystem-pure

Validate can be observational, but canonical pack and ephemeral snapshot
creation read a source tree and create output bytes; packing may also overwrite
an output path. Calling the whole service “pure” can bypass normal filesystem
effect, cancellation, and artifact rules.

Reword it as non-executing and non-mutating with respect to installed Product
state. Define validate as read-only inspection and pack/snapshot as bounded
authoring artifact operations using exact filesystem effects and atomic output
publication. None may import or execute package content.

#### P1-3. Script authority metadata must not silently violate the current
data-only `resource_item` codec

The revised plan correctly places `SkillScriptDeclarationV1` inside the
Resource owner's Skill schema, but also gives it requested additive
authorities. The current declaration contract requires a data-only
`resource_item` contribution to have an empty contribution-level
`requestedAuthorities` set.

The ARD/schema revision must say that script requests are inert owner-specific
payload data evaluated only when `skill.script.run` is prepared; they do not
populate the existing contribution execution-authority field or turn Skill
discovery into executable admission. If contribution-level authority is
instead intended, the `resource_item` codec, fingerprints, owner admission,
preflight, and compatibility rules must advance explicitly.

The similarly named “Product runtime requirement” should resolve to an
existing Product-owned toolchain predicate or an existing typed Capability
requirement path. It must not become another Runtime Profile selector or
dependency graph inside the Skill schema.

#### P1-4. Operational intent needs one durable result-reference contract

The revised plan correctly prevents management from closing a Process handle,
but PLC9C should specify how a durable stop/restart intent references the exact
owner operation and terminal evidence. Management may record request/progress
references for UX and idempotency; the exact owner remains authoritative for
routing, drain, retirement, replacement, and failure. Recovery must show
pending/unknown/failed owner execution without promoting management's intent to
Worker state.

### Editorial Cleanup

Before merging the proposal, remove two duplicated lines in the revised draft
(`The managed declaration...` and the repeated containment-capability tail),
and update the Executive Decision phrase “existing authorized one-shot
execution boundary” to name the newly proposed authorized adapter above the
existing neutral Exec mechanics. These do not change the architecture verdict
but currently contradict the more precise normative sections.

### Final Verdict

**The revision resolves all original C1-C3 and H1-H5 findings, but it still
requires revision before architecture acceptance because P0-1 and P0-2 leave
durable materialization/cache ownership undefined.**

After those two owner/recovery contracts are added and P1 terminology is
tightened, this reviewer recommends accepting the document as the PLC8/PLC9
delivery proposal, subject to its stated Execution/Worker ARD gate. The
zero-dependency, Session-owned first slices are appropriately narrow and do not
need to wait for optional domain plan/apply work.

### Final Closure Check

Final disposition against the latest revised plan:

| Finding | Closure |
| --- | --- |
| P0-1 staged install ownership/recovery | Closed. `PluginManagementService` coordinates one durable staged operation while the existing resolution/package-binding authority retains byte ownership. The operation binds exact inspection/source identity, desired-state CAS and idempotency; records inspected, published/bound, desired-state-committed, terminal and orphan-repair states; preserves inert pinned bytes across the publication/CAS crash gap; and uses the same transaction for local and remote sources. PLC8C and adversarial gates now require this path. |
| P0-2 prepared-environment owner | Closed. V1 is an immutable non-shared child artifact of one exact Package Revision. Its derived identity, preparation receipt, package pin, execution lease, repair/cleanup records, recovery barrier and byte-level GC recheck extend the existing package lifecycle without changing package digest or creating a shared cache owner. Future sharing requires a separate accepted design. |
| P1-1 Worker start versus activation Approval | Closed. Worker spawn is explicitly the process-backed arm of one versioned `ContributionActivationApprovalSubject`/activation-use reservation; `process.host.start` remains enforcement and cannot duplicate or replace that decision. |
| P1-2 authoring purity | Closed. Authoring is now described as non-executing and lifecycle-pure; validate is read-only, while pack/snapshot are bounded filesystem-effectful artifact operations with cancellation and atomic publication. |
| P1-3 Skill-script requested authorities | Closed. Script requests are inert owner-specific payload data, do not populate the data-only `resource_item` authority field, and compile to effects only at `skill.script.run`; runtime requirements use the existing Product toolchain/Capability predicate path. |
| P1-4 operational-intent result ownership | Closed. The durable intent binds idempotency plus exact owner-operation and terminal-evidence references; management projects progress only, while the exact owner retains routing, drain, retirement, replacement and failure authority. |

No new P0 or P1 was introduced by these closures. The staged-install ARD and
tests must preserve a write-ahead recoverable operation/pin before an
unrecoverable publication gap, but that is now an implementation linearization
detail inside the stated staged transaction, recovery states and adversarial
gate rather than a missing architecture owner.

One non-blocking editorial inconsistency remains: the Executive Decision still
calls one-shot execution an “existing authorized one-shot execution boundary,”
while the normative design correctly introduces a new authorized adapter above
existing neutral Exec mechanics. Rewording it would improve accuracy but does
not reopen an architecture finding.

**Final verdict: architecture-review findings are closed. Recommend accepting
the document as the proposed PLC8/PLC9 delivery plan, subject to its explicit
Execution/Worker ARD gate and regression-first implementation workflow. This
acceptance is not authorization to expose executable APIs before the stated
slice exit gates pass.**
