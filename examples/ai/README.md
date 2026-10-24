# AI examples

`examples/ai` 展示当前 `loushang.ai` 公共调用边界。编号示例全部离线运行，
不会访问真实厂商。

## 编号示例

1. `01_complete.py`：完整返回与最终 `AssistantMessage`。
2. `02_stream.py`：事件流和 `result()`。
3. `03_typed_context.py`：显式 `Context`、`Tool`、`UserMessage`。
4. `04_tools.py`：工具调用、严格参数校验和结果回传。
5. `05_parallel_tools.py`：并行 tool call 增量组装。
6. `06_reasoning.py`：`ReasoningOptions`。
7. `07_structured_output.py`：结构化输出映射与解析。
8. `08_image_input.py`：图片输入与图片工具结果。
9. `09_errors_retry.py`：稳定错误载荷与 retry trace。
10. `10_usage.py`：response usage 和未知价格。
11. `11_provider_matrix.py`：内置 catalog 概览。
12. `12_provider_smoke.py`：可选真实调用入口。

`custom_model_file.py` 展示显式装载自定义 catalog。

内置 catalog 当前覆盖这些 provider：

- `anthropic`
- `baidu-qianfan`
- `dashscope`
- `deepseek`
- `minimax`
- `moonshot`
- `openai`
- `stepfun`
- `tencent-hunyuan`
- `volcano-ark`
- `zai`

常用 API key 环境变量包括 `ANTHROPIC_API_KEY`、`QIANFAN_API_KEY`、
`DASHSCOPE_API_KEY`、`DEEPSEEK_API_KEY`、`MOONSHOT_API_KEY` 和
`STEPFUN_API_KEY`。具体 endpoint 声明以 `models.json` 为准。

OpenAI 的 `openai-responses` 与 `coding-responses` catalog 路由均列出
`gpt-6-sol`、`gpt-6-astra`、`gpt-6.1-sol` 和 `gpt-6-luna`。例如可用
`get_model("openai", "openai-responses", "gpt-6.1-sol")` 获取标准 API 模型。
`coding-responses` 使用 ChatGPT OAuth，实际可用模型仍由账号权限决定。

MiniMax 的普通模型列表在每个 endpoint 内按 `MiniMax-M3.1-Flash`、`MiniMax-M3`
排序，Flash 的 catalog alias 为 `default-chat`。例如：

```python
model = get_model("minimax", "anthropic-messages", "MiniMax-M3.1-Flash")
```

Flash 强制开启 thinking，默认 effort 为 `max`；可通过 `ReasoningOptions(effort=...)`
选择 `low`、`medium`、`high`、`xhigh` 或 `max`（通用 `minimal` 映射到 `low`）。
`enabled=False` 会在发送请求前报错。Anthropic 使用 `output_config.effort`，
OpenAI Chat Completions 使用 `reasoning_effort`。M3 保持可选 thinking，不发送深度档位。

两个 Anthropic Flash 路由默认请求预算为 8192 tokens，与模型的 524288 输出能力上限
分开记录，以兼容 Anthropic SDK 的非流式超时检查。显式 `max_output_tokens` 和自定义
模型默认值仍优先使用，不会被静默截断。较大预算（例如 32000）请使用 `stream()`；
Anthropic 0.89.0 的默认客户端会在发送 HTTP 前拒绝这样的非流式请求。自定义 adaptive
模型在关闭 thinking 时保留显式 temperature，开启 thinking 时仍省略 temperature。

OpenAI Chat Completions 的 JSON 和 SSE 响应保留 reasoning 文本及来源字段名。
将返回的 `AssistantMessage` 连同 `ToolResultMessage` 传入下一次调用时，MiniMax 的
`reasoning_content` 按原值回传；其他兼容服务的 `reasoning` / `reasoning_text` 也保留
各自字段语义，不需要手动重建 thinking 内容。整条响应共用一个 thinking 累加器，
因此字段标记在该响应内只记录一次；SSE 中 text/tool 与 reasoning 交错也不会重复标记。

Catalog 的可选字段 `listed: false` 只隐藏普通列表项；显式 `get_model`、完整
`ModelSelection` 和 `list_models(model_id=...)` 仍能读取旧模型。`listOrder` 只控制
endpoint 内排序，默认值为 0；自定义文件可以显式覆盖整个模型定义。
因此旧 MiniMax-M2.7 配置保持原 ID，不会被静默迁移。

Flash 的 1M context / 524288 output 上限用于文本与 SDK 已支持的图片输入；此 SDK
没有 video 消息类型，因此不声明视频能力。全球路由记录 Flash 的 USD 单价；未推断
国内路由价格。M3 分档价格无法由当前 flat `Pricing` 表达，因此保持未知，避免误算。
来源：[模型说明](https://platform.minimax.io/docs/guides/models-intro.md)、
[价格](https://platform.minimax.io/docs/pricing/overview)、
[OpenAI 兼容接口](https://platform.minimax.io/docs/api-reference/text-openai-api.md)、
[Anthropic 兼容接口](https://platform.minimaxi.com/docs/api-reference/text-anthropic-api.md)。

运行全部离线示例：

```bash
uv run python scripts/ai/check_examples.py
```

## 常规调用

```python
from loushang.ai import ApiKeyAuth, CallOptions, complete, get_model

model = get_model("moonshot", "openai-completions", "kimi-k2.6")
message = await complete(
    model,
    {"messages": [{"role": "user", "content": "Hello"}]},
    CallOptions(auth=ApiKeyAuth("...")),
)
```

`message.provider`、`message.endpoint` 和 `message.model` 共同记录完整响应来源。

公共 `complete` 和 `stream` 不接收 registry 参数。

## 高级示例

`advanced/` 用于 catalog 检查、归一化诊断、trace、取消和自定义 adapter。
自定义 adapter 通过进程级高级 registry 注册：

```python
from loushang.ai.advanced.registry import (
    clear_api_adapters,
    register_api_adapter,
)

clear_api_adapters()
register_api_adapter(custom_adapter)
```

高级离线 faux 示例：

- `advanced/faux_stream.py`
- `advanced/context_tools_minimal.py`
- `advanced/tool_result_roundtrip.py`
- `advanced/cancel_stream.py`
- `advanced/trace_events.py`
- `advanced/inspect_endpoint_contract.py`
- `advanced/custom_catalog.py`

## OpenAI Codex live validation

真实的上层应用验证位于 `examples/auth/openai_codex_live_example.py`。它选择
`openai:coding-responses:gpt-5.5`，调用公共 `auth.get_auth(model)`，再把认证显式传给
公共 `stream()`。示例不读取 token 文件，也不直接调用 credential source。

## Live tests

真实厂商验证位于 `tests/ai/vendors/`，默认跳过。运行时必须显式设置
`LOUSHANG_AI_LIVE=1` 并提供对应 API key，或使用 Makefile 的
`vendor-ai-*` 目标。
