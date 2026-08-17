"""
GM (掘金) 交易执行器模块.

提供 GM 交易渠道的执行器实现，支持回调模式。

主要组件：
- GMExecutor: GM 交易执行器，继承 AbstractExecutor 并实现 UnifiedCallbackClient 接口
- GMCallbackDispatcher: 回调分发器

使用示例：
    ```python
    from axile.executor.gm import GMExecutor
    from axile.executor.models.unified_input import GMAccountConfig
    from axile.executor.models.unified_order import UnifiedOrder

    # 创建账户配置
    config = GMAccountConfig(
        account_id="your_account_id",
        token="your_token",
        terminal_path="C:/goldminer3",  # 或者 serv_addr="127.0.0.1:7001"
    )

    # 创建执行器
    executor = GMExecutor(config)

    # 注册回调
    def on_order_update(order: UnifiedOrder):
        print(f"订单更新: {order.order_id} - {order.status}")

    def on_trade_record(trade):
        print(f"成交: {trade.trade_id}")

    executor.register_order_callback(on_order_update)
    executor.register_trade_callback(on_trade_record)

    # 启动回调监控
    executor.start_callback_monitoring()

    # 下单（订单状态会通过回调推送）
    order = executor.place_order(...)

    # 停止监控
    executor.stop()
    ```
"""

from axile.executor.gm.core.callback_dispatcher import GMCallbackDispatcher
from axile.executor.gm.gm_execute import GMExecutor

__all__ = [
    "GMExecutor",
    "GMCallbackDispatcher",
]
