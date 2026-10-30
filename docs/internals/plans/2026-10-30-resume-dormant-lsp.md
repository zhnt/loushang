# 修复按需 LSP 的恢复参与判定

基线：`b1a4d6f84`。用户要求正常的延迟启动不能导致恢复失败，并将规则直接落实到开发代码。本次没有新增配置开关、环境变量或持久协议。

## 问题与修复

原 Hosted / Embedded 恢复计划把 LSP 的 `on_demand` 配置直接当作本次激活必须具备 Plugin effect owners 的依据。bootstrap 则依据原启动记录，让未立即装配 LSP 的会话保持待命。两者对参与范围的定义不同，导致正常恢复被 `resume_plugin_participation_changed` 拒绝。

现在两条恢复入口与 bootstrap 共用 `coding_lsp_should_defer`：

| 场景 | 本次恢复的 LSP 装配 |
| --- | --- |
| on_demand，原启动记录未选择 LSP | 保持待命，不要求立即装配的 Plugin parents；后续使用时走原激活流程 |
| on_demand，原启动记录已选择 LSP | 保持历史 eager 兼容路径 |
| 旧会话无启动记录，包括空会话 | 保持既有 eager 兼容路径；恢复提交 intent 后也使用同一口径 |
| always | 立即装配 |
| disabled / 禁用全部工具 / coding-minimal | 不因 LSP 要求 Plugin owners |

其他能力、Worker 和授权约束仍按原规则处理。该函数只决定初始装配，不承担未完成效果的接管或清算。原 pending activation、来源及权限校验继续生效；不以忽略异常、允许任意 owner 子集或强行启动 LSP 来实现兼容。

## 验证与边界

原先失败的 `test_G17_PRODUCT_stdio_resume_uses_stable_execution_and_commits_once` 已通过：真实离线子进程恢复成功，重复提交返回同一个执行身份，历史中只追加一次输入和回复。连同 Embedded 初始回归及 LSP 实际激活、再次打开、关闭的已有测试，首轮 19 项通过。

Embedded 回归额外覆盖 legacy / dormant / empty 历史，以及 on_demand / always / disabled，并检查禁用工具和 Worker 的参与集合。独占 scratch 重跑的 116 项恢复副作用、首次输入、历史投影及扩展 Embedded 回归全部通过；首轮另外 7 项 bootstrap 回归已通过，未重复执行。四个修改源码文件 mypy（`--follow-imports=silent`）、Ruff 与 diff whitespace 检查通过。

第一次扩展回归的临时根被移除，导致 1 项执行失败和 77 项 fixture 错误（具体为 FileNotFoundError）；改用项目已有 `scripts/dev/run_pytest.py` 独占 scratch 入口重跑受影响项，不修改产品来掩盖临时目录故障。

本次 `check_changed.py --base b1a4d6f84 --plan-only` 被前一引用切片遗漏的测试分类阻断：`tests/harnesswork/integrations/test_transcript.py` 未登记在完整 HarnessWork 清单中。尚未调整分类和 CI 路由，本次不声称全仓门禁通过。之前的终端首次创建及恢复样本检查问题也不因本修复自动关闭。

## 2026-10-30 后续：测试分类遗漏已补齐

用户明确要求完成第 1 项“补齐测试分类遗漏”。已将上述文件登记为 `contract`：使用模拟 Session、模拟 source reader 和内存日志，核验固定交接、来源身份/摘要/期限、追加失败和取消；不访问真实 Transcript store、Product 会话、子进程或在线模型。

登记复用既有 HarnessWork 模块检查及 Ubuntu runner，不新增 workflow、job、平台、触发器或 targeted route。该文件单独变更时，计划只选择既有 HarnessWork 单分片模块检查和文档检查，不触发 E2E；模块命令中该测试只执行一次。它与现有 Session bridge 测试共享装配合同范围，但新增文件已有的断言专门覆盖 Transcript 引用交接，不额外重复安排来源存储或 SDK 场景。

验证：普通及 PR-fast 检查计划均生成成功；既有 CI 回归 144 项及引用合同 19 项共 163 项通过，用时 4.02 秒（本机合计观察，不是 CI 时延保证）。Actions 语法检查（actionlint v1.7.12，使用本地缓存离线构建，参数与现有 CI 一致）、9 项文档不变量及变更文档链接检查通过。完整性校验保持启用，其他未登记文件仍会被拒绝。若撤回该引用测试，应同步撤回对应分类；单独删除分类会恢复本次错误，不应关闭完整性校验来规避。
