# 托管仓库 Goal：R2.1 实施与验证

- Authority: descriptive — implementation evidence；Design status: accepted；Implementation status: implemented — focused offline verified。
- 接受依据：用户2026-11-02“接受R2.1, 开始实现”。设计为 [COD-KD-HG-002](hosted-repository-goal.md)，设计接受原稿摘要及三视角记录见[评审记录](hosted-repository-goal-review.md)。
- 基线：`40c4c2b69cf4c70df1b3d56fb31a8e6a082d42a5`；任务工作树 `hosted-repository-goal-824`。不包含控制工作树中的既有未提交文档。

## 已实现的协作

服务器通过 `loushang.coding.hosted_goal_application` 的 `CodingHostedRepositoryGoalV1` 和 `create_coding_repository_goal_application` 显式选择冻结仓库任务。配置包含 workspace、data_root、manifest、expected_sha256、reviewer_id 和异步 reviewer，以及只能收紧的调用、输出和截止额度。任务必须声明原 closeout 预算；没有把本地缺省20/8变成托管默认值。

SDK仍通过原 `scope.goal_client` 查询 capability、start(submission_id)、wait/query/interrupt/retry_settlement；capability.profile 为 `repository-closeout`。普通提示、steer/follow-up不成为第二条任务驱动路径。

| 实施接缝 | 责任与复用 |
| --- | --- |
| `_hosted_repository_config` | 服务器显式配置，根目录隔离、固定解释器和原Method编译校验；复用原HostedGoalSetup及application factory |
| `adapters._goal_repository_hosted_task` | 原RepositoryTask的hosted私有准入/材料读取：先确认manifest摘要，规范成员及物理归属，冻结初始内容；原本地API保留旧行为 |
| 原 `CodingGoal._initialize_borrowed` | 根据既有profile选用原初始化；借用唯一canonical Session，不创建第二SDK或Session |
| `_hosted_repository_work` | 原GoalInvocation内的固定命令选择；从原batch source/run确认repair后调用verify_current，再交给一次可信reviewer并调用submit_review |
| 原 `CodingHostedGoalSessionV1` | 原guard/registry、查询及清理责任；repository专用出站投影，不向SDK发送任务材料 |

成功路径分别为4个Work（planning、repair、verification、review）和6个Work（planning、inspect、planning、repair、verification、review）。第六个命令之后直接观察原验收，不需要第七次advance。命令调用计数只防循环；任务6/2约束仍来自原Goal metadata/Policy，模型额度仍来自同一个PlanningCallAllowance。

## 评审与内容边界

reviewer只对冻结材料进行有界、合作取消的纯异步判定，不取得文件、网络、模型、子任务、进程或跨调用资源。请求是深不可变的identity、requirements、initial、candidate和原身份绑定的verification结果，整个请求≤4MiB。返回字典含decision、reason、coverage、findings，可带与服务器配置相同的reviewer；身份、命令及评审id由宿主确定。原review_value继续负责完整意见的字段/32KiB校验，原submit_review负责候选匹配、Work交付及事实。

拒绝评审会进入原review Work，随后托管失败并按原条件暂停。异常不伪装成拒绝；reviewer自身TimeoutError归为review_unavailable，只有真正的合作式截止归为goal_deadline_exceeded。取消或截止后的迟到返回不会受理review Work。

Goal DTO保留原operation/run/session身份，method_id/plan_id不交付，step只接受固定白名单。代码评审还核对了继承出口：repository模式的普通Session和execution快照不返回records/draft，标题固定，不转发普通Session内容事件；原guard状态观察保留。canonical Transcript仍保存完整原事实，calculator及普通Session保持原投影。

## 代码三视角复核

三个原独立xhigh评审者分别核查职责/复用、运行/失败、数据/权限/兼容。初审绑定code-r1快照，修订后定向复核code-r2；不把有协调上下文的定向复核称为全新隔离评审。code-r2清单摘要为 `fda1367369304efa3bc85351b7b31283deae5451b5ff59462b8ae7b989d2749e`，完整快照、摘要和各视角报告位于产品树外 `architecture-analysis/hosted-repository-goal-824-20261102/`。

| 发现 | 关闭方式 |
| --- | --- |
| 普通snapshot/content绕过Goal投影暴露源码 | repository facade收窄所有继承内容出口；原Transcript不删改；成功路径覆盖两类订阅及普通/execution快照 |
| 缺少必需inspect/check组直到执行才失败 | 新入口前置检查固定inspect组、完整验证regression组及列表形状；非法包无模型/Work即拒绝 |
| reviewer TimeoutError被误归为全局截止 | callback异常捕获与checkpoint分离；单独回归异常归因 |
| 回调返回Mapping注解与dict受理不一致 | 公开配置注解明确返回dict；仍由原codec冻结/校验 |
| repository特有故障证据不足 | 补录制未知、初始化/收尾债务、review Work中取消、绝对截止、预算、材料边界和跨await撤权测试 |

三视角code-r2静态复核均无剩余阻断；评审者未运行测试，运行结果由主实施记录。清理故障用例直接证明原owner/模型不重启；reviewer已经调用之后再发生清理故障的计数，当前依赖guard只重试settle的既有结构，不宣称新增动态证明。

## 验证记录

所有pytest均在沙箱外通过仓库leased scratch runner执行，保留not live、not requires_host_runtime及skip-host-runtime；无付费/在线模型试验。

| 范围 | 结果 |
| --- | --- |
| `tests/coding/test_hosted_repository_goal.py`最终聚焦 | 35 passed，306.25秒；真实AppHost/Session/工具/Work/verifier配确定性离线provider |
| Ruff（变更源码及新测试） | 通过 |
| 文档9项规则及包依赖事实生成检查 | 通过 |
| 广泛Coding首次尝试 | 18 failed / 396 passed后主动中断；所有失败为共享venv中旧工作树editable身份与当前源码不一致，不修改产品来绕过 |
| 临时安装环境核验 | 单项原失败插件来源测试通过；隔离本任务editable元数据，复用现有依赖，不改共享venv |
| 相关源码类型检查 / 服务侧清单Ruff | 147源码文件通过 / 通过 |
| 隔离环境广泛Coding | 581 passed / 62 deselected后主动中止；后续改为直接相关兼容范围，不宣称全量通过 |
| 隔离环境AppHost/AppService清单去重 | 2633 passed / 11 skipped / 1 failed后中止；失败为基线G16行数上限，详见下文 |
| 直接相关兼容回归 | 126 passed，512.62秒；旧calculator Goal、Method、本地repository（20/8及子Session）、托管执行/权限、G11 |

首次验证的基线遗留：`tests/architecture/test_detachable_local_workspace_g16.py::test_G16_BOUNDARIES_optional_scopes_have_separate_reviewable_budgets` 要求 `appservice/client_scope.py` ≤600行，基线实际637行。当时该源码与测试均逐字匹配 `40c4c2b69`。该失败现已按下述职责复核关闭；此前中止的广泛检查仍是历史部分结果，不追改为全量通过。

未增加门禁。G11精确消费者清单只登记本次已评审的固定repository驱动模块，没有放宽扫描或豁免目录。

## G16后续收尾：保留职责检查，撤除过时文件行数限制

用户在实施完成后要求继续收尾。本次按本地干净archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e` 的change tailoring采用保持合同的内部维护路径；没有改变组件、公有协议、权限或资源owner，无需新增环境图/ARD。

增量溯源：Method接入前 `client_scope.py` 为599行；已交付的 `f784dc81e` 增加24行，形成623行；已交付的 `b3f2989e2` 再增加14行，形成637行。新增内容是原scope上的Method/Goal客户端延迟装配、共用execution客户端借用和旧输入入口限制，执行仍归原registry/guard，方法执行和Goal规划仍在原组件。

责任复核由本次维护者完成，不冒称新一轮独立agent评审：

| 视角 | 核对与结论 |
| --- | --- |
| 职责与复用 | scope仍拥有调用权限、附件/控制者和交付寿命；新增门面借用原execution客户端，不拥有第二执行器或Goal策略。维持模块比另建转发模块更内聚 |
| 运行与失败 | 产品源码不变，断开后的已受理工作、跨await撤权、关闭/重试均沿原路径；原scope行为测试通过 |
| 数据与兼容 | 无存储/DTO/导入边界变化；保留原精确依赖白名单、默认关闭检查及交互模块220行限制 |

取舍：保留现有职责和模块，撤除只针对 `client_scope.py` 的600行机械断言。抬高到637或另一个数字不能说明未来变化是否合理；为了减少37行拆走短转发方法会增加接口与协调而不隔离新的责任。未来若scope引入规划、执行或Product行为，应按职责/依赖及运行合同评审，不能以行数作为已分离职责的证明。

本次为既有门禁范围缩减，未增加或替换任何阻断条件，未改变触发、矩阵、平台或测试路由；原测试node id保留。适用工作区规则允许此类缩减直接推进。回滚仅需恢复原行数断言，无运行时迁移。

验证：沙箱外leased scratch runner执行完整 `tests/architecture/test_detachable_local_workspace_g16.py` 与 `tests/appservice/test_client_scope.py`，保留离线选择器，**35 passed，5.53秒**；Ruff及diff格式检查通过。此前35项新Goal专项和126项直接兼容结果继续有效，产品源码与已评审code-r2无变化。此处只关闭已定位G16失败，不宣称完成此前未跑完的广泛旧安装/终端矩阵。

## 交付边界

本实现是同进程Linux/POSIX托管入口的有限仓库Goal，不承诺任意长任务、远程wire、跨进程恢复、多个Session或有资源的reviewer。原snapshot仍扫描Git清单，4MiB只限制评审材料，不是全仓扫描成本上限；截止是合作式停止，物理收尾可超过业务截止。未来真实Kimi试验需要另外冻结一个小任务、可信评审细则和预算，本轮不启动。
