"""
Axile 统一 CLI 入口.

使用 Typer 组织主命令与子命令，并在未指定子命令时直接启动 API
服务器。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Optional

import typer

app = typer.Typer(
    name="axile",
    help="Axile 量化交易框架 CLI 工具集",
    invoke_without_command=True,
    rich_markup_mode="rich",
)


@app.callback()
def callback(
    ctx: typer.Context,
    host: Annotated[str, typer.Option(help="监听地址（仅允许回环地址）")] = "127.0.0.1",
    port: Annotated[int, typer.Option(help="监听端口")] = 8000,
    algorithm_dir: Annotated[Path, typer.Option(help="用户算法目录")] = Path("user_algorithms"),
    workers: Annotated[Optional[int], typer.Option(help="工作进程数；当前仅支持 1，更大值会被拒绝")] = None,
    reload: Annotated[bool, typer.Option(help="启用后端热重载（开发模式）")] = False,
    reload_dir: Annotated[Optional[list[Path]], typer.Option(help="热重载监听目录，可多次传入")] = None,
) -> None:
    """
    处理 Axile CLI 根命令，并在默认情况下启动 API 服务器.

    Parameters
    ----------
    ctx : typer.Context
        当前命令执行上下文。
    host : str
        API 服务器监听地址；仅允许回环地址，传入 ``0.0.0.0`` 等通配地址会被拒绝。
    port : int
        API 服务器监听端口。
    algorithm_dir : Path
        用户算法目录路径。
    workers : int | None
        服务端工作进程数；当前仅支持单 worker，大于 1 会直接拒绝启动
        （实盘互斥锁、调度器与实盘进度镜像均为进程内内存态）。
    reload : bool
        是否启用后端热重载。
    reload_dir : list[Path] | None
        额外热重载监听目录。
    """
    # 如果没有子命令，启动 server
    if ctx.invoked_subcommand is None:
        from axile.server.main import run_server

        run_server(
            host=host,
            port=port,
            algorithm_dir=algorithm_dir,
            workers=workers,
            reload=reload,
            reload_dirs=reload_dir or [],
        )


def main() -> None:
    """执行 Axile CLI 应用."""
    app()


if __name__ == "__main__":
    main()
