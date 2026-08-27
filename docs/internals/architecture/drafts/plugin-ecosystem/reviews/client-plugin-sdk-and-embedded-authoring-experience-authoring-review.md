# Client Plugin SDK And Embedded Authoring Experience: Independent Authoring Review

## Status

- Authority: descriptive — independent author-experience validation evidence
- Artifact type: validation
- Reviewed design status: proposed
- Implementation status: not-applicable
- Owner: Loushang architecture review

## Review Scope And Method

This is an independent review of
[`client-plugin-sdk-and-embedded-authoring-experience.md`](../client-plugin-sdk-and-embedded-authoring-experience.md)
from the Plugin/Skill author's point of view. It focuses on API minimality,
learning curve, directory and manifest conventions, built-in authoring, typed
injection, managed-script I/O, CLI development flow, Work/Coding overlays, and
the cross-language Worker SDK.

The review checked the proposal against current source and delivery plans. It
did not use another review as evidence, and it does not review an implementation
that does not yet exist.

## Verdict

**Conditionally reject the document as an SDK-shape freeze; accept its
authoring ladder and simplicity objective as the direction of travel.**

The proposed L0/L1 split is strong: a plain Skill remains one directory, and a
script remains a one-shot program rather than being forced into a Worker. The
proposal is also right to hide Approval, Sandbox, process, generation, lease,
and cleanup mechanics from ordinary authors.

Built-in and embedded authoring is not yet demonstrably simple or internally
consistent, however. Three plan-level blockers remain:

1. the Python builder is said to derive the inert identity/authority envelope,
   but that envelope must exist before executable definition code may be
   imported;
2. managed scripts are declared at package scope but invoked through a Skill
   identity, leaving the authoritative `{package, skill, script}` identity
   undefined; and
3. the built-in examples conflate executable Tool definitions with the existing
   data-only `tool_pack` contribution and introduce signature-based facet
   injection that conflicts with today's Tool authoring contract.

These are fixable without making the common path verbose. The correction is to
make the compiler boundary and its outputs explicit, give scripts one exact
Resource-owner identity, and layer the convenience API over existing owner
types instead of inventing a single polymorphic `Plugin` object.

## Source-Backed Baseline

| Evidence | Authoring consequence |
| --- | --- |
| `src/loushang/harness/plugin_authoring/__init__.py:1-3` exports nothing and explicitly labels the package internal. | No current public Plugin SDK exists; every proposed public name remains a design candidate. |
| `src/loushang/harness/plugin_authoring/builder.py:31-81` constructs `PluginDeclarationBuilder` from a pre-existing `PluginDeclarationSourceGroup` and its reservations. | A builder cannot discover its own contribution IDs, owners, execution model, or authorities at runtime; those inert reservations precede evaluation. |
| `src/loushang/coding/_plugins/coding_lsp_default/plugin.json:4-40` carries the contribution index, owner, execution model, source, and requested authorities before `definition.py` is evaluated. | The first real adopter confirms that preflight metadata must be packaged as data. |
| `src/loushang/coding/_plugins/coding_lsp_default/definition.py:37-60` must manually translate the reserved contribution into the internal builder today. | A façade is justified, but it must preserve the prior reservation rather than replace it with runtime introspection. |
| `src/loushang/harness/resources/plugins/declarations.py:220-265` permits authorities only on the in-process Capability Provider arm; Resource, Tool Pack, and Command Pack contributions are data-only and request no authorities. | A callable Tool list is not the existing canonical `tool_pack` payload. |
| `src/loushang/harness/plugin_authoring/consumer_pack.py:325-345` defines Tool Pack as a catalog-backed Consumer declaration. | `tool_pack([callables])` would freeze a second meaning for Tool Pack unless an owner-specific compile step separates Tool definitions from their pack references. |
| `src/loushang/harness/tools/authoring.py:89-102,224-262` recognizes one explicit `ToolContext` parameter and otherwise builds Tools through `direct_tool` or `authorized_tool`. | Arbitrary annotation-based facet injection is neither current behavior nor a compatible cosmetic wrapper. |
| `docs/internals/architecture/harness/tool-authoring-guide.md:35-90` makes the direct-versus-authorized execution route explicit and keeps protected effects behind an action adapter. | A new Plugin façade must reuse this choice, not make a Tool trusted merely because it is built in. |
| `src/loushang/harness/resources/types.py:101-127` has a Skill descriptor but no managed-script field, while `src/loushang/harness/resources/_descriptor_parsing.py:74-128` parses only current Skill metadata. | `SkillScriptDeclarationV1` is genuinely new Resource-owner schema, not a manifest-only alias over current fields. |
| `src/loushang/harness/resources/_loader_discovery.py:309-317` and `_loader_discovery_filesystem.py:129-177` discover native Skills below a supported `skills/` root and stop recursion at the first `SKILL.md`. | Documentation must show a real supported root and define where adjacent scripts belong; an arbitrary `review/SKILL.md` is not by itself a complete placement contract. |
| `src/loushang/harness/resources/plugins/manifest.py:32-77` currently parses `plugin.json`, while `src/loushang/harness/resources/packages/manifest.py:178-183` separately recognizes `loushang-package.json` and `plugin.json`. | A TOML authoring source may be useful, but runtime support for another peer manifest would deepen an existing naming/codec split. |
| `src/loushang/harness/cli/profile.py:236-256` currently exposes legacy list/toggle/source/package flags, not the proposed authoring subcommands. | `plugin validate/dev/test/pack/install/explain` is a migration and command-ownership design, not a small syntax addition. |
| `docs/internals/architecture/harness/plugin-lifecycle-coding-pluginization-plan.md:19-41` reports the LSP vertical path implemented but PLC6-PLC9 and the public SDK unimplemented. | Examples must remain explicitly experimental until more than LSP proves them. |
| `docs/internals/architecture/harness/plugin-authoring-primitives-delivery-plan.md:73-125` already sketches a Provider-specific target API and preserves explicit Capability requirements. | The new façade should reconcile with this earlier target rather than publish a competing generic `Plugin(tools=...)` model. |
| `docs/internals/architecture/drafts/plugin-ecosystem/plugin-management-and-isolated-execution-improvement-plan.md:723-763,794-877` orders inert metadata, experimental Skill scripts, conformance, and only later stabilization. | The proposed author journey is correctly placed in PLC8, but stable examples need the same versioned experimental status. |

## P0 Findings

### P0-1: The built-in builder has an unresolved preflight/compiler cycle

The proposal says a built-in can omit a handwritten manifest and that the
compiler derives strict contributions, IDs, schema, fingerprints, requirements,
and compatibility diagnostics from this executable form:

```python
@builtin("coding.base", version="1")
def plugin() -> Plugin:
    return Plugin(...)
```

At runtime, importing that function in order to discover its authorities would
violate the same proposal's no-import-before-decision rule. The implemented
builder cannot solve this: it is created only after an inert contribution index
has already produced a reservation-bound source group.

The document needs to distinguish two compilers:

- a **trusted Product build compiler**, which may evaluate first-party build
  declarations in the Product build environment and emits packaged inert
  metadata; and
- a **runtime declaration evaluator**, which may execute only the exact
  predeclared source after trust, Approval, and preflight have accepted the
  already-packaged envelope.

The build result must contain, before runtime discovery:

- canonical package identity/version metadata;
- a complete contribution index with IDs, owners, execution models,
  authorities, source descriptors, and required/optional flags;
- data-only declaration documents where possible; and
- exact executable symbol locators only where execution is required.

For third-party packages, `pack` must not silently import arbitrary author code
to infer this envelope. Either authors provide declarative source metadata, or
they explicitly run a local code generator and `pack` validates its inert
output. Product-built code may use the trusted build compiler because its trust
derives from the Product build pipeline, not from being found at runtime.

Until that distinction is normative, “no handwritten manifest” is not a
complete implementation path and risks creating import-on-discovery.

### P0-2: Managed-script ownership and invocation identity disagree

The manifest sketch declares `[[scripts]]` at package scope, but both the CLI
and model action call it a Skill script and pass `acme.review` in the `skill`
position. `acme.review` was introduced as the Plugin ID, not a Skill ID. A
single package may contain several Skills, and different packages may expose
the same logical Skill name under Resource precedence.

The contract must choose one of two shapes:

1. **Skill-owned script:** the normalized identity is
   `{package_revision, skill_resource_id, script_id}`; metadata is attached to
   one declared Skill; invocation resolves the exact active Skill candidate and
   its revision; or
2. **Package-owned command:** the identity is `{package_revision, command_id}`
   and the public surface is `plugin command run`, not `skill script run`.

The current PLC8 plan explicitly names `SkillScriptDeclarationV1` and an exact
Skill/script identity, so option 1 is the consistent default. The authoring
source may remain concise, but it must normalize to a declaration resembling:

```text
skill: review
  path: skills/review/SKILL.md
  scripts:
    - id: generate
      entrypoint: scripts/generate.py
```

Installed invocation should accept a Resource-catalog-qualified Skill reference,
not reinterpret a Plugin ID as a Skill ID. Development invocation must also
name the local Skill when a source contains more than one:

```text
loushang plugin dev PATH --skill review --script generate --input request.json
loushang skill script run acme.review:review generate --input request.json
```

The exact delimiter is not important; the three-part identity and its
resolution semantics are.

### P0-3: The L2 examples freeze the wrong Tool and injection abstraction

The examples use both `tool_pack(..., [read_file, search_files])` and
`Plugin.builtin(..., tools=[read_file, search_files])`. In the current canonical
model, a Tool Pack is a data-only Consumer over Tool catalog item identities.
It is not a collection of executable callables. The examples therefore hide a
material owner crossing behind a pleasant-looking list.

The annotation example has a second incompatibility:

```python
@tool("coding.analyze")
async def analyze(request, workspace: WorkspaceRead, log: PluginLog): ...
```

Today's Tool authoring treats ordinary function parameters as model input and
recognizes one explicit `ToolContext`. Inferring every known class annotation as
injected authority would make schema generation dependent on imports, permit
ambiguous model-versus-Host parameters, and try to discover authority after
code execution.

The façade must preserve three distinct authoring objects:

- an executable `ToolDefinition`, built through the existing `direct_tool` or
  `authorized_tool` decision;
- an owner-stage/build input by which a trusted Product makes those definitions
  available to its Tool catalog; and
- a canonical data-only Tool Pack contribution that references exact Tool item
  IDs and Capability requirements.

If typed parameter injection is retained as an ergonomic option, it must use an
explicit marker such as `Injected[WorkspaceRead]`, be excluded deterministically
from the model schema, compile its requirement into inert metadata before
runtime import, and resolve only through a Product-owned adapter. Plain type
annotations must not silently grant or request facets. The simpler first public
version is to keep `ToolContext`/typed Provider context and defer parameter-level
injection until two real adopters prove it.

The document should also change “stateless Tool functions are owned by their
exact Tool pack generation.” Tool definitions are owned by the Tool owner;
Tool Pack generations select/consume those definitions. A pack cannot acquire
execution ownership merely because a builder accepted a callable.

## P1 Findings

### P1-1: Choose one author manifest source and one runtime canonical form

The TOML example is readable, but the current source of truth is `plugin.json`,
and package discovery already has a second `loushang-package.json` path. Calling
TOML “illustrative” does not prevent examples, templates, and third-party code
from making it a de facto contract.

Before publishing a template, decide one of these models:

- keep `plugin.json` as both author and canonical runtime source, with a schema
  and generator to remove verbosity; or
- introduce a clearly named author-only source such as `plugin.authoring.toml`
  that `pack` deterministically compiles into canonical `plugin.json` plus
  declarations, while runtime discovery never parses the author file.

Do not make TOML and JSON peer runtime authorities. `validate` should report
both the source location and the generated canonical JSON pointer when a
compiler is involved.

### P1-2: The CLI journey omits the executable middle and mixes offline and live work

The command list shows validate, dev, test, pack, install-disabled, and explain,
but the acceptance gate additionally requires prepare, enable, invoke, update,
and rollback. A new author cannot follow the displayed sequence from package to
working script. `dev` and `test` also have underspecified behavior: whether they
execute code, create a Session, watch files, select a Product, or persist state
is unclear.

Define command ownership before adding argparse spellings:

- `validate` and structural `pack` are offline authoring operations and must not
  construct an Agent session or import package code;
- `dev ... --script ...` is an explicit execution operation over an ephemeral
  immutable snapshot and may request normal Approval;
- `test --conformance` validates fixtures through the same route and grants no
  testing-only authority;
- `install --disabled`, `prepare`, `enable`, `update`, and `rollback` are
  management mutations; and
- `explain` is a read projection.

The current CLI still exposes resource/package/source flags. The plan should
name the one-way compatibility and deprecation path so that users do not learn
both `--install-package` and `plugin install` as permanent interfaces.

`--target current` should resolve to and print a concrete tuple containing
Product ID/version, Plugin API contract, OS, architecture, and runtime
availability. It must not mean “whatever this machine happens to accept” in a
packaged compatibility claim.

### P1-3: “JSON in, JSON out” is not yet a typed managed-script ABI

The proposed defaults correctly reserve stdout for the result and stderr for
bounded diagnostics, but `input = "json"` and `output = "json"` specify an
encoding, not a schema. The model action is described as typed even though no
input/result schema, version, or compatibility rule exists.

V1 should define:

- absent input versus JSON `null`;
- one complete UTF-8 JSON value, maximum bytes, duplicate-key and non-finite
  number handling, trailing data, and newline behavior;
- an optional versioned JSON Schema reference or generated schema fingerprint;
- exact behavior for empty stdout on success;
- progress/log output only on stderr or a separate Host channel;
- result media type and maximum bytes before the process starts;
- Artifact descriptor/result structure independent from stdout business data;
  and
- stable exit/result categories without exposing raw platform exit details as
  the only diagnostic.

Use one vocabulary for profile IDs. The draft uses `workspace-read`, while the
delivery plan uses `compute_only` and read-only workspace profiles. Canonical
IDs should not vary between hyphenated manifest strings, Python enums, CLI
output, and Approval evidence.

### P1-4: Work and Coding overlays expose attractive but unproved meta-DSLs

The class-decorator examples are likely to be copied even though they are
labelled illustrative.

For Work, `step_executor("collect", collect)` does not reveal whether `collect`
is a trusted in-process callable, a managed script, or a Worker operation. Those
forms have materially different admission and cancellation semantics. A public
overlay should make the execution shape explicit, for example separate
`builtin_step`, `script_step`, and `worker_step` constructors, while all return
typed candidates to the Work owner.

For Coding, `language_service(command=[...])` looks like a raw PATH-based
subprocess declaration. Current LSP construction resolves definitions and uses
an authorized launcher; the SDK should require a Product-resolved toolchain or
runtime reference, explicit server protocol/schema, workspace authority, and
containment requirements. The convenience layer may render that as one short
declaration, but `command` alone is not the authority-bearing contract.

Ship overlays only after each Product has two dissimilar adopters. Before then,
document ordinary common builders plus private Product helpers; do not publish
`@work_plugin` and `@coding_plugin` as a stable class metaprogramming style.

### P1-5: Worker authoring should be domain-generated, not generic-string-first

Hiding framing, handshake, cancellation, and shutdown is correct. The example
nevertheless starts from `@service("coding.index.v1")` and a generic `serve()`,
which risks freezing a generic RPC framework instead of a Product-owned domain
contract.

The stable author surface should import a generated or hand-maintained domain
interface package:

```python
from loushang_plugin_sdk.coding_index_v1 import CodingIndexService, serve


class PythonIndexer(CodingIndexService):
    ...


if __name__ == "__main__":
    serve(PythonIndexer())
```

The service contract version, Worker transport protocol version, and Plugin
package version must be independent. `serve` owns stdout completely; ordinary
printing to stdout should fail a conformance test or be redirected to bounded
diagnostics. A `__main__` guard avoids presenting import-time server startup as
the normal Python shape.

Do not promise four production-quality language SDKs in the first public
release. Freeze the language-neutral wire schema only after Python and one
non-Python implementation pass the same golden protocol suite across at least
two domain shapes, including streaming/cancellation. Additional language SDKs
can then be generated without making all four a PLC9B prerequisite.

## P2 Findings

### P2-1: L0 examples need concrete placement and supported-kind truth

Show the default native path explicitly, for example
`.loushang/skills/review/SKILL.md`, and separately show the contents of a package
root supplied to `validate`. Otherwise “place files in standard directories”
leaves authors guessing which directory is the discovery root.

The ladder mentions templates and assets, but current standard discovery
directories do not include them, while canonical `resource_item` supports an
asset and the Resource plan also names methods and sources. The table should
either list only the first stable author-facing kinds or point to a versioned
Product target matrix rather than imply that every named directory works by
convention.

### P2-2: Availability needs separate visibility, readiness, and invocation decisions

`pending_approval` is not necessarily a stable availability state: an
invocation-level Approval may not exist until a call is prepared. Prefer three
fields:

- visibility/enabled state;
- runtime readiness (`prepared`, `unsupported`, `missing`); and
- last or current invocation decision, if one exists.

This prevents a list command from implying that one future action is already
approved or pending.

### P2-3: Namespace and version examples need one compatibility story

The proposal alternates between package version `1.0.0`, built-in version `1`,
service name suffix `.v1`, declaration schema versions, and Worker protocol
versions. Authors need a short table explaining which version they increment
for content changes, breaking service contracts, wire-protocol changes, and
Product compatibility changes.

Keep the public root small. `loushang.plugin` should export author values and
builders only; codec internals should normally be used through `validate`,
generated types, or a testing package rather than becoming a broad stable
namespace on day one.

## Minimum Viable Author Journey

The first public journey should prove three paths without teaching internal
owners or runtime protocols.

### Journey A: Native content-only Skill

Author files:

```text
.loushang/
`-- skills/
    `-- review/
        `-- SKILL.md
```

Author actions:

```text
loushang --list-skills
loushang skill show review
```

No Plugin Instance, manifest, Python, installation, or Approval is introduced.
If `skill show` is not selected as the final spelling, the shipped journey must
still include an equally direct offline validation/inspection command.

### Journey B: Packaged Skill with one managed script

Author files:

```text
acme-review/
|-- <one author manifest>
|-- skills/
|   `-- review/
|       `-- SKILL.md
`-- scripts/
    `-- generate.py
```

The manifest carries Plugin ID `acme.review`, Skill ID `review`, and a script
entry owned by that Skill. The common zero-dependency script reads at most one
JSON value from stdin, writes one result to stdout, and writes diagnostics to
stderr.

Author actions:

```text
loushang plugin validate . --target coding --format json
loushang plugin dev . --skill review --script generate --input request.json
loushang plugin test . --conformance
loushang plugin pack . --output dist/
loushang plugin install dist/acme.review-1.0.0.lspkg --disabled
loushang plugin prepare acme.review
loushang plugin enable acme.review
loushang skill script run acme.review:review generate --input request.json
loushang plugin explain acme.review --format json
```

PLC8B-1 may omit `prepare` for a Product-supplied standard-library runtime, but
the command and status model must remain compatible with PLC8B-2 dependency
environments. The output of every step names the exact revision it validated,
snapshotted, packed, installed, prepared, enabled, or invoked.

### Journey C: Trusted Product built-in

The Product developer uses existing Tool authoring decisions and one concise
Product build façade. Conceptually:

```python
@tool()
async def analyze(path: str) -> AnalyzeResult:
    ...


ANALYZE = direct_tool(analyze)

BUILTIN = product_builtin(
    id="coding.base",
    resources=resource_tree("resources"),
    tool_definitions=[ANALYZE],
    tool_packs=[tool_pack_ref("coding.base.tools", tools=("analyze",))],
)
```

`product_builtin` is a trusted Product-build input, not a runtime Plugin context.
The build compiler emits owner-specific static registration input and canonical
Plugin package/declaration data. Runtime still performs normal identity,
admission, selection, and exact-owner publication. The precise API may become
shorter, but its two outputs must not be represented as one callable-bearing
canonical Tool Pack.

The first Worker journey comes later in PLC9B and should use a generated domain
service package. It is not required for an author to ship Journeys A or B.

## API And CLI Corrections Required Before Acceptance

1. Replace the single “everything compiles to canonical declaration IR” diagram
   with a compiler model that distinguishes canonical package/declaration data
   from Product-owner static registration inputs and generated Worker adapters.
2. State that generated inert metadata is packaged before runtime preflight;
   runtime never imports a builder to discover requested authority.
3. Normalize managed script identity to
   `{package_revision, skill_resource_id, script_id}`, or rename it as a package
   command everywhere.
4. Remove callable lists from `tool_pack` examples. Reuse `ToolDefinition` and
   exact Tool catalog references through separate Product build outputs.
5. Defer plain-annotation injection. If later adopted, require an explicit
   injection marker and a deterministic model-schema exclusion rule.
6. Select one author manifest source. If TOML remains, make it compile-only and
   never a second runtime manifest authority.
7. Specify the full offline/development/management/invocation CLI state machine,
   including `prepare`, `enable`, exact revision output, and the legacy flag
   migration.
8. Add versioned schemas and limits to JSON input/result modes; do not call an
   encoding-only action typed.
9. Make Work/Coding constructors name their execution shape and Product-owned
   runtime/toolchain reference.
10. Make the Worker API domain-schema-first, include the Python main-guard
    pattern, and require Python plus one non-Python golden-wire proof before
    protocol stability.

## Acceptance Gates

### Author simplicity

- A fresh repository with one `.loushang/skills/<id>/SKILL.md` is listed and
  loaded without a manifest or code.
- A zero-dependency managed-script sample contains only one manifest, one
  `SKILL.md`, and one script; it contains no subprocess, Approval, Sandbox,
  Artifact publication, digest, RPC, or cleanup code.
- A trusted built-in Tool reuses `tool`, `direct_tool`/`authorized_tool`, and one
  Product build façade; it imports no internal `harness.plugin_authoring` module.
- The public docs have one canonical tutorial for each supported level and no
  alternative manifest spelling or competing builder style in the primary path.

### Compiler and API correctness

- Built-in build compilation produces a complete inert contribution index
  before runtime, and `validate/list/install` can operate without importing the
  executable definition module.
- Generated declaration documents exact-match the strict canonical codecs and
  are deterministic across repeated builds.
- Tool callables never appear inside the canonical data-only Tool Pack payload;
  Product Tool-owner staging and Tool Pack references are separately testable.
- Any injected parameter uses an explicit marker, is absent from the model JSON
  schema, appears in inert Capability requirements, and cannot exceed the
  Product authority ceiling.
- Public modules expose only reviewed author contracts; compatibility snapshots
  fail on accidental export or signature drift.

### Managed scripts

- Two Skills in one package with the same script ID resolve to distinct exact
  identities, and precedence/update cannot route a call to the wrong revision.
- JSON ABI tests cover absent input, `null`, malformed UTF-8, duplicate keys,
  non-finite values, trailing data, empty success output, oversized stdout,
  stderr flood, timeout, cancellation, and stable structured failure categories.
- `validate`, `list`, `show`, `pack`, and `install --disabled` never execute the
  script or prepare dependencies.
- `dev` snapshots first and invokes the immutable snapshot through the same
  Policy, Approval, containment, result, and cleanup path as installed content.
- CLI and model actions produce the same normalized invocation record and exact
  package/Skill/script identities.

### CLI and diagnostics

- Every proposed command can run without starting a model; commands document
  whether they are pure reads, author Artifact writes, management mutations, or
  protected execution.
- Text and JSON output name Product target, exact package revision, Skill/script
  identity, runtime readiness, effective execution route, and remediation.
- The legacy `--install-package`, source, and enable/disable flags have one
  tested migration/deprecation path to the subcommand control plane.
- `--target current` emits its resolved target tuple and never becomes an
  unrecorded compatibility wildcard.

### Product overlays

- Work examples prove one script-backed step and one Worker-backed or trusted
  built-in step without giving either direct `WorkRun` or event-log mutation.
- Coding examples prove one declarative language server and one non-LSP
  contribution; executable resolution does not depend on ambient `PATH`.
- The common SDK has no Work/Coding import, and Product overlays compile to the
  same accepted canonical records and owner-specific adapters.

### Worker interoperability

- One Python and one non-Python Worker implementation pass identical handshake,
  request, cancellation, streaming, backpressure, malformed-frame, shutdown,
  and version-negotiation golden tests.
- At least two domain service schemas prove that the SDK is not an LSP- or
  indexer-specific abstraction.
- Service contract, wire protocol, package, and Product compatibility versions
  change independently with deterministic diagnostics.
- Worker authors implement only generated domain methods; they do not handle
  raw stdio, framing, process supervision, Approval, Sandbox, owner publication,
  or cleanup.

## Final Assessment

The document is close to a strong authoring strategy, but its simplest-looking
examples currently erase distinctions that the implemented architecture relies
on: preflight data versus executable declaration, Tool definition versus Tool
Pack selection, and Plugin package identity versus Skill identity. Those
distinctions do not need to burden authors. They need to be absorbed by a
clearly specified build compiler, owner-specific adapters, generated metadata,
and exact CLI resolution.

After the three P0 corrections, the target can be genuinely simple:

```text
plain Skill         -> one directory
managed Skill code  -> one script declaration and one script
trusted built-in    -> existing typed author object plus one Product build entry
long-lived service  -> generated domain interface implementation
```

Do not stabilize the decorator, class, manifest, or Worker examples before the
minimum journeys and acceptance gates above pass. The current internal LSP
slice proves the governance mechanics and the need for a façade; it does not yet
prove which façade ordinary authors should learn.
