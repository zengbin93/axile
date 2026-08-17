"""Ad-hoc data API smoke script used during local development."""

import os
from typing import cast

import pandas as pd
import pytest
import requests

from axile.common.config import settings

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_DATA_API_TESTS", "0") != "1",
    reason="需要真实数据 API 联机环境，默认跳过；设置 RUN_LIVE_DATA_API_TESTS=1 后执行",
)


def _fetch_data_api_frame() -> pd.DataFrame:
    if not settings.quant_data_token:
        pytest.skip("config.toml 未配置 quant_data_token（数据 API 联机测试所需）")

    req_params = {
        "api_name": "",
        "token": settings.quant_data_token,
        "params": {
            "v": "check",
            "ttl": 15,
            "hist": True,
            "sdt": "2025-06-01",
        },
    }

    url = "https://xapi.zbczsc.com:9106/get_strategy_latest"
    response_json = cast(dict[str, object], requests.post(url=url, json=req_params, timeout=30).json())
    if "data" not in response_json:
        raise KeyError("API response missing 'data' field")

    frame_data_raw = response_json["data"]
    if isinstance(frame_data_raw, dict):
        frame_data: dict[str, object] | list[dict[str, object]] = cast(dict[str, object], frame_data_raw)
    elif isinstance(frame_data_raw, list):
        raw_items = cast(list[object], frame_data_raw)
        if not all(isinstance(item, dict) for item in raw_items):
            raise TypeError("Expected API response data list items to be dict objects.")
        frame_data = [cast(dict[str, object], item) for item in raw_items]
    else:
        raise TypeError("Expected API response data to be a dict or list[dict].")

    return pd.DataFrame(frame_data)


def test_data_api_smoke() -> None:
    """Fetch the live data API payload and ensure it can be normalized into a DataFrame."""
    df = _fetch_data_api_frame()
    assert isinstance(df, pd.DataFrame)
