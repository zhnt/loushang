# Hosted 恢复检查收尾

基线：`0a938c967`。本轮完成 [Work → Transcript 引用交付](2026-10-29-work-transcript-references.md) 中遗留的终端恢复、首次创建和恢复样本检查；此前的 [LSP 参与判定修复](2026-10-30-resume-dormant-lsp.md) 已合入本地 main。

## 根因与处理

| 遗留场景 | 核实结果与处理 |
| --- | --- |
| 进程退出后恢复历史并继续输入，cwd / user_home | 两个原失败用例均通过；已有 LSP 参与判定修复解决了恢复拒绝，本轮不再修改 Product |
| Hosted 终端首次创建，随后取消恢复并再次启动 | 测试观察器的目录同时是 Session Blob 根。本机 `umask=0002` 下默认 `mkdir()` 创建可被同组用户写入的目录；原写入校验返回 `session_blob_writer:unsafe`，上层转换后终端表现为 `snapshot_required`。仅将测试自建根明确设为 `0700`，保留产品所有权与权限校验 |
| 恢复样本的 startup decision roots | 校验器无条件要求两个能力决策日志，但默认 on-demand LSP 未选中插件时没有启动效果需要记录。改为依据已验证的原 startup receipt 判断：选择能力插件时仍要求原有唯一根和完整两份日志；未选择时要求没有能力决策日志 |

恢复样本的 shape 新增 `capability_decisions`，区分 `eager` / `dormant`，防止性能比较将两种不同工作量混为一谈。原缺日志、额外日志等故障用例使用真实 eager 样本；有效样本同时覆盖两种装配方式及 cwd / user_home。没有改持久格式、恢复准入、Product 配置能力或 CI 路由。

## 验证

- 原进程退出恢复用例：cwd / user_home 共 2 项通过。
- 恢复样本与 shape 相关检查：18 passed、238 deselected，115.94 秒；包括已有故障拒绝检查。
- Hosted 完整新建、取消恢复及再次启动场景：1 passed，65.73 秒。
- 合并去重后的既有 AppHost / AppService 离线路由（100 个既有路径，目录与文件按 pytest 既有收集规则）：2662 passed、16 skipped，1002.58 秒；完整运行结束，零失败。
- 三个变更测试文件 Ruff、9 项文档不变量、三个变更文档的链接以及差异空白检查通过。

测试按项目规则在沙箱外执行，使用既有 `scripts/dev/run_pytest.py` 独占 scratch 入口及私有磁盘 runtime 目录，保留 `not live` / `--skip-host-runtime`。没有访问在线模型，也没有重复验证已通过且不受本轮变更影响的 AI、Agent、完整 Coding 等路由。上述定向结果与广泛路由有重叠，不相加宣称独立测试总数。

遗留项及此前中断的 AppHost / AppService 离线检查至此关闭。本轮验证环境为 Linux；其他平台、host-runtime 与在线模型不在本次验证范围内，不宣称全仓或所有平台检查全绿。变更通过本地提交交付，不包含远程发布。

本机诊断日志位于 `/tmp/hosted-recovery-*.log`；用于定位原始 Blob writer 异常的临时观察器在产品树外，不进入交付。日志是本次复核线索，不是长期可用性承诺。

## 另行记录的 TUI 问题

按用户要求，由独立子 agent 提交 [#828：`/new` 后推理档位由 high 变为 default，需明确继承语义](https://github.com/zhnt/loushang/issues/828)。用户观察中新建会话及聊天成功；本轮没有认定模型实际推理配置已改变，也没有将该问题混同为 Hosted 恢复失败。`cautious` 是权限配置的展示。
