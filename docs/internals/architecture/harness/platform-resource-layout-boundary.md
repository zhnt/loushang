# Harness Platform Resource Layout Boundary

Status: resource and package runtime implementation complete for integration
into `lane/harness`.

## Decision

Harness owns the standard cross-product resource layout and its concrete
discovery mechanisms. Products own domain content, product-only additions,
activation policy, trust policy, and runtime projection.

This decision distinguishes two kinds of defaults:

- a **platform default** is useful to every Loushang product and may be supplied
  by Harness with an explicit override;
- a **product default** selects domain behavior or content and remains in the
  product adapter.

Providing a platform default does not violate Product Kernel Ownership. It
prevents every product from rebuilding the same filesystem and package runtime.

## Standard Roots And Layout

Harness owns resolution of these standard shared roots:

```text
$LOUSHANG_HOME, otherwise ~/.loushang/   # user-global shared resources
<workspace>/.loushang/                   # workspace/project shared resources
```

The workspace root is supplied by the host or product. Harness does not choose
which filesystem tree a product is allowed to access.

The standard resource layout may contain:

```text
prompts/
skills/
extensions/
themes/
packages/
```

Harness may also expose an optional product namespace such as
`~/.loushang/products/<product>/`. A product registers that additional root; it
does not reimplement standard root resolution.

The platform supplies the standard scope vocabulary and an overridable
precedence preset:

```text
temporary > project > user > package > built_in
```

Candidate indexing, deterministic tiebreaking, collision diagnostics, disabled
records, and merge decisions are Harness mechanisms. A product may explicitly
override the preset when its domain semantics require a different order.

## Agent Instruction Conventions

`AGENTS.md` is a cross-product agent-instruction convention, not a Coding file
format. Harness owns its reusable convention implementation:

- accepted standard filenames and case variants;
- discovery bounded by the caller-supplied workspace root;
- ancestor/path scope evaluation;
- text loading, provenance, diagnostics, ordering, and merge records.

Compatibility formats such as `CLAUDE.md` may be implemented as optional
Harness presets. Products and OEMs decide which presets are enabled by default
and may register product-only conventions.

Harness returns instruction resources. It does not decide where they appear in
a product system prompt, how salient they are, or how they are summarized or
truncated.

## Built-In Packages

Harness owns the built-in resource package mechanism:

- package descriptors and registration;
- traversable/resource-root resolution;
- standard resource directory enumeration;
- provenance, diagnostics, and merge participation.

Products own their built-in resource content and register it with Harness. For
example, Coding may register `loushang.coding.resources`; Design may register
`loushang.design.resources`. The package slot and loading machinery are shared,
while the prompt, skill, theme, and extension content remains product-owned.

## Package, Plugin, And Extension Roles

Canonical terminology comes from the
[Product And OEM Glossary](../../glossary/loushang-product.md). Within the
resource runtime, the three concepts remain separate:

- a **Resource Package** is the distribution or materialization root for
  resources;
- a **Plugin** is a manifest-backed optional identity and activation view that
  may resolve to a package root;
- an **Extension** is executable or declarative behavior described by a
  resource descriptor and admitted into an extension surface.

The standard projection is:

```text
plugin source -> plugin manifest -> resource package root -> resource descriptors
                                                        -> extension descriptors
```

A configured package root does not require a Plugin manifest. A Plugin may
contain only prompts, Skills, themes, or assets and therefore no Extension.
Package installation, Plugin enablement, descriptor discovery, Extension
admission, and Extension activation are distinct state transitions. None of
the first three grants execution authority.

## Responsibility Split

Harness owns:

- platform home and standard workspace resource-root resolution;
- the standard directory layout, scope vocabulary, and precedence preset;
- reusable `AGENTS.md` and optional compatibility convention implementations;
- resource descriptors, candidates, snapshots, bundles, merge decisions, and
  diagnostics when expressed without product state;
- filesystem/package discovery, filtering, deterministic merging, reload, and
  package materialization mechanisms;
- built-in package registration and enumeration.

Product adapters own:

- product prompt, skill, theme, and extension content;
- selection and default activation of standard/compatibility conventions;
- additional and overridden roots, including product namespaces;
- product-specific validation, disabled-resource policy, and package filters;
- trust, permissions, approval defaults, and remote-source policy;
- prompt/tool/runtime projection, salience, ordering, and user presentation.

OEM/deployment layers may override Harness platform roots and Product policy
without changing the discovery engine.

## Implemented Runtime

The product-neutral runtime now lives under `loushang.harness.resources`:

- `layout` owns `LOUSHANG_HOME`/`~/.loushang`, workspace `.loushang`, product
  namespace, standard resource directories, and scope precedence;
- `builtin` owns built-in package registration and enumeration;
- `types` owns descriptors, bundles, snapshots, merge decisions, and package
  summaries;
- `loader` is the stable public facade and owns loader state, runtime options,
  reload, queries, and the standard workspace resource-root mode;
- `_loader_pipeline` owns the immutable loader-to-pipeline discovery request,
  candidate-source ordering, discovery-to-resolution orchestration, diagnostic
  and merge-decision aggregation, and `ResourceSnapshot` assembly;
- `_loader_discovery_context` owns context-file ancestor traversal, descriptor
  construction, diagnostics, and nearest-context selection;
- `_loader_descriptor_parsing` owns source-neutral prompt/skill frontmatter
  projection, descriptor construction, and skill validation without I/O;
- `_loader_discovery_filesystem` owns filesystem directory traversal and reads,
  skill ignore rules, extension entry lookup, and theme JSON validation;
- `_loader_discovery_builtin` owns built-in package traversal, logical package
  paths and reads, category discovery, and built-in diagnostics;
- `_loader_discovery_temporary` owns temporary runtime-path resolution,
  single-file/directory dispatch, source metadata, and path diagnostics;
- `_loader_discovery` owns external-package and project/user source coordination
  plus source-specific filtering;
- `_loader_package_policy` owns external-package root/filter normalization,
  root diagnostics, filtering, and per-root resource accounting;
- `_loader_resolution` owns collision handling and winner/active-candidate
  decisions without importing discovery;
- `_loader_precedence` is the single owner of the source priority table, rank,
  and stable candidate/winner sort keys;
- `_loader_types` owns private discovery records and shared private constants,
  but not precedence policy;
- `packages` owns source identity/config parsing, manifests, materialization,
  resource-root resolution, and injected source-policy contracts;
- `plugins` owns neutral plugin source, manifest, registry, resolver, and
  manager mechanics;
- `skills` owns the reusable skill loader facade and its settings protocol.

`ResourceLoader` defaults to the standard `<workspace>/.loushang` resource
root and standard `AGENTS.md` filenames. Products may explicitly select a
legacy project-root mode or optional compatibility filenames. A built-in
resource package must be registered by the product; Harness contains no Coding
package name or content default.

The private modules above are implementation owners, not additional public
APIs. Consumers continue to import `ResourceLoader`, `ResourceLoaderProfile`,
and `ProfiledResourceLoader` through the public resources facade.

Harness package materialization requires an injected source-policy evaluator
and safely rejects materialization when none is supplied. Coding injects its
existing `PackageSecurityPolicy`, preserving HTTPS/trust behavior without
moving product risk defaults into Harness.

## Coding Migration Result

Reusable behavior formerly exposed through `coding.loader`, `coding.package`,
`coding.plugin`, and `coding.skill` lives under focused
`loushang.harness.resources` modules. Those Coding import paths are removed;
all generic consumers import the Harness owner directly.

`coding.resource_runtime.CodingResourceLoader` is Coding's resource binding
and:

- registers `loushang.coding.resources`;
- selects standard and compatibility convention presets;
- adds Coding-specific roots and settings-derived filters;
- projects the Harness resource snapshot into Coding prompt/session behavior.

It does not retain a second implementation of scanning, provenance, merging,
package materialization, package catalog construction, source resolution, or
`AGENTS.md` discovery. `harness.resources.packages` owns the structured
catalog, scoped source resolver, materialization lifecycle, manifest summary,
and conflict diagnostics. `harness.resources.packages.projection` owns the
structured catalog and materialization-record projection;
`harness.resources.packages.session` owns session package operations.
`CodingPackageMaterializer` supplies Coding's settings object and package
security policy; no Coding package projection or controller facade remains.

## Security Boundary

Resource discovery is not resource authorization. Harness may enumerate and
describe a candidate without activating or executing it. Product/deployment
policy decides whether remote packages, extensions, executable resources, or
untrusted workspace content may be activated.

Harness must not import Coding, Design, Research, PPT, Cowork, TUI, Method,
Work, or AI provider packages to implement the standard layout.

## Non-Goals

This design does not move product prompt text, skill content, extension
permissions, package approval policy, settings persistence, UI presentation, or
model/auth resolution into Harness.
