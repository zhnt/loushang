# Plugin Management And Isolated Execution Authoring Review

## Status

- Authority: descriptive — independent author-experience validation evidence
- Artifact type: validation
- Reviewed design status: proposed
- Implementation status: not-applicable
- Owner: Loushang architecture review

This is an independent author-experience review of
[Plugin Management And Isolated Execution Improvement Plan](../plugin-management-and-isolated-execution-improvement-plan.md).

This review is source-based. It evaluates the proposed plan from the point of
view of a Plugin or Skill author, with particular attention to Skills that ship
scripts. It does not accept the proposed architecture and does not review the
Worker protocol as a security implementation in full.

## Verdict

**Revise before acceptance.** The plan makes the correct top-level choice:
ordinary Skill scripts should be first-class one-shot executions, not forced
into long-lived Workers, and installation must not execute adjacent code. That
direction can keep common Skills lightweight.

The current proposal is nevertheless not yet author-implementable. PM2 names
the runtime evidence and safety properties that a script execution should
have, but does not define how a Skill refers to a script, how the model or a
human invokes it, what crosses stdin/stdout, how produced files become
artifacts, or how a developer tests a mutable source tree without bypassing the
same admission path. It also promises Python, Bash, and Node conformance before
choosing a dependency-environment and platform model.

The most important correction is to add a small, versioned
`SkillScriptDeclaration` and `SkillScriptInvocation` slice before PM2. A simple
zero-dependency script should require only a script file and one compact inert
declaration. Package digests, runtime fingerprints, snapshots, approvals,
sandbox setup, output capture, and leases must remain Host-generated details,
not author boilerplate.

## Source Evidence

The current implementation baseline is substantially narrower than the plan's
author-facing target:

- `SkillDescriptor` contains the `SKILL.md` identity, text, frontmatter-derived
  metadata, provenance, and one Resource revision reference, but no script
  declarations or invocable script IDs
  (`src/loushang/harness/resources/types.py:101`).
- Filesystem discovery stops descending when it finds `SKILL.md`; adjacent
  `scripts/` content is neither interpreted nor projected into the Skill
  descriptor (`src/loushang/harness/resources/_loader_discovery_filesystem.py:129`).
  This is a good inert-loading property, but it means PM2 needs a separate
  package-bound script projection rather than assuming scripts are already
  discoverable.
- For packaged Resources, the Skill's `RevisionResourceRef` is currently made
  from the `SKILL.md` path, not from the Skill directory
  (`src/loushang/harness/resources/_loader_discovery.py:218`). The package store
  captures a complete immutable package tree, but the author/runtime contract
  still lacks an explicit verified locator for each adjacent script.
- Skill frontmatter is parsed into generic metadata and validates only the
  existing Skill fields; no script codec exists
  (`src/loushang/harness/resources/_descriptor_parsing.py:74`). The local YAML
  subset also does not support a list of maps, so the proposal's illustrative
  TOML shape cannot simply be copied into existing `SKILL.md` frontmatter
  (`src/loushang/harness/resources/frontmatter.py:107`).
- The canonical Plugin manifest is strict `plugin.json`. Its contribution
  vocabulary currently has only `capability_provider`, `command_pack`,
  `resource_item`, and `tool_pack`, and its execution vocabulary has only
  `data_only` and `in_process`
  (`src/loushang/harness/resources/plugins/declarations.py:31`). A script
  declaration therefore requires an explicit schema/version migration; it is
  not merely author documentation.
- The Plugin authoring package explicitly exports no public SDK
  (`src/loushang/harness/plugin_authoring/__init__.py:1`). The lifecycle plan
  likewise records PLC6 through PLC9 and the public SDK as unimplemented
  (`docs/internals/architecture/harness/plugin/plugin-lifecycle-coding-pluginization-plan.md:40`).
- The existing dependency lock records installed Python distribution names and
  versions. It does not identify or build an isolated interpreter/environment,
  model Node dependencies, or describe platform artifacts
  (`src/loushang/harness/resources/plugins/dependencies.py:41`).
- `ExecRequest` accepts text stdin and captures text stdout/stderr plus local
  output-file paths (`src/loushang/harness/workspace/exec/types.py:56` and
  `:178`). It does not define a Skill input schema, typed result protocol, or
  publication of script-produced business artifacts.
- More importantly, `materialize_exec_request()` merges `os.environ` into the
  child environment by default (`src/loushang/harness/workspace/exec/types.py:102`).
  A Skill adapter must therefore construct a sanitized complete environment;
  merely freezing the inherited environment would still expose ambient
  credentials.
- `EffectiveExecutionProfile` currently models readable, writable, and denied
  roots plus a coarse network level. It has no executable allowlist, endpoint
  list, environment policy, or secret handles
  (`src/loushang/harness/authorization/execution_profile.py:31`). The proposed
  `process = ["pandoc"]` and endpoint-level permissions are not enforceable just
  by passing today's Profile to `ExecService`.
- Current Skill and Plugin CLI projections are read-only lists over Resource
  descriptors and legacy settings-backed Plugin sources
  (`src/loushang/harness/cli/skill_listing.py:15` and
  `src/loushang/harness/cli/plugin_listing.py:21`). There is no current
  validate/pack/dev-run/script-run diagnostic journey to preserve.

## Findings

### Critical: no bound invocation path from Skill instructions to a declared script

The plan defines illustrative script metadata and an execution result, but not
the action that turns `(skill identity, script name, user input)` into one
authorized execution. Without that contract, a Skill author must keep writing
instructions such as `python scripts/report.py ...`, which sends execution
through a generic shell/tool path. That loses the declared script identity,
argument schema, requested authorities, package revision, and result contract
that PM2 is intended to establish.

Add two inert, versioned records before implementing PM2:

- `SkillScriptDeclarationV1`: owning Plugin/Skill ID, stable script ID,
  package-relative entrypoint, runtime requirement, input/result contract,
  resource limits, requested authorities, platform constraints, and schema
  version;
- `SkillScriptInvocationV1`: exact selected declaration/revision, structured
  input, actor/session/turn identity, effective profile, deadline, and
  Host-generated invocation ID.

Expose a Host-owned typed action such as `skill.script.run`, and a matching
manual CLI command. A selected Skill may refer to its stable script ID in
`SKILL.md`; it must not need to expose a mutable filesystem path to the model.
One generic Host action is sufficient for V1: every script does not need to
become a separately implemented Tool or Worker.

### Critical: `compute_only` and process allowlists are not executable with the current adapter

The proposed security language is stronger than today's one-shot substrate.
`ExecService` inherits the complete Host environment unless the adapter
provides an already materialized environment, so a nominal `compute_only`
script can receive cloud tokens, proxy credentials, and other ambient values.
Likewise, declaring `process = ["pandoc"]` does not prevent Python or Bash from
launching some other executable. Process-tree cleanup controls lifetime, not
which descendants may start.

PM2 must deliver a `SkillScriptExecutionAdapter` that creates a minimal
environment from a Product allowlist, adds secrets only through explicit
short-lived bindings, and never starts from `os.environ`. It must also classify
every permission as one of:

- OS-enforced by the selected containment backend;
- Host-brokered and re-authorized per request; or
- cooperative only and therefore insufficient for untrusted execution.

For V1, direct child-process execution should be denied for untrusted scripts
unless the sandbox can actually enforce an executable set. The safer portable
alternative is to broker approved tool execution through the Host. The same
rule applies to endpoint-specific network declarations: the current
`denied/restricted/allowed` field does not by itself enforce a domain list.

### High: the manifest source of truth and loose-Skill migration are unresolved

The TOML example in the proposal is intentionally illustrative, but PM2 cannot
start before the authoritative location is chosen. Loushang currently has
strict `plugin.json`, declaration documents, and `SKILL.md` frontmatter. Adding
a fourth implicit schema or treating arbitrary frontmatter as an execution
contract would fragment validation and compatibility.

Prefer a strict package-level declaration document referenced by
`plugin.json`, with a stable reference back to the Skill canonical ID. Keep
human-oriented Skill metadata in `SKILL.md`. If script declarations become a
new contribution kind or payload, version that change in the existing Plugin
declaration vocabulary and include it in semantic fingerprints.

The migration rule should be explicit:

- existing loose or packaged Skills remain inert and require no manifest
  change;
- adjacent files never become executable merely by convention;
- a project-local executable Skill is snapshotted to an ephemeral immutable
  revision before a development invocation; and
- a production invocation requires a package-bound verified script locator.

The plan must also say whether an invalid optional script disables only that
script while leaving its inert Skill usable, and when a required script causes
the complete Plugin admission to fail.

### High: input, stdout, diagnostics, and artifact semantics are underspecified

The current result paragraph groups exit status, stdout/stderr, diagnostics,
and artifacts without defining their relationship. Authors need deterministic
answers to the following questions:

- Is input passed as argv, UTF-8 stdin, JSON stdin, a mounted file, or some
  combination? Which values may contain secrets?
- Is stdout the primary result or a log stream? What happens when declared JSON
  is invalid or output is truncated?
- Are non-zero exit codes always failures, or may an author declare meanings?
- How does a script publish generated files without returning arbitrary Host
  paths, symlinks, devices, or files outside its output root?
- Which diagnostics are model-visible, user-visible, retained, or redacted?

Define a deliberately small V1 convention: JSON-compatible input is encoded as
UTF-8 JSON on stdin; stdout is either declared `text` or one strict JSON result;
stderr is bounded diagnostic/log output; zero is success and all other exit
codes are failure; cancellation and timeout are separate terminal reasons.
Large stdout/stderr capture files remain execution-log artifacts, not Product
business artifacts.

Produced artifacts should be written under a fresh Host-owned output directory
whose path is injected privately. After exit, the Host validates regular-file
type, containment, symlinks, count, size, declared media type/name, and total
quota before publishing immutable artifact references. Script-returned
filesystem paths must never themselves become trusted artifact references.

### High: dependency and cross-platform promises are too broad for PM2

The proposal requires an interpreter and dependency-lock digest while leaving
the environment format as a later open decision. Its PM2 exit gate nevertheless
calls for Python, Bash, and Node fixtures. These cannot prove reproducibility or
portable support against the current Python-distribution inventory lock.

Split PM2 into capability slices:

1. product-supplied Python runtime, standard library only, no install hooks;
2. immutable prepared Python environments cached by
   `(runtime, platform, architecture, dependency-lock digest)`;
3. explicitly available Bash/PowerShell/Node toolchains with their own locks
   and platform contracts; and
4. native helpers only after per-platform artifact identity and loading policy
   exist.

Runtime names must resolve through a Product toolchain registry, not arbitrary
`PATH`. Declarations need an OS/architecture/runtime compatibility predicate
and, where necessary, platform-specific entrypoints. Validation should be able
to distinguish `valid but unsupported on this target` from an invalid package.
Bash must not be advertised as a portable generic `shell` runtime on Windows.
Tests need CRLF, Unicode, spaces, case-insensitive paths, missing interpreters,
signal/termination differences, and Windows/POSIX argument behavior.

Environment preparation must be explicit and cacheable; it must not create a
virtual environment or run a package manager on every invocation. Preparation
failure, offline operation, cache identity, environment retention, rebuild,
and garbage-collection leases need user-facing diagnostics.

### High: the public author contract arrives after the feature that needs it

PM2 delivers script declarations and execution, while PM5 later delivers the
public manifest/declaration and Skill-script authoring SDK. This leaves the
first real script adopter dependent on an internal format and makes the
multi-adopter stabilization gate circular.

Add an experimental but documented `v1alpha` authoring contract before PM2.
It may carry an explicit instability label, but it must have a codec, schema
version, CLI validator, migration policy, and conformance fixture. PM5 should
stabilize that surface after multiple adopters; it should not be the first time
authors can use it.

### High: there is no safe development loop

Immutable install and exact digests are production requirements, but requiring
pack/install/enable for every edit will push authors toward running scripts
directly. The plan needs a development command that snapshots the current
source into an ephemeral content-addressed revision and then uses the same
runtime resolver, policy, sandbox, input/result codec, and cleanup route as an
installed package.

Suggested commands are:

```text
loushang plugin validate PATH --target current --format json
loushang skill script run PATH SKILL_ID SCRIPT_ID --input request.json
loushang plugin pack PATH --output DIST
loushang plugin install DIST --disabled
loushang plugin explain PLUGIN_ID --format json
```

The development command must not offer an `--unsafe` shortcut that silently
changes execution trust. A debug option may retain a redacted diagnostic bundle
or ephemeral output directory under an explicit retention lease, but it must
not expose secrets or bypass containment.

### Medium: effect class must be a risk projection, not the only capability field

The plan says every declaration has one effective effect class, while its own
example combines workspace write and child-process execution. Common scripts
also read the workspace, invoke a compiler, and make a network request in one
call. One categorical value cannot faithfully express that authority set.

Keep a compositional requested/effective authority record—workspace roots and
mode, brokered tools, network profiles, secret references, artifact quota—and
derive one maximum risk/effect classification for policy, presentation, and
Approval routing. The derived class must not erase the individual capabilities
that enforcement consumes.

### Medium: authoring reads/builds should not be durable management mutations

The one-mutation-plane rule is correct for install, enable, update, repair,
retirement, and deletion. Pure `validate`, read-only `inspect/list/explain`, and
reproducible `pack` do not mutate Plugin desired state and should not need a
durable `PluginManagementService` operation journal.

Introduce a pure `PluginAuthoringService`/codec facade for validation,
canonical packing, target compatibility checks, and conformance tests. Its
pack result may then be submitted to `PluginManagementService.install`. Keep a
shared projection layer for inspect/explain, but do not turn every author CLI
operation into a lifecycle mutation merely to obtain a uniform command name.

### Medium: enablement and failure projection need compatibility rules

Today Skill enablement and Plugin enablement travel through separate legacy
settings paths. The migration plan says to converge them but does not define
the author-visible intermediate states. A Skill can be selected while one of
its scripts is unsupported, denied, unprepared, or waiting for approval.

Add a script availability projection independent of inert Skill visibility:
`available`, `unsupported_platform`, `runtime_unprepared`, `disabled`,
`pending_approval`, `denied`, and `invalid`. Skill listings and model input
should not imply that a script is runnable merely because the instructions are
enabled. Deprecation diagnostics should identify the old source/setting, the
new canonical command, and whether migration changes trust or permission.

## Recommended Author Journey

The plan should use this journey as a conformance scenario rather than only
listing management operations:

1. **Create:** an author adds `SKILL.md`, a script file, and one compact strict
   declaration with a stable script ID. A content-only Skill remains exactly as
   simple as it is today.
2. **Validate:** a pure command checks paths, schemas, target support,
   permissions, runtime availability, dependency locks, and result schemas
   without importing or executing code. Diagnostics carry stable code, source
   path, field/JSON pointer, target, severity, and remediation.
3. **Develop:** a run/test command snapshots the source tree to an ephemeral
   immutable revision and invokes the symbolic script through the production
   authorization path. It streams bounded stdout/stderr and prints the exact
   execution profile and containment status without secret values.
4. **Pack:** a reproducible pack command emits canonical bytes, the complete
   tree digest, dependency/runtime requirements, target matrix, and requested
   permission summary. Repacking unchanged inputs produces the same identity.
5. **Install disabled:** management verifies and retains the revision but does
   not prepare dependencies, import code, run scripts, or grant invocation
   authority.
6. **Prepare and enable:** an explicit operation prepares any immutable runtime
   environment, displays trust/permission differences, and records the
   activation decision. Preparation and enablement remain separable.
7. **Invoke and debug:** human and model calls use the same stable script ID and
   typed input. Status distinguishes invalid input, unsupported runtime,
   containment unavailable, policy denial, launch failure, non-zero exit,
   invalid result, rejected artifact, timeout, and cancellation.
8. **Update:** changed package, runtime lock, result schema, or permissions
   produce an explainable diff and a new decision where required; rollback pins
   the old package and prepared environment until its lease expires.

## Minimum Usable Slice

The first production slice should be narrower than the current PM2 while still
proving the real author experience:

- one packaged Skill with one or more named one-shot scripts;
- a Product-supplied, digest-identified Python runtime using the standard
  library only;
- `compute_only` and optionally read-only workspace profiles; no network,
  secrets, direct child-process execution, or install hooks;
- strict JSON stdin or no input; strict JSON/text stdout; bounded stderr;
- one fresh validated output directory for declared artifacts;
- pure validate, ephemeral dev-run, canonical pack, install-disabled, enable,
  run, inspect, and explain paths;
- both human CLI invocation and one model-visible Host action over the same
  `SkillScriptInvocationV1`;
- local/package Skill compatibility and stable machine-readable diagnostics;
  and
- a second real Skill adopter before declaring the script schema stable.

This slice keeps scripts practical: authors do not write an RPC server, Worker
main loop, lifecycle hooks, digest code, sandbox adapter, or Approval code. The
Host supplies those mechanics. Locked third-party Python dependencies should
be the next authoring slice, followed by platform-specific command runtimes and
only then long-lived Worker authoring.

## Concrete Corrections To The Delivery Plan

1. Insert **PM1A: Experimental Authoring And Invocation Contract** between PM1
   and PM2. Deliver strict script declaration/invocation/result codecs,
   symbolic Skill binding, a pure validator, ephemeral snapshot dev-run, and
   the availability projection.
2. Split PM2 into **PM2A zero-dependency one-shot**, **PM2B immutable Python
   environments**, and **PM2C additional platform runtimes**. Do not make Bash
   and Node support an exit condition of the first slice.
3. Add a Host-built sanitized environment and runtime resolver to PM2A. State
   explicitly that the general `ExecService` inheritance behavior is not the
   Skill-script policy.
4. Replace the single effect-class declaration with a compositional permission
   request plus a Host-derived risk class. Mark direct subprocess/domain
   restrictions unsupported unless the chosen backend proves enforcement.
5. Freeze JSON/text stdin/stdout semantics and the secure artifact output
   directory before accepting script SDK examples.
6. Define the authoritative manifest/declaration location and version
   migration before coding PM2. Do not put executable authority in generic
   unvalidated Skill metadata.
7. Change PM5 from "first public authoring surface" to "stabilize the
   experimental multi-adopter surface" and require compatibility fixtures from
   the earlier slices.
8. Separate pure authoring/build commands from durable management commands,
   while preserving `PluginManagementService` as the sole desired-state and
   lifecycle mutation owner.
9. Add the end-to-end author journey above to Success Measures and make it a
   release test rather than a documentation-only example.

## Author-Facing Acceptance Gates

The plan should not claim usable Skill scripts until all of these pass:

- A legacy content-only Skill loads unchanged and no adjacent file is executed
  or made invocable by convention.
- A declared script can be invoked by stable Plugin/Skill/script identity
  without placing a raw package path or shell command in model input.
- Validation and listing never import code, start an interpreter, prepare an
  environment, or run package-manager hooks.
- Development execution snapshots mutable source and traverses the same
  policy, Approval, sandbox, runtime, input/result, and cleanup route as an
  installed revision.
- A `compute_only` child receives a documented minimal environment and cannot
  observe an ambient Host credential fixture.
- Every declared permission is reported as OS-enforced, broker-enforced, or
  cooperative; an untrusted invocation fails closed when its required
  enforcement is unavailable.
- JSON input/output, invalid UTF-8 or JSON, truncation, non-zero exit, timeout,
  cancellation, and stderr streaming have stable distinct results.
- Generated artifacts cannot escape the output root through traversal,
  absolute paths, hard links, symlinks, devices, case folding, alternate path
  separators, or post-exit mutation; count and byte quotas are enforced before
  publication.
- Runtime resolution is independent of ambient `PATH`, and dependency
  preparation is explicit, content-addressed, offline-diagnosable, reusable,
  and leased through update/rollback.
- Target validation covers Windows and POSIX path, environment, newline,
  argument, process-tree, and unsupported-runtime behavior without pretending
  Bash is universally available.
- CLI and SDK diagnostics contain stable codes and field locations, redact
  secrets, and distinguish author error, policy denial, unavailable
  containment, missing runtime, dependency preparation failure, script
  failure, and artifact rejection.
- Updating an entrypoint, runtime/dependency lock, input/result schema, or
  requested permission produces a visible diff and invalidates the appropriate
  decision without disabling unrelated inert Skill content silently.

With these corrections, the proposal's execution classification remains sound
and Skills with scripts do not become Terraform Providers. Most scripts stay
ordinary bounded child processes; only their identity, inputs, authority, and
outputs become explicit enough for Loushang to execute them safely and
diagnose them well.

## Re-review Addendum

### Scope And Disposition

This addendum independently re-reviews the revised improvement plan against
the Critical and High findings above. It does not replace the original review,
which remains a record of the initial draft.

**Disposition: substantially resolved at plan level.** The revision now turns
the original author-experience recommendations into explicit contracts and
PLC8 delivery gates rather than leaving them as unspecified implementation
details:

| Original finding | Re-review disposition |
| --- | --- |
| Existing Skills with adjacent scripts become too heavy or stop working | Resolved. The plan preserves instruction-driven scripts through visibly generic Tool execution while making named managed execution optional (`improvement-plan:214-228`, `:907-917`). This matches the current prompt behavior, which exposes the Skill location and tells the model to resolve relative paths against the Skill directory (`src/loushang/harness/capabilities/prompt_assembly.py:110`; `prompt_preflight.py:96`). |
| No bound invocation path | Resolved. `SkillScriptDeclarationV1`, stable Skill/script IDs, the `skill.script.run` action, invocation/result codecs, and one human/model invocation record are explicit (`improvement-plan:220-256`, `:718-745`). |
| Ambient environment and unenforceable allowlists | Resolved at plan level. `AuthorizedSkillScriptExecutor` builds an allowlisted environment from empty, uses a Product-qualified toolchain, and rejects cooperative executable/endpoint restrictions for untrusted execution unless sandbox-enforced or brokered (`improvement-plan:263-280`). The adversarial exit gate covers credentials and interpreter/PATH substitution (`:747-749`, `:959-970`). |
| Manifest/schema source of truth and optional failure | Resolved. The declaration is a strict versioned Resource-owner schema referenced from the existing Plugin declaration model, not arbitrary frontmatter or a new registry; optional and required failure behavior is stated (`improvement-plan:230-243`). PLC8A owns the codec, fingerprints, availability states, and v1alpha exposure before execution (`:718-732`). |
| Input/stdout/stderr/artifact ambiguity | Resolved. V1 fixes JSON/no-input stdin, text/strict-JSON stdout, diagnostic stderr, exit semantics, distinct terminal reasons, and Host-owned artifact validation/publication (`improvement-plan:288-312`). |
| Dependency and platform scope too broad | Resolved by sequencing. Zero-dependency Product Python is isolated in PLC8B-1, immutable Python environments in PLC8B-2, and explicit Bash/PowerShell/Node/native targets in PLC8B-3, including Windows/POSIX conformance (`improvement-plan:734-775`). |
| Public author contract arrives too late | Resolved. PLC8A publishes a documented experimental/v1alpha contract before executable implementation; PLC8C stabilizes it only after two materially different script adopters (`improvement-plan:718-728`, `:777-788`). |
| No safe development loop | Resolved. Mutable source is snapshotted into an ephemeral content-addressed revision and traverses the production managed route, with explicit validate, dev-run, pack, install-disabled, and explain examples and no `--unsafe` path (`improvement-plan:258-271`, `:668-688`). |
| Single effect class cannot express real scripts | Resolved. Effects are additive owner-qualified facts; the risk tier is derived diagnostics only (`improvement-plan:171-196`). |
| Authoring, query, and durable mutation are conflated | Resolved. `PluginAuthoringService`, `PluginManagementService`, and read/exact-owner projectors are separate ports (`improvement-plan:322-359`, `:599-617`). |

### Residual P0/P1 Findings

**P0: none found.** No original authoring blocker remains unaddressed strongly
enough to invalidate the revised delivery direction.

**P1: the legacy generic-Shell lane needs provenance-aware policy treatment.**
Preserving existing script-bearing Skills is the correct compatibility choice,
and current prompt assembly already makes their relative paths usable. The
revision currently says that installed third-party adjacent scripts continue
under generic Tool Policy/Sandbox and that organization policy *may* deny them
(`improvement-plan:214-228`). It also correctly refuses to report them as
managed Skill-script executions.

What remains unspecified is how the generic execution Policy subject learns
that an argv path resolves inside a known installed or project Skill package.
Without that provenance, an untrusted `SKILL.md` can recommend the raw adjacent
script path and receive only an ordinary command-path decision, bypassing the
managed lane's permission/trust diff and availability status. This does not
make the command unaudited—the generic Tool remains audited—but it makes
source trust and migration risk invisible at the authorization point.

Before architecture acceptance, add this invariant to PLC8A migration
semantics:

- generic Tool preparation resolves executable/script arguments against known
  Resource/Plugin roots when possible and attaches non-authoritative package,
  Skill, source-kind, revision, and trust provenance to Policy/Approval/audit;
- this classification never upgrades the command to managed execution and
  never grants package authority;
- Product policy defines an explicit default for raw script execution from an
  installed third-party package—at minimum `ask` with truthful provenance and
  required generic-tool containment, or deny—not an unspecified organization-
  policy option; and
- project-local/user-authored legacy scripts remain compatible under the
  Product's ordinary generic Tool policy, so this correction adds no manifest
  or Worker burden to existing Skill authors.

This closes the only material bypass between the compatibility and managed
lanes without prohibiting scripts or pretending that legacy execution has
managed identity.

### Non-blocking Delivery Details

The following details can remain owned by PLC8A/PLC8B contracts, but their
conformance fixtures should be explicit:

- freeze how the Host communicates the artifact output directory to the child
  and ensure that mechanism is part of the invocation ABI and clean-environment
  allowlist;
- require stable diagnostic code, source location/JSON pointer, target,
  severity, and remediation fields for validator and runtime failures;
- for the Product Python runtime, disable ambient user-site, `sitecustomize`,
  loader, and module-search-path influence rather than treating removal of
  environment variables alone as Python isolation; and
- do not treat the current Python `name==version` inventory lock as a complete
  immutable environment format. PLC8B-2 must bind exact distribution artifacts
  and any resolver/build/toolchain identity required for reproducibility before
  it claims prepared-environment identity.

### Final Verdict

**Conditionally approve the revised plan after the single P1 legacy-provenance
invariant is added.** The plan now keeps ordinary script-bearing Skills usable,
gives authors an optional lightweight managed path, and stages the hard runtime
and platform work without forcing one-shot scripts into Worker/RPC machinery.
The remaining dependency-format and ABI details are correctly deferred to
explicit PLC8 contracts and do not block the overall delivery sequence.

### Final Closure Check

**Disposition: closed.** The latest plan closes the remaining legacy generic-
Shell P1: generic Tool preparation attaches non-authoritative package, Skill,
source-kind, revision, and trust provenance when a path resolves under a known
root; this does not confer managed identity or authority, and raw execution
from an installed third-party Skill defaults to at least `ask` plus required
generic-Tool containment (`improvement-plan:224-231`). The verification matrix
now makes both provenance propagation and the minimum default policy release
gates (`improvement-plan:1034-1039`).

The accompanying ownership refinements preserve the author journey. Canonical
pack and ephemeral snapshot remain bounded, lifecycle-pure authoring artifact
operations; staged install coordinates verified publication/binding with an
install-disabled CAS without moving package-byte ownership into management
(`improvement-plan:645-690`). Prepared environments are package-owned immutable
derived artifacts with explicit preparation, leases, rollback, repair, and GC;
install, inspection, and invocation cannot build them implicitly
(`improvement-plan:825-846`). Authors still follow validate -> snapshot dev-run
-> pack -> install disabled -> prepare/enable -> invoke/debug.

**Final verdict: approve from the authoring perspective.** No residual P0 or P1
author-experience finding remains in this review scope. The deferred ABI,
diagnostic, Python-isolation, and dependency-format details remain correctly
assigned to PLC8 conformance contracts rather than reopening the delivery-plan
architecture.
