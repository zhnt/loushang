# COD-RESP-A19：既有本地托管启动阶段复用

- Authority: accepted implementation design；不新增系统组件或部署路线。
- Design status: accepted；2026-11-08三视角无实质阻断，实施owner在已有任务授权内接受本内部接缝。
- Implementation status: implemented（A19启动阶段及A48外层应用寿命）；有界代码接受，G17原业务故障及17项managed setup限制未关闭，不等于全托管路线或完整Goal验收。
- Owner: 原AppHost local与Coding托管薄入口；来源为[完整Coding职责Goal](../harness/coding-responsibility-convergence-goal.md)。
- 方法：本地干净archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

## 目的与既有职责

Coding本地命令的prepare/activate预算、任务等待与错误收束和AppHost本地部署中的同类程序重复。两者却不是同一资源owner：命令先拥有G13 attempt/尚未交接的application，交接后AppHost local独占部署停止；客户端EOF仍不停止应用。两条实际路径都须保留，不以通用基类替代G13、AppServer、Continuity或真实清理。

本片是原AppHost组件内的算法复用，环境、公开调用方向、原授权及所有资源owner不变，无新进程/对象/服务/任务表。它不采用KD-008的新完整Canary协调方案，也不实施尚待用户审阅的P2 Plugin/Session方向；原两者继续独立待定。本任务内的技术接受由实施owner记录，不归给用户。

## 最小接缝

在现有`apphost/local.py`中仅保留一份内部`_LocalStartup`算法，原AppHost/Coding两实际类继承它；managed Coding子类仍沿原继承链。不额外实例化控制器，不增加init或资源字段。六个原方法start/prepare/_prepare/activate/_activate/_remaining_startup同体；原_start_once/_activate_once/close和两项纯状态读取仍由各原owner提供。

仅两类原固定错误前缀分别为`hosted_local`/`coding_local`；仍构造原HostedApplicationError，不引入错误注册表或任意阶段callback。准备拒绝读取保各原字段短路顺序，ready判定保AppHost.accepting或Coding._local的原读取方式。Coding的_spawn与_failed直接绑定原AppHost的同体函数，保原私有名字；不改成会返回任意业务结果的另一类任务工厂。

| 保持的完整路径 | 约束 |
| --- | --- |
| 一步start与分步prepare/activate | 原one_step与重入拒绝时点；deadline验证与首错；原单调启动预算取min，activate不续期 |
| 正在prepare/activate时取消或超时 | 同一原Task经shield等待；未完成时用原错误；进入原close，close异常与首错覆盖关系保持 |
| 关闭或过期后activate | 原同步fence/closing及ready判定；不能宣布ready或重新发放预算 |
| 构造/交接/关闭/重试 | Code根目录准备、产品构造、adopt时点和先关闭local再join外层start保原体；AppHost的reply/connection/directory/application顺序保原体 |
| managed子类 | 原prepare不建根、原attempt/Profile与output capture清理继续用原覆写；不扩大支持Profile或改变关闭债务 |

基类只有原状态的静态注解和具名覆写接缝，无新增持久化、缓存、锁、create_task或截止期。运行时仍用原两个实例的各自字段/锁/任务；每个实际任务创建仍发生在原调用位置。Task发布函数原先已在AppHost拥有并被复用，不重新实现发布算法。

## 兼容、成本与验证

原公开类/FQN、构造签名、所有公开方法参数/返回注解、Launch dataclass及__all__保持。六个方法继承后，定义位置/qualname/类自有成员与MRO改变，Code的start/prepare/activate文档字符串改为共享文本；不承诺完整反射或未绑定方法pickle兼容。已核实际managed覆写和原测试的实例级_prepare/_activate_once注入仍经虚调用生效；不能仅凭仓库未发现消费者删除已知公开合同。Code原私有_spawn别名保留，但共享启动方法现在读取实际AppHost模块的发布函数；不保证任意旧私有模块重绑定影响时点。

当前两源Code402/AppHost337行；树外候选按Product导入排序后Code319/AppHost380，合计739→699，系统预计−40、Coding−83。全部类型注解、覆写接缝、导入和兼容绑定都计入；不是千行级删减，更不验收15K Goal。真实实物和来源守卫决定最终数，不通过换行压缩凑数。

改前20677原四文件测试64 passed/17 setup errors（48.15s）。17项全部来自managed部署fixture祖先目录权限拒绝，在本片改动前即发生；不放宽Product原生路径校验、不改工作区祖先权限、不删除断言或绕过托管pytest wrapper。保留该未验证边界，不把基线称全绿。原型两源mypy已通过（silent imports，非全图）。

实施复用原AppHost local、Coding local/ownership及managed消费者测试，原签名/同步fence与边界检查；新增生产测试仅在原覆盖确有缺口时采用。核其它所有业务定义AST、声明与构造顺序不变；异步测试沿原sandbox外、磁盘runtime、not-live/skip-host-runtime。三视角先接受上述内部接缝，实际替换后再核代码/成本/失败与兼容；原始源/测试和切点保存树外，按整套两源回退，无数据迁移。

## 实际交付与有界接受

原设计冻结SHA256 `37fca043b8eb174efdef98f1b1412a1bb58c3576611a1dc6d5d2c4a861736cb6`及三份独立设计报告、两before/候选和四份原managed阶段观察均保存树外。三视角核六方法按原前缀/状态读取展开后的AST、其它各16方法/构造、真实资源owner、接口与全成本，无剩余实质阻断；实施owner `/root`在既有Goal/P3授权内接受该组件内部复用。未制造KD-008、P2或新重要环境图的用户接受。

实际两源逐字匹配被审候选：AppHost `e1ac071d4b94ca87d9aa6933383b728283aff6137b87489d5b850363de194023`，Coding `bafb1ebcca6125af9324a91f8ea07afa5c8ffaff7fb22058d5f3cc874f7f8492`。与A18全量1882生产源pre-image相比，只有这两项改变，其余1880项同SHA，包括P2来源；没有新增生产文件或Harness根目录实现。Code319/AppHost380的完整实账仍为系统−40、Code−83，不预支其它波次。

实际44776为114 passed/17 errors/117.45s、runner exit1。JUnit131条中零failure/零skip；17条仍在原ManagedRegistry fixture的ancestor权限校验处setup失败，和改前原因相同，不能写整批全绿。另四个原managed阶段期望在改前33283使用真实class/launch与假attempt/local/capture端口独占捕获（4 passed/5.23s），在44776逐字重放，已含114，不重复累计。它们补证分派、取消/异常、预算与capture关闭次序，不证明原生注册授权或17项通过。

实际三源mypy58945通过（依赖silent，非全图）；6509原Ruff/diff与生成依赖check通过。没有修改Product测试、CI/选择器、路径权限防护或工作区祖先权限。三份独立代码报告分别复核实际SHA/旧逻辑、原字段/分派/反射限制、全成本及上述JUnit终态；实施owner仅接受本片本地替代及已验证阶段路径，不把基线受限接受扩成所有托管部署、跨平台或完整Goal。全量执行进展见[Goal记录](../harness/coding-responsibility-convergence-progress.md)。


## A48：完整外层应用寿命归原AppHost（2026-11-09）

本段扩充A19，不重记六个已交付启动方法。Code原命令仍是同一实际对象，但完整
根准备→G13 attempt.open→原HostedLocalRuntime交接→activate/run→同步fence→
local-first close→join原外层Task→未交接资源清理→显式重试程序由原AppHost local内
`_LocalApplicationStartup`实现，直接复用原`_LocalStartup`。已交接部署仍独占原server/
reply/application停止；未交接的attempt/application及原task/phase/deadline仍在原
command self，未新增controller、日志或状态镜像。managed覆写与output capture关闭
顺序保持。根准备仍是有IO的产品政策钩子，不称所有Code构造/输入已退出。

Code保真实公开类、原constructor/Launch/字段、产品准入及attempt/root/instance/mux
选择。私有Launch Protocol转为Core静态接口，Code旧名alias仍在；resolved type hint
名义身份、继承方法module/MRO/自有成员及私有factory/等待lookup位置变化明确保留，
不承诺任意反射/方法pickle/旧私有hotpatch全等。故障注入只移到真实Core，原43条
ownership Assert AST逐项保持，没有为测试另造factory或阶段框架。

完整实账Code319→214（−105）、原AppHost380→581（+201）、系统**+96**，其中28行
来自原同AST排版；这是职责归位成本，不称系统净删。两种原phase签名由薄方法共用
一份保留Task/截止期程序，wait也用原实现/原错误前缀。R1曾有private phase签名冲突，
R2分离共同实现名后解决，未加ignore/cast掩盖；三源mypy和实际Ruff通过。

首实际64节点为60过/4失败、138.31s：59原业务通过/1个G17 picker失败，外置四个A19
观察1过/3失败。复用旧观察时漏掉主线上managed策略已从False改True；旧期望未改。
临时仅恢复两迁前源码及fixture，以当前Managed原SHA守卫独占捕获另四份current-original
观察，**4捕获通过、同G17失败，46.89s**。新旧只差三个mode的execution flag，取消
case无差。恢复相同R2后四当前原点对照**4过/12.32s**，真实Core代码对象/路径/SHA及
同self见证；profile call含协程resume，不当多个独立操作数。原59业务节点未重跑，
四对照与首轮取消case重叠，不称一次64项全绿，也不把捕获加成业务通过。

G17在actual和当前迁前原体均assistant等待超时后报hosted_local_cleanup_incomplete，
内层hosted_continuity_cleanup_incomplete；原点对照未显示为本片新增，尚未定位根因
或修复该业务。原17项managed native Registry祖先权限限制未重试，继续未验证，不改
权限、旧断言、选择器或timeout制造通过。

既有G16单文件380行阈值按已审实际接收+201同步为581；只有这一旧大小条件放宽，
全模块其它AST、依赖/native/公共application guards均保留，未新增或扩大CI/gate。
首大小失败XML保留，对应原架构检查**19过/53.39s**。门禁治理按用户明确允许的旧
条件scope reduction处理，不制造新的审批要求或未来模块豁免。

三独立设计与实际代码视角、Root共同上级owner有界接受上述程序替代及已验证路径；
其它待用户重要图与整个Goal不因此接受。当前Code121023/系统641070，1932生产源
仅两源变化，其余1930逐SHA同主线同步帧。证据/两稿/旧新原点/各失败及成功XML、
源码/43断言核查/三视角报告保树外`p3-local-application-lifetime`，未commit/push。
