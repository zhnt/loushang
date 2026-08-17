# ARD-004: Package And Plugin Boundary

## Status

Superseded by the zero-compatibility resource facade cutover.

The package/plugin distinction and CLI/RPC wire semantics remain valid, but
the former `coding.package.*` and `coding.plugin.*` paths were removed. Generic
package and plugin APIs, including catalog/materialization projections, are now
imported from `loushang.harness.resources`; Coding binds product defaults in
`coding.resource_runtime` and retains no Package or Plugin facade. Canonical
terminology and current ownership are defined by the
[Product And OEM Glossary](../../glossary/loushang-product.md) and
[Harness Platform Resource Layout Boundary](../harness/platform-resource-layout-boundary.md).

## Context

`loushang-coding` has two related but distinct distribution concepts:

- package-oriented resource loading, exposed through `package_roots`,
  `PackageResourceSummary`, `get_packages()`, and package lifecycle commands
- plugin-oriented source management, exposed through `plugin_sources`,
  `PluginManifest`, `PluginManager`, and `plugin.json`

Early implementation used a `plugin` module to house both plugin source
management and package materialization. This matched the initial implementation
path, but it creates naming pressure:

- `PackageMaterializer` lives under `loushang.coding.plugin`
- remote lifecycle entries are projected as `kind="remote_plugin"` even though
  package lifecycle is the broader concept
- CLI has both `--remove-plugin-source` and `--remove-package`; these operate at
  different layers
- docs sometimes describe `plugin` as the package/distribution subsystem

The distinction matters more now that real git-backed package materialization,
package update, and package removal are part of the headless runtime surface.

## Decision

### 1. `package` is the resource distribution unit

A package is a source of coding resources.

It may contain:

- prompts
- skills
- extensions
- themes
- future resource types

The package layer owns distribution and resource-plane projection concerns:

- local package roots
- materialized remote checkouts
- package lifecycle state
- package resource summaries
- package policy and trust decisions
- package list projection for CLI/RPC/UI

Canonical package-facing names should use `package`:

- `PackageMaterializer`
- `PackageMaterializationRecord`
- `PackageResourceSummary`
- `PackageSourcePolicy`
- `get_packages()`
- `materialize_package()`
- `install_package()`
- `update_package()`
- `update_packages()`
- `check_package_updates()`
- `remove_package()`
- `uninstall_package()`

### 2. `plugin` is a manifest-backed package source view

A plugin is a managed source descriptor that may point to a package root.

The plugin layer owns identity and management concerns:

- plugin source registration
- plugin manifest parsing
- plugin enable/disable state
- plugin version/name metadata
- plugin `packageRoot` resolution

Canonical plugin-facing names should use `plugin`:

- `PluginSource`
- `PluginManifest`
- `InstalledPlugin`
- `PluginRegistry`
- `PluginResolver`
- `PluginManager`
- `plugin_sources`
- `add_plugin_source()`
- `remove_plugin_source()`
- `enable_plugin()`
- `disable_plugin()`

The relationship is:

```text
plugin source -> plugin manifest -> package root -> resource descriptors
```

Not every package is a plugin. A configured `package_root` can be consumed
directly without `plugin.json`.

Not every plugin is an extension. A plugin can provide prompts, skills, themes,
extensions, or any combination of these resources.

### 3. `extension` remains the runtime programmability surface

An extension is executable runtime behavior loaded from a resource descriptor.

Plugins and packages can carry extension files, but they do not replace the
extension boundary. Extension author APIs, command registration, tool
registration, hooks, UI context, and renderer registration remain under the
`extensions` component.

### 4. Package lifecycle does not imply plugin source persistence

Package lifecycle commands act on materialized package state:

- `materialize_package(source)` installs or prepares a package checkout
- `update_package(source)` refreshes a materialized package checkout
- `remove_package(source)` deletes the materialized checkout and returns the
  lifecycle to `remote_registered`

Plugin source commands act on settings:

- `add_plugin_source(source)` registers a source in settings
- `remove_plugin_source(source)` removes a source from settings

These commands intentionally remain separate.

If a future product command wants one-step uninstall behavior, it should be
introduced as an explicit higher-level operation, for example
`uninstall_package(source, persist=True)`, rather than overloading
`remove_package()` or `remove_plugin_source()`.

### 5. Python package management is not the package manager target

`loushang` is a Python project, but `loushang-coding` package management is about
coding resources, not Python dependency installation.

The package manager should not copy `reference CLI`'s npm-specific implementation. Alignment
with `reference CLI` should focus on cross-ecosystem semantics:

- source registration
- materialization
- update/remove lifecycle
- resource discovery
- diagnostics
- trust and pinning
- conflict projection/resolution

Python dependency installation remains outside the coding package manager unless
a future design explicitly defines a safe and isolated Python resource package
format.

### 6. Python package sources are isolated resource packages

`pypi:<requirement>` sources are allowed as a Python ecosystem distribution
format for coding resources. They are not installed into the user's project
environment, the active virtual environment, or the global Python environment.

The package layer installs them into Loushang-managed isolated targets and then
passes the installed package root to the normal resource loader. The supported
purpose is resource distribution:

- prompts
- skills
- extensions
- themes

This preserves the boundary above: Loushang can consume Python-distributed
coding resource packages without becoming a general Python dependency manager
for the user's project.

## Naming Review

### Current names that are clear

- `package_roots`: clear; these are directories consumed by the resource loader
- `plugin_sources`: clear; these are settings-level managed plugin sources
- `PackageMaterializer`: clear; it owns package lifecycle, not plugin identity
- `PluginResolver`: clear; it resolves plugin manifests to package roots
- `get_packages()`: clear; it returns package/resource projection, not only
  plugins
- `list_plugins()`: clear; it returns plugin manifest/source projection

### Historical Compatibility Names

The package lifecycle code now has canonical names under
`loushang.coding.package.*`. These older names remain as compatibility aliases
because they already appeared in tests, docs, and internal call sites:

- module path `loushang.coding.plugin.materializer`
  - canonical: `loushang.coding.package.materializer`
  - compatibility behavior: re-export package lifecycle types
- module path `loushang.coding.plugin.package_projection`
  - canonical: `loushang.coding.package.projection`
  - compatibility behavior: re-export package projection helpers
- `remote_plugin` package entry kind
  - canonical semantic field: `packageKind="remote_package"`
  - compatibility behavior: keep `kind="remote_plugin"` for existing consumers
- `PackageMaterializationRecord.name`
  - issue: for remote sources, this is a derived package name, not necessarily a
    plugin manifest name
  - preferred: keep for display, but add future fields such as
    `display_name`, `source_name`, or `manifest_name` if ambiguity appears
- `PackageSecurityPolicy.evaluate_plugin_source(...)`
  - canonical method: `evaluate_package_source(...)`
  - compatibility behavior: keep `evaluate_plugin_source(...)` as an alias

### Compatibility guidance

Do not rename public-ish CLI/RPC/session methods casually. Prefer a staged path:

1. add the clearer package module or entry kind
2. keep old import paths or old projection fields as compatibility aliases
3. update internal call sites
4. update docs and examples
5. remove aliases only after the API is explicitly versioned

## Consequences

### Positive

- Resource distribution and plugin manifest management have separate meanings.
- `remove_package` and `remove_plugin_source` no longer look like competing names
  for the same operation.
- Future trust, pinning, update, and conflict work has a package-level home.
- Git-backed package lifecycle now exposes pinned refs, resolved commits,
  installed commits, dirty state, and update availability at the package layer.
- Extension runtime APIs remain cleanly separate from package/plugin delivery.

### Negative

- The old Python module paths still exist as compatibility aliases, so readers
  need this ADR until the compatibility layer is removed.
- Some CLI aliases inherited from reference-style package commands still use plugin
  source settings operations; docs must be explicit about that compatibility
  layer.
- Removing compatibility aliases later will require explicit API versioning.

## Impacted Components

- `plugin`
- `loader`
- `control`
- `policy`
- `session`
- `runtime`
- `rpc`
- `cli`

## Superseded Follow-up

- Evaluate when to deprecate `loushang.coding.plugin.materializer` and
  `loushang.coding.plugin.package_projection` imports.
- Evaluate when to deprecate `kind="remote_plugin"` after consumers have moved
  to `packageKind="remote_package"`.
- Update component docs so `plugin` no longer claims ownership of the whole
  package/distribution subsystem.
- Continue hardening durable package lockfile and package trust policy at the
  package layer, not the plugin layer. Custom signature verification is an
  optional security enhancement rather than a confirmed reference parity requirement.
