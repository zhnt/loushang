# `skill`

## Role

- Catalog-backed Skill 查询、状态与正文加载边界

## Owns

- exact-generation Skill Consumer capture
- body-free Skill metadata/status projection
- receipt-bearing asynchronous body load
- settings mutation followed by Catalog refresh

## Depends On

- Resource Catalog
- Session Resource Capability
- `utils`

## Commands

- `load(handle)`
- settings `enable_skill(...)` / `disable_skill(...)` followed by refresh

## Queries

- `get_effective_skill(...)`
- `list_effective_skills()`
- `list_skill_statuses()`

## Events

- 当前无稳定事件面

## Key Data

- `SkillDescriptor`
- `SkillCatalogSummary`
- `SkillCatalogStatusSummary`
- `ResourceLoadReceipt`
- `SKILL.md` frontmatter:
  - `name`
  - `description`
  - `disable-model-invocation`

## Out Of Scope

- method 选择策略
- extension hook 执行
- prompt 最终组装

## Reference Implementation Alignment

- 语义上吸收 `reference CLI` 的 customization / resource discovery 经验
- RCP5.5 已删除独立 `SkillLoader`；Skill 不再拥有私有 discovery、body cache
  或 disabled-name overlay
- 迁移旧 `SkillLoader.list_skills()` / `reload_skills()` 调用时，Session 内部查询改用
  `list_skill_statuses()` 与 captured `SkillCatalogConsumer`；正文执行改用异步
  `/skill:*` preflight。只有明确选择 `legacy_explicit` 的兼容产品才继续通过
  `DefaultResourceLoader.discover_resources()` 读取旧 Bundle
- Session 只从一个 captured Catalog generation 暴露 Skill 查询与正文加载
- `description` 用于 `/skill:name` command 描述与 system prompt 中的 available skills 摘要。
- `disable-model-invocation: true` 让 skill 仍可显式 `/skill:name` 调用，但不会进入模型可自动发现的 skill 摘要。
- skill discovery 递归扫描 `skills/**/SKILL.md`；一旦某目录本身包含 `SKILL.md`，该目录即为 skill root，不再继续向下递归。
- discovery 跳过隐藏目录和 `node_modules`，并读取 `.gitignore` / `.ignore` / `.fdignore` 中的常用目录/路径/glob 忽略规则，避免把依赖、隐藏工作区或生成目录误注册为可用 skill。
