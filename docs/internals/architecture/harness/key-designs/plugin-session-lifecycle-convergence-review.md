# H-COD-KD-007：Plugin / Session 生命周期三视角设计评审

- Authority: review evidence；不替代设计或用户对环境/组件的评审。
- Design status: accepted（R2.1）；原技术合同评审及2026-11-08用户明确方向接受见末节。
- Implementation status: partial（D3实际有界接受）；其余P2实现仍待完成，原设计评审记录保留历史状态。
- Owner: 跨组件架构实施 owner `/root`；三独立 agent 分别审职责/复用、运行/失败、数据/兼容。
- 对象：[专项设计](plugin-session-lifecycle-convergence.md)；方法为本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

## R1 独立结论与 R2 修订

冻结 R1 SHA256 `d4262cc554ad1d93ac0b59f0a69fd1fae4289ddcbc4fb28867b0e64b16599951`，实际 A11 基线的八源/原件指纹独立匹配。三个视角只读源码与该对象，未读同行报告、未修改产品。完整原报告保存在产品树外 `p2-plugin-session/review-*-design-r1.md`。

方向可以提交用户评审，R1 不能作为实施就绪接受；具体问题不是“还有代码没写”，而是接口和失败合同存在下列缺口。

| 重点 | R1 实质发现 | R2 的明确选择 |
| --- | --- | --- |
| 职责 / D3 | Windows pin 请求 0x81，默认 Quarantine profile 额外权限与 native-query 时点不同；FD helper 失败已 close，存在二次关闭风险 | 在既有 Resources owner 内提供固定 pin profile，复用原 native query/close/转换，单份 raw→FD custody；不新造 ctypes |
| 职责 / D3 | POSIX 原名验证与公共 Journal 不全等价，全部 catch OSError 会改错误面 | 原 Journal 内部提取相同读取体，caller 保原名称准入；只 metadata 拒绝投影错误 |
| 职责 / D4 | GC writer pair 与 direct-host completion 协同去向不明确 | GC pair 归既有 PM assembly；固定 completion 协同与 Code 的 cleanup/成功声明/身份政策分开，不推广任意 host 自动成功 |
| 运行 / D1 | 两 registry 寿命不同，inner/outer closed 也不同，不能用统一 LeaseManager 或 DirectoryWriterLease 替代 | Session refcount/claim/incarnation 与 Package Product startup 无 refcount/pop 外 exit 分开，原 registration 与 state/OS 锁顺序保留 |
| 数据 / D2 | 跨家族只按 owner/generation/handle 三元组占用，单组内部才分别核 generation 二元与 handle；R1 表述会加严 | 写明两个集合及键、retired 仍占用；列 writer/replay 状态表、历史 published-first、幂等忽略新 reference 的分支 |
| 数据 / D3 | owner 查询 repair、兼容 raw 投影 skip、read_only 管理 raise 不可合并 | 保三种加载/锁/create/错误策略、缺根 no-op 和 root/ABA 顺序 |

R2 冻结对象 SHA256 `333cba4ddeb92283a7892fdafbae00255abe2eadbb3f892d6ed08d26ada1b699`；§9 明确上述接口与原方法归属，新增图示既有 Package Product 连接。当前正在做相同三个独立视角的增量复核，未预判接受或声称实施就绪。

## 已执行证据与局限

- 原 `test_plugin_owner_generations.py` 六项基线：7094，6 passed/0.79s，沙箱外、not live、skip-host-runtime。它只证明未迁移起点的已有回放/幂等/冲突/损坏/旧格式场景。
- 原 `_replay` 的三输入纯内存实验确认跨家族三元键边界：同 generation 不同 handle 可、同 handle 不同 owner/generation 可、相同三元组拒绝。没有打开文件，不证明 writer、并发或授权。
- 2,713 行为当前分析池；没有实施新 Product 源或实测替代成本，不声称新实现、全平台或系统净减。
- 原始指纹、R1/R2 冻结稿与报告不随后续文档状态补记重写。技术合同接受、用户方向评审、实际代码接受分别记录。


## R2 综合结论与 R2.1 澄清关闭

三独立增量报告分别保存为 review-ownership-design-r2.md、review-runtime-design-r2.md、review-data-design-r2.md，均核原八源未变。职责视角关闭 R1 三项具体问题，数据视角关闭 DATA-P2-R1-01 及原读取/状态合同缺口。运行视角在 R2 指出 RT-P2-R2-01：startup 注册前还有原 epoch 根准备，不能省略或移至注册之后。

R2.1 将该顺序补为 Linux authority/control 根或 Windows control 父链/root → 原 registration → state/package roots → startup OS lock；运行 reviewer 独立核对 diff/SHA 后关闭这一具体缺口，并在原 R2 报告另节记录，无剩余运行设计阻断。澄清冻结 SHA256 `df43ced34d0986adc324a0b00a35eb2595225e7cec29542de8c773556b5fb952`。职责/数据原报告绑定的是 R2 字节，不能冒称三个 agent 都重审了整份 R2.1；综合接受的是 R2 三视角合同加这一原序窄澄清。

实施 owner `/root` 在本 Goal 授权下接受上述**技术合同**，没有代替用户接受新增 Package Product 连接及 P2 环境/组件归属。按用户“系统环境图等重要工作件需要我评审”的明确要求，方向提交用户后才开始此切面产品代码。当前实现仍 not-started；Package Product 需要在原域最小扩充 startup 接口的成本不漏计，不能称其全部接口已经存在。

本接受只使设计可以指导有界实施，不证明 DTO/值兼容、真实关闭/恢复、新接口成本或原生平台已经通过。实施仍须从原源固定必要合同、替换完整路径、删旧并做实际三视角代码评审。系统 Code130,062/636,588 总量未因本轮文档工作变化，完整 Goal 保持 active。


## 用户方向接受（2026-11-08）

用户已明确接受本 R2.1 环境/组件职责方向，授权继续实施并完成代码三视角评审。原报告/冻结对象及“当时待用户”的结论保持历史事实；实际当前状态是设计接受、实施尚未开始。此接受不证明实现/新平台或全成本通过，也不接受KD-008。实际八源复核及用户接受记录在树外user-direction-acceptance-20261108.json。


## D3实现评审检查点

D3五源接入、Code全部原类AST及实际1886源摘要由三独立代码视角分别核查，无本片具体静态阻断。候选gate三词法替换曾增数值/格式敏感条件，原报告保留并另立职责/数据澄清；最终仅位置维护及明确scope reduction（10test/94→91assert），全部CLI174 assert AST/timeout保持，未增加PR gate。完整成本Code−397/Core+463/sys+66，不能当系统净删。

44698实际回归尚在运行，46989五实际源silent mypy及10361生成检查已exit0；不预支实际行为接受。原候选/基线及四注入失败历史不覆盖；代码报告在树外implementation-r21/compatibility-capture/review-code-actual-*.md，实际终态另补。整个P2及Goal继续active，不把这一完整查询路径替代成员身份/代际证据/startup和关闭重试。


D3实际终态补记：44698 exit0，181 passed/5原Windows skip、458.98s，XML186节点零failure/error；46989五实际源silent类型和10361生成check均exit0。原三实际静态报告及各自pending保留，运行/数据终态另补。实施owner `/root`接受D3完整查询路径，不接受尚未实施的成员身份/evidence/startup等余项或整个Goal；系统净增66如实计账。完整资料与源码归档另存树外。


## D1/D2/startup 实际代码三视角与终态接受

职责、运行失败、数据兼容三个原独立reviewer分别对实际七源及before审查；最终指纹、两个Code导入排序/延迟resolver修正与307原assert AST另核。结论是本子路径无剩余具体阻断：单一owner registry/claim/incarnation与证据append/replay归Session，原非refcount startup registry/registration/失活归Package Product，原Resources目录leaf及Journal复用。Code _prepare_private_tree仍有三个真实消费者，保留薄适配而非误删；原公开event/family/error/codec和具体返回类型不变。未把暂留Code的family/reconcile/外层close、GC和direct-host协同称为已完成。

原70项46518为69通过/1个20秒子进程握手超时，482.40s；25797精确重跑同原节点1通过/13.76s，未改Product/timeout/断言。最终startup/tree三个原消费者25247为29通过/49.74s。原CLI/架构61通过/5原Windows skip；树外交叉旧新续写与字段合同三项23782通过，原探针对象身份误比的失败保留。这些覆盖有重叠，不累计为独立总数，也不冒称首次全绿/最终字节全批重跑。最终silent类型、Ruff、生成check74821、静态文档9项及diff通过。原启动超时未确证原因，不据复验宣称消除了偶发风险。

报告分别保存于树外 remaining-lifecycle/review-actual-{ownership,runtime,data}.md，最终字节与运行/数据终态closure另立，原pending/失败报告不覆盖。最终全量1,890源中1,883与D3逐字同；Code126,023、system637,360，本片 **−558/+929/+371**，不当系统净删收益。实施owner `/root`按用户已授权方向接受这条D1/D2/startup子路径；完整P2及COD-RESP-GOAL-002继续active，15K/系统净减未达，不替代后续family/退役/关闭与PM协同的实现和代码评审。没有新增native Windows kernel/ACL/concurrency验证或PR gate。


## D4 完整路径代码评审及真实终态

三个原独立视角分别审实际4源/before、同对象状态、15项限定配置、PM原GC/settled-host动作与持久身份；原报告及终态窄补件分立在树外membership-completion。无本簇剩余具体职责/运行/兼容阻断。原Code字段/构造与acquire具体返回保持；继承方法定义metadata变化及私有重绑定边界明确。两builder/兼容投影AST同，原共享owner保持。

40816原70场景首轮70通过332.46s；34030原查询/架构/边界61通过/3测试旧符号AttributeError/5原Win skip。删除无实际分支的Code path观察，取实际capture lock_at，全部174原assert AST同；96929三原参数通过6.84s，未改Product/timeout/门禁。最终公开facade33350两项通过1.99s，原57583同两项不重复计。最终Code仅isort，其他三Core同被审字节；非import AST/绑定集合同首集成，最终四源成本−294/+616/+322，而首帧−293/+616/+323历史保留。11273四源silent mypy、58845生成check及Ruff通过；非全图类型或新native平台证明。

实施owner `/root`依据用户接受的R2.1方向及上述独立证据，接受KD007生命周期簇接通和旧机械体退出。未接受整个P2启动装配、其它P1/P3/P4或整个Goal完成；Code125729/系统637682，系统净减与Code15K条件仍未达。最终全源manifest/分支切点/测试/报告及原源另行归档，首失败与原pending不覆盖。
