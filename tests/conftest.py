"""全局pytest配置和共享fixtures."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 测试可能启动子进程；通过配置文件指针让父子进程共享同一个隔离数据库，
# 并确保任何服务端模块导入前都不会连接工作目录中的 ``axile.db``。
_TEST_RUNTIME = tempfile.TemporaryDirectory(prefix="axile-tests-")
_TEST_RUNTIME_PATH = Path(_TEST_RUNTIME.name)
_TEST_CONFIG_PATH = _TEST_RUNTIME_PATH / "config.toml"
_TEST_DATABASE_PATH = _TEST_RUNTIME_PATH / "axile.db"
_TEST_CONFIG_PATH.write_text(
    "\n".join(
        (
            f'sqlalchemy_database_uri = "sqlite+aiosqlite:///{_TEST_DATABASE_PATH}"',
            f'app_log_dir = "{_TEST_RUNTIME_PATH / "logs"}"',
            'environment = "local"',
            "",
        )
    ),
    encoding="utf-8",
)
os.environ["AXILE_CONFIG_TOML"] = str(_TEST_CONFIG_PATH)


@pytest.fixture(scope="session")
def project_root() -> Path:
    """返回项目根目录."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def tests_dir(project_root: Path) -> Path:
    """返回测试目录."""
    return project_root / "tests"


@pytest.fixture(scope="session")
def src_dir(project_root: Path) -> Path:
    """返回源码目录."""
    return project_root / "axile"


@pytest.fixture
def mock_logger():
    """创建模拟logger."""
    logger = MagicMock()
    logger.debug = MagicMock()
    logger.info = MagicMock()
    logger.warning = MagicMock()
    logger.error = MagicMock()
    logger.exception = MagicMock()
    return logger


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """自动为测试添加标记."""
    for item in items:
        path = item.location[0]
        if "\\unit\\" in path or "/unit/" in path:
            item.add_marker(pytest.mark.unit)
        elif "\\integration\\" in path or "/integration/" in path:
            item.add_marker(pytest.mark.integration)
        elif "\\live\\" in path or "/live/" in path:
            item.add_marker(pytest.mark.live)
            item.add_marker(pytest.mark.slow)
        if "ctp" in path.lower():
            item.add_marker(pytest.mark.ctp)
        if "server" in path.lower():
            item.add_marker(pytest.mark.server)
