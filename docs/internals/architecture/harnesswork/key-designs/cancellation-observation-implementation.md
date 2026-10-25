# HW-KD-001 第一阶段实施记录

- Authority: descriptive — local implementation and verification evidence。
- Design status: not-applicable；Implementation status: complete（观察切片；集成按 PR 记录）。
- Owner：HarnessWork。
- 实施基线：`11b854951125d3437fea9f43f65a9788af620933`。
- 合同：[R4.2 专项设计](cancellation-observation.md)；方法为本地干净 master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

用户在第一阶段开发建议后要求“继续”，本轮据此实施该观察切片。没有将这项授权
扩大为完整 Goal 架构接受、Goal 主体开发或 R3 的控制重构。实施评审时改动留在本地
任务分支；随后用户明确要求 `commit/push/merge/pr/sync local`，本轮据此提交和集成
该观察切片及配套设计材料。合并状态以对应 PR 为准，重要架构工作件仍按用户保留的
评审安排处理；其他 Goal 候选不因文档合入而自动接受。

## 实际交付

沿用原 WorkRuntime，在原终态记录中加入 owner metadata，新增不可变
`WorkCancellationRecord`、`get_cancellation(run_id)` 和只读
`project_work_cancellations(entries)`。旧 `loushang.work` facade 转发同一符号。

领域实际报告与 runtime 的最终归约分别保存。例如，领域超时后在收尾中返回
settled，观察仍是 failed/domain_timeout，同时保留 reported_status=settled。
它不代表外部效果已撤销。自中断保留原 CancelledError，不新增领域取消调用。

终态 append 成功后、listener 通知前提交观察和 terminal flag；listener 可查询同一
记录，不能再追加终态后的事件。所有 append 异常只使新增观察查询报固定的
`WorkCancellationObservationUnavailable`，旧错误继续传播；没有停写隔离、自动重试
或恢复执行的新保证。业务 payload 与 Channel wire 不携 owner metadata。

## 实施中发现的问题与合同协同

| 问题 | 处置 |
| --- | --- |
| operation.kind 与终态事件同名，operation-only 被误判 | projector 同时检查 entry_type；补三种同名操作测试 |
| Cancelling 写后报错，binding 存在但未创建取消 task | 原流程仍可产生 Cancelled；R4.2 增补 unknown/cancellation_not_driven/null，避免误报 no_capability。写前故障导致非法历史时仍由原 replay 拒绝 |
| 来源侧车可能额外保留 outcome/error 引用 | 终态确认后清理；终态后的迟到来源不再加入侧车，不改变旧 waiter 的返回/异常 |
| 原集成测试精确断言 raw operation payload | 两处断言补 owner marker，保留原业务字段；未放宽 WorkEvent/Channel 合同 |

R4.1 固定快照保留；新增 reason 在尚未发布的 v1 首次交付前纳入 R4.2，不声称已经
迁移任何已部署的新格式数据。三视角独立复核及哈希见[评审记录](cancellation-observation-review.md)。

## 已执行验证

所有 pytest 和 asyncio 实验均从首次执行起在沙箱外运行，保留离线选择器；静态检查
在沙箱内完成。显式设置 `PYTHONPATH=src`，避免虚拟环境的旧 editable 安装参与验证。

| 范围 | 结果与实际断言 |
| --- | --- |
| Work / HarnessWork / Method / Session / Channel / 旧 Work shell | 218 项通过；原状态、异常身份、取消调用次数、JSONL 重开、live/历史观察、自中断、领域异常/无效返回、两类超时及三类迟到报告 |
| 版本与失败 | 上述测试包含旧/未来版本、坏 v1、逐 run 截点、terminal listener 重入；15 种 operation/domain/lifecycle append 点分别写前/写后报错，检查原错误身份与新查询不可用 |
| 真正旧 reader/writer | 产品树外加载固定基线 event_log/run_projection/runtime 源码；正常完成、失败、自中断各做新写旧读及旧写新读，6 组通过；旧日志新观察为 unknown |
| 新增及修改源文件静态检查 | Ruff 通过；runtime/types/cancellation_projection 的 mypy 通过 |
| 既有 AI 门禁等价检查 | Ruff、mypy、catalog、imports、覆盖阈值通过；915 项离线测试通过、7 项 deselected，整体覆盖率 90.75%。使用 python -m 绕过旧 console script 的失效解释器路径 |
| 文档与架构 | 既有 9 项文档检查及包依赖图检查通过；链接/围栏另核验 |

检查选择器把未分类的 HarnessWork 路径回退为全仓检查；本轮执行相关模块及被选中
的 AI 检查，没有把全仓 `check-changed` 冒称通过，也没有修改门禁或分类规则。
扩大到整个 HarnessWork/Work 的 mypy 报告 20 项错误，位于未修改的 cli.py 和
integrations/agent_session.py；固定基线复现相同 20 项诊断，仅扫描文件数从 23 变为
25。对照结果另保留，不能用聚焦通过替代全包通过。

验证不覆盖真实磁盘满、断电、fsync 保证、多 writer、全部取消 waiter 的差异 deadline
与中断组合。半行修复/盲重试的历史隔离实验保留为风险证据，不升级为生产恢复合同。
先前 §2 的基线实验与本次实现测试分别登记，不混算为新增功能测试数。

## 交付边界与后续

实现位置是 [runtime](../../../../../src/loushang/harnesswork/runtime.py)、
[record 类型](../../../../../src/loushang/harnesswork/types.py)和
[只读回放](../../../../../src/loushang/harnesswork/cancellation_projection.py)。
原始脚本、结果、独立评审 JSON 和固定快照保存在产品 Git 外的工作区分析目录。

这一阶段提供的是取消观察事实，不是 Goal 完成能力。下一项建议按同样方式单独设计
产物证据交接：复用 Harness Artifact/Blob 及已有领域事实，先明确来源、寿命和
Work 引用合同。Goal 自动推进、计划准入及目标验收仍待整体架构评审，未在本轮实现。
