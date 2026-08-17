"""``tests.live_env`` 联机测试配置加载器的单元测试."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.live_env import config_value, require_live_config


def test_require_live_config_skips_when_flag_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """启用开关未置 1 时应直接 skip."""
    monkeypatch.delenv("RUN_LIVE_SAMPLE_TESTS", raising=False)

    with pytest.raises(pytest.skip.Exception, match="RUN_LIVE_SAMPLE_TESTS=1"):
        require_live_config("RUN_LIVE_SAMPLE_TESTS", "sample", ["api_key"])


def test_require_live_config_skips_when_required_missing(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """必填字段在环境变量与文件中均缺失时应 skip 并列出缺失项."""
    monkeypatch.setenv("RUN_LIVE_SAMPLE_TESTS", "1")
    monkeypatch.setenv("AXILE_TEST_CONFIG", str(tmp_path / "absent.toml"))
    monkeypatch.delenv("SAMPLE_API_KEY", raising=False)
    monkeypatch.delenv("SAMPLE_SECRET_KEY", raising=False)

    with pytest.raises(pytest.skip.Exception, match="api_key.*secret_key"):
        require_live_config("RUN_LIVE_SAMPLE_TESTS", "sample", ["api_key", "secret_key"])


def test_require_live_config_returns_env_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """环境变量（SECTION_KEY 全大写）应作为文件缺失时的取值来源."""
    monkeypatch.setenv("RUN_LIVE_SAMPLE_TESTS", "1")
    monkeypatch.setenv("AXILE_TEST_CONFIG", str(tmp_path / "absent.toml"))
    monkeypatch.setenv("SAMPLE_API_KEY", "key")
    monkeypatch.setenv("SAMPLE_SECRET_KEY", "secret")

    result = require_live_config("RUN_LIVE_SAMPLE_TESTS", "sample", ["api_key", "secret_key"])

    assert result == {"api_key": "key", "secret_key": "secret"}


def test_config_value_precedence_env_over_file_over_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """解析优先级应为：环境变量 > 配置文件 > 默认值."""
    config = tmp_path / "live.config.toml"
    config.write_text('[sample]\napi_key = "from_file"\nproxy = "file_proxy"\n', encoding="utf-8")
    monkeypatch.setenv("AXILE_TEST_CONFIG", str(config))

    # 环境变量覆盖文件值
    monkeypatch.setenv("SAMPLE_API_KEY", "from_env")
    assert config_value("sample", "api_key") == "from_env"

    # 无环境变量时取文件值
    monkeypatch.delenv("SAMPLE_PROXY", raising=False)
    assert config_value("sample", "proxy") == "file_proxy"

    # 环境变量与文件均缺失时取默认值
    monkeypatch.delenv("SAMPLE_MISSING", raising=False)
    assert config_value("sample", "missing", "fallback") == "fallback"
