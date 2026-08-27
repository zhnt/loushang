# Plugin Management And Isolated Execution Security Review

## Status

- Authority: descriptive — independent security validation evidence
- Artifact type: validation
- Reviewed design status: proposed
- Implementation status: not-applicable
- Owner: Loushang architecture review

This is an independent security review of
[`plugin-management-and-isolated-execution-improvement-plan.md`](../plugin-management-and-isolated-execution-improvement-plan.md).

Review basis: local source at `257dbd5cf78bba8f81e3a7546e961d935adb19f9`
plus the uncommitted proposal present on 2026-08-26. This review does not accept
new architecture and does not modify the reviewed plan.

## Verdict

**Request changes before architecture acceptance or PM2 implementation.**

The proposal makes the correct top-level decisions:

- executable Skill content is supported rather than prohibited;
- one-shot scripts and long-lived Workers retain distinct lifecycle owners;
- third-party executable code does not enter the Product Host;
- a same-user process and an IPC channel are explicitly not called a sandbox;
- durable external mutation is separated from ordinary script execution; and
- the existing Approval, Sandbox, Process Host, Graph, Registration, and domain
  owners are intended to remain authoritative.

Those decisions align with the accepted trust model: non-host-equivalent code
must be declarative or use an accepted isolated Worker, and isolation is only
as strong as Sandbox and Host facets
([Unified Plugin Architecture, lines 1395-1408](../../../harness/unified-plugin-architecture.md#L1395-L1408)).

The proposal is nevertheless not yet an executable security contract. Four
blocking gaps remain: mandatory containment is not concretely selected, the
one-shot path does not yet provide clean-environment or immutable-executable
launch, current durable Plugin Approval types only authorize in-process
execution, and a Worker with direct network or credentials can bypass the
proposed Effect Broker and plan/apply record. These must move from open
questions or prose guarantees into PM0 prerequisites and typed conformance
contracts.

## Evidence Checked

### Accepted and live boundaries

- The accepted Plugin architecture forbids import or launch before positive,
  digest-bound preflight and requires isolated discovery when executable code
  is needed below in-process trust
  ([lines 380-418](../../../harness/unified-plugin-architecture.md#L380-L418)).
- It requires durable Approval-owner decisions, one-shot consumption, current
  trust/policy/epoch revalidation, and a fixed lock order before code entry
  ([lines 420-469](../../../harness/unified-plugin-architecture.md#L420-L469)).
- It treats a compromised in-process realm as Host compromise, invalidates
  controlled leases before terminating isolated services, and refuses to call
  incomplete termination a successful disable
  ([lines 1072-1092](../../../harness/unified-plugin-architecture.md#L1072-L1092)).
- It requires verified revision handles, no mutable-path reopen, no-follow or
  equivalent immutable snapshots, and rejection on platforms unable to prove
  that property
  ([lines 1410-1428](../../../harness/unified-plugin-architecture.md#L1410-L1428)).
- `PluginManagementService`, exact component owners, and the existing
  Registration/Graph owners remain sole mutation/publication authorities
  ([lines 1607-1634](../../../harness/unified-plugin-architecture.md#L1607-L1634)).
- The accepted Process Host is only raw, bounded, session-owned child-process
  mechanics. Product code still owns executable admission, protocol,
  supervision, restart, and diagnostics
  ([Process Hosting Boundary, lines 10-32](../../../harness/process-hosting-boundary.md#L10-L32)).
- Required containment fails before spawn, while best-effort containment may
  deliberately fall back to an uncontained local process and report degraded
  status
  ([lines 75-106](../../../harness/process-hosting-boundary.md#L75-L106)).
- `ExecService` owns neutral one-shot mechanics, not command authorization, and
  its materialization deliberately does not freeze executable lookup,
  executable bytes, or files read by the child
  ([Workspace Execution Boundary, lines 45-90](../../../harness/workspace-execution-boundary.md#L45-L90)).
- The live authorization architecture requires one canonical action, Policy,
  Approval, execution-time revalidation, constrained execution, and audit; it
  explicitly separates consent from enforcement
  ([Policy And Approval Redesign, lines 887-945](../../../harness/policy-approval-redesign.md#L887-L945)).

### Current source constraints

- `ExecRequest` materialization currently merges the complete `os.environ` by
  default into the child environment
  ([workspace/exec/types.py, lines 102-138](../../../../../../src/loushang/harness/workspace/exec/types.py#L102-L138)).
- `EffectiveExecutionProfile` currently enforces filesystem roots and a coarse
  network enum only
  ([authorization/execution_profile.py, lines 31-115](../../../../../../src/loushang/harness/authorization/execution_profile.py#L31-L115));
  the accepted design explicitly says secret filtering, privilege, and
  external-effect enforcement remain deferred and must not yet be claimed as
  Sandbox enforcement
  ([Policy And Approval Redesign, lines 590-616](../../../harness/policy-approval-redesign.md#L590-L616)).
- `SandboxSettings` defaults to disabled and best-effort
  ([sandbox/types.py, lines 24-35](../../../../../../src/loushang/harness/sandbox/types.py#L24-L35));
  the hosted-process planner returns a plain uncontained launch plan when the
  Sandbox is disabled or unresolved
  ([sandbox/process.py, lines 49-68](../../../../../../src/loushang/harness/sandbox/process.py#L49-L68)).
- The current Linux Bubblewrap backend advertises filesystem, network
  isolation, private temporary directory, and inherited subprocess containment,
  but not CPU, memory, or PID quotas
  ([sandbox/backends/linux.py, lines 33-41](../../../../../../src/loushang/harness/sandbox/backends/linux.py#L33-L41)).
- `PluginExecutionApprovalSubject` rejects
  `ambient_host_authority=False`, and `ContributionActivationApprovalSubject`
  accepts only `execution_model="in_process"`
  ([selection.py, lines 390-459](../../../../../../src/loushang/harness/resources/plugins/selection.py#L390-L459),
  [plugin_activation.py, lines 88-157](../../../../../../src/loushang/harness/approval/plugin_activation.py#L88-L157)).
- The durable Plugin execution journal is specifically an in-process
  declaration-evaluation journal with `EVALUATED` / `FAILED_AFTER_START`
  terminal semantics, not a script or long-running Worker journal
  ([plugin_execution.py, lines 1-86](../../../../../../src/loushang/harness/approval/plugin_execution.py#L1-L86)).
- The authorized long-running launcher protects a generic
  `process.host.start` action containing command and launch fingerprint; it
  does not itself carry package revision, Plugin admission, script declaration,
  or Worker generation identity
  ([tools/process_hosting.py, lines 105-170](../../../../../../src/loushang/harness/tools/process_hosting.py#L105-L170)).
- `ProcessHost` bounds process count and stream operations but does not impose
  CPU/memory/PID quotas, and local process-tree signaling is explicitly
  best-effort
  ([workspace/process/host.py, lines 296-315](../../../../../../src/loushang/harness/workspace/process/host.py#L296-L315),
  [workspace/_local_process.py, lines 43-69](../../../../../../src/loushang/harness/workspace/_local_process.py#L43-L69)).
- The current `SkillDescriptor` has no executable-script declaration; it
  carries the `SKILL.md` content, source path, arbitrary frontmatter metadata,
  and an optional resource revision reference
  ([resources/types.py, lines 101-126](../../../../../../src/loushang/harness/resources/types.py#L101-L126),
  [resources/_descriptor_parsing.py, lines 74-128](../../../../../../src/loushang/harness/resources/_descriptor_parsing.py#L74-L128)).

## Findings

### BLOCKER-1: Third-party containment is still an open choice instead of an admission invariant

The plan correctly says process isolation is not a sandbox and says an
unenforceable required restriction fails closed. However, its execution table
allows a third-party one-shot under an “admitted execution profile,” while the
mandatory platform guarantees remain an open ARD question. The current runtime
defaults to Sandbox disabled/best-effort, and an unresolved hosted-process
Sandbox can yield a normal local process plan. An execution profile is data;
it is not evidence that every requested restriction was enforced.

This blocks both PM2 and PM3. A third-party script or Worker could otherwise be
reported as isolated while retaining the Host user's files, environment,
network, credentials, and process authority.

Required correction:

1. PM0 must define a typed `ExecutableContainmentRequirement` before PM2 starts.
   For code below host-equivalent trust it must require `enabled + required`,
   never best effort.
2. Each execution profile must name the exact required backend capabilities,
   not merely a generic Sandbox profile identifier. Admission compares that set
   with the effective per-scope descriptor before spawn.
3. Define a support matrix per platform. An unsupported platform rejects that
   executable payload; it may still install and inspect it inertly.
4. Reserve best-effort fallback for explicitly host-equivalent Product policy
   and always report it as degraded, never isolated.

Executable acceptance gates:

- With Sandbox disabled, unavailable, degraded, or missing one required
  capability, an untrusted script and Worker both fail before OS process
  creation.
- A fake backend that advertises filesystem enforcement but not required
  network/process-tree enforcement is rejected before spawn.
- Status and audit report `process_separated`, `sandbox_enforcing`, and the
  exact enforced capability set independently; no single `isolated=true` flag
  exists.

### BLOCKER-2: Reusing `ExecService` does not freeze script bytes, interpreter identity, PATH, or ambient secrets

The plan promises an exact revision, script digest, frozen interpreter, frozen
environment, and malicious-path resistance. The existing one-shot boundary
cannot supply those properties by itself: it inherits the complete Host
environment by default and explicitly preserves native executable lookup and
child file opens. Passing `['bash', verified_script]` is shell-free, but Bash
still opens a pathname after authorization; the word `verified` does not make
the pathname immutable.

Required correction:

1. Introduce a Host-internal `VerifiedScriptLaunch` (name illustrative) above
   `ExecService`. It must consume a `VerifiedRevisionHandle`, an exact relative
   entrypoint handle, a Product-admitted runtime/toolchain identity, dependency
   lock, and an artifact lease.
2. Execute only from a host-owned immutable revision/environment. Temporary or
   project-local mutable Skill paths must first be snapshotted and verified, or
   remain legacy generic shell actions without first-class Skill-script claims.
3. Hold revision, runtime, environment, and containment leases from Approval
   revalidation through process settlement; do not close a verified handle and
   reopen a user-controlled source path.
4. Build a minimal environment from an allowlist. Do not call the ordinary
   `ExecService` materialization path with `effective_environment=None` for
   untrusted content. `PATH`, Python/Node module paths, proxy variables, loader
   variables, Git credential variables, and cloud credentials are absent unless
   explicitly admitted.
5. Resolve interpreter and approved child tools through a Product-owned,
   digest/version-qualified toolchain registry. Model/Plugin arguments cannot
   replace the fixed interpreter prefix or inject interpreter control flags.

Executable acceptance gates:

- Mutating, replacing, symlinking, or renaming a script after Approval but
  before spawn never changes the executed bytes.
- Replacing `python`, `node`, `bash`, or an approved helper on `PATH` never
  changes the selected executable.
- A sentinel credential placed in Host `os.environ` is absent from the script
  and Worker environment unless referenced by an admitted secret capability.
- A temporary/local Skill without a verified immutable revision cannot use the
  first-class script runner.

### BLOCKER-3: Script and Worker Approval subjects, consumption, and recovery do not yet exist

The plan says PM2 and PM3 may share identity subjects, and diagrams an execution
coordinator before process launch, but it does not define how the accepted
Approval-owner protocol extends to either execution shape. Current source is
not polymorphic: the declaration-execution subject requires ambient Host
authority, the activation subject accepts only `in_process`, and the execution
journal terminates at in-process evaluation. The generic
`process.host.start` gateway cannot substitute for package/digest/trust-bound
Plugin execution Approval.

This is more than a schema omission. Process code begins at spawn, before the
Worker handshake. The durable decision must therefore be consumed and recorded
as starting before the OS process can execute; a post-spawn handshake cannot
retroactively authorize launch.

Required correction:

1. PM0 must define distinct, discriminated Approval subjects under the existing
   `harness.approval` owner:
   - one Skill-script invocation/start subject;
   - one isolated declaration-evaluation or Worker activation/start subject;
   - the existing contribution activation subject extended only through an
     accepted versioned migration; and
   - separate invocation/effect subjects for later actions.
2. Each start subject binds package/entrypoint/runtime/dependency digests,
   Plugin instance and Worker generation, exact execution-profile capability
   evidence, cwd/argv/environment fingerprint, trust and policy revisions,
   actor/scope, expiry, and revocation epoch.
3. Add one-shot and long-running use state machines with crash recovery.
   At minimum distinguish consumed-not-started, starting, running/ready,
   draining, stopped, failed, unknown-after-crash, and cleanup-incomplete where
   applicable.
4. Specify the lock/order contract before implementation: start permit,
   Approval consumption transaction, Plugin-instance lifecycle gate,
   containment reservation, spawn, handshake, owner publication. No Plugin code
   executes before the durable `STARTING` transition.
5. Keep all decision and use records in the existing Approval-owner durable
   authority; the Supervisor stores process observations, not a second
   authorization fact.

Executable acceptance gates:

- A positive in-process decision cannot be decoded or reused as script/Worker
  authority, and vice versa.
- Crash at every boundary from decision consumption through owner publication
  reconstructs exactly one use with an explainable terminal or repair state.
- Revocation racing start has a deterministic linearization result: either no
  process starts, or the started process is marked revoking and its broker
  capabilities are invalidated before termination begins.
- Handshake failure never returns the consumed decision to `AVAILABLE` and
  never publishes a contribution.

### BLOCKER-4: Direct network or raw credentials make Effect Broker and plan/apply advisory

The proposal says direct Sandbox access and brokered effects may coexist and
that secret access and durable mutation “should normally” be brokered. That is
insufficient for its success claim that destructive actions are individually
bounded, approved, idempotent, and recoverable. A Worker with direct network
and credentials can perform an undeclared mutation before or outside
`apply(plan_digest)`, then return any convenient receipt. IPC callback checks
do not constrain effects that never traverse IPC.

The single `effect class` rule compounds the problem. Real invocations require
sets such as workspace read + process exec + network + secret use. Choosing one
class either hides authority or turns the class into an unsafe total ordering.
The accepted authorization runtime already models typed effect collections and
intersected authority ceilings.

Required correction:

1. Replace “one effective effect class” with an immutable typed effect/authority
   set plus a separately derived risk tier. Every member receives independent
   Policy, ceiling, enforcement, and diagnostic treatment.
2. For untrusted secret-bearing or durable external mutation, require direct
   Worker network `denied` and no raw credential environment. The Host or exact
   Product/domain adapter performs the approved request through a broker/proxy.
3. If a Product deliberately grants coarse direct network authority, report it
   as coarse direct authority and do not claim exact plan/apply enforcement,
   action-level audit, or non-bypassable idempotency.
4. The Host/domain owner validates and canonicalizes a proposed ChangeSet; an
   untrusted Plugin cannot define the final target identity, precondition, or
   authority merely by hashing its own JSON.

Executable acceptance gates:

- A mutation Worker has no route to the test service except the broker; direct
  socket/DNS attempts fail even after activation Approval.
- An apply request containing an operation absent from the approved canonical
  plan is rejected by the Host/domain adapter.
- Every combination of filesystem, process, network, secret, and external
  mutation authorities preserves all members in admission, Approval, audit,
  and Sandbox/broker projection; no max-class collapse is possible.
- Duplicate/lost apply tests prove provider/domain idempotency or produce
  `unknown` and reconcile; the Host never infers success from IPC delivery.

### HIGH-1: The plan does not close the existing Skill-to-generic-shell path

Today a Skill is instruction text plus a source path and arbitrary metadata.
Its instructions can tell the model to invoke `python scripts/x.py` through the
ordinary Bash/tool path. Adding a strict `[[skill.scripts]]` declaration and a
dedicated runner does not automatically migrate those existing Skills or
prevent direct shell invocation. Such a launch has generic shell Policy and
Sandbox semantics; it does not have the package/digest/interpreter identity
promised by the new Skill-script contract.

Required correction:

1. Define two explicit compatibility lanes:
   - declared scripts invoked through a dedicated typed `run_skill_script`
     action (name illustrative), receiving PM2 guarantees; and
   - legacy instruction-directed commands, which remain ordinary shell actions
     and are never reported as verified Skill-script execution.
2. Provide validation/migration diagnostics for script files or instruction
   patterns without declarations, while avoiding claims that arbitrary Markdown
   can be parsed into a sound command policy.
3. Decide whether organization policy forbids generic shell execution of
   installed third-party Skill payloads. If allowed, its security boundary is
   the generic shell profile, not Skill identity. Reading/copying a script and
   passing it to an interpreter makes pathname-only blocking insufficient.
4. Model-visible Skill instructions are untrusted guidance, not authority; they
   cannot select execution profile, grant permissions, or suppress Approval.

Executable acceptance gates:

- A direct Bash invocation of a Skill-adjacent script never receives or is
  audited as a `skill.script` decision.
- The dedicated action resolves only an active, exact Skill revision and one
  declared script ID; traversal, aliases, copied files, and undeclared helpers
  fail.
- Legacy Skills continue to work under documented generic tool semantics, and
  operators can inventory which Skills have not migrated.

### HIGH-2: Deterministic kill, no-orphan, and quota claims exceed the current Process Host

`ProcessHost` provides valuable exactly-once Host bookkeeping, stream limits,
reservation cleanup, and terminate/kill escalation. It does not currently
provide CPU, memory, PID, file-size, or open-file quotas. Its process-tree
signal helper is explicitly best-effort. A malicious same-user process can
attempt daemonization or group escape when no stronger containment mechanism is
present. Therefore Supervisor completion cannot be equated with OS process-tree
absence on every platform.

Required correction:

1. Separate Supervisor lifecycle correctness from OS resource/process-tree
   containment in status and requirements.
2. Add backend capabilities for at least CPU, memory, PID/process tree, wall
   clock, output bytes, and owned temporary storage where the execution profile
   requires them. Use enforceable platform primitives such as a contained PID
   namespace/cgroup or Windows Job Object; otherwise fail closed for the
   affected untrusted profile.
3. Make `termination_incomplete` a durable high-severity state that blocks
   retirement success and GC. Never map a failed/best-effort kill to `stopped`.
4. Bound handshake, heartbeat, idle, drain, request, and shutdown separately;
   a healthy OS process with a dead protocol must still be quarantined and
   terminated.

Executable acceptance gates:

- Fork bombs and memory/CPU burners hit enforced limits without destabilizing
  the Host.
- A fixture that forks, daemonizes, closes stdio, or attempts a new process
  group is either fully reclaimed by backend evidence or leaves an explicit
  `termination_incomplete` fact; it never passes the no-orphan gate by checking
  only the root PID.
- Host close under cancellation waits for containment cleanup, and failure
  preserves package/environment leases for repair.

### HIGH-3: Worker sharing and security revocation need an authority-isolation rule

The proposal mentions a Session-owned Worker lease for one Skill case, but does
not define whether Workers may be pooled across Sessions, actors, workspaces, or
effective profiles. A shared compromised Worker can retain the union of every
scope ever attached to it. It also has direct mounted authority until the
process is actually terminated; invalidating broker tokens alone does not
revoke direct filesystem access.

Required correction:

1. Worker V1 must not pool across actor, Product, scope/workspace, Plugin
   instance revision, dependency environment, or effective authority profile.
   Any future pooling requires a separate accepted design with non-widening
   per-request isolation evidence.
2. Bind every request/callback to both Worker generation and an invocation
   capability; retired or revoked generations fail before policy evaluation.
3. Security revocation first blocks new calls and invalidates broker/secret/
   effect leases, then enters `REVOKING`, then terminates the containment. A
   directly mounted Worker remains security-active until confirmed exit.
4. GC and “disabled” success remain blocked while termination or containment
   cleanup is incomplete.

Executable acceptance gates:

- Two Sessions with different roots or authority profiles never share a V1
  Worker PID or private state namespace.
- Revocation racing a broker callback rejects the callback at the revocation
  linearization point.
- A revoked Worker that keeps issuing direct writes until kill is never shown
  as fully revoked before confirmed process/containment settlement.

### HIGH-4: The absolute no-secret-in-logs guarantee is not enforceable after raw materialization

The proposal allows short-lived secret materialization and simultaneously says
secret values never enter stdout/stderr logs or artifacts. Once an untrusted
process receives raw secret bytes, it can print, encode, split, hash, or upload
them. The Host can avoid placing secrets in its own structured events and can
redact exact known values, but it cannot truthfully guarantee that arbitrary
Plugin output contains no derivative or obfuscated secret. The current Process
Host also exposes a raw bounded stderr tail.

Required correction:

1. Prefer opaque credential handles and Host-performed authenticated effects;
   untrusted code receives no reusable secret bytes by default.
2. When raw materialization is an unavoidable, explicitly approved capability,
   classify all child output and artifacts as potentially secret-bearing. Store
   them in a restricted artifact channel; do not place them in ordinary status,
   transcript, or default logs.
3. State the guarantee precisely: Host-generated records never include secret
   material; known-value redaction is defense in depth, not proof that malicious
   output is safe.
4. Secret leases bind generation/invocation and expire, but documentation must
   acknowledge that revocation cannot make bytes already disclosed to a child
   unknowable.

Executable acceptance gates:

- A fixture echoing a materialized secret to stdout and stderr produces no
  ordinary transcript/status/log value; access to the quarantined artifact is
  separately authorized and audited.
- Opaque-handle flows complete authenticated effects without exposing the
  underlying credential in environment, argv, IPC payloads, or ordinary
  artifacts.

### HIGH-5: Direct workspace writes need partial-result semantics, not implied rollback

The plan reasonably avoids Terraform plan/apply for ordinary formatting and
generation, but a directly writable workspace mount is non-transactional.
Cancellation or kill can leave a half-written tree. Process cleanup, artifact
cleanup, and an exit code do not recover those bytes. The success criteria's
general “destructive actions are recoverable” wording is therefore too broad.

Required correction:

1. Record direct workspace writes as coarse, potentially partial effects. On
   abnormal exit, return `partial_workspace_write` or `unknown_workspace_state`
   and preserve diagnostics/leases.
2. Products that need rollback must add an owner-controlled checkpoint,
   staging-and-atomic-apply protocol, or exact file Effect Broker; cancellation
   alone is not rollback.
3. Preview/diff may improve consent but must not be called transactional unless
   commit and recovery are actually enforced.

Executable acceptance gates:

- Killing a script between two writes yields a visible partial/unknown result
  and never a clean cancellation result.
- A checkpoint-enabled Product proves restore after mid-write crash; a Product
  without checkpoints clearly preserves the modified workspace for operator
  inspection.

### MEDIUM-1: Durable mutation semantics must remain with the exact domain owner

The draft says the Host owns operation journals and includes durable external
mutation planning/application in a Host-owned Effect Broker. Read literally,
that can become a new generic mutation owner. The accepted Plugin architecture
instead requires irreversible external effects to be admitted, recorded,
reconciled, and compensated by their exact domain owner; the Plugin and Harness
may aggregate evidence but do not invent resource semantics.

Required correction:

1. Harness may own neutral envelopes, correlation, idempotency fields, leases,
   and durable journal mechanics.
2. The exact Product/domain owner owns refresh, target identity, ChangeSet
   schema, preconditions, apply, result interpretation, reconcile,
   compensation, and safe-abandon policy.
3. `PluginManagementService` records Plugin desired state and coordinates
   lifecycle; it does not become the authority for a cloud/database/SaaS
   resource state machine.

Executable acceptance gates:

- A Plugin cannot submit a ChangeSet for an unregistered domain schema or a
  target outside that domain owner's admitted scope.
- Recovery dispatches an unknown/partial operation only to its recorded domain
  owner and cannot select a generic Plugin-defined compensator.

## Consolidated Executable Security Gate

PM2 or PM3 must not expose a public executable author API until one adversarial
suite proves all of the following:

1. **Admission before code:** install/list/inspect/preflight never executes
   content; exact durable start authority is consumed before spawn.
2. **Immutable launch:** package, entrypoint, interpreter, dependencies, argv,
   cwd, environment, and containment fingerprint cannot change between decision
   and process execution.
3. **Clean environment:** no ambient Host credentials or loader/proxy/toolchain
   variables reach untrusted code.
4. **Capability-complete containment:** missing/degraded enforcement fails before
   spawn for untrusted execution; process separation and Sandbox enforcement are
   reported independently.
5. **No broker bypass:** secret-bearing and durable external mutations have no
   direct network/credential path; every exact effect passes the owner gateway.
6. **Generation isolation:** stale/revoked Worker responses and callbacks cannot
   publish, apply effects, or answer an active request.
7. **Lifecycle settlement:** spawn failure, handshake failure, cancellation,
   dead protocol, output flood, process-tree escape, Host close, and containment
   cleanup failure release or retain the correct durable reservations and
   leases exactly once.
8. **Honest failure state:** partial workspace writes, uncertain external
   mutations, leaked process-tree evidence, and cleanup failure are never
   projected as clean cancellation, stopped, disabled, or rollback success.
9. **Secret-safe projection:** Host records are structurally secret-free; raw
   Plugin output from secret-bearing executions is quarantined rather than
   treated as ordinary logs.
10. **Owner correctness:** only the exact Component/domain owner publishes live
    contributions or interprets durable external effects; the Supervisor,
    Plugin runtime, and management service cannot mutate foreign registries or
    manufacture recovery outcomes.

## Recommended Plan Changes Before Re-review

1. Move open decisions 1, 4, and 5 into PM0 blocking decisions for third-party
   executable support; they cannot remain deferred while PM2 starts.
2. Replace the single effect class with a typed effect set and derived risk
   tier.
3. Add explicit Approval subjects, state machines, lock order, and crash
   recovery for script starts and Worker starts before describing their public
   SDKs.
4. Add the verified-script/toolchain launch adapter and clean-environment
   contract above `ExecService`.
5. Make broker-only network/credential access normative for untrusted durable
   mutations, or weaken all exact-effect and plan/apply guarantees for direct
   network profiles.
6. Add a legacy Skill-script compatibility/migration section so existing
   instruction-driven shell execution is not confused with first-class script
   execution.
7. Split lifecycle bookkeeping, process separation, OS containment, and
   recoverability into separately evidenced operator status fields.
8. Assign every plan/apply schema and recovery state machine to an exact
   Product/domain owner, leaving only neutral journal/correlation primitives in
   Harness.

After those corrections, the proposed delivery sequence is security-sound in
shape: PM0 decisions and adversarial fixtures, PM1 management convergence, PM2
one-shot execution, PM3 Worker supervision, then PM4 brokered durable effects.

## Re-review Addendum

### Re-review Baseline

This narrow independent re-review checked the revised
[`plugin-management-and-isolated-execution-improvement-plan.md`](../plugin-management-and-isolated-execution-improvement-plan.md)
at SHA-256
`9a088d38a121317494221b02374038a10b0e461b17cdc76455ac74ef39629078`,
against local source commit
`257dbd5cf78bba8f81e3a7546e961d935adb19f9`. The revised plan and this review
remain uncommitted draft files at the time of re-review.

Scope was limited to the four original blockers, the original HIGH findings,
and any new P0/P1 introduced by the revision. The accepted/live evidence listed
earlier in this review remains unchanged.

### Original Finding Dispositions

| Finding | Disposition | Re-review evidence |
| --- | --- | --- |
| BLOCKER-1: mandatory containment | **Resolved at plan level** | Untrusted execution now requires capability-complete `enabled + required` containment and rejects disabled, best-effort, degraded, unresolved, or incomplete enforcement before process creation ([revised plan, lines 190-194](../plugin-management-and-isolated-execution-improvement-plan.md#L190-L194), [423-432](../plugin-management-and-isolated-execution-improvement-plan.md#L423-L432)). The execution/Worker ARD and platform capability matrix are an explicit prerequisite with a fail-closed exit gate ([699-716](../plugin-management-and-isolated-execution-improvement-plan.md#L699-L716)). |
| BLOCKER-2: immutable launch and ambient environment | **Resolved at plan level** | Managed local development snapshots mutable source first; `AuthorizedSkillScriptExecutor` consumes a leased verified revision and Product-resolved toolchain, builds an allowlisted environment from empty, revalidates immediately before launch, and holds leases through physical settlement ([258-280](../plugin-management-and-isolated-execution-improvement-plan.md#L258-L280)). PLC8B-1 and the common verification matrix make ambient credential, PATH/runtime substitution, mutable-entrypoint, and mutable reopen attacks executable gates ([734-749](../plugin-management-and-isolated-execution-improvement-plan.md#L734-L749), [934-970](../plugin-management-and-isolated-execution-improvement-plan.md#L934-L970)). |
| BLOCKER-3: script/Worker Approval subjects and use recovery | **Resolved at plan level** | The plan requires versioned, non-replayable subjects/use records for managed scripts, isolated declaration evaluation, Worker activation/start, and later effects. It places durable consumption before containment/spawn and defines crash-recovery states and owner publication order ([386-421](../plugin-management-and-isolated-execution-improvement-plan.md#L386-L421)). Cross-subject replay and crash-point reconstruction are explicit verification gates ([973-985](../plugin-management-and-isolated-execution-improvement-plan.md#L973-L985)). |
| BLOCKER-4: broker bypass and single effect class | **Resolved** | The Plugin-only single class is replaced by additive owner-qualified effects plus a diagnostics-only risk tier ([170-194](../plugin-management-and-isolated-execution-improvement-plan.md#L170-L194)). Untrusted secret-bearing/durable mutation has direct network denied and no reusable raw credential; deliberate coarse direct authority loses exact plan/apply claims ([521-550](../plugin-management-and-isolated-execution-improvement-plan.md#L521-L550)). Canonical plan and recovery semantics belong to the exact domain owner ([578-591](../plugin-management-and-isolated-execution-improvement-plan.md#L578-L591)). |
| HIGH-1: legacy Skill-to-shell path | **Resolved** | Managed and legacy compatibility lanes are explicit; legacy instructions remain generic Tool actions and cannot acquire managed Skill-script identity or authority ([214-260](../plugin-management-and-isolated-execution-improvement-plan.md#L214-L260)). PLC8A and verification preserve this distinction ([718-732](../plugin-management-and-isolated-execution-improvement-plan.md#L718-L732), [941-944](../plugin-management-and-isolated-execution-improvement-plan.md#L941-L944)). |
| HIGH-2: kill and quota overclaim | **Resolved at plan level** | Required containment vocabulary now covers process-tree/PID ownership, CPU, memory, wall clock, output, temporary storage, and platform cleanup where required; unenforced limits cannot be advertised ([423-432](../plugin-management-and-isolated-execution-improvement-plan.md#L423-L432)). Incomplete termination is an explicit non-success state that retains leases and blocks retirement/GC ([468-491](../plugin-management-and-isolated-execution-improvement-plan.md#L468-L491), [946-957](../plugin-management-and-isolated-execution-improvement-plan.md#L946-L957)). |
| HIGH-3: Worker pooling and security revocation | **Partially resolved** | Session ownership and the V1 prohibition on cross-actor/Product/workspace/revision/environment/profile pooling are explicit ([365-369](../plugin-management-and-isolated-execution-improvement-plan.md#L365-L369)). Pre-start revocation identity is bound and revalidated. The running-Worker security-revocation sequence remains under-specified; see residual P1-1 below. |
| HIGH-4: no-secret-in-logs overclaim | **Resolved** | The guarantee is narrowed to Host-generated records. Opaque handles/Host-authenticated effects are the default; raw materialization makes child output a separately authorized restricted artifact, with redaction described only as defense in depth ([307-312](../plugin-management-and-isolated-execution-improvement-plan.md#L307-L312), [959-971](../plugin-management-and-isolated-execution-improvement-plan.md#L959-L971)). |
| HIGH-5: partial workspace writes | **Resolved** | Direct writes are explicitly non-transactional, abnormal termination reports partial/unknown state, and rollback requires a Product-owned checkpoint or atomic/file-effect owner ([314-320](../plugin-management-and-isolated-execution-improvement-plan.md#L314-L320), [998-1007](../plugin-management-and-isolated-execution-improvement-plan.md#L998-L1007)). |
| MEDIUM-1: generic owner of durable mutation | **Resolved** | Harness is limited to neutral envelopes/mechanics; exact Product/domain owners own ChangeSet schemas, observations, journals, apply interpretation, reconcile, compensation, and safe abandon ([505-519](../plugin-management-and-isolated-execution-improvement-plan.md#L505-L519), [578-591](../plugin-management-and-isolated-execution-improvement-plan.md#L578-L591)). |

### Residual And New Findings

#### P1-1: Running-Worker security revocation is not mapped to the new coordinator lifecycle

The revision prevents stale start and forbids unsafe pooling, but it does not
state how the accepted Plugin security-revocation invariant enters
`WorkerAttemptCoordinator`, exact-owner routing, broker callbacks, and direct
mount lifetime after a Worker is running. The only explicit Worker lifecycle
path is ready/drain/stop/failure; the verification matrix rejects stale attempts
but does not exercise a current attempt racing security revocation.

This is a residual portion of original HIGH-3, not a new architecture owner.
The accepted architecture already supplies the required governing order:
controlled leases are invalidated before isolated-service termination, direct
authority remains dangerous until confirmed process exit, and incomplete
termination cannot be reported as successful disable
([Unified Plugin Architecture, lines 1072-1092](../../../harness/unified-plugin-architecture.md#L1072-L1092)).

Required narrow correction before PLC9B implementation:

1. Map the revocation linearization point into the exact owner and coordinator:
   stop new routing/acquisition; invalidate invocation, broker, secret, and
   effect capabilities; enter `REVOKING`; then terminate and settle containment.
2. State that a Worker with a direct readable/writable mount remains
   security-active until confirmed process/containment settlement. A logical
   token revocation cannot revoke already granted direct OS access.
3. Preserve `termination_incomplete` and all package/environment/private-state
   leases after a failed kill; do not project disabled/retired success.
4. Add adversarial races for revocation versus callback, in-flight request,
   direct write, drain, natural exit, and Host close.

This is **P1 and blocks PLC9B security acceptance**, but it does not reopen the
four original blockers or require a new owner.

#### P1-2: The Approval subject binds “enforced” containment evidence before the containment plan exists

The start subject is described as binding enforced containment capabilities at
lines 398-402, while the stated lock order does not reserve/create the actual
containment plan until after durable Approval consumption at lines 408-413.
Unless the subject distinguishes required/preflight capability claims from the
actual per-attempt enforcement descriptor, it can present anticipated evidence
as already enforced or force an unsafe await/plan while holding an earlier
authorization transaction.

Required narrow correction:

1. The Approval subject binds the `ExecutableContainmentRequirement`, selected
   backend/profile identity and policy/probe revision, not a claim that the
   per-attempt scope is already enforcing.
2. After Approval consumption, containment planning returns an actual immutable
   enforcement descriptor. Before spawn, the coordinator verifies it covers the
   approved requirement and records its digest on the start-use/attempt record.
3. Any mismatch or degraded/failure result transitions the consumed use to the
   appropriate pre-spawn failure state and never starts code; it does not return
   the decision to available.
4. Approval/audit/status projections label `required`, `selected/probed`, and
   `actual enforcing` evidence as three different facts.

This is a **new P1 contract-precision issue**, not a P0: the revised plan already
requires fail-closed capability completeness, so correcting the evidence phase
does not change the topology or authority model.

### Re-review Verdict

**Conditional pass for the revised plan's security architecture shape.** All
four original blockers are substantively resolved, and no new P0 was found.
The revision is a material security improvement and now correctly separates
process topology, Sandbox enforcement, additive authority, Approval uses,
exact owner publication, legacy Skill execution, brokered mutation, secret
output, and honest partial/cleanup states.

Before architecture acceptance or PLC9B implementation, make the two narrow P1
corrections above: add the running-Worker security-revocation mapping and split
pre-start containment requirements from post-plan enforcement evidence. After
those changes, this security review has no remaining plan-level blocker.

This verdict approves only the proposal's shape. Untrusted executable support
still cannot ship until the execution/Worker ARD, platform capability matrix,
versioned subjects/use records, and adversarial gates required by the proposal
are implemented and pass.

### Final Closure Check

Closure baseline: revised plan SHA-256
`ed6fe0da4c9bdf21d3cc162cb2b1a3e9d3aba343d71dfe578019a41ab01e9dcc`
against local source commit
`257dbd5cf78bba8f81e3a7546e961d935adb19f9`.

- **P1-1 running-Worker security revocation: closed.** The exact owner now
  blocks routing/acquisition, Approval/Policy invalidates invocation, broker,
  secret and effect capabilities, the Plugin Instance enters `REVOKING`, and
  only then does the coordinator shut down and physically settle the process
  and containment. Direct mounts remain security-active until confirmed exit;
  failed termination retains leases and cannot project disabled/retired success
  ([revised plan, lines 526-535](../plugin-management-and-isolated-execution-improvement-plan.md#L526-L535)).
  The same order and direct-mount caveat are executable verification gates
  ([lines 1084-1086](../plugin-management-and-isolated-execution-improvement-plan.md#L1084-L1086)).
- **P1-2 containment evidence phase: closed.** Approval now binds the required
  capability set plus selected backend/profile and probe/policy revisions,
  explicitly without claiming that a per-attempt Sandbox already exists. After
  consumption, containment planning returns an immutable actual enforcement
  descriptor; coverage is checked and recorded before spawn, while mismatch or
  degradation becomes a durable pre-spawn failure
  ([lines 420-454](../plugin-management-and-isolated-execution-improvement-plan.md#L420-L454)).
  Verification independently checks required/selected facts and actual
  enforcement evidence ([lines 1070-1076](../plugin-management-and-isolated-execution-improvement-plan.md#L1070-L1076)).
- **Staged install: no new P0/P1.** Management coordinates but does not own or
  materialize package bytes; the existing resolution authority verifies and
  publishes the revision before an install-disabled CAS. CAS/crash failure
  leaves inert pinned bytes and an idempotent retry/orphan-repair record, never
  inferred enablement ([lines 668-690](../plugin-management-and-isolated-execution-improvement-plan.md#L668-L690)).
- **Package-owned prepared environment: no new P0/P1.** It is an immutable
  derived child of one exact package revision, cannot be shared across packages
  in V1, has a canonical identity and preparation receipt, and reuses existing
  package pins, recovery barrier, cleanup and byte-level GC recheck. Install,
  prepare, enable and invoke remain separate; no package manager/build runs
  implicitly, and Approval/launch/rollback/cleanup bind the exact environment
  identity and lease
  ([lines 825-846](../plugin-management-and-isolated-execution-improvement-plan.md#L825-L846)).
  Any future install/build hook remains a separately approved and isolated
  executable operation ([lines 298-302](../plugin-management-and-isolated-execution-improvement-plan.md#L298-L302)).

**Final security verdict: closed at plan level.** Both residual P1 findings are
substantively resolved, and the staged-install/environment additions introduce
no evident security P0/P1. This is not runtime certification: shipping
untrusted execution still depends on acceptance and implementation of the
required ARD, platform containment matrix, versioned Approval/use contracts,
package/environment recovery, and adversarial conformance gates.
