"""TqSdk 完整代码与 Axile 通用合约代码之间的映射."""

from __future__ import annotations

from dataclasses import dataclass

_TRADE_CLASSES = frozenset({"FUTURE", "OPTION", "COMBINE"})
_TRADE_EXCHANGES = frozenset({"CFFEX", "SHFE", "DCE", "CZCE", "INE", "GFEX"})


@dataclass(frozen=True, slots=True)
class TQInstrument:
    """一条不可变的天勤合约目录记录."""

    symbol: str
    instrument_id: str
    exchange_id: str
    ins_class: str
    expired: bool = False

    @property
    def tradable(self) -> bool:
        """返回该记录是否属于 v1 可交易的国内衍生品."""
        return not self.expired and self.ins_class in _TRADE_CLASSES and self.exchange_id in _TRADE_EXCHANGES


class TQSymbolResolver:
    """解析 CTP InstrumentID，并对未知和重名代码显式失败."""

    def __init__(self, instruments: list[TQInstrument]) -> None:
        self._by_full = {item.symbol: item for item in instruments}
        by_local: dict[str, list[TQInstrument]] = {}
        for item in instruments:
            by_local.setdefault(item.instrument_id, []).append(item)
        self._by_local = by_local

    def to_tq(self, symbol: str, *, for_trade: bool = False) -> str:
        """将通用 symbol 转换为 TqSdk 完整代码."""
        if "." in symbol:
            item = self._by_full.get(symbol)
            if for_trade and item is None:
                raise ValueError(f"品种 {symbol} 不属于当前 TqSdk 账户可交易的国内衍生品")
            if for_trade and not item.tradable:
                raise ValueError(f"品种 {item.symbol} 仅支持行情查询，不能下单")
            return symbol
        candidates = self._by_local.get(symbol, [])
        if not candidates:
            raise ValueError(f"天勤合约目录中不存在品种: {symbol}")
        live = [item for item in candidates if not item.expired]
        selected = live or candidates
        if len(selected) != 1:
            names = ", ".join(sorted(item.symbol for item in selected))
            raise ValueError(f"品种 {symbol} 对应多个天勤代码，无法自动选择: {names}")
        item = selected[0]
        if for_trade and not item.tradable:
            raise ValueError(f"品种 {item.symbol} 仅支持行情查询，不能下单")
        return item.symbol

    def to_axile(self, symbol: str) -> str:
        """将 TqSdk 完整代码转换为通用代码；非衍生品保留完整代码."""
        item = self._by_full.get(symbol)
        if item is not None and item.ins_class in _TRADE_CLASSES:
            return item.instrument_id
        return symbol

    def instrument(self, symbol: str) -> TQInstrument | None:
        """返回通用或完整代码对应的目录记录."""
        try:
            return self._by_full.get(self.to_tq(symbol))
        except ValueError:
            return None


__all__ = ["TQInstrument", "TQSymbolResolver"]
