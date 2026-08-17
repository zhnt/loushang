## Loushang-AI 流式事件语义设计（详细版）

### 概述与目标
- 目标
  - 为多 Provider（Anthropic、OpenAI 及兼容代理）提供稳定一致且高可观测的流式事件语义。
  - 与 reference AI SDK 在语义上等价：支持文本、思考、工具、多模态、用量与停因，并保证流可靠落幕。
- 范围
  - Provider 原始事件 → RawPart（统一原语） → 高层事件（组装后） → 最终 `AssistantMessage`。
- 非目标
  - 不直接把供应商专属细节（如 Anthropic 的 content_block_*）暴露到通用层，避免耦合与回归风险；必要时通过扩展机制旁路直通。

### 核心概念
- RawPart
  - 统一原始事件类型集合（TypedDict + Literal 判别联合），与 JSON/dict 零拷贝互通，适合热路径。
  - 定义见 `src/loushang/ai/event_stream/raw_parts.py`。
- 高层事件
  - 面向调用方/CLI/UI 的稳定事件名：`start/text_* /thinking_* /toolcall_* /image_* /done/error`。
- Assembler
  - 负责把 RawPart 组装为高层事件并最终合成 `AssistantMessage`，位于 `src/loushang/ai/event_stream/assembler.py`。
- 内容块（content block）
  - 供应商侧的文本/思考/工具/图片单元，可能并行/交错（如 Anthropic 的 index）。

### 统一事件模型
- 控制与统计
  - response_start / response_done / response_error / aborted
  - usage_delta（input/output/cacheRead/cacheWrite/totalTokens）
  - stop_reason（stop/length/toolUse/error）
- 取消
  - `CallOptions.cancellation` 承载最小取消信号协议（仅关心 `cancelled: bool`）
  - 取消映射为 stop_reason=aborted，并通过 error 事件对外可见；finally 仍需保证完成收口
- 内容
  - text_delta、thinking_delta、tool_call_*、image_part
- 高层（装配后）
  - text_start/delta/end、thinking_start/delta/end、toolcall_start/delta/end、image_start/end、done/error
  - 当 RawPart 不显式提供 start/end 时，Assembler 根据 delta + done 自动补齐 start/end。

### RawPart 事件规范（当前实现）
- response_start(response_id)
- text_delta(text)
- thinking_delta(text)
- tool_call_start(id,name)
- tool_call_args_delta(delta)  // JSON 片段
- tool_call_done
- image_part(data,mime_type)
- usage_delta(input,output,cache_read,cache_write,total_tokens?)
- stop_reason(stop|length|toolUse|error)
- response_error(message)
- response_done
- aborted
- 扩展机制（可选）：后续可加入 `vendor_event` 与 `extensions`，用于旁路直通供应商细粒度事件与扩展字段。

### Assembler 组装规则
- start
  - 首次出现任何内容 delta 或 response_start 时，推送 `start` 高层事件。
- text_*
  - 第一条 text_delta 到来时自动推导并发 `text_start`。
  - 每条 text_delta → 推送高层 `text_delta`。
  - 在 response_done 前，若 text 已开始，合并缓存并发 `text_end`。
- thinking_*
  - 第一条 thinking_delta 到来时自动推导并发 `thinking_start`。
  - 每条 thinking_delta → 推送高层 `thinking_delta`。
  - 在 response_done 前，若 thinking 已开始，合并缓存并发 `thinking_end`。
- toolcall_*
  - tool_call_start(id,name) → 推送 `toolcall_start`。
  - tool_call_args_delta(delta) → 推送 `toolcall_delta`，同时缓存 JSON 片段。
  - tool_call_done → 解析缓存 JSON 到 arguments，推送 `toolcall_end(toolCall)`。
- image_*
  - 收到 image_part 即在同一 tick 推送 `image_start` 与 `image_end`（我们当前将 image 视为原子块）。
- usage/stop/done/error
  - usage_delta：覆盖存在字段；total 可按需计算或保持 0。
  - stop_reason：规范化并用于最终消息。
  - response_done：在 finally 中保证发送；在其前补齐一切未结束内容块；产出最终 `AssistantMessage` 并推送 `done`。
  - response_error/aborted：推送 error 并尽量完成收口（仍会 done）。

### Provider 适配与归一化
- 设计原则
  - Provider 适配层只负责“协议 → RawPart”的最小必要映射；通用语义补全（start/end）在 Assembler 完成。
  - 对具备块边界的协议（如 Anthropic content_block_*），可选择在 Provider 层显式发 start/end 以增强可观测；对无块边界协议则由 Assembler 推断。
- Anthropic（messages.stream）
  - Headers/Features
    - 默认合并注入 `anthropic-beta: fine-grained-tool-streaming-2025-05-14`；
    - 若启用 thinking（且非 4.6 自带）可加 `interleaved-thinking-2025-05-14`；
    - 透传 `anthropic-version` 与代理所需头；支持 `tool_choice`、思考模式与 effort。
  - 映射
    - message_start → response_start + usage_delta
    - content_block_start(type=text/thinking/redacted_thinking/tool_use) → 可选发对应 start 或仅建块状态
    - content_block_delta(text_delta/thinking_delta/input_json_delta/signature_delta) → text_delta/thinking_delta/tool_call_args_delta/签名缓冲
    - content_block_stop → text_end/thinking_end/tool_call_done（内部完成 JSON 解析）
    - message_delta → stop_reason + usage_delta
    - message_stop/完成 → response_done（补齐未结束块）
    - error/failed → response_error（finally 仍 response_done）
- OpenAI Completions
  - 以文本为主，可能含工具调用（一次性或增量）；映射到 text_delta 与 tool_call_*，缺少边界时由 Assembler 推断。
- OpenAI Responses
  - reasoning/text/function_call_arguments 的增量，映射到 thinking_delta、text_delta、tool_call_args_delta；item 完成时触发 *_end。
  - 若代理不发块结束，需在完成/异常时由 Provider/Assembler 补齐。

### 并行/交错块与数据结构
- Provider 适配侧建议维护 `blocks: Dict[int, BlockState]`（尤其针对 Anthropic 的 index）：
  - kind: "text" | "thinking" | "redacted_thinking" | "tool" | "image"
  - 文本/思考缓冲（list[str]）
  - 思考签名缓冲（list[str]）
  - 工具 id/name/partial_json（str）
  - meta/context（保留供应商细粒度）
- stop 时清理对应 BlockState 并发 *_end/done；异常时也需在 finally 里做补齐。
- content_index（对外）
  - Assembler 依据“最终消息构建顺序”回填（当前策略：text 固定 0；thinking=1；tool/image 按内容增长）；后续可扩展支持多文本段索引。

### 思考（thinking）与签名（signature）
- thinking_delta：流式思考文本；signature_delta：签名增量。
- redacted_thinking：只暴露 opaque 数据（可通过 extensions 或 vendor_event 保留）。
- 结束策略
  - 有签名：与思考内容一并保留（高层目前不强约束展示）。
  - 无签名/中断：降级为纯文本，保证流程不被拒绝/中断。

### 工具调用（tool use）的细粒度流
- start：tool_call_start(id,name)
- delta：tool_call_args_delta(delta JSON 片段；内部拼接 partial_json 并可尝试流式解析）
- end：tool_call_done（Assembler 内部完成 arguments 解析与合成 ToolCall）
- 兜底：若仅有 stop_reason=tool_use 而无细粒度
  - 首选：确认 beta 头与代理能力
  - 退化：发提示事件或走 agent 回路本地执行工具并回灌 tool_result（作为后续增强）

### 图片与多模态
- RawPart：image_part(data,mime_type) 原子事件；Assembler 推出 image_start/image_end。
- 混排：按块出现顺序进入最终内容。

### usage / stop_reason / 完成态
- usage
  - message_start 推送初值（确保即使中断也有输入用量）；
  - message_delta 按存在字段覆盖增量，不覆盖缺失字段；
  - normalized `Usage.total_tokens` 必须在 `RawAssembler` 层保持可用：provider 明确提供 `total_tokens` 时可优先使用，
    但不得低于 `input + output + cache_read + cache_write`；未提供或为 0 时按组件和推导，保证 session / compaction
    能直接消费 usage 事实。
- stop_reason
  - 规范映射为 stop/length/toolUse/error，并写入最终消息。
- 完成
  - finally 中总是发出 response_done；如有未关闭块，先补齐 *_end/done，再完成。

### 错误与中止
- response_error：统一错误事件，带供应商原始 message。
- aborted：外部信号中止；仍应尽量补齐并通过 error 结束。
- 不变量：不让流“悬空”；所有路径最终都落幕。

### 细粒度语义的演进与不丢失
- 旁路直通：后续加入 `vendor_event{provider,api,name,payload,context}`；不影响主装配。
- 扩展袋：事件可带 `extensions: dict`；新增字段不破坏旧消费方。
- adapter config：在 `models.json` 的 endpoint adapter 配置中记录当前核心协议真实需要的静态适配字段。
- 模式：严格/宽松开关，决定对块边界的要求与告警等级。

### 可观测与回放
- Trace：支持 `CallOptions.trace`，coding CLI/TUI 通过 `--trace=<scope>`、`--trace-file` 或 `LOUSHANG_TRACE_SCOPES`、`LOUSHANG_TRACE_FILE` 接入统一 observability sink。
- 回放：保存原始事件 → 重放到 Assembler，对比高层产出与最终消息，便于回归。
- 指标：块生命周期、工具完成率、usage 完整性、stop_reason 分布、错误率。

### 配置与上层调用方
- `models.json`：在 endpoint adapter 配置中标注核心 adapter 实际消费的字段；provider-specific 传输策略不进入 core model contract。
- coding CLI/TUI 可暴露 tool choice、思考参数与 headers 透传，便于快速验证工具/思考流。

### 测试与验证
- 单测：RawPart 映射（provider 适配）与 Assembler 组装（含异常补齐）。
- 集成：Anthropic/OpenAI/DashScope/Kimi（SDK 与 httpx 双路线）。
- 回归：并行/签名/redacted/无块结束/仅 tool_use 停因 等边界。

### 与 reference AI SDK 的对照
- 关键事件等价：text/thinking/tool（start/delta/end）、usage、stop_reason、done/error。
- 差异策略：我们允许在 Assembler 自动补齐 start/end；对具备块边界的协议推荐在 Provider 显式发 start/end 以提升可观测。
- 参考文档
  - 《Reference AI SDK 流式事件语义（参考）》：`./reference/reference-ai-sdk/reference-ai-sdk-streaming-semantics.md`

### 未来工作
- 多文本段 contentIndex 精细化与 UI 对齐。
- 外部 API 层引入 pydantic/dataclass 做运行时契约校验。
- 扩展 vendor_event 与 extensions 并形成统一回放工具链。
