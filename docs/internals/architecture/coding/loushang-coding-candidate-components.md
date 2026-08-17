# Loushang Coding Candidate Components

## Status

Superseded as the current ownership topology by the
[Harness Current Owner Map](../harness/current-owner-map.md). This document is
retained as design history for the original Coding decomposition. Canonical
Product, Capability, Resource Package, Plugin, and Extension terms come from
the [Product And OEM Glossary](../../glossary/loushang-product.md).

## Scope

本文档给出 `loushang-coding` 的候选组件列表，用于设计阶段对齐 `reference coding agent`。

本文档当前假设：

- 语言为 Python
- 目录前缀采用 `loushang/coding/`
- screen UI 已作为 `loushang.coding.ui` product adapter 落地
- 组件识别应同步当前代码包边界，并保留目标架构边界

本文档不讨论：

- 具体文件级实现
- 具体类名与函数签名
- TUI 的详细交互设计

## Design Basis

本轮组件识别主要参考：

- `reference/reference-coding-agent/architecture-dependencies.md`
- `reference/reference-coding-agent/reference-coding-agent-reference.md`

同时结合当前对 `loushang` 分层的约束：

- `loushang-ai` 负责模型接入
- `loushang-agent` 负责 agent runtime core
- `loushang-coding` 负责 coding 产品装配层
- `loushang-coding` 对 `loushang-ai` 保留直接依赖，不只是通过 `loushang-agent` 间接依赖
- `loushang-method` / `loushang-work` 是相邻子系统，coding 只保留 domain bridge 与 work-log integration

## Candidate Components

当前建议的 `loushang-coding` 候选组件为：

- `bootstrap`
- `sdk`
- `cli`
- `mode`
- `runtime`
- `session`
- `store`
- `message`
- `event`
- `tools`
- `exec`
- `prompt`
- `skill`
- `loader`
- `resources`
- `extensions`
- `plugin`
- `package`
- `domain`
- `control`
- `policy`
- `compaction`
- `diagnostics`
- `platform`
- `workflow`
- `utils`

## Component Notes

### `bootstrap`

内部装配中心。

负责：

- 创建共享依赖
- 装配默认运行时对象
- 为 `cli` 与 `sdk` 提供统一入口

### `sdk`

对外嵌入入口层。

负责：

- 向宿主程序暴露 `loushang-coding` 的创建与调用入口
- 复用 `bootstrap` 完成默认装配

### `cli`

命令行进程入口。

负责：

- 参数解析
- 命令分发
- 将 CLI 输入翻译为 mode 启动参数

### `mode`

运行形态适配层。

当前阶段建议列出这些 mode：

- `text`
- `print`
- `json`
- `rpc`
- `tui` / `interactive`

### `runtime`

当前活动 session 的生命周期宿主。

负责：

- 创建 session
- 切换 session
- 恢复 session
- 替换当前活动 session

它主要对应 `reference coding agent` 的 `agent-session-runtime`。

### `session`

单个 coding session 的核心门面。

负责：

- 组织一次 coding session 的运行
- 协调 prompt、tools、loader、policy、compaction
- 管理 session 内部状态与高层动作

它主要对应 `reference coding agent` 的 `agent-session`。

备注：

- 当前不单列 `context`
- 相关职责先由 `session` 协调，并与 `prompt`、`loader`、`compaction` 配合

### `store`

会话持久化与恢复层。

负责：

- transcript 存储
- session metadata
- session summary / cross-session read model
- branch / fork 相关持久化语义
- session 恢复与加载
- 按 cwd / name / parent session / text 查询历史 session

它更接近 `reference coding agent` 的 `SessionManager`，不等同于 `context`。

### `message`

session entry 与 coding-specific custom message 层。

负责：

- `SessionEntry` 及其子类型
- custom agent message family
- coding-specific custom messages
- `SessionEntry` 与 `AgentMessage` 之间的投影辅助
- tool call / tool result 的记录结构

备注：

- 尽量对齐 `reference coding agent`，因此 `message` 不重新定义一套完整基础消息宇宙
- 通用 `AgentMessage` 仍归 `loushang-agent`
- `loushang-coding.message` 更接近 `reference coding agent` 中：
  - `messages.ts`
  - `session-manager.ts` 里的 `SessionEntry` 体系
- 建议显式保留两层：
  - `SessionEntry` family
  - custom agent message family

### `event`

动态运行事件层。

负责：

- session / run lifecycle events
- message streaming events
- tool execution events
- diagnostics-friendly event records

### `tools`

工具系统。

负责：

- 内置工具定义
- 工具注册
- 工具调用路由
- 与 `policy` 协同做能力暴露

### `exec`

命令执行子系统。

负责：

- shell / subprocess 执行
- 执行结果采集
- 与 `policy` 协同处理审批、限制与保护

### `prompt`

提示词装配层。

负责：

- system prompt
- tool prompt
- session prompt
- method/skill 注入后的 prompt 组装

### `skill`

skill 资源与运行接缝。

负责：

- skill 发现
- skill 解析
- skill 注入与使用约束

### `loader`

统一资源加载入口。

负责加载：

- `AGENTS.md`
- prompt 资源
- skill 资源
- extension 资源
- 其他 coding 侧资源文件

### `resources`

coding resource descriptors 与加载结果边界。

负责：

- prompt/skill/theme/extension resource descriptors
- loader/package/plugin 展开后的资源结果
- coding 运行时可消费的资源投影

### `extensions`

扩展运行时。

负责：

- 扩展发现
- 扩展加载
- hook 绑定
- 生命周期管理

备注：

- `extensions` 是 runtime 扩展面
- `plugin` 是 manifest-backed 可选贡献源的身份与启停边界，不取代
  `extensions`，也不是 Package 分发边界

### `plugin`

plugin identity、source、启停与资源根解析层。

负责：

- plugin manifest
- plugin source
- plugin 启停与作用域
- 将 plugin 展开为 extensions / skills / prompts / themes 资源描述符

### `package`

Resource Package lifecycle、source 与物化管理层；Plugin identity 和启停状态
是独立边界。

负责：

- package catalog/source
- package install/update/remove
- package materialization
- package 与 plugin resource 形态的衔接

### `domain`

coding domain bridge。

负责：

- `CodingDomainRequest`
- `MethodPolicy`
- `CodingDomainPreparedTurn`
- 通过 `loushang.method` 应用 method plan/prepared turn
- 将 method plan/step metadata 传递给 work-log path

### `control`

控制平面组件集合。

当前建议吸收：

- settings
- config
- model selection / model registry
- 其他运行控制配置

备注：

- 其中 model selection / model registry 与 `loushang-ai` 存在直接接缝
- `control` 负责在 coding 产品层组织这些控制能力，但不取代 `loushang-ai` 自身的模型与 provider 语义

### `policy`

权限与执行策略层。

负责：

- tool permission
- approval policy
- sandbox / filesystem / network policy
- destructive action guardrails

`policy` 不等同于 `auth`，它更接近 Claude Code 式的权限/审批管理。

### `compaction`

上下文压缩与摘要层。

负责：

- 会话压缩
- 摘要生成
- 上下文预算收缩策略

### `diagnostics`

诊断与检查能力。

负责：

- 配置检查
- 环境检查
- 执行失败归一化
- 可观测诊断输出

### `platform`

平台能力 helper。

负责：

- clipboard
- filesystem
- terminal/platform capability detection
- 跨 mode 共享的平台差异封装

### `workflow`

prompt workflow loader / runner。

负责：

- prompt workflow 文件加载
- workflow step 展开
- 将 prompt workflow 映射到 coding session 调用

### `utils`

真正通用、无稳定业务边界的辅助代码。

约束：

- 不承载核心业务职责
- 只放跨组件复用的轻量工具

## Current Orientation

### Core Skeleton

当前 coding 产品的骨架组件：

- `bootstrap`
- `sdk`
- `cli`
- `mode`
- `runtime`
- `session`
- `store`
- `message`
- `event`
- `tools`
- `exec`
- `prompt`
- `resources`
- `loader`
- `domain`
- `control`
- `policy`
- `diagnostics`
- `platform`
- `utils`

当前 mode / surface：

- `text`
- `print`
- `json`
- `rpc`
- `tui` / `interactive`

### Productization And Extension Components

当前产品化与扩展组件：

- `skill`
- `extensions`
- `compaction`
- `plugin`
- `package`
- `workflow`

### Later Directions

后续增强方向：

- TUI + method status layer
- 更强的 extension/plugin 生态
- 更复杂的方法编排
- multi-agent / orchestration 扩展

## Open Decisions

当前仍保留的设计决策包括：

- 是否未来将 `control` 再拆分为 `settings` / `config` / `model`
- 是否未来为 orchestration / multi-agent 单列组件
- 是否未来将 `session` 内的 context 相关职责再抽成独立 `context`
