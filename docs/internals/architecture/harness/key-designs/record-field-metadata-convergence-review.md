# H-COD-KD-006：三视角设计与实际代码复核

- Authority: descriptive review evidence。
- Design status: accepted within delegated R3 implementation scope。
- Implementation status: implemented locally and reviewed；不是完整 Goal 验收。
- 对象：[字段声明复用](record-field-metadata-convergence.md)及 20 份实际生产源码。
- 方法：本地干净 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

## 结论与责任

职责／复用、运行／失败、数据／兼容三位 reviewer 分别完成候选及实际增量复核，未互读报告、未修改产品或重跑检查。当前无剩余具体阻断，实施 owner 据原 R3 和全 Coding 扩围授权接受本片内部复用。系统环境、运行角色和外部协议未变；不制造用户接受新的重要架构工作件或完整 Goal 的记录。

| 视角 | 核查与结论 |
| --- | --- |
| 职责／复用 | 原 RecordSchema 增加加载期声明准备，当前 51 项符合全部 dataclass 字段即 wire 的显式选择；没有新 serializer、Profile、Protocol、存储或状态权威，特殊覆盖与其他 14 表保留；无阻断 |
| 运行／失败 | 20 实际源与候选逐字相等，原记录方法及 encode／decode／keys 不变，数据校验、错误顺序及寿命不改；新扫描／tuple／dict／set 成本仅在加载期，不宣称零启动成本；无阻断 |
| 数据／兼容 | 静态展开 229 个特殊覆盖及 50 个无 label／180 个派生 label，与原属性、顺序、key、转换和绑定目标相同；原 65 元数据及旧字节／日志／业务证据分列；无阻断 |

## 实际来源与结果

候选 frame SHA256 为 `ae3f770f60aff0e682a0a685b0180380a318d2de287918f748c9bfbdbd3e3e5e`。最终实际 `code-checkpoint-a54/frame.json` SHA256 为 `6c24d2932f661334250d738309e7860f4da482088670309283f413851e24154b`，241 路径、198 Python。20 实际源逐字等于候选；将 51 处声明还原、去新增 helper／import 后整模块 AST 相同。所有记录方法及原 Schema 执行体、其余显式表保持。

原 65 元数据在未改原树的 20 源 SHA／canonical 守卫后首次冻结，SHA256 `e8417dd53b863ccb8c4c016fbfeec73277d0558cde835e3ee233f3ae3bda246c`。初探针未支持既有 partial，未产出预期；修探针后仍在原树冻结，没有用新 builder 重写旧预期。观察覆盖函数代码、bound class 和 partial.func／args／keywords 内的递归 callable，静态特殊覆盖 AST 等价另补强其来源。

| 执行 | 终态及范围 |
| --- | --- |
| 原冻结 74961 | 1 passed／2.43s，原 SHA／路径守卫，首次固定 65 元数据 |
| 候选 80257 | 1 passed／2.58s，启动前限定 20 模块加载器，65 项一致 |
| 候选类型 23027 | 149 显式源／20 shadow，silent mypy 通过 |
| 实际元数据 76072 | 1 passed／5.89s，普通工作树路径、无 overlay，20 实际源守卫及原 65 项一致 |
| 实际原回归 84073 | 19 文件，196 passed／46.63s；原 C08 记录字节／日志／业务及相关 Package 记录／事务 |
| 实际类型 73444 | 149 显式生产源联合 silent mypy 通过，无 shadow／overlay |

上述测试不相加成独立覆盖数量；元数据比较不代替实际业务，silent 检查不等于默认全依赖遍历。A42 默认广依赖 237 错误／8 文件记录继续保留。未新增原生 Windows、任意断电、启动性能或全部 Product 权限证明。241 live hash、198 Python Ruff、20 改源格式与 diff 检查通过；实际回归后无源或测试差分。

## 演进及完整成本

当前采用明确要求全部 dataclass 字段为 wire 字段，ClassVar／InitVar 排除而 init=False 仍包含。helper 不自动守未来版本兼容，也不自动排除辅助字段；增加或重排字段仍须原 wire／版本／存量兼容设计。存在辅助字段、子集、多版本不同 shape 或不同顺序时继续原显式 Schema。一次性函数指纹证据仅在产品树外保留，没有增加永久测试或 PR gate。

六原 C08 源净减 54，Harness 净减 177（已含 helper 新增 25），系统净减 **231 行**。原 before 独立格式化 +4，结构减少 235／格式增加 4 分列；减少的是 230 条重复字段声明及结构，序列化执行算法仍用原实现。最初改写更多序列化方法、系统反增 5 行的方案已拒绝，未接入。

独立全源核算：Code 138,805／累计 −7,037，原 C08 7,235／累计 −4,536／八千行缺口 3,464，系统仍 **+1,113**。本片不能替代原规模或系统净减少条件，整体 Goal 保持 active／incomplete。原源、候选、一次性样本、终态结果、三视角候选／实际报告及 SHA、实际快照和计数保存在产品树外 A54 目录；未提交或发布。


## A55：两种 Wheel 记录的实际执行复用

A54 后，两种原 Wheel 绑定记录的四个 to_dict／from_dict 字段遍历改用已有 RecordSchema，Core 与 A54 逐字相同。frame SHA256 `914f52194fe1a21a9935bca58b0e046e5024b19a77eaa0d5d4c0f335ed58975b`，两实际源逐字等于被评审 source；除四方法、两 schema 声明及 import 外，两完整模块 AST 等于 before。领域构造、hash／ID、exact dict／keys、错误及 catalog／IO 保持。

职责／复用、运行／失败、数据／兼容三个独立实际审查均无具体阻断。两记录各十字段的 dataclass、原 getter、wire key、原 cls kwargs 顺序一致；identity decoder 不转换值，固定基类 shape／派生构造行为保持。没有新序列化框架或事实权威。评审同时指出：循环与每字段 identity 调用增加热路径常数成本，未做性能基准；只有 record_revision 序号，不存在独立 record_version，未来字段／hash 变化仍须真实存量兼容设计，不能靠 all-fields-wire 或缺省值自动升级。

改动前两原源码 SHA／canonical 守卫首次排他冻结旧输出，预期 SHA256 `cf496f17e672a8049d8c1b5c990553906e31f5b431dff23977729bb2e01626da`。每类型 131 组观察包含真实有效记录、反序输入、shape／缺项／十种字段值，getter／派生 constructor spy 只补充顺序，不代表 Product／原生权威；预期与探针仅留产品树外，不新增永久测试、指纹门禁或平台。

| 执行 | 实际结果与范围 |
| --- | --- |
| 原冻结 95898 | 1 passed／0.75s，原 SHA／路径守卫、exclusive expected create |
| 实际旧输出 64324 | 1 passed／2.15s，普通工作树路径，无 overlay，旧输出逐项一致 |
| 实际三文件选择 96536 | **51 passed／1 failed，840.44s**；fail-fast 后其余案例未执行 |
| 原两模块对照 50289 | 原 SHA／canonical 受限加载，技能目录同案例同断言失败，30.69s；其他组件仍为活树，不冒称原完整基线 |
| 干净原主线对照 64442 | HEAD `8ad6b6098f1c24c8cfb6f4d9d290e99bc74d618d`，普通主线 PYTHONPATH、无覆盖层，同断言失败，16.21s；相同测试文件字节，证明它早于整个 Goal |
| 实际补跑 2304 | 此前未执行的原 dependency Wheel／IO 兼容两文件，**81 passed／42.49s**，普通工作树加载，无覆盖层 |
| 实际类型 55366 | 两显式源 silent mypy 通过；不是默认全依赖图通过 |

未通过项为 `test_external_data_skill_enters_fenced_session_catalog` 第 4008 行：preview 没有 `workspace/skills/local-review`。没有修改断言、加跳过或改 Product 来掩盖它，缺陷根因未在本片修复。上述完整原基线对照只定位这项失败，不推导原基线全部通过。reviewer 写作时业务仍待回收，实施者在此补录终态，不改写为其亲自运行；51／81／一次性观察分别记录，不将被截断选择写成全绿。

两个源的 Ruff／格式／diff 通过；241 个前检查点路径仅两选定源变化，测试／fixture未改，实际验证后没有源改动。A42 默认全依赖 237 错误／8 文件、原生 Windows／断电与完整 Goal 限制保留。实施 owner 接受的是直接复用已有遍历的有界增量，保留原主线失败；不替代整个 Goal、用户重要架构或原生接受。

完整成本 Code／系统−22、Harness0（结构−52／格式+30，data实际+6、dependency−28均计入）；C08 无交集。独立全源核算：Code138,783／累计−7,059，原C087,235／累计−4,536／八千行缺口3,464，系统仍+1,091。before/source、旧结果、各实际终态、三视角报告与计数保存产品树外 direct-record-codec-a55；未提交或发布。


## A56 R3：叶子值校验直接复用

早期 R1 的同名 `_exact_dict` 组合假设被 90960 候选行为回放推翻（1 failed／1.15s）：不同模块实际使用了不同的 Mapping／dict、复制／引用、错误合同。三份较早静态意见不能证明该假设；R1 明确 rejected／never-installed，预期未改。R2 带函数参数的组合原型也未采用。最终 R3 经重新解析实际绑定和完整函数体，以原 records 为规范值 helper owner，没有新增组合解码入口。

R3 frame SHA256 `e6b1aec545cbf53ff269ec24aac4ba9df7b9164049fa1ea0d83c55883d2ee27e`：19 份实际源与候选逐字相同。54 个原定义按完整 AST 及标准 builtins／同一 Mapping／cast 绑定分成 11 组；49 本地定义退出，五份已有规范体复用、六份等价原体最小迁入，净退出 43 重复定义。49 原名均为实际同对象导入别名，原记录类、MRO、字段、构造、from_dict／to_dict、Schema、其他算法及 IO 的 AST 保持。

三个视角重新独立审查候选及实际增量，均无具体阻断：职责确认原 owner 单份算法与原调用消费、无注册表／框架；运行确认原调用深度、检查顺序、Mapping 复制与 dict 原引用、无回调或新增资源；数据确认 bool／整数子类、字符串和错误家族分别保留，以及 alias／旧引用和 schema／wire 不变。F-A56-01（同名不是同合同）由 R3 真绑定分组、原观察、实际业务验证关闭。helper 的真实 module／qualname、traceback 和私有错误调用签名诊断允许变更，旧名称及正常参数合同保留；不将旧私有 globals 热改写或新私有 pickle 路径的旧版本读取作为承诺。

| 执行 | 终态与范围 |
| --- | --- |
| 原额外 helper 冻结 52088 | 1 passed／0.88s；原 19 SHA／路径和 54 函数定义 module／首行守卫，exclusive expected |
| 候选 R3 35436 | 1 passed／2.21s；启动前限定 19 模块覆盖，守候选 SHA 和活树 before SHA，原 helper／记录／alias／pickle 对照 |
| 候选类型 62081 | 19 显式 shadow 源 silent mypy 通过 |
| 实际旧合同 52901 | 1 passed／3.40s；普通工作树、无覆盖，原 1,134 helper 观察及原 756 记录观察、49 alias、54 原签名／旧 pickle |
| 实际原业务 23286 | **217 passed／16.55s**；18 完整原测试文件加一个 settlement 恢复 node，Package 原记录／事务及 C08 记录边界 |
| 实际类型 55881 | 19 显式生产源 silent mypy 通过，无 shadow |
| 全源独立计数 26646 | 634,820→635,779，仍 +959；Code／原 C08 数不变 |

旧 helper 预期 SHA256 `eb4852a4af289c2b4d0e8a17d003460f57ac4fc20231a9f4fcab6d913fee147c`，原记录预期 `a2c94ccc906292b5bda6a13ae8437c2041fdc08fbdacedf671f6e8f98346bd2c`，均未被候选重写。惯性输入观察不代替真实 Product／原生权限；有效记录及事务另列，三种测试不相加为独立能力数。reviewer 写作时有 pending 记录保留，实施者在此补录终态，不改写为其亲跑结果。没有增加永久测试、指纹门禁、模型调用或平台。A42 全依赖 237 错误／8 文件和原生／断电／性能未验证范围继续保留，A55 原主线技能目录失败不重复验证或冒称修复。

完整19源净减 132（records +36／其他 −168），结构 −143／原 before 排版 +11；所有新规范函数、别名和 imports 计入。Coding／原 C08 本片为 0；累计 Code −7,059、C08 −4,536／八千行缺口 3,464，系统仍 +959，完整 Goal 未完成。实际源在相关回归后没有再改；R1 原样存档、R3 before/source、原预期、终态、计数和独立报告保存在产品树外 A56 目录。实施 owner 接受此有界修订，不制造用户对新架构或完整 Goal 的接受，未提交或发布。


## A71 R2：旧安装评审记录直接消费

三位独立 reviewer 分别对实际三份 Coding 源审查，无具体阻断，未互读报告或重跑测试。职责确认直接复用原 Resources/Packages RecordSchema、Core零修改且无新运行owner；运行确认7/8/8/22个标量前缀的getter/kwargs顺序以及原列表捕获、guard、try/cause位置；数据确认原wire/key、optional/v1/v2、canonical/hash和审批政策保持。除Schema/import/keys及八个目标方法外，整模块AST保持，方法签名和装饰器不变。

实际评审frame SHA256为`2c5c50dee5d63c2d5c365febe0aa9cbee017154751fc03325e2aba007a3bbd34`，绑定三源、原组件、固定输入/expected/actors、全源计数及三个独立报告。1,637项旧观察在实际普通worktree复放1 passed（3.51s）；三完整shadow源silent-import类型检查通过，实际逐字相同，不当作全图通过。三位写作时原业务仍pending，该历史不覆写为其亲跑结果；后置真实终态为两完整原文件157 passed（1364.16s），终态SHA256 `ee809ed734c4d5fe11666006b827f1f9eb11b1779ff26abf3439ea41aac965bf`。两个测试源与原Git逐字相同，实际三源与固定预期在测试后均保持；实施owner在原授权内接受本次有界交付。

该静态子集选择仍由作者对旧wire/version负责，不是新增字段自动兼容；getter/循环/临时dict未作性能基准。完整三源净减61，含Builtin+2，结构59/格式2，Harness零新增、原C08无交集。R1嵌套转换候选没有接入；不新增永久测试、协议或gate，也不替代完整Goal验收。终态及实施owner接受另补于[推进记录](../coding-convergence-progress.md#旧安装评审记录直接复用原字段遍历a71-r2)。


## A73：四恢复请求直接复用的三视角代码复核

本轮只改原Resources/Packages记录模块，四个identity dict与四个from_dict字段遍历复用既有Schema，完整净减139行；CoreSchema不扩充，Coding及原C08为0。三位独立reviewer分别核对职责／复用、运行／失败、数据／兼容：实际源逐字等候选、四组10/9/11/13字段的原wire/getter/kwargs/decoder/label保持，原Mapping复制和跨字段/ID/hash等其余模块AST不变，261项守卫及五原测试Git字节相符。三个实际报告无本片剩余阻断，实施owner在原授权内接受这一有界实现。

固定682项旧观察在实际普通路径1 passed（1.11s），四完整相关生命周期业务文件102 passed（42.35s）。初轮19 passed／1 failed及原before记录模块同node失败保留：review skill预期缺失不因本片记录改动出现，但该单源对照不是干净main或完整根因证明。原adversarial文件后续参数未执行，不把补跑四文件或重叠观察合成为原五文件全绿。actual frame的pending历史与后置终态分开，工作件SHA及实际接受见[交付记录](../private-data-convergence-delivery.md#a73四种-package-恢复请求的实际字段遍历复用)。

单完整候选源silent-import窄mypy通过，actual同字节，不宣称默认全依赖检查绿。四显式表固定基类字段与原版本，不自动反射子类或承诺私有helper热替换等价；新调用/循环/临时字典不称零成本或性能提升。全系统仍+515、原C08缺口3,424及完整Goal未完成保持；未新增gate／模型／平台或发布。


## A74：四 Record 共同封装三视角实际复核

三位独立reviewer核对actual==candidate、原Schema不变、261项guard、四测试Git字节及原16wire／六kind／642观察来源，无本片剩余阻断。运行视角独立展开七字段encode并归一静态键集后，完整模块AST与before相等；公开getter、nested动态分派、原预解码／授权／supersession顺序保持，表不被当成完整decoder。职责视角确认同组件既有复用，parent有界设计裁剪与三份实际代码评审合理，不虚构三份新候选设计报告。

实施owner接受本片净减44的实际接入，实际普通对照1 passed（1.61s）、四原完整业务102 passed（32.64s），单完整shadow窄type通过且actual同字节。既有adversarial失败未重跑／修复，native／全仓／性能不扩张；全系统仍+471、原C08缺口3,424，Goal未完成。固定frame与报告／终态见[交付记录](../private-data-convergence-delivery.md#a74恢复记录共同封装的有界接收)。
