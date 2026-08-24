"""防止公共核心重新引入私有市场词汇或渠道专属资产示例。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _tracked_files() -> list[str]:
    """返回已跟踪及待纳入版本控制的文件路径。"""
    return subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()


def test_public_core_has_no_private_market_term() -> None:
    """文件路径和可解码文本均不得出现私有市场禁词。"""
    forbidden = "cryp" + "to"
    failures: list[str] = []
    for relative in _tracked_files():
        path = ROOT / relative
        if not path.is_file():
            continue
        if forbidden.casefold() in relative.casefold():
            failures.append(relative)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if forbidden.casefold() in line.casefold():
                failures.append(f"{relative}:{line_number}")

    assert failures == [], "发现私有市场禁词:\n" + "\n".join(failures)


def test_public_core_has_no_channel_specific_asset_examples() -> None:
    """源码、文档和测试应使用公共市场标的，渠道专属示例由插件提供。"""
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

    for relative in _tracked_files():
        path = ROOT / relative
        if not path.is_file():
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if match := pattern.search(line):
                failures.append(f"{relative}:{line_number}: {match.group(0)}")

    assert failures == [], "发现渠道专属资产示例:\n" + "\n".join(failures)
