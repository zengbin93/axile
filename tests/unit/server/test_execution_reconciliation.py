"""``build_symbol_reconciliation`` 与账户快照溯源标的单元测试.

覆盖逐只对账的到位、欠量、清仓、做空和前仓缺失分支，以及账户级权益与来源标。
"""

import asyncio

from loguru import logger

from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.server.execution.backend import _capture_before_account_snapshot as capture_before_inline
from axile.server.execution.execution_summaries import build_symbol_reconciliation
from axile.server.execution.worker_backend.worker import (
    _capture_before_account_snapshot as capture_before_worker,
)


class _RaisingExecutor:
    """``get_account_assets`` 抛错的执行器桩，用于验证降级不中断。"""

    def get_account_assets(self) -> UnifiedAccountAssets:
        raise RuntimeError("boom")


class _AssetsExecutor:
    """返回真实账户快照的执行器桩。"""

    def get_account_assets(self) -> UnifiedAccountAssets:
        return UnifiedAccountAssets(available_cash=1.0, total_asset=1.0, market_value=0.0, positions=[])


def _long(symbol: str, volume: float) -> dict[str, object]:
    """构造一条多头持仓字典。"""
    return {"symbol": symbol, "volume": volume, "direction": "多头"}


def _short(symbol: str, volume: float) -> dict[str, object]:
    """构造一条空头持仓字典。"""
    return {"symbol": symbol, "volume": volume, "direction": "空头"}


def _order(direction: str, filled: float, avg_price: float = 0.0) -> dict[str, object]:
    """构造一条带成交量与均价的订单字典。"""
    return {"direction": direction, "filled_volume": filled, "avg_price": avg_price}


def test_reconciliation_reached_target_exactly() -> None:
    """买入到位：after≈target 且 drift≈0，reached 为真、attained≈1。"""
    result = {
        "account_assets": {"total_asset": 1000.0, "positions": [_long("ag2612", 4.366)], "source": "real"},
        "symbol_results": {
            "ag2612": {"target_volume": 4.366, "orders": [_order("BUY", 4.366)], "status": "SUCCEEDED"},
        },
    }
    before = {"total_asset": 1000.0, "positions": [], "source": "real"}

    recon = build_symbol_reconciliation(result, before)

    row = recon["symbols"][0]
    assert row["symbol"] == "ag2612"
    assert row["target"] == 4.366
    assert row["filled"] == 4.366
    assert row["before"] == 0.0
    assert row["after"] == 4.366
    assert row["moved"] == 4.366
    assert abs(row["drift"]) < 1e-9
    assert abs(row["attained_ratio"] - 1.0) < 1e-9
    assert row["reached"] is True


def test_reconciliation_undershoot_counts_preexisting_position() -> None:
    """欠量到位：已有底仓 + 部分成交，after 由前仓叠加，attained<1、reached 为假。"""
    result = {
        "account_assets": {"total_asset": 5149.0, "positions": [_long("rb2610", 0.1011)], "source": "real"},
        "symbol_results": {
            "rb2610": {"target_volume": 0.1243, "orders": [_order("BUY", 0.0675)], "status": "SUCCEEDED"},
        },
    }
    before = {"total_asset": 5149.0, "positions": [_long("rb2610", 0.0336)], "source": "real"}

    row = build_symbol_reconciliation(result, before)["symbols"][0]

    assert row["before"] == 0.0336
    assert row["after"] == 0.1011
    assert abs(row["moved"] - 0.0675) < 1e-9
    assert abs(row["filled"] - 0.0675) < 1e-9
    assert abs(row["drift"]) < 1e-9
    assert 0.80 < row["attained_ratio"] < 0.82
    assert row["reached"] is False


def test_reconciliation_fill_value_and_avg_price() -> None:
    """成交金额与均价：多单加权、卖出成交额记负号。"""
    result = {
        "account_assets": {"total_asset": 1000.0, "positions": [_long("ag2612", 4.366)], "source": "real"},
        "symbol_results": {
            "ag2612": {
                "target_volume": 4.366,
                "orders": [_order("BUY", 2.0, 1800.0), _order("BUY", 2.366, 1750.0)],
                "status": "SUCCEEDED",
            },
        },
    }
    row = build_symbol_reconciliation(result, {"total_asset": 1000.0, "positions": [], "source": "real"})["symbols"][0]

    assert abs(row["filled_value"] - (2.0 * 1800.0 + 2.366 * 1750.0)) < 1e-6
    assert abs(row["avg_price"] - row["filled_value"] / 4.366) < 1e-6

    sell_result = {
        "account_assets": {"total_asset": 1000.0, "positions": [], "source": "real"},
        "symbol_results": {
            "m2609": {"target_volume": 0, "orders": [_order("SELL", 2.34, 566.27)], "status": "SUCCEEDED"},
        },
    }
    sell_row = build_symbol_reconciliation(sell_result, None)["symbols"][0]
    assert sell_row["filled_value"] < 0
    assert abs(sell_row["avg_price"] - 566.27) < 1e-6


def test_symbol_tca_slippage_liquidity_fee_and_tree() -> None:
    """逐只 TCA：卖在卖一=被动+有利滑点、费用取自成交 extra、订单→成交树成形。"""
    result = {
        "account_assets": {"total_asset": 1000.0, "positions": [], "source": "real"},
        "symbol_results": {
            "ag2612": {
                "status": "SUCCEEDED",
                "target_volume": 0,
                "first_tick": {"bid_price": 100.0, "ask_price": 100.1, "last_price": 100.05},
                "orders": [
                    {
                        "order_id": "o1",
                        "direction": "OrderDirection.SELL",
                        "order_type": "OrderType.LIMIT",
                        "price": 100.1,
                        "avg_price": 100.1,
                        "volume": 2.0,
                        "filled_volume": 2.0,
                        "status": "已成交",
                        "extra": {"client_order_id": "c1"},
                    }
                ],
                "trades": [
                    {
                        "order_id": "o1",
                        "trade_price": 100.1,
                        "trade_volume": 2.0,
                        "trade_value": 200.2,
                        "trade_time": "2026-07-14T10:00:00",
                        "extra": {"commission": 0.5, "commission_asset": "CNY"},
                    }
                ],
            }
        },
    }
    before = {"total_asset": 1000.0, "positions": [_long("ag2612", 2.0)], "source": "real"}
    row = build_symbol_reconciliation(result, before)["symbols"][0]

    tca = row["tca"]
    assert tca["n_orders"] == 1
    assert tca["n_trades"] == 1
    assert tca["liquidity"] == "passive"
    assert 4.9 < tca["slippage_bps"] < 5.0  # 卖在卖一、高于中间价 → 有利、正号
    assert tca["fee"] == 0.5
    assert tca["fee_asset"] == "CNY"
    assert abs(tca["fill_ratio"] - 1.0) < 1e-9
    assert abs((tca["arrival_mid"] or 0) - 100.05) < 1e-9

    order = row["orders"][0]
    assert order["side"] == "sell"
    assert order["order_type"] == "LIMIT"
    assert order["client_order_id"] == "c1"
    assert len(order["trades"]) == 1
    assert order["trades"][0]["fee"] == 0.5


def test_symbol_tca_counts_zero_trades_when_order_filled_without_trade_records() -> None:
    """订单已成但无成交明细时，TCA 仍按明细笔数为 0，不把 filled_volume 假装成一笔成交."""
    result = {
        "account_assets": {"total_asset": 1000.0, "positions": [_short("TA701", 3.0)], "source": "real"},
        "symbol_results": {
            "TA701": {
                "status": "SUCCEEDED",
                "target_volume": -3.0,
                "first_tick": {"bid_price": 5517.0, "ask_price": 5518.0, "last_price": 5517.5},
                "orders": [
                    {
                        "order_id": "o1",
                        "direction": "OrderDirection.SELL",
                        "order_type": "OrderType.LIMIT",
                        "price": 5516.0,
                        "avg_price": 5516.0,
                        "volume": 1.0,
                        "filled_volume": 1.0,
                        "status": "已成交",
                    }
                ],
            }
        },
    }
    before = {"total_asset": 1000.0, "positions": [_short("TA701", 2.0)], "source": "real"}
    row = build_symbol_reconciliation(result, before)["symbols"][0]

    assert row["tca"]["n_orders"] == 1
    assert row["tca"]["n_trades"] == 0
    assert abs(row["tca"]["fill_ratio"] - 1.0) < 1e-9
    assert row["orders"][0]["filled_volume"] == 1.0
    assert row["orders"][0]["trades"] == []


def test_reconciliation_close_to_zero_target() -> None:
    """清仓：target≈0，卖出后 after≈0 视为到位。"""
    result = {
        "account_assets": {"total_asset": 1000.0, "positions": [], "source": "real"},
        "symbol_results": {
            "m2609": {"target_volume": 0, "orders": [_order("SELL", 2.34)], "status": "SUCCEEDED"},
        },
    }
    before = {"total_asset": 1200.0, "positions": [_long("m2609", 2.34)], "source": "real"}

    row = build_symbol_reconciliation(result, before)["symbols"][0]

    assert row["before"] == 2.34
    assert row["after"] == 0.0
    assert row["filled"] == -2.34
    assert row["reached"] is True


def test_reconciliation_short_position_is_negative() -> None:
    """做空：空头持仓与卖出成交都记负号。"""
    result = {
        "account_assets": {"total_asset": 1000.0, "positions": [_short("ag2612", 5.0)], "source": "real"},
        "symbol_results": {
            "ag2612": {"target_volume": -5.0, "orders": [_order("SELL", 5.0)], "status": "SUCCEEDED"},
        },
    }
    before = {"total_asset": 1000.0, "positions": [], "source": "real"}

    row = build_symbol_reconciliation(result, before)["symbols"][0]

    assert row["after"] == -5.0
    assert row["filled"] == -5.0
    assert abs(row["attained_ratio"] - 1.0) < 1e-9
    assert row["reached"] is True


def test_reconciliation_missing_before_marks_unavailable() -> None:
    """前仓不可用：before=None → 账户级 source_before 记 unavailable、逐只 before 记 0。"""
    result = {
        "account_assets": {"total_asset": 1000.0, "positions": [_long("ag2612", 1.0)], "source": "real"},
        "symbol_results": {
            "ag2612": {"target_volume": 1.0, "orders": [_order("BUY", 1.0)], "status": "SUCCEEDED"},
        },
    }

    recon = build_symbol_reconciliation(result, None)

    assert recon["account"]["source_before"] == "unavailable"
    assert recon["account"]["equity_before"] is None
    assert recon["account"]["equity_after"] == 1000.0
    assert recon["account"]["source_after"] == "real"
    assert recon["symbols"][0]["before"] == 0.0


def test_reconciliation_empty_symbol_results() -> None:
    """无逐只结果时仍返回账户块、symbols 为空。"""
    result = {"account_assets": {"total_asset": 1000.0, "positions": [], "source": "assumed"}}

    recon = build_symbol_reconciliation(result, None)

    assert recon["symbols"] == []
    assert recon["account"]["source_after"] == "assumed"


def test_reconciliation_none_target_leaves_ratio_unset() -> None:
    """NOOP 品种 target_volume 缺失：attained_ratio 与 reached 均为 None。"""
    result = {
        "account_assets": {"total_asset": 1000.0, "positions": [_long("ag2612", 1.0)], "source": "real"},
        "symbol_results": {
            "ag2612": {"target_volume": None, "orders": [], "status": "NOOP"},
        },
    }

    row = build_symbol_reconciliation(result, {"total_asset": 1000.0, "positions": [], "source": "real"})["symbols"][0]

    assert row["target"] is None
    assert row["attained_ratio"] is None
    assert row["reached"] is None


def test_account_assets_default_source_is_real() -> None:
    """``UnifiedAccountAssets`` 默认来源标为 real。"""
    assets = UnifiedAccountAssets(available_cash=1.0, total_asset=1.0, market_value=0.0, positions=[])
    assert assets.source == "real"


def test_inline_before_capture_degrades_on_error() -> None:
    """inline 路径：执行前读账户抛错时返回 ``None``（降级不中断执行主线）。"""
    result = asyncio.run(capture_before_inline(_RaisingExecutor(), logger))  # type: ignore[arg-type]
    assert result is None


def test_worker_before_capture_variants() -> None:
    """worker 路径：无该方法或抛错返回 ``None``，正常读取返回带 ``source`` 的快照。"""
    assert capture_before_worker(object()) is None
    assert capture_before_worker(_RaisingExecutor()) is None

    dump = capture_before_worker(_AssetsExecutor())
    assert dump is not None
    assert dump["source"] == "real"
    assert dump["total_asset"] == 1.0
