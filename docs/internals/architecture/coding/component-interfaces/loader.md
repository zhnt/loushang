# `loader`

## Role

- Coding 对 `loushang.harness.resources` 平台资源运行时的产品适配层

## Owns

- `DefaultResourceLoader` compatibility/configuration facade
- `PackageResourceSummary`
- `ResourceBundle`
- `loushang.coding.resources` 内置内容注册
- standard/compatibility convention 的选择与默认激活
- Coding 附加 roots、settings filters、trust/approval policy 的注入
- 配置到单次 Catalog input receipt 的规范化
- 已发布 Catalog projection 的只读兼容转发

标准根、目录布局、`AGENTS.md` discovery、descriptor、扫描、provenance、
merge、diagnostics 与 package materialization 由 `loushang.harness.resources`
拥有。

## Depends On

- filesystem
- `control`
- `loushang.harness.resources`

## Commands

- `prepare_catalog_input_receipt(...)`
- `adopt_catalog_projection(...)`
- 显式 legacy compatibility 才可调用 `discover_resources(...)` /
  `reload_resources(...)`

## Queries

- `get_resource_bundle()`
- `get_skills()`
- `get_prompts()`
- `get_agents_files()`
- `get_append_system_prompt()`
- `get_system_prompt(...)`
- `get_extensions()`
- `get_resource_diagnostics(...)`
- `get_package_resource_summaries()`

## Events

- 无

## Key Data

- Harness-owned `ResourceBundle`
- Harness-owned `PackageResourceSummary`
- 资源 descriptor provenance：
  - `source`: 原始来源类型，当前主要为 `filesystem`
  - `source_kind`: `built_in` / `project_local` / `external_package`
  - `source_scope`: `builtin` / `project` / `package`
  - `source_root`: 资源所在类别目录，例如 package 的 `prompts/`、`skills/`、`extensions/`

## Out Of Scope

- prompt 最终组装
- session 生命周期
- skill / extension 执行逻辑
- 标准资源根与目录解析
- 通用 filesystem/package discovery 与 merge engine

## Reference Implementation Alignment

- 默认路径的 `DefaultResourceLoader` 只准备 source receipt，并在发布后转发
  exact Catalog projection；不导入或执行 legacy effective-selection pipeline
- 每个 loader 实例只允许单调选择一次 Catalog 或显式 legacy 权威；准备、发布或
  回滚失败不会让同一实例切换到另一条路径，未发布 Catalog 查询返回有限错误
- `BootstrapServices` 的共享 loader 只保存配置与准备 input receipt；每个 Catalog
  Session 都创建独立 compatibility view，projection 发布/回滚不会跨 Session 串写
- 保留显式 Coding loader adapter，避免产品配置散落进 bootstrap 或 session
- Harness loader 是 package provenance 的源头；Coding session / RPC / CLI
  只做产品投影，不重新推断 package 来源
- theme discovery 对齐 参考实现的资源诊断语义：themes 目录下非 `.json` 文件会跳过并记录
  `unsupported_theme_entry` warning，而不是作为 theme descriptor 暴露
- loader 查询面对齐 `reference CLI` 的资源读取面：Harness 负责
  `AGENTS.md` resource discovery，Coding facade 负责 append system prompt
  fragments 和 assembled system prompt 投影，供 runtime/RPC 复用
- package roots 不再静默失败：missing / invalid / empty package root 会产生稳定 resource diagnostic
- package summary 查询面提供 prompt / skill / extension / theme / diagnostic 计数，后续 CLI/RPC/TUI 只做展示投影
