# A106：历史读取任务归原 Session runtime

- Authority: accepted bounded implementation record；完整 Goal 仍 partial。
- Design status: accepted；Implementation status: implemented for the existing history read path。
- Owner: 原 AgentProductSessionRuntime；Coding 保领域读取与关闭政策。
- Method: 本地 archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

## 原能力及最小扩充

Coding 的历史 preview 同时承担每 Root 两项容量、loop 绑定、Task 创建与失败时
coroutine close、保留集合、完成观察、shield、前后指纹与关闭后交付拒绝，另实现
drain。原 Session runtime 已有 source 解析/生命周期，原 Transcript 提供文件读取/
指纹，原 settled_io 提供真实 native IO 结清；这些现成机制继续直接复用，不重复
记迁移收益。原 CatalogPreviewTaskScope 的全局容量/共享缓存/预算会新增拒绝，原
Foundation joins 的失败传播及取消策略也不同，不能直接替原两个完整程序。

只扩原 AgentProductSessionRuntime 三个私有方法：初始化、read、drain；没有新
manager、状态表、scheduler 或复制 IO。一个只读 source_fingerprint Protocol 与
方法 TypeVar 保原 Coding DTO。初始化在 Code 原三个字段赋值时点调用，仍是同
root 上同名字段；Core 原 constructor 不重置、不向其它 Product 自动添加准入或
关闭动作。Code 外层 closed 决策、域 guard 与完整 dispose 顺序保持。

Code 原两个私有入口保薄 await，公共 snapshot/recent/startup、预算2及错误前缀
保持。原 reader closure 仍调用共享 Transcript IO 并做 Coding 领域投影，不称纯
无 IO 回调；它不回借本片退出的 Task/loop/settle 程序。本片也不是全 Resume 或
整个 AgentSessionRuntime 的收敛完成。

## 时序、失败与兼容

第一次 loop 绑定仍早于容量/resolve，失败也保留；done 但 callback 未 discard 的
任务仍占容量。原 source 解析、任务内前指纹、settled_io、保留集合与 callback、
shield、关闭拒绝和后指纹顺序都保持；关闭拒绝早于读取返回 DTO 属性。原 done
callback 只 discard、按 cancelled 情况观察 exception，不改 retry 或创建新读任务。

Drain 保集合快照、跳过 already-done、不主动取 result、按原次序继续。它抑制
原 Exception，记录 shield 抛出的最后一个 CancelledError（不区分 caller 与被读
Task），末尾再抛；其它 BaseException 直接传播。不能将其改成 failure-first join。
取消等待者不会取消 native read；Code 原 close 仍在依赖 owner 释放前等待结清。

公开签名、DTO/持久格式、Code reader hook 与 private drain hook 保持。内部 read
coroutine/done callback 的 qualname、traceback 与调试位置迁到 Core；不是私有
反射或所有警告位置全等承诺。移走的两个导入是原内部调用点，不新增公开 export。

## 全成本与范围

| 源码 | 原行数 | 当前行数 | 变化 |
| --- | ---: | ---: | ---: |
| Coding AgentSessionRuntime | 829 | 780 | −49 |
| 原 Session AgentProduct runtime | 454 | 538 | +84 |
| 全系统 | 648046 | 648081 | +35 |

含字段初始化、Protocol/TypeVar、薄入口、imports与新方法格式。原型R1漏替嵌套
callback注解中的Code DTO且片段格式器没去缩进，外部即拒；R2修复后另仅去两个
新增方法间多余空行，整 AST 同。所有原件/修正保留，未安装R1。
全 Coding430源113344行，系统1968源648081行；相对 Goal−24411/+13287，距15K尚
98344行。其余1966源及13资源 SHA 同。完整任务程序归位而非重复算法消除，不把
系统增长称精简。显式 probe205+冻结JSONL21行（4632 bytes）另计，不进默认 gate。

## 验证和接受

原历史/规划/preview三个完整模块37项过。旧源进程内路径/SHA守卫固定21观察，
旧21回放过；实际候选21过，持久化21在最终来源/SHA守卫下再过，不重复累计。
11读取场景用真实 asyncio loop/Task，但 IO、fingerprint、source为受控叶；10个
drain场景是脚本 Task/shield，非真实取消/IO证明。比较 trace、错误类型/文本/
cause/context、loop粘性、retained容量、closed及create_task拒绝后的coroutine close。

候选原五模块77项过（包含原37，另39 AgentProduct与1 ProductRuntime），36条
warning来自未改 tools.py 的 allowed_tool_names=None 调用点；未跑原全77组，不
将 warning 数量反写成已基线复现。原两个线程读取/真实Task取消/容量/关闭取消
场景与 planning close-drain 节点均过，提供真实线程与生命周期证据。两源限定
mypy follow-imports=silent、Ruff及依赖图新鲜度通过；另原UI/托管26项、原导入边界
165项和文档9项通过。不冒称全库类型或全产品绿。

脚本模型不证明真实 Task 自取消/最后取消对象身份、所有异常 notes/identity、
Python3.12 eager task、所有线程/平台调度。原测试断言/安全选择及 gate 保持；
三独立实际职责/运行/兼容评审和 Root 有界接受、原固定观察与完整帧保留在树外
A106。完整 preview/drain 回绑政策并归一注解后 AST 同，其余 Code 与原 Core 操作
不变；本批不关闭更早构造/绑定、五项 Hosting、AI coverage 或完整 P1–P4。
KD003未实施，KD011/A33待用户且未采用。
