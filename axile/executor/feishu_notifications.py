"""执行器飞书通知辅助函数."""

from __future__ import annotations

import queue
import threading
from typing import Protocol, TypedDict

import loguru

from axile.executor.algorithms.utils import clock_now
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


def send_execute_results_to_feishu(
    source: FeishuNotificationSource,
    output: UnifiedStandardOutput,
    feishu_key: str | None = None,
    template_id: str = "AAqRUQhyOM90g",
) -> None:
    """发送执行结果到飞书群机器人."""
    if not feishu_key:
        source.logger.info("未提供飞书key，跳过通知发送")
        return

    from czsc.fsa import push_card  # type: ignore[import-not-found]

    account_mark = source._get_account_mark()
    dt = clock_now().strftime("%Y-%m-%d %H:%M:%S")
    algorithm_name = str(output.inputs.algorithm.get("method", "Unknown")) if output.inputs else "Unknown"

    account_assets = output.account_assets
    total_assets = float(account_assets.total_asset)
    available_cash = float(account_assets.available_cash)
    market_value = float(account_assets.market_value)
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
    trades = [format_trade_for_feishu(source, trade, order_lookup) for trade in output.trades]

    card: ObjectDict = {
        "type": "template",
        "data": {
            "template_id": template_id,
            "template_variable": {
                "account_mark": account_mark,
                "dt": dt,
                "algorithm": algorithm_name,
                "total_assets": f"{total_assets:.2f}",
                "available_cash": f"{available_cash:.2f}",
                "market_value": f"{market_value:.2f}",
                "positions": positions,
                "trades": trades,
            },
        },
    }

    try:
        push_card(card, feishu_key)
        source.logger.info(f"飞书通知发送成功 - 账户: {account_mark}")
    except Exception as exc:
        source.logger.error(f"发送飞书通知失败: {exc}")


# ---- 有界后台通知派发器 ----
#
# 飞书通知是执行尾部的尽力而为副作用。底层 czsc.fsa.push_card 是无 timeout 的
# 第三方阻塞调用，飞书侧挂起时会永久阻塞。若沿用「每次执行裸起 daemon 线程」，
# 卡死线程会随执行次数无界增长。这里收口成「固定 worker + 有界队列 + 满则丢弃」：
# 无论 push_card 是否挂死，存活线程恒 ≤ worker 数、内存 ≤ 队列容量，主执行链路零阻塞。

_FEISHU_NOTIFY_WORKER_COUNT = 2
"""后台飞书通知 worker 线程数（同时也是 push_card 挂死时的卡死线程上界）。."""

_FEISHU_NOTIFY_QUEUE_MAXSIZE = 64
"""待发通知队列容量；超出后丢弃最新通知，避免无界堆积。."""

_FeishuNotifyTask = tuple["FeishuNotificationSource", UnifiedStandardOutput, str]

_notify_queue: queue.Queue[_FeishuNotifyTask] = queue.Queue(maxsize=_FEISHU_NOTIFY_QUEUE_MAXSIZE)
_notify_workers_started = False
_notify_workers_lock = threading.Lock()


def _feishu_notify_worker_loop() -> None:
    """后台 worker 主循环：串行消费队列并发送飞书通知，异常不退出。"""
    while True:
        source, output, feishu_key = _notify_queue.get()
        try:
            send_execute_results_to_feishu(source, output, feishu_key)
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
    尽力而为语义：由固定数量的后台 worker 串行发送。底层 ``push_card`` 是无
    超时的第三方阻塞调用，故在此收口并发与积压——队列满时**丢弃本次通知并记
    warning**，用「丢通知」换取「主执行链路不阻塞、线程与内存有界」。绝不为单次
    执行新建线程。
    """
    if not feishu_key:
        return
    _ensure_feishu_notify_workers_started()
    try:
        _notify_queue.put_nowait((source, output, feishu_key))
    except queue.Full:
        loguru.logger.warning(f"飞书通知队列已满（maxsize={_FEISHU_NOTIFY_QUEUE_MAXSIZE}），丢弃本次通知以避免无界堆积")
