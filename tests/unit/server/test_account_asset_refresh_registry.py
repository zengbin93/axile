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


def test_target_refresh_blocks_account_operations_and_same_portfolio() -> None:
    account_id = 91003
    portfolio_id = 92003
    try:
        assert registry.try_register_target_refresh(portfolio_id, account_id) is True
        assert registry.try_register_target_refresh(portfolio_id, None) is False
        assert registry.try_register_account_asset_refresh(account_id) is False
        assert registry.try_register_running_execution(account_id, "exec-blocked-by-target") is False
    finally:
        registry.clear_target_refresh(portfolio_id, account_id)


def test_account_operations_block_target_refresh() -> None:
    asset_account_id = 91004
    execution_account_id = 91005
    try:
        assert registry.try_register_account_asset_refresh(asset_account_id) is True
        assert registry.try_register_target_refresh(92004, asset_account_id) is False
        assert registry.try_register_running_execution(execution_account_id, "exec-running-target") is True
        assert registry.try_register_target_refresh(92005, execution_account_id) is False
    finally:
        registry.clear_account_asset_refresh(asset_account_id)
        registry.clear_running_execution(execution_account_id, "exec-running-target")


def test_target_refresh_release_restores_registration() -> None:
    account_id = 91006
    portfolio_id = 92006
    assert registry.try_register_target_refresh(portfolio_id, account_id) is True
    registry.clear_target_refresh(portfolio_id, account_id)
    try:
        assert registry.try_register_target_refresh(portfolio_id, account_id) is True
    finally:
        registry.clear_target_refresh(portfolio_id, account_id)
