# 使用手册

[English](../../en/user-guide/) | 中文

使用手册说明当前 `loushang code` 相关的产品面。

## CLI 与 TUI

`loushang` 是主 CLI 入口。它支持一次性 prompt 运行、text/print/json/rpc 模式、会话控制、模型列表、命令列表、诊断、工具、扩展、技能、方法、包、导出和 work log。

需要交互式 coding session 时，可以使用 `loushang --tui` 启动终端 UI 产品面。已安装的 `loushang-tui` 命令是同一 TUI 模式的便捷入口。

TUI 模式当前有两个运行面。在 stdin/stdout 都是 TTY 时，`loushang --tui` 和
`loushang-tui` 会打开 screen 交互面。在 `--tui` 下使用管道或重定向 stdio 时，同一模式会使用
plain prompt loop，适合做快速 smoke test：

```bash
printf "hi\n/quit\n" | loushang --tui
```

plain 输出没有单独的 UI selector flag。继续使用 `--tui`，由终端交互性决定具体运行面。

常用起始命令：

```bash
loushang --help
loushang --list-models
loushang --list-commands
loushang --list-sessions
loushang --tui
loushang-tui
loushang -p "Summarize the current project."
```

如果要用 `loushang.tui` 构建终端 UI 应用，见 [构建 TUI 应用](tui.md)。

## 会话

会话保存 coding 对话与执行记录，适合需要恢复、分叉、导出、诊断和后续检查的工作流。

常见操作：

```bash
loushang --list-sessions
loushang --resume
loushang --continue
loushang --resume <session-id-or-path>
loushang --export
```

交互式 `loushang --resume` 和无参数 `/resume` 会打开全屏、可搜索的 continuity 选择器。默认按键中，空格按需加载预览；安装多个 Provider 时 Tab 切换 Domain；Ctrl+S 切换公共排序。`--continue` 恢复当前项目最新会话，`--resume <session-id-or-path>` 和 `/resume <session-id-or-path>` 直接恢复指定会话。非交互模式必须使用这些显式形式之一。

在交互界面中，内置 slash commands 包括 `/session`、`/resume`、`/fork`、`/clone`、`/tree`、`/tools`、`/extensions`、`/export`、`/compact`、`/reload` 和 `/quit`。

## 工具

工具把可执行能力暴露给 agent。Coding 产品包含内置工具面，并支持启用、禁用和收窄工具范围：

新的交互会话默认启用内置 `read`、`ls`、`find`、`grep`、`bash`、`edit` 和 `write` 工具。文件探索优先使用 `ls`、`find`、`grep` 和 `read`；`bash` 更适合 shell 管道、重定向、构建命令、测试和 Git 操作。

```bash
/tools
/tools off bash
/tools only read,ls,find,grep
/tools reset
loushang --tools bash,write -p "Inspect this project."
loushang --no-tools -p "Explain the repository from context only."
```

### LSP 语义工具

`coding.lsp` 是可选的高频 Coding 能力，提供 `inspect_symbol` 和
`document_outline`。默认是 `on_demand`；要让它们进入当前 agent 的默认工具集：

```bash
loushang --capability coding.lsp=always
loushang lsp status
loushang lsp doctor
```

Server 仍只会在第一次语义查询时惰性启动。独立 CLI 的 `status` 和 `doctor` 标记为
`scope=catalog`：它们只检查配置与可执行文件，不构造 Session，也不会启动或安装任何
Server。Loushang 会探测已安装的 Pyright、TypeScript Language Server、rust-analyzer、
gopls 和 clangd。

TypeScript 预设覆盖 `.ts`、`.tsx`、`.js`、`.jsx` 及其标准模块变体，并选择最近的
`tsconfig.json`、`jsconfig.json`、`package.json` 或 `.git` 作为根。用户需要自行安装
`typescript-language-server` 和兼容的 `typescript` 包；缺少可用 Server 时，普通 Coding
工具仍可继续工作，Loushang 不会自动安装任何包。

其他默认预设同样选择最近的语言原生项目根：Pyright 使用 `pyrightconfig.json` 或
`pyproject.toml`，rust-analyzer 使用 `rust-project.json` 或 `Cargo.toml`，gopls 使用
`go.work` 或 `go.mod`，clangd 使用 `.clangd`、`compile_commands.json` 或
`compile_flags.txt`；它们也都会回退到最近的 `.git` 根。

在交互式 Coding Session 内，使用独立的 Session 运行态表面：

```text
/lsp status
/lsp stop <server-id> <root>
```

`/lsp status` 只报告当前 Session 已知的 Server，包括生命周期、打开文档数、请求、超时、
替换次数和已丢弃诊断发布数；查询本身不会启动 Server。`/lsp stop` 优雅关闭精确匹配的
Session Server，下一次语义查询可以按需启动替代实例。嵌入方可使用
`session.get_lsp_status()` 和 `await session.stop_lsp_server(...)` 取得同一份有界状态。
TUI 会直接执行同一个 Session 命令；RPC 客户端可以先用 `get_commands` 发现命令，再在不经过
模型回合的情况下执行：

```json
{"id":"lsp-status","type":"execute_command","command":"lsp","args":"status"}
```

响应会把命令的结构化结果放在 `data.result`。

已经把 `pyright-langserver` 放入 `PATH` 的贡献者可以运行可选真实 Server 门：
`uv run pytest tests/integration/coding/test_pyright_lsp_live.py -q`。未安装 Pyright 时测试会
跳过，测试自身不会安装它。

TypeScript 的对应兼容性门是
`uv run pytest tests/integration/coding/test_typescript_lsp_live.py -q`，默认从 `PATH`
查找 `typescript-language-server`，也可通过 `LOUSHANG_TEST_TYPESCRIPT_LANGSERVER`
指定可执行文件；测试同样不会安装 Server。

gopls 的兼容性门是 `uv run pytest
tests/integration/coding/test_gopls_lsp_live.py -q`，默认从 `PATH` 查找 `gopls`，
也可通过 `LOUSHANG_TEST_GOPLS` 指定；安装仍是独立的开发者或 CI 步骤。

rust-analyzer 的兼容性门是 `uv run pytest
tests/integration/coding/test_rust_analyzer_lsp_live.py -q`，默认从 `PATH` 查找
`rust-analyzer`，也可通过 `LOUSHANG_TEST_RUST_ANALYZER` 指定；贡献者应通过 rustup
安装相互匹配的稳定 toolchain、`rust-analyzer` 与 `rust-src`。

自定义 Server 写入 `~/.loushang/coding/lsp.json`：

```json
{
  "servers": [
    {
      "id": "python-custom",
      "command": ["my-language-server", "--stdio"],
      "language_extensions": {"python": [".py", ".pyi"]}
    }
  ]
}
```

项目的 `.loushang/lsp.json` 可以调整产品默认或用户已声明的 Server，但在通用 workspace
trust 机制完成前，不能从仓库配置引入新的可执行文件或环境变量。

## 扩展

扩展是可以注册生命周期 hooks、工具、动态资源、命令和 flags 的 Python 文件。可以先阅读 [examples/coding/extensions](../../../examples/coding/extensions/) 中的可运行扩展示例。

扩展可以携带相邻的 `loushang-extension.toml` manifest，用来声明身份、权限等级、依赖和预期贡献。使用 `/extensions` 查看已加载扩展、贡献摘要和诊断；使用 `/extensions <id>` 查看单个扩展详情。`/tools` 会在可用时展示 extension tool 的来源信息。

## 包与插件

包与插件可以提供可复用的 coding 资产。常见生命周期命令：

```bash
loushang --list-plugins
loushang --list-packages
loushang --install-package <source>
loushang --check-package-updates
loushang --update-packages
```

## 方法与技能

方法与技能把可复用工作实践变成运行时资产。CLI 中可以使用：

```bash
loushang --list-methods
loushang --show-method <method>
loushang --show-method-plan <method>
loushang --method <method> -p "Run this coding task."
loushang --no-method -p "Run without the configured default method."
loushang --list-skills
```

`--method` 支持非交互的 prompt/print/json 路径。在 method step UI 与 work-event projection 路径就绪前，TUI 和 RPC mode 会继续拒绝 `--method`。

## Work Logs

Work log 会为一次性 prompt/print/json 运行记录 `WorkOperation` 与 `WorkEvent`：

```bash
loushang --work-log .loushang/work/events.jsonl -p "Run this coding task."
loushang --work-log-inspect .loushang/work/events.jsonl
loushang --work-log-inspect .loushang/work/events.jsonl --work-log-inspect-format plans
```

`--work-log` 不支持 TUI 或 RPC mode。

## 诊断与导出

诊断和导出用于检查 session 中发生了什么：

```bash
loushang --list-diagnostics
loushang --diag-export --diag-output diagnostics.json
loushang --export session.html
```
