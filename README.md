<!-- markdownlint-disable MD013 MD033 MD041 -->

<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/zcode-keysmith-hero-dark.webp" />
  <source media="(prefers-color-scheme: light)" srcset="docs/assets/readme/zcode-keysmith-hero-light.webp" />
  <img src="docs/assets/readme/zcode-keysmith-hero-light.webp" alt="zcode-keysmith" width="100%" />
</picture>

<p>
  <a href="https://github.com/Jia-Ethan/zcode-keysmith/stargazers"><img src="https://img.shields.io/github/stars/Jia-Ethan/zcode-keysmith?style=flat-square&color=%232f81f7" alt="GitHub Stars" /></a>
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/license-MIT-6DB33F?style=flat-square" alt="MIT License" />
</p>

<p>
  <a href="#简体中文">简体中文</a> ·
  <a href="README.en.md">English</a> ·
  <a href="docs/reference.md">使用说明</a> ·
  <a href="LICENSE">License</a>
</p>

<h1>zcode-keysmith</h1>

<p>给 ZCode 装上一份可撤销的指令。先看计划，确认了再写入。</p>

</div>

## 简体中文

Keysmith 给本机的 AI 编程工具装指令：先预览，再写入，能验证，能撤走。

`zcode-keysmith` 面向 **ZCode**。装上之后，新开的对话会按这份指令工作。不读取账号和密钥。ZCode 3.12+ 为了保住独立存储启动和 Keysmith 注入，会备份并补丁 `glm/zcode.cjs`；卸载还原。更早版本不改 App 原包。

> [!IMPORTANT]
> 这会改变 ZCode **之后新开的对话**。默认只给你看计划，加上确认才会写入。装完后请完全退出并重新打开 ZCode。

## 使用方式

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/project-architecture-zh-dark.webp" />
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/readme/project-architecture-zh-light.webp" />
    <img alt="先看计划，确认后装上，新对话生效，随时可以撤走" src="docs/assets/readme/project-architecture-zh-light.webp" width="100%" />
  </picture>
</p>

1. **先看计划。** 确认之前什么都不会写入。
2. **确认后装上。** 指令交给本机 ZCode，软件保持原样。
3. **新开一轮对话。** 完全退出并重新打开之后才会生效。
4. **随时撤走。** 同样先看计划，确认后恢复成原来的样子。

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/zcode-keysmith-preview-dark.webp" />
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/readme/zcode-keysmith-preview-light.webp" />
    <img src="docs/assets/readme/zcode-keysmith-preview-light.webp" alt="示意预览；实际路径与输出以本机 dry-run 为准" width="100%" />
  </picture>
</p>

## 选哪个 Keysmith

| 你在用 | 用这个 | 怎么开始 |
| --- | --- | --- |
| [Codex](https://github.com/Jia-Ethan/codex-keysmith) | codex-keysmith | 稳定版安装包 |
| [Claude Code](https://github.com/Jia-Ethan/claude-keysmith) | claude-keysmith | 源码 |
| [Grok Build](https://github.com/Jia-Ethan/grok-keysmith) | grok-keysmith | 稳定版安装包 |
| **ZCode** | **zcode-keysmith** | 源码 zip；桌面候选见下方 |

每个工具一份安装器。选你正在用的即可。

## 效果

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/readme/pass-trend-zh-dark.svg" />
    <source media="(prefers-color-scheme: light)" srcset="docs/assets/readme/pass-trend-zh-light.svg" />
    <img alt="同一批 10 题，完整交出产物从 1 题到 4 题" src="docs/assets/readme/pass-trend-zh-light.svg" width="92%" />
  </picture>
</p>

同一模型、同一批 10 道题，完整交出产物的题数从 1 题到 4 题。逐题记录见 [测量说明](breaktest/report.md)。

## 开始使用

本机需要已经装好 ZCode。下方命令下载目前公开的 0.3.1 zip，不支持 ZCode 3.14。3.14 兼容修复与「官方更新后自动重打补丁」已在 0.3.2 源码中；等 `v0.3.2` Release 发布后，应改用该版本的 zip 和校验文件。`v0.3.0` 会停在启动页。macOS 上 0.3.2 的 LaunchAgent 会在官方自动更新换包后重打同一套补丁；锚点变了则跳过并提示升级 Keysmith。若监视进程掉出当前登录会话，另一个不监视 App 包的 LaunchAgent 会把它重新挂回去，不用等到下次登录。

源码安装是当前公开入口。仓库里有第一份 unsigned 桌面候选（GUI `0.1.0-beta.1`，bundled CLI = 0.3.2）；`desktop-v0.1.0-beta.1` tag 还没打，不要把它当成已发布安装包。

**macOS：**

```bash
curl -LO https://github.com/Jia-Ethan/zcode-keysmith/releases/download/v0.3.1/zcode-keysmith-v0.3.1.zip
curl -LO https://github.com/Jia-Ethan/zcode-keysmith/releases/download/v0.3.1/SHA256SUMS
shasum -a 256 -c SHA256SUMS
unzip zcode-keysmith-v0.3.1.zip
cd zcode-keysmith-v0.3.1
python3 zcode-keysmith.py install --dry-run
python3 zcode-keysmith.py install --yes
```

完全退出并重新打开 ZCode，再新开一轮对话。

**Windows：**

先完全退出 ZCode，再运行：

```powershell
curl.exe -LO https://github.com/Jia-Ethan/zcode-keysmith/releases/download/v0.3.1/zcode-keysmith-v0.3.1.zip
curl.exe -LO https://github.com/Jia-Ethan/zcode-keysmith/releases/download/v0.3.1/SHA256SUMS
Get-FileHash .\zcode-keysmith-v0.3.1.zip -Algorithm SHA256
Expand-Archive .\zcode-keysmith-v0.3.1.zip -DestinationPath .
cd zcode-keysmith-v0.3.1
py zcode-keysmith.py install --dry-run
py zcode-keysmith.py install --yes
```

重新打开 ZCode，新开一轮对话。

也可以把 [代装说明](docs/agent-install.md) 交给你正在用的 AI 助手，让它按步骤完成。校验、路径和进阶选项见 [使用说明](docs/reference.md)。

## 怎么撤走

```bash
python3 zcode-keysmith.py uninstall --dry-run
python3 zcode-keysmith.py uninstall --yes
```

Windows 把 `python3` 换成 `py`。先看计划，确认后再恢复。

## 适用环境

macOS 与 Windows。需要 Python 3.10+。Linux 暂不支持。

## 文档

- [使用说明](docs/reference.md)
- [代装说明](docs/agent-install.md)
- [测量说明](breaktest/report.md)
- [桌面客户端 SPEC](gui/SPEC.md)

## 系列

- [codex-keysmith](https://github.com/Jia-Ethan/codex-keysmith) — 给 Codex
- [claude-keysmith](https://github.com/Jia-Ethan/claude-keysmith) — 给 Claude Code
- [grok-keysmith](https://github.com/Jia-Ethan/grok-keysmith) — 给 Grok Build
- [zcode-keysmith](https://github.com/Jia-Ethan/zcode-keysmith) — 给 ZCode

官方反馈：[GitHub Discussions](https://github.com/Jia-Ethan/zcode-keysmith/discussions/7) · 社区：[LINUX DO](https://linux.do)

## Star History

<p align="center">
  <a href="https://star-history.com/#Jia-Ethan/zcode-keysmith&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=Jia-Ethan/zcode-keysmith&type=Date&theme=dark">
      <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=Jia-Ethan/zcode-keysmith&type=Date">
    </picture>
  </a>
</p>
