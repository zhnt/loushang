# loushang-ai Gap Matrix vs reference AI SDK

本文基于以下代码范围对比：

- `reference-repository/packages/ai`
- `loushang/src/loushang/ai`

结论先说：`loushang.ai` 已经具备了 `reference AI SDK` 的基础语义骨架，但距离“功能面对齐”仍有明显差距。当前最大的 gap 集中在 provider 覆盖、图像 tool result 闭环、复杂 reasoning continuity、模型目录规模，以及 `reference AI SDK` 的懒加载与浏览器兼容相关能力。OAuth login 属于调用方或产品层，不计入 `loushang.ai` gap。

## 总体判断

- 如果目标是“让 `loushang.ai` 在 Python 后端场景达到 `reference AI SDK` 80% 实用能力”，当前大概已经有 55%-65%。
- 如果目标是“功能面对齐 `reference AI SDK` 当前完整能力面”，仍大约差 35%-45%。
- 剩余工作量主要不在基础框架，而在 provider 扩展与高级语义闭环。

## 对齐矩阵

| 能力项 | `reference AI SDK` 状态 | `loushang.ai` 状态 | 结论 | 证据 |
|---|---|---|---|---|
| 顶层统一 API：`stream/complete` | 完整，且额外包含 `streamSimple/completeSimple` | `stream/complete` 已冻结，Simple 入口有意删除 | 部分对齐；Python core 保持更窄根 API | [reference implementation stream](/home/dev/workspace/reference-repository/packages/ai/src/stream.ts#L25) [loushang api](/home/dev/workspace/loushang/src/loushang/ai/api/streaming.py#L51) |
| API adapter registry | 完整 | 完整 | 已基本对齐 | [reference implementation registry](/home/dev/workspace/reference-repository/packages/ai/src/api-registry.ts#L66) [loushang registry](/home/dev/workspace/loushang/src/loushang/ai/api_registry.py#L27) |
| 模型注册/查询接口 | 完整 | 完整但规模小 | 语义对齐，数据面不足 | [reference implementation models](/home/dev/workspace/reference-repository/packages/ai/src/models.ts#L20) [loushang exports](/home/dev/workspace/loushang/src/loushang/ai/__init__.py#L36) |
| 标准消息类型：`text/thinking/toolCall/image/toolResult` | 完整 | 完整 | 已基本对齐 | [reference implementation types](/home/dev/workspace/reference-repository/packages/ai/src/types.ts#L137) [loushang types](/home/dev/workspace/loushang/src/loushang/ai/types.py#L7) |
| StopReason：`stop/length/toolUse/error/aborted` | 完整 | 完整 | 已对齐 | [reference implementation types](/home/dev/workspace/reference-repository/packages/ai/src/types.ts#L182) [loushang types](/home/dev/workspace/loushang/src/loushang/ai/types.py#L97) |
| streaming event 语义：`text_* thinking_* toolcall_* done/error` | 完整 | 完整 | 已基本对齐 | [reference implementation README events](/home/dev/workspace/reference-repository/packages/ai/README.md#L374) [loushang assembler](../../../src/loushang/ai/event_stream/assembler.py) |
| abort 语义 | 完整 | 完整 | 已基本对齐 | [reference implementation abort tests](/home/dev/workspace/reference-repository/packages/ai/test/abort.test.ts#L30) [loushang aborted handling](../../../src/loushang/ai/event_stream/assembler.py) |
| overflow 检测 | 完整 | 完整 | 已基本对齐 | [reference implementation overflow](/home/dev/workspace/reference-repository/packages/ai/src/utils/overflow.ts#L12) [loushang overflow](/home/dev/workspace/loushang/src/loushang/ai/utils/overflow.py#L14) |
| `ThinkingLevel/CacheRetention/xhigh` 等核心 options | 完整，含 root transport preference | 核心 options 已收敛到 `CallOptions` | 部分对齐；root API 有意不暴露 `Transport` | [reference implementation options](/home/dev/workspace/reference-repository/packages/ai/src/types.ts#L45) [loushang options](/home/dev/workspace/loushang/src/loushang/ai/options.py#L52) |
| `supportsXhigh` 模型级能力 | 有显式 helper | 缺少统一 helper/策略 | 部分缺失 | [reference implementation helper](/home/dev/workspace/reference-repository/packages/ai/src/models.ts#L55) |
| Tool schema 校验 | 完整 | 完整但实现较简 | 基本对齐 | [reference implementation validation](/home/dev/workspace/reference-repository/packages/ai/src/utils/validation.ts#L49) [loushang validation](/home/dev/workspace/loushang/src/loushang/ai/tool/validation.py#L25) |
| Tool call replay / cross-provider transform | 完整 | 完整 | 已基本对齐 | [reference implementation transform](/home/dev/workspace/reference-repository/packages/ai/src/providers/transform-messages.ts#L13) [loushang tool transform](../../../src/loushang/ai/tool/transform.py) |
| Tool call ID normalization | 完整 | 完整 | 已基本对齐 | [reference implementation anthropic note](/home/dev/workspace/reference-repository/packages/ai/src/providers/anthropic.ts#L697) [loushang normalize](/home/dev/workspace/loushang/src/loushang/ai/tool/transform.py#L240) |
| Orphaned tool call repair | 完整 | 完整 | 已基本对齐 | [reference implementation transform](/home/dev/workspace/reference-repository/packages/ai/src/providers/transform-messages.ts#L98) [loushang tool transform](../../../src/loushang/ai/tool/transform.py) |
| Strict pairing / late tool result / duplicate result 检查 | 有较成熟语义 | 有 | 基本对齐 | [loushang strict](/home/dev/workspace/loushang/src/loushang/ai/tool/transform.py#L31) |
| OpenAI compat：`requiresToolResultName` | 完整 | 有 | 基本对齐 | [reference implementation compat](/home/dev/workspace/reference-repository/packages/ai/src/types.ts#L268) [loushang openai completions](../../../src/loushang/ai/protocols/openai_chat_completions.py) |
| OpenAI compat：`requiresAssistantAfterToolResult` | 完整 | 有 | 基本对齐 | [reference implementation openai](/home/dev/workspace/reference-repository/packages/ai/src/providers/openai-completions.ts#L521) [loushang openai responses shared](../../../src/loushang/ai/protocols/_openai_responses.py) |
| OpenAI compat：`supportsStrictMode` | 有 | 无统一能力暴露 | 缺失 | [reference implementation types compat](/home/dev/workspace/reference-repository/packages/ai/src/types.ts#L280) |
| OpenAI compat：`requiresThinkingAsText` | 有 | 只有局部降级，没有完整 compat 层 | 部分缺失 | [reference implementation types compat](/home/dev/workspace/reference-repository/packages/ai/src/types.ts#L273) [loushang tool transform](../../../src/loushang/ai/tool/transform.py) |
| OpenAI compat：`thinkingFormat` 多形态 | 有 | 无 | 缺失 | [reference implementation types compat](/home/dev/workspace/reference-repository/packages/ai/src/types.ts#L275) [reference implementation openai](/home/dev/workspace/reference-repository/packages/ai/src/providers/openai-completions.ts#L407) |
| OpenRouter/Vercel routing 配置 | 有 | 无 | 缺失 | [reference implementation routing](/home/dev/workspace/reference-repository/packages/ai/src/types.ts#L294) |
| 图像输入 | 完整 | 基本完整 | 已基本对齐 | [reference implementation stream image tests](/home/dev/workspace/reference-repository/packages/ai/test/stream.test.ts#L223) [loushang OpenAI completions tests](../../../tests/protocols/test_openai_chat_completions.py) |
| 图像输出事件 | 完整 | 完整 | 已基本对齐 | [loushang assembler](../../../src/loushang/ai/event_stream/assembler.py) |
| Tool result 中只有图片 | 多 provider 支持 | OpenAI 路径不支持 | 关键缺失 | [reference implementation image tool result](/home/dev/workspace/reference-repository/packages/ai/test/image-tool-result.test.ts#L26) [loushang text-only limit](/home/dev/workspace/loushang/src/loushang/ai/tool/providers.py#L115) |
| Tool result 中图文混合 | 多 provider 支持 | OpenAI 路径不支持 | 关键缺失 | [reference implementation openai completions images](/home/dev/workspace/reference-repository/packages/ai/src/providers/openai-completions.ts#L641) |
| Thinking signature / encrypted continuity | 完整度较高 | 有字段和局部处理，但未闭环 | 关键缺失 | [reference implementation openai responses](/home/dev/workspace/reference-repository/packages/ai/src/providers/openai-responses.ts#L222) [loushang gap doc](/home/dev/workspace/loushang/docs/architecture/ai/validation/loushang-ai-gap-vs-reference-ai-sdk-round-1.md#L151) |
| Response ID / reasoning replay | 有 | 很弱，只有局部处理 | 缺失 | [reference implementation responseid test](/home/dev/workspace/reference-repository/packages/ai/test/responseid.test.ts#L21) [loushang openai responses shared](../../../src/loushang/ai/protocols/_openai_responses.py) |
| Built-in providers/API 覆盖 | 9 条内建 API | 3 条内建 API | 最大 gap | [reference implementation builtins](/home/dev/workspace/reference-repository/packages/ai/src/providers/register-builtins.ts#L366) [loushang bootstrap](/home/dev/workspace/loushang/src/loushang/ai/bootstrap.py#L13) |
| Anthropic provider | 有 | 有 | 对齐 | [reference implementation builtins](/home/dev/workspace/reference-repository/packages/ai/src/providers/register-builtins.ts#L367) [loushang bootstrap](/home/dev/workspace/loushang/src/loushang/ai/bootstrap.py#L56) |
| OpenAI Completions provider | 有 | 有 | 对齐 | [reference implementation builtins](/home/dev/workspace/reference-repository/packages/ai/src/providers/register-builtins.ts#L373) [loushang bootstrap](/home/dev/workspace/loushang/src/loushang/ai/bootstrap.py#L63) |
| OpenAI Responses provider | 有 | 有 | 对齐 | [reference implementation builtins](/home/dev/workspace/reference-repository/packages/ai/src/providers/register-builtins.ts#L385) [loushang bootstrap](/home/dev/workspace/loushang/src/loushang/ai/bootstrap.py#L69) |
| ChatGPT Coding Plan route | 独立 Codex adapter | catalog route 复用 `openai-responses` | 有意采用更窄协议边界 | [loushang models](../../../src/loushang/ai/model/models.json) |
| Azure OpenAI Responses provider | 有 | 无 | 缺失 | [reference implementation builtins](/home/dev/workspace/reference-repository/packages/ai/src/providers/register-builtins.ts#L391) |
| Google Generative AI provider | 有 | 无 | 缺失 | [reference implementation builtins](/home/dev/workspace/reference-repository/packages/ai/src/providers/register-builtins.ts#L403) |
| Google Gemini CLI provider | 有 | 无 | 缺失 | [reference implementation builtins](/home/dev/workspace/reference-repository/packages/ai/src/providers/register-builtins.ts#L409) |
| Google Vertex provider | 有 | 无 | 缺失 | [reference implementation builtins](/home/dev/workspace/reference-repository/packages/ai/src/providers/register-builtins.ts#L415) |
| Mistral provider | 有 | 无 | 缺失 | [reference implementation builtins](/home/dev/workspace/reference-repository/packages/ai/src/providers/register-builtins.ts#L379) |
| Bedrock provider | 有 | 无 | 缺失 | [reference implementation builtins](/home/dev/workspace/reference-repository/packages/ai/src/providers/register-builtins.ts#L421) |
| Faux provider | 有 | 有 | 对齐 | [reference implementation faux](/home/dev/workspace/reference-repository/packages/ai/src/providers/faux.ts) [loushang faux](/home/dev/workspace/loushang/src/loushang/ai/protocols/faux.py#L8) |
| 调用期 OAuth credential | provider registry 驱动 | auth 层解析完整 credential，AI 调用只接收 `OAuthBearerAuth` + supplemental headers | Python core 保持更窄边界 | [loushang options](../../../src/loushang/ai/options.py) |
| 懒加载 provider module | 有 | 无 | 缺失 | [reference implementation lazy](/home/dev/workspace/reference-repository/packages/ai/src/providers/register-builtins.ts#L168) |
| 浏览器兼容/Node-safe import | 有 | 无对应目标 | 若追平 SDK 体验则缺失 | [reference implementation browser-safe](/home/dev/workspace/reference-repository/packages/ai/src/env-api-keys.ts#L1) |
| TypeBox 顶层导出 | 有 | 无 Python 对应物 | 非必要差异 | [reference implementation index](/home/dev/workspace/reference-repository/packages/ai/src/index.ts#L1) |
| 自动模型生成/超大模型目录 | 有 `generate-models.ts` + 大型 generated registry | 无自动生成，模型目录很小 | 明显缺失 | [reference implementation generate-models](/home/dev/workspace/reference-repository/packages/ai/scripts/generate-models.ts) [loushang models](/home/dev/workspace/loushang/src/loushang/ai/model/models.json#L3) |
| 测试覆盖深度 | 很深，覆盖跨 provider、OAuth、image/tool result、abort、xhigh、reasoning replay | 中等偏深，但覆盖面更窄 | 仍有 gap | [reference implementation tests](/home/dev/workspace/reference-repository/packages/ai/test) [loushang tests](../../../tests) |

## 剩余 Gap 按优先级整理

### P0

- 补 provider/API：
  - `azure-openai-responses`
  - `google-generative-ai`
  - `google-gemini-cli`
  - `google-vertex`
  - `mistral-conversations`
  - `bedrock-converse-stream`
- 补 OpenAI/Responses/Google 路径下的 image tool result 闭环

### P1

- OAuth 登录与账号产品能力不属于 `loushang.ai` gap
- 补 compat 层剩余能力：
  - `supportsStrictMode`
  - `requiresThinkingAsText`
  - `thinkingFormat`
  - routing 元数据

### P2

- 补 reasoning continuity：
  - `reasoning.encrypted_content`
  - thought signature continuity
  - response id replay
  - aborted turn 后 reasoning history 跳过语义
- 扩模型目录与自动生成机制

### P3

- 如果目标是库分发体验接近 `reference AI SDK`，再补：
  - provider 懒加载
  - browser-safe runtime import
  - 文档与发布体验

## 实际判断

- 如果目标是 Python server-side runtime 能力，`loushang.ai` 不必完全照搬 `reference AI SDK` 的浏览器兼容与 TypeBox 导出层。
- 但如果目标是“功能面对齐 `reference AI SDK`”，当前最先需要补的仍然是 provider 覆盖与 image tool result；OAuth login 仍由调用方或产品层负责。
- 在当前阶段，`loushang.ai` 的基础框架已经够用，瓶颈主要在“能力面不够宽”和“复杂语义未闭环”。
