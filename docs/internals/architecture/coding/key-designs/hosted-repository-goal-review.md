# 托管真实仓库 Goal：三视角评审

- Authority: descriptive — review evidence；Design status: accepted — 用户2026-11-02接受R2.1；Implementation status: implemented — focused offline verified。
- 对象：[COD-KD-HG-002](hosted-repository-goal.md)，#824 后续有界接入专项。
- 源码基线：`40c4c2b69cf4c70df1b3d56fb31a8e6a082d42a5`。
- 方法：干净本地 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- 评审问题：复用现有repository Goal而不复制执行/评审/预算；托管生命周期和可信评审交接是否闭合；任务与证据身份、权限及兼容是否清楚。
- 三个独立视角：职责与复用；运行与失败；数据/权限/兼容。包含同机Linux/POSIX部署约束；排除远程协议、跨进程恢复及多Session。
- 证据范围：设计与静态源码核查，不运行产品测试或付费模型。用户于2026-11-02接受设计并授权实施。

## 固定修订与独立性

R1摘要为 `e029b6190fe85eeb980fcbcc54ed0cf153e5b6c333ff0985778e50a59cdd07af`；三个独立xhigh agent分别读取相同设计和必要源码，不互读报告。主评综合发现形成R2，由原视角定向复核；随后R2.1仅澄清原命令内部受理与协作式截止的边界。关闭复核有协调上下文，不宣称为重新隔离发现。

最终R2.1摘要：`d36185ec154d03f3458ae2c84dfea707086e0930649809cec2160fedcb764ae4`。原稿、修订与各视角完整报告保存在产品树外 `/home/dev/lsspace/architecture-analysis/hosted-repository-goal-824-20261102/`。设计评审时源码保持上述基线，没有产品编码或运行时验证；后续实现证据单独记录。

最终复核者：`/root/repository_goal_ownership`（职责与复用）、`/root/repository_goal_runtime`（运行与失败）、`/root/repository_goal_data`（数据/权限/兼容）。三者均核对上述R2.1摘要并确认本视角无剩余设计阻断；原报告分别为 `review-r2-ownership.md`、`review-r2-runtime.md`、`review-r2-data.md`，文件名保留R2，正文绑定最终R2.1。

## 发现与关闭

| 发现 / 视角 | R1问题 | R2/R2.1处置 |
| --- | --- | --- |
| OWN-01 / 职责与复用；RR-01 / 运行与失败 | 一次异步reviewer回调不能兑现“资源清理失败后只重试收尾”的承诺；原guard没有其资源凭据 | 收窄为只判断冻结材料、无额外执行资源的可信依赖；异常为review_unavailable，不虚构cleanup债务。只join原drive；原Goal/Session资源失败仍由原guard收尾重试。两个原视角关闭设计发现 |
| RR-02 / 运行与失败 | asyncio deadline不能抢占同步Git/全仓库哈希，120秒不能作为硬实时保证 | 明确协作式业务截止及真实任务可行性。R2.1区分外层后续命令与已经进入原命令的内部最多一个Work受理；不引入core定时器，不回滚已产生事实 |
| DP-01 / 数据权限 | 原material/inspect直接读取未由文件工具policy覆盖；只读与祖先symlink、inspect越界、protected缺成员均未封闭 | 在原Task构造前按摘要字节准入；定义read/write/inspect集合、逐成员物理边界、mandatory protected和读取后摘要检查；限定hosted模式，不改变旧本地合同。原视角关闭 |
| DP-02 / 数据权限 | 原Work DTO原样披露task Method ID及派生Plan ID，可能携带路径/内部任务名 | repository投影将method/plan置None，step固定词汇；保留原operation/run且不改Work事实。calculator/Method SDK原投影保持。原视角关闭 |

实现时注意：同一规范文件出现在allowed/read及不同inspect组的正常集合交集合法；拒绝的是不同名称、symlink或硬链接造成的物理别名，不能误拒原allowed⊆read关系。设计评审时，评审材料的深度隔离、任务起点核验与最终DTO检查均为待实施断言；实施证据单独记录。

## 综合结论与剩余验证

复用原事实权威、6/2两条合法路线、可信评审权限和canonical Session责任在静态审查中一致。采用收窄reviewer允许行为关闭生命周期缺口，没有因此新增通用评审管理器、清理端口、队列、账本、schema或权限组件。新的路径准入和披露约束仅作用于hosted repository；原calculator与本地20/8、多Session及重规划能力不变。

上述设计验证是源码核查与场景走查；文档9项规则、变更链接及diff格式检查通过。没有运行产品测试、verifier或模型，不把现有测试资产写成本轮运行证据。实现后仍须按专项HRG-V1–V7完成离线接入验证；具体真实任务、reviewer业务核查及预算可行性另外冻结，不重复既有Kimi动态重规划试验。

用户于2026-11-02明确“接受R2.1, 开始实现”，重要工作件接受已发生。后续代码三视角复核和实际运行结果见[实施与验证记录](hosted-repository-goal-implementation.md)。不得将此接受扩大为远程协议、任意任务上传、硬实时期限或自动批准保证。
