# Plugin Lifecycle PLC1A Baseline

## Status

- Source commits: implementation `2ebac237`, first review hardening `27715416`,
  and second-review remediation on
  `harness/plugin-authoring-primitives-pap1`.
- Scope: PAP1 / PLC1A, inert Capability Provider authoring only.
- Publication: local only. GitHub issue/PR attachment and independent review
  remain required before remote publication.
- Live effect: none. This slice does not import Plugin code, consume an
  execution approval, admit a Provider, construct a component, bind a Graph,
  publish a Mount, or expose a public author SDK.

## Implemented Boundary

The internal `loushang.harness.plugin_authoring` composition layer now owns:

- strict, versioned JSON codecs for `CapabilityContractRange`,
  `CapabilityRequirement`, and the existing `CapabilityBundleProvider` type;
- `PluginSymbolReference`, containing only a canonical relative Python path,
  dotted symbol, exact package SHA-256 digest, and execution model;
- `CapabilityProviderDeclarationPayload`, containing canonical Provider
  metadata, factory/disposer locators, JSON-only binding inputs, and the
  reservation configuration fingerprint; and
- `PluginDeclarationBuilder`, which consumes exact preflight
  `PluginDeclarationReservation` values, retains only narrow data facts,
  consumes each selected contribution exactly once, and freezes after
  `build()`.

`CapabilityProviderDeclarationPayload.from_reserved_declaration()` is the
single strict bridge from opaque `PluginDeclaration` IR to the existing
Capability semantic types. It checks the complete reservation envelope,
Plugin-derived source identity, fixed candidate selection rule, exact requested
authorities, configuration fingerprint, package revision, and execution model.
There is no weaker declaration-object decoder beside it.

The generic Resource-layer `PluginDeclaration` and `PluginSelectionResolver`
remain payload-opaque and inert. They freeze, fingerprint, reserve, and select;
they do not acquire Capability-owner decoding or admission authority.

## Dependency Placement Correction

The initial implementation sketch placed the typed codec under
`harness.resources.plugins`. The full Harness dependency gate demonstrated
that this creates a forbidden cycle:

```text
resources -> capabilities -> resources
```

No exception was added. The cross-owner authoring adapter was moved to the
higher internal `harness.plugin_authoring` composition layer, whose dependency
direction is:

```text
plugin_authoring -> capabilities
plugin_authoring -> resources.plugins
```

Neither lower layer imports `plugin_authoring`. Existing Capability semantic
types remain authoritative; no parallel Provider or Consumer model was added.

## Frozen Contracts

- Unknown fields and noncanonical list order are rejected.
- Duplicate facets, authorities, or required Capability identities are
  rejected by the strict codec or existing semantic constructors.
- Callable and non-JSON binding inputs are rejected.
- POSIX and Windows absolute, drive-qualified, backslash, traversing,
  non-canonical, or non-Python symbol paths are rejected.
- Factory and disposer references must share package revision and execution
  identity.
- Builder inputs are derived from one preflight context and must share its
  Product, scope, policy revision, source identity/trust class, ambient-host
  authority, published package, and dependency lock. Each reservation must
  also match its approval subject, owner, authorities, configuration, package
  revision, and execution model.
- Builder reservations are one-use; every selected reservation must be
  consumed, and the Builder cannot mutate after freeze.
- Canonical payload and binding-input SHA-256 fixtures are pinned in tests.

## Verification

The implementation commit passed:

- 98 focused Plugin authoring and Resource Plugin tests after review hardening;
- 180 unified-Plugin and Harness import-boundary architecture tests;
- Ruff over changed source/tests;
- mypy over the new internal authoring package; and
- `git diff --check`.

The first full `make check-harness` run passed Ruff, mypy over 490 Harness source
files, and 2352 tests with four skips; its only failure exposed the original
package-placement cycle. The placement was corrected without an allowlist. The
pre-review final `make check-harness` passed Ruff, mypy over 491 Harness source
files, and 2352 tests with four skips. After review remediation, the final gate
passed Ruff, mypy over 492 source files, and 2355 tests with four skips. The
architecture-documentation gate also passed its renderer check and five tests.

## Review Remediation

The first implementation review found three blocking issues:

1. `PurePosixPath` alone accepted `..\\provider.py`, `C:\\provider.py`, and
   `C:/provider.py` even though a Windows host would interpret them as traversal
   or absolute paths.
2. Builder and strict decoder callers could independently combine Plugin ID,
   package digest, and contribution reservation facts.
3. `from_declaration()` offered a declaration-object decode that did not check
   reservation authorities, configuration, package revision, or execution
   model.

`27715416` closes them without adding live behavior: symbol paths are checked
under both POSIX and Windows semantics; exact package/approval facts are derived
from `PluginDeclarationReservation` and immediately narrowed to a data-only
view; and `from_reserved_declaration()` is now the sole declaration-object
decode path. Regression tests cover all three failures.

The second implementation review found three additional gaps:

1. Manifest Definition entrypoints and verified-revision logical paths still
   used independent, weaker POSIX-only validation even though Provider symbol
   references used a host-independent codec.
2. Reservations for one immutable package revision could be combined across
   different Product, scope, policy, or source-trust preflight contexts.
3. The inert-layer architecture gate scanned `resources.plugins` but not the
   higher `plugin_authoring` composition layer.

The remediation introduces one Resource-owned canonical path/symbol codec used
by manifest reservations, verified revisions, and Provider symbol references;
retains a narrow immutable common preflight context in the Builder; validates
ambient-host authority against the reserved execution model; and scans both
inert source roots for forbidden runtime/product imports and executable loading.
Regression tests cover the original failing forms without adding a dependency
allowlist or any live Plugin behavior. The remediation's focused suite passes
102 tests together with Ruff and focused mypy. Its final `make check-harness`
gate passes Ruff, mypy over 493 source files, and 2361 tests with four skips;
the unified-Plugin, import-boundary, and architecture-documentation gate passes
185 tests.

## Deferred

PLC1A intentionally does not implement document-backed declarations,
Definition import/evaluation, durable execution-decision consumption,
Capability-owner admission, Product Provider selection, Component Host symbol
resolution, Graph binding, `coding.lsp`, `coding.base`, `coding.arch`, Skill
convergence, or additional MCP functionality.

PLC1B is the next declaration-only slice. PAP2/PLC3 executable trust remains a
fresh source-backed review boundary.
