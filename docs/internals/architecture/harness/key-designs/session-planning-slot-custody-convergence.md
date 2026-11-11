# A116：Session规划槽的单waiter与缓存寿命

- Authority: bounded implementation under COD-RESP-GOAL-002；完整Goal仍partial。
- Design status: accepted direction；三独立实际视角和实施owner的接受证据在树外。
- Implementation status: implemented，限本完整操作及下列验证。
- Owner: 原Session Agent Product runtime；方法为本地clean archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

Code原ResumePlanningSlot已有Root/Hosted两消费者，共用一个算法。现在同一个Code
对象继承原Session runtime内的私有泛型基类；原loop/task/key/plan/closed/lock六字段
只存一次、顺序不变，无第二manager/registry、调度器或阶段状态。Core接整个锁内
重复抑制→discard旧waiter→设置key→构造domain coroutine→create_task/拒绝时close→
done身份校验/缓存，以及原loop检查、discard与close；不接Resource native工作/容量。

Code保start前段的baseline/预算/真实loader检查、弱引用key、原当前source/owner
校验及stale失效政策。唯一factory lambda只在原锁内、原discard和key赋值之后
构造原domain请求，不把Code物理IO程序回借Core，不存factory到self。error prefix
是ClassVar产品数据，不增加实例字段；current域算法原样。没有新虚拟阶段接口。

DeferredCapabilitySlot持authority candidate/prepare-publish-dispose并隔离普通caller取消；
CatalogPreviewTaskScope负责native容量/跨scope共享，且不缓存完成值，close又会fence。
它们不是本waiter-reference槽的替代；后者原已被domain planner复用，不重复计收益。
Foundation join会改变child Exception吞掉与last caller取消合同，也不强套。与A38
十九字段/广协议/三虚方法/八诊断的候选不同，本片只移完整中性Task/cache程序，
一请求factory与一prefix数据；无IO-stage callback池。仍是职责迁移，不报双算法去重。

Code194→117（−77）、Core538→636（+98）、系统+21。当前Coding430源112801行，
系统1969源648205行（含GUI Rust/TS），较Goal−24954/+13411，距15K97801。其余
1967源/13资源SHA同。旧Code公开FQN、start/current/discard/close及构造签名、六字段
顺序和fresh Protocol4 pickle hash相同；不承诺live Task pickle、私方法FQN/own-method
反射或traceback帧数。五继承方法逆类型/prefix同原，展开factory后完整start逆AST同；
current与原Core所有非import定义AST同。mypy两源及Ruff通过。

旧32消费者过/1原Windows skip；21旧真实Task观察捕获及重放过，持久原值不重录。
原实物上持久21+实际Hosted后台+原共享Resource peer两例合24过；源码固定后的
候选合221过/1原skip（原32+边界165+上述24），保两项原xunit record_property警告。
首轮安装交叠的3次新运行不计验收；unscoped冷导入误读control lane后，原/新shape
均以显式任务PYTHONPATH及origin/MRO重新核实，未改产品迎合观察器。

21观察用真实Task/Event/Lock，domain baseline/worker受控；晚callback由实际Task子类
刻意延后。记录完整有序trace、状态、错误args/notes/cause/context/suppress，仅观察器
FalseyError类名用稳定别名，Product错误类型不归一。覆盖连续caller.cancel两次、
工厂拒绝/新coroutine关闭/重试、late callback、新旧key、弱引用和source/owner失效。
weak-loader经gc.collect核，不是无GC证明；字段状态不是所有FD/native job普查。

Hosted观察使用真实Catalog header/source与ResourceLoader，执行原后台规划/close并
核同session/原header bytes、无active Session；不激活Product，unused selection=None，
不外推全AppHost/Writer/执行路由。四次初夹具错误（import、未被Catalog接纳的legacy
header、未准备Session提交输入、错误history字段）全在旧源出现并保留；最终用原
Catalog创建的合法空header，不绕过原输入政策。显式probe_*及JSONL不进默认gate。

完整旧源、候选、AST/shape、原21值、失败/修正、JUnit和三视角在树外
`coding-convergence-continue/a116-planning-slot`。其它Hosting/AI覆盖率、构造/Session及
P1–P4仍有欠账；KD003未实施，KD011/A33待用户未采用，不由本片关闭。
