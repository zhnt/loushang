# Goal 最小闭环：本地实现与验证

- Authority: descriptive — 实施授权、源码边界、复核及实际验证记录。
- Design status: accepted for reviewed R3.2 local SDK scope；Implementation status: implemented and verified locally for the stated profile；integrated into local main；remote publication pending。
- Owner: HarnessWork 通用 Goal / Coding Product 领域与物理适配。
- 授权：用户明确“请你开始开发”，替代此前暂停；保持 [GM-01…08](../../../plans/2026-10-25-goal-minimum-business-loop.md) 范围。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 分支：`feat/goal-minimum-loop`；固定设计父提交 `102869927ec98794e4b1ad00a147ac15a795cd97`。
- 前置证据切片 `d1f418de53c58040a590683a0c499ff3de50e50d` 与 Goal 已于 2026-10-26 随 `e0031f273` 快进集成本地 main；原集成基线为 `372cde4ad`，尚未发布远程。

## 实现边界

可选 `loushang.harnesswork.goal` 提供 GoalController、三个注入合同与纯记录组件。
记录模型、Reducer、Codec 归同一 `records` 模块，普通 Work/Harness 不依赖 Goal。
Controller 只协调一次显式批次，查询原 operation→run/取消观察，不创建执行引擎。

Coding 的 `adapters/goal.py` 提供专用 SDK owner/受控输入/只读冷重开；私有
`_goal_store` 复用原 retained writer/rooted I/O/Journal，`_goal_calculator` 复用原
Method/SessionTurnExecutor/Blob，`_goal_driver` 承担限定纯函数语法及固定测试执行。
原验证器只最小拆出 executor，standalone wrapper 的原行为保留。

实际原 SDK 非零命令会记录结果并抛带 `tool_result_details` 的 RuntimeError。
私有验证器对带明确执行选项的消费路径捕获最后一份累计 SDK preview，只有原
完整性、非截断、无取消/超时/留存错误及原 stdout/stderr 字节总计完全吻合时，
才用原转换器形成失败报告；不拼累计预览、不解析错误文字、不推测 exit code。
最终 Work 仍失败，原 v1 evidence envelope 不扩字段，不改公共 Work/Session 语义。

## 实现复核发现及处置

固定 r1 的 9 份生产源及三位独立 xhigh agent 报告保存在产品树外：
`/home/dev/lsspace/architecture-analysis/goal-minimum-business-loop-implementation-20261026/`。
原始 `implementation-r1-manifest.json` 和 `r1/` 不覆盖；报告为
`review-implementation-r1-a/b/c.json`。评审为静态核查，不是再次运行产品。

| 发现 | 处置与需要的关闭证据 |
| --- | --- |
| IA-B1 Method metadata 键错误 | 按原 prepared turn 的 planned_constraint/audit_policy 拒绝本 profile 无法执行的非空合同；通过原 Method compiler 的约束/审计反例拒绝修复受理 |
| IA-B2 resume 未核领域与余量 | 在原 NextWorkPolicy 增加同步只读 confirm_resume；共享层先查 Work/余量，Product 查方法/项目/材料，返回后重核 basis；拒绝时不写 active，不准备或执行 Work |
| B-IMP-01 / CI-GC-C2 取消与冷读事实不一致 | 所有原终态均核取消观察；not_requested 普通失败及 settled 与 failed/unsupported/unknown 区分；冷读全量核 Session/run receipt，不因最后验证通过盖过未知；live/cold 共用展示规则 |
| B-IMP-02 清理异常及退休重试 | 检查回调/query gather 的非取消错误并保留原错误/owner；外部 cancel 纳入在途，retire 后不可调用；关闭按已完成阶段只重试剩余步骤，writer-last 失败不重新借用退休 Core |
| CI-GC-C1 验收引用旧 epoch | 共享 Core 和纯记录的完成依赖都匹配当前 Goal/revision/epoch；fresh basis 加旧 operation 仍拒绝 |
| CI-GC-C3 命令效果关系不全 | 精确绑定 create/revise/replace/control 的请求数据及动作，拒绝同命令重复主效果；允许 advance 合法多阶段；同步主效果先用同一 Reducer 预校验再接纳命令 |
| CI-GC-C4 AST 嵌套定义漏拒 | 全树仅准两个顶层固定函数，拒绝不可达的额外定义/default/annotation，不因测试通过放宽语法 |
| CI-GC-CN1 头可选字段往返丢失 | Header 与 Record 都保留非语义扩展，未知必要 feature 仍拒绝；扩展不改变 scope/policy 身份 |

恢复确认是对既有 resume 语义的窄接口补齐，仍为三个合同、两个组件，无第四端口
或共享领域判断。清理回调未正常收束时明确保留 fenced owner/资源；没有强制释放
或有限关闭延迟保证，也没有新增恢复引擎。后续固定修订需实际独立复核关闭。

## 已执行轨迹与验证范围

真实 SDK 场景使用原 23 项测试、两步 Method 与缺陷项目。固定输入按设计记录
保持；只有实际模型通过原文件工具改变 calculator.py。初始失败验证、修复和
再验证形成三批原 Work，最终有完整要求覆盖和绑定输入的证据，结果保存至
专用 `/tmp` 数据目录。最终运行和只读独立进程重开记录在分析目录，精确结果
待全部复核/检查收束后补充，不以“正在运行”或旧版本结果冒充新版本通过。

离线反例并入原 `tests/work/test_runtime.py`、`tests/coding/test_work_shell.py`，
不为 examples runner 增加测试、不新增 test catalog 路由或扩大 PR gate。
既有选择器对新的共享路径采用未分类全检回退，相关范围与实际执行情况分别
记录；不声称未执行的全部 native/平台路由已通过。整个交付仍限 Linux 本地 SDK、
显式 Method 与逐批推进，不提供自动 planner/后台唤醒、多目标并发或远程 Goal API。


## 最终固定复核与实际结果

最终实现修订 r2.1 的 manifest SHA256 为
`11774f30316caf9abce34e225849c11971e207bce5b702d16f9bfd199e00a921`，
固定 9 份生产源与 4 份设计/测试辅助对象。原 r1/r2 报告均保留；r2 运行视角发现
恢复/关闭准入的两处剩余切点后，r2.1 在 cached 回执只读之后、任何 Work/领域
访问之前检查 fence，并由 close 的首个同步入口 begin_close 关闭新外部 cancel
准入，内部 Work 收尾仍可用。对应零调用/拒绝断言及 writer-last 重试已验证。

| 独立 xhigh 复核 | 最终结论 | 报告 SHA256 |
| --- | --- | --- |
| 职责与复用 | 原问题关闭，0 剩余阻断、0 新发现 | `20dd07ea14dc5f9e0913b805aff14f6310b828c46dd0b98afcc2665571f8e039` |
| 运行与失败 | 原问题关闭，0 剩余阻断、0 新发现 | `59278738bc01e83638a737b393ac95469a74b2510fafa8e34a0c4e544ab31fbb` |
| 数据与兼容 | 原问题关闭，0 剩余阻断、0 新发现 | `df845dcd888866ad36c2602d100242bd5c1b574c840330b93b58fc385edb1a45` |

原始报告为分析目录 `review-implementation-r2.1-a/b/c.json`，作者逐份读取关闭
证据并对组合交接作综合核对，不把评审者静态阅读说成其重新执行过测试。
主代理作为已授权任务的实施与架构责任执行者，接受所列首版本地 profile 的
实现；未把接受扩张为全部平台、远程入口或完整未来规划能力。

| 验收 | 实际证据及范围 |
| --- | --- |
| GM-01/03 | 最终 r2.1 真实 Goal `calculator` 经三批 Work：初始验证 failed、两步 Method 修复 completed、独立再验证 completed；身份、版本、批次和原 operation 关联持久保存 |
| GM-02 | 真实原 Method 的 inspect/repair 两步经原 SessionTurnExecutor 执行；原 compiler 的 step_constraints/step_audit 反例在修复受理前拒绝，不以元数据透传充当强制执行 |
| GM-04 | 原固定 23 项测试实际初始 13 failures，最终 0 failures/0 errors/0 skipped；模型只改变 calculator.py，其他项目路径/类型/内容保持；代码/测试/driver/input/result/原 Work 全链关联 |
| GM-05 | 离线合同覆盖准备期间暂停、版本修订/旧 epoch 拒绝、重复命令冲突、恢复前方法/材料/余量核对、输入转发及结束窗口；原 SDK/工具/RPC 兼容合同另外通过 |
| GM-06 | 新 Python 进程 --reopen 返回 completed/current，原 22 个数据文件集合和内容摘要前后一致；没有创建模型 Session 或重执行 Work。追加未知、冷读错 run、取消失败、缺失/损坏证据、query/callback 清理异常和 writer-last 重试均有反例断言 |
| GM-07 | 两个共享组件、原三个协作合同、单个原 WorkRuntime；普通 Work/Harness 根包、原 SDK 队列和原始用量账本不改；源依赖图/导入边界核验通过 |
| GM-08 | Work/Method/Coding Work 组合 277 passed；原 Session/工具/RPC、示例静态与导入边界组合 381 passed；最终受影响 guard 10 passed/74 deselected、Product Goal 11 passed/75 deselected（与前组合重叠，不累加为独立数量） |

最终真实执行使用现有 `kimi-code / kimi-for-coding` 配置，经原 provider、Session
与文件工具完成修复；没有预设补丁或固定模型回复。数据位于
`/tmp/loushang-goal-live-20261026-r21/`，分析目录保留 `real-sdk-r21.log`、
`real-sdk-r21-reopen.log`、`real-sdk-r21-summary.json` 和
`real-sdk-r21-validation-results.json`。临时数据目录的机器清理寿命不作为存储承诺。

R2.1 的 driver 仅有类型标注变化也改变字节 SHA，因此旧运行未冒称新 driver 的
当前证明；最终真实轨迹按 r2.1 固定字节重新执行。独立冷重开核对的全部摘要
保存在 `r21-data-before-reopen.json`，最后再次验证文件集合/内容未变。

最终 9 源 mypy、所有改动 Python 的 Ruff、文档规则/链接及 diff 检查通过。
既有选择器对新增共享路径回退全检并选择 AI，已按原 `make check-ai` 完成
936 passed/7 deselected，覆盖率 90.77%，原覆盖目标通过；没有新增/扩展路由，
也没有宣称整个 `check-changed`、暂停门禁或 Windows/hosted/native 矩阵已执行。
验证使用既有隔离环境避免共享 editable 指向旧工作树，没有放宽来源校验或
改动用户共享环境。上述验证完成时尚未集成 main；后续本地集成见收尾记录，
没有创建远程 PR 或 push。

## 2026-10-26 用户手工验证与交付收尾

用户使用示例 27 和真实 Kimi 模型完成手工验证，结果位于本机临时目录
`/tmp/loushang-goal-manual.4ZhrwD/run`。原始 JSONL 与 Blob 保留实际执行事实；
独立只读复核结果保存于产品树外
`/home/dev/lsspace/architecture-analysis/goal-delivery-closeout-20261026/manual-result.json`。

| 核验项 | 结果 |
| --- | --- |
| 三批原 Work | 初始验证 failed、显式 Method 修复 completed、独立再验证 completed |
| 固定测试 | 初始 23 项、13 failures；最终 23 项、0 failures/0 errors/0 skipped |
| 目标结果 | completed/current，execution_unresolved=false |
| 只读重开 | 用户实际执行 --reopen 后结果保持；独立复核的 22 个数据文件集合和摘要未变 |
| 等待可见性 | 用户真实执行期间每五秒显示原 Work 状态和 inspect/repair 步骤；修复 Work 实际约 47.8 秒，提示间隔不构成超时或进展保证 |

示例补充初始失败的预期说明、advance 开始及等待提示、Ctrl+C 简洁提示；观察任务
在每次 advance 的 finally 中收束，原 Work/Session 的取消和关闭路径不改。
用户早先中断的另一份运行保留 settled 取消观察；源码虽已修改，冷读仍为 active、
not_satisfied，理由为 verification_after_repair_required，没有冒称目标完成。
原 r2.1 固定生产源未改；新示例/文档修改与该固定评审对象分开记录。

收尾提交为 e0031f273，本地 main 已从 372cde4ad 快进集成。文档规则、示例 Ruff
及格式检查通过，原固定 9 份生产源码摘要全部匹配。本轮没有重跑真实模型或把
静态/只读复核冒称完整回归；前述实现测试证据继续适用于未改变的生产源码。
当前处于工作日 18:30 中国标准时间之前的远程推送静默时段，未发布远程。

## 已知基线问题：新 Session 存储准入

手工启动暴露的 transcript_writer:unavailable 在创建 Session 时发生，早于 Goal
构造和执行。问题归原 Transcript 存储准入机制，不是 Goal 独立配置或执行队列。

共享 GoalController 不创建 Session，也不要求每个 Goal 使用独立会话库。首版
CodingGoal.open 在未提供 session_id 时创建专用 Session，提供身份时恢复该 Session；
其数据根由 Product 选择。示例使用新输出目录，因而首次初始化独立会话库。
这个已评审的专用 owner 装配不等于普通 prompt 的当前 Session 已能直接附加 Goal；
后者涉及输入、活动 Work 和关闭所有权，需要单独明确交接，不能仅取消一行创建代码。

admission.json 由底座生成，保存存储根、父目录、锁等物理身份及初始化阶段；共享
存储版本还记录 family/member 关系。它不是用户配置，空文件或通用默认值不能
证明原身份。全新且经检查可初始化的库会自动生成记录；旧登记或初始化残留
不能仅凭缺文件推导成全新空库。

本机全局状态目录存在一个只有锁目录、没有 admission.json 的旧条目。创建新的
独立会话库时，共享 family 的历史检查扫描到该条目，FileNotFoundError 被包装为
unavailable。已登记的默认会话库保有完整 v1 记录，可走原身份校验路径；所以普通
prompt 使用该库时可正常准入，新独立库却失败。同一代码的离线对照结果如下，
不是通过真实 prompt 或模型调用推测：

| 选择的存储 | 结果 |
| --- | --- |
| 已登记默认库，只读 inspect | 原 v1 身份校验成功 |
| 新独立库，复用全局状态 | 失败，底层为缺失 admission.json |
| 新独立库，隔离状态 | 自动初始化并成功准入 |

诊断结果为产品树外同一收尾目录的 admission-probe-result.json；原全局 83 个文件
内容未变，没有清理残留或改写用户会话。该次 Goal 收尾没有修复此存储问题。错误应可定位
具体准入阶段及条目；恢复方案还须区分未完成初始化、登记丢失与原身份替换，
保持既有历史和物理排他保证，不能以跳过检查或默认补身份充当修复。

用户随后授权的[Transcript 准入定点修复](../../harness/key-designs/transcript-admission-publication.md)
补完整登记原子发布、可定位错误和匹配备份恢复；不改 Goal 生产源码。真实机器的
旧残留在该修复交付时无对应身份记录，仍保留未决，不能把预防新残留的修复说成已恢复该旧库。

随后用户授权完成机器残留处置：该单条缺失登记已持锁、备份并移出扫描范围归档；
其余 82 个有效状态文件身份与内容保持不变。本机安装也已离线更新到包含初始化修复
的包。默认全局状态下普通 Session 创建/写入/重开，以及 Goal 新库创建、本地首次检查
和冷读均通过。旧阻塞已解除；原未知库身份并未恢复。详细边界与证据见上述专项的
“后续机器维护”记录，不需要为本次旧残留再增加 Goal 或底座功能。
