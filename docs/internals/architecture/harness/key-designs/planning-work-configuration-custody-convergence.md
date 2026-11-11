# A126：完整model Work配置寿命归原HarnessWork规划集成

- Authority: bounded implementation acceptance under COD-RESP-GOAL-002.
- Design status: accepted for this configuration lifetime only.
- Implementation status: partial for full P1–P4/15K.
- Owner: HarnessWork planning / original Session and Allowance; Code binds Product profile.
- Method: clean local archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`.

## 原操作与归属

四条实际规划路线构造原ScopedSessionWork。其获取reservation、进入allowance、
按step配置、await delegate、等Session idle、释放同一配置、失败fence/退出phase
原在Code；原SessionExecutionConfiguration、ModelCallAllowance、GoalCoordinator
早已共享。现在原HarnessWork.integrations.planning内私有_ScopedSessionWork执行
这条完整程序；Code原同名类继承，七实例字段和构造/cancel方法AST同，原FQN保留。
同一适配对象，无新Task、运行账本、manager、Protocol族或Code配置/关闭阶段回调。
Code仍定义repair阶段、inspect/repair工具映射和GoalError/三条诊断纯值，原领域
PlanningToolPolicy与其文件/effects政策保Code。Verification finally不同，保持原位。

原PlanningWork完整AST不变。SessionExecutionScope会增加Task/取消/settle准入，
不是drop-in；SessionWorkRuntime.settle会取消active run，也不能替代idle→release。
本片不重复计算前序底层共享收益，未采用更大Hosted/Method保留Task候选。

## 旧失败顺序与候选修正

getter缺失/None先拒；allowance.enter与step读取/alias/工具投影在try外，故这些
旧失败不进入cleanup。unsupported检查、配置失败及delegate/repair额度失败在try内，
沿原idle→policy reset→release；idle失败跳release，清理错误fence并按原异常链外抛。
最终policy reset在leave前；若该reset抛出，旧leave也会跳过，未借重构悄悄修复。
cancel_and_wait直接委托原Work，不新增abort/retry/close或Task ownership。

初A以dict.get投影tools，会在try前hash列表alias；合法str context+构造参数
step_aliases={'repair':[]}可使它提前跳过cleanup。A未装即拒，B以有序step==name
比较投影，hash成员检查仍在原try内，TypeError之后原idle/release/leave保留。
不加typeguard/缩支持；反例实际旧记录已冻结。profile tuple值/顺序保持，不承诺
每次新tuple对象身份；Code类method定义元信息/MRO变化不造反射兼容壳。

## 全成本与验证

Code237→196（−41），既有Core68→139（+71），系统+30；所有类型/导入/profile及
排版计入，非系统净去重。当前Code112224/系统648324，距离15K97224，完整Goal仍开。
原Work shell151通过/7deselect；旧capture2通过、fresh旧replay30通过/1capture skip
（29case+source origin）。实际联合181通过/1capture skip/7deselect；持久29另通过。
29条含18fault case/23触发事件；CASES、canonical、整observe和replay断言AST同，
gzip1432B逐字还原旧26356B记录，不用规范化JSON稿重录期望。现有测试有真实Task
取消/idle控制；补缺观察的Session/delegate受控、注入Cancel仅为异常，不是Task.cancel。
未新增native平台声明、模型provider或真实Writer证明。

Ruff通过、仅新块format通过；mypy两源通过但默认不检查所有untyped方法体，不称
全函数类型验证。依赖图/docs9通过。路径未分类触发原全量fallback；已执行AI检查，
935过/2skip/7deselect但coverage89.87%、runtime-core6745/7526=89.62%未达90，
make exit2，AI门禁仍失败。79 AI源SHA及每文件可执行/covered行集合逐项同A117
既有失败，不降阈值/绕门禁；其它fallback平台与全套门禁不冒称已执行或全绿。
UV_NO_SYNC保持共享venv绑定main，原nonlive/skip-host选择器保留。

三独立设计/实际视角、原源/观察、A拒绝、全成本与静态/运行终态位于树外
`coding-convergence-continue/a126-planning-scope-custody`。未扩PR gate/平台/断言。
Hosting/AI覆盖率/构造、KD003未实施与KD011/A33待用户未采用保持原边界。
