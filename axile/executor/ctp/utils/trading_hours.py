"""
CTP交易时间检查工具.

通过交易所、品种类型和当前时间判断是否在交易时间内.
"""

import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from logging import Logger
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

import czsc  # type: ignore[import-untyped]


def get_trading_times(
    file_cache: Path = czsc.home_path / "futures_trading_times.json",
) -> Dict[str, Dict[str, List["TradingHours"]]]:
    """获取交易时间配置."""
    import json

    import requests

    def __load() -> dict[str, dict[str, list["TradingHours"]]]:
        with open(file_cache, "r", encoding="utf-8") as f:
            xxx = json.load(f)
        return xxx

    if file_cache.exists() and time.time() - file_cache.stat().st_mtime < 3600 * 24:
        trading_times = __load()
    else:
        try:
            response = requests.get("http://dict.openctp.cn/times?types=futures")
            response.raise_for_status()
            trading_times = response.json()
            with open(file_cache, "w", encoding="utf-8") as f:
                json.dump(trading_times, f, ensure_ascii=False, indent=4)
        except Exception:
            trading_times = __load()

    data = trading_times["data"]

    # 转成 EXCHANGE_TRADING_HOURS
    exchange_hours: Dict[str, Dict[str, List[TradingHours]]] = {}

    # 处理新的数据格式：按交易所和品种分组交易时间段
    for raw_segment in data:
        segment = cast("dict[str, str]", raw_segment)
        exchange_id: str = segment["ExchangeID"]
        product_id: str = segment["ProductID"]
        time_begin: str = segment["TimeBegin"][:5]  # 截取 HH:MM 格式
        time_end: str = segment["TimeEnd"][:5]  # 截取 HH:MM 格式

        # 判断交易时段类型（简化判断：21:00之后或02:30之前为夜盘）
        start_hour = int(time_begin.split(":")[0])
        if start_hour >= 21 or start_hour <= 2:
            session_type = TradingSession.NIGHT
        else:
            session_type = TradingSession.DAY

        # 初始化交易所
        if exchange_id not in exchange_hours:
            exchange_hours[exchange_id] = {}

        # 初始化品种
        if product_id not in exchange_hours[exchange_id]:
            exchange_hours[exchange_id][product_id] = []

        # 添加交易时间段
        trading_hour = TradingHours(start_time=time_begin, end_time=time_end, session_type=session_type)
        exchange_hours[exchange_id][product_id].append(trading_hour)

    return exchange_hours


class TradingSession(Enum):
    """交易时段枚举."""

    DAY = "day"  # 日盘
    NIGHT = "night"  # 夜盘
    BOTH = "both"  # 日夜盘
    CLOSED = "closed"  # 停止交易


@dataclass
class TradingHours:
    """交易时间段."""

    start_time: str  # 格式: "HH:MM"
    end_time: str  # 格式: "HH:MM"
    session_type: TradingSession

    def is_in_session(self, current_time: datetime) -> bool:
        """检查当前时间是否在此交易时段内."""
        current_time_str = current_time.strftime("%H:%M")

        # 处理跨天的情况（如夜盘）
        if self.start_time > self.end_time:
            # 跨天的时间段，如 21:00-02:30
            return current_time_str >= self.start_time or current_time_str <= self.end_time
        else:
            # 同一天的时间段，如 09:00-15:00
            return self.start_time <= current_time_str <= self.end_time


class TradingTimeChecker:
    """交易时间检查器."""

    # 各交易所的交易时间配置
    EXCHANGE_TRADING_HOURS: Dict[str, Dict[str, List[TradingHours]]] = get_trading_times()

    def __init__(self, logger: Optional[Logger] = None) -> None:
        """初始化交易时间检查器."""
        self.logger = logger

    def extract_product_code(self, instrument_id: str) -> str:
        """从合约代码中提取品种代码.

        例如：
        au2412 -> au
        CF405 -> CF
        IF2403 -> IF
        """
        if instrument_id.endswith("9001"):
            return instrument_id[2:-4]
        # 移除数字，保留字母部分
        product_code = ""
        for char in instrument_id:
            if char.isalpha():
                product_code += char
            else:
                break
        return product_code.upper()

    def is_trading_time(
        self,
        instrument_id: str,
        exchange_id: str,
        current_time: Optional[datetime] = None,
    ) -> Tuple[bool, str]:
        """
        检查指定合约是否在交易时间内.

        Parameters
        ----------
        instrument_id : str
            合约代码，如 ``"au2412"``。
        exchange_id : str
            交易所代码，如 ``"SHFE"``。
        current_time : Optional[datetime], optional
            当前时间；未提供时使用系统时间。

        Returns
        -------
        Tuple[bool, str]
            是否在交易时间，以及对应的状态描述。
        """
        if current_time is None:
            current_time = datetime.now()

        # 提取品种代码
        product_code = self.extract_product_code(instrument_id)

        # 检查是否是周末
        if not czsc.is_trading_date():  # 周六(5)和周日(6)
            return (
                False,
                f"当前不是交易日 (当前: {current_time.strftime('%Y-%m-%d %H:%M')})",
            )

        # 检查交易所是否存在
        if exchange_id not in self.EXCHANGE_TRADING_HOURS:
            return False, f"未知交易所: {exchange_id}"

        # 检查品种是否存在
        product_hours: Dict[str, List[TradingHours]] = self.EXCHANGE_TRADING_HOURS[exchange_id]
        if product_code not in product_hours:
            # 如果品种不在配置中，尝试小写
            product_code_lower = product_code.lower()
            if product_code_lower not in product_hours:
                return (
                    False,
                    f"品种 {product_code} 不在 {exchange_id} 交易所交易时间配置中",
                )
            product_code = product_code_lower

        # 检查当前时间是否在任一交易时段内
        trading_hours_list: List[TradingHours] = product_hours[product_code]
        for trading_hour in trading_hours_list:
            if trading_hour.is_in_session(current_time):
                session_desc = "夜盘" if trading_hour.session_type == TradingSession.NIGHT else "日盘"
                return (
                    True,
                    f"在交易时间内 ({session_desc}: {trading_hour.start_time}-{trading_hour.end_time})",
                )

        # 找到最近的交易时段
        next_session = self._get_next_trading_session(product_code, exchange_id, current_time)
        if next_session:
            return False, f"非交易时间，下次交易时间: {next_session}"
        else:
            return False, f"非交易时间 (当前: {current_time.strftime('%H:%M')})"

    def _get_next_trading_session(self, product_code: str, exchange_id: str, current_time: datetime) -> Optional[str]:
        """获取下一个交易时段的开始时间."""
        try:
            trading_hours_list: List[TradingHours] = self.EXCHANGE_TRADING_HOURS[exchange_id][product_code]
            current_time_str = current_time.strftime("%H:%M")

            # 查找今天的下一个交易时段
            for trading_hour in trading_hours_list:
                if current_time_str < trading_hour.start_time:
                    session_desc = "夜盘" if trading_hour.session_type == TradingSession.NIGHT else "日盘"
                    return f"{trading_hour.start_time} ({session_desc})"

            # 如果今天没有更多时段，返回明天第一个时段
            if trading_hours_list:
                first_session: TradingHours = trading_hours_list[0]
                session_desc = "夜盘" if first_session.session_type == TradingSession.NIGHT else "日盘"
                return f"明日 {first_session.start_time} ({session_desc})"

        except KeyError:
            pass

        return None

    def filter_trading_instruments(
        self, instruments: Dict[str, Any], current_time: Optional[datetime] = None
    ) -> Tuple[Dict[str, Any], List[str]]:
        """
        过滤出当前可交易的合约.

        Parameters
        ----------
        instruments : Dict[str, Any]
            合约字典，格式为 ``{instrument_id: instrument_info}``。
        current_time : Optional[datetime], optional
            当前时间。

        Returns
        -------
        Tuple[Dict[str, Any], List[str]]
            可交易合约字典，以及被过滤掉的合约原因列表。
        """
        if current_time is None:
            current_time = datetime.now()

        tradable_instruments: Dict[str, Any] = {}
        filtered_out: List[str] = []

        for instrument_id, instrument_info in instruments.items():
            # 获取交易所信息
            exchange_id: str = ""
            if isinstance(instrument_info, dict):
                exchange_id = str(instrument_info.get("ExchangeID", ""))  # type: ignore[arg-type]
            elif hasattr(instrument_info, "ExchangeID"):
                exchange_id = str(instrument_info.ExchangeID)

            # 检查交易时间
            is_trading, reason = self.is_trading_time(str(instrument_id), exchange_id, current_time)

            if is_trading:
                tradable_instruments[instrument_id] = instrument_info
                if self.logger:
                    self.logger.debug(f"✅ {instrument_id} ({exchange_id}): {reason}")
            else:
                filtered_out.append(f"{instrument_id} ({exchange_id}): {reason}")
                if self.logger:
                    self.logger.info(f"🚫 {instrument_id} ({exchange_id}): {reason}")

        return tradable_instruments, filtered_out


# 全局实例
trading_time_checker = TradingTimeChecker()


def is_trading_time(instrument_id: str, exchange_id: str, current_time: Optional[datetime] = None) -> Tuple[bool, str]:
    """
    快捷函数：检查合约是否在交易时间内.

    Parameters
    ----------
    instrument_id : str
        合约代码。
    exchange_id : str
        交易所代码。
    current_time : Optional[datetime], optional
        当前时间。

    Returns
    -------
    Tuple[bool, str]
        是否在交易时间，以及对应状态描述。
    """
    return trading_time_checker.is_trading_time(instrument_id, exchange_id, current_time)


def filter_trading_symbols(
    target_dict: Dict[str, float],
    instruments: Dict[str, Any],
    current_time: Optional[datetime] = None,
    logger: Optional[Logger] = None,
) -> Tuple[Dict[str, float], List[str]]:
    """
    过滤出当前可交易的目标品种.

    Parameters
    ----------
    target_dict : Dict[str, float]
        目标持仓字典，格式为 ``{symbol: weight}``。
    instruments : Dict[str, Any]
        合约信息字典。
    current_time : Optional[datetime], optional
        当前时间。
    logger : Optional[Logger], optional
        日志记录器。

    Returns
    -------
    Tuple[Dict[str, float], List[str]]
        可交易目标字典，以及被过滤原因列表。
    """
    # logger 可以为 None，不需要默认值

    checker = TradingTimeChecker(logger)

    tradable_targets: Dict[str, float] = {}
    filtered_reasons: List[str] = []

    for symbol, weight in target_dict.items():
        if symbol in instruments:
            instrument_info: Any = instruments[symbol]
            exchange_id: str = str(getattr(instrument_info, "ExchangeID", ""))

            is_trading, reason = checker.is_trading_time(symbol, exchange_id, current_time)

            if is_trading:
                tradable_targets[symbol] = weight
                if logger:
                    logger.debug(f"✅ {symbol}: {reason}")
            else:
                filtered_reasons.append(f"{symbol}: {reason}")
                if logger:
                    logger.warning(f"🚫 过滤非交易时间品种 {symbol}: {reason}")
        else:
            filtered_reasons.append(f"{symbol}: 合约信息未找到")
            if logger:
                logger.warning(f"🚫 过滤未知品种 {symbol}: 合约信息未找到")

    if logger:
        logger.info(f"📊 交易时间过滤结果: {len(tradable_targets)}/{len(target_dict)} 个品种可交易")

    return tradable_targets, filtered_reasons
