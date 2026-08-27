# Security Review: Client Plugin SDK And Embedded Authoring Experience

## Status

- Authority: descriptive — independent security validation evidence
- Artifact type: validation
- Reviewed design status: proposed
- Implementation status: not-applicable
- Owner: Loushang architecture review

## Review Scope

This is an independent security, trust, authority, Approval, Sandbox, verified-
launch, and Worker-SDK review of
[`client-plugin-sdk-and-embedded-authoring-experience.md`](../client-plugin-sdk-and-embedded-authoring-experience.md).
It evaluates the proposal against the current accepted Loushang architecture
and the present source tree. It does not review implementation quality for
features that do not yet exist, and it does not make the proposed SDK an
accepted contract.

## Verdict

**Conditionally accept the authoring direction, but do not accept the current
document as an implementation-ready security contract.**

The central decision is sound: author-facing APIs may hide lifecycle mechanics,
but they must compile into the same immutable declaration, Approval, exact-owner,
Sandbox, and process-hosting paths. The document also correctly rejects a
universal mutable `PluginContext`, import-on-discovery, path-implied trust,
complete Host-environment inheritance, Worker self-publication, and an unsafe
development bypass.

Five P0 seams remain insufficiently closed:

1. a Python builder cannot be treated as a pure compiler unless its execution
   phase and trust boundary are explicit;
2. a managed script invocation needs its own exact Approval use and verified-
   launch adapter, while the current `ExecService` freezes neither executable
   nor script bytes;
3. Product embedding and automatic policy need a Host-resolved immutable trust
   root, not a manifest/path/signature-shaped shortcut; and
4. project-local legacy scripts must not receive implied authorship or a
   source-location policy downgrade; and
5. the Worker SDK must inherit a fail-closed activation/start/containment and
   callback protocol before `serve()` can become public.

A repository path is source location, not authorship or trust evidence.

## Authoritative Evidence

### Accepted architecture

- Executable contributions, including local development Plugins, require a
  content digest, and bind/import/launch must revalidate that identity. A local
  source change invalidates the plan and Approval rather than executing changed
  bytes
  (historical `unified-plugin-architecture.md:269` in the reviewed revision).
- Only a digest-bound package with a positive execution-preflight decision may
  evaluate executable declarations. Disabled, unselected, untrusted, denied,
  or unapproved packages are not imported or launched
  (historical `unified-plugin-architecture.md:380` in the reviewed revision).
- Declaration execution and contribution activation are two independent
  Approval subjects. Package Approval does not replace later action-level
  policy
  (historical `unified-plugin-architecture.md:390` in the reviewed revision).
- Factory execution, owner bind, and external-service launch consume activation
  authority at actual start; process reservation and PID/handle publication are
  recovery facts, not implied by a positive decision
  (historical `unified-plugin-architecture.md:478` in the reviewed revision).
- In-process Python is explicitly host-equivalent ambient authority. Typed
  facets improve architecture and audit but are not isolation. Code below that
  trust level must remain declarative or use an accepted isolated Worker
  (historical `unified-plugin-architecture.md:1395` in the reviewed revision).
- Executable use must retain a `VerifiedRevisionHandle`/equivalent immutable
  identity through launch. Closing the verified handle and reopening a mutable
  path is forbidden
  (historical `unified-plugin-architecture.md:1410` in the reviewed revision).
- A compromised in-process realm is an ambient Host compromise and cannot be
  revoked by pretending typed action policy controls arbitrary already-imported
  Python
  (historical `unified-plugin-architecture.md:1087` in the reviewed revision).

### Accepted process and execution boundaries

- `ProcessHost` is private; Products receive only
  `AuthorizedProcessLauncher`. Admission, protocol behavior, restart, and
  diagnostics remain Product responsibilities
  ([process-hosting-boundary.md:21](../../../harness/process-hosting-boundary.md#L21),
  [process-hosting-boundary.md:34](../../../harness/process-hosting-boundary.md#L34)).
- `process.host.start` is still a protected action. Required containment fails
  before spawn, while best-effort containment may deliberately degrade
  ([process-hosting-boundary.md:75](../../../harness/process-hosting-boundary.md#L75)).
- One-shot `ExecService` and long-lived Process Hosting have separate ownership
  and cancellation contracts
  ([process-hosting-boundary.md:108](../../../harness/process-hosting-boundary.md#L108)).
- `materialize_exec_request()` freezes cwd and environment only. It deliberately
  does not freeze executable lookup, executable bytes, or arbitrary child-read
  files
  ([workspace-execution-boundary.md:77](../../../harness/workspace-execution-boundary.md#L77)).

### Current source reality

- The current canonical Plugin parser reads strict `plugin.json`; the TOML in
  the proposal is illustrative, not an existing alternate authority
  ([manifest.py:32](../../../../../../src/loushang/harness/resources/plugins/manifest.py#L32)).
- The current `SkillDescriptor` has no managed-script field, and Skill parsing
  stores generic frontmatter/body metadata only
  ([types.py:101](../../../../../../src/loushang/harness/resources/types.py#L101),
  [_descriptor_parsing.py:74](../../../../../../src/loushang/harness/resources/_descriptor_parsing.py#L74)).
- The current activation subject admits only `execution_model="in_process"`;
  a Worker-backed activation arm therefore requires a versioned contract change,
  not a facade over the current record
  ([plugin_activation.py:88](../../../../../../src/loushang/harness/approval/plugin_activation.py#L88)).
- `ExecRequest` currently carries command strings, cwd, environment, timeout,
  and output controls, but no verified package/script handle
  ([workspace/exec/types.py:56](../../../../../../src/loushang/harness/workspace/exec/types.py#L56)).
- The current built-in LSP proof explicitly declares its in-process model,
  requested authorities, and executable Definition entrypoint; its Product
  adapter independently approves Definition execution and activation
  ([coding LSP plugin.json:1](../../../../../../src/loushang/coding/_plugins/coding_lsp_default/plugin.json#L1),
  [_plugin_opt_in.py:110](../../../../../../src/loushang/coding/lsp/_plugin_opt_in.py#L110)).

## P0 Findings

### P0-1: The Python builder has an undefined execution phase

**Finding.** The common pipeline places `Python builder` beside directory and
manifest inputs before canonical IR, and the L2 examples derive contributions
from live Python functions. Evaluating decorators, module globals, function
signatures, `resources.from_directory()`, or builder callbacks executes Python.
If `validate`, discovery, install, or runtime composition imports the module to
obtain IR, the shortest author path becomes import-before-preflight.

The proposal says that the compiler derives IDs, schemas, fingerprints, and
facets, but does not distinguish:

- an inert codec over already-serialized data;
- a trusted Product-build generator executed in a controlled build;
- a runtime in-process Plugin Definition evaluated after execution Approval; or
- an isolated declaration evaluator for code below host-equivalent trust.

Those four operations do not share a security boundary.

**Required correction.** Replace the single ambiguous `compiler` with explicit
phases:

1. `InertAuthoringCodec` parses data without imports or hooks.
2. A Product build generator may execute co-owned source in the trusted build
   environment and must emit canonical IR plus exact build/distribution
   evidence. Runtime consumes the emitted inert artifact; it does not rerun the
   generator merely to discover it.
3. If a Python builder is evaluated at runtime, classify it as an executable
   declaration source. It follows the complete `PluginExecutionApprovalSubject`
   and one-shot consumption path before import.
4. Project/user/OEM builder code below host-equivalent trust uses the separately
   accepted isolated declaration-evaluator arm or is rejected.

Mark every L2/Product-overlay example as either `build_only` or
`runtime_host_equivalent`; do not let the same decorator silently choose based
on source location. `validate` may statically validate the inert envelope and
report executable validation as deferred, but it must not import the builder.

**Security consequence if omitted.** An apparently harmless validation or
listing operation can execute module import side effects with Host authority,
before immutable identity, Approval, owner admission, or Sandbox selection.

### P0-2: Managed scripts need a distinct action authority and a real verified-launch seam

**Finding.** The proposal states that the Host binds digests, containment, and
“Approval subjects,” but it does not name which decision is consumed at one
`skill.script.run`. Declaration execution Approval authorizes only evaluation of
one declaration group. Contribution activation Approval authorizes factory,
bind, or service launch. Neither grants arbitrary future script invocations.

The current one-shot `ExecService` cannot satisfy the proposal's identity
claim: it freezes cwd and environment but does not freeze `argv[0]`, interpreter
bytes, shebang resolution, the script file, or other child-read files. The
current `VerifiedRevisionHandle` can verify/open bytes, but the current
`ExecRequest` cannot carry it through process creation. Merely checking a digest
and then passing a filesystem path to `ExecService` reopens the TOCTOU window.

**Required correction.** Define the managed route as all of the following:

- the Resource/Skill owner admits an inert, versioned
  `SkillScriptDeclarationV1`; admission makes it callable but grants no call;
- every invocation builds a separate versioned
  `SkillScriptInvocationSubject` and consumes a one-attempt use record in the
  existing Approval owner;
- the subject binds the exact package revision, entrypoint identity,
  toolchain/interpreter identity, dependency environment, argv, cwd, clean-
  environment fingerprint, input/result ABI, actor/Product/Profile/Session,
  authority, containment requirement, expiry, and revocation epoch;
- an internal `AuthorizedSkillScriptExecutor`, not the public SDK and not raw
  `ExecService`, consumes the action decision and binds the verified revision
  to an immutable Sandbox projection or an equivalent handle-relative launch;
- required containment is proven before spawn, and an exact start/result use is
  durably terminalized; and
- automatic Product policy, where allowed, still creates the same per-invocation
  subject/use/audit record. It is not an enable-time blanket grant.

The interpreter must be a Product-admitted toolchain or an immutable
package-owned environment. A string such as `python`, `node`, `bash`, or
`pyright-langserver` resolved through mutable `PATH` is not verified launch.

**Security consequence if omitted.** The user can approve one digest/display
while a different script, interpreter, wrapper, or environment is executed.
Plugin enablement may also be misused as standing action authority.

### P0-3: Product embedding and automatic policy need non-self-asserted trust roots

**Finding.** The proposal correctly states that embedded location is not trust,
but `included in the Product distribution or signed Product bundle` remains too
broad. A package manifest must not self-declare `product_embedded`, select a
Product signer, or become eligible because its path resembles a Product root.
“Signed” proves only possession of some key unless the Host already binds that
key, Product build, exact package closure, and policy revision.

The automatic-decision diagram also compresses distinct facts. Source trust,
declaration execution Approval, owner admission, contribution activation
Approval, and later tool/action Approval remain separate even when the same
Product policy issues automatic positive decisions.

**Required correction.** Define `product_embedded` as a Host-resolved source
classification obtained only from an immutable Product release manifest or
equivalent Product-owned build registry. The trust record must bind:

- Product distribution/build identity and trusted release-key policy;
- exact package and dependency-closure digest;
- Plugin ID and allowed declaration source/execution topology;
- maximum requested authorities and allowed owners/contribution kinds;
- Product/Profile/trust-policy revisions and revocation epoch.

No package field, directory name, project configuration, CLI flag, developer
mode, or arbitrary signature may create this classification. A Product allowlist
is immutable Product policy input and cannot be contributed or mutated through
the Plugin SDK.

Replace `automatic recorded decision` with an explicit projection showing
separate execution and activation decisions/use records, followed by any
action-level decisions. Automatic policy may avoid interactive prompts; it may
not merge or reuse the subjects. Explain/status must call in-process code
`host-equivalent` even when its typed signature requests only `WorkspaceRead`.

**Security consequence if omitted.** A project can masquerade as a built-in,
or a legitimate Product signature can be overread as ambient permission for
unlisted authorities, later activations, or individual effects.

### P0-4: Legacy compatibility treats project location as implied authorship

**Finding.** `Project-local/user-authored scripts retain normal Product Tool
policy` joins two facts that are not equivalent. A cloned repository, extracted
archive, generated workspace, or malicious dependency is project-local without
being authored or reviewed by the current user. Path recognition is explicitly
non-authoritative and is incomplete for interpreter flags, wrappers, shell
expansion, `PATH` lookup, symlinks, and scripts that launch other scripts. It
cannot justify a more permissive decision.

The generic Tool path is useful and should remain, but it is deliberately not
verified managed execution. It cannot truthfully promise digest-bound execution
or reusable package authority.

**Required correction.** Replace the source-specific relaxation with these
rules:

- every legacy invocation remains one ordinary generic Tool action under the
  Product's exact command/effect Policy, Approval, Sandbox, and audit path;
- recognized Skill/package provenance may only make policy stricter or improve
  disclosure; it never lowers risk or supplies authority;
- unknown/unrecognized provenance is `unknown`, not local/trusted;
- `project_local` and `user_global` describe source scope only, never authorship
  or host-equivalent trust;
- reusable Plugin/script grants are unavailable on the legacy path because
  mutable executable bytes are not bound; and
- when Product policy requires immutable or package-qualified execution, the
  legacy call is denied with migration guidance to snapshot/use the managed
  script path.

Approval UX and audit must label the script/executable identity as mutable or
unverified where that is true. Do not display the advisory package revision as
the bytes that were executed.

**Security consequence if omitted.** Moving the same untrusted script from an
installed package into a project directory can silently downgrade its policy,
and incomplete path recognition becomes an authorization bypass.

### P0-5: The Worker author facade is specified before its security bootstrap

**Finding.** The L3 example makes `serve(PythonIndexer())` intentionally simple,
but the overlay does not state what makes the process an authorized Worker, what
claims are merely untrusted telemetry, or what reverse Host services it may
call. Handshake, `PluginInfo`, health, and a Worker-reported fingerprint cannot
establish trust, contribution identity, authority, or effectiveness.

The current `ContributionActivationApprovalSubject` supports only
`in_process`. The current `AuthorizedProcessLauncher` protects the physical
`process.host.start` action but does not itself perform Plugin admission or
consume a Worker activation decision. Therefore publishing `loushang.plugin.worker`
before a versioned Worker activation contract would invite Products to wire the
SDK directly to the generic launcher and create a second start path.

**Required correction.** Gate public Worker SDK delivery on a versioned
Execution/Worker ARD and require:

- the exact Component owner prepares an admitted Worker candidate;
- the owner/coordinator consumes the process-backed activation subject/use
  immediately before required-containment planning and spawn;
- the generic `process.host.start` gateway remains an invariant lower layer but
  neither substitutes for nor duplicates Plugin activation authority;
- the Host supplies an attempt-bound nonce/bootstrap channel; the Worker only
  echoes admitted service/schema/package facts, and additional Worker claims
  never expand the candidate;
- `serve()` exposes no `ProcessHandle`, launcher, Approval resolver, Sandbox,
  registry, management writer, environment dump, or generic Host object proxy;
- strict bounded language-neutral messages are used; Python `pickle`, dynamic
  imports/object proxies, and untyped reverse RPC are forbidden;
- every reverse callback is a narrow Product-owned facet and reauthorizes exact
  attempt, owner generation, invocation, target/effect, deadline, and
  revocation facts; and
- project/user/OEM Workers require capability-complete containment. Disabled,
  best-effort, degraded, unresolved, or incomplete containment fails before
  process creation.

Worker health/fingerprint is compatibility and observation evidence only. Only
the exact owner can publish readiness/effectiveness.

**Security consequence if omitted.** A convenient Worker helper becomes a
second process launcher, service registry, or reverse-RPC authority, while a
cooperative handshake is mistaken for isolation or admission.

## P1 Findings

### P1-1: Typed facets must not be presented as enforcement for in-process code

The L2 signature example is useful dependency injection, but
`WorkspaceRead`/`PluginLog` cannot constrain host-equivalent Python from using
`os`, inherited modules, environment, filesystem, subprocess, or network.

**Correction.** Add an explicit note beside the L2 example: typed facets are
cooperative architecture/audit contracts for admitted host-equivalent code,
not a Sandbox. Conformance must reject attempts to label a built-in
`facet_scoped`, `sandboxed`, or revocably least-privileged merely because its
function signature is narrow.

### P1-2: Managed-script schema ownership must be explicit and strict

The current Skill schema has no script declaration. Placing `scripts` into
generic frontmatter metadata or inventing a second manifest parser would bypass
the Resource owner's strict schema and compatibility diagnostics.

**Correction.** State that PLC8A introduces one versioned, owner-specific
`SkillScriptDeclarationV1` in the canonical Resource/Skill projection. Unknown
fields, duplicate IDs, absolute/escaping/symlinked entrypoints, ambiguous
runtime aliases, and authority/profile aliases fail that script closed. Invalid
optional script metadata may not erase inert `SKILL.md` availability. Resource
discovery may inventory adjacent files as data, but never imports, executes, or
infers script permissions from them.

### P1-3: Product-specific helpers must not hide mutable executable resolution

The Coding example uses `command=["pyright-langserver", "--stdio"]`. This is a
good authoring shorthand only if the Product compiler resolves it to an admitted
toolchain/server definition. Passing the string through to process launch lets
ambient `PATH` choose the executable after Product admission.

**Correction.** Compile command shorthand into either a Product-owned toolchain
ID with exact distribution evidence or a package-relative verified executable.
Store and explain the selected executable/runtime identity. Reject ambiguous
lookup for untrusted execution; do not silently switch to the Host PATH.

### P1-4: Secrets, logs, and result channels need SDK-level negative guarantees

The proposal correctly requires a minimal environment and bounded diagnostics,
but the public facades should state that secrets are not ordinary constructor
arguments, environment defaults, log fields, errors, health payloads, or normal
artifacts.

**Correction.** Expose only opaque credential handles or Product-owned narrow
facets by default. Secret materialization, if a Product supports it, requires a
separate decision/lease and restricted output handling. `PluginLog` performs
structural redaction but cannot be claimed as proof against a malicious
in-process or Worker transformation. Reject environment-field projection into
normal explain/status/Approval data.

### P1-5: `dev` and `test` need negative capability guarantees

The workflow says that `dev` uses production policy and `test` grants no extra
authority, which is correct but should be made mechanically testable.

**Correction.** Define `dev` as snapshot-first and require a new decision after
every content change. Define test fixtures as fake Product facets with no Host
fallback; absence of a fixture must fail rather than resolving a live service.
`validate`, `pack`, and `install --disabled` must never prepare dependencies or
execute build/install hooks.

## P2 Findings

### P2-1: Avoid a temporary public manifest dialect becoming a second authority

The illustrative TOML is harmless in a discussion, but the current canonical
parser is strict JSON. Before documentation becomes author-facing, choose one
public source format or define a deterministic, versioned front-end compiler
whose output alone enters the current parser. Round-trip/canonical-byte tests
must prove aliases do not survive downstream.

### P2-2: Clarify L0 vocabulary

Call L0 a native Resource authoring form rather than a Plugin Instance. This
preserves the useful zero-manifest experience without implying Plugin desired
state, execution Approval, or per-Skill lifecycle evidence exists where the
Resource owner is the only authority.

### P2-3: Add SDK supply-chain provenance

Generated Python/Rust/Go/Node Worker adapters and Product build generators are
part of the executable supply chain. Pack output should record compiler/SDK
schema version and generator identity. Runtime compatibility should consume
those inert facts without running a package-selected generator.

### P2-4: Split availability from authorization state

`available`, `pending_approval`, and `denied` currently mix static
compatibility, desired state, and one invocation's authorization. Present at
least separate fields for descriptor availability, activation/readiness, and
last/current invocation decision. A stale denial or expired prompt must not be
projected as permanent script unavailability.

## Required Acceptance Gates

The following gates are executable release criteria, not documentation-only
checks.

### No execution during inert operations

- Fixture modules with import/global/decorator side effects remain untouched by
  `validate`, `pack` inspection, install-disabled, list, inspect, Resource
  discovery, and explain.
- A runtime Python builder cannot return declarations without a matching fresh
  execution subject, consumed use, verified revision, and import-realm gate.
- Copying a Product builder into a project root selects isolated evaluation or
  fails; it never selects in-process by path/name.

### Trust and automatic-policy separation

- A project package may spoof Plugin ID, directory layout, metadata,
  `product_embedded`, and an untrusted signature without becoming eligible for
  Product automatic policy.
- Replacing any package/dependency digest, authority, owner, execution model,
  Product build ID, trust-policy revision, or revocation epoch invalidates the
  automatic decision.
- Execution, activation, and action subjects cannot deserialize as or consume
  one another's records. A valid declaration-execution receipt cannot launch a
  Worker or invoke a script.
- Explain shows the policy rule/allowlist and exact subject/use; it never says
  “trusted because embedded.”

### Managed verified launch

- Mutating, replacing, symlinking, or reparse-point swapping the script,
  interpreter, dependency environment, cwd, or output root between Approval and
  spawn fails before execution.
- PATH substitution, shell-string injection, shebang/wrapper substitution, and
  interpreter-flag changes invalidate the subject or are structurally
  impossible.
- A direct `ExecService`/`AuthorizedProcessLauncher` call cannot claim managed
  script status or consume managed-script authority.
- Containment requirement, selected backend/probe revision, and actual enforced
  capabilities remain distinct evidence. Required/degraded mismatch never
  spawns.
- Cancellation/crash at consumed-not-started, starting, running, output
  validation, and cleanup points reaches one durable truthful terminal state
  and never reuses the decision.

### Legacy-path truthfulness

- Project-local, user-global, installed, unknown, symlinked, wrapped, and PATH-
  resolved scripts receive no authority from advisory Skill provenance.
- Moving identical bytes between source roots cannot make an otherwise equal
  generic command less restricted solely because the destination is a project.
- Approval/audit distinguishes advisory provenance from executable-byte
  identity and labels mutable/unverified execution truthfully.
- A Product mode requiring verified script identity denies legacy invocation
  and points to managed snapshot execution.

### Worker confinement and authority

- Worker activation uses a versioned process-backed activation subject and use;
  the existing in-process subject cannot be coerced into the Worker arm.
- A Worker cannot start when required Sandbox capability coverage is missing,
  disabled, best-effort, degraded, or unresolved.
- Forged service IDs, package digests, attempts, nonces, owner generations,
  schema versions, extra fields, oversized frames, duplicate responses, and
  retired-attempt responses fail closed before owner publication.
- Health/readiness/fingerprint claims cannot add services, authorities, or
  effective contributions.
- Worker reverse calls to raw process launch, Approval, Sandbox, management,
  owner registry, secrets, or foreign Product services are absent. Every
  supported callback is a narrow typed facet with fresh scope/revocation checks.
- Worker process, child tree, streams, Sandbox plan, package/environment lease,
  and owner route settle on cancellation, revoke, Session close, crash, and
  protocol failure. Incomplete termination is not reported as disabled or
  retired.

### Facet, environment, and secret honesty

- In-process Plugin status always reports host-equivalent ambient authority;
  typed `WorkspaceRead` injection never changes that classification.
- Managed/Worker child environments start from an explicit allowlist rather
  than `os.environ` minus a denylist; normal status/audit/Approval never contains
  environment values.
- Secret handles are scope-, attempt-, actor-, deadline-, and revocation-bound.
  Raw secrets, when explicitly supported, cannot enter ordinary log/result/
  artifact paths.
- Artifact publication rejects escapes, symlinks, hard links, devices, unstable
  post-exit content, excessive counts/bytes, and unapproved media types.

## Recommended Document Disposition

Revise the main proposal to close P0-1 through P0-5 and add the associated
acceptance gates. The result can then remain a concise authoring overlay by
linking the detailed lifecycle mechanics to the parent execution plan and
accepted architecture; it need not duplicate every internal state machine.

After those revisions, the proposal is a good security posture for client
products: L0/L1 can stay genuinely simple, trusted built-ins can keep an
ergonomic typed SDK without pretending to be sandboxed, and third-party
long-lived services can use an equally small Worker author API while the Host
retains all authority.
