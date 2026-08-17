"""execution_query_runtime 模块公开入口测试。"""


def test_execution_query_runtime_module_exports_runtime_and_bridge() -> None:
    from axile.executor.execution_query_runtime import ExecutionQueryRuntime, ExecutionQueryRuntimeBridge

    assert ExecutionQueryRuntime.__name__ == "ExecutionQueryRuntime"
    assert ExecutionQueryRuntimeBridge.__name__ == "ExecutionQueryRuntimeBridge"
