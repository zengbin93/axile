"""执行结论里「交易时段关闭」的身份。

活路径只许把 :data:`COMMON_SESSION_CLOSED` 写入 ``AlgorithmResult.reason_code``。
产品钟 / 下单守卫的渠道内部码（TQ ``CLOSED``、``CTP.SESSION.CLOSED``）不得进入执行结论。
曾经落库的旧码和旧中文整句只在 ``axile.server.execution.legacy_compat`` 读时回填。
"""

COMMON_SESSION_CLOSED = "COMMON.SESSION.CLOSED"
SESSION_CLOSED_MESSAGE = "非交易时段"
