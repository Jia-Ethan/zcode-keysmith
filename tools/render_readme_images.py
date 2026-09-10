#!/usr/bin/env python3
"""Rasterize architecture HTML and convert hero JPEGs to webp."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets" / "readme"
HTML = ROOT / "tools" / "readme-architecture.html"
CHROME = Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
CWEBP = Path("/opt/homebrew/bin/cwebp")

HERO_DARK = ROOT / "tools" / "readme-src" / "hero-dark.jpg"
HERO_LIGHT = ROOT / "tools" / "readme-src" / "hero-light.jpg"


def run(cmd: list[str]) -> None:
    print("+", " ".join(cmd))
    subprocess.run(cmd, check=True)


def chrome_shot(url: str, dest_png: Path) -> None:
    dest_png.parent.mkdir(parents=True, exist_ok=True)
    run(
        [
            str(CHROME),
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=2",
            "--window-size=2400,988",
            f"--screenshot={dest_png}",
            "--virtual-time-budget=4000",
            url,
        ]
    )


def to_webp(src: Path, dest: Path, quality: str = "90") -> None:
    run([str(CWEBP), "-q", quality, str(src), "-o", str(dest)])


def main() -> int:
    if not CHROME.is_file():
        print("Google Chrome not found", file=sys.stderr)
        return 1
    if not CWEBP.is_file():
        print("cwebp not found", file=sys.stderr)
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = ROOT / "tools" / ".readme-render"
    tmp.mkdir(exist_ok=True)

    to_webp(HERO_DARK, OUT / "zcode-keysmith-hero-dark.webp")
    to_webp(HERO_LIGHT, OUT / "zcode-keysmith-hero-light.webp")

    html_uri = HTML.resolve().as_uri()
    for lang in ("zh", "en"):
        for theme in ("light", "dark"):
            png = tmp / f"arch-{lang}-{theme}.png"
            chrome_shot(f"{html_uri}?lang={lang}&theme={theme}", png)
            to_webp(png, OUT / f"project-architecture-{lang}-{theme}.webp")

    for p in sorted(OUT.glob("*.webp")):
        print(p.relative_to(ROOT), p.stat().st_size, "bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
