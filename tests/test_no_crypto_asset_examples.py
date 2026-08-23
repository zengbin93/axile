"""防止公共核心重新引入渠道专属的加密资产示例."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".json", ".md", ".py", ".toml", ".ts", ".tsx", ".yaml", ".yml"}
EXCLUDED_PARTS = {".git", "node_modules", "_static"}
EXCLUDED_NAMES = {"bun.lock", "uv.lock"}


def test_public_core_has_no_crypto_asset_examples() -> None:
    """源码、文档和测试应使用公共市场标的，渠道专属示例由插件提供."""
    asset_codes = (
        "B" + "TC",
        "E" + "TH",
        "S" + "OL",
        "B" + "NB",
        "X" + "RP",
        "D" + "OGE",
        "L" + "UNA",
        "A" + "DA",
        "A" + "VAX",
        "L" + "INK",
        "L" + "TC",
        "T" + "RX",
        "D" + "OT",
        "US" + "DT",
    )
    pattern = re.compile(rf"\b(?:{'|'.join(asset_codes)})(?:/?{'US' + 'DT'})?\b")
    failures: list[str] = []

    tracked = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    for relative in tracked:
        path = ROOT / relative
        if (
            not path.is_file()
            or path.suffix not in TEXT_SUFFIXES
            or path.name in EXCLUDED_NAMES
            or any(part in EXCLUDED_PARTS for part in path.parts)
        ):
            continue
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if match := pattern.search(line):
                failures.append(f"{path.relative_to(ROOT)}:{line_number}: {match.group(0)}")

    assert failures == [], "发现加密资产示例:\n" + "\n".join(failures)
