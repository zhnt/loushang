# ARD-005: RpcMode Transitional Positioning and Channel Migration Path

## Status

Superseded.

The transition described here completed by removing `coding.mode` and placing
Product command JSONL under `loushang.harness.host.rpc`. Channel's
`rpc_jsonl` remains a separate Work/runtime-view boundary adapter. Current
authority:

- [Harness Mode/Host Boundary](../harness/mode-host-boundary.md);
- [Harness Session/RPC Operation Boundary](../harness/session-rpc-operation-boundary.md);
- [Channel RPC JSONL Boundary](../channel/rpc-jsonl-boundary.md).

The remainder of this ARD is retained as migration rationale and historical
protocol comparison, not Current architecture.

## Context

`loushang.coding.mode.RpcMode` 自 ARD-001 以来被归类为 `loushang-coding` 的 core mode adapter，与 `print`、`json`、`interactive` 并列。当前实现位于 `src/loushang/coding/mode/rpc_mode.py`，是一个 JSONL-over-stdio 的 headless control surface，支持 prompt、abort、steer、fork、set_model、get_messages、package lifecycle 等命令。

随着 `loushang.work`、`loushang.method` 和 `loushang.channel` 的架构设计推进，出现以下需要明确的问题：

1. `RpcMode` 究竟是长期 channel surface，还是 transitional coding adapter？
2. 如果是 transitional，哪些资产可以迁移到未来的 `loushang.channel`，哪些必须留在 coding domain？
3. 当前 `RpcMode` 直接操作 `AgentSession` / `AgentSessionRuntime`，这是否与 channel 层的设计原则冲突？
4. 在 `loushang.channel` 落地之前，`RpcMode` 的演进策略是什么？

## Decision

### 1. RpcMode 当前定位为 transitional coding mode adapter

`RpcMode` **不是**长期 channel surface。它是一个已经验证有价值的 headless host/control adapter，服务于：

- 测试自动化（playback、smoke、regression）
- SDK host / 外部脚本集成
- CI/CD 场景下的无头 coding session 控制
- 第三方工具（编辑器插件、IDE extension）的临时集成面

### 2. RPC/JSONL 协议形态可以长期存在，但归属发生变化

JSONL request/response framing、id correlation、event stream projection 等机制 **可以长期保留**，但未来应归属于 `loushang.channel` 下的一个具体 channel adapter，而非 `loushang.coding.mode`。

具体归属变化：

| 当前归属 | 未来归属 | 说明 |
|---------|---------|------|
| `loushang.coding.mode.RpcMode` | legacy/compat adapter | 当前实现保留为 coding-local 兼容面，不直接升级为 channel |
| JSONL framing | `loushang.channel.rpc_jsonl` (新增) | 传输机制可复用，语义面向 WorkOperation/WorkEvent |
| id correlation | `loushang.channel` message envelope | 升级为跨 channel 的通用关联机制 |
| event stream delivery | `WorkEvent -> ChannelOutbound` | 当前 projected session event schema 保留为 legacy，不原样迁移 |
| extension_ui_request/response pattern | `ChannelInteractionRequest/Response` + `ChannelCapability` | request/response 协议对象与 capability 声明分开建模 |

### 3. 明确区分"可迁移机制"、"可迁移语义能力"与"legacy command shape"

当前 `RpcMode` 的旧 command table 不应约束未来 channel 协议。但其中部分能力语义会在
`work`、host API、domain operation 或 channel interaction 中重新出现。

#### 可迁移机制（沉淀到 `loushang.channel`）

- JSONL request/response framing
- id correlation（request/response/event 关联）
- minimal ACK policy（preflight accepted，后续结果走 event stream）
- event stream delivery 机制
- rendered tool event 的展示契约经验
- extension interaction 的 request/response 交互模式
- canonical snapshot projection 的原则

这些机制迁移时必须重新投影到 `WorkEvent` / channel event payload。当前 RPC 的
projected session event schema、rendered payload shape 和 state response shape 只作为
legacy compatibility contract，不作为 channel payload 的直接来源。

#### 可迁移语义能力（通过新对象重新表达）

| 当前 RpcMode command shape | 未来语义归属 | 说明 |
| --- | --- | --- |
| `prompt` / `steer` / `follow_up` / `abort` | `WorkOperation` / `WorkRun` control | 不再直接调用 `AgentSession`，而是提交或控制 work run |
| `fork` / `clone` / `new_session` / `switch_session` | host/work session addressing 或 run/session lifecycle API | 旧 command 不迁移，但 resume/switch/fork 语义仍需要长期存在 |
| `get_state` / `get_messages` / `get_session_stats` | work query / event log / artifact or transcript projection | 未来 channel 不读取 `AgentSession` 内部状态 |
| `set_model` / `set_active_tools` / `set_thinking_level` | coding domain operation 或 control-plane setting | 是否开放取决于 domain/control policy，不属于通用 channel command |
| package lifecycle commands | package/plugin domain operation 或 admin/market surface | 不属于通用 channel protocol |
| extension UI dialog commands | `ChannelInteractionRequest/Response` | 是否支持由 `ChannelCapability` 决定 |

#### legacy-only 资产（留在当前 RpcMode）

- `_handle_*_command` command table
- 直接调用 `AgentSession` / `AgentSessionRuntime` 的实现方式
- 当前 `RpcExtensionUIContext` 的 widget/title/editor 具体 wire shape
- 当前 RPC response shape 中的 coding-specific payload

### 4. channel 层核心语义与当前 RpcMode 的差异

长期 `loushang.channel` 应围绕以下链路设计：

```
ChannelInbound
  -> WorkOperation
  -> WorkRun (status: accepted | running | cancelling | completed | failed | cancelled)
  -> WorkEvent (delivery_hint: immediate | coalesce | final_only)
  -> ChannelOutbound
```

当前 `RpcMode` 与此的差异：

| 维度 | 长期 channel | 当前 RpcMode |
|------|------------|-------------|
| 入口归一化 | `WorkOperation` | 直接解析 JSON command table |
| 运行生命周期 | `WorkRun` 状态机 | 隐式绑定 session streaming 状态 |
| 事件语义 | `WorkEvent`（归一化） | 输出 projected session events，不经过 WorkEvent |
| delivery policy | `delivery_hint` + capability | 无，所有 event 同等发送 |
| channel capability | `ChannelCapability` 协商 | 无 |
| 重连/地址 | `address` / `reconnect` 语义 | 无 |
| domain 隔离 | channel 不感知 coding 细节 | 直接暴露 coding session 控制面 |

### 5. 短期冻结 RpcMode v1

在 `loushang.channel` 落地之前：

- **默认冻结** `RpcMode` 的 product command table 扩展。新增产品能力应通过 CLI mode、TUI 或未来的 channel adapter 实现，不再直接扩展 `_handle_*_command`。
- **保留** 现有功能继续服务测试、SDK host、外部脚本和集成。
- **允许** bugfix 和稳定性改进（stress、race、序列化边界）。
- **允许** 经小型 ARD / compatibility note 明确批准的兼容、安全、诊断或测试基础设施级扩展。
- **不允许** 未经设计记录新增 coding-specific product command 或改变既有 response shape 的语义扩展。

### 6. 中期新增 `loushang.channel.rpc_jsonl`

当 `loushang.work` 的 `WorkOperation/WorkRun/WorkEvent` 语义稳定后：

- 新增 `loushang.channel.rpc_jsonl` adapter
- 复用 JSONL framing 和 id correlation
- 面向 `WorkOperation/WorkEvent`，不直接面向 `AgentSession`
- coding-specific 旧命令不直接迁移；其语义能力按需转为 `CodingDomainApp` operation kind、work/host API、control-plane setting，或通过 domain extension 注册

### 7. 长期保留当前 RpcMode 为 legacy/compat adapter

两种可选策略：

- **策略 A（推荐）**：保留当前 `RpcMode` 为 `coding-local legacy adapter`，独立维护，不扩展。新的集成需求统一走 `loushang.channel.rpc_jsonl`。
- **策略 B**：让当前 `RpcMode` 薄包装新的 `rpc_jsonl` channel，在兼容层内将旧 command 映射为 `WorkOperation`、work query 或 host/session operation。仅在需要无缝迁移旧集成时采用。

默认采用策略 A，除非有明确的旧集成迁移压力。

## Rationale

1. **分层原则**：channel 层负责边界协议与 transport，不应被 coding-specific command table 污染。当前 `RpcMode` 直接暴露 `AgentSession` 控制面，适合作为 transitional coding adapter，不适合作为长期 channel 协议基础。
2. **演进连续性**：JSONL framing、id correlation、event projection 等机制已经验证有价值，不应废弃，但应升级语义归属。
3. **冻结优于重构**：在 `loushang.work/channel` 尚未落地时，重构 `RpcMode` 为 "半 channel" 会制造更多过渡态债务。冻结当前实现、新建 clean adapter 是更清晰的演进路径。
4. **headless 价值保留**：测试、SDK host、CI/CD 等 headless 场景不会消失。transitional 定位不等于 "临时可用"，而是 "已有价值、但语义归属需要调整"。
5. **与 ARD-001 的兼容性**：ARD-001 将 `rpc` 列为 `loushang-coding` 的 mode 之一。本决策不推翻 ARD-001，而是明确 `rpc mode` 的长期归属：当前作为 coding mode adapter 存在，未来 channel 层成熟后，其协议形态上提为 `loushang.channel.rpc_jsonl`，coding 层不再直接维护 RPC transport。

## Consequences

### Positive

- 明确 `RpcMode` 的边界，防止其继续膨胀为 "准 channel"
- 保护 `loushang.channel` 的设计空间，避免被当前 RPC command table 约束
- 保留已验证的 JSONL/event stream 资产，减少重复建设
- 测试/集成/CI 场景短期不受影响
- 为 `loushang.work` 落地后的 channel 建设提供清晰的迁移目标

### Negative

- 短期内存在 "两个 RPC 面"：coding-local RpcMode 和未来的 channel rpc_jsonl
- 旧集成（基于当前 RpcMode command table）未来可能需要迁移到 channel adapter
- 默认冻结 RpcMode product command 扩展意味着部分 headless 新需求需要等待 channel 层、走 CLI mode，或经过单独 compatibility/design 记录

## Impacted Documents

- `docs/internals/architecture/coding/ARD-001-coding-product-boundaries.md`（rpc mode 定位需更新）
- `docs/internals/architecture/loushang-channel-boundary-protocol.md`（legacy reference；当前 channel 设计文档，新的 channel 文档落地后评估是否归档至 `legacy/`）
- `docs/internals/architecture/drafts/loushang-work-method-channel-harness-architecture.md`（需对齐 WorkOperation/WorkEvent 语义）
- `docs/internals/architecture/coding/loushang-coding-rpc-mode-surface.md`（需标记为 transitional）

## Impacted Code

- `src/loushang/coding/mode/rpc_mode.py`（冻结扩展，允许 bugfix）
- `src/loushang/coding/cli/__main__.py`（rpc mode 入口保留，不新增 rpc-specific CLI 参数）
- 未来新增：`src/loushang/channel/rpc_jsonl.py`（或类似路径）

## Follow-up

- [x] `loushang.channel.rpc_jsonl` 已实现 JSONL framing、request correlation、accepted ACK 和 WorkEvent delivery；不包含 dispatcher 或旧 RpcMode command mapping
- [ ] 定义旧 RpcMode command 到 future `WorkOperation`、work query、host/session operation 的分类矩阵
- [ ] 定义 `ChannelInteractionRequest/Response` 与 `ChannelCapability` 的关系
- [ ] 评估当前 `RpcMode` 的测试覆盖率，确保冻结期间 regression 可控
- [ ] 在 `loushang-ai` 或 `loushang.work` 的 TODO 中记录：usage/quota 标准化后，rpc_jsonl channel 应支持 `platform_quota` 查询 operation
