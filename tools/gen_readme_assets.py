#!/usr/bin/env python3
"""Generate README SVG assets (light/dark pairs) for zcode-keysmith.

Run:  python3 tools/gen_readme_assets.py
Outputs:
  docs/assets/readme/deploy-flow-{zh,en}-{light,dark}.svg

No pass-trend SVGs: this repo has no breaktest/ bank with comparable
full-delivery counts across versions. Do not invent trend points.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "readme"
OUT.mkdir(parents=True, exist_ok=True)

# ---- shared palette -------------------------------------------------------
LIGHT = {
    "bg": "#ffffff",
    "fg": "#24292f",
    "muted": "#57606a",
    "accent": "#0969da",
    "accent_soft": "#ddf4ff",
    "border": "#d0d7de",
    "good": "#1a7f37",
    "good_soft": "#dafbe1",
    "warn": "#9a6700",
    "warn_soft": "#fff8c5",
    "grid": "#eaeef2",
    "arrow": "#57606a",
}
DARK = {
    "bg": "#0d1117",
    "fg": "#e6edf3",
    "muted": "#8b949e",
    "accent": "#58a6ff",
    "accent_soft": "#121d2f",
    "border": "#30363d",
    "good": "#3fb950",
    "good_soft": "#12261e",
    "warn": "#d29922",
    "warn_soft": "#211d0e",
    "grid": "#21262d",
    "arrow": "#8b949e",
}

FONT = "-apple-system, 'Segoe UI', 'Noto Sans', 'Noto Sans SC', 'PingFang SC', 'Microsoft YaHei', sans-serif"


def esc(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


# ---- deploy flow diagram ---------------------------------------------------
FLOW_ZH = [
    ("1 预览", "--dry-run", "查看 ~/.zcode-keysmith 目标、\nsystem-role 与 wrapper 计划", "accent"),
    ("2 写入", "--yes", "写入 system-role.md 与 wrapper，\n激活用户目录入口", "accent"),
    ("3 验证", "新会话", "退出并重开 ZCode，新建任务；\nverify 确认 wrapper 已调用", "good"),
    ("4 撤销", "uninstall", "预览完整卸载计划，\n确认后 --yes 一键恢复", "good"),
]
FLOW_EN = [
    ("1 Preview", "--dry-run", "Review ~/.zcode-keysmith, the\nsystem-role, and wrapper plan", "accent"),
    ("2 Apply", "--yes", "Write system-role.md and wrapper,\nactivate the user-dir entrypoint", "accent"),
    ("3 Verify", "new session", "Quit and reopen ZCode, start a\nfresh task; verify wrapper invoked", "good"),
    ("4 Undo", "uninstall", "Preview the full uninstall plan,\nthen add --yes to restore", "good"),
]


def flow_svg(strings, theme: str) -> str:
    t = LIGHT if theme == "light" else DARK
    card_w, card_h, gap = 265, 148, 38
    pad_x, pad_y = 28, 30
    title_h = 44
    total_w = pad_x * 2 + card_w * 4 + gap * 3
    total_h = title_h + pad_y * 2 + card_h
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}" height="{total_h}" viewBox="0 0 {total_w} {total_h}" font-family="{FONT}">',
        f'<rect width="{total_w}" height="{total_h}" fill="{t["bg"]}"/>',
    ]
    for i, (step, cmd, body, kind) in enumerate(strings):
        cx = pad_x + i * (card_w + gap)
        cy = title_h + pad_y
        head_fill = t["accent_soft"] if kind == "accent" else t["good_soft"]
        head_fg = t["accent"] if kind == "accent" else t["good"]
        parts.append(
            f'<rect x="{cx}" y="{cy}" width="{card_w}" height="{card_h}" rx="10" fill="{t["bg"]}" stroke="{t["border"]}" stroke-width="1.2"/>'
        )
        parts.append(
            f'<rect x="{cx}" y="{cy}" width="{card_w}" height="34" rx="10" fill="{head_fill}"/>'
        )
        parts.append(
            f'<rect x="{cx}" y="{cy + 24}" width="{card_w}" height="10" fill="{head_fill}"/>'
        )
        parts.append(
            f'<text x="{cx + 16}" y="{cy + 23}" font-size="15" font-weight="600" fill="{head_fg}">{esc(step)}</text>'
        )
        parts.append(
            f'<text x="{cx + 16}" y="{cy + 62}" font-size="14" font-family="ui-monospace, SFMono-Regular, Menlo, monospace" font-weight="600" fill="{t["fg"]}">{esc(cmd)}</text>'
        )
        for j, line in enumerate(body.split("\n")):
            parts.append(
                f'<text x="{cx + 16}" y="{cy + 88 + j * 18}" font-size="12.5" fill="{t["muted"]}">{esc(line)}</text>'
            )
        if i < 3:
            ax = cx + card_w + 7
            ay = cy + card_h / 2
            parts.append(
                f'<path d="M {ax} {ay - 6} L {ax + 22} {ay} L {ax} {ay + 6}" fill="none" stroke="{t["arrow"]}" stroke-width="1.6"/>'
            )
    parts.append("</svg>")
    return "\n".join(parts)


def main() -> None:
    for lang, flow in (("zh", FLOW_ZH), ("en", FLOW_EN)):
        for theme in ("light", "dark"):
            (OUT / f"deploy-flow-{lang}-{theme}.svg").write_text(
                flow_svg(flow, theme), encoding="utf-8"
            )
    for p in sorted(OUT.glob("deploy-flow-*.svg")):
        print(p.relative_to(ROOT), p.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
