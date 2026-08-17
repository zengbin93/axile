"""全局pytest配置和共享fixtures."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


def pytest_configure(config: pytest.Config) -> None:
    """注册自定义标记."""
    markers = [
        ("unit", "单元测试标记"),
        ("integration", "集成测试标记"),
        ("live", "联机测试标记（需要真实环境）"),
        ("slow", "慢速测试标记"),
        ("ctp", "CTP渠道相关测试"),
        ("server", "服务器模块测试"),
    ]
    for marker, description in markers:
        config.addinivalue_line("markers", f"{marker}: {description}")


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
