# 通用子 Session 收敛交付

- 基线：`64d035620`；实现：`43c39c8b4`。
- 分支：`refactor/harness-child-session`；独立工作树 `.worktrees/child-session`。原 Harness 工作树有未提交设计资料，原 `lane/harness` 还有主线外历史，本次均未修改或混入。
- 授权：用户要求把通用子 Session 创建、驱动、清理收敛到 Harness，复用已有能力。
- 设计与范围：[子 Session 装配与清理](../architecture/harness/multiagent/child-session-composition.md)。不接入 Goal 子 Work，不启用持久子历史，不新增 PR gate。

## 交付内容

`harness.session.subagent.AgentSessionSubagentFactory` 实现原 `SessionSubagentFactory` 合同。Product 注入 runtime builder；Harness 使用原 workspace lease、子 actor 审批、Session 创建、历史安装、输入 facade 与结果投影。完整 Session 继续使用自己的 Host 和队列。

`CodingSubagentFactory` 入口保持兼容，内部只选择角色、工具、模型、沙箱与当前 `persist=False` 策略，委托共享工厂。原 Coding 私有 driver 已移除。另有不依赖 Coding 的测试消费者检验共享接缝，不把测试替身声称为第二个生产 Product。

创建失败或取消时，共享 owner 关闭已取得的资源；清理失败用 `SessionSubagentCreationError` 交付原 owner、原创建错误与清理错误。Session 多 agent runtime 留存该 owner 的 cleanup-only 句柄，根退出仍可重试。直接 factory 消费者也必须保留异常中的 owner，重试 `await owner.dispose()` 并检查 `dispose_error`。

关闭按审批结束 → 子 runtime 关闭 → workspace 释放推进。失败阶段保留原对象，已完成阶段不重复执行；关闭等待方取消不打断 owner 的清理 task。原 RunHandle 在资源清理成功后才 commit_closed，失败不释放路径/名额。原树 owner 封闭待关闭子树的新输入/派生，后代清理失败时保留祖先；根 before_release 报错而不继续释放依赖。

`close_agent` 在失败时补充 cleanup_errors，recipe 识别原结构化关闭错误；不重发模型或工具调用，不建立自动重试循环。旧控制枚举、事件格式、普通成功结果不变。清理失败后容量仍占用是明确的行为修正，必须修复故障并对原对象重试。

## 验证

| 项目 | 结果 |
| --- | --- |
| Coding Multiagent、Harness Session/RunHandle/Recipe/Tools 定向回归 | 79 passed，12.50 秒 |
| 新增通用消费者与生命周期故障场景 | 包含在上述回归；单独运行 6 passed |
| 关闭工具错误展示与原句柄重试 | 单独 1 passed；原成功返回格式保留 |
| Ruff / 五个核心源码 mypy | 通过，mypy 使用 `--follow-imports=silent`；不声称全仓类型检查无错误 |
| 文档 / 架构依赖事实 | 9 项既有不变量、变更文档链接及生成依赖事实检查通过 |
| Coding PR-fast 首段 | 1 failed、1842 passed、13 skipped、64 deselected，936.49 秒；失败为 lmux 第二服务创建时 busy |
| 该 lmux 用例单独复核 | 1 passed，15.09 秒；未修改产品代码或测试 |
| Harness PR-fast | 5954 passed、121 skipped、3 deselected，381.13 秒；36 条既有显式工具选择提醒 |
| Coding PR-fast 剩余段（从 lmux selector 整文件开始） | 2169 passed、7 skipped、19 deselected，931.21 秒 |
| 两项离线冒烟 | 2 passed，11.08 秒；真实 Session 工具/持久化/恢复/关闭，以及终端取消后继续输入 |

所有 pytest 在沙箱外运行，使用现有磁盘 scratch 租约和原 `not live` / `--skip-host-runtime` 选择器。没有调用在线模型；未改 CI 路由、触发器、平台或合并门禁。上述路由有重叠，不累加为独立用例总数。

首段失败是 `test_only_live_mux_among_multiple_services_attaches_without_selector`，
第二次 `lmux new` 返回 `ManagedStorageError: busy`。该存储路径与测试均未由本轮修改，
单独重跑和所在文件的完整上下文复核均通过；根因未完全定位，不能将重跑通过写成首次全绿。
Coding 后续检查从该测试所在文件继续，保留原路由的选择器与 deselection；
首段已完整通过的前置文件不重复运行，不修改 CI 门禁。

本轮评审为实施 agent 按职责/复用、运行/失败、数据/兼容三视角自查，未派遣独立 reviewer，不宣称完成独立三视角评审。共享工厂抽取与关闭失败保留容量的旧取舍已在设计及原边界文档中明确调整。
