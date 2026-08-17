"""订单回报通道健康度契约.

定义跨渠道通用的订单回报通道（例如 WebSocket 用户数据流）健康度枚举，
供执行器上报、会话代理透传，以及订单跟踪器据此调节 REST 对账频率。放在中立的
``models`` 层，避免通用组件（``ExecutionSession`` / ``OrderTracker``）反向依赖具体
渠道实现。
"""

from __future__ import annotations

from enum import Enum


class OrderChannelHealth(str, Enum):
    """
    订单回报通道健康度.

    Attributes
    ----------
    HEALTHY : str
        通道活跃，订单终态可实时送达；REST 对账退居加速角色，使用慢频。
    DEGRADED : str
        通道可疑（心跳陈旧，或下单后迟迟收不到该单回报）；REST 对账应提频接管。
    DOWN : str
        通道确认失联；正确性完全依赖 REST 对账维持。
    UNKNOWN : str
        执行器未提供健康度信息（如无 WebSocket 概念的渠道）；按默认节奏处理，
        不改变原有行为。
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"

    def needs_rest_takeover(self) -> bool:
        """
        判断该健康度是否需要 REST 对账提频接管.

        Returns
        -------
        bool
            通道可疑或失联（``DEGRADED`` / ``DOWN``）时返回 ``True``；``HEALTHY``
            与 ``UNKNOWN`` 返回 ``False``（后者保持无 WS 渠道的既有节奏）。
        """
        return self in (OrderChannelHealth.DEGRADED, OrderChannelHealth.DOWN)
