# Loushang Coding Plugin V1 Design

## Status

Retired historical design. Product-neutral Plugin architecture now lives in
the [Harness Plugin Architecture](../architecture/harness/plugin/architecture.md),
and package/Resource layout is governed by the
[Harness Platform Resource Layout Boundary](../architecture/harness/platform-resource-layout-boundary.md).
The remaining text describes the original Coding-local V1 and is not an active
implementation contract.

## Goal

Define `plugin v1` as a new component in `loushang-coding` without turning it into a new runtime core.

The design target is:

- support `local path plugin`
- make `plugin` a first-class package / distribution management subsystem
- keep `extensions` as the runtime extension subsystem
- keep `session` and `ExtensionRunner` free from install / packaging concerns

## Non-Goals

`plugin v1` does not try to provide:

- npm / git / marketplace installation
- dependency solving
- strong sandbox enforcement
- a second runtime hook system
- direct plugin access to `session` internals

## Architecture

`plugin v1` introduces one new component:

- `plugin`: package / distribution management subsystem

It works together with existing components:

- `loader`: resource aggregation subsystem
- `extensions`: runtime extension subsystem

The intended data flow is:

- `PluginSource -> PluginManager -> PluginRegistry -> PluginResolver -> ResourceDescriptors -> DefaultResourceLoader -> ExtensionLoader -> ExtensionRunner -> Session`

This keeps the responsibilities split cleanly:

- `plugin` answers: what is this bundle, where does it come from, and what resources does it contain
- `extensions` answers: how are extension hooks, tools, and lifecycle logic executed at runtime
- `session` only consumes the final runtime surface

## Component Split

### `PluginManager`

Owns:

- plugin source management
- enable / disable state
- scope-aware plugin activation

Suggested commands:

- `add_plugin_source(...)`
- `remove_plugin_source(...)`
- `enable_plugin(...)`
- `disable_plugin(...)`
- `refresh_plugins(...)`

### `PluginRegistry`

Owns:

- indexing known plugins
- deduplication
- scope precedence

Suggested queries:

- `list_plugins()`
- `list_enabled_plugins()`
- `find_plugin(...)`

### `PluginResolver`

Owns:

- reading plugin manifest
- validating resource declarations
- producing resource descriptors

Suggested commands / queries:

- `resolve_plugin(source) -> InstalledPlugin`
- `resolve_resources(plugin) -> PluginResolvedResources`

## Manifest V1

Formal plugins should require a manifest file:

- `loushang-plugin.json`

Recommended minimal shape:

```json
{
  "id": "acme.dev-tools",
  "name": "Acme Dev Tools",
  "version": "0.1.0",
  "description": "Project-local coding helpers",
  "capabilities": [
    "resources.contribute",
    "tools.register",
    "tools.intercept"
  ],
  "resources": {
    "extensions": ["extensions/*.py"],
    "skills": ["skills/**/SKILL.md"],
    "prompts": ["prompts/*.md"],
    "themes": ["themes/*.json"]
  }
}
```

### Field Rules

- `id`
  - required
  - stable plugin identity
- `name`
  - required
- `version`
  - required
- `description`
  - optional
- `capabilities`
  - optional
  - defaults to `[]`
- `resources`
  - optional
  - when omitted, resolver may fall back to convention directories

`v1` does not require a separate `entrypoints` field. For runtime extensions, `resources.extensions` is enough.

## Directory Layout

Recommended plugin root:

```text
my-plugin/
  loushang-plugin.json
  extensions/
    guard.py
    review_tool.py
  skills/
    review/
      SKILL.md
  prompts/
    review.md
  themes/
    clean.json
```

Resolution rule:

- if `loushang-plugin.json` exists, treat the directory as a formal plugin
- if no manifest exists, do not treat it as a formal plugin in `plugin v1`
- plain resource directories may still exist, but they remain a `ResourceLoader` concern rather than a `plugin` concern

## Core Data

### `PluginSource`

Represents where a plugin comes from.

Suggested fields:

- `kind`: `local`
- `locator`
- `scope`: `project | global`

`v1` only supports `local`, but the type should remain open for future `git` / `registry`.

### `InstalledPlugin`

Represents one resolved plugin installation.

Suggested fields:

- `source`
- `install_path`
- `manifest`
- `enabled`

### `PluginResolvedResources`

Represents the plugin’s resolved resource descriptors.

Suggested fields:

- `extension_descriptors`
- `skill_descriptors`
- `prompt_descriptors`
- `theme_descriptors`
- `diagnostics`

This object should never contain runtime-bound extension instances.

## Settings Model

`control` should grow a plugin source state similar to:

```json
{
  "plugins": [
    {
      "source": "./.loushang/plugins/acme-dev-tools",
      "scope": "project",
      "enabled": true
    }
  ]
}
```

Rules:

- `scope` is `project` or `global`
- if the same `plugin.id` appears in both scopes, `project` overrides `global`
- disabled plugins do not participate in resolution

## Capability Model

`plugin v1` should declare capabilities even before strong enforcement exists.

Suggested capability strings:

- `resources.contribute`
- `tools.register`
- `tools.intercept`
- `commands.register`
- `ui.interact`
- `session.persist`
- `session.actions`
- `network`
- `exec`

For `v1`, the most important practical set is:

- `resources.contribute`
- `tools.register`
- `tools.intercept`

The rest can remain forward-looking declarations.

## Integration With Existing Components

### `control`

Owns:

- plugin sources
- enabled state
- scope

### `loader`

Owns:

- aggregating project resources and plugin-resolved resources

### `extensions`

Owns:

- loading extension entries into `LoadedExtension`
- running hooks, tools, and lifecycle logic

### `session`

Does not need plugin-specific semantics.

It should continue to consume:

- tools
- prompts
- skills
- loaded extensions

## Rejected Designs

### `plugin == extension`

Rejected because package/distribution concerns would pollute the runtime extension boundary.

### `plugin` directly under `session`

Rejected because installation and bundle resolution are not session responsibilities.

### npm / git installation in `v1`

Rejected because it expands scope too early. `local path plugin` is enough to validate the architecture first.

## Recommended Implementation Order

1. Add plugin data models
   - `PluginManifest`
   - `PluginSource`
   - `InstalledPlugin`
   - `PluginResolvedResources`
2. Add plugin services
   - `PluginRegistry`
   - `PluginResolver`
   - `PluginManager`
3. Extend `control` with plugin source state
4. Extend `DefaultResourceLoader` to merge plugin-resolved resources
5. Add examples and docs for local plugin layout

## Summary

`plugin v1` should become a new component, but it should be a package / distribution management subsystem rather than a new runtime center.

In one sentence:

- `plugin` is the bundle boundary
- `extension` is the runtime boundary
- `loader` is the aggregation boundary
- `session` remains the business center
