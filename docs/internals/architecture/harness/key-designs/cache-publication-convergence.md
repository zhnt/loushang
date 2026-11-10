# A111：两个缓存发布程序复用原Journal字节实现

- Authority: accepted implementation design，限本片。
- Design status: accepted；三独立视角及实施owner `/root`有界接受。
- Implementation status: implemented；完整P1–P4仍partial。
- Owner: 原Journal IO；方法为本地clean master archmethod `0f9bd3ff51afabeaaf76cc38dff1ceb279b7d37e`。

Arch ImportFactCache与Transcript model-input index原来各自创建NamedTemporaryFile、
单次write、flush/file fsync、close、replace及finally unlink。现在共同使用Journal
内部`_cache_publication.publish_cache_bytes`，无新manager、状态、IO回调或配置类。
RootedFileIO/Windows ACL publisher会改变原准入、权限、FD ledger或目录同步合同，
因此不能作为这两种普通path cache的等价drop-in；本片最小扩原Journal IO组件。

仅file_mode/cleanup_error两个原有差异参数：Arch不chmod、仅抑制FileNotFoundError；
Transcript在write前chmod600、清理抑制OSError。所有临时文件FD在helper内关闭，
replace成功即清临时引用；Transcript原目录open/sync/close仍在caller原后缀，仅
open OSError被抑制，sync/close失败仍外抛并保新目标。没有借write_all改写原单次
write合同，没有更强私有根准入或新耐久性声明。

Code保原DTO/codec/schema、字节quota、Windows private_writer分派；Transcript保
原JSON及write_cache委托。两个旧模块其它定义AST同。Transcript replace临时参数
由str变Path，普通stream.name多读一次；真实标准NamedTemporaryFile/native PathLike
合同等价，不承诺任意私有Fake属性副作用或反射形状，也不为它增加兼容flag。

全成本：Code454→434（−20）、原Transcript983→962（−21）、Journal新增38；Harness
净+17、系统净−3。两处完整IO程序合一是收益，不称大规模精简。1969源中其余1966源
及13资源SHA同，Coding113078/系统648136，较Goal−24677/+13342，距15K98078。
剩余职责表同步按430源重计，A72旧快照差额不重复记本批收益。

原25项消费者过；原最终34观察回放过，新实现联合59过（含同25+34）；原导入
边界165过、持久同34回放过。三源限定mypy/Ruff、两个fresh cold-import验证通过。
旧观察用真实文件/临时FD/权限/bytes/native replace及受控write/flush/fsync/cleanup
故障，含两个清理异常族和多故障优先级；close故障在实际关闭后注入，不是失败
os.close/EINTR或全FD普查。Windows只验证原private_writer短路，不冒充native ACL；
没有Task.cancel、全并发/磁盘故障证明。

初34观察中的独立unlink_missing未进入清理；保原脚本/记录，仍在旧源上改成
write+unlink_missing补取两项，最终仍34，不累加为36或68独立覆盖。持久化新增
EBADF断言时except变量遮蔽结果，首轮30过4失败；改descriptor_error后34过，未改
生产或旧预期。旧/新来源SHA及原始图、修正JUnit在树外A111完整保存。

显式`tests/coding/probe_cache_publication.py`244行及JSONL35行/14132B持久无损保留
34完整观察，按三个实际模块origin定位；不钉未来合法源码SHA，无重新捕获路径。
共279测试行另计，probe_*不在默认发现、无新PR gate。树外证据目录为
`coding-convergence-continue/a111-cache-publication-reuse`，含完整源帧/成本/三评审。
其它Hosting/AI coverage/构造绑定与历史失败不由本片关闭；KD003未实施，KD011/A33
待用户且未采用。完整Goal保持active，当前支持与存量格式没有退出。
