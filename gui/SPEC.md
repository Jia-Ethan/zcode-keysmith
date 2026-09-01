# zcode-keysmith GUI

Tauri 2 + React 19 + Tailwind 4 客户端，视觉与结构对齐 Codex Keysmith（浅色 clay / 深色 tech blue）。

- CLI：`zcode-keysmith.py`（subcommand 式）。所有调用带 `--json`，契约 `zcode-keysmith/v1`。不传 `--lang`。
- 视图：Dashboard = `doctor --json`；Deploy = `install --dry-run` / `install --yes`；Manage = `uninstall`（无 recover，展示 `.bak_`）。无 Scenarios。
- Sidecar：`scripts/build-sidecar.mjs` 产出 `zcode-keysmith-cli-<triple>`。烟雾测试 `--version` 与隔离目录下的 `doctor --json`，不得探测本机 `~/Library/LaunchAgents/com.jia.zcode-keysmith.env.plist`。
- identifier：`com.jia-ethan.zcode-keysmith-gui`
- 版本：`0.1.0-beta.1`
