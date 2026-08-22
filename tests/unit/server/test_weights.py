"""目标权重加载与时效辅助函数测试。"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import pytest

from axile.server import weights as weights_module
from axile.server.weights import _extract_target_update_time, _fetch_latest_weights_frame, get_latest_weights


def test_fetch_latest_weights_uses_get_bearer_and_weight_type(monkeypatch: pytest.MonkeyPatch) -> None:
    """开放平台请求必须使用 GET、Bearer 认证和显式仓位类型。"""
    captured: dict[str, Any] = {}

    class FakeResponse:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        def raise_for_status(self) -> None:
            return None

        async def json(self) -> dict[str, object]:
            return {
                "code": 0,
                "msg": "ok",
                "data": {
                    "items": [
                        {
                            "dt": "2026-08-22 16:00:00",
                            "strategy": "alpha",
                            "symbol": "BTCUSDT",
                            "weight": 0.5,
                            "update_time": None,
                        }
                    ]
                },
            }

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        def get(self, url: str, **kwargs: Any) -> FakeResponse:
            captured.update(url=url, **kwargs)
            return FakeResponse()

    monkeypatch.setattr(weights_module.settings, "quant_data_token", "sk_test")
    monkeypatch.setattr(weights_module.aiohttp, "ClientSession", FakeSession)

    frame = asyncio.run(_fetch_latest_weights_frame("https://example.test/latest", "cs"))

    assert captured == {
        "url": "https://example.test/latest",
        "params": {"weight_type": "cs"},
        "headers": {"Authorization": "Bearer sk_test"},
    }
    assert frame.loc[0, "strategy"] == "alpha"


def test_extract_target_update_time_returns_oldest() -> None:
    """多策略时应返回最旧的 update_time（staleness 上界）。"""
    df = pd.DataFrame(
        [
            {"strategy": "alpha", "symbol": "BTCUSDT", "weight": 0.5, "update_time": "2026-07-02 09:05:00"},
            {"strategy": "beta", "symbol": "ETHUSDT", "weight": 0.25, "update_time": "2026-07-02 09:00:00"},
        ]
    )
    assert _extract_target_update_time(df) == pd.Timestamp("2026-07-02 09:00:00").isoformat()


def test_extract_target_update_time_missing_column_returns_none() -> None:
    """缺少 update_time 列时应返回 None。"""
    df = pd.DataFrame([{"strategy": "alpha", "symbol": "BTCUSDT", "weight": 0.5}])
    assert _extract_target_update_time(df) is None


def test_extract_target_update_time_empty_returns_none() -> None:
    """空数据表应返回 None。"""
    assert _extract_target_update_time(pd.DataFrame(columns=["strategy", "symbol", "weight", "update_time"])) is None


def test_extract_target_update_time_all_invalid_returns_none() -> None:
    """update_time 全部无法解析时应返回 None。"""
    df = pd.DataFrame([{"strategy": "alpha", "symbol": "BTCUSDT", "weight": 0.5, "update_time": "bad"}])
    assert _extract_target_update_time(df) is None


def test_get_latest_weights_returns_frame_and_update_time(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_latest_weights 应返回 (仅三列的权重表, 最旧 update_time) 二元组。"""

    async def fake_fetch(_url: str, weight_type: str) -> pd.DataFrame:
        assert weight_type == "cs"
        return pd.DataFrame(
            [
                {"strategy": "alpha", "symbol": "BTCUSDT", "weight": 0.5, "update_time": "2026-07-02 09:05:00"},
                {"strategy": "beta", "symbol": "ETHUSDT", "weight": 0.25, "update_time": "2026-07-02 09:00:00"},
                {"strategy": "gamma", "symbol": "SOLUSDT", "weight": 0.1, "update_time": "2026-07-02 08:00:00"},
            ]
        )

    # 显式置非空数据源，使结果不依赖本机/CI 的 config.toml（否则入口护栏会先拦下）。
    monkeypatch.setattr(weights_module.settings, "quant_data_api", "http://x")
    monkeypatch.setattr(weights_module, "_fetch_latest_weights_frame", fake_fetch)

    result_df, target_update_time = asyncio.run(get_latest_weights(["alpha", "beta"], weight_type="cs"))

    # 只保留目标策略（gamma 被过滤掉），且只保留三列。
    assert sorted(result_df.columns.tolist()) == ["strategy", "symbol", "weight"]
    assert sorted(result_df["strategy"].tolist()) == ["alpha", "beta"]
    # 最旧时间来自被选中的 beta（gamma 已过滤，不参与）。
    assert target_update_time == pd.Timestamp("2026-07-02 09:00:00").isoformat()


def test_get_latest_weights_raises_without_data_source(monkeypatch: pytest.MonkeyPatch) -> None:
    """未配置数据源（quant_data_api 为空）时应抛 DataSourceUnavailableError，且取数前即拦下、不重试。"""
    monkeypatch.setattr(weights_module.settings, "quant_data_api", "")

    calls = {"n": 0}

    async def fake_fetch(_url: str, _weight_type: str) -> pd.DataFrame:
        calls["n"] += 1
        return pd.DataFrame()

    monkeypatch.setattr(weights_module, "_fetch_latest_weights_frame", fake_fetch)

    with pytest.raises(weights_module.DataSourceUnavailableError):
        asyncio.run(get_latest_weights(["alpha"], weight_type="ts"))
    # 护栏在取数前就拦下：既未触发 fetch，也未因 retry 反复调用。
    assert calls["n"] == 0
