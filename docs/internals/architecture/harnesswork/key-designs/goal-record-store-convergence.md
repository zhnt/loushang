# HW-KD-GOAL-STORE-01：可选 Goal 记录后端职责归一

- Authority: accepted focused integration contract；实施owner `/root`在COD-RESP-GOAL-002授权内接受。
- Design status: accepted；三个独立视角无实质阻断，公共支持面澄清已纳入。没有新增环境角色或重要组件关系，不替代用户对其它待审图的接受。
- Implementation status: local integration；实际代码三视角与终态记录见末节，不代表完整Goal或全部场景健康。
- Owner: HarnessWork Records可选集成；Harness Journal拥有原写租约、Rooted IO和JSONL；Product仍选择路径、身份并保留/关闭实际store。
- 方法：本地干净archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`，本轮复核未变；未核上游。
- 来源：[完整重构Goal](../../harness/coding-responsibility-convergence-goal.md)、[F06及G03](../../harness/coding-reconstruction-proposal.md#f06-通用-goal-物理日志适配仍在-coding)、[Goal原组件](../goal/README.md)。

## 1. 已有能力与真实缺口

GoalController已经注入原`GoalRecordStore.load/append`，本轮不开发第二个注入机制。Header/Record codec与replay已归Goal记录组件，JSONL、DirectoryWriterLease及RootedFileIO也已有实现；Coding原138行是唯一物理Goal backend，不存在可直接替换的共享同格式后端。Work event log不是相同格式/锁/寿命，不能强套。

选择将这个单份中性backend放入原HarnessWork可选集成，物理算法仍复用原Journal。不是新日志、store registry、全局服务或Goal状态权威。Product仍持有同一个实例，明确open/close并处理原清理债务；Controller不获得根选择、open或close权。原Goal环境中的Product持有store→Journal关系不变，源码归位不等于增加运行owner。

## 2. 接收、支持面与产品保留项

| 落点 | 唯一职责与复用 |
| --- | --- |
| [Journal owned](../../../../../src/loushang/harness/journal/owned.py) | 按需导出原DirectoryWriterLease、DirectoryWriterError、RootedFileIO同一对象；borrow_root_io只转调用原借用方法，无新状态、FD、锁或IO程序 |
| [可选Goal store](../../../../../src/loushang/harnesswork/integrations/goal_store.py) | 用原Journal、Goal codec和固定Goal writer namespace完成原open/load/append/close，无Harness私有import |
| [Code薄绑定](../../../../../src/loushang/coding/adapters/_goal_store.py) | 保GoalJournal真实类/FQN/显式构造签名、原SHA文件路径和coding-goal标签；六个中性操作体及writer定义退出，不保fallback |

Goal core及两个包根不自动导入该backend；基础Harness不依赖Goal/Work。Product仍可注入其它符合原端口的store，不把JSONL变成唯一必选后端。新接口不包含Coding/Method/AppService类型。

本次Journal接缝支持原lease构造、可信子系统固定的`_lock_directory`/`_hash_domain`子类钩子、acquire/check_binding/close，以及borrow返回IO的bind/cleanup和原JsonlJournal bound_file消费。不是将其它私有claim/字段/反射或任意热替换提升为公共合同；不扩大原Linux/profile范围。根和值来自原可信装配，不按外来记录临时选namespace或授权任意路径。

caller须先保留lease，再acquire、借IO，排空原操作并清理借用IO后关闭lease；失败保同一对象重试。原lease不自动追踪所有borrower，借用函数不新开根、不另签权限。公开借用函数的运行时类型注解可解析；三个导出类型仍是原对象及原异常。

Code继续负责物理路径：SHA256(session_id UTF-8)+`.goal.jsonl`及旁侧Work路径不变。owner_id仅为原借用绑定的配置，不分区物理锁；原锁名仍hash([GOAL_WRITER_HASH_DOMAIN, scope_id])，同根/scope不同标签仍互斥。`.goal-writers`、hash域、权限和常驻lock不变。

同一物理日志须由可信装配固定到同一scope/锁域；不承诺任意path/header/scope组合可安全并发。共享backend没有新增该绑定的校验或修复，更不能据显式path参数绕过原scope合同；Code继续原固定布局。

## 3. 原交互及失败合同

构造无文件IO。readonly或非create先lstat，缺失保持原GoalError；随后acquire原writer→借root IO→bound stat→仅原create资格下rewrite header→load→check header。失败不自动关闭admission，原Product必须保留owner并finally关闭。read_only不造缺失日志或lock，仍持原排他writer，不是在线无锁读取。

load使用原codec与header检查；读模式仅比较scope/Session，写模式比较完整header。append仍按readonly→load→header/expected sequence→record sequence/scope→原append顺序，不新增跨store CAS、重试、修复或回滚。Journal profile保持locking=False/flush=True/fsync=True、header=required、partial_tail=raise；外层原lease提供物理排斥。

close先_io.cleanup，再_lease.close；前者失败不提前放根。未知close或append仍沿原机制处理，不换owner重试未知FD或盲目追加。原GoalWorkSourceCleanupError仍保存真实Code owner和原read_error/cleanup_error，成功/业务失败/取消后的调用方重试资格不变。

原wire、codec/reducer、scope/Session/policy绑定和公开异常类型不变。Code新增基类，因此MRO、操作方法定义位置和私有writer类型改变；不宣称任意私有反射全等。路径计算相对self.header赋值提前，不为effectful Path/Header子类及失败构造私有状态增加合同。Work证据私有codec及领域role继续遵守原HW-KD-002，本片不共享它们或新增验收器。

## 4. 成本、替代与回退

| 全部生产成本 | 原 | 最终 | 变化 |
| --- | ---: | ---: | ---: |
| Code Goal store | 138 | 28 | −110 |
| Journal明确支持接缝 | 0 | 40 | +40 |
| HarnessWork可选backend | 0 | 137 | +137 |
| 全Coding | 123976 | 123866 | **−110** |
| 四生产根 | 638335 | 638402 | **+67** |

候选Code29/Work138/系统+69；最终仅项目Ruff重排同一import集合并去两空行，非import AST与import绑定保持。所有接收/别名/桥/文档字符串成本计入。原来只有一份算法，本片为职责归位，不称去重或系统净减；当前系统仍比634794起点多3608，完整15K/系统净减验收不变。

拒绝直接移动私有import、Harness反向依赖Goal、复制Journal或writer、默认自动加载backend、改物理namespace以及为单backend新增通用store框架/Profile/registry。原owned借用缺公开接点，以同对象导出和单调用桥补齐，不新增机制。回退恢复原Code backend、撤去本可选集成及支持模块；先收敛在途并关闭原owner，持久文件格式不迁移、不清空，不能同时放两条writer。

## 5. 实际验证及边界

原件、三源候选、R1/R1.1支持面澄清、报告、旧JSON及全量1906源指纹保存在产品树外`p4-goal-record-store`。原测试/五个旧fixture均未改，不新增PR gate或平台。

- 38691实际迁前14项全部通过12.79s，涵盖冻结旧records、原路径/锁/只读、坏tail及冷读成功/失败/取消后同owner关闭重试。
- 23943未改原Source时独占捕获7项真实IO观察，全部通过0.50s；实际76680同7项通过，原14项也全部通过。观察包含锁路径、不同owner标签同scope真实排斥、旧/新源码backend双向读写、header policy、readonly、IOcleanup失败保锁后同owner重试，以及完整append后模拟交付丢失时保记录并拒绝错误序号重试。
- 旧reader是冻结原backend源码，依赖当前未修改的Goal codec/Journal，不是独立旧安装环境；交付丢失不是断电或任意原生fsync失败证明。public-api.json没有GoalJournal条目，另作实际类FQN/构造签名及导出类型身份核查，不借旧fixture宣称新MRO已验证。
- 实际批次额外两个Session lifecycle节点在create_session阶段被原Transcript父目录安全检查拒绝：76680为21过/2失败14.68s。40935使用固定原Code后端、同一原managed wrapper和选择器，仍为同两项失败6.20s，status/message相同；加载witness确认两个新模块均未导入。没有到达Goal attach/日志创建，所以不能将这两项记成完整生命周期通过，也没有改权限/祖先/测试/发现语义制造通过。
- 5485候选及37446实际三显式源silent-import mypy、实际Ruff/format通过；是窄域检查，不是全依赖图、native或所有调用者证明。一次静态import核查因遗漏工作树PYTHONPATH误读control lane而ImportError，修正路径后在实际树核原对象/FQN/签名/运行时注解通过，非Product缺陷。

已有14原节点及7观察合计21项通过，彼此不重复叠加；两项已复现原环境/准入失败继续保留。原Catalog的10项失败也不因本片销账。没有付费或在线模型调用、性能指标或新30秒矩阵。

## 6. 评审与接受范围

三位独立设计评审核原组件/注入缺口、公共与私有依赖、生命周期、旧wire/namespace及全成本，无实质阻断；职责视角的支持面精度建议由R1.1和§2明确。三位均确认沿原可选store/Journal关系，无新增用户保留的重要环境图角色，不能据此接受KD008等其它待审方向。

三位实际代码评审分别核对职责与复用、运行与失败、数据与兼容，独立检查最终三源、1906源指纹、旧观察及真实XML，均无本片剩余具体阻断。职责视角确认Product仍持有并关闭原实例，Journal支持面澄清N1已关闭；运行视角确认原锁、追加和同owner清理重试顺序；数据视角确认旧wire/路径及实际Code类与构造合同，明确不承诺新MRO或任意私有反射等价。

实施owner `/root` 据此接受本地三源替换及§5所列有限验证。三报告和接受记录随实物保存在产品树外`p4-goal-record-store`；21过/2失败原样保留，不接受完整P4/Goal、全部生命周期健康或系统净减达标，也不关闭其它Catalog失败和待审环境图。
