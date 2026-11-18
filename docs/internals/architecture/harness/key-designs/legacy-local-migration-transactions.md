# 旧本地安装的接受与来源消费事务

状态：A199实际有界接受，2026-11-15；完整Goal仍开放。
方法咨询为本地archmethod master 0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e，非上游同步声明。

## 现有职责与选择

原Package Product已拥有binding catalog、Wheel重捕获和发布；不重复迁移或计益。
剩余Code接受收据与来源消费仍直接拥有FD、双锁、Desired读取、原子发布、Settings事务、
prepared/settled重放及结清。现有Journal字节接口、Config事务或SourceCatalog均不能
直接代替此完整协议。扩充原Package Product私有家族的两个固定事务kernel，直接复用
现有epoch、RootedFileIO、JournalRecordCodec、Desired decoder和真实SettingsManager；
不新建manager、注册表、持久状态、Task、重试或阶段回调框架。

Code保原公开名义记录/Error/签名与版本1/2/3（skill/prompt/theme）codec、产品支持范围、
first-B证据分类和原晚kind/review准入。该准入、accepted-record reopening会读真实领域
证据，明确不是纯函数；它们不回借锁、发布、配置消费或整事务。稳定settings读取绑定
仍直接复用原Config读取，原路径资格/预算/异常时点保持。现有catalog391行只作上下文。

## 完整操作与失败合同

接受：原review/epoch/proposed后，原state root→FD私有身份→receipt独占锁→current；
有相同收据直接复用，缺失时才取Desired锁→读取/尾检查/解码→构造实际installation key→
原unseen判断→Code晚kind/review复核→exclusive atomic write→current。成功时target
退出后、RootedFileIO退出前原父身份postcheck；异常不新增postcheck，原finally关闭FD。

重开：原Code参数/epoch资格后，Core私有FD读/解码/单记录检查；root或receipt缺失仍先
assert current再None。FD完全结清后Code原first-B frozen-review复核，再current/return。
不会因为旧Source消失而拒绝已接受记录的恢复。

消费：完整prepared/settled receipt锁在真实Settings.transaction外。每次重验其它已结清
来源、global/project原路径顺序与raw digest、original/cleared CAS；写prepared后才允许
清掉一个精确来源，再验证并写settled。崩溃/异常在原收据与真实配置上重开，未知live修改
拒绝覆盖，无自动重试。只读结清证明使用相同Core判断。consume不新增退出父目录复核。
原Code动态_receipt_bytes每个原点晚调用，保两原CLI中断挂点及_receipt_path定位入口；
原os.link注入仍通过真实os对象作用到原Rooted IO。

## 全部成本与代价

| 来源 | 原→实际 | 净值 |
| --- | ---: | ---: |
| Code local_acceptance | 542→427 | −115 |
| Code source_consumption | 397→172 | −225 |
| Harness Package Product固定协议 | 0→480 | +480 |
| 生产源码合计 | 939→1079 | +140 |

raw=uniform。全部Code门面、typing、compat与绑定成本计入；1T、3只读role/8属性、
两次调用内recipe的6+9引用字段及原4字段事实对象，不是第二状态权威。Code−340而系统
+140，是完整职责归位，不称系统精简或第二receipt引擎去重。相较仅移壳方案，本片让
原生IO/锁/Desired/Settings/重放/关闭操作体完整退出Code；界面仅保必要领域准入与codec。

私有recipe增加调用帧；私有FrozenSources的FQN/readonly注解变化，内部Code配置值仍
是原对象，没有第二份事实复制。recipe在入口绑定codec/error/预算，不承诺任意中途突变
私有globals的观察等价。A199当时的SettingsManager为TYPE_CHECKING导入；发布整分支
复核发现它仍造成反向静态依赖，改用消费owner七成员私结构端口，原对象和事务操作
不变，全部typing成本另增19行（Core480→499）。既有ResourceRootSettingsManager不含
事务/path/分层读取和更新契约，不能直接复用。私dataclass字段/构造及两私方法注解
演进，不承诺全部resolved hints相同。原公开record类、五公开签名和两领域helper原样。

## 验证与剩余

原四测试载体的74个节点全部通过（JUnit 696.505s），包括12个完整CLI函数的全部原参数。
冻结三源接入后相同有序74节点全部通过（JUnit 692.969s），0fail/error/skip；原测试与fixture逐SHA不变。
实际三源mypy/Ruff及五原公开接口/记录源对照通过。父进程来源守卫旧5/实际6模块，
仅核源码声明callable及19递归code字段；不覆盖生成方法/子进程或所有native故障。
无新test/probe/oracle/gate，未运行完整PR或nativeWindows矩阵。冷导入来源另记。

完整P1–P4/KD003/KD011仍开放；C09整组尚未完成或证成保留下界。当前计量与下一大块
顺序分别见[逐文件清单](../coding-responsibility-inventory.md)和[优先队列](../coding-responsibility-priority.md)。
