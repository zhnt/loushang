# ARD-001: Loushang Coding Product Boundaries

## Status

Superseded as the canonical Current Coding topology.

This ARD is retained as a historical decision record for the original Coding
Product boundary. Its Coding-owned shared component list and mode placement
predate the completed Harness/HarnessTUI migration. Current placement and
ownership are defined by:

- [Coding Architecture](README.md);
- [Coding System Context](loushang-coding-system-context.md);
- [Harness Current Owner Map](../harness/current-owner-map.md);
- [Harness Mode/Host Boundary](../harness/mode-host-boundary.md).

Stable Product principles preserved by those replacements remain valid; this
file must not be read as a current source/module inventory.

## Context

`loushang-coding` 当前是 V1 coding 产品主承载层。早期目标是：

- 参考 `reference coding agent`
- 使用 Python 实现
- 先设计完整组件边界，再分阶段实现

截至当前实现，headless CLI/mode、session/runtime/store、extensions、tools、
diagnostics、package/plugin、screen TUI、method-guided non-interactive path 与
work-log/projection 都已有主干。`--method` 与 TUI/RPC 仍保持互斥，原因见
[ARD-006](./ARD-006-tui-method-integration-constraints.md)。

同时，`loushang` 总体架构中已经存在这些相邻子系统概念：

- `loushang-ai`
- `loushang-agent`
- `loushang-tui`
- `loushang-method`
- `loushang-work`
- `loushang-coding`

`loushang-channel` 仍是目标架构层，但当前没有 package-level implementation。

在讨论中出现了几个需要尽早钉住的边界问题：

- `loushang-coding` 的候选组件列表是什么
- `context` 是否当前就单列
- `channel` 是否应并入 `coding`
- `coding` 前期是否必须依赖 `channel`
- `print/json/rpc/interactive` 如何归类
- `tui` 与 `coding` 的边界如何处理
- `coding` 是否只通过 `agent` 间接依赖 `ai`

## Decision

### 1. `loushang-coding` 的候选组件列表

当前接受以下候选组件列表：

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

`method` 不再作为 `loushang.coding` 内部独立 registry 组件表达；当前由
`loushang.method` 承载 method 资源、编译与投影，`loushang.coding.domain`
负责把 method plan/prepared turn 应用到 coding turn。

### 2. 当前不单列 `context`

当前阶段不把 `context` 作为 `loushang-coding` 的独立顶层组件。

相关职责先由以下边界协同承接：

- `session`
- `prompt`
- `loader`
- `compaction`

后续如果 session 内部的上下文选择、投影、working set 组装明显膨胀，再考虑单独拆出 `context`。

### 3. `mode` 是 `loushang-coding` 的核心组件

当前接受以下 mode / product surface 列表：

- `text`
- `print`
- `json`
- `rpc`
- `tui` / `interactive`

其中：

- `text` / `print` / `json` / `rpc` 属于 headless / non-interactive 运行形态
- `tui` / `interactive` 已由 native terminal core 和 `loushang.coding.ui` 承载
- 在架构对象层，`json` 当前应视为 `PrintMode` 的结构化输出 projection，而不是独立 `JsonMode`

**关于 `rpc` mode 的长期定位**：

`rpc` mode 当前作为 `loushang-coding` 的 headless control adapter 实现（`loushang.coding.mode.RpcMode`），是一个 **transitional surface**。它直接暴露 coding session 控制命令（prompt、abort、fork、set_model 等），服务于测试、SDK host、CI/CD 和第三方工具集成。

但 `rpc` mode **不是**长期 channel surface。JSONL request/response framing、id correlation、event stream projection 等机制有价值且应长期保留，但未来归属于 `loushang.channel` 下的 `rpc_jsonl` adapter，面向 `WorkOperation/WorkEvent` 语义，而非直接操作 `AgentSession`。

详见 [ARD-005: RpcMode Transitional Positioning and Channel Migration Path](./ARD-005-rpc-mode-transitional-channel-positioning.md)。

### 4. `sdk` 保留为对外入口层

`sdk` 不只是内部辅助文件，而是 `loushang-coding` 的对外嵌入入口层。

其职责是：

- 暴露可嵌入的 coding runtime 创建入口
- 复用 `bootstrap` 的默认装配能力

### 5. `loushang-channel` 不并入 `loushang-coding`

`loushang-channel` 不作为 `loushang-coding` 的内部组件。

原因：

- `channel` 的职责是边界协议与 transport 语义
- `coding` 的职责是 coding 产品装配
- `channel` 是跨产品的稳定协议层，不应被 coding-specific 语义吞并

因此：

- `loushang-channel` 仍保持独立子系统定位
- `loushang-coding` 未来可依赖 `channel`
- 但 `channel` 不进入 `coding` 的候选组件列表

### 6. `loushang-coding` 直接依赖 `loushang-ai`

`loushang-coding` 不只是通过 `loushang-agent` 间接依赖 `loushang-ai`，还保留对 `ai` 的直接依赖。

主要原因是，参考 `reference coding agent`，coding 产品层会直接消费一部分 AI 能力，例如：

- model registry / model selection
- direct summarization / compaction requests
- 某些 helper-style AI 调用

因此，当前接受的关系是：

- `loushang-coding -> loushang-agent`
- `loushang-coding -> loushang-ai`
- `loushang-agent -> loushang-ai`

### 7. `loushang-coding` 前期不依赖 `channel`

前期实现 `loushang-coding` 时，不要求先实现 `loushang-channel`。

这意味着：

- 没有 `channel` 也不影响 `coding` 起步
- `print mode`、`json mode`、`rpc mode` 可以先直接基于 `session/runtime/event` 工作
- 后续如果边界协议、审计、回放、跨客户端一致性需求成熟，再引入 `channel`

### 8. `print mode` 是输出适配层，不是 `channel`

`print mode` 的职责是把运行事件投影到 stdout/stderr 或结构化输出。

它属于：

- `coding` 的 mode adapter

它不属于：

- `channel` 协议层

### 9. `loushang-tui` 与 `coding` 保持分层

`loushang-tui` 代表独立的终端交互子系统，不并入 `loushang-coding`。

边界建议为：

- `coding` 负责 TUI product adapter、session/runtime 流程编排、命令和 coding-specific 状态
- `tui` 负责 terminal-native UI primitives、render loop、input、surface、layout 与编辑基础设施

当前目标实现是 native terminal core，不是 Textual/fullscreen 方案。旧 Textual /
prompt-toolkit/Rich 设计只保留在 TUI history 文档中。

但约束是：

- 对齐 terminal-native TUI 的职责边界
- 不要求逐字 API 兼容
- 更强调语义兼容与 Python 化实现

### 10. `coding` 是产品线，不是通用 agent/work/method 层

`loushang-coding` 与 future `loushang.research`、`loushang.ppt`、
`loushang.cowork` 是并列产品线。`cowork` 在这里表示一个 future product
vertical，不是 `work` 的协作语义层名称。

因此：

- `coding` 可以直接使用 `loushang.harness` 执行普通 headless agent run
- `coding` 使用 `loushang.harness.commands` 的 product-neutral
  command/effect/catalog 能力，并通过
  `loushang.harnesstui.commands.catalog.ConversationCommandCatalog`
  绑定会话命令；
  Coding 只保留产品命令选择、最终 UI action 和产品措辞
- `coding` 可以直接写入或投影到 `loushang.work`
- `method` 是结构化 / guided work 的可选组织层，不是所有 coding turn 的必经层
- `coding` 不应把自己的 tools、slash commands、`AGENTS.md` prompt
  projection、TUI adapter、package/plugin/extension policy 上提到 `agent`；
  标准 `AGENTS.md` discovery 与资源机制属于 `harness.resources`

详见
[Agent Harness and Product Adapter Boundaries](../agent/ARD-001-agent-harness-and-product-adapters.md)。

### 11. 共享代码机制与 Coding 专属可挂载 Capability 分离

每个 Product 都可以具备适合自己的代码能力，但并非每个 Product 都是 Coding
Product。read、list、search、write、edit 和进程执行的公共契约、实现与不可绕过
执行边界属于顶层 Capability ID `harness.workspace`；这些操作是其内部 facet，
不是独立 DAG 节点。Coding 只选择其缺省 pack、产品文案、允许根、权限、审批、
Sandbox、激活和呈现策略。

当前 Coding 专属的可挂载 Capability ID 只有：

- `coding.arch`：Coding 的仓库 import-graph 分析语义与工具面；
- `coding.lsp`：Coding 的 language-server 选择、文档同步、生命周期与工具语义。

`coding.lsp` 与 `coding.arch` 都可以声明对 `harness.workspace` 的窄 facet 依赖。
未来 `coding.arch` 可以通过显式 optional dependency 消费 `coding.lsp` 的语义
事实，但当前不得形成硬依赖，确定性 analyzer 和 CI gate 必须可独立运行。依赖图
统一使用 `A -> B` 表示 A 依赖 B；具体 port、adapter、provider 或权限名称不作为
公共依赖身份。

其他 Product 不应为了获得 read/write/edit 或受限脚本执行而依赖
`loushang.coding`。反过来，这份 mountable Capability inventory 也不表示 Coding
只有两个 Product 专属关注点；Coding Prompt、仓库/Git 工作流、Session 兼容性、
诊断、Artifact 和呈现仍属于 Coding Product Kernel。

Capability ID、Mount 实例、内部 Binding Facet 与依赖图规则见
[Capability Dependency And Mount Lifecycle](../harness/capability-dependency-and-mount-lifecycle.md)。

## Rationale

本次决定采用“先稳住产品骨架，再后置跨边界协议层”的策略，理由是：

1. 当前 `loushang-coding` 的优先目标是镜像 `reference coding agent` 的产品装配主干。
2. `channel` 是长期有价值的边界层，但不是 `coding` 起步的前置条件。
3. 过早把 `channel` 并入 `coding`，会污染分层并让 `coding` 过厚。
4. 参考 `reference coding agent`，`coding` 产品层不仅装配 `agent`，也会直接依赖部分 `ai` 能力，因此系统环境图必须显式保留 `coding -> ai`。
5. 过早单列 `context`，会增加边界数量，但当前其职责仍可被 `session/prompt/loader/compaction` 稳定承接。
6. 明确保留 `sdk`、`mode`、`tui/interactive`，有利于从 CLI 扩展到嵌入式、RPC 与 TUI。

## Consequences

### Positive

- `loushang-coding` 可以先独立推进，不被 `channel` 阻塞
- 组件列表更贴近 `reference coding agent`
- `mode`、`sdk`、`runtime`、`session` 的主干更清楚
- `coding -> ai` 的直接依赖被显式保留，后续 model registry / summarization 等设计更容易落位
- `channel` 与 `tui` 的长期独立价值被保留

### Negative

- 早期不同 mode 可能会暂时重复做一部分边界投影逻辑
- 后续引入 `channel` 时，可能需要把 `rpc/web/interactive` 的部分适配逻辑上提
- `context` 暂不单列，意味着 `session` 设计时需要更克制地控制体积

## Impacted Documents

- `docs/internals/architecture/coding/loushang-coding-candidate-components.md`
- `docs/internals/architecture/coding/loushang-coding-system-context.md`
- `docs/internals/architecture/subsystem.md`
- `docs/internals/architecture/agent/loushang-agent-system-context.md`
- `docs/internals/legacy/loushang-channel-boundary-protocol.md`

## Follow-up

- 后续补一份 `loushang-coding` 分阶段实现建议
- 后续在 TUI + method 集成阶段，按 ARD-006 决定 method status layer 与 WorkEvent projection
- 后续在 `rpc/web` 需求稳定后，再决定 `loushang-channel` 的落地时机
- `rpc` mode 的长期定位与迁移路径参见 [ARD-005](./ARD-005-rpc-mode-transitional-channel-positioning.md)
