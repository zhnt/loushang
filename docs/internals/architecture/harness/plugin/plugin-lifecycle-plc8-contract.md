# PLC8 Public Plugin SDK And Managed Skill Action Contract

## Status And Scope

- Contract type: implemented incremental contract under Plugin Architecture V2.
- Implementation status: review candidate on `harness/plugin-plc8`.
- Sole writers remain unchanged: Plugin package/declaration authorities own
  package facts, the Resource Catalog owns Skill selection and content facts,
  Approval/Policy own authorization, Process Host owns child processes, and
  Sandbox owns containment.
- This contract implements issue `#508`. It does not authorize MCP,
  marketplace, remote-service, Worker, or a second Plugin/Graph/Resource
  authority.
- The umbrella plan's Product build-facade bullet is not silently claimed by
  issue `#508`: PLC8 publishes independently selectable Plugin packages only.
  Embedded-without-Plugin-identity Product build projection remains an
  explicitly deferred PLC9/follow-up delivery.

## Stable Author Surface

`loushang.plugin` is the public author namespace. Its stable v1 surface is
data-only:

- `plugin_definition`, `PluginDefinitionBuilder`;
- `capability_requirement`, `capability_provider`;
- `resource.skill`, `skill_action`, `skill_action_effect`;
- `package`, `PluginPackageSpec`, `PluginPackageArtifact`; and
- `validate_package` plus immutable validation result/diagnostic records.

The surface contains no Graph, registry, registration scope, Approval store,
Sandbox, mutable `PluginContext`, Session, secrets, credentials, Product
service bag, or owner authority object. Provider requirements use the existing
canonical immutable `CapabilityRequirement`; public specs compile through the
existing private builder and declaration owners.

Executable provider symbols use a separate least-authority direct-import ABI,
`loushang.plugin.provider_runtime`. The Component Host admits that exact module,
not the `loushang.plugin` package prefix or a broad Harness Capability prefix.
It exposes only provider context, bundle/facet/dependency values, and factory /
disposer typing aliases. Definition authoring and provider execution therefore
remain distinct import surfaces. Exact-ABI imports must use an explicit,
non-wildcard `from loushang.plugin.provider_runtime import ...` list whose names
are all in the Host-owned export allowlist. A dotted plain import is rejected
because Python would otherwise bind the broad parent package into provider
globals and make sibling runtime modules reachable by attribute traversal.
This is a direct-import and API-compatibility boundary for trusted,
host-equivalent in-process code, not a Python object-capability sandbox.
Reflection through admitted Python class objects, their function globals, or
other language introspection remains ambient same-process authority; Plugins
that require isolation belong in a future contained execution model.

The supported stable package matrix is exact:

| Contract | Stable value |
| --- | --- |
| `manifestVersion` | `1` |
| `engine.apiVersion` | `1` |
| `engine.declarationIrVersion` | `2` |
| declaration document | `1` |
| managed Skill action document/declaration | `1` / `1` |

`engine.requiredFeatures` is a sorted exact set selected from the Host-known
feature catalog. The checked-in `sdk_v1_ir2` fixture is accepted. The
`sdk_v0_ir1` fixture is retained as an explicit incompatible-version fixture
and fails with manifest, engine API, and declaration IR diagnostics. Runtime
and public validation call the same engine negotiator: a manifest that claims
`manifestVersion` or `engine` fails closed on unknown versions, fields,
features, missing required features, or extra stable declarations. Legacy
internal manifests that claim neither field remain migration substrate, not
part of this stable author contract.

`managed-skill-action-v1` is closed over the Contribution Index rather than
inferred later from a mutable sidecar. A Skill reservation with actions carries
the exact `configuration.managedSkillActions: true` marker, so the shared
negotiator rejects both missing and extra known features in runtime parsing and
public validation. Admitted package input retains that marker. A stable package
whose sidecar and marker disagree, and a legacy package that attempts to
publish an action sidecar, both fail before Catalog publication.

## One Compiler And Inert Validation

`package(...)` emits the same canonical `plugin.json`, Contribution Index v2,
declaration IR v2, strict JSON bytes, and owner payloads used by production
synthetic, `coding.base`, `coding.lsp.default`, and `coding.arch.default`
packages. It does not create a parallel manifest or semantic IR.

`loushang-plugin validate PATH` is inert. It reads regular contained files,
negotiates exact engine features, decodes the existing Index and document IR,
checks exact reservation/document closure, Resource locators, `SKILL.md`,
`actions.json`, script locators, and script digests, and returns attributed
diagnostics. Every inspected file is captured through a bounded, regular-file,
no-follow reader; manifest bytes captured for validation are reused by the
runtime parser. It never imports a Definition or executes package code.

`loushang-plugin conformance PATH --approve-execution` is a separate,
developer-only, same-trust command. It first requires inert validation, then
requires the explicit flag before evaluating exact Definition source files and
checking entrypoint callability. It is not runtime admission, Plugin execution
Approval, isolation, or a security boundary; package activation continues to
use the existing durable decision/evaluator path.

## Skill Is One Catalog Resource

Every `SKILL.md` remains one `resource_item` with a directory locator.
`actions.json` is a versioned sidecar inside that same Skill directory; it does
not create a Plugin Instance, Capability, Tool registry, or second Resource
identity.

List, enable/status, lazy load, and refresh remain projections over the single
Resource Catalog. An exact `SkillCatalogSummary` carries Catalog generation,
snapshot fingerprint, candidate fingerprint, source revision reference, and
expected body digest. A lazy load returns a receipt for that same generation
and digest, and model-visible content retains the summary plus receipt.

During Resource source generation, native and admitted-package sources capture
the exact canonical action document and every digest-matching script. That
capture fingerprint enters the Resource candidate discovery fingerprint. The
effective `SkillCatalogConsumer` can then mint an opaque
`CatalogManagedSkillAction` for each captured action. Its private selection
binds generation, snapshot, candidate, Skill digest, action-document digest,
source kind, source revision, declaration, and copied script bytes. Public
constructors cannot mint either the selection or the action evidence. The Tool
layer consumes only that opaque record; it cannot supply a declaration or
source, import the private Catalog projection, list or enable a Skill, refresh
the Catalog, or mint replacement Catalog facts.
Each action additionally carries a Resource-owner identity and an
identity-bound seal over that exact evidence object. Every verification checks
the seal and a separate live Resource-owner registration against an
authority-owned primitive snapshot of the exact Catalog generation, snapshot,
candidate, source capture fingerprint, declaration, script bytes, and
Skill-root identity. The graph-owned `PreparedResourceOwnerGeneration`
atomically derives those facts, constructs the canonical consumer itself,
prepares a single-use binding in the action authority's external owner registry,
and consumes it for that exact projection before returning the consumer. Owner
provenance begins only when an exact factory-recorded Resource generation is
attached to an exact staging-factory `StagedResourceCompositionCandidate`.
Construction and subclassing remain ordinary Python compatibility surfaces,
but they do not mint authority: only the canonical staging functions record an
exact candidate, and only the exact prepared-generation factory records an
owner after deriving its binding fingerprint. The record also pins runtime id,
Catalog generation, binding fingerprint, the exact unpublished shadow, and its
snapshot, projection, source, runtime, binder, and lease facts. Sensitive owner
operations revalidate those facts, so field copying, later scalar mutation,
in-place action/capture mutation, or shadow replacement cannot turn a directly
constructed or retargeted object into owner evidence. The original frozen
action facts are carried into attachment enrollment and every later consumer
construction must match them exactly. The structural owner Protocol remains a
typing seam only and is never an admission check.

The exact attachment is recorded by a product-neutral Harness authority ledger
and produces an opaque, single-use receipt. This root ledger records only exact
candidate / generation object identity and receipt custody; it knows no Resource
Catalog snapshot, projection, status, action, or shadow field. Resource Catalog's
private authority separately pins its owner scalars, original cleanup shadow,
logical snapshot/projection/status copies, and immutable action facts. The
Capability composition core does not import or mutate Skill-action authority.
Resource Catalog generation, as the downstream owner of both concerns, consumes
the neutral receipt and its private frozen action facts into an unpublished
Skill-action `attachment_pending` enrollment; only successful
completion commits it as the root-owned lifecycle, while an exception cancels
the pending enrollment. The attachment transaction retains its separate,
single-use rollback receipt until enrollment commits; only the controlled
failure path may consume it to detach after cleanup succeeds. Cleanup remains cancellation
atomic and retains the exact candidate-to-owner custody until disposal succeeds;
retryable retirement debt therefore keeps a reachable cleanup handle instead
of detaching it. Cleanup uses the factory-recorded original shadow even if a
caller has attempted to retarget the owner. There is no owner registrar to
claim during module import and no function that accepts an arbitrary owner as
a new provenance root. The registries record owner provenance and
graph-owned/retired lifecycle state; no mutable registration dictionary lives
on the owner instance. No transferable grant, caller-provided snapshot, or
caller-provided consumer crosses that construction boundary. A structural
lookalike therefore cannot ask the authority to bootstrap a new owner
registration, even if it copies every projection/source field from a genuine
consumer. Direct consumer
construction remains available only for read-only projections with no managed
actions. The action authority does not import or callback the concrete Catalog
consumer. It retains only the primitive snapshot, opaque identity/capability,
and a semantically neutral liveness anchor; its snapshot is not a shallow
reference into mutable consumer state. Copying fields, recomputing fingerprints, using
`object.__new__`, self-signing a fresh seal, or copying another action's seal
cannot create acceptable evidence, and there is no module-level action mint
helper callable by an ordinary consumer. The unpublished shadow runner is
discovery/validation substrate only and exposes no parallel action authority.
The historical explicit eager-body compatibility path is not an action source
and is not a peer path for package/native managed actions; its final unrelated
adapter cleanup remains PLC9 work.

The Capability layer applies the same split to staged Resource candidates. The
neutral ledger records opaque exact identity, while a Capability-private ledger
pins the exact candidate state, binding, binder, selected profile, binding
context facts, implementation callbacks, binding lifecycle inputs, and
canonical Resource profiles. Attachment, graph claim, refresh, and
replacement revalidate those facts. A controlled final-profile selection updates
the private record only after proving identical Resource mechanisms. Copies and
mutated candidates therefore cannot launder a fresh authorized successor.
Cleanup repairs and uses the original externally recorded state, binder, binding,
registry, callbacks, and Resource shadow dependencies instead of trusting a
caller-reachable facade after provenance has failed. The private custody also
records whether binding cleanup has started, so a partial synchronous disposal
keeps its failed-entry retry queue and never re-disposes entries that already
succeeded. Candidate authority identities are minted and published only inline
in the two canonical staging paths; their shared record builder freezes facts
but cannot register an arbitrary caller-provided candidate. If post-bind sealing
fails, the unpublished binding is disposed and all partial ledger entries are
removed. If that disposal itself leaves retryable debt,
`ResourceCandidateSealingCleanupError` retains the exact binder/binding pair and
an idempotent `retry_cleanup()` handle until cleanup succeeds.
Replacement is an external-ledger, single-use transaction keyed by an opaque
token; copying its facade cannot replay commit or rollback after the original
facade resolves it. Token claim is lock-serialized before state mutation, so
copied facades cannot resolve the same transaction concurrently. Reservation
rechecks the exact current owner generation under that same lock; a concurrent
begin that captured a stale generation therefore cannot skip the generation
installed by the winning transaction.

## Managed Action Declaration And Execution

Action documents are canonical strict JSON with exact fields. Each action binds
an id, contained script locator and SHA-256, runtime family (`python` or
`posix`), fixed argv, cwd policy (`skill` or `workspace`), sorted non-secret
environment literals, sorted declared effects, and `containment: required`.
Environment values are an author-declared, non-secret precondition rather than
a content-classification promise: validation cannot infer whether an arbitrary
literal is a credential. Secret lookup, reference resolution, and credential
injection are not PLC8 author SDK features.

Native sources copy exact script bytes at Catalog capture. Package sources read
them only through a live verified revision handle during source generation,
then retain copied bytes plus the package content digest; Tool binding never
reopens an author-selected path. Binding verifies the opaque Resource-owner
record and fingerprints all action, Catalog, source, and content facts.

The Host chooses and fingerprints the exact runtime executable through the
Process substrate's single bounded, no-follow, stat-before/after streaming
digest primitive. Verification and immutable capture use that same primitive;
no Tool-layer `read_bytes()` path can allocate the complete runtime. Before
Approval, Process copies those revalidated bytes into a bounded anonymous Linux
file, applies kernel write/grow/shrink seals, and retains its descriptor through
spawn. The admitted Bubblewrap backend mounts that exact descriptor read-only
over the approved executable path. The child therefore
executes the digest-bound immutable image even if the original path changes
after Approval or queues a replacement immediately before spawn. Hosts without
an accepted immutable executable mechanism fail closed. Script bytes cross
stdin (`python -` or `sh -s --`) so mutable script paths are never re-opened by
the child. The immutable executable's exact logical path, digest, size, and
owner-sealed descriptor identity enter the Process authorization fingerprint
alongside cwd, environment, argv, effects, source facts, and binding digest.
The Catalog action and Skill-root identity are revalidated after Approval at
the final Process-owner start boundary. For `cwdPolicy: skill`, Process also
retains an open directory descriptor and Bubblewrap mounts that exact directory
read-only with `--ro-bind-fd` before `chdir`; a late path replacement therefore
cannot redirect the child between validation and spawn.

Managed actions require both:

1. the exact Process-owner `ScopeBoundProcessLauncher` private managed-start
   path configured for mandatory Approval; and
2. a containment planner whose requirement is exactly `required`.

Managed-start authority additionally requires an active required Sandbox
binding whose selected backend was admitted by the Harness-owned backend
registry and whose independent feature probe confirms both `--ro-bind-data`
and `--ro-bind-fd`. Missing managed-bind features remove only managed-start
authority; the backend remains available for ordinary Sandbox execution after
its namespace probe succeeds. A public custom registry cannot self-declare
managed-process trust.
Each plan is sealed to its planner and checked before Process Host receives it;
a structural object that merely reports `requirement = "required"` or returns
a raw no-op plan cannot acquire managed authority. The Sandbox composition
seam passes a private token and plan verifier into the Process Tool, which
depends only on its neutral containment port and never imports a Sandbox
concrete. Disabled, best-effort, and untrusted-custom Sandbox runtimes retain
their ordinary process launcher, but it carries no managed-start capability.

An ordinary allow or absent policy becomes an explicit Approval request; deny
and ask remain deny and ask. Weak/best-effort containment fails before process
start. The public four-field `ProcessLaunchRequest` remains unchanged; managed
effects and authorization metadata live only in a private Process-tool
envelope. Process Host, Approval, Policy, effects, execution profile, and
Sandbox remain their existing exact owners.

Stdin writing, stdout draining, streamed-stderr draining, and process waiting
begin concurrently. Both output streams use ProcessHost-compatible 64 KiB
reads through EOF. Each stream has a 1 MiB accumulated limit; overflow,
cancellation, or any pipe failure cancels sibling tasks, terminates the child,
and closes the owned process. This prevents a POSIX shell that emits early
output while a near-limit script is still entering stdin from deadlocking the
parent. Non-zero process exits are returned as action results, not confused
with hosting failure.

Native source capture uses the same bounded descriptor-relative no-follow
reader as stable package validation. Every ancestor directory and the final
regular file are opened relative to the trusted root descriptor; post-read
identity, size, mtime, and ctime are rechecked. Replacing an ancestor with a
symlink during capture cannot redirect action or script bytes outside the
Resource root. The portable fallback repeats link/reparse and identity checks
before and after the read.

## Exit Evidence

- Public SDK tests freeze exports, immutable specs, canonical compilation,
  stable/incompatible version fixtures, inert validation, and explicitly gated
  conformance execution.
- Production Base, LSP, and Arch manifests validate against the stable engine
  contract; LSP and Arch Definitions use only `loushang.plugin` author helpers.
- Resource tests prove native and package sources capture action bytes before
  the owner-built consumer mints opaque action evidence, caller-built captures
  and consumers cannot acquire action authority, and retiring/disposed owners
  cannot construct a replacement, while lazy body receipts retain
  generation/revision/digest identity.
- Action tests prove caller-forged evidence and launchers are rejected, exact
  Approval metadata and required containment are enforced, runtime replacement
  during Approval still executes the approved sealed image, Skill-root
  replacement fails before spawn, and real ProcessHost execution drains large
  stdout/stderr while large stdin is still writing, preserves non-zero exit,
  and terminates output overflow.
- PLC9 cannot start until architecture, correctness/security, and Product/test
  reviewers pass this slice and re-review every blocking fix.
