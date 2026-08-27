# Plugin Management And Isolated Execution Improvement Plan

## Status

- Authority: proposed — non-normative cross-scope delivery plan
- Design status: proposed, revised after three independent reviews
- Implementation status: partial foundations exist; proposed PLC8/PLC9 slices
  and executable SDK contracts are not implemented
- Owner: Loushang architecture; affected owners include Harness, Product,
  Resource, execution, Approval, Sandbox, and domain effect owners

This plan is not accepted architecture.

The later source-revision, contribution-selection, and mutable-state
refinements were made after those reviews and remain subject to the same ARD and
delivery gates.

This document turns the current Plugin lifecycle, execution-trust, process
hosting, and Skill-script requirements into one staged delivery plan. It does
not supersede the accepted ownership, admission, Graph, Approval, Sandbox, or
process-hosting boundaries. Any conflict with a live ARD or implemented
contract must be resolved in favor of the live source until a separate
architecture decision accepts a revision.

Independent review records:

- [Security review](reviews/plugin-management-and-isolated-execution-security-review.md)
- [Authoring review](reviews/plugin-management-and-isolated-execution-authoring-review.md)
- [Architecture review](reviews/plugin-management-and-isolated-execution-architecture-review.md)

All three reviews accepted the direction but requested changes before
architecture acceptance. This revision incorporates their common blockers:
additive effects instead of a second effect taxonomy; a non-owning Worker
attempt coordinator; an authorized verified-launch adapter above one-shot Exec;
required containment for untrusted code; separate script/Worker Approval use
records; Session-owned Worker V1; exact domain ownership for durable mutation;
and an explicit mapping into the existing PLC8/PLC9 delivery sequence.

## Executive Decision

Loushang should support executable Plugin and Skill content, including Python,
Shell, Node, and native helpers. It should not interpret "support" as importing
all executable content into the Product Host.

The target has four execution shapes:

1. `declarative`: inert Resources, manifests, prompts, Skill instructions, and
   static declarations are parsed by typed Component Hosts without arbitrary
   code execution;
2. `oneshot_process`: bounded Skill scripts and command-like helpers run through
   a new Product-owned authorization/verified-launch adapter over the existing
   neutral one-shot Exec mechanics;
3. `isolated_worker`: long-lived, stateful, streaming, dependency-conflicting,
   or third-party executable providers run in supervised child processes over
   a versioned IPC protocol; and
4. `trusted_in_process`: only explicitly host-equivalent, admitted first-party
   or OEM code may execute inside the Product Host.

Execution shape is selected from trust, required authority/effect set,
lifecycle, and dependency isolation. It is not selected solely from whether a
package is called a Resource Plugin, Skill, Tool Plugin, or Provider. These
shapes describe target execution topology and lifecycle; they do not silently
replace the current `data_only | in_process` declaration codec. Advancing that
codec and adding isolated declaration-source/runtime arms requires a versioned
architecture decision and migration.

Separate process execution is necessary but is not a security sandbox. A child
running as the same user may still read files, use credentials, access the
network, or launch processes unless an OS containment plan and Host-owned
capability boundary prevent it. The isolated Worker milestone is therefore not
complete until its sandbox, authority, Approval, audit, termination, and lease
contracts are executable.

Terraform contributes two distinct patterns that Loushang should adopt
separately:

- executable providers as separate processes behind a stable protocol; and
- plan/approve/apply/reconcile semantics for durable external mutations.

Terraform's documented Plugin architecture executes Providers as separate
processes over RPC; HashiCorp's `go-plugin` documents the same subprocess/RPC
pattern and its crash/protocol benefits. Neither source makes same-user process
separation a substitute for Loushang's Sandbox and authority enforcement:
[Terraform Plugin architecture](https://developer.hashicorp.com/terraform/plugin/how-terraform-works),
[HashiCorp go-plugin](https://github.com/hashicorp/go-plugin).

The first is the default for untrusted executable providers. The second is
reserved for durable, expensive, partially reversible, or externally visible
changes; ordinary analyzers, formatters, LSP servers, and bounded Skill scripts
must not inherit a Terraform-shaped state machine without need.

## Why This Plan Exists

The current architecture has stronger lifecycle and governance primitives than
its public Plugin-management product surface:

- immutable package identity, preflight evidence, execution trust, Approval,
  desired state, owner generations, retirement, and recovery have accepted or
  implemented foundations;
- `PluginManagementService` exists as the intended mutation authority;
- the Harness process-hosting boundary already owns bounded long-lived child
  process mechanics and an authorized launcher; and
- the Coding LSP Plugin route provides one real executable vertical proof.

The remaining gap is an end-to-end author and operator control plane. Public
authoring, packaging, status/explain UX, isolated Worker evaluation, Skill
script execution metadata, effect mediation, retained-version cleanup, and
multiple production adopters are incomplete or fragmented across old and new
paths.

This plan closes that gap without introducing another Profile resolver,
Registration owner, Graph, Approval store, Sandbox, raw subprocess API, or
universal `PluginContext`.

Current authority baseline:

- [Unified Plugin Architecture](../../harness/unified-plugin-architecture.md)
- [Plugin Lifecycle And Coding Pluginization Delivery Plan](../../harness/plugin-lifecycle-coding-pluginization-plan.md)
- [Resource Catalog Pluginization Plan](../../harness/resource-catalog-pluginization-plan.md)
- [Harness Process Hosting Boundary](../../harness/process-hosting-boundary.md)
- [Harness Workspace Execution Boundary](../../harness/workspace-execution-boundary.md)

## Goals

- Provide one understandable install-to-retirement Plugin lifecycle through
  CLI, RPC, UI, and SDK adapters.
- Make Skill scripts a supported first-class execution payload.
- Keep inert content cheap while preventing untrusted code from entering the
  Product Host.
- Reuse the existing neutral one-shot Exec mechanics and long-lived Process
  Host boundary through new narrow Product adapters.
- Make executable identity, authority, execution shape, runtime generation, and
  effective owner contribution explainable.
- Support deterministic cancellation, drain, kill, recovery, update, rollback,
  and garbage-collection behavior.
- Add plan/apply only where durable external effects justify it.
- Preserve fixed Product ownership: Plugins contribute through admitted typed
  seams and do not replace core control-plane owners.

## Non-Goals

- Turning the Agent loop, Approval owner, Sandbox owner, Profile resolver, or
  Registration owner into arbitrary third-party Plugins.
- Treating a same-user subprocess or IPC channel as a complete security
  boundary.
- Making every Skill script a long-lived Worker.
- Supporting arbitrary hot replacement across owner, authority, dependency,
  process-topology, or multi-owner changes.
- Exposing raw `subprocess`, Process Host, transport, or Sandbox internals to
  Plugin authors.
- Defining a generic remote-object protocol such as `call(method, Any)`.
- Running install hooks or ambient dependency installers merely because a
  package was downloaded.
- Publishing a stable public Plugin SDK before multiple production contribution
  shapes pass compatibility and lifecycle conformance.

## Normative Classification

### Orthogonal Placement Inputs

Execution never derives trust or topology from one overloaded source label. The
Host resolves four independent inputs before admission: source authority,
installation/selection scope, release provenance, and requested execution
shape. `product_embedded`, `project_local`, `user_global`, and `session` are
placement or selection facts; none grants execution authority. An Executor- or
Orchestrator-owned source, if later admitted, is read only through its owning
provider and never reinterpreted as a Host filesystem path.

The immutable execution identity below is therefore source-neutral:

```text
ExecutableSourceRevision
  = PackageRevision(package_id, revision, digest)
  | ResourceSnapshotRevision(authority, resource_root_id, revision, digest)
```

Both variants are Host-resolved, content-addressed, leased, and immutable for
the duration of a decision and attempt. The second variant gives a native Skill
a managed development/runtime path without manufacturing a Plugin Instance,
Plugin desired state, or package lifecycle.

### Execution Shape

The four names below are operator/author shorthand, not one new persisted enum.
The authoritative record keeps orthogonal axes: declaration evaluation route
(`data_only`, admitted in-process, or isolated evaluator), runtime topology
(none, one-shot, long-lived local Worker, or separately admitted remote
service), execution trust (data-only, containment-required, or
host-equivalent), and lifetime/scope (invocation, Session, or a future accepted
scope). Existing codecs advance explicitly per axis.

| Shape | Intended use | Default trust rule | Host boundary |
| --- | --- | --- | --- |
| `declarative` | Skill instructions, prompts, Resources, schemas, static Tool and service declarations | Any admitted source whose inert bytes validate | Typed parser and Component Host |
| `oneshot_process` | Bounded Python/Shell/Node scripts, formatters, generators, migration helpers | Third-party permitted only when required containment is proven | Product-owned authorized Skill-script adapter over `ExecService` |
| `isolated_worker` | Stateful providers, indexes, LSP/MCP-style services, streaming or frequent calls, native or conflicting dependencies | Required for executable code below host-equivalent trust | Exact Component Host/owner plus internal Worker attempt coordinator over `AuthorizedProcessLauncher` |
| `trusted_in_process` | Narrow low-latency built-ins with compatible dependencies | Explicit host-equivalent trust only | Existing verified evaluation and Component Host path |

Installation and signature verification do not choose an execution shape and
do not grant execution authority. A package declaration proposes a maximum
shape and authority requirement; Product policy, Profile ceilings, Approval,
platform containment, and runtime admission choose or reject the effective
shape.

### Additive Effects And Derived Risk Tier

Every executable declaration requests an additive, owner-qualified authority
set. Every invocation carries the exact Host-resolved `ToolEffect` set and one
non-widening `EffectiveExecutionProfile`. Filesystem, process, network,
publication, secret, and external-domain effects remain independently visible
through Policy, Approval, Sandbox/broker enforcement, and audit. This plan does
not introduce a competing Plugin-only authority classifier.

A derived risk tier may summarize the set for routing and UX:

| Derived risk tier | Example effect set | Minimum enforcement |
| --- | --- | --- |
| `compute_only` | private temporary filesystem only | Bounded process; minimal environment; no workspace/network/secret access |
| `workspace_read` | admitted read roots | Read-only containment and redacted diagnostics |
| `workspace_write` | admitted read/write roots | Scoped writable roots, command-level policy, cancellation, partial-write reporting |
| `process_or_network` | process and/or network effects | Capability-complete Sandbox or Host broker, time and byte limits |
| `external_mutation` | owner-qualified external-domain effects | Exact domain-owner Approval; plan/apply when durable or partially reversible |
| `host_control` | control-plane mutation | Not available to ordinary third-party Plugins |

The risk tier is diagnostics only and grants no authority. If a platform cannot
enforce every required effect restriction, untrusted execution fails closed
before process creation. `best_effort` containment is limited to explicit
host-equivalent Product policy and is always reported as degraded, never as
sandbox-enforcing.

### Decision Matrix

| Payload or behavior | Default execution | Additional rule |
| --- | --- | --- |
| `SKILL.md`, templates, static assets | `declarative` | Parsing never executes adjacent scripts |
| Skill Python/Bash/Node helper | `oneshot_process` | Exact revision and script digest; frozen interpreter, argv, cwd, environment, and authority |
| Skill helper requiring warm cache or interactive stream | `isolated_worker` | Typed protocol and Session-owned Worker lease |
| Third-party Python Provider | `isolated_worker` | In-process import is rejected regardless of cooperative typed facets |
| Native extension or incompatible dependency graph | `isolated_worker` | Dedicated environment or immutable runtime image |
| First-party low-latency Provider | `trusted_in_process` may be allowed | Host-equivalent status must be explicit; update may require restart |
| Persistent external mutation | `isolated_worker` plus effect mediation | Plan/approve/apply/reconcile when a stable plan is meaningful |

## Skill Script Contract

Skill scripts are executable payloads, not inert Resources. Their presence does
not make the whole Skill a Worker, and installing or inspecting a Skill must
never execute them.

Two compatibility lanes are explicit:

1. an existing `SKILL.md` may instruct the Agent to run an adjacent script
   through the ordinary Shell/Tool path; this remains supported under generic
   Tool Policy and Sandbox semantics, but is never reported as verified
   Skill-script execution; and
2. an optional named `SkillScriptDeclarationV1` enables a dedicated
   `skill.script.run` action with stable identity, structured input/result,
   exact executable-source/runtime evidence, and script-specific diagnostics.

Generic Tool preparation resolves script/executable arguments against known
Resource/Plugin roots when possible and attaches non-authoritative package,
Skill, source-kind, revision, and trust provenance to Policy, Approval, and
audit. This never upgrades the command to managed execution or grants package
authority. Raw script execution from an installed third-party Skill defaults
to at least `ask` plus required generic-Tool containment, or a stricter Product
deny policy; it is never an unspecified allow. Project-local/user-authored
legacy scripts retain the Product's ordinary generic Tool policy.

Markdown instructions are guidance, never authority, and cannot select an
execution profile or suppress Approval. Validation may identify likely
undeclared adjacent scripts for migration, but it must not pretend to derive a
sound executable contract from prose.

The managed declaration is a strict, versioned owner-specific part of the
Resource owner's Skill schema. It may arrive through a packaged Resource
declaration or a Product-supported native Skill sidecar; both compile to the
same owner descriptor. It is not arbitrary `SKILL.md` frontmatter, a new Skill
registry, or one Plugin Instance per Skill. Existing content-only and
instruction-driven Skills require no manifest change. Invalid optional script
metadata makes that script unavailable without erasing inert Skill content; a
script explicitly required by an owning package makes that package contribution
inadmissible.

`SkillScriptDeclarationV1` contains a stable Skill/script ID, a package-relative
or Resource-root-relative entrypoint, Product runtime requirement, structured
input/result mode, requested additive authorities, resource/output limits,
platform predicates, and schema version. It is a requested ceiling, not an
authority token. The author never supplies package digests, Approval records,
runtime fingerprints, or leases.

Requested script authorities are inert owner-specific payload data. They do
not populate the data-only `resource_item` contribution's execution-authority
field, do not change Skill discovery into executable admission, and are
compiled into concrete effects only when `skill.script.run` is prepared. The
Product runtime requirement resolves through the existing Product-owned
toolchain/Capability predicate path; it is not another Runtime Profile selector
or dependency graph.

For every managed execution, the Host-built invocation binds at least:

- exact `ExecutableSourceRevision`; packaged sources additionally bind complete
  package and dependency-closure digests, while native sources bind source
  authority, Resource root, snapshot revision, and complete snapshot digest;
- declaration and entrypoint digest;
- interpreter/runtime identity and dependency-lock digest;
- exact argv, absolute admitted cwd, frozen environment fingerprint, and
  redacted display form;
- Product, Profile, Session, actor, and invocation identity;
- exact additive effects, effective execution profile, enforcement evidence,
  and secret-handle references;
- deadline, output limits, abort state, and Approval/audit correlation; and
- artifact/result ownership and cleanup policy.

Project-local development uses a Host-created ephemeral content-addressed
snapshot and then traverses this same managed route. A mutable local path that
has not been snapshotted remains only a generic Tool command and receives none
of the managed-path identity claims.

An internal `AuthorizedSkillScriptExecutor` sits above `ExecService`. It accepts
only an owner-admitted descriptor, leased verified revision, Product-resolved
toolchain, additive effect set, and execution scope. It constructs a minimal
allowlisted environment from empty rather than inheriting `os.environ`,
revalidates identity/Profile/revocation/containment immediately before launch,
and holds revision, runtime, artifact, secret, and containment leases through
physical process settlement. `ExecService` remains the neutral subprocess,
streaming, cancellation, and capture mechanism; it is not itself the complete
authorization or immutable-launch boundary.

Shell-free launch means the Host constructs an argument vector such as
`["bash", verified_script, "--flag"]`; it does not forbid Bash scripts. It
forbids concatenating untrusted values into an ambient shell command string.
The runtime and allowed helper tools resolve through a Product-owned,
digest/version-qualified toolchain registry rather than ambient `PATH`.
Requested executable or endpoint allowlists are reported as cooperative and
rejected for untrusted use unless the selected Sandbox can enforce them or the
operation is brokered by the Host.

Runtime dependency installation is not an implicit script right. Dependencies
must be resolved into a verified lock and immutable environment during an
explicit preparation operation, or the invocation must use an admitted Product
toolchain. Install/build hooks, if later supported, are executable operations
with their own isolation and Approval subject.

### Script Result Model

V1 uses either no input or one JSON-compatible value encoded as UTF-8 JSON on
stdin. Stdout is declared as bounded UTF-8 text or one strict JSON value;
stderr is bounded diagnostic/log output. Exit code zero is success, non-zero is
failure, and timeout, cancellation, containment failure, invalid output,
rejected artifact, and partial workspace write are distinct terminal results.

Business artifacts are written only below a fresh Host-owned output directory.
After process settlement the Host validates containment, regular-file type,
symlinks/hard links/devices, file count, total bytes, declared name/media type,
and post-exit stability before publishing immutable artifact references. A
Plugin-returned path never becomes a trusted artifact reference by itself.

The minimum result contains terminal reason, exit status where present,
bounded stdout/stderr references, structured diagnostics, validated artifact
references, duration, containment evidence, and a partial/unknown workspace
state flag where applicable.

Host-generated records never include secret material. Untrusted execution gets
opaque credential handles and Host-performed authenticated effects by default.
If raw secret bytes are explicitly materialized, child output is treated as
potentially secret-bearing and goes to a separately authorized restricted
artifact channel; known-value redaction is defense in depth, not proof that a
malicious child did not transform the secret.

A script that only writes through its directly mounted workspace receives a
coarse, visible `workspace_write` authority. A script that needs individual
high-risk effects should request them through the Effect Broker so the Host can
authorize and audit each exact action. Direct workspace writes are
non-transactional: abnormal termination reports `partial_workspace_write` or
`unknown_workspace_state`. Rollback requires a Product-owned checkpoint,
staging/atomic-apply protocol, or exact file-effect owner.

## Target Runtime Architecture

```text
author CLI/SDK --> PluginAuthoringService --> validate / canonical pack

management adapters --> PluginManagementService --> desired/operational intent
query adapters -------> inventory + exact owner/runtime projections

desired state + trust + Approval + admission
                    |
                    v
           exact Product / Component owner
                    |
                    +-- declarative ------> owner publication
                    |
                    +-- Skill invocation -> AuthorizedSkillScriptExecutor
                    |                         -> ExecService
                    |
                    +-- Worker-backed candidate
                              -> WorkerAttemptCoordinator
                              -> AuthorizedProcessLauncher
                              -> Session-owned sandboxed process
                              -> versioned IPC / owner-qualified broker facets
                    |
                    `-- exact owner alone publishes/retires contribution
```

The management service remains the sole Plugin mutation authority. The
management service records desired state and typed operational intent; it does
not launch, route, publish, stop, or dispose a Worker directly. Pure authoring
operations and read projections are separate APIs. Cross-owner `explain`
presentation shows each source revision and missing/skewed evidence instead of
inventing one effective clock.

Plugin desired state remains Plugin-identity-level. Per-contribution selection
and policy are stable-ID, owner-qualified configuration projected through
existing configuration and Product composition owners. Required contributions
form a new-Session readiness barrier; optional failures are reported as
`partial`. This barrier never lets `PluginManagementService` publish an owner
generation or pretend that several owner clocks committed atomically.

The exact Component owner prepares and publishes a Worker-backed candidate.
The internal `WorkerAttemptCoordinator` consumes accepted start authority,
drives protocol mechanics, and reports observations; it is not a Registration
owner, management writer, package-state owner, effective projector, or durable
domain-state owner. `ProcessHost` retains physical process reservation and
termination ownership, `PluginInstanceRuntimeLedger` retains direct-host
Instance lifecycle, the exact owner retains routing/publication/drain, and the
existing package lifecycle retains quarantine, repair, retention, and GC.

Worker V1 is Session-owned because the accepted launcher and Sandbox execution
runtime are Session-owned. Cross-Session/workspace/process pooling requires a
separate accepted hosting scope, quota owner, authorization scope, recovery
barrier, and isolation proof. V1 never pools across actor, Product, workspace,
Plugin revision, dependency environment, or effective authority profile.

### Mapping To Existing Authorities

| Proposed concept | Existing authority or required versioned extension |
| --- | --- |
| Execution shape | Orthogonal target topology/lifecycle mapping; version the current `PluginContributionExecutionModel` and declaration-source arms rather than replacing them implicitly |
| Managed Skill script | Owner-specific Resource/Skill schema inside the one Resource catalog; no per-Skill Plugin or registry |
| Executable source revision | Existing immutable package revision or Resource-owner source snapshot plus the corresponding lease; no path-derived identity |
| One-shot script execution | New `AuthorizedSkillScriptExecutor` Product port over existing neutral `ExecService` mechanics |
| Worker attempt | Correlation across existing Plugin Instance revision, exact owner candidate/generation, Approval use, Session runtime, `ProcessHandle`, and package lease; no new effective clock |
| Worker-backed effectiveness | Existing exact Capability/Resource/Extension/external-service owner publication only |
| Process lifecycle | Existing Session `ProcessHost` and `SandboxExecutionRuntime` |
| Plugin desired state | Existing `PluginManagementService` durable commands |
| Package retention/quarantine/GC | Existing resolution authority, verified revision store, dependency lock, package lifecycle ledger, recovery barrier, and GC recheck |
| Prepared dependency environment V1 | Immutable child artifact of one exact package revision, extended into the existing package lifecycle with its own derived identity, preparation receipt, pin, cleanup task, recovery evidence, and byte recheck; no cross-package sharing |
| Approval authority | Existing Approval owner with new discriminated subjects/use records |
| Durable external mutation | Exact Product/domain owner; Harness supplies only neutral envelopes/mechanics |

### Mutable Component Data

Executable isolation needs an explicit data boundary; otherwise a nominally
isolated Worker can turn one ambient writable directory into an unversioned
shared service locator. Artifact and prepared-environment revisions stay
read-only. Mutable data is requested by subject and classified as rebuildable
cache, durable domain state, credential reference, or published business
Artifact.

No new `PluginDataManager` owns all four classes. Existing Product/domain,
credential, Artifact, quota, and package-lifecycle owners remain authoritative.
A common request envelope may normalize subject, Product/Profile,
tenant/workspace, schema, quota, and retention, after which the exact owner may
issue a bounded facet or attempt-scoped mount and lease. Disable retains durable
state; artifact uninstall/GC does not delete it; deletion and schema migration
are separate authorized domain operations. Failed migration preserves the prior
usable revision and the leases required for recovery or rollback.

## Approval And Containment Before Process Creation

The execution/Worker ARD gate must version the existing Approval-owner
contracts with distinct subjects and use records for:

- managed Skill-script invocation/start;
- isolated declaration evaluation, which may emit only frozen declarations;
- the process-backed arm of admitted contribution activation; and
- later invocation/effect actions.

Declaration evaluation and runtime activation never reuse a decision, receipt,
nonce, or process identity. Worker spawn is the process-backed arm of one
versioned `ContributionActivationApprovalSubject` and activation-use
reservation, not a second independent Plugin start Approval. The generic
`process.host.start` gateway still enforces process policy but cannot substitute
for or duplicate the Plugin activation decision.

A start subject binds the exact package, declaration/entrypoint,
runtime/dependency, argv/cwd/environment fingerprint, Plugin Instance, owner
candidate, Session, execution profile, `ExecutableContainmentRequirement`,
selected backend/profile identity and probe/policy revision, trust/policy
revisions, actor, expiry, and revocation epoch. It does not claim that a
per-attempt Sandbox is already enforcing before its plan exists. The existing
Approval owner records consumption and start-use recovery; the attempt
coordinator records process observations, not authorization facts.

Because Plugin code begins at OS spawn rather than successful handshake, the
lock/order contract is:

```text
start permit
  -> durable Approval consume/use transition
  -> Plugin Instance and exact-owner lifecycle gates
  -> required containment reservation
  -> immutable actual enforcement descriptor and requirement coverage check
  -> process spawn
  -> handshake/health
  -> prepared candidate returned to exact owner
  -> exact owner publication
```

No executable byte runs before the durable start transition. Crash recovery
distinguishes consumed-not-started, starting, running/ready, draining, stopped,
failed, unknown-after-crash, and cleanup-incomplete where applicable.

After Approval consumption, containment planning returns an immutable actual
enforcement descriptor. Before spawn the coordinator proves that it covers the
approved requirement and records its digest on the start-use/attempt record.
Mismatch, degradation, or planning failure produces a durable pre-spawn
failure and never returns the decision to available. Approval, audit, and
status label required, selected/probed, and actual-enforcing evidence as three
different phases.

An `ExecutableContainmentRequirement` names the exact backend capabilities
required by an execution profile. For code below host-equivalent trust it is
always `enabled + required`; disabled, best-effort, degraded, unresolved, or
capability-incomplete containment fails before process creation. Status reports
process separation, Sandbox enforcement, and the exact enforced capabilities
as separate facts. Capability vocabulary includes filesystem, network,
process-tree/PID ownership, CPU, memory, wall clock, output bytes, temporary
storage, and platform cleanup guarantees where the selected profile requires
them. A limit that Process Host merely records but the backend cannot enforce
is not advertised as containment.

## Plugin Worker Protocol V1

### Protocol Principles

- Prefer strict, bounded, language-neutral value messages. Do not use Python
  `pickle`, arbitrary object proxies, or implicit import callbacks.
- The initial local transport may use framed JSON over raw stdin/stdout. Protobuf
  or gRPC is justified only after message evolution, streaming, and cross-
  language evidence require it.
- Stdout used for protocol frames cannot simultaneously be ambient Plugin
  logging. Logs use a separate bounded stderr/event path.
- Every message carries protocol version, Worker attempt ID, exact owner
  candidate/reference, Session runtime identity, request ID, and
  size/deadline enforcement where applicable.
- Transport possession is not authority. Every Host callback rechecks the
  invocation scope and effective capability.

### Handshake

Before readiness the Worker proves or echoes:

- protocol version and compatible feature set;
- package, declaration, entrypoint, dependency-lock, and runtime digest;
- Product and Plugin instance identity;
- Worker attempt, activation-use, exact owner candidate, Session runtime,
  revocation epoch, and execution-profile identifier;
- supported typed service contracts and schema versions; and
- a Host-issued nonce bound to the launched process and exact launch
  fingerprint.

A mismatch terminates the process before any contribution becomes visible.
The handshake is process identity and compatibility evidence; it does not
replace package verification, Sandbox containment, or Approval.

### Lifecycle

The coordinator observes one non-authoritative process attempt:

```text
reserved -> starting -> handshaking -> ready -> draining -> stopped
                                  \-> failed / cleanup_incomplete
```

- Capacity is reserved before spawn.
- Readiness returns a prepared service candidate after handshake and health;
  only the exact owner may publish it.
- The exact owner stops routing and requests drain; the coordinator lets
  bounded in-flight calls finish.
- Stop escalates from protocol shutdown to terminate to process-group kill.
- Cancellation never skips lease, stream, containment, or process cleanup.
- Natural exit and explicit stop converge on one terminal result.
- Responses from retired attempts or owner generations are rejected.
- Crash-loop suppression is an owner/policy diagnostic. It does not quarantine
  package bytes; package quarantine requires separate security evidence through
  the package owner.
- Failed/best-effort process-tree termination is
  `termination_incomplete`/`cleanup_incomplete`, blocks retirement success and
  GC, and is never projected as stopped.

Security revocation linearizes through existing owners in this order: the
exact owner blocks new routing/acquisition; Approval/Policy invalidates
invocation, broker, secret, and effect capabilities; the Plugin Instance enters
`REVOKING`; the coordinator requests protocol shutdown and then physical
termination/containment settlement. A Worker with direct filesystem mounts
remains security-active until confirmed process and containment exit. Failed
termination preserves package, environment, private-state, and cleanup leases
and cannot project disabled or retired success. Adversarial gates cover revoke
racing callbacks, in-flight requests, direct writes, drain, natural exit, and
Host close.

### Invocation

Requests contain a typed service/method identifier, schema version, bounded
input, request ID, deadline, cancellation identity, exact additive effect set,
invocation capability, and idempotency metadata when relevant. Streaming uses
explicit sequence and backpressure frames. Unknown methods, fields, schema
versions, frames, or oversized payloads fail deterministically.

The protocol should expose narrow service contracts such as analyzer,
formatter, index, external service, or mutation planner. It must not expose one
universal Plugin context that can discover and call arbitrary Host services.

### State And Recovery

Model-visible or externally authoritative state cannot live only in Worker
memory. Existing exact Product/domain owners own authoritative operation
journals, owner generation/routing, checkpoints, and effect receipts; Harness
may supply neutral envelopes and journal mechanics but does not interpret
domain state. Plugin-private caches may remain disposable.
Durable Plugin-private data is namespaced by Product, Plugin identity, package
revision, schema version, and scope, with explicit migration and retention
rules.

On uncertain external mutation outcome, the recorded exact domain owner marks
`unknown` and reconciles; generic Plugin management and Worker code do not
blindly replay or select a compensator. Disposers, compensations, and retries
must be idempotent or use the domain owner's journaled prepare/commit protocol.

## Owner-Qualified Effect Brokers

Effect brokering is a set of narrow Host/Product-owned facets, not one general
RPC gateway or a new external-state owner. Initial facets cover only
demonstrated needs:

- scoped workspace read/write;
- approved process/tool execution;
- approved network request profiles;
- short-lived secret materialization or credential handles;
- artifact publication; and
- calls into a registered exact Product/domain mutation owner.

Direct sandbox access and brokered effects can coexist for effects whose coarse
authority is acceptable. Low-risk, high-volume workspace reads may use a
read-only mount. For untrusted secret-bearing or durable external mutation,
direct network is denied and no raw reusable credential enters the Worker; the
exact Product/domain adapter performs the authenticated effect. If a Product
deliberately grants coarse direct network or raw credentials, diagnostics must
say so and the Product cannot claim non-bypassable per-action Approval,
plan/apply enforcement, or exact idempotency.

Diagnostics distinguish requested/cooperative declarations, OS-enforced
restrictions, broker-enforced authority, and coarse direct authority.

Each effect request binds Worker attempt, owner generation, invocation
capability/ID, actor/session, owner-qualified effect schema, exact target,
redacted display, private canonical fingerprint, deadline, and idempotency key
where required. Policy and Approval decisions are made against this
Host/domain-computed subject, not Plugin-provided prose.

## Plan / Approve / Apply / Reconcile

This path is required when all of the following are materially relevant:

- the change persists outside the current process or workspace transaction;
- failure can leave partial external state;
- the target has a readable current state or meaningful preconditions; and
- the proposed actions can be represented before execution.

The flow is:

```text
refresh/inspect
      |
      v
plan -> canonical ChangeSet -> plan digest
                              |
                        Policy + Approval
                              |
                              v
apply(exact plan digest, preconditions, idempotency key)
                              |
                              v
result / partial / unknown -> reconcile
```

Every ChangeSet schema, target identity, observation, operation journal,
precondition, result interpretation, reconcile, compensation, and safe-abandon
decision belongs to one registered exact Product/domain owner. Harness may
provide strict envelopes, correlation/idempotency fields, transport,
redaction, leases, and fault-injection fixtures; Plugin management, the Worker
coordinator, and a generic broker do not infer domain state.

The domain owner's canonical plan digest binds the exact Plugin revision,
owner/schema, target identities, observed-state fingerprint, effective
configuration, authority set, ordered or grouped effects, expiry, and redacted
presentation. Apply rejects stale or altered plans. Approval of Plugin
activation never implies Approval of future plans or actions. An untrusted
Plugin may propose input to planning, but cannot establish final target
identity, preconditions, authority, or canonical digest by hashing its own JSON.

Workspace formatting and ordinary code generation usually remain bounded
one-shot writes, not Terraform-style plans. A Product may add preview/diff UX
for them without claiming durable infrastructure reconciliation semantics.

## Management And Author Experience

### Separate Authoring, Mutation, Query, And Operation Ports

- `PluginAuthoringService` is non-executing and lifecycle-pure: validate is
  read-only inspection, while canonical pack and ephemeral snapshot are bounded
  authoring artifact operations with exact filesystem effects, cancellation,
  and atomic output publication. It never imports/executes package content or
  installs, enables, prepares, or mutates Product desired state.
- `PluginManagementService` is the only durable desired-state mutation port:
  install-disabled, remove, enable, disable, staged update, rollback selection,
  and accepted repair/data-deletion operations.
- Plugin inventory and exact owner/effective runtime projectors remain the read
  authorities for list, inspect, status, and diff.
- `plugin explain` is an adapter/presentation join over immutable projections;
  it exposes their independent revision clocks and never manufactures
  effectiveness from management inventory.
- Worker stop/restart is a typed operational intent routed to the exact owner.
  Only that owner stops routing, drains, retires, and prepares a replacement;
  management never closes a Process handle directly. The durable intent binds
  idempotency, exact owner operation reference, and eventual terminal-evidence
  reference; management may project requested/pending/unknown/failed progress
  but never converts intent into authoritative Worker or owner state.

Adapters do not edit desired-state files, materialize package roots, mutate
owner registries, launch processes, or refresh/replace contributions directly.

### Staged Install Coordination

`plugin install DIST --disabled` is one durable staged operation coordinated by
`PluginManagementService` without transferring package-byte ownership into
management. Local and future remote sources use the same transaction:

```text
source/snapshot inspection
  -> existing resolution authority verifies and publishes/binds exact revision
  -> expected inventory revision and install-disabled desired-state CAS
  -> terminal operation result
```

The command binds exact source/snapshot/package inspection identity, expected
inventory revision, idempotency key, and target desired-state change. Its
journal distinguishes inspected, published/bound, desired-state-committed,
terminal, and orphan-repair states. If verified publication succeeds and the
desired-state CAS fails or the Host crashes, the package remains inert and
pinned for idempotent retry or explicit orphan repair; it never becomes enabled
by inference. Recovery queries the existing resolution/package-binding
authorities and resumes the exact operation rather than republishing bytes or
letting an adapter materialize them. Remote acquisition changes only the source
transport, not this verified publication/install transaction.

### Explainability

`plugin explain` should project, without inference across missing evidence:

```text
source and package revision
  -> integrity and publisher evidence
  -> requested/effective trust and authority
  -> desired state and selected declaration
  -> Approval and admission result
  -> execution shape and sandbox enforcement
  -> exact owner generation and Worker attempt reference
  -> effective contributions, leases, health, and restart requirement
```

The operator must be able to distinguish:

- installed but disabled;
- enabled but rejected by trust/Profile/policy;
- admitted but waiting for restart;
- an inert Skill that is visible while one managed script is `available`,
  `unsupported_platform`, `runtime_unprepared`, `disabled`,
  `pending_approval`, `denied`, or `invalid`;
- Worker attempt starting, ready, draining, failed, cleanup-incomplete, or
  crash-suppressed;
- declared authority versus effective enforceable authority;
- failed cleanup versus complete retirement; and
- current revision versus retained rollback revisions.

### Public Authoring Surface

The author API should progress in this order:

1. stable inert manifest/resource/Skill metadata;
2. experimental versioned `SkillScriptDeclarationV1`, invocation/result codecs,
   validation, dev snapshot-run, pack, immutable install, and diagnostics;
3. zero-dependency one-shot Python conformance, followed by immutable Python
   environments and explicitly supported platform runtimes;
4. isolated declaration-evaluator and Session-owned Worker SDK candidates from
   narrow protocol schemas;
5. multiple production contribution shapes and compatibility suites; and
6. only then stabilize executable script/Provider exports and remote
   distribution UX.

The SDK exposes data types, builders, protocol adapters, test fixtures, and
diagnostics. It does not expose management internals, raw process launch,
Approval issuance, Sandbox backends, owner registrars, or mutable global
contexts.

The author conformance journey is create -> pure validate -> ephemeral
snapshot dev-run -> canonical pack -> install disabled -> explicit prepare and
enable -> typed invoke/debug -> permission-aware update/rollback. Development
uses the production identity, authorization, Sandbox, input/result, and cleanup
route; there is no `--unsafe` bypass. A simple standard-library Python script
does not require the author to implement RPC, Worker lifecycle, digest,
Approval, or Sandbox code.

Illustrative V1 commands are:

```text
loushang plugin validate PATH --target current --format json
loushang skill script run PATH SKILL_ID SCRIPT_ID --input request.json
loushang plugin pack PATH --output DIST
loushang plugin install DIST --disabled
loushang plugin explain PLUGIN_ID --format json
```

Names remain a CLI design input. The important contract is that development
run snapshots mutable source and enters the same managed invocation path as an
installed revision.

## Integration With The Existing PLC Delivery Spine

This plan is a proposed sequencing revision and decomposition of the existing
PLC8/PLC9 work. It is not a parallel PM0-PM6 master lifecycle. PLC6
(`coding.base`) and PLC7 (`coding.arch`) continue to provide the production
combination evidence required before stable public SDK publication; Worker V1
does not block those adopters. Truthful `trusted_in_process` diagnostics may be
added along their existing route.

### Execution And Worker ARD Gate

Before executable authoring implementation:

- accept execution topology, additive effects, Skill-script schema ownership,
  Worker-attempt ownership, Session scope, process-versus-Sandbox reporting,
  isolated declaration evaluation, and exact domain mutation ownership;
- define `ExecutableContainmentRequirement` and the platform capability matrix;
- version script invocation, isolated-evaluation, process-backed contribution
  activation, subsequent invocation, and effect Approval subjects/use records
  plus lock order and recovery;
- record current management/CLI/package/source paths and their sole migration
  target; and
- freeze Plugin lifecycle, LSP, Exec, Process Host, Approval, Sandbox, package
  lifecycle, and architecture-test baselines with adversarial fixtures.

Exit gate: no unresolved second owner/clock/permission model; untrusted
execution cannot start with disabled, best-effort, degraded, unresolved, or
capability-incomplete containment.

### PLC8A: Skill Owner Schema And Experimental Author Contract

Deliverables:

- preserve one Resource catalog and native content-only Skill compatibility;
- admit the same strict script declaration from a packaged Resource projection
  or a Product-supported native sidecar, with no synthetic Plugin identity;
- add strict owner-admitted `SkillScriptDeclarationV1`, invocation/result
  codecs, stable script IDs, availability states, and semantic fingerprints;
- add pure validate/target checks and an ephemeral immutable snapshot dev-run;
- define input/output, diagnostics, artifact, optional/required failure, and
  legacy generic-Shell compatibility semantics; and
- expose the contract as documented experimental/v1alpha, not stable SDK.

Exit gate: discover/list/load/model-input never execute adjacent content; the
dedicated action resolves one active exact Skill/script identity, while legacy
commands remain visibly generic Tool execution.

### PLC8B-1: Authorized Zero-Dependency One-Shot Execution

Deliverables:

- internal `AuthorizedSkillScriptExecutor` above `ExecService`;
- Product-supplied digest-identified Python runtime, standard library only;
- verified `ExecutableSourceRevision`/entrypoint/toolchain launch, minimal
  environment, exact additive effects, required containment, Approval/use
  recovery, cancellation, bounded output, and validated artifact publication;
- `compute_only` and optionally read-only workspace profiles; no direct
  network, raw secrets, child-tool execution, or install hooks; and
- human CLI and model-visible typed action over the same invocation record.

Exit gate: ambient credential, PATH/interpreter substitution, mutable-script,
path traversal, cancellation, output flood, invalid JSON, artifact escape, and
cleanup adversarial tests pass.

### PLC8B-2: Immutable Dependency Environments

Deliverables:

- V1 environment is an immutable derived child artifact of one exact Plugin
  package revision and is never shared across packages;
- canonical derived identity binds package revision, runtime digest,
  platform/architecture, dependency-lock digest, exact distribution artifacts,
  resolver/build/toolchain identity, and environment schema;
- extend the existing package lifecycle with a preparation journal/receipt,
  package pin, environment lease, corruption/repair disposition, cleanup task,
  recovery barrier, and byte-level GC recheck without changing the published
  package content digest;
- offline-diagnosable preparation, retention, update, rollback, rebuild, and GC
  using those existing package/runtime authorities; and
- visible separation of install, prepare, enable, and invoke.

Exit gate: no package manager or environment build runs implicitly during
install, list, inspection, or ordinary invocation; Approval, launch, explain,
rollback, and cleanup bind the exact environment identity and lease. Any future
cross-package sharing requires a separate accepted environment-cache owner and
cannot be introduced as an optimization.

### PLC8B-3: Additional Platform Runtimes

Deliverables:

- only explicitly available Bash, PowerShell, Node, or native toolchains;
- Product registry resolution independent of ambient `PATH`;
- OS/architecture/runtime predicates and platform-specific entrypoints; and
- Windows/POSIX path, argument, newline, signal, process-tree, and unsupported-
  runtime conformance.

Exit gate: validation distinguishes invalid packages from valid-but-
unsupported targets and never presents Bash as a universal shell runtime.

### PLC8C: Stabilize Data And One-Shot Authoring

Deliverables:

- canonical validate/pack/install-disabled journey and compatibility kit;
- one staged install transaction coordinating existing verified publication/
  binding with desired-state CAS, idempotency, crash recovery, and orphan
  repair for local and future remote sources;
- at least inert composition and two materially different real Skill-script
  adopters in addition to existing LSP/Base/Arch evidence;
- version/deprecation/migration/diagnostic policy; and
- stable author exports only after cross-version conformance.

Exit gate: the SDK does not freeze LSP-only, Provider-only, or one-runtime
assumptions; public examples cannot bypass trust, management, or execution.

### PLC9A: Isolated Declaration Evaluation

Deliverables:

- a new admitted declaration-source arm for untrusted executable evaluation;
- distinct Approval/use record and required containment before spawn;
- strict frozen declaration output only, with no runtime service, broker, owner
  publication, or activation authority; and
- crash/revocation/recovery evidence separate from contribution activation.

Exit gate: evaluation authority cannot decode or replay as runtime activation,
and evaluator output passes the same inert declaration validation/admission as
other sources.

### PLC9B: Session-Owned Worker V1

Deliverables:

- internal `WorkerAttemptCoordinator` over `AuthorizedProcessLauncher` behind
  one exact Component Host;
- framed protocol, handshake, request/cancel, streaming, backpressure, health,
  bounded diagnostics, and protocol negotiation;
- exact Plugin Instance, owner candidate/generation, activation-use, Session,
  Process handle, package, containment, artifact, and cleanup correlations;
- one read-only production-shaped long-lived adopter plus stateful/streaming and
  hostile fixtures; and
- bounded component-data facets or attempt-scoped mounts with quota, schema,
  tenant/workspace, revocation, and lease evidence; and
- owner-coordinated stage/publish/drain/rollback, crash suppression, and
  cleanup-incomplete diagnostics.

Exit gate: untrusted Provider code has no in-process path; handshake cannot
publish; Worker failure preserves Host/owner correctness; retired attempts
cannot answer or callback for the active owner generation.

### PLC9C: Management And Operator Convergence

Deliverables:

- route every durable mutation adapter through `PluginManagementService`;
- pure authoring service, management inventory queries, exact owner/runtime
  projectors, and cross-projection explain UX as separate ports;
- typed owner-coordinated Worker operational intents with idempotent exact-owner
  operation and terminal-evidence references;
- one-way migration/removal schedule for legacy source/package/disabled paths;
  and
- permission/trust/topology/containment diffs before enable or update.

Exit gate: no adapter mutates materialization, desired state, owner
publication, refresh, process state, or cleanup outside its exact authority;
crash recovery preserves the same explainable independent projections.

Management adapters for already implemented command families and read-only
inventory improvements may land before PLC9B if they make no claims about
unimplemented Worker/repair/GC state.

### PLC9D: Existing Package Lifecycle Productization

Deliverables:

- publisher authentication and signed metadata feeding the existing source and
  resolution authority;
- remote acquisition materializing into the existing verified revision store;
- operator workflows over the existing canonical lock, package lifecycle pins,
  cleanup tasks, recovery barrier, and GC-candidate/recheck records;
- retained-version and prepared-environment reclamation plus separately
  authorized durable-state retention, migration, export, and deletion;
  and
- optional remote catalog/registry only after local lifecycle completion.

Exit gate: no second cache, lock, retention counter, recovery barrier, or GC
eligibility calculation; active/unknown/recovery/rollback leases prevent
reclamation.

### Optional Domain Milestone: Brokered Durable Mutation

Start only when a real Product/domain owner has concrete mutation semantics.
Deliver owner-qualified ChangeSet, plan, Approval, apply receipt,
partial/unknown result, reconcile, compensation, idempotency, and fault-
injection contracts. It is not a prerequisite for ordinary Skill scripts,
Worker protocol, or the general SDK.

## Recommended Delivery Order

```text
execution/Worker ARD gate
          |
          +--> PLC6 / PLC7 existing production adopters
          |
          v
PLC8A script schema + v1alpha author contract
          |
          v
PLC8B-1 zero-dependency Python
          |
          +--> PLC8B-2 immutable Python environments
          `--> PLC8B-3 explicit platform runtimes
          |
          v
PLC8C one-shot authoring stabilization
          |
          v
PLC9A isolated declaration evaluator
          |
          v
PLC9B Session-owned Worker V1
          |
          v
PLC9C management/operator convergence
          |
          v
PLC9D existing package lifecycle productization

optional exact-domain plan/apply milestone starts only on real demand
```

One-shot and long-lived paths may share strict codecs, Approval infrastructure,
Sandbox profiles, audit events, and artifact contracts, but retain distinct
lifecycle/use records. Stable executable APIs still require multiple real
adopters and cross-version evidence.

## Migration Strategy

1. Keep existing trusted built-ins operational; report them explicitly as
   `trusted_in_process` rather than pretending typed facets sandbox them.
2. Keep instruction-driven adjacent scripts working as generic Tool commands;
   inventory them separately and never relabel them as managed Skill scripts.
3. Introduce optional named script metadata and availability projections
   without changing inert Skill parsing or requiring every Skill to have a
   Plugin manifest.
4. Route newly supported managed third-party Skill scripts through the
   authorized one-shot path; project-local development snapshots first.
5. Introduce Worker V1 behind internal Product adapters and prove one real
   long-lived service.
6. Make isolated Worker mandatory for new third-party executable Providers.
7. Drain legacy desired-state mutation paths into
   `PluginManagementService`, then remove them under recorded migrations.
   Preserve pure authoring and exact read projectors outside that mutation
   service.
8. Move existing built-ins to Workers only where trust reduction, crash
   containment, dependency isolation, or independent upgrade value justifies
   the operational cost.

No migration step may reinterpret an existing package as more trusted, broaden
its authorities, or silently convert `required` containment into best effort.

## Verification Matrix

### Identity And Admission

- mutated package or entrypoint after verification is rejected;
- symlink, traversal, case-folding, alternate separator, and mutable runtime
  path attacks cannot rebase the executed file;
- stale Approval, Profile, desired-state, or package generation cannot start;
- install/inspect/list do not import code or execute scripts;
- crash after verified package publication but before install-disabled CAS
  leaves inert pinned bytes and one resumable/orphan-repair operation, never an
  inferred Installation or a second adapter materialization;
- managed launch uses the same opened verified identity or immutable Sandbox
  snapshot that was approved; it never closes and reopens a mutable source path;
- native and packaged managed scripts with the same display IDs cannot
  cross-route because their exact `ExecutableSourceRevision` differs;
- generic Shell execution of adjacent content is never audited or displayed as
  a managed Skill-script invocation;
- generic Tool Policy/Approval/audit carries non-authoritative Skill/package/
  revision/trust provenance when a path resolves under a known root, and raw
  installed-third-party script execution never falls below `ask + required`
  generic-Tool containment.

### Process And Protocol

- failed spawn, early exit, failed handshake, version mismatch, malformed or
  oversized frame, blocked stream, and stderr flood release reservations;
- terminate escalates to process-group kill and owned containment cleanup;
- concurrent stop, natural exit, cancellation, and Host close converge on one
  terminal result;
- stale Worker attempt/owner-generation responses and callbacks are rejected;
- required CPU, memory, PID/process-tree, wall-clock, output, and temporary-
  storage limits are backed by advertised containment capabilities;
- incomplete process-tree termination is visible, retains leases, and blocks
  successful retirement/GC.

### Authority And Secrets

- required sandbox unavailable fails before spawn;
- read-only and writable root boundaries are enforced;
- combined filesystem, process, network, publication, secret, and external-
  domain effects remain additive through admission, Policy, Approval,
  containment/brokering, audit, and explanation;
- unauthorized network, process, secret, and broker effects are rejected;
- the managed child receives a minimal environment with no ambient credential,
  loader, proxy, module-path, or toolchain variables;
- Host-generated records contain no secret material; raw-secret child output,
  if permitted, is quarantined from transcript/status/ordinary logs;
- Worker callbacks re-authorize against the exact invocation scope.

### Approval And Owner Boundaries

- in-process, Skill-script, isolated declaration-evaluation, Worker activation,
  invocation, plan, and action subjects cannot decode or replay as one another;
- durable start authority is consumed before spawn and every crash point
  reconstructs one use/attempt outcome;
- Approval binds required and selected/probed containment facts; the attempt
  records the post-plan actual enforcement descriptor, and any coverage
  mismatch fails durably before spawn;
- handshake produces only a prepared candidate; only the exact Component owner
  can publish it;
- management, Worker coordinator, public SDK, and adapters cannot import or
  invoke raw owner publication, `ProcessHost`, raw Sandbox, or subprocess
  mutation APIs;
- Worker stop/restart intent does not let management close the process handle
  or retire a foreign owner generation;
- security revoke first blocks routing/acquisition and invalidates callback,
  broker, secret, and effect capabilities, then enters `REVOKING` and settles
  physical containment; direct mounts remain active until confirmed exit.

### Durable Effects

- duplicate apply with one idempotency key does not duplicate effects;
- stale plan or changed precondition is rejected;
- partial and unknown outcomes remain leased and repairable;
- recovery never silently repeats an untracked compensation;
- activation, plan, and action Approval subjects remain distinct;
- every plan/journal/reconcile route names an exact registered domain owner;
- an untrusted mutation Worker has no direct network/raw-credential path around
  the domain broker.

### Lifecycle And Operations

- enable, disable, update, rollback, repair, restart-required, drain, retire,
  and garbage collection are durable and explainable after crash;
- exact owners publish new generations atomically; Worker readiness alone is
  never effective publication;
- failed cleanup is visible and blocks unsafe garbage collection;
- permission and execution-shape widening require a new decision;
- package-owned prepared environments retain exact preparation receipts,
  package pins, execution leases, recovery barriers, and byte-recheck evidence
  through update/rollback/GC;
- disabling or collecting Plugin artifact bytes cannot delete durable component
  state, and a failed state migration preserves the prior usable revision and
  recovery leases;
- abnormal direct workspace writes report partial/unknown state rather than
  clean cancellation or rollback success.

## Success Measures

The improvement is successful when:

- an author can use an inert native Skill, add a managed native script without
  creating a Plugin, and package the same Resource when distribution or package
  desired state is required;
- an author can package an isolated Provider through the same contribution
  model;
- an operator can explain why a Plugin is or is not effective without reading
  internal stores;
- third-party executable content has no untrusted in-process path;
- ordinary scripts remain simple one-shot executions rather than artificial
  daemons;
- exact owners can survive Worker crashes and stage, publish, drain, or roll
  back Worker-backed candidates without corrupting Host-owned state;
- brokered durable destructive actions are individually bounded, approved,
  auditable, idempotent, and domain-recoverable, while direct workspace writes
  report honest partial/unknown outcomes; and
- Product owners retain all mandatory control-plane authority.

## Independent Review Disposition

| Review | Blocking findings incorporated in this revision |
| --- | --- |
| Security | Required capability-complete containment; verified script/toolchain launch and clean environment; distinct Approval uses before spawn; required/selected/actual containment evidence; running-Worker revoke order; broker-only secret-bearing durable mutation; honest termination, secret-output, and partial-write states |
| Authoring | Legacy generic-script compatibility and provenance-aware default policy plus optional named managed scripts; strict Resource-owner schema; experimental author contract before implementation; JSON/text I/O and secure artifacts; ephemeral snapshot dev loop; staged Python environments and platform runtimes |
| Architecture | Additive existing effects rather than one new class; non-owning Worker attempt coordinator; exact owner publication/drain; Session-owned V1; domain-owned plan/apply; separate authoring/mutation/query ports; staged install coordination; package-owned prepared environment; PLC8/PLC9 crosswalk; reuse of existing package/lock/GC authorities |

Each review file preserves its initial findings and appends an independent
re-review plus final closure check. The final checks found no remaining plan-
level P0/P1 and recommend the revised plan as a PLC8/PLC9 delivery proposal.
This is review approval of the plan shape, not acceptance of the architecture
or certification of an implementation; the Execution/Worker ARD and every
stage gate remain mandatory.

## Risks And Explicit Tradeoffs

- IPC adds latency, protocol compatibility work, serialization limits, and
  harder debugging. Use it where trust, failure, dependency, or lifecycle
  isolation provides material value.
- OS containment differs by platform. Support claims must reflect enforceable
  backend evidence, not one portable marketing label.
- Direct workspace mounts are simpler and faster than brokering every read or
  write, but provide coarser authority and audit. Choose per effect profile.
- Plan/apply improves safety for durable effects but creates state, drift,
  partial-failure, and schema-migration obligations. Do not universalize it.
- Supporting arbitrary runtime dependency installation greatly expands supply-
  chain and reproducibility risk. Prefer pre-resolved immutable environments.
- Premature SDK stability can freeze a single Product's assumptions. Keep
  executable authoring internal until the multi-adopter gate passes.

## Open Decisions Requiring An ARD

1. Which sandbox guarantees are mandatory for third-party execution on each
   supported platform?
2. Is framed JSON sufficient for Worker V1, and what evidence triggers a move
   to protobuf/gRPC?
3. Which first production long-lived service proves the Worker boundary without
   coupling Harness to a Product protocol?
4. Which effects may use direct sandbox access, and which must always traverse
   a Host broker?
5. What is the supported immutable dependency environment format for Python,
   Node, and native helpers?
6. Which durable external mutation is real enough to justify the first
   plan/apply implementation?
7. What compatibility window and retirement policy apply to Worker protocol
   versions and private-data schemas?
8. Which existing Product/domain owner accepts each durable component-state
   class, and what common request envelope can be shared without creating a
   universal Plugin data owner?

Until these decisions are accepted, this document is a delivery proposal and
review target, not authorization to expose untrusted executable Plugins.
