# `plugin`

## Status

Superseded as a Coding-owned component. Product-neutral Plugin identity,
manifest, source, registry, resolver, and manager mechanics now belong to
[Harness Platform Resource Layout](../../harness/platform-resource-layout-boundary.md).
The definitions below are retained for compatibility history.

## Role

- manifest-backed plugin source management component
- plugin source 到 package root 的解析边界
- package/resource distribution 的概念边界见 `ARD-004: Package And Plugin Boundary`

## Owns

- `PluginManifest`
- `PluginSource`
- `InstalledPlugin`
- `PluginRegistry`
- `PluginManager`
- `PluginResolver`

## Depends On

- `control`
- `loader`
- 可选接 `cli` / `sdk`

## Commands

- `add_plugin_source(...)`
- `remove_plugin_source(...)`
- `enable_plugin(...)`
- `disable_plugin(...)`
- `refresh_plugins(...)`
- `prepare_remote_source(source)`
- `await materialize_remote_source(source)`

## Queries

- `list_plugins()`
- `get_plugin(...)`
- `list_enabled_plugins()`
- `resolve_plugin(...)`
- `get_record(source)`
- `list_records()`
- CLI projection: `--list-packages` combines configured `package_roots` with plugin-provided package roots and exposes scope, prompt / skill / extension / theme / diagnostic counts.
- Remote source projection: HTTPS/SSH-style plugin sources can be registered as remote lifecycle records without being resolved as local paths.

## Events

- 当前不单独定义稳定外发事件
- 主要向 `loader` 提供 plugin 解析后的资源描述符

## Key Data

- `PluginManifest`
- `PluginSource`
- `InstalledPlugin`
- `PluginResolvedResources`

## Related Package Data

这些对象由 [package](package.md) 拥有。`plugin` 可以投影或委托使用它们，但不拥有
package lifecycle facade：

- `PackageMaterializer`
- `PackageMaterializationRecord`
- `PackageSourcePolicy`
  - canonical method: `evaluate_package_source(...)`
  - compatibility method: `evaluate_plugin_source(...)`

## Out Of Scope

- hook dispatch
- tool 执行实现
- session 生命周期管理
- prompt assembly
- package lifecycle backend internals; `PackageMaterializer` owns the facade, concrete backends should be treated as package/distribution implementation details

## Design Notes

- `plugin` 是 manifest、source、声明与启停边界，不是新的 runtime 编排中心
- `package` 是资源分发与 lifecycle 边界；两者关系由 `ARD-004` 固定
- `extension` 仍是 runtime 可执行扩展面；`plugin` 中携带的 extension entry 最终仍由 `ExtensionLoader` / `ExtensionRunner` 消费
- 推荐主链路：
  - `PluginSource -> PluginManager -> PluginRegistry -> PluginResolver -> ResourceDescriptors -> DefaultResourceLoader -> ExtensionLoader -> ExtensionRunner -> Session`

## Reference Implementation Alignment

- 对齐 `reference CLI` 中 package / package-manager / resource-plane 的总体方向
- `plugin` 对齐 manifest/source 声明与可选激活语义，但不拥有 Package 分发，也不等同于 `ExtensionAPI`
- `ExtensionAPI` 继续承担作者编程面；`plugin` 把已解析的 package root 投影为 resources
- `package` / `plugin` 在 loushang 中不再视为同义词：package 是资源分发单位，plugin 是 manifest-backed source view。
- Headless MVP 已覆盖本地 plugin source 管理、enabled state、resource 展开与 package list UX；`--list-packages --list-packages-format json` 会标记同名多版本 package/plugin 的 `versionConflict` / `conflictVersions`。
- Offline catalog projection is covered through CLI `--package-catalog <json>`; catalog entries are read locally and projected alongside installed/local packages without performing network install/update.
- Remote plugin source lifecycle is covered through `PackageMaterializer`: `remote_registered` sources can move to
  `materialization_pending`, `installed`, or `failed` records and package projection reflects the current record.
- `PackageMaterializer` intentionally owns lifecycle state, package source policy evaluation, git-backed materialization/update/remove, and an injectable async backend seam.
- Package materialization must evaluate `PackageSourcePolicy` before invoking the backend; denied sources become `failed` / `denied` records and are still visible in package projection.
- Package projection now includes pinned/ref/commit/dirty/update metadata and supports package source filters for prompts/skills/extensions/themes.
- Python package sources use the Python package backend rather than the reference implementation's npm backend; install/update and update-check semantics are covered through
  `pypi:` sources while preserving pinned-version skip behavior.
- Configured package source merging uses package identity instead of exact source strings, so project sources override user sources even when
  the two entries differ only by pinned version/ref syntax.
- Local relative package sources are resolved against their settings scope before identity merging, so `packages/foo` in user and project settings
  can coexist when they point to different directories.
- 剩余 package manager gap 主要是 approval UI 和兼容字段的后续退场。当前未在 reference coding agent 中确认到独立的
  package signature verification 语义；loushang 的 package trust / policy hardening 属于可选增强，不作为 reference parity 阻塞项。
