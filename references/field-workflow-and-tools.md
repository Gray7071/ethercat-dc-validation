# 现场检查顺序、故障分类与离线工具

## 先查配置，再评估策略

1. **现场身份与拓扑**：确认安装二进制/源码/模块版本、实际主站、各站身份和枚举位置、端口方向、
   参考时钟、已有会话及是否实际断电。保留基线，不以 IP 或旧记录替代当前身份检查。
2. **周期与相位配置**：列出每站 AssignActivate、PDO 周期、SYNC0/1 周期和 shift、工作模式及设备要求。
   结合 ESI、应用传参和运行时状态核对。DC 时间对齐与 PDO 到达/设备采样窗口是不同问题；
   DC 数值很好但某站不能 OP 时，优先检查它的周期、相位、数据有效性及 AL 错误，先别增加校时频率。
   依据设备时序评估相位候选；每轮记录完整组合和改动项，不盲扫所有相位、不默认半周期正确。
3. **分阶段故障和曲线**：记录初始化、请求 OP、全站 OP、应用 READY、持续运行、停止和释放；
   DC、逐站状态、各 domain WKC、驱动错误、邮箱事件、周期记录同轮留存。先处理无法进 OP 的配置故障，
   不把低 DC 值计为全系统通过。画曲线需标明时间原点和采样间隔。
4. **应用层策略**：在配置匹配基础上评估统一时基、固定发送位置、实时调度/日志和有界密集校时。
   比较同条件基线，保持控制周期与验收窗口；额外发送可能影响配置交互和看门狗。
5. **必要时研究主站模块**：证据指向 offset 初始化与周期同步交互时才评估 K4 类修改。
   先评估改动影响范围、模块兼容性和回滚；无证据时不把内核修改当默认第一步。

配置表至少记录：从站身份/固件、位置、参考站、PDO/SYNC0/SYNC1 周期、各 shift、AssignActivate、
DC 时基与同步方向、burst 开关/窗口/时隙、驱动与模块哈希、冷/热启动条件、验收阈值/稳定窗口。
一次改变多个参数只支持组合效果；需要定位贡献时再做有界消融对照。

## 不同故障使用不同记录

| 类型 | 记录内容与下一步 |
|---|---|
| 驱动错误，如 0xA000 | 记录厂家/型号/固件、0x603F/状态字或实际错误来源、首次出现时间及上次遗留可能性。含义以厂商资料为准，不将它解释为通用 EtherCAT AL 码；未确认前不自动故障复位。 |
| EtherCAT AL 0x001A | 记录对应从站、状态转换、周期/相位/PDO 条件。它表示同步错误，不能仅凭代码断言时钟漂移或主机调度是根因。 |
| SDO/邮箱超时 | 记录对象索引、上传/下载方向、发起方、所在阶段、返回码及同轮链路/状态。区分启动配置与 OP 后读回，不把全部 SDO 禁用当通用修复。 |
| 停止/释放后的错误 | 仍保留原始记录，单列阶段；不能算作运行期间失锁，也不能从整轮日志删除。 |

[Beckhoff 对 AL 0x001A 的说明](https://infosys.beckhoff.com/content/1033/ethercatsystem/1072492555.html)
指出其为同步错误，并不唯一确定具体原因。

## 附带工具：Python 3.9+，仅标准库

工具相对路径从技能目录运行。它们不启动后端、不请求 OP、不写寄存器、不发使能/运动，也不管理远程登录。
现场实时采集必须复用应用的非实时日志线程/有界队列；不要在 1 ms 线程中调用 Python 或逐周期写文件。

### 采集已有日志和配置

```sh
python scripts/collect_dc.py --file session.jsonl --file states.json --file kernel-new.log --metadata config.json --out run-001-bundle
```

逐文件复制、计算 SHA256、检测复制期间源文件变化，生成 manifest.json；不覆盖已有目录。
优先使用停止写入的文件。config.json 是现场自填的 JSON 对象，按上面的配置表记录，未知项写 null，
不要包含账号密码。不要把正在变化的内存映射环形缓冲直接当成一致快照；需应用支持冻结或一致性读取。

在 Linux 现场可加 `--snapshot-master 1`，只执行一次 `uname`、`ethercat version`、`modinfo ec_master`、
该主站的 `master`/`slaves -v` 只读查询，单命令限时 5 秒，不调用 sudo；无权限/命令缺失如实记入清单。
这是状态快照，不是高频 DC 采样。只在已获准读取的现场运行；本次维护仅测试离线文件采集，未连接设备。

### 通用 CSV 分析

```sh
python scripts/analyze_dc.py samples.csv --dc-limit-ns 10000 --stable-seconds 2 --max-observation-gap-s 0.15 --out report.json
```

门槛必须按现场填写，示例值不是默认验收标准。CSV 一行一个同步观察，必须包含以下列，未知字段留空：

```csv
time_s,all_op,wkc,wkc_expected,dc_ns,dc_valid,dc_fresh,ready,phase,al_code,drive_error,cycle,cycle_time_ns
0.0,0,0,6,,0,1,0,initialization,0x0000,0x0000,,
0.1,1,6,6,500,1,1,0,run,0x0000,0x0000,,
```

- time_s：同一次运行、同一时间原点的秒数，严格递增；不要混入 UTC 或其他开机的单调时钟。
- all_op：所有预期站均 OP 且无 AL 错误为 1；缺站为 0，状态没采到留空。布尔列只接受 0/1 或 true/false。
- wkc/wkc_expected：同一时刻、同一组 domain 的实际与期望值；多个 domain 必须各自核对后统一记录，
  不用单电机 WKC 代表联合总线。不能从从站数量猜期望 WKC。
- dc_ns、dc_valid：有明确来源和有效性的 DC 读数；dc_fresh 仅在确认为新样本时为 1，缓存重复为 0，
  缺少样本序号/采样事件证据则留空。持续达标只累计新鲜有效观察，缺失、失败、超阈或观察缺口会重置窗口。
- ready：应用实际 READY 状态，与独立计算的联合达标时间分开。阶段 phase 可用 initialization/run/stopping/released/after_release；
  后三种不纳入运行段指标。未知阶段保留 unknown，不能擅自排除故障。
- al_code、drive_error：已解码的非负错误码，支持十进制或 0x；原始 0x092C 的符号格式应由采集器正确解码，
  不将无效哨兵值当小偏差。多站错误保留逐站原始事件，不能用本表的单列替代完整记录。
- cycle/cycle_time_ns：可选的完整逐周期记录号和软件生产时间戳。只有每个周期都记录时才加
  `--every-cycle --period-ns 1000000`；报告记录缺口、间隔极值/平均值及连续周期偏差。
  100 ms 遥测中 cycle 每次加 100 是降采样，不能报 99 个周期丢失。记录缺口也不能直接称为网线上丢帧。

输出包含首次全 OP、应用 READY、独立联合达标时间、运行段/READY 后/联合达标后 DC 峰值、
无效与缺失计数、WKC 异常、OP 异常、观察缺口、可用时的周期缺口和分类故障；后续失锁不被删掉。
联合窗口以首尾观察覆盖的时间计算，不把 20 个 100 ms 样本机械等同为恰好 2 秒，也不代替应用原门槛。
报告不自动判“通过”：缺少逐站故障、工作模式、冷启动条件或硬件同步证据时需人工补充验收。

可加 `--kernel-log kernel-new.log`，分类 AL/邮箱/其他诊断，并标记释放前后。
输入必须已隔离到本轮；脚本不猜不同日志时钟的换算，无法确定的故障阶段标为未知。

### 193 r13 已有日志适配

```sh
python scripts/analyze_dc.py evidence/final-check-01 --format sophon-r13 --motor-wkc 3 --sensor-wkc 3 --dc-limit-ns 10000 --stable-seconds 2 --max-observation-gap-s 0.15 --kernel-log evidence/final-check-01/kernel-new.log --out final-check-report.json
```

专门支持 193 r13 的 session.jsonl 格式，使用进程启动后的外部观察时间；motor TELEM 与不超过 150 ms 的
最近传感器遥测合并。其全 OP 时间与 200 ms CLI 轮询略有差异，不能混用。这份日志没有 DC 样本序号，
因此独立联合达标时间输出 null，保留应用 READY；不虚构新鲜度。它也不是每周期采集，周期缺口标为不可用。
原始周期数据的独立核验结果见 193 案例，不能伪装成本适配器重新测得。

执行离线回归：`python -m unittest discover -s scripts -p test_tools.py`。
