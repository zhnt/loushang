## Extension Examples

These examples demonstrate the current `loushang-coding` `ExtensionAPI v1` surface.

`01-06` are offline and runnable without API keys. Each script creates a temporary project, writes an extension file using the recommended `register(api)` protocol, and then runs a local coding session against that project.

`11+` are online integration examples. They require API credentials in the environment and run against a real model.

### Examples

- `01_lifecycle.py`: `session_start`, `before_agent_start`, `session_shutdown`
- `02_dynamic_resources.py`: `resources_discover` with prompt and skill resource additions
- `03_custom_tool.py`: `@tool` and tool execution through a session
- `04_tool_guard.py`: `tool_call` and `tool_result` interception
- `05_manifest_visibility.py`: `loushang-extension.toml`, `/extensions`, and extension tool source visibility
- `06_runtime_capability_replacement.py`: permission-gated side-question Runtime Capability replacement and lifecycle
- `11_online_tool_guard.py`: extension interception on top of the real built-in `bash` tool
- `12_online_dynamic_resources.py`: dynamic prompt/skill resources against a real model
- `13_online_resume_with_extension.py`: persisted online session + restore with extension resources still active

### Recommended Protocol

- Recommended: `@tool` for Python-authored tools
- Low-level escape hatch: handwritten `ToolDefinition(...)`

### Extension file location strategy

示例运行器会把 `LOUSHANG_EXAMPLES_EXTENSIONS_DIR` 透传给子进程，默认指向
`examples/coding/.loushang/extensions/`（若未设置则回退该目录）。
当前示例文件主要使用临时工作目录创建 demo extension；如果你想持久管理一套 extension 文件，可直接放在该目录并在
具体示例或自定义脚本中按需加载。

该目录通常由一键初始化脚本创建：

```bash
python examples/coding/init_examples_env.py
```

如果你只想定制扩展目录，直接覆盖参数即可：

```bash
python examples/coding/run.py --extensions-dir /path/to/extensions run legacy-ext-01
```
