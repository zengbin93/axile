"""
Axile 服务器启动脚本入口.

该模块兼容传统命令行参数解析流程，并委托
``axile.server.main.run_server`` 启动服务。
"""

from pathlib import Path

from axile.server.main import build_arg_parser, run_server


def main() -> None:
    """解析命令行参数并启动 Axile 服务器."""
    parser = build_arg_parser()
    args = parser.parse_args()

    run_server(
        host=args.host,
        port=args.port,
        algorithm_dir=Path(args.algorithm_dir),
        workers=args.workers,
        reload=args.reload,
        reload_dirs=[Path(directory) for directory in args.reload_dir],
    )


if __name__ == "__main__":
    main()
