# Private Journal的完整操作scope

状态：A201实际有界接受，2026-11-15；完整Coding Goal仍开放。
方法咨询本地archmethod master 0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e，非上游同步声明。

## 职责及现有接口缺口

G10 Code继续拥有enabled/selection-generation/history/admission、原名义record/snapshot/error、
codec和Product机器路径；Harness Journal拥有中性持锁/strict读写机制。原JsonlJournal已有
load/append/append_batch/rewrite代理，但无完整private检查/同线程async等待/跨consumer保锁；直接继承还会写
self.path，与原Code readonly property冲突。DirectoryLease、rooted IO与path-admission均有
不同authority/异常/owner回退/缺失合同，不用更强IO或新mode池强替。

原Journal family增加_PrivateJournalOperations[RecordT,SnapshotT]，same-self只有原_path、
_unlocked_durability、_load_policy三个字段，直接调用原filelock/load/append。Code保8typed
公开返回门面、Ctor/path，以及pure codec/history/fold/transition/admission/error和profile。
不新增Role、manager、Task、selector、第二对象/状态，Core不读enabled/generation。

## 成功、失败及退出

同步snapshot的initial exists在try外，false直接虚拟值；later FNF可回退。async initial缺失
亦直接回退并跳timeout资格，但进入后FNF不catch。load初始exists仍在corrupt catch外，
实际load与Code history validator在catch内，Snapshot fold在外；不拓宽错误映射。

mutation先在Code按原顺序验证operation-id/目标，Core持独占scope后load并问pure decision。
Code返回(record或None, lateResult, late旧errorContext)；同state幂等保原对象，不新做opID
去重。Record构造仍append前、成功Snapshot仍append后、旧generation仅append失败时读取。
Core只在record存在时写一条，使用原strict/no-nested-lock profiles；未知write结果不自动重试。

private scope为原optional mkdir→private检查→filelock→取锁成功后且yield前再检查→consumer→
退出。没有body后postcheck或新pinning。sync consumer OSError会经原CM映射storage_unsafe；
async finally显式context.__exit__(None,None,None)，不把consumer异常注入sync CM。保此差异。
async轮询只重试LockUnavailable、原loop.time deadline/min(0.01,remaining)，同线程enter/exit，
不换executor或额外Task。admitted scope跨完整原run/cleanup结清，回滚不能穿过该锁。

## 全税、兼容与限定

Code567→419（−148），Core0→284，raw=uniform系统+136；全部2T、typed门面、纯policy/
late factory、错误/profile/import成本已计，是完整职责归位，非系统精简或第二引擎去重。
Code pure政策不因唯一consumer而移到Core。G10四文件1767→1619，原1800预算、所有gate
覆盖/触发/平台/路由/断言未改。新private base/MRO、属性/CM帧及纯profile绑定是明确实现
演进，不声称全反射/任意私global替换/异常栈字节一致；公开record/frozen slots/FQN不改。

原六载体34旧/实际同序全过（35.68/38.85s），含installed native-run；取消用例是注入
BlockingHost上的真实Task.cancel、组合结清与真实control锁，不外推native child取消。
五个新局部观察先old再actual全过（2.86/5.81s），JSON错误图/持久wire SHA一致，覆盖
sync/async consumer OSError、initialexists后私scope入口FNF、append后结果Ctor失败。
JSON仅比类型/消息/code/generation/cause/context/suppress，不含identity/notes/traceback。
五项与原34分列；外部故障支持80行、有限API/冷观察21行单列，产品测试源码0增、
无新fixture/PR gate。未覆盖所有Stop*/GeneratorExit/多重native close失败。

来源守卫主套old3mod143decl/actual4mod163decl，各34nodes/68checks；局部套各5nodes/
10checks，parent路径/SHA/19递归code字段不证明installed子进程来源或生成函数。有限API
进程另记自身source路径/SHA，10public signature/resolved hints与2DTO fields/slots/FQN同；
冷11→12只加新Core，不作所有import effect结论。实际mypy2/Ruff/格式及58source proof过。

当前计量见[清单](../coding-responsibility-inventory.md)，接受与剩余见[进度](../coding-responsibility-convergence-progress.md)。
完整P1–P4/KD003/KD011仍开放，C05其余内容/验证政策不据本批判定永久下界。
