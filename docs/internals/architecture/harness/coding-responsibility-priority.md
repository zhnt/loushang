# Coding剩余职责实施优先级

2026-11-14，承接A168当前434份Code源码111687行及[逐文件清单](coding-responsibility-inventory.md)。
按用户最新要求，后续以大块完整可迁移职责为主线。以下是设计和实施顺序，不将待查目录
宣称为已可直接迁移，也不把涉及行数当可删除量；已有共享机制不再开发或计益。

| 顺序 | 完整工作件 | 当前涉及范围 | 正确接收者与现状 | 进入实施的条件 |
| --- | --- | --- | --- | --- |
| 1 | Worker Product收据authority：签发、currentness、选定payload/native读取及撤销结清 | receipt族1578、installed族299、policy317，共2194行；属于C07的21132行，含需保留的产品政策/DTO | 原Package Product及Resources native/source custody；原Worker activation继续拥有执行协调。现有candidate验证/receipt witness/kill-switch等共享直接复用，完整Product读取接口仍缺 | 设计整个authority闭包，核准入/IO/寿命的单一owner；Code只留Profile、领域政策、公开DTO和薄适配；不重启A166四方法mixin搬迁 |
| 2 | Legacy已安装状态的inventory/snapshot证据读取与重取一致性 | installation_inventory514、snapshot_member198，共712行；关联C09当前9265行 | 原Plugin Management及Resources epoch/snapshot owner；A168原Source重捕获、A157首次删除重放已完成 | 先区分通用读取/身份/结清与Code存量分类及授权政策；证明原snapshot/epoch与审阅后重验时点；不整搬分类表或删旧支持 |
| 3 | 启动、Product装配、刷新及Resume/close的一条完整交接链 | C01 12774、C15 2042、C17 904，共15720行审计池 | 原Session construction/product composition/registration owner已接管多项主机制；剩余Code领域选择与跨阶段协调需拆清 | 按完整调用链提出原owner最小扩充；先核真实剩余操作体和全部端口成本，不能把bootstrap闭包池改成Context/厚回调。A168三seed泛化+60已拒，不重复尝试同形状 |
| 4 | 托管/CLI跨入口的完整应用控制与生命周期 | C02 8385、C11 9478行为审计池 | 原AppHost/AppService/Host/Session；A156托管控制、A158review fence已共享 | 在前三项后处理剩余通用控制；严格Catalog、确认、CAS及输出合同保留；不为搬迁整lmux引入新框架 |

第一项是下一主工作件。先输出完整设计、真实消费者、旧实现退出表及总成本，再作整条
业务链的替换。至少覆盖两平台原读取差异、Linux payload四次/绑定两次witness、Windows
原backend重验、opt-in读取时点、同GC内构造、撤销CAS/重试以及失败/取消/资源结清。
不得回借Code完整IO程序或厚阶段协调；必要既有窄owner/准入端口及纯政策绑定须计入
全部成本，实际资源寿命由接收owner掌握。三独立视角评审后才能把候选计为已接受；函数/目录搬迁不算退出证明。

第二、三项目前只有可核查的职责边界，尚没有已接受的完整替代API。排序不预支迁移收益，
也不据无drop-in就停止设计。若第一项全成本仍不能形成有效替代，应记录具体拒绝原因并
转下一完整工作件，不能连续用局部十几行去重替代主任务。

C04 Continuity仍保留KD003等明确待确认边界，不因“优先大块”提前采用；其余C05/C06、
C08、C10、C12–C28继续在[剩余责任账](coding-responsibility-remaining-audit.md)中跟踪，
没有从P1–P4范围移除。领域LSP/Arch/任务判据、内容和产品政策不能换目录后从Code归属
扣除。暂未建立≤15K的不可压缩下界，也不把当前领域审计池当最终保留成本。

后续每批同时报告Code、接收组件、兼容适配及系统源码净值；新增测试/探针另列。小修只
用于解除主工作件的真实阻断，不再作为连续主线。完整目标仍是Code领域化及≤15000行，
当前差96687行；本排序不是缩小Goal，也不是已完成迁移的清单。
