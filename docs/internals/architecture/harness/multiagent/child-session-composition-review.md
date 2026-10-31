# 子 Session 收敛：独立三视角评审

- Authority: descriptive；Owner：Harness / Coding；日期：2026-10-31。
- 初审固定实现：`8a43354ee01b0d2decbf89146380f62a1096f5e4`；对比基线：`64d035620`。
- 方法：干净本地 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 用户接受“先补独立三视角评审、收尾当前底座，再推进 Goal 专属子 Session”。三个独立 xhigh agent 分别读取源码，不读取其他评审结果，不以实施自查代替证据。
- 对象：[子 Session 创建、驱动与清理设计](child-session-composition.md)及实现。此轮不接受 Goal 子 Work、持久子历史或远程入口设计。

## 视角与初审结果

| Reviewer | 视角 | 独立证据与结论 |
| --- | --- | --- |
| child_session_ownership_review | 职责与复用 | 原 Session、Host、队列、控制树、审批与 lease 复用成立；Coding 保留产品策略。7 项离线聚焦测试通过。发现创建失败说明过时 |
| child_session_runtime_review | 运行与失败 | 9 项既有测试通过，但两个沙箱外 asyncio 反例证明取消等待者可丢失 Session 层移除，阻断合并 |
| child_session_compat_review | 数据与兼容 | 产品配置、历史、首轮 source、普通结果与记录格式未变。26 项离线测试通过；实测创建失败工具信息不足和 Recipe 丢失清理错误 |

## Findings 与处置

| ID | 发现与影响 | 处置 / 关闭条件 |
| --- | --- | --- |
| CS-R1 阻断 | close_agent 等待者取消后，底层 RunHandle 可后台 commit_closed，而 Session 的 pop 未执行；旧 handle 误拦同路径新 incarnation 的后代。首条 deliver 失败后取消创建清理也有同一缺陷 | Session owner 持有树级清理 task，锁、计划、关闭、精确 ref 移除和 drain 一并收敛；创建异常路径的关闭与移除也交给 owner task。三入口回归要求无需再次 close 即可重建同路径、派生后代，最后无旧 handle/input。待 reviewer 固定修订复核 |
| CS-C1 P2 | 创建和清理均失败时保留 cleanup-only 节点，但工具和 Coding 提示声称失败不创建 child，错误结果无节点及失败原因 | 修正说明；沿原 tool_result_details 投影实际 ref、两个错误与关闭指引，保留异常中的原 owner。经实际工具及 Agent 错误结果投影验证原节点可关闭、容量释放。待复核 |
| CS-C2 P2 | Recipe 业务失败时丢掉同时发生的 dispose_errors，隐藏容量仍占用的原因 | 保留原业务异常，同时附原清理错误/ref、notes 及工具详情。回归要求关闭原节点后再次执行成功。待复核 |
| CS-A1 非阻断 | 一个后代清理失败后，关闭计划也停止处理不相关兄弟；保留了安全性但降低尽力清理程度 | 本轮保留既有保守策略。若将来要求关闭独立兄弟继续推进，另行评审依赖次序，不在此次抽取中扩展 |

修正后的定向回归：84 passed，15.93 秒；包含新增的 close_agent、close_owned_children、创建失败清理三条等待者取消反例，以及工具和 Recipe 错误交付。原 79 项回归保留。首次定向运行因提示文案断言失败，恢复原“失败不等待”纪律措辞后通过，未放宽运行语义断言。

## 接受与局限

初审不通过；修正已实现，独立关闭复核待登记，尚不据此合并。原广泛回归及一次 lmux busy 的记录见[交付说明](../../../plans/2026-10-31-child-session-consolidation.md)。后续只补与实际修正相关的验证，不把此前通过记录冒充修订后的全部证据。

测试没有调用在线模型，不证明第二个生产 Product、强断电恢复或全部 Product disposer 内部可重试。既有非 Coding consumer 为测试替身。本记录不替代用户对后续 Goal 系统环境和关键交互工作件的评审。
