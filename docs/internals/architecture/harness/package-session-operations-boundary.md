# Package Session Operations Boundary

## Decision

`loushang.harness.resources.packages.PackageOperationsRuntime` owns the
product-neutral lifecycle ordering for an already-selected package source:

1. materialize a local path or remote source;
2. register an installed source through a Product callback;
3. refresh Product resources after a successful install, update, or uninstall;
4. prepare configured remote records before a bulk update; and
5. remove and forget a source during uninstall.

`PackageCatalogDiagnosticsRecorder` consumes typed
`PackageCatalogEntry` values and records manifest, catalog, and version-conflict
diagnostics before any Product wire projection. The existing
`PackageCatalogBuilder` remains the single shared owner of catalog discovery;
this runtime does not introduce a second catalog or repository.

## Product Binding

Products supply the materializer, source registration and removal callbacks,
resource refresh callback, and optional bulk-update preparation. They choose
the settings scope and fallback behavior, materializer security policy,
resource roots, catalog summary policy, and diagnostic service/session scope.

The runtime returns typed `PackageMaterializationRecord` and
`PackageCatalogEntry` values. It owns no CLI, RPC, channel, or presentation
schema.

## Coding Binding

`coding.session.PackageController` binds its `SettingsManager`, materializer,
`DefaultResourceLoader`, current session id, configured-source preparation,
and resource refresh. It retains scope fallback to the Coding session layer,
trust and approval policy injected into the Coding materializer, resource-root
configuration, update-check wording, and projection to Coding's Pi/CLI field
names.

Coding's package projection still chooses how catalog records appear to users.
It now collects typed records first, lets Harness record shared discovery
diagnostics, then serializes the Coding-specific payload.

## Dependency Rule

`harness.resources.packages.operations` and
`harness.resources.packages.catalog_diagnostics` may depend on Harness package,
resource, and diagnostics contracts. They must not import Coding settings,
loaders, security policy, commands, UI/RPC types, or Product diagnostics
wording. Products bind all concrete behavior through values or callbacks.

## Verification

- Harness tests cover local and remote materialization, success-only source
  registration, bulk-update preparation, uninstall ordering, unavailable
  materializers, and typed catalog diagnostic recording.
- Coding package-controller and AgentSession package regressions retain the
  existing settings, refresh, catalog, and Pi projection behavior.
- Architecture tests require the Harness owners, Coding adoption, the
  documented Product Binding and Coding Binding, and forbid a Coding import in
  either shared module.
