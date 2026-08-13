# `loushang.ai` 领域模型

本文以当前 `src/loushang/ai/model/` 实现和 `models.json` 为准，描述模型接入领域语义。

## 核心结构

模型接入结构固定为：

```text
Provider -> Endpoint -> Model
```

- `Provider` 是模型服务提供方，也是 Endpoint 的归属边界。
- `Endpoint` 是 Provider 下的一条完整模型接入通道，声明 `api`、地址、认证、静态
  headers、adapter 配置、defaults 和模型清单。
- `Model` 是 Endpoint 下可直接调用的模型。

同一个 `model_id` 可以出现在多个 Endpoint 下。模型的完整、唯一标识始终是：

```text
provider:endpoint:model
```

因此，`provider + model_id` 不是已经确定的模型身份。

## Provider

`Provider` 位于 `providers.{provider_id}`，包含元数据、可选认证声明和 Endpoint
映射。Provider 不负责选择 API adapter，也不是可调用对象。

## Endpoint

`Endpoint` 位于 `providers.{provider_id}.endpoints.{endpoint_id}`，是一条完整接入
通道。主要事实包括：

- `api`
- `baseUrl` / `baseUrlEnv`
- `region` / `lane`
- `auth`
- `headers`
- `adapter`
- `defaults`
- `models`

Endpoint 直接持有 Model。`region` 和 `lane` 只是 Endpoint 属性，不构成新的领域层级。

## Model

`Model` 位于
`providers.{provider_id}.endpoints.{endpoint_id}.models.{model_id}`。原始模型定义包含
能力、价格、模型级认证或 adapter 覆盖、defaults 和上游模型 ID 等事实。

`ModelRegistry` 构造索引时，将 Endpoint 的生效配置合并进每个 `Model`。Registry
返回的 `Model` 已经携带：

- `provider_id` 和 `endpoint_id`
- Endpoint 的 `api` 和地址
- 生效认证与静态 headers
- 合并后的 adapter 配置和 defaults
- Model 自身的 capabilities、pricing 和 upstream ID

这个 `Model` 是完整调用对象。公共 `complete()` / `stream()` 只接收 `Model`，不会再
单独接收 Endpoint，也不会在调用阶段重新选择 Endpoint。

## ModelSelection

`ModelSelection` 是已经确定的模型轻量引用，不是选择偏好：

```python
@dataclass(frozen=True)
class ModelSelection:
    provider: str
    endpoint_id: str
    model_id: str
```

三个身份字段都必须是非空字符串。`ModelSelection` 始终可以格式化为完整的
`provider:endpoint:model`，并由 `ModelRegistry.resolve_model_selection()` 解析为完整
可调用的 `Model`。配置传递、目录转换和持久化不得删除 `endpoint_id`。

最外层文本输入可以使用 `provider:model`（也接受 `provider/model`）或分别提供
provider 与 model 的简写，但
补全规则固定为：

1. 按 `provider + model_id` 查询候选。
2. 恰好一个候选时，立即补全 Endpoint 并生成完整 `ModelSelection`。
3. 没有候选时返回不存在错误。
4. 多个候选时返回列出完整三元组的歧义错误。

`preferred`、默认 Endpoint 和候选顺序都不能用于打破歧义。

## API adapter 路由

`APIAdapter` 是 API 调用适配单元的唯一正式术语，最小契约为
`api + invoke_raw(request)`。调用路由保留两层：

1. `ProviderRegistry` 先按 `(provider_id, api)` 查找厂商专用 adapter。
2. 未命中时，回退 `APIRegistry` 中按 `api` 注册的通用 `APIAdapter`。

`ProviderRegistry` 只负责厂商专用优先路由，不拥有模型目录；`APIRegistry` 只拥有
通用 API adapter 注册。两者都不会改变已选定的 `Model`。

## AssistantMessage 来源

流式和非流式调用共用同一事件装配路径。每个 partial/final `AssistantMessage` 都记录：

- `api`
- `provider`
- `endpoint`
- `model`

其中 `provider:endpoint:model` 可以还原响应的完整模型来源。`endpoint` 只记录响应
来源，不改变调用只传 `Model` 的边界。

## 边界约束

本领域不增加另一套模型绑定对象或 resolver 层。`Provider -> Endpoint -> Model`、
`ModelRegistry`、`ModelSelection`、`APIAdapter` 和 `AssistantMessage` 已覆盖本次所需
语义；认证类型、OAuth 生命周期和 `ProviderRequest` 也不因模型身份收敛而改变。
