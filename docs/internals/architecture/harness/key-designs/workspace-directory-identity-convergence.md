# 四消费者完整工作区目录身份协议 A195

状态：本批有界接受；完整Coding重构仍partial。2026-11-14。

原[read SDK](../../../../../src/loushang/coding/plugin_manager/read_sdk.py)、
[command SDK](../../../../../src/loushang/coding/plugin_manager/command_sdk.py)、
[backup SDK](../../../../../src/loushang/coding/package/private_data_backup_sdk.py)三份18行guard，
以及[private read owner](../../../../../src/loushang/coding/package/private_data_read_owner.py)的12行函数，
共66方法span，是同一完整程序的四个生产实现。原[Workspace路径组件](../../../../../src/loushang/harness/workspace/paths.py)
已有路径解析/规范化，但没有相同strict/身份/错误合同，故最小扩充一个固定身份检查入口。

完整顺序：lstat和resolve(strict=True)都先执行，try仅覆盖这两个操作；OSError在原点
由Code错误工厂创建原错误并from原异常。随后依原短路检查目录、canonical path与dev/ino，
此处失败不新增cause。Code保原Error类/message/code及wrapper签名；lambda失败时晚查
Code error global，无业务选择/IO回调。无新状态/锁/Role/T/validation。CLI captureNone先
检查身份再resolve、Windows先dir再resolve且不catch是不同合同，均保原样。

四producer只留一份kernel，退出三份实际重复。全税Code−29/Harness+21/系统−8，
raw=uniform：SDK283→275、226→218、334→326，reader283→278，paths101→122。
导入、lambda、typing/doc均计。四wrapper逆实参/错误factory AST同，其余四Code整源
及Core原定义AST保持。字段/validators/dataclass bases/MRO不改。SDK值参数在入口读取，
旧版重复字段读取的可观察时点不同；实际frozen Path/tuple值合同保持，不承诺自定义
副作用getter/低层字段突变观测等价。函数/异常栈帧与实现位置变化明示。

五原测试模块的既有针对节点：SDK查询/command/CLI工作区替换、owner bind/open后替换、
pending恢复、backup/read离线状态与Core paths。旧34过115.30s、实际同34过121.46s，
各142 deselected，0fail/error/skip，不累计为68覆盖。无新增测试、probe/oracle、fixture或gate。
五模块父进程来源守卫旧65/actual66声明、各34nodes/68checks，phase/PID分立，比较路径/
SHA及19递归code字段。不是子进程native/cold import来源审计；没有独立逐点权限或Error
构造失败/任意getter/所有并发复合故障证明。实际project mypy五源/Ruff通过，不称fullstrict。

三独立设计与实际审阅、冻源manifest/逆AST/原同组XML及frame保树外A195证据。
2059源仅五源改变；当前Code110287/Harness364501，C06为26源4444/C08为31源6665，
source659818，排GUI独立4524后655294。完整P1–P4/KD003/KD011与≤15K仍未完成。
