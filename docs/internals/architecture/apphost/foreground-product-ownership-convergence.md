# COD-RESP-A21：foreground Product Session所有权归一

- Authority: accepted implementation design；不替代原公开合同。
- Design status: accepted；2026-11-08三独立视角无实质阻断，实施owner `/root`在原P3职责范围接受内部接缝；不归为用户对新环境的接受。
- Implementation status: implemented（foreground Product接管/交付接缝）；三实际源已接通，旧包装退出，三视角代码有界接受见§5；不等于完整P3或整个Goal。
- Owner: AppHost Product集成、原Harness Session业务owner、Coding产品政策各原owner。
- 需求：[Coding职责Goal P3](../harness/coding-responsibility-convergence-goal.md)；前置：[A20控制桥接](session-control-bridge-convergence.md)。
- 方法：archmethod本地干净master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

## 1. 完整场景与实际缺口

原AppHost从已打开的候选请求一个foreground Product Session。工厂先结清未发布资源，创建Session后立即接管可关闭返回值，检查绑定，成功交付受限的非拥有profile视图；失败释放或保留清理债务。交付后的Session归原AppHost runtime，工厂关闭仍独立围栏/关闭catalog及原Session factory。本片覆盖这条完整路径，不改Session业务、产品选择、Transcript或进程启动。

设计起点Coding的hosted_application共932行，含Session owner、profile借用视图、转发runtime、Product factory，以及绑定校验。其余request、Profile执行权冲突检查、resolver、leased binding和原应用装配保留。不能因为在同一文件就把这些领域合同全搬走。

| 现有能力 | 复用/保留决定 |
| --- | --- |
| AppHost原ProductFactory / ScopedProductRuntime / ProductProfileBinding | 保原合同与调用者，不新增factory框架、事务管理器或第二控制对象 |
| AppHost runtime的`_BoundProfileView` | 已是只有binding_key/opaque_binding的非拥有视图；直接复用，删除Code自建profile视图 |
| AppHost application的descriptor、task failure与background result helper | 与Code对应程序同体，直接调用原定义，Code保必要私有别名，不另写一套 |
| Harness `await_owned_task` | 原failure-first join直接复用；不改取消/失败优先级 |
| AppHost `RetryableCloser` / CloseGroup | catch BaseException转bool、shield及debt语义不同，不能直接替代本片异常可见的Session close |
| dark HarnessAppHostSessionAdapter | 负责候选目录/claim/canonical协作，不是本片Product Session factory；保持dark，不激活其路径 |
| Coding的Session工厂、catalog、身份/投影及Profile执行权 | 原产品提供并继续拥有领域语义；无Core到Coding依赖 |

## 2. 内部接缝与资源分配

保留原公开`CodingForegroundProductFactoryV1`真实类、明确构造签名及两个原Product Protocol。其同一个实例继承AppHost内部`_ForegroundProductFactory`，原五字段、active/debt集合及虚调用点只一份；仅以product_id与显示标签两项纯元数据表达原Coding错误和选择。不以新回调表、服务查找器或大Product/context表达流程。

机制置于`apphost/integrations/session_product.py`；绑定检查归同一集成组的原`session_control.py`，沿原Identity DTO与Core已接受协议端口。Code原`_validate_hosted_binding`名薄委托。foreground校验保持原identity→control→projection callable→静态respond/close→control callable顺序；与A20的动态结构校验是不同接受集合，不合成更严格的通用准入。

原Session owner同时实现ScopedProductRuntime，删除仅转发key/profile/close的`_ForegroundProductRuntime`。在原验证完成、active移除之后才构造原`_BoundProfileView`并返回；owner提供的key/opaque getter只读内部值，不新增raw Session属性读取。profile视图没有close，不把拥有者自身暴露为借用视图。每个已交付Session从三个辅助对象变为owner+原非拥有view两个，不增加Task或持久事实。

这是原AppHost factory/资源角色内的定义归位，无新系统环境参与者、进程、授权主体或存储。不接受KD-008/P2待审方向；若独立评审发现实际改变重要职责或权限，应收回该判断并按用户约定评审。原Harness仍负责Session业务，线协议/托管资源交接仍归AppHost。

## 3. 时序、失败与兼容合同

| 路径 | 必须保持 |
| --- | --- |
| 构造 | 用原类型静态descriptor检查create_session为native async，再绑定原bound方法；不接受仅挂实例上的新async端口，也不加别的准入 |
| candidate与create | 先通过self.settle_pending_cleanup；按原顺序读key/opaque及精确key/Product ID判断；原create参数与失败外逸保持 |
| raw Session接管 | 先动态读取close并核async，随后成为同一active owner，再检查绑定；无close时仍按原unowned错误，不假称已经清理不可关闭返回值 |
| 发布 | 验证成功后移除active，再取得非拥有view并交付同一owner；不把返回运行时继续留在factory债务集合 |
| Session close | 原每Session lock与close task；并发共享同一任务，失败/owned task自身取消可重试；failure-first join成功后才置closed，不改成吞错误或caller取消立即返回 |
| 无效返回清理 | 原CancelledError分支移除active/debt并重抛；其它BaseException留下debt并抛原cleanup_incomplete。保此既有边界，不悄悄增加新承诺 |
| 清理重试 | 原tuple快照、gather/return_exceptions及只有None结果移除debt；active或debt仍在则原拒绝，不新增全局串行锁 |
| 工厂关闭 | 原catalog fence→self.settle_pending_cleanup→catalog close→可选factory close；各Exception独立收集，最后抛第一项，BaseException原传播不改 |
| Profile | 原Coding ProfileFactory继续校验原绑定与execution_claimed；不会因通用factory而多获得Session执行权 |

公开Code类FQN、构造/公开方法签名及解析后的注解、原DTO/Protocol/导出、原参数值和错误type/message/cause保留。Code两个原导入类型保同名reexport，避免迁移后去掉原可解析名字。原私有helper定义位置、工厂MRO及类自身slot/方法元数据改变；返回runtime/profile的私有具体类型也改变，不承诺未约定的完整反射或私有类型pickle。旧runtime的`_session`等私有属性不作为兼容API。若发现真实外部支持义务，须明确处理，不能只因仓库无引用断言生态无消费者。

底层Journal、Transcript、锁/权限/数据格式均不改，无迁移/双写或远程副作用。整个三源加原架构位置清单一起回退，不保Code重型fallback。

## 4. 实物、全成本与验证

产品树外`p0-worker/a21-foreground-product/`保存十源/测试起点、A20全量生产manifest、外置候选及原行为期望。原三文件baseline24957：28 passed/1原Windows条件skip/2JUnit属性warnings，31.34s。另用旧实际Code源码独占捕获八组可观察调用/错误/资源事件，含非拥有view、未发布debt后再create、owned task取消重试、caller取消并发close、无效candidate先drain、动态close与静态校验、async descriptor和关闭首错；期望不从候选生成。

首个捕获28841因探针构造了非法scope fingerprint，三项失败并在随后错误路径等待；已定位并INT终止该确切进程，修正测试身份为合法64hex，原产品未改。修正后53009九项通过/2.49s，八组原预期完整落盘；不把探针错误当Product缺陷或隐藏为首轮全绿。产品候选只用明确三模块import overlay，不把原型通过写成实际交付。

| 完整生产成本 | 原实际 | 格式化候选 | 变化 |
| --- | ---: | ---: | ---: |
| Code hosted_application | 932 | 734 | −198 |
| 原AppHost session_control | 377 | 421 | +44 |
| AppHost session_product（含类型/导入） | 0 | 243 | +243 |
| 合计 | 1,309 | 1,398 | **+89** |

本片有两个重复薄包装退出和原helper直接复用，但主要是必要职责迁移，系统整体仍增89，不能称系统净删。两个内部Protocol、泛型、兼容类及格式成本均计入；不以放在树外/生成实现隐藏。原Code≤15K、系统低于634794和全部P1–P4目标不变。单片成本须由真实职责/复用评审判断，不借迁移重复搭新框架。

三显式候选源mypy21684通过（silent imports，非全项目图）。候选行为与实际替代回归分别记录；未变的本机/原生限制沿原标记，不重开测试矩阵或付费模型试验。实际实施需同步原AppHost文件闭集的唯一新路径；不增加扫描、assertion、门禁/触发/平台/route，也不放宽整个目录。原AppServer消费者无需增加路径，协议校验继续位于A20已登记模块。

三视角设计接受后才能接入实际三源，关闭原重型体，再复用上述消费者及必要负分支做实际代码评审。实际生产计量、受测路径、Core拒绝Coding冷导入、公开面和完整成本均须核实；外置候选不计为实现，实际接入后的partial/接受状态另记。并发探针只覆盖所列交错，不能外推所有取消/跨进程或性能负载。

## 5. 三视角与实际交付证据

原设计冻结770c35104e5ef955be447b633c574ce3bb9aff4fc67cf18966288bf3f58dacf7经职责/复用、运行/失败、数据/兼容三独立视角接受。各自核实原BoundProfileView及failure-first join的真实复用、单factory/Session资源owner、原公开合同与完整成本；此为原AppHost内部接缝，无新重要环境参与者或权限，不接受KD-008/P2。实施owner `/root`在原Goal/P3授权内接受设计并安装三源。

两Core实际源逐字等候选。Code实际路径Ruff重排imports，比候选多3行；完整import alias绑定集合与非import AST相同，保留定义未被整体格式化。实际Code932→737、原Core377→421、新Core243；本片**Code−195、AppHost+287、系统+92**，区别于历史候选−198/+89。全量1,884生产文件中，两旧源修改、一源新增，另1,881生产源逐字等A20；Coding127,564、系统637,054。整体Goal累计Coding−10,191、系统+2,260，仍未达≤15K/系统净减。

仅给原AppHost.rglob精确文件闭集增加`integrations/session_product.py`一项，删除该Set literal后整测试AST恢复，未新增断言/扫描/route/trigger/platform或目录豁免。实际消费者、Core冷导入、公开签名/解析hints与原Code其余17定义AST检查均走实际路径，无候选overlay。

95250实际综合批exit1：92 passed/2 failed/1原Windows native skip/2JUnit warnings，137.86s。两项失败分别处理且原JUnit不覆盖：

- G14原整个scenario的20秒上限触发，hosted binding占19.771s（CPU5.227s），其中未改的插件fresh cutover占17.261s。原baseline与候选同节点通过；待类型/生成进程结束后，52927对同一selector、源码/断言/20秒上限不变独跑，1 passed/10.63s。关闭本片具体回归疑问，不把它当性能负载或所有环境保证，也不加sleep/放宽预算来造绿。
- G9旧expected_imports遗漏早已存在的`loushang.harness.runtime`。实际`coding/apphost_composition.py`摘要等A20起点，本片未改该源；两独立窄核确认这是原owned-task join依赖清单漂移。仅补此Set literal，删除后整原测试AST恢复；属于精确允许集同步，不新建门禁。23757原失败selector通过（1/0.74s），其它检查不变。

最终94个不同pytest节点通过及1原skip；原28、候选37、旧捕获9和额外表面3均不重复累加。44094四显式源mypy通过（silent imports，非全项目图），35440生成新鲜度check通过，实际Ruff通过。三实际代码视角的静态结论与运行终态关闭附记保存在树外同一目录，不重写初次失败或将它称作综合首轮全绿。最终接受与文档/源码归档由实施owner综合收回；本片不增加Session业务、存储或执行权限。

三实码视角及运行/数据终态附记均无本片未关闭具体阻断；G9实际窄diff和两次失败selector关闭由独立视角复核。实施owner `/root`综合接受本接缝，原始报告/失败/候选及实际成本不覆盖。公开外观、所属资源与借用视图的职责归一已实施；完整P1–P4和整个Goal继续active。
