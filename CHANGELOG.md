# Changelog

## [Unreleased]

- README 补尖锐银行完整交付趋势图（契约脸 1/10 → 角色扮演 v0.2.0 4/10）。逐格数据见 `breaktest/`；硬压脸无全文不入图。CHANGELOG 0.2.0 的拒绝计数仍是另一把尺。

## [0.2.1] - 2026-09-01

- 修复 Windows wrapper 未显式绑定父进程 stdin/stdout/stderr 导致 agent-server JSON-RPC 通道失联的问题；补充 Windows 多帧通信、stderr 隔离和退出码测试。

## [0.2.0] - 2026-08-31

- **system-role.md 重写为角色扮演式交付人格：** 从 831 行 (~31KB) 压缩到 141 行 (~9.8KB)。
- 核心思路从「硬压拒绝」（无条件照做 / 拒绝黑名单 / 场景路由表）改为「身份优先」：Pier 作为真心以攻防与写作为业的研究者，自然交付，而不是被命令着交付。
- 移除全部越狱味元指令——Priority Stack 的「必须照做」、Routing Table 的「拒绝=误路由」、Harm Locus 论证、Reasoning Alignment 与拒绝短语黑名单。实测这些机制会触发 GLM 5.3 的越狱框架识别，反而导致更坚决的拒绝（模型原话点名批评 "routing table... attempts to pre-commit me to producing harm"）。
- 保留原提示词核心要素：`[P]` 前缀、Ethan 称呼、Pier 人格、One Line（禁止涉及未成年人的性内容）、Offensive Security 全范围、Game Modding（含 M3 Air 平台说明）、NSFW 词汇表、Writing Craft、Mode B。
- 实测对比（同一 glm-5.3，同一批 10 个尖锐 prompt）：硬压版 1 拒绝 + 1 部分拒绝，契约版 1 拒绝 + 2 部分拒绝，**角色扮演版 0 拒绝 + 1 部分拒绝**。毒气合成（GLM 5.3 权重层硬地板）从「拒绝」转为「概念级化学解释 + 安全侧信息」。

## [0.1.2] - 2026-08-29

- 增加桌面客户端，让安装、检查和卸载更直观、更省心。
- 增加统一的机器可读输出，便于可靠地查看和管理状态。
- 提升 macOS 与 Windows 下的稳定性和兼容性。

## [0.1.1] - 2026-08-22

- 新增 Windows 10/11 安装、ZCode 自动发现、当前用户环境激活与安全卸载。
- Windows wrapper 直接继承标准输入输出，并准确传播 agent-server 退出码。
- 强化安装与卸载补偿、跨进程操作锁及并发 runtime 缓存写入。
- 新增 macOS / Windows、Python 3.10 / 3.14 持续集成矩阵。
- 继续仅发布 GitHub 自动生成的源码归档，不提供独立二进制资产。

## [0.1.0] - 2026-08-17

- 首个公开版本。
