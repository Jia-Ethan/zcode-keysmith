<!-- markdownlint-disable MD013 -->

# 复制给智能体安装 / Copy this to an agent

## 简体中文

```text
请从公开仓库 https://github.com/Jia-Ethan/zcode-keysmith 安装 zcode-keysmith 0.2.4。只 clone 当前 `master` 源码树，不要虚构 Release ZIP / tag 检出；检出后确认 `python3 zcode-keysmith.py --version`（Windows 用 `py`）输出 `0.2.4`，并校验 examples/system-role.md 的 SHA-256 为 `73458b16bbb5c879e85c13d7beb6c4f99caab858a5b5b5e35ee367027111cfca`。识别当前平台：Windows 使用 `py`，macOS 使用 `python3`。运行 --version、install --dry-run 和 doctor，报告目标 ~/.zcode-keysmith 目录、内置提示词来源与 SHA-256、将写入的 system-role.md / config.json / wrapper / env 脚本路径、macOS LaunchAgent 或 Windows HKCU\Environment 的 ZCODE_* 计划、ZCode runtime 与 node command 路径，以及 app_bundle_modified: false。默认只预览；等我明确确认后才添加 --yes。写入后运行 doctor 与 verify。提醒我完全退出并重新打开 ZCode，新建任务后再运行 verify，确认 wrapper_invoked: true。不要删除任何备份，不修改 ZCode 原包、网络、运行中进程、API key、token、cookie、MCP 或 provider 配置。
```

## English

```text
Install zcode-keysmith 0.2.4 from the public repository https://github.com/Jia-Ethan/zcode-keysmith. Clone the current `master` source tree only; do not invent a Release ZIP or tag checkout. After checkout, confirm that `python3 zcode-keysmith.py --version` (`py` on Windows) reports `0.2.4`, and verify that the SHA-256 of examples/system-role.md is `73458b16bbb5c879e85c13d7beb6c4f99caab858a5b5b5e35ee367027111cfca`. Detect the platform; use `py` on Windows and `python3` on macOS. Run --version, install --dry-run, and doctor, then report the target ~/.zcode-keysmith directory, the bundled prompt source and its SHA-256, the planned system-role.md / config.json / wrapper / env-script paths, the macOS LaunchAgent or Windows HKCU\Environment ZCODE_* plan, the ZCode runtime and node-command paths, and app_bundle_modified: false. Preview only by default; wait for my explicit confirmation before adding --yes. After writing, run doctor and verify. Tell me to quit and reopen ZCode, start a fresh task, then run verify again and confirm wrapper_invoked: true. Do not delete any backups, and do not modify the ZCode app bundle, network, running processes, API keys, tokens, cookies, MCP, or provider config.
```
