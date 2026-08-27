# Independent Architecture Review: Client Plugin SDK And Embedded Authoring Experience

## Status

- Authority: descriptive — independent architecture validation evidence
- Artifact type: validation
- Reviewed design status: proposed
- Implementation status: not-applicable
- Owner: Loushang architecture review
- Review type: independent architecture and delivery review.
- Reviewed document:
  [Client Plugin SDK And Embedded Authoring Experience](../client-plugin-sdk-and-embedded-authoring-experience.md).
- Review scope: fixed owners, Capability/Graph authority, Resource Catalog,
  `PluginManagementService`, package lifecycle, `ExecService`/Process Host,
  Work/Coding Product boundaries, and PLC8/PLC9 sequencing.
- Source baseline inspected: current local source and live/accepted architecture
  in `/home/dev/lsspace/loushang` on 2026-08-26.
- Independence: this review did not consult another reviewer and did not modify
  the reviewed proposal.

## Verdict

**Revise before architecture acceptance.**

The authoring ladder is directionally correct and should be retained. In
particular, convention-only Resources, managed one-shot scripts, concise
trusted Product definitions, and generated Worker protocol adapters are the
right four usability levels. The proposal also correctly forbids a universal
mutable Plugin context, direct Registration/Graph publication, raw Process Host
access, import during discovery, and project-location-based trust.

The proposal is not yet safe to accept as an implementation contract because
two central diagrams/examples leave room for new runtime authorities:

1. the stated uniform path sends native convention-only Resources through
   canonical Plugin declaration IR, conflicting with the accepted one-Resource-
   catalog path where a plain `SKILL.md` has no Plugin manifest, instance, or
   declaration; and
2. the proposed manifest/decorator/compiler surface does not define the
   mandatory two-stage relation between the inert ContributionIndex and the
   reservation-bound `PluginDeclarationBuilder`. As written, it could become a
   second manifest parser, declaration compiler, or callable registry.

Those are P0 plan defects, not objections to a simple SDK. Both can be fixed by
making the facade an authoring-only projection onto existing strict inputs and
keeping every runtime transition under the current Host and exact-owner path.

After the P0 corrections, the remaining P1 findings should be resolved before
freezing any public executable SDK or Product overlay. No source-code change is
recommended until that contract is corrected.

## Evidence Baseline

The review used the following current evidence:

- The accepted architecture keeps typed Capability Provider/Consumer seams as
  runtime injection, the existing owners authoritative, one parser per
  manifest, and one exact Registration owner per live contribution
  ([UPA invariants](../../../harness/unified-plugin-architecture.md#non-negotiable-invariants)).
- Executable declarations must pass pure preflight before import, receive one
  source-group-owned gate and reservations, and finalize only through the
  Coordinator
  ([UPA preflight](../../../harness/unified-plugin-architecture.md#2-preflight-then-declare-once)).
- A native filesystem Skill remains an ordinary `<skill>/SKILL.md` without a
  Plugin manifest, entrypoint, install record, or activation decision
  ([Resource Catalog plan](../../../harness/resource-catalog-pluginization-plan.md#executive-decision)).
- Current `PluginManifestParser` is explicitly the canonical parser for one
  `plugin.json`, and parsing produces an inert descriptor
  ([manifest.py](../../../../../../src/loushang/harness/resources/plugins/manifest.py)).
- Current `PluginDeclarationBuilder` is internal, accepts a Host-created
  `PluginDeclarationSourceGroup`, verifies one package/preflight context, and
  consumes every exact reservation
  ([builder.py](../../../../../../src/loushang/harness/plugin_authoring/builder.py)).
- The production `coding.lsp.default` Definition receives that reservation-
  bound builder and emits inert symbol references instead of registering a live
  Provider
  ([definition.py](../../../../../../src/loushang/coding/_plugins/coding_lsp_default/definition.py)).
- The current authoring namespace deliberately exports no public SDK
  ([plugin_authoring/__init__.py](../../../../../../src/loushang/harness/plugin_authoring/__init__.py)).
- `PluginManagementService` is the implemented sole durable command authority
  over inert desired state
  ([service.py](../../../../../../src/loushang/harness/plugin_management/service.py)).
- Process Host exposes only an authorized launcher; Products own protocol and
  semantic behavior, while one-shot and hosted-process lifecycles remain
  distinct
  ([Process Hosting Boundary](../../../harness/process-hosting-boundary.md)).
- `loushang.work` is currently a compatibility namespace migrating to the
  product-neutral `harnesswork` kernel. Work owns lifecycle facts and is not the
  owner of Product Capability resolution or Product payloads
  ([Work architecture](../../../work/README.md)).
- The improvement plan deliberately sequences Skill-script contracts through
  PLC8, isolated evaluation and Session Worker through PLC9, and public
  executable exports only after multiple production shapes
  ([improvement plan](../plugin-management-and-isolated-execution-improvement-plan.md#integration-with-the-existing-plc-delivery-spine)).

## Findings

## P0 Findings

### P0-1: Uniform canonical runtime incorrectly includes native Resources in Plugin declaration IR

**Proposal evidence**

The proposal says every directory convention, manifest, Python builder, and
Worker adapter compiles into the same canonical declaration IR, then trust,
Approval, and owner admission. It later correctly says that an L0 native Skill
has no manifest and no per-Skill Plugin Instance. These statements cannot both
be the runtime contract.

**Conflict**

The accepted Resource architecture intentionally does not Plugin-wrap every
piece of native content. Native filesystem/user roots produce normalized
Resource source snapshots/candidates inside the single Resource Catalog.
Packaged `resource_item` contributions enter through Plugin declaration and
owner admission. Converging their final Resource projection does not mean that
both sources acquire Plugin identity, desired state, preflight, or package
lifecycle.

If the uniform diagram is implemented literally, one of these unwanted designs
results:

- a generated Plugin identity and instance per Skill/directory;
- a hidden manifest/declaration compiler in the Resource loader; or
- Plugin trust/Approval/install facts synthesized for native Resource content.

All three violate the one Catalog/no per-Skill Plugin decision.

**Required correction**

Replace “uniform canonical runtime” with “uniform exact-owner projection” and
show two distinct ingress paths:

```text
native Resource convention
  -> Resource source snapshot/candidate
  -> Resource-owner catalog admission/selection
  -> Resource generation

packaged Plugin Resource
  -> plugin.json + ContributionIndex
  -> Plugin declaration/preflight/finalize
  -> Resource-owner candidate/admission
  -> the same Resource generation
```

Only the second path has Plugin identity and package lifecycle. The convergence
point is the Resource-owner candidate/catalog contract, not
`PluginDeclaration`.

**Closure gate**

- A source and architecture test loads a native `SKILL.md` and proves that no
  Plugin manifest, Plugin instance, desired-state record, declaration batch,
  Approval subject, or package lease is created.
- A packaged Skill reaches the same Resource projection through an evidenced
  `resource_item` declaration.
- Model-input output is parity-checked while provenance truthfully distinguishes
  native source from packaged Plugin source.

### P0-2: The facade/compiler contract can become a second manifest and declaration authority

**Proposal evidence**

The L1 example introduces a TOML manifest and says it compiles to canonical
declaration IR. The L2 examples pass live Python callables to `Plugin` and ask a
“compiler” to derive contributions, IDs, schemas, requirements, and
fingerprints. The public namespace sketch also groups manifest, declarations,
and builders without distinguishing author input from runtime IR.

**Conflict**

The accepted runtime has a deliberately ordered security envelope:

```text
canonical plugin.json / ContributionIndex
  -> verified immutable package
  -> pure preflight and Approval lookup
  -> Host-created SourceGroup and one-use reservations
  -> document decoding OR approved Definition evaluation
  -> reservation-bound PluginDeclarationBuilder
  -> Coordinator finalize
  -> exact-owner admission/publication
```

The ContributionIndex must contain the facts needed to decide whether executable
declaration evaluation is permissible. A decorator cannot be imported to
discover those facts. The current builder cannot be replaced by a convenient
unbound builder: it deliberately requires a `PluginDeclarationSourceGroup` and
consumes matching reservations. The current LSP Definition demonstrates the
correct seam.

A second public TOML parser consumed by install/runtime, an auto-scanner that
imports modules to discover decorated callables, or a builder that mints
`PluginDeclaration` without Host reservations would each defeat this ordering.

**Required correction**

Define two explicitly different artifacts and compilers:

1. `AuthorPackageSpec` (name illustrative) is authoring-only. `validate` and
   `pack` may convert it into canonical package bytes containing the one
   `plugin.json`, complete ContributionIndex, and strict declaration documents
   or Definition locators. Runtime install/discovery never consumes this
   shorthand directly.
2. Runtime declaration compilation remains the existing reservation-bound
   operation. A trusted Definition/decorator is imported only after executable
   preflight and receives a Host-minted builder/context tied to one SourceGroup.
   It emits only strict IR matching the predeclared reservation closure.

For built-ins that avoid a handwritten manifest, the Product build must emit
the canonical manifest/index into the immutable co-distributed package. “No
handwritten manifest” must not mean “no inert security envelope.” Build tooling
may inspect trusted Product source in a controlled build step, but runtime must
validate the emitted bytes and never re-run build discovery as an authority.

The public SDK may export author-facing specs and owner-versioned payload
builders. It must not export unrestricted canonical `PluginDeclaration`
constructors, reservation constructors, the Coordinator, registrars, or a
function-discovery registry.

**Closure gate**

- Static architecture checks prove that install/list/inspect/validate parse only
  the canonical package format and never import author modules.
- The installed artifact contains a complete ContributionIndex before any
  executable preflight.
- Every executable Definition invocation receives a Host-created SourceGroup;
  no public constructor can mint or substitute reservations.
- Handwritten canonical package and author-shorthand-packaged forms produce the
  same canonical bytes/fingerprints.
- Changing a callable, generated declaration, or index changes the package
  identity and invalidates the previous preflight/Approval evidence.
- Unknown/extra/unconsumed contributions fail exactly as they do in the current
  Coordinator path.

## P1 Findings

### P1-1: Built-in convenience does not yet preserve the two Approval uses and independent selection/admission authorities

The proposal compresses Product co-distribution, allowlist, authority, Profile,
and policy into one “automatic recorded decision.” That presentation is too
coarse for executable built-ins.

At minimum, an executable in-process built-in crosses two independent gates:

- declaration-source evaluation/import, represented by the complete
  `PluginExecutionApprovalSubject`; and
- contribution activation, represented by the independent
  `ContributionActivationApprovalSubject` after exact-owner admission facts
  exist.

Product policy may arrange non-interactive positive decisions, but only the
Approval owner records/consumes them. The Product/OEM allowlist is an input
ceiling, not owner admission. The exact Capability owner remains final admission
authority, `ProductCapabilityProviderResolver` remains selection authority, and
the Graph Binder remains publication authority. Product default enablement must
also be expressed through the accepted Product Runtime Plan/Composition Set and
durable desired-state rules; a decorator cannot self-enable or mutate
`PluginManagementService` state.

**Required revision**

Expand the built-in diagram to show separate trust provenance, Product/OEM
selection ceiling, declaration-execution decision/use, exact-owner admission,
activation decision/use, Product selection, and publication. State whether a
co-distributed default is an initial desired-state record or a Product baseline
selection, and forbid a second “built-in registry” from becoming either.

**Gate**

- Built-in and external fixtures traverse the same descriptor, declaration,
  owner admission, selection, binding, inventory, and retirement shapes.
- Tests prove that co-distribution alone cannot import, enable, admit, or publish
  a contribution.
- Explain output shows the two decision/use records independently.

### P1-2: Typed signature injection and Product overlays need a closed owner mapping

The proposed `WorkspaceRead`/`PluginLog` signature is good author ergonomics,
but “the Product compiler and owner resolve the declared facets” is not precise
enough. Python annotations must not establish a second dependency-injection
container or infer authority. Each annotation must map to a closed,
owner-versioned facet or Product domain contract; existing Capability
requirements, owner admission, Product compilation, Provider selection, Graph
binding, and Consumer capture remain the only runtime resolution path.

The Work and Coding examples have the same issue at Product scale:

- The Work proposal names `loushang.work.plugins` and “Work step executor
  contributions,” but no accepted Work Plugin contribution/Component Host seam
  exists. `loushang.work` is currently a compatibility namespace migrating to
  product-neutral `harnesswork`; `WorkPlanSpec` is still a target. Publishing
  this overlay now would make a facade choose an owner before the domain has
  accepted one.
- Coding already has a concrete exact-owner route. Additional language servers
  are `coding.lsp` owner-schema components referencing an admitted external
  service, composed into one owner generation. The overlay must compile to that
  candidate; it cannot create a `language_services` registry or bind a second
  Graph.

**Required revision**

- Define an allowlisted annotation-to-contract table owned and versioned by the
  exact Tool/Capability/Product owner. Annotations emit inert requirement
  references; they do not cause runtime service lookup.
- Move the Work example to a future/non-committed section. Do not reserve
  `loushang.work.plugins` until the harnesswork migration, run-bound plan
  contract, Product work-preparer/executor boundary, contribution kind, exact
  owner, and Component Host are accepted and proven.
- Define the Coding overlay as sugar over existing `coding.lsp` component,
  Tool-pack, Resource-item, and Product composition contracts. It must have a
  byte/fingerprint equivalence test against the non-overlay form.
- Product overlays may narrow configuration and construct authoring specs; they
  may not admit, select, register, publish, or rewrite Product defaults after
  `ProductCompositionCompiler`.

**Gate**

- Import graphs reject Product overlay dependencies on Registry, Graph Binder,
  Approval issuance, Process Host, desired-state ledger, and owner publication
  internals.
- For each overlay feature, a table names the declaration kind, exact admission
  owner, selection owner, binding/publication owner, and retirement owner.
- Work conformance proves that only `WorkRuntime` publishes lifecycle events and
  a Plugin executor can return only domain result/fact candidates.

### P1-3: The Coding language-server example relies on ambient executable resolution

The Coding example uses `command=["pyright-langserver", "--stdio"]`. The
improvement plan explicitly requires Product registry resolution independent of
ambient `PATH`, and Process Host expects a fully materialized shell-free launch
request whose executable, cwd, and effective environment are frozen before
Policy.

The concise facade should instead declare a stable runtime/tool identity plus
arguments, for example:

```python
language_service(
    language="python",
    runtime="node.product.pyright@1",
    entrypoint="pyright-langserver",
    args=["--stdio"],
)
```

The exact names are not important. The important property is that the Product
runtime/toolchain registry resolves an immutable runtime/environment/executable
identity before activation Approval and launch. Authors never supply a raw
`PATH` lookup as canonical executable identity.

**Gate**

- PATH substitution and executable-shadowing tests fail closed.
- The launch fingerprint binds the resolved executable/runtime/environment,
  not only the author string.
- Unsupported runtime/platform is a validation/availability result and never a
  fallback to ambient shell behavior.

### P1-4: The delivery table publishes concepts before their prerequisites are available

The delivery table places “experimental manifest/builder codecs” in PLC8A,
suggests the internal built-in builder may develop earlier, and presents one
minimum workflow including `dev`, `install --disabled`, and `explain`. This
blurs four different readiness levels:

- PLC8A owns the Skill-script schema and non-executing validation/snapshot
  contract, not a general public Plugin compiler.
- Executing a managed Python script is unavailable until PLC8B-1.
- Canonical pack/install-disabled and stable data/one-shot authoring require
  PLC8C, including the staged package-publication/desired-state transaction.
- Full management/operator convergence and cross-projection explain remain
  PLC9C, although narrowly scoped adapters over already implemented commands may
  land earlier.

The built-in executable builder is also gated by PLC6/PLC7 production evidence,
two IR/engine compatibility fixtures, and the mandatory executable preflight;
it cannot be made “stable” merely because the syntax is concise.

**Required revision**

Replace the single minimum workflow with a capability matrix by delivery slice.
Separate `snapshot` creation from executable `dev-run`; make commands return
`unsupported/not_delivered` truthfully until their backend slice exists. Define
the exact minimal `PluginManagementService` adapter needed by PLC8C, without
claiming PLC9C operational convergence.

**Gate**

- No public import is added for a surface whose owner/adopter/conformance slice
  has not exited.
- Documentation tests prove each command's availability and no-fallback behavior
  at each feature level.
- PLC8C public exports contain only forms proven by LSP/Base/Arch plus two
  materially different Skill-script adopters and cross-version fixtures.

## P2 Findings

### P2-1: Managed-script identity is underspecified

The example uses `acme.review` as both apparent Plugin/package and Skill
identity. A package may contain multiple Skills and scripts. The authoritative
invocation should resolve an exact tuple such as package revision, Resource
identity, script ID, Product, Session, and invocation ID. Human-friendly aliases
may be accepted only as query input and must resolve to exactly one current
identity before Approval.

Add ambiguity/not-found/stale-revision diagnostics and show the fully resolved
identity in `explain` and audit.

### P2-2: Public namespace sketches should distinguish author types from internal runtime evidence

`loushang.plugin.manifest / declarations / builders` suggests that canonical
runtime records may become author contracts. The current public-looking
`resources.plugins` package already exposes many internal lifecycle types while
`plugin_authoring` intentionally exports none. The new SDK should avoid
stabilizing those internals accidentally.

Prefer a namespace distinction such as:

```text
loushang.plugin.authoring   # specs, validation diagnostics, test fixtures
loushang.plugin.scripts     # invocation/result author contracts
loushang.plugin.worker      # generated domain-service adapters, after PLC9B
```

Canonical reservations, decisions, candidates, ledgers, owners, binders, and
process contracts remain internal even if author types serialize into their
accepted wire representation.

### P2-3: Multi-language Worker SDKs are an outcome, not a PLC9B prerequisite

The proposal correctly requires more than an LSP-only proof, but four language
packages should not become an implied first-release commitment. PLC9B should
freeze a language-neutral protocol only after one second domain shape and at
least one non-Python interoperability fixture. Additional maintained SDKs can
then be separately versioned and staffed.

This preserves the architectural test without multiplying product-support
surface before the Worker protocol stabilizes.

## Required Owner And API Mapping

The revised proposal should include this mapping, or an equivalent one with
accepted type names:

| Author-facing concept | Author input only | Runtime compilation/admission | Exact live owner | Forbidden substitute |
| --- | --- | --- | --- | --- |
| Native `SKILL.md`/Prompt/Theme | Directory convention | Resource source snapshot and owner Catalog rules | Resource generation owner | Generated Plugin identity or per-Skill registry |
| Packaged Resource | Author package spec or canonical `plugin.json` | Canonical parser, ContributionIndex, declaration decoder, Resource-owner admission | Resource generation owner | Runtime TOML parser or package-local Resource registry |
| Managed Skill script | Owner-versioned Skill script metadata | Exact Skill/resource resolution, `AuthorizedSkillScriptExecutor`, `ExecService` | Resource/Skill action owner plus one-shot execution scope | Per-Skill Plugin Instance or direct subprocess |
| Built-in Tool pack | Product author spec plus inert symbol references | Reservation-bound declaration, Tool-owner admission and staged Registration | Exact Tool owner generation/`RegistrationScope` | Decorator registry registering callables at import |
| Capability Provider | Provider author spec | Eligibility, Product normalization, final owner admission, Product selection, Graph plan/bind | Capability owner and Graph Binder | Product overlay selecting/unilaterally publishing Provider |
| Capability component | Owner-schema author spec | Exact owner component resolver/admission | Exact Capability component generation | Global component/service registry |
| Coding language server | Coding overlay author spec | `coding.lsp` component referring to admitted external service; exact runtime resolution | `coding.lsp` owner generation | `language_services` registry or bare PATH command |
| Work executor | Future Product author spec only after separate acceptance | Product work preparer/executor resolves requirements before invoking Work | Work lifecycle remains `WorkRuntime`; future executor owner must be explicit | `loushang.work.plugins` mutating runs/events or resolving Graph |
| One-shot executable | Managed invocation spec | Authorized adapter over `ExecService` | One-shot execution scope | `keep_alive` Exec or Process Host access |
| Long-lived Worker | Domain service implementation | Exact Component Host plus internal Worker coordinator and authorized launcher | Exact domain owner; Process Host owns process mechanics | Worker self-registration or generic remote Plugin context |
| Install/enable/update/remove | Typed client command | `PluginManagementService` and existing package authorities | Management desired-state owner plus exact package owners | CLI/SDK materializing bytes or editing desired state |
| Built-in trust | Co-distribution and Product/OEM policy facts | Approval-owner decisions/uses plus exact-owner admission | Existing independent owners | Decorator, path, signature, or built-in registry granting trust |

## Required Sequencing Revision

The following sequence keeps the simple facade while respecting current
delivery dependencies.

### Gate A: Correct the authoring architecture before implementation

- Accept the two-ingress Resource diagram from P0-1.
- Define the author-package-spec to canonical-package build boundary.
- Freeze the rule that the runtime accepts only canonical package bytes and the
  existing reservation-bound declaration path.
- Inventory all current Product direct registrars/builders and assign each one
  exact migration owner.

Exit: no unresolved second manifest, compiler, registry, owner, or effective
clock.

### PLC8A: L0 and experimental L1 data contracts only

- Preserve native Resource conventions through the one Catalog.
- Add owner-versioned Skill-script metadata and strict codecs.
- Deliver pure validate, availability, diagnostics, and immutable snapshot
  creation without promising executable `dev`.
- Keep general Plugin/built-in/Worker SDK imports private.

Exit: discovery and all non-executing author commands cannot import or launch
adjacent content.

### PLC8B-1 through PLC8B-3: Managed one-shot execution

- Deliver one Product-managed Python runtime first.
- Add immutable per-package dependency environments second.
- Add only explicit, registry-resolved platform runtimes third.
- Expose the same typed invocation to human and model clients.

Exit: execution uses verified identities, required containment, Approval/use
records, bounded result/Artifact contracts, and exact cleanup.

### PLC8C: Data/one-shot public authoring and local package journey

- Stabilize author-facing package/resource/script specs, not unrestricted
  runtime IR constructors.
- Deliver canonical pack and `install --disabled` through the staged package-
  publication plus desired-state CAS transaction.
- Add the minimum read projections and management adapter needed for the local
  journey.
- Require LSP/Base/Arch and two materially different Skill-script adopters plus
  version compatibility fixtures.

Exit: one public path exists without a second parser, store, management writer,
or Resource registry.

### PLC9A: Untrusted executable declaration authoring

- Add the isolated evaluator source arm.
- Permit the concise Python facade for project/third-party executable packages
  only through that accepted evaluator.
- Keep evaluator and activation Approval uses distinct.

Exit: the same facade syntax cannot change its effective execution topology
silently; diagnostics report the chosen topology and reason.

### PLC9B: Worker SDK candidate

- Generate framing, lifecycle, cancellation, health, and typed adapters behind
  one exact Component Host.
- Prove at least two domain shapes and one cross-language interoperability
  fixture.
- Keep Worker V1 Session-owned.

Exit: handshake cannot publish, acquire owner authority, or outlive its Session;
old attempts cannot serve an active generation.

### Product overlay milestones

- Coding overlay may stabilize feature by feature only after each facade maps to
  an existing `coding.*` exact-owner path and matches its canonical fingerprint.
- Work overlay remains deferred until harnesswork migration and a separate Work
  Product-extension ARD define the Product executor owner and contribution
  contract. It is not implied by PLC8C.

### PLC9C and PLC9D: Operator and distribution closure

- Finish all client mutation adapters over `PluginManagementService` and keep
  query projections independent.
- Remove legacy direct registrars/mutation paths before declaring replacement
  SDK paths complete.
- Productize remote distribution only over the existing verified store, lock,
  retention, recovery, and GC owners.

## Executable Acceptance Gates

The revised plan should make the following checks mandatory:

### Single-authority architecture checks

- Exactly one runtime parser recognizes `plugin.json`; no runtime/install code
  recognizes an authoring shorthand such as `plugin.toml`.
- No L0 native Resource path imports Plugin declaration, management, Approval,
  or package-lifecycle APIs.
- Public authoring modules cannot import RegistrationScope constructors, Graph
  Binder, owner publisher, Approval writer, Process Host, Sandbox backend,
  package store writer, or desired-state ledger internals.
- Product overlays cannot import or mutate a live registry.
- Every public convenience construct maps to one canonical declaration kind or
  one native Resource source contract; unmapped constructs fail validation.

### Canonical equivalence checks

- Handwritten canonical packages and facade-generated packages produce
  byte-identical canonical documents and semantic fingerprints.
- Product-specific facade and generic author spec produce identical owner
  candidate fingerprints.
- Reordered inputs normalize deterministically; duplicate IDs, unknown fields,
  ambiguous facets, and unsupported owner schemas fail with stable diagnostics.

### Preflight and built-in checks

- Build-generated built-ins contain a complete inert ContributionIndex.
- No decorator/function module is imported during install, list, inspect,
  validate, Resource discovery, or pending/denied preflight.
- Co-distribution without current trust policy, declaration-execution decision,
  exact-owner admission, activation decision, Product selection, or current
  package identity cannot publish.
- In-process status always reports host-equivalent trust.

### Owner and lifecycle checks

- Tool/Command contributions are staged and retired only by exact owner
  generations; provider failure cannot leave early registrations.
- Resource refresh never rebuilds Plugin or foreign owner state.
- `PluginManagementService` is the only durable desired-state mutation port;
  authoring commands cannot install or enable by side effect.
- Worker and one-shot paths use their distinct accepted process lifecycles.
- Work executor fixtures cannot append lifecycle events or decide a Work terminal
  state directly.

### Delivery and compatibility checks

- A public symbol is absent until its delivery slice, owner implementation,
  real adopters, cross-version fixtures, and removal/migration gate are complete.
- Old direct Coding registration paths are removed only after canonical facade
  parity; there is no fallback on failure.
- Native Skills remain compatible without acquiring Plugin identity.
- Project-embedded and Product-embedded packages may share author syntax, but
  exact trust, execution topology, and Approval outcomes remain observably
  different.

## Final Recommendation

Retain the four-level usability goal, but define the SDK as a set of constrained
authoring projections rather than a new runtime framework:

```text
native content
  -> existing Resource source/catalog path

packaged data/scripts
  -> author spec (optional) -> canonical package bytes
  -> existing Plugin selection -> exact owner

trusted built-in code
  -> build-generated canonical envelope
  -> approved reservation-bound Definition
  -> exact owner

long-lived third-party code
  -> canonical envelope + isolated evaluation
  -> exact Component Host + Session Worker
  -> exact owner
```

With P0-1 and P0-2 corrected and the P1 gates incorporated, the proposal can
provide a substantially simpler client SDK without introducing a second
manifest, compiler, registry, management writer, Graph, or owner. Until then,
the document should remain a usability exploration rather than an accepted
delivery contract.
