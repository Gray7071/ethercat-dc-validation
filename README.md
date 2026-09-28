# EtherCAT DC 实证诊断技能

用于 IgH/EtherCAT DC 收敛、首次进入 OP 慢、重复失锁及主站时序问题的诊断方法、历史案例与离线工具。

使用本技能**不要求修改 IgH 内核**。先核对版本、拓扑、周期与相位，再分析故障和曲线，按证据评估应用层策略，必要时才研究主站模块。

## 内容

- [技能入口](SKILL.md)：现场检查顺序、测量定义和操作边界。
- [现场流程与工具](references/field-workflow-and-tools.md)：采集/分析命令、输入格式及缺失数据处理。
- [单轴案例](references/validated-case.md)：时基、日志与发送路径。
- [多从站案例](references/multislave-startup-and-app-port.md)：初始化顺序控制（K4）与启动密集校时（B1）。
- [193 两站案例](references/case-193-phase-and-burst.md)：相位与策略组合的成功、失败记录。

K4/B1 是历史实验标签，不是 EtherCAT 标准术语或 IgH 官方开关。500 µs 相位、1 ms 周期和各案例收益均需结合现场验证。

## 给同事安装

本仓库为私有仓库，同事需先获得仓库访问权限并登录 GitHub。将整个仓库作为 `ethercat-dc-validation` 文件夹放入本机技能目录，保留 `references`、`scripts` 和 `agents` 子目录。

按当前 [Codex 官方技能说明](https://learn.chatgpt.com/docs/build-skills)，用户级目录为：

- Windows：`%USERPROFILE%\.agents\skills\ethercat-dc-validation`
- Linux/macOS：`~/.agents/skills/ethercat-dc-validation`

也可放到项目的 `.agents/skills/ethercat-dc-validation`。若机器已在其他受支持的目录装有同名技能，应更新已有副本，避免重复加载。
新安装未出现时重启 Codex。调用示例：

> 使用 $ethercat-dc-validation 检查本项目的 DC 收敛问题。先核对实际版本、拓扑、周期和相位，区分 OP 与 READY，先只读检查。

## 离线工具

Python 3.9+，仅使用标准库。在仓库根目录运行：

```sh
python -m unittest discover -s scripts -p test_tools.py
python scripts/collect_dc.py --help
python scripts/analyze_dc.py --help
```

工具支持已有文件归档、可选的一次性 Linux 只读状态快照、规范 CSV 和 Sophon r13 日志分析。
不启动控制程序，不发使能或运动，不修改主站模块。逐周期缺口需要完整逐周期记录，不能由 100 ms 遥测推算。

## 证据与限制

发布前运行 15 项离线回归；历史九轮 193 日志的 READY 和 READY 后 DC 峰值已复核。
本仓库保留案例摘要和来源哈希，不包含完整驱动源码、实验内核二进制、原始现场日志或登录凭据。
个人绝对路径替换为占位说明；没有原始归档时不能声称重新验证过硬件结果。

软件 DC 值不等同于物理 SYNC0 相位、ADC 采样瞬间或网卡出线 jitter。案例短时通过不保证每次冷启动、带负载运动或长期可靠性。
