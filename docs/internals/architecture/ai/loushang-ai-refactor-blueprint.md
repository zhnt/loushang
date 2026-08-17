# `loushang.ai` 重构蓝图

本文档现在只保留当前重构后的结构结论，不再保留旧中间方案。

## 当前目标结构

`loushang.ai` 当前按以下主轴组织：

1. `model/`
   - 领域对象、registry、装载
2. `provider/`
   - 统一 provider 边界、请求解析、payload helper
3. `protocols/`
   - OpenAI Chat Completions、OpenAI Responses、Anthropic Messages 协议适配
4. `messages.py` / `context.py`
   - 消息规范化与 `Context` 形状整理
5. `event_stream/`
   - raw part 与统一流式事件组装
6. `auth/`
   - 调用凭证解析与 provider auth header 生成
   - OAuth 生命周期、账号选择、quota、billing 和产品级认证策略不属于 AI 包

## 当前原则

- 参考 `reference repository`
- 不引入额外中间层
- 根包只保留 SDK 门面
- provider 边界与具体 provider 实现分开
- `model` 子包不再承担历史中间层语义

## 当前模型侧结论

模型相关结构已经收敛为：

- `domain.py`
- `registry.py`
- `loader.py`

以下旧概念已废弃：

- 全局规格表对象
- 绑定表对象
- endpoint config 中间层
- 旧模型中间层
- capability resolver

## 当前 provider 侧结论

- `provider/`
  - 负责统一请求解析与边界对象
- `protocols/`
  - 负责具体 wire protocol 适配，不承载产品路由

## 当前文档使用方式

如果需要理解当前代码，请优先阅读：

- [`src/loushang/ai/README.md`](../../../src/loushang/ai/README.md)
- [`docs/internals/architecture/ai/README.md`](./README.md)

本文件不再作为旧方案细节的保留地。
