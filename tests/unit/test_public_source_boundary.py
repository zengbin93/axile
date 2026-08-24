"""防止外部渠道知识渗回公共核心源码."""

import subprocess
from pathlib import Path


def _git_paths(root: Path, *args: str) -> set[Path]:
    output = subprocess.check_output(["git", "ls-files", "-z", *args], cwd=root)
    return {root / item.decode() for item in output.split(b"\0") if item}


def test_tracked_source_has_no_private_channel_terms() -> None:
    """路径与文本均不得直接固化外部渠道名称."""
    root = Path(__file__).parents[2]
    paths = _git_paths(root, "--cached", "--others", "--exclude-standard") - _git_paths(root, "--deleted")
    forbidden = ("bi" + "nance", "cryp" + "to")

    violations: list[str] = []
    for path in sorted(paths):
        relative = path.relative_to(root).as_posix()
        folded_path = relative.casefold()
        for term in forbidden:
            if term in folded_path:
                violations.append(f"{relative}: path")
        if not path.is_file():
            continue
        text = path.read_bytes().decode("utf-8", errors="ignore").casefold()
        for term in forbidden:
            if term in text:
                violations.append(f"{relative}: content")

    assert not violations, "private channel terms found:\n" + "\n".join(violations)
