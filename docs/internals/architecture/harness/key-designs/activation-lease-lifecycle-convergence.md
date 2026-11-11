# Continuity 激活lease机制复用（A92）

- Authority: COD-RESP-GOAL-002 有界交付及证据；不替代完整P1–P4验收。
- Design status: accepted，Root按授权综合职责、运行、数据三个独立源码视角接受R3。
- Implementation status: complete within the activation-lease algorithm；完整Goal仍partial。
- Owner: 原Harness.Continuity；Coding产品策略、源选择和Session适配保持。
- 起点：`0510042f8092345dc671407228284ffbf841f42d`；1967生产源与13资源树外冻结。
- 方法：本地干净archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`，未声称上游同步。

## 问题、真实消费者与复用

[CallbackPreparedActivationLease](../../../../../src/loushang/harness/continuity/activation.py)
与[Generation activation lease](../../../../../src/loushang/harness/continuity/plugin_provider.py)
重复实现完整consume/abort/close、单次标记、消费Event与abort Task重入/取消/重试。
实际Coding activation bridge返回Callback lease，安装Plugin Provider的copy-first准备
再用Generation lease绑定原Gate；Hub跟踪及security quiesce真实消费这条链。
两个阶段的lease实例承担不同责任，仍保留；本片退出的是第二份算法实现，不是再
把既有staging或整个Coding bridge迁一次。

直接让原Generation薄类继承现有Callback机制；只提取原flag初始化、准入完成回执
与成功/abort注销窄hook。原默认callback仍支持sync/awaitable及abort=None；Generation
用普通async方法严格await inner协议，晚读target/disposition/consumed，构造不缓存元数据。
没有新增组件、私有FSM基类、manager、状态表、持久格式或Code IO回调。原Gate、
prepare/deletion/pending cleanup/Hub机制不改，未把它们强套这一消费算法。

完整序列仍为closed/abort guard → attempt guard → Gate.admit → flags/Event.clear
（try外）→ inner效果 → 自身consumed标记 → Generation closed/unregister → finally中
consuming=False/Event.set → 原complete。admit拒绝不能污染attempt；clear/set抛错仍
按原范围跳过complete，complete与unregister异常仍保原context/优先级。Generation
公共consumed读inner，自身abort决策读私有标记，不能混成一个判断。

abort intent在await前；consume期间abort等待原Event，成功不再abort产品candidate，
失败保原可结清状态。并发abort共享一个原Task；取消waiter不取消Task，普通失败
清引用后可重试，owned Task自己取消仍保原cancelled Task供后续join，不顺手变重试。
Callback无abort时原地close，不创建Task。共享的postwait closed guard只省去已完成
状态的幂等重复赋值或join已完成Task，不新增效果。实际真实Event交错另有旧对照。

Gen是私有类，直接继承新增Callback isinstance/async-context能力，consume/abort/close
定义owner及Task coroutine私metadata改变；不为这些负能力/反射另造基类或保壳。
实际公开Callback构造、方法签名、属性/context/close、Error类型及export保持；没有
公开DTO/wire/schema/路径变化。普通方法descriptor仅在调用时绑定self，不保存自身
boundmethod字段，避免新增完成后的引用环。

## 候选修正与旧期望来源

R1系统−22的with方案通过原164消费者/1原skip，但Event.clear/set故障时新增complete。
原4项Generation Event反例实际全部失败，包括实际Event.set唤醒closed-loop Future；
R1不接受。R2系统−26恢复线性scope，但存两个self绑定方法，GC禁用的原即时弱引用
回收反例实际1失败，R2也不接受。两版完整候选/原green/反例均保留，不倒写历史。
R3只以原complete bound receipt作为consume局部变量，并直接用async方法descriptor
承接inner；保scope且不新增selfcycle。所有生产安装仅R3，旧raw与fixture未改。

固定旧观察仅运行冻结baseline：41项原capture通过0.31s，严格fixed replay41过0.50s。
真实Callback/Generation/Gate/Tasks/Events，inner与故障端口受控；记录完整错误类型/
消息/notes/cause/context、flags/Event、Gate记账/库存、同一abort Task的稳定角色及
cancelling状态、顺序/晚属性和GC禁用回收。Event方法注入与真实closed-loop Future
故障单列，不伪装全SDK或任意跨线程/跨loop行为证明。

原JSON241258字节，SHA256 `1d25a0ce05574359a6799387889c4097ed6a54a5a822560ac3e20ec2354aeeac`；
原41 exclusive raw文件逐SHA保存。持久gzip4627字节，SHA256
`28f664d55753a05c62009769ce8fec576674aa4d30f42c2eacf4df97cbcd8c8d`，无数据投影/候选生成期望。
[显式probe](../../../../../tests/harness/continuity/probe_activation_lease_runtime.py)482行，
保原全部case/helper AST，仅去捕获入口并用gzip/严格JSON比较，保bool/int/float类型。
外置原源/所有加载origin校验与持续probe分开，probe不锁未来生产SHA，不扩默认CI。

Root首次三个全外置命令未加载tests/conftest，skip-host-runtime未注册而usage退出4，
没有执行Product；保留setup失败，补载测试配置后保全部原selector重跑。仓库路径
自动加载conftest，不重复显式载入。未改产品来修测试启动或扩大平台支持。

## 成本、终态与剩余

| 生产源 | 原行 | R3行 | 净变化 |
| --- | ---: | ---: | ---: |
| 原Callback机制 | 149 | 168 | +19 |
| 原Provider/Generation模块 | 883 | 836 | −47 |
| Coding | 113755 | 113755 | 0 |

系统净−28，都是结构变化，无格式压缩；其余1965源及13资源字节同。原消费者
baseline164过/1skip5.90s；R3实际164过/1同skip6.09s，skip为当前平台已有secure
staging，原unsupported测试按自身规则跳过。实际旧41对照0.49s及仓库包装41项均
通过，mypy两完整源、Ruff/format通过。数据/职责/运行三视角按实际完整源有界接受，
有限交错不是任意调度穷举或Python3.12 eager task factory验证。

当前Coding430源113755行，系统1967源647636行；相对Goal起点Code−24000、系统
+12842。482测试行、4627字节fixture和文档单列，不把它们说成生产精简；整体系统
增长与完整P1–P4/领域化/≤15K缺口仍在，距15K尚98755行。KD003未实施；KD011/A33
待用户且未采用。

下一簇继续按整条真实路径审计。lmux close现有manager/connection已共享，剩余输出
与CAS屏障需要适配成本，目前没有充分简化证明而不迁；KD003原staging已在A68共享，
不能用owned-only bytes删除现存非owned/transient/copy及公开Path合同，也不重复计收益。
