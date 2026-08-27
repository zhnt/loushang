# Runtime Provenance Boundary

## Status

Status: implemented on the Harness runtime-provenance task branch.

## Purpose

Runtime provenance explains which host process and independently owned
components produced an observable Product surface. It is diagnostic evidence,
not a new selection authority, Plugin registry, or Capability graph.

Two scopes are intentionally distinct:

- `installation` is available before Product bootstrap and describes the host
  executable, Python/import environment, source checkout when present, and
  bundled or installed component contracts;
- `runtime` is available only after composition and describes effective
  component state supplied by the owners that actually activated it.

A bundled component is not implicitly active. Source Git revision is not a
build revision. The latter name is reserved for immutable metadata embedded in
a wheel or binary by a future build pipeline.

## Ownership

`loushang.foundation.observability.identity` owns pure host/package/source
inspection. It may inspect the current workspace and an importable source tree,
but it does not import Harness, a Product, Plugin, or UI package.

`loushang.harness.diagnostics.runtime_provenance` owns:

- the versioned composition envelope;
- immutable strict-JSON component facts;
- the contributor Protocol;
- deterministic component ordering and duplicate-id rejection; and
- the separation between installation and effective-runtime scope.

Products own contributor composition and final text, CLI, RPC, TUI, or Web
presentation. A Product may import a peer component such as `loushang.tui` and
adapt its constants into a Harness contributor. Harness must never import that
peer package.

Plugins own their component facts. A stat, LSP, Arch, renderer, or OEM Plugin
can implement the contributor Protocol without adding a Product-specific field
to the common schema. Runtime facts must come from the effective owner after
activation; an installation descriptor cannot claim `state="active"`.

## Value Contract

The composed mapping preserves the host identity and adds:

```json
{
  "provenance_schema_version": 1,
  "provenance_scope": "installation",
  "components": {
    "native-screen": {
      "kind": "renderer",
      "availability": "bundled",
      "contract_version": 1
    }
  }
}
```

Component ids are unique within one view. Component details are defensively
copied and restricted to the strict Foundation JSON algebra. The aggregator
does not infer missing state, call lifecycle operations, or replace facts from
one owner with another owner's values.

## CLI And Product Projection

The standard Harness CLI owns the early-exit behavior:

- plain `--version` reads only the Product package-version port;
- `--version --verbose` and `--source-info` call the injected Product
  provenance collector before runtime construction;
- JSON output serializes the same composed mapping used by text projection.

An interactive `/debug` command may show installation provenance before an
effective-runtime contributor is available. Its wording must retain the scope
and must not present bundled components as active. A later runtime view can add
effective Plugin/component contributors without changing the installation
contract.

## Build Metadata Gate

`build_revision` is not emitted until both wheel and PyInstaller build paths
embed immutable source revision metadata. Acceptance for that future field
requires installing or executing each artifact outside a Git checkout and
recovering the exact revision without runtime environment overrides.

## Acceptance

- Harness provenance modules import no Product, TUI, Work, Method, or Channel
  package.
- Fake Products can use verbose version through injected ports.
- Duplicate component ids and non-JSON facts are rejected deterministically.
- Installation-only contributors do not appear in a runtime-scoped view.
- Product output labels source revision and bundled component state accurately.
- POSIX commands and Windows `PATHEXT` console-script candidates remain
  distinguishable as active or shadowed.
