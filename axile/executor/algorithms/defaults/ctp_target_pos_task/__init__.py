"""默认算法：TARGET-POS-TASK（仅 CTP）."""

from axile.executor.algorithms.defaults.ctp_target_pos_task.impl import (
    CTPTargetPosTaskParams,
    ctp_target_pos_task_algorithm,
)

__all__ = ["CTPTargetPosTaskParams", "ctp_target_pos_task_algorithm"]
