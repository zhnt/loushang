# H-COD-KD-009：启动装配首批三视角评审

- Authority: review evidence；不替代设计或用户对重要环境/组件工作件的评审。
- Design status: accepted（R2 §5 owner publication及§10清理R2合同）；其余广域接口proposed。
- Implementation status: partial；publication与三种固定清理路径接通，实际代码三视角已完成，整个P2/Goal未完成。
- Owner: 共同实施owner `/root`；原三个独立agent分别审职责/复用、运行/失败、数据/兼容。
- 对象：[专项设计](startup-session-assembly-convergence.md)。方法：本地干净archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`，未验证远程。

## 设计评审与范围

R1三个视角均指出present-empty capability与absent binding不可合并；同一has_targets不能控制所有phase。R2补全原可达分支、错误首次抛出与组间短路、旧flag不重置及base→capability退役资格。六份原报告与R1/R2冻结字节分存树外，不随后续状态文字改写。

R2独立复核无首合同剩余具体阻断，确认新增的是原Session集成内部模块，不新增环境或组件关系。实施owner在用户已接受的P2 Session owner证据责任内接受§5合同，没有伪称用户接受新接口或整个8092行装配已就绪。其余广域关系变化仍按用户约定评审。

## 实际代码三视角

| 视角 | 独立核查 | 结论 |
| --- | --- | --- |
| 职责/复用 | 原两份Code状态机退出；单lease不加包装；集合fanout唯一，原assembly薄入口共用；Graph和证据账本仍原权威 | 本首批无具体阻断；不宜扩成任意phase引擎 |
| 运行/失败 | prepare先存后写、commit暂存BaseException且继续组、require一次抛错、present-empty与部分fanout、dispose按原资格和顺序 | 首批合同保持；不替代真实native/并发或其余构造路径证明 |
| 数据/兼容 | 原公开构造/collector AST、tuple/map真值、排序、持久wire与身份、21固定期望、全源摘要及全部接收成本 | 本首批无具体阻断；私有字段及继承metadata变化明确，不承诺任意私有反射/热重绑 |

实际四源frame SHA256 `3724e164324e6f2ca7462652263c14315f2c23fff8c04886c7720efe3d6aee78`。各原报告完成时真实集成仍pending，终态补件另立，未覆盖历史报告。

## 真实终态与有界接受

5537实际75不同节点通过/382.89s，XML零failure/error/skip；原not-live、skip-host-runtime和断言/超时保持。原21算法观察独占捕获后，实际30496同21期望通过；它们使用叶/Graph替身，不冒充真实IO。99424四显式源silent-import mypy通过，非全依赖图。原持久ledger/codec不改；当前1893源中1889同起点。

最终成本Code **−79**、Core **+180**、系统 **+101**；当前Code125650/系统637783，系统净减及Code15K均未达。首帧整文件格式化与最终未改子树布局恢复AST相同，原三文件已有format基线限制明确，原帧与最终字节均保留；不把格式改变当去重或全格式通过。

三个review-code-*-terminal.md独立核真实XML/实际源/固定期望后关闭首批pending。实施owner `/root`据此接受本片实际接通及旧共同体退出；不接受整个P2、KD008或完整Goal完成。其余共同输入/refresh、构造失败/正常关闭及薄入口继续推进；不重复开发KD007的租约和证据账本。


## 清理后续合同及实际终态

§10另行三视角评审，R1均发现dispose lookup提前离开原try；R2窄修复后设计接受。真实接入三个Code外观字段/构造/slots保持，Core无状态Mixin执行不同关闭合同，同一self的Protocol类型视图没有新增状态。Code只留领域标签/选择/绑定，原helper与实际Core构造共同复用；持久权威/根寿命/Graph未改变。

实际34原场景通过333.81s，属于类型/回调末修复前的import版本；末Protocol固定44及原构造45通过，5lookup探针因遗漏module globals而失败，保历史。修正probe环境后5过；最终具类型回调5lookup+原构造6过4.82s。原44期望全hash未变，不叠加重叠节点，不冒称最终全批重跑。原10类型错/随后1错与末单源通过分列；七显式源分批silent类型通过，非全图。各节点、局限与成本见[专项§11](startup-session-assembly-convergence.md#11-清理完整路径实际接入及代码评审)。

三个review-code-*-terminal.md核末具类型回调/同对象视图、1895全源与固定期望及真实结果后，无本路径剩余具体阻断。实施owner `/root`接受此清理路径，不代替完整P2或Goal接受。最终−252/+303/+51，Code125398/系统637834；系统仍未净减。源码、原失败/报告/期望与分支切点保存在产品树外cleanup。


## Loader回执至Catalog输入：设计与实际代码三视角

KD009 §12另经三视角设计评审后，实施owner在原P2关系内接受具体内部接口并接通。原Catalog的Selection/Adapter没有receipt fact→admission/path的转换实现，新内部模块补此缺口，直接消费原Source specs/handle/locator/capture；不新建Loader或重复Kernel。Code保来源/信任/plan/clock/错误政策及公开入口，六个私有重体退出。未引入新环境/组件关系，不借此接受KD008待用户评审的图。

| 视角 | 实际独立核查 | 结论与限度 |
| --- | --- | --- |
| 职责/复用 | Code领域定义保留，原Catalog接回完整输入边界；后续Adapter重验、Source/Graph/持久权威保持，原六体无fallback副本 | 本职责迁移可有界接受；原来只有一份算法，不能称去重 |
| 运行/失败 | 原前18语句、package早退、原因累计→native根→领域拒绝→embedded capture→Selection/Adapter；同handle借用、无新lease/clock/cleanup | 无新增具体运行阻断；原10失败未关闭，未证明隔离后全绿 |
| 数据/兼容 | 原公开policy/签名/DTO、coding-*身份与hash域、snapshot/disabled规则；1904实物SHA及16旧JSON、三份实际XML | 无新增具体数据阻断；probe没有非空package/snapshot成功样本，不扩称全部组合 |

最终两源frame SHA256 `acfb4deff7c40b649a82ecef4cfd4aa51e56396ad7cd7962eb6ddf6e4a43e7de`；全量1904源frame `63d9b49655f6594a080ce0fc4e0380f9a51690d576a609ef64773abcafeb3232`。最终Code725（−369）/Core410（+410）/系统+41，实际Code123976/系统638335。末修正仅Code import排序/空行，原审源与最终非import AST/import绑定相同；候选726/+42历史保存。

三位均自行核XML：迁前59454原47项37过/10失败；实际60806同47状态，加16旧观察，共53过/同10失败。失败message九项逐字同，另一项仅set元素显示顺序不同；原文未改。最终67613的16观察全过，和前批重叠，不累计。原5测试SHA保持，实际只跑shadow/local discovery/rcp5三个文件；首次两个probe无效输入失败及修正后仅补两期望的历史保留。16540实际两源silent类型、Ruff/format、83237生成及40450文档静态9项、diff检查通过，不是全图/全SDK/native证明。

原10失败保留为验证欠账：祖先AGENTS的输出/发现源码提示来源环境影响，但未逐项证实全部归因，更没有放宽断言、改Product发现或改指定runtime/wrapper制造通过。三个实际报告均有界接受本替换，不接受完整P2、Goal或其它图。实施owner `/root`据实际终态和报告接受此内部职责交付，完整原件/失败/期望和报告树外`p2-catalog-inputs`留存。

## A28：双Plugin Resume parent检查/登记/封存

对应[KD009 §13](startup-session-assembly-convergence.md#13-a28双plugin-resume-parent协作归原approval)。树外R1设计 `f2605823e518c2eb3748e588549ed87d3960b640c59a718721193ca95ed99c3b` 原样保存；运行/兼容独立发现“只读”措辞不准确，R2 `fef785ae8c025d60d29a6c5ba3a4bfb4ef88f3dfac761af1d65b6ca5b4cd0975`澄清本层不append事件，但底层原exclusive/create-lock与partial-tail repair保持。两个原Journal及其IO策略未改，不以更严无写盘检查兑现错误文案。两个窄补核分别关闭RT-RESUME-PARENT-D01和DATA-RESUME-R4-01。

三独立设计视角确认完整三操作归原Approval，无新重要环境关系、owner、parent registry或跨Journal事务；实施owner `/root`在原授权内接受具体R2并接通。Code保原实际DTO两自有字段/annotations/slots、原post_init和_journals，Core基类只含方法、无构造与状态；纯sealed错误构造保Code，不是IO callback。KD008/KD011图待用户状态不变。

| 实际代码视角 | 独立核查及有界结论 |
| --- | --- |
| 职责/复用 | 三旧操作体确实退出Code，原Code DTO同一对象承接无状态基类；实际直接复用两native Journal，无新事实/执行权威。+38对应完整三操作归位，不叫算法去重；无剩余职责阻断 |
| 运行/失败 | 原具体Error/code、Definition→Activation顺序、原revision取值、第二owner失败保留第一事实与重试、原Code工厂晚绑定保持；require_open锁/repair原效果准确披露。无剩余具体运行阻断 |
| 数据/兼容 | 1908全源/两实际SHA/58旧JSON与最终XML核实，fields/有效方法签名/hints/slots及未迁定义保持；MRO/方法定义位置改变、旧pickle/独立旧安装未跑不冒称全等。终态补件关闭pending，无剩余具体数据阻断 |

最终两源frame SHA256 `c03150f59dea2d225cf9a505b4777cd4d3d352a12da06153e50dc28afa1632dd`，全1908 frame `0c7a85a84fd7f2b084be336e02a679849bd9f7fabfcd061cf94de3e4f5dc7ee9`。实际Code1887（−70）/Core108/系统+38；候选1888/+39及首实际I001、首实际68通过保历史，末修改仅同组import排序/空行且最终实际62155同68再过/9.61s、exit0，不累加两批或原基线。1104最终两显式实际源silent/no-incremental类型、984af6 lint/format与80729生成检查通过，不外推全图。

三个实际review-code报告及数据终态补核均已读；实施owner `/root`有界接受本实际替换。原Catalog十项、Session两项失败不销账；完整Goal范围/15K已接受且active，但尚未达成完成验收。原报告“Goal不接受”仅指不接受完成交付，不否定用户已接受scope。源码/固定观察/两版设计/XML/完整切点与报告树外`p2-plugin-resume-parents`保存。
