# H-COD-KD-005：私有 Journal 与原 IO 作用域复用

- Authority: accepted key design；本片不改变总体系统环境图或公开合同。
- Design status: accepted within delegated implementation scope；三视角无剩余阻断。
- Implementation status: implemented locally；相关分片回归、窄类型检查与三视角代码复核完成。
- Owner: 既有 Harness Journal 的 RootedFileIO、Resources WindowsJournalFileIO 与 Worker 分段原语；R4 的过渡期 Coding 原语在 R5 归位，各 Coding Journal 保留 Product 与业务权威。
- 来源：[Coding 精简 Goal](../coding-private-data-implementation-goal.md)的全 Coding 扩围授权。
- 基线：`8ad6b6098f1c24c8cfb6f4d9d290e99bc74d618d` 加 A44；方法为干净本地 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

## R1：事实与选择

Coding 的 native approval、opt-in、activation receipt、start gate 四个 `_bound_journal` 都执行同一父目录程序：no-follow 打开→fstat→可见路径身份及私有权限核对→RootedFileIO 构造与绑定→退出绑定→cleanup→成功后的路径身份复核→关闭父 FD。

既有 Journal `_rooted_io` 已有 `_private_parent_matches`、RootedFileIO 的绑定、锁与清理，本片复用它们。该 owner 增加一个内部 context manager `bind_private_journal`，仅持有此次调用的父 FD 和原 IO。Coding 原方法删除上述操作体，保留自己的锁选择、V2 所有权检查、缺失锁诊断、首次 head 初始化和 yield。不会新增 Journal 实例、持久记录、锁、清理账本或事务框架。

两个差异明确作为输入：native approval 只读绑定原本 `durable=False`；start gate 原本单独把父目录 open 的 OSError 转成原 root-unsafe 错误。其他三个入口继续传播原 open 错误。标签与错误类型由原业务提供，不向 Harness 引入 Coding 依赖。

## 运行与兼容

| 时点 | 保持的原合同 |
| --- | --- |
| 打开与准入 | 原 flags、UID、权限、目录类型、可见 identity；不增加锁或平台范围 |
| 构造失败 | 父 FD 关闭；原 IO 构造失败之前不虚构 cleanup |
| body／bind 退出失败 | 先原 IO cleanup，再 close；不执行成功后路径复核 |
| cleanup 失败 | 保留原异常优先级，再关闭父 FD；不增加重试或回滚 |
| 成功后复核 | 只核对可见路径 dev/ino；不增加另一次 fstat 或权限准入 |
| close 失败 | 原失败覆盖规则及异常 context 保留 |

原公开类、方法、参数与存量格式不变。私有模块的 `os` 或 `RootedFileIO` import 不作为兼容 API 保留；故障注入应指向实际 native owner。原 Product、GC gate、历史解析、领域校验与记录编解码不迁移。其它相似 scope 有不同检查／锁顺序，不能自动纳入。

## 成本、验证与接受边界

完整格式化候选包含四个原调用者和原 `_rooted_io` 的增量：Coding −97 行，Harness +32 行，系统 −65 行。没有将四个原方法的全部行数计为收益，原 C08 的计数不变。

改源前以五份实际文件的 SHA 和 canonical import 路径守卫，冻结 256 项原入口观察：四入口及其读写／V2 选择下的成功、打开／准入／构造／绑定／body／退出／cleanup／postcheck／close 故障和双故障优先级。它们使用惰性测试 IO，证明作用域与错误合同，不证明可信 Product 或原生平台行为。另复用实际 Worker approval、opt-in、receipt、start gate、checkpoint、RootedFileIO 回归；不新增 CI gate、模型或联网试验。

候选、原源码及固定结果保存在产品树外的 A45 证据目录。实施前、实际接入后的[三视角代码复核](private-journal-parent-binding-review.md)均完成；已检查真实调用者与源码并运行对应回归。重要架构工作件的用户评审要求继续适用，本片不冒称用户接受了新架构或整个 Goal 已完成。


## R2：原 RootedFileIO 的显式词法清理（A46）

Design status: accepted within delegated implementation scope；Implementation status: implemented locally。R1的历史交付继续有效，R2三视角实际代码评审无剩余阻断，相关回归及15源窄类型检查完成。组件与事实权威不变，不改变系统环境图。

全生产源码中找到22个相同的局部构造→try/finally cleanup 作用域。原 RootedFileIO 增加标准 `__enter__`／`__exit__`：返回同一 IO；退出时只调用原 `cleanup()`，始终返回 None，不吞异常、不关闭借入的根 FD、不增加状态、重试或新账本。21处改为标准 with，原 try 内全部业务语句与绑定保持；另一处完整回执读取直接复用 R1 的 `bind_private_journal`，公开读取参数和 V1/V2 判据保留。

所有长寿命的 Transcript／lease IO 仍由原 owner 显式管理，本片不把字段持有的 IO 改成局部 with；构造后不是立即进入单一 try/finally cleanup 的路径也不自动纳入。构造失败仍不会调用 cleanup；业务／BaseException 失败仍触发一次原清理，清理错误仍覆盖原错并保留 context；成功后 Product 复核、pin 释放以及父 FD 关闭次序不变。新标准 API 的清理债务、重试和未知关闭处置完全沿用原实现。

完整15份生产候选格式化后 Code−87／Harness−5／系统−92；其中10行来自既有格式整理，纯作用域替换成本为 Code−77／Harness−5／系统−82。不把排版称为算法收益，也不把扩围计入原C08。没有新 runtime、manager、profile、协议或持久格式。

实际接入前核实15原文件的 SHA 与 canonical import，并复放原固定父目录观察；实际接入后复用原publication／RootedIO、legacy acceptance、V1/V2历史／checkpoint／GC场景。新增真实FD例验证清理后 publication witness 失效但数据保留，以及目录fsync失败后的债务、清理失败覆盖取消的原异常优先级和持有原目录重试。原惰性probe仅给注入IO补标准上下文接口，保留全部原expected。三视角独立审查须覆盖实际代码与上述证据局限，不能用局部新API测试替代整个Goal验收。


## R3：Windows Worker 只读作用域（A49）

Design status: accepted within delegated implementation scope；Implementation status: implemented locally。原系统环境不变，内部调用为 Code Journal→原 Resources WindowsJournalFileIO→原 Journal共享锁／Foundation ACL及原native文件端口；不存在新运行角色、存储、队列或记录协议。三个独立视角已复核候选；实际代码与运行证据的技术接受见[终审](private-journal-parent-binding-review.md#a49windows-worker-只读作用域终审)。

重复事实为三个完整读程序：receipt.records、native approval.history_read_only、opt-in.history_read_only 都在原借入root上执行 ACL→visible root→检查锁／文件→shared lock→validate marker→read→decode→解锁→visible root。原 FileIO已有validate_lock、read、ACL／native依赖；不具备覆盖这段共同寿命的作用域，单独调用底层方法不能删除三份外层协调。最小扩充原对象的read_snapshot context，而非新增reader、manager或另一backend。

原FileIO的构造字段、write/prepare/validate/read算法不变；新方法只提供原bytes或None，原记录解码仍在Code with体内、持ACL/sharedlock执行。原Product GC／root准入及写策略继续由调用者负责。该受限读scope可以持有原共享锁；它不创建锁或journal、不repair marker、不调用领域decoder、不解释记录、不保存Descriptor到实例、不补偿部分写。文首旧“完全不acquire锁”的adapter说明随实际受限能力修订，不能沿用为当前保证。

| 原分支 | 必须保留的合同 |
| --- | --- |
| 缺锁且缺文件 | 再查visible root并返回空；不创建或加锁 |
| 缺锁但有文件 | 原missing-lock异常，from None；不尝试修复 |
| 已有锁／原标记 | 原shared lock与同一locked handle；validate后再read |
| raw None／已初始化 | 原orphan-lock异常 |
| raw None／未初始化 | 仍在锁内复核root并返回空 |
| raw bytes／未初始化 | 原lock-corrupt异常；空bytes不等于None |
| 正常bytes | Code decoder在锁及ACL内执行；解锁成功后复核root |
| decode／lock exit／ACL exit失败 | 原覆盖顺序及exception context；失败不运行成功后检查 |

字段name沿原构造配置与对应_NAME相同的合同，不增加模块常量运行期变更能力。私有native注入随实际执行组件，不保留dead shim。四完整生产源为Code−84/Harness+40/系统−44，其中15行既有空白整理；纯流程净−29。全部收益归扩围，不补入原C08完成线。原66观察、实际265回归、窄类型检查及原生效力边界见[推进记录](../coding-convergence-progress.md#windows-worker-三类只读历史作用域复用a49)。原Goal完成条件未变。


## R4：五流固定追加协调（A51）

Design status: accepted within delegated implementation scope；Implementation status: implemented locally。原Code history_segments是本切片的过渡期原语owner，Harness Journal仍提供RootedFile及原append_jsonl_record；不把此内部去重称为中性机制已完成归Harness。系统环境与持久格式不变，没有新增运行组件、backend、manager、profile或记录协议。

五个V1写入尾部都有seal选择→追加→head commit程序，先前已各自使用原段函数和Journal原语，差异在错误投影与编码／目标绑定。最小方案是原owner内单份固定函数，复用原seal／_segment_name／commit；领域授权、CAS、单条容量、V2／checkpoint与返回值保留原入口。新增append(name)与seal_error两个窄端口恰好表示两种差异，不接受任意阶段、before／after hooks、另一个索引或自动补偿。

原正式frozenHistory及固定stem／stream是本次输入边界；receipt和gate generation0保留原_path.name，另三者按固定stem。三个caller先构造target再读取append参数；C5／Supervisor仍在append参数末尾构造target。codec／format／durability仍在seal之后由Code读取；不把此前line直接写入，原重新编码与随后head对expected line的核验保持。仅seal的CodingWorkerHistorySegmentError进入原映射，cause保留；目标／append／commit失败照原传播。

写入后报错不得提交head；commit失败不得自动修复、重试或回滚，原查询／恢复入口继续处理head债务。根、GC、持锁与fd寿命不在本函数内新建或转移。完整六源净减50（结构−51、before格式+1），H0；原C08不计此收益。实际验证、试验输入修正与三视角有界接受见[推进记录](../coding-convergence-progress.md#五流固定追加协调去重a51)及[终审](private-journal-parent-binding-review.md#a51五流追加协调终审)。原整体Goal条件不变。

## R5：分段历史原语归 Worker（A53）

Design status: accepted within delegated implementation scope；Implementation status: implemented locally and independently reviewed。接受仅限本片机制归属及兼容出口，不代表完整 Goal 或规模条件满足。

原 Worker 是本片唯一机制 owner。它已有通用状态迁移与 Journal 接入，但平面日志不提供现存分段／head 合同；因此将已存在的单份算法归入 Worker 内部 `_segmented_history.py`，继续使用原 RootedFile 与 canonical_json_bytes。不会把文件重新解释为普通 JSONL，也不增加 Journal 对 Resources 的反向依赖、第二后端、独立恢复或通用阶段框架。系统环境、进程、事实文件和操作授权不变。

所有类、常量、函数及其非文档 AST 保持；原 Coding 模块改为同一对象的兼容导出。保留历史符号名、错误和原 __all__，追加 helper 与三个 V2 命名函数也继续可导入；没有包装函数或第二份数据类型。定义模块／traceback 路径随真实 owner 改变，私有故障注入应指向实际 Harness 模块，不能保留无效 shim。旧引用样本和签名／JSON 字节在提取前固定；产品存量协议不变，不承诺旧版本理解新模块路径的 pickle。

五流及 V2 消费者仍只向这一份原语提供已准入 RootedFile、现有 stream/stem 与记录字节，不转移 Product／GC／锁／业务记录解码或封段政策。普通读取继续拒绝未提交债务，显式恢复仍由原入口授权，不重试未知写入或自动补 head。Harness 原语不反向依赖 Coding。

Code −760／Harness +779／系统 +19 全额计入。这是 owner 接管，不作为算法净删或原 C08 收益；原数量与全系统净负条件不降低。实际验证和三视角接受边界见[推进记录](../coding-convergence-progress.md#worker-分段历史原语归原-harness-组件a53)及[终审](private-journal-parent-binding-review.md#a53分段原语实际归属与兼容终审)。

## COD-RESP-GOAL-002 A30：受限私有收据文本读取

本节属于后续[职责归一Goal](../coding-responsibility-convergence-goal.md)，不改写上文COD-PD历史账目。Design status: accepted within delegated implementation scope；Implementation status: implemented locally and independently reviewed。实施owner `/root`在既有Code→Journal关系内接受本片，不替代KD008/KD011重要图审或完整Goal验收。方法为本地干净archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

原disabled-only收据读程序及两个仅本模块使用的私有校验helper退出Coding。原Journal `_rooted_io.read_private_text`承接受限二进制读取与UTF-8解码，直接复用既有 `_private_parent_matches`、五字段 `_version`。Code保原helper名字/签名及16MiB限额、错误类型和两个诊断标签；builtin POSIX与removed原本就导入该helper，继续同一对象，并非三份算法去重。记录codec、审批/Desired锁/epoch与Windows分支不变。

完整顺序为父FD准入→子相对打开/私有元数据与版本检查→单次buffered binary `read(max+1)`→handle退出/文件后验/子FD关闭→父后验/私有复核→UTF-8解码→父FD关闭。缺父或子仍为None，空文件为空串，CRLF不正规化；缺子不额外执行成功后验。原错误/cause、read/decode与后续close覆盖次序保持。不新增锁、文件、repair、重试、持久记录或回调框架；只在调用入口绑定标量，不承诺操作中任意替换私有globals。

未强套已有 `_read_private_regular_text_at`：它是无此限额的文本读取、统一换行且缺失归空；`RootedFile.read_bytes`的借用/022准入/读取循环/错误合同也不同。保留原077/euid/nlink/size/版本合同，仅复用等价原谓词。新helper位于原Journal子系统，无新增Harness根目录实现或重要环境参与者。

完整成本为Code347→264（−83）、Journal1140→1207（+67），系统净−16，未新增生产文件。全1909源相对A29仅这两旧源变化，另1907逐SHA同。原22份真实FD观察先排他捕获，比较阶段只读；实际80项为原57业务+22固定观察+1实际加载路径/SHA/真实Core callee/三消费者同对象及原定义AST合同，不累计候选或捕获批。close故障在真实关闭后抛错，只验证原覆盖顺序，不证明未知关闭结果恢复。

实际80项通过、两显式源silent/no-incremental类型及Ruff/format/原生成新鲜度通过；三实际代码视角无本片剩余阻断，见[本轮终审](private-journal-parent-binding-review.md#cod-resp-goal-002-a30实际代码终审)。首轮误填两个测试路径的0tests/exit4保留，非产品失败或通过。没有native Windows、所有竞态/断电或性能证明；原Catalog/Session旧失败保留。当前Code122753/系统638381，完整P1–P4、15K及系统严格净减仍未满足。
