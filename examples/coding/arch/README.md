## Architecture Analysis Example

`01_import_graph.py` 使用公共 `loushang.coding.arch` API 构造并分析一个临时 Python package，不需要模型或网络凭据：

```bash
uv run python examples/coding/arch/01_import_graph.py
```

正式的模块 CLI 也可以直接分析现有源码树：

```bash
uv run python -m loushang.coding.arch \
  src/loushang \
  --package-prefix loushang \
  --granularity subsystem \
  --imports all \
  --query summary \
  --pretty
```

模块 CLI 默认把按文件归一化事实缓存到
`$LOUSHANG_HOME/cache/coding/arch/`（默认 `~/.loushang/cache/coding/arch/`）。
可用 `--no-cache` 禁用、`--refresh-cache` 强制重建，或用 `--cache-info`
把易变的缓存命中统计加入 JSON；默认查询 JSON 不含这些运行时统计，因此冷、热查询保持一致。

在长期运行的 tool/session 进程中应复用一个 `ImportGraphAnalyzer` 实例。它默认持有内存事实缓存；第二次及后续扫描只为文件计算内容指纹，单文件内容变化只重解析该文件。需要跨进程复用时，可给构造器传入带路径的 `ImportFactCache`。

`scripts/arch/analyze_import_graph.py` 是供仓库 CI 和维护脚本使用的薄适配器，不是首选的用户示例入口。

维护者可以用同进程性能 gate 验证高频调用路径；它先强制冷扫描，再要求每次未修改的热扫描全部命中缓存，默认最大延迟为 1 秒：

```bash
uv run python scripts/arch/benchmark_import_graph.py \
  src/loushang \
  --package-prefix loushang \
  --pretty
```

CLI 默认使用位于 `LOUSHANG_HOME/cache/coding/arch` 的版本化逐文件事实缓存；可用
`--refresh-cache` 强制重建，或用 `--no-cache` 禁用。维护者可以单独运行可重复性能门槛：

```bash
uv run python scripts/arch/benchmark_import_graph.py \
  src/loushang \
  --package-prefix loushang \
  --max-warm-seconds 1 \
  --max-reload-seconds 1 \
  --max-query-seconds 0.1 \
  --pretty
```

计时从依赖导入完成后开始，分别报告冷扫描、同进程热扫描、磁盘缓存重新加载和纯查询，
因此不会把 Python 进程启动时间误算为分析器延迟。
