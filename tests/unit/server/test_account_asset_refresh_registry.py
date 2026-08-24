"""账户资产刷新与交易执行互斥测试."""

from axile.server.execution import registry


def test_asset_refresh_blocks_execution_registration() -> None:
    account_id = 91001
    try:
        assert registry.try_register_account_asset_refresh(account_id) is True
        assert registry.try_register_account_asset_refresh(account_id) is False
        assert registry.try_register_running_execution(account_id, "exec-blocked") is False
    finally:
        registry.clear_account_asset_refresh(account_id)


def test_execution_blocks_asset_refresh_registration() -> None:
    account_id = 91002
    execution_id = "exec-running"
    try:
        assert registry.try_register_running_execution(account_id, execution_id) is True
        assert registry.try_register_account_asset_refresh(account_id) is False
    finally:
        registry.clear_running_execution(account_id, execution_id)
