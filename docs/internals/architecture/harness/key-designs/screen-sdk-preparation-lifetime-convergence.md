# Screen SDK预热完整寿命收敛 A190

状态：本批有界接受；完整Coding重构仍partial。2026-11-14。
方法参照本机archmethod clean master 0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e，不携入方法文本。

原[CodingSdkWarmup](../../../../../src/loushang/coding/interaction/sdk_warmup.py)
在实际[UI mode](../../../../../src/loushang/coding/ui/mode.py) attach、model-change、
Session rebound及run_prepared链使用。原[screen Application Host](../../../../../src/loushang/harnesstui/conversation/application_host.py)
以固定私有base承接六完整程序及app/7调度状态，在同一实例拥有timer、waiter Task、
desired/active、completed/failed、hint及closed。无第二实例/状态表/manager、无role/T。
Code保原provider/SDK registry政策、loaded判断、原loader awaitable、日志及task/event文本；
四窄叶和三文本、公开ctor/attach、typing/导入成本全部计入。

原AI sdk_import已拥有loop/package共享且shield的真实导入Task；它不持屏幕状态。
pre-Session startup有必须结清的准备屏障，不能替代after-ready best-effort寿命。
本批不重计二者，也不将原on_start/bind cleanup视为notify-before-try的等价替换。

保50ms idle delay、selected模型才获hint、旧导入完成再启动desired、loaded优先failed、
原Exception日志范围、warm finally状态清除及重启、close同步cancel waiter但不join导入。
notify在try前；run finally先close再卸on_ready；不改原异常覆盖、timer手动观察或
create_task时点等边缘语义。原public六签名/attach整body及2Code政策同，14Core原定义同；
六完整程序84span逆叶/文本AST同。原九字段最终值相同，但provider私赋值顺序、MRO、
方法实现位置及同步调用帧改变，不承诺私dict插序/自定义setattr/任意私hook行为兼容。

raw Code184→101（−83）、HarnessTUI284→408（+124）、系统+41；uniform−85/+124/+39。
差2行仅格式。是完整可见预热寿命归已有screen host，不是另一算法消除或系统净精简。
Core不读Session/model/provider，不反向导入Code或AI，原导入边界无需扩gate。

原七消费者模块83项旧82过/1G11失败223.66s，实际同83为82过/同失败213.35s；
另外原screen入口/状态44与AI loader3在实际同47过19.83s。
共130不同项129过/1原失败，无skip/error；旧结果不累加。G11原集合未列原A179的
AppHost optional _continuity_preparation消费者，安装前已失败；保持测试与gate原样。
三模块父进程源码guard旧28/actual37声明，各130nodes/260checks，旧3/actual2进程收据。
其范围是路径/SHA/19递归code字段，不证明子进程native冷导入。Ruff/project mypy两源过。
原warmup5项覆盖hint/切换/custom/partial/loaded，真实UI与prepared错误清理路线有据；
未独立覆盖notify错误、全部日志BaseException、失败缓存及同步close错误图，源证明补充
而非冒称测试穷尽。无新增test/probe/oracle/fixture/PR gate。

三独立设计与实际审阅、冻源manifest/逆AST/XML及基线失败说明保树外A190记录。
当前Code110316/Harness364480/HarnessTUI29466，C18为5源791，完整P1–P4仍开放。
