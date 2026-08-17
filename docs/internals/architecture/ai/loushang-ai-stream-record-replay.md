## Loushang-AI 录制与回放（Record & Replay）设计（含 Agent 集成）

### 1. 目标与范围
- 目标
  - 零 Token 回归：将真实流式交互录制为可重放工件，用于本地/CI 回放与对比测试。
  - 逼真诊断：支持供应商原生流（vendor-raw）与规范化流（RawPart）双轨录制与回放。
  - 无侵入接入：在 Provider 层与 Agent 层均可一键启用；默认不影响线上性能。
- 范围
  - 覆盖一次响应（turn）与长会话（session）两种粒度。
  - 支持 Anthropic/OpenAI/httpx/SDK 等多 Provider 通道。
  - 支持工具调用链路（tool_use 增量与 tool_result）。

### 2. 架构与组件
- Recorder 中间件（Provider 侧）
  - 置于“Provider 事件 → RawPart 映射”边上，拦截并记录：
    - 请求侧：model/binding、system_prompt、messages、tools、options、headers（脱敏）、请求时间戳。
    - 响应侧：可选 vendor-raw（SSE 行/WS 帧/SDK 事件）、必选 RawPart（规范化原语），均带相对时间戳。
  - 输出格式：NDJSON（JSON Lines）。
- ReplayProvider / ReplayTransport
  - 白盒回放：从文件读取 RawPart 序列，按时间戳（real/fast/instant）吐给 Assembler，得到高层事件与最终消息。
  - 黑盒回放：起本地 SSE/WS 回放服务，原客户端“请求匹配后”直接接收与线上一致的 vendor-raw 事件。
- Agent 集成层（Agent Recorder）
  - 捕获 Agent 输入输出（包含模型调用前后的上下文、工具结果与裁决）：
    - turn_start/turn_end 边界；
    - tool_use 与 tool_result（含参数与结果）。
  - 为 Agent 提供统一开关：record/replay/auto（从环境或入参启用）。

### 3. 文件格式与版本
- 顶部 Header（第一行 JSON）
  - schemaVersion: "1.0"
  - sessionId: "uuid"
  - provider: "anthropic" | "openai" | "kimi" | ...
  - api: "anthropic-messages" | "openai-completions" | ...
  - model: "kimi-k2.5"
  - adapter: { protocol: "anthropic-messages" | "openai-completions" | "openai-responses" }
  - timebase: "monotonic" | "wallclock"
  - redaction: { pii: true, secrets: true }
  - hashing: { algorithm: "sha256", requestKey: "..." }
- 序列事件（后续每行 1 个对象，按时间顺序）
  - type: "session_start" | "turn_start" | "request" | "vendor_event" | "raw_part" | "agent_event" | "turn_end" | "session_end"
  - ts: number（相对前一事件的毫秒偏移）
  - payload: object（见各事件定义）
- 事件定义（关键）
  - request: 规范化请求（system_prompt/messages/tools/options/headers-脱敏副本）
  - vendor_event: { name, payload, meta }（SSE 行/WS 帧/SDK 事件序列化）
  - raw_part: Loushang RawPart（判别联合，跨 Provider 稳定）
  - agent_event:
    - "tool_use_delta" | "tool_result" | "agent_thought" | "agent_action" 等（按需扩展）

### 4. 时间轴与回放节奏
- 模式
  - real：严格按 ts 还原节奏（研发复现实时问题用）
  - fast：时间压缩系数（如 0.1x）
  - instant：无延迟（CI 快速回归）
- 长会话
  - session 记录 turn 之间的真实间隔；
  - 回放可选择保留间隔或忽略间隔快速跑完。

### 5. 匹配与启动（黑盒模式）
- 本地回放服务器（SSE/WS）
  - 当客户端发起请求时，使用“请求匹配键”匹配录制文件（或索引）：
    - requestKey = hash(normalize(model, binding, system_prompt, messages, tools, options))
    - 忽略 nonce/traceId/时间戳等动态字段
  - 匹配成功即开始推送 vendor-raw 流；匹配失败返回说明（或切换白盒回放）。
- 安全与隐私
  - 仅在本地/内网启用；默认禁网。

### 6. Agent 集成与开关
- 开关优先级（高→低）
  - 显式入参：agent.run(..., record="on" | "off" | "replay", replay_file=..., record_file=...)
  - 环境变量：LOUSHANG_AI_RECORD=on/off/replay、LOUSHANG_AI_RECORD_FILE、LOUSHANG_AI_REPLAY_FILE
  - 配置文件：~/.loushangai/config.json（可选）
- Agent 侧记录内容
  - turn 输入：用户消息/系统提示/工具定义/模型分配（binding）/agent 策略参数
  - 模型流：复用 Provider Recorder（vendor-raw/RawPart 双轨）
  - 工具流：tool_use 增量与 tool_result（参数与结果）
  - turn 输出：最终 AssistantMessage/裁决/元数据（usage/stopReason）
- 回放模式（Agent）
  - Strict：必须匹配请求键，不匹配则拒绝回放
  - Lenient：忽略部分上下文差异，仍按录制流回放，同时输出差异报告

### 7. Provider 接入要点
- Anthropic（httpx/SDK）
  - 录制 vendor_event：`message_start/content_block_* /message_delta/message_stop/error`
  - 同时录制 raw_part：`response_start/text_delta/thinking_delta/tool_call_* /usage_delta/stop_reason/response_done`
  - 记录已脱敏的协议语义：版本标识、fine-grained tools、interleaved thinking
- OpenAI Completions/Responses
  - 录制 SDK 事件或 SSE 行（Completions）
  - 同步生成 raw_part；在 `responses` 兼容代理缺失结束块时由 finally 补齐

### 8. 工具调用与本地回路
- 录制
  - tool_use 增量（作为 raw_part/tool_call_* 与 agent_event/tool_use_delta）
  - tool_result（作为 agent_event/tool_result，含 result 内容/错误）
- 回放
  - 默认直接“推送录制的工具结果”，确保确定性与零 Token
  - 半回放模式：由上层调用方选择保留真实工具执行以联调工具层

### 9. 安全与脱敏
- 写入前脱敏
  - API Key/Secrets：删除或掩码
  - PII/企业标识/文件与 URL：按策略模糊化或置空
- 元信息
  - 保留最小必要的调试信息（provider/api/model/compat）；敏感头仅保留键名或白名单
- 审计
  - 记录 redaction 策略与版本；提供重识别风险评估入口（后续）

### 10. 版本与兼容
- schemaVersion 版本化；各事件类型允许增加可选字段
- 引入 `rawPartsVersion` 与 `vendorEventVersion` 以支持演化
- 回放器按版本选择解析器并输出兼容警告

### 11. 测试与 CI 集成
- 单测
  - Provider 录制：mock 上游事件 → 断言 vendor_event/raw_part 写入正确
  - 回放：加载文件 → 断言高层事件与最终消息一致
- 集成
  - 覆盖主要 Provider（Anthropic/OpenAI/DashScope/Kimi）
  - 覆盖异常与兜底（缺结束块/stop_reason=tool_use 但无细粒度/超时/断线重连）
- CI
  - 基线文件存放与差异报告（final_message/usage/stop_reason/事件序列哈希）

### 12. 开放接口（草案）
- Python API（Agent 层）
  - `with agent.recording(enabled=True, file="session.jsonl", mode="append"): ...`
  - `agent.replay(file="session.jsonl", speed="instant", strict=True)`
- Provider 注册钩子
  - `register_recorder(fn_on_request, fn_on_vendor_event, fn_on_raw_part)`
  - `register_replay_source(kind="rawpart"|"vendor", reader=...)`

### 13. 路线图
- M1：RawPart 录制/回放（白盒）与 Agent 开关
- M2：vendor-raw 录制/回放（黑盒 SSE/WS），请求匹配键与本地服务
- M3：工具链半回放模式、差异报告、可视化时间线
- M4：脱敏策略库、版本迁移工具、CI 基线管理

### 14. 与现有实现的关系
- 不改变现有 RawPart/Assembler 语义；在 Provider 与 Agent 旁路集成
- 文档相关
  - 参考《Loushang-AI 流式事件语义设计（详细版）》
  - 参考《Reference AI SDK 流式事件语义（参考）》
