# Loushang AI API Adapter Registry

本文记录当前 `loushang.ai` 的 API adapter 注册和路由边界。

## APIAdapter

`APIAdapter` 是唯一正式术语，直接定义为 Protocol：

```python
class APIAdapter(Protocol):
    api: str

    def invoke_raw(self, request: ProviderRequest) -> AsyncIterator[RawPart]: ...
```

Adapter 按 API 语义翻译请求和响应，例如 `openai-responses`、
`openai-completions` 和 `anthropic-messages`。它不是模型服务 `Provider`，也不拥有
模型目录。

## APIRegistry

`APIRegistry` 维护 `api -> APIAdapter` 的通用 adapter 映射，提供：

- `register_api_adapter(adapter, source_id=None)`
- `get_api_adapter(api)`
- `list_api_adapters()`
- `unregister_api_adapters(source_id)`
- `clear_api_adapters()`

注册时会验证 `api`、`invoke_raw(request)` 和可选的
`validate_request(request)`；重复 API 注册立即失败。

内置 adapter 由 `register_builtin_api_adapters()` 注册。高级进程级配置通过
`loushang.ai.advanced.registry` 使用同一套 adapter 术语。

## ProviderRegistry

`ProviderRegistry` 保留厂商专用 adapter 优先路由，键为
`(provider_id, api)`。解析顺序固定为：

```text
ProviderRegistry exact (provider_id, api)
    -> 命中：厂商专用 APIAdapter
    -> 未命中：APIRegistry.get_api_adapter(api)
```

这两层不是两套模型选择机制。调用前已经获得 Endpoint 完整、包含生效配置的
`Model`；registry 只选择如何执行该 `Model` 所声明的 API。

## 调用链

`stream()` 和 `complete()` 共享以下路径：

```text
Model
-> ProviderRequest(model=Model, ...)
-> ProviderRegistry.resolve_api_adapter(model.provider_id, model.api)
-> APIAdapter.invoke_raw(request)
-> RawPart
-> AssistantMessageEventStream / AssistantMessage
```

`ProviderRequest.mode` 区分 `stream` 和 `complete`，不会产生第二条 adapter 路径。

## 边界

- `ModelRegistry` 维护 `Provider -> Endpoint -> Model` 目录并返回完整 `Model`。
- `ProviderRegistry` 维护厂商/API 精确 adapter 路由。
- `APIRegistry` 维护通用 API adapter fallback。
- `APIAdapter` 执行协议翻译，不选择 Endpoint 或 Model。
- 公共调用仍只传 `Model`，不注入 registry 或单独传 Endpoint。
