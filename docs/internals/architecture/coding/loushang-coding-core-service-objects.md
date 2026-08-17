# Loushang Coding Core Service Objects

## Scope

本文档给出 `loushang-coding` 的核心服务对象清单。

本文档目标是回答：

- `loushang-coding` 的核心服务对象有哪些
- 这些服务对象分别归属哪个组件
- 哪些对象应优先对齐 `reference coding agent` 命名
- 哪些对象当前没有直接对齐物，以及原因是什么

本文档不展开：

- 详细方法签名
- 详细依赖图
- 详细时序
- 具体模块路径

## Design Basis

本文档建立在以下文档之上：

- [Loushang Coding System Context](loushang-coding-system-context.md)
- [Loushang Coding Component Structure And Responsibilities](loushang-coding-component-structure-and-responsibilities.md)
- [Loushang Coding Core Data Objects](loushang-coding-core-data-objects.md)
- [reference coding agent Internal Dependency Overview](reference/reference-coding-agent/architecture-dependencies.md)
- [reference coding agent 架构分析](reference/reference-coding-agent/reference-coding-agent-reference.md)

## Naming Rule

当前接受的命名规则是：

- 服务对象优先对齐 `reference coding agent` 命名
- 如果 `reference coding agent` 已有稳定中心对象名，则优先复用
- 如果当前语义在 `reference coding agent` 中没有清晰的一等服务对象，则保留 `loushang-coding` 的候选命名
- 对所有未直接对齐项，必须写明理由

## Service Classification

当前建议把 `loushang-coding` 的核心服务对象分为五类：

1. 装配与入口服务
2. 运行时核心服务
3. 资源与扩展服务
4. 控制平面服务
5. 支撑服务

## 1. 装配与入口服务

### `Bootstrap`

归属组件：

- `bootstrap`

角色：

- 内部装配中心

主要职责：

- 创建共享服务对象
- 装配默认 runtime
- 为 `sdk` / `cli` / `mode` 提供统一构造入口

对齐情况：

- 不直接对齐 `reference coding agent` 的单一对象

理由：

- `reference coding agent` 的装配职责分散在：
  - `main.ts`
  - `agent-session-services.ts`
  - `sdk.ts`
- `Bootstrap` 是 `loushang-coding` 为 Python 设计收敛出的统一装配名
- 该名字保留的理由是：它能把 `reference CLI` 的多处装配链收束成一个更适合 Python 的内部入口对象

### `SDK`

归属组件：

- `sdk`

角色：

- 对外嵌入入口服务

主要职责：

- 向宿主暴露 coding runtime 创建入口
- 对外暴露高层嵌入 API

对齐情况：

- 对齐 `sdk.ts`

备注：

- 这里的 `SDK` 表示服务层入口，不要求最终一定以类实现

### `CLI`

归属组件：

- `cli`

角色：

- 命令行入口服务

主要职责：

- 参数解析
- 命令分发
- mode 启动

对齐情况：

- 对齐 `cli/*` + `main.ts` 入口表面

## 2. 运行时核心服务

### `AgentSessionRuntime`

归属组件：

- `runtime`

角色：

- 当前活动 session 的生命周期宿主

主要职责：

- 创建 session
- 切换 session
- 恢复 session
- 替换当前 session

对齐情况：

- 直接对齐 `AgentSessionRuntime`

备注：

- 这里最重要的是 lifecycle host 语义
- 是否额外携带 cwd-bound services、diagnostics 等载荷，可以按实现形态调整

### `AgentSession`

归属组件：

- `session`

角色：

- mode-neutral core facade

主要职责：

- 运行单个 coding session
- 协调 prompt、tools、policy、compaction、resources
- 驱动 `loushang-agent`
- 暴露高层 session 控制动作

对齐情况：

- 直接对齐 `AgentSession`

备注：

- 即使将 compaction、policy、tools、prompt 等横切能力显式拆成协作者
- `AgentSession` 仍应保持业务中心与 mode-neutral orchestration center 的语义

### `SessionManager`

归属组件：

- `store`

角色：

- session persistence 服务

主要职责：

- session 读写
- transcript 持久化
- branch / fork / restore
- metadata 维护

对齐情况：

- 直接对齐 `SessionManager`

备注：

- 除 append-only transcript tree 外，还应保持 `custom` / `custom_message` / branch summary / compaction 等 entry family 的分层语义
- `build_session_context()` 仍是 store 侧的重要职责

### `ModeAdapter`

归属组件：

- `mode`

角色：

- 某一种 mode 的适配服务抽象

主要职责：

- 把统一 session/runtime 语义映射到具体 I/O 表面

承担对象：

- `PrintMode`
- `RpcMode`
- `InteractiveMode`（未来）
- `PrintMode` 的 `json` 输出投影

对齐情况：

- 部分对齐 `InteractiveMode` / `runPrintMode` / `runRpcMode`
- 其中 `json` 语义应对齐 `runPrintMode(...)` 的结构化输出分支，而不是独立 `JsonMode`

理由：

- `reference coding agent` 没有统一命名的 `ModeAdapter` 一等服务对象
- 但确实存在一组 mode adapter 实现
- 这里保留 `ModeAdapter` 作为结构化总称，便于 Python 设计时统一讨论 mode 服务对象
- 其中 `PrintMode` / `RpcMode` 表示 mode-level service boundary，不要求最终一定以类实现

## 3. 资源与扩展服务

### `DefaultResourceLoader`

归属组件：

- `loader`

角色：

- Harness 平台资源发现与加载服务的 Coding facade

主要职责：

- 注册 Coding 内置资源内容
- 选择标准/兼容 conventions、附加 roots 与 settings filters
- 注入 Coding trust、权限和默认激活策略
- 将 Harness resource snapshot 聚合为 Coding 运行时投影

对齐情况：

- 查询语义对齐 `DefaultResourceLoader`；扫描、provenance、merge 与 package
  materialization 的实现 owner 是 `loushang.harness.resources`

备注：

- `ExtensionLoader` / `SkillLoader` 等可保留为产品投影子边界
- `DefaultResourceLoader` 应成为小型 facade，不保留第二套通用资源引擎

### `ExtensionRunner`

归属组件：

- `extensions`

角色：

- 扩展执行侧协调服务

主要职责：

- 绑定 session actions
- 分发 extension hooks
- 管理扩展运行时生命周期

对齐情况：

- 直接对齐 `ExtensionRunner`

### `ExtensionLoader`

归属组件：

- `extensions`

角色：

- 扩展发现与加载服务

主要职责：

- 从资源中发现扩展
- 将扩展定义转换为可运行对象

对齐情况：

- 语义上对齐 `extensions/loader.ts` 对应的 loader 语义

备注：

- 在整体结构上，它更适合作为 `DefaultResourceLoader` 下的显式子服务边界
- 不必被误读为独立于 resource hub 的另一套中心对象

### `SkillLoader`

归属组件：

- `skill`
- `loader`

角色：

- skill 发现与解析服务

主要职责：

- skill 扫描
- frontmatter 解析
- skill 文本加载

对齐情况：

- 不直接对齐 `reference coding agent` 的单一显式中心对象

理由：

- `reference coding agent` 把 skills 更强地收束在 resource loader 体系中
- 当前保留 `SkillLoader`，是为了让 Python 设计中 skill 边界更清楚
- 后续如果过重，可并回 `DefaultResourceLoader`
- 它更适合作为 resource loader 体系内的显式子边界，而不是并列资源中心

### `CodingDomainApp`

归属组件：

- `domain`

角色：

- coding domain method integration facade

主要职责：

- 接收 `CodingDomainRequest`
- 应用 `MethodPolicy`
- 调用 `loushang.method` 的 loader/compiler/projector
- 生成一个或多个 `CodingDomainPreparedTurn`
- 将 `method_id` / `plan_id` / `step_id` / step metadata 传递给 CLI runner 与 work-log path

对齐情况：

- 不直接对齐 `reference coding agent` 的一等对象

理由：

- `reference CLI` 更偏 `skills + prompt/resources + extension`
- `method` 是 `loushang` 当前特有的显式子系统边界，归属 `loushang.method`
- `loushang.coding` 只保留 domain bridge，不拥有 method registry lifecycle

## 4. 控制平面服务

### `SettingsManager`

归属组件：

- `control`

角色：

- settings 管理服务

主要职责：

- 读取/合并/持有 settings
- 为 session/runtime/mode 提供设置访问
- 提供 compaction / branch summary 配置切片

对齐情况：

- 直接对齐 `SettingsManager`

### `ModelRegistry`

归属组件：

- `control`

角色：

- model 目录与选择支撑服务

主要职责：

- model 查询
- model selection 支撑
- 与 `loushang-ai` 的 model registry 能力接缝

对齐情况：

- 直接对齐 `ModelRegistry`

备注：

- 这里是 `coding` 侧持有或使用的 model registry 服务，不取代 `loushang-ai` 自身的 provider/model 语义
- `control` 组件表达的是这些控制面服务的聚合边界，不要求对齐成 `reference CLI` 的单一中心对象

### `AuthStorage`

归属组件：

- `control`

角色：

- 认证与凭证持有服务

主要职责：

- 凭证读取
- 凭证持有
- 为 AI/provider 相关路径提供认证输入

对齐情况：

- 直接对齐 `AuthStorage`

### `PolicyEngine`

归属组件：

- `policy`

角色：

- 权限与审批判定服务

主要职责：

- allow / deny / ask 判定
- destructive action guardrails
- execution policy 判定

对齐情况：

- 不直接对齐 `reference coding agent` 的单一稳定对象

理由：

- `reference coding agent` 当前参考里有相关语义，但没有显式单一服务对象名
- 对 `loushang-coding` 而言，这是一块值得显式保留的服务边界
- mode 可以承接审批交互，但 `PolicyEngine` 自身应保持 mode-neutral

## 5. 支撑服务

### `ToolRegistry`

归属组件：

- `tools`

角色：

- definition-first 的工具定义注册服务

主要职责：

- 管理 `ToolDefinition`
- 管理 registered / enabled definition 集合
- 向 `session`、prompt、UI 暴露 definition 查询面
- 在需要时把 `ToolDefinition` materialize 成 runtime `AgentTool`

对齐情况：

- 部分对齐 `ToolDefinitions / ToolRegistry`

理由：

- `reference coding agent` 参考明确存在 `ToolDefinition`、definition query 面、以及 `ToolDefinition -> AgentTool` wrapper seam
- `reference CLI` 的中心更接近 `AgentSession` 内部的 `_toolDefinitions` 与 `_toolRegistry` 双层结构，而不是单一 registry bag
- 这里保留 `ToolRegistry` 这个名字，是为了把“定义注册”边界稳定下来；当前 session 的 active tools 仍归 `AgentSession`

### `ExecService`

归属组件：

- `exec`

角色：

- 命令执行服务

主要职责：

- shell / subprocess 执行
- 输出采集
- 承接 caller 已完成的执行决策与边界约束

对齐情况：

- 不直接对齐 `reference coding agent` 的单一服务对象

理由：

- `reference coding agent` 更像把 bash/read/edit/write 等能力放在 tool layer 内
- `loushang-coding` 当前保留 `ExecService`，是为了给 Python 实现中的命令执行边界留出明确位置
- `PolicyEngine` 与 `ExecService` 可协同，但不要求把 policy 内嵌进 exec service

### `PromptAssembler`

归属组件：

- `loushang.harness.capabilities.prompt_assembly`
- `coding.prompt` 仅保留默认值与公共导入兼容适配

角色：

- 提示词装配服务

主要职责：

- 组装 system prompt
- 组装工具提示
- 汇入资源与方法注入

对齐情况：

- 不直接对齐 `reference coding agent` 的单一服务对象

理由：

- `reference coding agent` 的 prompt assembly 分散在 `AgentSession`、`system-prompt`、resource loader 之间
- 标准资源、skill、tool 与 runtime footer 组装并非 Coding 独有，canonical 实现归 Harness
- Coding 只注入 `DEFAULT_CODING_SYSTEM_PROMPT`，不复制通用组装或 preflight 实现
- 该服务仍是显式桥接层，而不取代资源加载器的发现与聚合职责

### `CompactionCoordinator`

归属组件：

- `compaction`

角色：

- 压缩与摘要协调服务

主要职责：

- 判断手动 / threshold / overflow 等 compaction 触发条件
- 准备 cut point、summary 输入与预算边界
- 调用 summarization generator 生成 compaction 结果
- 将 compaction 结果回填 session/store，并触发上下文重建
- 暴露运行状态与 abort 能力

对齐情况：

- 不直接对齐 `reference coding agent` 的单一服务对象

理由：

- `reference coding agent` 明确有 compaction / summarization 层
- 但当前参考文档仍主要是职责簇，不是单名中心对象

### `DiagnosticsService`

归属组件：

- `diagnostics`

角色：

- 诊断服务

主要职责：

- 配置检查
- 环境检查
- 执行问题归一化

对齐情况：

- 不直接对齐 `reference coding agent` 的单一服务对象

理由：

- `reference coding agent` 有 diagnostics 关注点，但当前参考未显示一个统一命名中心对象

## Primary Service Backbone

如果只看第一批必须稳定下来的核心服务对象，建议优先保留这组：

- `Bootstrap`
- `SDK`
- `CLI`
- `AgentSessionRuntime`
- `AgentSession`
- `SessionManager`
- `SettingsManager`
- `ModelRegistry`
- `AuthStorage`
- `DefaultResourceLoader`
- `ExtensionRunner`
- `ToolRegistry`

## Strongly Aligned With reference coding agent

以下服务对象建议强对齐 `reference coding agent` 命名：

- `AgentSessionRuntime`
- `AgentSession`
- `SessionManager`
- `SettingsManager`
- `ModelRegistry`
- `AuthStorage`
- `DefaultResourceLoader`
- `ExtensionRunner`

这些对象之所以应优先对齐，是因为：

- 它们在 `reference coding agent` 中已经是稳定中心对象
- 它们构成了最关键的装配链与运行时骨架
- 后续若与 `reference coding agent` 做对照实现，这些对象名最值得保持一致

## Intentionally Not Fully Aligned

以下服务对象当前不完全对齐 `reference coding agent` 单一对象名，但保留有明确理由：

- `Bootstrap`
  - `reference CLI` 的装配职责分散在多个入口文件与工厂函数中

- `ModeAdapter`
  - `reference CLI` 有 mode 实现，但没有统一抽象名

- `SkillLoader`
  - `reference CLI` 更倾向并入 resource loader 体系

- `MethodRegistry`
  - `method` 是当前 `loushang` 特有的显式边界

- `PolicyEngine`
  - `reference CLI` 语义存在，但未见稳定单名中心对象

- `ToolRegistry`
  - `reference CLI` 有 tool registry 语义，但当前参考没有明确单一对象名

- `ExecService`
  - `reference CLI` 更像把这层压在工具执行里

- `PromptAssembler`
  - `reference CLI` 更像是职责分散协同，而非单名服务对象

- `CompactionCoordinator`
  - `reference CLI` 有清晰层次，但当前参考不表现为统一中心类

- `DiagnosticsService`
  - `reference CLI` 有相关关注点，但当前参考未给出单一服务对象名

## Next Step

基于当前服务对象清单，后续建议继续：

1. 组件接口
2. 组件依赖关系
3. 关键 mode 的时序
