# A127：托管Work共同机制归原AppHost Session集成

- Authority: bounded implementation acceptance under COD-RESP-GOAL-002.
- Design status: accepted for the two invocation paths described here.
- Implementation status: full P1–P4/15K remains partial.
- Owner: original AppHost optional Session integration; Code owns Product policy.
- Method: clean local archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`.

## 实物与职责

普通CodingExecutionWorkV1和Deferred Resume Work原来各自订阅Agent、解释最后
Assistant outcome、绑定turn interrupt、dispatch、清turn并在Session结清后退订。
原AgentProductSession.execute_prompt/settle_execution和既有_ResumeContinuationSession
的published-input程序已经共享，不新建Session、输入/Model barrier、ExecutionGuard
或Task。原AppHost.integrations.session_control内新增私有同实例Work实现直接调用
它们，共享完整观察/outcome/retirement；不让Harness逆依赖AppService，也不在
AppService引入具体Agent/Session。原Core其它定义及Code其它定义AST同。

Code保两个原run的try边界与真实binding.activate原子准入入口、subject/IDs和权限政策，
不把activate塞新Core回调。普通先wait-title再checkpoint，取消依次abort五类任务；
Resume pre-cancel在try外返回，仅对已交付Session abort。Core没有内层finally抢先
unbind，仍先Code取消/abort再清turn。普通interrupt读公开self.session动态值，Resume
捕获已激活局部Session；late agent_end仍能在settle中更新同一outcome。

退订只能在Session结清成功后；解绑/退订抛出时引用保留可观察，不加best-effort吞错。
普通标题先清_start_title再调用一次，Resume成功settle可重试title-if-unnamed，保Code。
原两个Code类/FQN/构造与run/settle签名保留；Resume私_outcome统一为_agent_outcome，
未保无消费者的私字段名、helper模块/MRO或任意猴补丁身份。实际Activated DTO是
原frozen slots三字段；两个ID引用提前纯读、observer闭包构造推迟到订阅点，Resume
inline stop_reason重复读取与显式None改用同一DTO默认None。仅承诺原实际类型数据
行为，不谎称任意Proxy/副作用getter/私构造器补丁的逐点等价。

## 依赖与完整成本

Code214→159及751→713，合计−93；既有AppHost433→551，+118；系统+25。
没有新生产模块、manager、mode flags、Protocol族、第二state或Code IO阶段callback。
新增Agent/Session类型imports在TYPE_CHECKING内，AppHost→Agent静态边已记录；
AppHost标准库core边界仍受原测试约束。集成冷入口345→346（execution_guard）；
普通Work927→940增加13个可选AppHost/Session控制模块；Resume986逐项不变。
不是冷启动依赖下降，不从导入模块数量推出runtime或资源创建，未声称import完全同。
当前Code112131/系统648349，距15K97131；完整Goal不以此片替代验收。

## 验证与限制

原76消费者通过/1原Windows skip/2既有record_property warnings。48缺口观察用实际
Work、Frozen Activated、AI/Outcome/Ack DTO及原ExecutionControl内核，Session/Agent/
activation端口受控；31fault cases/41触发事件，run及两次settle完整trace/error graph
保留。首次capture因observer未编码AckV1而失败，完整脚本/XML保留；仅以实际Ack
qualified type+全部dataclass字段修codec，矩阵/旧断言不动。原source捕获2过、fresh
原重放49过/1capture skip（48+origin）；实际125过/2skip（76+48+origin），不虚增为
全新125场景。持久48另通过，CASES/canonical/observe/每条replay assert AST同，
gzip3162B逐字还原原114837B期望，无重录/数据规范化。同步取消注入不是Task.cancel；
真实Session取消/写入由原消费者覆盖，未声称原生Windows/过程平台全验收。

另补原Linux Deferred首输入workflow：actual1通过；在树外af802可信只读Git快照
验证同原三SHA后原node亦1通过，未回切任务源。它断言真实history/user append、
published输入只消费一次及stable execution重复ID，补足受控观察不证明的Writer路径。

现有架构批186通过/1消费者库存失败（两新增Code→既有bridge边），不写成旧基线。
随后只对两个exact path及唯一module/member上界作可选减集，原23必需路径、scanner、
34assert及其它整module AST保留；12,288反事实中64个old-pass全保、11,776缺必需和
6,144未知consumer仍拒。无新presence要求/merge失败条件，属scope reduction，
未扩PR gate。修后原失败node通过；其它186未无故重跑。生成图最初stale记录保留，
按新真实TYPE_CHECKING边重生成并check通过。Ruff/mypy3通过；本批AI未选中，A126
既有覆盖率失败不关闭；不声称其它fallback/全平台或全部架构门禁已绿。

三独立设计/实际、旧源/观察、失败/修正、冷模块差异、门禁单调减集及全成本在树外
`coding-convergence-continue/a127-hosted-work-selection`。Hosting/AI覆盖率/构造欠账、
KD003未实施与KD011/A33待用户未采用保持；无远程发布授权或新平台开放。
