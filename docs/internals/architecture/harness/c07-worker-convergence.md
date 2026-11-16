# C07 Worker 职责收敛与删减

- Authority: descriptive audit / execution evidence
- Design status: partial acceptance — native cleanup and mutation scope accepted by implementation owner; remaining chains under review
- Implementation status: partial; first native/retirement slice locally checked, full C07 not delivered
- Owner: Coding / Harness Worker / Package Product / Hosting
- 执行基线：`cb54b4b6d13e82d7cb9043862ab67c20293e7b9f`；开始时 fetch 后 main 与 lane/harness 相同。
- 方法查阅：本机 archmethod clean `master`，`0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`；不声称与方法上游同步。

## 范围、事实与验收

按 Coding 原职责清单重新定位 112 个 C07 Python 文件，当前为 20,533 个物理行（含空行、注释、docstring）。
已冻结逐文件 SHA、模块说明、声明位置、Harness/Hosting 导入及 src/tests 的静态引用路径，外部记录为本次任务的 `baseline-audit.json`。
引用是模块名静态匹配，不证明动态消费者不存在。函数体精确 AST 匹配未发现长度至少 13 行的完全相同体；这不排除带类型、错误标签、平台或步骤差异的语义重复。

本轮验收范围为全部 C07，不以先完成某一链代替整组完成。先前迁移均是基线；已有 Worker storage/history、Package Product authority 和 Hosting 原生执行不重计收益。
每个文件最终必须给出具体保留或退出理由，以下静态清点尚不是最终语义处置。

| 要求 | 完成证据 | 当前状态 |
| --- | --- | --- |
| 112 文件的调用方、共享实现、支持及存量依赖 | 逐文件静态清点 + 具体源码/测试复核 + 最终处置 | 静态清点完成；语义复核进行中 |
| 完整链路归已有 owner，旧实现退出 | 实际调用路径、替代实现、差分与失败路径验证 | 尚未完成 |
| 先复用、再删除，核实动态与兼容消费者 | 基线对照、公开/名义契约及原测试 | 尚未完成 |
| 无平行框架或大量回调搬运 | 原 owner 接入与新增成本复核 | 候选设计中 |
| 系统成本与纯去重分别报告 | Coding/Harness/Hosting/其他/总量，测试和文档单列 | 生产代码尚未改动 |
| 正常、失败、恢复、退休兼容 | 现有适用本地检查及远端平台实际结果 | 尚未执行本轮回归 |
| PR→lane/harness→main、同步、清理、暂停 | 已合并 PR、提交树、分支和 Goal 返回状态 | 尚未交付 |

## 实施顺序与已有 owner

1. **载荷、待启动身份与请求绑定**：POSIX 的物化/规划/绑定已用 `worker.payload._selected_payload`，存储和债务修复已用 `_storage/_recovery/_repair`。Windows 的原生 stage 创建、检查和物理退休已用 `_windows_stage_io/_windows_stage_retirement`；Coding 的 Windows pending/materialize/bind 仍有较长组合流程。先明确 Product 准入与中性机制的边界，保留持锁下观察顺序及阶段创建失败留下债务的语义。
2. **回执与启动意图**：复用 `package_product._worker_product_authority`、`worker.history._receipt_store/_windows_record_journals` 及原 `WindowsProductWorkerIntentRecords`。核实两平台选定 Session 的关联证明、原生证据与 kill switch；不能重复搭建 receipt owner。
3. **历史关联与恢复**：复用 `_linux_worker_history/_linux_worker_recovery`、`_worker_windows_attempt`、原六流 semantic bases 与既有 Journal。核实 retained attempt、GC、备份、Job absence 与 orphan lease 的关联，明确无法观察不等于不存在。
4. **停止、退休与清理**：保留独立 Supervisor/native/C5/lease/payload 事实；优先合并确实重复的协调。完整、partial、unlaunched、crash 四种 stage 的允许状态不同，不能仅因函数形状相似合并批准政策。

普通 Session 启动、Resume、pending host、provider 和 query 为真实消费者，必须与上述四链一同验收；此前 `_ordinary_prepare`、Session provider、history publication 的共享寿命不重新实现。

## 成本与设计约束

Windows payload 的直接函数搬迁尚未采用：该模块目前 498 行，主要三条流程为 pending 规划、物化和请求绑定。若通过库存、Supervisor、marker、错误及值构造的多组回调照搬，会产生额外接口成本，不能据迁出行数宣称删减。
后续候选须先比较现有 owner 的直接复用、同域去重与迁移方案，再选择最低必要复杂度。未经源码和实际接线验证，不把候选写成已完成。

当前生产变化：Coding −88、Harness +121、Hosting 0、其他 0、系统总量 +33。测试 +2 行，仅将现有故障注入接缝移至真实共享 owner；无新增 case、断言或 PR 门禁。文档净变化在最终交付单列，当前尚在更新。

## 兼容与验证义务

- 公开 API、名义类的模块路径/字段/slots/pickle、历史 wire 与错误身份保持基线；动态探针和故障注入接缝必须核实实际消费者。
- 锁顺序、观察次数/顺序、发布后复核、异常优先级、持有句柄期间的最后复核及失败留下的恢复债务不可随迁移改变。
- Windows pending 要求 exact type，POSIX 某些入口接受 isinstance；不得机械统一。只读 review 不得授予写入、修复或删除权限。
- 本地 pytest 使用管理 wrapper、工作树 PYTHONPATH、non-live/skip-host-runtime，并从第一次就在 sandbox 外执行。用户已明确批准本轮测试临时使用私有磁盘目录 `/home/dev/.cache/loushang-tests-c07`；仅测试环境覆盖，不修改正常 Product/AppHost runtime 或其他 lanes 的规则。
- 使用现有 change-aware 计划决定本地与远端路线，不新增或扩大 PR 门禁。未执行的平台路线单列，既有绿灯不作为本轮变更的替代证据。

## 首批实现与证据

本批设计由 Codex 实现 owner 在 C07 授权范围内接受；仅接受下列边界，不据此关闭整 C07。

- **Windows 崩溃原生清理**：在原 `_worker_windows_attempt` 增加固定清理操作，直接复用原 native profile bridge、Hosting Job 观察和 `WindowsWorkerProvisioningStateJournal`。stage/root 句柄及 pinned Journal 一直保持到最终 authority 复核和原名义结果构造；没有第二份账本、恢复器或物理执行回调。Coding 保留 Package orphan→GC 锁内的批准、跨历史关联和原生后端选择。
- **五条退休/结算的离线写入寿命**：complete、partial、unlaunched、crash stage 及 reserved native settlement 共用同一原 owner 的 Package quiescence→active lease 拒绝→writable GC→authority 复核作用域。五个产品政策体和各自错误类/文本原样保留；不增加退出时复核，不改变 early return 的资源释放。

职责迁移按两组机制统计；纯去重仅可核实为五个相同写入作用域合一、退出四个重复作用域体。原生清理是 owner 归位，不冒称重复删除。两组成本分别为 Coding −78/Harness +102/系统 +24，以及 Coding −10/Harness +19/系统 +9；累计 +33，尚未实现系统净删减。作用域抽取的成本仍需结合后续实际复用复核，不以 Coding 下降作为保留方案的充分理由。

局部验证：

- 现有 native cleanup、stage review 和导入边界组合：169 passed。
- 五条退休/结算及 native cleanup 现有回归：32 passed。
- 7 个变更生产源 mypy（沿用 `--follow-imports=silent`）及 Ruff 通过。
- 112 个模块的公开函数签名、公开类声明与显式 `__all__` AST 保持基线；这不是全部运行时兼容性的证明。
- 仓库外原场景故障差分：34 组观察一致，其中 19 组实际触发故障；五个原作用域对照 70 组一致，覆盖活跃租约、正文返回及锁/正文/退出故障，五个产品政策体 AST 未变。
- 原 native 测试仅调整 mock/故障注入目标，既有断言语义保留；没有将模拟结果当作 Windows 原生执行证据。

全 C07 语义处置、完整相关本地/远端验证与交付均未完成；本地局部通过不能替代整组验收。

## 逐文件初始清点

下表记录基线实物，所属链仅用于复核排序。全部文件已静态清点，具体保留/迁移/删除决定仍需结合方法体、消费者和支持合同复核。

| 文件（相对 Coding） | 基线行 | 源码引用文件 | 测试引用文件 | 复核链 |
| --- | ---: | ---: | ---: | --- |
| `package_product_worker_activation_base_v2.py` | 32 | 3 | 5 | 历史/状态/证据 |
| `package_product_worker_activation_history.py` | 53 | 15 | 10 | 历史/状态/证据 |
| `package_product_worker_activation_state.py` | 113 | 5 | 12 | 历史/状态/证据 |
| `package_product_worker_activation_state_journal.py` | 88 | 3 | 9 | 历史/状态/证据 |
| `package_product_worker_capability.py` | 151 | 4 | 4 | Session/Provider 消费者 |
| `package_product_worker_cleanup_evidence.py` | 113 | 3 | 3 | 恢复/退休/清理 |
| `package_product_worker_crash_c5_settlement.py` | 102 | 3 | 6 | 恢复/退休/清理 |
| `package_product_worker_discovery.py` | 95 | 2 | 3 | Session/Provider 消费者 |
| `package_product_worker_gc_references.py` | 45 | 1 | 2 | 历史/状态/证据 |
| `package_product_worker_history_checkpoint.py` | 288 | 9 | 23 | 历史/状态/证据 |
| `package_product_worker_history_checkpoint_anchor.py` | 66 | 4 | 14 | 历史/状态/证据 |
| `package_product_worker_history_commit_v2.py` | 138 | 0 | 13 | 历史/状态/证据 |
| `package_product_worker_history_cutover_v2.py` | 99 | 2 | 9 | 历史/状态/证据 |
| `package_product_worker_history_deletion_v2.py` | 34 | 1 | 13 | 历史/状态/证据 |
| `package_product_worker_history_preflight_v2.py` | 93 | 2 | 4 | 历史/状态/证据 |
| `package_product_worker_history_prepared_v2.py` | 112 | 5 | 9 | 历史/状态/证据 |
| `package_product_worker_history_read_v2.py` | 98 | 9 | 19 | 历史/状态/证据 |
| `package_product_worker_history_retention.py` | 364 | 8 | 6 | 历史/状态/证据 |
| `package_product_worker_history_retire_v2.py` | 88 | 0 | 6 | 恢复/退休/清理 |
| `package_product_worker_history_retirement_preview.py` | 71 | 2 | 10 | 恢复/退休/清理 |
| `package_product_worker_history_rotate_v2.py` | 75 | 0 | 5 | 历史/状态/证据 |
| `package_product_worker_history_segments.py` | 18 | 7 | 37 | 历史/状态/证据 |
| `package_product_worker_history_stage_v2.py` | 178 | 5 | 23 | 历史/状态/证据 |
| `package_product_worker_history_stream_snapshot.py` | 120 | 5 | 24 | 历史/状态/证据 |
| `package_product_worker_history_v2_names.py` | 4 | 4 | 17 | 历史/状态/证据 |
| `package_product_worker_installed_native.py` | 154 | 7 | 6 | 载荷/原生材料/待启动 |
| `package_product_worker_native_approval.py` | 242 | 8 | 10 | 回执/意图/批准 |
| `package_product_worker_native_install.py` | 74 | 1 | 2 | 历史/状态/证据 |
| `package_product_worker_native_release.py` | 77 | 2 | 9 | 历史/状态/证据 |
| `package_product_worker_no_effect_archive_v2.py` | 74 | 3 | 3 | 历史/状态/证据 |
| `package_product_worker_no_effect_closure.py` | 31 | 0 | 4 | 历史/状态/证据 |
| `package_product_worker_operator_query.py` | 342 | 1 | 6 | Session/Provider 消费者 |
| `package_product_worker_opt_in.py` | 208 | 16 | 18 | 回执/意图/批准 |
| `package_product_worker_opt_in_base_v2.py` | 49 | 3 | 8 | 回执/意图/批准 |
| `package_product_worker_opt_in_owner.py` | 169 | 3 | 2 | 回执/意图/批准 |
| `package_product_worker_ordinary_bootstrap.py` | 288 | 1 | 2 | Session/Provider 消费者 |
| `package_product_worker_ordinary_error.py` | 12 | 2 | 1 | Session/Provider 消费者 |
| `package_product_worker_payload.py` | 789 | 9 | 13 | 载荷/原生材料/待启动 |
| `package_product_worker_pending_host.py` | 207 | 1 | 5 | 载荷/原生材料/待启动 |
| `package_product_worker_policy.py` | 319 | 12 | 13 | 回执/意图/批准 |
| `package_product_worker_posix_gc_history.py` | 60 | 1 | 6 | 历史/状态/证据 |
| `package_product_worker_provider.py` | 288 | 7 | 6 | Session/Provider 消费者 |
| `package_product_worker_provider_host.py` | 237 | 4 | 4 | Session/Provider 消费者 |
| `package_product_worker_query_consumer.py` | 159 | 9 | 5 | Session/Provider 消费者 |
| `package_product_worker_receipt.py` | 602 | 26 | 20 | 回执/意图/批准 |
| `package_product_worker_receipt_base_v2.py` | 44 | 3 | 3 | 回执/意图/批准 |
| `package_product_worker_registered_c5_settlement.py` | 102 | 1 | 3 | 恢复/退休/清理 |
| `package_product_worker_registered_payload_repair.py` | 273 | 2 | 7 | 载荷/原生材料/待启动 |
| `package_product_worker_registered_recovery.py` | 199 | 5 | 6 | 恢复/退休/清理 |
| `package_product_worker_resume.py` | 196 | 5 | 5 | Session/Provider 消费者 |
| `package_product_worker_session_composition.py` | 343 | 5 | 7 | Session/Provider 消费者 |
| `package_product_worker_start_gate.py` | 159 | 14 | 14 | 历史/状态/证据 |
| `package_product_worker_start_gate_base_v2.py` | 53 | 3 | 5 | 历史/状态/证据 |
| `package_product_worker_start_gate_journal.py` | 230 | 9 | 12 | 历史/状态/证据 |
| `package_product_worker_start_gate_recovery.py` | 350 | 2 | 4 | 恢复/退休/清理 |
| `package_product_worker_supervisor_base_v2.py` | 57 | 3 | 5 | 历史/状态/证据 |
| `package_product_worker_supervisor_journal.py` | 42 | 1 | 8 | 历史/状态/证据 |
| `package_product_worker_turn_tool.py` | 73 | 2 | 3 | Session/Provider 消费者 |
| `package_product_worker_windows_activation_state_journal.py` | 59 | 8 | 6 | 历史/状态/证据 |
| `package_product_worker_windows_backend_release.py` | 129 | 3 | 5 | 载荷/原生材料/待启动 |
| `package_product_worker_windows_base_files.py` | 25 | 5 | 0 | 历史/状态/证据 |
| `package_product_worker_windows_c5_base.py` | 91 | 2 | 4 | 历史/状态/证据 |
| `package_product_worker_windows_checkpoint.py` | 466 | 3 | 6 | 历史/状态/证据 |
| `package_product_worker_windows_cleanup_evidence.py` | 387 | 3 | 5 | 恢复/退休/清理 |
| `package_product_worker_windows_crash_c5_settlement.py` | 180 | 1 | 4 | 恢复/退休/清理 |
| `package_product_worker_windows_crash_cleanup_review.py` | 246 | 9 | 7 | 恢复/退休/清理 |
| `package_product_worker_windows_crash_lease_repair.py` | 199 | 1 | 4 | 恢复/退休/清理 |
| `package_product_worker_windows_crash_native_settlement.py` | 203 | 1 | 4 | 恢复/退休/清理 |
| `package_product_worker_windows_crash_recovery.py` | 154 | 1 | 1 | 恢复/退休/清理 |
| `package_product_worker_windows_crash_stage_retirement.py` | 278 | 2 | 6 | 恢复/退休/清理 |
| `package_product_worker_windows_crash_stage_review.py` | 287 | 2 | 5 | 恢复/退休/清理 |
| `package_product_worker_windows_crash_supervisor_settlement.py` | 154 | 1 | 4 | 恢复/退休/清理 |
| `package_product_worker_windows_desired_references.py` | 230 | 1 | 3 | 历史/状态/证据 |
| `package_product_worker_windows_gc_history.py` | 239 | 3 | 6 | 历史/状态/证据 |
| `package_product_worker_windows_history_bases.py` | 184 | 0 | 1 | 历史/状态/证据 |
| `package_product_worker_windows_history_cutover_preflight.py` | 76 | 0 | 1 | 历史/状态/证据 |
| `package_product_worker_windows_history_cutover_record.py` | 148 | 2 | 5 | 历史/状态/证据 |
| `package_product_worker_windows_history_join.py` | 93 | 3 | 6 | 历史/状态/证据 |
| `package_product_worker_windows_history_preparation.py` | 267 | 10 | 17 | 历史/状态/证据 |
| `package_product_worker_windows_history_sources.py` | 498 | 11 | 17 | 历史/状态/证据 |
| `package_product_worker_windows_installed_backend.py` | 148 | 5 | 4 | 载荷/原生材料/待启动 |
| `package_product_worker_windows_launch_intent.py` | 315 | 14 | 15 | 回执/意图/批准 |
| `package_product_worker_windows_launch_intent_base.py` | 113 | 2 | 4 | 回执/意图/批准 |
| `package_product_worker_windows_native_approval_journal.py` | 92 | 2 | 4 | 回执/意图/批准 |
| `package_product_worker_windows_native_approval_owner.py` | 94 | 2 | 3 | 回执/意图/批准 |
| `package_product_worker_windows_opt_in_base.py` | 98 | 2 | 4 | 回执/意图/批准 |
| `package_product_worker_windows_opt_in_journal.py` | 97 | 3 | 3 | 回执/意图/批准 |
| `package_product_worker_windows_opt_in_owner.py` | 126 | 2 | 2 | 回执/意图/批准 |
| `package_product_worker_windows_orphan_review.py` | 191 | 10 | 5 | 恢复/退休/清理 |
| `package_product_worker_windows_package_references.py` | 333 | 2 | 5 | 历史/状态/证据 |
| `package_product_worker_windows_partial_stage_retirement.py` | 255 | 1 | 5 | 恢复/退休/清理 |
| `package_product_worker_windows_partial_stage_review.py` | 257 | 1 | 7 | 历史/状态/证据 |
| `package_product_worker_windows_payload.py` | 498 | 5 | 8 | 载荷/原生材料/待启动 |
| `package_product_worker_windows_payload_inventory.py` | 86 | 2 | 5 | 载荷/原生材料/待启动 |
| `package_product_worker_windows_pending_host.py` | 256 | 1 | 5 | 载荷/原生材料/待启动 |
| `package_product_worker_windows_persisted_bases.py` | 257 | 2 | 4 | 历史/状态/证据 |
| `package_product_worker_windows_provisioning.py` | 318 | 14 | 11 | 历史/状态/证据 |
| `package_product_worker_windows_provisioning_base.py` | 106 | 2 | 4 | 历史/状态/证据 |
| `package_product_worker_windows_provisioning_journal.py` | 37 | 7 | 7 | 历史/状态/证据 |
| `package_product_worker_windows_receipt.py` | 252 | 16 | 10 | 回执/意图/批准 |
| `package_product_worker_windows_receipt_base.py` | 93 | 3 | 5 | 回执/意图/批准 |
| `package_product_worker_windows_receipt_journal.py` | 69 | 4 | 4 | 回执/意图/批准 |
| `package_product_worker_windows_recovery_inventory.py` | 571 | 17 | 23 | 恢复/退休/清理 |
| `package_product_worker_windows_reserved_review.py` | 338 | 2 | 9 | 历史/状态/证据 |
| `package_product_worker_windows_reserved_settlement.py` | 147 | 0 | 2 | 恢复/退休/清理 |
| `package_product_worker_windows_stage_retirement.py` | 446 | 8 | 10 | 恢复/退休/清理 |
| `package_product_worker_windows_stage_review.py` | 345 | 9 | 9 | 历史/状态/证据 |
| `package_product_worker_windows_supervisor_base.py` | 95 | 2 | 4 | 历史/状态/证据 |
| `package_product_worker_windows_supervisor_journal.py` | 50 | 4 | 3 | 历史/状态/证据 |
| `package_product_worker_windows_unlaunched_stage_retirement.py` | 315 | 1 | 5 | 恢复/退休/清理 |
| `_worker_history_access.py` | 54 | 9 | 2 | 历史/状态/证据 |
| `_worker_preparation_inputs.py` | 348 | 3 | 4 | Session/Provider 消费者 |
