# A187 Goal资源寿命归原Session Goal集成

- Authority: COD-RESP-GOAL-002内部有界实施接受；完整Goal仍开放。
- Design status: accepted，限本寿命闭包。
- Implementation status: implemented，限下列实际验证。
- Owner: 既有HarnessWork [Session Goal集成](../../../../../src/loushang/harnesswork/integrations/session_goal.py)，不是新增独立管理器。
- Scope: CodingGoal九个完整生命周期程序及18同实例字段；领域命令/政策不迁。
- Method: clean local archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

A186完整核repository命令门面204行/7方法195行，实际执行/取消/child release已Core，
余体是trusted verification/review、身份/预算和重放政策，不整搬或抽busy helper。
A187是另一个真实闭包：未发布构造失败与attached关闭时的具体Goal资源结清和进度。

原SessionExecutionScope仍拥有attached outer invocation/close Task及阶段，原Controller、
Coordinator、Delegation、TranscriptReader、GoalStore仍是各自机制权威。新固定same-self
base `_SessionGoalLifetime`接原attach/begin/close/fallback/owned-dispose/quiesce/settle/
release/finalize九程序（方法span70）及18个原字段，实际CodingGoal仍同一个对象，
没有sidecar状态、第二Task/phase表或cleanup框架。Code保领域准入/构造catch、SDK
presence与两个原dispose叶绑定及原task名数据；不把整stage作为Code callback借回。

原close先begin再查closed；fallback失败/取消done Task后可同owner重试，caller取消
仅取消shield等待，原清理Task继续保留；attached仍借原scope.close_handle。owned
parent用dispose_bound_session，未发布用dispose_session_runtime，顺序不互换。
observer→controller quiesce、Work settle、coordinator每retry release、delegation→source、
SDK parent、core retire→writer close→prepared clear→closed各成功点flag不前移。
source失败后delegation仍在重试路径，writer失败不重入已retired core，finalize最先
无条件标session_retired。没有为统一CloseGroup改原短路或失败重试。

九个控制body逆展开两SDK叶/task名后AST同，22个其它Code方法及4个原Core定义AST同。
原构造字段集合/初值同，18字段初始化集中至原_session赋值后；私dict插入顺序、
ExecutionObservations分配相对_policy/_work的时点、MRO/方法实现归属及两个SDK额外
协程帧有变化，不假称整个constructor/layout/traceback帧数同。公有CodingGoal名义类、
constructor/close参数与返回签名、原construction catch/GoalConstructionError均保。
公开attach采用1个窄Session结构角色（实际SessionRuntime+attach），不用7泛型擦型；
0新TypeVar。所有接口、tasklabel和两SDK叶成本均计入。

raw Code878→790（−88），HarnessWork Core294→432（+138），系统+50；uniform为
−96/+138/+42，差8为格式，不计额外迁移。旧布局保留，只规范新区域，不冒全文件format绿。
Harness目录364378不变；HarnessWork单列8194→8332，不混入Harness目录计量。

原三个消费者模块旧163过143.97s/7 deselect；装冻结两源后同163过143.17s/7 deselect，
0fail/error/skip：shell151、entry2、frozen compatibility10。旧结果不重复累计，未改
测试/断言/fixture/CI路由，无新probe/oracle。原真实路线含writer-last retry、source关闭
失败、observer错误与outer-finally join、Work/验证取消、owned/borrowed Goal及冻结记录/
公开签名；未逐阶段独立注入所有constructor+cleanup复合错误图，不以163宣称全错窗。

旧/actual独立phase/PID核5模块实际路径/SHA及递归19个code字段，分别101/108声明
callable、163节点/326checks，只证父进程，不替child/wheel/全平台/native或整PR。
实际两源Ruff及项目mypy通过（原untyped-body默认限界仍在）；Root额外严格generic
检查有两Core旧type-arg诊断，旧shadow有相同两项及原Code Task共三项；不称全strict
通过或为本片修无关源码。source/成本/类型范围/两JUnit及三独立设计和实际评审保树外
`coding-convergence-resumed-20261114/a187-goal-lifetime`。

当前2059源659754（排GUI独立测试4524后655230），Code434源110470，Harness364378，
HarnessWork8332，AppHost19717；C12为25源6929，距15K95470。只完成本寿命闭包，
A117既有cold-source IO、原Scope Task/阶段不重计；完整P1–P4、KD003/KD011仍未完成。

## Session Goal 装配与原 Work 后端

以 `38ba5b4e9` 为基线，原 Session Goal 集成接管当前 Session 的装配预约、Work
后端选择、Goal 日志准入及控制器绑定。独立 SDK、当前 Session 和 Hosted Goal
都经过该入口。已绑定后端必须继续满足原 Session、Profile、记录版本、日志路径和取消
合同。当前 Session 的装配在原预约内验证，失败由原作用域结清。Goal 先持有 Writer，
再打开和验证，保留构造失败时关闭同一 Writer 的能力。

Coding 提供日志路径、Work 产品 Profile、业务政策及构造新后端时的原 SDK 工厂。
模型规划直接构造选定的政策，省去随后被覆盖的默认计算器政策。存量记录和公开入口
沿用原格式和签名。

本批生产 Python 为 Coding −32 行、HarnessWork +80 行、系统 +48 行。增长主要
来自共享集成的类型边界及三个入口沿用同一装配步骤的接线。
Linux 上 44 项 Session、SDK、Hosted 和 HarnessWork 回归通过，另外 6 项 Repository、
Interactive 和批次政策回归通过。它们覆盖旧 Work 后端复用、不兼容后端拒绝、
构造失败后的原 Session 归还，以及原日志与命令的重放。
