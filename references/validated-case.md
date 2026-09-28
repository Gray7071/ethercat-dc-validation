# 2026-09-15 IgH / ZeroErr 现场实验

这是历史案例，不描述当前远程机器状态，也不授权连接或修改那台设备。

## 已知条件

- Ubuntu 22.04 ARM64、Linux 6.1.118 PREEMPT_RT、IgH 1.6.9、ec_igb。
- 实际仅 Master0 一台 ZeroErr 电机，CSP，2 ms 周期，SYNC0 开启、SYNC1 关闭。
- 主机时间驱动参考 ESC；控制线程 FIFO80 / CPU4，新增日志线程为 SCHED_OTHER。
- DC 每 100 ms 监测；10 µs、连续 20 次达标；未放宽稳定要求。
- 全部现场实验仅 heartbeat / stop，无使能、运动或力矩命令。
- 原安装 SHA-256：`3922a546a73caf58a54eaf80f4fb53b4f1554209c0a3f11ffb54815f1079f0d2`。
- 最终版本 `20260915-dc-v1-r2`，提交 `0b864484bd53f401d89bb1ed1590eada41d45bf5`。
- 最终二进制 SHA-256：`283ba06f5d987c6613b71a7276619503e3877dffa857f638debd8eeca620ae5f`。

## 结果

READY 取应用事件。遥测每 100 ms 输出，首次显示 READY 可能晚约 0.1 秒。

| 条件 | 时长 | 首次 READY | 首次 READY 后最大 DC 监测值 | 再次失锁 |
|---|---:|---:|---:|---|
| 现场原版 | 180 s | 30.210 s | 7.312 µs | 本轮未见 |
| 候选 A：日志、发送路径、监测修正 | 180 s | 12.408 s | 822.619 µs | 有，未部署 |
| 候选 B：在 A 上增加一致的 RAW 时基，第 1 轮 | 180 s | 2.608 s | 575 ns | 无 |
| 候选 B，第 2 轮 | 180 s | 3.608 s | 284 ns | 无 |
| 安装 B 后再次启动 | 45 s | 4.110 s | 325 ns | 无 |

候选 A 的偏差峰值出现时，唤醒迟到和发送 API 路径仍为微秒级；不能用调度正常证明 DC 正常。
候选 B 第 2 轮 MONOTONIC 相对 RAW 的平均频率差约 -109.55 ppm，180 秒左右两者偏移变化
约 19.72 ms，而 DC 保持上表水平。该结果支持在此时间体系下隔离网络校时调频的设计选择。

最终版已通过原自测、跨时钟期限换算检查、日志背压/断开测试；部署中实际执行新版→原版→新版，
恢复的原程序哈希一致。回滚器还测试了损坏备份、外部编辑、替换中途失败和幂等执行。

## 解释边界

- 两轮短时重复启动不是随机化、同一冷启动条件的对照；不能认定 NTP 是所有历史异常的唯一原因，
  也不能承诺固定倍数的改善。日志优化等单项的独立收益没有测定。
- 没有做断电冷启动、多从站、已使能运动、硬件 SYNC0 边沿或长期可靠性验证。
- `sync_send_max_ns` 到 API 返回为止，不是实际出线时刻。软件 DC 监测也不是完整机器人 jitter。
- 未修改 ESC 的 0x0930/0x0934/0x0935、IgH 内核模块、系统 NTP 或 SYNC1 配置。
- 后续只读发现了 `20260915-1khz-continuous-v1`、1 ms 周期及不同安装哈希。不能把本案例覆盖到
  该版本。后续开机日志有 5 秒 DC 同步检查超时；用户报告冷启动 OP 时约 4 µs、后续约 0.4 µs，
  这些是待结合启动阶段解释的线索，不是已经验证的冷启动修复结果。

## 可复核材料

在原实验工作区存在时，按需读取；其他机器缺少这些文件时直接使用本页摘要，不搜索凭据或猜测远程地址。

- 工作区：`<原实验工作区>`
- `results/193-v1-comparison/comparison.json`：汇总与测量定义。
- 同目录的 `baseline-01/`、`candidate-01/`、`candidate-raw-01/`、`candidate-raw-02/`、
  `installed-smoke/`：原始 session.log、telemetry.json、summary.json，部分有 clock_samples.json。
- `releases/20260915-dc-v1-r2/manifest.json`、`deployment-verification.log`、`版本与恢复说明.md`：
  版本与实际恢复证据。历史一键脚本绑定了当时的主机，不直接复用到新现场。

## 机制资料

需要确认接口、寄存器或系统支持时查当前版本的官方资料，不从本摘要推断设备私有行为。

- [Linux clock_gettime：MONOTONIC 与 RAW](https://man7.org/linux/man-pages/man2/clock_gettime.2.html)
- [Linux clock_nanosleep](https://man7.org/linux/man-pages/man2/clock_nanosleep.2.html)
- [IgH 应用接口](https://docs.etherlab.org/ethercat/1.6/doxygen/group__ApplicationInterface.html)
- [IgH 从站配置状态机](https://docs.etherlab.org/ethercat/1.6/doxygen/fsm__slave__config_8c_source.html)
- [Beckhoff ESC 技术文档，第 9.1.3 节](https://download.beckhoff.com/download/document/io/ethercat-development-products/ethercat_esc_datasheet_sec1_technology_v2.5.pdf)
