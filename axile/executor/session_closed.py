"""执行结论里的「交易时段关闭」身份。

产品钟 / 下单守卫仍用渠道内部码（如 ``CTP.SESSION.CLOSED``、TQ ``CLOSED``）。
变成 ``AlgorithmResult`` / ``UnifiedStandardOutput`` 时映射为本模块的公共码。
读时归一把旧码和旧中文整句升成同一码；展示层只认这个码，不解析 ``error``。
"""

from __future__ import annotations

COMMON_SESSION_CLOSED = "COMMON.SESSION.CLOSED"
SESSION_CLOSED_MESSAGE = "非交易时段"

# 执行结论边界之前的渠道内部码；只在映射和读时归一使用。
LEGACY_SESSION_CLOSED_CODES = frozenset(
    {
        COMMON_SESSION_CLOSED,
        "CLOSED",
        "CTP.SESSION.CLOSED",
    }
)

# 无码的旧 BLOCKED 记录：只认整句，不用包含匹配。
LEGACY_SESSION_CLOSED_ERRORS = frozenset(
    {
        SESSION_CLOSED_MESSAGE,
        "当前不在交易时段",
        "当前不在交易时间",
    }
)


def map_session_closed(channel_code: str) -> tuple[str, str] | None:
    """渠道时段码若表示闭市，返回执行结论 ``(reason_code, message)``。"""
    if channel_code in LEGACY_SESSION_CLOSED_CODES:
        return COMMON_SESSION_CLOSED, SESSION_CLOSED_MESSAGE
    return None
