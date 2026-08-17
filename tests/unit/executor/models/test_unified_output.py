"""UnifiedStandardOutput 当前主路径测试。"""

from axile.common.trade_channel import TradeChannel
from axile.executor.models.execution_result import AlgorithmResult
from axile.executor.models.unified_account_assets import UnifiedAccountAssets
from axile.executor.models.unified_order import TradeRecord
from axile.executor.models.unified_output import ExecutionStatus, UnifiedStandardOutput


def _build_symbol_result_payload() -> dict[str, AlgorithmResult]:
    """构造一个最小可用的单品种结果对象。"""
    return {
        "BTCUSDT": AlgorithmResult.model_validate(
            {
                "symbol": "BTCUSDT",
                "algorithm": "TWAP",
                "status": "SUCCEEDED",
                "orders": [
                    {
                        "order_id": "1",
                        "symbol": "BTCUSDT",
                        "direction": "BUY",
                        "order_type": "LIMIT",
                        "volume": 1.0,
                        "price": 100.0,
                        "status": "待成交",
                        "filled_volume": 0.0,
                        "avg_price": 0.0,
                    }
                ],
                "trades": [
                    {
                        "trade_id": "trade-1",
                        "symbol": "BTCUSDT",
                        "order_id": "1",
                        "trade_time": "2026-03-18T00:00:01",
                        "trade_volume": 1.0,
                        "trade_price": 100.0,
                        "trade_value": 100.0,
                    }
                ],
                "target_volume": 0.25,
                "first_tick": {
                    "symbol": "BTCUSDT",
                    "last_price": 100.0,
                    "bid_price": 99.5,
                    "ask_price": 100.5,
                    "bid_volume": 1.0,
                    "ask_volume": 1.5,
                    "volume": 10.0,
                    "turnover": 1000.0,
                    "timestamp": 1,
                    "update_time": "2026-03-18T00:00:00",
                },
                "memory": {},
            }
        )
    }


def _build_account_assets_payload() -> UnifiedAccountAssets:
    """构造一个最小可用的账户资产对象。"""
    return UnifiedAccountAssets.model_validate(
        {
            "available_cash": 100.0,
            "total_asset": 150.0,
            "market_value": 50.0,
            "currency": "USDT",
            "positions": [],
        }
    )


def test_constructor_converts_nested_objects() -> None:
    """直接构造时仍应完成嵌套对象解析。"""
    output = UnifiedStandardOutput(
        account_assets=_build_account_assets_payload(),
        execution_time=1.25,
        inputs=None,
        memory={},
        status=ExecutionStatus.SUCCEEDED,
        symbol_results=_build_symbol_result_payload(),
        channel_type=TradeChannel("external"),
    )

    assert output.account_assets.currency == "USDT"
    assert len(output.orders) == 1
    assert len(output.trades) == 1
    assert output.trades[0].order_id == "1"
    assert output.orders[0].symbol == "BTCUSDT"
    assert output.first_ticks["BTCUSDT"].ask_price == 100.5
    assert output.target_volume == {"BTCUSDT": 0.25}
    assert output.execution_time == 1.25
    assert output.extra["channel_type"] == "external"


def test_constructor_parses_symbol_results() -> None:
    """symbol_results 应直接成为主体数据。"""
    output = UnifiedStandardOutput(
        account_assets=_build_account_assets_payload(),
        inputs=None,
        memory={},
        status=ExecutionStatus.PARTIAL,
        symbol_results={
            "BTCUSDT": AlgorithmResult.model_validate(
                {
                    "symbol": "BTCUSDT",
                    "algorithm": "TWAP",
                    "status": "SUCCEEDED",
                    "orders": [],
                    "target_volume": 1.0,
                    "first_tick": {
                        "symbol": "BTCUSDT",
                        "last_price": 100.0,
                        "bid_price": 99.5,
                        "ask_price": 100.5,
                        "bid_volume": 1.0,
                        "ask_volume": 1.5,
                        "volume": 10.0,
                        "turnover": 1000.0,
                        "timestamp": 1,
                        "update_time": "2026-03-18T00:00:00",
                    },
                    "memory": {"step": "done"},
                }
            ),
            "ETHUSDT": AlgorithmResult.model_validate(
                {
                    "symbol": "ETHUSDT",
                    "algorithm": "VWAP",
                    "status": "FAILED",
                    "error": "ETHUSDT failed",
                    "orders": [],
                    "target_volume": None,
                    "first_tick": None,
                    "memory": {},
                }
            ),
        },
        channel_type=TradeChannel("external"),
    )

    assert output.symbol_results["BTCUSDT"].symbol == "BTCUSDT"
    assert output.symbol_results["BTCUSDT"].algorithm == "TWAP"
    assert output.symbol_results["BTCUSDT"].status == ExecutionStatus.SUCCEEDED
    assert output.symbol_results["BTCUSDT"].target_volume == 1.0
    assert output.symbol_results["BTCUSDT"].first_tick is not None
    assert output.symbol_results["BTCUSDT"].first_tick.ask_price == 100.5
    assert output.symbol_results["ETHUSDT"].status == ExecutionStatus.FAILED
    assert output.symbol_results["ETHUSDT"].error == "ETHUSDT failed"
    assert output.status == ExecutionStatus.PARTIAL


def test_constructor_without_symbol_results_keeps_empty_mapping() -> None:
    """未提供按品种结果时保持空映射。"""
    output = UnifiedStandardOutput(
        account_assets=UnifiedAccountAssets.model_validate(
            {
                "available_cash": 0.0,
                "total_asset": 0.0,
                "market_value": 0.0,
                "positions": [],
            }
        ),
        inputs=None,
        memory={},
        status=ExecutionStatus.FAILED,
        error="boom",
        channel_type=TradeChannel("external"),
    )

    assert output.symbol_results == {}
    assert output.success is False


def test_memory_error_does_not_treat_output_as_failed() -> None:
    """memory.error 只作为诊断信息。"""
    output = UnifiedStandardOutput(
        account_assets=UnifiedAccountAssets.model_validate(
            {
                "available_cash": 0.0,
                "total_asset": 0.0,
                "market_value": 0.0,
                "positions": [],
            }
        ),
        inputs=None,
        memory={"error": "debug only"},
        status=ExecutionStatus.SUCCEEDED,
        channel_type=TradeChannel("external"),
    )

    assert output.status == ExecutionStatus.SUCCEEDED
    assert output.success is True
    assert output.error is None


def test_model_dump_keeps_symbol_results_as_main_payload() -> None:
    """顶层输出只持久化账户级字段。"""
    output = UnifiedStandardOutput(
        account_assets=_build_account_assets_payload(),
        inputs=None,
        memory={},
        status=ExecutionStatus.SUCCEEDED,
        symbol_results=_build_symbol_result_payload(),
        channel_type=TradeChannel("external"),
    )

    dumped = output.model_dump(mode="json")

    assert set(dumped) == {
        "account_assets",
        "inputs",
        "memory",
        "status",
        "symbol_results",
        "channel_type",
        "error",
        "execution_time",
        "success",
        "extra",
    }
    assert dumped["symbol_results"]["BTCUSDT"]["target_volume"] == 0.25
    assert dumped["symbol_results"]["BTCUSDT"]["first_tick"]["ask_price"] == 100.5
    assert len(output.orders) == 1
    assert len(output.trades) == 1
    assert output.target_volume == {"BTCUSDT": 0.25}
    assert output.first_ticks["BTCUSDT"].ask_price == 100.5


def test_output_aggregates_symbol_trades_separately_from_orders() -> None:
    output = UnifiedStandardOutput(
        account_assets=_build_account_assets_payload(),
        inputs=None,
        memory={},
        status=ExecutionStatus.SUCCEEDED,
        symbol_results={
            "BTCUSDT": AlgorithmResult(
                symbol="BTCUSDT",
                algorithm="TWAP",
                orders=[],
                trades=[
                    TradeRecord(
                        trade_id="trade-1",
                        symbol="BTCUSDT",
                        order_id="order-1",
                        trade_time="2026-03-25T10:00:00",
                        trade_volume=1.0,
                        trade_price=100.0,
                        trade_value=100.0,
                    )
                ],
            )
        },
        channel_type=TradeChannel("external"),
    )

    assert [trade.trade_id for trade in output.trades] == ["trade-1"]
