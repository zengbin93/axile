"""用于健康检查、诊断与本机目录浏览的工具路由."""

from __future__ import annotations

import ctypes
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

router = APIRouter(prefix="/utils", tags=["utils"])


class DirectoryEntry(BaseModel):
    """目录选择器中的一个可进入目录."""

    name: str
    path: str


class DirectoryListing(BaseModel):
    """目录选择器当前层级的只读快照."""

    path: str | None
    parent: str | None
    entries: list[DirectoryEntry]


def _directory_roots() -> list[Path]:
    """返回当前平台可浏览的文件系统根目录."""
    if sys.platform != "win32":
        return [Path("/")]

    mask = ctypes.windll.kernel32.GetLogicalDrives()  # type: ignore[attr-defined]
    return [Path(f"{chr(ord('A') + index)}:\\") for index in range(26) if mask & (1 << index)]


def _entry(path: Path) -> DirectoryEntry:
    """将本机路径转换为不含文件内容的公开目录项."""
    return DirectoryEntry(name=path.name or str(path), path=str(path))


@router.get("/health-check/")
def health_check() -> bool:
    """返回一个简单的 API 进程存活信号."""
    return True


@router.get("/directories", response_model=DirectoryListing)
def list_directories(path: str | None = Query(default=None)) -> DirectoryListing:
    """按用户指定层级列出本机目录，不扫描子树或读取文件."""
    if path is None:
        roots = [root for root in _directory_roots() if root.is_dir()]
        return DirectoryListing(path=None, parent=None, entries=[_entry(root) for root in roots])

    requested = Path(path).expanduser()
    if not requested.is_absolute():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="目录路径必须是绝对路径")

    try:
        current = requested.resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="目录不存在") from exc
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无法访问该目录") from exc

    if not current.is_dir():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="路径不是目录")

    try:
        children = sorted(
            (child for child in current.iterdir() if child.is_dir()),
            key=lambda child: child.name.casefold(),
        )
    except OSError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="没有权限读取该目录") from exc

    parent = None if current.parent == current else str(current.parent)
    return DirectoryListing(path=str(current), parent=parent, entries=[_entry(child) for child in children])
