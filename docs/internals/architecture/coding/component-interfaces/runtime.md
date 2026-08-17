# `runtime`

## Role

- 当前活动 session 的生命周期宿主

## Owns

- `AgentSessionRuntime`
- current session 指针
- create / restore / fork / replace current session 流程

## Depends On

- `session`
- `store`

## Commands

- `create_session(...)`
- `switch_session(...)`
- `restore_session(...)`
- `fork_session(...)`
- `new_session_operation(...)`
- `restore_session_operation(...)`
- `fork_session_operation(...)`
- `import_session_operation(...)`
- `import_from_jsonl(...)`
- `importFromJsonl(...)`
- `replace_current_session(...)`
- `await materialize_package(source)`
- `await dispose()`

## Queries

- `get_current_session()`
- `list_sessions()`
- `list_session_summaries()`
- `find_session_summaries(query)`
- `list_all_session_summaries()`
- `find_all_session_summaries(query)`
- `get_session_diagnostics(query)`
- `refresh_session_index()`
- `refresh_all_session_indexes()`
- `list_indexed_session_summaries(refresh=False)`
- `find_indexed_session_summaries(query)`
- `list_all_indexed_session_summaries(refresh=False)`
- `find_all_indexed_session_summaries(query)`
- `get_packages(catalog_path=None)`

## Events

- 当前无稳定 runtime-level 事件面

## Key Data

- `AgentSession`
- `SessionRecord`
- `SessionSummary`
- `SessionStartEvent`
- `SessionShutdownEvent`

## Out Of Scope

- prompt 组装
- transcript 持久化实现
- policy / tool / exec 细节

## Reference Implementation Alignment

- 语义上对齐 `reference CLI` 的 `AgentSessionRuntime`
- 保留 runtime 作为 session lifecycle host，而不是把这些动作塞回 `session`
- 这里最重要的对齐点是 session replacement / switching lifecycle 的宿主语义
- runtime 是否额外携带 cwd-bound services、diagnostics 等载荷，可以按实现形态调整
- replacement 顺序对齐 `reference CLI`：`session_before_switch` / `session_before_fork` 通过后，先 `session_shutdown(old)`，再创建新 session 并触发 `session_start(new)`
- `fork_session_operation(entry_id, position)` 对齐 fork target 语义：`at` 保留目标 entry，`before` 仅支持 user message 并 fork 到其 parent；其标准 `SessionOperationResult.payload` 承载 selected text
- extension command context 的 `ctx.fork(entryId)` 默认使用 `position="before"`；需要 clone 当前 entry 时显式传 `position="at"`
- runtime 仅提供 snake_case API；Pi-style action aliases 由 extension adapter 在边界投影，不能成为 Python runtime 的第二套 lifecycle surface
- `new_session_operation(...)` 支持 `parent_session` / `setup` / `with_session`；`setup` 必须是 async callable，在新 `SessionManager` 上运行，随后同步 agent messages
- `restore_session_operation(...)` 和 `fork_session_operation(...)` 支持 `with_session`，并在 replacement 完成、新 session 已成为 current session 后执行
- replacement callback 失败不回滚已经完成的 session replacement；错误继续向调用方冒泡，并记录 `session_replacement_callback_failed` runtime diagnostic
- `session_before_switch` / `session_before_fork` / `session_shutdown` hook 失败保持 extension runner 的 non-throwing 语义，同时 runtime 会同步 extension diagnostics，避免 lifecycle 失败只停留在 runner 内部
- `import_session_operation(path, cwd_override?)` 把外部 JSONL 复制进当前 `session_dir`，走 `session_before_switch`，再用 resume lifecycle 替换 current session；`import_from_jsonl(...)` 保留为 Coding SDK 的结果投影入口
- JSONL import 在 loushang 中额外采用非破坏性文件语义：若目标 `session_dir` 已存在同名 session 文件，会生成唯一导入文件名而不是覆盖；若 copy-time 目标被并发创建抢占，会选择下一个唯一文件名重试；`session_before_switch` 只针对最终落盘目标触发；若 hook 取消或复制后 cwd 校验等后续步骤失败，会清理本次导入创建的副本，并保持 current session 不变
- `restore_session_operation(...)` / `import_session_operation(...)` / `rename_session(...)` / `delete_session(...)` 的未处理失败会记录 `session_restore_failed` / `session_import_failed` / `session_rename_failed` / `session_delete_failed` runtime diagnostic；调用方仍收到原异常，诊断层提供稳定 code 与 operation details
- `restore_session(...)` / `switch_session(...)` 支持 reference-style session id prefix 解析；多匹配时返回稳定 ambiguous error，避免 CLI/RPC 上层重复实现 session lookup
- `list_all_session_summaries()` / `find_all_session_summaries(query)` 对齐 `reference CLI` 的 all-session lookup 思路：runtime 以当前 session dir 的父目录作为 sessions root，聚合兄弟 project/session 目录中的 JSONL summaries
- `get_session_diagnostics(query)` 默认限定 current session，保留 runtime 全局 `get_diagnostics(query)` 作为跨 session/service 诊断查询
- runtime 暴露显式 indexed session summary facade，但常规 `list_session_summaries()` / `find_session_summaries(query)` 仍保持 JSONL 直接扫描；是否启用 cache 由 CLI/RPC/TUI 等调用方显式选择
- `auto_refresh_session_index=True` 是 long-running runtime 的 opt-in delayed flush policy：session replacement 和 indexed list 查询会 schedule coalesced index flush；`session_index_refresh_interval` 控制查询侧 debounce，`session_index_flush_delay` 控制延迟 flush，`dispose()` 会 drain pending flush
- runtime session rename/delete 也参与 `auto_refresh_session_index`，因此跨 session store 操作不会留下未刷新的 `.session-index.json` cache
- indexed summary facade 会继承 store 的 stale-cache 自愈语义：如果外部进程删除了已缓存的 session 文件，下一次 indexed 查询会重建相关 index
