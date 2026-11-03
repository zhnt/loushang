# 既有批次规划策略的职责收敛

- Authority: proposed；Revision: R2；关联重构计划R2的S3。
- 基线：3cffb4199；来源核对的小切片已提炼并通过独立评审，批次策略本节Target尚未实施。
- 沿用本地archmethod master 0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e；本专项只细化已授权的职责迁移，不改变普通Session专项R2或存储合同。

## 问题与边界

当前Coding的BatchPlanningPolicy同时承担两类职责：用Goal/Work事实选择尚未消费的提案、核对来源并限制无效/无进展批次；以及构造Coding提示、文件材料、工具执行与编码动作。它还直接依赖calculator的Blob辅助函数，虽已被repository复用，源码职责仍未收敛。

将前一类原算法移到HarnessWork Goal策略组件，后一类保留为既有profile适配。Harness来源核对只验证Transcript，不处理Goal、提案或验收。继续由原GoalController调用同一个NextWorkPolicy，不增加模型loop、运行driver、状态机、队列、账本或提案存储。

## 子组件与交互

| 单元 | 责任 | 不承担 |
| --- | --- | --- |
| Harness response_proof | 原输入、响应、调用及事件的来源核对 | 提案解析、Goal决策、Work证据编码 |
| HarnessWork BatchPlanningPolicy | 原提案选择、拒绝/无进展限制、一次消费、basis与Work关联、trace、candidate确认 | Session操作、文件/测试解释、具体动作名、模型/工具调用、编码Method |
| Coding兼容策略适配 | 原提示与JSON/profile、原输入上下文、动作绑定、原Work装配、Blob/证据格式与读侧错误转换 | 第二套提案选择或批次推进算法 |
| 原领域策略与method | 仓库事实、动作语义、原Method加载/准备、约束及验收 | 授权扩张、模型自动选择Method的新能力 |

原Controller调用共享策略；共享策略从原Goal/Work事实找到可用提案，经既有profile读取原证据与解析，再向领域适配请求一个WorkCandidate。领域适配仍用原SessionWorkRuntime/SessionTurnExecutor及受理桥接绑定执行。共享策略返回candidate或PolicyStop，不自行执行。后续confirm仍通过原Controller与原领域检查，原intent/accept/association顺序不变。

## 最小接缝

保留现有协作式mixin类型层次，拆出通用方法而非另建运行对象；不引入通用大facade。现有领域的_current_inputs/_implementation继续内部使用，但跨层只传入一个opaque领域上下文，共享层不得解包source/tests/code。

| 接缝组 | 适配提供的内容 | 约束 |
| --- | --- | --- |
| 领域输入与动作 | planning_context返回fingerprint与opaque上下文；bind_planned_action接收其原值；已有_observations与confirm_candidate保留 | 不拷贝领域算法；同一MRO的父确认链必须仍执行 |
| 来源与证据读取 | 当前Session id、是否有普通输入、原证据记录、Blob bytes、原严格JSON解码、原响应proof验证 | 复用现有authority/digest/事件检查；不另建索引或codec，不以Work completed替代proof |
| profile与准备 | limits、rejection_error、原parse_proposal；原_planning构造提示和prepared Work绑定 | 提案解析/具体动作与Method仍注入；原冻结输入模板、异常及预算编码逐字保留 |

共享策略只依赖HarnessWork自己的Goal/Work模型与纯记录工具，不导入Coding、AI、Method或Product DTO。Coding的旧BatchPlanningPolicy符号保留为薄适配基类，其子类和super确认顺序不变；不把整个旧类搬进Harness。保留旧policy id、角色名、prompt builder、report字段、snapshot与operation关联。

这里的fingerprint就是原inventory结构，不另算摘要、不更换source["inventory"]或规划输入中的原字段。它与opaque上下文来自同次原_current_inputs取样；上下文只在本次prepare内同步传递，不持久化、跨批缓存或另建索引。原profile负责其输入取样/冻结，通用层不得重新解释或修改。

prepared仍是原候选绑定槽位：保留prepare入口清理、原resolver注册/消费及CodingGoal.advance未受理绑定清理的归属。confirm仍先调用原父确认链，保留intent前后两次确认和basis+仅自身intent的例外。任何已写intent中的proposal_id都计为已消费，包括not_submitted；不得因未提交而自动恢复该提案资格，原parent_proposal_id筛选规则也不改变。

## 失败、兼容与验证

保持原异常分支：profile的语义拒绝进入下一份原rejections输入；来源/JSON/关联错误按原PolicyStop处理；不扩大重试或预算。现有方法和工具授权只由原适配决定。没有新持久数据，已有提案仍按原operation只消费一次，旧冷读沿原codec与proof重建。

错误按产生位置保留：report.rejection以及_implementation的原ProposalRejected可计invalid；_proposal内对原bytes重parse或proof核对失败仍包原GoalError。prepare将其映射原PolicyStop，trace返回unknown，confirm返回False；不能统一变成可付费重试的语义拒绝。

验证优先用S0固定calculator/repository输入、提案与Work样本；核对原实际提示字节、parser输出及来源proof。运行原候选过期、已消费提案、语义拒绝、无进展、缓存命令与预算用例；核实两种既有profile确实调用同一个共享选择算法。职责/运行/数据三视角先审本接缝，再审固定源码与回归范围。不为搬迁新增付费试验或PR门禁。

实施前从父提交的原算法独立冻结下一candidate、trace及下一份规划输入字节；至少覆盖初次规划、待消费提案、语义拒绝、来源失败、无进展/限额及not_submitted消费规则。Domain取样与外部事实可用确定性替身，原算法本身不可用新实现生成。此差分不代替真实profile/proof与受理/生命周期回归，二者共同作为验收依据。
