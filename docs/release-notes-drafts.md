# Release Notes 草稿

## zcode-keysmith v0.3.3

项目里的 MEMORY.md 会盖过 Pier。这一版跳过那段 auto-memory 挂载，并去掉 agentsMd 里的 adhere 句。system-role 不再写死 M3 Air 和家目录路径。Persona、`[P]`、One Line 不变。

runtime-patch 下 `verify` 不再因为 leftover wrapper 的 `--help` smoke 失败（#32）。ShipIt 换包或 LaunchAgent 掉出会话后可用 `recover --yes` 重打补丁并 bootstrap 监视进程。3.12 与 3.14 都用这一版。

装完请完全退出并重新打开 ZCode，再开一轮新对话。本次不发布桌面安装包。

## zcode-keysmith desktop 0.1.0-beta.1

# zcode-keysmith 桌面测试版

第一次提供桌面安装包，内置命令行 0.3.2。可以用它安装、检查和卸载。

## zcode-keysmith v0.3.2

ZCode 3.14 改了 runtime 锚点，0.3.1 装不上。这一版同时识别 3.12 和 3.14，装完仍可卸载还原。macOS 上官方自动更新换包后，LaunchAgent 会等文件稳定再打回同一套补丁；锚点变了则跳过并提示升级 Keysmith。

装完请完全退出并重新打开 ZCode，再开一轮新对话。本次不发布桌面安装包。

## zcode-keysmith v0.3.1

ZCode 3.12 装旧版会停在启动页。这一版不再劫持官方 Agent；3.12 改为备份并补丁 runtime，卸载能还原。Latest 现在有稳定版压缩包，先校验再装。

装完请完全退出并重新打开 ZCode，再开一轮新对话。本次不发布桌面安装包。

## zcode-keysmith v0.3.0

默认提示词整体重写。硬压那种「必须照做」的写法，在 GLM 上会适得其反；改成正常研究者口吻之后，拒绝少了，完整结果多了。

以前一开口就被拦、或者只给你空话和替代方案的请求——逆向、补丁、实验室里的安全工具、创作——现在更容易直接拿到能用的东西。同一批 10 题，完整交付从 1/10 到 4/10。

首页也改过了：这是什么、怎么用、效果，一眼能看完。装完请完全退出并重新打开 ZCode，再开一轮新对话。

目前仍是源码安装，本次不发布桌面安装包。
