"""CTP 主力合约映射工具."""

import re
from typing import Dict, List

import czsc  # type: ignore[import-untyped]
import pandas as pd
import requests
from bs4 import BeautifulSoup

from axile.common.config import settings


@czsc.disk_cache(ttl=3600 * 12)
def get_futures_main_contracts_from_api() -> Dict[str, str]:
    """获取期货主力合约代码.

    Returns
    -------
        dict: 期货主力合约代码字典，格式如 {'rb':'rb2501', ...}
    """
    dc = czsc.DataClient(token=settings.quant_data_token, url=settings.quant_data_api)
    df = dc.get_future_main_contract_code(ttl=0, v="xy")
    df["contract"] = df["contract"].apply(lambda x: str(x)[2:])  # type: ignore[misc]
    main_contract: Dict[str, str] = df.set_index("symbol")["contract"].to_dict()  # type: ignore[assignment]
    return main_contract


@czsc.disk_cache(ttl=3600 * 12)
def get_futures_main_contracts() -> Dict[str, str]:
    """
    从九期货网站获取期货主力合约数据.

    Returns
    -------
        Dict[str, str]: 期货主力合约代码字典，格式如 {'rb':'rb2501', ...}
    """
    url = "https://www.9qihuo.com/hangqing"

    headers_dict = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }

    response = requests.get(url, headers=headers_dict, timeout=60)
    response.raise_for_status()
    response.encoding = "utf-8"

    soup = BeautifulSoup(response.text, "html.parser")

    # 查找期货数据表格
    table = soup.find("table", class_="table-striped") or soup.find("table")

    data: List[List[str]] = []
    if table is None:
        return {}
    rows = table.find_all("tr")

    # 提取表头
    headers_row = rows[0] if len(rows) > 0 else None
    column_headers: List[str]
    if headers_row is not None:
        column_headers = [th.get_text(strip=True) for th in headers_row.find_all(["th", "td"])]
    else:
        column_headers = [
            "合约代码",
            "最新价",
            "涨跌",
            "涨跌幅",
            "开盘价",
            "最高价",
            "最低价",
            "昨收价",
            "成交量",
            "持仓量",
        ]

    # 提取数据行
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) >= 3:  # 确保有足够的列
            row_data: List[str] = []
            for i, cell in enumerate(cells):
                text = cell.get_text(strip=True)
                # 第一列(合约代码)保留原始格式，其他列清理特殊字符
                if i == 0:
                    # 合约代码列保留括号等格式
                    row_data.append(text)
                else:
                    # 其他列清理数据，移除特殊字符
                    text = re.sub(r"[^\w\s\.\-\+%]", "", text)
                    row_data.append(text)

            if row_data and row_data[0]:  # 确保第一列不为空
                data.append(row_data)

    # 创建DataFrame
    max_cols = max(len(row) for row in data) if data else len(column_headers)

    # 确保所有行都有相同的列数
    for i, row in enumerate(data):
        if len(row) < max_cols:
            data[i].extend([""] * (max_cols - len(row)))

    # 确保column_headers长度匹配
    if len(column_headers) < max_cols:
        column_headers.extend([f"列{i + 1}" for i in range(len(column_headers), max_cols)])
    elif len(column_headers) > max_cols:
        column_headers = column_headers[:max_cols]

    df = pd.DataFrame(data, columns=column_headers[:max_cols])

    # 清理空行
    df = df.dropna(how="all")  # type: ignore[assignment]
    df = df[df.iloc[:, 0] != ""]  # type: ignore[index]

    contract_pattern = r"^(.+?)\(([^)]+)\)$"
    df["合约代码_英文"] = df["合约"].str.extract(contract_pattern)[1]

    main_contract: Dict[str, str] = {str(v).strip("0123456789"): str(v) for v in df["合约代码_英文"].unique()}
    return main_contract


@czsc.disk_cache(ttl=3600 * 3)
def init_futures_main_contracts() -> Dict[str, str]:
    """初始化期货主力合约代码.

    Returns
    -------
        Dict[str, str]: 期货主力合约代码字典，格式如 {'rb':'rb2501', ...}
    """
    main_contract_map: Dict[str, str]
    try:
        main_contract_map = get_futures_main_contracts_from_api()
    except Exception:
        main_contract_map = get_futures_main_contracts()
    return main_contract_map


def format_symbol(symbol: str) -> str:
    """对品种格式化."""
    main_contract_map: Dict[str, str] = init_futures_main_contracts()
    contract: str
    if symbol.endswith("9001"):
        contract = main_contract_map.get(symbol[2:-4], symbol)
    elif symbol in main_contract_map.keys():
        contract = main_contract_map[symbol]
    else:
        contract = symbol
    return contract


def format_target(target: Dict[str, float]) -> Dict[str, float]:
    """
    格式化目标持仓数据.

    Parameters
    ----------
    target : Dict[str, float]
        原始目标持仓映射，例如 ``{"SQhc9001": 0.5, "rb2510": 0.8}``。

    Returns
    -------
    Dict[str, float]
        格式化后的目标持仓映射。
    """
    _formatted: Dict[str, float] = {}
    for symbol, volume in target.items():
        contract = format_symbol(symbol)
        _formatted[contract] = volume
    return _formatted
