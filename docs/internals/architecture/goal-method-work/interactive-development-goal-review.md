# 交互式开发 Goal：实施与三视角代码评审

- Authority: descriptive；Design: R2 已按用户授权范围收敛接受；Implementation: implemented；远程交付由 [PR #853](https://github.com/zhnt/loushang/pull/853) 记录。
- 任务：用户要求“收敛并实施，开发完成后进行三视角评审”。设计、支持范围和命令由[专项 R2](interactive-development-goal.md)唯一维护。
- 基线：`832d7249d089586a0bd01907e1458808bf317461`；分支 `feat/tui-embedded-goal`，长期 tui lane。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 接受责任：本次实施 agent 汇总独立意见、关闭技术阻断并按已有任务授权接受实现；没有制造用户对具体源码的验收结论。

## 已实现的最小交付

参数化 GoalTask/任务策略复用原 BatchPlanningPolicy；Coding 注入任意目标、已选 Method 和有限动作/检查。TUI 创建、运行、单步、状态、暂停、取消、继续、人工批准/反馈、放弃和关闭沿原 Session/Goal/Work 路径。创建不调用模型，run 才执行。控制面板复用原 surface starter，原 TUI 活动 Task 承担长运行。

原 journal、Transcript、Blob、Work、受理/overlay/limiter 与关闭机制继续权威；没有新执行器内核、输入队列、事实账本或全局状态文件。新 profile 不复写旧 fixed policy；原公共 CodingGoal.attach 签名及旧行为保留，通过私有装配参数注入新 profile。

首次本地交付 `cff86ec2c` 的固定对象为 13 份 source/test 文件，manifest SHA256：
`b3b0074d206c77f9a9c5ecfedd5a63358ac8e28ee1636abbdb0f160f982452e3`。
该历史固定源码仍保留；后续远程交付中发生的布局修正见下节，不将旧摘要冒称最终 PR 源码。

## 独立三视角与发现关闭

三名独立 agent 分别阅读固定源码、已有协作者和设计；未读取彼此意见。作者走查不充当独立评审。初评固定 manifest `873092025ea5f2d3938a495540cf690147b89015da389cf1822f8cab307ae54c`，修正与最终增量分别重新冻结、复核。

| 视角 / reviewer | 实质发现 | 修正及最终结论 |
| --- | --- | --- |
| 职责/复用 `/root/tui_goal_ownership` | O-01：多步骤 Method 每步写同名 task_report，违反共享唯一报告合同；O-02：手工 turn 投影丢约束/审计/计划事实；O-03：最终控制改动中 pause 返回未定义变量 | 最终步骤唯一报告，提前失败单份报告后重抛；使用原 prepared-turn projector，保留原 step ID；修正 pause 并加入实际路径断言。三项关闭，无新增职责阻断 |
| 运行/失败 `/root/tui_goal_runtime` | RUNTIME-01：同步 Git/文件取样冻结 UI，无超时；最终增量发现 pause 返回错误，以及只捕获 GoalError 无法覆盖本次控制 append 的 OSError | 复用 settled_io worker，原 scope/reservation/observation 保持跨 await 当前性和原生收敛；禁 fsmonitor、Git 等待 2 秒；修正 pause；记录失败后仍调用原 request_cancel，保留真实状态/失败。全部关闭 |
| 数据/兼容 `/root/tui_goal_data` | D1：多步同名证据歧义；D2：gitlink 内容被固定 missing 隐藏，旧批准可能仍有效；D3：pause 返回错误 | 单最终报告及原 Method 元数据；未支持子模块明确拒绝；pause 关闭。批准/来源/预算未被放宽，无新增阻断 |

最终窄复核覆盖 `accepted-source-review-input` 全部哈希：三位 reviewer 均明确无剩余阻断。共享 Selector、Work、Session 复用方向与真实嵌入式入口可达性成立。额外核查的人工反馈逻辑只允许 reject 不受“必需检查已过”限制，approve 仍须通过；并保证 Goal 控制失败不阻止原 shell abort。

完整原始意见、各轮固定快照、基线对照脚本与结果保存在产品树外 `architecture-analysis/goal-tui-20261103/`。评审属于静态源码核对与局部实验；没有把父 agent 执行的测试冒称各 reviewer 独立运行，也没有宣称真实终端/在线模型已验收。

## 实际验证及局限

以下范围有重叠，数量不能相加计算“总测试数”。所有 pytest 首次即在托管沙箱外执行；未运行 live/付费模型。

| 验证 | 实际结果 |
| --- | --- |
| 原 TUI controller/input/surfaces/mode、当前 Session Goal 与双入口等价 | 156 passed，97.73 秒 |
| 新入口与共享 input/clipboard/surface/completion 组合 | 79 passed，35.51 秒；包括两个不同非 calculator 目标、实际文件工具、两步 Method、检查与用户审阅 |
| 最终控制专项 | 4 passed，19.44 秒：真实阻塞 provider 下正常 pause→cancel、已有 fence、本次 append OSError，以及 Goal 失败仍执行原 shell abort |
| 原 Work / HarnessWork 独立回归 | 241 passed，3.47 秒；临时目录初始化错误未在该独立运行重现 |
| 受影响源码 Ruff / mypy | Ruff 通过；10 份受影响源码 mypy 通过 |
| 文档 | 既有纯文档规范通过；交付前另核本轮相对链接、源依赖生成事实和 diff 空白 |

完整 architecture/Work 共跑得到 866 passed、3 failed、31 setup errors，不标为全绿。31 项是后续 tmp_path 初始化错误；Work/HarnessWork 拆开原套件独立运行 241 项全过，未将未定位的共跑副作用归咎于本次产品改动。

三项架构断言为 hosting optional modules、RCP0 caller inventory、direct AI imports 的精确清单。对未修改 main `832d7249` 导出的源码和同名断言作静态双侧运行，三项均在 main 和当前树失败；对照记录 `architecture-baseline-comparison.json`。没有删断言、放宽验收或增加 CI gate 来取得绿色结果；这三项仍作为主线既有清单问题保留。

本轮未运行整个 check-changed 计划的全平台/全模块检查，未声称远程 CI 已通过。真实 lmux wire、跨进程自动接续、任意扩展/后端配置、子模块取样、完整配置表单与任意命令式实施仍不在完成口径。首版实施工具为当前工作区 read/edit/write；检查走原 Bash 审批。用户人工批准不替代缺失或失败的必需检查。

## 手工使用

从本分支的 Python 安装启动嵌入式入口，在要处理的项目目录运行：

```bash
/home/dev/lsspace/loushang/.worktrees/tui/.venv/bin/loushang --tui
```

进入后先输入 `/goal <目标>`，检查显示的目标/默认预算，再 `/goal run`。需要测试作为硬条件时使用 `/goal new --check '<检查命令>' -- <目标>`。状态用 `/goal status`；人工审阅用 `/goal review`，确认实际文件后按显示的 token 接受，或 reject 并给出具体反馈。原模型/认证/权限照常加载，没有切换全局安装或替用户触发在线试验。

## PR #853 的 UI 预算修正

首次远程 CI 检出本次新增的两项真实架构失败：`coding.ui.goal` 不在原模块清单、UI 总行数 2552 超出原 2200 行预算。没有修改测试清单、预算阈值或 CI gate。将 Goal 交互适配完整字节不变移到已有 `coding.interaction` 层；原 UI 只更换导入。将原纯 Plugin support status 格式化函数体字节不变归回已有 `coding.plugin_management_ui`，UI 保留同名导出及 monkeypatch 接缝。UI 总行数回到 2178，既有 UI 模块集合恢复。

窄修正固定 manifest SHA256 `7990c1c962ef9e68d7fcf8f327f68fe5348b69f24c04433953dcb9303ea00f77`，三位原 reviewer 分别独立复核布局、运行及数据兼容；复核原文保存在产品树外 `architecture-analysis/goal-tui-20261104-delivery/ci-closure/`。实际检查及远程合并结果以 PR 头提交和 checks 为准，不用旧提交的 CI 结果代替新头。

该布局修正的本地检查：原 UI 模块/预算、Plugin support status 及 Goal 入口共 68 passed（180.48 秒）；Ruff 与 3 份受影响源码 mypy 通过，原断言和阈值未改。
