# `resource-descriptors`

## Scope

- prompt、skill、theme、extension、package resource 与 provenance 描述对象

## Objects

### `SkillDescriptor`

归属组件：

- `loushang.harness.resources`；Coding 的产品 runtime 直接消费该类型

角色：

- skill 描述对象

承担语义：

- skill identity
- metadata
- source location
- activation constraints

### `ResourceBundle`

归属组件：

- `loushang.harness.resources`；Coding 的产品 runtime 直接消费该类型

角色：

- loader 聚合出的运行资源集合对象

承担语义：

- prompts
- skills
- extensions
- themes
- `AGENTS.md`
- package resource summaries
- resource diagnostics

### `ExtensionDescriptor`

归属组件：

- `loushang.harness.resources`；`coding.extensions` 保留运行时投影

角色：

- 扩展描述对象

承担语义：

- extension identity
- load target
- hook capabilities

### `PackageResourceSummary`

归属组件：

- `loushang.harness.resources`

角色：

- package/plugin 提供的资源汇总对象

承担语义：

- package identity
- package source/provenance
- prompt / skill / extension / theme counts
- resource diagnostic counts

## Reference Implementation Alignment

- `ResourceBundle`、`SkillDescriptor`、`ExtensionDescriptor`、`PackageResourceSummary` 当前不直接复用 `reference CLI` 的统一导出对象名

## Notes

- 这组跨产品对象由 Harness 拥有，服务于 Product loader / skill /
  extensions / plugin / package adapters 之间的资源交换
- `MethodDescriptor` / `MethodPlan` / `MethodStep` 归属 `loushang.method`，不再作为 `loushang-coding` resource descriptor 拥有对象
