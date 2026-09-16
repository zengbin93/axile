"""收尾查询保留普通渠道错误，透传生命周期控制异常。"""

from unittest.mock import Mock

import pytest

from axile.executor.algorithms.utils.final_position import read_final_position
from axile.executor.ctp.ctp_execute import CtpSessionRecoveryRequired
from axile.executor.execution_engine import ExecutionEngine
from axile.executor.termination import ExecutionTerminated


@pytest.mark.parametrize("engine", [False, True])
@pytest.mark.parametrize(
    "error",
    [
        CtpSessionRecoveryRequired("disconnected"),
        ExecutionTerminated(reason="stop", mode="graceful"),
        MemoryError("fatal"),
    ],
)
def test_final_query_propagates_control_exceptions(engine, error):
    executor = Mock()
    executor.get_account_assets.side_effect = error
    with pytest.raises(type(error)) as raised:
        if engine:
            ExecutionEngine(executor)._read_result_assets()
        else:
            read_final_position(executor, lambda assets: 0)
    assert raised.value is error
