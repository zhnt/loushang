# H-COD-KD-003：三视角设计审查与旧行为取证

- Authority: descriptive review evidence。
- Design status: R1 not-ready；[R2](continuity-bytes-import-convergence.md)修订后仍 draft，未接受实施。
- Implementation status: not-started；本轮仅增加旧行为取证，不把测试当新能力。
- Owner: 原 Transcript／Session 与 Coding 集成 owner。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。
- R1 SHA256：`aa2709181761aea3af805989dab401c3cb34eea2b3bad2f08d28dd58631b36d6`，绑定产品树外冻结原稿；当前产品文档已修订为 R2，不能混用指纹。

三位独立 reviewer 只读核查当前源码和 R1，没有互相读取报告、执行 async／测试或修改产品。结论分别为：

| 视角 | 判断 | 需要关闭的事项 |
| --- | --- | --- |
| 职责／复用 | 一份输入贯通原 factory/lifecycle 的方向合理；不应新造六层平行 import API | 原支持构造范围、真实 Blob 来源、成功结果／abort-debt 持有及全部接收成本 |
| 运行／失败 | 保持直接 await 且成功准备后不新增 await，可避免另造交接任务表 | 非 owned／transient 原成功路径、direct bridge 平台门槛；不得假定成功后的 pending owner 仍持有 Prepared |
| 数据／兼容 | codec 与原 BlobStore 可以复用；R1 的源目录语义不足以防选错库 | source.parent=temporary_root 的唯一公式、原 leaf/ancestor 准入、label/fingerprint 组合、JSONL 与 ZIP 的不同接受规则 |

R2 已写明来源字段、direct 门槛、直接 await 的最小路径和 owned-only 假设撤回；完整非 owned 接续及替代成本仍未关闭，不能以“现有 `_import_frozen` 可调用”认定已满足。

实施 owner 在产品代码不变时补充 8 项真实桥接／Transcript 叶子组合（1.89s）。有图 JSONL、初始缺失 source leaf 与无附件 transient JSONL／ZIP 均实际成功，foreign-root 被原 Blob owner 拒绝；owned abort 撤回真实未交付目标与 Blob。另观察到旧 transient source lock 残留，记录原状态而非删断言。薄 runtime 仍不等于 SDK／Agent／lifecycle hooks 全链路。

首版取证为 4 passed／3 failed：两例空 owned Session 惰性未生成 JSONL，以及一例非私有中间目录夹具错误。用原 export codec 提供实际输入并明确私有夹具后为 6 passed／1 failed，余下失败推翻了 transient source 无锁副作用的错误假设。记录原锁残留后 7 项通过，再加初始 missing leaf 合法附件为 8 项通过。相关产品原源始终未改，不归因于新导入实现，也不以此声称修复产品。

本轮不要求用户接受缺口设计，不推动不完整的 owned-only 实现。原 Coding Goal 继续 active，数量收益未记账；本内部评审不替代重要架构工作件的用户评审。


## A60 追加旧路由取证，不构成 R3 设计批准

原三视角关于“完整非owned接续与成本未关闭”的结论继续有效。实施owner补查真实ProductSessionRuntime/Binding/Lifecycle/Transcript链：非owned持久JSONL走目标复制及原rollback；非owned JSONL带图可成功而health missing；有file factory和有效cwd的持久ZIP可成功，但abort保留规范JSONL/Blob；header cwd缺失时fallback重试可因首轮Blob副作用失败。bare factory没有file factory的ZIP绑定失败单列，不冒称Coding配置也不支持ZIP。

取证为三个外置观察函数各1 passed，含13次成功/失败/取消观察，不是13项成功回归；无Agent、完整Coding政策或原生多平台证明，也未实现bytes入口。旧随机输入/路径与进程加载来源尚非完整候选fixture；后续必须按实际范围固定旧预期，不能用新实现生成。没有再开启一轮设计批准或替代用户重要工作件评审；本文档与R2继续draft/not-started。详细Current与后续限制见[专项设计补证](continuity-bytes-import-convergence.md)。
