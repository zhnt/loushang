# H-COD-KD-005：三视角代码评审

- Authority: descriptive review evidence。
- Design status: accepted within delegated implementation scope。
- Implementation status: actual code reviewed；相关回归与五源窄类型检查完成。
- Owner: 原 Coding 与 Harness Journal 实施 owner；独立 reviewer 分别审查职责／复用、运行／失败、数据／兼容。
- 对象：[专项设计](private-journal-parent-binding.md)及四个原调用者、原 Journal 增量和兼容测试。

## 评审与处理

三位 reviewer 独立核验实际五份生产源码与完整候选逐字相等。四个旧 bind 内的锁、V2、head 初始化与 yield 体逐 AST 保持，其余原 Coding 声明／方法不变；原 RootedFileIO 及既有 helper 不改。共享 scope 直接复用 `_private_parent_matches` 和原 bind／cleanup，没有新增事实权威或通用回调框架。

运行视角确认 open 错误翻译仅 start gate、native approval 只读的 durable 原值、构造失败的父 FD 关闭，以及 bind 退出→cleanup→成功后路径复核→close 的原顺序；失败时后验跳过，cleanup／close 异常覆盖及 context 保持。

数据视角发现 DATA-A45-01：新 probe 使用 Linux flags 和 Linux 固定结果，但未限定平台。已只增加 `sys` import 与 Linux skipif，原生产和固定期望不变，问题关闭。测试其余部分逐字相同；未为平台兼容改生产或扩大支持范围。

最终清单 SHA256 `5b87f2aaf5831f46cf21c58720455ca53d44c366cfdd2764b2a6eb402f50a606`，200 份 source／test／fixture。三份外置报告各自复核实际字节和该测试 delta，无剩余阻断；原报告写作时测试待终态的记录保留，下列终态由实施 owner 收集，不冒称 reviewer 亲自执行。

## 实际验证与限制

- 改源前五份原文件 SHA 与 canonical import 守卫冻结成功，1 passed（2.87s）；固定结果在原树只读复放，4 passed（3.16s）。没有从新实现重写 expected。
- 实际生产最终字节的相关回归 76 passed（160.22s）：含固定观察、原 RootedFileIO／publication、opt-in、receipt、start gate、checkpoint 和真实 Worker Product 事务。
- 测试增加 Linux 标记后，原固定观察再次 4 passed（3.76s）。两组范围重叠，不能相加为 80 种独立能力。
- 256 项是惰性 IO 的参数观察，部分模式重复；锁恒返回 False，stat 恒成功，不证明首次 head、缺失锁或原生 FD 行为。原锁体 AST 与上述实际回归是另外的证据。
- 第一轮 mypy 退出为内部错误；带 traceback 的复验定位到缓存 `mypy/metastore.py` 提交时报 `OperationalError: disk I/O error`。未改产品；改用磁盘上的独立缓存目录并禁用 SQLite 缓存后，五源 `--follow-imports=silent` 检查通过。两次失败和最终成功分别记录，不把成功扩称为宽依赖检查通过；A42 的既有未通过记录继续保留。
- 最终 200 项 live hash、164 份 Python Ruff、六份变化 Python 格式检查及 diff 检查通过；原九项纯静态文档不变量和清单内 16 份 Markdown 的相对路径检查通过。

原始报告、五份 before、候选、freezer／probe、固定结果和实际清单保存在产品树外 A45 目录。实施 owner 的接受仅限既有组件内的本片复用，不替代用户重要架构评审、完整 Goal 或原生 Windows 验收。源码净量为 Coding −97、Harness +32、系统 −65；原 C08 的 8,000 行目标与系统总体净减少仍未满足，未提交或发布。

## R2／A46：原 IO 词法清理与完整回执读取

三视角独立候选复核后，15份生产与两份测试接入活树，最终frame SHA256 `cd363001f4ecd39f5849df2fa4bc90b5e51decaa573c1376dbf81fe817a266a6`，212份source／test／fixture。三份实际报告确认候选逐字一致，无剩余阻断。21处标准with逆展开后与原赋值＋try/finally AST相同，没有IO变量重绑定；RootedFileIO只增加enter／exit，原算法不改。第22处旧scope随完整receipt读取归R1父目录helper，原bind内体、公开签名和存量格式保持。

原Product为冻结dataclass，helper使用的path.parent与原state_root一致；GC检查仍在打开前。Legacy部分后验原本在cleanup之前，原位置保留；生成器跨yield持有、return、Product pin释放与根FD关闭也不变。退出调用原cleanup，不吞BaseException、不消除清理债务、不接管借入根FD、不自动重试未知close。长期字段持有的IO不在本轮替换范围。

验证终态由实施owner收集，独立报告保留其写作时pending状态：

- 修改前15原SHA与canonical导入守卫、原固定256观察复放：1 passed（2.89s）。未重建expected；外置before_probe.py保留来源。
- 实际IO／原固定作用域／真实publication合同：99 passed（8.74s），含新增5项真实FD例。成功、ValueError和CancelledError退出后witness失效但数据保留、根FD继续可用；目录fsync失败的原债务可沿持有目录重试，不触及替换目录，清理错误覆盖取消并保留context。
- 原legacy／V1/V2 stage、commit、retire、rotate／checkpoint／GC／activation业务回归：92 passed（94.14s），运行进程已正常结束。两组范围分别报告，不包装为独立能力数量。
- 15源窄mypy通过，沿磁盘隔离缓存并禁用SQLite；212项live hash、176份Python Ruff、17份变化Python格式与diff检查通过。未扩大到A42尚未通过的宽依赖类型检查。

完整成本Code−87／Harness−5／系统−92；其中10行为格式整理，机械收敛净−82。原A30固定31源交集独立核算发现backup_types属于C08，本片真减3，纠正预审中“C08不变”的概括，其余84行仍计扩围。累计Code−5,860、原C08−4,253（最低线差3,747）、系统仍+1,347。实施owner在原授权内接受本片，不替代整体Goal、用户重要架构或原生平台验收。未提交或远程发布。


## A49：Windows Worker 只读作用域终审

实施 owner 在原 COD-PD-GOAL-001 全 Coding 扩围授权内接受 KD-005 R3 的有界内部实现。职责／复用、运行／失败、数据／兼容三个独立 agent 已检查候选及实际源，当前无剩余具体阻断。原系统环境及重要架构工作件的用户评审边界未变；本片技术接受不等于完整Goal、全部类型或原生Windows验收。

最终实际 code-checkpoint-a49/frame.json SHA256 `aa304e560a2facf9e7e518339b6c68932d78b1cfb0076d583b01765ac0f45ae3`，218源码／测试／fixture路径、179Python；四份生产源与已审候选逐字相同。三份Code只有指定只读方法AST变化；字段／constructor／decode／write／GC／marker及原FileIO算法全部保持。read_snapshot仅提供原bytes或None；Code仍在ACL与原共享锁内解码，原Root／Product准入和写决策保留。没有新manager、记录、存储、协议或平台开放。

四份原SHA及canonical路径守卫先冻结66个旧观察，原freeze 1passed/3.00s；四源候选67passed/6.24s含来源检查，shadow四源窄mypy通过。实际普通worktree PYTHONPATH／无overlay的265passed/6.80s覆盖新66观察、原IO兼容／本地真实FD寿命／原历史语义；实际四源窄mypy通过。265不代表全Product或native平台证明。

数据视角发现新测试Path('/inert')在Windows无drive，不满足真实constructor的absolute前提；该DATA-A49-01保留发现历史并关闭。只将惯性构造路径改成Path.cwd()/inert/name并加说明；spy／断言／固定expected及四份生产源未变，路径不进入trace或native参数。最后仅改动测试范围66passed/4.37s，不与265重复累计。旧265对应6a3f完整frame及test以逆单注释／路径增量事后重建，并校验先前已记录frame SHA；报告明确不是预执行捕获，也不称旧265运行了新label。

原固定fixture字节未改；最终218hash、179Python Ruff、五文件格式、diff和9静态文档不变量通过。新66的ACL／Native／锁和准入均为惯性端口；原本机FD例不是原生Windows ACL／stream／durability证据，原candidate范围不扩大。A42默认依赖扩查237错误／8文件仍未解决或充分归因，窄检查不等于全面绿。

本片Code−84／Harness+40／系统−44，其中15行来自旧空白整理，纯流程结构净−29。原31源交集为空，不能补入C08：累计Code−6,144／C08−4,453（8K最低线差3,547），系统仍+1,404。Goal保持active／incomplete，原条件不降低；未提交或远程发布。三个最终独立报告、旧fixture及各路线来源、独立原基线全源计数均保存在外部code-checkpoint-a49。

## A51：五流追加协调终审

职责／复用、运行／失败、数据／兼容三位独立 reviewer 已核对实际六源与候选逐字相同，当前没有本片剩余阻断。实施 owner 在原全 Coding 扩围授权内接受本次内部去重；原段组件仍在 Coding，不代表公共职责已经归 Harness，不替代用户重要架构工作件或完整 Goal 验收。

最终 `code-checkpoint-a51/frame.json` SHA256 为 `c7f14a2fef954a3ff901e9f2b39531d07f1840535e030443ab7ae72989ac2612`，227 个源码／测试／fixture 路径、185 份 Python。五个调用者仅替换追加尾部，原授权、CAS、容量、V2／checkpoint、返回值和其余方法不变；原段组件的 seal／commit／head／恢复算法不变。两个窄端口保留原编码及错误映射，没有新 backend、状态机或任意阶段回调框架。

原六源及 canonical 路径先冻结五流各十五项尾部观察。首候选探针误选 start-gate 外层 append；只修探针，六原源、提取程序范围／hash 和 75 项旧预期只读复放通过，未重写 expected。候选 76 passed；实际普通 worktree PYTHONPATH、无 overlay 的定向回归 **107 passed（30.55s）**，实际六源窄 mypy 通过。最后只为新测试循环变量增加显式绑定，相关 **3 passed（0.77s）**；生产与预期不变，两组结果不累加，也不声称 107 项执行了后续测试修订字节。

真实 RootedIO 三例验证跨代重开、写后报错与重新编码漂移：数据保留、旧 head 不变，常规读取继续拒绝未提交债务。首轮真实测试错误使用默认 locking，与已有绑定事务冲突；测试改用原调用者已有策略后通过，未削弱产品锁。75 项尾部观察使用惯性端口，不代替公开授权或真实文件证据；本地真实文件也不证明原生 Windows、任意断电或全部 Product 恢复。A42 宽依赖类型检查 237 错误／8 文件仍未解决或充分归因，窄检查不消除此限制。

五调用者合计删除 98 行、原段组件新增 48 行，全部六源净减 **50 行**（结构 −51、格式 +1），Harness 不变。收益不属于原 C08；累计 Coding −6,223、原 C08 −4,482，原八千行最低线仍差 3,518，全部生产源码仍净增 1,325。整体 Goal 保持 active／incomplete，未提交或远程发布。原源、候选、不可变预期、终态结果及三份报告保存在产品树外 A51 目录。

## A53：分段原语实际归属与兼容终审

职责／复用、运行／失败、数据／兼容三位独立 reviewer 核对实际代码、冻结样本、完整成本及终态结果，无剩余具体阻断。实施 owner 在原 whole-Coding 扩围授权内接受本片：Worker 拥有公共分段机制，Code 保留领域政策与薄兼容出口。原环境角色、授权和持久协议不变；不替代用户重要架构工作件、完整 Goal 或平台验收。

最终 `code-checkpoint-a53/frame.json` SHA256 为 `01c76a0f0a1706e45af6b38dcdedff34e46c45e820354e3d074dbd65b40a42c6`，232 路径、189 Python。原 Code 至新 Harness 的整模块去 docstring 后 AST 相等，原实现已退出 Code；18 行 Code 仅为同对象 alias，没有包装函数、第二类型或旧体回退。全部原公开符号及实际 V2 使用的三个私有命名函数可继续导入，Harness 无 Coding 反向依赖。原 Worker 平面日志不等价于既有 segment/head 协议，继续复用原 RootedFile 和 canonical JSON 的接管位置合理。

公开符号／签名、manifest 字节和四种旧对象样本，在未改 Code 的 SHA／canonical 路径守卫下先冻结；实际 fixture 与原冻结逐字相等。原 75 项追加观察的 expected 保持，只将故障注入转到实际 Harness globals。定义模块、traceback 路径随真实 owner 改变；旧引用可通过原路径解析，不承诺旧版本理解新模块路径的 pickle，不把对象样本扩成任意 Python 序列化保证。

首轮实际 80 passed／1 failed 是新增测试漏传原必需的 stream_id；原签名样本早已包含该参数。仅补新测试输入，生产及两份 fixture 未改，初帧及旧测试另存。同组最终 **174 passed（41.83s）**、**140 份显式生产源码联合 silent mypy 通过**；此后无源码／测试改动，不与前 80 项累加。选择是 22 个测试文件，覆盖五流、V1/V2 历史、checkpoint／stage／commit／retire／rotate 及其中的 GC 寿命案例，不冒称完整 Worker／GC 测试套件。原惯性观察、本机 rooted 文件及产品案例分列，不扩大到 native Windows、任意掉电点或全部 Product 权限。A42 默认广依赖 237 错误／8 文件的限制保留。

232 live hash、189 Python Ruff、四份改动 Python 格式及 diff 核对通过。Code −760／Harness +779／系统 +19 的全部成本计入，算法删除为 0，不能重复计 A51 的去重或用迁移量补原 C08。独立全源核算为 Coding 138,859（累计 −6,983），原 C08 7,289（−4,482，最低线仍差 3,518），全系统 636,164（仍 +1,344）。本片 owner 归属已接管，整体 Goal 保持 active／incomplete；未提交或发布。三份报告、原源、固定样本、首轮与最终结果、实际清单及独立计数保存在产品树外 A53 目录。

## COD-RESP-GOAL-002 A30：实际代码终审

本节为后续Goal的有界内部接受，上文历史基线保持。实施owner `/root`已读取三个独立设计视角、三个实际代码视角及运行/数据终态补件；本片职责、运行失败和数据兼容无剩余具体阻断。接受Code薄绑定及原Journal完整读取程序，不等于完整legacy、KD008/KD011图或整个Goal验收。

实际两源frame SHA256 `ca6ec5e9329d6e2df8cb6fb4c35224be24092ad0e7ea8b9352c9c4882f74e90d`；全1909源frame `0bc02f35f16e84d63c154115c2f5bc3aa830dbcc4a8c0b38c7564c770313667d`。两实际源逐字同已审候选，原Code其它定义与Core所有原定义AST不变，原22期望JSON逐SHA不变。原三个POSIX消费者仍共享同一Code helper；没有三份算法收益、第二IO owner或新状态权威。

原57业务为69611/57过/13.97s；24456原FD捕获22过、1故意跳过候选合同节点；49306候选80过/19.89s。最终实际92115在普通worktree、`ACCEPTANCE_ACTUAL=1`、原managed wrapper/not-live/skip-host-runtime及指定磁盘runtime、沙箱外取得**80过/53.23s、零skip/error/fail、exit0**。其中57原业务+22真实FD旧观察+1真实callee/共享绑定合同，重叠批不累加。70318两实际显式源silent/no-incremental类型、67896 Ruff/format和原生成检查均exit0；源在运行后未改。报告原pending由实施owner依据真实终态关闭，不冒称reviewer自行执行测试。

首19987测试路径填写错误导致0tests/exit4，记录与XML保留；通过rg修正选择，未改原测试/断言。新观察虽使用真实Linux FD，但容量边界采用小限额、close错误在真实关闭后注入，不证明16MiB压力、未知close恢复、所有并发或native Windows。无新CI门禁、付费模型、网络或矩阵。本片Code−83/Journal+67/系统−16；当前Code122753/系统638381，整体系统仍较起点增3587，完整Goal保持active。源码、原期望、XML、三视角报告和分支切点保存在产品树外`p4-legacy-acceptance-reader`。
