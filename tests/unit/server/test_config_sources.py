"""``axile.common.config`` 配置来源、就绪判据与写入器测试."""

from pathlib import Path

import pytest

import axile.common.config as cfg


def _settings_with_toml(monkeypatch: pytest.MonkeyPatch, toml_path: Path) -> cfg.Settings:
    """构造一个从指定 TOML 文件读取的 ``Settings`` 实例."""
    monkeypatch.setitem(cfg.Settings.model_config, "toml_file", str(toml_path))
    return cfg.Settings()


def test_missing_toml_falls_back_to_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """缺失 config.toml 时应回退到代码默认值，且不抛错."""
    settings = _settings_with_toml(monkeypatch, tmp_path / "nope.toml")

    assert settings.algorithm_modules == []
    assert str(settings.sqlalchemy_database_uri).startswith("sqlite+aiosqlite")


def test_toml_overrides_defaults(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """config.toml 中的值应覆盖默认值（含 list 类型的算法模块）."""
    toml_path = tmp_path / "config.toml"
    toml_path.write_text(
        'algorithm_modules = ["a.b", "c.d"]\n',
        encoding="utf-8",
    )
    settings = _settings_with_toml(monkeypatch, toml_path)

    assert settings.algorithm_modules == ["a.b", "c.d"]


def test_env_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """进程环境变量不作为配置来源：即便设置同名 env 也完全不影响 Settings."""
    toml_path = tmp_path / "config.toml"
    toml_path.write_text('algorithm_modules = ["from.toml"]\n', encoding="utf-8")
    monkeypatch.setenv("ALGORITHM_MODULES", '["from.env"]')

    settings = _settings_with_toml(monkeypatch, toml_path)

    # toml 提供的键取 toml 值（非 env）；toml 未提供的键回退默认值（不被 env 兜底）。
    assert settings.algorithm_modules == ["from.toml"]


def test_is_configured_reflects_toml_existence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """is_configured 以 config.toml 是否存在为准，与数据源是否配置无关."""
    toml_path = tmp_path / "config.toml"
    monkeypatch.setattr(cfg, "CONFIG_TOML_PATH", toml_path)

    # 文件不存在时进入初始化向导。
    assert cfg.is_configured() is False

    # 文件存在且日历上游为空也视为已配置。
    toml_path.write_text("", encoding="utf-8")
    assert cfg.is_configured() is True


def test_write_config_toml_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """写入的 config.toml 应带告警注释，且能被 Settings 正确回读."""
    toml_path = tmp_path / "config.toml"
    monkeypatch.setattr(cfg, "CONFIG_TOML_PATH", toml_path)

    cfg.write_config_toml(
        {
            "sqlalchemy_database_uri": "sqlite+aiosqlite:///./axile.db",
            "environment": "local",
            "app_log_dir": "./logs",
            "axile_log_rotation": "1 day",
            "algorithm_modules": ["a.b", "c.d"],
        }
    )

    assert toml_path.exists()
    assert "请勿手工编辑" in toml_path.read_text(encoding="utf-8")

    settings = _settings_with_toml(monkeypatch, toml_path)
    assert settings.algorithm_modules == ["a.b", "c.d"]
