# Loushang-AI Whitebox Candidate Functions

> Status: pre-freeze candidate inventory. This file may mention removed simple entrypoints or legacy option names as historical candidates. Current root invocation is `stream()` / `complete()` with `CallOptions`; AIF-015 will decide whether to rewrite or archive this candidate inventory.

## Scope

本文档从白盒视角列出 `loushang-ai` 的候选功能清单。  
这里讨论的是 `loushang-ai` 作为子系统需要承载的稳定能力，而不是最终组件划分、模块划分或代码类设计。

本文档只讨论：

- `loushang-ai` 应承载哪些白盒候选功能
- 每项功能的大致来源
- 每项功能的作用与边界
- 哪些功能更接近主功能，哪些更接近支撑功能或横切技术功能

本文档不讨论：

- 最终组件清单
- 组件到功能的映射粒度
- 代码包结构或 class 结构
- v0.1 之外的长期演进路线图

---

## Reading Rule

这里的“候选功能”并不意味着：

- 每项都必须成为一级 public API
- 每项都必须成为独立组件
- 每项都要在 v0.1 一次性实现完毕

本文档只做两件事：

1. 从 `loushang-ai` 已有架构文档、参考系统与验证结果中识别稳定能力
2. 为后续 `loushang-ai` 白盒候选组件清单提供输入

---

## Function Categories

本文档先用较宽的分类来组织候选功能：

- 主功能
- 支撑功能
- 边界功能
- 横切技术功能

这里的分类只服务于识别，不代表最终组件层次。

---

## Candidate Functions

## 1. Unified Top-Level Model Invocation

**类别：**

- 主功能

**来源：**

- [loushang-ai-top-level-api-signatures.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-top-level-api-signatures.md)
- `reference AI SDK` 顶层 public contract

**作用：**

- 为上层提供统一模型调用入口

**主要能力：**

- 暴露 `stream`
- 暴露 `complete`
- 暴露 `stream_simple`
- 暴露 `complete_simple`
- 以统一 `model + context + options` 骨架承接调用

**边界说明：**

- 这是 `loushang-ai` 最直接的对外主能力之一
- 它不直接等同于某个 provider API，也不等同于某个内部组件

---

## 2. Model Description And Lookup

**类别：**

- 主功能
- 支撑功能

**来源：**

- glossary 中 `Model`
- `reference AI SDK` 的 model registry 经验
- [loushang-ai-system-context.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-system-context.md)

**作用：**

- 提供模型定义、模型查询与模型元数据能力

**主要能力：**

- 描述模型所属 `api`
- 描述模型所属 `provider`
- 提供模型 capability 元数据
- 支撑顶层调用时的 resolved api 解析

**边界说明：**

- 这是 `loushang-ai` 的内建能力，不应把 model 定义与 provider 实现混在一起

---

## 3. API-Based Provider Resolution

**类别：**

- 主功能
- 边界功能

**来源：**

- [loushang-ai-api-adapter-registry.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-api-adapter-registry.md)
- `reference AI SDK` api registry 经验

**作用：**

- 按 `api` 维度解析真实调用执行单元

**主要能力：**

- 注册 `APIAdapter`
- 查询 `APIAdapter`
- 列出已注册 `APIAdapter`
- 在顶层调用中基于 resolved api 找到执行者

**边界说明：**

- 这是 `loushang-ai` 的统一接线能力
- 它不负责工具执行、上层 orchestration，也不负责 model registry 内部语义

---

## 4. Cross-Provider Simple Invocation Semantics

**类别：**

- 主功能
- 支撑功能

**来源：**

- `reference AI SDK` 的 `streamSimple` / `completeSimple`
- [loushang-ai-top-level-api-signatures.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-top-level-api-signatures.md)
- [loushang-ai-provider-adapter-strategy.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-provider-adapter-strategy.md)

**作用：**

- 为跨 provider 常见调用提供统一简化语义

**主要能力：**

- 承接 `SimpleStreamOptions`
- 抽象 reasoning / thinking 等常见控制项
- 将 simple 语义下沉映射到具体 `APIAdapter`

**边界说明：**

- 这不是另一个独立子系统
- 它是统一顶层调用语义的一部分

---

## 5. Unified Context Intake

**类别：**

- 主功能

**来源：**

- glossary 中 `Context`
- [loushang-ai-system-context.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-system-context.md)
- `reference AI SDK` / `kimi-cli` 都以消息上下文为主输入

**作用：**

- 统一承接模型调用所需上下文

**主要能力：**

- 承接 `system_prompt`
- 承接 `messages`
- 承接 `tools`
- 承接 session metadata / stream options 等调用上下文

**边界说明：**

- `loushang-ai` 负责统一上下文语义
- 不负责上层 agent loop 或 channel policy

---

## 6. Provider Protocol Adaptation

**类别：**

- 边界功能

**来源：**

- [loushang-ai-provider-adapter-strategy.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-provider-adapter-strategy.md)
- `kimi-cli` provider adapter 经验

**作用：**

- 将统一 AI 调用语义适配到真实 provider 应用协议

**主要能力：**

- 承接 `openai-compatible`
- 承接 `anthropic-messages`
- 将统一 `Context + Model + Options` 转换为 provider request
- 将 provider stream / response 归一回内部语义

**边界说明：**

- 这是典型的边界能力
- 它要隔离外部协议变化，不应把上游 SDK 对象泄漏进 public contract

---

## 7. Provider Carrier Selection And Invocation

**类别：**

- 边界功能
- 横切技术功能

**来源：**

- [loushang-ai-physical-system-context.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-physical-system-context.md)
- [loushang-ai-provider-adapter-strategy.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-provider-adapter-strategy.md)
- spike 验证结果

**作用：**

- 通过合适的实现载体接入真实 provider

**主要能力：**

- 使用 official SDK 作为 carrier
- 使用 `httpx-thin` 作为 carrier
- 处理 `base_url`、headers、auth、timeout 等 carrier-level 调用参数

**边界说明：**

- 这是 `loushang-ai` 内部能力
- 它不等同于 public `Api`
- 也不应被误识别为逻辑功能组件本身

---

## 8. Streaming Event Normalization

**类别：**

- 主功能
- 支撑功能

**来源：**

- [loushang-ai-streaming-and-cancellation.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-streaming-and-cancellation.md)
- `reference AI SDK` event stream 经验
- `kimi-cli` stream merge / event conversion 经验

**作用：**

- 将 provider streaming 过程归一为统一事件流语义

**主要能力：**

- 暴露统一 `AssistantMessageEventStream`
- 支持异步迭代消费
- 支持最终 `.result()` 收敛
- 吸收 provider-specific stream delta 差异

**边界说明：**

- 这是 `loushang-ai` 对上游最重要的运行时主边界之一

---

## 9. Final Assistant Message Assembly

**类别：**

- 主功能
- 支撑功能

**来源：**

- [loushang-ai-streaming-and-cancellation.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-streaming-and-cancellation.md)
- `kimi-cli` 的 generate orchestration / merge 经验

**作用：**

- 将流式增量收敛成最终 `AssistantMessage`

**主要能力：**

- 聚合 text delta
- 聚合 thinking / reasoning delta
- 聚合 tool call delta
- 收敛 `usage`
- 收敛 `stop_reason`
- 为 `complete()` / `complete_simple()` 提供统一最终结果

**边界说明：**

- 这是统一 streaming 语义能成立的必要能力
- 不应被散落到每个 provider 内部重复实现

---

## 10. Raw-Part Level Normalization

**类别：**

- 支撑功能
- 边界功能

**来源：**

- [loushang-ai-provider-adapter-strategy.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-provider-adapter-strategy.md)
- streaming/cancellation 文档里的三层结构

**作用：**

- 提供 provider stream 与 public event stream 之间的中间标准化层

**主要能力：**

- 接收 provider 原始事件翻译结果
- 作为 assembler 的唯一标准输入
- 承载 text / thinking / tool / image 等内部归一语义

**边界说明：**

- 这是内部稳定能力
- 它不需要直接出现在 public API，但对白盒设计很关键

---

## 11. Tool Schema And Tool-Call Semantic Support

**类别：**

- 主功能
- 边界功能

**来源：**

- [loushang-ai-system-context.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-system-context.md)
- `reference AI SDK` / `kimi-cli` tool support 经验

**作用：**

- 让 `loushang-ai` 能理解并传递 tool 相关 AI 语义

**主要能力：**

- 承接 tool schema
- 传出 tool call 内容块 / 参数
- 承接 tool result message 语义
- 兼容不同 provider 的 tool 表达差异

**边界说明：**

- `loushang-ai` 负责 tool 语义兼容
- 不负责完整 tool orchestration policy

---

## 12. Tool Argument Validation Support

**类别：**

- 支撑功能
- 横切技术功能

**来源：**

- [loushang-ai-system-context.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-system-context.md)
- `kimi-cli` tool validation 经验

**作用：**

- 为 tool-call 相关输入输出提供 AI 侧校验支撑

**主要能力：**

- 参数结构校验
- 结构不合法时的错误收敛
- provider tool payload 适配前的基本保护

**边界说明：**

- 这是 AI 侧辅助能力
- 不等同于完整 tool runtime

---

## 13. Thinking / Reasoning Semantic Normalization

**类别：**

- 支撑功能
- 边界功能

**来源：**

- adapter strategy 文档
- `kimi-cli` 多 provider thinking / reasoning 映射经验

**作用：**

- 统一 reasoning / thinking 相关控制项与输出语义

**主要能力：**

- simple options 中的 reasoning 控制
- provider-specific thinking / reasoning config 映射
- thinking 内容与签名 / encrypted 内容的统一表达

**边界说明：**

- 这是跨 provider 的统一能力，不应被理解为单个 provider 的私有选项包装

---

## 14. Multimodal Content Semantic Support

**类别：**

- 主功能
- 边界功能

**来源：**

- glossary 中 content part
- `kimi-cli` message content 与 MCP content conversion 经验
- physical/system context 中的 provider capability 考量

**作用：**

- 统一承接文本之外的内容部件语义

**主要能力：**

- text
- image
- audio
- video
- 后续可能的 file / document / structured blocks

**边界说明：**

- v0.1 具体支持面可以克制
- 但白盒阶段应把它识别为稳定功能域，而不是以后临时拼接

---

## 15. Error Normalization

**类别：**

- 横切技术功能
- 边界功能

**来源：**

- `reference AI SDK` / `kimi-cli` error mapping 经验
- provider adapter spike

**作用：**

- 将 SDK、HTTP、provider status 等错误收敛成统一 AI 层语义

**主要能力：**

- timeout / connection / status error 归一
- provider error 到统一错误类型的映射
- registry resolution error 收敛
- stream / complete 路径上的错误统一暴露

**边界说明：**

- 这不是次要 helper
- 它是稳定 public contract 的必要支撑

---

## 16. Cancellation And Aborted Semantics

**类别：**

- 横切技术功能
- 主功能

**来源：**

- [loushang-ai-streaming-and-cancellation.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-streaming-and-cancellation.md)
- spike 验证文档

**作用：**

- 提供统一取消语义，并把内部 runtime cancellation 收敛成协议级 `aborted`

**主要能力：**

- 调用前取消检查
- stream 循环中的取消检查
- result 收敛前取消检查
- `aborted` stop reason
- `aborted` event / message error 语义

**边界说明：**

- 内部可以使用 runtime cancellation 机制
- 对外应暴露协议语义上的 `aborted`

---

## 17. OAuth / Auth Input Support

**类别：**

- 边界功能
- 横切技术功能

**来源：**

- `reference AI SDK` 内部已有 oauth/auth 相关结构
- physical system context 的真实接入边界
- 用户明确指出白盒阶段不能漏掉

**作用：**

- 为 provider 接入提供认证输入与凭据边界支撑

**主要能力：**

- API key 输入
- OAuth token 输入
- 认证相关 header / metadata 注入
- auth config 与 provider invocation 的衔接

**边界说明：**

- 这里先识别为候选功能
- 不代表 v0.1 必须完整开放整套 oauth public surface

---

## 18. Environment And Host Capability Intake

**类别：**

- 支撑功能
- 横切技术功能

**来源：**

- [loushang-ai-system-context.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-system-context.md)
- physical system context

**作用：**

- 承接宿主环境对 AI 运行的必要输入

**主要能力：**

- 环境变量读取
- 网络可达性相关参数承接
- timeout / cancellation signal 输入
- 资源边界信息承接

**边界说明：**

- 这是环境边界支撑能力
- 不应与业务上下文功能混在一起

---

## 19. Observability And Audit Emission

**类别：**

- 横切技术功能

**来源：**

- [loushang-ai-system-context.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-system-context.md)

**作用：**

- 向外部 observability / audit 边界输出运行记录

**主要能力：**

- logs
- metrics
- traces
- audit records

**边界说明：**

- 这不是 `loushang-ai` 的主业务功能
- 但它是白盒阶段不能忽略的稳定横切需求

---

## 20. Built-In Provider Bootstrap And Extensibility

**类别：**

- 支撑功能
- 横切技术功能

**来源：**

- `reference AI SDK` built-in provider bootstrap / lazy loader 经验
- `loushang-ai` 当前 registry 与 adapter 设计

**作用：**

- 为内建 provider 注册与后续扩展点预留稳定接线能力

**主要能力：**

- built-in provider 注册
- provider 扩展入口
- 延迟加载或按需接线的可能性
- 测试 / faux provider 的接入基础

**边界说明：**

- 这不是用户直接感知的功能
- 但对白盒结构的可扩展性至关重要

---

## 21. Test / Validation Support For AI Integration

**类别：**

- 支撑功能
- 横切技术功能

**来源：**

- `reference AI SDK` faux provider
- `kimi-cli` mock / chaos / echo provider
- 当前 spike 验证实践

**作用：**

- 为 `loushang-ai` 的 adapter、streaming、tooling、cancellation 验证提供稳定支撑

**主要能力：**

- faux / mock provider 支撑
- compatibility spike 支撑
- streaming / cancellation 验证支撑
- 真实端点适配验证支撑

**边界说明：**

- 这不是产品主功能
- 但对 `loushang-ai` 这种协议层子系统是必要的长期支撑能力

---

## Summary

从白盒视角看，`loushang-ai` 的候选功能并不只包括“调模型”这一条主路径。  
它至少同时覆盖四类稳定能力：

- 面向上层的统一调用能力
- 面向 provider 的协议与 carrier 适配能力
- 面向 streaming / message / tool 的语义归一能力
- 面向认证、取消、错误、可观测性、扩展点、验证的横切支撑能力

如果只识别第一类功能，而忽略后三类，后续组件设计很容易出现：

- 主功能组件过载
- 边界逻辑渗透进核心组件
- 横切能力散落
- 扩展点补得太晚

---

## Takeaway For Next Step

这份候选功能清单的下一步不是直接进入开发，而是继续产出：

- `loushang-ai` 白盒候选组件清单

那一步需要回答的是：

- 哪些候选功能可以映射为逻辑功能组件
- 哪些更适合作为逻辑支撑组件、逻辑技术组件或边界逻辑组件
- 哪些只应保留为组件内部责任簇，而不必升格为独立组件
