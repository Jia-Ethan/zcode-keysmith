<!-- markdownlint-disable MD013 -->

# 复制给智能体安装 / Copy this to an agent

## 简体中文

```text
请从公开仓库 https://github.com/Jia-Ethan/zcode-keysmith 安装 zcode-keysmith 0.3.1。只使用 GitHub Release `v0.3.1` 的 `zcode-keysmith-v0.3.1.zip` 与同级 `SHA256SUMS`，不要从浮动 master 或 `v0.3.0` 安装。下载后先校验 SHA-256，再解压并确认 `python3 zcode-keysmith.py --version`（Windows 用 `py`）输出 `0.3.1`，同时校验 examples/system-role.md 的 SHA-256 为 `a62de09eb5d918e649f997c4fb18c3447f6f246bc284250ca04d4c6532c5a0a0`。识别当前平台：Windows 使用 `py`，macOS 使用 `python3`。运行 --version、install --dry-run 和 doctor，报告目标 ~/.zcode-keysmith 目录、内置提示词来源与 SHA-256、将写入的 system-role.md / config.json / wrapper / env 脚本路径、macOS LaunchAgent 或 Windows HKCU\Environment 的 ZCODE_* 计划、ZCode runtime 与 node command 路径、injection_mode，以及真实的 app_bundle_modified（3.12+ runtime-patch 为 true）。默认只预览；等我明确确认后才添加 --yes。写入后运行 doctor 与 verify。提醒我完全退出并重新打开 ZCode，新建任务后首行应是 `[P]`。不要删除任何备份；3.12+ 允许按安装器备份并补丁 glm/zcode.cjs，卸载必须能还原。不要改网络、运行中进程、API key、token、cookie、MCP 或 provider 配置。
```

## English

```text
Install zcode-keysmith 0.3.1 from https://github.com/Jia-Ethan/zcode-keysmith. Use only GitHub Release `v0.3.1` assets `zcode-keysmith-v0.3.1.zip` and `SHA256SUMS`; do not install from floating `master` or `v0.3.0`. Verify the zip checksum, unpack it, confirm `python3 zcode-keysmith.py --version` (`py` on Windows) reports `0.3.1`, and that examples/system-role.md SHA-256 is `a62de09eb5d918e649f997c4fb18c3447f6f246bc284250ca04d4c6532c5a0a0`. Detect the platform; use `py` on Windows and `python3` on macOS. Run --version, install --dry-run, and doctor. Report ~/.zcode-keysmith, the bundled prompt hash, planned system-role.md / config.json / wrapper / env-script paths, macOS LaunchAgent or Windows HKCU\Environment ZCODE_* plan, ZCode runtime and node-command paths, injection_mode, and the real app_bundle_modified flag (true for 3.12+ runtime-patch). Preview only by default; wait for explicit confirmation before --yes. After writing, run doctor and verify. Tell me to quit and reopen ZCode; a fresh task should start with `[P]`. Do not delete backups. On 3.12+ the installer may back up and patch glm/zcode.cjs; uninstall must restore it. Do not change network, running processes, API keys, tokens, cookies, MCP, or provider config.
```
