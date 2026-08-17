# Loushang Method Notes

## Status

- Authority: historical method evidence
- Design status: superseded
- Implementation status: not-applicable
- Owner: Loushang architecture method history

This document preserves lessons from the original AI architecture exercise.
The canonical reusable process is now
[Architecture Design And Governance Method](../README.md).

## Scope

本文档沉淀本次 `loushang.ai` 前期设计过程中形成的方法论经验。  
它不是模板，也不是规范，只记录这次被证明有效的工作方式。

## 1. 先分层，再设计子系统

一开始没有直接进入 `loushang.ai` 代码设计，而是先建立：

- strategy
- architecture overview
- subsystem responsibilities
- subsystem diagram

这一步的价值在于：

- 先把 `loushang-ai`、`loushang-agent`、`loushang-channel`、`loushang-tui` 的职责边界钉住
- 避免在 AI 层设计时把 agent/channel/tui 的职责混进来

## 2. 先 glossary，再 types

这次没有直接写 API，而是先写：

- [Loushang AI Glossary](../../glossary/loushang-ai.md)
- [Loushang AI Types](../../glossary/loushang-ai-types.md)

这样做的价值在于：

- 先统一术语
- 再冻结对象边界
- 减少“命名讨论”和“类型讨论”交叉污染

## 3. 高风险问题单独开关键技术设计

这次 streaming / cancellation / asyncio 绑定边界，没有塞进 glossary 或 types，而是单独形成：

- [Loushang AI Streaming and Cancellation](../../architecture/ai/loushang-ai-streaming-and-cancellation.md)

这一步很重要，因为：

- streaming/cancellation 是结构性决策
- 不适合只在 types 文档中顺手拍板
- 单独开文档可以容纳对比、权衡、开放问题

## 4. 用参考系统做对比，而不是直接照搬

这次设计不是抽象空转，而是持续对照三类参考：

- `reference AI SDK`
  - 用来约束 public contract
- `kimi-cli`
  - 用来吸收 Python 实现经验
- LiteLLM
  - 用来理解 lower-level provider adapter 可能的形态

最后形成的取舍是：

- public contract 对齐 `reference AI SDK`
- internal streaming 结构吸收 `kimi-cli`
- provider adapter lower-level shape 可参考 LiteLLM

这类“多参考系统对比，再做分层取舍”的方法，比简单模仿一个参考实现更稳。

## 5. 在正式实现前先做技术验证

这次没有等顶层 API 全定完再写代码，而是先做了：

- `spikes/ai-streaming`

这个 spike 的作用不是实现功能，而是验证：

- `AssistantMessageEventStream` 的形态
- internal reader / writer 分离
- `AbortSignalLike`
- `aborted` 映射
- throughput smoke

这一步的价值在于：

- 先验证结构性决策
- 避免把错误设计继续推到正式实现
- 让后续 API 设计建立在被验证过的模型之上

## 6. spike 与正式文档分层记录

这次没有把实验结果直接塞回架构总览，而是分成两层：

### spike 层

- [AI Streaming Spike README](../../../../spikes/ai-streaming/README.md)
- [AI Streaming Spike Results](../../../../spikes/ai-streaming/RESULTS.md)

记录：

- 怎么验证
- 跑了什么
- 实际结果是什么

### architecture validation 层

- [Loushang AI Streaming Validation](../../architecture/ai/validation/loushang-ai-streaming-validation.md)

记录：

- 这次验证对架构意味着什么
- 哪些结论已经可以冻结
- 哪些问题仍然开放

这种分层记录方式很值得保留：

- `spikes/` 记实验事实
- `docs/architecture/ai/validation/` 记架构结论

## 7. public contract 与 default implementation 分层

这次最大的技术判断之一是：

- `loushang.ai` 不把 `asyncio` 深度写入 public contract
- 但默认实现允许基于 `asyncio`

这类分层判断很关键：

- 不把默认 runtime 误当成协议本身
- 同时也不为了抽象而拒绝使用 Python 最自然的实现方式

## 8. 先冻结方向，再进入 registry 与顶层 API

本次工作顺序不是：

1. 先设计顶层函数
2. 再补流模型

而是：

1. 先定 glossary
2. 再定 types
3. 再定 streaming/cancellation
4. 再做 spike
5. 再做 validation
6. 最后才进入 `ApiProvider` registry 和顶层签名

这条顺序的价值在于：

- 顶层 API 建立在稳定协议之上
- 不容易在后面反复推翻签名

## 9. 会话结束前必须写 handoff

本次会话信息量很大，因此单独写了：

- [Loushang AI Historical Handoff Summary](../../architecture/ai/history/loushang-ai-historical-handoff.md)

这说明一个实用方法：

- 当会话已经形成完整设计链路时，不要依赖聊天记录本身
- 应该主动生成 handoff summary
- 新会话应优先从 handoff 继续，而不是重新翻全部历史

## 10. 在回改组件设计前先更新系统环境图

这次继续推进 `loushang-ai` 时，一个明显经验是：

- 当 protocol family、auth、transport、model family handling 开始显式出现后
- 不应直接跳到组件设计文档里加组件

更稳的顺序是：

1. 先更新逻辑系统环境图
2. 再更新物理系统环境图
3. 再从环境图里识别变化维度和 actor
4. 最后回到组件设计文档

这样做的价值在于：

- 先确认变化源来自哪里
- 再决定哪些变化应被组件吸收
- 避免在组件设计中凭感觉加 `auth` / `transport` / `resolver`

## 11. 系统环境图不仅用于画边界，也用于识别变化

这次一个很实用的方法论收获是：

- 系统环境图不只是 black-box overview
- 它也是白盒组件识别的正式输入

尤其当系统开始面对多协议族、多 auth、多 transport、多 provider actor 时，环境图可以先帮助识别：

- 哪些是 actor
- 哪些是 protocol family
- 哪些是 auth source
- 哪些是 transport mode
- 哪些是 model family metadata

然后再进一步判断：

- 哪些会驱动边界组件出现
- 哪些会驱动 supporting component 出现
- 哪些应上提为 capability handling

这一步里还有一个容易漏掉、但后来证明很重要的点：

- 逻辑环境图要显式识别 `actor`
- 物理环境图要显式识别 `user`

因为很多后续会长成：

- public entry 组件
- boundary component
- auth / transport / bootstrap supporting component

的对象，最早并不是以“组件名”出现，而是先以 actor / user 的形式出现。

## Current Takeaway

本次形成的工作方法，可以概括为：

1. 先建立系统分层与子系统边界
2. 先 glossary，再 types
3. 关键技术问题单独开设计文档
4. 多参考系统对比后做分层取舍
5. 正式实现前先做技术 spike
6. 用 validation 文档固化验证结论
7. 会话结束前必须写 handoff
8. 回改组件设计前先更新系统环境图
9. 用系统环境图识别变化维度与候选组件
10. 逻辑环境图显式识别 actor，物理环境图显式识别 user
