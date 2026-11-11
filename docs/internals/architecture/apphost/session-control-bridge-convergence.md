# COD-RESP-A20：托管Session控制桥接职责归一

- Authority: accepted implementation design；完整Goal与既有公开合同继续有效。
- Design status: accepted；2026-11-08三视角核查无实质阻断，实施owner在已有P3职责范围接受本内部接缝。
- Implementation status: implemented（完整托管Session适配接缝）；三视角实码有界接受，不等于完整P3或整个Goal完成。
- Owner: 原Harness Session业务控制、AppHost集成适配与Coding领域投影各原owner。
- 需求：[Coding职责Goal P3](../harness/coding-responsibility-convergence-goal.md)；前置为[A19本地启动阶段复用](local-startup-convergence.md)。
- 方法：本地干净archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

## 1. 场景与已有机制

选中并已准入的真实Coding或历史Session，经原Product resolver成为HostedSessionPort；AppService在自己的作用域授权后查询快照、接收事件、执行prompt/steer/follow-up/interrupt或交互回应、查询/更换模型，最终关闭同一binding。原执行子类还会在监听器之前观察投影。该完整场景是本片边界，不只搬模型列表或几项字段。

当前`coding/appservice_adapter.py`470行，其中CodingHostedSessionV1约270行承担协议转换及订阅/关闭；`coding/hosted_session.py`598行还持相同桥接所用的结构校验。前者已经使用Harness的SessionOperationRuntime和model_selection接口。后者的真实Session构造、历史与Coding恢复输入语义是领域路径，不整体搬迁。

| 责任 | 原权威/已有支撑 | 本片处置 |
| --- | --- | --- |
| prompt、steer、follow-up、abort及原输入队列 | Harness SessionControlPort / SessionOperationRuntime | 直接复用，不造Session/Agent/Goal循环或第二队列 |
| 模型可用项、身份与选择 | 原Harness Session model_selection及AI | 直接复用；不搬provider/auth或重新实现选择策略 |
| 协议DTO、作用域授权、连接和已受理工作 | 原AppServer/AppService端口与执行owner | 直接复用；桥接不签发权限，不控制应用停止/监听器寿命 |
| Coding标题/快照/事件投影、恢复输入与execution claim | 原Code绑定、投影值与execution子类 | 原DTO/校验/观察与方法保留；Core不导入Coding |
| 从上述控制与投影到HostedSessionPort的转换 | 当前仅Code类有完整实现 | 将这一份机制归AppHost integration，Code保原真实类/签名与纯类型/身份绑定 |

已有HarnessAppHostSessionAdapterV1是候选目录/claim/canonical owner适配，仍保持原dark状态；它不是完整交互端口实现，不能冒称直接调用它就能删去当前桥接。原AppHost静态descriptor校验还会拒绝Code当前允许的动态callable端口，不能为复用而收紧原接受集合。

## 2. 现有环境与最小接缝

不新增系统环境角色、进程、事实库或资源权威。共同业务仍归Harness；涉及AppService线协议的转换归既有AppHost integration。变化是原Code适配对象的机制定义位置，实际返回仍为原CodingHostedSessionV1，未再包一个控制器。此处不是将通用业务上移AppHost，也不采用KD-008或P2待审的新生命周期方向。

候选内部文件为`apphost/integrations/session_control.py`，不进入AppHost顶层facade，不在Harness根目录增加模块。内部基类承接原操作、快照/事件转换、模型线格式、订阅与关闭。Code实际类继承它，保持明确原构造面、原lookup_resume_input和_observe_projection；execution子类继续经原Code类覆写。原Code结构校验名保留薄委托，共同校验只实现一份。

仅四项固定类元数据：原product_id、原显示标签、原精确Snapshot/Event类型。它们不是service locator、可执行策略registry或任意阶段callback。三个内部Protocol只描述已用的投影/绑定形状，不新增运行时isinstance准入，也不另造DTO。每个原实例的十一项slot及原锁/Task/订阅仍各只有一份；Code薄类不持第二状态。原公开Code类/构造与方法签名、DTO/导出保持，继承的定义位置、MRO、slot声明位置和私有模块hotpatch位置改变，不承诺完整反射/pickle兼容。

## 3. 交互、失败与关闭合同

| 路径 | 必须保持 |
| --- | --- |
| 构造 | 原结构校验→execution_submission精确bool→读取并精确检查identity/product→原SessionOperationRuntime→原字段初始化→订阅；原control=None历史绑定合法，不增加写能力 |
| snapshot | 原开放状态检查、精确Product投影类型与原异常翻译；不推断历史可恢复或目标验收完成 |
| prompt与控制 | 原SessionPromptRequest(source=appservice)、原SessionOperationRuntime方法；不增加排队、并发或重放政策 |
| interaction/models | 原批准字符串映射、取消重抛/其余异常翻译、当前模型过滤、streaming拒绝更换与实际原选择调用保持 |
| events | 原投影失败降级、精确类型检查、cursor递增→原_observe_projection→监听器；监听器的取消传播与其它Exception忽略边界保持 |
| close | 同一原锁下先unsubscribe一次/清listeners，再创建或join原binding.close任务；caller取消不取消owned task。仅非CancelledError的原BaseException分支按task identity重置，owned task自身取消仍保留原cancelled task，不能宣称所有失败都可重建；成功才settled |

原_observe_projection必须保留Code声明与self虚调用，已有execution与边界trace覆写继续命中。lookup_resume_input仍是Code到原Coding恢复观察的薄转接，AppService保读取授权；本片不变更原查询、来源摘要或model outcome合同。原字段、状态时点、错误文本/code/cause和属性读取次序按原源码核对；不顺带“修正”旧取消或投影异常策略。

## 4. 完整成本、替代与收尾

| 完整生产源码 | 原实际A19 | 树外候选 | 变化 |
| --- | ---: | ---: | ---: |
| Code appservice_adapter | 470 | 223 | −247 |
| Code hosted_session | 598 | 579 | −19 |
| AppHost integration接收体（含类型/导入） | 0 | 377 | +377 |
| 合计 | 1,068 | 1,179 | **+111** |

这是有明确owner缺口的职责迁移，主要算法原先只有一份，**不是净删收益**；只称Code候选−266、系统候选+111。不能将接收体藏在树外计收益，整个Code≤15K和系统低于634794要求不变。相较A18完整Canary的13项配置，本候选只有四项纯元数据，不复制既有核心引擎；是否值得这个成本由职责/兼容评审判断，不能因成本为正直接省掉原类型和合同。

不选把线协议放进Harness，否则倒置Harness到AppService依赖；不选据调用者只有Code而保留全部通用机制在产品；不选直接调用dark目录适配器或严格descriptor校验，它们合同不同。原嵌入式与托管业务仍共用Harness控制接口，Code不另持一套业务控制。

既有架构检查的源文件清单需登记本内部路径；AppServer消费者例外仅跟随原Code桥接迁移到这一确切AppHost路径，原dark目录适配器与facade约束保持。仅维护原断言的实际owner位置，不新增/扩大required check、工作流/路径触发、平台、矩阵、路由或断言覆盖；不能用全目录豁免替代一个具体路径。实际实施前须独立核查这些修改是否确属原覆盖维护。

基线52835为原四文件48 passed/1 skipped/36.58s；树外三模块覆盖5908在同四文件及三项来源/公开面/拒绝Coding冷导入检查取得51 passed/1 skipped/37.86s，两个JUnit property警告不改配置消除。原型三源mypy7397通过（silent依赖；其后仅Core排版与docstring改变，不是全图）。这些证明有限可行性，不是实际工作树/架构门禁或新Product完整验收；基线skip、native与跨进程局限保持，不因此重开矩阵。

实施前保存两原源、完整候选/元数据与原测试实物及切点；三视角接受后再按整套三源替换、同步原owner清单，复用原Hosted/执行消费者测试并作实际代码评审。原算法在Code退出，不保留fallback或双份实现；按整套三源及相应清单回退，无持久数据迁移。重要新架构方向若被评审认定超出当前组件职责，保留候选提交用户，不能把技术原型或Goal自动续跑视为用户接受。

## 5. 三视角接受与实际交付

原设计冻结SHA256 `2b02f08809948e6182fbe9299b97696cc96357776efb2ed98c045d3a5009cfe2`、candidate frame及三份独立设计报告保存树外。职责视角确认这是原对象内的集成机制归位，未新增系统环境角色/资源权威；运行视角明确owned close task自身取消仍保留任务；数据视角确认原DTO/协议/签名及Generic静态类型接缝，清单维护不增加断言覆盖。实施owner `/root`在原Goal/P3授权内接受此内部设计，不归给用户，不批准KD-008/P2新方向。

实际三源接通：Code adapter经Product路径Ruff重排同一组import，非import整模块AST仍与候选相等，物理行223→222；另两源逐字等候选。故实际Code−267/AppHost+377/系统+110（1,068→1,178），区别于历史候选+111；这一行是导入排版差额，不记算法收益。与A19的1882项全量pre-image比较，仅两旧Code源改变、新增本Core文件，其余1880生产源保持原字节；实际为Code127759/系统636962/1883文件。

两处架构测试只各增加一个确切`integrations/session_control.py`路径：一处原AppHost.rglob闭集，一处原AppServer消费者allowlist。删去新Set元素或新BoolOp比较后，整文件AST恢复before；没有新函数、断言、扫描范围、workflow/route/platform/trigger或目录豁免。原Code仍持DTO等协议消费，保留其原登记；原dark目录适配器与facade约束不改。

8502实际无导入覆盖回归exit0：103 passed/1 skipped/2 warnings，132.67s；JUnit104项零failure/error，suite132.582s，skip仍为原Windows native材料限制。涵盖原四Session/执行文件、原hosted_application消费者、三实际来源/声明/冷导入检查及六个原架构文件。原48与候选51不再叠加为独立通过数；两条JUnit property警告保持，不改配置造绿。75239实际四源mypy通过（silent依赖，非全图），11976原生成新鲜度check通过，实际Ruff/diff通过。

三份独立实码报告分别复核实际SHA、接口/算法/关闭边界、1883份全成本、两处精确清单和JUnit/进程终态；没有新增具体阻断，实施owner仅接受本片已验证替代。不外推新的Product、原生平台、所有取消交错或性能数值；A19所记17项祖先权限setup限制也未因本次选择的不同测试范围消失。全Goal仍较系统起点多2168行、Coding距15K尚差112759行；继续完整职责收敛，不能以本片验收整项。
