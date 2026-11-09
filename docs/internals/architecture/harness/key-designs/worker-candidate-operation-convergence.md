# H-COD-KD-012：Worker候选操作共同程序归一

- Authority: accepted bounded internal refinement；由已授权Goal的实施owner `/root`接受，不替代用户图审。
- Design status: accepted R1；职责/复用、运行/失败、数据/兼容三独立视角及采用范围已记录。
- Implementation status: implemented bounded slice A27；五实际源接通并完成代码三视角，当前Code123062/系统638313。
- Owner: 原Package Product候选/生命周期协调；原Plugin Management、Resources、Worker事实权威不变。
- 需求：[Coding职责Goal](../coding-responsibility-convergence-goal.md) P1/P4；完整15K/系统净减不变。
- 方法：本地干净archmethod master `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`，未核上游。

## 1. 原有能力、重复与接缝

完整调查四Code模块2435行。Linux与Windows opt-in allow在原GC guard内有19条/82行完全相同的选择事实联接语句；两个CLI又有四份候选install/update的factory→runtime→原lifecycle→选择验证→dispose程序。不是把整个CLI或opt-in文件搬走：平台锁/根借用、native release解释、持久decision及重放/kill generation留原owner，参数语法、撤销前置要求、分类错误和JSON投影保Code。

原`verify_product_selected_worker_candidate`验证所选内容/声明/可执行格式，不读取当前Desired/GC crosswalk/committed事实，不能代替allow前的事实联接。原`submit_plugin_desired_command`有不同请求/响应校验；`run_package_lifecycle`会选新operation id及包装错误；`activate_package_product_runtime`会补验证/包装错误。不能强套它们改变原CAS、回放和失败合同。新程序只调用原Desired State、GC binding、committed journal、factory与lifecycle，不创建引擎、状态机、日志或第二权威。

两私有函数放原Package Product `product_worker_candidate.py`：

- `_capture_worker_opt_in_selection(product, plugin_id, *, product_id, error_type, error_prefix)`：在调用者已有GC guard内联接原事实，返回既有binding/admission，不授予opt-in或启动权。Code提供固定产品id、错误类型/前缀，均纯值；无Code IO callback。
- `_run_worker_candidate_lifecycle(product, binding, *, product_id, plugin_id, operation_id, session_id, action, label, entrypoint, selected_key, refresh_install_inventory, update_error_type, update_error_code)`：只执行两种既有生命周期命令与结果核验，返回原lifecycle及inventory revision。Code继续原前置policy/CAS/撤销条件和响应形状；特殊错误factory只构造值。

两函数消费原具体Core owner/record，新增参数均为窄值，不传argparse Namespace、大context、任意steps或service locator。`refresh_install_inventory=True`只固定绑定原Windows install的第二次snapshot，不成为CLI用户开关或新保证。所有完整接口成本计入；三视角已核为原组件内部细化，无新需用户接受的重要环境角色。

## 2. 运行、数据与失败合同

| 路径 | 保留的程序 |
| --- | --- |
| allow入口 | 原require_worker exact bool检查及GC guard在原Code；共同函数首原root-current→candidate筛选→key→snapshot/selection→binding/admission→crosswalk→committed→单节点限制。原19节点在名称/固定产品/错误前缀正规化后须逐AST相同 |
| 后续allow/revoke | 原两平台native release读/平台比对、generation/重复operation、decision构造与journal.change保持；Windows原root descriptor/末current，Linux原自身journal权限不互换 |
| CLI前置 | 原candidate matching、原installation筛选、精确已完成update/removal回放、opt-in撤销要求和状态拒绝保持在原位置；不把install/enable/update差异统一成更严准入 |
| 创建与失败 | 原session nonce在Code；helper内原factory(session,cwd,runtime id)→try构造原Request/create；失败先原dispose_unbound再原raise，cleanup异常仍覆盖。成功后原activate/route/installed核验/后snapshot与选择核验；始终原finally dispose_runtime，无新retry/rollback/包装 |
| 结果核验 | install仍按plugin/product/workspace选，update仍按原installation key；保原source/digest核验及Linux update的分类错误。Linux install/update和Windows update各一次后snapshot；Windows install原两次观察保持 |
| 输出与身份 | nonce、operation id、entrypoint、scope、真实record、ID/hash、decision/DTO的自有字段/FQN/构造不变；Code仅格式化返回的原事实，不把installed当Worker已使用 |

本次helper接收已解析CLI的普通字符串、以及原冻结Core binding/key；这些值在命令内稳定。原私有`_execute`里若人为使用副作用Namespace属性、在dispose回调中改Namespace、或热替换opt-in owner的私有_product，不承诺任意这些内部反射行为等价。未新增运行拒绝/类型检查来强制此约定。正常公开main(argv)字段取值和纯字典投影不产生IO，响应格式化在helper返回后，所有具效果操作仍在原异常/释放边界；不声称全Python属性读取次数相同。

helper为普通函数，无generator/新增Task、线程、锁或持久缓存。不能承诺已修复原close/未知结果或原事务非原子性；原部分失败由原store/原组件继续负责。

## 3. 成本、验证与接受

迁前Code opt-in223/240、CLI1098/874，共2435；接收Core65。候选Code147/164/1012/799，共2122（−313），Core255（+190），系统**−123**；含完整格式、接收类型/导入及薄适配。不按文件总长预估可删量。未知旧体/新接口成本未核前不接受，不以目录下降冒充净删。

树外`p4-worker-candidate-operations`冻结十原输入与1907生产源SHA。18726在原未改源、原wrapper/not-live/skip-host-runtime及指定磁盘runtime取得16过/2原skip、61.31s；只是原三个测试文件，不是候选行为或Windows原生证明。候选先Ruff/五显式shadow类型，固定旧两平台allow/四事务故障顺序与结果，再以五模块明确overlay对同旧期望/原测试比较。接口/其余定义/DTO AST、无Core反向依赖、完整成本及真实加载路径一并核验。

接受设计后才接入；实际源码再运行原受影响节点、补有限对照、做代码三视角并明确原生/并发/断电/性能局限。原测试/fixture及旧期望不重录，不新增平台、测试路线或PR gate。回退为四Code与同Core模块整套，保原数据/路径，不留Code fallback。KD008/KD011待用户图不因本片自动接受，完整Goal继续active。

## 4. 原程序差分与候选终态

32220在原冻结源码与未变Code值/端口绑定上排他捕获84份观察：32项完整allow方法、52项从四CLI事务提取的原factory/create/body/finally块。后者不包含完整CLI前置匹配/CAS/授权；native、GC/Desired及journal是声明端口，不是原生或真实权限证明。正常allow/replay/revoke-generation六组及四事务成功有明确result断言，负例另断言错误类别，再逐项比trace/结果/类型/code/context和primary/cleanup对象。

96953五模块明确overlay下，同84+原三个文件实际为100过/2原skip、71.14s；44047五真实模块路径/原保留定义/签名AST、19节点正规化与coldCore拒产品依赖3过8.54s。随后仅补强公开检查的inspect.signature/get_type_hints断言，54662该单节点通过4.76s；没有把早先未调用的工具误记为已验证，不为新增断言重跑其它已通过节点。所有五候选字节同被审frame，84旧JSON不重录。

观察覆盖各19节点首错、重放/冲突、四事务factory/Request/create/activate/route/后验/snapshot、dispose及覆盖、取消。Windows install两snapshot取不同revision11/12、结果保12；其余三路保11，Linux update原分类错误/code保持。有限差分与公开普通值边界支持内部采用就绪，不扩为所有Python反射、真实native、所有故障交错或完整Goal。此处为采用前检查点，未据候选结果预记实际接受；实际接入和代码三视角终态见下节。

## 5. A27实际接入与三视角代码接受

五源逐字接入已接受候选，1907份生产源中其余1902逐SHA保持，无新增生产文件；原三个测试文件及84份排他捕获的旧JSON未改。迁前Code123375/系统638436，实际Code**123062**/系统**638313**，本片Code−313/接收+190/**系统净−123**。累计Coding减14693（10.7%），距15K仍108062，系统仍高于634794起点3519；不能据本片净减宣布完整Goal完成。

8101在实际工作树、无候选overlay，经原managed wrapper、原not-live/skip-host-runtime与指定磁盘runtime取得**103过/2原skip，144.93s，exit0**。105节点由84旧程序观察、3实际公开面/真实模块路径/AST/冷Core检查及原三个文件18节点组成，不与候选/旧捕获重复累计。公开面节点实际执行inspect.signature/get_type_hints；两skip为原跨进程operator和native Windows节点，仍未验证原生授权。52事务观察使用原AST块及声明端口，不是整个CLI前置/CAS或完整授权的运行证明。

52224五实际显式源silent/no-incremental类型与23072原依赖生成检查均exit0，Ruff/format在实际运行前通过且源未再变化。不是全依赖图、并发、断电或性能证明。三独立实际静态报告及各自终态补件均无本片剩余具体阻断，实施owner `/root`接受这一原Package Product内部替换及所列证据边界；不替用户接受KD008/KD011，不销其它旧失败，不接受完整P1/P4或Goal。

原件、候选、旧观察、真实XML、完整成本与实际源指纹、三设计/三代码视角及接受记录保存在产品树外 `p4-worker-candidate-operations`。原pending报告保持，终态单独补存；未新增gate/测试路线/平台，未修改原持久格式。
