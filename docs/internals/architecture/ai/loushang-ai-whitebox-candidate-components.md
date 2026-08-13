# Loushang-AI Whitebox Candidate Components

> Status: pre-freeze candidate inventory. This file may mention removed simple entrypoints or legacy option names as historical candidates. Current root invocation is `stream()` / `complete()` with `CallOptions`; AIF-015 will decide whether to rewrite or archive this candidate inventory.

## Scope

本文档从白盒视角列出 `loushang-ai` 的候选组件清单。  
它建立在以下输入之上：

- [Component Identification Method](../../architecture-method/component-identification.md)
- [Reference AI SDK Whitebox Candidate Components](/home/dev/workspace/loushang/docs/architecture/ai/reference/reference-ai-sdk/reference-ai-sdk-whitebox-candidate-components.md)
- [Kimi-CLI AI Whitebox Candidate Components](/home/dev/workspace/loushang/docs/architecture/ai/reference/kimi-cli/kimi-cli-ai-whitebox-candidate-components.md)
- [Loushang-AI Whitebox Candidate Functions](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-whitebox-candidate-functions.md)

本文档只讨论：

- `loushang-ai` 的白盒候选组件
- 每个候选组件的类别、作用与主要职责
- 每个候选组件与现有架构文档的对应关系
- 每个候选组件的初步内聚 / 耦合判断

本文档不讨论：

- 最终组件定版
- 组件之间的最终映射粒度
- 代码文件结构
- 组件到类的映射

---

## Reading Rule

这里的“候选组件”并不意味着：

- 它已经是最终组件
- 它必须独立成单独包或单独文件
- 它一定会在 v0.1 完整落地

本文档的目标是：

1. 先识别哪些职责单元值得成为白盒设计对象
2. 为下一步的抽象、分解、组合、内聚/耦合分析提供输入

因此本文档会同时保留两类对象：

- 已经很像独立组件的候选组件
- 尚未最终提升、但职责已很稳定的候选责任簇

---

## Candidate Components

## 1. Top-Level AI API

**类别：**

- 逻辑功能组件

**主要来源：**

- [loushang-ai-top-level-api-signatures.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-top-level-api-signatures.md)
- `reference AI SDK` 顶层 API

**作用：**

- 作为 `loushang-ai` 的统一顶层调用入口

**主要职责：**

- 暴露 `stream`
- 暴露 `complete`
- 暴露 `stream_simple`
- 暴露 `complete_simple`
- 以统一 `model + context + options` 承接调用
- 触发 provider resolution 并连接统一 event stream 语义

**初步判断：**

- 内聚性高
- 是最清晰的对外主组件之一
- 不应直接耦合 provider 私有 payload 或 SDK 对象

---

## 2. Model Registry

**类别：**

- 逻辑功能组件

**主要来源：**

- glossary 中 `Model`
- `reference AI SDK` model registry 经验
- [loushang-ai-system-context.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-system-context.md)

**作用：**

- 管理模型定义、模型查询与模型元数据

**主要职责：**

- 提供 model lookup
- 暴露 endpoint `api` / resolved api 事实
- 暴露 provider / capability 元数据
- 为顶层调用与 provider resolution 提供稳定输入

**初步判断：**

- 内聚性高
- 与 provider 执行细节应保持低耦合

---

## 3. API Adapter Registry

**类别：**

- 逻辑功能组件
- 边界逻辑组件

**主要来源：**

- [loushang-ai-api-adapter-registry.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-api-adapter-registry.md)
- `reference AI SDK` api registry 经验

**作用：**

- 作为 `api -> APIAdapter` 的统一接线中枢

**主要职责：**

- `register_api_adapter`
- `get_api_adapter`
- `list_api_adapters`
- 按 resolved api 解析真实调用执行单元

**初步判断：**

- 内聚性高
- 与 model registry、top-level API 有稳定关系
- 不应膨胀成 orchestration system 或 plugin framework

---

## 4. Context Intake And Normalization

**类别：**

- 逻辑功能组件
- 逻辑支撑组件

**主要来源：**

- glossary 中 `Context`
- [loushang-ai-system-context.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-system-context.md)
- `kimi-cli` message/context intake 经验

**作用：**

- 统一承接 AI 调用所需上下文，并保持内部一致语义

**主要职责：**

- 承接 system prompt
- 承接 messages
- 承接 tools
- 承接 session metadata / stream options / host-bound hints
- 为 provider adapter 与 assembler 提供稳定输入

**初步判断：**

- 职责稳定
- 值得作为候选组件识别
- 也可能最终与部分 type-system 责任簇组合

---

## 5. APIAdapter Protocol

**类别：**

- 边界逻辑组件

**主要来源：**

- [loushang-ai-api-adapter-registry.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-api-adapter-registry.md)
- `reference AI SDK` 的 `APIAdapter`
- `kimi-cli` 的 `ChatProvider` protocol

**作用：**

- 定义 `loushang-ai` 内部统一 provider 适配抽象面

**主要职责：**

- 声明 `api`
- 定义 `stream`
- 定义 `stream_simple`
- 约束 provider adapter 向上暴露的最小统一调用面

**初步判断：**

- 是边界稳定性的关键接口对象
- 虽然不是最终用户直接感知的功能，但非常适合独立识别

---

## 6. Provider Adapter Component

**类别：**

- 边界逻辑组件

**主要来源：**

- [loushang-ai-provider-adapter-strategy.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-provider-adapter-strategy.md)
- [loushang-ai-physical-system-context.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-physical-system-context.md)
- `kimi-cli` provider adapter 经验

**作用：**

- 隔离 `loushang-ai` 与真实 provider API / SDK / transport 的变化

**主要职责：**

- 承接 `openai-compatible`
- 承接 `anthropic-messages`
- 接收统一 `Context + Model + Options`
- 调用 carrier
- 输出 raw parts
- 执行取消检查与 error mapping 桥接

**初步判断：**

- 边界职责非常稳定
- 对外部协议天然高耦合
- 这种耦合应被局部化在该层内部

---

## 7. Provider Payload Transformation

**类别：**

- 逻辑支撑组件
- 边界逻辑组件

**主要来源：**

- `kimi-cli` payload transformation 经验
- adapter strategy 文档

**作用：**

- 承担内部语义与 provider wire format 之间的双向转换

**主要职责：**

- `Context/Message/Tool` -> provider payload
- provider event -> raw part
- provider usage / stop reason -> internal normalized semantics
- tool result message 与 multimodal block 的协议映射

**初步判断：**

- 责任稳定且重要
- 当前更像 provider adapter 内部的子责任簇
- 值得单独保留观察，后续再决定是否提升为更明确组件

---

## 8. Carrier Invocation Cluster

**类别：**

- 逻辑技术组件
- 边界逻辑组件

**主要来源：**

- [loushang-ai-physical-system-context.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-physical-system-context.md)
- spike 验证结果
- `kimi-cli` client/carrier management 经验

**作用：**

- 管理 official SDK / `httpx-thin` 等实现载体的接入与调用

**主要职责：**

- 创建 carrier client
- 管理 `base_url`、auth、headers、timeouts
- 处理 client 生命周期
- 为 retry / reconnect / stream transport 提供落点

**初步判断：**

- 白盒阶段必须识别
- 但更像技术边界支撑层，而不是主功能组件

---

## 9. Raw Part Types

**类别：**

- 逻辑支撑组件

**主要来源：**

- adapter strategy 文档
- streaming/cancellation 文档中的三层结构
- `kimi-cli` 的 `StreamedMessagePart` / `ContentPart` 启发

**作用：**

- 作为 provider stream 与 public event stream 之间的唯一标准归一化层

**主要职责：**

- 表达 text / thinking / tool / image 等 raw 语义
- 作为 assembler 的唯一标准输入
- 为不同 provider adapter 提供统一输出目标

**初步判断：**

- 这是 `loushang-ai` 白盒阶段的关键支撑组件
- 若没有它，provider 语义很容易直接泄漏到 event stream

---

## 10. Raw Assembler

**类别：**

- 逻辑支撑组件

**主要来源：**

- [loushang-ai-streaming-and-cancellation.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-streaming-and-cancellation.md)
- `kimi-cli` stream merge / message assembly 经验

**作用：**

- 把 raw parts 收敛成统一事件流与最终消息

**主要职责：**

- 合并 text delta
- 合并 thinking / tool delta
- 维护 partial -> complete 的收敛过程
- 更新 usage / stop reason
- 生成最终 `AssistantMessage`

**初步判断：**

- 内聚性应很高
- 是 `loushang-ai` 比 `kimi-cli` 更值得显式独立建模的一层

---

## 11. Assistant Message Event Stream

**类别：**

- 逻辑功能组件
- 逻辑支撑组件

**主要来源：**

- [loushang-ai-streaming-and-cancellation.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-streaming-and-cancellation.md)
- `reference AI SDK` event stream 经验

**作用：**

- 作为 `loushang-ai` 的统一流式运行时主边界

**主要职责：**

- 暴露异步事件迭代
- 支持 `.result()`
- 对上屏蔽 provider 私有 stream 对象
- 承接 `done` / `error` / `aborted` 等统一事件语义

**初步判断：**

- 内聚性高
- 应作为独立候选组件保留

---

## 12. Final Message Completion Cluster

**类别：**

- 逻辑支撑组件

**主要来源：**

- 顶层 API 签名文档
- streaming validation 与 `complete-on-stream` 规则

**作用：**

- 让 `complete()` / `complete_simple()` 建立在统一 stream 收敛语义之上

**主要职责：**

- 通过 event stream `.result()` 收敛最终消息
- 共享 streaming 路径的最终状态
- 避免单独维护另一套 provider completion 调用链

**初步判断：**

- 它和 event stream / assembler 关系很紧
- 后续可能不独立成一级组件，但当前值得保留为明确责任簇

---

## 13. Simple Invocation Mapping

**类别：**

- 逻辑支撑组件
- 逻辑技术组件

**主要来源：**

- `reference AI SDK` simple API 经验
- 顶层 API 签名文档
- adapter strategy 文档

**作用：**

- 承接 simple 入口的统一语义，并映射到 full / provider-specific 调用面

**主要职责：**

- `SimpleStreamOptions` 解释
- thinking / reasoning 级别映射
- simple -> provider adapter 的桥接

**初步判断：**

- 责任稳定
- 很可能最终作为支撑组件或 provider-shared layer 出现

---

## 14. Tool Semantic Component

**类别：**

- 逻辑功能组件
- 边界逻辑组件

**主要来源：**

- [loushang-ai-system-context.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-system-context.md)
- `reference AI SDK` / `kimi-cli` tool support 经验

**作用：**

- 统一 AI 侧的 tool schema、tool call、tool result 语义

**主要职责：**

- 承接 tool schema
- 表达 tool call 内容块
- 表达 tool result message 语义
- 兼容 provider 间 tool 表达差异

**初步判断：**

- 这是功能域明确的候选组件
- 但不应被扩展成 tool orchestration runtime

---

## 15. Tool Validation Cluster

**类别：**

- 逻辑技术组件
- 逻辑支撑组件

**主要来源：**

- system context 文档中对 validation 的表述
- `kimi-cli` tooling validation 经验

**作用：**

- 为 AI 侧 tool 输入输出提供基础校验支撑

**主要职责：**

- tool argument validation
- tool payload safety check
- 结构异常时的错误收敛

**初步判断：**

- 是稳定横切能力
- 未必需要单独升成一级组件，但很值得单独观察

---

## 16. Thinking / Reasoning Mapping Cluster

**类别：**

- 逻辑支撑组件
- 边界逻辑组件

**主要来源：**

- adapter strategy 文档
- `kimi-cli` 多 provider thinking mapping 经验

**作用：**

- 统一 `ThinkingEffort` 与 provider-specific reasoning / thinking 配置和输出

**主要职责：**

- simple reasoning 级别映射
- thinking block 语义归一
- encrypted/signature 相关归一

**初步判断：**

- 是跨 provider 的稳定责任簇
- 很可能是多个边界组件共享的支撑层

---

## 17. Multimodal Content Component

**类别：**

- 逻辑功能组件
- 逻辑支撑组件

**主要来源：**

- glossary 中 content part
- `kimi-cli` message / MCP conversion 经验

**作用：**

- 承接 text 外的图像、音频、视频等内容语义

**主要职责：**

- image / audio / video content 语义
- 内容部件统一表达
- 与 provider payload transformation 的对接

**初步判断：**

- 是明确功能域
- 但在 v0.1 里可保持支持面克制

---

## 18. Error Mapping Cluster

**类别：**

- 逻辑技术组件
- 边界逻辑组件

**主要来源：**

- spike 验证
- `reference AI SDK` / `kimi-cli` error mapping 经验

**作用：**

- 将 registry、carrier、SDK、HTTP、provider 返回的错误归一到统一 AI 层语义

**主要职责：**

- timeout / connection / status error 映射
- provider-specific error 到统一 error family 的转换
- stream / complete 路径的一致错误暴露

**初步判断：**

- 这是典型的横切技术支撑层
- 若不单独识别，很容易散落

---

## 19. Cancellation And Aborted Bridge

**类别：**

- 逻辑技术组件
- 逻辑支撑组件

**主要来源：**

- [loushang-ai-streaming-and-cancellation.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-streaming-and-cancellation.md)
- provider adapter validation spike

**作用：**

- 把内部 runtime cancellation 收敛为协议语义上的 `aborted`

**主要职责：**

- 调用前取消检查
- stream 中取消检查
- result 前取消检查
- `aborted` stop reason / error event 归一

**初步判断：**

- 已经通过真实验证支撑
- 是很值得明确保留的内部技术组件或技术责任簇

---

## 20. Auth Input Cluster

**类别：**

- 边界逻辑组件
- 逻辑技术组件

**主要来源：**

- 白盒阶段用户强调不能漏掉 oauth/auth
- `reference AI SDK` 内部 auth / oauth 相关结构
- physical system context

**作用：**

- 向 provider 接入层提供认证输入边界

**主要职责：**

- API key 输入
- OAuth token 输入
- header / metadata 认证注入
- auth config 与 carrier 调用的衔接

**初步判断：**

- 目前还不是 public contract 的主叙事
- 但白盒阶段必须识别为稳定边界组件候选

---

## 21. Environment Intake Cluster

**类别：**

- 逻辑技术组件

**主要来源：**

- system context / physical context 文档
- `kimi-cli` provider env intake 经验

**作用：**

- 承接宿主环境输入给 `loushang-ai` 的运行条件

**主要职责：**

- 环境变量读取
- network / timeout / signal 输入承接
- 资源边界与 host 条件输入

**初步判断：**

- 是稳定技术支撑点
- 不应与业务上下文组件混在一起

---

## 22. Observability Emission Cluster

**类别：**

- 逻辑技术组件

**主要来源：**

- [loushang-ai-system-context.md](/home/dev/workspace/loushang/docs/architecture/ai/loushang-ai-system-context.md)

**作用：**

- 向 logs / metrics / traces / audit 边界发出记录

**主要职责：**

- 运行日志
- 指标
- trace
- audit records

**初步判断：**

- 这是横切技术能力
- 很可能最终以内聚度更高的子模块形态出现

---

## 23. Provider Bootstrap And Extensibility Component

**类别：**

- 逻辑技术组件
- 扩展点组件

**主要来源：**

- `reference AI SDK` built-in provider bootstrap / lazy loader 经验
- registry 与 adapter strategy 文档

**作用：**

- 为内建 provider 注册与后续扩展点预留稳定骨架

**主要职责：**

- built-in provider bootstrap
- provider extension point
- lazy loading / deferred registration 的可能落点
- faux / test provider 的接线基础

**初步判断：**

- 黑盒阶段容易漏掉
- 白盒阶段很值得显式识别

---

## 24. Test / Validation Support Cluster

**类别：**

- 逻辑技术组件
- 扩展点组件

**主要来源：**

- `reference AI SDK` faux provider
- `kimi-cli` mock / chaos / echo provider
- 当前 spike 实践

**作用：**

- 为 `loushang-ai` 的协议层与 adapter 层提供长期验证支撑

**主要职责：**

- faux / mock provider
- compatibility validation
- streaming / cancellation validation
- real endpoint spike support

**初步判断：**

- 不是产品主功能
- 但对 AI 协议层子系统非常重要

---

## Candidate Clusters Not Yet Finalized

以下对象当前更像“责任簇”，还未必需要立即升格为最终一级组件：

- Provider Payload Transformation
- Final Message Completion Cluster
- Tool Validation Cluster
- Thinking / Reasoning Mapping Cluster
- Error Mapping Cluster
- Cancellation And Aborted Bridge

它们已经稳定到值得单独识别，但还需要下一步继续判断：

- 是否独立成组件
- 是否组合进更高层组件
- 是否保留为组件内部子模块

---

## Summary

从白盒视角看，`loushang-ai` 的候选组件当前更适合被理解为几组组件与责任簇：

- 对外主入口组件组
- 统一语义与装配组件组
- provider 边界与 carrier 接入组件组
- 横切技术与扩展支撑责任簇

这也说明 `loushang-ai` 不能只照抄任一参考系统：

- `reference AI SDK` 给了顶层 API、registry、bootstrap、event stream 视角
- `kimi-cli` 给了 message model、assembly、tooling、runtime 边界视角

`loushang-ai` 的白盒组件设计需要把两边拼起来，而不是只继承一边。

---

## Takeaway For Next Step

到这一步，白盒分析的“发现阶段”基本完整。  
下一步不应直接写代码，而应进入收敛阶段，至少包括：

1. 候选功能 -> 候选组件的映射分析
2. 哪些候选责任簇需要升格为独立组件
3. 哪些候选组件需要分解
4. 哪些候选组件可以组合
5. 对内聚 / 耦合做第一轮明确判断
