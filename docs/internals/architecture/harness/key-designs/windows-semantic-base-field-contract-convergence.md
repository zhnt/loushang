# Windows六流语义值字段契约收敛 A196

状态：本批有界接受；完整Coding重构仍partial。2026-11-15。
方法参照本机archmethod clean master 0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e。

六个原Code值类与各自Core验证/codec基类重复写46个有效字段：receipt、opt_in、
launch_intent、supervisor、provisioning及C5。Core typed字段已参与相同语义验证，采用
标准dataclass(frozen=True,init=False,repr=False,eq=False)使其成为单一字段schema来源。
保Core原空__slots__=()，关闭Core构造/repr/eq生成，不增加实体状态或独立记录工厂。
Code仍用原frozen/slotted dataclass，生成原public构造、全部physical slots、repr/eq/hash；
类型FQN/profile/schema和全部方法保持。3个Code nominal peer注解覆写保留：opt_in的
latest_decisions、launch_intent的retained_intents、provisioning的retained_attempts。

最初Core slots=True方案会把Code ownslots变空，不能复用旧观察，未进入原型/生产。
实际方案保留原Code名义类及physical slot descriptor所属位置，字段schema声明源改Core；
无反射注入、虚假
slots、生成DSL、新Role/T或状态框架。原V1 version默认1继承自同一个语义契约。
Core dataclass身份/frozen setter、Code ownannotations减少、继承字段dict新增15个ClassVar
pseudo-fields是实际变化，不能称全部metadata相同；fields()/schema排除pseudo-fields。

六Code651→605（−46，含43中性重复注解及声明段空行），六Core1154→1166（+12），
系统−34；raw=uniform。所有decorator/import/default/peer覆写成本计。原12源方法/profile/
schema及其它定义逆声明AST同，没有第二codec或物理IO退出，收益是字段契约去重。

原11模块同212节点，旧212过36.36s，实际212过35.21s，0fail/error/skip。原wire carrier
6role、每role empty/retained的有效fields/constructor/default1/ownslots/noDict/frozen/wire
与current pickle roundtrip全部按旧fixture，另12份protocol4旧pickle加载为原Code类型并
匹配旧wire；不证明新dump字节完全同或所有pickle协议。实际producer消费者包括六流19、
preparation6、persisted2、join2，以及原受控persisted-reader171，不当nativeWindows权限证明。

14模块父进程来源守卫各212nodes/424checks/59声明callable、phase/PID分立，pin路径/SHA
及19递归code字段；它不验证生成dataclass函数，生成行为依据原carrier实际重放。
三fixture逐SHA保持，所有观察/断言未改；无新增test/probe/oracle/fixture/gate。实际project
mypy12源/Ruff过，不称全strict/全PR。repr/hash/所有eq/get_type_hints/weakref/basicsize没有
独立旧观察冻结，不能把源码/类型判断包装成这些元数据的运行全等证明。

源码、静态投影、冻稿/成本、三独立设计和实际评审及原同组XML留树外A196记录。
当前Code110241/Harness364513，C07为112源21086；source659784，排GUI4524后655260。
完整P1–P4/KD003/KD011及≤15K仍开放。其它29类253fields仅导航，其中25类209fields
有明确ownannotations原观察，不直接推广本方案；剩4类44fields也须独立全成本与兼容验证。
