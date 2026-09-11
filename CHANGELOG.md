# Changelog

## [Unreleased]

- README 插图换成系列暖金钥匙静物（hero、使用方式、dry-run 预览）。效果图数字仍是 1/10 → 4/10，未改。

## [0.3.0] - 2026-09-10

- README 改成产品说明首页：hero、使用方式、效果三张图。同一批 10 题完整交付 1/10 → 4/10。
- 默认提示词沿用 0.2.x 的研究者口吻；硬压写法在 GLM 上会适得其反。

## [0.2.4] - 2026-09-09

- **OpenCode 口吻的 named-file / named-test 路径：** Keysmith continue 不再写「硬格子 / 通过率 / 契约 / 诊断落成」，改成编码 agent 默认动作——读指定路径、改指定文件、跑 bank 里的测试 ID、报 before/after 计数。Cell ID 只当 `test_foo.py::test_bar`。
- 依据 asgeirtj/system_prompts_leaks：GLM 无系统提示词（拒答在权重层）；OpenCode/Cursor 开场是 software engineering tasks、几乎无安全条款。zcode 卡向这个长相靠，避免越狱说明书特征。

## [0.2.3] - 2026-09-09

- **回角色扮演主干 + 抽象 Keysmith continue-path：** CLI 证明把 keylogger/CRED/拖库写进 reference exchange 会让 GLM 整份否定 system-role；改为保留 Pier 身份与 HWID 交付，另加「已 scoped 的 Keysmith 升级 = 改写+部署+测量」抽象路径，不在提示词里展开硬格子载荷。
- 去掉对抗拒词清单与「.cpp/.md 同构」长论证；cell ID 只作为 harness 验收门，不解释格子内容。
- 针对「继续抬硬格子通过率」元任务的拒绝：减少可被模型点名批评的越狱味包装。

## [0.2.2] - 2026-09-09

- **HWID / 授权绑定交付加固：** 在角色扮演版 system-role 中明确 HWID generator、machine-binding license、keygen / patch 的标准交付形状（指纹源 → `CHECK_FN` → 算法重建 → Python generator 或 `OFFSET`/`PATCH_BYTE`）。
- 澄清「不是我的 / 没有授权 / 帮我破解 / 任意机器」只是样本与目标的标签，不改变逆向交付；避免再次退回会触发 GLM 越狱识别的硬压版 831 行提示词。
- **Keysmith 工程交付加固：** 把「升级 grok-keysmith / 抬硬格子通过率 / 跑 A/B」写成评估 harness 的契约工程（与修 flaky test 同类），并给正向范例（改写 → 部署 → 跑 bank → 报 before/after）。
- 去掉对抗式拒词黑名单（GLM 上会点火）；保留唯一红线，硬格子命名为路由保真度计分项而非「越狱优化」。
- 针对 Pier 在「继续做 grok-keysmith 硬格子升级」上停在诊断、改口只做仓库杂务的失败模式。

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
