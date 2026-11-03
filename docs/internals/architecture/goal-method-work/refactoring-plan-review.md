# GMW-RF-001 重构计划三视角评审

- Authority: descriptive，独立评审与处置摘要。
- 评审对象：[重构计划](refactoring-plan.md) R1 → R2；源码基线e1601d0593085120078e3bc468c07756cb89fb8b。
- 方法：archmethod master 0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e，干净本地版本。
- R1 SHA256：b85700dd6adef7544ddd21763159e2ef40139a762277c0f5534aa358f5213478。
- R2 SHA256：f1206ea51c851a43acf8adc0b911fe1fbf1d56e03cb5c340c80f97ad771f88dc。
- 三名独立agent以单独任务上下文核查源码，初评不读取其他报告；修订后各自复核同一R2。未执行模型、运行时或产品测试，未修改运行代码。

## 结论

三个视角均确认R2可呈交用户评审，无剩余计划层阻断。这不是完整实施合同接受，不是新方案运行验证，也不代替用户对环境图和重要交互的评审。计划仍为proposed / not-started。

| 视角 / 独立任务 | R1主要发现 | R2处置与复核 |
| --- | --- | --- |
| 职责/复用：goal_refactor_ownership | A-01 Harness对HarnessWork的依赖反转未明确；A-02遗漏已有SessionWorkRuntime/HostPort的共存受理；A-03规划/Transcript/Work证据归属混合 | A-01关闭；A-02/A-03计划缺口关闭，S2/S3保留精确合同前置。复核：可呈交，无呈交阻塞 |
| 运行/失败：goal_refactor_runtime | B-01 application-local AppService不能证明真实lmux Goal可达；B-02撤权与关闭失败、waiter取消的组合清理责任 | B-01以RF-02a/02b和S4a/S4b分开；B-02明确服务端原owner持续持有清理责任。计划层关闭；S2/S4接入仍需专项设计与验证 |
| 数据/兼容：goal_refactor_data | C1中立端口与旧profile解释器归属不清；C2固定迁移前fixture/旧reader双向核查细化；C3物理路径/锁及符号类型身份兼容 | C1计划层关闭；C2/C3纳入S0与相应切片退出条件。复核：可呈交，但验证尚未执行 |

## 综合一致性复核

1. 用户确认的通用协同下沉方向，通过Harness中立执行作用域和反向注入实现；Harness不导入HarnessWork，包括类型标注。Goal-specific候选/状态/证据仍由原策略与集成负责，不出现第二Goal内核。
2. 候选准备/确认、intent、Work accept、association沿原顺序；Session外层受理不冒充Work提前受理。已有SessionWork装配纳入S0/S2，不能以两个runtime各自的active_runs证明互斥。
3. owned与borrowed清理、AppService权限和业务验收是不同合同；撤权后服务端仍须保留清理owner。普通会话retry/compaction/工具策略不得被有限profile静默修改。
4. 保持method独立组件；来源核对、Work evidence和Goal规划策略分层提炼。旧profile prompt/parser/limits/codec和记录路径不随搬包改变。
5. 共同能力重构与真实lmux接通分别计完成；当前原Goal DTO为application-local，不能由离线装配等价测试直接宣布lmux已可用。
6. 计划权重只用于规划，不是完成率。纯重构不重复付费验证；重大行为增量与wire接入须各有合同和接受记录。

## 仍待关闭的阶段义务

- S0：迁移前固定样本、旧reader和API/物理路径/锁/符号身份基线实际建立。
- S1：源码依赖、计数/期限/取消及prepared委托回归。
- S2：中立端口、桥接与owner表、联合受理、既有SessionWork共存、普通Session配置作用域和切换关闭合同，经用户评审后实施。
- S3：历史prompt/proof、双向reader和领域策略注入的实际兼容证明。
- S4a：双装配共同机制等价及各自权限/身份测试；S4b：真实lmux请求/观察/取消/版本/能力协商专项，另估算并评审。

原始独立报告与冻结R1保存于产品树外architecture-analysis/goal-refactor-review-20261103/；本页记录去对话化处置结论，后续仍须保留原报告及修订切点。

## 本轮文档检查

文档规则9项通过；盘点与计划的本地源码/文档链接检查通过，git diff空白检查通过。仅是文档检查，不替代以上阶段的产品验收或独立代码评审。
