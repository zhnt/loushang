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
