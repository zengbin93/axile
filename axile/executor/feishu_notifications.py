"""执行器飞书通知辅助函数."""

from __future__ import annotations

import queue
import threading
from typing import Protocol, TypedDict

import loguru

from axile.common.feishu import push_feishu_card
from axile.executor.algorithms.utils import clock_now
from axile.executor.models.feishu import FeishuCardConfig
from axile.executor.models.unified_account_assets import Position
from axile.executor.models.unified_order import TradeRecord, UnifiedOrder
from axile.executor.models.unified_output import UnifiedStandardOutput

type ObjectDict = dict[str, object]


class FormattedFeishuPosition(TypedDict):
    """飞书持仓卡片使用的持仓信息."""

    symbol: str
    direction: str
    market_value: float
    volume: float
    avg_price: float


class LoggerLike(Protocol):
    """通知辅助函数使用的最小日志接口."""

    def info(self, message: object, *args: object, **kwargs: object) -> None:
        """记录普通通知日志."""

    def error(self, message: object, *args: object, **kwargs: object) -> None:
        """记录错误通知日志."""


class FeishuNotificationSource(Protocol):
    """飞书通知需要的最小执行器视图."""

    logger: LoggerLike

    def _get_account_mark(self) -> str: ...

    def _get_operation_display(self, order: UnifiedOrder) -> str: ...


def format_position_for_feishu(position: Position) -> FormattedFeishuPosition:
    """格式化持仓数据为飞书通知格式."""
    return {
        "symbol": position.symbol,
        "direction": position.direction.value if hasattr(position.direction, "value") else str(position.direction),
        "market_value": float(position.market_value),
        "volume": float(position.volume),
        "avg_price": float(position.avg_price) if position.avg_price is not None else 0,
    }


def _build_order_lookup(orders: list[UnifiedOrder]) -> dict[tuple[str, str], UnifiedOrder]:
    """按 (symbol, order_id) 建立订单查找表."""
    lookup: dict[tuple[str, str], UnifiedOrder] = {}
    for order in orders:
        lookup[(order.symbol, order.order_id)] = order
    return lookup


def format_trade_for_feishu(
    source: FeishuNotificationSource,
    trade: TradeRecord,
    order_lookup: dict[tuple[str, str], UnifiedOrder],
) -> dict[str, str]:
    """格式化单笔成交为飞书通知格式."""
    order = order_lookup.get((trade.symbol, trade.order_id))
    operate = source._get_operation_display(order) if order is not None else "-"
    return {
        "symbol": trade.symbol,
        "dt": trade.trade_time,
        "operate": operate,
        "volume": f"{trade.trade_volume:.4f}",
        "price": f"{trade.trade_price:.4f}",
        "order_id": trade.order_id,
        "trade_id": trade.trade_id,
    }


def _redact_sensitive(value: object) -> object:
    """递归移除普通策略配置中疑似凭据的字段."""
    if isinstance(value, dict):
        return {
            key: _redact_sensitive(item)
            for key, item in value.items()
            if not any(marker in key.lower() for marker in ("key", "secret", "token", "password", "credential"))
        }
    if isinstance(value, list):
        return [_redact_sensitive(item) for item in value]
    return value


def _legacy_template_variables(
    source: FeishuNotificationSource,
    output: UnifiedStandardOutput,
) -> dict[str, object]:
    """构造与既有飞书模板完全兼容的变量集合."""
    account_mark = source._get_account_mark()
    account_assets = output.account_assets
    total_assets = float(account_assets.total_asset)
    target_volume = output.target_volume
    positions: list[dict[str, str]] = []
    for position in account_assets.positions:
        formatted_pos = format_position_for_feishu(position)
        if formatted_pos["market_value"] <= 0:
            continue
        positions.append(
            {
                "symbol": formatted_pos["symbol"],
                "direction": formatted_pos["direction"],
                "market_value": f"{formatted_pos['market_value']:.2f}",
                "volume": f"{formatted_pos['volume']:.4f}",
                "target_volume": f"{target_volume.get(formatted_pos['symbol'], 0):.4f}",
                "rate": f"{formatted_pos['market_value'] / total_assets:.2%}" if total_assets > 0 else "0.00%",
            }
        )
    order_lookup = _build_order_lookup(output.orders)
    return {
        "account_mark": account_mark,
        "dt": clock_now().strftime("%Y-%m-%d %H:%M:%S"),
        "algorithm": str(output.inputs.algorithm.get("method", "Unknown")) if output.inputs else "Unknown",
        "total_assets": f"{total_assets:.2f}",
        "available_cash": f"{float(account_assets.available_cash):.2f}",
        "market_value": f"{float(account_assets.market_value):.2f}",
        "positions": positions,
        "trades": [format_trade_for_feishu(source, trade, order_lookup) for trade in output.trades],
    }


def _structured_template_variables(
    source: FeishuNotificationSource,
    output: UnifiedStandardOutput,
    legacy: dict[str, object],
) -> dict[str, object]:
    """构造版本化、跨渠道且不含连接信息的模板变量."""
    inputs = output.inputs
    assets = output.account_assets
    audit_value = inputs.extra.get("audit") if inputs else None
    audit: dict[str, object] = audit_value if isinstance(audit_value, dict) else {}
    total_asset = float(assets.total_asset)
    orders = [order.model_dump(mode="json", exclude={"extra", "update_timestamp"}) for order in output.orders]
    trades = [trade.model_dump(mode="json", exclude={"extra"}) for trade in output.trades]
    positions = [
        {
            **position.model_dump(mode="json", exclude={"extra"}),
            "target_volume": output.target_volume.get(position.symbol, 0),
            "target_weight": inputs.curr_target.get(position.symbol) if inputs else None,
            "rate": float(position.market_value) / total_asset if total_asset > 0 else 0.0,
        }
        for position in assets.positions
    ]
    symbols: list[dict[str, object]] = []
    for symbol, result in output.symbol_results.items():
        symbols.append(
            {
                "symbol": symbol,
                "algorithm": result.algorithm,
                "status": str(result.status),
                "success": result.success,
                "error": result.error,
                "target_volume": result.target_volume,
                "sizing": result.sizing.model_dump(mode="json") if result.sizing else None,
                "first_tick": result.first_tick.model_dump(mode="json", exclude={"extra"})
                if result.first_tick
                else None,
                "order_count": len(result.orders),
                "trade_count": len(result.trades),
            }
        )
    account = dict(inputs.feishu_account) if inputs else {}
    account["mark"] = source._get_account_mark()
    status = str(output.status)
    structured = {
        "schema_version": 1,
        "account": account,
        "execution": {
            "id": audit.get("execution_id"),
            "kind": audit.get("execution_kind"),
            "trigger_source": audit.get("trigger_source"),
            "notified_at": legacy["dt"],
            "execution_time": output.execution_time,
            "status": status,
            "success": output.success,
            "error": output.error,
            "channel_type": str(output.channel_type),
            "is_test": bool(audit.get("is_test", False)),
        },
        "strategy": {
            "algorithm": _redact_sensitive(inputs.algorithm) if inputs else {},
            "symbol_algorithms": _redact_sensitive(inputs.symbol_algorithms) if inputs else {},
            "trade_rules": _redact_sensitive(inputs.trade_rules) if inputs else {},
            "forbidden_symbols": list(inputs.forbidden_symbols) if inputs else [],
            "risk_symbols": list(inputs.risk_symbols) if inputs else [],
        },
        "assets": {
            "total_assets": total_asset,
            "available_cash": float(assets.available_cash),
            "market_value": float(assets.market_value),
            "currency": assets.currency,
            "update_time": assets.update_time,
            "source": assets.source,
            "cash_rate": float(assets.available_cash) / total_asset if total_asset > 0 else 0.0,
            "position_rate": float(assets.market_value) / total_asset if total_asset > 0 else 0.0,
        },
        "targets": {
            "current": dict(inputs.curr_target) if inputs else {},
            "previous": dict(inputs.last_target) if inputs else {},
            "target_volume": output.target_volume,
        },
        "positions": positions,
        "orders": orders,
        "trades": trades,
        "symbols": symbols,
        "summary": {
            "symbol_count": len(output.symbol_results),
            "position_count": len(positions),
            "order_count": len(orders),
            "filled_order_count": len(output.get_filled_orders()),
            "active_order_count": len(output.get_active_orders()),
            "trade_count": len(trades),
            "trade_value": sum(float(trade.trade_value) for trade in output.trades),
            "succeeded_symbol_count": sum(1 for result in output.symbol_results.values() if result.success),
            "failed_symbol_count": sum(1 for result in output.symbol_results.values() if not result.success),
        },
    }
    return {**legacy, **structured}


def send_execute_results_to_feishu(
    source: FeishuNotificationSource,
    output: UnifiedStandardOutput,
    feishu_key: str | None = None,
    card_config: FeishuCardConfig | None = None,
    template_id: str = "AAqRUQhyOM90g",
) -> None:
    """发送执行结果到飞书群机器人."""
    if not feishu_key:
        source.logger.info("未提供飞书key，跳过通知发送")
        return

    card = build_execute_results_feishu_card(source, output, card_config, template_id=template_id)

    try:
        push_feishu_card(card, feishu_key)
        source.logger.info(f"飞书通知发送成功 - 账户: {source._get_account_mark()}")
    except Exception as exc:
        source.logger.error(f"发送飞书通知失败: {exc}")


def build_execute_results_feishu_card(
    source: FeishuNotificationSource,
    output: UnifiedStandardOutput,
    card_config: FeishuCardConfig | None = None,
    *,
    template_id: str = "AAqRUQhyOM90g",
) -> ObjectDict:
    """按账户配置构造可直接发送的执行结果卡片."""
    legacy = _legacy_template_variables(source, output)
    if card_config and card_config.mode == "custom":
        card: ObjectDict = dict(card_config.card or {})
    else:
        custom_template = card_config.template_id if card_config and card_config.mode == "template" else None
        variables = _structured_template_variables(source, output, legacy) if custom_template else legacy
        card = {
            "type": "template",
            "data": {
                "template_id": custom_template or template_id,
                "template_variable": variables,
            },
        }
    return card


# ---- 有界后台通知派发器 ----
#
# 飞书通知是执行尾部的尽力而为副作用。HTTP 请求虽有超时，仍使用固定 worker 与
# 有界队列隔离网络延迟；队列满时丢弃新通知，保证主执行链路不阻塞且资源有界。

_FEISHU_NOTIFY_WORKER_COUNT = 2
"""后台飞书通知 worker 线程数。"""

_FEISHU_NOTIFY_QUEUE_MAXSIZE = 64
"""待发通知队列容量；超出后丢弃最新通知，避免无界堆积。"""

_FeishuNotifyTask = tuple["FeishuNotificationSource", UnifiedStandardOutput, str, FeishuCardConfig | None]

_notify_queue: queue.Queue[_FeishuNotifyTask] = queue.Queue(maxsize=_FEISHU_NOTIFY_QUEUE_MAXSIZE)
_notify_workers_started = False
_notify_workers_lock = threading.Lock()


def _feishu_notify_worker_loop() -> None:
    """后台 worker 主循环：串行消费队列并发送飞书通知，异常不退出。"""
    while True:
        source, output, feishu_key, card_config = _notify_queue.get()
        try:
            if card_config is None:
                send_execute_results_to_feishu(source, output, feishu_key)
            else:
                send_execute_results_to_feishu(source, output, feishu_key, card_config)
        except Exception as exc:  # noqa: BLE001 - 通知任务异常不得拖垮 worker
            loguru.logger.error(f"飞书通知任务执行异常: {exc}")
        finally:
            _notify_queue.task_done()


def _ensure_feishu_notify_workers_started() -> None:
    """惰性启动后台通知 worker 线程（幂等、线程安全）。"""
    global _notify_workers_started
    if _notify_workers_started:
        return
    with _notify_workers_lock:
        if _notify_workers_started:
            return
        for index in range(_FEISHU_NOTIFY_WORKER_COUNT):
            threading.Thread(
                target=_feishu_notify_worker_loop,
                name=f"feishu-notify-{index}",
                daemon=True,
            ).start()
        _notify_workers_started = True


def enqueue_execute_results_to_feishu(
    source: FeishuNotificationSource,
    output: UnifiedStandardOutput,
    feishu_key: str | None = None,
    card_config: FeishuCardConfig | None = None,
) -> None:
    """
    将执行结果飞书通知投递到有界后台队列.

    Parameters
    ----------
    source : FeishuNotificationSource
        提供日志与账户视图的执行器。
    output : UnifiedStandardOutput
        本次执行的统一输出对象。
    feishu_key : str | None, default=None
        飞书群机器人 key；为空时直接跳过。

    Returns
    -------
    None
        该函数仅投递任务，不返回结果。

    Notes
    -----
    尽力而为语义：由固定数量的后台 worker 串行发送。队列满时**丢弃本次通知并记
    warning**，用「丢通知」换取「主执行链路不阻塞、线程与内存有界」。绝不为单次
    执行新建线程。
    """
    if not feishu_key:
        return
    _ensure_feishu_notify_workers_started()
    try:
        _notify_queue.put_nowait((source, output, feishu_key, card_config))
    except queue.Full:
        loguru.logger.warning(f"飞书通知队列已满（maxsize={_FEISHU_NOTIFY_QUEUE_MAXSIZE}），丢弃本次通知以避免无界堆积")
