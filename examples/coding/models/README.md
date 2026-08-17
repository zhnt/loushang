# Example Model Catalog Overrides

Kimi Code 等官方支持的 provider、endpoint 和 model 统一维护在
`src/loushang/ai/model/models.json`。本目录不提供会被示例默认加载的真实 provider
catalog，避免示例配置遮蔽内置配置并发生漂移。

只有需要验证私有网关或尚未进入内置 catalog 的模型时，才在这里创建兼容
`providers -> endpoints -> models` 结构的自定义 JSON，例如：

```json
{
  "providers": {}
}
```

自定义 catalog 必须显式传入：

```bash
uv run python examples/coding/run.py \
  --model-catalog examples/coding/models \
  run legacy-001
```

也可以设置 `LOUSHANG_EXAMPLES_MODEL_CATALOG`。未显式设置时，示例使用内置
catalog；`LOUSHANG_EXAMPLES_ARTIFACT_ROOT` 下由初始化脚本生成的 catalog 副本仅用于
用户主动选择的本地定制流程。
