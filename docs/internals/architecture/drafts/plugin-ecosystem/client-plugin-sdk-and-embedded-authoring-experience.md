# Client Plugin SDK And Embedded Authoring Experience

## Status

- Authority: proposed — non-normative authoring contract
- Design status: proposed, revised after three independent reviews
- Implementation status: not-started as a stable public SDK; internal
  authoring and runtime foundations exist
- Owner: Loushang architecture; affected owners include Harness and client
  Products

This document is not accepted architecture and does not define a stable public
SDK.

This revision incorporates the independent
[security review](reviews/client-plugin-sdk-and-embedded-authoring-experience-security-review.md),
[authoring review](reviews/client-plugin-sdk-and-embedded-authoring-experience-authoring-review.md),
and
[architecture review](reviews/client-plugin-sdk-and-embedded-authoring-experience-architecture-review.md).
It closes their plan-level findings in the document; implementation acceptance
still requires the delivery and executable gates below.

The later source-authority, native managed-script, contribution-selection,
configuration, and mutable-state refinements were made after those reviews and
remain proposed.

This document is an authoring overlay for the
[Plugin Management And Isolated Execution Improvement Plan](plugin-management-and-isolated-execution-improvement-plan.md).
It does not create another Plugin lifecycle, Resource catalog, manifest runtime,
declaration compiler, dependency-injection container, Capability Graph,
Registration owner, Approval owner, Sandbox, package store, process launcher,
management writer, or effective-state clock.

## Executive Decision

Loushang client products should provide a deliberately small Plugin SDK.
Ordinary authors should not implement
activation hooks, process launch, RPC, Approval, Sandbox, digest, lease,
generation, or cleanup logic.

The simplification is an authoring projection onto existing strict inputs and
exact owners. It is not a simpler parallel runtime.

The target authoring ladder is:

| Level | Primary author | Typical content | Short author experience | Effective execution |
| --- | --- | --- | --- | --- |
| L0: native Resource tree | Skill/Prompt/Theme author | `SKILL.md`, prompts, themes, supported assets, and optional named bounded Skill scripts | Put files in a Product-supported native root; add one strict script sidecar only when managed execution is needed | Declarative Resource path plus optional snapshot-bound one-shot action; no Plugin identity |
| L1: canonical Resource package | Resource/script or distribution author | Versioned Resources, named bounded scripts, and optional independently enabled Plugin identity | One canonical package manifest plus owner documents | Declarative plus authorized one-shot process |
| L2: Product build facade | Loushang/Product developer | Trusted Tools, Components, Providers | Existing typed definitions plus one concise Product build spec | Explicit host-equivalent in-process where admitted |
| L3: generated Worker SDK | Long-lived service author | LSP, indexer, browser, debugger, connector | Implement one generated domain interface | Supervised required-containment Worker |

Authors start at the lowest level that meets the requirement. Adding a script
does not require a Worker or Plugin identity. Packaging is required when
distribution, versioned dependency preparation, independent Plugin desired
state, or atomic install/update/rollback is required. Packaging data does not
require executable declaration code. Source location never creates trust.

## Contract Vocabulary

- **Native Resource** is content discovered directly from a Product-supported
  Resource root. It has Resource provenance, but no synthesized Plugin Instance,
  desired state, package lease, or Plugin Approval.
- **Canonical package** is an immutable package whose single runtime manifest is
  `plugin.json`, including a complete inert `ContributionIndex` before any
  executable declaration source can be considered.
- **Authoring facade** is a constrained way to produce native Resource input,
  canonical package bytes, Product-owned static registration input, or a
  generated Worker adapter. It is not a runtime owner.
- **Product build facade** is first-party code evaluated only by the trusted
  Product build pipeline. Runtime consumes its emitted inert artifacts and does
  not re-run it for discovery.
- **Definition** is an executable declaration source evaluated only after the
  exact immutable source has passed preflight and declaration-execution
  Approval. It receives a Host-created, reservation-bound builder.
- **Managed Skill script** is a one-shot executable action owned by one exact
  executable source revision, Skill Resource, and script declaration. The source
  revision is either a canonical package revision or a Host-created immutable
  Resource snapshot. It is not a Tool Pack item or a per-Skill Plugin.
- **Source authority** is the exact Host, Executor, Orchestrator, or future
  owner-qualified provider through which Resource bytes are listed and read. It
  is not a path prefix, installation scope, or trust level.
- **Worker adapter** is generated protocol glue behind an exact Product domain
  contract. It is not a generic remote `PluginContext` or self-registering RPC
  service.

Human-readable IDs and paths are query inputs. Immutable package identity,
owner evidence, decisions, uses, generations, and leases remain Host-resolved
runtime facts.

## Authoring And Runtime Architecture

### Native and packaged Resources have two ingress paths

The convergence point is the Resource-owner candidate/catalog contract, not a
universal Plugin declaration IR:

```text
native Resource convention
  -> Resource source snapshot/candidate
  -> Resource-owner catalog admission and selection
  -> Resource generation

canonical packaged Resource
  -> plugin.json + complete ContributionIndex
  -> Plugin preflight and declaration finalization
  -> Resource-owner candidate/admission
  -> the same Resource generation
```

Only the second path has Plugin identity, package lifecycle, desired state,
declaration reservations, and Plugin Approval evidence. A native `SKILL.md`
must not be silently wrapped in a generated Plugin.

### Executable authoring has explicit phases

The word `compiler` is not one security boundary. The following phases are
different and must stay visibly different:

| Input or operation | May execute author code? | Output or runtime route |
| --- | --- | --- |
| Native directory parsing | No | Resource source snapshot/candidate |
| Canonical `plugin.json` and strict declaration documents | No | Inert descriptor, ContributionIndex, preflight input |
| Trusted Product build facade | Yes, only in the controlled Product build | Canonical package envelope plus Product-owner static build input |
| Runtime in-process Definition | Only after exact declaration-execution decision/use | Reservation-bound declarations matching the predeclared index |
| Project/OEM/third-party executable declaration source | Only in the accepted isolated evaluator, otherwise rejected | The same reservation-bound declarations |
| Worker domain implementation | Only after process-backed activation and required containment | Attempt-bound typed domain service |

`validate`, structural `pack`, install-disabled, list, inspect, Resource
discovery, and explain never import a builder, execute a decorator, evaluate a
module global, prepare dependencies, or run a generator selected by the
package.

### One manifest and one runtime declaration authority

V1 has one runtime package manifest: strict canonical `plugin.json`. Primary
author documentation and templates use that format. This proposal does not
introduce runtime TOML or make `loushang-package.json` a peer Plugin declaration
authority.

Simplicity comes from schema-aware initialization, completion, diagnostics, and
generators that write canonical JSON, not from teaching authors a second source
format. Generated files remain ordinary inspectable package inputs.

A later author-only shorthand may be considered after PLC8C, but only if:

- it has an explicit versioned `AuthorPackageSpec` identity;
- an offline compiler deterministically emits the canonical `plugin.json` and
  strict declaration documents;
- the authoring source is never parsed by runtime install/discovery;
- canonical JSON pointers and author source locations appear together in
  diagnostics;
- handwritten and generated canonical forms produce byte-identical documents
  and semantic fingerprints; and
- no alias, default, or shorthand survives downstream as an additional policy
  input.

The same rule applies to interoperability. A future Agent Plugin or other
external-layout importer is an offline authoring adapter that emits the one
canonical `plugin.json` plus owner documents and dual-source diagnostics. The
runtime never gains a second manifest parser or a vendor-extension authority;
unsupported or lossy executable fields fail instead of being silently widened.

The public authoring compiler cannot construct reservations, mint canonical
`PluginDeclaration` objects, publish contributions, or access the Coordinator.
Runtime declaration compilation remains the Host-created SourceGroup and
one-use reservation path. Unknown, extra, duplicate, or unconsumed
contributions fail closed under the existing strict codecs.

Build output records the compiler, SDK schema, generated-adapter, and Product
build identities. Runtime consumes those inert supply-chain facts; it never
runs a package-provided generator to reconstruct them.

## Trust, Desired State, And Independent Decisions

### Placement, scope, authority, provenance, and execution are independent

The concise author labels are placement facts:

- `product_embedded`: exact bytes are bound by an immutable Host Product release
  manifest or equivalent Product-owned build registry;
- `project_local`: bytes are discovered from a Product-supported project root;
  and
- `user_global`: bytes are discovered from a Product-supported user root.

They are separate from source authority, installation/desired-state scope,
release provenance, execution trust, and execution shape. Packaged Plugins use
the unified `user | project` desired-state scopes; a Session may select an
already admitted revision but cannot install bytes. Native Resources have
source precedence and selection, not fabricated Plugin desired state.

V1 reads materialized artifacts and local Resource trees through the Host
authority. A future Executor- or Orchestrator-owned root keeps an opaque locator
and must be read through that owner. No caller may reconstruct a Host path from
it. Resolution remains inert and does not activate any contribution.

No package field, directory name, CLI switch, developer mode, naming convention,
local placement, source authority, or package-selected signature can create
`product_embedded` placement or host-equivalent execution trust.

The Product release trust record binds at least:

- Product distribution/build identity and trusted release-key policy;
- exact package and dependency-closure digest;
- Plugin ID and allowed declaration execution topology;
- maximum owner kinds and requested authorities;
- Product/Profile/trust-policy revisions; and
- revocation epoch.

The allowlist is immutable Product/OEM policy input. It cannot be contributed,
mutated, or widened by Plugin code or the authoring SDK.

### Co-distribution does not collapse authority

An executable built-in follows separate decisions and owners:

```text
Host-resolved Product release provenance
  -> Product/OEM trust and authority ceiling
  -> desired-state input from Product Runtime Plan or management ledger
  -> declaration-execution subject / decision / one-attempt use
  -> Host-created SourceGroup and reservation-bound Definition
  -> exact-owner admission
  -> contribution-activation subject / decision / one-attempt use
  -> Product selection and Graph binding
  -> exact-owner publication
  -> later action-specific decisions, when effects are invoked
```

Product policy may make the execution and activation decisions non-interactive,
but the Approval owner records and consumes them independently. A declaration
execution receipt cannot activate a contribution, start a Worker, or invoke a
script. Enablement is expressed through the Product Runtime Plan/Composition
Set and the sole `PluginManagementService` desired-state port; a decorator or a
second built-in registry cannot self-enable anything.

The exact capability owner remains admission authority, Product composition
remains selection authority, and the Graph Binder remains binding/publication
authority.

## L0: Native Convention-Only Resources

The smallest supported author journey is concrete:

```text
.loushang/
`-- skills/
    `-- review/
        `-- SKILL.md
```

The Product Resource owner discovers, validates, normalizes, fingerprints,
selects, and projects this content. There is no manifest, Plugin Instance,
installation, Python import, Worker, or Approval.

A native Skill may optionally add a strict Resource-owner script sidecar. The
proposed spelling is `skill.scripts.json`; the owner schema, not the filename,
is normative until PLC8A freezes it:

```text
.loushang/skills/review/
|-- SKILL.md
|-- skill.scripts.json
`-- scripts/
    `-- generate.py
```

Discovery parses the sidecar and script inventory as inert data. Before a
dedicated `skill.script.run`, the Host creates and leases an immutable
`ResourceSnapshotRevision` covering the complete Skill root. This supplies
managed identity without synthesizing a Plugin Instance, desired state,
installation record, or package lifecycle. A mutable unsnapshotted path remains
only a generic Tool/Shell action.

Only Resource kinds listed by the versioned Product target matrix may use a
native convention. Documentation must not imply that templates, assets,
methods, sources, prompts, or themes all share a directory convention unless
that Product target actually declares it. Other kinds use an accepted packaged
`resource_item` route.

L0 requirements are:

- zero Python execution and zero RPC during discovery, validation, refresh, and
  model-input projection;
- no lifecycle hooks and no per-Resource Plugin Instance;
- existing native content-only Skills remain compatible;
- listing/loading/validation/refresh never executes adjacent files; and
- provenance distinguishes native source from packaged Plugin source while the
  final Resource projection remains semantically equivalent where applicable.

## L1: Canonical Resource Package

### Package shape and ownership

A packaged Skill with one managed script has one canonical manifest:

```text
acme-review/
|-- plugin.json
|-- declarations/
|   `-- resources.json
|-- skills/
|   `-- review/
|       `-- SKILL.md
`-- scripts/
    `-- generate.py
```

`plugin.json` contains the complete inert ContributionIndex. The Resource
declaration document contains the strict Resource/Skill projection. PLC8A adds
one owner-versioned `SkillScriptDeclarationV1` to that Skill projection. The
native sidecar and packaged declaration compile to the same owner descriptor;
script metadata is not arbitrary `SKILL.md` frontmatter and not a
package-global `[[scripts]]` registry.

The normalized managed-script identity is:

```text
{executable_source_revision, skill_resource_id, script_id}

executable_source_revision
  = PackageRevision(package_id, revision, digest)
  | ResourceSnapshotRevision(authority, resource_root_id, revision, digest)
```

The full invocation additionally binds Product, Profile, actor, Session,
invocation/attempt, deadline, and revocation facts. A friendly reference such
as `acme.review:review` must resolve to exactly one active immutable Resource
identity before Approval. Ambiguous, missing, disabled, or stale-revision
resolution fails with a stable diagnostic.

`SkillScriptDeclarationV1` contains only author intent:

- stable script ID owned by one Skill Resource;
- contained source-root-relative entrypoint;
- Product-owned runtime/toolchain requirement;
- versioned input, result, and Artifact contract;
- requested additive authorities and containment floor;
- platform predicates; and
- time, stream, file, count, byte, and output limits.

Unknown fields, duplicate IDs, absolute or escaping paths, symlinked
entrypoints, ambiguous runtime aliases, and unknown authority/profile IDs fail
the script closed. An invalid optional script does not erase inert `SKILL.md`
availability. A required invalid script makes its owning package contribution
inadmissible; for a native Skill it makes only that script unavailable unless
the Product explicitly declares it required for Resource admission.

Profile, runtime, authority, and containment IDs use one owner-versioned
canonical vocabulary across JSON, Python author types, CLI output, decisions,
and audit. Alternate hyphen/underscore spellings are not implicit aliases.

### Managed invocation and independent action authority

Human and model clients prepare the same typed action:

```text
loushang skill script run acme.review:review generate --input request.json
```

```text
skill.script.run(
  package="acme.review",
  skill="review",
  script="generate",
  input={...},
)
```

The display aliases are not authority. Preparation resolves and displays the
exact executable source revision, Skill Resource ID, and script ID. A native
source may omit `package` from the author-facing request, but the prepared
action never omits its exact Resource snapshot identity.

Every invocation creates a separate versioned `SkillScriptInvocationSubject`
and consumes one one-attempt Approval use. The subject binds at least:

- exact executable source revision, entrypoint, interpreter/toolchain, and any
  dependency-environment identities;
- actor, Product, Profile, Session, Skill, script, invocation, and attempt;
- argv, cwd, clean-environment fingerprint, input/result schema fingerprints,
  limits, and Artifact policy;
- additive effects, required containment, Sandbox policy/probe revisions;
- expiry and revocation epoch.

Package enablement, declaration execution, Resource selection, and contribution
activation do not grant later script calls. Product automatic policy may avoid
an interactive prompt, but it still emits the same per-invocation subject,
decision, use, and audit evidence.

### Verified launch

An internal `AuthorizedSkillScriptExecutor`, not the public SDK and not raw
`ExecService`, consumes the invocation decision. It accepts only an
owner-admitted descriptor, leased verified revision, Product-resolved
toolchain, additive effect set, and execution scope.

It must:

- bind the opened verified revision to an immutable Sandbox projection or an
  equivalent handle-relative launch;
- prevent a check-then-reopen of mutable script, interpreter, dependency
  environment, cwd, or output-root paths;
- use a Product-admitted immutable runtime rather than ambient `PATH`, shebang,
  wrapper, or shell-string resolution;
- construct the child environment from an explicit allowlist starting empty;
- prove required containment before spawn;
- hold revision, runtime, Artifact, credential, and containment leases through
  physical settlement; and
- durably terminalize consumed-not-started, running, cancellation, crash,
  output-validation, and cleanup outcomes without reusing a decision.

`ExecService` remains neutral process/stream/cancellation mechanics. Direct use
of `ExecService` or `AuthorizedProcessLauncher` cannot claim managed-script
identity or consume managed-script authority.

### V1 input, result, diagnostics, and Artifact ABI

V1 uses a versioned ABI, not merely the phrase “JSON in, JSON out”:

- input is either absent or exactly one bounded UTF-8 JSON value; absent and
  JSON `null` are distinct;
- duplicate object keys, non-finite numbers, malformed UTF-8, and trailing data
  fail closed;
- the declaration fixes maximum input/result/diagnostic bytes and an optional
  versioned JSON Schema reference plus fingerprint;
- stdout contains one declared result only; empty success output is valid only
  when explicitly declared;
- stderr contains bounded diagnostics; progress uses stderr or a separate
  bounded Host channel, never business-result framing;
- Artifact descriptors are separate from stdout business data;
- zero/non-zero platform exits normalize into stable result categories instead
  of leaking platform status as the only contract; and
- timeout, cancellation, containment failure, script failure, invalid result,
  Artifact rejection, partial workspace write, and cleanup debt remain
  distinguishable.

Business Artifacts are accepted only from a fresh Host-owned output root after
escape, symlink, hard-link, device, file-type, count, byte, media-type,
post-exit stability, and containment validation. The output root is supplied by
a versioned invocation ABI, not an undocumented ambient environment convention.

### Legacy adjacent scripts

An existing `SKILL.md` may instruct the Agent to execute an adjacent script via
the generic Tool/Shell path. That route remains a generic Tool action and is
never relabelled as managed execution.

Recognized Resource/Plugin provenance is advisory. It may tighten Policy or
improve disclosure; it never grants authority or reduces containment. In
particular:

- `project_local` and `user_global` describe placement, not authorship or
  trust;
- unknown or unrecognized provenance stays `unknown`;
- moving identical bytes into a project directory cannot make a generic command
  less restricted;
- reusable Plugin/script grants are unavailable because mutable executable
  bytes are not bound; and
- Products requiring immutable package-qualified execution deny the legacy
  action with migration guidance to snapshot and use the managed route.

Approval and audit label mutable/unverified executable identity truthfully and
do not present an advisory package revision as the bytes actually executed.

## L2: Trusted Product Build Facade

The first stable L2 form reuses existing Tool authoring decisions and separates
executable Tool definitions from data-only Tool Pack references:

```python
from loushang.plugin.authoring import (
    product_builtin,
    resource_tree,
    tool_pack_ref,
)
from loushang.product.tools import direct_tool, tool


@tool()
async def analyze(path: str) -> AnalyzeResult:
    ...


ANALYZE = direct_tool(analyze)

BUILTIN = product_builtin(
    id="coding.base",
    version="1",
    resources=resource_tree("resources"),
    tool_definitions=[ANALYZE],
    tool_packs=[
        tool_pack_ref("coding.base.tools", tools=("coding.analyze",)),
    ],
)
```

Names are candidate author APIs, not currently stable imports. The shape is
normative:

- `product_builtin` is trusted Product-build input, not a runtime decorator
  registry or `PluginContext`;
- the controlled Product build may evaluate it and emits a complete inert
  canonical package envelope before runtime;
- Tool definitions are staged by the exact Tool owner;
- Tool Pack declarations remain data-only references to admitted Tool item IDs;
- runtime never imports this module to discover IDs, authority, owners, schemas,
  or execution topology; and
- runtime Definitions, where still needed, receive only a Host-created
  reservation-bound builder and must match the predeclared index closure.

“No handwritten manifest” means the Product build generated the canonical
manifest. It never means “no inert security envelope.” Copying the same source
to a project root selects the isolated declaration evaluator or fails; it does
not retain first-party build trust.

### Dependency injection

V1 keeps the existing explicit `ToolContext` or owner-specific Provider context.
Plain Python annotations remain model input and never infer authority or trigger
runtime service lookup.

Parameter-level injection is deferred until at least two real adopters justify
it. If later accepted, it must use an explicit marker such as
`Injected[WorkspaceRead]`, be deterministically excluded from the model schema,
compile to an inert allowlisted owner-versioned requirement, and resolve only
through Product composition, Provider selection, Graph binding, and Consumer
capture. It cannot introduce another dependency-injection container.

Typed facets are cooperative architecture and audit contracts for
host-equivalent in-process code. They do not Sandbox Python, prevent ambient
module/filesystem/network/process access, or make authority revocably least
privileged. Status must report admitted in-process code as `host_equivalent`,
never `facet_scoped` or `sandboxed` merely because the function signature is
narrow.

### Default lifecycle

The common built-in form has no public `start()` or `stop()`:

- immutable Resources are owned by the Resource generation;
- Tool definitions are staged, committed, and retired by the exact Tool owner;
- Tool Packs select/consume Tool definitions but do not own their execution;
- typed Provider factories are constructed and disposed by their exact
  Component Host; and
- a narrow async disposer exists only for a service that owns resources.

The facade cannot admit, select, register, publish, mutate desired state, or
publish foreign-owner generations.

## L3: Generated Domain Worker SDK

The Worker facade is not public until the accepted Execution/Worker ARD and
PLC9B provide a versioned process-backed activation subject. A generic
`@service("string")` registry plus unqualified `serve()` is not the stable API.

The target author shape is generated from a Product-owned domain schema:

```python
from loushang_plugin_sdk.coding_index_v1 import CodingIndexService, serve


class PythonIndexer(CodingIndexService):
    async def open(self, request: OpenRequest) -> OpenResult:
        ...

    async def query(self, request: QueryRequest) -> QueryResult:
        ...

    async def close(self, request: CloseRequest) -> None:
        ...


if __name__ == "__main__":
    serve(PythonIndexer())
```

The generated SDK owns framing, schema negotiation, request IDs, deadlines,
cancellation, streaming, backpressure, bounded diagnostics, graceful shutdown,
and protocol-version tests. It owns stdout exclusively; ordinary stdout writes
fail conformance or are redirected to bounded diagnostics.

The internal runtime must additionally guarantee:

- the exact Component owner prepares and admits the Worker candidate;
- an independent process-backed activation decision/use is consumed immediately
  before containment planning and spawn;
- `AuthorizedProcessLauncher` remains a lower physical-launch invariant and
  cannot substitute for Plugin activation authority;
- project/user/OEM Workers fail before spawn unless capability-complete required
  containment is proven; best-effort, degraded, disabled, unresolved, or
  incomplete containment is not enough;
- the Host provides an attempt-bound nonce/bootstrap channel; Worker-reported
  identity, health, fingerprint, and schema facts cannot expand the admitted
  candidate;
- IPC uses strict, bounded, language-neutral values and rejects pickle, dynamic
  object proxies, unknown fields, oversized frames, duplicate/stale replies, and
  retired attempts;
- every reverse callback is a narrow Product-owned facet with a fresh check of
  attempt, owner generation, target/effect, deadline, and revocation facts; and
- process tree, streams, Sandbox plan, package/environment leases, owner route,
  drain, termination, and cleanup settle truthfully on revoke, cancellation,
  crash, Session close, or protocol failure.

`serve()` exposes no raw process handle, launcher, Approval resolver, Sandbox,
management writer, Registry, environment dump, secret material, or generic Host
object proxy. Only the exact owner can publish readiness and effectiveness.

Service-contract version, wire-protocol version, Plugin package version, and
Product compatibility version are independent. PLC9B freezes the wire protocol
only after two materially different domain shapes and Python plus one non-Python
implementation pass the same golden suite, including cancellation, streaming,
malformed input, shutdown, and version negotiation. Rust, Go, and Node SDKs are
possible later outcomes, not first-release prerequisites.

## Host-Release And Local-Source Outcomes

Placements may share concise author syntax, but they have different runtime
truth. The table compares provenance/placement only; installation scope and
source authority remain separately reported:

| Fact | Product-embedded Host release | Project-local or user-global source |
| --- | --- | --- |
| Classification source | Immutable Host Product release manifest | Project/user configuration |
| Declarative Resources | Allowed after normal validation/admission | Allowed after normal validation/admission |
| In-process executable declaration | Only if exact host-equivalent allowlist and decisions agree | Rejected |
| Managed script | Per-invocation authorized launch bound to the release/package revision | Per-invocation authorized launch bound to an immutable Resource snapshot or installed package revision |
| Long-lived executable | May be in-process only under explicit host-equivalent policy; otherwise Worker | Required-containment Worker |
| Automatic decisions | May be non-interactive but remain separate recorded uses | Product policy normally asks or denies; placement grants nothing |
| Explain language | Exact release evidence and policy rule | Placement, source authority, and effective route; never “trusted because local” |

Changes to executable digest, dependency closure, authority, execution topology,
Product build, Profile, trust policy, or revocation epoch invalidate prior
automatic evidence. Conservative restart/new-Session rules remain in force
where the current lifecycle cannot safely hot-replace host-equivalent code.

### Plugin desired state and contribution selection

The client exposes one Plugin enable/disable control. It does not imply that all
contributions share one runtime state. Each packaged contribution has a stable
ID and an explicit `required | optional` relation:

- Plugin desired state remains owned by `PluginManagementService` and the
  existing Config owner;
- per-contribution enablement, Product eligibility, MCP/tool policy, and similar
  choices are owner-qualified configuration;
- a required contribution blocks the revision from becoming effective for the
  affected Product/Profile when it is denied or unavailable;
- an optional contribution may be unavailable while status reports `partial`;
  and
- new Sessions select an updated revision only after its required contributions
  reach their exact-owner readiness gates.

This is a selection barrier over existing owner generations, not a global
Plugin registry or a fabricated cross-owner transaction. Existing Sessions keep
their accepted revision and generations.

## Exact Owner And API Mapping

| Author-facing concept | Author input only | Runtime compilation/admission | Exact live owner | Forbidden substitute |
| --- | --- | --- | --- | --- |
| Native Skill/Prompt/Theme | Directory convention | Resource source snapshot and owner Catalog rules | Resource generation owner | Generated Plugin identity or per-Resource registry |
| Packaged Resource | Canonical `plugin.json` and strict document | ContributionIndex, declaration decoder, Resource-owner admission | Resource generation owner | Runtime shorthand parser or package-local Resource registry |
| Managed Skill script | Native strict sidecar or packaged `SkillScriptDeclarationV1` | Exact executable-source/Resource resolution and `AuthorizedSkillScriptExecutor` | Resource/Skill action owner plus one-shot execution scope | Per-Skill Plugin Instance or direct subprocess |
| Built-in Tool | Product build spec plus existing typed `ToolDefinition` | Reservation-bound declaration and Tool-owner staging | Exact Tool owner generation/Registration scope | Import-time decorator registry |
| Tool Pack | Data-only exact Tool item references | Tool Pack owner admission and Product selection | Tool Pack generation | Callable-bearing Tool Pack |
| Capability Provider | Provider author spec | Eligibility, Product normalization, final owner admission, selection, Graph bind | Capability owner and Graph Binder | Facade-owned provider registry |
| Capability component | Owner-schema author spec | Exact-owner component resolver/admission | Exact capability component generation | Global component/service registry |
| Coding language server | Coding author spec | `coding.lsp` component referencing admitted service and immutable runtime | `coding.lsp` owner generation | `language_services` registry or bare `PATH` command |
| Work executor | Future author spec after separate acceptance | Future Product preparer/executor contract | `WorkRuntime` retains lifecycle; future executor owner must be explicit | Plugin mutation of `WorkRun` or event log |
| Long-lived Worker | Generated domain service implementation | Exact Component Host and internal Worker coordinator | Exact domain owner; Process Host owns mechanics | Worker self-registration or generic remote context |
| Configuration option | Data-only `ConfigSpec` | Existing layered configuration schema/codec | Exact Configuration destination owner | Plugin-local settings runtime |
| Presentation | Data-only `PluginPresentationSpec` | Product presentation admission | Product presentation owner | Metadata granting trust or availability |
| Mutable component data | Generated domain request | Exact class/subject/quota/schema admission | Existing Product/domain, credential, or Artifact owner | Universal writable Plugin directory |
| Typed event extension | Future exact-event owner spec | Existing Extension admission plus event-owner policy | Exact event/Extension owner generation | Global Hook bus or raw command/URL callback |
| Install/enable/update/remove | Typed client command | `PluginManagementService` and package authorities | Management desired-state owner plus exact package owners | SDK writing desired state or materializing bytes |
| Built-in trust | Co-distribution and Product/OEM facts | Approval decisions/uses plus exact-owner admission | Existing independent owners | Decorator, path, signature, or built-in registry granting trust |

## Product-Specific Convenience Overlays

The common SDK has no dependency on Work or Coding. A Product overlay may only
narrow configuration and build accepted authoring specs. It cannot admit,
select, register, bind, publish, mutate desired state, or rewrite Product
defaults after `ProductCompositionCompiler`.

Every overlay feature must name its declaration kind, admission owner, selection
owner, binding/publication owner, and retirement owner, and must produce the
same canonical bytes and candidate fingerprint as the non-overlay form.

### Coding overlay

Coding may stabilize features incrementally where an existing exact owner is
already proven. A language-server convenience form must reference a
Product-resolved immutable runtime/tool identity, never ambient `PATH`:

```python
language_service(
    language="python",
    runtime="node.product.pyright@1",
    entrypoint="pyright-langserver",
    args=("--stdio",),
    protocol="lsp.stdio.v1",
    workspace_authority="read_write",
    containment="required",
)
```

This is candidate authoring syntax, not a stable import. It compiles to the
existing `coding.lsp` component referencing an admitted external service. The
Product registry resolves runtime, environment, and executable identity before
activation Approval and launch. Unsupported platform/runtime is an explicit
availability result; there is no fallback to ambient shell or `PATH` behavior.

Tool Pack and Resource conveniences likewise compile to existing owner kinds.
The overlay cannot create a second `language_services`, Tool, Resource, or Graph
registry.

### Work overlay is deferred

No public `loushang.work.plugins`, `@work_plugin`, or `step_executor` contract is
reserved by this proposal. Work authoring remains a future, non-committed
overlay until all of the following are accepted and proven:

- the `harnesswork` migration and run-bound plan contract;
- Product work-preparer/executor boundary;
- contribution kind and exact admission/selection/retirement owner;
- Component Host and cancellation semantics; and
- the rule that only `WorkRuntime` publishes lifecycle events and terminal
  state.

A future overlay must distinguish `builtin_step`, `script_step`, and
`worker_step` execution shapes. Each may return only typed domain result/fact
candidates; none may mutate `WorkRun`, `WorkPlanSpec`, the Work Event Log, step
state, or final outcome.

Product overlays stabilize only after two materially different adopters prove
their owner mapping and canonical equivalence.

## Typed Event Extensions, Not Generic Hooks

Codex and Claude Code demonstrate real demand for lifecycle and tool-event
extensions, but the common SDK does not expose a generic `hooks` command map.
A future hook is an owner-versioned Extension contract for one named event and
declares:

- typed input and output plus whether it observes, gates, or transforms;
- ordering, timeout, cancellation, reentrancy, and failure policy;
- execution shape and exact authority/effect request; and
- generation, audit, redaction, and retirement behavior.

Data-only observers, Host-mediated model hooks, one-shot process hooks, and
brokered HTTP callbacks are distinct owner schemas. A URL, command string, or
environment-variable template is never itself an authority-bearing hook. Remote
or Executor-contributed hooks remain unsupported until publisher/source trust,
event timing, and exact callback targets have accepted contracts. This section
reserves a mapping discipline, not a V1 public Hook API or global event bus.

## Minimum Author Journeys

### Journey A: Native content-only Skill

```text
.loushang/skills/review/SKILL.md
loushang --list-skills
loushang skill show review
```

No Plugin Instance, manifest, code, installation, or Approval is introduced.

### Journey B: Native Skill with one managed script

```text
.loushang/skills/review/SKILL.md
.loushang/skills/review/skill.scripts.json
.loushang/skills/review/scripts/generate.py

loushang skill script validate review
loushang skill script run review generate --input request.json
```

The run prepares and displays one immutable `ResourceSnapshotRevision`, then
uses the production Policy, Approval, containment, ABI, and cleanup path. It
does not install or enable a Plugin. The command spelling remains proposed; the
no-hidden-snapshot and exact-identity semantics are normative.

### Journey C: Packaged Skill with one script

```text
loushang plugin validate . --target coding --format json
loushang plugin snapshot .
loushang plugin dev-run SNAPSHOT --skill review --script generate --input request.json
loushang plugin test . --conformance
loushang plugin pack . --output dist/
loushang plugin install dist/acme.review-1.0.0.lspkg --disabled
loushang plugin prepare acme.review
loushang plugin enable acme.review
loushang skill script run acme.review:review generate --input request.json
loushang plugin explain acme.review --format json
```

These are proposed command semantics, not a claim that every command is already
delivered. Every step prints the exact Product target and package revision it
validated, snapshotted, packed, installed, prepared, enabled, or invoked.

PLC8B-1 may require no explicit dependency preparation for a Product-supplied
standard-library runtime, but the status model remains compatible with PLC8B-2
package-owned environments.

### Journey D: Trusted Product built-in

The Product developer reuses one existing typed Tool/Provider definition plus
one Product build facade. Build output contains the inert canonical package
envelope and owner-specific Product build input. Runtime still performs normal
identity, preflight, Approval, admission, selection, publication, and
retirement. Journey D does not require a Worker.

## Client Command Semantics And Delivery

Command spelling remains a design input; ownership and effects are normative:

| Operation | Class | May execute author code? | Earliest complete slice |
| --- | --- | --- | --- |
| `skill show`, `skill script validate`, `plugin validate`, list/inspect | Pure read | No | Existing/L0, PLC8A for script metadata |
| `plugin snapshot` | Author Artifact write | No | PLC8A |
| `plugin dev-run SNAPSHOT ...` | Protected execution | Yes, after normal decisions | PLC8B-1 |
| `plugin test --conformance` | Pure checks plus explicit protected fixtures | Only when the requested fixture is an execution test | PLC8B-1 for script execution |
| `plugin pack` | Bounded author Artifact write | No third-party imports or hooks | PLC8C |
| `plugin install --disabled` | Management mutation | No | PLC8C |
| `plugin prepare`, `enable`, `update`, `rollback`, `remove` | Management mutation | Only through later explicit activation/action routes | PLC8C minimum adapters; full convergence PLC9C |
| `skill script run` | Protected action | Yes, exact one-shot route | PLC8B-1 |
| `plugin explain` | Read projection | No | Narrow views may appear earlier; cross-owner convergence PLC9C |

Unsupported commands return a stable `unsupported/not_delivered` result. They
must not fall back to a generic Shell command, legacy mutation flag, ambient
runtime, or partial state change.

`validate`, structural `pack`, and install-disabled do not create an Agent
Session, execute install/build hooks, or prepare dependencies. `snapshot` is
separate from `dev-run`; every content change creates a new immutable revision
and requires a fresh decision. Development execution uses the production
Policy, Approval, Sandbox, invocation ABI, result validation, and cleanup path.

Test fixtures are fake Product facets with no Host fallback. Missing fixtures
fail instead of resolving live filesystem, process, network, credentials, or
external services. There is no `--unsafe` or testing-only authority shortcut.

`--target current` resolves and prints a concrete tuple containing Product ID
and version, Plugin API contract, OS, architecture, and runtime availability. It
is never an unrecorded “whatever this machine accepts” compatibility wildcard.

Legacy `--install-package` and direct source/enable flags require one documented
and tested one-way migration/deprecation path to the subcommand control plane;
both interfaces do not remain permanent mutation authorities.

## Diagnostics And Availability

Listing separates four axes:

| Axis | Example values |
| --- | --- |
| Visibility/desired state | `visible_enabled`, `visible_disabled`, `shadowed`, `invalid` |
| Contribution effectiveness | `effective`, `partial`, `blocked_required`, `not_selected` |
| Runtime readiness | `not_required`, `prepared`, `runtime_missing`, `unsupported_platform`, `containment_unavailable` |
| Current/last invocation decision | `not_prepared`, `pending`, `allowed`, `denied`, `expired`, `revoked` |

An expired or previous denial is not permanent script unavailability. A prompt
that does not yet exist is not projected as `pending_approval`.

Stable diagnostics include code, source location, canonical JSON pointer,
Product target tuple, severity, remediation, exact executable-source/Skill/
script identity, runtime route, and redacted trust/authority/containment facts.
`explain` separates required, selected, and actually enforced containment and
shows execution, activation, and action decision/use records independently.

## Public SDK Shape And Versioning

The intended namespace split is narrow:

```text
loushang.plugin.authoring  # author specs and Product build facades
loushang.plugin.scripts    # invocation/result author contracts
loushang.plugin.testing    # fixtures and conformance helpers
loushang.plugin.worker     # generated domain adapters, only after PLC9B

loushang.coding.plugins    # feature-by-feature after owner proof
# no public loushang.work.plugins yet
```

Canonical reservations, Approval records, declaration builders, candidates,
management ledgers, owners, registrars, binders, Process Host, raw Sandbox, and
package-store writers remain internal. Public compatibility snapshots reject
accidental exports and signature drift.

Version axes are independent:

| Change | Version to change |
| --- | --- |
| Package content or release | Plugin package version and immutable revision |
| Skill script fields or ABI | `SkillScriptDeclaration` / invocation schema version |
| Product owner payload | Exact owner-schema version |
| Domain method contract | Domain service contract version |
| Framing/transport behavior | Worker wire-protocol version |
| Supported Product/platform/runtime tuple | Product compatibility declaration |
| Generator output semantics | SDK/compiler/generator identity and version |

A suffix such as `coding.index.v1` cannot stand in for all these axes.

## Configuration, Credentials, Presentation, And Mutable State

The author SDK projects the existing layered Configuration owner; it does not
create Plugin-local settings semantics. A concise, data-only `ConfigSpec` may
declare option type, title, description, default, requiredness, permitted
scope, redaction, and `live | next_session | restart_required` effect. The
compiler emits canonical configuration schema/default references, and the exact
destination owner remains the only validator and applier.

Credential requirements are not ordinary configuration values. An author may
declare a named credential requirement and preferred acquisition timing such as
`on_enable` or `on_first_use`; the Host stores only an opaque reference in
ordinary configuration and resolves a scope/actor/attempt/deadline/revocation-
bound handle through the credential owner. No SDK substitutes secret values
into Skill text, Hook commands, generic environment variables, logs, or
manifests.

Optional `PluginPresentationSpec` data may contain display name, descriptions,
icon references, supported Products/platforms, and documentation links. It is
presentation-only: it cannot declare capabilities, grant trust, select a
Product, trigger authentication, or change availability facts.

Mutable component data is not configuration and is never written inside an
immutable package or Resource snapshot. The common authoring SDK exposes no
global `plugin_data_dir`. A generated domain SDK may request one of four
owner-mediated classes—rebuildable cache, durable domain state, credential
reference, or business Artifact—and receives only a bounded facet or
attempt-scoped mount and lease. The exact Product/domain, credential, or Artifact
owner retains schema migration, quota, retention, export, deletion, and recovery
authority. Disable retains durable state; uninstall or artifact GC does not
delete it.

## Environment, Credentials, Logs, And Results

Managed processes and Workers start from an explicit allowlist, not
`os.environ` minus a denylist. Normal Approval, status, audit, explain, health,
error, log, and Artifact projections never contain environment values.

Credentials are opaque, scope/attempt/actor/deadline/revocation-bound handles or
narrow Product-owned facets. Secret materialization, if a Product supports it,
requires a separate decision and lease plus restricted result handling. Secrets
are not ordinary constructor parameters, environment defaults, log fields,
health payloads, errors, or normal Artifacts.

`PluginLog` provides bounded structured logging and structural redaction. It is
not proof that malicious host-equivalent or Worker code cannot transform and
exfiltrate a secret. Status and documentation must state the effective execution
boundary honestly.

## Complexity Budgets

| Scenario | Authoring budget |
| --- | --- |
| Native content-only Skill | One directory and `SKILL.md` |
| Native managed Skill script | One strict sidecar and one script; no Plugin manifest or runtime glue |
| Packaged Resource bundle | One canonical manifest plus content/declaration directories |
| Packaged managed Skill script | One Skill-owned declaration and one script; no runtime glue |
| Trusted Product Tool | Existing typed Tool definition plus one Product build entry |
| Product-embedded language server | One declarative definition with immutable Product runtime reference |
| Long-lived Worker | One generated domain interface implementation; no handwritten handshake or supervisor |

These budgets do not permit hidden authority. If a scenario cannot meet both
the author budget and the runtime gates, the facade remains experimental rather
than exposing internal APIs as a shortcut.

## What Must Not Be Simplified Away

The SDK must not permit:

- universal mutable `PluginContext` access;
- direct owner Registry or Graph publication;
- raw `subprocess` or Process Host access through public Plugin APIs;
- embedded source location, local path, manifest field, or arbitrary signature
  to imply trust;
- import or execution during validate, structural pack, install-disabled, list,
  inspect, Resource discovery, or explain;
- manifest permission requests to grant themselves;
- automatic inheritance of complete Host environment or credentials;
- Tool callables inside data-only Tool Pack declarations;
- plain annotations to infer injected authority;
- managed execution to reopen mutable script/runtime paths after Approval;
- a source locator to be reconstructed as a Host path outside its owning
  authority;
- a global writable Plugin data directory or artifact GC to delete durable
  component state;
- generic command/URL hooks that bypass exact event-owner schemas;
- Worker self-publication of Tools or effective generations;
- generic Worker reverse RPC into Host internals;
- silent switching between in-process and Worker execution;
- a Product overlay to create an owner or Registry; or
- public stable executable APIs before owner, adopter, compatibility, security,
  and lifecycle conformance.

## Delivery Sequence

| Slice | Authoring deliverable | Exit condition |
| --- | --- | --- |
| Gate A | Two-ingress Resource model, orthogonal placement axes, canonical-package boundary, exact owner inventory | No unresolved second manifest, source authority, compiler, registry, owner, management writer, or effective clock |
| PLC8A | L0 plus native-sidecar and packaged forms of experimental strict `SkillScriptDeclarationV1`, pure validation, availability, diagnostics, immutable Resource/package revisions | Non-executing operations cannot import or launch adjacent content; native managed execution creates no Plugin identity |
| PLC8B-1 | Product-supplied zero-dependency Python and `AuthorizedSkillScriptExecutor` | Verified launch, independent action Approval, required containment, bounded ABI, exact cleanup |
| PLC8B-2 | Immutable package-owned Python dependency environments | Environment identity and lease are package-bound and reproducible |
| PLC8B-3 | Explicit additional Product-resolved runtimes | No ambient PATH/runtime fallback |
| PLC8C | Stable data/one-shot author specs, canonical pack/install-disabled, minimum management/read adapters | One public journey with LSP/Base/Arch plus two materially different script adopters and cross-version fixtures |
| PLC9A | Isolated executable declaration evaluator | Third-party concise executable facade cannot import in Host; route is explicit |
| PLC9B | Session-owned generated Worker SDK candidate | Process-backed activation, two domains, Python plus one non-Python golden proof |
| Coding overlay milestones | Feature-by-feature exact-owner facade | Canonical/fingerprint parity with generic form and two adopters |
| Work overlay milestone | Separate accepted Work extension ARD | Work owner and lifecycle boundary proven; not implied by PLC8C |
| PLC9C | Full management, inventory, explain, operational-intent, and client convergence | `PluginManagementService` is sole mutation port; projections agree without a second clock |
| PLC9D | Distribution productization | Existing verified store, lock, retention, recovery, and GC owners remain authoritative |

The internal Product build facade is additionally gated by PLC6/PLC7 production
evidence, executable preflight, and at least two IR/engine compatibility
fixtures. Syntax simplicity alone does not make it stable.

No public symbol ships before its owner implementation, adopter evidence,
cross-version fixtures, migration/removal gate, and delivery slice have exited.

## Acceptance Gates

### Single-authority and inert-operation gates

- Exactly one runtime parser recognizes `plugin.json`; runtime/install code does
  not recognize an author shorthand.
- External-layout importers run only as offline authoring adapters; their output
  passes byte/fingerprint parity and runtime never parses the external manifest.
- Native Resource paths do not import Plugin declaration, management, Approval,
  or package lifecycle APIs and create no Plugin records.
- Install, list, inspect, validate, Resource discovery, explain, structural pack,
  and install-disabled do not import executable modules or run hooks/generators.
- Product-built packages contain a complete inert ContributionIndex before
  runtime preflight.
- Every runtime Definition receives a Host-created SourceGroup and matching
  reservations; no public constructor can mint or substitute them.
- Handwritten and generated canonical packages have byte/fingerprint parity;
  reordered input is deterministic and unknown/duplicate/ambiguous data fails
  closed.
- Public authoring/overlay imports cannot reach Registration constructors,
  Graph Binder, Approval writer, Process Host, Sandbox backend, package-store
  writer, management ledger, or live owner publication internals.

### Trust and built-in gates

- Spoofing Plugin ID, directory, metadata, `product_embedded`, or an untrusted
  signature never selects Product automatic policy.
- Installation/selection scope, placement, source authority, release provenance,
  execution trust, and execution shape remain independently explainable and
  cannot substitute for one another.
- Changing package/dependency digest, authority, owner, topology, Product build,
  Profile, policy revision, or revocation epoch invalidates prior evidence.
- Execution, activation, and action subjects cannot deserialize as or consume
  one another's records.
- Co-distribution alone cannot import, enable, admit, select, bind, or publish a
  contribution.
- Built-in and external fixtures traverse equivalent descriptor, declaration,
  admission, selection, inventory, publication, drain, and retirement shapes.
- In-process status always reports host-equivalent ambient authority; typed
  facets never claim Sandbox enforcement.

### Managed-script and legacy gates

- Native and packaged Skills with the same display/script IDs resolve to
  distinct exact executable-source identities; update, precedence, and stale
  aliases cannot cross-route them.
- Mutating, replacing, symlinking, or swapping script, interpreter, environment,
  cwd, or output root between decision and spawn fails before execution.
- PATH, shebang, wrapper, shell-string, and interpreter-flag substitution are
  structurally impossible or invalidate the subject.
- Required, selected, and actual containment remain distinct; required/degraded
  mismatch never spawns.
- JSON ABI tests cover absent/null, malformed UTF-8, duplicates, non-finite
  values, trailing data, empty success, oversize output, stderr flood, timeout,
  cancellation, and stable failure categories.
- CLI and model clients produce the same normalized invocation and exact
  executable-source/Skill/script identity.
- Project-local, user-global, installed, unknown, symlinked, wrapped, and
  PATH-resolved legacy scripts receive no authority from advisory provenance.
- Cancellation/crash at every use/start/run/result/cleanup boundary reaches one
  truthful durable terminal state and cannot reuse a decision.

### Worker gates

- Worker activation uses a versioned process-backed subject/use and cannot be
  coerced through the in-process activation arm.
- Required-containment Workers do not start under missing, disabled,
  best-effort, degraded, unresolved, or incomplete capability coverage.
- Forged service IDs, package digests, attempts, nonces, generations, schema
  versions, extra fields, oversized frames, duplicate replies, and retired
  replies fail before owner publication.
- Worker health/readiness/fingerprint cannot add service, authority, or
  contribution facts.
- Reverse calls expose only admitted typed facets and reauthorize exact attempt,
  generation, invocation, effect, target, deadline, and revocation facts.
- Worker process tree, streams, Sandbox, package/environment lease, route,
  publication, and cleanup settle on cancellation, revoke, Session close,
  crash, and protocol failure; incomplete termination is reported honestly.

### Client, SDK, and Product gates

- A native Skill works with one directory and no manifest or code.
- A native Skill with `skill.scripts.json` runs only from a Host-created
  immutable Resource snapshot and creates no Plugin Instance or desired state.
- A zero-dependency managed-script sample has one canonical manifest, one
  `SKILL.md`, one script, and no subprocess/Approval/Sandbox/Artifact/RPC/cleanup
  glue.
- A trusted built-in reuses existing Tool/Provider author objects and one
  Product build facade; Tool callables never appear in data-only Tool Packs.
- Any future injected parameter uses an explicit marker, is absent from model
  schema, exists in inert requirements, and cannot exceed Product authority.
- `dev-run` snapshots first and uses the production path; conformance fixtures
  have no live Host fallback.
- Every command declares whether it is a read, author Artifact write,
  management mutation, or protected execution and returns no-fallback
  `unsupported/not_delivered` when absent.
- Coding overlay executable resolution is immutable and PATH-independent; its
  canonical candidate equals the generic form.
- No Work overlay public import exists before its separate owner/lifecycle ARD.
- Configuration authoring compiles to the existing Configuration owner;
  credential requirements yield opaque references, and presentation metadata
  grants no capability or trust.
- Required contribution failure blocks new-Session selection; optional failure
  reports `partial` without a global Plugin publication transaction.
- Durable component data survives disable and artifact GC until a separate
  authorized deletion; no generated SDK exposes a universal data directory.
- Public API snapshots, documentation journeys, compatibility fixtures, and
  migration tests gate stability.

### Environment, credential, and Artifact gates

- Child environments start from an explicit allowlist; environment values do
  not enter normal status, audit, Approval, explain, or diagnostics.
- Credential handles are exact-scope, attempt, actor, deadline, lease, and
  revocation bound; raw secrets cannot enter normal logs/results/Artifacts.
- Artifact publication rejects escapes, links, devices, unstable post-exit
  content, excessive files/bytes, and unapproved media types.
- Product behavior distinguishes script failure, invalid result, Artifact
  rejection, partial workspace writes, cancellation, timeout, containment
  failure, and cleanup debt.

## Independent Review Disposition

| Review | Findings resolved in this revision |
| --- | --- |
| Security | Split build/import/evaluator phases; independent script action authority and verified launch; immutable Host trust root; project scope is not authorship; Worker activation/containment/callback bootstrap; honest facets, secrets, dev/test, provenance, and availability |
| Authoring | Exact package/Skill/script identity; one canonical manifest; ToolDefinition versus Tool Pack separation; deferred explicit injection; complete author journeys and typed ABI; domain-generated Worker surface; concrete L0 placement and version axes |
| Architecture | Two Resource ingress paths; authoring-only facade over existing reservation-bound runtime; separate execution/activation decisions and exact owners; immutable Coding runtime; deferred Work overlay; corrected PLC8/PLC9 sequencing and public namespace |

The review documents remain unchanged as historical findings. Closure here
means the revised proposal now contains the required rules and executable gates;
it does not claim that the underlying PLC8/PLC9 implementation already exists.

## Final Recommendation

The stable mental model should remain small:

```text
native Skill/Prompt
  -> native Resource convention

native Skill with managed script
  -> strict Resource-owner sidecar + immutable Resource snapshot
  -> authorized verified one-shot execution; no Plugin identity

packaged Resource or Skill with script
  -> canonical package + Skill-owned script declaration
  -> authorized verified one-shot execution

trusted Product built-in
  -> existing typed definitions + Product build facade
  -> emitted inert envelope + normal exact-owner runtime path

long-lived third-party service
  -> generated domain interface
  -> process-backed activation + required-containment Worker
```

The SDK absorbs formatting and protocol boilerplate. The Host retains explicit,
independent, recoverable authority over identity, desired state, Approval,
admission, selection, publication, execution, containment, and cleanup.
