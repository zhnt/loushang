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
