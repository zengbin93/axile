# 测试指南

测试按运行条件分为以下目录：

- `tests/unit/`：不访问真实外部服务的单元测试。
- `tests/integration/`：跨模块集成测试。
- `tests/live/`：需要显式开关及真实环境的联机测试。

安装开发依赖和 CTP 测试依赖：

```bash
uv sync --group dev --extra ctp
```

离线测试套件包含 CTP 渠道用例；`openctp-ctp` 是 CTP 的可选运行时依赖，
因此执行完整测试套件时必须安装 `ctp` extra。未安装该 extra 的环境仅适合
不运行 CTP 测试的开发工作。

运行离线测试与覆盖率门禁：

```bash
uv run pytest tests/ -v \
  --ignore=tests/live \
  --cov=axile --cov-report=xml --cov-report=term-missing --cov-fail-under=69
```

测试启动时会在系统临时目录生成独立的 ``config.toml``、SQLite 数据库和日志目录，
并通过 ``AXILE_CONFIG_TOML`` 传递给测试启动的子进程。测试不得读取或写入工作目录中的
``axile.db``；需要数据库的用例应使用这套会话级隔离环境或自己的 ``tmp_path``。

运行单个文件或测试：

```bash
uv run pytest tests/unit/channels/test_registry.py -v
uv run pytest tests/unit/channels/test_registry.py::test_duplicate_channel_registration_fails_clearly -v
```

联机测试默认跳过。需要运行时，将 `tests/live.config.example.toml` 复制为已被
`.gitignore` 忽略的 `tests/live.config.toml`，填写对应 section，并设置测试文件说明的
`RUN_LIVE_*` 环境变量。

新增测试应保持确定性，不依赖执行顺序、真实时钟或公网服务。渠道插件自身的实现测试
应放在对应插件项目，公共核心只验证开放注册协议与通用行为。
