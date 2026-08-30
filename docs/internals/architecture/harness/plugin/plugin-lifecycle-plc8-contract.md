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
compatibility parsers used for older internal packages are migration substrate,
not part of this stable author contract.

## One Compiler And Inert Validation

`package(...)` emits the same canonical `plugin.json`, Contribution Index v2,
declaration IR v2, strict JSON bytes, and owner payloads used by production
synthetic, `coding.base`, `coding.lsp.default`, and `coding.arch.default`
packages. It does not create a parallel manifest or semantic IR.

`loushang-plugin validate PATH` is inert. It reads regular contained files,
negotiates exact engine features, decodes the existing Index and document IR,
checks reservations, Resource locators, `SKILL.md`, `actions.json`, script
locators, and script digests, and returns attributed diagnostics. It never
imports a Definition or executes package code.

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

For action execution the Resource owner mints a
`SkillActionCatalogSelection` from the exact summary. It binds generation,
snapshot, candidate, Skill digest, source kind, and source revision. The Tool
layer may consume that record but cannot import the private Catalog projection,
list or enable a Skill, refresh the Catalog, or mint replacement Catalog facts.
The historical explicit eager-body compatibility path is not an action source
and is not a peer path for package/native managed actions; its final unrelated
adapter cleanup remains PLC9 work.

## Managed Action Declaration And Execution

Action documents are canonical strict JSON with exact fields. Each action binds
an id, contained script locator and SHA-256, runtime family (`python` or
`posix`), fixed argv, cwd policy (`skill` or `workspace`), sorted non-secret
environment literals, sorted declared effects, and `containment: required`.
Static environment values must not contain credentials; secret resolution is
not an author SDK feature.

Native sources copy exact script bytes at Catalog capture. Package sources hold
a live verified revision handle and package content digest. Binding requires
the source kind, revision, and Skill content digest to match the Resource-owner
Catalog selection, revalidates the script digest, and fingerprints all action,
Catalog, source, and content facts.

The Host chooses and fingerprints the exact runtime executable. Immediately
before launch it revalidates the runtime and script bytes. Script bytes cross
stdin (`python -` or `sh -s --`) so mutable script paths are never re-opened by
the child. Cwd, environment, argv, effects, source facts, and binding digest
enter the existing Process authorization fingerprint.

Managed actions require both:

1. a `ScopeBoundProcessLauncher` configured for mandatory Approval; and
2. a containment planner whose requirement is exactly `required`.

An ordinary allow or absent policy becomes an explicit Approval request; deny
and ask remain deny and ask. Weak/best-effort containment fails before process
start. The public four-field `ProcessLaunchRequest` remains unchanged; managed
effects and authorization metadata live only in a private Process-tool
envelope. Process Host, Approval, Policy, effects, execution profile, and
Sandbox remain their existing exact owners.

## Exit Evidence

- Public SDK tests freeze exports, immutable specs, canonical compilation,
  stable/incompatible version fixtures, inert validation, and explicitly gated
  conformance execution.
- Production Base, LSP, and Arch manifests validate against the stable engine
  contract; LSP and Arch Definitions use only `loushang.plugin` author helpers.
- Resource tests prove the Catalog summary mints exact action-selection facts
  and lazy body receipts retain generation/revision/digest identity.
- Native and package action tests prove copied or verified revision bytes,
  Catalog mismatch rejection, exact Approval metadata, required-containment
  rejection before start, runtime/script digest checks, and Process-hosted
  execution.
- PLC9 cannot start until architecture, correctness/security, and Product/test
  reviewers pass this slice and re-review every blocking fix.
