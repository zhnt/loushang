# 测试去重实施记录

本记录是[测试与 PR 门禁重构方案](test-and-pr-gate-refactoring-plan.md)的实施证据，不能替代全量语义审查或远程性能验收。当前接受范围为下述已确认重复项与 AppHost Linux 同配置重复执行；其他项仍待审查。

## 0. 全仓完全相同函数体复核（2026-10-14）

在远端 `main` 的 `ed01d756` 上，对全部 `tests/**/test_*.py` 进行静态 AST
复核：保留函数参数、decorator 和函数体，只忽略测试函数名称及源码位置，再按
规范化 AST 哈希分组。没有发现可直接删除的普通 unit/contract 完全重复函数。
仅有两类完全相同函数体，均因执行配置不同而保留：

- Windows 与 POSIX epoch cutover 的并发收敛测试各验证独立平台实现，不能以函数
  体相同视为重复平台覆盖。
- DashScope/Moonshot 的 live stream/tools/complete 包装测试调用各自文件绑定的
  provider fixture，函数体相同但外部模型、协议和凭据配置不同；它们继续留在
  显式 live 路径，不进入 PR 门禁。

该扫描只证明没有“忽略名称后完全相同”的剩余低风险删除项，不证明近似实现、
参数矩阵或不同写法覆盖相同行为。后续语义去重仍须逐候选比较断言、fixture、
marker、平台和最终 collected node ID。

## 1. 全仓候选扫描

2026-10-14 扫描当前任务工作树的 1475 个 `test_*.py` 文件、13755 个静态 `test_` 函数定义。比较忽略位置和函数自身名称的完整 AST，保留参数、装饰器和函数体，发现 10 组候选。参数化实际运行数量、全局配置、共享夹具和被包含但不完全相同的断言不在这项扫描的证明范围内。

完成映射删除后以相同算法复扫，剩余 3 组：POSIX/Windows epoch 收敛各一项、五个 vendor live wrapper、两个 Kimi OpenAI stream/complete wrapper，均为下表已审查且保留的平台或 provider 变体。当前树不再有未处置的完整 AST 重复簇；这不代表近似 AST 或语义包含关系已经全仓审完。

| 候选 | 上下文核对 | 处置 |
| --- | --- | --- |
| AI `test_api_streaming.py` 的 register/get 两个 legacy signature 用例 | 同文件、同 provider、同 registry，实际都只调用 register 并检查相同异常 | 合并到 register owner |
| AI 同文件 optional legacy signature 两个用例 | 同一 `_LegacyProviderWithOptionalDebug`、相同调用与异常 | 合并到 register owner |
| 五个 vendor live 测试 wrapper | 各模块的 main、模型/协议和工具配置不同 | 保留；wrapper 相同不代表网络行为相同，不执行 live 验证 |
| 两个 Kimi OpenAI live wrapper | 分别调用 stream/complete 示例流程 | 保留；全局函数不同 |
| Coding 两个 UI 文件的 non-interactive 用例 | 两个函数体相同，均 patch 同一 mode 入口；两套 helper 对被断言的 runtime/current session/prompt 行为相同 | 删除 Screen 复本，保留聚焦的 UI mode owner |
| Coding session codec 的 native/read-only v3 rejection | 同文件、同 tmp_path 隔离、同 `load_session_repository`，并未调用不同入口 | 合并为原 native 用例 |
| Harness events/host 的 subscribe/unsubscribe | 相同 canonical 导入、无局部夹具、同父级 conftest | 仅 events owner 保留 |
| Harness events/host 的 scheduled listener serialization | 同上，相同事件栅栏、调度顺序与 drain 断言 | 仅 events owner 保留 |
| Harness events/host 的 no-loop rejection | 同上，相同定制错误与拒绝断言 | 仅 events owner 保留 |
| POSIX/Windows epoch concurrent convergence | owner、平台跳过条件、布局/ACL 配置不同 | 保留对应平台覆盖 |

## 2. 已实施的旧用例到保留集合映射

以下旧 node ID 可在基线提交 `1f1fcaf1` 中核对。已删除项均不携带独有参数、失败分支、平台或生命周期差异。

| 旧用例 | 保留用例 | 等价或包含依据 |
| --- | --- | --- |
| `tests/resource/test_frontmatter.py::test_harness_frontmatter_entrypoint_is_canonical` | 同文件 `test_legacy_resource_frontmatter_path_preserves_harness_owner_identity` | 同一 parse 函数身份断言被包含，其他导出/错误类型身份仍保留 |
| `tests/coding/test_session_file_codec.py::test_read_only_repository_rejects_session_v3_without_rewriting_source` | 同文件 `test_native_repository_rejects_session_v3_without_rewriting` | 完整函数体等价，均检验 v3 拒绝、错误码与原文件字节不变 |
| `tests/harness/host/test_events.py::test_ordered_event_bus_subscribes_and_unsubscribes` | `tests/harness/events/test_bus.py::test_ordered_event_bus_subscribes_and_unsubscribes` | 相同 canonical 类型、订阅/退订和监听状态断言 |
| `tests/harness/host/test_events.py::test_ordered_event_bus_serializes_scheduled_async_listeners` | `tests/harness/events/test_bus.py::test_ordered_event_bus_serializes_scheduled_async_listeners` | 相同受控 async listener，串行与 drain 行为完整保留 |
| `tests/harness/host/test_events.py::test_ordered_event_bus_no_loop_rejects_async_listener_with_configured_error` | `tests/harness/events/test_bus.py::test_ordered_event_bus_no_loop_rejects_async_listener_with_configured_error` | 相同无事件循环拒绝及定制异常信息 |
| `tests/ai/test_api_streaming.py::test_get_api_adapter_stream_rejects_legacy_provider_signature` | 同文件 `test_register_api_adapter_rejects_legacy_provider_signature` | 两者构造同一 `_LegacyProvider` 和空 registry，均只调用 `register_api_adapter` 并断言相同 TypeError；旧名称未经过 get/call 路径 |
| `tests/ai/test_api_streaming.py::test_get_api_adapter_stream_rejects_legacy_optional_arg_signature` | 同文件 `test_register_api_adapter_rejects_optional_legacy_argument_signature` | 两者构造同一 optional-debug provider，调用与异常断言完全相同；无独有 get/call 行为 |
| `tests/coding/test_screen_coding_tui_mode.py::test_run_coding_tui_non_interactive_keeps_plain_prompt_loop` | `tests/coding/test_ui_mode.py::test_run_coding_tui_non_interactive_keeps_plain_prompt_loop` | 两个函数体完全相同，均 patch 同一 mode 入口并断言非交互分支、prompt 与参数集合；保留 fixture 更小且职责更聚焦的 UI mode owner |
| `tests/coding/test_file_mutation_queue.py::{test_mutation_queue_serializes_same_file_operations,test_mutation_queue_uses_canonical_same_file_identity}` | `tests/harness/workspace/test_mutation_queue.py::test_mutation_queue_serializes_canonical_same_path` | canonical Harness owner 同时覆盖相同路径串行与不同拼写归一化，包含基本同路径场景 |
| `tests/coding/test_file_mutation_queue.py::test_mutation_queue_allows_different_files_to_progress_independently` | `tests/harness/workspace/test_mutation_queue.py::test_mutation_queue_allows_different_paths_to_progress` | 都用受控 event 栅栏证明不同绝对路径不会共享锁；Harness 用例无脆弱的 0.1 秒完成超时 |
| `tests/coding/test_file_mutation_queue.py::test_mutation_queue_rejects_relative_paths` | `tests/harness/workspace/test_mutation_queue.py::test_mutation_queue_rejects_relative_paths` | 同一 canonical API、相同异常类型和消息 |
| `tests/coding/test_file_mutation_queue.py::test_mutation_queue_cleans_up_lock_entries_after_use` | `tests/harness/workspace/test_mutation_queue.py::test_mutation_queue_context_tracks_and_releases_active_path` | 独有的持锁期间可见与退出清理断言迁入 canonical owner |
| `tests/coding/test_file_mutation_queue.py::test_run_with_file_mutation_queue_serializes_callback_operations` | `tests/harness/workspace/test_mutation_queue.py::test_mutation_queue_runner_serializes_callbacks_and_returns_results` | 独有的 callback 串行、顺序及返回值断言迁入 canonical owner |
| `tests/coding/test_file_mutation_queue.py::{test_run_with_file_mutation_queue_accepts_sync_callback,test_mutation_queue_uses_its_direct_harness_owner}` | `tests/harness/workspace/test_mutation_queue.py::test_mutation_queue_runner_accepts_sync_results_and_cleans_up` | 统一保留同步 callback 返回与锁清理；从同一模块重复导入后比较对象身份没有额外消费者边界 |
| `tests/coding/test_file_mutation_queue.py::test_run_with_file_mutation_queue_cleans_up_after_callback_error` | `tests/harness/workspace/test_mutation_queue.py::test_mutation_queue_cleans_up_after_callback_failure` | 同一 canonical runner、异步异常传播与锁表清理 |
| `tests/ontology/test_action_schema.py::test_schema_v3_documents_are_not_loaded_as_v4` | `tests/ontology/test_schema.py::test_schema_v3_documents_are_not_loaded_as_v4` | `load_json` 在解析内容前按同一 format 字段拒绝 v3；换用包含 action 的合法 v4 草稿不会形成新的版本边界 |
| `tests/coding/test_frontmatter.py::{test_parse_frontmatter_normalizes_crlf_and_block_scalars,test_parse_frontmatter_supports_simple_lists_and_maps,test_parse_frontmatter_supports_nested_maps}` | `tests/harness/resources/test_frontmatter.py::{test_parse_frontmatter_normalizes_newlines_and_block_scalars,test_parse_frontmatter_supports_lists_and_nested_maps}` | Coding 文件直接导入 canonical Harness parser，没有 Coding adapter；Harness owner 覆盖 CRLF/block scalar、list 和 nested map 的相同解析边界 |
| `tests/coding/test_frontmatter.py::test_parse_frontmatter_keeps_original_body_without_complete_frontmatter` | `tests/harness/resources/test_frontmatter.py::{test_parse_frontmatter_returns_plain_content_unchanged,test_parse_frontmatter_preserves_unterminated_document}` | Harness owner 分别保留普通正文与未闭合 frontmatter 的原文保持，并额外校验完整结果值 |
| `tests/coding/test_frontmatter.py::test_parse_frontmatter_reports_invalid_yaml_location` | `tests/harness/resources/test_frontmatter.py::test_parse_frontmatter_reports_source_location` | 同一 canonical 异常、输入及 line/field 断言 |
| `tests/coding/test_prompt_assembly.py::test_prompt_template_args_do_not_recursively_substitute_argument_values` | `tests/harness/capabilities/test_prompt.py::test_template_expansion_does_not_reprocess_argument_values` | 完整调用、恶意占位符参数和输出断言相同；Coding 文件直接调用 canonical Harness helper，没有 Coding adapter |
| `tests/ai/test_provider_contract_matrix.py::test_builtin_registration_is_frozen_to_core_adapter_matrix` | `tests/ai/contracts/test_core_provider_contracts.py::test_builtin_registration_matches_core_contracts` | 两份矩阵包含同一三个 core adapter，均对 builtin registry 的排序 API 集合做相同断言；文档矩阵文件保留文档一致性职责 |
| `tests/ai/test_provider_contract_matrix.py::test_core_production_adapters_implement_api_adapter_contract` | `tests/ai/contracts/test_core_provider_contracts.py::test_core_adapters_implement_invoke_raw_contract` | canonical contract 对同一三个具体 adapter 保留全部旧断言，并额外验证 PreparedRequest adapter、prepare 与 invoke_prepared 签名 |
| `tests/coding/test_workspace_path_mutation_compatibility.py::test_workspace_mutation_queue_preserves_owner_identity` | `tests/harness/workspace/test_mutation_queue.py` 的 canonical runner/context 行为集合 | 两种导入写法都解析为同一个 Harness 模块，没有 legacy Coding facade；同模块对象自等不构成消费者合同 |
| `tests/coding/test_screen_coding_tui_mode.py::test_run_coding_tui_non_interactive_keeps_plain_prompt_loop` | `tests/coding/test_ui_mode.py::test_run_coding_tui_non_interactive_keeps_plain_prompt_loop` | 两个函数体完全相同，均 patch 同一 mode 入口并断言非交互分支、prompt 与参数集合；保留 fixture 更小且职责更聚焦的 UI mode owner |

Harness host 测试文件只包含这三个重复项，且也直接导入 canonical events 类型，没有独有 facade 合同，因此删除整个重复文件。canonical events 的失败传播且不阻塞后续事件用例继续保留。

## 3. AppHost Linux 一次执行与报告派生

主回归一次执行原集合，并补入原 G8 独有的 `test_product_normal_close_retires_exact_attempt_without_global_rollback`。G8/G9/G10 后续步骤从主 JUnit 派生报告，不再重复执行 pytest。

- join：完整 `tests.coding.test_apphost_product` 与上述 Worker close node。
- composition/rollback：完整 `tests.coding.test_apphost_composition`。
- canary：原四个文件中带 G10 标识的用例；其他架构约束也在主回归执行。
- 原 manifest 精确 case ID、最少数量、零跳过/失败/错误校验继续执行。
- installed canary 的真实安装验证仍单独执行，它与源码回归的运行配置不同。
- Windows 验证未因 Linux 派生报告被删除，跨平台去重需另行证明。

[报告派生器](../../../scripts/ci/derive_junit.py)拒绝来源失败/错误、重复身份、声明与实际数量不符、选择缺失、所选用例跳过以及覆盖来源文件。保留测试结果和 suite properties，不执行 Product、不共享可变状态。来源中合法平台 skip 可以不进入派生报告；所选必需用例必须真实通过。

## 4. 当前验证与剩余工作

- 合并执行的重点集合：62 项通过，27.74 秒；派生 join/composition/canary 报告分别为 19/16/13 项，原 manifest 均通过。
- 去重后的完整事件总线与 session codec 文件：15 项通过，1.58 秒。
- Resource 去重后：4 项通过，1.28 秒；Work 完整初审集合：45 项通过，3.71 秒。
- CI 合同：117 项通过，包含报告派生的缺失、跳过、失败、重复与数量矛盾负例；Ruff、Actions 语法和 diff 检查通过。
- 完整 AppHost 主集合离线验证：2646 项通过、11 项跳过，518.16 秒；跳过项均为明确的 Windows native 条件，不作为 Linux 通过的原生证据。三个报告从这份完整结果再次派生，原 manifest 全部通过。已验证同次执行没有导致该集合的夹具或顺序失败；本地附加 `not live and not requires_host_runtime`、`--skip-host-runtime`，因此仍不是所有执行配置的验收。
- 完整报告显示反复扫描全仓的静态依赖检查单项耗时 60.804/42.307/21.760 秒；两个终端进程死亡恢复用例分别为 38.180/31.081 秒。这些是后续共享扫描和能力拆分的实测依据，不以增加超时解决。
- 上述数字为本地执行，不证明 PR 排队和总耗时达标；真实 installed 与 Windows 运行仍待交付验证。

仍需完成其他非相同 AST 的语义重复、全部目录角色与夹具影响、其余跨工作流唯一执行、历史 job 重组、必要原生场景和真实多次 PR/main 验收。当前共删除 27 个旧 node ID，其中 mutation queue 的 2 个独有合同迁入 canonical Harness owner；数量变化本身不代表全部单元测试去重完成。

## 5. 共享全仓源码扫描准备

AppHost A0、A0.2、A0.3/A0.4 与 Hosted Application G11 的导入扫描统一采用[共享导入事实](../../../tests/architecture/_source_imports.py)。同一进程、同文件内容只解析一次 AST，返回新的结果集合；源文本变更立即失配，缓存只保留不可变导入元组，不缓存可变 AST、Product 状态或会话资源。

保留各消费者原有解析模式：是否包含 from-import 的成员、是否显式拒绝越界相对导入。所有 32 个测试函数的完整 AST 与改动前相同，参数化收集的 32 个用例身份也与完整基线报告一致，32 项全部通过。

旧完整 AppHost 报告中这四个文件的 testcase 时间累计 148.515 秒；新聚焦执行墙钟 20.83 秒。前者为用例时间总和、后者包括聚焦执行准备，且运行时负载不同，因此只作为初步改善证据，不能宣称严格对照倍数或远程总耗时达标。四个消费者覆盖保持，其他消费者与完整远程流程仍待验证。

新增缓存合同验证覆盖绝对/相对/别名/条件导入、两种成员模式、相同输入单次解析、返回集合隔离、同大小同时间戳内容变更、非法相对导入与语法错误；CI 合同增至 121 项通过。

完整 `tests/architecture/test_import_boundaries.py` 也有自己的相对导入错误格式和
成员展开语义，不能直接改用不同返回约定。该文件现在按 `文件名 + 实际源码内容`
缓存不可变的绝对导入 tuple；每次调用仍重新读取源码，内容变化立即形成新键，
返回给调用方的 list 也彼此隔离。全部现有边界测试身份和断言保持不变。同机完整
165 项对照从 537.86 秒降到 83.79 秒；旧远程 #746 报告中的同文件 testcase 时间
合计 134.02 秒，最终远程收益仍以本次 PR 运行确认。

Harness 模块报告中 `test_exec_capture.py` 的 14 个 reader failure 组合各等待测试
请求的 3 秒预算，累计 42.70 秒。它们保留全部 task publication point、before/
after fault 与 reader/non-reader 组合；仅把测试请求预算收紧为 1 秒。断言仍要求
原始 reader 异常、进程退出及 stdout/stderr transport 关闭，不把超时本身作为成功。

## 6. AI 示例唯一执行

旧 `check-ai` 先由 `scripts/ai/check_examples.py` 子进程执行所有离线 AI 示例，再由 `tests/examples` 重跑它们，最后 coverage 又运行 `test_ai_examples.py`；同时把 Agent/Coding/Harness examples 带入 AI gate。现在保留带文件清单、环境清理、输出和公开导入断言的 pytest owner，把 AI 与 Auth example tests 各放入 coverage 执行一次，移除重复脚本阶段及无关 examples 全目录。示例脚本本身和独立检查工具仍保留；变更只收敛 PR gate 的重复执行。

完整新配置实测 858 项通过、7 项 marker deselect，45.18 秒；总覆盖率 90.65%，三个细分 coverage target 均通过。Ruff、76 个 AI 源文件 mypy、catalog 和 import boundary 同时通过。该数据是本地执行时间，不包含远程 runner 安装和排队。

## 7. Coding 混合集合拆分

PR #742 的 8 个 Coding 分片报告共执行约 4,798 项。slowest 列表中的主要耗时来自真实终端/PTY、子进程服务、安装 wheel、包迁移/删除/GC CLI、Worker 修复和完整插件旅程；这些文件按实际边界登记为 integration、platform 或 e2e，而非按 `not live` 标记继续归入单元。

策略 v4 先登记 55 个有运行或静态进程边界证据、且适合整文件迁移的文件。未登记的 372 个文件仍在保守模块集合中，避免把尚未审查的测试默认为单元；targeted 文件变更精确执行自身，不再同时展开 8 个模块分片和通用 E2E。初次候选中的 9 个混合文件仍保留在模块回归，防止同文件的参数解析、选择算法、注册表或纯计划单元用例丢失。代表文件 `test_package_gc_cli.py` 两项通过，耗时 53.75/47.29 秒，证明它是应按能力触发的真实 CLI 集成场景。

第一轮仅移出 slowest 报告出现的 30 个文件时，原最慢 2/8 分片本地仍为 593 项通过、10 项跳过、9 分 18 秒。哈希重新分配及剩余跨进程文件使尾部没有改善，因此不据此减少分片数；第二轮扩展到所有已核对的显式进程边界后再做远程测量。此记录不宣称 Coding 全目录分类完成。

第二轮收紧为 55 个适合整文件迁移的文件后，同一 2/8 分片为 545 项通过、4 项跳过、1 项失败、7 分 29 秒。失败的 lmux selector 用例单独复跑 14.89 秒通过，属于需要继续治理的顺序/环境敏感信号；本次只把 1 分 49 秒的耗时下降作为方向性数据，绿色与全分片尾部以远程 PR 运行确认。

PR #743 的完整远程运行 `38554483283` 为 6 分 04 秒，8 个 Coding job 为 2 分 09 秒至 3 分 30 秒；此前 #742 最慢 Coding 用例阶段为 7 分 48 秒。Ubuntu/macOS/Windows 恢复会话冒烟为 23/41/40 秒，全部通过。合并后的 push 运行 `38555330728` 使用同树、同计划证据，在 58 秒内完成。该结果证明第一批拆分已达到 15 分钟目标，但不代表剩余 Coding 文件完成语义分类。

第三轮从 #743 的 8 份 slowest 报告继续复核。新增 13 个适合整文件迁移的真实执行、托管会话、持久化、LSP、终端和恢复文件，targeted 合计 68 个，359 个文件继续保守回归。候选 `test_hosted_session.py` 同时包含 Ubuntu 集成和 Windows 原生条件用例，Ubuntu 为 18 项通过、1 项跳过，已撤回整文件分类，等待 node 级分类。

部分分类把 Coding 目录展开为显式文件后，pytest 的 `--ignore` 不会再次排除同一显式参数，导致 39 个由 Harnesstui/Coding UI 独立拥有的文件重新进入 Coding 后端；#743 的两个 13 秒全仓 import 扫描即由此重复。runner 现在先从显式 Coding 集合移除这 39 个文件，同时保留 Harnesstui/Coding UI owner。新增 13 个 targeted 文件在合并验证集合中全部通过；修正后的本地 0/8 为 463 项通过、2 项平台条件跳过，原 #743 远端 0/8 为 538 项通过、3 项跳过。不同 runner 的墙钟不作倍数比较，下一次远程全选确认最终尾部。

PR #744 远程全选运行 `38557834260` 绿色完成于 4 分 58 秒。Coding 8 个 job 为 2 分 04 秒至 2 分 57 秒，0/8 从 #743 的 3 分 30 秒降为 2 分 56 秒；Ubuntu/macOS/Windows 恢复冒烟为 26/40/64 秒。该结果确认重复 owner 移除和第三轮分类没有丢失顶层必需检查。

完整验证覆盖补强：此前 catalog targeted 文件只在自身发生改动时执行，schedule/manual full 会从模块集合排除它们却不生成 targeted job。现在 full plan 枚举所有非 live targeted owner，并按平台、类别和稳定路径哈希合并为 19 个批次（当前 76 个平台执行），避免 76 次独立环境安装。普通 PR 仍只批处理实际改动的 targeted 文件。批处理使用 JSON 路径数组和 Python 参数列表，不经过 shell 路径拼接；JUnit 验证要求每个登记文件至少有一项通过，不能由同批其他文件掩盖全 skip。双文件实际执行 11 项通过，两个文件均通过文件级报告验证。

## 8. 跨工作流实际执行去重

PR #746 的运行 `38563194640` 提供了所有活动 pytest job 的 JUnit。审计按
`classname + name` 比较实际 testcase，并区分派生报告、平台变体、skip 和独立
pytest 进程；报告条目重复不直接计为重复执行。

- G8/G9/G10 Linux 三份报告来自同一份 AppHost 主报告，分别包含 19/16/13 项，
  不启动 pytest，因此不是 48 次额外执行。
- AppHost Linux 主报告为 2657 项，其中 11 项平台 skip；它与 Linux 模块、
  Harnesstui/Coding UI 报告共有 1174 个均通过的 testcase。
- 上述 1174 项在 AppHost 进程中的 testcase 时间合计 5.65 秒，在其他 owner
  中合计 4.76 秒。即使全部从 AppHost 删除，可直接归因的 pytest 时间上限也
  只有 5.65 秒；不能把 1174 的数量当作尾部收益。
- AppHost 其余 1483 个身份的 testcase 时间为 144.96 秒。主要成本是终端进程
  死亡恢复、双 mux 交互、真实 Coding 断线恢复、native/installed canary、
  托管进程清理和全仓架构扫描；它们不是模块 job 中已经执行的同配置复本。
- Ubuntu、macOS、Windows 的恢复会话冒烟属于不同平台配置；相同测试身份不按
  普通重复删除。Windows AppHost 的 G8/G9/G10/G13 也需先按平台独有断言审查，
  不能用 Linux 报告代替。

结论：删除 AppHost 与模块的廉价重合项只能减少收集与少量执行开销，不是当前
尾部的主要手段。下一轮应逐项判断 144.96 秒独有集合中哪些是普通 PR 必需冒烟、
哪些适合按变更触发或定时运行。任何因此新增或扩大 test route、平台、job 或失败
条件的方案均先进入审批包；未获明确批准前只记录建议，不修改门禁。

首批执行归属收敛移除 AppHost PR 主回归中的四个已有 targeted owner：
`test_hosted_local.py`、`test_mux_product_terminal.py`、`test_mux_subprocess.py` 和
`test_mux_terminal_process.py`。它们在 #746 AppHost 报告中合计 56.16 秒；直接修改
由 catalog 的 Ubuntu integration/platform job 执行，schedule/manual full 也会
执行，且本地 `make check-apphost` 继续包含完整集合。普通 AppHost PR 保留
`tests/apphost` 全包、架构合同、G8/G9 组合、G10 native/installed canary、Windows
G8/G9/G10/G13 及独立三平台核心冒烟。本批只删除旧 PR 清单归属，不新增 job、
test route、平台、触发或失败条件。

随后对 catalog 的 77 个 targeted 文件逐一生成 test-only 计划。旧选择器在选中精确
targeted job 后仍继续套用目录和 Makefile 清单，使 20 个整文件 owner 额外选择
AppHost，另一个 node 级混合文件额外选择 architecture。选择器现在以 catalog 作为
已审查 test-only 路径的完整 owner：整文件和专用夹具只执行既有 targeted job；
node 级混合文件同时执行原模块剩余节点与既有精确节点。源码、未知测试、共享夹具
和 CI 编排仍走原影响规则。该变化删除旧规则误触发，不新增 job、route、平台、
触发或失败条件。

同一提前收敛也移除了四个已分类 Worker test-only 文件附带的完整 Windows native
矩阵，其中 candidate wheel 过去还会选择持续查询。对应源码平台边界、三个未分类
Windows Worker 测试和 schedule/manual full 仍保留原完整矩阵；被修改的四个测试
继续在 catalog 声明的平台执行自身场景。

## 9. Protocols 测试支撑代码合并

`tests/protocols` 的 4 个测试文件包含 101 个静态测试函数，参数化后收集 109 个
实例。逐项按协议入口、输入分区和断言复核后，没有可删除的行为复本：相似的
max-token、reasoning、auth、tool-call 和资源关闭用例分别约束 Anthropic Messages、
OpenAI Chat Completions、OpenAI Responses 的不同 wire payload 或生命周期。所有
SDK 调用由 fake module、内存 adapter 或合成事件驱动，不访问真实网络。

三个真实协议文件此前各自复制同一套 context normalization、request mode 转换和
stream 启动代码，只替换 API 名称。该驱动已合并到 `_runtime.py`，协议文件通过
绑定 API 名称复用；测试 node、参数、fake SDK、输入与断言均未改变。改动净减少
75 行测试支撑代码，完整目录仍为 109 项通过、1.36 秒。所属 AI 完整离线回归
858 项通过、7 项 live deselect，31.28 秒；总覆盖率 90.65% 及三个细分阈值、
Ruff、mypy、catalog 和 import boundary 均通过。本批减少维护重复，不改变门禁、
route、平台、触发或失败条件。

## 10. Root、Examples 与 Integration 初审

Root 的 1 个实例只约束打包 console script。Examples 的 49 个静态函数收集为
61 个实例，按 Agent、AI/Auth、Coding 和 Harness 的公开示例分别验证公开导入、
受控 fake 模型或认证、脚本 help/import 与独有输出。忽略函数名的完整 AST 没有
重复测试；相似的 module loader 属于多个模块 owner，共享它需要先定义跨 owner
测试助手的影响路由，因此本批不以无归属 helper 替换局部代码。

Integration 的 10 个静态函数收集为 42 个实例：4 个显式 `live` LSP Server
兼容用例，5 个 Ontology 内存/SQLite 产品组合实例，以及 33 个 manifest 示例
子进程 smoke。LSP 用例分别验证 Pyright、TypeScript、gopls、rust-analyzer 的真实
协议和诊断生命周期；Ontology 用例覆盖 action/fact 投影与真实 SQLite 重启、身份
拒绝边界，不能跨平台或存储配置合并。

Root、Examples 与 Integration 的非 live 联合运行结果为 97 项通过、3 项失败、
4 项 live deselect，3 分 58.95 秒。`legacy-007/013/019` 三个示例在各自新建临时
目录首次创建 Session 时稳定得到 transcript writer `conflict/unavailable`；精确
复跑仍为 3 项失败、12.89 秒，不能作为绿色证据。manifest smoke 的 33 个参数逐个
启动子进程，最慢两个为 24.69 秒和 20.11 秒；当前正常 PR workflow 不执行该文件，
直接修改它却会因无 owner 保守选择全量门禁。为它新增 targeted owner 会增加测试
route，须单独审批；本批仅记录问题，不改变门禁、测试身份或失败条件。

## 11. CI 合同初审

`tests/ci` 当前有 6 个文件、139 个静态测试函数和 139 个收集实例：

- `test_change_gates.py` 的 95 项覆盖选择与暂停、顶层聚合、suite 清单、Git diff
  范围、工作流结构和轻量文档链接检查；
- `test_test_catalog.py` 的 16 项覆盖完整目录、targeted 文件/node、专用夹具、
  schema 拒绝和执行计划归属；
- 其余 28 项分别覆盖 JUnit 证据派生、模块报告完整性、PR 证据复用和导入事实缓存。

这些用例只使用临时 Git 仓库、合成 JUnit、fake GitHub API、静态工作流文本及
mock 执行器，不运行 Product 或访问网络。忽略函数名和源码位置的完整 AST 扫描
没有重复簇。选择器与 catalog 的相似路径样本分别证明“触发集合”和“清单归属”；
JUnit 派生与模块报告分别证明“子集证据真实”和“模块集合完整”；证据复用与顶层
聚合分别证明“可复用来源匹配”和“当前运行不会误绿”。这些失败面不能由另一组
断言替代。

完整目录 139 项通过，2.493 秒。当前成本很小，删除或跨文件合并不会显著缩短 PR，
却会降低失败定位或引入共享夹具状态，因此本批保留全部节点。审计没有增加 required
check、workflow、job、route、平台、触发或失败条件。

## 12. Dev 目录初始分组与误路由收敛

`tests/dev` 的 45 个文件包含 406 个静态测试函数，参数化后收集 1674 个实例。明确
绑定当前 worktree 源码的 Linux 离线运行结果为 1669 项通过、5 项平台条件跳过，
243.10 秒。这里混合了纯比较/收据合同、真实子进程监督、进程树回收、临时 Git 与
wheel、POSIX 行为及跨平台 observer，不能把目录整体归作快速单元。忽略函数名和
源码位置的完整 AST 扫描没有重复簇；参数矩阵和相似合同仍待继续语义审查。

路由逐文件检查发现，18 个 `test_lmux_*` 文件和
`test_screen_first_probe_readiness.py` 复用已有 G18 runner、comparison 或 Coding
probe，却没有进入 G18/AppService 路径规则。它们的 test-only PR 因此使用未知路径
全量回退，误选八类 workflow。现将 19 个路径加入已有 G18/AppService owner，静态
验证均收敛到相同的 `docs`、`appservice`、`host_runtime` check 与 `units`、`e2e`
workflow；这只删除无关选择，未增加任何门禁。

AppService 工作流仍按用户要求暂停，现有 owner 也不直接执行这 19 个测试文件。
若要在修改这些测试时新增精确 targeted 执行，将形成新的 PR 失败条件；按审批规则
须先提交成本、断言和回退方案，本批不实施。

同一目录的首个执行成本重复位于
`test_recovery_seed_rejects_changed_workload`：12 个故障参数都先创建完整真实 Session
seed，约 4.2--4.7 秒后才分别改写一个输入分区。现在模块级创建一次与原路径绑定的
合法 cwd seed，并保存只读文件快照；函数级 fixture 在每个参数前删除上一份活动树，
从快照恢复到同一原路径，再返回重新解码的 record 与重新构造的 scope。这样保留
绝对 cwd、scope fingerprint、session identity 和每例独立初态，也避免在不同路径
复制 seed 导致路径绑定失真。

12 个原 node ID 和 fault 参数全部通过。聚焦重复运行分别为 12.54 秒与 8.99 秒；
完整 `test_measure_g18_native.py` 为 250 项通过、4 项平台跳过，55.86 秒。相同机器
上的完整 Dev 回归从 194.89 秒降到 138.37 秒，1669 项通过、5 项平台跳过，减少
56.52 秒。该文件当前仍属于暂停的 AppService 路径；收益适用于本地、手动及未来经
审批恢复后的执行，不据此声称当前 PR 墙钟同步减少。

该优化 PR 的首轮远程计划还暴露一项执行重复：G18 test-only 改动除既有 owner 与
模块回归外，又被通用未审查路径规则附加三平台 Resume E2E，而 E2E 不执行这些 Dev
测试。G18 规则现复用既有 reviewed-test 语义，test-only 只保留原 owner、依赖和
模块回归；源码与未知路径继续保守选择。本次只移除无关 E2E，不增加 route、job、
平台或失败条件。

PR #763 同分支远程对照中，旧运行 `38588834269` 的两个模块单元为 18/19 秒，三平台
Resume E2E 为 29/41/63 秒，总墙钟同口径 84 秒。新运行 `38589276148` 保留模块单元
并明确跳过 E2E，总墙钟 61 秒；`changes` 在两轮间从 10 秒波动到 26 秒，所以实际
端到端净减少 23 秒，不能把三个 E2E job 的时间直接相加作为墙钟收益。

## 13. Architecture 目录部分初审

`tests/architecture` 当前有 62 个测试文件和 654 个收集实例。它不是单一快速单元
套件：文件分别进入 Harness、Hosting、AppHost 等历史清单，且包含全仓源码库存、
导入边界、文档状态、平台证据和运行时所有权合同。控制分支上的首次整目录性能探测
在 900 秒上限时仍约有 12% 未完成；该控制分支包含未推送提交，因此这次探测只作为
成本证据，不作为远端主线通过或失败结论。不能把整目录加入普通 PR 门禁。

首个确定热点位于 `test_hosted_product_runtime_v1_baseline.py`。其中
`test_current_inventory_matches_source_and_retained_absences` 为寻找 AppHost 反向依赖，
原先对 `src/loushang` 下每个 Python 文件执行 AST 解析。基于 `origin/main` 的隔离
基线为 16.48 秒。现在先检查源码是否包含断言所需的精确 `loushang.apphost` 前缀；
不含此前缀的文件不可能由原助手返回匹配项，候选文件仍走相同 AST 解析。导入事实
同时按文件名和实际源码内容缓存为不可变 tuple，对调用方继续返回独立 set。

同一节点优化后为 0.81 秒，约快 20 倍；该文件全部 11 项通过、总计 1.73 秒。
测试名称、断言、源码读取和候选文件 AST 语义均保持不变。

路由复核还发现，该测试已同时列入 `HOSTING_TEST_PATHS` 和
`APPHOST_TEST_PATHS`，却因不在已完整分类的目录中又附加三平台 Resume E2E。
选择器现在把现有 Makefile `*_TEST_PATHS` 当作 test-only 文件的既有 owner：保留
所有原 owner 和依赖，只停止追加不执行这些文件的通用 E2E。源码、未知测试、
非 Python 支持文件、专项 targeted 路由和完整验证保持原规则。该文件的计划由
`Hosting + AppHost + E2E` 收敛为 `Hosting + AppHost`；139 项现有 CI 契约全部
通过。此项只删除重复执行，没有增加 check、workflow、job、route、平台、触发或
失败条件。

远程首轮还暴露 AppHost workflow 内部耦合：同一个 `apphost` 开关同时启动普通
回归和 Windows native 证据，即使计划已明确关闭 E2E。Windows native job 现在只在
既有 `apphost` 与 `e2e` 风险位同时成立时运行；AppHost 源码、未知变更和完整验证仍
满足该条件，已审查 test-only 改动只保留普通回归。`apphost-quality.yml` 自身的修改
归入已有 CI 契约短路径，由路由/聚合合同与 actionlint 验证，不再为了验证 YAML
条件而执行产品和 Windows native 场景。这同样只收窄现有门禁。

继续按实际执行命令复核后，62 个文件中有 12 个同时列入两个历史 Makefile owner：
7 个属于 AppHost/AppService，1 个属于 AppHost/Hosting，4 个属于 Harness/Hosting。
这些清单重叠不等于当前重复执行：AppService、Hosting 和 Harness workflow 仍处于暂停
状态。恢复任何一个暂停 workflow 前，必须先为重叠文件确定唯一执行 owner；不得只从
一侧删除后让另一侧独有源码变更失去合同覆盖。

另有 13 个文件未被上述历史 owner 清单覆盖。其中
`test_architecture_documentation.py` 已由顶层轻量文档检查直接执行 9 个纯函数合同，
生成依赖事实由既有 Architecture source-facts job 校验；
`test_coding_wave_a_budget.py` 已由 Harnesstui 清单执行。两者过去仍附加不读取这些文件
的产品 E2E，现分别复用既有 reviewed-test 语义，计划收敛为 Architecture 与
Harnesstui 原 owner，E2E 关闭。

剩余 11 个文件共 107 项静态架构合同。逐文件路由显示，它们因未知路径回退而选择
几乎全部活动 workflow 和 7 个模块回归，但这些 workflow 都没有执行被修改的 11 个
文件本身。这是“高成本且无直接覆盖”的路由缺口。为它们建立精确执行 owner 会增加
test route 和失败条件，已单列为方案中的待审批 AP-02；本批不实现该路由。

这 11 个文件的相同本地命令基线为 107 项通过、402.46 秒。四个文件各自重复解析
同一批全仓 Python 源码，现统一复用按“文件名 + 实际源码内容”缓存的不可变 import
facts；Unified Plugin 的多种只读 AST 派生检查也在同模块内复用同一语法树，并在模块
结束时清缓存。没有删除或增加测试节点，也没有改变相对导入处理、成员展开或断言。
相同 107 项优化后为 213.69 秒，减少 188.77 秒（46.9%）；原 RCP2 最慢项从
49.16 秒降至 0.23 秒。

第二轮剖析显示 graph mutation helper 已取得扁平 code-unit AST，却又对每个节点
递归 `ast.walk`，单个测试在 cProfile 下产生约 1.1 亿次函数调用；现在直接扫描扁平
节点，并只让源码范围含四个敏感字段的函数进入原 mutation/alias 分析。live binding
预筛选则因方法名 `on` 的普通子串匹配几乎读取了每个 Python 文件；现在先匹配完整
`on` 词元，对可能用转义或相邻字符串组成 `"on"` 的少量源码再用 tokenizer 解码，
其他长标识保持原匹配。这避免把 `connection` 一类普通单词当成候选，也不允许通过
转义字符串绕过原 AST 检查。

完整 Unified Plugin 文件 55 项从 97.78 秒降至 48.66 秒；相同 107 项命令进一步从
213.69 秒降至 156.22 秒。相对最初 402.46 秒基线共减少 246.24 秒（61.2%）。所有
测试节点、预期库存、合成 alias/reflection/模块级负例及失败语义保持不变；没有增加
或扩大门禁。当前最大剩余项为 15--19 秒的独立 owner/resource/runtime 全仓语义
扫描，继续合并前需逐项证明派生事实等价。

第三轮确认这些独立扫描中仍有可证明等价的候选过滤。Owner foundation 和 RCP1
只在源码含各自完整导入前缀时读取共享 import facts；Contribution type 只对含目标
标识符的源码解析顶层赋值；runtime dependency 也复用相同不可变 import facts，继续
只统计绝对 `loushang.*` 导入。RCP0 原先已收集函数 AST，却在五类调用/属性检查中从
每个节点再次递归后代；现在每个函数只生成一次等价扫描序列，并保留 lambda 内调用
归属于外层函数的既有库存语义。Legacy loader import inventory 也只解析含完整导入
前缀的候选文件。

Owner、RCP1 和 Contribution 三个独立热点由 19.23、18.55、11.23 秒降至聚焦复跑的
0.91、0.29、0.14 秒；完整 RCP0 文件 9 项为 10.50 秒。相同 107 项最终为 81.19 秒，
比第二轮 156.22 秒再减少 75.03 秒（48.0%），比最初 402.46 秒共减少 321.27 秒
（79.8%）。107 个测试节点和预期库存保持不变；本轮仍未实现 AP-02 或任何新增门禁。

## 14. Architecture 目录完整初审

62 个文件、654 个收集实例已完成角色、执行边界、历史 owner 和完全重复扫描。忽略测试
函数名称后对 AST 函数体做全目录精确比较，没有完全重复实现。全部文件属于源码依赖、
架构库存、文档状态、生成物 freshness 或纯内存对象合同；平台命名文件读取各平台源码、
manifest 和既有证据，不直接调用 Windows/macOS 原生机制。只有 4 个文件启动子进程，
目标是仓库内文档生成器或隔离 Python import 检查，不启动 Product 会话、网络服务或
真实平台进程。

历史 Makefile 清单为 49 个文件提供 owner，其中 12 个重复归属：7 个同时属于
AppHost/AppService，1 个属于 AppHost/Hosting，4 个属于 Harness/Hosting。其余 13 个
文件中，文档合同和 Coding budget 已有独立执行 owner；11 个文件仍属于 AP-02 的
未归属合同。重复清单当前不等于重复活动执行，因为 Harness、Hosting、AppService
workflow 仍暂停；恢复前必须审批并确定唯一 owner，不能同时恢复两侧历史副本。

基于合并后的远程主干首次完整复跑在 701.71 秒结束，652 项通过、2 项失败。两个失败
都来自提交 `efcf40f7` 新增的 Windows Worker C5/Supervisor semantic base 已进入主干，
但堆叠分支中已有的 Architecture allowlist 更新没有随产品文件合入。当前基线补入这
两个消费者及 recovery inventory 的实际 `activation_state_journal` 导入；这只是让
既有精确库存追上已接受源码，不增加断言或测试节点。

同批继续消除测试实现重复：C5.0/C5.4 和 RCP5 复用按文件内容缓存的不可变 import
facts，C5.0/C5.2 只对含目标 import token 的候选源码解析 AST。Import 语义、相对导入
展开、成员 allowlist 和星号排除保持原合同。C5.0 热点从 44.24 秒降至 2.18 秒，C5.2
从 61.86 秒降至 0.68 秒，RCP5 两个 30 秒热点合计降至 0.48 秒。四个受影响文件 30 项
完整回归通过；Architecture 全目录最终 654 项通过、无 skip，503.68 秒（8 分 23 秒），
比本轮初测减少 198.03 秒（28.2%）。Ruff 通过。

这证明完整 Architecture 合同本身可在单个 Ubuntu runner 的 15 分钟预算内完成，
但不授权把它加入普通 PR。把 62 个文件收敛到 Architecture canonical owner、恢复暂停
范围，或让 AP-02 的 11 个文件首次阻断合并，都会新增/迁移 route 与失败条件，仍须按
门禁增加审批规则提交触发范围、唯一 owner、墙钟、重复关系和回退方案后实施。

## 15. Hosting 目录完整初审与暂停 workflow 内部去重

`tests/hosting` 的 28 个文件包含 309 个静态测试函数，参数化后收集为 454 个实例。
逐文件执行边界如下；分类依据实际依赖与副作用，不依据 Windows/POSIX 文件名：

| 类别 | 文件 | Linux 收集实例 | 角色 |
| --- | --- | ---: | --- |
| 受控单元/合同 | `test_contracts.py`、`test_endpoint_host.py`、`test_process_host.py`、`test_platform_selection.py`、`test_windows_handle_probe.py`、`test_windows_launch_preparation.py`、`test_windows_lpac_preparation.py` | 137 | 不启动真实 Product 进程；使用内存 fake backend/Win32 seam、合成 PE/ACL 与状态机验证合同、错误和资源所有权 |
| 混合合同与 native | `test_child_session_host.py`、`test_windows_endpoint.py`、`test_win32_process.py`、`test_windows_process.py` | 113 | 大部分为 fake/状态机合同，但分别含真实 POSIX round trip 或 Windows pipe、Job、进程/crash 节点，不能整文件归为单元 |
| POSIX/真实进程边界 | `test_machine_identity.py`、`test_native_conformance.py`、`test_posix_process.py`、`test_service_process.py`、`test_posix_endpoint.py`、`test_service_group.py`、`test_linux_service_observer.py`、`test_service_handoff.py`、`test_posix_release_launcher.py`、`test_posix_launch_preparation.py` | 160 | 使用真实文件描述符、socketpair、pidfd、进程组、编译产物、wheel、进程 crash/回收或完整 Host/Session 组合 |
| 平台选择合同 | `test_posix_launch_preparation_platform.py`、`test_windows_launch_preparation_platform.py` | 2 | 在当前平台证明选择精确 backend，其他平台证明 fail closed；不启动子进程 |
| Windows 专项 | `test_plc9c5_c53_windows_mechanics.py`、`test_plc9c5_c55b_windows_lpac_native.py`、`test_windows_launch_preparation_native.py`、`test_windows_lpac_preparation_native.py`、`test_windows_backend_material_native.py` | 42 | 真实 Windows token、LPAC、Job、image identity 与 containment evidence；Linux 全部跳过 |

忽略测试函数名称后的完整 AST 函数体扫描没有完全重复簇。相似的资源关闭、拒绝和
故障矩阵分别覆盖不同获取阶段、所有权转移点、平台 API 或未知结果语义，当前没有证据
可删除其断言。Linux 初始全目录为 401 项通过、53 项平台跳过，46.10 秒；其中
`test_posix_release_launcher.py` 四项占 18.65 秒，每项都重新调用会进行两次可重复性
编译的 release builder。现在模块级构建一次只读模板，每项复制到独立 `tmp_path`
后继续执行原有重复构建拒绝、wheel reproducibility/install/tamper、进程组、start
gate 和权限隔离断言。该文件 4 项全部通过，降至 13.97 秒；共享的是不可变构建输入，
每项会修改的 release、catalog、wheel、payload 和进程资源仍独立。

暂停的 Hosting workflow 还存在同一次候选、同一平台的确定重复：Ubuntu 的
`test_posix_launch_preparation.py` 与 `test_posix_release_launcher.py` 先由 H6.2 专项
执行，随后又随 `tests/hosting` 全目录执行；Windows 的 launch-native、backend
material、C5.3 与 C5.5b 四个文件也先生成并验证专项 evidence，随后全目录重跑。
合同阶段现按 matrix 平台使用 `--ignore` 排除已经由前序专项成功执行的文件；macOS
没有对应前序专项，仍执行完整适用目录。没有删除测试、job、平台、报告校验或失败
传播，也没有增加 route、触发或失败条件。

去重后的 Linux 执行并集仍精确覆盖 454 个实例：H6.2 两文件 31 项通过、30.74 秒；
其余目录 370 项通过、53 项平台跳过、9.29 秒。两份报告 node 总数为 31 + 423，交集
为空，等于原全目录收集数。仅这两段顺序执行由原全目录基线及重复专项约 76.84 秒
降至 40.03 秒；真实 workflow 还包含 H6.2 的 Coding/native wheel 用例和依赖准备，
因此该数字不冒充完整远程墙钟。

后续复核确认 #711 已让 `unit_hosting` 直接执行 `tests/hosting` 完整目录；历史
`unit-tests.json` 的 3 文件、44 项只是配置清单，不限制当前 pytest 参数。因此其余
410 项并不存在 test-only 覆盖缺口。AP-03 现只保留 unit/contract、混合 node、POSIX
进程与 Windows platform 的精确归属提案；新增平台 owner 或恢复 workflow 仍须审批。

本批首次远程运行还显示，单独修改暂停的 `hosting-quality.yml` 会按通用 scoped
workflow 规则附加 Agent、Hosting 模块和三平台 Resume E2E。它们均不执行或验证该
YAML 的独有编排；Hosting workflow 本身随后又被暂停规则关闭。该文件现与已处理的
`apphost-quality.yml` 一样走现有 CI 合同短路径，由 139 项路由/聚合合同、文档检查
和 `actionlint` 验证，只删除无关模块及 E2E 选择。恢复 Hosting workflow 前须重新
审查这条短路径；本次没有增加 check、route、平台、触发或失败条件。

## 16. AI 目录完整初审

`tests/ai` 的 56 个文件包含 540 个静态测试函数，参数化后收集 719 个实例。49 个
非 live 文件主要使用 fake SDK module、合成 provider stream、内存 registry、临时
credential/model 文件和受控 async signal；URL 字符串本身不代表网络访问。

其中只有两个非 live 节点越过纯单元边界：
`test_auth_api.py::test_login_returns_session_without_opening_browser` 启动本机 OAuth
callback listener 并以受控 client 完成回调；
`test_auth_oauth_lifecycle.py::test_real_authlib_login_store_resolve_refresh_lifecycle` 使用
本机 `ThreadingHTTPServer`、真实 Authlib/httpx loopback 交换和临时 credential store。
它们不访问公网，但属于 integration。其余 710 个非 live 实例为受控单元/合同。

`tests/ai/vendors` 下 7 个文件各有一个显式 `live`/`vendor_verification` 实例，分别
验证 DashScope 与 Moonshot/Kimi 的 OpenAI Responses 或 Anthropic wire 行为；默认
由 marker 和凭据条件排除，不能并入普通离线 PR。忽略函数名称后的完整 AST 扫描仍
得到两组 wrapper：五个 provider/protocol scenario wrapper，以及 Kimi OpenAI 的
stream/complete wrapper。它们的局部函数体都只是调用模块级 scenario，但被调用的
scenario、wire 模式和生命周期不同，因此保留；这与此前初步重复记录一致。

完整非 live 目录实测 712 项通过、7 项 live deselect，7.55 秒；最慢的真实 OAuth
loopback 生命周期为 0.58 秒，其余单项不超过 0.40 秒。当前没有执行热点值得通过共享
可变状态、减少错误矩阵或缩短确定性超时来优化。此前已删除 `test_api_streaming.py`
中两项实际只重复调用 register 的用例；本轮未发现新的可证明语义复本，没有删除节点。

后续复核确认 #711 已把 package runner 改为：包测试目录存在时直接运行完整目录。
因此上述 7 文件只是历史 JSON inventory，并没有限制当前 `unit_ai` 的 pytest 参数；
普通 AI test-only PR 已执行完整 `tests/ai`、`tests/protocols` 和 AI/auth examples 合同，
原记录的 564 项覆盖缺口实际不存在。指定审批方于 2026-10-15 明确允许 AP-04：两个
OAuth loopback 节点登记为 Ubuntu targeted integration；其余 710 项继续由 AI 模块
任务执行。AI 源码 PR 和对应 test-only PR 选择精确 loopback job，普通 AI 模块命令
deselect 两节点。全量 AI coverage 若同时排除两节点实测为 89.68%，低于既有 90%
门槛，因此 coverage 采集保留两节点作为明确例外；7 项 live vendor 场景仍不进入普通 PR。

## 17. AppHost 目录完整初审与测试准备提速

`tests/apphost` 的 64 个文件包含 693 个静态测试函数，安全离线选择器下收集 1217
个实例。完整执行为 1216 passed、1 skipped；唯一跳过项是
`test_harness_session_integration.py::test_adapter_windows_native_backend_is_explicitly_fail_closed`，
它要求 Windows native backend。其余集合不访问公网或真实大模型，但并不全是单元
测试：13 个文件直接使用 `subprocess`，多个 managed 文件覆盖真实文件、SQLite、锁、
本机 socket、进程和信号边界。临时 managed 根还要求整条祖先目录链满足私有权限，
因此本地审计使用 mode `0700` 的独立临时根，不能把普通 repo-local 临时目录失败解释
成 Product 死锁或回归。

后续复核确认 #711 已让 `unit_apphost` 直接执行 `tests/apphost` 完整目录；历史
`unit-tests.json` 的 7 文件、165 项不限制当前 pytest 参数。修改其余 57 个测试文件时，
现有 test-only 路径会运行被修改文件及完整 1217 项离线集合，并且不会附加全局 E2E。
AP-05 现只保留 unit/contract、真实进程及平台节点的精确归属提案；新增 targeted 或
平台失败条件仍须审批。

本轮没有删除测试节点。忽略函数名称后的完整 AST 扫描未发现完全重复函数；managed
故障矩阵虽然结构相近，但覆盖不同事务阶段、持久状态和恢复结果，不能仅凭相似代码
合并。两处已确认的成本来自测试准备，而非被验证行为：

- launcher 的 cold hello 用例原先真实等待 10.1 秒，只为证明 15 秒 owner budget 不会
  被默认 10 秒 connection phase 截断。现在推进事件循环单调时钟并让出一次调度；若
  默认 10 秒 timeout 仍错误包裹 hello，它仍会触发，聚焦执行由 10.11 秒降至 0.43 秒。
- managed log reader 原先为构造读取边界逐条执行 220 次锁、SQLite 和 durability 写入。
  现在先用一次真实 write 建立并绑定 charged file，再用生产 `_encode` 构造同样的 220
  个合法 frame，一次写入测试夹具；真实 `os.pread`、切断首帧、序号 121--220 与读取
  上限断言保持不变，聚焦调用由 5.23 秒降至 0.07 秒。

相同完整命令优化前为 1216 passed、1 skipped、103.74 秒，优化后为 1216 passed、
1 skipped、87.87 秒，墙钟减少 15.87 秒（15.3%）；最慢单项降到 2.02 秒。该结果只
证明 Linux 安全离线集合和本轮测试准备修改，不替代 Windows native、installed 或
远程 runner 证据，也不批准 AP-05。

## 18. Coding 当前目录增量初审

当前 `tests/coding` 已增长到 440 个 `test_*.py` 文件、3959 个静态测试函数。既有
classification catalog 登记 68 个整文件 owner：53 个 integration、14 个 platform、
1 个 E2E；其中 66 个运行于 Ubuntu、1 个 macOS、1 个 Windows。另有
`test_agent_session_runtime.py` 与 `arch/test_activation.py` 两个混合文件的 32 个
integration node；未登记节点继续留在模块回归。39 个 Coding UI 文件由既有
Harnesstui/Coding UI owner 单独执行，不再重复进入后端模块集合。

策略 v5 的远程全选运行 `38563194640` 提供 8 份 Coding JUnit。模块命令显式包含
333 个 Coding 文件和 `tests/examples/test_coding_examples.py`；报告并集为 3723 个
实例，3703 passed、20 skipped、0 failed，testcase 时间合计 530.29 秒。8 个 job
从开始到完成分别约 1 分 33 秒至 2 分 21 秒，顶层运行从创建到 `quality-gate`
完成约 5 分 27 秒。每个 testcase 只出现于一个分片；当前没有固定分片重复执行。

PR #779 的更新报告并集为 3771 个唯一 testcase，时间合计 640.406 秒。使用生产
SHA-256 node ID 分配算法重算时，4 片为 918–975 项/片，净用例时间为
114.221–198.444 秒；8 片最慢为 100.718 秒。4 片候选保持相同 testcase 并集与
唯一归属，只减少四次 runner 准备、依赖同步、collection 和报告上传，等待远程
墙钟与报告并集验收。

PR #780 同提交的手动 full 运行 `38630526974` 验证四片实际为 918–975 项，净测试
140.647–190.205 秒，job 3 分 06 秒至 4 分 11 秒。与 #779 八份报告逐身份比较，
3771 项并集的 missing、added 和新分片交集均为零。full 运行另由既有 targeted #5
形成尾部：92 passed、1 skipped、835.20 秒，其中
`test_package_worker_candidate_wheel.py` 占 711.327 秒；该 skip 属于暂停的 H6
耐久用例并被 integration 零 skip 校验拒绝。诊断运行在 15 分钟边界取消，不作为
全量绿色证据；分类或失败语义调整继续受审批边界约束。

对 711.327 秒热点文件的下一轮逐断言复核发现，public Coding Session 用例内部用
`print` 和 `text` 参数重复构造 runtime，并执行相同的 Worker selection、真实 Tool
turn、startup composition 和 tool-result 断言。`default_runtime_builder` 对两个值
使用同一实现分支；text adapter 的独有行为由 `test_print_mode.py` 的 mode 合同覆盖。
因此保留 print 集成路径、删除第二套等价 text runtime。本地真实 Worker 单例
1 passed / 437.52 秒；远程加速仍待可合并路径验证。

disable、update、hosted 三个 wrapper 还重复开启 `author_with_public_cli`，但其独有
断言位于候选安装完成后的 Session 生命周期阶段，不检查 author CLI 输出。公共 CLI
构建、产物字段和真实安装由主 public-session 场景及 native CLI/author smoke 测试
覆盖；fixture 与 example 的 C Worker 只有注释差异。三个 wrapper 改用内部 builder，
保留各自 Session fence/update/revoke 行为，公共 author CLI 从四次收敛为一次。
代表性的 disable 场景本地 1 passed / 163.30 秒。

命令参数本身不等于执行证据。21 个显式路径没有产生 testcase：其中包含 Windows
Product Worker base 文件、三类 terminal marker 文件、installed evidence、PR smoke
和 render contract。另有 20 个 skip 分布在 9 个文件，原因为 Darwin/Windows native、
Windows Product root 或 secure staging 条件。这些路径需要先核对现有平台 owner；
让当前未执行场景首次阻断 PR 或 full validation 属于新增失败条件，未经审批不修改。

远程文件级热点为 `test_bootstrap.py` 138.79 秒、`test_cli.py` 50.74 秒、
`test_lmux_command.py` 48.58 秒和 `test_resume_runtime_publication.py` 33.61 秒。
`test_bootstrap.py` 的慢例会建立隔离的 `LOUSHANG_HOME` 并进入当前默认 Product
composition；CLI/lmux 文件含真实本地进程；恢复矩阵按撤销、提交结果、持久状态和
恢复结果隔离。把这些用例批量改走 `legacy_coding_route`、共享可变会话或把多个故障
模式串进一个实例，会减少当前路径或隔离证明，因此本轮不采用。

一次本机全文件测量误把 `TMPDIR` 放在 `/home/dev/lsspace` 下，资源发现合法继承工作区
`AGENTS.md`，使 9 个依赖空祖先的测试改变输入；该运行不作为失败或性能基线。改用
mode `0700`、无仓库资源祖先的 `/var/tmp` 专用根后，三个代表失败全部通过。正式成本
仍采用同提交的远程 JUnit，避免用环境不同的本机墙钟调整分片。

对当前 440 文件再次执行忽略测试名称、保留参数/decorator/函数体的完整 AST 扫描，
没有完全相同函数体。恢复和 publication 参数矩阵虽然共用测试主体，但每个参数验证
不同故障阶段与最终状态，不能按代码相似删除。剩余 333 文件的逐 node 完整角色、
21 个零报告路径和 9 个 skip 文件的目标平台归属记为 AP-06；在逐 node 审批材料完成
并获批前，不修改 catalog、route、平台、触发或失败条件。

## 19. Harness 当前目录增量初审

当前 `tests/harness` 有 474 个 `test_*.py` 文件、4106 个静态测试函数。Harness 尚未
进入 complete module catalog，也没有 whole-file 或 node targeted override；因此统一
`unit_harness` 仍直接执行完整 `tests/harness`，并包含两个 Harness example 文件。
`unit-tests.json` 中历史 13 文件清单只保留配置身份，不会把当前模块执行缩成 13 文件。
旧独立 Harness workflow 保持暂停，不能与统一模块路径混为一项额外执行。

PR #756 的运行 `38577076277` 位于 exec-capture 优化提交 `da76388f`，提供当前有效的
4 份 Harness JUnit：5507 个实例中 5386 passed、121 skipped、0 failed，testcase
时间合计 119.19 秒。4 个分片 job 为约 57、71、62 和 104 秒；该 PR 从创建到
`quality-gate` 完成约 2 分 10 秒。此前运行 `38563194640` 的同一集合为 155.99 秒，
其中 `test_exec_capture.py` 为 42.57 秒；优化后该文件为 14.64 秒。

这项优化保留 14 个 reader failure 的全部 publication point、before/after fault、原始
reader 异常、子进程退出及 stdout/stderr transport 关闭断言，只把测试请求 timeout
从 3 秒收紧为 1 秒。当前树本地聚焦复核 14 passed、47 deselected、14.54 秒，各实例
约 1.02 秒；没有用 timeout 本身代替成功断言。

121 个 skip 分布在 13 个文件：117 个为 Windows Product Worker、materialization、
epoch、lease、rooted handle、data stream 等 Windows 合同，另 4 个要求 native Windows
host。Ubuntu 报告只能证明这些条件被正确跳过，不能证明 Windows 行为通过。把它们
接入新的 Windows owner、恢复暂停 workflow 或首次形成失败条件均须审批。

文件级主要成本为 `test_plc9b_adversarial.py` 52.69 秒，其中
`test_posix_local_wheel_product_composition_uses_live_epoch_and_owners[session-False]`
远程 27.95 秒。该节点构建 checked-in Coding base wheel 并验证真实 Product
composition、epoch 与 owner；当前树在私有 `/var/tmp` 根复核 55.75 秒通过。本机明显
慢于远程，但两边均证明它是真实重型集成，不能用共享可变 Product 状态或删减验证来
伪装成快速单元。

忽略测试名称并保留参数、decorator 与完整函数体的 AST 扫描只发现一组相同函数体：
POSIX 与 Windows epoch cutover 的 concurrent exact request 收敛用例。它们使用不同
平台 owner、布局和安全语义，继续分别保留。4 份 JUnit 的 testcase 身份没有分片重叠。
其余完整单元/合同、本地进程/存储与平台 node 归属记录为 AP-07；未获逐项审批前不
修改 catalog、route、平台、触发或失败条件，现有完整离线 4 分片保持不变。

## 20. HarnessTUI 共享消费者文件的条件去重

`tests/harnesstui` 当前包含 98 个测试文件、625 个静态测试函数；忽略名称后的完整
AST 函数体扫描没有完全重复簇。远程基线 #755 的 HarnessTUI core 为 1020 passed、
零 skip、30.89 testcase 秒，合并 job 墙钟约 60 秒；Coding UI 为独立文件集合。

core 清单还包含 8 个完整 `tests/tui` 文件和 5 个完整 `tests/harness` 文件。它们是
HarnessTUI 的必要消费者合同，因此 HarnessTUI-only 候选继续执行全部 16 个入口。
当已有选择计划同时安排 TUI unit 或 Harness unit owner 时，同一文件原先会在相同
Ubuntu 源码环境执行两次。执行器现按计划分别剔除 8 个或 5 个重复入口；TUI 候选
保留 8 个 core 入口，Harness 候选保留 11 个，独有 HarnessTUI 与 Architecture 合同
均保留。CI 合同覆盖三个计划分支和 workflow 的计划传递。

该改动只缩减现有执行，没有新增门禁、平台、触发、测试 route 或失败条件。其余
逐 node 分类及任何覆盖扩张列为 AP-08，必须经门禁增加审批后才可实施。

双选路径继续去重执行器启动：core 与 Coding UI 的测试文件集合互斥，当前 job 却分别
启动 Ruff、mypy 和 pytest。联合 scope 对两组源码/测试清单稳定去重后各运行一次；
单选路径不变。完整 PR 计划本地得到 1516 passed、64 deselected，与远程顺序执行的
两个报告计数并集完全相同。直接并发两套命令因 mypy cache 竞态和明显 CPU/IO 争用
被否决，没有进入实现。本项只减少同一 job 的重复工具启动和重复依赖分析。PR #779
首轮远程联合 pytest 为 62.64 秒，job 为 1 分 32 秒，原 job 基线为 2 分 24 秒。

## 21. TUI Linux platform 与 unit owner 去重

`tests/tui` 当前有 87 个测试文件、1336 个静态测试函数；忽略测试名称后的完整 AST
函数体扫描没有重复簇。PR #775 中 TUI unit 为 1273 passed、118 deselected、13.83
秒；Ubuntu render 181 项、36.56 秒；Linux native job 墙钟 48 秒。

Linux native job 的 shared/POSIX platform 两段分别为 107 项、6.82 秒和 7 项、0.27
秒。对应 11 个文件没有 `tui_render_contract`、`tui_terminal_backend`、
`tui_terminal_contract` 或 `tui_tmux_integration` marker；现有 `tui_native` 选择又
必然依赖 `tui_unit`，所以它们已在同一 Ubuntu/Python/源码配置的完整 TUI unit 集合
执行。Linux native job 现只保留 12 项真实 PTY/backend/CLI 和 3 项 tmux 合同。

Windows full 仍执行 shared/Windows platform 与 ConPTY，普通 Windows 路径仍执行
原 ConPTY 短冒烟；两平台 render 集合保持。此变更减少 114 个同配置重复实例，没有
新增门禁、测试 route、平台、触发或失败条件。

已登记的 scoped reusable workflow 修改也已有唯一 owner：CI 合同检查选择和 Actions
结构，workflow 自身运行其完整 checks 与平台分支。原先额外启动的 Agent module 与
产品 E2E 不消费该 workflow 的结果，也不验证其独有编排，现已删除。未知 workflow、
共享执行器和其他未分类 gate infrastructure 仍保留原 Agent/E2E 保守回退。

## 22. Dev 完整初审与恢复 seed 候选否决

`tests/dev` 共 45 个测试文件、406 个静态测试函数。完整 AST 扫描在忽略函数名称、
保留参数、decorator 与函数体后没有完全重复簇。使用当前工作树源码和独立私有临时
根执行 `not live and not requires_host_runtime` 集合，1669 项通过、5 项平台条件
跳过，耗时 155.51 秒。最慢项集中在真实恢复 seed、安装证据 selector、Windows
observer 收集和真实子进程监督，和纯单元断言不是同一种执行角色。

现有 12 个恢复故障参数继续复用同路径 seed 快照，保留原 12 个 node 和逐故障隔离。
对其余正向恢复场景进一步合并 seed 的候选在聚焦验证中得到 4 failed、12 passed；
Store head 将 journal 的 device、inode、size、mtime 和 ctime 纳入身份，复制目录后
不能保持该证据。通过测试辅助代码重写 head 会让恢复验证自行制造预期值，因此候选
被撤销，生产代码和测试节点均未改变。

18 个 lmux 文件及 screen-first readiness 文件虽然已经归到既有 AppService 选择
owner，但暂停状态使其当前没有活动直接执行 owner。补齐执行会新增 PR 失败条件，
已列为 AP-10；未经指定审批方批准，不修改 catalog、workflow、平台或失败条件。
本节只记录审计与否决证据。

## 23. Typing 合同与根夹具补充盘点

顶层目录复核发现一个非 pytest 类型合同：`tests/typing/input_intent_contract.py`。
它没有 `test_` 函数，必须由 mypy 显式消费；当前 `typecheck-tui` 只检查生产源码，
所以该文件没有活动执行 owner。补接会新增 PR 失败条件，列为 AP-11，未经指定审批方
批准不修改 Makefile 或 workflow。

根夹具中，`contained_query_worker.c` 的两个消费者都在 Coding package worker 测试，
不存在跨 owner 重复；`resume_overflow_with_thinking.jsonl` 没有当前消费者，也不被
任何门禁读取，因此不会贡献运行时间。本轮不删除测试、夹具或节点，只补齐库存边界。

## 24. Worker candidate 专用场景归属

Worker candidate targeted 路径曾收集 H6 sustained 专用节点，然后因环境变量未开启
产生 guaranteed skip，最终被既有零 skip verifier 拒绝。指定审批方于 2026-10-15
批准将该节点标记为 `live`：普通 `-m not live` 路径在收集阶段排除它，既有
`worker-sustained` 精确节点路径仍执行它。该批准只校正现有归属，不增加测试节点、
工作流、job、平台或矩阵。

## 25. Worker Session 聚焦变体的公共回归去重

函数级采样显示 entry 变体在独有断言前重复执行 deferred host 和 selected ordinary
Worker 场景；两者没有返回值，其成功、拒绝、清理、查询、payload 变化与资源投影
断言已经由同文件 canonical `installed-protocol` 节点覆盖。disable、update、hosted
三个聚焦变体不消费这些场景产生的历史，因此改为在候选安装和授权后直接进入各自
Session 状态转换。disable 本地由原 163.30 秒降至 120.80 秒，update 为 129.22 秒，
hosted 在组合验证中通过。

PR #782 的同 runner JUnit 为 49 tests、零 failure/error/skip、466.865 秒，较 PR #781
基线 574.865 秒减少 108 秒（18.8%）；targeted job 由 9 分 52 秒降到 8 分 05 秒。
四个关键节点分别为完整 public-session 138.516 秒、disable 33.180 秒、update
31.744 秒、hosted 28.686 秒；后三项旧基线为 54.266、53.455、49.726 秒。最终
quality gate 通过，其他模块、E2E、Windows 与专项 workflow 均未被误选。

完整 public-session 的首次候选也跳过公共场景时，后置 GC 检查只得到一条同 receipt
start gate，`len(receipt_gates) > 1` 失败。这证明它实际消费公共场景的历史，不属于
可删除重复；条件已收窄为只优化三个不使用该历史的聚焦变体，完整节点重跑
511.00 秒通过。保留集合仍由 canonical 公共场景、完整 public-session 组合证据和
三个聚焦状态转换构成，没有共享可变 Product/Session，也没有减少测试身份。

## 21. Targeted 批次条件 skip 假红

定时 full validation 38652515258 的两个 targeted integration 批次在 pytest 阶段分别
得到 `92 passed, 1 skipped` 与 `103 passed, 5 skipped`，唯一失败来自报告 verifier
对 integration 类别要求整批零 skip。批次内每个登记文件或 node 已由
`--required-files-json` 要求至少一个对应 case 通过，因此零 skip 规则既不增加 owner
完整性，又会让同文件中的条件不适用节点制造假红。

PR #786 删除 category 专用的双分支和 `allow_skipped` 矩阵字段，统一使用
`--allow-skipped --required-files-json`。零 failure/error、至少一项通过、每个目标至少
一个通过 case 的 fail-closed 语义保持不变。107 项路由与 JUnit verifier 合同通过。
合并后 full validation 38671220972 的 60 个 job 全绿，总墙钟 10 分 31 秒；最长
三个 targeted integration 批次为 9 分 28 秒、8 分 44 秒、8 分 19 秒，满足 15 分钟
完整计划目标。

## 22. Full targeted 重型文件隔离

AP-04 合并前的 full validation 38673724755 因与 PR 全量任务并发排队，总墙钟为
16 分 29 秒。最后完成的 Ubuntu integration 分片 targeted-5 共 92 项、760.73 秒；
其中 `test_package_worker_candidate_wheel.py` 49 项占 630.66 秒，同分片其他测试合计
约 130 秒。另两个批次中，`test_package_external_data_wheel.py` 占 427.51 秒，
`test_package_cutover_cli.py` 占 374.38 秒；原分片总量分别为 649.85 秒和 441.30 秒。

full 计划现把这三个已测量重型文件各自放入原有 8 个 Ubuntu integration 槽位，只有
哈希落入保留槽的普通路径才稳定改派至其余 5 槽。用该次全部 8 份 JUnit 重算后，
重型槽的 testcase 总量分别为 630.66、427.51、374.38 秒，其余槽最高 300.36 秒；
旧关键槽减少 130.07 秒。分片上限、测试并集、PR test-only 路由、平台及失败条件均
未改变。targeted job 名称同时改为 YAML quoted scalar，使 `#<id>` 不再被解析为注释，
便于从 Actions 页面直接定位分片。

PR #789 的首个实现 head full validation 38676143469 在 11 分 21 秒内完成；合入同期
`main` 后，最终 head `c9689156` 的 full validation 38677731417 在 13 分 35 秒内完成。
两次均为 54 success、6 个暂停项按计划 skipped、零失败，且后一次 job 名称已显示精确
分片编号。连同 38671220972 的 10 分 31 秒样本，当前活动 full 计划完成三次 15 分钟内
绿色验收。
