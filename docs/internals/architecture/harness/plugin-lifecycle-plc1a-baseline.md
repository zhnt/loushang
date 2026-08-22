# Plugin Lifecycle PLC1A Baseline

## Status

- Source commit: `2ebac237` on `harness/plugin-authoring-primitives-pap1`.
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
- `PluginDeclarationBuilder`, which consumes each selected reservation exactly
  once and freezes after `build()`.

`CapabilityProviderDeclarationPayload.from_reserved_declaration()` is the
single strict bridge from opaque `PluginDeclaration` IR to the existing
Capability semantic types. It checks the complete reservation envelope,
Plugin-derived source identity, fixed candidate selection rule, exact requested
authorities, configuration fingerprint, package revision, and execution model.

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
- Absolute, traversing, non-canonical, or non-Python symbol paths are rejected.
- Factory and disposer references must share package revision and execution
  identity.
- Builder declarations must match reservation owner, authorities,
  configuration, package revision, and execution model.
- Builder reservations are one-use; every selected reservation must be
  consumed, and the Builder cannot mutate after freeze.
- Canonical payload and binding-input SHA-256 fixtures are pinned in tests.

## Verification

The implementation commit passed:

- 95 focused Plugin authoring and Resource Plugin tests;
- 180 unified-Plugin and Harness import-boundary architecture tests;
- Ruff over changed source/tests;
- mypy over the new internal authoring package; and
- `git diff --check`.

The first full `make check-harness` run passed Ruff, mypy over 490 Harness source
files, and 2352 tests with four skips; its only failure exposed the original
package-placement cycle. The placement was corrected without an allowlist. The
final `make check-harness` passed Ruff, mypy over 491 Harness source files, and
2352 tests with four skips. The architecture-documentation gate also passed its
renderer check and five tests.

## Deferred

PLC1A intentionally does not implement document-backed declarations,
Definition import/evaluation, durable execution-decision consumption,
Capability-owner admission, Product Provider selection, Component Host symbol
resolution, Graph binding, `coding.lsp`, `coding.base`, `coding.arch`, Skill
convergence, or additional MCP functionality.

PLC1B is the next declaration-only slice. PAP2/PLC3 executable trust remains a
fresh source-backed review boundary.
