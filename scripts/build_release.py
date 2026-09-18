#!/usr/bin/env python3
"""Build the grok-style stable zip and SHA256SUMS for zcode-keysmith."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ZIP_TIMESTAMP = (2026, 9, 19, 0, 0, 0)
VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
VERSION_ASSIGN_RE = re.compile(r'^__version__ = "([^"]+)"$', re.MULTILINE)

REQUIRED_FILES = (
    "CHANGELOG.md",
    "LICENSE",
    "README.md",
    "README.en.md",
    "VERSION",
    "zcode-keysmith.py",
    "docs/agent-install.md",
    "docs/reference.md",
    "docs/release-notes-drafts.md",
    "examples/system-role.md",
    "breaktest/report.md",
    "breaktest/scores.json",
)

INCLUDE_GLOBS = (
    "docs/assets/readme/*",
    "docs/releases/*.md",
)

SKIP_SUFFIXES = {".pyc", ".DS_Store"}


class ReleaseError(Exception):
    """User-facing packaging error."""


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def read_version(root: Path) -> str:
    version = (root / "VERSION").read_text(encoding="ascii").strip()
    if not VERSION_RE.fullmatch(version):
        raise ReleaseError(f"invalid VERSION: {version!r}")
    script = (root / "zcode-keysmith.py").read_text(encoding="utf-8")
    match = VERSION_ASSIGN_RE.search(script)
    if match is None:
        raise ReleaseError("zcode-keysmith.py is missing __version__")
    if match.group(1) != version:
        raise ReleaseError(
            f"VERSION {version} does not match zcode-keysmith.py __version__ {match.group(1)}"
        )
    return version


def collect_files(root: Path) -> list[str]:
    files: set[str] = set(REQUIRED_FILES)
    for pattern in INCLUDE_GLOBS:
        for path in root.glob(pattern):
            if not path.is_file():
                continue
            if path.name in SKIP_SUFFIXES or path.suffix in SKIP_SUFFIXES:
                continue
            files.add(path.relative_to(root).as_posix())
    missing = [name for name in REQUIRED_FILES if not (root / name).is_file()]
    if missing:
        raise ReleaseError("missing required release files: " + ", ".join(missing))
    forbidden = [name for name in sorted(files) if name.startswith("gui/") or name.startswith("docs/legacy/")]
    if forbidden:
        raise ReleaseError("release zip must not include: " + ", ".join(forbidden))
    return sorted(files)


def archive_name(version: str, relative_path: str) -> str:
    return f"zcode-keysmith-v{version}/{relative_path}"


def file_mode(relative_path: str) -> int:
    return 0o755 if relative_path == "zcode-keysmith.py" else 0o644


def write_zip(path: Path, version: str, root: Path, files: list[str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for relative_path in files:
            data = (root / relative_path).read_bytes()
            info = zipfile.ZipInfo(archive_name(version, relative_path), ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (file_mode(relative_path) & 0xFFFF) << 16
            archive.writestr(info, data)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_sums(path: Path, assets: list[Path]) -> None:
    lines = [f"{sha256_file(asset)}  {asset.name}\n" for asset in assets]
    path.write_text("".join(lines), encoding="ascii")


def build(root: Path, output_dir: Path) -> list[Path]:
    version = read_version(root)
    files = collect_files(root)
    output_dir.mkdir(parents=True, exist_ok=True)
    zip_path = output_dir / f"zcode-keysmith-v{version}.zip"
    sums_path = output_dir / "SHA256SUMS"
    write_zip(zip_path, version, root, files)
    write_sums(sums_path, [zip_path])
    return [zip_path, sums_path]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build zcode-keysmith stable zip assets.")
    parser.add_argument(
        "--output-dir",
        default="dist",
        help="Directory for zcode-keysmith-v<VERSION>.zip and SHA256SUMS. Default: dist",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = repo_root()
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = root / output_dir
    try:
        assets = build(root, output_dir)
    except ReleaseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for asset in assets:
        print(asset)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
