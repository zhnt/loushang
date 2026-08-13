# Loushang-AI Implementation Status

本文档已同步到当前实现口径，不再保留 round-1 旧结构叙事。

## 当前实现状态

`loushang.ai` 当前已经形成以下稳定主轴：

- `model/`
  - `domain / registry / loader`
- `provider/`
  - 统一 provider 边界与请求解析
- `providers/`
  - Anthropic / OpenAI / Faux 等具体适配实现
- `messages.py`
  - 消息规范化
- `context.py`
  - `Context` 形状整理
- `event_stream/`
  - raw part 与统一流式事件
- `auth/`
  - 认证解析与 OAuth 支持

## 当前已落地能力

- `stream / complete / stream_simple / complete_simple`
- `ModelRegistry`
- built-in `models.json`
- `APIRegistry`
- `resolve_auth_for_model(...)`
- `ResolvedRequest / ResolvedEndpoint`
- 多 provider 适配主链
- 统一消息、工具、事件流协议

## 当前不再使用的旧结构

以下概念已经移除：

- 旧模型中间层
- 旧 loader 命名
- capability resolver
- 绑定表叙事

如果旧文档或旧代码还提到这些名字，应按当前结构理解并继续清理。
