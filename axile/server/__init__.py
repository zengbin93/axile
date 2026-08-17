"""Axile 长期运行服务的入口与运行时组件集合.

专门用于承载 axile 中所有长期运行的服务进程入口，例如：

- HTTP / REST API 服务器
- 调度器 / 定时任务进程
- 其他需要常驻运行的 worker

约定结构：

- `axile.server.app`   : FastAPI 应用实例及 lifespan 相关逻辑
- `axile.server.api`   : 对外暴露的 API 路由集合
- `axile.server.main`  : 命令行入口，负责解析参数并启动服务
"""

__all__ = []
