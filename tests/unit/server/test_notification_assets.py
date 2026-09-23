"""飞书通知备用资产查询的边界测试。"""

import asyncio
from types import SimpleNamespace

from axile.server.execution import notification_assets


def test_load_notification_snapshot_uses_shared_query(monkeypatch) -> None:
    """仅配置飞书的账户读取页面同源快照，并保留 ID 与时间。"""
    calls: list[tuple[list[int], int]] = []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

    async def fake_query(_session, account_ids, *, limit):
        calls.append((account_ids, limit))
        return {7: [SimpleNamespace(id=42, created_at="2026-09-23 11:19", assets={"total_asset": 1000})]}

    monkeypatch.setattr(notification_assets, "SessionLocal", FakeSession)
    monkeypatch.setattr(notification_assets, "get_recent_account_asset_snapshots_for_accounts", fake_query)
    account = SimpleNamespace(id=7, feishu_key="hook")
    result = asyncio.run(notification_assets.load_notification_snapshot(account))
    assert result == {"id": 42, "created_at": "2026-09-23 11:19", "assets": {"total_asset": 1000}}
    assert calls == [([7], 1)]
    assert asyncio.run(notification_assets.load_notification_snapshot(SimpleNamespace(id=7, feishu_key=None))) is None
    assert calls == [([7], 1)]


def test_load_notification_snapshot_failure_does_not_block(monkeypatch) -> None:
    """备用查询异常时继续执行，不把读取故障升级为交易故障。"""

    class FailingSession:
        async def __aenter__(self):
            raise RuntimeError("database unavailable")

        async def __aexit__(self, *_args):
            return False

    monkeypatch.setattr(notification_assets, "SessionLocal", FailingSession)
    result = asyncio.run(notification_assets.load_notification_snapshot(SimpleNamespace(id=7, feishu_key="hook")))
    assert result is None


def test_backend_requests_keep_notification_snapshot_outside_trade_input(monkeypatch) -> None:
    """调仓和清仓只把备用快照放在独立通知上下文。"""
    from axile.server.execution import clear_positions, rebalance
    from tests.unit.server._execution_test_support import WarningLogger, build_account

    account = build_account()
    account.feishu_key = "hook"
    snapshot = {"id": 42, "created_at": "2026-09-23 11:19", "assets": {"total_asset": 1000}}

    async def fake_last_target(_account):
        return {}

    async def fake_snapshot(_account):
        return snapshot

    monkeypatch.setattr(rebalance, "_load_last_target_snapshot", fake_last_target)
    monkeypatch.setattr(rebalance, "load_notification_snapshot", fake_snapshot)
    rebalance_request = asyncio.run(
        rebalance._build_rebalance_backend_request(
            account=account,
            curr_target={"rb2610": 0.1},
            execution_id="execution-1",
            trigger_source="manual",
            logger=WarningLogger(),
            cleanup=True,
        )
    )
    assert rebalance_request.notification_snapshot == snapshot
    assert "notification_snapshot" not in rebalance_request.standard_input_dict
    assert "notification_snapshot" not in rebalance_request.audit_input

    clear_request = clear_positions._build_clear_positions_backend_request(
        account=account,
        algorithm=None,
        execution_id="execution-2",
        logger=WarningLogger(),
        notification_snapshot=snapshot,
    )
    assert clear_request.notification_snapshot == snapshot
    assert "notification_snapshot" not in clear_request.empty_kwargs
    assert "notification_snapshot" not in clear_request.audit_input
