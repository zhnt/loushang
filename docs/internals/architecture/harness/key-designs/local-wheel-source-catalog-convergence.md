# COD-RESP-A22 R2：受控 Wheel Source 目录职责归一

- Authority: accepted implementation design。
- Design status: accepted（R2内部接缝）；三独立视角关闭Code IO hook发现后，实施owner `/root`于2026-11-08在原Goal内接受；原完整基线与实际交付另行收束。
- Implementation status: implemented（有界）；四实际源已接通，147项实际回归通过，三视角实码核查无新增具体阻断；终态补件与旧失败独立保存。完整Goal仍partial。
- Owner: 原Package Product namespace/来源授权、Journal持久事实与Resources受控文件操作各原owner；Coding保准入政策与兼容外观。
- 需求：[Coding职责Goal](../coding-responsibility-convergence-goal.md) P1/P4；不改变P2/KD-008待用户的职责方向。
- 方法：archmethod本地干净master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`，未核上游。

## 1. 业务场景与已存在的重复

本片按一次完整Source操作处理：显式选择的本地Wheel经原Product epoch核验，读取稳定来源字节，检查同名/同版本绑定，先发布受控副本，再追加原来源授权记录；后续只读查询、重开与策略扩展沿同一原namespace执行。目录只固定来源事实，不授予Plugin安装、Worker启动或依赖执行权限。

起点`package_external_data_wheel.py`427行、dependency509行、worker827行，合计1,763。三个POSIX目录有同体构造/记录查询/epoch核对/链检查；data与Worker还重复稳定来源读取、受控发布和Plugin策略扩展。既有[controlled Source IO](../../../../../src/loushang/harness/resources/packages/plugin_lifecycle/_controlled_source_io.py)已承接底层发布、摘要复核及短写/同步/清理，本片直接调用，不能重新搬一份IO。原Journal继续锁、codec、append/load与耐久策略。

现有[PackageProductLocalWheelInventory](../../../../../src/loushang/harness/package_product/product_local_wheel_inventory.py)读取已安装/desired/committed状态，不能代替本片的外部来源记录；现有[LocalWheelPolicy](../../../../../src/loushang/harness/resources/packages/product_local_wheel_policy.py)验证已绑定Source，不是目录提交器。它们继续原权威，本片只收敛之前散落Code的共同协作程序。

## 2. 原组件内部接缝

机制位于`harness/package_product/_local_source_catalog.py`，不放Harness根目录，不进公共facade。三个原公开Code目录对象仍各自是一份真实实例、一个原path/namespace与原可变字段；内部基类不再创建一份“catalog manager”，不新增registry、日志、锁或进程。Coding保原真实类/FQN与明确构造、capture、records/read_records签名。

| 职责 | 复用与保留 |
| --- | --- |
| POSIX目录的构造、read-only查询、epoch与原链核验 | 同一私有`_PosixSourceCatalog`，直接用原Journal及原Product epoch端口 |
| data/Worker稳定来源捕获、受控发布、Plugin binding策略扩展 | 私有`_PluginWheelSourceCatalog`特化，继续调用原controlled Source IO；不是通用步骤引擎 |
| 原具体记录/JSON/wire/hash、Code错误类 | 原Code dataclass、codec及其构造不迁；Core只用只读Protocol描述用到的字段，不另造DTO或改module伪装 |
| 产品id、错误显示label、原捕获条件 | Code原值与条件；静态文本只投影原错误，不用于配置新运行权限 |
| codec、限额、具体新记录、判重键 | Code窄纯值hook返回原codec/常量/record/Version键；在原位置调用，不给Core Code IO回调或大Product/context |
| dependency Wheel元数据、标准化版本、子目录 | 原Code路径保持；不强套Plugin id或Worker admission，不把Version判重改成字符串判重 |
| Windows Worker目录 | A22当时完整保留并作AST守卫；后续A26按§10归原Package Product，原行为/数据/平台保持，不把POSIX后端用于Windows |

这是原Package Product内既有Source事实的协作程序归位：记录仍由同一Code外观所绑定的原Journal写入，物理文件仍由原Resources操作，原Product掌握epoch/currentness。没有新增环境参与者或事实权威。若评审发现实际超出该内部边界，应按用户重要工作件约定处理，不能把Goal或本候选自动视作新方向接受。

## 3. 接口、顺序及不可合并差异

`_PosixSourceCatalog[RecordT]`保原`__init__`字段写入、`records/read_records`与`_assert_epoch/_load_unlocked`。具体Code保public typed薄方法，避免继承泛型TypeVar改变原公开返回注解。私有`_record_codec()`在原参数求值点取原`_CODEC`；`_record_key(record)`只给判重键。Core的`_catalog_present()`固定承接原exists与strict lstat两种观察，CodeWorker仅声明`_catalog_regular_single_link=True`；它不再借Code hook做物理IO，也不获得恢复/修复权。该私有常量保持原差异，不作为公开输入开关。

Plugin特化的`_capture_validated(source, *, epoch_runtime, admission=None)`只在Code原read-only、epoch和来源/Worker准入条件检查之后调用。它直接执行原来源捕获与锁内绑定程序；Code `_new_record(source,digest,revision,*,admission)`只构造原值，`_admission_conflicts`只比较原Worker准入，`_max_source_bytes`仍读原模块常量，不提前冻结现有调用期限额。没有任意步骤列表、运行期策略registry或持久缓存。

| 时点 | 原合同与保留差异 |
| --- | --- |
| 只读 | 原shared lock、create_lock=False、raise-tail；不创建/修复目录记录。Worker原catch多TypeError，data/dependency不补此catch |
| 进入capture | 各自原read-only错误先于epoch；Worker再核精确admission/native platform和Path类型，data/dependency不加新Path类型拒绝 |
| 稳定读取 | 原open_regular_no_follow→fdopen→前fstat/预算→一次有界read→后fstat→退出→lstat及原file_identity比较；OSError/cause保持，不能换要求600/UID的controlled读来加严输入文件 |
| 锁内 | 再核epoch→读原链→同名冲突/重复→上限→原record构造→原副本发布/验证→原JSONL append→原assert_current。重复仍先验证受控副本，再返回旧record |
| 目录记录观察 | data/dependency沿原Path.exists；Worker仍lstat且拒非regular或nlink非1。不将强规则扩给另两类，也不弱化Worker |
| 判重与上限 | data/Worker按原(plugin_id,version字符串)和125，仅属于Plugin特化这两个原调用者的合同；dependency按(project_name,Version)和128，其capture/元数据及重复版本分支保原Code主体，不外推为所有Source额度 |
| 部分失败 | 副本发布成功、验证/append/currentness失败时保原痕迹与异常；不跨store回滚、删除共享字节或盲重试，也不把查到文件推成记录已提交 |
| 策略扩展 | data/Worker保原Product/source root/scope、Plugin id碰撞与逐项受控验证后合并排序；dependency独立保其dependencies与版本语义 |

公开记录声明/fields/frozen/ctor/FQN、codec/to_dict/from_dict及数据名称/摘要/排序不改。纯getter/构造及额外私有函数帧不承诺任意副作用属性或完整反射等价。公共目录原签名与解析hints、原__all__保留；MRO、继承方法定义位置、私有全局故障注入位置改变，需明示，不通过测试另留一套旧IO。所有持久格式与路径保持，无数据迁移/双写。

## 4. 实物与全成本

起点九源/测试、A21完整1,884生产manifest、四外置候选及旧观察在产品树外`p0-worker/a22-wheel-source-catalog/`。45748只从实际旧Code独占捕获三类各八组观察（24组+1完整性节点，25 passed/11.74s）；含capture/reopen/重复、发布后冲突、read-only、坏epoch/输入类型、TypeError差异、hardlink和发布验证失败。临时根与派生recordId作明确规范化，记录/codec主体另以旧AST守卫；该端口级证据不是实际Product授权或原生Worker证明。

18865明确四模块overlay下，原75个受控IO反例、上述25节点和四公开面/Core拒Code导入检查合计104 passed/11.32s。71657四显式候选源mypy通过（silent imports，非全图）；此前51970发现私有exception tuple注解过窄、presence hook从旧return空tuple转换不当，已仅修候选为宽异常类型声明及False；没有Product源变化或弱化原运行规则。候选静态/行为证明不能代替实际安装验收。

| 完整生产成本 | 原实际 | 候选 | 变化 |
| --- | ---: | ---: | ---: |
| Code data | 427 | 242 | −185 |
| Code dependency | 509 | 445 | −64 |
| Code worker（含完整Windows） | 827 | 653 | −174 |
| Package Product内部机制/类型/导入 | 0 | 336 | +336 |
| **合计** | **1,763** | **1,676** | **Code−423，系统−87** |

上表含全部公开薄方法、纯hook、泛型/Protocol、导入和格式；原底层IO不另复制。只有实际接通、原重型体退出并复核全量差额后才能计收益；安装时若Product Ruff造成导入分组差额，另列真实数量，不覆盖冻结候选。Coding≤15K及系统低于634794、完整P1–P4目标保持。

R1冻结设计c33c7d3bb79564916c1e2cd7676580d17cb6fd782e90cba54710e5b4c321a753及四源保留树外。职责视角指出原CodeWorker presence hook真实执行lstat，与“无Code IO hook”声明不符；R2将该观察归Core，Code仅保原固定profile。R1 Code−413/系统−86与104候选通过均为历史对象，不反称它们已经验证R2；R2两变化源、成本及复验独立记录，其它两个候选字节保持。

## 5. 验证、接受与回退

原三文件完整基线88560与实际替代回归分别保留，终态及旧失败处置见§7。所有消费者仍按not-live/skip-host-runtime，不新增矩阵或gate。实际跑受影响目录/来源/依赖消费者和真实Product路径，必要失败反例优先用原固定fixture。公开面、旧dataclass/codec及Windows整个类AST、Core无Code导入、四源实际路径和完整成本一并检查，再做三视角实际代码评审。

设计三视角先核职责与真实复用、运行/失败、数据/兼容，关闭实质问题才安装。回退是三个Code薄外观+同一Core机制整体及必要原清单同步，不保Code fallback，不改变路径或要求用户重建库。未发现必须新增/扩大PR gate的需要；若旧清单漂移，只可按确切事实独立复核，不以整个目录豁免造绿。

## 6. R2设计接受与验证终态范围

R1原对象/四源与三份原报告保留；职责发现O-A22-01是真实的Code IO覆写，与纯值hook声明不符。R2只把该目录观察移至Core固定profile，CodeWorker删真实lstat方法，另两候选逐字同R1。冻结R2设计c975979fac695da61999d5196117f7f693a4e4bdb39f8bace2d1a7e9976320f9、frame8b29cbef20950e92a9b4f14133262f05a2f2292b0f3de967048930649f30dfe7，经三个原视角独立窄核，无未关闭职责/运行/数据阻断；125的Plugin特化范围也已明示。实施owner仅接受此内部实现接缝，不接受其它待审方向或完整Goal。

63759 R2明确overlay复验104 passed/17.73s，原旧期望未重录；72361四显式候选源mypy通过（silent imports），Product配置Ruff检查通过。原报告中的pending由本终态回收，不改写R1对象或把R1通过计给R2；候选仍不是实际生产实现。

接入前历史检查点：原88560完整基线保持同一运行handle，持续有进度但已输出一项F，尚未返回明细/终态；不预测其归因，不重启或覆盖输出，不在它回收前替换生产源。实际仍A21的Coding127,564/系统637,054，A22收益为0。回收后须先定位原失败，再按接受接缝接入、复核真实成本与原消费者，并做三视角代码评审。当前设计源码/证据是可复用起点，不把等待写成整个Goal受阻或完成。

## 7. 原基线处置与实际接入

上一节末为接入前检查点的历史状态。88560已正常回收为exit1：179 passed/1 failed、1318.62s；没有重复启动或中止。唯一失败为`test_external_data_skill_enters_fenced_session_catalog`，在替换任何A22产品源码之前，预览缺少fixture的local-review skill。原XML与失败位置保留，不冒称全绿。

核查原loader及旧源纯loader探针43109（1 passed/0.93s）确认：本机RunLease测试目录位于`/home/dev/lsspace`之下，legacy资源模式按最近context文件选择项目资源根，祖先AGENTS.md使原fixture的resource root落在祖先；临时workspace增加空AGENTS.md后，resource root准确落在该workspace。它不屏蔽所有祖先context descriptors，也不改变产品的legacy选择规则。职责相关的数据/运行两独立窄核同意只在原失败test的mkdir后增加这一Expr；删它后整测试AST恢复原字节语义，没有新断言、timeout、selector或CI条件。原失败节点必须实际复验，纯loader诊断不能代替它。

回收原基线并记录处置后，四R2源按指纹安装。Core逐字等336行候选；三Code仅Product Ruff导入重排，同一alias绑定集合与非import AST保持，实际data241/dependency445/worker652。本片Code−425、Core+336、系统−89；相较候选多出的两行减少来自正常导入分组，不计算法收益。全量1,885源中三旧修改加一新，另1,881源逐字等A21；实际Coding127,139/系统636,965。

47478四实际源silent-import mypy和11831生成依赖新鲜度检查已exit0，实际Ruff通过。59933实际回归针对原75个IO反例、24组旧观察/完整性节点、公开面/冷导入、data目录及真实Product准入、dependency整文件、原失败节点与两个现有cross-runtime场景，并复用C50/C51/C54架构检查。原43项事务阶段变体与其它未修改的管理命令不重复展开；这是原检查选择，不增加门禁或删原测试。实际结果及代码评审收尾后才能接受本片实现，完整Goal与15K/系统净减条件不变。

## 8. 实际终态与有界接受

59933实际无overlay回归已exit0：147 passed/186.67s，XML为147 cases/0failure/0error/0skip。原failed skill节点27.317s明确通过；它只关闭本地fixture资源根问题，原179/1基线XML仍保留，不反称原基线全绿，也不累加旧/候选/实际重叠节点。四实际源silent-import mypy、生成新鲜度、Ruff/format与diff检查通过，非全图类型、原生平台或性能证明。

三独立实际代码视角分别核职责/复用、运行/失败、数据/兼容，没有本片未关闭具体静态阻断。职责原报告的运行pending由此真实终态关闭；运行和数据原报告及另立终态补件均保留，不覆盖为首轮全绿。实际frame逐一核1,885源摘要不变，唯一fixture表达式的摘要及旧AST守卫也保持。实施owner `/root`接受本片原组件内部接缝；不代表新环境方向、KD-008/P2或整个Goal接受。

最终Coding127,139、系统636,965；累计Coding减少10,616，但系统仍增2,171。15K、系统严格净减及完整P1–P4均未达；dependency具体操作、原Windows路径和其它职责簇仍须按各原owner继续归位。实际源码/fixture、原期望与XML、设计/三视角原报告及终态另存树外归档，不新增gate或远程发布。

## 9. A25：内置 Product Source 的发布与精确核验

- Authority: accepted internal refinement；沿本设计的原Resources/Package Product关系，不新增重要环境参与者或事实权威。
- Design status: accepted；2026-11-08三独立视角无具体阻断后，实施owner `/root`接受§9有限内部合同；冻结设计与接受记录在树外保存，不预支完整Goal。
- Implementation status: implemented（有界）；两实际源已接入，65过/1原生Windows skip，三独立实码视角无具体阻断，实施owner接受；不代表完整Goal。

### 9.1 场景、复用与职责

已安装的Coding base/Capability内容仍由Coding按固定白名单构造确定性Wheel，原产品policy绑定仍留Coding。本片只收敛`package_builtin_wheel.py`四个私有Windows/POSIX发布/检查操作；Windows外部Worker已有调用沿原同名私有入口消费，整个目录类与准入政策不改。接收处为原Resources `packages/plugin_lifecycle/_exact_product_source.py`，不是新Source service、Package manager、存储或Harness根目录工具。

`ExactProductSourceFiles`只有固定Product显示文本与动态预算getter，没有FD、root、ledger、缓存或生命周期状态。Coding固定绑定`Coding`及原`_MAX_WHEEL_BYTES`读取；它不是可注入IO hook。四个原私有名字绑定到同一对象的四个方法，原公开函数/类/FQN/构造/字段、Wheel内容与policy保留。私有函数变bound method，其定义模块、qualname与函数反射不承诺等价；正常调用签名仍相同，不伪造元数据。实例可以独立存在，不建立全局registry或跨Session锁。

既有Resources `publish_controlled_source`使用staging→link和清理，`read_controlled_source`使用euid、稳定读取前后身份和摘要。两者不能替代此处直接最终文件发布及已知字节比较，否则改变失败残留、接受范围和错误顺序。Windows receipt IO也有不同的暂存/ADS/ACL合同，不能整套套入。这里只直接复用原Journal `write_all`与原Windows pinned authority、private ACL、regular-file open和flush原语；重复的POSIX根准入/成员比较与Windows输入条件在原owner内部各归一份。

### 9.2 具体运行与失败合同

| 时点 | 必须保持 |
| --- | --- |
| POSIX输入 | 原平台、Path、绝对路径、`..`、原生flags检查先于预算；预算在原调用位置读取，不在装配时冻结。UID仍getuid，不改euid，不增加祖先目录或其它权限要求 |
| POSIX根 | 原open flags、fstat类型/077/UID顺序；检查失败仍close，close错误覆盖原错。普通函数try/except/finally，不用generator scope转换StopIteration |
| 已存在成员 | 原REG/nlink/UID/权限/size短路顺序及一次`os.read(len(body)+1)`精确比较；不变成read_all、摘要近似、自动修复或更严的元数据检查 |
| POSIX新成员 | 原最终文件O_EXCL/600→fchmod→完整短写→file fsync→close→directory fsync→root close。不引入staging/rename/rollback；失败可留下部分文件，后续不能当成已提交事实 |
| Windows | 原平台和supports检查先后、root/ACL/native open；存在文件不覆盖，新文件write/flush/close/dir flush后原visible检查。退出第一root/ACL作用域后，仍重新打开独立inspect作用域验证，不合并两次open |
| IO故障 | 原异常对象及清理覆盖顺序保留；write_all只在非正写入时构造原错误消息，空body不调用write。无自动重试、后台Task或取消吞没 |
| 证据 | 返回同一路径、已知body的SHA256与长度，不宣称提交日志/持久事务/断电耐久或Source授权；只读检查不建文件 |

### 9.3 全成本、验证与接受范围

原Code676行，两源候选Code461/Core220行；**Coding−215，系统+5**，包含配置、别名、类型、导入、注释与格式。此片是共同物理操作归原owner，不把所有215行算作重复消除或净删；完整Goal的15K及系统严格净减要求不变。候选先按正常Ruff完整格式计量，不以压缩声明追行数。所有其它生产源、原测试与固定fixture保持。

树外`p1-builtin-source-files`冻结11原源/测试、A24全量frame及原四函数。原两个测试文件迁前6过/1原生Windows skip，未证明Windows native。在未改源时，44组真实POSIX文件/声明Windows native端口替身观察独占写旧JSON，另1项公开面/其它定义AST检查，45过；候选对同旧期望45过。Windows替身只证明列出的调用/失败/残留顺序，不证明ACL、native路径、原生Windows运行或全平台行为。路径与临时FD标签有明确规范化，原错误类型/文本/对象身份及文件字节权限保持比较。

接入前需完成职责/复用、运行/失败、数据/兼容三个独立审查；尤其核私有别名是否影响已支持消费者、接收层是否回借Coding IO、四路径完整生命周期和系统新增成本。接入后用原managed wrapper、原not-live/skip-host-runtime跑原两个文件与固定对照，保留native skip；显式类型检查、原生成新鲜度与两源静态检查，再做实际代码三视角。回退为Code原文件与单Core模块一起回退，不保两套IO/fallback，无格式迁移或要求重建用户数据。不新增测试路由、平台或CI门禁。

### 9.4 设计接受、实际接入与终态

三个独立设计报告无本片职责、运行、数据阻断；均确认原Resources内部细化、无新重要环境角色。实施owner `/root`对冻结设计与两候选作有界接受，记录`design-acceptance.json`；KD008/KD011重要图仍独立待用户，本片不接入其候选。运行/数据审查指出首公开面节点实际读活树旧Code的证据缺口，外部probe已改核候选Code AST与Core bound签名；末候选57过仍未冒称候选Code别名实际加载。

原44 JSON保持，又用原冻结程序排他捕获raw StopIteration/CancelledError、close最终异常对象及Windows重新inspect前预算改变12项（51001：12过/45 deselected）；76631末候选同56观察+1表面节点57过1.75s。原源SHA、旧JSON与首XML保持，不覆盖成初次全绿或累计重复节点。

两接受候选按SHA接入。41300经原managed wrapper及原not-live/skip-host-runtime、指定disk runtime实际取得**65 passed/1原生Windows skipped、7.86s、exit0**：原两个业务文件7节点、56固定观察+1表面节点、另2实际Code bound alias/typing hints/Worker符号绑定与冷Core拒Product导入检查。它关闭真实Code绑定证据缺口；native skip保留，不冒称原生Windows、任意私有反射、完整故障空间或全仓通过。

接入Code首lint报告一处import空行分组；正常Product Ruff仅去此空行，整模块AST连import完全等已执行候选，Core逐字同。最终Code**460**/Core**220**，本片**Coding−216、系统+4**（较候选−215/+5差1空行），不能当系统净删；运行字节与此末空白差异分别保留，不声称另一次完整重跑。全量1907源：原1906中仅Code改变、另1905逐SHA同A24，新增唯一Core。当前Coding**123579**、系统**638358**；累计Coding减14176、系统仍比634794起点增3564，15K与净减目标保持。

42497两显式实际源silent-import/no-incremental mypy成功；90948原生成新鲜度exit0，最终两源Ruff/format通过。不是全图类型、原生权限/断电或性能证明；原Catalog十项、Session两项与KD011原unsafe场景欠账不据此销账。实际代码三视角结论收束后另记录，不让设计通过替代代码接受。无测试/固定fixture修改、无新增gate或平台，无远程发布。

三实际代码视角分别核1907实物指纹、56旧观察、真实Code/Worker绑定和原公开面，无本片剩余职责/运行/兼容阻断。实施owner `/root`接受本片实际两源及所列验证范围，记录`code-acceptance.json`；不销账其它失败，不改变原生Windows未知或KD008/KD011重要图待审。

## 10. A26候选：Windows Worker Source 的完整目录程序

- Authority: accepted internal refinement；2026-11-08实施owner `/root`按三视角R2合同及真实代码终态有界接受，不据A22/A25预支。
- Design status: accepted R2；三视角完成旧行为/候选补核后，实施owner记录`design-acceptance.json`；不是其它图或整个Goal接受。
- Implementation status: implemented（有界）；两实际源逐字等R2，117过/1原native skip，三独立代码终态无具体阻断；全Goal仍partial。

### 10.1 已有能力与选择

前轮A22/A23已经共同承接三个POSIX Source目录，不能重复计其收益。原Windows Worker目录仍有独立的捕获、126位置只读扫描、精确重放/冲突和策略扩展程序；它用不可变native receipt，不能继承POSIX append/lock/read-only文件模型。A25已经接管精确发布，Windows receipt物理IO此前也已归Resources；本片直接复用同一已配置对象，不重建ACL、native handle、receipt或Source文件引擎。

原Code `CodingWindowsExternalWorkerWheelCatalog`保真实类/FQN、明确构造、capture/records/verify_record/extend_policy公开签名、准入/文件名/平台要求、具体Record/codec和Coding政策。完整目录协调归原Package Product私有`_WindowsPluginSourceCatalog`；它与POSIX目录共享稳定来源读取和Plugin policy合并，但不共享持久化后端。原epoch/Resources/Journal仍各自权威，没有新进程、队列、索引、服务或环境角色；三个视角须核这是否确为已接受关系内部细化，不能用新类名掩盖新重要关系。

### 10.2 具体接口与原合同

| 接缝 | 候选及边界 |
| --- | --- |
| 单份稳定Source读取 | `_StableWheelSource._read_source`直接复用原no-follow→fdopen→前stat/预算→一次有界read→后stat→退出→lstat→原identity/digest。保OSError与dependency额外ValueError区别，校验名仍在原try中；Windows不继承POSIX Journal方法 |
| Plugin策略 | 同一私有policy合并体保product/root/scope核对、记录顺序、碰撞、逐项controlled校验与排序。Windows在原return前多一次epoch核验；POSIX对应私有hook纯pass，不新增IO/授权 |
| 物理IO | 直接用原`WindowsPrivateReceiptIO`和A25 `ExactProductSourceFiles`实例，Code只绑定已有配置对象；不是Code原始IO回调。原rename lambda的故障注入和native owner不变 |
| 原值与预算 | Code保record类型、纯`_new_record`、两个动态预算getter、原诊断标签及既有write默认4MiB。扫描read上限16KiB与write原4MiB不同，不把二者强行统一；A25发布的预算仍取Builtin模块的动态常量 |
| 构造/输入 | 原typed Windows epoch、平台、两root、store/switch/namespace检查与assert顺序保持；capture先原epoch，再原admission/nativePlatform/Path/Wheel标签检查；不扩大平台或默认选Worker |
| 读目录 | 仍扫描1..126，位置126只检测溢出，拒gap/非canonical/foreign namespace/重复name或(plugin,version)。保allow_pending_stage两种调用和原异常/cause，读不创建/修复 |
| 新捕获 | 原字节读取→读目录→冲突/125上限→原Code Record构造→canonical预算→精确发布→epoch→receipt write→epoch→verify。没有跨store事务、锁或自动回滚 |
| receipt写冲突 | 只捕原receipt error，原重新扫描后相同winner才精确verify并返回；不同winner仍按原cause冲突。不能仅凭Source文件存在认定记录已提交 |
| 校验 | 原isinstance(record, CodeRecord)及目录成员判断后核controlled字节/epoch。原ACL、双stat、single read、可见根及file identity/digest顺序保持，不改read_all或新增更严属性/权限 |

公开Record所有自有字段/构造/反序列化/摘要与旧wire保原AST，不采用字段继承/伪造module。目录内部方法MRO、定义位置与私有故障注入位置会变化；只承诺原公开调用和数据，不承诺任意私有热替换/函数pickle。原公开方法保显式Code薄声明，不删除支持换行数。

### 10.3 成本、验证与接受

原Code640/Core455，两候选Code436/Core737；完整成本**Code−204、接收+282、系统+78**，所有新增Protocol、mixin、纯配置和薄方法计入。这是R1职责候选，尚未证明可以据此实施；评审应特别指出是否有可以复用的更窄原能力或不必要层次，不能把Code下降当系统净删。原四根系统严格净减与15K目标保持。

11源/测试、1907源SHA和两候选保树外`p1-windows-source-catalog`。原66132业务基线75过/1原Windows skip、6.65s；85184 shadow-file两显式候选源silent-import类型通过，候选Ruff/format已按项目配置整理。它们不是候选行为或实际安装通过。候选及类型证明不代替先固定旧运行观察、原捕获/回执/异常/cause/残留对照与真实公开面/MRO/调用路径核查。

接受前要完成上述旧程序观察及候选对照；接入后须由实际Code入口重跑原相关节点，保持原not-live/skip-host-runtime/Windows标记及旧fixture，完成类型/依赖事实和代码三视角。Windows native本机不能由端口替身推出；不去标记、不新增矩阵/gate/付费调用。原目录对象/数据与接收模块一起可回退，不留Code fallback或第二事实路径。

### 10.4 R2：命名收窄及旧程序差分

三个R1独立视角确认原Package Product/Resources内部细化，无新重要环境角色或静态职责/运行/兼容阻断；但原75基线主要是POSIX受控IO，不是Windows目录行为。原66132实际是完整兼容文件75节点，加Windows文件的一个原native节点skip，不能称Windows全文件通过。

采纳职责建议，将两个新私有符号`_WindowsPluginSourceCatalog`/`_WindowsPluginRecord`收窄为`_WindowsWorkerSourceCatalog`/`_WindowsWorkerRecord`。R1两源原样保留，R2明确重命名正规化后整模块AST相等，没有改执行体、公开Code类/字段、预算或IO对象；Code436/Core737及系统+78保持。69956两显式R2 shadow源silent-import类型通过。

31039从冻结原class与未变Code DTO/helper绑定排他捕获25观察，48243真实两模块overlay下，对同25及原75受控IO、实际data capture和完整dependency文件共107过37.00s。27717另3项候选Code实际路径/原公开签名与resolved hints、所有其它Code定义/DTO/公开导出AST、三个POSIX消费者共享读取的展开AST及冷Core拒Product依赖检查通过1.61s。它们不是独立旧安装或原生Windows行为；Windows native/receipt/ACL是声明端口替身，来源及受控字节用真实文件。

另补原源具体类型首拒、Source/receipt取消和receipt已写后epoch失败4观察（4647：4过），与损坏JSON/类型2观察（67979：2过/1探针失败）。非法UTF-8原操作已正确归类为catalog错误，但探针保存残留时自行decode失败；47156 R2对应34过/同1探针失败。只将这一未捕获输入改存十六进制，原31份JSON未改，58350从原源排他补捕获该1项通过。10638候选对应1项通过，未重录候选期望、不改Product逻辑、不把首轮报告覆盖成全绿。R2的35节点证据是34原通过+1修探针后窄通过，不冒称最终字节曾一次完整跑35。

32原观察覆盖125/126、gap/foreign/canonical/duplicate、精确winner/异winner及cause、read/write两上限、首拒、政策排序/碰撞、部分失败与取消；正常fresh/repeat/same winner/policy确实成功，根另核结果类别，避免“全部意外错误也录成绿”。实际绑定检查同时确认新Code使用原Receipt及A25对象，不是新复制品；尚待接入及代码三视角，不能将候选证据当生产收益。

### 10.5 实际接入、终态与有界接受

实施owner `/root`综合三个R2具体合同评审后接受原owner内部接缝，记录冻结设计/候选SHA。两源按SHA接入、未作末格式更改；Code436/Core737与已审R2逐字相同。没有新生产文件，1907全源中仅本片两旧源改变、另1905源逐SHA同A25；原11输入及额外data/dependency测试、IO fixture守卫保持。

31882用原managed wrapper、原not-live/skip-host-runtime及指定磁盘runtime，无overlay实际取得**117 passed/1原Windows native skipped，100.67s，exit0**。118节点组成是32固定观察、3真实Code/资源对象/公开面/共享AST/冷导入检查、原POSIX IO75、data capture1、dependency6及原Win节点skip1；原baseline76节点精确包含，不能与候选批累计或称Windows全文件运行。32观察包括坏UTF8的实际组本次全过，但首候选34过/1探针失败与窄修历史仍保留，不改写首轮。Windows epoch/native/ACL/receipt仍有声明替身，不证明真实Product权限、原生Windows、所有故障交错或断电。

2678两显式实际源silent-import/no-incremental类型exit0；97465原生成新鲜度exit0，测试前两源Ruff/format已过。没有使用passing局部结果外推整个依赖图；原Source fdopen失败的raw descriptor边界与其它旧失败不在此销账。

三个实际代码视角及各自终态补件核两实际字节、1907源、32旧JSON、真实绑定与XML，无剩余本片职责/运行/兼容阻断；实施owner `/root`记录`code-acceptance.json`有界接受。Code本片**−204**、Core**+282**、系统**+78**；全Code**123375**、系统**638436**，累计Code减14380，系统仍较634794起点增3642。原15K/系统净减与完整P1–P4不变；KD008/KD011图待用户不因自动续轮接受，无远程发布或新增gate。

## 11. A34：Legacy Source 目录的完整操作归位

- Authority: accepted internal implementation design；实施 owner `/root`依据三个独立设计视角接受继续有限候选验证。
- Design status: accepted（原 Source/Resources 关系内的接缝）；不接受 A33 的 Product 历史职责图或 KD008/KD011。
- Implementation status: implemented（有界）；四实际源逐字等已审候选，164项实际验证通过，三视角实际代码与终态复核完成。

### 11.1 场景、复用与保留政策

旧本地 skill/prompt/theme 已获原 operator acceptance，经过受控 Wheel 发布、精确绑定追加、严格重开和原策略扩充，才成为同一 namespace 的来源依据。原 `CodingLegacyLocalBindingCatalog` 仍承担完整目录操作及双描述符校验；其余 Source 目录已沿本设计使用 Package Product、Journal 和 Resources。新增固定私有 Legacy 特化归原 Package Product，而不新增 manager、registry、存储或授权方式。

Coding 保留原公开目录类与明确构造、六个公开类型化薄入口、完整 record/schema/wire/hash、错误类、产品限额及文件名政策，以及原 `_require_accepted_binding`。该方法调用原 acceptance reader，是有副作用可能的领域授权查询，不是纯 getter；不能缓存、前移或借它回调 Coding 做目录 IO。原九实例字段保持，接收机制在同一个对象上工作。

原 Package Product `_local_source_catalog` 抽出既有 POSIX `records/read_records` 两个完整作用域供原调用者与 Legacy 使用；Legacy 的外层错误集合为空，保留其原先不包装 lock 异常的行为。固定 Legacy load 仍使用默认修尾、strict no-create、重复 JSON 键检查及 revision/plugin/namespace/policy 检查，不套普通 Source 的 filename 或 plugin/version 唯一规则。追加保先实际文件验证、锁内 load、精确重放比较、对旧或新记录作原 acceptance 查询，再仅对新记录 append。策略扩充保逐项 acceptance、累计碰撞、物理核验和原排序。

Resources 既有 controlled Source IO 接管完整私有 root/member 验证；其 `file_identity` 显式选择旧 Legacy 的八字段含 nlink，缺省七字段及原调用者不加严。既有 `consume_file` 的限额允许原整数或窄零参 getter；整数及 callable-int 子类仍按原数值比较，原 quota 优先级不变。Legacy 在原检查点读动态限额，仍以 64 KiB 读到 EOF；先完成后验 metadata 与可见路径检查，再摘要，不提前 hash。BytesIO 是局部缓冲，不承诺节省内存或提高性能。

发布仍使用原 fenced epoch、原 controlled publication、独立重开核验及原 staging 清理。部分发布或未知 append 不自动补偿，close/lock 退出异常不被新层吞掉。构造与公开数据保兼容；私有方法定义/global、MRO 与故障注入位置会变化，不承诺任意私有热替换或 pickle 布局兼容。

### 11.2 全成本与验证界限

四候选：Coding 675→391（−284）、原 Package Product 737→1063（+326）、原 Resources controlled IO 98→177（+79）、原 consumption 111→111。全部类型与兼容成本计入，系统 **+121**，是完整职责归位而非系统净删。整个 Goal 的 15K 与系统净减少验收不变。

原 Journal 已有重复键收集与 `JsonlSnapshot.require_unique_keys`；当前保留旧第二次物理扫描是为了保持其独立故障观察，不代表该扫描永久属于领域政策。后续应在原场景允许的故障合同下比较快照复用，不能悄悄删除物理观察来凑行数。

原四源与 1911 生产源指纹、完整候选、三个设计报告、接受记录及树外探针保存在 `architecture-analysis/coding-responsibility-goal-20261107/p4-legacy-source-catalog`。原 58 项观察覆盖真实公开操作、原 native verifier 和 ABI/共同消费默认合同；首轮探针因原件路径写错发生 58 setup errors，未执行产品操作，修正路径后 58 项通过。原失败 XML 保留，没有把候选写成期望。候选对照及相关既有回归正在进行，不预支终态；仍须实际接入后的检查与三视角代码接受。

### 11.3 接入及验证范围收束

三个独立候选代码视角未发现产品阻断，所提实际加载来源与 resolved hints、双重 close 故障链缺口另用两项补件关闭，原 58 份期望及执行程序保持不变。候选主体 **159 项通过**，补件 **2 项通过**；四显式候选源类型检查通过。实施 owner `/root`据此有界接受四源采用，不预支实际源码或整个 Goal 验收。

原宽基线误选整个外部数据包测试文件，包含本片未改动的 CLI/RPC/管理场景；纠正影响范围后精确中断自有进程，终态为 **99 passed、KeyboardInterrupt、exit2**，1370.96s。原 XML 保留，该运行不是完整基线通过，也没有因观察超时重启。原行为的 58+2 有限观察独立完整通过；本片实际验证选用相同候选回归范围，另含原层间方向/环检查，不扩大门禁或平台。

四实际源逐字同已审候选，原 1911 生产源中仅四源改变，其他 1907 源逐 SHA 不变。实际 Coding **121529**、系统 **638589**；本片 Code−284／接收+405／系统+121，累计 Coding 减 16226，系统仍比 634794 起点多 3795。15K 与系统净减少均未达成。Ruff/format 四实际源通过；实际行为、类型及代码评审终态另补，不能由候选结果替代。

### 11.4 实际终态与三视角接受

21761从实际工作树取得 **164 passed、0 skipped/failure/error、147.22s、exit0**：原58观察、2补件、Legacy目录6、policy reopen2、dependency6、旧Wheel IO75、data2、stream custody3、consumption7和三个原架构边界。实际加载四模块与确切Core/Resources callee、原公开类型及真实FD异常链由同探针守卫，不用旧AST代新实现，不重复累计原/候选数量。

11907四实际显式源 silent-import/no-incremental mypy成功；80384原dependency renderer新鲜度exit0，原Ruff/format范围保持。三个独立实码视角及终态补件核四实际源、1911生产指纹、60原JSON与真实XML，无本片剩余职责/运行/数据阻断。实施owner `/root`记录 `code-acceptance.json`，接受本片有界交付；四实际源SHA与候选及前述完整成本不变。

不销账原目录10项、Goal Store/Session2项及其它旧失败，不接受完整安装/迁移家族、原生Windows、全部竞态或断电。原99通过后中断的宽运行与首setup探针错误各自保留。整个Goal继续active，原15K与系统严格净减少目标保持，重要待用户工作件不由本片替代。
