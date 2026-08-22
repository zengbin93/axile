"""默认算法：CTP_OPTION_EXERCISE（仅 CTP）.

负责把单品种期权目标"行权 / 放弃 / 自对冲"指令落地到 CTP，
通过 ``ReqExecOrderInsert`` / ``ReqOptionSelfCloseInsert`` 提交，并由
``CTPExecutor`` 的轻量期权记录轮询直到终态。
"""

from axile.executor.algorithms.defaults.ctp_option_exercise.impl import (
    CTPOptionExerciseParams,
    ctp_option_exercise_algorithm,
)

__all__ = ["CTPOptionExerciseParams", "ctp_option_exercise_algorithm"]
