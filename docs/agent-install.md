<!-- markdownlint-disable MD013 -->

# 复制给智能体安装 / Copy this to an agent

## 简体中文

```text
请从公开仓库 https://github.com/Jia-Ethan/zcode-keysmith 安装 zcode-keysmith。先检查 GitHub Release：当前稳定版是 v0.3.3（zcode-keysmith-v0.3.3.zip 与同级 SHA256SUMS），支持 ZCode 3.12 与 3.14。不要从浮动 master 安装。下载后先校验 SHA-256，再解压并确认 python3 zcode-keysmith.py --version（Windows 用 py）为 0.3.3，同时校验 examples/system-role.md 的 SHA-256 为 30e7de01b1a453d38cb1fa38bc8f4bb26eeaf8eccafada1aa178df1a1cf1c9e1。识别当前平台：Windows 使用 py，macOS 使用 python3。运行 --version、install --dry-run 和 doctor，报告目标 ~/.zcode-keysmith 目录、内置提示词来源与 SHA-256、将写入的 system-role.md / config.json / wrapper / env 脚本路径、macOS LaunchAgent 或 Windows HKCU\Environment 的 ZCODE_* 计划、ZCode runtime 与 node command 路径、injection_mode、auto_repatch_watch（macOS 3.12+ 应为 true）、auto_repatch_rearm（macOS 3.12+ 应为 true），以及真实的 app_bundle_modified（3.12+ runtime-patch 为 true）。默认只预览；等我明确确认后才添加 --yes。写入后运行 doctor 与 verify。提醒我完全退出并重新打开 ZCode，新建任务后首行应是 [P]。不要删除任何备份；3.12+ 允许按安装器备份并补丁 glm/zcode.cjs，卸载必须能还原。macOS 上 0.3.3 会在官方更新后自动重打同一套补丁，不要关掉 autoDownloadAndInstallUpdates 来留住补丁。不要改网络、运行中进程、API key、token、cookie、MCP 或 provider 配置。
```

## English

```text
Install zcode-keysmith from https://github.com/Jia-Ethan/zcode-keysmith. Check GitHub Releases first: the current stable release is v0.3.3 (zcode-keysmith-v0.3.3.zip and SHA256SUMS) and supports ZCode 3.12 and 3.14. Never install from floating master. Verify the zip checksum, unpack it, confirm python3 zcode-keysmith.py --version (py on Windows) is 0.3.3, and that examples/system-role.md SHA-256 is 30e7de01b1a453d38cb1fa38bc8f4bb26eeaf8eccafada1aa178df1a1cf1c9e1. Detect the platform; use py on Windows and python3 on macOS. Run --version, install --dry-run, and doctor. Report ~/.zcode-keysmith, the bundled prompt hash, planned system-role.md / config.json / wrapper / env-script paths, macOS LaunchAgent or Windows HKCU\Environment ZCODE_* plan, ZCode runtime and node-command paths, injection_mode, auto_repatch_watch (true for macOS 3.12+), auto_repatch_rearm (true for macOS 3.12+), and the real app_bundle_modified flag (true for 3.12+ runtime-patch). Preview only by default; wait for explicit confirmation before --yes. After writing, run doctor and verify. Tell me to quit and reopen ZCode; a fresh task should start with [P]. Do not delete backups. On 3.12+ the installer may back up and patch glm/zcode.cjs; uninstall must restore it. On macOS, 0.3.3 re-applies the same patch after an official update; do not turn off autoDownloadAndInstallUpdates just to keep the patch. Do not change network, running processes, API keys, tokens, cookies, MCP, or provider config.
```
