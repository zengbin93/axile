"""为飞书通知读取与账户页面一致的最近可信资产快照。"""

from __future__ import annotations

from typing import cast

import loguru

from axile.server.core.db import SessionLocal
from axile.server.db.models import Account
from axile.server.repositories import get_recent_account_asset_snapshots_for_accounts


async def load_notification_snapshot(account: Account) -> dict[str, object] | None:
    """仅为配置了飞书通知的账户读取备用快照，查询失败不影响执行。"""
    if not account.feishu_key or account.id is None:
        return None
    try:
        async with SessionLocal() as session:
            grouped = await get_recent_account_asset_snapshots_for_accounts(session, [account.id], limit=1)
            snapshots = grouped.get(account.id, [])
            if not snapshots:
                return None
            snapshot = snapshots[0]
            return {
                "id": snapshot.id,
                "created_at": snapshot.created_at,
                "assets": cast("dict[str, object]", snapshot.assets),
            }
    except Exception as exc:
        loguru.logger.opt(exception=exc).warning("飞书通知备用资产快照读取失败: account_id={}", account.id)
        return None
