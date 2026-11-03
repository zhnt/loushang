# Goal重构推进记录

- Authority: descriptive；总Goal：按[重构计划R2](refactoring-plan.md)完成既有职责收敛和双入口共同能力，包含最终交付。
- 源码基线e1601d059；隔离任务分支refactor/goal-shared-session，工作树goal-refactor。原code/harness工作树未提交材料保持原状。
- 用户启动了完整重构Goal。S2普通Session环境、交互、联合受理、配置和资源owner须用户评审后实施；不是本记录可以自行免除的条件。

## 当前状态

| 阶段 | 实际进展 | 尚需完成 |
| --- | --- | --- |
| S0 | 冻结迁移前Goal记录、通用proof、calculator/repository真实规划input/proof/Work及公开符号签名；保存原源码快照，旧reader9例通过 | 随后续受影响切片扩充固定样本和物理并发/回退矩阵，不以当前有限fixture冒称全部历史组合 |
| S1 | 执行控制首切片：Harness新增ModelCallAllowance与ExecutionDeadline；原Coding限额/托管Invocation委托，原异常与结果映射保留；三视角代码评审及修正完成，专项38 passed/315 deselected | 完整Coding检查4165 passed、21 skipped、62 deselected；Harness首轮6038 passed后发现依赖放置错误，修正后6389 passed、121 skipped；取消/收敛的通用资源组合待S2合同落地继续提炼；尚未远程交付 |
| S2 | 用户已接受[协同专项R2](session-goal-coordination.md)；原Goal及已有Session首profile共用原受理、队列、操作配置、资源scope与原Work resolver；查询/取消调用边界已收敛 | 整体故障证据合并、选择检查与最终评审；不能扩大为任意Session/profile均受支持 |
| S3 | 来源核对归Harness，批次选择/消费与PlanningWork交接归HarnessWork，领域/Method内容保留；固定旧proof与12场景差分通过；旧全局配置回退删除 | 原repository/委派/托管整体回归和最终源码评审 |
| S4a | 已验证同profile本地Session绑定与application-local AppService完成/有界暂停的业务等价，三视角无阻断 | 整体检查、权限/故障既有证据合并、最终交付；未激活日常菜单或真实lmux wire |
| S4b | 分离为后续专项 | 真实lmux Goal wire；不能因本地能力通过就宣称可达 |

总体Goal未完成，S2用户评审前置条件已解除；不计算没有完整权重校准的总体完成百分比。下文S0/S1检查记录为历史切点，不代替S2新增代码的验证。

## S0固定兼容基线

固定fixture位于tests/coding/fixtures/goal_refactor_v1，manifest记录e160源码摘要及各文件摘要。生成器只用原版本与确定性离线provider，没有网络调用或私有真实会话。calculator/repository各一次离线规划，非线上成功率实验。原版本source archive与旧reader校验保存在产品树外，不依赖长期工作树保持旧版本。

覆盖：旧日志只读字节不变、journal路径/持久锁常量、原公开符号/签名、真实profile模板逐字节重建、提案解析、input/response/report摘要及Work归属；修改旧prompt仍拒绝。现阶段不证明每种终态、图片/损坏记录组合或后续迁移writer都兼容；这些仍按切片补齐。

## S1实现与独立评审

- 通用限额由参数声明phase及provider策略；Coding继续提供planning/repair限额与原错误类型，最大输出下的retry=1策略仍由Coding配置。原counter在await前增加，失败不返还，原committer/cancellation原对象转交。
- ExecutionDeadline只提炼时钟/checkpoint/阶段转收尾；原GoalInvocation仍拥有任务、一次启动、托管结果及settlement。没有第二执行driver、状态机或记录。
- 三视角发现通用wrapper无条件宣称prepared_request_conformant会升级不可信transport。已修为只传递已有显式声明；Coding旧closure在原可信边界显式声明。新增marked/unmarked测试，原问题复核关闭。
- 三视角均无S1剩余代码阻塞；结论仅覆盖S1。原始独立报告保存于产品树外s1-review-ownership/runtime/data.md。
- 专项最终38 passed、315 deselected（77.09秒）；Ruff通过，共享两文件mypy通过，生成依赖图检查通过。旧reader9例通过。首轮fixture遗漏持久锁与0600权限、首轮committer替身不满足协议，已修测试装配，未为此修改产品存储/权限检查。

## 交付边界

当前保留Goal记录格式、Work引擎和Method包；S2正在修改原Session受理与操作级配置，不启动新的线上试验。用户已接受S2。广泛检查/提交/PR/合并/本地同步的实际结果必须后续登记，不把专项绿灯当整体Goal完成。

## 本轮续跑补充

S1[三视角代码评审摘要](refactoring-s1-review.md)已落盘。广泛检查首次因共享editable环境的来源校验拒绝而停止，已保存失败日志；本工作树独立uv.lock环境建立后，原失败点与关键兼容15项通过，广泛检查使用原选择器重新执行。没有改变产品来源校验或测试门禁。S0提交42096eff5只冻结测试基线，S1运行代码在下述最终检查后本地提交，远程交付仍属于完整Goal的后续义务。S2用户接受仍pending。

## 最终位置修正与检查范围

完整Coding离线检查通过（4165 passed、21 skipped、62 deselected，2707.57秒）。随后Harness在6038 passed、121 skipped后被既有import boundary检查阻断：调用限额器位于runtime却直接依赖AI/Agent。已迁到harness/session/call_allowance.py，仅导入ai.options并继承delegate显式conformance；期限helper留在runtime。三位独立评审均复核最终位置；没有改动allowlist。最终位置精确回归200 passed（290.66秒），包含全部import boundary检查；依赖图检查通过。完整Harness检查通过：6389 passed、121 skipped、36 warnings（1080.19秒），Ruff及780个文件mypy通过。

检查命令静态对照：unit_coding与已通过coding命令仅相差额外排除e2e_smoke，因此不重复相同大套件。unit_harness的485个文件中，check-harness覆盖除两个examples测试文件外的全部路径；这两个文件另行执行，3 passed（3.39秒），保持原离线/host-runtime选择器。该文件级对照只说明范围关系，不预先代替测试结果。

## S1切点与当时的后续前置条件（历史）

S0固定基线已提交；S1限额/期限首切片及配套设计/评审材料本地保存。没有进入S2，未发布远程PR或合并。最终代码由三视角复核，精确回归200项、完整Harness6389项及额外3项通过；Coding4165项通过在最终模块位置修正之前，位置修正后已覆盖原调用限额/预算/旧profile及全部import boundary，未重复45分钟完整Coding套件。

用户要求普通Session环境、组件交互、联合受理、配置作用域与资源所有权先经其评审再实施。专项R2及独立评审已就绪，用户接受尚未收到；自动Goal续跑不等于设计接受。依赖该协同合同的取消/收敛组合、后续规划集成和双入口装配继续等待该评审，不借局部绿灯推进尚未接受的接口。整个Goal尚未达到完成条件。

## S2实施启动

用户已明确接受协同专项R2并要求继续；普通Session专项的用户评审前置条件解除。开始在原Session受理/队列/执行配置与原SessionWorkRuntime resolver中落地，目标范围不变。原R2 SHA固定，接受证据见专项评审记录；S2仍需真实原路径故障验证及代码独立评审。

## S2共享执行中间切片

Harness只拥有Session身份/输入受理、明确任务委托、操作配置和资源作用域；Goal桥接放在HarnessWork integrations中。原GoalController的prepare、confirm、intent、accept顺序保留，Session保留在原resolver同步提交；同Session使用原Work后端，不增加执行队列或第二runtime。

本切片增加了取消后模型输入后台保存的等待：复用原prepare锁，先让原调用方停止，再等已受理保存完成。失败事件仍在原执行身份内处理；无明确身份的任务不能借自动重试进入Goal。配置使用操作级overlay，不恢复旧全局快照。

中间快照三视角分别发现关闭异常永久锁存、旧Goal取消期限从None漂移至30秒、复用后端缺少期限/来源核对、同文本绑定输入误消费尚未投递的普通输入；随后补查并发收敛及命令启动前的取消窗口。已修复并完成独立复核，详见[代码评审汇总](refactoring-s2-code-review.md)。既有架构检查另外发现具体Agent依赖，已改中立只读接口，未改白名单；最终包边界、Session与Agent专项224项通过，文档9项通过。托管组合补查纯同步publisher取消声明，已修复并三视角复核；该失败点之后的25项及冻结收尾预算20项通过。旧reader读取新记录的11个Goal、30个Work、10份规划来源证明通过。整仓check-changed及最终PR检查尚未运行，不能据此声明S2全部验收。

验证执行器现经原Bash完成屏障及已受理delegate退出证明收敛，启动前与执行中取消两场景通过。unsupported及未知追加仍保留未知，不能因Work cancelled而释放依赖。普通Session公开接入、S3规划/方法收敛和S4双入口等价仍未完成；本次切片仅本地保存，尚未发布S2。

## S3来源核对首切片

S2共享执行中间切片本地提交3cffb4199。随后把原单次文本回复的Transcript来源核对提炼到Harness.session.response_proof，Coding保留旧错误、入口及3次attempt读侧上限。[首切片评审](refactoring-s3-response-review.md)三视角无阻断，28项与12项精确检查通过（有重叠），两源Ruff/mypy通过。没有更改writer、提示或Goal/Work算法；没有线上调用。

下一项批次策略提炼先形成专项设计，补明确inventory与opaque上下文配对、旧异常分支、intent消费和原槽位owner，并冻结旧算法的下一candidate/trace/下一输入作差分。尚未实施该策略迁移，原有领域profile仍权威。

## S3批次规划切片

来源核对首切片已提交c93ea90ba。随后按专项R3完成批次策略和PlanningWork交接收敛，原领域工厂和提示不变。[三视角及验证记录](refactoring-s3-policy-review.md)覆盖固定12场景差分、原本地160项、仓库14项和托管3项；这些检查部分重叠，不相加。通用消费者不需要Coding上下文。当前仍无普通Session公开接入与双入口等价的完成结论。

## 操作级边界与查询清理补齐

临时transport必须自行声明来源合同；继续使用原队列，校验前不消费，scope内clear不复活输入。三视角复核和200项Agent/Session/队列检查通过，提交3079d4c98。随后将query调用边界追踪收敛到Harness，关闭只等待查询自身finally，避免与调用方外层close互相等待；原reader cleanup异常保留合同不变。见[查询清理评审](refactoring-observation-review.md)，9项相关回归通过。普通Session公开接入及S4仍待完成。

## 当前Session接入首切片

已增加CodingGoal.attach，借用确切持久Session及历史，沿共同受理/配置/Work桥接运行，不修改原基线。新inspect_session_goal支持实际Session目录冷读；旧公开API保持。三视角关闭transport漂移、标准函数声明与目录冷读问题。7项配置组合、2项真实失败路径、174项原路径回归及175项旧兼容/包边界通过（范围部分重叠），详见[实施评审](current-session-implementation-review.md)。本切片不是所有普通Session组合的支持声明，S4双入口等价尚待完成。

## 删除无消费者的全局配置回退

所有模型Work生产构造均提供原执行绑定，已删除ScopedSessionWork旧global setter/快照恢复分支；缺绑定明确拒绝，旧候选只构造解释器保留。三视角无阻断，16项相关回归通过；见[清理评审](refactoring-configuration-cleanup-review.md)。当前仍在核对两入口相同profile的业务结果，不因共享类名相同就宣称等价验收完成。

## S4a两入口业务等价切片

本地Session attach与application-local AppService现对同一固定calculator profile、匹配模型输出/调用限额做原管线对照。正常完成及无效提案后暂停2项通过32.68秒，三视角无阻断，见[等价评审](dual-entry-equivalence-review.md)。实际日常TUI菜单及真实lmux wire未激活；取消/deadline/权限的其他组合沿原专项与最终回归核查，不因两个样例一致泛称全矩阵等价。

## 取消调用与选择检查收尾

公开取消调用现复用原Harness观察调用边界，关闭不join调用方外层Task，保留原Core/Work取消和错误权威。三视角无阻断，两模式回归通过，见[取消调用评审](refactoring-cancellation-call-review.md)。非Coding selector测试移入既有Work runtime测试路由，选择器已通过，未新增门禁。旧e160 reader读取S4新产物的4个Goal、18个Work、6份真实规划proof通过且日志摘要不变；hosted独立Transcript不在该6份proof范围内，原S2 repository来源双向证据继续保留。整体检查与远程交付仍未完成。

## 最终整体评审与闭合

完整三视角发现应用direct输入遗漏原受理，以及Goal缺撤权/关闭失败/waiter取消组合证据。原direct/trigger已接回同一admission，冲突前拒绝、正常原commit/project持票，未增加队列；真实公共send_message来源隔离与原身份重试通过。托管组合通过，原server重试保留Goal与父Session，不重跑业务；重复prompt模板已薄再导出。三视角关闭，详见[最终评审](refactoring-final-review.md)。已合入最新main（GUI为主、文件零重叠）；整体选择检查正在收尾，尚未远程发布或宣布整个Goal完成。
