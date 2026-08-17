"""AbstractExecutor 模块公开入口测试。"""


def test_abstract_executor_module_exports_abstract_executor() -> None:
    from axile.executor.abstract_executor import AbstractExecutor

    assert AbstractExecutor.__name__ == "AbstractExecutor"
