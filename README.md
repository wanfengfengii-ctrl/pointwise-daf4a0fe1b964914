# 澄湾计量质控数仓

澄湾计量资料室接收仪器按业务日导出的批次。接入员保存原件，校正员按校准单登记偏移，白班根据固定日表挑选复核明细，夜班按原摘录号重印。同标签、同读数的两次采集是两个实际出现。后续校正会生成新日表修订，已经发出的呈现和用于核账的历史日表仍可读取。

## 运行

使用 Python 3.11 和标准库。平台提供 `check_project.py`，标准入口运行完整 `tests` 包。

```sh
python3 -B check_project.py
python3 -B demo.py
python3 -B range_examples.py
```

`check_project.py` 先跑完整 `tests` 包，再联合运行 `range_examples.py` 的分段场景，任一检查失败即以非零状态退出。

演示只在测试临时目录创建工作库。它按 B、A 接纳两条原读数 100，随后登记 G 组偏移 10 和 B 的绝对覆盖 2。按 A、B 排列的新日表为 110、102，总和为 212。阈值 102 只选出 A。白班把 B、A、B 发给夜班。校正员清除 B 的覆盖后，新日表为 110、110。关闭重开后，夜班仍读到原摘录的 102、110、102。演示还调用 `range_examples.py` 的按序位场景，展示空段撤单被拒、失败提交后重试、迟到序位 18 读为 109 以及关闭重开后的原摘录。演示核对实际结果后才输出场景数据，任何差异都会使进程以非零状态结束。

## Python 接口

`warehouse.open_store(path)` 打开或初始化 SQLite 工作库，返回连接。调用方负责关闭连接。`initialize_store(db)` 可以在已有工作连接上重复运行，保留已提交的数据。下面的业务接口自行管理事务，须在调用方没有活动事务时调用。

- `accept_batch(db, batch_id, day, observations)` 接纳有序 `Observation(occurrence_id, group_id, label, raw_value, can_override, source_sequence=None)` 序列，返回首修订号。批号在仓内唯一。完全相同的重投领取原修订，业务日、行序或任一字段（含可缺省的仪器序位）有差异则拒绝。已给序位须为非负 Python 整数且布尔值非法，在同日同组跨批唯一；同一批内同日同组同序位也拒绝。不同日、不同组可复用同序位，未给序位的原件可任意共存。空序列同样可以登记为批次。
- `set_range_offset(db, day, expected_revision, group_id, ticket_id, interval)` 按采集序位登记或撤回分段校准，返回新修订号，是 `RANGES.md` 定义的新接口。`interval=(lo, hi, priority, offset)` 登记 `[lo, hi)` 区间（四项均为非布尔整数，`0 <= lo < hi`，数字较大的优先级优先），`interval=None` 撤回该单号。单号只在同日同组的在效单中唯一，撤回后可再次登记。提交前校验覆盖区间内所有潜在序位在最高优先级处只给出一个偏移值，包括当天尚无原件的序位；非法输入、未知组、过期日头、单号冲突、未知在效单或歧义抛 `ValueError`，失败不留变更。
- `get_day_head(db, day)` 返回该日最新修订，没有正式接纳或校正时返回 `None`。原件核账可用 `find_batch(db, batch_id)` 获取含日和首修订的批头，再以 `load_batch_payload(db, header)` 读取原序观察。
- `set_offsets(db, day, expected_revision, group_offsets=None, overrides=None)` 提交显式校正，返回新修订号。两个参数均为按键映射。组偏移须为整数，覆盖映射的整数为绝对偏移，`None` 值表示清除。省略键时保留已有设置。空校准单可以登记一个无动作修订。预期修订须为该日日头。`read_correction_audit(db, revision)` 返回该次登记的组设值和逐行设值或清除。
- `inspect_day(db, day, revision, threshold)` 返回 `DayInspection`，包含 `rows`、`groups`、`exceedances` 以及日、正式修订和阈值。修订号是固定读取的全仓上界，业务日独立筛选。日表和超阈明细按出现 ID 排列，组汇总按组键排列。
- `issue_report(db, day, revision, occurrence_ids)` 返回普通摘录号和冻结的标签、有效值序列。选择必须在指定日和修订可见。重复选择和空序列均保留。`read_report(db, report_id)` 返回摘录号、源修订和原序呈现。交班时用业务日和源修订对照固定日表。

业务日采用真实的 `YYYY-MM-DD` 日期，标识和标签为非空 UTF-8 文本。读数、偏移和阈值为带符号 Python 整数，单位为毫单位。覆盖资格为布尔值。固定日表的逐行偏移优先级为：合资格行的绝对覆盖（显式零也算）、命中分段区间的序位最高层偏移、整组偏移（缺省为零）。分段偏移是相对原值的完整偏移，不与整组偏移相加；锁行仍可采用分段偏移，只是不能逐行覆盖。原值、校正和呈现采用十六进制文本无损存储，计算在 Python 整数域进行。空日返回空明细、空汇总和空超阈明细。

非法字段、未知对象、过期修订或不合资格的校正抛 `ValueError`。SQLite 存储错误原样传播。批次和校正的业务写入、正式修订与日头一起提交，摘录头和呈现行一起归档。校正审计只返回正式校正修订中的登记动作。
